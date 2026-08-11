"""Build SAC repair-target CSVs from Simulink pass-set and ODE-vs-Simulink diagnostics."""
from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "lab" / "results"
DEFAULT_COMPARE = RESULTS / "simulink_passset_full320_current_puresac_vs_traditional_20260712_pure_sac_vs_traditional.csv"
DEFAULT_ODE_SIM = RESULTS / "ode_vs_simulink_full320_current_puresac_vs_traditional_20260712.csv"


def read_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_rows(path: Path, rows: list[dict]) -> None:
    fields = [
        "scenario_id", "source", "target_group", "expert", "category", "fault_type", "scr",
        "target_V_pu", "sac_mi12", "fixed_mi7", "mpc_mi8", "sim_failed_criteria",
        "ode_failed_criteria", "ode_blind_failed_criteria", "sac_reactive", "sac_recover",
        "sac_survive",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def expert_of(category: str, fault_type: str) -> str:
    if category == "HVRT":
        return "hvrt_asym" if fault_type == "swell_1ph" else "hvrt_sym"
    return "sym" if fault_type == "sym3ph" else "asym"


def key(row: dict) -> int:
    return int(row.get("scenario_id") or row.get("sid"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare", type=Path, default=DEFAULT_COMPARE)
    ap.add_argument("--ode-sim", type=Path, default=DEFAULT_ODE_SIM)
    ap.add_argument("--tag", default="full320_sim_repair_20260712")
    args = ap.parse_args()

    compare_rows = read_rows(args.compare)
    ode_rows = [r for r in read_rows(args.ode_sim) if r["controller"] == "pure_sac_mi12"]
    ode_by_id = {key(r): r for r in ode_rows}

    targets: dict[int, dict] = {}
    for r in compare_rows:
        sid = key(r)
        if r["strict_category"] in ("traditional-only", "both-fail"):
            o = ode_by_id.get(sid, {})
            src = r["strict_category"]
            if o.get("danger_sim_fail_ode_proxy_pass") == "True":
                src += "+ode_blind"
            row = {
                "scenario_id": sid,
                "source": src,
                "target_group": r["strict_category"],
                "expert": expert_of(r["category"], r["fault_type"]),
                "category": r["category"],
                "fault_type": r["fault_type"],
                "scr": r["scr"],
                "target_V_pu": r["target_V_pu"],
                "sac_mi12": r["sac_mi12"],
                "fixed_mi7": r["fixed_mi7"],
                "mpc_mi8": r["mpc_mi8"],
                "sim_failed_criteria": o.get("sim_failed_criteria", ""),
                "ode_failed_criteria": o.get("ode_failed_criteria", ""),
                "ode_blind_failed_criteria": o.get("ode_blind_failed_criteria", ""),
                "sac_reactive": r.get("sac_reactive", ""),
                "sac_recover": r.get("sac_recover", ""),
                "sac_survive": r.get("sac_survive", ""),
            }
            targets[sid] = row

    all_rows = [targets[sid] for sid in sorted(targets)]
    base = RESULTS / f"repair_targets_{args.tag}"
    write_rows(base.with_suffix(".csv"), all_rows)

    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "compare_csv": str(args.compare),
        "ode_sim_csv": str(args.ode_sim),
        "n_targets": len(all_rows),
        "by_source": dict(Counter(r["source"] for r in all_rows)),
        "by_expert": dict(Counter(r["expert"] for r in all_rows)),
        "by_group": dict(Counter(f"{r['category']}/{r['fault_type']}" for r in all_rows)),
        "outputs": {"all": str(base.with_suffix(".csv"))},
    }

    for expert in ("sym", "asym", "hvrt_sym", "hvrt_asym"):
        rows = [r for r in all_rows if r["expert"] == expert]
        path = base.with_name(f"{base.name}_{expert}").with_suffix(".csv")
        write_rows(path, rows)
        summary["outputs"][expert] = str(path)
    base.with_suffix(".json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"summary": summary, "json": str(base.with_suffix(".json"))}, indent=2), flush=True)


if __name__ == "__main__":
    main()
