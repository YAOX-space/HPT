"""Fast target-first search for the remaining weak-HVRT ODE failures.

This is a prefilter for focused_projection_search.  It evaluates only the remaining target ids
1441/1443/1444 first, then runs hard24/switching checks for candidates that improve those targets.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, replace
from pathlib import Path

from ..error_analysis_mi14 import residual_model_path
from .focused_projection_search import base_fallback_spec
from ..frt_env import load_frt_scenarios
from ..model_io import load_sac
from .overnight_constrained_projection import EXPANDED, HARD24, ProjectionPolicy, eval_rows
from .switching_aware_preserve_retrain import SWITCHING_FAIL_IDS
from ..train_common import pick_device


ROOT = Path(__file__).resolve().parents[4]
RES = ROOT / "lab" / "results"
TARGET_IDS = {1441, 1443, 1444}


def candidate_specs(limit: int | None = None):
    vals = []
    for vmin in [0.70, 0.75, 0.82, 0.84, 0.86, 0.88, 0.90, 0.92, 0.94]:
        for vmax in [0.955, 0.965, 0.975, 0.985, 1.000, 1.020]:
            for vdcmin in [0.64, 0.68, 0.70, 0.73, 0.75, 0.77]:
                for iq in [0.00, 0.12, 0.20, 0.27, 0.30]:
                    for md in [0.10, 0.114, 0.116, 0.118, 0.12, 0.122, 0.124, 0.14, 0.16, 0.18, 0.20]:
                        vals.append((vmin, vmax, vdcmin, iq, md))
    vals = sorted(vals, key=lambda x: (
        abs(x[0] - 0.90),
        abs(x[1] - 0.97),
        abs(x[2] - 0.75),
        abs(x[3] - 0.30),
        abs(x[4] - 0.118),
    ))
    if limit is not None:
        vals = vals[: int(limit)]
    base = base_fallback_spec("target_base")
    for i, (vmin, vmax, vdcmin, iq, md) in enumerate(vals):
        yield replace(
            base,
            name=f"target_fb_{i:04d}",
            fallback_v_min=vmin,
            fallback_v_max=vmax,
            fallback_vdc_min=vdcmin,
            fallback_iq=iq,
            fallback_md=md,
        )


def compact(ev):
    return {k: v for k, v in ev.items() if k != "rows"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=512)
    ap.add_argument("--hours", type=float, default=8.0)
    args = ap.parse_args()

    run_dir = RES / time.strftime("target_projection_search_%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + args.hours * 3600.0

    expanded = load_frt_scenarios(EXPANDED)
    targets = [s for s in expanded if int(s["scenario_id"]) in TARGET_IDS]
    switch_fail = [s for s in expanded if int(s["scenario_id"]) in SWITCHING_FAIL_IDS]
    hard24 = load_frt_scenarios(HARD24)
    base = load_sac(residual_model_path(), device=pick_device())

    records = []
    print(json.dumps({"run_dir": str(run_dir), "target_ids": sorted(TARGET_IDS)}, indent=2), flush=True)
    for spec in candidate_specs(args.limit):
        if time.time() > deadline:
            break
        model = ProjectionPolicy(base, spec)
        target_ev = eval_rows(model, targets)
        hard24_ev = None
        switch_ev = None
        if target_ev["pass_count"] >= 1:
            hard24_ev = eval_rows(model, hard24)
            switch_ev = eval_rows(model, switch_fail)
        rec = {
            "name": spec.name,
            "spec": asdict(spec),
            "target": compact(target_ev),
            "target_fail_rows": [r for r in target_ev["rows"] if not r["passed"]],
            "hard24": compact(hard24_ev) if hard24_ev else None,
            "switching_fail_ode": compact(switch_ev) if switch_ev else None,
        }
        records.append(rec)
        (run_dir / "candidate_results.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
        if target_ev["pass_count"] or len(records) % 20 == 0:
            print(
                spec.name,
                "target", target_ev["pass_count"], "/", target_ev["n"],
                "hard24", None if hard24_ev is None else hard24_ev["pass_count"],
                "switch", None if switch_ev is None else switch_ev["pass_count"],
                "spec", {
                    "vmin": spec.fallback_v_min,
                    "vmax": spec.fallback_v_max,
                    "vdcmin": spec.fallback_vdc_min,
                    "iq": spec.fallback_iq,
                    "md": spec.fallback_md,
                },
                flush=True,
            )

    best = sorted(
        records,
        key=lambda r: (
            r["target"]["pass_count"],
            -len(r["target_fail_rows"]),
            -sum(float(x.get("vdc_min") or 0.0) for x in r["target_fail_rows"]),
        ),
        reverse=True,
    )[:30]
    (run_dir / "best30.json").write_text(json.dumps(best, indent=2), encoding="utf-8")
    print("BEST30", json.dumps(best[:5], indent=2), flush=True)
    print(f"wrote {run_dir}", flush=True)


if __name__ == "__main__":
    main()
