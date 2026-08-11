"""Compare ODE proxy verdicts against switching Simulink verdicts per scenario.

This is a diagnostic, not a training script. It answers:

* Which Simulink FAIL criteria are visible in the ODE?
* Which failures are ODE-blind because the ODE marks the criterion PASS/NOT_EVALUATED?
* Where does the ODE proxy pass a case that switching Simulink fails?

The default compares the current pure-SAC four-expert controller plus the two active
traditional baselines on full320.
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
from .eval_pass_sets_2040 import DQDroopPolicy, ExplicitMPCPriorPolicy
from .frt_env import I_Q_ACT, load_frt_scenarios
from .frt_env_v2 import HPTFRTEnvV2
from .frt_metrics import CRITERIA, evaluate_scenario
from .model_io import load_sac
from .pure_sac_hard_curriculum import ExpertRouter


ROOT = Path(__file__).resolve().parents[3]
LAB = ROOT / "lab"
RESULTS = LAB / "results"
FULL320 = LAB / "frt_scenarios.csv"
DEFAULT_COMBO = RESULTS / "pure_sac_combo_export_pure_sac_gate1060_current_models_20260711.json"
DEFAULT_TAG = "current_puresac_vs_traditional_20260712"


def norm_status(x) -> str:
    s = "" if x is None else str(x)
    return s if s else ""


def boolish_pass(x) -> bool:
    return str(x) == "True"


def proxy_pass_from_ode(res: dict) -> bool:
    statuses = [res[c]["status"] for c in CRITERIA if res[c]["status"] != FV2.NOT_EVALUATED]
    if not statuses:
        return False
    return all(s == FV2.PASS for s in statuses) and res.get("vdc_survive_proxy", FV2.PASS) == FV2.PASS


def ode_pack(classified: dict) -> dict:
    if classified["kind"] != "evaluated":
        return {
            "ode_kind": classified["kind"],
            "ode_proxy_pass": False,
            "ode_frt_pass": "",
            "ode_failed_criteria": classified.get("error", classified["kind"]),
            "ode_not_eval_criteria": "",
            "ode_vdc_min": "",
            **{f"ode_{c}": "" for c in CRITERIA},
        }
    res = classified["res"]
    failed = [c for c in CRITERIA if res[c]["status"] == FV2.FAIL]
    if res.get("vdc_survive_proxy") == FV2.FAIL:
        failed.append("vdc_survive_proxy")
    ne = [c for c in CRITERIA if res[c]["status"] == FV2.NOT_EVALUATED]
    frt = res.get("frt_pass")
    return {
        "ode_kind": "evaluated",
        "ode_proxy_pass": proxy_pass_from_ode(res),
        "ode_frt_pass": "None" if frt is None else str(bool(frt)),
        "ode_failed_criteria": "+".join(failed),
        "ode_not_eval_criteria": "+".join(ne),
        "ode_vdc_min": res.get("vdc_min", ""),
        **{f"ode_{c}": res[c]["status"] for c in CRITERIA},
    }


def load_current_sac(combo_path: Path):
    combo = json.loads(combo_path.read_text(encoding="utf-8"))
    paths = {k: ROOT / v for k, v in combo["model_paths"].items()}
    models = {k: load_sac(v, device="cpu") for k, v in paths.items()}
    return ExpertRouter(models), {k: str(v) for k, v in paths.items()}, combo.get("run_id", combo_path.stem)


def sim_csv_for(results_dir: Path, scenario_set: str, tag: str, mi: int) -> Path:
    return results_dir / f"passset_{scenario_set}_switching_{tag}_mi{mi}.csv"


def read_sim_rows(path: Path) -> dict[int, dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return {int(r["sid"]): r for r in csv.DictReader(f)}


def sim_pack(row: dict) -> dict:
    failed = [c for c in CRITERIA if norm_status(row.get(c)) == FV2.FAIL]
    ne = [c for c in CRITERIA if norm_status(row.get(c)) == FV2.NOT_EVALUATED]
    return {
        "sim_frt": row.get("frt", ""),
        "sim_strict_pass": row.get("frt", "") == "True",
        "sim_no_fail": row.get("frt", "") in ("True", "None"),
        "sim_failed_criteria": "+".join(failed),
        "sim_not_eval_criteria": "+".join(ne),
        **{f"sim_{c}": row.get(c, "") for c in CRITERIA},
    }


def classify_visibility(sim: dict, ode: dict) -> tuple[str, str, str]:
    sim_failed = [c for c in CRITERIA if sim.get(f"sim_{c}") == FV2.FAIL]
    if not sim_failed:
        return "no_sim_fail", "", ""
    matched, blind, mismatch = [], [], []
    for c in sim_failed:
        os = ode.get(f"ode_{c}", "")
        if os == FV2.FAIL:
            matched.append(c)
        elif os == FV2.NOT_EVALUATED:
            blind.append(c)
        else:
            mismatch.append(c)
    if blind or mismatch:
        label = "ode_blind_or_mismatch"
    else:
        label = "ode_visible"
    return label, "+".join(matched), "+".join(blind + mismatch)


def evaluate_controller(name: str, policy, scenarios: list[dict], sim_rows: dict[int, dict]) -> list[dict]:
    out = []
    for i, s in enumerate(scenarios, 1):
        sid = int(s["scenario_id"])
        if sid not in sim_rows:
            continue
        sim = sim_pack(sim_rows[sid])
        ode = ode_pack(evaluate_scenario(policy, HPTFRTEnvV2, s))
        vis, matched, blind = classify_visibility(sim, ode)
        row = {
            "controller": name,
            "scenario_id": sid,
            "category": s["category"],
            "fault_type": s["fault_type"],
            "scr": float(s["scr"]),
            "target_V_pu": float(s["target_V_pu"]),
            **sim,
            **ode,
            "agreement_strict_vs_proxy": str(boolish_pass(sim["sim_frt"]) == bool(ode["ode_proxy_pass"])),
            "danger_sim_fail_ode_proxy_pass": str(sim["sim_frt"] == "False" and bool(ode["ode_proxy_pass"])),
            "sim_true_ode_proxy_fail": str(sim["sim_frt"] == "True" and not bool(ode["ode_proxy_pass"])),
            "ode_visibility": vis,
            "ode_matched_failed_criteria": matched,
            "ode_blind_failed_criteria": blind,
        }
        out.append(row)
        if i % 100 == 0 or i == len(scenarios):
            print(f"{name}: {i}/{len(scenarios)}", flush=True)
    return out


def summarize(rows: list[dict]) -> dict:
    by_controller = {}
    for name in sorted({r["controller"] for r in rows}):
        rs = [r for r in rows if r["controller"] == name]
        n = len(rs)
        crit_blind = Counter()
        crit_match = Counter()
        groups = defaultdict(lambda: Counter())
        for r in rs:
            for c in str(r["ode_blind_failed_criteria"]).split("+"):
                if c:
                    crit_blind[c] += 1
            for c in str(r["ode_matched_failed_criteria"]).split("+"):
                if c:
                    crit_match[c] += 1
            groups[(r["category"], r["fault_type"])][r["sim_frt"]] += 1
        by_controller[name] = {
            "n": n,
            "sim_true": sum(r["sim_frt"] == "True" for r in rs),
            "sim_false": sum(r["sim_frt"] == "False" for r in rs),
            "sim_none": sum(r["sim_frt"] == "None" for r in rs),
            "ode_proxy_pass": sum(bool(r["ode_proxy_pass"]) for r in rs),
            "agreement_strict_vs_proxy": sum(r["agreement_strict_vs_proxy"] == "True" for r in rs),
            "danger_sim_fail_ode_proxy_pass": sum(r["danger_sim_fail_ode_proxy_pass"] == "True" for r in rs),
            "sim_true_ode_proxy_fail": sum(r["sim_true_ode_proxy_fail"] == "True" for r in rs),
            "ode_visible_sim_fail": sum(r["ode_visibility"] == "ode_visible" for r in rs),
            "ode_blind_or_mismatch_sim_fail": sum(r["ode_visibility"] == "ode_blind_or_mismatch" for r in rs),
            "blind_failed_criteria": dict(crit_blind),
            "matched_failed_criteria": dict(crit_match),
            "by_group_sim_frt": {
                f"{k[0]}/{k[1]}": dict(v) for k, v in sorted(groups.items())
            },
        }
    return by_controller


def write_csv(path: Path, rows: list[dict]) -> None:
    fields = [
        "controller", "scenario_id", "category", "fault_type", "scr", "target_V_pu",
        "sim_frt", "ode_proxy_pass", "ode_frt_pass", "agreement_strict_vs_proxy",
        "danger_sim_fail_ode_proxy_pass", "sim_true_ode_proxy_fail", "ode_visibility",
        "sim_failed_criteria", "ode_failed_criteria", "sim_not_eval_criteria", "ode_not_eval_criteria",
        "ode_matched_failed_criteria", "ode_blind_failed_criteria", "ode_vdc_min",
    ]
    fields += [f"sim_{c}" for c in CRITERIA] + [f"ode_{c}" for c in CRITERIA]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario-set", choices=["full320"], default="full320")
    ap.add_argument("--scenarios", type=Path, default=FULL320)
    ap.add_argument("--tag", default=DEFAULT_TAG)
    ap.add_argument("--combo", type=Path, default=DEFAULT_COMBO)
    ap.add_argument("--out-tag", default=None)
    args = ap.parse_args()

    scenarios = load_frt_scenarios(args.scenarios)
    sac, sac_paths, sac_run_id = load_current_sac(args.combo)
    controllers = {
        "pure_sac_mi12": (sac, sim_csv_for(RESULTS, args.scenario_set, args.tag, 12)),
        "fixed_mi7": (DQDroopPolicy(cap=0.27), sim_csv_for(RESULTS, args.scenario_set, args.tag, 7)),
        "mpc_mi8": (ExplicitMPCPriorPolicy(), sim_csv_for(RESULTS, args.scenario_set, args.tag, 8)),
    }

    all_rows = []
    for name, (policy, sim_path) in controllers.items():
        if not sim_path.exists():
            raise FileNotFoundError(sim_path)
        print(f"comparing {name}: {sim_path}", flush=True)
        all_rows.extend(evaluate_controller(name, policy, scenarios, read_sim_rows(sim_path)))

    out_tag = args.out_tag or f"ode_vs_simulink_{args.scenario_set}_{args.tag}"
    base = RESULTS / out_tag
    write_csv(base.with_suffix(".csv"), all_rows)
    summary = {
        "metrics_version": FV2.METRICS_VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "scenario_set": args.scenario_set,
        "scenario_file": str(args.scenarios),
        "simulink_tag": args.tag,
        "sac_run_id": sac_run_id,
        "sac_model_paths": sac_paths,
        "meaning": {
            "danger_sim_fail_ode_proxy_pass": "Simulink has frt=False but ODE partial proxy passes.",
            "ode_blind_failed_criteria": "Simulink failed criteria whose ODE status was PASS/NOT_EVALUATED/other.",
        },
        "summary": summarize(all_rows),
    }
    base.with_suffix(".json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"csv": str(base.with_suffix(".csv")), "json": str(base.with_suffix(".json")),
                      "summary": summary["summary"]}, indent=2), flush=True)


if __name__ == "__main__":
    main()
