"""Topology-neutral SAC surrogate for HPT voltage regulation and FRT transitions.

This environment targets the final HPT switch-level models in
``simulink``.  It keeps the final 4-D direct-action contract and
extends the observation from the early steady-regulation 16-D vector to a
fault-transition-aware 24-D vector:

    obs = [
        v_lv_rms_pu, grid_v_pos_pu, grid_v_neg_pu, vdc_pu, vdc_err_pu, v_err_pu,
        energy_id_pu, energy_iq_pu,
        last_m_reg_d, last_m_reg_q, last_m_energy_d, last_m_energy_q,
        sag_flag, swell_flag, topology1_flag, topology2_flag,
        fault_active_est, recovery_active_est, t_fault_est_pu, t_recovery_est_pu,
        grid_fault_min_pu, grid_fault_max_pu, d_grid_pos_dt_pu, d_vdc_dt_pu,
    ]

    act = [m_reg_d, m_reg_q, m_energy_d, m_energy_q]

The fault detector and scenario coverage are intentionally borrowed from the
older ``src/hpt_frt/device`` FRT SAC design: online measured-voltage detection,
LVRT/HVRT depth sweeps, asymmetric negative-sequence cases, and recovery
segments.  The dynamics remain a fast averaged proxy; the switch-level Simulink
models are still the source of record.  The energy action is the normalized
energy-bridge dq modulation/current command used by the version-2 full-action
interface; switch-level validation keeps command and measured response fields
separate.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Iterable

import gymnasium as gym
import joblib
import numpy as np
from gymnasium import spaces

from .frt_envelope import DEFAULT_SOLVER_TOL_PU, sample_load_voltage_quality
from .gate_contract import (
    CURRENT_FRT_VALIDATOR_SCHEMA,
    normalize_target_gate,
)
from .hybrid_dc_channel import DCChannelInputs, HybridDCLinkChannel
from .slow_state_correction import (
    SlowStateCorrectionInputs,
    SlowStateProfileCorrection,
)


OBS_DIM_HPT = 24
ACT_DIM_HPT = 4
DEFAULT_PROXY_CALIBRATION = Path(__file__).with_name("hpt_proxy_calibration.json")
_INTERP_EPS = 1e-6
_VDC_COLLAPSE_PU = 0.25

_HIGH_IS_BAD_METRIC_KEYS = {
    "lv_peak_pu",
    "vdc_max_pu",
    "energy_i_rms_mean",
    "action_max_abs",
    "bridge_modulation_abs_max",
    "grid_iq_shortfall_max_pu",
    "grid_iq_wrong_sign",
    "grid_current_peak_pu",
    "grid_idq_peak_pu",
}


@dataclass(frozen=True)
class HPTVoltageScenario:
    """One averaged HPT voltage/FRT scenario.

    ``grid_pu`` is the disturbed source voltage during the fault window.  The
    default ``fault_start_s=0`` preserves the old steady sag/swell behavior for
    small unit tests and hand-constructed scenarios.
    """

    topology: str
    grid_pu: float
    neg_seq_pu: float = 0.0
    fault_phase_key: str = "abc"
    duration_s: float = 0.20
    load_pu: float = 1.0
    category: str = "steady"
    fault_type: str = "steady"
    pre_fault_pu: float = 1.0
    post_fault_pu: float = 1.0
    fault_start_s: float = 0.0
    fault_duration_s: float | None = None
    recovery_tau_s: float = 0.05
    scr: float = 3.0
    xr_ratio: float = 3.0
    calibration_mode: str = "joint_sweep"


@dataclass(frozen=True)
class HPTVoltageEnvConfig:
    """Tunable surrogate parameters."""

    dt: float = 2e-3
    v_ref_phase_rms: float = 207.0
    vdc_ref: float = 800.0
    reg_limit: float = 0.80
    energy_limit: float = 0.95
    reg_d_limit: float = 0.80
    reg_q_limit: float = 0.40
    energy_d_limit: float = 0.95
    energy_q_limit: float = 0.95
    v_tau: float = 0.012
    vdc_tau: float = 0.018
    use_switch_calibration: bool = True
    calibration_path: str = str(DEFAULT_PROXY_CALIBRATION)
    source_gain_topology1: float = 1.0
    source_bias_topology1: float = 0.0
    source_gain_topology2: float = 1.0
    source_bias_topology2: float = 0.0
    reg_gain_topology1: float = 0.33
    reg_gain_topology2: float = 0.27
    vdc_base_pu_topology1: float = 1.0
    vdc_base_pu_topology2: float = 1.0
    energy_q_gain: float = 0.04
    energy_d_gain: float = 0.10
    reg_dc_cost: float = 0.23
    energy_q_dc_cost: float = 0.04
    energy_d_dc_gain: float = 0.15
    load_dc_cost: float = 0.025
    action_slew_weight: float = 0.03
    sag_entry: float = 0.92
    sag_exit: float = 0.97
    swell_entry: float = 1.08
    swell_exit: float = 1.03
    neg_seq_entry: float = 0.04
    neg_seq_exit: float = 0.025
    recovery_hold_s: float = 0.08
    fault_time_norm_s: float = 0.50
    recovery_time_norm_s: float = 0.50
    derivative_norm: float = 50.0
    dynamic_reg_limit_topology1: float = 0.80
    dynamic_reg_limit_topology2: float = 0.60
    topology2_dynamic_soft_reg_limit: float = 0.25
    topology2_dynamic_stress_weight: float = 35.0
    topology2_dynamic_slew_weight: float = 8.0
    recovery_action_reward_weight: float = 0.0
    recovery_reg_action_limit: float = 0.18
    recovery_energy_action_limit: float = 0.20
    recovery_vdc_high_reward_weight: float = 0.0
    recovery_vdc_high_limit_pu: float = 1.20
    recovery_energy_overshoot_gain: float = 0.0
    recovery_energy_overshoot_threshold: float = 0.10
    grid_reactive_tolerance_pu: float = 0.12
    grid_reactive_delay_s: float = 0.06
    grid_reactive_iq_limit_pu: float = 0.30
    grid_current_limit_pu: float = 1.50
    grid_reactive_reward_weight: float = 40.0
    grid_current_reward_weight: float = 50.0
    grid_wrong_sign_reward_weight: float = 8.0
    voltage_wrong_sign_reward_weight: float = 80.0
    vdc_soft_reward_weight: float = 55.0
    vdc_bounds_reward_weight: float = 0.0
    vdc_margin_reward_weight: float = 0.0
    vdc_margin_pu: float = 0.05
    vdc_lower_barrier_reward_weight: float = 0.0
    vdc_lower_barrier_start_pu: float = 0.84
    vdc_lower_barrier_floor_pu: float = 0.8125
    vdc_low_terminal_enable: bool = False
    vdc_low_terminal_pu: float = 0.8125
    vdc_low_terminal_penalty: float = 0.0
    grid_current_margin_reward_weight: float = 0.0
    grid_current_margin_pu: float = 0.05
    lv_margin_reward_weight: float = 0.0
    lv_margin_pu: float = 0.02
    proxy_vdc_reward_downshift_pu: float = 0.0
    proxy_grid_current_reward_upshift_pu: float = 0.0
    envelope_reward_weight: float = 260.0
    envelope_terminal: bool = False
    envelope_tolerance_pu: float = DEFAULT_SOLVER_TOL_PU
    fault_settle_s: float = 0.0
    calibrated_survival_reward_weight: float = 140.0
    calibration_ood_reward_weight: float = 220.0
    calibration_ood_violation_reward_cap: float = 4.0
    reward_scale: float = 1.0
    action_projection_enable: bool = False
    safety_classifier_path: str = ""
    safety_penalty_weight: float = 8.0
    safety_unsafe_terminal: bool = False
    teacher_prior_weight: float = 0.0
    target_gate: str = "L1"
    l1_current_limit_required: bool = True
    hybrid_dc_channel_enable: bool = False
    hybrid_dc_model_path: str = ""
    hybrid_dc_fault_pu_max: float = 0.85
    hybrid_dc_duration_ms_min: float = 100.0
    hybrid_dc_duration_ms_max: float = 180.0
    slow_state_correction_enable: bool = False
    slow_state_correction_path: str = ""
    slow_state_correction_fault_pu_max: float = 0.85
    slow_state_correction_duration_ms_min: float = 100.0
    slow_state_correction_duration_ms_max: float = 180.0


@lru_cache(maxsize=4)
def _load_proxy_calibration(path: str) -> dict:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("schema") != "hpt_proxy_calibration_v1":
        return {}
    return data


@lru_cache(maxsize=4)
def _load_safety_classifier(path: str) -> dict:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    data = joblib.load(p)
    if data.get("schema") != "hpt-safety-classifier-v1":
        return {}
    return data


def classify_hpt_operating_condition(
    v_pos_pu: float,
    v_neg_pu: float,
    *,
    grid_pu: float | None = None,
    config: HPTVoltageEnvConfig | None = None,
) -> str:
    """Online-friendly HPT condition classifier used by the proxy.

    The classifier uses measured positive/negative sequence voltage and, in
    the proxy only, the known source-voltage profile.  The deployed Simulink
    controller still uses measured voltage features only.
    """

    cfg = config or HPTVoltageEnvConfig()
    if v_neg_pu > cfg.neg_seq_entry:
        if grid_pu is not None and grid_pu > cfg.swell_entry:
            return "asymmetric_swell"
        return "asymmetric_sag"
    probe = float(grid_pu) if grid_pu is not None else float(v_pos_pu)
    if probe < cfg.sag_entry:
        return "sag"
    if probe > cfg.swell_entry:
        return "swell"
    return "nominal"


def _has_numeric_key(row: dict, key: str) -> bool:
    if key not in row or row.get(key) in ("", None):
        return False
    try:
        return bool(np.isfinite(float(row[key])))
    except (TypeError, ValueError):
        return False


def _axis_key(table: list[dict], preferred: str, fallback: str) -> str:
    if any(_has_numeric_key(row, preferred) for row in table):
        return preferred
    return fallback


def _row_numeric(row: dict, preferred: str, fallback: str, default: float = 0.0) -> float:
    if _has_numeric_key(row, preferred):
        return float(row[preferred])
    if _has_numeric_key(row, fallback):
        return float(row[fallback])
    return float(default)


def _interp_response_table(
    table: list[dict],
    grid_pu: float,
    reg_d: float,
    value_key: str,
) -> float | None:
    if not table:
        return None

    grids = sorted({float(row["grid_pu"]) for row in table})
    values_by_grid: list[float] = []
    for grid in grids:
        bucket: dict[float, list[float]] = {}
        for row in table:
            if abs(float(row["grid_pu"]) - grid) > 1e-9:
                continue
            if not _has_numeric_key(row, value_key):
                continue
            axis_key = _axis_key(table, "cmd_m_reg_d", "reg_d_mean")
            if not _has_numeric_key(row, axis_key):
                continue
            x = float(row[axis_key])
            bucket.setdefault(x, []).append(float(row[value_key]))
        if not bucket:
            return None
        xs = np.asarray(sorted(bucket), dtype=float)
        ys = np.asarray([np.mean(bucket[float(x)]) for x in xs], dtype=float)
        if float(reg_d) < float(xs[0]) - _INTERP_EPS or float(reg_d) > float(xs[-1]) + _INTERP_EPS:
            return None
        values_by_grid.append(float(np.interp(float(reg_d), xs, ys)))

    return _conservative_grid_interp(
        float(grid_pu),
        np.asarray(grids, dtype=float),
        np.asarray(values_by_grid, dtype=float),
        value_key,
    )


def _interp_energy_axis(
    table: list[dict],
    grid_pu: float,
    action_value: float,
    axis_key: str,
    other_axis_key: str,
    value_key: str,
) -> float | None:
    if not table:
        return None

    grids = sorted({float(row["grid_pu"]) for row in table})
    values_by_grid: list[float] = []
    for grid in grids:
        bucket: dict[float, list[float]] = {}
        for row in table:
            if abs(float(row["grid_pu"]) - grid) > 1e-9:
                continue
            if not _has_numeric_key(row, other_axis_key):
                continue
            if abs(float(row[other_axis_key])) > 1e-6:
                continue
            if not _has_numeric_key(row, value_key):
                continue
            x = float(row[axis_key])
            bucket.setdefault(x, []).append(float(row[value_key]))
        if not bucket:
            return None
        xs = np.asarray(sorted(bucket), dtype=float)
        ys = np.asarray([np.mean(bucket[float(x)]) for x in xs], dtype=float)
        if float(action_value) < float(xs[0]) - _INTERP_EPS or float(action_value) > float(xs[-1]) + _INTERP_EPS:
            return None
        values_by_grid.append(float(np.interp(float(action_value), xs, ys)))

    return _conservative_grid_interp(
        float(grid_pu),
        np.asarray(grids, dtype=float),
        np.asarray(values_by_grid, dtype=float),
        value_key,
    )


def _interp_energy_response(
    table: list[dict],
    grid_pu: float,
    energy_d: float,
    energy_q: float,
    value_key: str,
) -> float | None:
    d_key = _axis_key(table, "cmd_m_energy_d", "energy_d_mean")
    q_key = _axis_key(table, "cmd_m_energy_q", "energy_q_mean")
    coupled = _interp_grid_axes_table(
        table,
        grid_pu,
        [d_key, q_key],
        [energy_d, energy_q],
        value_key,
    )
    if coupled is not None:
        return coupled

    baseline = _interp_energy_axis(
        table, grid_pu, 0.0, d_key, q_key, value_key
    )
    d_axis = _interp_energy_axis(
        table, grid_pu, energy_d, d_key, q_key, value_key
    )
    q_axis = _interp_energy_axis(
        table, grid_pu, energy_q, q_key, d_key, value_key
    )
    if baseline is None or d_axis is None or q_axis is None:
        return None
    return float(baseline + (d_axis - baseline) + (q_axis - baseline))


def _interp_axes(rows: list[dict], axis_keys: list[str], axis_values: list[float], value_key: str) -> float | None:
    if not rows:
        return None
    if not axis_keys:
        vals = [float(row[value_key]) for row in rows if _has_numeric_key(row, value_key)]
        if not vals:
            return None
        return float(np.mean(vals))

    axis_key = axis_keys[0]
    target = float(axis_values[0])
    bucket: dict[float, list[dict]] = {}
    for row in rows:
        if not _has_numeric_key(row, axis_key):
            continue
        bucket.setdefault(float(row[axis_key]), []).append(row)
    if not bucket:
        return None

    xs: list[float] = []
    ys: list[float] = []
    for x in sorted(bucket):
        value = _interp_axes(bucket[x], axis_keys[1:], axis_values[1:], value_key)
        if value is None:
            continue
        xs.append(float(x))
        ys.append(float(value))
    if not xs:
        return None
    if target < min(xs) - _INTERP_EPS or target > max(xs) + _INTERP_EPS:
        return None
    return float(np.interp(target, np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)))


def _interp_grid_axes_table(
    table: list[dict],
    grid_pu: float,
    axis_keys: list[str],
    axis_values: list[float],
    value_key: str,
) -> float | None:
    if not table:
        return None
    grids = sorted({float(row["grid_pu"]) for row in table if "grid_pu" in row})
    if not grids:
        return None
    xs: list[float] = []
    ys: list[float] = []
    for grid in grids:
        rows = [row for row in table if abs(float(row["grid_pu"]) - grid) <= 1e-9]
        value = _interp_axes(rows, axis_keys, axis_values, value_key)
        if value is None:
            continue
        xs.append(float(grid))
        ys.append(float(value))
    if not xs:
        return None
    if float(grid_pu) < min(xs) - _INTERP_EPS or float(grid_pu) > max(xs) + _INTERP_EPS:
        return None
    return _conservative_grid_interp(
        float(grid_pu),
        np.asarray(xs, dtype=float),
        np.asarray(ys, dtype=float),
        value_key,
    )


def _neg_seq_for_fault(fault_type: str, target: float) -> float:
    depth = abs(1.0 - target)
    if fault_type in {"1ph_g", "swell_1ph"}:
        return min(0.18, 0.33 * depth)
    if fault_type in {"2ph", "swell_2ph"}:
        return min(0.14, 0.25 * depth)
    if fault_type == "2ph_g":
        return min(0.16, 0.28 * depth)
    return 0.0


def _phase_key_for_fault_type(fault_type: str) -> str:
    ft = str(fault_type).lower()
    if ft in {"1ph_g", "swell_1ph", "a_phase", "a_lvrt", "a_hvrt"}:
        return "a"
    if ft in {"2ph", "2ph_g", "ab_phase", "ab_lvrt", "ab_hvrt"}:
        return "ab"
    if ft in {"bc_phase", "bc_lvrt", "bc_hvrt"}:
        return "bc"
    if ft in {"ca_phase", "ca_lvrt", "ca_hvrt"}:
        return "ca"
    return "abc"


def _finite_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(out):
        return None
    return out


def _conservative_grid_interp(grid_pu: float, xs: np.ndarray, ys: np.ndarray, value_key: str) -> float:
    """Interpolate grid-voltage tables without smoothing DC-collapse edges."""

    target = float(grid_pu)
    if len(xs) <= 1:
        return float(ys[0])
    exact = np.where(np.isclose(xs, target, atol=_INTERP_EPS, rtol=0.0))[0]
    if exact.size:
        return float(ys[int(exact[0])])
    upper = int(np.searchsorted(xs, target, side="right"))
    lower = max(0, upper - 1)
    upper = min(len(xs) - 1, upper)
    if lower == upper:
        return float(ys[lower])
    y0 = float(ys[lower])
    y1 = float(ys[upper])
    if value_key.startswith("vdc_") and ((y0 < _VDC_COLLAPSE_PU) != (y1 < _VDC_COLLAPSE_PU)):
        if value_key in _HIGH_IS_BAD_METRIC_KEYS:
            return max(y0, y1)
        return min(y0, y1)
    return float(np.interp(target, xs, ys))


def default_hpt_voltage_scenarios() -> list[HPTVoltageScenario]:
    """Return a mixed topology/FRT curriculum inspired by the main FRT SAC.

    Coverage includes steady regulation, LVRT residual-voltage bins, HVRT swell
    bins, asymmetric negative-sequence cases, weak/strong grid proxies, and
    short/long fault durations.
    """

    scenarios: list[HPTVoltageScenario] = []
    lvrt_types = ("sym3ph", "1ph_g", "2ph", "2ph_g")
    hvrt_types = ("swell_3ph", "swell_1ph")
    lvrt_residuals = (0.20, 0.50, 0.75, 0.85, 0.90)
    hvrt_levels = (1.10, 1.20, 1.25, 1.30)
    durations = (0.12, 0.25)
    grid_strengths = (("weak", 3.0, 1.08), ("strong", 10.0, 0.92))

    for topology in ("topology1", "topology2"):
        for grid_pu in (0.90, 1.00, 1.10):
            scenarios.append(
                HPTVoltageScenario(
                    topology=topology,
                    grid_pu=grid_pu,
                    duration_s=0.22,
                    category="steady",
                    fault_type="steady",
                )
            )

        for fault_type in lvrt_types:
            for target in lvrt_residuals:
                for duration in durations:
                    for _grid_name, scr, load_pu in grid_strengths:
                        scenarios.append(
                            HPTVoltageScenario(
                                topology=topology,
                                grid_pu=target,
                                neg_seq_pu=_neg_seq_for_fault(fault_type, target),
                                fault_phase_key=_phase_key_for_fault_type(fault_type),
                                duration_s=0.08 + duration + 0.16,
                                load_pu=load_pu,
                                category="LVRT",
                                fault_type=fault_type,
                                fault_start_s=0.04,
                                fault_duration_s=duration,
                                scr=scr,
                            )
                        )

        for fault_type in hvrt_types:
            for target in hvrt_levels:
                for duration in durations:
                    for _grid_name, scr, load_pu in grid_strengths:
                        scenarios.append(
                            HPTVoltageScenario(
                                topology=topology,
                                grid_pu=target,
                                neg_seq_pu=_neg_seq_for_fault(fault_type, target),
                                fault_phase_key=_phase_key_for_fault_type(fault_type),
                                duration_s=0.08 + duration + 0.16,
                                load_pu=load_pu,
                                category="HVRT",
                                fault_type=fault_type,
                                fault_start_s=0.04,
                                fault_duration_s=duration,
                                scr=scr,
                            )
                        )
    return scenarios


class HPTOnlineFaultDetector:
    """Online detector using only measured sequence voltage and local time."""

    def __init__(self, cfg: HPTVoltageEnvConfig) -> None:
        self.cfg = cfg
        self.reset()

    def reset(self) -> None:
        self.fault_active = False
        self.recovery_active = False
        self.onset_t = 0.0
        self.clear_t = 0.0
        self.v_fault_min = 1.0
        self.v_fault_max = 1.0
        self.prev_v_pos: float | None = None
        self.prev_vdc: float | None = None
        self.dv_pos_dt = 0.0
        self.d_vdc_dt = 0.0

    def update(self, t: float, v_pos: float, v_neg: float, vdc: float, dt: float) -> None:
        cfg = self.cfg
        if self.prev_v_pos is None:
            self.dv_pos_dt = 0.0
            self.d_vdc_dt = 0.0
        else:
            self.dv_pos_dt = (v_pos - self.prev_v_pos) / max(dt, 1e-9)
            self.d_vdc_dt = (vdc - self.prev_vdc) / max(dt, 1e-9)
        self.prev_v_pos = float(v_pos)
        self.prev_vdc = float(vdc)

        measured_fault = (
            v_pos < cfg.sag_entry or v_pos > cfg.swell_entry or v_neg > cfg.neg_seq_entry
        )
        normal_band = (
            cfg.sag_exit <= v_pos <= cfg.swell_exit and v_neg <= cfg.neg_seq_exit
        )

        if measured_fault:
            if not self.fault_active:
                self.onset_t = float(t)
                self.v_fault_min = float(v_pos)
                self.v_fault_max = float(v_pos)
            self.fault_active = True
            self.recovery_active = False
            self.v_fault_min = min(self.v_fault_min, float(v_pos))
            self.v_fault_max = max(self.v_fault_max, float(v_pos))
            return

        if self.fault_active and normal_band:
            self.fault_active = False
            self.recovery_active = True
            self.clear_t = float(t)
            return

        if self.fault_active:
            return

        if self.recovery_active and normal_band and (t - self.clear_t) >= cfg.recovery_hold_s:
            self.recovery_active = False
            self.v_fault_min = 1.0
            self.v_fault_max = 1.0

    def features(self, t: float) -> tuple[float, float, float, float, float, float, float, float]:
        cfg = self.cfg
        t_recovery = (t - self.clear_t) if self.recovery_active else 0.0
        t_fault = (t - self.onset_t) if self.fault_active else 0.0
        return (
            float(self.fault_active),
            float(self.recovery_active),
            min(1.0, max(0.0, t_fault / max(cfg.fault_time_norm_s, 1e-9))),
            min(1.0, max(0.0, t_recovery / max(cfg.recovery_time_norm_s, 1e-9))),
            self.v_fault_min,
            self.v_fault_max,
            self.dv_pos_dt / max(cfg.derivative_norm, 1e-9),
            self.d_vdc_dt / max(cfg.derivative_norm, 1e-9),
        )


class HPTVoltageSACEnv(gym.Env):
    """Fast averaged HPT voltage-regulation and transition environment."""

    metadata = {"render_modes": []}

    def __init__(
        self,
        scenarios: Iterable[HPTVoltageScenario] | None = None,
        *,
        config: HPTVoltageEnvConfig | None = None,
        seed: int = 0,
        train_mode: bool = True,
    ) -> None:
        super().__init__()
        self.config = config or HPTVoltageEnvConfig()
        normalize_target_gate(self.config.target_gate, trainable_only=True)
        self._calibration = (
            _load_proxy_calibration(self.config.calibration_path)
            if self.config.use_switch_calibration
            else {}
        )
        self._safety_classifier = _load_safety_classifier(self.config.safety_classifier_path)
        self._hybrid_dc_channel = self._load_hybrid_dc_channel()
        self._slow_state_correction = self._load_slow_state_correction()
        self.scenarios = list(scenarios or default_hpt_voltage_scenarios())
        if not self.scenarios:
            raise ValueError("HPTVoltageSACEnv requires at least one scenario")
        self.rng = np.random.default_rng(seed)
        self.train_mode = train_mode
        low = np.array(
            [
                -self.config.reg_d_limit,
                -self.config.reg_q_limit,
                -self.config.energy_d_limit,
                -self.config.energy_q_limit,
            ],
            dtype=np.float32,
        )
        high = -low
        self.action_space = spaces.Box(low=low, high=high, dtype=np.float32)
        self.observation_space = spaces.Box(-5.0, 5.0, shape=(OBS_DIM_HPT,), dtype=np.float32)
        self._scenario_index = 0
        self._sc = self.scenarios[0]
        self._last_action = np.zeros(ACT_DIM_HPT, dtype=np.float32)
        self._detector = HPTOnlineFaultDetector(self.config)
        self._calibrated_metric_cache: dict[tuple, float | None] = {}
        self._reset_states()

    def _load_hybrid_dc_channel(self) -> HybridDCLinkChannel | None:
        if not self.config.hybrid_dc_channel_enable:
            return None
        if not self.config.hybrid_dc_model_path:
            raise ValueError("hybrid_dc_channel_enable=True requires hybrid_dc_model_path")
        return HybridDCLinkChannel(
            self.config.hybrid_dc_model_path,
            fault_pu_max=self.config.hybrid_dc_fault_pu_max,
            duration_ms_min=self.config.hybrid_dc_duration_ms_min,
            duration_ms_max=self.config.hybrid_dc_duration_ms_max,
        )

    def _load_slow_state_correction(self) -> SlowStateProfileCorrection | None:
        if not self.config.slow_state_correction_enable:
            return None
        if not self.config.slow_state_correction_path:
            raise ValueError(
                "slow_state_correction_enable=True requires slow_state_correction_path"
            )
        return SlowStateProfileCorrection(
            self.config.slow_state_correction_path,
            fault_pu_max=self.config.slow_state_correction_fault_pu_max,
            duration_ms_min=self.config.slow_state_correction_duration_ms_min,
            duration_ms_max=self.config.slow_state_correction_duration_ms_max,
        )

    def _reset_states(self) -> None:
        self.t = 0.0
        self.v_lv = 1.0
        self.v_pos = 1.0
        self.v_neg = 0.0
        self.vdc = 1.0
        self.energy_id = 0.0
        self.energy_iq = 0.0
        self.grid_vpos_pu = 1.0
        self.grid_id_pu = 0.0
        self.grid_iq_pu = 0.0
        self.grid_iq_ref_pu = 0.0
        self.grid_iq_shortfall_pu = 0.0
        self.grid_reactive_wrong_sign = False
        self.grid_current_peak_pu = 0.0
        self.episode_grid_current_peak_pu = 0.0
        self.episode_vdc_min_pu = 1.0
        self.episode_vdc_max_pu = 1.0
        self.episode_action_max_abs = 0.0
        self.envelope_violation_max_pu = 0.0
        self.load_quality_violation_max_pu = 0.0
        self.envelope_violation_duration_s = 0.0
        self.fault_band_violation_max_pu = 0.0
        self.fault_band_violation_duration_s = 0.0
        self.recovery_violation_max_pu = 0.0
        self.recovery_violation_duration_s = 0.0
        self._calibrated_metric_cache.clear()
        self._detector.reset()

    def reset(self, *, seed: int | None = None, options=None):
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        if self.train_mode:
            self._sc = self.scenarios[int(self.rng.integers(0, len(self.scenarios)))]
        else:
            self._sc = self.scenarios[self._scenario_index % len(self.scenarios)]
            self._scenario_index += 1
        self._last_action = np.zeros(ACT_DIM_HPT, dtype=np.float32)
        self._reset_states()
        grid_now, neg_now = self._grid_profile(self.t)
        if float(self._sc.fault_start_s) > 0.0:
            self.v_lv = float(self._sc.pre_fault_pu)
        else:
            calibrated_lv = self._calibrated_lv_target(grid_now, 0.0)
            self.v_lv = calibrated_lv if calibrated_lv is not None else self._source_base_voltage(grid_now)
        self.v_pos = self.v_lv
        self.v_neg = neg_now
        self._detector.update(self.t, grid_now, neg_now, self.vdc, self.config.dt)
        return self._obs(), {}

    def _fault_duration(self) -> float:
        if self._sc.fault_duration_s is not None:
            return float(self._sc.fault_duration_s)
        return max(0.0, float(self._sc.duration_s) - float(self._sc.fault_start_s))

    def _grid_profile(self, t: float) -> tuple[float, float]:
        sc = self._sc
        start = float(sc.fault_start_s)
        end = start + self._fault_duration()
        if t < start:
            return float(sc.pre_fault_pu), 0.0
        if t <= end:
            return float(sc.grid_pu), float(sc.neg_seq_pu)

        tau = max(float(sc.recovery_tau_s), 1e-9)
        w = 1.0 - float(np.exp(-(t - end) / tau))
        grid = float(sc.grid_pu) + (float(sc.post_fault_pu) - float(sc.grid_pu)) * w
        neg = float(sc.neg_seq_pu) * float(np.exp(-(t - end) / tau))
        return grid, neg

    def _reg_gain(self) -> float:
        cal = self._topology_calibration()
        if self._topology_name() == "topology2":
            default = self.config.reg_gain_topology2
        else:
            default = self.config.reg_gain_topology1
        if cal:
            return float(cal.get("reg_gain", default))
        return default

    def _topology_name(self) -> str:
        return self._sc.topology.lower()

    def _topology_calibration(self) -> dict:
        topologies = self._calibration.get("topologies", {})
        return dict(topologies.get(self._topology_name(), {}))

    def _source_base_voltage(self, grid_pu: float) -> float:
        cal = self._topology_calibration()
        if self._topology_name() == "topology2":
            default_gain = self.config.source_gain_topology2
            default_bias = self.config.source_bias_topology2
        else:
            default_gain = self.config.source_gain_topology1
            default_bias = self.config.source_bias_topology1
        if cal:
            default_gain = float(cal.get("source_gain", default_gain))
            default_bias = float(cal.get("source_bias", default_bias))
        return default_gain * float(grid_pu) + default_bias

    def _vdc_base_pu(self) -> float:
        cal = self._topology_calibration()
        if cal:
            return float(cal.get("vdc_base_pu", 1.0))
        if self._topology_name() == "topology2":
            return self.config.vdc_base_pu_topology2
        return self.config.vdc_base_pu_topology1

    def _reg_dc_cost(self) -> float:
        cal = self._topology_calibration()
        if cal:
            return float(cal.get("vdc_reg_abs_cost", self.config.reg_dc_cost))
        return self.config.reg_dc_cost

    def _filtered_fault_rows(self, table_name: str) -> list[dict]:
        """Return switch-calibration rows for the active fault category/duration."""

        if not self._has_current_fault_calibration():
            return []
        cal = self._topology_calibration()
        if not cal:
            return []
        rows = list(cal.get(table_name, []))
        if not rows or self._sc.category == "steady":
            return rows
        category = str(self._sc.category).upper()
        rows = [
            row
            for row in rows
            if str(row.get("category", category)).upper() == category
            and self._row_matches_fault_duration(row)
        ]
        if any("fault_phase_key" in row for row in rows):
            phase = str(getattr(self._sc, "fault_phase_key", "abc") or "abc").lower()
            phase_rows = [
                row
                for row in rows
                if str(row.get("fault_phase_key", "abc")).lower() == phase
            ]
            if phase_rows:
                return phase_rows
        return rows

    def _has_current_fault_calibration(self) -> bool:
        return (
            self._calibration.get("frt_validator_schema")
            == CURRENT_FRT_VALIDATOR_SCHEMA
            and self._calibration.get("frt_calibration_status") == "current"
        )

    def _calibrated_lv_target(self, grid_pu: float, reg_d: float, reg_q: float = 0.0) -> float | None:
        cal = self._topology_calibration()
        table: list[dict] = []
        if cal:
            if self._sc.category != "steady":
                reg_table = self._filtered_fault_rows("fault_reg_response_table")
                reg_d_key = _axis_key(reg_table, "cmd_m_reg_d", "reg_d_mean")
                reg_q_key = _axis_key(reg_table, "cmd_m_reg_q", "reg_q_mean")
                value = _interp_grid_axes_table(
                    reg_table,
                    grid_pu,
                    [reg_d_key, reg_q_key],
                    [reg_d, reg_q],
                    "lv_pu_mean",
                )
                if value is not None:
                    return value
                table = self._filtered_fault_rows("fault_response_table")
            if not table:
                table = cal.get("response_table", [])
        return _interp_response_table(table, grid_pu, reg_d, "lv_pu_mean")

    def _calibrated_vdc_target(self, grid_pu: float, reg_d: float, reg_q: float = 0.0) -> float | None:
        cal = self._topology_calibration()
        table: list[dict] = []
        if cal:
            if self._sc.category != "steady":
                reg_table = self._filtered_fault_rows("fault_reg_response_table")
                reg_d_key = _axis_key(reg_table, "cmd_m_reg_d", "reg_d_mean")
                reg_q_key = _axis_key(reg_table, "cmd_m_reg_q", "reg_q_mean")
                value = _interp_grid_axes_table(
                    reg_table,
                    grid_pu,
                    [reg_d_key, reg_q_key],
                    [reg_d, reg_q],
                    "vdc_pu_mean",
                )
                if value is not None:
                    return value
                table = self._filtered_fault_rows("fault_response_table")
            if not table:
                table = cal.get("response_table", [])
        return _interp_response_table(table, grid_pu, reg_d, "vdc_pu_mean")

    def _calibrated_joint_target(
        self,
        grid_pu: float,
        reg_d: float,
        reg_q: float,
        energy_d: float,
        energy_q: float,
        value_key: str,
    ) -> float | None:
        cal = self._topology_calibration()
        if not cal or self._sc.category == "steady":
            return None
        table = self._filtered_fault_rows("fault_joint_response_table")
        return _interp_grid_axes_table(
            table,
            grid_pu,
            [
                _axis_key(table, "cmd_m_reg_d", "reg_d_mean"),
                _axis_key(table, "cmd_m_reg_q", "reg_q_mean"),
                _axis_key(table, "cmd_m_energy_d", "energy_d_mean"),
                _axis_key(table, "cmd_m_energy_q", "energy_q_mean"),
            ],
            [reg_d, reg_q, energy_d, energy_q],
            value_key,
        )

    def _calibrated_energy_target(
        self,
        grid_pu: float,
        energy_d: float,
        energy_q: float,
        value_key: str,
    ) -> float | None:
        cal = self._topology_calibration()
        table = []
        if cal:
            if self._sc.category != "steady":
                table = self._filtered_fault_rows("fault_energy_response_table")
            if not table:
                table = cal.get("energy_response_table", [])
        return _interp_energy_response(table, grid_pu, energy_d, energy_q, value_key)

    def _duration_filtered_conventional_rows(self) -> list[dict]:
        rows = self._filtered_fault_rows("fault_conventional_response_table")
        if not rows or self._sc.category == "steady":
            return []
        return rows

    def _conventional_teacher_action(self, grid_pu: float) -> np.ndarray | None:
        rows = self._duration_filtered_conventional_rows()
        if not rows:
            return None
        row = min(rows, key=lambda r: abs(float(r.get("grid_pu", grid_pu)) - float(grid_pu)))
        if abs(float(row.get("grid_pu", grid_pu)) - float(grid_pu)) > 0.051:
            return None
        return np.asarray(
            [
                _row_numeric(row, "cmd_m_reg_d", "reg_d_mean"),
                _row_numeric(row, "cmd_m_reg_q", "reg_q_mean"),
                _row_numeric(row, "cmd_m_energy_d", "energy_d_mean"),
                _row_numeric(row, "cmd_m_energy_q", "energy_q_mean"),
            ],
            dtype=np.float32,
        )

    def _nearest_conventional_fault_row(
        self,
        grid_pu: float,
        reg_d: float,
        reg_q: float,
        energy_d: float,
        energy_q: float,
        *,
        max_distance: float = 0.50,
    ) -> dict | None:
        rows = self._duration_filtered_conventional_rows()
        if not rows:
            return None

        def span(key: str, minimum: float) -> float:
            vals = [float(row[key]) for row in rows if _has_numeric_key(row, key)]
            if not vals:
                return minimum
            return max(max(vals) - min(vals), minimum)

        grid_span = min(span("grid_pu", 0.02), 0.03)
        reg_d_key = _axis_key(rows, "cmd_m_reg_d", "reg_d_mean")
        reg_q_key = _axis_key(rows, "cmd_m_reg_q", "reg_q_mean")
        energy_d_key = _axis_key(rows, "cmd_m_energy_d", "energy_d_mean")
        energy_q_key = _axis_key(rows, "cmd_m_energy_q", "energy_q_mean")
        reg_d_span = span(reg_d_key, 0.08)
        reg_q_span = span(reg_q_key, 0.05)
        energy_d_span = span(energy_d_key, 0.08)
        energy_q_span = span(energy_q_key, 0.05)

        best_row: dict | None = None
        best_distance = float("inf")
        for row in rows:
            if not _has_numeric_key(row, "grid_pu"):
                continue
            vec = np.asarray(
                [
                    (float(grid_pu) - float(row["grid_pu"])) / grid_span,
                    (float(reg_d) - _row_numeric(row, reg_d_key, "reg_d_mean")) / reg_d_span,
                    (float(reg_q) - _row_numeric(row, reg_q_key, "reg_q_mean")) / reg_q_span,
                    (float(energy_d) - _row_numeric(row, energy_d_key, "energy_d_mean")) / energy_d_span,
                    (float(energy_q) - _row_numeric(row, energy_q_key, "energy_q_mean")) / energy_q_span,
                ],
                dtype=float,
            )
            distance = float(np.linalg.norm(vec))
            if distance < best_distance:
                best_distance = distance
                best_row = row

        if best_row is None or best_distance > max_distance:
            return None
        return best_row

    def _row_matches_fault_duration(self, row: dict, *, tolerance_s: float = 2e-3) -> bool:
        duration = self._fault_duration()
        if _has_numeric_key(row, "fault_duration_s"):
            return abs(float(row["fault_duration_s"]) - duration) <= tolerance_s
        text = f"{row.get('fault', '')} {row.get('case_name', '')}"
        match = re.search(r"(\d+)\s*ms", text, flags=re.IGNORECASE)
        if match:
            return abs(float(match.group(1)) / 1000.0 - duration) <= tolerance_s
        return True

    @staticmethod
    def _row_is_voltage_survival_failure(row: dict) -> bool:
        if "voltage_survival_pass" in row:
            value = row.get("voltage_survival_pass")
            if isinstance(value, bool):
                return not value
            if str(value).strip().lower() in {"0", "0.0", "false", "no"}:
                return True
        vref = 207.0
        vdc_ref = 800.0
        checks = [
            ("lv_recovery_pu_mean", 180.0 / vref, 235.0 / vref),
            ("lv_min_pu", 180.0 / vref, float("inf")),
            ("lv_peak_pu", -float("inf"), 235.0 / vref),
            ("vdc_min_pu", 650.0 / vdc_ref, float("inf")),
            ("vdc_max_pu", -float("inf"), 1000.0 / vdc_ref),
        ]
        for key, lo, hi in checks:
            if not _has_numeric_key(row, key):
                continue
            value = float(row[key])
            if value < lo - 1e-9 or value > hi + 1e-9:
                return True
        return False

    def _nearest_failed_joint_fault_row(
        self,
        grid_pu: float,
        reg_d: float,
        reg_q: float,
        energy_d: float,
        energy_q: float,
        value_key: str,
        *,
        max_distance: float = 0.20,
    ) -> dict | None:
        cal = self._topology_calibration()
        rows = [
            row
            for row in self._filtered_fault_rows("fault_joint_response_table")
            if str(row.get("category", "")).upper() == str(self._sc.category).upper()
            and self._row_is_voltage_survival_failure(row)
            and _has_numeric_key(row, value_key)
        ]
        if not rows:
            return None

        def span(key: str, minimum: float) -> float:
            vals = [float(row[key]) for row in rows if _has_numeric_key(row, key)]
            if not vals:
                return minimum
            return max(max(vals) - min(vals), minimum)

        grid_span = span("grid_pu", 0.03)
        reg_d_key = _axis_key(rows, "cmd_m_reg_d", "reg_d_mean")
        reg_q_key = _axis_key(rows, "cmd_m_reg_q", "reg_q_mean")
        energy_d_key = _axis_key(rows, "cmd_m_energy_d", "energy_d_mean")
        energy_q_key = _axis_key(rows, "cmd_m_energy_q", "energy_q_mean")
        reg_d_span = span(reg_d_key, 0.10)
        reg_q_span = span(reg_q_key, 0.05)
        energy_d_span = span(energy_d_key, 0.06)
        energy_q_span = span(energy_q_key, 0.04)

        best_row: dict | None = None
        best_distance = float("inf")
        for row in rows:
            vec = np.asarray(
                [
                    (float(grid_pu) - _row_numeric(row, "grid_pu", "fault_pu")) / grid_span,
                    (float(reg_d) - _row_numeric(row, reg_d_key, "reg_d_mean")) / reg_d_span,
                    (float(reg_q) - _row_numeric(row, reg_q_key, "reg_q_mean")) / reg_q_span,
                    (float(energy_d) - _row_numeric(row, energy_d_key, "energy_d_mean")) / energy_d_span,
                    (float(energy_q) - _row_numeric(row, energy_q_key, "energy_q_mean")) / energy_q_span,
                ],
                dtype=float,
            )
            distance = float(np.linalg.norm(vec))
            if distance < best_distance:
                best_distance = distance
                best_row = row
        if best_row is None or best_distance > max_distance:
            return None
        return best_row

    def _calibrated_fault_metric(
        self,
        grid_pu: float,
        reg_d: float,
        reg_q: float,
        energy_d: float,
        energy_q: float,
        value_key: str,
    ) -> float | None:
        """Predict a fault-only grid metric from switch-level calibration tables."""

        cal = self._topology_calibration()
        if not cal or self._sc.category == "steady":
            return None

        mode = str(getattr(self._sc, "calibration_mode", "joint_sweep"))
        cache_key = (
            self._topology_name(),
            mode,
            value_key,
            round(float(grid_pu), 9),
            round(float(self._fault_duration()), 9),
            round(float(reg_d), 9),
            round(float(reg_q), 9),
            round(float(energy_d), 9),
            round(float(energy_q), 9),
        )
        if cache_key in self._calibrated_metric_cache:
            return self._calibrated_metric_cache[cache_key]

        def cached(value: float | None) -> float | None:
            self._calibrated_metric_cache[cache_key] = value
            return value

        def from_baseline() -> float | None:
            return _finite_or_none(
                _interp_grid_axes_table(
                    self._filtered_fault_rows("fault_baseline_table"),
                    grid_pu,
                    [],
                    [],
                    value_key,
                )
            )

        def from_conventional() -> float | None:
            row = self._nearest_conventional_fault_row(
                grid_pu, reg_d, reg_q, energy_d, energy_q
            )
            if row is None or not _has_numeric_key(row, value_key):
                return None
            return _finite_or_none(float(row[value_key]))

        def from_reg() -> float | None:
            table = self._filtered_fault_rows("fault_reg_response_table")
            value = _interp_grid_axes_table(
                table,
                grid_pu,
                [
                    _axis_key(table, "cmd_m_reg_d", "reg_d_mean"),
                    _axis_key(table, "cmd_m_reg_q", "reg_q_mean"),
                ],
                [reg_d, reg_q],
                value_key,
            )
            value = _finite_or_none(value)
            if value is not None:
                return value
            return _finite_or_none(
                _interp_response_table(
                    self._filtered_fault_rows("fault_response_table"),
                    grid_pu,
                    reg_d,
                    value_key,
                )
            )

        def from_energy() -> float | None:
            return _finite_or_none(
                _interp_energy_response(
                    self._filtered_fault_rows("fault_energy_response_table"),
                    grid_pu,
                    energy_d,
                    energy_q,
                    value_key,
                )
            )

        def from_joint() -> float | None:
            table = self._filtered_fault_rows("fault_joint_response_table")
            if value_key in {
                "lv_pu_mean",
                "lv_recovery_pu_mean",
                "lv_peak_pu",
                "lv_min_pu",
                "vdc_pu_mean",
                "vdc_min_pu",
                "vdc_max_pu",
                "grid_iq_shortfall_max_pu",
                "grid_current_peak_pu",
            }:
                failed_row = self._nearest_failed_joint_fault_row(
                    grid_pu,
                    reg_d,
                    reg_q,
                    energy_d,
                    energy_q,
                    value_key,
                )
                if failed_row is not None:
                    return _finite_or_none(float(failed_row[value_key]))
            interpolated = _finite_or_none(
                _interp_grid_axes_table(
                    table,
                    grid_pu,
                    [
                        _axis_key(table, "cmd_m_reg_d", "reg_d_mean"),
                        _axis_key(table, "cmd_m_reg_q", "reg_q_mean"),
                        _axis_key(table, "cmd_m_energy_d", "energy_d_mean"),
                        _axis_key(table, "cmd_m_energy_q", "energy_q_mean"),
                    ],
                    [reg_d, reg_q, energy_d, energy_q],
                    value_key,
                )
            )
            if interpolated is not None:
                return interpolated
            # Sparse joint-action matrices can leave holes inside the per-axis
            # min/max box.  Returning None makes those holes look artificially
            # cheap to SAC because no calibrated constraint cost is applied.
            # Use the nearest known failed response as a conservative fallback;
            # the support-distance penalty still discourages leaving sampled
            # joint-action neighborhoods.
            failed_row = self._nearest_failed_joint_fault_row(
                grid_pu,
                reg_d,
                reg_q,
                energy_d,
                energy_q,
                value_key,
                max_distance=float("inf"),
            )
            if failed_row is not None:
                return _finite_or_none(float(failed_row[value_key]))
            return None

        if mode == "baseline":
            value = from_baseline()
            if value is not None:
                return cached(value)
            return cached(from_conventional())
        if mode == "reg_sweep":
            value = from_reg()
            if value is not None:
                return cached(value)
            return cached(from_conventional())
        if mode == "energy_sweep":
            value = from_energy()
            if value is not None:
                return cached(value)
            return cached(from_conventional())
        if mode == "joint_sweep":
            value = from_joint()
            if value is not None:
                return cached(value)
            value = from_conventional()
            if value is not None:
                return cached(value)

        value = from_reg()
        if value is not None:
            return cached(value)

        value = from_energy()
        if value is not None:
            return cached(value)

        value = from_baseline()
        if value is not None:
            return cached(value)
        return cached(None)

    def _calibration_support_violation(
        self,
        reg_d: float,
        reg_q: float,
        energy_d: float,
        energy_q: float,
    ) -> float:
        """Return normalized action distance outside switch-calibrated support.

        The calibrated proxy is only trustworthy inside the fixed-action
        switch-level matrix that produced ``hpt_proxy_calibration.json``.  SAC
        can otherwise exploit optimistic extrapolation, so out-of-support
        actions are penalized and treated as unsafe by the evaluator.
        """

        cal = self._topology_calibration()
        if not cal or self._sc.category == "steady":
            return 0.0

        ranges: dict[str, list[float]] = {}
        joint_rows: list[dict] = []
        for table_name in (
            "fault_reg_response_table",
            "fault_energy_response_table",
            "fault_joint_response_table",
            "fault_conventional_response_table",
        ):
            table_rows = self._filtered_fault_rows(table_name)
            if table_name in {"fault_joint_response_table", "fault_conventional_response_table"}:
                joint_rows.extend(table_rows)
            for row in table_rows:
                for key in (
                    "cmd_m_reg_d",
                    "cmd_m_reg_q",
                    "cmd_m_energy_d",
                    "cmd_m_energy_q",
                    "reg_d_mean",
                    "reg_q_mean",
                    "energy_d_mean",
                    "energy_q_mean",
                ):
                    if _has_numeric_key(row, key):
                        ranges.setdefault(key, []).append(float(row[key]))

        def excess(key: str, value: float) -> float:
            vals = ranges.get(key, [])
            if not vals:
                return 0.0
            lo = min(vals)
            hi = max(vals)
            raw_span = hi - lo
            if raw_span <= 1e-6 and abs(value - lo) <= 1e-3:
                return 0.0
            span = max(raw_span, 1e-6)
            if value < lo - _INTERP_EPS:
                return (lo - value) / span
            if value > hi + _INTERP_EPS:
                return (value - hi) / span
            return 0.0

        terms = [
            excess("cmd_m_reg_d" if ranges.get("cmd_m_reg_d") else "reg_d_mean", float(reg_d)),
            excess("cmd_m_reg_q" if ranges.get("cmd_m_reg_q") else "reg_q_mean", float(reg_q)),
            excess("cmd_m_energy_d" if ranges.get("cmd_m_energy_d") else "energy_d_mean", float(energy_d)),
            excess("cmd_m_energy_q" if ranges.get("cmd_m_energy_q") else "energy_q_mean", float(energy_q)),
        ]
        box_violation = float(np.linalg.norm(np.asarray(terms, dtype=float)))

        # Axis-aligned ranges are insufficient for sparse full-action data: a
        # cross-combination may lie inside every axis range while being far
        # from every action that was actually run in Simulink.  Measure the
        # distance to the sampled 4-D joint-action cloud as well.
        action_keys = (
            ("cmd_m_reg_d", "reg_d_mean"),
            ("cmd_m_reg_q", "reg_q_mean"),
            ("cmd_m_energy_d", "energy_d_mean"),
            ("cmd_m_energy_q", "energy_q_mean"),
        )
        samples: list[list[float]] = []
        for row in joint_rows:
            values = [_row_numeric(row, primary, fallback) for primary, fallback in action_keys]
            if np.all(np.isfinite(values)):
                samples.append(values)
        if not samples:
            return box_violation

        sample_array = np.asarray(samples, dtype=float)
        query = np.asarray([reg_d, reg_q, energy_d, energy_q], dtype=float)
        spans = np.maximum(
            np.ptp(sample_array, axis=0),
            np.asarray([0.08, 0.05, 0.08, 0.10], dtype=float),
        )
        nearest_distance = float(np.min(np.linalg.norm((sample_array - query) / spans, axis=1)))
        joint_radius = 0.35
        joint_violation = max(0.0, nearest_distance - joint_radius)
        return max(box_violation, joint_violation)

    def _grid_iq_reference(self, vpos_pu: float) -> float:
        limit = float(self.config.grid_reactive_iq_limit_pu)
        if vpos_pu < 0.9:
            return float(min(limit, 1.5 * (0.9 - vpos_pu)))
        if vpos_pu > 1.1:
            return float(max(-limit, -1.5 * (vpos_pu - 1.1)))
        return 0.0

    def _estimate_grid_metrics(
        self,
        grid_pu: float,
        m_reg_d: float,
        m_reg_q: float,
        m_energy_d: float,
        m_energy_q: float,
    ) -> dict[str, float | bool]:
        """Estimate the evaluator's grid-current/FRT metrics inside the proxy."""

        cfg = self.config
        vpos = self._calibrated_fault_metric(
            grid_pu, m_reg_d, m_reg_q, m_energy_d, m_energy_q, "grid_vpos_pu_mean"
        )
        if vpos is None:
            vpos = float(grid_pu)

        iq_ref = self._calibrated_fault_metric(
            grid_pu, m_reg_d, m_reg_q, m_energy_d, m_energy_q, "grid_iq_ref_mean_pu"
        )
        if iq_ref is None:
            iq_ref = self._grid_iq_reference(vpos)

        iq = self._calibrated_fault_metric(
            grid_pu, m_reg_d, m_reg_q, m_energy_d, m_energy_q, "grid_iq_mean_pu"
        )
        if iq is None:
            direction = 1.0 if vpos < 0.9 else (-1.0 if vpos > 1.1 else 0.0)
            directed_reg = max(0.0, direction * m_reg_d) if direction else 0.0
            support_mag = min(
                cfg.grid_reactive_iq_limit_pu,
                0.28 * directed_reg + 0.12 * abs(m_reg_q) + 0.05 * abs(m_energy_q),
            )
            iq = direction * support_mag

        shortfall = self._calibrated_fault_metric(
            grid_pu,
            m_reg_d,
            m_reg_q,
            m_energy_d,
            m_energy_q,
            "grid_iq_shortfall_max_pu",
        )
        if shortfall is None:
            tol = float(cfg.grid_reactive_tolerance_pu)
            if iq_ref > tol:
                shortfall = max(0.0, (iq_ref - tol) - iq)
            elif iq_ref < -tol:
                shortfall = max(0.0, iq - (iq_ref + tol))
            else:
                shortfall = 0.0

        wrong_sign_metric = self._calibrated_fault_metric(
            grid_pu, m_reg_d, m_reg_q, m_energy_d, m_energy_q, "grid_iq_wrong_sign"
        )
        if wrong_sign_metric is None:
            wrong_sign = bool((vpos < 0.9 and iq < -1e-3) or (vpos > 1.1 and iq > 1e-3))
        else:
            wrong_sign = bool(wrong_sign_metric >= 0.5)

        current = self._calibrated_fault_metric(
            grid_pu, m_reg_d, m_reg_q, m_energy_d, m_energy_q, "grid_current_peak_pu"
        )
        if current is None:
            load_current = float(self._sc.load_pu) / max(abs(vpos), 0.25)
            action_current = 0.08 * abs(m_reg_d) + 0.04 * abs(m_reg_q) + 0.04 * float(
                np.hypot(m_energy_d, m_energy_q)
            )
            current = float(np.hypot(load_current, iq) + action_current)

        self.grid_vpos_pu = float(vpos)
        self.grid_id_pu = float(
            self._calibrated_fault_metric(
                grid_pu, m_reg_d, m_reg_q, m_energy_d, m_energy_q, "grid_id_mean_pu"
            )
            or 0.0
        )
        self.grid_iq_pu = float(iq)
        self.grid_iq_ref_pu = float(iq_ref)
        self.grid_iq_shortfall_pu = float(max(0.0, shortfall))
        self.grid_reactive_wrong_sign = bool(wrong_sign)
        self.grid_current_peak_pu = float(max(0.0, current))
        return {
            "vpos": self.grid_vpos_pu,
            "iq": self.grid_iq_pu,
            "iq_ref": self.grid_iq_ref_pu,
            "shortfall": self.grid_iq_shortfall_pu,
            "wrong_sign": self.grid_reactive_wrong_sign,
            "current_peak": self.grid_current_peak_pu,
        }

    def _obs(self) -> np.ndarray:
        cfg = self.config
        grid_now, neg_now = self._grid_profile(self.t)
        v_err = 1.0 - self.v_lv
        vdc_err = 1.0 - self.vdc
        topology1_flag = 1.0 if self._topology_name() == "topology1" else 0.0
        topology2_flag = 1.0 if self._topology_name() == "topology2" else 0.0
        obs = np.array(
            [
                self.v_lv,
                grid_now,
                neg_now,
                self.vdc,
                vdc_err,
                v_err,
                self.energy_id,
                self.energy_iq,
                *self._last_action,
                float(grid_now < cfg.sag_entry),
                float(grid_now > cfg.swell_entry),
                topology1_flag,
                topology2_flag,
                *self._detector.features(self.t),
            ],
            dtype=np.float32,
        )
        assert obs.shape == (OBS_DIM_HPT,), obs.shape
        return np.clip(obs, -5.0, 5.0)

    def _table_teacher_action(self, grid_pu: float) -> np.ndarray:
        """Best supported regulation command from the calibrated switch sweep.

        The table is intentionally based on switch-level fixed-action data, not
        on the learned/SAC proxy.  It gives SAC a local action prior while still
        allowing the actor to learn deviations when the reward supports them.
        """

        conventional = self._conventional_teacher_action(grid_pu)
        if conventional is not None:
            return conventional.astype(np.float32)

        candidates = np.linspace(-self.config.reg_limit, self.config.reg_limit, 81)
        best_score = float("inf")
        best_reg_d = 0.0
        if self._topology_name() == "topology2":
            lv_low, lv_high = 198.0 / 207.0, 212.0 / 207.0
            vdc_low, vdc_high = 760.0 / 800.0, 930.0 / 800.0
        else:
            lv_low, lv_high = 200.0 / 207.0, 210.0 / 207.0
            vdc_low, vdc_high = 760.0 / 800.0, 920.0 / 800.0

        for raw_reg_d in candidates:
            projected = self._project_action(
                np.asarray([raw_reg_d, 0.0, 0.0, 0.0], dtype=np.float32)
            )
            reg_d = float(projected[0])
            lv_target = self._calibrated_lv_target(grid_pu, reg_d)
            vdc_target = self._calibrated_vdc_target(grid_pu, reg_d)
            if lv_target is None:
                continue
            vdc_target = 1.0 if vdc_target is None else float(vdc_target)
            lv_penalty = max(0.0, lv_low - float(lv_target)) ** 2
            lv_penalty += max(0.0, float(lv_target) - lv_high) ** 2
            vdc_penalty = max(0.0, vdc_low - vdc_target) ** 2
            vdc_penalty += max(0.0, vdc_target - vdc_high) ** 2
            tracking_bias = 0.05 * abs(float(lv_target) - 1.0)
            dc_bias = 0.03 * abs(vdc_target - 1.0)
            action_penalty = 0.003 * abs(reg_d)
            score = 35.0 * lv_penalty + 30.0 * vdc_penalty + tracking_bias + dc_bias + action_penalty
            if score < best_score:
                best_score = score
                best_reg_d = reg_d

        if not np.isfinite(best_score):
            fallback = teacher_action(
                self._obs(),
                reg_limit=self.config.reg_limit,
                energy_limit=self.config.energy_limit,
            )
            return fallback.astype(np.float32)

        return np.asarray([best_reg_d, 0.0, 0.0, 0.0], dtype=np.float32)

    def _project_action(self, action: np.ndarray) -> np.ndarray:
        projected = np.asarray(action, dtype=np.float32).copy()
        cfg = self.config
        grid_now, _ = self._grid_profile(self.t)
        if (grid_now < cfg.sag_entry or self.v_lv < 0.98) and projected[0] < 0.0:
            projected[0] = 0.0
        elif grid_now > cfg.swell_entry and projected[0] > 0.0:
            projected[0] = 0.0

        if self.vdc < 0.95:
            projected[0] *= np.clip((self.vdc - 0.75) / 0.20, 0.0, 1.0)
            projected[2] = max(projected[2], min(cfg.energy_d_limit, 0.20 + 1.2 * (0.82 - self.vdc)))
        elif self.vdc > 1.12:
            projected[2] = min(projected[2], -0.05)
        dynamic_fault = (
            float(self._sc.fault_start_s) > 0.02
            and (self._detector.fault_active or self._detector.recovery_active)
        )
        if dynamic_fault:
            dyn_limit = (
                cfg.dynamic_reg_limit_topology2
                if self._topology_name() == "topology2"
                else cfg.dynamic_reg_limit_topology1
            )
            projected[0] = float(np.clip(projected[0], -dyn_limit, dyn_limit))
        return projected

    def _safety_feature(
        self,
        *,
        grid_pu: float,
        raw_action: np.ndarray,
        projected_action: np.ndarray,
        sweep: str,
    ) -> np.ndarray:
        names = list(self._safety_classifier.get("feature_names", []))
        values = {
            "topology1": 1.0 if self._topology_name() == "topology1" else 0.0,
            "topology2": 1.0 if self._topology_name() == "topology2" else 0.0,
            "grid_pu": float(grid_pu),
            "raw_m_reg_d": float(raw_action[0]),
            "raw_m_reg_q": float(raw_action[1]),
            "raw_m_energy_d": float(raw_action[2]),
            "raw_m_energy_q": float(raw_action[3]),
            "effective_m_reg_d": float(projected_action[0]),
            "effective_m_reg_q": float(projected_action[1]),
            "effective_m_energy_d": float(projected_action[2]),
            "effective_m_energy_q": float(projected_action[3]),
            "controller_enabled": 1.0,
            "is_reg_sweep": 1.0 if sweep == "reg" else 0.0,
            "is_energy_sweep": 1.0 if sweep == "energy" else 0.0,
            "is_fault_sweep": 1.0 if sweep == "fault" else 0.0,
        }
        return np.asarray([values.get(name, 0.0) for name in names], dtype=np.float32).reshape(1, -1)

    def _safety_score(
        self,
        *,
        grid_pu: float,
        raw_action: np.ndarray,
        projected_action: np.ndarray,
        fault_or_recovery: float,
    ) -> tuple[float, float, bool]:
        if not self._safety_classifier:
            return 1.0, 0.0, False
        clf = self._safety_classifier["classifier"]
        threshold = float(self._safety_classifier.get("safe_probability_threshold", 0.75))
        reg_mag = float(np.hypot(projected_action[0], projected_action[1]))
        energy_mag = float(np.hypot(projected_action[2], projected_action[3]))
        sweeps = ["fault"] if fault_or_recovery > 0.5 else ["reg"]
        if energy_mag > 0.05 or energy_mag >= reg_mag:
            sweeps.append("energy")
        probs = []
        for sweep in dict.fromkeys(sweeps):
            feature = self._safety_feature(
                grid_pu=grid_pu,
                raw_action=raw_action,
                projected_action=projected_action,
                sweep=sweep,
            )
            probs.append(float(clf.predict_proba(feature)[0, 1]))
        safe_probability = min(probs) if probs else 1.0
        return safe_probability, threshold, bool(safe_probability < threshold)

    def step(self, action):
        cfg = self.config
        raw_action = np.asarray(action, dtype=np.float32)
        raw_action = np.clip(raw_action, self.action_space.low, self.action_space.high)
        action = self._project_action(raw_action) if cfg.action_projection_enable else raw_action.copy()
        m_reg_d, m_reg_q, m_energy_d, m_energy_q = [float(v) for v in action]
        hybrid_dc_source = "disabled"

        grid_now, neg_now = self._grid_profile(self.t)
        calibrated_fault_case = bool(
            self._has_current_fault_calibration() and self._sc.category != "steady"
        )
        lookup_grid = float(self._sc.grid_pu) if calibrated_fault_case else float(grid_now)
        slow_state_correction_source = "disabled"
        corrected_energy_i_mag = float("nan")
        support_violation = (
            self._calibration_support_violation(m_reg_d, m_reg_q, m_energy_d, m_energy_q)
            if calibrated_fault_case
            else 0.0
        )
        support_violation_for_reward = min(
            float(support_violation),
            float(cfg.calibration_ood_violation_reward_cap),
        )
        calibrated_lv = None
        lv_mode_exact = False
        if calibrated_fault_case:
            mode_lv = self._calibrated_fault_metric(
                lookup_grid, m_reg_d, m_reg_q, m_energy_d, m_energy_q, "lv_pu_mean"
            )
            if mode_lv is not None:
                calibrated_lv = mode_lv
                lv_mode_exact = True
        if calibrated_lv is None:
            calibrated_lv = self._calibrated_lv_target(lookup_grid, m_reg_d, m_reg_q)
        load_drop = 0.010 * max(0.0, float(self._sc.load_pu) - 1.0)
        if calibrated_lv is None:
            base_lv = self._source_base_voltage(grid_now)
            reg_effect = self._reg_gain() * m_reg_d
            q_effect = 0.0 if self._calibration else cfg.energy_q_gain * m_energy_q
            calibrated_lv = base_lv + reg_effect + q_effect
        if not lv_mode_exact:
            joint_lv = self._calibrated_joint_target(
                lookup_grid, m_reg_d, m_reg_q, m_energy_d, m_energy_q, "lv_pu_mean"
            )
            joint_lv_zero = self._calibrated_joint_target(
                lookup_grid, m_reg_d, m_reg_q, 0.0, 0.0, "lv_pu_mean"
            )
            if joint_lv is not None:
                calibrated_lv = joint_lv
            elif joint_lv is not None and joint_lv_zero is not None:
                calibrated_lv += joint_lv - joint_lv_zero
            else:
                energy_lv = self._calibrated_energy_target(lookup_grid, m_energy_d, m_energy_q, "lv_pu_mean")
                energy_lv_zero = self._calibrated_energy_target(lookup_grid, 0.0, 0.0, "lv_pu_mean")
                if energy_lv is not None and energy_lv_zero is not None:
                    calibrated_lv += energy_lv - energy_lv_zero
        fault_end = float(self._sc.fault_start_s) + self._fault_duration()
        if calibrated_fault_case and self.t >= fault_end:
            recovery_lv = self._calibrated_fault_metric(
                lookup_grid,
                m_reg_d,
                m_reg_q,
                m_energy_d,
                m_energy_q,
                "lv_recovery_pu_mean",
            )
            if recovery_lv is not None:
                calibrated_lv = recovery_lv
        v_target = max(0.0, calibrated_lv - load_drop)
        v_alpha = 1.0 if calibrated_fault_case else cfg.dt / cfg.v_tau
        self.v_lv += (v_target - self.v_lv) * float(np.clip(v_alpha, 0.0, 1.0))
        self.v_pos = max(0.0, self.v_lv)
        self.v_neg += (neg_now + 0.02 * abs(m_reg_q) - self.v_neg) * (cfg.dt / cfg.v_tau)

        calibrated_i = None
        if calibrated_fault_case:
            mode_i = self._calibrated_fault_metric(
                lookup_grid,
                m_reg_d,
                m_reg_q,
                m_energy_d,
                m_energy_q,
                "energy_i_rms_mean",
            )
            if mode_i is not None:
                calibrated_i = mode_i
        if calibrated_i is None:
            calibrated_i = self._calibrated_energy_target(
                lookup_grid, m_energy_d, m_energy_q, "energy_i_rms_mean"
            )
        if calibrated_i is None:
            energy_direct_scale = 0.0 if self._calibration else 1.0
            target_energy_id = energy_direct_scale * cfg.energy_d_gain * m_energy_d
            target_energy_iq = energy_direct_scale * cfg.energy_q_gain * m_energy_q
        else:
            current_scale = 200.0
            target_energy_id = np.sign(m_energy_d) * min(2.0, abs(calibrated_i) / current_scale)
            target_energy_iq = np.sign(m_energy_q) * min(2.0, abs(calibrated_i) / current_scale)
        self.energy_id += (target_energy_id - self.energy_id) * 0.25
        self.energy_iq += (target_energy_iq - self.energy_iq) * 0.25
        calibrated_vdc = None
        vdc_mode_exact = False
        if calibrated_fault_case:
            mode_vdc = self._calibrated_fault_metric(
                lookup_grid, m_reg_d, m_reg_q, m_energy_d, m_energy_q, "vdc_pu_mean"
            )
            if mode_vdc is not None:
                calibrated_vdc = mode_vdc
                vdc_mode_exact = True
        if calibrated_vdc is None:
            calibrated_vdc = self._calibrated_vdc_target(lookup_grid, m_reg_d, m_reg_q)
        if calibrated_vdc is None:
            calibrated_vdc = (
                self._vdc_base_pu()
                - self._reg_dc_cost() * max(0.0, abs(m_reg_d))
                - 0.04 * max(0.0, 1.0 - grid_now)
            )
        if vdc_mode_exact:
            energy_direct_scale = 0.0
            energy_vdc_delta = 0.0
        else:
            joint_vdc = self._calibrated_joint_target(
                lookup_grid, m_reg_d, m_reg_q, m_energy_d, m_energy_q, "vdc_pu_mean"
            )
            joint_vdc_zero = self._calibrated_joint_target(
                lookup_grid, m_reg_d, m_reg_q, 0.0, 0.0, "vdc_pu_mean"
            )
            if joint_vdc is not None and joint_vdc_zero is not None:
                energy_direct_scale = 0.0
                energy_vdc_delta = joint_vdc - joint_vdc_zero
            elif joint_vdc is not None:
                energy_direct_scale = 0.0
                energy_vdc_delta = joint_vdc - calibrated_vdc
            else:
                energy_vdc = self._calibrated_energy_target(lookup_grid, m_energy_d, m_energy_q, "vdc_pu_mean")
                energy_vdc_zero = self._calibrated_energy_target(lookup_grid, 0.0, 0.0, "vdc_pu_mean")
                if energy_vdc is not None and energy_vdc_zero is not None:
                    energy_direct_scale = 0.0
                    energy_vdc_delta = energy_vdc - energy_vdc_zero
                else:
                    energy_direct_scale = 0.0 if self._calibration else 1.0
                    energy_vdc_delta = energy_direct_scale * cfg.energy_d_dc_gain * m_energy_d
        vdc_target = (
            calibrated_vdc
            + energy_vdc_delta
            - energy_direct_scale * cfg.energy_q_dc_cost * abs(m_energy_q)
            - cfg.load_dc_cost * max(0.0, float(self._sc.load_pu) - 1.0)
        )

        grid_metrics = self._estimate_grid_metrics(
            lookup_grid, m_reg_d, m_reg_q, m_energy_d, m_energy_q
        )

        hybrid_next_vdc = None
        if self._hybrid_dc_channel is not None and self._sc.category != "steady":
            fault_start = float(self._sc.fault_start_s)
            in_fault_window = fault_start <= self.t <= fault_end
            in_recovery_window = self.t > fault_end
            if in_fault_window or in_recovery_window:
                hybrid_next_vdc = self._hybrid_dc_channel.predict_next_vdc(
                    DCChannelInputs(
                        vdc=float(self.vdc),
                        grid_cmd=float(self._sc.pre_fault_pu),
                        grid_v_mag=float(grid_now),
                        energy_v_mag=float(max(self.v_lv, 0.0)),
                        fault_flag=1.0 if in_fault_window else 0.0,
                        recovery_flag=1.0 if in_recovery_window else 0.0,
                        time_in_fault=max(0.0, self.t - fault_start) if in_fault_window else 0.0,
                        time_in_recovery=max(0.0, self.t - fault_end) if in_recovery_window else 0.0,
                        m_reg_d=m_reg_d,
                        m_reg_q=m_reg_q,
                        m_energy_d=m_energy_d,
                        m_energy_q=m_energy_q,
                        grid_i_d=float(self.grid_id_pu),
                        grid_i_q=float(self.grid_iq_pu),
                        energy_i_d=float(self.energy_id),
                        energy_i_q=float(self.energy_iq),
                        dt=float(cfg.dt),
                        fault_pu=float(self._sc.grid_pu),
                        duration_ms=float(self._fault_duration() * 1000.0),
                    )
                )
            hybrid_dc_source = "v5_boundary_dc" if hybrid_next_vdc is not None else "v4_default_dc"
        if hybrid_next_vdc is None:
            vdc_alpha = 1.0 if calibrated_fault_case else cfg.dt / cfg.vdc_tau
            self.vdc += (vdc_target - self.vdc) * float(np.clip(vdc_alpha, 0.0, 1.0))
        else:
            self.vdc = float(hybrid_next_vdc)
        vdc_floor = 0.0 if calibrated_fault_case else 0.05
        vdc_ceiling = 2.0 if calibrated_fault_case else 1.30
        self.vdc = float(np.clip(self.vdc, vdc_floor, vdc_ceiling))

        if self._slow_state_correction is not None and self._sc.category != "steady":
            next_t = self.t + float(cfg.dt)
            correction_fault_active = float(self._sc.fault_start_s) <= next_t <= fault_end
            correction_recovery_active = next_t > fault_end
            correction = self._slow_state_correction.correct(
                SlowStateCorrectionInputs(
                    fault_pu=float(self._sc.grid_pu),
                    duration_ms=float(self._fault_duration() * 1000.0),
                    fault_flag=1.0 if correction_fault_active else 0.0,
                    recovery_flag=1.0 if correction_recovery_active else 0.0,
                    time_in_fault=max(0.0, next_t - float(self._sc.fault_start_s))
                    if correction_fault_active
                    else 0.0,
                    time_in_recovery=max(0.0, next_t - fault_end)
                    if correction_recovery_active
                    else 0.0,
                    v_lv=float(self.v_lv),
                    grid_i_mag=float(grid_metrics["current_peak"]),
                    energy_i_mag=float(np.hypot(self.energy_id, self.energy_iq)),
                    m_reg_d=float(m_reg_d),
                    m_reg_q=float(m_reg_q),
                    m_energy_d=float(m_energy_d),
                    m_energy_q=float(m_energy_q),
                )
            )
            if correction is not None:
                self.v_lv = float(max(0.0, correction["v_lv"]))
                self.v_pos = max(0.0, self.v_lv)
                grid_metrics["current_peak"] = float(max(0.0, correction["grid_i_mag"]))
                self.grid_current_peak_pu = float(grid_metrics["current_peak"])
                corrected_energy_i_mag = float(correction["energy_i_mag"])
                slow_state_correction_source = "profile_correction"
            else:
                slow_state_correction_source = "outside_gate"

        calibrated_lv_recovery = None
        calibrated_lv_peak = None
        calibrated_lv_min = None
        calibrated_vdc_min = None
        calibrated_vdc_max = None
        if calibrated_fault_case:
            calibrated_lv_recovery = self._calibrated_fault_metric(
                lookup_grid, m_reg_d, m_reg_q, m_energy_d, m_energy_q, "lv_recovery_pu_mean"
            )
            calibrated_lv_peak = self._calibrated_fault_metric(
                lookup_grid, m_reg_d, m_reg_q, m_energy_d, m_energy_q, "lv_peak_pu"
            )
            calibrated_lv_min = self._calibrated_fault_metric(
                lookup_grid, m_reg_d, m_reg_q, m_energy_d, m_energy_q, "lv_min_pu"
            )
            calibrated_vdc_min = self._calibrated_fault_metric(
                lookup_grid, m_reg_d, m_reg_q, m_energy_d, m_energy_q, "vdc_min_pu"
            )
            calibrated_vdc_max = self._calibrated_fault_metric(
                lookup_grid, m_reg_d, m_reg_q, m_energy_d, m_energy_q, "vdc_max_pu"
            )

        self.t += cfg.dt
        detector_grid, detector_neg = self._grid_profile(self.t)
        self._detector.update(self.t, detector_grid, detector_neg, self.vdc, cfg.dt)

        if self._sc.category != "steady":
            load_quality = sample_load_voltage_quality(
                t_s=self.t,
                lv_pu=self.v_lv,
                fault_start_s=float(self._sc.fault_start_s),
                fault_clear_s=fault_end,
                stop_time_s=float(self._sc.duration_s),
                tolerance_pu=float(cfg.envelope_tolerance_pu),
                fault_settle_s=float(cfg.fault_settle_s),
            )
            load_quality_violation = float(
                load_quality["load_quality_violation_max_pu"]
            )
            fault_band_violation = float(
                load_quality["fault_band_violation_max_pu"]
            )
            recovery_violation = float(
                load_quality["recovery_violation_max_pu"]
            )
            if calibrated_fault_case:
                calibrated_fault_band_violation = self._calibrated_fault_metric(
                    lookup_grid,
                    m_reg_d,
                    m_reg_q,
                    m_energy_d,
                    m_energy_q,
                    "fault_lv_band_violation_max_pu",
                )
                calibrated_recovery_violation = self._calibrated_fault_metric(
                    lookup_grid,
                    m_reg_d,
                    m_reg_q,
                    m_energy_d,
                    m_energy_q,
                    "recovery_violation_max_pu",
                )
                if calibrated_fault_band_violation is not None:
                    fault_band_violation = max(
                        fault_band_violation,
                        float(calibrated_fault_band_violation),
                    )
                if calibrated_recovery_violation is not None:
                    recovery_violation = max(recovery_violation, float(calibrated_recovery_violation))
                load_quality_violation = max(
                    fault_band_violation,
                    recovery_violation,
                )
            self.load_quality_violation_max_pu = max(
                self.load_quality_violation_max_pu,
                load_quality_violation,
            )
            # Kept as a reporting alias for old result readers.  It now means
            # project load-quality violation, never the PCC grid-code curve.
            self.envelope_violation_max_pu = max(
                self.envelope_violation_max_pu,
                load_quality_violation,
            )
            self.fault_band_violation_max_pu = max(
                self.fault_band_violation_max_pu,
                fault_band_violation,
            )
            self.recovery_violation_max_pu = max(
                self.recovery_violation_max_pu,
                recovery_violation,
            )
            if load_quality_violation > cfg.envelope_tolerance_pu:
                self.envelope_violation_duration_s += cfg.dt
            if fault_band_violation > cfg.envelope_tolerance_pu:
                self.fault_band_violation_duration_s += cfg.dt
            if recovery_violation > cfg.envelope_tolerance_pu:
                self.recovery_violation_duration_s += cfg.dt
        else:
            load_quality = {
                "load_quality_violation_max_pu": 0.0,
                "fault_band_violation_max_pu": 0.0,
                "recovery_violation_max_pu": 0.0,
                "load_quality_pass": True,
            }
            load_quality_violation = 0.0
            fault_band_violation = 0.0
            recovery_violation = 0.0

        recovery_negative_energy_mag = 0.0
        recovery_energy_overshoot_violation = 0.0
        if self._detector.recovery_active and cfg.recovery_energy_overshoot_gain > 0.0:
            recovery_negative_energy_mag = float(
                np.hypot(min(0.0, m_energy_d), min(0.0, m_energy_q))
            )
            recovery_energy_overshoot_violation = float(
                cfg.recovery_energy_overshoot_gain
                * max(
                    0.0,
                    recovery_negative_energy_mag
                    - float(cfg.recovery_energy_overshoot_threshold),
                )
            )
            recovery_violation = max(recovery_violation, recovery_energy_overshoot_violation)
            load_quality_violation = max(load_quality_violation, recovery_violation)
            self.load_quality_violation_max_pu = max(
                self.load_quality_violation_max_pu,
                load_quality_violation,
            )
            self.envelope_violation_max_pu = max(
                self.envelope_violation_max_pu,
                load_quality_violation,
            )
            self.recovery_violation_max_pu = max(
                self.recovery_violation_max_pu,
                recovery_violation,
            )
            if recovery_violation > cfg.envelope_tolerance_pu:
                self.recovery_violation_duration_s += cfg.dt

        voltage_err = self.v_lv - 1.0
        unbalance = self.v_neg
        vdc_low_limit = 0.95 if self._calibration else 0.82
        vdc_soft = max(0.0, vdc_low_limit - self.vdc) + max(0.0, self.vdc - 1.12)
        vdc_bounds_state_violation = max(0.0, 650.0 / cfg.vdc_ref - self.vdc) ** 2
        vdc_bounds_state_violation += max(0.0, self.vdc - 1000.0 / cfg.vdc_ref) ** 2
        reg_mag = float(np.hypot(m_reg_d, m_reg_q))
        energy_mag = float(np.hypot(m_energy_d, m_energy_q))
        energy_weight = 0.60 if self._calibration else 0.08
        slew = float(np.linalg.norm(action - self._last_action))
        fault_or_recovery = float(self._detector.fault_active or self._detector.recovery_active)
        if cfg.teacher_prior_weight > 0.0:
            teacher_prior = self._table_teacher_action(lookup_grid)
            teacher_delta = action - teacher_prior
            teacher_gap = float(np.dot(teacher_delta, teacher_delta))
        else:
            teacher_prior = np.zeros(ACT_DIM_HPT, dtype=np.float32)
            teacher_gap = 0.0
        safe_probability, safety_threshold, safety_unsafe = self._safety_score(
            grid_pu=grid_now,
            raw_action=raw_action,
            projected_action=action,
            fault_or_recovery=fault_or_recovery,
        )
        safety_gap = max(0.0, safety_threshold - safe_probability)
        wrong_sign = float(
            (grid_now < cfg.sag_entry and m_reg_d < -1e-4)
            or (grid_now > cfg.swell_entry and m_reg_d > 1e-4)
        )
        topology2_dynamic = float(self._topology_name() == "topology2" and fault_or_recovery > 0.5)
        topology2_reg_excess = max(0.0, abs(m_reg_d) - cfg.topology2_dynamic_soft_reg_limit)
        topology2_dynamic_stress = topology2_dynamic * (
            cfg.topology2_dynamic_stress_weight * topology2_reg_excess * topology2_reg_excess
            + cfg.topology2_dynamic_slew_weight * slew * slew
            + 2.0 * abs(m_reg_q)
        )
        recovery_active_for_reward = float(self._detector.recovery_active)
        recovery_reg_excess = recovery_active_for_reward * max(
            0.0,
            reg_mag - float(cfg.recovery_reg_action_limit),
        )
        recovery_energy_excess = recovery_active_for_reward * max(
            0.0,
            energy_mag - float(cfg.recovery_energy_action_limit),
        )
        recovery_action_violation = recovery_reg_excess * recovery_reg_excess
        recovery_action_violation += recovery_energy_excess * recovery_energy_excess
        reactive_demand = abs(float(grid_metrics["iq_ref"])) > cfg.grid_reactive_tolerance_pu
        reactive_window_ready = bool(
            self._detector.recovery_active
            or (
                self._detector.fault_active
                and (self.t - self._detector.onset_t) >= cfg.grid_reactive_delay_s
            )
        )
        reactive_assessed = bool(reactive_window_ready and reactive_demand)
        reactive_shortfall = float(grid_metrics["shortfall"]) if reactive_assessed else 0.0
        reactive_wrong_sign = float(bool(grid_metrics["wrong_sign"]) and reactive_assessed)
        grid_current_peak_for_reward = (
            float(grid_metrics["current_peak"])
            + float(cfg.proxy_grid_current_reward_upshift_pu)
        )
        grid_current_violation = max(
            0.0, grid_current_peak_for_reward - cfg.grid_current_limit_pu
        )
        self.episode_grid_current_peak_pu = max(
            self.episode_grid_current_peak_pu,
            grid_current_peak_for_reward,
        )
        lv_fault_for_bounds = self.v_lv
        lv_recovery_for_bounds = (
            float(calibrated_lv_recovery)
            if calibrated_lv_recovery is not None
            else self.v_lv
        )
        lv_peak_for_bounds = (
            float(calibrated_lv_peak)
            if calibrated_lv_peak is not None
            else self.v_lv
        )
        lv_min_for_bounds = (
            float(calibrated_lv_min)
            if calibrated_lv_min is not None
            else self.v_lv
        )
        vdc_min_for_bounds = (
            float(calibrated_vdc_min)
            if calibrated_vdc_min is not None
            else self.vdc
        )
        vdc_max_for_bounds = (
            float(calibrated_vdc_max)
            if calibrated_vdc_max is not None
            else self.vdc
        )
        vdc_min_for_bounds = vdc_min_for_bounds - float(cfg.proxy_vdc_reward_downshift_pu)
        vdc_max_for_bounds = vdc_max_for_bounds - float(cfg.proxy_vdc_reward_downshift_pu)
        vdc_bounds_metric_violation = max(
            0.0, 650.0 / cfg.vdc_ref - vdc_min_for_bounds
        ) ** 2
        vdc_bounds_metric_violation += max(
            0.0, vdc_max_for_bounds - 1000.0 / cfg.vdc_ref
        ) ** 2
        vdc_bounds_violation = max(
            float(vdc_bounds_state_violation),
            float(vdc_bounds_metric_violation),
        )
        recovery_vdc_high_violation = recovery_active_for_reward * max(
            0.0,
            vdc_max_for_bounds - float(cfg.recovery_vdc_high_limit_pu),
        ) ** 2
        calibrated_survival_violation = 0.0
        if calibrated_fault_case:
            calibrated_survival_violation += max(0.0, 176.0 / cfg.v_ref_phase_rms - lv_fault_for_bounds) ** 2
            calibrated_survival_violation += max(0.0, lv_fault_for_bounds - 238.0 / cfg.v_ref_phase_rms) ** 2
            calibrated_survival_violation += max(0.0, 180.0 / cfg.v_ref_phase_rms - lv_recovery_for_bounds) ** 2
            calibrated_survival_violation += max(0.0, lv_recovery_for_bounds - 235.0 / cfg.v_ref_phase_rms) ** 2
            calibrated_survival_violation += max(0.0, 180.0 / cfg.v_ref_phase_rms - lv_min_for_bounds) ** 2
            calibrated_survival_violation += max(0.0, lv_peak_for_bounds - 235.0 / cfg.v_ref_phase_rms) ** 2
            calibrated_survival_violation += max(0.0, 650.0 / cfg.vdc_ref - vdc_min_for_bounds) ** 2
            calibrated_survival_violation += max(0.0, vdc_max_for_bounds - 1000.0 / cfg.vdc_ref) ** 2
        vdc_margin_violation = 0.0
        if cfg.vdc_margin_pu > 0.0:
            vdc_low_gate = 650.0 / cfg.vdc_ref
            vdc_high_gate = 1000.0 / cfg.vdc_ref
            vdc_margin_violation += max(
                0.0, vdc_low_gate + cfg.vdc_margin_pu - vdc_min_for_bounds
            ) ** 2
            vdc_margin_violation += max(
                0.0, vdc_max_for_bounds - (vdc_high_gate - cfg.vdc_margin_pu)
            ) ** 2
        vdc_lower_barrier_violation = 0.0
        if cfg.vdc_lower_barrier_reward_weight > 0.0:
            barrier_start = float(cfg.vdc_lower_barrier_start_pu)
            barrier_floor = float(cfg.vdc_lower_barrier_floor_pu)
            barrier_span = max(1e-6, barrier_start - barrier_floor)
            vdc_barrier_state = min(float(self.vdc), float(vdc_min_for_bounds))
            vdc_lower_barrier_violation = (
                max(0.0, barrier_start - vdc_barrier_state) / barrier_span
            ) ** 2
        grid_current_margin_violation = 0.0
        if cfg.grid_current_margin_pu > 0.0:
            current_margin_limit = max(
                0.0, cfg.grid_current_limit_pu - cfg.grid_current_margin_pu
            )
            grid_current_margin_violation = max(
                0.0, grid_current_peak_for_reward - current_margin_limit
            ) ** 2
        lv_margin_violation = 0.0
        if calibrated_fault_case and cfg.lv_margin_pu > 0.0:
            lv_fault_low = 176.0 / cfg.v_ref_phase_rms
            lv_fault_high = 238.0 / cfg.v_ref_phase_rms
            lv_recovery_low = 180.0 / cfg.v_ref_phase_rms
            lv_recovery_high = 235.0 / cfg.v_ref_phase_rms
            margin = float(cfg.lv_margin_pu)
            lv_margin_violation += max(
                0.0, lv_fault_low + margin - lv_fault_for_bounds
            ) ** 2
            lv_margin_violation += max(
                0.0, lv_fault_for_bounds - (lv_fault_high - margin)
            ) ** 2
            lv_margin_violation += max(
                0.0, lv_recovery_low + margin - lv_recovery_for_bounds
            ) ** 2
            lv_margin_violation += max(
                0.0, lv_recovery_for_bounds - (lv_recovery_high - margin)
            ) ** 2
            lv_margin_violation += max(
                0.0, lv_recovery_low + margin - lv_min_for_bounds
            ) ** 2
            lv_margin_violation += max(
                0.0, lv_peak_for_bounds - (lv_recovery_high - margin)
            ) ** 2
        reward = (
            -(90.0 + 35.0 * fault_or_recovery) * voltage_err * voltage_err
            -45.0 * unbalance * unbalance
            -cfg.vdc_soft_reward_weight * vdc_soft * vdc_soft
            -cfg.vdc_bounds_reward_weight * vdc_bounds_violation
            -cfg.vdc_margin_reward_weight * vdc_margin_violation
            -cfg.vdc_lower_barrier_reward_weight * vdc_lower_barrier_violation
            -cfg.voltage_wrong_sign_reward_weight * wrong_sign
            -cfg.envelope_reward_weight * (
                fault_band_violation * fault_band_violation
                + recovery_violation * recovery_violation
            )
            -cfg.lv_margin_reward_weight * lv_margin_violation
            -topology2_dynamic_stress
            -cfg.calibrated_survival_reward_weight * calibrated_survival_violation
            -cfg.calibration_ood_reward_weight
            * support_violation_for_reward
            * support_violation_for_reward
            -cfg.grid_reactive_reward_weight * reactive_shortfall
            -cfg.grid_wrong_sign_reward_weight * reactive_wrong_sign
            -cfg.grid_current_reward_weight * grid_current_violation
            -cfg.grid_current_margin_reward_weight * grid_current_margin_violation
            -cfg.recovery_action_reward_weight * recovery_action_violation
            -cfg.recovery_vdc_high_reward_weight * recovery_vdc_high_violation
            -0.20 * reg_mag * reg_mag
            -energy_weight * energy_mag * energy_mag
            -cfg.action_slew_weight * slew * slew
            -cfg.safety_penalty_weight * safety_gap * safety_gap
            -cfg.teacher_prior_weight * teacher_gap
            + 1.0
        )
        if 0.98 <= self.v_lv <= 1.02 and 0.85 <= self.vdc <= 1.10:
            reward += 1.0
        if self._detector.recovery_active and 0.97 <= self.v_lv <= 1.03:
            reward += 0.5
        vdc_low_terminal = bool(
            cfg.vdc_low_terminal_enable
            and min(float(self.vdc), float(vdc_min_for_bounds))
            < float(cfg.vdc_low_terminal_pu)
        )
        if vdc_low_terminal:
            reward -= float(cfg.vdc_low_terminal_penalty)

        reward_unscaled = float(reward)
        reward = float(cfg.reward_scale) * reward_unscaled

        self._last_action = action.copy()
        action_max_abs = float(np.max(np.abs(action)))
        raw_action_max_abs = float(np.max(np.abs(raw_action)))
        self.episode_action_max_abs = max(self.episode_action_max_abs, action_max_abs)
        self.episode_vdc_min_pu = min(self.episode_vdc_min_pu, vdc_min_for_bounds)
        self.episode_vdc_max_pu = max(self.episode_vdc_max_pu, vdc_max_for_bounds)
        l1_grid_current_pass = bool(
            (not cfg.l1_current_limit_required)
            or self.episode_grid_current_peak_pu <= cfg.grid_current_limit_pu + 1e-9
        )
        l1_load_voltage_survival_pass = bool(
            self.fault_band_violation_max_pu <= cfg.envelope_tolerance_pu
            and self.recovery_violation_max_pu <= cfg.envelope_tolerance_pu
            and self.episode_vdc_min_pu >= 650.0 / cfg.vdc_ref
            and self.episode_vdc_max_pu <= 1000.0 / cfg.vdc_ref
            and self.episode_action_max_abs <= 0.9501
            and l1_grid_current_pass
        )
        if calibrated_fault_case:
            terminated = False
        else:
            terminated = bool(
                self.vdc < 0.65 or self.vdc > 1.25 or self.v_lv < 0.45 or self.v_lv > 1.40
            )
        if vdc_low_terminal:
            terminated = True
        if cfg.safety_unsafe_terminal and safety_unsafe:
            terminated = True
        if (
            cfg.envelope_terminal
            and self._sc.category != "steady"
            and (
                self.envelope_violation_max_pu > cfg.envelope_tolerance_pu
                or self.fault_band_violation_max_pu > cfg.envelope_tolerance_pu
                or self.recovery_violation_max_pu > cfg.envelope_tolerance_pu
            )
        ):
            terminated = True
        truncated = bool(self.t >= float(self._sc.duration_s))
        action_limit_violation = max(0.0, action_max_abs - 0.9501)
        raw_action_delta = raw_action - action
        projection_delta_norm = float(np.linalg.norm(raw_action_delta))
        cost_tracking = float(voltage_err * voltage_err)
        cost_unbalance = float(unbalance * unbalance)
        cost_vdc_soft = float(vdc_soft * vdc_soft)
        cost_vdc_bounds = float(vdc_bounds_violation)
        cost_vdc_margin = float(vdc_margin_violation)
        cost_vdc_lower_barrier = float(vdc_lower_barrier_violation)
        cost_envelope = float(
            fault_band_violation * fault_band_violation
            + recovery_violation * recovery_violation
        )
        cost_lv_margin = float(lv_margin_violation)
        cost_fault_band = float(fault_band_violation * fault_band_violation)
        cost_recovery = float(recovery_violation * recovery_violation)
        cost_support = float(support_violation * support_violation)
        cost_support_for_reward = float(
            support_violation_for_reward * support_violation_for_reward
        )
        cost_safety = float(safety_gap * safety_gap)
        cost_reg_action = float(reg_mag * reg_mag)
        cost_energy_action = float(energy_mag * energy_mag)
        cost_recovery_action = float(recovery_action_violation)
        cost_recovery_vdc_high = float(recovery_vdc_high_violation)
        cost_slew = float(slew * slew)
        info = {
            "validator_schema": CURRENT_FRT_VALIDATOR_SCHEMA,
            "target_gate": normalize_target_gate(cfg.target_gate, trainable_only=True),
            "scenario_valid_evaluated": False,
            "scenario_valid": False,
            "scenario_valid_reason": "proxy_does_not_assess_pcc_test_validity",
            "l1_load_voltage_survival_pass": l1_load_voltage_survival_pass,
            "l1_grid_current_required": bool(cfg.l1_current_limit_required),
            "l1_grid_current_pass": l1_grid_current_pass,
            "l2_grid_code_ride_through_evaluated": False,
            "l2_grid_code_ride_through_pass": False,
            "l3_full_frt_evaluated": False,
            "l3_full_frt_pass": False,
            "topology": self._sc.topology,
            "category": self._sc.category,
            "fault_type": self._sc.fault_type,
            "grid_pu": grid_now,
            "v_lv_pu": self.v_lv,
            "vdc_pu": self.vdc,
            "v_neg_pu": self.v_neg,
            "condition": classify_hpt_operating_condition(
                self.v_pos, self.v_neg, grid_pu=grid_now, config=cfg
            ),
            "uses_switch_calibration": bool(self._calibration),
            "hybrid_dc_channel_enabled": bool(self._hybrid_dc_channel is not None),
            "hybrid_dc_channel_source": hybrid_dc_source,
            "slow_state_correction_enabled": bool(self._slow_state_correction is not None),
            "slow_state_correction_source": slow_state_correction_source,
            "fault_active_est": self._detector.fault_active,
            "recovery_active_est": self._detector.recovery_active,
            "safety_safe_probability": safe_probability,
            "safety_threshold": safety_threshold,
            "safety_unsafe": safety_unsafe,
            "safety_gap": safety_gap,
            "teacher_m_reg_d": float(teacher_prior[0]),
            "teacher_m_reg_q": float(teacher_prior[1]),
            "teacher_m_energy_d": float(teacher_prior[2]),
            "teacher_m_energy_q": float(teacher_prior[3]),
            "teacher_gap": teacher_gap,
            "grid_vpos_pu": float(grid_metrics["vpos"]),
            "grid_iq_pu": float(grid_metrics["iq"]),
            "grid_iq_ref_pu": float(grid_metrics["iq_ref"]),
            "grid_iq_shortfall_pu": float(grid_metrics["shortfall"]),
            "grid_iq_shortfall_reward_pu": reactive_shortfall,
            "grid_reactive_assessed": reactive_assessed,
            "grid_reactive_wrong_sign": bool(grid_metrics["wrong_sign"]),
            "grid_current_peak_pu": float(grid_metrics["current_peak"]),
            "episode_grid_current_peak_pu": self.episode_grid_current_peak_pu,
            "grid_current_limit_pu": cfg.grid_current_limit_pu,
            "grid_current_limit_violation": grid_current_violation,
            "grid_current_margin_violation": grid_current_margin_violation,
            "corrected_energy_i_mag": corrected_energy_i_mag,
            "load_quality_violation_pu": load_quality_violation,
            "load_quality_violation_max_pu": self.load_quality_violation_max_pu,
            "load_quality_pass": bool(load_quality["load_quality_pass"]),
            "envelope_violation_pu": load_quality_violation,
            "envelope_violation_max_pu": self.envelope_violation_max_pu,
            "envelope_violation_duration_s": self.envelope_violation_duration_s,
            "fault_band_violation_pu": fault_band_violation,
            "fault_band_violation_max_pu": self.fault_band_violation_max_pu,
            "fault_band_violation_duration_s": self.fault_band_violation_duration_s,
            "recovery_violation_pu": recovery_violation,
            "recovery_violation_max_pu": self.recovery_violation_max_pu,
            "recovery_violation_duration_s": self.recovery_violation_duration_s,
            "recovery_negative_energy_mag": recovery_negative_energy_mag,
            "recovery_energy_overshoot_violation": recovery_energy_overshoot_violation,
            "timestep_envelope_pass": bool(load_quality["load_quality_pass"]),
            "calibration_support_violation": support_violation,
            "calibration_support_violation_for_reward": support_violation_for_reward,
            "calibrated_survival_violation": calibrated_survival_violation,
            "cost_tracking": cost_tracking,
            "cost_unbalance": cost_unbalance,
            "cost_vdc_soft": cost_vdc_soft,
            "cost_vdc_bounds": cost_vdc_bounds,
            "cost_vdc_margin": cost_vdc_margin,
            "cost_vdc_lower_barrier": cost_vdc_lower_barrier,
            "cost_wrong_sign": wrong_sign,
            "cost_envelope": cost_envelope,
            "cost_lv_margin": cost_lv_margin,
            "cost_fault_band": cost_fault_band,
            "cost_recovery": cost_recovery,
            "cost_topology2_dynamic": topology2_dynamic_stress,
            "cost_calibrated_survival": calibrated_survival_violation,
            "cost_support": cost_support,
            "cost_support_for_reward": cost_support_for_reward,
            "cost_reactive_shortfall": reactive_shortfall,
            "cost_reactive_wrong_sign": reactive_wrong_sign,
            "cost_grid_current": grid_current_violation,
            "cost_grid_current_margin": grid_current_margin_violation,
            "cost_recovery_action": cost_recovery_action,
            "cost_recovery_vdc_high": cost_recovery_vdc_high,
            "cost_reg_action": cost_reg_action,
            "cost_energy_action": cost_energy_action,
            "cost_slew": cost_slew,
            "cost_safety": cost_safety,
            "cost_teacher_gap": teacher_gap,
            "cost_action_limit": action_limit_violation,
            "reward_unscaled": reward_unscaled,
            "reward_scale": float(cfg.reward_scale),
            "action_max_abs": action_max_abs,
            "episode_action_max_abs": self.episode_action_max_abs,
            "episode_vdc_min_pu": self.episode_vdc_min_pu,
            "episode_vdc_max_pu": self.episode_vdc_max_pu,
            "raw_action_max_abs": raw_action_max_abs,
            "projection_delta_norm": projection_delta_norm,
            "raw_m_reg_d": float(raw_action[0]),
            "raw_m_reg_q": float(raw_action[1]),
            "raw_m_energy_d": float(raw_action[2]),
            "raw_m_energy_q": float(raw_action[3]),
            "effective_m_reg_d": float(action[0]),
            "effective_m_reg_q": float(action[1]),
            "effective_m_energy_d": float(action[2]),
            "effective_m_energy_q": float(action[3]),
            "calibrated_lv_recovery_pu": float(calibrated_lv_recovery)
            if calibrated_lv_recovery is not None
            else float("nan"),
            "calibrated_lv_peak_pu": float(calibrated_lv_peak)
            if calibrated_lv_peak is not None
            else float("nan"),
            "calibrated_lv_min_pu": float(calibrated_lv_min)
            if calibrated_lv_min is not None
            else float("nan"),
            "calibrated_vdc_min_pu": float(calibrated_vdc_min)
            if calibrated_vdc_min is not None
            else float("nan"),
            "calibrated_vdc_max_pu": float(calibrated_vdc_max)
            if calibrated_vdc_max is not None
            else float("nan"),
            "action": action.copy(),
        }
        return self._obs(), float(reward), terminated, truncated, info


def teacher_action(obs: np.ndarray, *, reg_limit: float = 0.80, energy_limit: float = 0.95) -> np.ndarray:
    """Rule-based bootstrap action using the same SAC action contract."""

    obs = np.asarray(obs, dtype=np.float32)
    vpu = float(obs[0])
    vpos = float(obs[1])
    v_err = float(obs[5])
    vdc_err = float(obs[4])
    vneg = float(obs[2])
    fault_active = float(obs[16]) if obs.size > 16 else float(vpos < 0.92 or vpos > 1.08)
    recovery_active = float(obs[17]) if obs.size > 17 else 0.0
    boost = 1.0 + 0.35 * fault_active + 0.15 * recovery_active

    m_reg_d = np.clip(2.2 * boost * v_err, -reg_limit, reg_limit)
    if vpos < 0.92 and m_reg_d < 0.0:
        m_reg_d = 0.0
    elif vpos > 1.08 and m_reg_d > 0.0:
        m_reg_d = 0.0

    m_reg_q = np.clip(-0.9 * vneg, -reg_limit, reg_limit)
    m_energy_d = np.clip(1.4 * vdc_err + 0.22 * abs(m_reg_d), -energy_limit, energy_limit)
    if vpu < 0.92:
        m_energy_d = max(m_energy_d, min(energy_limit, 0.10 + 0.25 * (0.92 - vpu)))
    m_energy_q = np.clip(0.25 * v_err - 0.35 * vneg, -energy_limit, energy_limit)
    return np.array([m_reg_d, m_reg_q, m_energy_d, m_energy_q], dtype=np.float32)


def execution_guard_teacher_action(
    obs: np.ndarray,
    *,
    reg_limit: float = 0.80,
    energy_limit: float = 0.95,
    dynamic_mode: bool = False,
    dynamic_reg_limit_topology1: float = 0.80,
    dynamic_reg_limit_topology2: float = 0.60,
) -> np.ndarray:
    """Teacher target copied from the guarded Simulink execution layer.

    This function exists only to create training labels.  Final switch-level
    promotion must run with the corresponding Simulink guard disabled.
    """

    obs = np.asarray(obs, dtype=np.float32)
    vpu = float(obs[0])
    vpos = float(obs[1])
    vdcpu = float(obs[3])
    topology1 = bool(obs.size > 14 and obs[14] > 0.5)
    topology2 = bool(obs.size > 15 and obs[15] > 0.5)

    if topology2 and dynamic_mode:
        dyn_lim = float(np.clip(dynamic_reg_limit_topology2, 0.0, reg_limit))
        m_reg_d = float(np.clip(20.0 * (1.0 - vpu), -dyn_lim, dyn_lim))
        return np.asarray([m_reg_d, 0.0, 0.0, 0.0], dtype=np.float32)

    if topology1 and not dynamic_mode:
        m_reg_d = 0.32 + 2.35 * (1.0 - vpu)
        if vpu > 0.995:
            m_reg_d = 0.26
        m_reg_d = float(np.clip(m_reg_d, 0.22, 0.46))
        return np.asarray([m_reg_d, 0.0, 0.0, 0.0], dtype=np.float32)

    action = teacher_action(obs, reg_limit=reg_limit, energy_limit=energy_limit)
    if vpos < 0.92 and action[0] < 0.0:
        action[0] = 0.0
    if vpos > 1.08 and action[0] > 0.0:
        action[0] = 0.0
    if vpu < 0.98 and action[0] < 0.0:
        action[0] = 0.0
    if vdcpu < 0.95:
        action[0] *= float(np.clip((vdcpu - 0.75) / 0.20, 0.0, 1.0))
        action[2] = max(action[2], min(energy_limit, 0.20 + 1.2 * (0.82 - vdcpu)))
    elif vdcpu > 1.12:
        action[2] = min(action[2], -0.05)
    if dynamic_mode:
        dyn_lim = dynamic_reg_limit_topology2 if topology2 else dynamic_reg_limit_topology1
        dyn_lim = float(np.clip(dyn_lim, 0.0, reg_limit))
        action[0] = float(np.clip(action[0], -dyn_lim, dyn_lim))
        action[1] = float(np.clip(action[1], -dyn_lim, dyn_lim))
    action[0] = float(np.clip(action[0], -reg_limit, reg_limit))
    action[1] = float(np.clip(action[1], -reg_limit, reg_limit))
    action[2] = float(np.clip(action[2], -energy_limit, energy_limit))
    action[3] = float(np.clip(action[3], -energy_limit, energy_limit))
    return action.astype(np.float32)
