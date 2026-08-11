"""Pass-set comparison on expanded-2040 ODE frt-v2 proxy.

This compares the current deployed pure-SAC four-expert controller against
traditional/controller baselines on exactly the same expanded scenario list and
the same ODE frt-v2 partial-proxy semantics used for checkpoint selection.

Important: ODE cannot certify limit/survive because switching currents and I2
are unavailable. Here "pass" means all available frt-v2 criteria pass and the
ODE Vdc survival proxy passes. This is a pass-set coverage experiment, not a
Simulink strict certification.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from hpt_frt.common import frt_v2 as FV2
from .frt_env import I_Q_ACT, V_SE_MAX, load_frt_scenarios
from .frt_env_v2 import HPTFRTEnvV2
from .frt_metrics import CRITERIA, evaluate_scenario
from .model_io import load_sac
from .pure_sac_hard_curriculum import ExpertRouter
from .residual_env import mpc_prior3


ROOT = Path(__file__).resolve().parents[3]
LAB = ROOT / "lab"
RESULTS = LAB / "results"
EXPANDED = LAB / "frt_scenarios_expanded.csv"


DEFAULT_COMBO = RESULTS / "pure_sac_combo_export_pure_sac_recent_hvrt_hvrtsym_multilabel_20260711.json"


class ConstantPolicy:
    def __init__(self, action):
        self.action = np.asarray(action, dtype=np.float32)

    def predict(self, obs, deterministic=True):
        return self.action.copy(), None


class DQDroopPolicy:
    """Reactive-current-only dq droop, no series injection."""

    def __init__(self, cap=0.30):
        self.cap = float(cap)

    def predict(self, obs, deterministic=True):
        v = float(obs[1])
        iq = float(np.clip(FV2.iq_ref_droop(v), -self.cap, self.cap))
        return np.array([iq, 0.0, 0.0], dtype=np.float32), None


class ExplicitMPCPriorPolicy:
    """Analytic mode-8 prior, without learned residual."""

    def predict(self, obs, deterministic=True):
        a = mpc_prior3(float(obs[1]), float(obs[0]))
        a[0] = float(np.clip(a[0], -I_Q_ACT, I_Q_ACT))
        a[1] = float(np.clip(a[1], -V_SE_MAX, V_SE_MAX))
        a[2] = float(np.clip(a[2], -V_SE_MAX, V_SE_MAX))
        return a.astype(np.float32), None


def available_proxy_pass(res: dict) -> bool:
    statuses = [res[c]["status"] for c in CRITERIA if res[c]["status"] != FV2.NOT_EVALUATED]
    if not statuses:
        return False
    return all(s == FV2.PASS for s in statuses) and res.get("vdc_survive_proxy", FV2.PASS) == FV2.PASS


def status_pack(classified: dict) -> dict:
    if classified["kind"] != "evaluated":
        return {
            "proxy_pass": False,
            "kind": classified["kind"],
            "failed_criteria": classified.get("error", classified["kind"]),
            "not_eval_criteria": "",
            "vdc_min": "",
            "connect": "",
            "reactive": "",
            "limit": "",
            "recover": "",
            "survive": "",
        }
    res = classified["res"]
    fails = [c for c in CRITERIA if res[c]["status"] == FV2.FAIL]
    if res.get("vdc_survive_proxy") == FV2.FAIL:
        fails.append("vdc_survive_proxy")
    ne = [c for c in CRITERIA if res[c]["status"] == FV2.NOT_EVALUATED]
    return {
        "proxy_pass": available_proxy_pass(res),
        "kind": "evaluated",
        "failed_criteria": "+".join(fails),
        "not_eval_criteria": "+".join(ne),
        "vdc_min": res.get("vdc_min", ""),
        "connect": res["connect"]["status"],
        "reactive": res["reactive"]["status"],
        "limit": res["limit"]["status"],
        "recover": res["recover"]["status"],
        "survive": res["survive"]["status"],
    }


def load_current_sac(combo_path: Path):
    combo = json.loads(combo_path.read_text(encoding="utf-8"))
    paths = {k: ROOT / v for k, v in combo["model_paths"].items()}
    models = {k: load_sac(v, device="cpu") for k, v in paths.items()}
    return ExpertRouter(models), {k: str(v) for k, v in paths.items()}, combo.get("run_id", combo_path.stem)


def evaluate_policy(name: str, policy, scenarios: list[dict]) -> list[dict]:
    rows = []
    t0 = time.time()
    for i, s in enumerate(scenarios, 1):
        c = evaluate_scenario(policy, HPTFRTEnvV2, s)
        p = status_pack(c)
        p.update(
            controller=name,
            scenario_id=int(s["scenario_id"]),
            category=s["category"],
            fault_type=s["fault_type"],
            scr=float(s["scr"]),
            target_V_pu=float(s["target_V_pu"]),
            duration_bin_s=float(s.get("duration_bin_s", 0.0)),
            xr_ratio=float(s.get("xr_ratio", 0.0)),
        )
        rows.append(p)
        if i % 200 == 0 or i == len(scenarios):
            n_pass = sum(r["proxy_pass"] for r in rows)
            print(f"{name}: {i}/{len(scenarios)} proxy_pass={n_pass} elapsed={time.time()-t0:.1f}s", flush=True)
    return rows


def summarize_controller(rows: list[dict]) -> dict:
    n = len(rows)
    pass_rows = [r for r in rows if r["proxy_pass"]]
    fail_counter = Counter()
    ne_counter = Counter()
    by_cat = defaultdict(lambda: [0, 0])
    by_ft = defaultdict(lambda: [0, 0])
    for r in rows:
        by_cat[r["category"]][0] += 1
        by_cat[r["category"]][1] += int(r["proxy_pass"])
        by_ft[r["fault_type"]][0] += 1
        by_ft[r["fault_type"]][1] += int(r["proxy_pass"])
        for c in str(r["failed_criteria"]).split("+"):
            if c:
                fail_counter[c] += 1
        for c in str(r["not_eval_criteria"]).split("+"):
            if c:
                ne_counter[c] += 1
    return {
        "n": n,
        "proxy_pass_count": len(pass_rows),
        "proxy_fail_count": n - len(pass_rows),
        "proxy_pass_pct": round(100.0 * len(pass_rows) / n, 3) if n else 0.0,
        "failed_criteria": dict(fail_counter),
        "not_eval_criteria": dict(ne_counter),
        "by_category": {k: {"n": v[0], "pass": v[1], "pass_pct": round(100.0 * v[1] / v[0], 3)}
                        for k, v in sorted(by_cat.items())},
        "by_fault_type": {k: {"n": v[0], "pass": v[1], "pass_pct": round(100.0 * v[1] / v[0], 3)}
                          for k, v in sorted(by_ft.items())},
    }


def bucket_summary(sac_pass: set[int], trad_pass: set[int], scenario_meta: dict[int, dict]) -> dict:
    sac_only = sorted(sac_pass - trad_pass)
    trad_only = sorted(trad_pass - sac_pass)
    both = sorted(sac_pass & trad_pass)
    neither = sorted(set(scenario_meta) - (sac_pass | trad_pass))
    def top(ids, keys=("fault_type", "scr", "target_V_pu", "duration_bin_s")):
        c = Counter(tuple(scenario_meta[i].get(k) for k in keys) for i in ids)
        return [{"count": n, **{keys[j]: vals[j] for j in range(len(keys))}}
                for vals, n in c.most_common(12)]
    return {
        "sac_only_pass_count": len(sac_only),
        "traditional_only_pass_count": len(trad_only),
        "both_pass_count": len(both),
        "both_fail_count": len(neither),
        "sac_only_pass_ids": sac_only,
        "traditional_only_pass_ids": trad_only,
        "both_pass_ids": both,
        "both_fail_ids": neither,
        "traditional_only_top": top(trad_only),
        "sac_only_top": top(sac_only),
    }


def write_pair_csv(path: Path, pair_rows: list[dict]):
    fields = [
        "baseline", "scenario_id", "bucket", "sac_pass", "baseline_pass",
        "category", "fault_type", "scr", "target_V_pu", "duration_bin_s", "xr_ratio",
        "sac_failed_criteria", "baseline_failed_criteria",
        "sac_not_eval_criteria", "baseline_not_eval_criteria",
        "sac_vdc_min", "baseline_vdc_min",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(pair_rows)


def write_traditional_only_union_csv(
    path: Path,
    traditional_only_ids: list[int],
    sac_rows: dict[int, dict],
    baseline_pass_by_id: dict[int, list[str]],
    scenario_meta: dict[int, dict],
):
    fields = [
        "scenario_id", "baselines_passed", "category", "fault_type", "scr", "target_V_pu",
        "duration_bin_s", "xr_ratio", "sac_failed_criteria", "sac_not_eval_criteria", "sac_vdc_min",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for sid in traditional_only_ids:
            sr = sac_rows[sid]
            w.writerow({
                "scenario_id": sid,
                "baselines_passed": "+".join(baseline_pass_by_id.get(sid, [])),
                **scenario_meta[sid],
                "sac_failed_criteria": sr["failed_criteria"],
                "sac_not_eval_criteria": sr["not_eval_criteria"],
                "sac_vdc_min": sr["vdc_min"],
            })


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", type=Path, default=EXPANDED)
    ap.add_argument("--combo", type=Path, default=DEFAULT_COMBO)
    ap.add_argument("--tag", default=f"pass_sets_2040_{time.strftime('%Y%m%d_%H%M%S')}")
    args = ap.parse_args()

    scenarios = load_frt_scenarios(args.scenarios)
    scenario_meta = {
        int(s["scenario_id"]): {
            "category": s["category"],
            "fault_type": s["fault_type"],
            "scr": float(s["scr"]),
            "target_V_pu": float(s["target_V_pu"]),
            "duration_bin_s": float(s.get("duration_bin_s", 0.0)),
            "xr_ratio": float(s.get("xr_ratio", 0.0)),
        }
        for s in scenarios
    }

    sac, sac_paths, run_id = load_current_sac(args.combo)
    controllers = {
        "pure_sac_current": sac,
        "dq_droop_iq030_no_series": DQDroopPolicy(cap=0.30),
        "fixed_law_iq027_no_series": DQDroopPolicy(cap=0.27),
        "explicit_mpc_prior": ExplicitMPCPriorPolicy(),
        "no_hlc_zero": ConstantPolicy([0.0, 0.0, 0.0]),
    }

    all_rows = {}
    summaries = {}
    for name, policy in controllers.items():
        rows = evaluate_policy(name, policy, scenarios)
        all_rows[name] = rows
        summaries[name] = summarize_controller(rows)

    sac_rows = {r["scenario_id"]: r for r in all_rows["pure_sac_current"]}
    sac_pass = {sid for sid, r in sac_rows.items() if r["proxy_pass"]}
    pair_rows = []
    pass_sets = {}
    baseline_names = [n for n in controllers if n != "pure_sac_current"]
    union_pass = set()
    baseline_pass_by_id = defaultdict(list)
    for b in baseline_names:
        b_rows = {r["scenario_id"]: r for r in all_rows[b]}
        b_pass = {sid for sid, r in b_rows.items() if r["proxy_pass"]}
        union_pass |= b_pass
        for sid in b_pass:
            baseline_pass_by_id[sid].append(b)
        pass_sets[b] = bucket_summary(sac_pass, b_pass, scenario_meta)
        for sid in sorted(scenario_meta):
            sp = sid in sac_pass
            bp = sid in b_pass
            if sp and bp:
                bucket = "both_pass"
            elif sp and not bp:
                bucket = "sac_only"
            elif bp and not sp:
                bucket = "traditional_only"
            else:
                bucket = "both_fail"
            sr = sac_rows[sid]
            br = b_rows[sid]
            meta = scenario_meta[sid]
            pair_rows.append({
                "baseline": b,
                "scenario_id": sid,
                "bucket": bucket,
                "sac_pass": sp,
                "baseline_pass": bp,
                **meta,
                "sac_failed_criteria": sr["failed_criteria"],
                "baseline_failed_criteria": br["failed_criteria"],
                "sac_not_eval_criteria": sr["not_eval_criteria"],
                "baseline_not_eval_criteria": br["not_eval_criteria"],
                "sac_vdc_min": sr["vdc_min"],
                "baseline_vdc_min": br["vdc_min"],
            })
    pass_sets["traditional_union"] = bucket_summary(sac_pass, union_pass, scenario_meta)

    base = RESULTS / args.tag
    out = {
        "metrics_version": FV2.METRICS_VERSION,
        "layer": "ODE",
        "scenario_file": str(args.scenarios),
        "n_scenarios": len(scenarios),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "sac_run_id": run_id,
        "sac_model_paths": sac_paths,
        "pass_definition": (
            "ODE partial proxy: all available frt-v2 criteria PASS and vdc_survive_proxy PASS; "
            "limit/survive remain NOT_EVALUATED when switching current/I2 are unavailable. "
            "This is not a certified Simulink frt-v2 pass rate."
        ),
        "controller_summaries": summaries,
        "pass_sets": pass_sets,
    }
    base.with_suffix(".json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    write_pair_csv(base.with_suffix(".csv"), pair_rows)
    write_traditional_only_union_csv(
        base.with_name(base.name + "_traditional_only_union").with_suffix(".csv"),
        pass_sets["traditional_union"]["traditional_only_pass_ids"],
        sac_rows,
        baseline_pass_by_id,
        scenario_meta,
    )

    print(json.dumps({
        "json": str(base.with_suffix(".json")),
        "csv": str(base.with_suffix(".csv")),
        "traditional_only_union_csv": str(base.with_name(base.name + "_traditional_only_union").with_suffix(".csv")),
        "summaries": {k: {"pass": v["proxy_pass_count"], "n": v["n"], "pct": v["proxy_pass_pct"]}
                      for k, v in summaries.items()},
        "pass_sets": {k: {kk: vv for kk, vv in v.items() if kk.endswith("_count")}
                      for k, v in pass_sets.items()},
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
