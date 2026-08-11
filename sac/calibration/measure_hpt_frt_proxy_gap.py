"""Measure FRT proxy gap against the switch-level calibration matrix.

The key holdout is ``joint_sweep``: it is not stored in the proxy tables, so
the predictor must combine the regulating and energy response tables.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from sac.calibration.calibrate_hpt_frt_proxy_from_matrix import validate_envelope_columns


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()
DEFAULT_MATRIX_DIR = ROOT / "lab" / "results" / "hpt_v2_frt_calibration_matrix"
DEFAULT_CALIBRATION = ROOT / "sac" / "hpt_proxy_calibration.json"
DEFAULT_OUT_DIR = ROOT / "lab" / "results" / "hpt_v2_frt_proxy_gap"
INTERP_EPS = 1e-6
VDC_COLLAPSE_PU = 0.25


LOW_IS_BAD_KEYS = {
    "lv_pu_mean",
    "lv_recovery_pu_mean",
    "lv_min_pu",
    "vdc_pu_mean",
    "vdc_min_pu",
}

HIGH_IS_BAD_KEYS = {
    "lv_peak_pu",
    "vdc_max_pu",
    "energy_i_rms_mean",
    "action_max_abs",
    "bridge_modulation_abs_max",
    "grid_iq_shortfall_max_pu",
    "grid_iq_wrong_sign",
    "grid_current_peak_pu",
    "grid_idq_peak_pu",
    "fault_lv_band_violation_max_pu",
    "envelope_violation_max_pu",
    "recovery_violation_max_pu",
}


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
    if isinstance(value, str):
        lower = value.strip().lower()
        if lower in {"true", "yes"}:
            return 1.0
        if lower in {"false", "no"}:
            return 0.0
    return float(value)


def has_numeric(row: dict[str, Any], key: str) -> bool:
    if key not in row or row.get(key) in ("", None):
        return False
    try:
        return bool(np.isfinite(float(row[key])))
    except (TypeError, ValueError):
        return False


def axis_key(table: list[dict[str, Any]], preferred: str, fallback: str) -> str:
    if any(has_numeric(row, preferred) for row in table):
        return preferred
    return fallback


def row_numeric(row: dict[str, Any], preferred: str, fallback: str, default: float = 0.0) -> float:
    if has_numeric(row, preferred):
        return f(row, preferred)
    if has_numeric(row, fallback):
        return f(row, fallback)
    return float(default)


def row_action(row: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        row_numeric(row, "cmd_m_reg_d_mean", "raw_m_reg_d", f(row, "reg_d_mean", 0.0)),
        row_numeric(row, "cmd_m_reg_q_mean", "raw_m_reg_q", f(row, "reg_q_mean", 0.0)),
        row_numeric(row, "cmd_m_energy_d_mean", "raw_m_energy_d", f(row, "energy_d_mean", 0.0)),
        row_numeric(row, "cmd_m_energy_q_mean", "raw_m_energy_q", f(row, "energy_q_mean", 0.0)),
    )


def row_response(row: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        row_numeric(row, "meas_reg_d_mean", "reg_d_mean", 0.0),
        row_numeric(row, "meas_reg_q_mean", "reg_q_mean", 0.0),
        row_numeric(row, "meas_energy_d_mean", "energy_d_mean", 0.0),
        row_numeric(row, "meas_energy_q_mean", "energy_q_mean", 0.0),
    )


def conservative_grid_interp(grid_pu: float, xs: np.ndarray, ys: np.ndarray, key: str) -> float:
    """Interpolate over grid voltage without smoothing across DC-collapse edges.

    The switch-level HPT model can jump between a normal DC-link state and a
    collapsed state over a narrow voltage interval.  Linear interpolation across
    that edge invents nonphysical medium-Vdc points, which then gives SAC the
    wrong reward ordering.  When the two bracketing samples straddle the
    collapse threshold, return the pessimistic endpoint instead.
    """

    target = float(grid_pu)
    if len(xs) <= 1:
        return float(ys[0])
    exact = np.where(np.isclose(xs, target, atol=INTERP_EPS, rtol=0.0))[0]
    if exact.size:
        return float(ys[int(exact[0])])
    upper = int(np.searchsorted(xs, target, side="right"))
    lower = max(0, upper - 1)
    upper = min(len(xs) - 1, upper)
    if lower == upper:
        return float(ys[lower])
    y0 = float(ys[lower])
    y1 = float(ys[upper])
    if key.startswith("vdc_") and ((y0 < VDC_COLLAPSE_PU) != (y1 < VDC_COLLAPSE_PU)):
        if key in HIGH_IS_BAD_KEYS:
            return max(y0, y1)
        return min(y0, y1)
    return float(np.interp(target, xs, ys))


def interp_response(table: list[dict[str, Any]], grid_pu: float, reg_d: float, key: str) -> float | None:
    if not table:
        return None
    x_key = axis_key(table, "cmd_m_reg_d", "reg_d_mean")
    grids = sorted({round(f(row, "grid_pu"), 9) for row in table})
    vals: list[float] = []
    used_grids: list[float] = []
    for grid in grids:
        bucket: dict[float, list[float]] = defaultdict(list)
        for row in table:
            if abs(f(row, "grid_pu") - grid) > 1e-9:
                continue
            if not has_numeric(row, key):
                continue
            if not has_numeric(row, x_key):
                continue
            bucket[f(row, x_key)].append(f(row, key))
        if not bucket:
            continue
        xs = np.asarray(sorted(bucket), dtype=float)
        ys = np.asarray([np.mean(bucket[float(x)]) for x in xs], dtype=float)
        if float(reg_d) < float(xs[0]) - INTERP_EPS or float(reg_d) > float(xs[-1]) + INTERP_EPS:
            continue
        vals.append(float(np.interp(reg_d, xs, ys)))
        used_grids.append(grid)
    if not vals:
        return None
    return conservative_grid_interp(
        grid_pu,
        np.asarray(used_grids, dtype=float),
        np.asarray(vals, dtype=float),
        key,
    )


def interp_by_grid(table: list[dict[str, Any]], grid_pu: float, key: str) -> float | None:
    if not table:
        return None
    bucket: dict[float, list[float]] = defaultdict(list)
    for row in table:
        if not has_numeric(row, key):
            continue
        bucket[round(f(row, "grid_pu"), 9)].append(f(row, key))
    if not bucket:
        return None
    xs = np.asarray(sorted(bucket), dtype=float)
    ys = np.asarray([np.mean(bucket[float(x)]) for x in xs], dtype=float)
    return conservative_grid_interp(grid_pu, xs, ys, key)


def interp_energy_axis(
    table: list[dict[str, Any]],
    grid_pu: float,
    action_value: float,
    axis_key: str,
    other_axis_key: str,
    value_key: str,
) -> float | None:
    if not table:
        return None
    grids = sorted({round(f(row, "grid_pu"), 9) for row in table})
    vals: list[float] = []
    used_grids: list[float] = []
    for grid in grids:
        bucket: dict[float, list[float]] = defaultdict(list)
        for row in table:
            if abs(f(row, "grid_pu") - grid) > 1e-9:
                continue
            if not has_numeric(row, other_axis_key) or abs(f(row, other_axis_key)) > 1e-9:
                continue
            if not has_numeric(row, value_key):
                continue
            bucket[f(row, axis_key)].append(f(row, value_key))
        if not bucket:
            continue
        xs = np.asarray(sorted(bucket), dtype=float)
        ys = np.asarray([np.mean(bucket[float(x)]) for x in xs], dtype=float)
        if float(action_value) < float(xs[0]) - INTERP_EPS or float(action_value) > float(xs[-1]) + INTERP_EPS:
            continue
        vals.append(float(np.interp(action_value, xs, ys)))
        used_grids.append(grid)
    if not vals:
        return None
    return conservative_grid_interp(
        grid_pu,
        np.asarray(used_grids, dtype=float),
        np.asarray(vals, dtype=float),
        value_key,
    )


def interp_energy(table: list[dict[str, Any]], grid_pu: float, ed: float, eq: float, key: str) -> float | None:
    ed_key = axis_key(table, "cmd_m_energy_d", "energy_d_mean")
    eq_key = axis_key(table, "cmd_m_energy_q", "energy_q_mean")
    coupled = interp_grid_axes(
        table,
        grid_pu,
        [ed_key, eq_key],
        [ed, eq],
        key,
    )
    if coupled is not None:
        return coupled

    baseline = interp_energy_axis(table, grid_pu, 0.0, ed_key, eq_key, key)
    d_axis = interp_energy_axis(table, grid_pu, ed, ed_key, eq_key, key)
    q_axis = interp_energy_axis(table, grid_pu, eq, eq_key, ed_key, key)
    if baseline is None or d_axis is None or q_axis is None:
        return None
    return float(baseline + (d_axis - baseline) + (q_axis - baseline))


def interp_axes(rows: list[dict[str, Any]], axis_keys: list[str], axis_values: list[float], key: str) -> float | None:
    if not rows:
        return None
    if not axis_keys:
        vals = [f(row, key, np.nan) for row in rows]
        vals = [value for value in vals if np.isfinite(value)]
        if not vals:
            return None
        return float(np.mean(vals))

    axis_key = axis_keys[0]
    target = float(axis_values[0])
    bucket: dict[float, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if not has_numeric(row, axis_key):
            continue
        bucket[f(row, axis_key)].append(row)
    if not bucket:
        return None

    xs: list[float] = []
    ys: list[float] = []
    for x in sorted(bucket):
        value = interp_axes(bucket[x], axis_keys[1:], axis_values[1:], key)
        if value is None:
            continue
        xs.append(float(x))
        ys.append(float(value))
    if not xs:
        return None
    if target < min(xs) - INTERP_EPS or target > max(xs) + INTERP_EPS:
        return None
    return float(np.interp(target, np.asarray(xs), np.asarray(ys)))


def interp_grid_axes(
    table: list[dict[str, Any]],
    grid_pu: float,
    axis_keys: list[str],
    axis_values: list[float],
    key: str,
) -> float | None:
    if not table:
        return None
    grids = sorted({round(f(row, "grid_pu"), 9) for row in table})
    xs: list[float] = []
    ys: list[float] = []
    for grid in grids:
        rows = [row for row in table if abs(f(row, "grid_pu") - grid) <= 1e-9]
        value = interp_axes(rows, axis_keys, axis_values, key)
        if value is None:
            continue
        xs.append(float(grid))
        ys.append(float(value))
    if not xs:
        return None
    if float(grid_pu) < min(xs) - INTERP_EPS or float(grid_pu) > max(xs) + INTERP_EPS:
        return None
    return conservative_grid_interp(
        float(grid_pu),
        np.asarray(xs, dtype=float),
        np.asarray(ys, dtype=float),
        key,
    )


def context_filtered_rows(
    table: list[dict[str, Any]],
    row: dict[str, Any],
    *,
    phase_key_name: str = "fault_phase_key",
    duration_key_name: str = "fault_duration_s",
) -> list[dict[str, Any]]:
    """Return rows from the same local fault context when possible.

    A family proxy table can contain several phases and fault durations.  For a
    sparse fixed-action diagnostic, mixing those contexts makes the nearest
    action lookup overconfident and can invert the switch-level ranking.  Keep
    the lookup local: same phase first, then nearest available duration.
    """

    if not table:
        return []
    phase = str(row.get(phase_key_name, "") or "")
    candidates = list(table)
    if phase:
        same_phase = [item for item in candidates if str(item.get(phase_key_name, "") or "") == phase]
        if same_phase:
            candidates = same_phase

    if row.get(duration_key_name, "") not in ("", None):
        target_duration = f(row, duration_key_name)
        duration_rows = [item for item in candidates if has_numeric(item, duration_key_name)]
        if duration_rows:
            min_delta = min(abs(f(item, duration_key_name) - target_duration) for item in duration_rows)
            candidates = [
                item
                for item in duration_rows
                if abs(abs(f(item, duration_key_name) - target_duration) - min_delta) <= INTERP_EPS
            ]
    return candidates


def nearest_joint_value(
    table: list[dict[str, Any]],
    grid_pu: float,
    reg_d: float,
    reg_q: float,
    ed: float,
    eq: float,
    key: str,
) -> float | None:
    """Conservative sparse-cloud fallback for fixed-action joint rows.

    The family proxy is calibrated from sparse switch-level action-response
    points, not a full tensor grid.  A strict multilinear interpolator returns
    ``None`` for cross-combinations that are inside the sampled cloud but not on
    every axis-aligned grid line.  Use the nearest measured joint response so
    alignment diagnostics match the SAC environment's conservative fallback.
    """

    samples: list[list[float]] = []
    values: list[float] = []
    for row in table:
        if not has_numeric(row, key):
            continue
        samples.append(
            [
                f(row, "grid_pu"),
                row_numeric(row, "cmd_m_reg_d", "reg_d_mean", 0.0),
                row_numeric(row, "cmd_m_reg_q", "reg_q_mean", 0.0),
                row_numeric(row, "cmd_m_energy_d", "energy_d_mean", 0.0),
                row_numeric(row, "cmd_m_energy_q", "energy_q_mean", 0.0),
            ]
        )
        values.append(f(row, key))
    if not samples:
        return None
    sample_array = np.asarray(samples, dtype=float)
    query = np.asarray([grid_pu, reg_d, reg_q, ed, eq], dtype=float)
    spans = np.maximum(
        np.ptp(sample_array, axis=0),
        np.asarray([0.05, 0.08, 0.05, 0.08, 0.10], dtype=float),
    )
    idx = int(np.argmin(np.linalg.norm((sample_array - query) / spans, axis=1)))
    return float(values[idx])


def analyze(rows: list[dict[str, Any]], calibration: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        topology = str(row["topology"])
        top = calibration["topologies"][topology]
        mode = str(row["mode"])
        raw_reg_q = f(row, "raw_m_reg_q")
        mode_label = mode
        if mode == "reg_sweep" and abs(raw_reg_q) > 1e-9:
            mode_label = "reg_q_sweep"
        grid = f(row, "grid_pu", f(row, "fault_pu"))
        reg, reg_q, ed, eq = row_action(row)
        meas_reg, meas_reg_q, meas_ed, meas_eq = row_response(row)
        reg_table = top.get("fault_reg_response_table", top.get("fault_response_table", []))
        reg_d_axis_table = top.get("fault_response_table", [])
        energy_table = top.get("fault_energy_response_table", [])
        joint_table = top.get("fault_joint_response_table", [])
        baseline_table = top.get("fault_baseline_table", [])
        local_joint_table = context_filtered_rows(joint_table, row)

        def predict_metric(key: str) -> float | None:
            pred = interp_grid_axes(
                reg_table,
                grid,
                [
                    axis_key(reg_table, "cmd_m_reg_d", "reg_d_mean"),
                    axis_key(reg_table, "cmd_m_reg_q", "reg_q_mean"),
                ],
                [reg, reg_q],
                key,
            )
            if pred is None:
                pred = interp_response(reg_d_axis_table, grid, reg, key)
            pred_energy = interp_energy(energy_table, grid, ed, eq, key)
            if mode == "baseline":
                return interp_by_grid(baseline_table, grid, key)
            if mode in {"energy_sweep"}:
                return pred_energy
            if mode in {"joint_sweep"}:
                joint = interp_grid_axes(
                    local_joint_table,
                    grid,
                    [
                        axis_key(local_joint_table, "cmd_m_reg_d", "reg_d_mean"),
                        axis_key(local_joint_table, "cmd_m_reg_q", "reg_q_mean"),
                        axis_key(local_joint_table, "cmd_m_energy_d", "energy_d_mean"),
                        axis_key(local_joint_table, "cmd_m_energy_q", "energy_q_mean"),
                    ],
                    [reg, reg_q, ed, eq],
                    key,
                )
                if joint is not None:
                    return joint
                joint = nearest_joint_value(local_joint_table, grid, reg, reg_q, ed, eq, key)
                if joint is not None:
                    return joint
                if pred is not None and pred_energy is not None:
                    zero_energy = interp_energy(energy_table, grid, 0.0, 0.0, key)
                    if zero_energy is not None:
                        return pred + (pred_energy - zero_energy)
            return pred

        pred_lv = predict_metric("lv_pu_mean")
        pred_lv_recovery = predict_metric("lv_recovery_pu_mean")
        pred_lv_peak = predict_metric("lv_peak_pu")
        pred_lv_min = predict_metric("lv_min_pu")
        pred_lv_unbalance = predict_metric("lv_unbalance_pu")
        pred_vdc = predict_metric("vdc_pu_mean")
        pred_vdc_min = predict_metric("vdc_min_pu")
        pred_vdc_max = predict_metric("vdc_max_pu")
        pred_action_max = predict_metric("action_max_abs")
        pred_i_energy = predict_metric("energy_i_rms_mean")
        pred_grid_vpos = predict_metric("grid_vpos_pu_mean")
        pred_grid_iq = predict_metric("grid_iq_mean_pu")
        pred_grid_iq_ref = predict_metric("grid_iq_ref_mean_pu")
        pred_grid_iq_shortfall = predict_metric("grid_iq_shortfall_max_pu")
        pred_grid_iq_wrong_sign = predict_metric("grid_iq_wrong_sign")
        pred_grid_current = predict_metric("grid_current_peak_pu")
        pred_grid_idq = predict_metric("grid_idq_peak_pu")
        pred_fault_band_violation = predict_metric("fault_lv_band_violation_max_pu")
        pred_envelope_violation = predict_metric("envelope_violation_max_pu")
        pred_recovery_violation = predict_metric("recovery_violation_max_pu")
        out.append(
            {
                "topology": topology,
                "category": row.get("category", ""),
                "fault": row.get("fault", row.get("case_name", "")),
                "mode": mode_label,
                "grid_pu": grid,
                "reg_d": reg,
                "reg_q": reg_q,
                "energy_d": ed,
                "energy_q": eq,
                "cmd_m_reg_d": reg,
                "cmd_m_reg_q": reg_q,
                "cmd_m_energy_d": ed,
                "cmd_m_energy_q": eq,
                "meas_reg_d": meas_reg,
                "meas_reg_q": meas_reg_q,
                "meas_energy_d": meas_ed,
                "meas_energy_q": meas_eq,
                "sim_lv_pu": f(row, "lv_pu_mean"),
                "proxy_lv_pu": pred_lv,
                "err_lv_pu": None if pred_lv is None else pred_lv - f(row, "lv_pu_mean"),
                "sim_lv_recovery_pu": f(row, "lv_recovery_pu_mean", np.nan),
                "proxy_lv_recovery_pu": pred_lv_recovery,
                "err_lv_recovery_pu": None if pred_lv_recovery is None else pred_lv_recovery - f(row, "lv_recovery_pu_mean", np.nan),
                "sim_lv_peak_pu": f(row, "lv_peak_pu", np.nan),
                "proxy_lv_peak_pu": pred_lv_peak,
                "err_lv_peak_pu": None if pred_lv_peak is None else pred_lv_peak - f(row, "lv_peak_pu", np.nan),
                "sim_lv_min_pu": f(row, "lv_min_pu", np.nan),
                "proxy_lv_min_pu": pred_lv_min,
                "err_lv_min_pu": None if pred_lv_min is None else pred_lv_min - f(row, "lv_min_pu", np.nan),
                "sim_lv_unbalance_pu": f(row, "lv_unbalance_pu", np.nan),
                "proxy_lv_unbalance_pu": pred_lv_unbalance,
                "err_lv_unbalance_pu": None if pred_lv_unbalance is None else pred_lv_unbalance - f(row, "lv_unbalance_pu", np.nan),
                "sim_vdc_pu": f(row, "vdc_pu_mean", f(row, "vdc_mean") / 800.0),
                "proxy_vdc_pu": pred_vdc,
                "err_vdc_pu": None if pred_vdc is None else pred_vdc - f(row, "vdc_pu_mean", f(row, "vdc_mean") / 800.0),
                "sim_vdc_min_pu": f(row, "vdc_min_pu", f(row, "vdc_min") / 800.0),
                "proxy_vdc_min_pu": pred_vdc_min,
                "err_vdc_min_pu": None if pred_vdc_min is None else pred_vdc_min - f(row, "vdc_min_pu", f(row, "vdc_min") / 800.0),
                "sim_vdc_max_pu": f(row, "vdc_max_pu", f(row, "vdc_max") / 800.0),
                "proxy_vdc_max_pu": pred_vdc_max,
                "err_vdc_max_pu": None if pred_vdc_max is None else pred_vdc_max - f(row, "vdc_max_pu", f(row, "vdc_max") / 800.0),
                "sim_action_max_abs": f(row, "action_max_abs", np.nan),
                "proxy_action_max_abs": pred_action_max,
                "err_action_max_abs": None if pred_action_max is None else pred_action_max - f(row, "action_max_abs", np.nan),
                "sim_energy_i_rms": f(row, "energy_i_rms_mean"),
                "proxy_energy_i_rms": pred_i_energy,
                "err_energy_i_rms": None if pred_i_energy is None else pred_i_energy - f(row, "energy_i_rms_mean"),
                "sim_grid_vpos_pu": f(row, "grid_vpos_pu_mean", np.nan),
                "proxy_grid_vpos_pu": pred_grid_vpos,
                "err_grid_vpos_pu": None if pred_grid_vpos is None else pred_grid_vpos - f(row, "grid_vpos_pu_mean", np.nan),
                "sim_grid_iq_pu": f(row, "grid_iq_mean_pu", np.nan),
                "proxy_grid_iq_pu": pred_grid_iq,
                "err_grid_iq_pu": None if pred_grid_iq is None else pred_grid_iq - f(row, "grid_iq_mean_pu", np.nan),
                "sim_grid_iq_ref_pu": f(row, "grid_iq_ref_mean_pu", np.nan),
                "proxy_grid_iq_ref_pu": pred_grid_iq_ref,
                "err_grid_iq_ref_pu": None if pred_grid_iq_ref is None else pred_grid_iq_ref - f(row, "grid_iq_ref_mean_pu", np.nan),
                "sim_grid_iq_shortfall_pu": f(row, "grid_iq_shortfall_max_pu", np.nan),
                "proxy_grid_iq_shortfall_pu": pred_grid_iq_shortfall,
                "err_grid_iq_shortfall_pu": None if pred_grid_iq_shortfall is None else pred_grid_iq_shortfall - f(row, "grid_iq_shortfall_max_pu", np.nan),
                "sim_grid_iq_wrong_sign": f(row, "grid_iq_wrong_sign", np.nan),
                "proxy_grid_iq_wrong_sign": pred_grid_iq_wrong_sign,
                "err_grid_iq_wrong_sign": None if pred_grid_iq_wrong_sign is None else pred_grid_iq_wrong_sign - f(row, "grid_iq_wrong_sign", np.nan),
                "sim_grid_current_peak_pu": f(row, "grid_current_peak_pu", np.nan),
                "proxy_grid_current_peak_pu": pred_grid_current,
                "err_grid_current_peak_pu": None if pred_grid_current is None else pred_grid_current - f(row, "grid_current_peak_pu", np.nan),
                "sim_grid_idq_peak_pu": f(row, "grid_idq_peak_pu", np.nan),
                "proxy_grid_idq_peak_pu": pred_grid_idq,
                "err_grid_idq_peak_pu": None if pred_grid_idq is None else pred_grid_idq - f(row, "grid_idq_peak_pu", np.nan),
                "sim_fault_lv_band_violation_max_pu": f(row, "fault_lv_band_violation_max_pu", np.nan),
                "proxy_fault_lv_band_violation_max_pu": pred_fault_band_violation,
                "err_fault_lv_band_violation_max_pu": None if pred_fault_band_violation is None else pred_fault_band_violation - f(row, "fault_lv_band_violation_max_pu", np.nan),
                "sim_envelope_violation_max_pu": f(row, "envelope_violation_max_pu", np.nan),
                "proxy_envelope_violation_max_pu": pred_envelope_violation,
                "err_envelope_violation_max_pu": None if pred_envelope_violation is None else pred_envelope_violation - f(row, "envelope_violation_max_pu", np.nan),
                "sim_recovery_violation_max_pu": f(row, "recovery_violation_max_pu", np.nan),
                "proxy_recovery_violation_max_pu": pred_recovery_violation,
                "err_recovery_violation_max_pu": None if pred_recovery_violation is None else pred_recovery_violation - f(row, "recovery_violation_max_pu", np.nan),
            }
        )
    return out


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(str(row["topology"]), str(row["category"]), str(row["mode"]))].append(row)
    summary: list[dict[str, Any]] = []
    for (topology, category, mode), data in sorted(groups.items()):
        lv_err = np.asarray([f(r, "err_lv_pu", np.nan) for r in data], dtype=float)
        lv_recovery_err = np.asarray([f(r, "err_lv_recovery_pu", np.nan) for r in data], dtype=float)
        lv_peak_err = np.asarray([f(r, "err_lv_peak_pu", np.nan) for r in data], dtype=float)
        lv_min_err = np.asarray([f(r, "err_lv_min_pu", np.nan) for r in data], dtype=float)
        vdc_err = np.asarray([f(r, "err_vdc_pu", np.nan) for r in data], dtype=float)
        vdc_min_err = np.asarray([f(r, "err_vdc_min_pu", np.nan) for r in data], dtype=float)
        vdc_max_err = np.asarray([f(r, "err_vdc_max_pu", np.nan) for r in data], dtype=float)
        i_err = np.asarray([f(r, "err_energy_i_rms", np.nan) for r in data], dtype=float)
        grid_iq_err = np.asarray([f(r, "err_grid_iq_pu", np.nan) for r in data], dtype=float)
        grid_iq_shortfall_err = np.asarray([f(r, "err_grid_iq_shortfall_pu", np.nan) for r in data], dtype=float)
        grid_iq_wrong_err = np.asarray([f(r, "err_grid_iq_wrong_sign", np.nan) for r in data], dtype=float)
        grid_current_err = np.asarray([f(r, "err_grid_current_peak_pu", np.nan) for r in data], dtype=float)
        fault_band_err = np.asarray([f(r, "err_fault_lv_band_violation_max_pu", np.nan) for r in data], dtype=float)
        envelope_err = np.asarray([f(r, "err_envelope_violation_max_pu", np.nan) for r in data], dtype=float)
        recovery_err = np.asarray([f(r, "err_recovery_violation_max_pu", np.nan) for r in data], dtype=float)
        summary.append(
            {
                "topology": topology,
                "category": category,
                "mode": mode,
                "n": len(data),
                "lv_mae_pu": float(np.nanmean(np.abs(lv_err))),
                "lv_max_abs_pu": float(np.nanmax(np.abs(lv_err))),
                "lv_recovery_mae_pu": float(np.nanmean(np.abs(lv_recovery_err))) if np.any(~np.isnan(lv_recovery_err)) else float("nan"),
                "lv_peak_mae_pu": float(np.nanmean(np.abs(lv_peak_err))) if np.any(~np.isnan(lv_peak_err)) else float("nan"),
                "lv_min_mae_pu": float(np.nanmean(np.abs(lv_min_err))) if np.any(~np.isnan(lv_min_err)) else float("nan"),
                "vdc_mae_pu": float(np.nanmean(np.abs(vdc_err))),
                "vdc_max_abs_pu": float(np.nanmax(np.abs(vdc_err))),
                "vdc_min_mae_pu": float(np.nanmean(np.abs(vdc_min_err))) if np.any(~np.isnan(vdc_min_err)) else float("nan"),
                "vdc_max_mae_pu": float(np.nanmean(np.abs(vdc_max_err))) if np.any(~np.isnan(vdc_max_err)) else float("nan"),
                "energy_i_mae": float(np.nanmean(np.abs(i_err))) if np.any(~np.isnan(i_err)) else float("nan"),
                "grid_iq_mae_pu": float(np.nanmean(np.abs(grid_iq_err))) if np.any(~np.isnan(grid_iq_err)) else float("nan"),
                "grid_iq_shortfall_mae_pu": float(np.nanmean(np.abs(grid_iq_shortfall_err))) if np.any(~np.isnan(grid_iq_shortfall_err)) else float("nan"),
                "grid_iq_wrong_sign_mae": float(np.nanmean(np.abs(grid_iq_wrong_err))) if np.any(~np.isnan(grid_iq_wrong_err)) else float("nan"),
                "grid_current_mae_pu": float(np.nanmean(np.abs(grid_current_err))) if np.any(~np.isnan(grid_current_err)) else float("nan"),
                "fault_lv_band_violation_mae_pu": float(np.nanmean(np.abs(fault_band_err))) if np.any(~np.isnan(fault_band_err)) else float("nan"),
                "envelope_violation_mae_pu": float(np.nanmean(np.abs(envelope_err))) if np.any(~np.isnan(envelope_err)) else float("nan"),
                "recovery_violation_mae_pu": float(np.nanmean(np.abs(recovery_err))) if np.any(~np.isnan(recovery_err)) else float("nan"),
            }
        )
    return summary


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
    calibration = json.loads(Path(args.calibration).read_text(encoding="utf-8"))
    detail = analyze(rows, calibration)
    summary = summarize(detail)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(matrix_csv).stem.replace("frt_calibration_matrix_", "frt_proxy_gap_")
    detail_csv = args.out_dir / f"{stem}_detail.csv"
    summary_csv = args.out_dir / f"{stem}_summary.csv"
    summary_json = args.out_dir / f"{stem}_summary.json"
    write_csv(detail_csv, detail)
    write_csv(summary_csv, summary)
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"detail_csv": str(detail_csv), "summary_csv": str(summary_csv)}, indent=2), flush=True)


if __name__ == "__main__":
    main()


