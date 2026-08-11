"""Behavior-cloning repair for the pure-SAC sym expert.

This is for the canonical pure SAC Mode-5 path (mi==12). It does not add any deployment-time rule:
the output is still a normal SAC checkpoint whose actor directly maps the frt-v2 observation to the
3-D action [iq, mse_d, mse_q].
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
from ..frt_env import I_Q_ACT, SE_GAIN, V_SE_MAX, effective_fault_dur, load_frt_scenarios
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
HARD24 = RESULTS / "hard24_sym3ph_vdc.csv"


@dataclass(frozen=True)
class Candidate:
    name: str
    lr: float
    epochs: int
    preserve_n: int
    preserve_stride: int
    preserve_weight: float
    teacher_weight: float
    connect_margin: float
    max_boost: float
    hard_repeat: int


def sym_scenarios(path: Path):
    return [
        s for s in load_frt_scenarios(path)
        if s["category"] == "LVRT" and s["fault_type"] == "sym3ph"
    ]


def scale_action(model, action):
    lo = np.array([-I_Q_ACT, -V_SE_MAX, -V_SE_MAX], np.float32)
    hi = np.array([I_Q_ACT, V_SE_MAX, V_SE_MAX], np.float32)
    return model.policy.scale_action(np.clip(np.asarray(action, np.float32), lo, hi)).astype(np.float32)


def lvrt_floor_real(t_real: float, residual: float):
    return FV2.lvrt_lower_env(t_real, residual)


def sym_teacher_action(s: dict, info: dict, spec: Candidate):
    """Scenario-aware teacher used only to label training samples.

    It computes a minimal positive series boost when the measured V+ is below the frt-v2 LVRT floor,
    while keeping the strong-grid target=0.5 hard24 region conservative to protect Vdc.
    """
    v2p = float(info["V2p"])
    iq_ref = float(info["iq_ref"])
    vdc = float(info["Vdc"])
    t = float(info["t"])
    t_real = float(s["t_fault"]) + (t - float(s["t_fault"])) / 0.20
    floor = lvrt_floor_real(t_real - float(s["t_fault"]), float(s["target_V_pu"]))
    deficit = max(0.0, floor + spec.connect_margin - v2p)
    iq = min(I_Q_ACT, max(0.0, iq_ref + 0.01))

    strong_mid = float(s["scr"]) >= 8.0 and 0.45 <= float(s["target_V_pu"]) <= 0.55
    if strong_mid and ("zero_series" in spec.name or "onset_saturate" in spec.name):
        iq = I_Q_ACT
        boost_cap = 0.0
    elif strong_mid:
        # hard24 evidence: avoid large positive series; use only enough to clear connect margin.
        boost_cap = min(spec.max_boost, 0.035)
    else:
        boost_cap = spec.max_boost
    mse_d = min(boost_cap, max(0.0, deficit / max(1e-6, SE_GAIN)))

    if vdc < 0.80 and deficit < 0.004:
        mse_d = min(mse_d, 0.005)
    return np.array([iq, mse_d, 0.0], np.float32)


def rollout_samples(model, scenarios, spec: Candidate, *, preserve: bool):
    X, Y, W, tags = [], [], [], []
    for s in scenarios:
        env = HPTFRTEnvV2([s], seed=42, train_mode=False)
        obs, _ = env.reset()
        done = False
        k = 0
        while not done:
            cur, _ = model.predict(obs, deterministic=True)
            obs2, _rew, term, trunc, info = env.step(cur)
            t_sample = max(0.0, float(info["t"]) - 0.002)
            clear_t = float(s["t_fault"]) + effective_fault_dur(s) * 0.20
            in_fault = float(s["t_fault"]) <= t_sample <= clear_t
            strong_mid = float(s["scr"]) >= 8.0 and 0.45 <= float(s["target_V_pu"]) <= 0.55
            teacher_window = in_fault
            if "onset_saturate" in spec.name and strong_mid:
                teacher_window = (float(s["t_fault"]) - 0.020) <= t_sample <= (clear_t + 0.020)
            if preserve:
                if k % spec.preserve_stride == 0:
                    X.append(obs.copy())
                    Y.append(scale_action(model, cur))
                    W.append(spec.preserve_weight)
                    tags.append("preserve")
            elif teacher_window:
                X.append(obs.copy())
                Y.append(scale_action(model, sym_teacher_action(s, info, spec)))
                weight = spec.teacher_weight
                if float(s["scr"]) >= 8.0 and float(s["target_V_pu"]) <= 0.55:
                    weight *= 1.5
                    if "onset_saturate" in spec.name:
                        weight *= 2.0
                W.append(weight)
                tags.append("teacher")
            obs = obs2
            done = term or trunc
            k += 1
    return X, Y, W, tags


def collect_dataset(base_model, expanded_sym, train_sym, hard24, spec: Candidate):
    rng = random.Random(20260710)
    preserve = rng.sample(expanded_sym, min(spec.preserve_n, len(expanded_sym)))
    target_ids = {int(s["scenario_id"]) for s in hard24}
    hard = [s for s in train_sym if int(s["scenario_id"]) in target_ids]
    nonhard = [s for s in train_sym if int(s["scenario_id"]) not in target_ids]
    targets = list(nonhard) + list(hard) * max(1, spec.hard_repeat)

    X, Y, W, tags = [], [], [], []
    for args in (
        rollout_samples(base_model, preserve, spec, preserve=True),
        rollout_samples(base_model, targets, spec, preserve=False),
    ):
        X.extend(args[0]); Y.extend(args[1]); W.extend(args[2]); tags.extend(args[3])
    return np.asarray(X, np.float32), np.asarray(Y, np.float32), np.asarray(W, np.float32), Counter(tags)


def train_actor_bc(base_path: Path, out_path: Path, X, Y, W, *, lr: float, epochs: int, device: str):
    model = load_sac(base_path, device=device)
    actor = model.policy.actor
    actor.train()
    opt = torch.optim.Adam(actor.parameters(), lr=lr)
    Xt = torch.as_tensor(X, device=model.device)
    Yt = torch.as_tensor(Y, device=model.device)
    Wt = torch.as_tensor(W[:, None], device=model.device)
    n = len(X)
    bs = 512
    hist = []
    for epoch in range(epochs):
        perm = torch.randperm(n, device=model.device)
        total = 0.0
        for st in range(0, n, bs):
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
        tgt = float(s["target_V_pu"])
        by_target[tgt][0] += int(ok)
        by_target[tgt][1] += 1
        for f in fc:
            fails[f] += 1
        rows.append({
            "scenario_id": int(s["scenario_id"]),
            "target_V_pu": tgt,
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
        "by_target": {str(k): f"{v[0]}/{v[1]}" for k, v in sorted(by_target.items())},
        "rows": rows,
    }


def summarize(model, scenarios):
    m = evaluate_frt(model, scenarios, HPTFRTEnvV2, n_eval=None)
    return {
        "n": len(scenarios),
        "partial_proxy_pct": m["partial_proxy_pct"],
        "connect": m["connect"],
        "reactive": m["reactive"],
        "vdc_survive_proxy_pct": m["vdc_survive_proxy_pct"],
        "n_decided_fail": m["n_decided_fail"],
    }


def compact(ev):
    return {k: v for k, v in ev.items() if k != "rows"}


def score(ev, baseline):
    reasons = []
    ok = True
    if ev["val"]["pass_count"] < baseline["val"]["pass_count"]:
        ok = False
        reasons.append("val_regressed")
    if ev["hard24"]["pass_count"] < baseline["hard24"]["pass_count"]:
        ok = False
        reasons.append("hard24_regressed")
    score_value = ev["val"]["pass_count"] + 2.0 * ev["hard24"]["pass_count"] + ev["expanded_sym"]["partial_proxy_pct"]
    return score_value, ok, reasons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=Path, default=MODELS / "sac_sym_best.zip")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--only", default="", help="Run only the named candidate.")
    args = ap.parse_args()

    run_dir = RESULTS / time.strftime("pure_sac_sym_bc_%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    expanded_sym = sym_scenarios(EXPANDED)
    full320_sym = sym_scenarios(FULL320)
    train_sym, val_sym = split_scenarios(expanded_sym, val_frac=0.2, seed=FROZEN_SPLIT_SEED)
    hard24 = load_frt_scenarios(HARD24) if HARD24.exists() else []
    device = pick_device()
    base = load_sac(args.base, device=device)
    baseline = {
        "model": str(args.base),
        "sha256": sha256_file(args.base),
        "val": row_eval(base, val_sym),
        "hard24": row_eval(base, hard24),
        "full320_sym": summarize(base, full320_sym),
        "expanded_sym": summarize(base, expanded_sym),
    }
    (run_dir / "baseline.json").write_text(json.dumps(baseline, indent=2), encoding="utf-8")

    specs = [
        Candidate("bc_connect_mild", 4e-6, 8 if args.quick else 18, 160 if args.quick else 1200,
                  3, 6.0, 24.0, 0.012, 0.08, 2),
        Candidate("bc_connect_strong", 5e-6, 10 if args.quick else 24, 220 if args.quick else 1600,
                  2, 8.0, 36.0, 0.018, 0.12, 3),
        Candidate("bc_hard24_balanced", 3e-6, 10 if args.quick else 26, 260 if args.quick else 1900,
                  2, 10.0, 48.0, 0.010, 0.045, 5),
        Candidate("bc_hard24_zero_series", 4e-6, 10 if args.quick else 26, 240 if args.quick else 1800,
                  2, 10.0, 70.0, 0.006, 0.0, 8),
        Candidate("bc_hard24_onset_saturate", 6e-6, 12 if args.quick else 40, 180 if args.quick else 1200,
                  2, 4.0, 120.0, 0.004, 0.0, 16),
    ]
    if args.quick:
        specs = specs[:1]
    if args.only:
        specs = [s for s in specs if s.name == args.only]
        if not specs:
            raise SystemExit(f"unknown candidate {args.only!r}")

    print(json.dumps({"run_dir": str(run_dir), "baseline": {
        "val": compact(baseline["val"]),
        "hard24": compact(baseline["hard24"]),
        "full320_sym": baseline["full320_sym"],
        "expanded_sym": baseline["expanded_sym"],
    }}, indent=2), flush=True)

    results = []
    for spec in specs:
        cand_dir = run_dir / spec.name
        cand_dir.mkdir(parents=True, exist_ok=True)
        print(f"=== {spec.name} ===", flush=True)
        X, Y, W, tags = collect_dataset(base, expanded_sym, train_sym, hard24, spec)
        (cand_dir / "dataset.json").write_text(
            json.dumps({"n": int(len(X)), "tags": dict(tags), "spec": spec.__dict__}, indent=2),
            encoding="utf-8",
        )
        model_path = cand_dir / "sac_sym_best.zip"
        model, hist = train_actor_bc(args.base, model_path, X, Y, W, lr=spec.lr, epochs=spec.epochs,
                                     device=device)
        ev = {
            "model": str(model_path),
            "model_sha256": sha256_file(model_path),
            "spec": spec.__dict__,
            "train_loss": hist,
            "dataset_tags": dict(tags),
            "val": row_eval(model, val_sym),
            "hard24": row_eval(model, hard24),
            "full320_sym": summarize(model, full320_sym),
            "expanded_sym": summarize(model, expanded_sym),
        }
        ev["score"], ev["non_regression_ok"], ev["rejection_reasons"] = score(ev, baseline)
        (cand_dir / "eval.json").write_text(json.dumps(ev, indent=2), encoding="utf-8")
        slim = {
            "model": ev["model"],
            "model_sha256": ev["model_sha256"],
            "spec": ev["spec"],
            "score": ev["score"],
            "non_regression_ok": ev["non_regression_ok"],
            "rejection_reasons": ev["rejection_reasons"],
            "dataset_tags": ev["dataset_tags"],
            "val": compact(ev["val"]),
            "hard24": compact(ev["hard24"]),
            "full320_sym": ev["full320_sym"],
            "expanded_sym": ev["expanded_sym"],
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
