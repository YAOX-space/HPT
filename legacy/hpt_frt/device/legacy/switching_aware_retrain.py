"""switching_aware_retrain.py -- Scheme A for ODE-blind Simulink failures.

This experiment fine-tunes the current residual SAC with an ODE reward that includes
switching-informed penalties for:

* DC-link survival margin near Vdc=0.75
* LVRT post-clear recovery over-voltage
* HVRT post-clear recovery under/over-voltage

It does not promote the result automatically and does not mutate certified Simulink artifacts.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from pathlib import Path

from stable_baselines3.common.vec_env import DummyVecEnv

from ..error_analysis_mi14 import residual_model_path
from ..frt_env import load_frt_scenarios
from ..frt_metrics import evaluate_frt, evaluate_scenario
from ..model_io import load_sac
from ..residual_env import HPTFRTResidualEnvV2, HPTFRTResidualSwitchingAwareEnvV2
from ..train_common import env_seeds, pick_device, sha256_file
from hpt_frt.common import frt_v2 as FV2


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


def hard92_ids() -> set[int]:
    if not HARD92_ANALYSIS.exists():
        return set()
    with HARD92_ANALYSIS.open(newline="", encoding="utf-8") as f:
        return {int(r["scenario_id"]) for r in csv.DictReader(f)}


def weighted_scenarios(expanded: list[dict], hard_weight: int, recover_weight: int) -> tuple[list[dict], dict]:
    hard92 = hard92_ids()
    out = list(expanded)
    by_id = {int(s["scenario_id"]): s for s in expanded}
    tags = Counter(base=len(expanded))
    for sid in sorted(hard92):
        if sid in by_id:
            out.extend([by_id[sid]] * max(0, hard_weight - 1))
            tags["hard92_extra"] += max(0, hard_weight - 1)
    for sid in sorted(SWITCHING_FAIL_IDS):
        if sid in by_id:
            out.extend([by_id[sid]] * max(0, recover_weight - hard_weight))
            tags["switching_recover_extra"] += max(0, recover_weight - hard_weight)
    return out, dict(tags)


def summarize_model(model, scenarios, env_cls=HPTFRTResidualEnvV2) -> dict:
    m = evaluate_frt(model, scenarios, env_cls, n_eval=None)
    return {
        "n": len(scenarios),
        "partial_proxy_pct": m["partial_proxy_pct"],
        "vdc_survive_proxy_pct": m["vdc_survive_proxy_pct"],
        "connect": m["connect"],
        "reactive": m["reactive"],
        "recover": m["recover"],
        "n_decided_fail": m["n_decided_fail"],
        "proxy_note": m["proxy_note"],
    }


def row_eval(model, scenarios, env_cls=HPTFRTResidualEnvV2) -> dict:
    rows = []
    fail_criteria = Counter()
    for s in scenarios:
        c = evaluate_scenario(model, env_cls, s)
        if c["kind"] != "evaluated":
            fails = [c["kind"]]
            vdc_min = None
        else:
            res = c["res"]
            fails = [k for k in ("connect", "reactive", "recover") if res[k]["status"] == FV2.FAIL]
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=60_000)
    ap.add_argument("--n-envs", type=int, default=4)
    ap.add_argument("--seed", type=int, default=20260709)
    ap.add_argument("--hard-weight", type=int, default=12)
    ap.add_argument("--recover-weight", type=int, default=40)
    ap.add_argument("--lr", type=float, default=3e-6)
    args = ap.parse_args()

    run_dir = RES / time.strftime("switching_aware_A_%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    expanded = load_frt_scenarios(EXPANDED)
    full320 = load_frt_scenarios(FULL320)
    hard24 = load_frt_scenarios(HARD24)
    hard92 = [s for s in expanded if int(s["scenario_id"]) in hard92_ids()]
    switch_fail = [s for s in expanded if int(s["scenario_id"]) in SWITCHING_FAIL_IDS]
    train_scen, tags = weighted_scenarios(expanded, args.hard_weight, args.recover_weight)

    base_path = residual_model_path()
    device = pick_device()
    model = load_sac(base_path, device=device)
    baseline = {
        "model": str(base_path),
        "sha256": sha256_file(base_path),
        "hard24": row_eval(model, hard24),
        "hard92": row_eval(model, hard92),
        "switching_fail_ode": row_eval(model, switch_fail),
        "original320": summarize_model(model, full320),
    }
    (run_dir / "baseline.json").write_text(json.dumps(baseline, indent=2), encoding="utf-8")

    vec = DummyVecEnv([
        (lambda s=s: HPTFRTResidualSwitchingAwareEnvV2(train_scen, seed=s))
        for s in env_seeds(args.seed, args.n_envs)
    ])
    model = load_sac(base_path, device=device, env=vec)
    model.learning_rate = args.lr
    model.lr_schedule = lambda _: args.lr
    for group in model.actor.optimizer.param_groups:
        group["lr"] = args.lr
    for group in model.critic.optimizer.param_groups:
        group["lr"] = args.lr
    if model.ent_coef_optimizer is not None:
        for group in model.ent_coef_optimizer.param_groups:
            group["lr"] = args.lr
    print(f"=== switching-aware Scheme A ===", flush=True)
    print(f"base={base_path}", flush=True)
    print(f"train_scen={len(train_scen)} tags={tags} steps={args.steps}", flush=True)
    t0 = time.time()
    model.learn(total_timesteps=args.steps, reset_num_timesteps=False)

    out_model = run_dir / "sac_residual_switching_aware_A.zip"
    model.save(str(out_model))
    result = {
        "metrics_version": "frt-v2",
        "layer": "ODE training with switching-informed reward",
        "scheme": "A",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_s": round(time.time() - t0, 2),
        "source_model": str(base_path),
        "source_sha256": sha256_file(base_path),
        "model": str(out_model),
        "model_sha256": sha256_file(out_model),
        "args": vars(args),
        "train_tags": tags,
        "hard24": row_eval(model, hard24),
        "hard92": row_eval(model, hard92),
        "switching_fail_ode": row_eval(model, switch_fail),
        "original320": summarize_model(model, full320),
        "expanded2040": summarize_model(model, expanded),
        "disclaimer": "ODE proxy only; Simulink switching spotcheck must be rerun before promotion.",
    }
    (run_dir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items()
                      if k in {"elapsed_s", "model", "hard24", "hard92", "switching_fail_ode",
                               "original320", "expanded2040"}}, indent=2), flush=True)
    print(f"wrote {run_dir}", flush=True)


if __name__ == "__main__":
    main()
