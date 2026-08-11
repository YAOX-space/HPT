"""Blend two HPT action trajectories into a Simulink MAT trajectory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from sac.datasets.build_hpt_action_trajectory import write_csv, write_mat


def load_csv(path: Path) -> tuple[np.ndarray, np.ndarray]:
    data = np.genfromtxt(path, delimiter=",", names=True, dtype=float)
    t = np.asarray(data["t"], dtype=float).reshape(-1, 1)
    action = np.column_stack(
        [
            np.asarray(data["m_reg_d"], dtype=float),
            np.asarray(data["m_reg_q"], dtype=float),
            np.asarray(data["m_energy_d"], dtype=float),
            np.asarray(data["m_energy_q"], dtype=float),
        ]
    )
    return t, action


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-csv", type=Path, required=True)
    parser.add_argument("--target-csv", type=Path, required=True)
    parser.add_argument("--alpha", type=float, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--write-csv", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    t_base, base = load_csv(args.base_csv)
    t_target, target = load_csv(args.target_csv)
    if t_base.shape != t_target.shape or base.shape != target.shape:
        raise ValueError("Trajectories must have the same number of samples")
    if not np.allclose(t_base, t_target, atol=1e-9, rtol=0.0):
        raise ValueError("Trajectory time bases do not match")
    alpha = float(args.alpha)
    action = (1.0 - alpha) * base + alpha * target
    action = np.clip(action, [-0.8, -0.8, -0.95, -0.95], [0.8, 0.8, 0.95, 0.95])
    write_mat(args.out, t_base, action)
    csv_path = None
    if args.write_csv:
        csv_path = args.out.with_suffix(".csv")
        write_csv(csv_path, t_base, action)
    manifest = {
        "schema": "hpt-blended-action-trajectory-v1",
        "base_csv": str(args.base_csv),
        "target_csv": str(args.target_csv),
        "alpha": alpha,
        "mat_file": str(args.out),
        "csv_file": str(csv_path) if csv_path else None,
        "n_points": int(action.shape[0]),
        "action_min": action.min(axis=0).tolist(),
        "action_max": action.max(axis=0).tolist(),
    }
    args.out.with_suffix(".json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
