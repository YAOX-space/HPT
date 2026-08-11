"""hard24_fallback_experiment.py -- targeted experiments for the remaining hard-24 failures.

The current promoted residual SAC improves expanded-2040 but still fails the hard-24 subset:
scenario_id 217..240, sym3ph target=0.5, SCR=10/15.  All three main traditional baselines pass these
scenarios by staying conservative: droop iq, no series boost.  This script runs actor-level local
distillation experiments that try to teach the residual actor that fallback behavior while preserving
the current promoted policy elsewhere.

It is an ODE-proxy experiment only, not Simulink switching certification.
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
from ..frt_metrics import CRITERIA, evaluate_scenario
from ..model_io import load_sac
from ..residual_env import HPTFRTResidualEnvV2, RES_IQ, RES_MSE, mpc_prior3


ROOT = Path(__file__).resolve().parents[4]
LAB = ROOT / "lab"
RES = LAB / "results"
EXPANDED = LAB / "frt_scenarios_expanded.csv"
FULL320 = LAB / "frt_scenarios.csv"
HARD24 = RES / "hard24_sym3ph_vdc.csv"
HARD92_ANALYSIS = RES / "p3_expanded_baseline_only_error_analysis.csv"


@dataclass(frozen=True)
class Candidate:
    name: str
    hard_weight: float
    preserve_weight: float
    lr: float
    epochs: int
    reg_n: int
    reg_stride: int
    include_hvrt_keep: bool


def scale_action(model, action):
    return model.policy.scale_action(np.clip(np.asarray(action, np.float32),
                                             np.array([-RES_IQ, -RES_MSE, -RES_MSE], np.float32),
                                             np.array([RES_IQ, RES_MSE, RES_MSE], np.float32))).astype(np.float32)


def fixed_fallback_residual(obs):
    """Teacher residual action for stiff sym LVRT fallback: droop iq, no series."""
    vdc = float(obs[0])
    v2p = float(obs[1])
    if v2p < 0.9:
        iq = min(0.27, 1.5 * (0.9 - v2p))
    elif v2p > 1.1:
        iq = max(-0.27, -1.5 * (v2p - 1.1))
    else:
        iq = 0.0
    total = np.array([iq, 0.0, 0.0], np.float32)
    return total - mpc_prior3(v2p, vdc)


def collect_samples(base_model, scenarios, *, hard_ids, spec: Candidate):
    rng = random.Random(20260708)
    all_scen = list(scenarios)
    hard24 = [s for s in all_scen if int(s["scenario_id"]) in hard_ids]
    reg_pool = [s for s in all_scen if int(s["scenario_id"]) not in hard_ids]
    reg = rng.sample(reg_pool, min(spec.reg_n, len(reg_pool)))

    X, Y, W, tags = [], [], [], []

    # Hard-24: teach conservative fixed fallback for all samples while the measured trajectory is
    # in the stiff symmetric LVRT region. The actor sees only obs, so labels are generated from obs.
    for s in hard24:
        env = HPTFRTResidualEnvV2([s], seed=42, train_mode=False)
        obs, _ = env.reset()
        done = False
        while not done:
            cur, _ = base_model.predict(obs, deterministic=True)
            target = fixed_fallback_residual(obs)
            X.append(obs.copy())
            Y.append(scale_action(base_model, target))
            W.append(spec.hard_weight)
            tags.append("hard24")
            obs, _, term, trunc, _info = env.step(cur)
            done = term or trunc

    # Optional HVRT keep: keep the already promoted HVRT behavior on the 68 fixed hard-92 cases.
    if spec.include_hvrt_keep and HARD92_ANALYSIS.exists():
        hard92_ids = []
        with HARD92_ANALYSIS.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if str(r["category"]) == "HVRT":
                    hard92_ids.append(int(r["scenario_id"]))
        hard92 = [s for s in all_scen if int(s["scenario_id"]) in set(hard92_ids)]
        for s in hard92:
            env = HPTFRTResidualEnvV2([s], seed=42, train_mode=False)
            obs, _ = env.reset()
            done = False
            while not done:
                cur, _ = base_model.predict(obs, deterministic=True)
                X.append(obs.copy())
                Y.append(scale_action(base_model, cur))
                W.append(spec.preserve_weight * 2.0)
                tags.append("hvrt_keep")
                obs, _, term, trunc, _info = env.step(cur)
                done = term or trunc

    # Preserve current promoted policy over expanded samples to prevent global regression.
    for s in reg:
        env = HPTFRTResidualEnvV2([s], seed=42, train_mode=False)
        obs, _ = env.reset()
        done = False
        k = 0
        while not done:
            cur, _ = base_model.predict(obs, deterministic=True)
            if k % spec.reg_stride == 0:
                X.append(obs.copy())
                Y.append(scale_action(base_model, cur))
                W.append(spec.preserve_weight)
                tags.append("preserve")
            obs, _, term, trunc, _info = env.step(cur)
            done = term or trunc
            k += 1

    return np.asarray(X, np.float32), np.asarray(Y, np.float32), np.asarray(W, np.float32), Counter(tags)


def train_bc(base_path: Path, out_path: Path, X, Y, W, *, lr: float, epochs: int):
    model = load_sac(base_path)
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


def eval_model(model, scenarios):
    rows, fail_criteria = [], Counter()
    by_pass, by_fail, by_total = Counter(), Counter(), Counter()
    for s in scenarios:
        cls = evaluate_scenario(model, HPTFRTResidualEnvV2, s)
        if cls["kind"] != "evaluated":
            fails = [cls["kind"]]
            vdc_min = None
        else:
            res = cls["res"]
            fails = [k for k in CRITERIA if res[k]["status"] == FV2.FAIL]
            if res.get("vdc_survive_proxy") == FV2.FAIL:
                fails.append("vdc_survive_proxy")
            vdc_min = res.get("vdc_min")
        ok = not fails
        ft = s["fault_type"]
        by_total[ft] += 1
        (by_pass if ok else by_fail)[ft] += 1
        rows.append(dict(scenario_id=int(s["scenario_id"]), category=s["category"], fault_type=ft,
                         target_V_pu=float(s["target_V_pu"]), scr=float(s["scr"]),
                         duration_bin_s=float(s.get("duration_bin_s", 0.0)),
                         passed=ok, failed_criteria="+".join(fails), vdc_min=vdc_min))
        for f in fails:
            fail_criteria[f] += 1
    n_pass = sum(1 for r in rows if r["passed"])
    return dict(n=len(rows), pass_count=n_pass, fail_count=len(rows) - n_pass,
                pass_pct=round(100.0 * n_pass / len(rows), 3) if rows else 0.0,
                fail_criteria=dict(fail_criteria), by_pass_fault_type=dict(by_pass),
                by_fail_fault_type=dict(by_fail), by_total_fault_type=dict(by_total), rows=rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=6.0)
    args = ap.parse_args()
    run_dir = RES / time.strftime("hard24_fallback_%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    base_path = residual_model_path()
    expanded = load_frt_scenarios(EXPANDED)
    full320 = load_frt_scenarios(FULL320)
    hard24 = load_frt_scenarios(HARD24)
    hard92_ids = set()
    with HARD92_ANALYSIS.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            hard92_ids.add(int(r["scenario_id"]))
    hard92 = [s for s in expanded if int(s["scenario_id"]) in hard92_ids]
    hard24_ids = {int(s["scenario_id"]) for s in hard24}
    baseline_model = load_sac(base_path)
    baseline = dict(
        model=str(base_path),
        hard24=eval_model(baseline_model, hard24),
        hard92=eval_model(baseline_model, hard92),
        expanded2040_summary=json.loads((RES / "p3_expanded_ode_proxy_promoted_bc_hvrt_only.json").read_text(encoding="utf-8")),
    )
    (run_dir / "baseline.json").write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    specs = [
        Candidate("hard24_bc_w30_keep6", 30.0, 6.0, 8e-6, 16, 900, 3, True),
        Candidate("hard24_bc_w60_keep8", 60.0, 8.0, 8e-6, 18, 1100, 3, True),
        Candidate("hard24_bc_w90_keep12", 90.0, 12.0, 6e-6, 20, 1300, 3, True),
        Candidate("hard24_bc_w45_keep16", 45.0, 16.0, 5e-6, 22, 1600, 2, True),
    ]
    deadline = time.time() + args.hours * 3600
    results = []
    for spec in specs:
        if time.time() > deadline:
            break
        cand_dir = run_dir / spec.name
        cand_dir.mkdir(parents=True, exist_ok=True)
        print(f"=== {spec.name} ===", flush=True)
        base_model = load_sac(base_path)
        X, Y, W, tag_counts = collect_samples(base_model, expanded, hard_ids=hard24_ids, spec=spec)
        (cand_dir / "dataset.json").write_text(
            json.dumps(dict(n=int(len(X)), tags=dict(tag_counts), spec=spec.__dict__), indent=2),
            encoding="utf-8",
        )
        model_path = cand_dir / f"{spec.name}.zip"
        model, hist = train_bc(base_path, model_path, X, Y, W, lr=spec.lr, epochs=spec.epochs)
        ev = dict(model=str(model_path), spec=spec.__dict__, train_loss=hist,
                  hard24=eval_model(model, hard24),
                  hard92=eval_model(model, hard92),
                  expanded2040=eval_model(model, expanded),
                  original320=eval_model(model, full320))
        ev["score"] = (ev["expanded2040"]["pass_count"]
                       + 2 * ev["hard92"]["pass_count"]
                       + 4 * ev["hard24"]["pass_count"])
        (cand_dir / "eval.json").write_text(json.dumps(ev, indent=2), encoding="utf-8")
        slim = {k: v for k, v in ev.items() if k not in {"hard24", "hard92", "expanded2040", "original320"}}
        slim.update(hard24={k: v for k, v in ev["hard24"].items() if k != "rows"},
                    hard92={k: v for k, v in ev["hard92"].items() if k != "rows"},
                    expanded2040={k: v for k, v in ev["expanded2040"].items() if k != "rows"},
                    original320={k: v for k, v in ev["original320"].items() if k != "rows"})
        print(json.dumps(slim, indent=2), flush=True)
        results.append(slim)
        (run_dir / "candidate_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    if results:
        winner = max(results, key=lambda r: (r["score"], r["expanded2040"]["pass_count"],
                                             r["hard92"]["pass_count"], r["hard24"]["pass_count"]))
        (run_dir / "winner.json").write_text(json.dumps(winner, indent=2), encoding="utf-8")
        print("WINNER", json.dumps(winner, indent=2), flush=True)
    print(f"wrote {run_dir}", flush=True)


if __name__ == "__main__":
    main()
