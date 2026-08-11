"""overnight_constrained_projection.py -- automatic constrained repair search.

This runner explores analytic projection wrappers around the promoted residual SAC after the ODE was
aligned to the Simulink Vdc/recovery failures.  It is deliberately conservative:

* no model promotion;
* every candidate is evaluated against the current promoted SAC baseline;
* full expanded-2040 checks are run only for promising candidates;
* logs are written incrementally so the run can be inspected while it is still running.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from hpt_frt.common import frt_v2 as FV2

from ..error_analysis_mi14 import residual_model_path
from ..frt_env import load_frt_scenarios
from ..frt_metrics import CRITERIA, evaluate_frt, evaluate_scenario
from ..model_io import load_sac
from ..residual_env import HPTFRTResidualEnvV2, RES_IQ, RES_MSE, mpc_prior3
from .switching_aware_preserve_retrain import SWITCHING_FAIL_IDS, hard92_ids
from ..train_common import pick_device, sha256_file


ROOT = Path(__file__).resolve().parents[4]
LAB = ROOT / "lab"
RES = LAB / "results"
EXPANDED = LAB / "frt_scenarios_expanded.csv"
FULL320 = LAB / "frt_scenarios.csv"
HARD24 = RES / "hard24_sym3ph_vdc.csv"


@dataclass(frozen=True)
class ProjectionSpec:
    name: str
    lvrt_enable: bool
    lvrt_iq_gain: float = 0.50
    lvrt_iq_bias: float = 0.03
    lvrt_md_fault: float = 0.0
    lvrt_post_thr: float = 1.02
    lvrt_post_iq: float = -0.08
    lvrt_post_md: float = -0.05
    lvrt_v2n_max: float = 0.025
    lvrt_vdc_trigger: float = 1.01
    lvrt_v_min: float = 0.43
    lvrt_v_max: float = 0.62
    hvrt_enable: bool = False
    hvrt_abs_gain: float = 0.0
    hvrt_md_abs_gain: float = 0.0
    hvrt_low_md: float = 1.2
    hvrt_high_md: float = 1.2
    hvrt_post_iq: float = -0.04
    recover_enable: bool = False
    recover_v2n_max: float = 0.025
    recover_v_min: float = 0.0
    recover_v_max: float = 0.97
    recover_vdc_min: float = 0.93
    recover_vdc_max: float = 1.0
    recover_iq: float = 0.12
    recover_md: float = 0.03
    fallback_enable: bool = False
    fallback_v2n_max: float = 0.025
    fallback_v_min: float = 0.90
    fallback_v_max: float = 0.97
    fallback_vdc_min: float = 0.75
    fallback_vdc_max: float = 1.0
    fallback_iq: float = 0.30
    fallback_md: float = 0.12


class ProjectionPolicy:
    """Policy-like wrapper that projects total commands in narrow measured-voltage regions."""

    def __init__(self, base_model, spec: ProjectionSpec):
        self.base_model = base_model
        self.spec = spec
        self.action_space = base_model.action_space
        self.observation_space = base_model.observation_space

    def predict(self, obs, deterministic=True):
        base, _ = self.base_model.predict(obs, deterministic=deterministic)
        obs = np.asarray(obs, np.float32)
        vdc = float(obs[0])
        v = float(obs[1])
        v2n = float(obs[2])
        in_fault = bool(float(obs[16]) > 0.5)
        total = None
        s = self.spec

        # High-authority fallback controller for the weak-HVRT recovery frontier. This deliberately
        # returns an unclipped residual and lets the env/controller physical total-command clamps apply.
        # It is not a SAC action; it represents a fallback path to be validated separately in Simulink.
        if (s.fallback_enable and v2n <= s.fallback_v2n_max
                and s.fallback_v_min <= v < s.fallback_v_max
                and s.fallback_vdc_min <= vdc <= s.fallback_vdc_max):
            total = np.array([s.fallback_iq, s.fallback_md, 0.0], np.float32)
            return (total - mpc_prior3(v, vdc)).astype(np.float32), None

        # Narrow post-fault recovery lift for the remaining weak-HVRT recover-low cases.  This is
        # gated by high Vdc so it does not spend the already-thin DC margin of the hard LVRT cases.
        if (s.recover_enable and v2n <= s.recover_v2n_max
                and s.recover_v_min <= v < s.recover_v_max
                and s.recover_vdc_min <= vdc <= s.recover_vdc_max):
            total = np.array([s.recover_iq, s.recover_md, 0.0], np.float32)

        # LVRT hard24 projection found by aligned_ode_hard24_fine_policy_sweep.json.
        if total is None and s.lvrt_enable and v2n <= s.lvrt_v2n_max:
            if ((in_fault or v < 0.9)
                    and s.lvrt_v_min <= v <= s.lvrt_v_max
                    and vdc <= s.lvrt_vdc_trigger):
                iq = max(0.0, min(0.27, s.lvrt_iq_gain * FV2.iq_ref_droop(v) + s.lvrt_iq_bias))
                total = np.array([iq, s.lvrt_md_fault, 0.0], np.float32)
            elif v > s.lvrt_post_thr:
                total = np.array([s.lvrt_post_iq, s.lvrt_post_md, 0.0], np.float32)

        # HVRT projection: weaker result than LVRT, but useful for recovering 4/5 selected failures.
        if total is None and s.hvrt_enable:
            if in_fault or v > 1.1:
                iq = max(-0.27, min(0.0, s.hvrt_abs_gain * FV2.iq_ref_droop(v)))
                md = -min(0.16, s.hvrt_md_abs_gain * max(0.0, v - 1.1))
                total = np.array([iq, md, 0.0], np.float32)
            elif v < 0.97:
                total = np.array([0.0, s.hvrt_low_md * (0.97 - v), 0.0], np.float32)
            elif v > 1.03:
                total = np.array([s.hvrt_post_iq, -s.hvrt_high_md * (v - 1.03), 0.0], np.float32)

        if total is None:
            return base, None
        res = total - mpc_prior3(v, vdc)
        res = np.clip(res, [-RES_IQ, -RES_MSE, -RES_MSE], [RES_IQ, RES_MSE, RES_MSE]).astype(np.float32)
        return res, None


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


def compact_rows(x: dict) -> dict:
    return {k: v for k, v in x.items() if k != "rows"}


def score(ev: dict, baseline: dict) -> tuple[float, bool, list[str]]:
    reasons = []
    ok = True
    for key in ("hard24", "switching_fail_ode"):
        if ev[key]["pass_count"] < baseline[key]["pass_count"]:
            ok = False
            reasons.append(f"{key}_regressed")
    for key in ("original320", "expanded2040"):
        if ev[key]["partial_proxy_pct"] + 1e-9 < baseline[key]["partial_proxy_pct"]:
            ok = False
            reasons.append(f"{key}_regressed")
    value = (
        ev["expanded2040"]["partial_proxy_pct"]
        + 0.4 * ev["original320"]["partial_proxy_pct"]
        + 1.5 * ev["hard24"]["pass_count"]
        + 2.0 * ev["switching_fail_ode"]["pass_count"]
    )
    return value, ok, reasons


def candidate_specs() -> list[ProjectionSpec]:
    specs = []
    lvrt_core = [
        (0.50, 0.030, -0.08, -0.05, 1.01, 0.62),
        (0.50, 0.030, -0.08, -0.05, 0.88, 0.62),
        (0.50, 0.030, -0.08, -0.05, 0.84, 0.62),
        (0.50, 0.030, -0.10, -0.06, 0.88, 0.62),
        (0.45, 0.045, -0.08, -0.05, 0.88, 0.62),
        (0.55, 0.025, -0.08, -0.05, 0.88, 0.62),
        (0.50, 0.030, -0.08, -0.05, 0.92, 0.90),
        (0.50, 0.030, -0.08, -0.05, 0.88, 0.90),
        (0.45, 0.045, -0.08, -0.05, 0.88, 0.90),
        (0.40, 0.055, -0.08, -0.05, 0.88, 0.90),
    ]
    for i, (gain, bias, piq, pmd, vdc_trigger, vmax) in enumerate(lvrt_core):
        specs.append(ProjectionSpec(
            name=f"lvrt_proj_{i}",
            lvrt_enable=True,
            lvrt_iq_gain=gain,
            lvrt_iq_bias=bias,
            lvrt_post_iq=piq,
            lvrt_post_md=pmd,
            lvrt_vdc_trigger=vdc_trigger,
            lvrt_v_max=vmax,
        ))
    recover_core = [
        # These start from lvrt_proj_6 and add a deliberately narrow high-Vdc recovery lift.  The
        # broad version can rescue 3/4 remaining switching-fail ODE cases but regresses expanded2040;
        # these narrower gates test whether the same family can be non-regressing.
        (0.930, 1.000, 0.97, 0.03, 0.12),
        (0.935, 1.000, 0.97, 0.03, 0.12),
        (0.940, 1.000, 0.97, 0.03, 0.12),
        (0.930, 0.960, 0.97, 0.03, 0.12),
        (0.935, 0.960, 0.97, 0.03, 0.12),
        (0.930, 1.000, 0.93, 0.03, 0.12),
        (0.935, 1.000, 0.93, 0.03, 0.12),
        (0.930, 1.000, 0.97, 0.02, 0.12),
        (0.930, 1.000, 0.97, 0.03, 0.08),
        (0.930, 1.000, 0.97, 0.04, 0.12),
    ]
    for i, (vlo, vhi, vmax, md, iq) in enumerate(recover_core):
        specs.append(ProjectionSpec(
            name=f"lvrt_recover_proj_{i}",
            lvrt_enable=True,
            lvrt_iq_gain=0.50,
            lvrt_iq_bias=0.030,
            lvrt_post_iq=-0.08,
            lvrt_post_md=-0.05,
            lvrt_vdc_trigger=0.92,
            lvrt_v_max=0.90,
            recover_enable=True,
            recover_vdc_min=vlo,
            recover_vdc_max=vhi,
            recover_v_max=vmax,
            recover_md=md,
            recover_iq=iq,
        ))
    fallback_core = [
        # Counterfactual frontier for scenario 1441: narrow near-normal low-recovery gate avoids deep
        # LVRT, while symmetric HVRT post-clear total [iq, md] ~= [0.30, 0.118] rides both the
        # recovery and Vdc boundaries.
        (0.90, 0.97, 0.75, 1.00),
        (0.91, 0.97, 0.75, 1.00),
        (0.92, 0.97, 0.75, 1.00),
        (0.93, 0.97, 0.75, 1.00),
    ]
    for i, (vmin, vmax, vlo, vhi) in enumerate(fallback_core):
        specs.append(ProjectionSpec(
            name=f"lvrt_fallback_proj_{i}",
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
            fallback_v_min=vmin,
            fallback_v_max=vmax,
            fallback_vdc_min=vlo,
            fallback_vdc_max=vhi,
        ))
    hvrt_core = [
        (0.0, 0.0, 1.2, 1.2, -0.04),
        (0.0, 0.2, 1.2, 1.2, -0.04),
        (0.2, 0.0, 1.8, 1.2, 0.0),
    ]
    for i, (ag, mdg, low, high, piq) in enumerate(hvrt_core):
        specs.append(ProjectionSpec(
            name=f"lvrt_hvrt_proj_{i}",
            lvrt_enable=True,
            lvrt_iq_gain=0.50,
            lvrt_iq_bias=0.030,
            lvrt_post_iq=-0.08,
            lvrt_post_md=-0.05,
            lvrt_vdc_trigger=0.88,
            hvrt_enable=True,
            hvrt_abs_gain=ag,
            hvrt_md_abs_gain=mdg,
            hvrt_low_md=low,
            hvrt_high_md=high,
            hvrt_post_iq=piq,
        ))
    return specs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=8.0)
    ap.add_argument("--quick-eval", type=int, default=240)
    ap.add_argument("--full-check", action="store_true",
                    help="Run full 320/2040 checks for promising candidates; slower.")
    ap.add_argument("--max-full", type=int, default=3,
                    help="Maximum number of quick-ranked candidates to full-check.")
    args = ap.parse_args()

    run_dir = RES / time.strftime("overnight_constrained_projection_%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    expanded = load_frt_scenarios(EXPANDED)
    full320 = load_frt_scenarios(FULL320)
    hard24 = load_frt_scenarios(HARD24)
    h92 = hard92_ids()
    hard92 = [s for s in expanded if int(s["scenario_id"]) in h92]
    switch_fail = [s for s in expanded if int(s["scenario_id"]) in SWITCHING_FAIL_IDS]
    base_path = residual_model_path()
    base = load_sac(base_path, device=pick_device())
    deadline = time.time() + args.hours * 3600.0

    baseline = {
        "model": str(base_path),
        "sha256": sha256_file(base_path),
        "hard24": eval_rows(base, hard24),
        "hard92": eval_rows(base, hard92),
        "switching_fail_ode": eval_rows(base, switch_fail),
        "original320": summarize_model(base, full320, n_eval=min(args.quick_eval, len(full320))),
        "expanded2040": summarize_model(base, expanded, n_eval=min(args.quick_eval, len(expanded))),
    }
    (run_dir / "baseline.json").write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    print(json.dumps({
        "run_dir": str(run_dir),
        "baseline": {
            "hard24": compact_rows(baseline["hard24"]),
            "hard92": compact_rows(baseline["hard92"]),
            "switching_fail_ode": compact_rows(baseline["switching_fail_ode"]),
            "original320": baseline["original320"],
            "expanded2040": baseline["expanded2040"],
        },
    }, indent=2), flush=True)

    quick_records = []
    for spec in candidate_specs():
        if time.time() > deadline:
            break
        print(f"=== {spec.name} ===", flush=True)
        model = ProjectionPolicy(base, spec)
        quick = {
            "spec": asdict(spec),
            "hard24": eval_rows(model, hard24),
            "hard92": eval_rows(model, hard92),
            "switching_fail_ode": eval_rows(model, switch_fail),
            "original320": summarize_model(model, full320, n_eval=min(args.quick_eval, len(full320))),
            "expanded2040": summarize_model(model, expanded, n_eval=min(args.quick_eval, len(expanded))),
        }
        quick["quick_score"], quick["quick_non_regression_ok"], quick["quick_rejection_reasons"] = score(
            quick, baseline)
        rec = {"name": spec.name, "spec": asdict(spec), "quick": quick, "full": None}
        (run_dir / f"{spec.name}.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
        slim = {
            "name": spec.name,
            "spec": asdict(spec),
            "quick": {k: (compact_rows(v) if k in {"hard24", "hard92", "switching_fail_ode"} else v)
                      for k, v in quick.items() if k != "spec"},
            "full": None,
        }
        print(json.dumps(slim, indent=2), flush=True)
        quick_records.append(slim)
        (run_dir / "candidate_results.json").write_text(json.dumps(quick_records, indent=2), encoding="utf-8")

    # Full-check only the most promising quick candidates. This avoids spending the night replaying
    # several parameterisations that are identical on the hard sets.
    fulls = []
    if args.full_check:
        ranked = sorted(
            quick_records,
            key=lambda r: (
                bool(r["quick"].get("quick_non_regression_ok")),
                r["quick"]["hard24"]["pass_count"],
                r["quick"]["switching_fail_ode"]["pass_count"],
                r["quick"].get("quick_score", -1),
            ),
            reverse=True,
        )
        selected = ranked[:max(0, int(args.max_full))]
        for r in selected:
            if time.time() > deadline:
                break
            spec = ProjectionSpec(**r["spec"])
            model = ProjectionPolicy(base, spec)
            print(f"=== full {spec.name} ===", flush=True)
            full = {
                "spec": asdict(spec),
                "hard24": eval_rows(model, hard24),
                "hard92": eval_rows(model, hard92),
                "switching_fail_ode": eval_rows(model, switch_fail),
                "original320": summarize_model(model, full320),
                "expanded2040": summarize_model(model, expanded),
            }
            full["score"], full["non_regression_ok"], full["rejection_reasons"] = score(full, baseline)
            fulls.append(full)
            rec_path = run_dir / f"{spec.name}.json"
            rec = json.loads(rec_path.read_text(encoding="utf-8"))
            rec["full"] = full
            rec_path.write_text(json.dumps(rec, indent=2), encoding="utf-8")
            for rr in quick_records:
                if rr["name"] == spec.name:
                    rr["full"] = {
                        k: (compact_rows(v) if k in {"hard24", "hard92", "switching_fail_ode"} else v)
                        for k, v in full.items() if k != "spec"
                    }
                    break
            (run_dir / "candidate_results.json").write_text(json.dumps(quick_records, indent=2), encoding="utf-8")
            print(json.dumps({"name": spec.name, "full": quick_records[[x["name"] for x in quick_records].index(spec.name)]["full"]},
                             indent=2), flush=True)

    winner = None
    if fulls:
        winner = max(fulls, key=lambda r: (r.get("non_regression_ok", False), r.get("score", -1)))
    (run_dir / "winner.json").write_text(json.dumps({"winner": winner}, indent=2), encoding="utf-8")
    print("WINNER", json.dumps({"winner": winner}, indent=2), flush=True)
    print(f"wrote {run_dir}", flush=True)


if __name__ == "__main__":
    main()
