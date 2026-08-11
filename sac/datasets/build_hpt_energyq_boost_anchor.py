"""Build an energy-q-boosted anchor dataset from HPT family traces.

This utility is a targeted repair for topology2 deep-LVRT family training.
The strong-dq trace provides the regulating-bridge state/action trajectory, but
its energy bridge commands are zero.  A switch-level sign sweep showed that a
positive ``m_energy_q`` command can restore DC-link survival in representative
deep LVRT cells, so this builder creates an auditable anchor where only the
fault/recovery energy-q target is edited.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import math
from pathlib import Path
from typing import Any

import numpy as np


OBS_DIM = 24
ACT_DIM = 4
ACTION_LOW = np.asarray([-0.8, -0.8, -0.95, -0.95], dtype=np.float32)
ACTION_HIGH = np.asarray([0.8, 0.8, 0.95, 0.95], dtype=np.float32)


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def repeat_for_zone(
    zone: str,
    *,
    prefault_repeat: int,
    fault_repeat: int,
    recovery_repeat: int,
    tail_repeat: int,
) -> int:
    return max(
        1,
        {
            "prefault": prefault_repeat,
            "fault": fault_repeat,
            "recovery": recovery_repeat,
            "tail": tail_repeat,
        }.get(zone, 1),
    )


def edited_action(row: dict[str, str], args: argparse.Namespace) -> np.ndarray:
    action = np.asarray(
        [to_float(row.get(f"action_{idx:02d}"), 0.0) for idx in range(1, ACT_DIM + 1)],
        dtype=np.float32,
    )
    zone = str(row.get("window_zone") or "").strip().lower()
    if zone == "fault":
        action[0] = action[0] * float(args.fault_reg_d_scale) + float(args.fault_reg_d_offset)
        action[1] = 0.0 if args.reg_q_mode == "zero" else action[1] * float(args.fault_reg_q_scale)
        action[2] = float(args.fault_energy_d)
        action[3] = float(args.fault_energy_q)
    elif zone == "recovery":
        action[0] = (
            action[0] * float(args.recovery_reg_d_scale)
            + float(args.recovery_reg_d_offset)
        )
        action[1] = (
            0.0 if args.reg_q_mode == "zero" else action[1] * float(args.recovery_reg_q_scale)
        )
        action[2] = float(args.recovery_energy_d)
        action[3] = float(args.recovery_energy_q)
    else:
        if math.isfinite(float(args.outside_reg_d)):
            action[0] = float(args.outside_reg_d)
        if math.isfinite(float(args.outside_reg_q)):
            action[1] = float(args.outside_reg_q)
        if math.isfinite(float(args.outside_energy_d)):
            action[2] = float(args.outside_energy_d)
        elif args.zero_energy_outside_fault:
            action[2] = 0.0
        if math.isfinite(float(args.outside_energy_q)):
            action[3] = float(args.outside_energy_q)
        elif args.zero_energy_outside_fault:
            action[3] = 0.0

    if np.isfinite(float(args.reg_d_clip_abs)) and float(args.reg_d_clip_abs) > 0:
        clip = float(args.reg_d_clip_abs)
        action[0] = float(np.clip(action[0], -clip, clip))
    if np.isfinite(float(args.reg_q_clip_abs)) and float(args.reg_q_clip_abs) > 0:
        clip = float(args.reg_q_clip_abs)
        action[1] = float(np.clip(action[1], -clip, clip))
    return np.clip(action, ACTION_LOW, ACTION_HIGH)


def build_from_trace(
    trace_csv: Path,
    *,
    args: argparse.Namespace,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    obs_rows: list[np.ndarray] = []
    action_rows: list[np.ndarray] = []
    zone_counts: dict[str, int] = {}
    weighted_zone_counts: dict[str, int] = {}
    with trace_csv.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"Trace CSV has no header: {trace_csv}")
        missing = [
            name
            for name in [*(f"obs_{idx:02d}" for idx in range(1, OBS_DIM + 1)),
                         *(f"action_{idx:02d}" for idx in range(1, ACT_DIM + 1)),
                         "window_zone", "t"]
            if name not in reader.fieldnames
        ]
        if missing:
            raise KeyError(f"{trace_csv} is missing columns: {missing[:8]}")
        for row in reader:
            row_t = to_float(row.get("t"), 0.0)
            if row_t < float(args.min_time_s):
                continue
            zone = str(row.get("window_zone") or "").strip().lower() or "unknown"
            obs = np.asarray(
                [to_float(row.get(f"obs_{idx:02d}"), 0.0) for idx in range(1, OBS_DIM + 1)],
                dtype=np.float32,
            )
            action = edited_action(row, args)
            repeat = repeat_for_zone(
                zone,
                prefault_repeat=args.prefault_repeat,
                fault_repeat=args.fault_repeat,
                recovery_repeat=args.recovery_repeat,
                tail_repeat=args.tail_repeat,
            )
            zone_counts[zone] = zone_counts.get(zone, 0) + 1
            weighted_zone_counts[zone] = weighted_zone_counts.get(zone, 0) + repeat
            for _ in range(repeat):
                obs_rows.append(obs)
                action_rows.append(action)
    observations = np.asarray(obs_rows, dtype=np.float32)
    actions = np.asarray(action_rows, dtype=np.float32)
    if observations.ndim != 2 or observations.shape[1] != OBS_DIM:
        raise RuntimeError(f"Bad observation shape in {trace_csv}: {observations.shape}")
    if actions.ndim != 2 or actions.shape[1] != ACT_DIM:
        raise RuntimeError(f"Bad action shape in {trace_csv}: {actions.shape}")
    summary = {
        "trace_csv": str(trace_csv),
        "trace_sha256": sha256_file(trace_csv),
        "samples": int(observations.shape[0]),
        "source_rows": int(sum(zone_counts.values())),
        "zone_counts": zone_counts,
        "weighted_zone_counts": weighted_zone_counts,
        "action_mean": actions.mean(axis=0).astype(float).tolist(),
        "action_min": actions.min(axis=0).astype(float).tolist(),
        "action_max": actions.max(axis=0).astype(float).tolist(),
    }
    return observations, actions, summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-family-anchor-json", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--min-time-s", type=float, default=0.020)
    parser.add_argument("--prefault-repeat", type=int, default=2)
    parser.add_argument("--fault-repeat", type=int, default=16)
    parser.add_argument("--recovery-repeat", type=int, default=10)
    parser.add_argument("--tail-repeat", type=int, default=1)
    parser.add_argument("--fault-reg-d-scale", type=float, default=0.65)
    parser.add_argument("--fault-reg-d-offset", type=float, default=0.0)
    parser.add_argument("--recovery-reg-d-scale", type=float, default=0.55)
    parser.add_argument("--recovery-reg-d-offset", type=float, default=0.0)
    parser.add_argument("--reg-q-mode", choices=["zero", "scale"], default="zero")
    parser.add_argument("--fault-reg-q-scale", type=float, default=0.5)
    parser.add_argument("--recovery-reg-q-scale", type=float, default=0.3)
    parser.add_argument("--reg-d-clip-abs", type=float, default=0.12)
    parser.add_argument("--reg-q-clip-abs", type=float, default=0.08)
    parser.add_argument("--fault-energy-d", type=float, default=0.0)
    parser.add_argument("--fault-energy-q", type=float, default=0.60)
    parser.add_argument("--recovery-energy-d", type=float, default=0.0)
    parser.add_argument("--recovery-energy-q", type=float, default=0.35)
    parser.add_argument("--outside-reg-d", type=float, default=float("nan"))
    parser.add_argument("--outside-reg-q", type=float, default=float("nan"))
    parser.add_argument("--outside-energy-d", type=float, default=float("nan"))
    parser.add_argument("--outside-energy-q", type=float, default=float("nan"))
    parser.add_argument("--zero-energy-outside-fault", action="store_true", default=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_json = args.base_family_anchor_json.resolve()
    if not base_json.exists():
        raise FileNotFoundError(base_json)
    base = json.loads(base_json.read_text(encoding="utf-8"))
    per_case = base.get("per_case") or []
    if not per_case:
        raise ValueError(f"No per_case trace metadata found in {base_json}")

    obs_parts: list[np.ndarray] = []
    action_parts: list[np.ndarray] = []
    source_summaries: list[dict[str, Any]] = []
    for item in per_case:
        trace_csv = Path(str(item.get("trace_csv", ""))).resolve()
        if not trace_csv.exists():
            raise FileNotFoundError(trace_csv)
        obs, actions, summary = build_from_trace(trace_csv, args=args)
        summary["case"] = item.get("case", {})
        obs_parts.append(obs)
        action_parts.append(actions)
        source_summaries.append(summary)

    observations = np.concatenate(obs_parts, axis=0)
    actions = np.concatenate(action_parts, axis=0)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.out,
        observations=observations.astype(np.float32),
        actions=actions.astype(np.float32),
    )
    metadata = {
        "schema": "hpt-energyq-boost-family-anchor-v1",
        "git_head": git_head(),
        "base_family_anchor_json": str(base_json),
        "base_family_anchor_sha256": sha256_file(base_json),
        "dataset": str(args.out.resolve()),
        "samples": int(observations.shape[0]),
        "source_count": len(source_summaries),
        "source_summaries": source_summaries,
        "action_mean": actions.mean(axis=0).astype(float).tolist(),
        "action_min": actions.min(axis=0).astype(float).tolist(),
        "action_max": actions.max(axis=0).astype(float).tolist(),
        "config": {
            "min_time_s": float(args.min_time_s),
            "prefault_repeat": int(args.prefault_repeat),
            "fault_repeat": int(args.fault_repeat),
            "recovery_repeat": int(args.recovery_repeat),
            "tail_repeat": int(args.tail_repeat),
            "fault_reg_d_scale": float(args.fault_reg_d_scale),
            "fault_reg_d_offset": float(args.fault_reg_d_offset),
            "recovery_reg_d_scale": float(args.recovery_reg_d_scale),
            "recovery_reg_d_offset": float(args.recovery_reg_d_offset),
            "reg_q_mode": str(args.reg_q_mode),
            "fault_reg_q_scale": float(args.fault_reg_q_scale),
            "recovery_reg_q_scale": float(args.recovery_reg_q_scale),
            "reg_d_clip_abs": float(args.reg_d_clip_abs),
            "reg_q_clip_abs": float(args.reg_q_clip_abs),
            "fault_energy_d": float(args.fault_energy_d),
            "fault_energy_q": float(args.fault_energy_q),
            "recovery_energy_d": float(args.recovery_energy_d),
            "recovery_energy_q": float(args.recovery_energy_q),
            "outside_reg_d": float(args.outside_reg_d),
            "outside_reg_q": float(args.outside_reg_q),
            "outside_energy_d": float(args.outside_energy_d),
            "outside_energy_q": float(args.outside_energy_q),
            "zero_energy_outside_fault": bool(args.zero_energy_outside_fault),
        },
    }
    args.out.with_suffix(".json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2), flush=True)


if __name__ == "__main__":
    main()
