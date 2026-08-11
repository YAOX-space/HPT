"""Build an HPT action trajectory MAT file from a collected switch trace.

The collector can record both the requested controller command and the
effective bridge response reconstructed from ``Mref6_cmd`` / energy current.
For conventional-trace teachers we normally use ``teacher_action_*`` so the
trajectory follows the switch-level response that actually produced the
baseline score.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import numpy as np

from .build_hpt_action_trajectory import write_csv, write_mat
from ..experiment_metadata import write_experiment_metadata


ACTION_LIMIT_LOW = np.asarray([-0.8, -0.8, -0.95, -0.95], dtype=float)
ACTION_LIMIT_HIGH = np.asarray([0.8, 0.8, 0.95, 0.95], dtype=float)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return [dict(row) for row in csv.DictReader(f)]


def to_float(value: Any, default: float = float("nan")) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def action_columns(prefix: str) -> list[str]:
    return [f"{prefix}_action_{idx:02d}" for idx in range(1, 5)]


def source_columns(source: str) -> list[str]:
    if source == "teacher":
        return action_columns("teacher")
    if source == "meas":
        return action_columns("meas")
    if source == "cmd":
        return action_columns("cmd")
    if source == "actor":
        return action_columns("actor")
    if source == "raw":
        return [f"action_{idx:02d}" for idx in range(1, 5)]
    raise ValueError(f"Unknown action source: {source}")


def apply_window_edits(
    t: np.ndarray,
    action: np.ndarray,
    *,
    fault_start: float,
    fault_clear: float,
    recovery_end: float,
    fault_reg_scale: float,
    fault_reg_offset: float,
    recovery_reg_scale: float,
    recovery_reg_offset: float,
    fault_energy_scale: float,
    recovery_energy_scale: float,
) -> np.ndarray:
    out = np.asarray(action, dtype=float).copy()
    fault = (t >= fault_start) & (t < fault_clear)
    recovery = (t >= fault_clear) & (t <= recovery_end)

    out[fault, 0] = fault_reg_scale * out[fault, 0] + fault_reg_offset
    out[recovery, 0] = recovery_reg_scale * out[recovery, 0] + recovery_reg_offset
    out[fault, 1] = fault_reg_scale * out[fault, 1]
    out[recovery, 1] = recovery_reg_scale * out[recovery, 1]
    out[fault, 2:4] = fault_energy_scale * out[fault, 2:4]
    out[recovery, 2:4] = recovery_energy_scale * out[recovery, 2:4]
    return np.clip(out, ACTION_LIMIT_LOW, ACTION_LIMIT_HIGH)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-csv", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--source",
        default="teacher",
        choices=["teacher", "meas", "cmd", "actor", "raw"],
        help="Which action columns to turn into hpt_traj_action.",
    )
    parser.add_argument("--fault-start", type=float, default=0.035)
    parser.add_argument("--fault-clear", type=float, default=0.095)
    parser.add_argument("--recovery-end", type=float, default=0.220)
    parser.add_argument("--fault-reg-scale", type=float, default=1.0)
    parser.add_argument("--fault-reg-offset", type=float, default=0.0)
    parser.add_argument("--recovery-reg-scale", type=float, default=1.0)
    parser.add_argument("--recovery-reg-offset", type=float, default=0.0)
    parser.add_argument("--fault-energy-scale", type=float, default=1.0)
    parser.add_argument("--recovery-energy-scale", type=float, default=1.0)
    parser.add_argument("--write-csv", action="store_true")
    parser.add_argument("--metadata-dir", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = read_rows(args.trace_csv)
    if not rows:
        raise ValueError(f"Trace CSV is empty: {args.trace_csv}")

    cols = source_columns(args.source)
    missing = [col for col in ["t", *cols] if col not in rows[0]]
    if missing:
        raise KeyError(f"Missing required trace columns: {missing}")

    t = np.asarray([to_float(row["t"]) for row in rows], dtype=float)
    action = np.asarray(
        [[to_float(row[col], 0.0) for col in cols] for row in rows],
        dtype=float,
    )
    order = np.argsort(t)
    t = t[order]
    action = action[order, :]
    action = apply_window_edits(
        t,
        action,
        fault_start=args.fault_start,
        fault_clear=args.fault_clear,
        recovery_end=args.recovery_end,
        fault_reg_scale=args.fault_reg_scale,
        fault_reg_offset=args.fault_reg_offset,
        recovery_reg_scale=args.recovery_reg_scale,
        recovery_reg_offset=args.recovery_reg_offset,
        fault_energy_scale=args.fault_energy_scale,
        recovery_energy_scale=args.recovery_energy_scale,
    )

    write_mat(args.out, t.reshape(-1, 1), action)
    if args.write_csv:
        write_csv(args.out.with_suffix(".csv"), t.reshape(-1, 1), action)

    manifest = {
        "schema": "hpt-trajectory-from-trace-v1",
        "trace_csv": str(args.trace_csv),
        "mat_file": str(args.out),
        "csv_file": str(args.out.with_suffix(".csv")) if args.write_csv else None,
        "source": args.source,
        "n_points": int(t.size),
        "fault_start": args.fault_start,
        "fault_clear": args.fault_clear,
        "recovery_end": args.recovery_end,
        "fault_reg_scale": args.fault_reg_scale,
        "fault_reg_offset": args.fault_reg_offset,
        "recovery_reg_scale": args.recovery_reg_scale,
        "recovery_reg_offset": args.recovery_reg_offset,
        "fault_energy_scale": args.fault_energy_scale,
        "recovery_energy_scale": args.recovery_energy_scale,
        "action_min": action.min(axis=0).tolist(),
        "action_max": action.max(axis=0).tolist(),
        "action_mean": action.mean(axis=0).tolist(),
    }
    manifest_path = args.out.with_suffix(".json")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if args.metadata_dir is not None:
        write_experiment_metadata(
            args.metadata_dir,
            experiment_name="hpt_trajectory_from_trace",
            config=manifest,
            dataset_manifest=manifest_path,
        )
    print(json.dumps(manifest, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
