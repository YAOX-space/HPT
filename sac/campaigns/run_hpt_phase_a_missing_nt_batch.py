"""Run one MATLAB batch to fill Phase-A not-tested cells in the boundary matrix."""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import time
from pathlib import Path


ROOT = Path(r"E:\research_space\Hybrid-power-transformer")
SIMULINK = ROOT / "simulink"
DEFAULT_CELLS = (
    ROOT
    / "experts"
    / "topology2_single_phase_lvrt"
    / "results"
    / "combined_strong_dq_boundary_20260804"
    / "analysis_matrix_refine50"
    / "strong_dq_boundary_cells.csv"
)
DEFAULT_OUT = (
    ROOT
    / "experts"
    / "topology2_single_phase_lvrt"
    / "results"
    / "phase_a_nt_fill_20260804"
)


def matlab_string(value: Path | str) -> str:
    return str(value).replace("\\", "/").replace("'", "''")


def read_missing_phase_a(cells_csv: Path) -> list[tuple[float, int]]:
    rows = list(csv.DictReader(cells_csv.open(newline="", encoding="utf-8-sig")))
    depths = sorted({float(row["fault_pu"]) for row in rows})
    durations = sorted({int(float(row["duration_ms"])) for row in rows})
    tested = {
        (float(row["fault_pu"]), int(float(row["duration_ms"])))
        for row in rows
        if str(row.get("phase") or "") == "a"
    }
    return [(depth, duration) for depth in depths for duration in durations if (depth, duration) not in tested]


def case_name(depth: float, duration_ms: int) -> str:
    return f"lvrt_{int(round(depth * 1000)):04d}_{duration_ms:03d}ms"


def write_runner(run_dir: Path, missing: list[tuple[float, int]]) -> Path:
    compare_dir = run_dir / "control_comparison"
    compare_dir.mkdir(parents=True, exist_ok=True)
    faults = []
    for depth, duration_ms in missing:
        faults.append(
            "'{name}', {depth:.12g}, {duration:.12g}, [{depth:.12g} 1 1]".format(
                name=case_name(depth, duration_ms),
                depth=depth,
                duration=duration_ms / 1000.0,
            )
        )
    runner = run_dir / "run_phase_a_missing_nt_batch.m"
    runner.write_text(
        "\n".join(
            [
                f"cd('{matlab_string(ROOT)}');",
                f"addpath(genpath('{matlab_string(SIMULINK)}'));",
                'hpt_compare_topology = "topology2";',
                'hpt_compare_scenario_type = "fault";',
                'hpt_compare_case_name = "all";',
                'hpt_compare_modes = ["conventional_dq"];',
                "hpt_compare_energy_enable = 1.0;",
                "hpt_compare_voltage_survival_current_gate = true;",
                "hpt_compare_fault_start = 0.080;",
                "hpt_compare_fault_stop_margin = 0.125;",
                'hpt_compare_conventional_profile = "tuned_v2_l1";',
                "hpt_compare_conventional_params = struct();",
                "hpt_compare_faults = { ...",
                "    " + "; ...\n    ".join(faults),
                "};",
                'hpt_compare_run_label = "phase_a_nt_fill_20260804";',
                f"hpt_compare_output_dir = '{matlab_string(compare_dir)}';",
                f"run('{matlab_string(SIMULINK / 'evaluators' / 'eval_hpt_v2_control_comparison.m')}');",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return runner


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cells-csv", type=Path, default=DEFAULT_CELLS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    missing = read_missing_phase_a(args.cells_csv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "schema": "hpt-phase-a-nt-fill-v1",
        "source_cells_csv": str(args.cells_csv),
        "missing_count": len(missing),
        "missing_cases": [
            {"phase": "a", "fault_pu": depth, "duration_ms": duration_ms}
            for depth, duration_ms in missing
        ],
    }
    (args.out_dir / "phase_a_missing_cases.json").write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )
    if not missing:
        print(json.dumps({"out_dir": str(args.out_dir), "missing_count": 0}, indent=2))
        return

    runner = write_runner(args.out_dir, missing)
    log_path = args.out_dir / "phase_a_missing_nt_batch.log"
    command = ["matlab", "-batch", f"run('{matlab_string(runner)}')"]
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("$ " + " ".join(command) + "\n\n")
        log.flush()
        start = time.time()
        proc = subprocess.run(
            command,
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    saved = re.findall(r"Saved CSV:\s*(.+?\.csv)", log_text)
    result = {
        "out_dir": str(args.out_dir),
        "runner": str(runner),
        "log": str(log_path),
        "missing_count": len(missing),
        "returncode": proc.returncode,
        "elapsed_s": time.time() - start,
        "saved_csv": saved[-1].strip() if saved else None,
    }
    (args.out_dir / "phase_a_missing_nt_batch_result.json").write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2), flush=True)
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


if __name__ == "__main__":
    main()
