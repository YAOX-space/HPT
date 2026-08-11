"""Behavior-cloning repair for pure-SAC HVRT experts.

Produces normal SAC checkpoints for mi12 experts. The teacher is used only to label training samples;
deployment remains a pure neural actor with no runtime rule layer.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("MKL_THREADING_LAYER", "SEQUENTIAL")

import numpy as np
import torch

from hpt_frt.common import frt_v2 as FV2
from ..frt_env import I_Q_ACT, V_SE_MAX, effective_fault_dur, load_frt_scenarios
from ..frt_env_v2 import HPTFRTEnvV2
from ..frt_metrics import CRITERIA, evaluate_frt, evaluate_scenario
from ..model_io import load_sac
from ..train_common import FROZEN_SPLIT_SEED, pick_device, sha256_file, split_scenarios


ROOT = Path(__file__).resolve().parents[4]
LAB = ROOT / "lab"
RESULTS = LAB / "results"
MODELS = ROOT / "data" / "models"
EXPANDED = LAB / "frt_scenarios_expanded.csv"
FULL320 = LAB / "frt_scenarios.csv"
HARD92 = RESULTS / "p3_expanded_baseline_only_error_analysis.csv"


@dataclass(frozen=True)
class Candidate:
    name: str
    lr: float
    epochs: int
    preserve_n: int
    preserve_stride: int
    preserve_weight: float
    teacher_weight: float
    post_weight: float
    absorb_extra: float
    recover_gain: float


def expert_filter(expert):
    if expert == "hvrt_sym":
        return lambda s: s["category"] == "HVRT" and s["fault_type"] == "swell_3ph"
    if expert == "hvrt_asym":
        return lambda s: s["category"] == "HVRT" and s["fault_type"] == "swell_1ph"
    raise ValueError(expert)


def scenarios_for(expert, path=EXPANDED):
    flt = expert_filter(expert)
    return [s for s in load_frt_scenarios(path) if flt(s)]


def scale_action(model, action):
    lo = np.array([-I_Q_ACT, -V_SE_MAX, -V_SE_MAX], np.float32)
    hi = np.array([I_Q_ACT, V_SE_MAX, V_SE_MAX], np.float32)
    return model.policy.scale_action(np.clip(np.asarray(action, np.float32), lo, hi)).astype(np.float32)


def hvrt_teacher_action(expert: str, s: dict, info: dict, spec: Candidate):
    v2p = float(info["V2p"])
    vdc = float(info["Vdc"])
    iq = float(info["iq_ref"])
    t_sample = max(0.0, float(info["t"]) - 0.002)
    clear_t = float(s["t_fault"]) + effective_fault_dur(s) * 0.20
    in_fault = float(s["t_fault"]) <= t_sample <= clear_t
    post_clear = clear_t < t_sample <= clear_t + 0.10

    if in_fault:
        if v2p > 1.095:
            iq_cmd = max(-I_Q_ACT, min(0.0, iq - spec.absorb_extra))
        else:
            iq_cmd = min(0.0, iq)
        mse_d = -min(0.12, max(0.0, spec.recover_gain * (v2p - 1.08)))
        if expert == "hvrt_asym":
            # Negative-sequence measurement bias makes wrong-sign reactive failures; absorb harder.
            iq_cmd = max(-I_Q_ACT, iq_cmd - 0.05)
        return np.array([iq_cmd, mse_d, 0.0], np.float32), spec.teacher_weight, "fault_teacher"

    if post_clear:
        if v2p < 0.97 and vdc > 0.77:
            mse_d = min(0.08, spec.recover_gain * (0.97 - v2p))
            return np.array([0.0, mse_d, 0.0], np.float32), spec.post_weight, "post_low_recover"
        if v2p > 1.03:
            mse_d = -min(0.06, spec.recover_gain * (v2p - 1.03))
            iq_cmd = -min(0.08, 0.8 * (v2p - 1.03))
            return np.array([iq_cmd, mse_d, 0.0], np.float32), spec.post_weight, "post_high_damp"
    return None, None, None


def collect_dataset(expert, base_model, scen, train_scen, spec):
    rng = random.Random(20260710)
    preserve = rng.sample(scen, min(spec.preserve_n, len(scen)))
    X, Y, W, tags = [], [], [], []

    def add(obs, action, weight, tag):
        X.append(obs.copy())
        Y.append(scale_action(base_model, action))
        W.append(float(weight))
        tags.append(tag)

    for s in preserve:
        env = HPTFRTEnvV2([s], seed=42, train_mode=False)
        obs, _ = env.reset()
        done = False
        k = 0
        while not done:
            cur, _ = base_model.predict(obs, deterministic=True)
            if k % spec.preserve_stride == 0:
                add(obs, cur, spec.preserve_weight, "preserve")
            obs, _, term, trunc, _info = env.step(cur)
            done = term or trunc
            k += 1

    for s in train_scen:
        env = HPTFRTEnvV2([s], seed=42, train_mode=False)
        obs, _ = env.reset()
        done = False
        while not done:
            cur, _ = base_model.predict(obs, deterministic=True)
            obs2, _, term, trunc, info = env.step(cur)
            teacher, weight, tag = hvrt_teacher_action(expert, s, info, spec)
            if teacher is not None:
                add(obs, teacher, weight, tag)
            obs = obs2
            done = term or trunc
    return np.asarray(X, np.float32), np.asarray(Y, np.float32), np.asarray(W, np.float32), Counter(tags)


def train_actor_bc(base_path, out_path, X, Y, W, lr, epochs, device):
    model = load_sac(base_path, device=device)
    actor = model.policy.actor
    actor.train()
    opt = torch.optim.Adam(actor.parameters(), lr=lr)
    Xt = torch.as_tensor(X, device=model.device)
    Yt = torch.as_tensor(Y, device=model.device)
    Wt = torch.as_tensor(W[:, None], device=model.device)
    bs = 512
    hist = []
    for epoch in range(epochs):
        perm = torch.randperm(len(X), device=model.device)
        total = 0.0
        for st in range(0, len(X), bs):
            idx = perm[st:st + bs]
            pred = actor(Xt[idx], deterministic=True)
            loss = ((pred - Yt[idx]) ** 2 * Wt[idx]).mean()
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(actor.parameters(), 1.0)
            opt.step()
            total += float(loss.detach().cpu())
        hist.append(total)
        if epoch in {0, 1, 2, 4, 9, epochs - 1}:
            print(f"epoch={epoch} loss={total:.6f}", flush=True)
    model.save(str(out_path))
    return model, hist


def row_eval(model, scenarios):
    rows = []
    fails = Counter()
    by_target = defaultdict(lambda: [0, 0])
    for s in scenarios:
        c = evaluate_scenario(model, HPTFRTEnvV2, s)
        if c["kind"] != "evaluated":
            fc = [c["kind"]]
            vdc_min = None
        else:
            res = c["res"]
            fc = [k for k in CRITERIA if res[k]["status"] == FV2.FAIL]
            if res.get("vdc_survive_proxy") == FV2.FAIL:
                fc.append("vdc_survive_proxy")
            vdc_min = res.get("vdc_min")
        ok = not fc
        key = (float(s["target_V_pu"]), float(s["scr"]))
        by_target[key][0] += int(ok)
        by_target[key][1] += 1
        for f in fc:
            fails[f] += 1
        rows.append({
            "scenario_id": int(s["scenario_id"]),
            "target_V_pu": float(s["target_V_pu"]),
            "scr": float(s["scr"]),
            "passed": ok,
            "failed_criteria": "+".join(fc),
            "vdc_min": vdc_min,
        })
    n_pass = sum(r["passed"] for r in rows)
    return {
        "n": len(rows),
        "pass_count": n_pass,
        "fail_count": len(rows) - n_pass,
        "pass_pct": round(100.0 * n_pass / len(rows), 3) if rows else 0.0,
        "fail_criteria": dict(fails),
        "by_target_scr": {str(k): f"{v[0]}/{v[1]}" for k, v in sorted(by_target.items())},
        "rows": rows,
    }


def summarize(model, scenarios):
    m = evaluate_frt(model, scenarios, HPTFRTEnvV2, n_eval=None)
    return {
        "n": len(scenarios),
        "partial_proxy_pct": m["partial_proxy_pct"],
        "connect": m["connect"],
        "reactive": m["reactive"],
        "recover": m["recover"],
        "vdc_survive_proxy_pct": m["vdc_survive_proxy_pct"],
        "n_decided_fail": m["n_decided_fail"],
    }


def compact(ev):
    return {k: v for k, v in ev.items() if k != "rows"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expert", choices=["hvrt_sym", "hvrt_asym"], required=True)
    ap.add_argument("--base", type=Path, default=None)
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    if args.base is None:
        args.base = MODELS / f"sac_{args.expert}_best.zip"

    run_dir = RESULTS / time.strftime(f"pure_sac_{args.expert}_bc_%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    scen = scenarios_for(args.expert, EXPANDED)
    full = scenarios_for(args.expert, FULL320)
    train_scn, val_scn = split_scenarios(scen, val_frac=0.2, seed=FROZEN_SPLIT_SEED)
    device = pick_device()
    base = load_sac(args.base, device=device)
    baseline = {
        "model": str(args.base),
        "sha256": sha256_file(args.base),
        "val": row_eval(base, val_scn),
        "full320_expert": summarize(base, full),
        "expanded_expert": summarize(base, scen),
    }
    (run_dir / "baseline.json").write_text(json.dumps(baseline, indent=2), encoding="utf-8")

    specs = [
        Candidate("bc_hvrt_recover_mild", 4e-6, 8 if args.quick else 18, 160 if args.quick else 900,
                  2, 8.0, 24.0, 36.0, 0.03, 0.9),
        Candidate("bc_hvrt_recover_strong", 5e-6, 10 if args.quick else 24, 220 if args.quick else 1200,
                  2, 10.0, 40.0, 60.0, 0.06, 1.3),
    ]
    if args.quick:
        specs = specs[:1]

    print(json.dumps({"run_dir": str(run_dir), "baseline": {
        "val": compact(baseline["val"]),
        "full320_expert": baseline["full320_expert"],
        "expanded_expert": baseline["expanded_expert"],
    }}, indent=2), flush=True)

    results = []
    for spec in specs:
        cand_dir = run_dir / spec.name
        cand_dir.mkdir(parents=True, exist_ok=True)
        print(f"=== {spec.name} ===", flush=True)
        X, Y, W, tags = collect_dataset(args.expert, base, scen, train_scn, spec)
        (cand_dir / "dataset.json").write_text(
            json.dumps({"n": int(len(X)), "tags": dict(tags), "spec": spec.__dict__}, indent=2),
            encoding="utf-8",
        )
        model_path = cand_dir / f"sac_{args.expert}_best.zip"
        model, hist = train_actor_bc(args.base, model_path, X, Y, W, spec.lr, spec.epochs, device)
        ev = {
            "model": str(model_path),
            "model_sha256": sha256_file(model_path),
            "spec": spec.__dict__,
            "train_loss": hist,
            "dataset_tags": dict(tags),
            "val": row_eval(model, val_scn),
            "full320_expert": summarize(model, full),
            "expanded_expert": summarize(model, scen),
        }
        ok = ev["val"]["pass_count"] >= baseline["val"]["pass_count"]
        ev["non_regression_ok"] = ok
        ev["score"] = ev["val"]["pass_count"] + ev["expanded_expert"]["partial_proxy_pct"]
        (cand_dir / "eval.json").write_text(json.dumps(ev, indent=2), encoding="utf-8")
        slim = {
            "model": ev["model"],
            "model_sha256": ev["model_sha256"],
            "spec": ev["spec"],
            "score": ev["score"],
            "non_regression_ok": ev["non_regression_ok"],
            "dataset_tags": ev["dataset_tags"],
            "val": compact(ev["val"]),
            "full320_expert": ev["full320_expert"],
            "expanded_expert": ev["expanded_expert"],
        }
        results.append(slim)
        (run_dir / "candidate_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(json.dumps(slim, indent=2), flush=True)

    winner = max(results, key=lambda r: (r["non_regression_ok"], r["score"])) if results else None
    (run_dir / "winner.json").write_text(json.dumps({"winner": winner}, indent=2), encoding="utf-8")
    print("WINNER", json.dumps({"winner": winner}, indent=2), flush=True)
    print(f"wrote {run_dir}", flush=True)


if __name__ == "__main__":
    main()
