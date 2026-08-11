"""Collect per-step switch-level actor traces for an HPT fault-family manifest.

This is a small orchestration layer around
``simulink/collectors/collect_hpt_v2_trajectory_trace.m``.  It keeps
the actor export, MATLAB run commands, generated trace CSVs, and aggregate CSV
together in one reproducible run directory.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
from pathlib import Path
from typing import Any

from sac.experiment_metadata import write_experiment_metadata
from sac.run_hpt_trajectory_specialist_campaign import (
    ROOT,
    SIMULINK_DIR,
    TRACE_DIR,
    matlab_string,
    safe_token,
)


RESULTS = ROOT / "lab" / "results" / "hpt_family_actor_traces"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return [dict(row) for row in csv.DictReader(f)]


def row_float(row: dict[str, str], key: str, default: float) -> float:
    value = row.get(key, "")
    if value is None or str(value).strip() == "":
        return float(default)
    return float(value)


def row_bool(row: dict[str, str], key: str, default: bool = False) -> bool:
    value = row.get(key, "")
    if value is None or str(value).strip() == "":
        return bool(default)
    return str(value).strip().lower() in {"1", "1.0", "true", "yes", "y"}


def row_float_vector(row: dict[str, str], key: str) -> list[float]:
    value = row.get(key, "")
    if value is None:
        return []
    text = str(value).strip().strip("[]()")
    if not text:
        return []
    return [float(part) for part in text.replace(",", " ").split() if part]


def matlab_vector(values: list[float]) -> str:
    return "[" + " ".join(f"{value:.12g}" for value in values) + "]"


def run_command(
    cmd: list[str],
    *,
    cwd: Path,
    timeout_s: int,
    log_path: Path,
) -> subprocess.CompletedProcess[str]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=timeout_s,
    )
    log_path.write_text(
        "COMMAND:\n"
        + " ".join(cmd)
        + "\n\nSTDOUT:\n"
        + proc.stdout
        + "\n\nSTDERR:\n"
        + proc.stderr,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")
    return proc


def latest_new_file(directory: Path, pattern: str, before: set[Path]) -> Path:
    after = set(directory.glob(pattern))
    new_files = sorted(after - before, key=lambda p: p.stat().st_mtime)
    if new_files:
        return new_files[-1]
    files = sorted(after, key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"No files match {directory / pattern}")
    return files[-1]


def export_actor(model_path: Path, out_path: Path, run_dir: Path, timeout_s: int) -> None:
    if not model_path.exists():
        raise FileNotFoundError(model_path)
    run_command(
        [
            "py",
            "-3",
            "-m",
            "sac.export_hpt_sac_actor",
            "--model",
            str(model_path),
            "--out",
            str(out_path),
        ],
        cwd=ROOT,
        timeout_s=timeout_s,
        log_path=run_dir / f"export_{safe_token(model_path.stem)}.log",
    )


def select_rows(
    rows: list[dict[str, str]],
    *,
    case_ids: set[str],
    splits: set[str],
    max_cases: int | None,
) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    for row in rows:
        if case_ids and row.get("case_id", "") not in case_ids:
            continue
        if splits and row.get("split", "") not in splits:
            continue
        selected.append(row)
        if max_cases is not None and len(selected) >= max_cases:
            break
    return selected


def model_param_struct(row: dict[str, str]) -> str:
    chopper_threshold = row_float(row, "chopper_threshold", 850.0)
    rchop_scale = row_float(row, "rchop_scale", 1.0)
    base_rchop = (800.0**2) / 120e3
    items = [
        f"'hpt_chopper_threshold',{chopper_threshold:.12g}",
        f"'hpt_rchop',{base_rchop * rchop_scale:.12g}",
    ]
    if row_bool(row, "phase_override", False):
        fault_start = row_float(row, "fault_start_s", 0.035)
        duration_s = row_float(row, "duration_s", 0.060)
        fault_stop_margin = row_float(row, "fault_stop_margin_s", 0.125)
        fault_clear = fault_start + duration_s
        recovery_end = fault_clear + fault_stop_margin
        items.extend(
            [
                "'hpt_sac_phase_override_enable',1",
                f"'hpt_sac_phase_fault_start_s',{fault_start:.12g}",
                f"'hpt_sac_phase_fault_clear_s',{fault_clear:.12g}",
                f"'hpt_sac_phase_recovery_end_s',{recovery_end:.12g}",
            ]
        )
    return "struct(" + ",".join(items) + ")"


def collect_case_trace(
    row: dict[str, str],
    *,
    run_id: str,
    run_dir: Path,
    matlab_cmd: str,
    timeout_s: int,
    sample_stride: int,
    actor_select_mode: float,
    policy_mode: float,
) -> Path:
    case_id = row["case_id"]
    fault_phase_pu = row_float_vector(row, "fault_phase_pu")
    before = set(TRACE_DIR.glob("trajectory_trace_*.csv"))
    statements = [
        f"cd({matlab_string(str(SIMULINK_DIR).replace(chr(92), '/'))})",
        f"hpt_trace_topology={matlab_string(row['topology'])}",
        f"hpt_trace_fault_pu={float(row['fault_pu']):.12g}",
        f"hpt_trace_fault_duration={float(row['duration_s']):.12g}",
        f"hpt_trace_fault_start={row_float(row, 'fault_start_s', 0.035):.12g}",
        f"hpt_trace_fault_stop_margin={row_float(row, 'fault_stop_margin_s', 0.125):.12g}",
        f"hpt_trace_policy_mode={policy_mode:.12g}",
        f"hpt_trace_actor_select_mode={actor_select_mode:.12g}",
        f"hpt_trace_actor_filter_tau={row_float(row, 'actor_filter_tau', 0.0):.12g}",
        f"hpt_trace_sample_stride={sample_stride:d}",
        f"hpt_trace_model_params={model_param_struct(row)}",
        f"hpt_trace_run_label={matlab_string(run_id + '_' + safe_token(case_id))}",
    ]
    if len(fault_phase_pu) == 3:
        statements.append(f"hpt_trace_fault_phase_pu={matlab_vector(fault_phase_pu)}")
    statements.append("run(fullfile(pwd,'collectors','collect_hpt_v2_trajectory_trace.m'))")
    run_command(
        [matlab_cmd, "-batch", "; ".join(statements)],
        cwd=ROOT,
        timeout_s=timeout_s,
        log_path=run_dir / f"collect_{safe_token(case_id)}.log",
    )
    return latest_new_file(TRACE_DIR, "trajectory_trace_*.csv", before)


def aggregate_traces(trace_paths: list[Path], *, run_id: str, run_dir: Path, timeout_s: int) -> Path:
    cmd = [
        "py",
        "-3",
        "-m",
        "sac.datasets.build_hpt_trace_aggregate",
        "--run-id",
        run_id,
    ]
    for path in trace_paths:
        cmd.extend(["--trace", str(path)])
    run_command(
        cmd,
        cwd=ROOT,
        timeout_s=timeout_s,
        log_path=run_dir / "aggregate_traces.log",
    )
    return ROOT / "lab" / "results" / "hpt_trace_aggregates" / run_id / "aggregate_trace.csv"


def jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--split", action="append", default=[])
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument("--base-model", type=Path, default=None)
    parser.add_argument("--dynamic-model", type=Path, default=None)
    parser.add_argument("--actor-select-mode", type=float, default=4.0)
    parser.add_argument("--policy-mode", type=float, default=1.0)
    parser.add_argument("--sample-stride", type=int, default=100)
    parser.add_argument("--matlab-cmd", default="matlab")
    parser.add_argument("--timeout-s", type=int, default=900)
    args = parser.parse_args()

    rows = read_csv(args.manifest)
    selected = select_rows(
        rows,
        case_ids=set(args.case_id),
        splits=set(args.split),
        max_cases=args.max_cases,
    )
    if not selected:
        raise RuntimeError("No manifest rows selected")

    first = selected[0]
    base_model = args.base_model or Path(first.get("base_model_path", ""))
    dynamic_model = args.dynamic_model or Path(first.get("dynamic_model_path", ""))
    if not base_model.is_absolute():
        base_model = ROOT / base_model
    if not dynamic_model.is_absolute():
        dynamic_model = ROOT / dynamic_model

    run_dir = RESULTS / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    base_actor_path = SIMULINK_DIR / "hpt_sac_actor_weights.mat"
    dynamic_actor_path = SIMULINK_DIR / "hpt_sac_actor_weights_dynamic.mat"
    export_actor(base_model, base_actor_path, run_dir, args.timeout_s)
    export_actor(dynamic_model, dynamic_actor_path, run_dir, args.timeout_s)

    trace_paths: list[Path] = []
    case_records: list[dict[str, Any]] = []
    for row in selected:
        trace_path = collect_case_trace(
            row,
            run_id=args.run_id,
            run_dir=run_dir,
            matlab_cmd=args.matlab_cmd,
            timeout_s=args.timeout_s,
            sample_stride=args.sample_stride,
            actor_select_mode=args.actor_select_mode,
            policy_mode=args.policy_mode,
        )
        trace_paths.append(trace_path)
        case_records.append({"case_id": row["case_id"], "trace_csv": str(trace_path)})

    aggregate_csv = aggregate_traces(
        trace_paths,
        run_id=args.run_id,
        run_dir=run_dir,
        timeout_s=args.timeout_s,
    )
    summary = {
        "schema": "hpt-family-actor-trace-collection-v1",
        "run_id": args.run_id,
        "manifest": str(args.manifest),
        "case_count": len(selected),
        "base_model": str(base_model),
        "dynamic_model": str(dynamic_model),
        "actor_select_mode": args.actor_select_mode,
        "policy_mode": args.policy_mode,
        "sample_stride": args.sample_stride,
        "cases": case_records,
        "aggregate_csv": str(aggregate_csv),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_family_actor_trace_collection",
        config=jsonable(vars(args)),
        dataset_manifest=args.manifest,
        extra=summary,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
