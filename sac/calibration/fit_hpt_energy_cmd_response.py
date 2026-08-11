"""Fit energy-branch command-to-measured-response maps from FRT matrix rows.

The direct SAC action is a command:

    [m_reg_d, m_reg_q, m_energy_d, m_energy_q]

The switch-level plant may respond with a different effective energy d/q
component because of bridge polarity, current-loop saturation, DC-link dynamics,
and transformer direction.  This diagnostic fits

    meas_energy_[d/q] = f(grid_pu, cmd_m_energy_d, cmd_m_energy_q)

per topology/category/mode group so the proxy can be corrected before SAC uses
energy actions as if command and response were identical.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from sac.experiment_metadata import sha256_file, write_experiment_metadata


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()
DEFAULT_MATRIX_DIR = ROOT / "lab" / "results" / "hpt_v2_frt_calibration_matrix"
DEFAULT_OUT_DIR = ROOT / "lab" / "results" / "hpt_v2_energy_cmd_response"


def latest_csv(directory: Path, pattern: str) -> Path:
    files = sorted(Path(directory).glob(pattern), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"No files matching {pattern} in {directory}")
    return files[-1]


def read_csv(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            row: dict[str, Any] = {}
            for key, value in raw.items():
                if value in ("", None):
                    row[key] = value
                    continue
                try:
                    row[key] = float(value)
                except ValueError:
                    row[key] = value
            rows.append(row)
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def f(row: dict[str, Any], key: str, default: float = float("nan")) -> float:
    value = row.get(key, default)
    if value in ("", None):
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def s(row: dict[str, Any], key: str, default: str = "") -> str:
    value = row.get(key, default)
    return str(default if value is None else value)


def finite(value: float) -> bool:
    return bool(math.isfinite(float(value)))


def command_response(row: dict[str, Any]) -> tuple[float, float, float, float]:
    cmd_d = f(row, "cmd_m_energy_d_mean", f(row, "raw_m_energy_d", f(row, "energy_d_mean")))
    cmd_q = f(row, "cmd_m_energy_q_mean", f(row, "raw_m_energy_q", f(row, "energy_q_mean")))
    meas_d = f(row, "meas_energy_d_mean", f(row, "energy_d_mean"))
    meas_q = f(row, "meas_energy_q_mean", f(row, "energy_q_mean"))
    return cmd_d, cmd_q, meas_d, meas_q


def fit_group(rows: list[dict[str, Any]], key: tuple[str, str, str]) -> dict[str, Any]:
    samples: list[tuple[float, float, float, float, float]] = []
    for row in rows:
        cmd_d, cmd_q, meas_d, meas_q = command_response(row)
        grid = f(row, "grid_pu", f(row, "fault_pu", 1.0))
        if all(finite(x) for x in (grid, cmd_d, cmd_q, meas_d, meas_q)):
            samples.append((grid, cmd_d, cmd_q, meas_d, meas_q))

    topology, category, mode = key
    out: dict[str, Any] = {
        "topology": topology,
        "category": category,
        "mode": mode,
        "n": len(samples),
    }
    if len(samples) < 4:
        out.update(
            {
                "status": "too_few_samples",
                "rmse_d": float("nan"),
                "rmse_q": float("nan"),
                "sign_mismatch_d_fraction": float("nan"),
                "mean_abs_cmd_d": float("nan"),
                "mean_abs_meas_d": float("nan"),
            }
        )
        return out

    data = np.asarray(samples, dtype=float)
    grid = data[:, 0]
    cmd_d = data[:, 1]
    cmd_q = data[:, 2]
    meas_d = data[:, 3]
    meas_q = data[:, 4]
    X = np.column_stack([np.ones_like(grid), grid - 1.0, cmd_d, cmd_q])
    coef_d, *_ = np.linalg.lstsq(X, meas_d, rcond=None)
    coef_q, *_ = np.linalg.lstsq(X, meas_q, rcond=None)
    pred_d = X @ coef_d
    pred_q = X @ coef_q
    residual_d = meas_d - pred_d
    residual_q = meas_q - pred_q
    sign_mask = np.abs(cmd_d) > 1e-6
    if np.any(sign_mask):
        sign_mismatch = np.mean(np.sign(cmd_d[sign_mask]) != np.sign(meas_d[sign_mask]))
    else:
        sign_mismatch = float("nan")
    out.update(
        {
            "status": "fit",
            "coef_d_intercept": float(coef_d[0]),
            "coef_d_grid": float(coef_d[1]),
            "coef_d_cmd_d": float(coef_d[2]),
            "coef_d_cmd_q": float(coef_d[3]),
            "coef_q_intercept": float(coef_q[0]),
            "coef_q_grid": float(coef_q[1]),
            "coef_q_cmd_d": float(coef_q[2]),
            "coef_q_cmd_q": float(coef_q[3]),
            "rmse_d": float(np.sqrt(np.mean(residual_d**2))),
            "rmse_q": float(np.sqrt(np.mean(residual_q**2))),
            "mae_d": float(np.mean(np.abs(residual_d))),
            "mae_q": float(np.mean(np.abs(residual_q))),
            "sign_mismatch_d_fraction": float(sign_mismatch),
            "mean_abs_cmd_d": float(np.mean(np.abs(cmd_d))),
            "mean_abs_meas_d": float(np.mean(np.abs(meas_d))),
            "mean_abs_cmd_q": float(np.mean(np.abs(cmd_q))),
            "mean_abs_meas_q": float(np.mean(np.abs(meas_q))),
        }
    )
    return out


def build_report(path: Path, matrix_csv: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# HPT Energy Command-Response Fit",
        "",
        f"- Updated: `{datetime.now().isoformat(timespec='seconds')}`",
        f"- Matrix CSV: `{matrix_csv}`",
        f"- Groups: `{len(rows)}`",
        "",
        "| Topology | Category | Mode | N | d slope | d RMSE | d sign mismatch | |cmd d| | |meas d| |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| "
            f"{row['topology']} | {row['category']} | {row['mode']} | {row['n']} | "
            f"{row.get('coef_d_cmd_d', float('nan')):.4g} | "
            f"{row.get('rmse_d', float('nan')):.4g} | "
            f"{row.get('sign_mismatch_d_fraction', float('nan')):.3g} | "
            f"{row.get('mean_abs_cmd_d', float('nan')):.4g} | "
            f"{row.get('mean_abs_meas_d', float('nan')):.4g} |"
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix-csv", type=Path, default=None)
    parser.add_argument("--matrix-dir", type=Path, default=DEFAULT_MATRIX_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    matrix_csv = args.matrix_csv or latest_csv(args.matrix_dir, "frt_calibration_matrix_*.csv")
    rows = read_csv(matrix_csv)
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        mode = s(row, "mode")
        if mode not in {"energy_sweep", "joint_sweep", "conventional_dq", "fixed_action"}:
            continue
        category = s(row, "category", "LVRT" if f(row, "fault_pu", 1.0) < 1.0 else "HVRT")
        groups[(s(row, "topology"), category, mode)].append(row)

    fit_rows = [fit_group(group, key) for key, group in sorted(groups.items())]
    run_id = args.run_id or datetime.now().strftime("energy_cmd_response_%Y%m%d_%H%M%S")
    run_dir = args.out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    csv_path = run_dir / "energy_cmd_response_fit.csv"
    json_path = run_dir / "energy_cmd_response_fit.json"
    report_path = run_dir / "REPORT.md"
    write_csv(csv_path, fit_rows)
    json_path.write_text(json.dumps({"matrix_csv": str(matrix_csv), "fits": fit_rows}, indent=2), encoding="utf-8")
    build_report(report_path, matrix_csv, fit_rows)
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_energy_cmd_response_fit",
        config={"matrix_csv": str(matrix_csv), "run_id": run_id},
        dataset_manifest=matrix_csv,
        extra={"matrix_hash": sha256_file(matrix_csv), "fit_csv": str(csv_path), "fit_json": str(json_path)},
    )
    print(json.dumps({"run_dir": str(run_dir), "fit_csv": str(csv_path), "report": str(report_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


