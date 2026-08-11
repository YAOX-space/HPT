"""switching_aware_preserve_retrain.py -- conservative local repair for switching-visible failures.

This is the safer follow-up to ``switching_aware_retrain.py``.  The reward-only Scheme A made the
new Vdc/recovery terms visible to the ODE, but allowed the SAC actor to drift away from the promoted
policy.  This runner therefore fine-tunes only the actor with supervised targets:

* preserve the promoted residual SAC on broad expanded-2040 samples;
* use local switching-aware teachers on hard LVRT/HVRT states;
* evaluate every candidate against the promoted baseline before any promotion decision.

It never promotes automatically and remains an ODE-proxy experiment.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from hpt_frt.common import frt_v2 as FV2

from ..error_analysis_mi14 import residual_model_path
from ..frt_env import load_frt_scenarios
from ..frt_metrics import CRITERIA, evaluate_frt, evaluate_scenario
from ..model_io import load_sac
from ..residual_env import HPTFRTResidualEnvV2, RES_IQ, RES_MSE, mpc_prior3
from ..train_common import pick_device, sha256_file


ROOT = Path(__file__).resolve().parents[4]
LAB = ROOT / "lab"
RES = LAB / "results"
EXPANDED = LAB / "frt_scenarios_expanded.csv"
FULL320 = LAB / "frt_scenarios.csv"
HARD24 = RES / "hard24_sym3ph_vdc.csv"
HARD92_ANALYSIS = RES / "p3_expanded_baseline_only_error_analysis.csv"

SWITCHING_FAIL_IDS = {
    225, 226, 227, 228,
    233, 234, 235, 236, 237, 238, 239, 240,
    1441, 1456, 1500, 1873, 1875,
}


@dataclass(frozen=True)
class Candidate:
    name: str
    lr: float
    epochs: int
    preserve_n: int
    preserve_stride: int
    preserve_weight: float
    lvrt_weight: float
    hvrt_weight: float
    switch_weight: float


def hard92_ids() -> set[int]:
    if not HARD92_ANALYSIS.exists():
        return set()
    with HARD92_ANALYSIS.open(newline="", encoding="utf-8") as f:
        return {int(r["scenario_id"]) for r in csv.DictReader(f)}


def scale_action(model, action):
    lo = np.array([-RES_IQ, -RES_MSE, -RES_MSE], np.float32)
    hi = np.array([RES_IQ, RES_MSE, RES_MSE], np.float32)
    return model.policy.scale_action(np.clip(np.asarray(action, np.float32), lo, hi)).astype(np.float32)


def residual_from_total(obs, total):
    vdc = float(obs[0])
    v2p = float(obs[1])
    return np.asarray(total, np.float32) - mpc_prior3(v2p, vdc)


def lvrt_switching_teacher(obs):
    """Conservative LVRT repair: reactive support first, no positive series boost, damp high recovery."""
    vdc = float(obs[0])
    v2p = float(obs[1])
    in_fault = bool(float(obs[16]) > 0.5 or v2p < 0.9)
    if in_fault:
        # Aligned-ODE sweep (aligned_ode_hard24_fine_policy_sweep.json) shows that full droop
        # over-drains Vdc on the high-X/R strong-grid sym3ph cases.  Half droop plus a small floor
        # keeps the frt-v2 reactive criterion satisfied while preserving the DC survival margin.
        iq = max(0.0, min(0.27, 0.50 * FV2.iq_ref_droop(v2p) + 0.03))
        total = np.array([iq, 0.0, 0.0], np.float32)
    elif v2p > 1.03:
        # Simulink hard24 residuals recover high.  Add a small damping action after clearing.
        damp = min(0.08, 0.9 * (v2p - 1.03))
        series = -min(0.045, 0.7 * (v2p - 1.03))
        total = np.array([-damp, series, 0.0], np.float32)
    elif vdc < 0.82:
        total = np.array([0.0, 0.0, 0.0], np.float32)
    else:
        return None
    return residual_from_total(obs, total)


def hvrt_switching_teacher(obs):
    """HVRT repair: preserve absorption during swell, release it if post-clear voltage falls low."""
    vdc = float(obs[0])
    v2p = float(obs[1])
    in_fault = bool(float(obs[16]) > 0.5 or v2p > 1.1)
    if in_fault:
        total = np.array([FV2.iq_ref_droop(v2p), -min(0.12, 0.8 * max(0.0, v2p - 1.1)), 0.0],
                         np.float32)
    elif v2p < 0.97 and vdc > 0.79:
        total = np.array([0.0, min(0.035, 0.6 * (0.97 - v2p)), 0.0], np.float32)
    elif v2p > 1.03:
        total = np.array([0.0, -min(0.035, 0.6 * (v2p - 1.03)), 0.0], np.float32)
    else:
        return None
    return residual_from_total(obs, total)


def eval_rows(model, scenarios) -> dict:
    rows = []
    fail_criteria = Counter()
    for s in scenarios:
        c = evaluate_scenario(model, HPTFRTResidualEnvV2, s)
        if c["kind"] != "evaluated":
            fails = [c["kind"]]
            vdc_min = None
        else:
            res = c["res"]
            fails = [k for k in CRITERIA if res[k]["status"] == FV2.FAIL]
            if res.get("vdc_survive_proxy") == FV2.FAIL:
                fails.append("vdc_survive_proxy")
            vdc_min = res.get("vdc_min")
        ok = not fails
        rows.append({
            "scenario_id": int(s["scenario_id"]),
            "category": s["category"],
            "fault_type": s["fault_type"],
            "scr": float(s["scr"]),
            "target_V_pu": float(s["target_V_pu"]),
            "passed": ok,
            "failed_criteria": "+".join(fails),
            "vdc_min": vdc_min,
        })
        for f in fails:
            fail_criteria[f] += 1
    n_pass = sum(1 for r in rows if r["passed"])
    return {
        "n": len(rows),
        "pass_count": n_pass,
        "fail_count": len(rows) - n_pass,
        "pass_pct": round(100.0 * n_pass / len(rows), 3) if rows else 0.0,
        "fail_criteria": dict(fail_criteria),
        "rows": rows,
    }


def summarize_model(model, scenarios, n_eval=None) -> dict:
    m = evaluate_frt(model, scenarios, HPTFRTResidualEnvV2, n_eval=n_eval)
    return {
        "n": len(scenarios),
        "n_eval": len(scenarios) if n_eval is None else min(int(n_eval), len(scenarios)),
        "partial_proxy_pct": m["partial_proxy_pct"],
        "vdc_survive_proxy_pct": m["vdc_survive_proxy_pct"],
        "connect": m["connect"],
        "reactive": m["reactive"],
        "recover": m["recover"],
        "n_decided_fail": m["n_decided_fail"],
        "proxy_note": m["proxy_note"],
    }


def collect_samples(base_model, expanded, hard24, hard92, switch_fail, spec: Candidate):
    rng = random.Random(20260709)
    preserve_pool = list(expanded)
    preserve = rng.sample(preserve_pool, min(spec.preserve_n, len(preserve_pool)))
    target_ids = {int(s["scenario_id"]) for s in hard24}
    target_ids.update(int(s["scenario_id"]) for s in switch_fail)
    target_ids.update(int(s["scenario_id"]) for s in hard92)
    by_id = {int(s["scenario_id"]): s for s in expanded}
    targets = [by_id[sid] for sid in sorted(target_ids) if sid in by_id]

    X, Y, W, tags = [], [], [], []

    def add(obs, action, weight, tag):
        X.append(obs.copy())
        Y.append(scale_action(base_model, action))
        W.append(float(weight))
        tags.append(tag)

    # Broad preservation keeps the actor near the promoted policy.
    for s in preserve:
        env = HPTFRTResidualEnvV2([s], seed=42, train_mode=False)
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

    # Local repairs are collected along the promoted trajectory, so edits are state-local.
    for s in targets:
        env = HPTFRTResidualEnvV2([s], seed=42, train_mode=False)
        obs, _ = env.reset()
        done = False
        sid = int(s["scenario_id"])
        while not done:
            cur, _ = base_model.predict(obs, deterministic=True)
            cat = str(s["category"])
            ft = str(s["fault_type"])
            hard_lvrt = cat == "LVRT" and ft == "sym3ph" and float(s["scr"]) >= 8.0
            teacher = None
            weight = spec.preserve_weight
            tag = "target_preserve"
            if hard_lvrt:
                teacher = lvrt_switching_teacher(obs)
                weight = spec.lvrt_weight
                tag = "lvrt_switch_teacher"
            elif cat == "HVRT" and ft in ("swell_3ph", "swell_1ph"):
                teacher = hvrt_switching_teacher(obs)
                weight = spec.hvrt_weight
                tag = "hvrt_switch_teacher"
            step_action = cur
            if teacher is not None:
                if sid in SWITCHING_FAIL_IDS:
                    weight = max(weight, spec.switch_weight)
                    tag += "_simfail"
                add(obs, teacher, weight, tag)
                # Roll in with the teacher on target cases.  The previous version labelled states
                # from the promoted SAC's failing trajectory, which left the actor with little data
                # on the corrected Vdc/recovery trajectory.
                step_action = teacher
            else:
                add(obs, cur, spec.preserve_weight * 1.5, tag)
            obs, _, term, trunc, _info = env.step(step_action)
            done = term or trunc

    return np.asarray(X, np.float32), np.asarray(Y, np.float32), np.asarray(W, np.float32), Counter(tags)


def first_n(items, n):
    seq = list(items)
    return seq if n is None else seq[:min(int(n), len(seq))]


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


def compact_eval(ev: dict) -> dict:
    return {k: v for k, v in ev.items() if k != "rows"}


def score_candidate(ev: dict, baseline: dict) -> tuple[float, bool, list[str]]:
    reasons = []
    ok = True
    for key in ("hard24", "hard92"):
        if ev[key]["pass_count"] < baseline[key]["pass_count"]:
            ok = False
            reasons.append(f"{key}_regressed")
    for key in ("original320", "expanded2040"):
        if ev[key]["partial_proxy_pct"] + 1e-9 < baseline[key]["partial_proxy_pct"]:
            ok = False
            reasons.append(f"{key}_regressed")
    score = (
        ev["expanded2040"]["partial_proxy_pct"]
        + 0.4 * ev["original320"]["partial_proxy_pct"]
        + 0.8 * ev["hard92"]["pass_count"]
        + 1.2 * ev["hard24"]["pass_count"]
        + 1.5 * ev["switching_fail_ode"]["pass_count"]
    )
    return score, ok, reasons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="Run two small candidates for fast feedback.")
    args = ap.parse_args()

    run_dir = RES / time.strftime("switching_aware_preserve_%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    expanded = load_frt_scenarios(EXPANDED)
    full320 = load_frt_scenarios(FULL320)
    hard24 = load_frt_scenarios(HARD24)
    h92 = hard92_ids()
    hard92 = [s for s in expanded if int(s["scenario_id"]) in h92]
    switch_fail = [s for s in expanded if int(s["scenario_id"]) in SWITCHING_FAIL_IDS]
    eval_hard92 = first_n(hard92, 24 if args.quick else None)
    train_hard92 = first_n(hard92, 32 if args.quick else None)
    base_path = residual_model_path()
    device = pick_device()
    base_model = load_sac(base_path, device=device)
    summary_n_eval = 120 if args.quick else None
    baseline = {
        "model": str(base_path),
        "sha256": sha256_file(base_path),
        "hard24": eval_rows(base_model, hard24),
        "hard92": eval_rows(base_model, eval_hard92),
        "switching_fail_ode": eval_rows(base_model, switch_fail),
        "original320": summarize_model(base_model, full320, n_eval=summary_n_eval),
        "expanded2040": summarize_model(base_model, expanded, n_eval=summary_n_eval),
    }
    (run_dir / "baseline.json").write_text(json.dumps(baseline, indent=2), encoding="utf-8")

    specs = [
        Candidate("preserve_lvrt_hvrt_mild", 4e-6, 6 if args.quick else 14, 120 if args.quick else 1700,
                  3, 14.0, 45.0, 22.0, 70.0),
        Candidate("preserve_lvrt_strong", 3e-6, 7 if args.quick else 18, 160 if args.quick else 1900,
                  2, 18.0, 70.0, 22.0, 90.0),
    ]
    if not args.quick:
        specs.extend([
            Candidate("preserve_hvrt_strong", 3e-6, 18, 1900, 2, 18.0, 50.0, 45.0, 95.0),
            Candidate("preserve_tight", 2e-6, 22, 2040, 2, 24.0, 65.0, 38.0, 100.0),
        ])

    results = []
    print(json.dumps({
        "run_dir": str(run_dir),
        "baseline": {
            "hard24": compact_eval(baseline["hard24"]),
            "hard92": compact_eval(baseline["hard92"]),
            "switching_fail_ode": compact_eval(baseline["switching_fail_ode"]),
            "original320": baseline["original320"],
            "expanded2040": baseline["expanded2040"],
        },
    }, indent=2), flush=True)

    for spec in specs:
        cand_dir = run_dir / spec.name
        cand_dir.mkdir(parents=True, exist_ok=True)
        print(f"=== {spec.name} ===", flush=True)
        X, Y, W, tags = collect_samples(base_model, expanded, hard24, train_hard92, switch_fail, spec)
        (cand_dir / "dataset.json").write_text(
            json.dumps({"n": int(len(X)), "tags": dict(tags), "spec": spec.__dict__}, indent=2),
            encoding="utf-8",
        )
        model_path = cand_dir / f"{spec.name}.zip"
        model, hist = train_actor_bc(base_path, model_path, X, Y, W, lr=spec.lr, epochs=spec.epochs,
                                     device=device)
        ev = {
            "model": str(model_path),
            "model_sha256": sha256_file(model_path),
            "spec": spec.__dict__,
            "train_loss": hist,
            "dataset_tags": dict(tags),
            "hard24": eval_rows(model, hard24),
            "hard92": eval_rows(model, eval_hard92),
            "switching_fail_ode": eval_rows(model, switch_fail),
            "original320": summarize_model(model, full320, n_eval=summary_n_eval),
            "expanded2040": summarize_model(model, expanded, n_eval=summary_n_eval),
            "disclaimer": "ODE proxy only; Simulink switching spotcheck is required before promotion.",
        }
        ev["score"], ev["non_regression_ok"], ev["rejection_reasons"] = score_candidate(ev, baseline)
        (cand_dir / "eval.json").write_text(json.dumps(ev, indent=2), encoding="utf-8")
        slim = {k: v for k, v in ev.items()
                if k not in {"hard24", "hard92", "switching_fail_ode", "original320", "expanded2040"}}
        slim.update(
            hard24=compact_eval(ev["hard24"]),
            hard92=compact_eval(ev["hard92"]),
            switching_fail_ode=compact_eval(ev["switching_fail_ode"]),
            original320=ev["original320"],
            expanded2040=ev["expanded2040"],
        )
        print(json.dumps(slim, indent=2), flush=True)
        results.append(slim)
        (run_dir / "candidate_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    winner = max(results, key=lambda r: (r["non_regression_ok"], r["score"])) if results else None
    (run_dir / "winner.json").write_text(json.dumps({"winner": winner}, indent=2), encoding="utf-8")
    print("WINNER", json.dumps({"winner": winner}, indent=2), flush=True)
    print(f"wrote {run_dir}", flush=True)


if __name__ == "__main__":
    main()
