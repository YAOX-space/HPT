"""Trace diagnostics for the remaining weak-HVRT target failures."""
from __future__ import annotations

import argparse
import csv
import json
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

from ..error_analysis_mi14 import residual_model_path
from .focused_projection_search import base_fallback_spec
from ..frt_env import TSCALE, effective_fault_dur, load_frt_scenarios
from ..frt_metrics import evaluate_scenario
from ..model_io import load_sac
from .overnight_constrained_projection import EXPANDED, ProjectionPolicy
from ..residual_env import HPTFRTResidualEnvV2, mpc_prior3
from ..train_common import pick_device


ROOT = Path(__file__).resolve().parents[4]
RES = ROOT / "lab" / "results"
TARGET_IDS = {1441, 1443, 1444}


def rollout(model, scenario):
    env = HPTFRTResidualEnvV2([scenario], seed=42, train_mode=False)
    obs, _ = env.reset()
    rows = []
    done = False
    while not done:
        action, _ = model.predict(obs, deterministic=True)
        prior = mpc_prior3(float(obs[1]), float(obs[0]))
        total_cmd = prior + np.asarray(action, np.float32).reshape(3)
        obs, reward, term, trunc, info = env.step(action)
        rows.append({
            "t": float(info["t"]),
            "t_eval": float(scenario["t_fault"]) + (float(info["t"]) - float(scenario["t_fault"])) / TSCALE,
            "V2p": float(info["V2p"]),
            "V2n": float(info["V2n"]),
            "Vdc": float(info["Vdc"]),
            "iq": float(info["iq"]),
            "iq_ref": float(info["iq_ref"]),
            "mse_d": float(info["mse_d"]),
            "mse_q": float(info["mse_q"]),
            "res_iq": float(np.asarray(action).reshape(3)[0]),
            "res_md": float(np.asarray(action).reshape(3)[1]),
            "prior_iq": float(prior[0]),
            "prior_md": float(prior[1]),
            "total_iq_preclip": float(total_cmd[0]),
            "total_md_preclip": float(total_cmd[1]),
            "Vdc_eq": float(info["Vdc_eq"]),
            "Vg_p": float(info["Vg_p"]),
            "reward": float(reward),
        })
        done = term or trunc
    return rows


def summarize(rows, scenario, spec):
    t_fault = float(scenario["t_fault"])
    dur = effective_fault_dur(scenario)
    t_clear = t_fault + dur
    final = [r for r in rows if r["t_eval"] >= rows[-1]["t_eval"] - 0.12]
    post = [r for r in rows if r["t_eval"] >= t_clear]
    gate = [
        r for r in rows
        if r["V2n"] <= spec.fallback_v2n_max
        and spec.fallback_v_min <= r["V2p"] < spec.fallback_v_max
        and spec.fallback_vdc_min <= r["Vdc"] <= spec.fallback_vdc_max
    ]
    return {
        "sid": int(scenario["scenario_id"]),
        "target": float(scenario["target_V_pu"]),
        "dur": dur,
        "n": len(rows),
        "gate_count": len(gate),
        "gate_t_eval_first": gate[0]["t_eval"] if gate else None,
        "gate_t_eval_last": gate[-1]["t_eval"] if gate else None,
        "V2p_final_min": min(r["V2p"] for r in final),
        "V2p_final_mean": float(np.mean([r["V2p"] for r in final])),
        "V2p_post_min": min(r["V2p"] for r in post) if post else None,
        "V2p_post_max": max(r["V2p"] for r in post) if post else None,
        "Vdc_min": min(r["Vdc"] for r in rows),
        "Vdc_final_min": min(r["Vdc"] for r in final),
        "mse_d_final_mean": float(np.mean([r["mse_d"] for r in final])),
        "iq_final_mean": float(np.mean([r["iq"] for r in final])),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-tag", default=time.strftime("%Y%m%d_%H%M%S"))
    args = ap.parse_args()

    expanded = load_frt_scenarios(EXPANDED)
    targets = [s for s in expanded if int(s["scenario_id"]) in TARGET_IDS]
    spec = base_fallback_spec("diagnose_lvrt_fallback_proj_0")
    base = load_sac(residual_model_path(), device=pick_device())
    model = ProjectionPolicy(base, spec)

    out_dir = RES / f"target_projection_diagnosis_{args.out_tag}"
    out_dir.mkdir(parents=True, exist_ok=True)
    summaries = []
    for scenario in targets:
        sid = int(scenario["scenario_id"])
        rows = rollout(model, scenario)
        summary = summarize(rows, scenario, spec)
        ev = evaluate_scenario(model, HPTFRTResidualEnvV2, scenario)
        summary["eval"] = ev
        summaries.append(summary)
        with (out_dir / f"trace_{sid}.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(json.dumps(summary, indent=2), flush=True)

    payload = {"spec": asdict(spec), "summaries": summaries}
    (out_dir / "summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {out_dir}", flush=True)


if __name__ == "__main__":
    main()
