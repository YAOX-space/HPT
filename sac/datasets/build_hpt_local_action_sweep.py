"""Build fixed-action candidate CSVs for local switch-level sweeps.

The output uses the historical ``case_results.csv`` schema so existing result
parsers can inspect the candidates. It is a data builder, not an actor
promotion path.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

from sac.experiment_metadata import write_experiment_metadata


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()
RESULTS = ROOT / "lab" / "results"


def parse_grid(text: str) -> list[float]:
    values = [float(item.strip()) for item in text.split(",") if item.strip()]
    if not values:
        raise argparse.ArgumentTypeError("Grid must contain at least one value")
    return values


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--topology", default="topology2")
    parser.add_argument("--category", default="LVRT")
    parser.add_argument("--phase-key", default="abc")
    parser.add_argument("--case-name", default="lvrt_080ms_0p950pu")
    parser.add_argument("--fault-pu", type=float, default=0.95)
    parser.add_argument("--duration-ms", type=int, default=80)
    parser.add_argument("--reg-d-grid", type=parse_grid, default=parse_grid("0.145,0.172,0.200"))
    parser.add_argument("--energy-d-grid", type=parse_grid, default=parse_grid("0.017,0.022,0.027"))
    parser.add_argument("--reg-q", type=float, default=0.0)
    parser.add_argument("--energy-q", type=float, default=0.002)
    parser.add_argument(
        "--reg-q-grid",
        type=parse_grid,
        default=None,
        help="Optional comma-separated q-axis grid. Overrides --reg-q.",
    )
    parser.add_argument(
        "--energy-q-grid",
        type=parse_grid,
        default=None,
        help="Optional comma-separated energy q-axis grid. Overrides --energy-q.",
    )
    args = parser.parse_args()

    run_id = args.run_id or f"hpt_local_action_sweep_{datetime.now():%Y%m%d_%H%M%S}"
    run_dir = RESULTS / run_id
    rows: list[dict[str, object]] = []
    reg_q_grid = args.reg_q_grid if args.reg_q_grid is not None else [args.reg_q]
    energy_q_grid = args.energy_q_grid if args.energy_q_grid is not None else [args.energy_q]
    for reg_d in args.reg_d_grid:
        for reg_q in reg_q_grid:
            for energy_d in args.energy_d_grid:
                for energy_q in energy_q_grid:
                    token = (
                        f"r{reg_d:.3f}_rq{reg_q:.3f}_e{energy_d:.3f}_eq{energy_q:.3f}"
                        .replace(".", "p")
                        .replace("-", "m")
                    )
                    rows.append(
                        {
                            "algorithm": f"local_sweep/{token}",
                            "topology": args.topology,
                            "category": args.category,
                            "phase_key": args.phase_key,
                            "duration_ms": args.duration_ms,
                            "case_name": args.case_name,
                            "fault_pu": args.fault_pu,
                            "baseline_pass": True,
                            "baseline_score": "",
                            "baseline_reason": "",
                            "policy_pass": True,
                            "policy_score": "",
                            "policy_reason": "",
                            "beat": True,
                            "improved": True,
                            "action_m_reg_d": reg_d,
                            "action_m_reg_q": reg_q,
                            "action_m_energy_d": energy_d,
                            "action_m_energy_q": energy_q,
                            "action_max_abs": max(abs(reg_d), abs(reg_q), abs(energy_d), abs(energy_q)),
                        }
                    )

    csv_path = run_dir / "case_results.csv"
    write_csv(csv_path, rows)
    summary = {
        "schema": "hpt-local-action-sweep-v1",
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "case_results_csv": str(csv_path),
        "candidate_count": len(rows),
        "config": {
            "topology": args.topology,
            "category": args.category,
            "phase_key": args.phase_key,
            "case_name": args.case_name,
            "fault_pu": args.fault_pu,
            "duration_ms": args.duration_ms,
            "reg_d_grid": args.reg_d_grid,
            "energy_d_grid": args.energy_d_grid,
            "reg_q_grid": reg_q_grid,
            "energy_q_grid": energy_q_grid,
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_local_action_sweep",
        config=summary["config"],
        extra=summary,
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


