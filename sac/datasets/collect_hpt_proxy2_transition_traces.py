"""Collect timestep-level switch traces for proxy-2.0 calibration.

The input is a switch-level boundary summary CSV.  This script treats that
table only as a case index, then re-runs the Simulink trajectory collector in
strong-dq mode to obtain per-control-step rows:

``(fault context, time, state, action) -> next state``.

The output stays under the selected expert workspace so proxy data, training
anchors, and later SAC artifacts can be traced to the same fault family.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np

from sac.campaigns.run_hpt_t2_balanced_lvrt_dq_seeded_boundary import (
    ACT_DIM,
    OBS_DIM,
    ROOT,
    BoundaryCase,
    build_anchor_from_trace,
    matlab_collect_dq_trace,
    run_logged,
    write_csv,
)
from sac.experiment_metadata import write_experiment_metadata
from sac.expert_workspace import EXPERT_BY_ID, expert_workspace


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "1.0", "true", "yes", "pass", "passed"}


def row_float(row: dict[str, str], *keys: str, default: float = float("nan")) -> float:
    for key in keys:
        value = row.get(key)
        if value is None or str(value).strip() == "":
            continue
        try:
            return float(value)
        except ValueError:
            continue
    return float(default)


def row_int(row: dict[str, str], *keys: str, default: int = 0) -> int:
    value = row_float(row, *keys, default=float(default))
    if not np.isfinite(value):
        return int(default)
    return int(round(value))


def normalize_phase(raw: str) -> str:
    text = str(raw or "").strip().lower()
    aliases = {"balanced": "abc", "": "abc"}
    return aliases.get(text, text)


def case_key(row: dict[str, str]) -> tuple[str, float, int]:
    phase = normalize_phase(row.get("fault_phase_key") or row.get("phase") or "abc")
    pu = row_float(row, "family_fault_pu", "fault_pu")
    duration_ms = row_int(row, "family_duration_ms", "duration_ms", default=60)
    return phase, round(pu, 6), duration_ms


def select_rows(
    rows: list[dict[str, str]],
    *,
    phases: set[str],
    depths: set[float],
    durations_ms: set[int],
    require_scenario_valid: bool,
    max_cases: int | None,
    include_pass_fail_pairs: bool,
) -> list[dict[str, str]]:
    dedup: dict[tuple[str, float, int], dict[str, str]] = {}
    for row in rows:
        if require_scenario_valid and "scenario_valid" in row and not truthy(row.get("scenario_valid")):
            continue
        phase, pu, duration = case_key(row)
        if phases and phase not in phases:
            continue
        if depths and not any(abs(pu - target) < 1e-9 for target in depths):
            continue
        if durations_ms and duration not in durations_ms:
            continue
        key = (phase, pu, duration)
        dedup.setdefault(key, row)

    selected = list(dedup.values())
    selected.sort(key=lambda item: case_key(item))

    if include_pass_fail_pairs and max_cases is not None:
        passed = [row for row in selected if truthy(row.get("l1_pass"))]
        failed = [row for row in selected if not truthy(row.get("l1_pass"))]
        mixed: list[dict[str, str]] = []
        for bucket in (passed, failed):
            take = max(1, max_cases // 2)
            mixed.extend(bucket[:take])
        selected = mixed[:max_cases]
    elif max_cases is not None:
        selected = selected[:max_cases]
    return selected


def boundary_case_from_row(row: dict[str, str], *, family_label: str) -> BoundaryCase:
    phase, pu, duration_ms = case_key(row)
    category = "HVRT" if pu > 1.0 else "LVRT"
    return BoundaryCase(
        fault_pu=float(pu),
        duration_s=float(duration_ms) / 1000.0,
        topology=str(row.get("topology") or "topology2"),
        category=category,
        phase_key=phase,
        family_label=family_label,
    )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def aggregate_traces(trace_paths: list[Path], *, run_id: str, out_root: Path, run_dir: Path) -> Path:
    cmd = [
        "py",
        "-3",
        "-m",
        "sac.datasets.build_hpt_trace_aggregate",
        "--run-id",
        run_id,
        "--out-dir",
        str(out_root),
    ]
    for path in trace_paths:
        cmd.extend(["--trace", str(path)])
    run_logged(cmd, cwd=ROOT, log_path=run_dir / "aggregate_traces.log")
    return out_root / run_id / "aggregate_trace.csv"


def build_family_anchor(trace_paths: list[Path], *, run_dir: Path, min_time_s: float) -> tuple[Path, dict[str, Any]]:
    obs_parts: list[np.ndarray] = []
    action_parts: list[np.ndarray] = []
    sources: list[dict[str, Any]] = []
    anchor_dir = run_dir / "anchors"
    anchor_dir.mkdir(parents=True, exist_ok=True)

    for trace in trace_paths:
        stem = trace.stem[:80]
        out_npz = anchor_dir / f"{stem}_anchor.npz"
        out_json = anchor_dir / f"{stem}_anchor.json"
        summary = build_anchor_from_trace(
            trace,
            out_npz,
            out_json,
            min_time_s=min_time_s,
            prefault_repeat=1,
            fault_repeat=8,
            recovery_repeat=6,
            tail_repeat=1,
        )
        data = np.load(out_npz)
        obs = np.asarray(data["observations"], dtype=np.float32)
        action = np.asarray(data["actions"], dtype=np.float32)
        if obs.ndim != 2 or obs.shape[1] != OBS_DIM:
            raise RuntimeError(f"Bad observation shape in {out_npz}: {obs.shape}")
        if action.ndim != 2 or action.shape[1] != ACT_DIM:
            raise RuntimeError(f"Bad action shape in {out_npz}: {action.shape}")
        obs_parts.append(obs)
        action_parts.append(action)
        sources.append(
            {
                "trace_csv": str(trace),
                "trace_sha256": sha256_file(trace),
                "anchor_npz": str(out_npz),
                "samples": int(obs.shape[0]),
                "zone_counts": summary.get("zone_counts"),
            }
        )

    observations = np.concatenate(obs_parts, axis=0)
    actions = np.concatenate(action_parts, axis=0)
    family_npz = run_dir / "proxy2_strong_dq_bc_anchor.npz"
    np.savez_compressed(family_npz, observations=observations, actions=actions)
    summary = {
        "schema": "hpt-proxy2-strong-dq-bc-anchor-v1",
        "dataset": str(family_npz),
        "samples": int(observations.shape[0]),
        "source_trace_count": len(trace_paths),
        "teacher_source": "strong_dq_policy_mode_0_switch_trace",
        "action_columns": ["m_reg_d", "m_reg_q", "m_energy_d", "m_energy_q"],
        "action_mean": [float(x) for x in actions.mean(axis=0)],
        "action_min": [float(x) for x in actions.min(axis=0)],
        "action_max": [float(x) for x in actions.max(axis=0)],
        "sources": sources,
    }
    (run_dir / "proxy2_strong_dq_bc_anchor.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    return family_npz, summary


def write_case_manifest(selected: list[dict[str, str]], out_csv: Path, family_label: str) -> None:
    rows: list[dict[str, Any]] = []
    for idx, row in enumerate(selected):
        phase, pu, duration_ms = case_key(row)
        if idx % 5 == 4:
            split = "holdout"
        elif idx % 5 == 3:
            split = "validation"
        else:
            split = "train"
        rows.append(
            {
                "case_id": f"{family_label}_{phase}_pu{int(round(pu * 1000)):04d}_d{duration_ms:03d}ms",
                "split": split,
                "topology": row.get("topology") or "topology2",
                "fault_phase_key": phase,
                "fault_pu": f"{pu:.6g}",
                "duration_ms": duration_ms,
                "duration_s": f"{duration_ms / 1000.0:.6g}",
                "source_summary_row_l1_pass": row.get("l1_pass", ""),
                "source_csv": row.get("source_csv", ""),
            }
        )
    write_csv(out_csv, rows)


def run_proxy2_pilot(aggregate_csv: Path, out_dir: Path, run_dir: Path) -> None:
    cmd = [
        "py",
        "-3",
        "-m",
        "sac.calibration.proxy2_transition_pilot",
        "--trace-csv",
        str(aggregate_csv),
        "--out-dir",
        str(out_dir),
    ]
    run_logged(cmd, cwd=ROOT, log_path=run_dir / "proxy2_transition_pilot.log")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-csv", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expert-id", default="topology2_single_phase_lvrt")
    parser.add_argument("--family-label", default="t2_single_phase_lvrt")
    parser.add_argument("--phases", default="a")
    parser.add_argument("--depths", default="")
    parser.add_argument("--durations-ms", default="")
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument("--fault-start-s", type=float, default=0.035)
    parser.add_argument("--anchor-min-time-s", type=float, default=0.010)
    parser.add_argument("--require-scenario-valid", action="store_true")
    parser.add_argument("--include-pass-fail-pairs", action="store_true")
    parser.add_argument("--skip-proxy-fit", action="store_true")
    args = parser.parse_args()

    try:
        spec = EXPERT_BY_ID[args.expert_id]
    except KeyError as exc:
        raise ValueError(f"Unknown expert_id: {args.expert_id!r}") from exc
    workspace = expert_workspace(
        spec.topology,
        spec.category,
        spec.representative_phase_key,
        create=True,
    )
    data_root = workspace.data / "proxy2_transition"
    run_dir = data_root / args.run_id
    trace_dir = run_dir / "raw_traces"
    aggregate_root = run_dir / "aggregates"
    proxy_dir = workspace.proxy / "proxy2_transition" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_dir.mkdir(parents=True, exist_ok=True)

    rows = read_csv(args.case_csv)
    phases = {normalize_phase(part) for part in args.phases.split(",") if part.strip()}
    depths = {float(part) for part in args.depths.split(",") if part.strip()}
    durations_ms = {int(float(part)) for part in args.durations_ms.split(",") if part.strip()}
    selected = select_rows(
        rows,
        phases=phases,
        depths=depths,
        durations_ms=durations_ms,
        require_scenario_valid=args.require_scenario_valid,
        max_cases=args.max_cases,
        include_pass_fail_pairs=args.include_pass_fail_pairs,
    )
    if not selected:
        raise RuntimeError("No cases selected for proxy2 trace collection.")

    manifest_csv = run_dir / "case_manifest.csv"
    write_case_manifest(selected, manifest_csv, args.family_label)

    trace_paths: list[Path] = []
    trace_records: list[dict[str, Any]] = []
    for idx, row in enumerate(selected, start=1):
        case = boundary_case_from_row(row, family_label=args.family_label)
        # Keep the MATLAB runner path short on Windows.  The scientific case
        # label is still recorded in the manifest and in the trace run label.
        case_dir = run_dir / "matlab" / f"case_{idx:03d}"
        case_dir.mkdir(parents=True, exist_ok=True)
        trace_csv = matlab_collect_dq_trace(
            case,
            case_dir,
            fault_start_s=args.fault_start_s,
            trace_dir=trace_dir,
        )
        trace_paths.append(trace_csv)
        trace_records.append(
            {
                "case": case.label,
                "trace_csv": str(trace_csv),
                "trace_sha256": sha256_file(trace_csv),
            }
        )

    aggregate_csv = aggregate_traces(
        trace_paths,
        run_id=args.run_id,
        out_root=aggregate_root,
        run_dir=run_dir,
    )
    anchor_npz, anchor_summary = build_family_anchor(
        trace_paths,
        run_dir=run_dir,
        min_time_s=args.anchor_min_time_s,
    )
    if not args.skip_proxy_fit and len(trace_paths) >= 2:
        run_proxy2_pilot(aggregate_csv, proxy_dir, run_dir)

    summary = {
        "schema": "hpt-proxy2-transition-trace-collection-v1",
        "run_id": args.run_id,
        "expert_id": args.expert_id,
        "family_label": args.family_label,
        "case_csv": str(args.case_csv),
        "case_csv_sha256": sha256_file(args.case_csv),
        "case_count": len(selected),
        "trace_count": len(trace_paths),
        "case_manifest": str(manifest_csv),
        "aggregate_csv": str(aggregate_csv),
        "bc_anchor_npz": str(anchor_npz),
        "bc_anchor_summary": anchor_summary,
        "proxy2_out_dir": str(proxy_dir) if not args.skip_proxy_fit else None,
        "traces": trace_records,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_proxy2_transition_trace_collection",
        config=jsonable(vars(args)),
        dataset_manifest=manifest_csv,
        extra=summary,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
