"""Focused ODE projection search for the last weak-HVRT recovery failures.

This runner is intentionally narrower than overnight_constrained_projection:

* target the current residual failures 1441/1443/1444 (weak SCR=2 swell_3ph);
* preserve hard24 and switching-fail non-regression;
* only run sampled 320/2040 proxy checks after the hard sets look promising.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, replace
from pathlib import Path

from ..error_analysis_mi14 import residual_model_path
from ..frt_env import load_frt_scenarios
from ..model_io import load_sac
from .overnight_constrained_projection import (
    EXPANDED,
    FULL320,
    HARD24,
    ProjectionPolicy,
    ProjectionSpec,
    compact_rows,
    eval_rows,
    score,
    summarize_model,
)
from .switching_aware_preserve_retrain import SWITCHING_FAIL_IDS, hard92_ids
from ..train_common import pick_device, sha256_file


ROOT = Path(__file__).resolve().parents[4]
RES = ROOT / "lab" / "results"


def base_fallback_spec(name: str) -> ProjectionSpec:
    return ProjectionSpec(
        name=name,
        lvrt_enable=True,
        lvrt_iq_gain=0.50,
        lvrt_iq_bias=0.030,
        lvrt_post_iq=-0.08,
        lvrt_post_md=-0.05,
        lvrt_vdc_trigger=0.92,
        lvrt_v_max=0.90,
        recover_enable=True,
        recover_vdc_min=0.93,
        recover_vdc_max=1.00,
        recover_v_max=0.97,
        recover_md=0.03,
        recover_iq=0.12,
        fallback_enable=True,
        fallback_v_min=0.90,
        fallback_v_max=0.97,
        fallback_vdc_min=0.75,
        fallback_vdc_max=1.00,
        fallback_iq=0.30,
        fallback_md=0.12,
    )


def candidate_specs(limit: int | None = None) -> list[ProjectionSpec]:
    vals = []
    for vmin in [0.84, 0.86, 0.88, 0.90, 0.92, 0.94]:
        for vmax in [0.965, 0.975, 0.985, 1.000]:
            for vdcmin in [0.68, 0.70, 0.73, 0.75, 0.77]:
                for md in [0.10, 0.12, 0.14, 0.16, 0.18, 0.20]:
                    vals.append((vmin, vmax, vdcmin, md))

    # Test the current frontier first, then broaden.
    vals = sorted(vals, key=lambda x: (
        abs(x[0] - 0.90),
        abs(x[1] - 0.97),
        abs(x[2] - 0.75),
        abs(x[3] - 0.12),
    ))
    if limit is not None:
        vals = vals[: int(limit)]

    base = base_fallback_spec("focused_base")
    out = []
    for i, (vmin, vmax, vdcmin, md) in enumerate(vals):
        out.append(replace(
            base,
            name=f"focused_fb_{i:03d}",
            fallback_v_min=vmin,
            fallback_v_max=vmax,
            fallback_vdc_min=vdcmin,
            fallback_md=md,
        ))
    return out


def slim_hard(ev: dict) -> dict:
    return {k: compact_rows(v) for k, v in ev.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--quick-eval", type=int, default=240)
    ap.add_argument("--hours", type=float, default=8.0)
    ap.add_argument("--hard-only", action="store_true",
                    help="Only evaluate hard24/hard92/switching-fail sets; use for broad exploration.")
    args = ap.parse_args()

    run_dir = RES / time.strftime("focused_projection_search_%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + args.hours * 3600.0

    expanded = load_frt_scenarios(EXPANDED)
    full320 = load_frt_scenarios(FULL320)
    hard24 = load_frt_scenarios(HARD24)
    hard92 = [s for s in expanded if int(s["scenario_id"]) in hard92_ids()]
    switch_fail = [s for s in expanded if int(s["scenario_id"]) in SWITCHING_FAIL_IDS]

    base_path = residual_model_path()
    base = load_sac(base_path, device=pick_device())
    baseline = {
        "model": str(base_path),
        "sha256": sha256_file(base_path),
        "hard24": eval_rows(base, hard24),
        "hard92": eval_rows(base, hard92),
        "switching_fail_ode": eval_rows(base, switch_fail),
    }
    if not args.hard_only:
        baseline["original320"] = summarize_model(base, full320, n_eval=min(args.quick_eval, len(full320)))
        baseline["expanded2040"] = summarize_model(base, expanded, n_eval=min(args.quick_eval, len(expanded)))
    (run_dir / "baseline.json").write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    baseline_msg = {
        "run_dir": str(run_dir),
        "baseline": {
            "hard24": compact_rows(baseline["hard24"]),
            "hard92": compact_rows(baseline["hard92"]),
            "switching_fail_ode": compact_rows(baseline["switching_fail_ode"]),
        },
    }
    if not args.hard_only:
        baseline_msg["baseline"]["original320"] = baseline["original320"]
        baseline_msg["baseline"]["expanded2040"] = baseline["expanded2040"]
    print(json.dumps(baseline_msg, indent=2), flush=True)

    records = []
    for spec in candidate_specs(args.limit):
        if time.time() > deadline:
            break
        model = ProjectionPolicy(base, spec)
        hard = {
            "hard24": eval_rows(model, hard24),
            "hard92": eval_rows(model, hard92),
            "switching_fail_ode": eval_rows(model, switch_fail),
        }
        promising = (
            hard["hard24"]["pass_count"] >= baseline["hard24"]["pass_count"]
            and hard["switching_fail_ode"]["pass_count"] >= baseline["switching_fail_ode"]["pass_count"]
            and hard["hard92"]["pass_count"] >= 89
        )
        fullish = None
        if promising and not args.hard_only:
            fullish = {
                "original320": summarize_model(model, full320, n_eval=min(args.quick_eval, len(full320))),
                "expanded2040": summarize_model(model, expanded, n_eval=min(args.quick_eval, len(expanded))),
            }
            ev = {**hard, **fullish}
            ev["quick_score"], ev["quick_non_regression_ok"], ev["quick_rejection_reasons"] = score(ev, baseline)
        elif promising:
            ev = {
                **hard,
                "quick_score": (
                    10.0 * hard["hard24"]["pass_count"]
                    + 5.0 * hard["switching_fail_ode"]["pass_count"]
                    + 2.0 * hard["hard92"]["pass_count"]
                ),
                "quick_non_regression_ok": True,
                "quick_rejection_reasons": ["proxy_not_run_hard_only"],
            }
        else:
            ev = {
                **hard,
                "quick_score": -1.0,
                "quick_non_regression_ok": False,
                "quick_rejection_reasons": ["hardset_not_promising"],
            }

        rec = {
            "name": spec.name,
            "spec": asdict(spec),
            "hard": slim_hard(hard),
            "quick": {
                **slim_hard(hard),
                **(fullish or {}),
                "quick_score": ev["quick_score"],
                "quick_non_regression_ok": ev["quick_non_regression_ok"],
                "quick_rejection_reasons": ev["quick_rejection_reasons"],
            },
            "hard92_fail_rows": [r for r in hard["hard92"]["rows"] if not r["passed"]],
        }
        records.append(rec)
        (run_dir / f"{spec.name}.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
        (run_dir / "candidate_results.json").write_text(json.dumps(records, indent=2), encoding="utf-8")

        q = rec["quick"]
        print(
            spec.name,
            "h24", q["hard24"]["pass_count"],
            "h92", q["hard92"]["pass_count"],
            "sf", q["switching_fail_ode"]["pass_count"],
            "score", q["quick_score"],
            "ok", q["quick_non_regression_ok"],
            "reasons", q["quick_rejection_reasons"],
            "spec", {
                "vmin": spec.fallback_v_min,
                "vmax": spec.fallback_v_max,
                "vdcmin": spec.fallback_vdc_min,
                "md": spec.fallback_md,
            },
            flush=True,
        )

    best = sorted(
        records,
        key=lambda r: (
            bool(r["quick"].get("quick_non_regression_ok")),
            r["quick"]["hard24"]["pass_count"],
            r["quick"]["switching_fail_ode"]["pass_count"],
            r["quick"]["hard92"]["pass_count"],
            r["quick"].get("quick_score", -1.0),
        ),
        reverse=True,
    )[:20]
    (run_dir / "best20.json").write_text(json.dumps(best, indent=2), encoding="utf-8")
    print("BEST20", json.dumps(best[:5], indent=2), flush=True)
    print(f"wrote {run_dir}", flush=True)


if __name__ == "__main__":
    main()
