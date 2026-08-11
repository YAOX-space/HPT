"""Evaluate an arbitrary pure-SAC four-expert mi12 checkpoint combination in the ODE proxy."""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from hpt_frt.common import frt_v2 as FV2
from .frt_env import load_frt_scenarios
from .frt_env_v2 import HPTFRTEnvV2
from .frt_metrics import CRITERIA, evaluate_frt, evaluate_scenario
from .model_io import load_sac


ROOT = Path(__file__).resolve().parents[3]
LAB = ROOT / "lab"
RESULTS = LAB / "results"
MODELS = ROOT / "data" / "models"
EXPANDED = LAB / "frt_scenarios_expanded.csv"
FULL320 = LAB / "frt_scenarios.csv"
HARD24 = RESULTS / "hard24_sym3ph_vdc.csv"
HARD92 = RESULTS / "p3_expanded_baseline_only_error_analysis.csv"


class ExpertRouter:
    def __init__(self, models):
        self.models = models

    def _name(self, obs):
        v2p = float(obs[1])
        v2n = float(obs[2])
        probs = obs[9:15]
        if v2p >= 1.060 or float(probs[5]) > 0.5:
            return "hvrt_asym" if v2n > 0.05 else "hvrt_sym"
        if v2p < 0.90 or v2n > 0.05:
            return "asym" if v2n > 0.05 else "sym"
        return "sym"

    def predict(self, obs, deterministic=True):
        return self.models[self._name(obs)].predict(obs, deterministic=deterministic)


def read_hard92_ids():
    if not HARD92.exists():
        return set()
    import csv
    with HARD92.open(newline="", encoding="utf-8") as f:
        return {int(r["scenario_id"]) for r in csv.DictReader(f)}


def row_eval(model, scenarios):
    rows = []
    fail_criteria = Counter()
    for s in scenarios:
        c = evaluate_scenario(model, HPTFRTEnvV2, s)
        if c["kind"] != "evaluated":
            fails = [c["kind"]]
            vdc_min = None
        else:
            res = c["res"]
            fails = [k for k in CRITERIA if res[k]["status"] == FV2.FAIL]
            if res.get("vdc_survive_proxy") == FV2.FAIL:
                fails.append("vdc_survive_proxy")
            vdc_min = res.get("vdc_min")
        for f in fails:
            fail_criteria[f] += 1
        rows.append({
            "scenario_id": int(s["scenario_id"]),
            "category": s["category"],
            "fault_type": s["fault_type"],
            "target_V_pu": float(s["target_V_pu"]),
            "scr": float(s["scr"]),
            "passed": not fails,
            "failed_criteria": "+".join(fails),
            "vdc_min": vdc_min,
        })
    n_pass = sum(r["passed"] for r in rows)
    return {
        "n": len(rows),
        "pass_count": n_pass,
        "fail_count": len(rows) - n_pass,
        "pass_pct": round(100.0 * n_pass / len(rows), 3) if rows else 0.0,
        "fail_criteria": dict(fail_criteria),
        "rows": rows,
    }


def compact_rows(x):
    return {k: v for k, v in x.items() if k != "rows"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", type=Path, default=MODELS / "sac_sym_best.zip")
    ap.add_argument("--asym", type=Path, default=MODELS / "sac_asym_best.zip")
    ap.add_argument("--hvrt-sym", type=Path, default=MODELS / "sac_hvrt_sym_best.zip")
    ap.add_argument("--hvrt-asym", type=Path, default=MODELS / "sac_hvrt_asym_best.zip")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    paths = {
        "sym": args.sym,
        "asym": args.asym,
        "hvrt_sym": args.hvrt_sym,
        "hvrt_asym": args.hvrt_asym,
    }
    models = {k: load_sac(v, device="cpu") for k, v in paths.items()}
    router = ExpertRouter(models)
    expanded = load_frt_scenarios(EXPANDED)
    full320 = load_frt_scenarios(FULL320)
    hard24 = load_frt_scenarios(HARD24) if HARD24.exists() else []
    hard92 = [s for s in expanded if int(s["scenario_id"]) in read_hard92_ids()]

    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "pure_sac": True,
        "deployment_mode": "mi12 online-gated four-expert SAC",
        "model_paths": {k: str(v) for k, v in paths.items()},
        "full320": evaluate_frt(router, full320, HPTFRTEnvV2, n_eval=None),
        "expanded2040": evaluate_frt(router, expanded, HPTFRTEnvV2, n_eval=None),
        "hard24": row_eval(router, hard24) if hard24 else None,
        "hard92": row_eval(router, hard92),
    }
    if args.out is None:
        args.out = RESULTS / f"pure_sac_combo_eval_{time.strftime('%Y%m%d_%H%M%S')}.json"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({
        "out": str(args.out),
        "full320": out["full320"],
        "expanded2040": out["expanded2040"],
        "hard24": compact_rows(out["hard24"]) if out["hard24"] else None,
        "hard92": compact_rows(out["hard92"]),
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
