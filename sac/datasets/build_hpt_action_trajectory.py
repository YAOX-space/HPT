"""Build 4-D HPT action trajectory files for Simulink switch-level validation.

The generated MAT file is consumed by ``HPTSACController`` when
``hpt_sac_policy_mode = -2``:

    hpt_traj_t        Nx1 seconds
    hpt_traj_action   Nx4 [m_reg_d, m_reg_q, m_energy_d, m_energy_q]

This is the bridge from fixed-action experiments to true time-varying
trajectory control.  The first research gate is intentionally simple:
constant, step, ramp, two-stage, and fault/recovery trajectories around
already validated fixed-action setpoints.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from ..experiment_metadata import write_experiment_metadata


@dataclass(frozen=True)
class TrajectorySpec:
    preset: str
    dt: float
    stop_time: float
    base_action: tuple[float, float, float, float]
    start_action: tuple[float, float, float, float]
    action: tuple[float, float, float, float]
    step_time: float
    ramp_start: float
    ramp_end: float
    down_start: float | None = None
    down_end: float | None = None


def _as_action(values: list[float] | tuple[float, ...]) -> np.ndarray:
    arr = np.asarray(values, dtype=float).reshape(-1)
    if arr.size != 4:
        raise ValueError("Action must have 4 values: m_reg_d m_reg_q m_energy_d m_energy_q")
    return arr


def make_trajectory(spec: TrajectorySpec) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(t, action)`` for the requested trajectory preset."""

    if spec.dt <= 0:
        raise ValueError("dt must be positive")
    if spec.stop_time <= 0:
        raise ValueError("stop_time must be positive")

    n = int(np.floor(spec.stop_time / spec.dt)) + 1
    t = np.arange(n, dtype=float) * spec.dt
    base = _as_action(spec.base_action)
    start = _as_action(spec.start_action)
    target = _as_action(spec.action)
    preset = spec.preset.lower()

    if preset == "zero":
        action = np.zeros((n, 4), dtype=float)
    elif preset == "constant":
        action = np.tile(target, (n, 1))
    elif preset == "step":
        action = np.tile(start, (n, 1))
        action[t >= spec.step_time, :] = target
    elif preset == "ramp":
        if spec.ramp_end <= spec.ramp_start:
            raise ValueError("ramp_end must be greater than ramp_start")
        frac = np.clip((t - spec.ramp_start) / (spec.ramp_end - spec.ramp_start), 0.0, 1.0)
        action = start[None, :] + frac[:, None] * (target - start)[None, :]
    elif preset == "two_stage":
        if not (spec.ramp_start < spec.step_time < spec.ramp_end):
            raise ValueError("two_stage requires ramp_start < step_time < ramp_end")
        first = np.clip((t - spec.ramp_start) / (spec.step_time - spec.ramp_start), 0.0, 1.0)
        second = np.clip((t - spec.step_time) / (spec.ramp_end - spec.step_time), 0.0, 1.0)
        action = base[None, :] + first[:, None] * (start - base)[None, :]
        action = action + second[:, None] * (target - start)[None, :]
    elif preset == "two_stage_window":
        if not (spec.ramp_start < spec.step_time < spec.ramp_end):
            raise ValueError("two_stage_window requires ramp_start < step_time < ramp_end")
        down_start = spec.down_start if spec.down_start is not None else spec.stop_time
        down_end = spec.down_end if spec.down_end is not None else spec.stop_time
        if down_end < down_start:
            raise ValueError("two_stage_window requires down_end >= down_start")
        first = np.clip((t - spec.ramp_start) / (spec.step_time - spec.ramp_start), 0.0, 1.0)
        second = np.clip((t - spec.step_time) / (spec.ramp_end - spec.step_time), 0.0, 1.0)
        staged = base[None, :] + first[:, None] * (start - base)[None, :]
        staged = staged + second[:, None] * (target - start)[None, :]
        if down_end == down_start:
            down = (t < down_start).astype(float)
        else:
            down = 1.0 - np.clip((t - down_start) / (down_end - down_start), 0.0, 1.0)
        action = base[None, :] + down[:, None] * (staged - base[None, :])
    elif preset == "fault_window":
        # Hold base before/after the fault support window, ramp into target
        # during the transition, then ramp back down after fault clearing.
        action = np.tile(base, (n, 1))
        up = np.clip((t - spec.ramp_start) / max(spec.step_time - spec.ramp_start, spec.dt), 0.0, 1.0)
        down = 1.0 - np.clip((t - spec.ramp_end) / max(spec.stop_time - spec.ramp_end, spec.dt), 0.0, 1.0)
        frac = np.minimum(up, down)
        action = base[None, :] + frac[:, None] * (target - base)[None, :]
    elif preset == "fault_recovery":
        # Topology2 often needs a high regulating command during the fault,
        # then a lower recovery command after fault clearing.  This preset
        # makes that teacher shape explicit and reproducible:
        #   base -> start_action from ramp_start to step_time,
        #   hold start_action until ramp_end,
        #   start_action -> action from ramp_end to down_start,
        #   hold action afterwards.
        if spec.step_time <= spec.ramp_start:
            raise ValueError("fault_recovery requires step_time > ramp_start")
        if spec.down_start is None:
            raise ValueError("fault_recovery requires down_start as recovery-ramp end")
        if spec.down_start <= spec.ramp_end:
            raise ValueError("fault_recovery requires down_start > ramp_end")
        up = np.clip((t - spec.ramp_start) / (spec.step_time - spec.ramp_start), 0.0, 1.0)
        rec = np.clip((t - spec.ramp_end) / (spec.down_start - spec.ramp_end), 0.0, 1.0)
        action = base[None, :] + up[:, None] * (start - base)[None, :]
        action = action + rec[:, None] * (target - start)[None, :]
    else:
        raise ValueError(f"Unknown trajectory preset: {spec.preset}")

    return t.reshape(-1, 1), np.clip(action, [-0.8, -0.8, -0.95, -0.95], [0.8, 0.8, 0.95, 0.95])


def write_mat(path: Path, t: np.ndarray, action: np.ndarray) -> None:
    """Write trajectory MAT file using scipy."""

    try:
        from scipy.io import savemat
    except Exception as exc:  # pragma: no cover - environment guard
        raise RuntimeError("scipy is required to write MATLAB trajectory files") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    savemat(
        path,
        {
            "hpt_traj_t": np.asarray(t, dtype=float),
            "hpt_traj_action": np.asarray(action, dtype=float),
        },
        do_compression=True,
    )


def write_csv(path: Path, t: np.ndarray, action: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "t,m_reg_d,m_reg_q,m_energy_d,m_energy_q\n"
    rows = [
        f"{float(ti):.9g},{a[0]:.9g},{a[1]:.9g},{a[2]:.9g},{a[3]:.9g}"
        for ti, a in zip(t.reshape(-1), action)
    ]
    path.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--preset",
        default="constant",
        choices=[
            "zero",
            "constant",
            "step",
            "ramp",
            "two_stage",
            "two_stage_window",
            "fault_window",
            "fault_recovery",
        ],
    )
    parser.add_argument("--dt", type=float, default=2e-3)
    parser.add_argument("--stop-time", type=float, default=0.24)
    parser.add_argument("--base-action", type=float, nargs=4, default=[0.0, 0.0, 0.0, 0.0])
    parser.add_argument("--start-action", type=float, nargs=4, default=[0.0, 0.0, 0.0, 0.0])
    parser.add_argument("--action", type=float, nargs=4, default=[0.172, 0.0, 0.022, 0.002])
    parser.add_argument("--step-time", type=float, default=0.035)
    parser.add_argument("--ramp-start", type=float, default=0.035)
    parser.add_argument("--ramp-end", type=float, default=0.055)
    parser.add_argument("--down-start", type=float, default=None)
    parser.add_argument("--down-end", type=float, default=None)
    parser.add_argument("--write-csv", action="store_true")
    parser.add_argument("--metadata-dir", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    spec = TrajectorySpec(
        preset=args.preset,
        dt=args.dt,
        stop_time=args.stop_time,
        base_action=tuple(args.base_action),
        start_action=tuple(args.start_action),
        action=tuple(args.action),
        step_time=args.step_time,
        ramp_start=args.ramp_start,
        ramp_end=args.ramp_end,
        down_start=args.down_start,
        down_end=args.down_end,
    )
    t, action = make_trajectory(spec)
    write_mat(args.out, t, action)
    if args.write_csv:
        write_csv(args.out.with_suffix(".csv"), t, action)
    manifest = {
        "schema": "hpt-action-trajectory-v1",
        "mat_file": str(args.out),
        "csv_file": str(args.out.with_suffix(".csv")) if args.write_csv else None,
        "n_points": int(t.shape[0]),
        "spec": asdict(spec),
        "action_min": action.min(axis=0).tolist(),
        "action_max": action.max(axis=0).tolist(),
    }
    manifest_path = args.out.with_suffix(".json")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if args.metadata_dir is not None:
        write_experiment_metadata(
            args.metadata_dir,
            experiment_name="hpt_action_trajectory",
            config=manifest,
            dataset_manifest=manifest_path,
        )
    print(json.dumps(manifest, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
