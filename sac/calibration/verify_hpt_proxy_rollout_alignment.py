"""Verify HPT proxy rollout metrics against switch-level FRT matrix rows.

This is stricter than lookup reward alignment: it runs ``HPTVoltageSACEnv`` with
each fixed matrix action and compares the resulting aggregate metrics against
the Simulink switch-level matrix row.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np

from sac.calibration.calibrate_hpt_frt_proxy_from_matrix import validate_envelope_columns
from sac.hpt_voltage_sac_env import (
    HPTVoltageEnvConfig,
    HPTVoltageSACEnv,
    HPTVoltageScenario,
)


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()
DEFAULT_MATRIX_DIR = ROOT / "lab" / "results" / "hpt_v2_frt_calibration_matrix"
DEFAULT_CALIBRATION = ROOT / "sac" / "hpt_proxy_calibration.json"
DEFAULT_OUT_DIR = ROOT / "lab" / "results" / "hpt_v2_proxy_rollout_alignment"


def latest_csv(directory: Path, pattern: str) -> Path:
    files = sorted(Path(directory).glob(pattern), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"No files matching {pattern} in {directory}")
    return files[-1]


def read_csv(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for raw in reader:
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


def f(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = row.get(key, default)
    if value in ("", None):
        return float(default)
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return float(value)


def finite_mae(rows: list[dict[str, Any]], key: str) -> tuple[float, float]:
    vals = [
        abs(f(row, key, float("nan")))
        for row in rows
        if math.isfinite(f(row, key, float("nan")))
    ]
    if not vals:
        return float("nan"), float("nan")
    arr = np.asarray(vals, dtype=float)
    return float(np.mean(arr)), float(np.max(arr))


def verify_row(row: dict[str, Any], calibration: Path) -> dict[str, Any]:
    fault_start = f(row, "fault_start")
    fault_clear = f(row, "fault_clear")
    scenario = HPTVoltageScenario(
        topology=str(row["topology"]),
        grid_pu=f(row, "grid_pu", f(row, "fault_pu")),
        duration_s=f(row, "stop_time"),
        category=str(row.get("category", "LVRT")),
        fault_type=str(row.get("fault", row.get("case_name", ""))),
        fault_start_s=fault_start,
        fault_duration_s=fault_clear - fault_start,
        calibration_mode=str(row.get("mode", "joint_sweep")),
    )
    env = HPTVoltageSACEnv(
        [scenario],
        config=HPTVoltageEnvConfig(calibration_path=str(calibration)),
        train_mode=False,
    )
    env.reset()
    action = np.asarray(
        [
            f(row, "raw_m_reg_d"),
            f(row, "raw_m_reg_q"),
            f(row, "raw_m_energy_d"),
            f(row, "raw_m_energy_q"),
        ],
        dtype=np.float32,
    )

    t_values: list[float] = []
    lv_values: list[float] = []
    vdc_values: list[float] = []
    iq_values: list[float] = []
    iq_ref_values: list[float] = []
    current_values: list[float] = []
    envelope_values: list[float] = []
    fault_band_values: list[float] = []
    recovery_values: list[float] = []
    terminated = False
    truncated = False
    while not (terminated or truncated):
        _, _, terminated, truncated, info = env.step(action)
        t_values.append(float(env.t))
        lv_values.append(float(info["v_lv_pu"]))
        vdc_values.append(float(info["vdc_pu"]))
        iq_values.append(float(info["grid_iq_pu"]))
        iq_ref_values.append(float(info["grid_iq_ref_pu"]))
        current_values.append(float(info["grid_current_peak_pu"]))
        envelope_values.append(float(info.get("envelope_violation_max_pu", 0.0)))
        fault_band_values.append(float(info.get("fault_band_violation_max_pu", 0.0)))
        recovery_values.append(float(info.get("recovery_violation_max_pu", 0.0)))

    t = np.asarray(t_values, dtype=float)
    lv = np.asarray(lv_values, dtype=float)
    vdc = np.asarray(vdc_values, dtype=float)
    iq = np.asarray(iq_values, dtype=float)
    iq_ref = np.asarray(iq_ref_values, dtype=float)
    current = np.asarray(current_values, dtype=float)
    envelope = np.asarray(envelope_values, dtype=float)
    fault_band = np.asarray(fault_band_values, dtype=float)
    recovery = np.asarray(recovery_values, dtype=float)
    fault_idx = (t > fault_start + 0.010) & (t < fault_clear - 0.002)
    assess_idx = (t >= fault_start + 0.058) & (t <= fault_clear + 1e-9)
    tail = slice(int(len(vdc) * 0.7), None)

    env_lv = float(np.mean(lv[fault_idx])) if np.any(fault_idx) else float("nan")
    env_vdc = float(np.mean(vdc[tail])) if len(vdc) else float("nan")
    env_iq = float(np.mean(iq[assess_idx])) if np.any(assess_idx) else float("nan")
    env_iq_ref = float(np.mean(iq_ref[assess_idx])) if np.any(assess_idx) else float("nan")
    env_current = float(np.max(current)) if len(current) else float("nan")
    env_envelope = float(np.max(envelope)) if len(envelope) else float("nan")
    env_fault_band = float(np.max(fault_band)) if len(fault_band) else float("nan")
    env_recovery = float(np.max(recovery)) if len(recovery) else float("nan")

    return {
        "topology": row.get("topology", ""),
        "category": row.get("category", ""),
        "mode": row.get("mode", ""),
        "fault": row.get("fault", row.get("case_name", "")),
        "grid_pu": f(row, "grid_pu", f(row, "fault_pu")),
        "raw_m_reg_d": f(row, "raw_m_reg_d"),
        "raw_m_reg_q": f(row, "raw_m_reg_q"),
        "raw_m_energy_d": f(row, "raw_m_energy_d"),
        "raw_m_energy_q": f(row, "raw_m_energy_q"),
        "env_lv_pu_mean": env_lv,
        "sim_lv_pu_mean": f(row, "lv_pu_mean"),
        "err_lv_pu_mean": env_lv - f(row, "lv_pu_mean"),
        "env_vdc_pu_mean": env_vdc,
        "sim_vdc_pu_mean": f(row, "vdc_pu_mean", f(row, "vdc_mean") / 800.0),
        "err_vdc_pu_mean": env_vdc - f(row, "vdc_pu_mean", f(row, "vdc_mean") / 800.0),
        "env_grid_iq_mean_pu": env_iq,
        "sim_grid_iq_mean_pu": f(row, "grid_iq_mean_pu", float("nan")),
        "err_grid_iq_mean_pu": env_iq - f(row, "grid_iq_mean_pu", float("nan")),
        "env_grid_iq_ref_mean_pu": env_iq_ref,
        "sim_grid_iq_ref_mean_pu": f(row, "grid_iq_ref_mean_pu", float("nan")),
        "err_grid_iq_ref_mean_pu": env_iq_ref - f(row, "grid_iq_ref_mean_pu", float("nan")),
        "env_grid_current_peak_pu": env_current,
        "sim_grid_current_peak_pu": f(row, "grid_current_peak_pu", float("nan")),
        "err_grid_current_peak_pu": env_current - f(row, "grid_current_peak_pu", float("nan")),
        "env_envelope_violation_max_pu": env_envelope,
        "sim_envelope_violation_max_pu": f(row, "envelope_violation_max_pu", float("nan")),
        "err_envelope_violation_max_pu": env_envelope - f(row, "envelope_violation_max_pu", float("nan")),
        "env_fault_lv_band_violation_max_pu": env_fault_band,
        "sim_fault_lv_band_violation_max_pu": f(row, "fault_lv_band_violation_max_pu", float("nan")),
        "err_fault_lv_band_violation_max_pu": env_fault_band
        - f(row, "fault_lv_band_violation_max_pu", float("nan")),
        "env_recovery_violation_max_pu": env_recovery,
        "sim_recovery_violation_max_pu": f(row, "recovery_violation_max_pu", float("nan")),
        "err_recovery_violation_max_pu": env_recovery - f(row, "recovery_violation_max_pu", float("nan")),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix-csv", type=Path, default=None)
    parser.add_argument("--matrix-dir", type=Path, default=DEFAULT_MATRIX_DIR)
    parser.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--allow-legacy-no-envelope",
        action="store_true",
        help="Allow pre-envelope matrix CSVs. Use only for forensic debugging.",
    )
    args = parser.parse_args()

    matrix_csv = args.matrix_csv or latest_csv(args.matrix_dir, "frt_calibration_matrix_*.csv")
    validate_envelope_columns([matrix_csv], allow_legacy=args.allow_legacy_no_envelope)
    rows = read_csv(matrix_csv)
    detail = [verify_row(row, args.calibration) for row in rows]
    summary = {
        "schema": "hpt-proxy-rollout-alignment-v1",
        "matrix_csv": str(matrix_csv),
        "calibration": str(args.calibration),
        "rows": len(detail),
    }
    for key in [
        "err_lv_pu_mean",
        "err_vdc_pu_mean",
        "err_grid_iq_mean_pu",
        "err_grid_iq_ref_mean_pu",
        "err_grid_current_peak_pu",
        "err_envelope_violation_max_pu",
        "err_fault_lv_band_violation_max_pu",
        "err_recovery_violation_max_pu",
    ]:
        mae, max_abs = finite_mae(detail, key)
        summary[f"{key}_mae"] = mae
        summary[f"{key}_max_abs"] = max_abs

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(matrix_csv).stem.replace("frt_calibration_matrix_", "proxy_rollout_")
    detail_csv = args.out_dir / f"{stem}_detail.csv"
    summary_json = args.out_dir / f"{stem}_summary.json"
    write_csv(detail_csv, detail)
    summary["detail_csv"] = str(detail_csv)
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()


