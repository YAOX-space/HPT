"""GB/T 19963.1 voltage-time curves and project HPT load-quality gates.

The grid-code voltage-time curve describes an admissible PCC disturbance for
which the connected equipment is required to ride through.  It is not a
load-side voltage-control target.  This module therefore keeps PCC scenario
validation separate from the project-defined HPT load-voltage quality gate.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np


DEFAULT_PHASE_RMS = 207.0
DEFAULT_VDC = 800.0
DEFAULT_SOLVER_TOL_PU = 1e-3

LVRT_HOLD_S = 0.625
LVRT_RECOVERY_S = 2.0
LVRT_FLOOR_PU = 0.20
LVRT_RECOVERED_PU = 0.90

HVRT_130_END_S = 0.5
HVRT_125_END_S = 1.0
HVRT_120_END_S = 10.0

LOAD_FAULT_LOW_V = 176.0
LOAD_FAULT_HIGH_V = 238.0
LOAD_RECOVERY_SETTLE_S = 0.035
LOAD_RECOVERY_BAND_PU = 0.07


@dataclass(frozen=True)
class GridCodeEnvelopeMetrics:
    """Per-sample PCC voltage-time scenario validation result."""

    category: str
    assessment_signal: str
    violation_max_pu: float
    violation_mean_pu: float
    violation_duration_s: float
    margin_min_pu: float
    scenario_valid: bool

    def asdict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LoadVoltageQualityMetrics:
    """Project-defined HPT load-side voltage quality result."""

    fault_band_violation_max_pu: float
    fault_band_violation_mean_pu: float
    fault_band_violation_duration_s: float
    fault_band_pass: bool
    fault_lv_min_pu: float
    fault_lv_max_pu: float
    recovery_violation_max_pu: float
    recovery_violation_mean_pu: float
    recovery_violation_duration_s: float
    recovery_envelope_pass: bool
    recovery_lv_min_pu: float
    recovery_lv_max_pu: float
    load_quality_violation_max_pu: float
    load_quality_pass: bool

    def asdict(self) -> dict[str, Any]:
        return asdict(self)


def lvrt_lower_envelope(
    t_rel: np.ndarray | float,
    residual_pu: float | None = None,
) -> np.ndarray:
    """Return the GB/T 19963.1 LVRT lower voltage-time boundary.

    ``residual_pu`` is retained only to keep existing call sites source
    compatible.  The standard boundary is fixed at 0.20 pu during the first
    625 ms and must not be replaced by the imposed fault residual.
    """

    del residual_pu
    t = np.asarray(t_rel, dtype=float)
    y = np.full_like(t, LVRT_RECOVERED_PU, dtype=float)
    y = np.where((t >= 0.0) & (t <= LVRT_HOLD_S), LVRT_FLOOR_PU, y)
    ramp = LVRT_FLOOR_PU + (
        (LVRT_RECOVERED_PU - LVRT_FLOOR_PU)
        * (t - LVRT_HOLD_S)
        / (LVRT_RECOVERY_S - LVRT_HOLD_S)
    )
    y = np.where((t > LVRT_HOLD_S) & (t <= LVRT_RECOVERY_S), ramp, y)
    return y


def hvrt_upper_envelope(t_rel: np.ndarray | float) -> np.ndarray:
    """Return the GB/T 19963.1 HVRT upper voltage-time boundary."""

    t = np.asarray(t_rel, dtype=float)
    y = np.full_like(t, 1.10, dtype=float)
    y = np.where((t >= 0.0) & (t <= HVRT_130_END_S), 1.30, y)
    y = np.where((t > HVRT_130_END_S) & (t <= HVRT_125_END_S), 1.25, y)
    y = np.where((t > HVRT_125_END_S) & (t <= HVRT_120_END_S), 1.20, y)
    return y


def grid_code_envelope_arrays(
    t_s: np.ndarray,
    pcc_assessment_pu: np.ndarray,
    *,
    fault_pu: float,
    fault_start_s: float,
    stop_time_s: float | None = None,
    fault_settle_s: float = 0.0,
) -> dict[str, np.ndarray | str]:
    """Return the PCC grid-code envelope and per-sample scenario violation."""

    t, v = _paired_1d(t_s, pcc_assessment_pu, "pcc_assessment_pu")
    stop = _stop_time(t, stop_time_s)
    assess_start = float(fault_start_s) + max(0.0, float(fault_settle_s))
    active = (t >= assess_start) & (t <= stop)
    t_rel = t - float(fault_start_s)

    if float(fault_pu) < 1.0:
        category = "LVRT"
        lower = lvrt_lower_envelope(t_rel)
        upper = np.full_like(lower, np.inf, dtype=float)
        margin = v - lower
        violation = np.maximum(0.0, lower - v)
    else:
        category = "HVRT"
        upper = hvrt_upper_envelope(t_rel)
        lower = np.full_like(upper, -np.inf, dtype=float)
        margin = upper - v
        violation = np.maximum(0.0, v - upper)

    return {
        "category": category,
        "lower_pu": lower,
        "upper_pu": upper,
        "margin_pu": np.where(active, margin, np.inf),
        "violation_pu": np.where(active, violation, 0.0),
        "active": active,
    }


def summarize_grid_code_envelope(
    t_s: np.ndarray,
    pcc_assessment_pu: np.ndarray,
    *,
    fault_pu: float,
    fault_start_s: float,
    assessment_signal: str,
    stop_time_s: float | None = None,
    fault_settle_s: float = 0.0,
    tolerance_pu: float = DEFAULT_SOLVER_TOL_PU,
) -> GridCodeEnvelopeMetrics:
    """Summarize whether the measured PCC disturbance is inside the curve."""

    arrays = grid_code_envelope_arrays(
        t_s,
        pcc_assessment_pu,
        fault_pu=fault_pu,
        fault_start_s=fault_start_s,
        stop_time_s=stop_time_s,
        fault_settle_s=fault_settle_s,
    )
    t = np.asarray(t_s, dtype=float).reshape(-1)
    active = np.asarray(arrays["active"], dtype=bool)
    violation = np.asarray(arrays["violation_pu"], dtype=float)[active]
    margin = np.asarray(arrays["margin_pu"], dtype=float)[active]
    dt = _sample_period(t)
    max_violation = float(np.max(violation)) if violation.size else float("inf")
    mean_violation = float(np.mean(violation)) if violation.size else float("inf")
    duration = float(dt * np.count_nonzero(violation > tolerance_pu))
    min_margin = float(np.min(margin)) if margin.size else float("-inf")
    return GridCodeEnvelopeMetrics(
        category=str(arrays["category"]),
        assessment_signal=str(assessment_signal),
        violation_max_pu=max_violation,
        violation_mean_pu=mean_violation,
        violation_duration_s=duration,
        margin_min_pu=min_margin,
        scenario_valid=bool(violation.size and max_violation <= tolerance_pu),
    )


def load_voltage_quality_arrays(
    t_s: np.ndarray,
    lv_pu: np.ndarray,
    *,
    fault_start_s: float,
    fault_clear_s: float,
    stop_time_s: float | None = None,
    fault_settle_s: float = 0.0,
    recovery_settle_s: float = LOAD_RECOVERY_SETTLE_S,
    recovery_band_pu: float = LOAD_RECOVERY_BAND_PU,
    fault_low_pu: float = LOAD_FAULT_LOW_V / DEFAULT_PHASE_RMS,
    fault_high_pu: float = LOAD_FAULT_HIGH_V / DEFAULT_PHASE_RMS,
) -> dict[str, np.ndarray]:
    """Return project-defined load-side fault and recovery violations."""

    t, v = _paired_1d(t_s, lv_pu, "lv_pu")
    stop = _stop_time(t, stop_time_s)
    fault_active = (
        (t >= float(fault_start_s) + max(0.0, float(fault_settle_s)))
        & (t <= float(fault_clear_s))
    )
    recovery_active = (
        (t >= float(fault_clear_s) + max(0.0, float(recovery_settle_s)))
        & (t <= stop)
    )
    fault_violation = np.maximum(
        np.maximum(0.0, float(fault_low_pu) - v),
        np.maximum(0.0, v - float(fault_high_pu)),
    )
    recovery_violation = np.maximum(
        0.0,
        np.abs(v - 1.0) - float(recovery_band_pu),
    )
    fault_violation = np.where(fault_active, fault_violation, 0.0)
    recovery_violation = np.where(recovery_active, recovery_violation, 0.0)
    return {
        "fault_band_violation_pu": fault_violation,
        "fault_band_active": fault_active,
        "recovery_violation_pu": recovery_violation,
        "recovery_active": recovery_active,
        "load_quality_violation_pu": np.maximum(fault_violation, recovery_violation),
    }


def summarize_load_voltage_quality(
    t_s: np.ndarray,
    lv_pu: np.ndarray,
    *,
    fault_start_s: float,
    fault_clear_s: float,
    stop_time_s: float | None = None,
    tolerance_pu: float = DEFAULT_SOLVER_TOL_PU,
    fault_settle_s: float = 0.0,
    recovery_settle_s: float = LOAD_RECOVERY_SETTLE_S,
    recovery_band_pu: float = LOAD_RECOVERY_BAND_PU,
    fault_low_pu: float = LOAD_FAULT_LOW_V / DEFAULT_PHASE_RMS,
    fault_high_pu: float = LOAD_FAULT_HIGH_V / DEFAULT_PHASE_RMS,
) -> LoadVoltageQualityMetrics:
    """Summarize the project-defined HPT load-voltage quality gate."""

    arrays = load_voltage_quality_arrays(
        t_s,
        lv_pu,
        fault_start_s=fault_start_s,
        fault_clear_s=fault_clear_s,
        stop_time_s=stop_time_s,
        fault_settle_s=fault_settle_s,
        recovery_settle_s=recovery_settle_s,
        recovery_band_pu=recovery_band_pu,
        fault_low_pu=fault_low_pu,
        fault_high_pu=fault_high_pu,
    )
    t = np.asarray(t_s, dtype=float).reshape(-1)
    v = np.asarray(lv_pu, dtype=float).reshape(-1)
    dt = _sample_period(t)
    fault_active = np.asarray(arrays["fault_band_active"], dtype=bool)
    recovery_active = np.asarray(arrays["recovery_active"], dtype=bool)
    fault_violation = np.asarray(arrays["fault_band_violation_pu"], dtype=float)[fault_active]
    recovery_violation = np.asarray(arrays["recovery_violation_pu"], dtype=float)[recovery_active]

    fault_max, fault_mean, fault_duration = _violation_summary(
        fault_violation, dt, tolerance_pu
    )
    recovery_max, recovery_mean, recovery_duration = _violation_summary(
        recovery_violation, dt, tolerance_pu
    )
    fault_values = v[fault_active]
    recovery_values = v[recovery_active]
    fault_pass = bool(fault_violation.size and fault_max <= tolerance_pu)
    recovery_pass = bool(recovery_violation.size and recovery_max <= tolerance_pu)
    return LoadVoltageQualityMetrics(
        fault_band_violation_max_pu=fault_max,
        fault_band_violation_mean_pu=fault_mean,
        fault_band_violation_duration_s=fault_duration,
        fault_band_pass=fault_pass,
        fault_lv_min_pu=_safe_min(fault_values),
        fault_lv_max_pu=_safe_max(fault_values),
        recovery_violation_max_pu=recovery_max,
        recovery_violation_mean_pu=recovery_mean,
        recovery_violation_duration_s=recovery_duration,
        recovery_envelope_pass=recovery_pass,
        recovery_lv_min_pu=_safe_min(recovery_values),
        recovery_lv_max_pu=_safe_max(recovery_values),
        load_quality_violation_max_pu=max(fault_max, recovery_max),
        load_quality_pass=bool(fault_pass and recovery_pass),
    )


def sample_load_voltage_quality(
    *,
    t_s: float,
    lv_pu: float,
    fault_start_s: float,
    fault_clear_s: float,
    stop_time_s: float,
    tolerance_pu: float = DEFAULT_SOLVER_TOL_PU,
    fault_settle_s: float = 0.0,
    recovery_settle_s: float = LOAD_RECOVERY_SETTLE_S,
    recovery_band_pu: float = LOAD_RECOVERY_BAND_PU,
) -> dict[str, float | bool]:
    """Evaluate one control step against the HPT load-quality gate."""

    arrays = load_voltage_quality_arrays(
        np.asarray([float(t_s)], dtype=float),
        np.asarray([float(lv_pu)], dtype=float),
        fault_start_s=fault_start_s,
        fault_clear_s=fault_clear_s,
        stop_time_s=stop_time_s,
        fault_settle_s=fault_settle_s,
        recovery_settle_s=recovery_settle_s,
        recovery_band_pu=recovery_band_pu,
    )
    fault_violation = float(np.asarray(arrays["fault_band_violation_pu"])[0])
    recovery_violation = float(np.asarray(arrays["recovery_violation_pu"])[0])
    load_violation = max(fault_violation, recovery_violation)
    return {
        "fault_band_violation_max_pu": fault_violation,
        "recovery_violation_max_pu": recovery_violation,
        "load_quality_violation_max_pu": load_violation,
        "load_quality_pass": bool(load_violation <= tolerance_pu),
    }


def _paired_1d(
    t_s: np.ndarray,
    values: np.ndarray,
    value_name: str,
) -> tuple[np.ndarray, np.ndarray]:
    t = np.asarray(t_s, dtype=float).reshape(-1)
    v = np.asarray(values, dtype=float).reshape(-1)
    if t.shape != v.shape:
        raise ValueError(f"t_s and {value_name} shape mismatch: {t.shape} vs {v.shape}")
    if not np.all(np.isfinite(t)) or not np.all(np.isfinite(v)):
        raise ValueError(f"t_s and {value_name} must be finite")
    return t, v


def _stop_time(t: np.ndarray, stop_time_s: float | None) -> float:
    if stop_time_s is not None:
        return float(stop_time_s)
    return float(t[-1]) if t.size else 0.0


def _sample_period(t: np.ndarray) -> float:
    return float(np.median(np.diff(t))) if t.size > 1 else 0.0


def _violation_summary(
    values: np.ndarray,
    dt: float,
    tolerance_pu: float,
) -> tuple[float, float, float]:
    if not values.size:
        return float("inf"), float("inf"), 0.0
    return (
        float(np.max(values)),
        float(np.mean(values)),
        float(dt * np.count_nonzero(values > tolerance_pu)),
    )


def _safe_min(values: np.ndarray) -> float:
    return float(np.min(values)) if values.size else float("nan")


def _safe_max(values: np.ndarray) -> float:
    return float(np.max(values)) if values.size else float("nan")
