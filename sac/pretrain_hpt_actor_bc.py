"""Behavior-clone the HPT SAC actor from the switch-sweep table teacher.

This is a warm-start utility, not a replacement controller.  It preserves the
SAC checkpoint/export format while pulling the deterministic actor output into
the action region proven useful by switch-level fixed-action sweeps.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from stable_baselines3 import SAC
from stable_baselines3.common.vec_env import DummyVecEnv

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from .datasets.build_hpt_action_trajectory import TrajectorySpec, make_trajectory
from .experiment_metadata import write_experiment_metadata
from .hpt_voltage_sac_env import (
    ACT_DIM_HPT,
    OBS_DIM_HPT,
    HPTVoltageEnvConfig,
    HPTVoltageSACEnv,
    execution_guard_teacher_action,
)
from .offline.train_hpt_voltage_sac import (
    MODELS,
    RESULTS,
    TOPOLOGY_MODELS,
    scenario_summary,
    select_scenarios,
)
from .runtime_utils import pick_device


def make_env_config(args: argparse.Namespace) -> HPTVoltageEnvConfig:
    return HPTVoltageEnvConfig(
        reg_limit=args.reg_limit,
        energy_limit=args.energy_limit,
        reg_d_limit=args.reg_limit,
        reg_q_limit=args.reg_limit,
        energy_d_limit=args.energy_limit,
        energy_q_limit=args.energy_limit,
        teacher_prior_weight=args.teacher_prior_weight,
    )


def collect_teacher_samples(
    scenarios,
    config: HPTVoltageEnvConfig,
    *,
    episodes_per_scenario: int,
    noise_std: float,
    feedback_gain_topology1: float,
    feedback_gain_topology2: float,
    feedforward_scale_topology1: float,
    feedforward_scale_topology2: float,
    teacher_source: str,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    observations: list[np.ndarray] = []
    targets: list[np.ndarray] = []

    if episodes_per_scenario <= 0:
        return (
            np.zeros((0, OBS_DIM_HPT), dtype=np.float32),
            np.zeros((0, ACT_DIM_HPT), dtype=np.float32),
        )

    for scenario in scenarios:
        env = HPTVoltageSACEnv([scenario], config=config, seed=seed, train_mode=False)
        for _ in range(episodes_per_scenario):
            obs, _ = env.reset()
            done = False
            while not done:
                grid_now, _ = env._grid_profile(env.t)
                dynamic_mode = float(scenario.fault_start_s) > 0.02 and scenario.category != "steady"
                if teacher_source == "execution_guard":
                    target = execution_guard_teacher_action(
                        obs,
                        reg_limit=config.reg_limit,
                        energy_limit=config.energy_limit,
                        dynamic_mode=dynamic_mode,
                        dynamic_reg_limit_topology1=config.dynamic_reg_limit_topology1,
                        dynamic_reg_limit_topology2=config.dynamic_reg_limit_topology2,
                    )
                else:
                    target = env._table_teacher_action(grid_now)
                    if scenario.topology.lower() == "topology1":
                        target[0] *= feedforward_scale_topology1
                        target[0] += feedback_gain_topology1 * (1.0 - float(obs[0]))
                    elif scenario.topology.lower() == "topology2":
                        target[0] *= feedforward_scale_topology2
                        target[0] += feedback_gain_topology2 * (1.0 - float(obs[0]))
                    target = env._project_action(target)
                observations.append(np.asarray(obs, dtype=np.float32))
                targets.append(np.asarray(target, dtype=np.float32))
                noisy_action = target + rng.normal(0.0, noise_std, size=ACT_DIM_HPT).astype(np.float32)
                noisy_action[2:] *= 0.25
                obs, _, terminated, truncated, _ = env.step(noisy_action)
                done = bool(terminated or truncated)

    X = np.asarray(observations, dtype=np.float32)
    Y = np.asarray(targets, dtype=np.float32)
    if X.ndim != 2 or X.shape[1] != OBS_DIM_HPT:
        raise RuntimeError(f"Bad observation dataset shape: {X.shape}")
    if Y.ndim != 2 or Y.shape[1] != ACT_DIM_HPT:
        raise RuntimeError(f"Bad target dataset shape: {Y.shape}")
    return X, Y


def append_step4_corrections(
    X: np.ndarray,
    Y: np.ndarray,
    csv_path: Path | None,
    *,
    repeat: int,
    reg_limit: float,
) -> tuple[np.ndarray, np.ndarray]:
    if csv_path is None:
        return X, Y
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    extra_x: list[np.ndarray] = []
    extra_y: list[np.ndarray] = []
    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("mode") != "sac_actor":
                continue
            model = str(row.get("model", "")).lower()
            topology1 = 1.0 if "1to1" in model else 0.0
            topology2 = 1.0 - topology1
            lv = float(row["lv_rms_mean"])
            vdc = float(row["vdc_mean"])
            current_reg = float(row["reg_d_mean"])

            target_reg = current_reg
            if topology1 > 0.5:
                obs_vpu = float(row.get("obs_vpu_mean") or (lv / 207.0))
                target_reg = 0.38 + 2.0 * (0.99 - obs_vpu)
                target_reg -= 0.8 * max(0.0, lv - 210.0) / 207.0
                target_reg += 0.4 * max(0.0, 200.0 - lv) / 207.0
                target_reg -= 0.8 * max(0.0, 760.0 - vdc) / 800.0
            else:
                target_reg += 1.0 * max(0.0, lv - 212.0) / 207.0
                target_reg -= 1.0 * max(0.0, 198.0 - lv) / 207.0
                target_reg -= 0.4 * max(0.0, 760.0 - vdc) / 800.0
            target_reg = float(np.clip(target_reg, -reg_limit, reg_limit))

            obs = np.zeros(OBS_DIM_HPT, dtype=np.float32)
            obs[0] = float(row.get("obs_vpu_mean") or (lv / 207.0))
            obs[1] = float(row.get("obs_vpos_mean") or obs[0])
            obs[2] = 0.0
            obs[3] = float(row.get("obs_vdcpu_mean") or (vdc / 800.0))
            obs[4] = 1.0 - obs[3]
            obs[5] = float(row.get("obs_verr_mean") or (1.0 - obs[0]))
            obs[8] = float(row.get("obs_last_reg_d_mean") or current_reg)
            obs[12] = float(row.get("obs_sag_flag_mean") or 0.0)
            obs[13] = float(row.get("obs_swell_flag_mean") or 0.0)
            obs[14] = float(row.get("obs_topology1_flag_mean") or topology1)
            obs[15] = float(row.get("obs_topology2_flag_mean") or topology2)
            obs[20] = 1.0
            obs[21] = 1.0

            target = np.asarray([target_reg, 0.0, 0.0, 0.0], dtype=np.float32)
            for _ in range(max(1, repeat)):
                extra_x.append(obs)
                extra_y.append(target)

    if not extra_x:
        return X, Y
    return (
        np.concatenate([X, np.asarray(extra_x, dtype=np.float32)], axis=0),
        np.concatenate([Y, np.asarray(extra_y, dtype=np.float32)], axis=0),
    )


def append_anchor_dataset_samples(
    X: np.ndarray,
    Y: np.ndarray,
    dataset: Path | None,
    *,
    repeat: int,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Append pre-built observation/action anchors from an ``.npz`` dataset."""

    if dataset is None:
        return X, Y, 0
    if not dataset.exists():
        raise FileNotFoundError(dataset)
    with np.load(dataset, allow_pickle=False) as data:
        obs_key = "observations" if "observations" in data.files else "obs"
        act_key = "actions" if "actions" in data.files else "acts"
        if obs_key not in data.files or act_key not in data.files:
            raise ValueError(
                f"Anchor dataset must contain observations/actions arrays: {dataset}"
            )
        extra_x = np.asarray(data[obs_key], dtype=np.float32)
        extra_y = np.asarray(data[act_key], dtype=np.float32)
    if extra_x.ndim != 2 or extra_x.shape[1] != OBS_DIM_HPT:
        raise RuntimeError(f"Bad anchor observation shape: {extra_x.shape}")
    if extra_y.ndim != 2 or extra_y.shape[1] != ACT_DIM_HPT:
        raise RuntimeError(f"Bad anchor action shape: {extra_y.shape}")
    if repeat > 1:
        extra_x = np.repeat(extra_x, int(repeat), axis=0)
        extra_y = np.repeat(extra_y, int(repeat), axis=0)
    if extra_x.shape[0] <= 0:
        return X, Y, 0
    return (
        np.concatenate([X, extra_x], axis=0),
        np.concatenate([Y, extra_y], axis=0),
        int(extra_x.shape[0]),
    )


def _scenario_type_allowed(row: dict[str, str], scenario_types: str) -> bool:
    if scenario_types == "all":
        return True
    scenario_type = str(row.get("scenario_type", "")).lower()
    if scenario_types == "steady":
        return scenario_type == "steady"
    if scenario_types == "fault":
        return scenario_type != "steady"
    raise ValueError(f"Unknown scenario type filter: {scenario_types}")


def _csv_filter_allowed(value: str, allowed_csv: str) -> bool:
    allowed_csv = str(allowed_csv or "all").strip().lower()
    if allowed_csv in {"", "all", "*"}:
        return True
    allowed = {item.strip().lower() for item in allowed_csv.split(",") if item.strip()}
    return str(value or "").strip().lower() in allowed


def _contains_filter_allowed(value: str, needle_csv: str) -> bool:
    needle_csv = str(needle_csv or "all").strip().lower()
    if needle_csv in {"", "all", "*"}:
        return True
    value_l = str(value or "").lower()
    value_case = value_l.replace(".", "p")
    needles = [item.strip().lower() for item in needle_csv.split(",") if item.strip()]
    return any(
        needle in value_l or needle.replace(".", "p") in value_case
        for needle in needles
    )


def _trace_row_allowed(
    row: dict[str, str],
    *,
    scenario_types: str,
    topologies: str,
    condition_classes: str,
    case_contains: str,
    window_zones: str,
) -> bool:
    return (
        _scenario_type_allowed(row, scenario_types)
        and _csv_filter_allowed(row.get("topology", ""), topologies)
        and _csv_filter_allowed(row.get("condition_class", ""), condition_classes)
        and _contains_filter_allowed(row.get("case_name", ""), case_contains)
        and _csv_filter_allowed(row.get("window_zone", ""), window_zones)
    )


def _unit_ramp(value: float, zero_at: float, full_at: float) -> float:
    if not np.isfinite(full_at) or full_at <= zero_at:
        return 1.0 if value >= zero_at else 0.0
    return float(np.clip((value - zero_at) / (full_at - zero_at), 0.0, 1.0))


def append_switch_trace_samples(
    X: np.ndarray,
    Y: np.ndarray,
    csv_path: Path | None,
    *,
    repeat: int,
    topology2_phase_equivalent: bool,
    phase_shift_rad: float,
    scenario_types: str,
    topologies: str,
    condition_classes: str,
    case_contains: str,
    window_zones: str,
    fixed_target: str | None,
    energy_vdc_feedback_gain: float,
    energy_vdc_ref_pu: float,
    energy_two_zone_enable: bool,
    energy_two_zone_topology2_only: bool,
    energy_vdc_low_pu: float,
    energy_vdc_high_pu: float,
    energy_low_d_gain: float,
    energy_low_q_gain: float,
    energy_high_d_gain: float,
    energy_high_q_gain: float,
    energy_dvdc_d_gain: float,
    energy_dvdc_q_gain: float,
    energy_d_min: float,
    energy_d_max: float,
    energy_q_min: float,
    energy_q_max: float,
    energy_limit: float,
    q_gate_lv_min_pu: float,
    q_gate_time_min_s: float,
    q_gate_vdc_min_pu: float,
    q_gate_vdc_max_pu: float,
    q_gate_mode: str,
    q_gate_lv_full_pu: float,
    q_gate_time_full_s: float,
    fault_window_repeat_mult: int,
    recovery_window_repeat_mult: int,
    pre_window_repeat_mult: int,
    target_profile: str,
    target_columns: str,
    profile_csv: Path | None,
    profile_dt: float,
    profile_stop_time: float,
    profile_base_action: list[float],
    profile_start_action: list[float],
    profile_action: list[float],
    profile_step_time: float,
    profile_ramp_start: float,
    profile_ramp_end: float,
    profile_down_start: float | None,
    profile_down_end: float | None,
) -> tuple[np.ndarray, np.ndarray, int]:
    if csv_path is None:
        return X, Y, 0
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    profile_t: np.ndarray | None = None
    profile_y: np.ndarray | None = None
    if target_profile == "csv_file":
        if profile_csv is None:
            raise ValueError("--switch-trace-profile-csv is required when target profile is csv_file")
        if not profile_csv.exists():
            raise FileNotFoundError(profile_csv)
        t_values: list[float] = []
        y_values: list[list[float]] = []
        with profile_csv.open("r", newline="", encoding="utf-8-sig") as pf:
            for profile_row in csv.DictReader(pf):
                t_values.append(float(profile_row.get("t") or 0.0))
                if "m_reg_d" in profile_row:
                    y_values.append(
                        [
                            float(profile_row.get("m_reg_d") or 0.0),
                            float(profile_row.get("m_reg_q") or 0.0),
                            float(profile_row.get("m_energy_d") or 0.0),
                            float(profile_row.get("m_energy_q") or 0.0),
                        ]
                    )
                else:
                    y_values.append(
                        [
                            float(profile_row.get(f"action_{idx:02d}") or 0.0)
                            for idx in range(1, ACT_DIM_HPT + 1)
                        ]
                    )
        if not t_values:
            raise ValueError(f"Empty trajectory profile CSV: {profile_csv}")
        profile_t = np.asarray(t_values, dtype=float)
        profile_y = np.asarray(y_values, dtype=float)
    elif target_profile != "csv":
        spec = TrajectorySpec(
            preset=target_profile,
            dt=profile_dt,
            stop_time=profile_stop_time,
            base_action=tuple(float(v) for v in profile_base_action),
            start_action=tuple(float(v) for v in profile_start_action),
            action=tuple(float(v) for v in profile_action),
            step_time=profile_step_time,
            ramp_start=profile_ramp_start,
            ramp_end=profile_ramp_end,
            down_start=profile_down_start,
            down_end=profile_down_end,
        )
        profile_t, profile_y = make_trajectory(spec)
        profile_t = profile_t.reshape(-1)

    extra_x: list[np.ndarray] = []
    extra_y: list[np.ndarray] = []
    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if not _trace_row_allowed(
                row,
                scenario_types=scenario_types,
                topologies=topologies,
                condition_classes=condition_classes,
                case_contains=case_contains,
                window_zones=window_zones,
            ):
                continue
            obs = np.asarray(
                [float(row[f"obs_{idx:02d}"]) for idx in range(1, OBS_DIM_HPT + 1)],
                dtype=np.float32,
            )
            if profile_t is not None and profile_y is not None:
                row_t = float(row.get("t") or 0.0)
                idx = int(np.clip(np.searchsorted(profile_t, row_t, side="left"), 0, len(profile_t) - 1))
                if idx > 0 and abs(float(profile_t[idx - 1]) - row_t) <= abs(float(profile_t[idx]) - row_t):
                    idx -= 1
                target = np.asarray(profile_y[idx, :], dtype=np.float32)
            else:
                prefix = "actor_action" if target_columns == "actor_action" else "action"
                target = np.asarray(
                    [float(row[f"{prefix}_{idx:02d}"]) for idx in range(1, ACT_DIM_HPT + 1)],
                    dtype=np.float32,
                )
            if fixed_target and profile_t is None:
                parts = [p.strip() for p in fixed_target.split(",") if p.strip()]
                if len(parts) != ACT_DIM_HPT:
                    raise ValueError(
                        f"--switch-trace-fixed-target must have {ACT_DIM_HPT} values"
                    )
                target = np.asarray([float(p) for p in parts], dtype=np.float32)
                if target[1] != 0.0 and (
                    q_gate_lv_min_pu > 0.0
                    or q_gate_time_min_s > 0.0
                    or q_gate_vdc_min_pu > 0.0
                    or np.isfinite(q_gate_vdc_max_pu)
                ):
                    lv_pu = float(row.get("lv_rms_inst") or 0.0) / 207.0
                    if lv_pu <= 0.0:
                        lv_pu = float(obs[0])
                    vdc_pu = float(row.get("vdc_inst") or 0.0) / 800.0
                    if vdc_pu <= 0.0:
                        vdc_pu = float(obs[3])
                    t_s = float(row.get("t") or 0.0)
                    q_allowed = (
                        lv_pu >= q_gate_lv_min_pu
                        and t_s >= q_gate_time_min_s
                        and vdc_pu >= q_gate_vdc_min_pu
                        and vdc_pu <= q_gate_vdc_max_pu
                    )
                    if q_gate_mode == "continuous" and q_allowed:
                        lv_scale = _unit_ramp(lv_pu, q_gate_lv_min_pu, q_gate_lv_full_pu)
                        time_scale = _unit_ramp(t_s, q_gate_time_min_s, q_gate_time_full_s)
                        target[1] = float(target[1] * min(lv_scale, time_scale))
                    elif not q_allowed:
                        target[1] = 0.0
            if energy_vdc_feedback_gain != 0.0:
                target[2] = float(
                    np.clip(
                        target[2] + energy_vdc_feedback_gain * (energy_vdc_ref_pu - float(obs[3])),
                        -0.95,
                        0.95,
                    )
                )
            if energy_two_zone_enable:
                topology = str(row.get("topology", "")).lower()
                topology2 = topology == "topology2" or bool(obs[15] > 0.5)
                if (not energy_two_zone_topology2_only) or topology2:
                    vdc_pu = float(row.get("vdc_inst") or 0.0) / 800.0
                    if vdc_pu <= 0.0 or not np.isfinite(vdc_pu):
                        vdc_pu = float(obs[3])
                    dvdc = float(obs[23]) if obs.size > 23 and np.isfinite(obs[23]) else 0.0
                    low_err = max(0.0, energy_vdc_low_pu - vdc_pu)
                    high_err = max(0.0, vdc_pu - energy_vdc_high_pu)
                    dvdc_pos = max(0.0, dvdc)
                    target[2] = float(
                        np.clip(
                            target[2]
                            + energy_low_d_gain * low_err
                            + energy_high_d_gain * high_err
                            + energy_dvdc_d_gain * dvdc_pos,
                            max(-energy_limit, energy_d_min),
                            min(energy_limit, energy_d_max),
                        )
                    )
                    target[3] = float(
                        np.clip(
                            target[3]
                            + energy_low_q_gain * low_err
                            + energy_high_q_gain * high_err
                            + energy_dvdc_q_gain * dvdc_pos,
                            max(-energy_limit, energy_q_min),
                            min(energy_limit, energy_q_max),
                        )
                    )
            if (
                topology2_phase_equivalent
                and str(row.get("topology", "")).lower() == "topology2"
                and float(row.get("actor_select_mode", 0.0) or 0.0) >= 1.5
                and target[0] < 0.0
            ):
                reg_d = float(target[0])
                target[0] = reg_d * np.cos(phase_shift_rad)
                target[1] = reg_d * np.sin(phase_shift_rad)
            window_zone = str(row.get("window_zone", "")).strip().lower()
            zone_mult = 1
            if window_zone in {"pre", "prefault"}:
                zone_mult = max(1, pre_window_repeat_mult)
            elif window_zone == "fault":
                zone_mult = max(1, fault_window_repeat_mult)
            elif window_zone == "recovery":
                zone_mult = max(1, recovery_window_repeat_mult)
            row_repeat = max(1, repeat) * zone_mult
            for _ in range(row_repeat):
                extra_x.append(obs)
                extra_y.append(target)

    if not extra_x:
        return X, Y, 0
    return (
        np.concatenate([X, np.asarray(extra_x, dtype=np.float32)], axis=0),
        np.concatenate([Y, np.asarray(extra_y, dtype=np.float32)], axis=0),
        len(extra_x),
    )


def append_raw_smoke_corrections(
    X: np.ndarray,
    Y: np.ndarray,
    csv_path: Path | None,
    *,
    repeat: int,
    energy_limit: float,
    topology2_phase_equivalent: bool,
    phase_shift_rad: float,
    scenario_types: str,
) -> tuple[np.ndarray, np.ndarray, int]:
    if csv_path is None:
        return X, Y, 0
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    extra_x: list[np.ndarray] = []
    extra_y: list[np.ndarray] = []
    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("mode") != "sac_actor_raw_guard0":
                continue
            if not _scenario_type_allowed(row, scenario_types):
                continue
            topology = str(row.get("topology", "")).lower()
            scenario_type = str(row.get("scenario_type", "")).lower()
            lv_mean = float(row.get("lv_mean") or 207.0)
            vpu = lv_mean / 207.0
            vpos = vpu
            obs_vdcpu = float(row.get("obs_vdcpu_mean") or 1.0)
            vdc_min_pu = float(row.get("vdc_min") or 800.0) / 800.0
            vdcpu = min(obs_vdcpu, vdc_min_pu)
            current_reg_d = float(row.get("reg_d_mean") or 0.0)
            current_reg_q = float(row.get("reg_q_mean") or 0.0)
            current_energy_d = float(row.get("energy_d_mean") or 0.0)
            current_energy_q = float(row.get("energy_q_mean") or 0.0)

            obs = np.zeros(OBS_DIM_HPT, dtype=np.float32)
            obs[0] = vpu
            obs[1] = vpos
            obs[2] = 0.0
            obs[3] = vdcpu
            obs[4] = 1.0 - vdcpu
            obs[5] = 1.0 - vpu
            obs[8] = current_reg_d
            obs[9] = current_reg_q
            obs[10] = current_energy_d
            obs[11] = current_energy_q
            obs[12] = 1.0 if vpos < 0.92 else 0.0
            obs[13] = 1.0 if vpos > 1.08 else 0.0
            obs[14] = 1.0 if topology == "topology1" else 0.0
            obs[15] = 1.0 if topology == "topology2" else 0.0
            obs[16] = float(row.get("obs_fault_flag_mean") or 0.0)
            obs[17] = float(row.get("obs_recovery_flag_mean") or 0.0)
            obs[20] = min(vpos, 1.0)
            obs[21] = max(vpos, 1.0)

            if topology == "topology1":
                reg_d = 0.32 + 2.35 * (1.0 - vpu)
                if vpu > 0.995:
                    reg_d = 0.26
                reg_d = float(np.clip(reg_d, 0.22, 0.46))
            elif scenario_type == "fault":
                reg_d = float(np.clip(20.0 * (1.0 - vpu), -0.60, 0.60))
            else:
                reg_d = current_reg_d + 1.8 * ((207.0 - lv_mean) / 207.0)
                reg_d = float(np.clip(reg_d, -0.60, 0.60))

            energy_d = 0.0
            if vdcpu < 0.95:
                dc_scale = float(np.clip((vdcpu - 0.75) / 0.20, 0.0, 1.0))
                reg_d *= dc_scale
                energy_d = min(energy_limit, 0.20 + 1.2 * (0.82 - vdcpu))
            elif vdcpu > 1.12:
                energy_d = max(-energy_limit, -0.05)

            target = np.asarray([reg_d, 0.0, energy_d, 0.0], dtype=np.float32)
            if (
                topology2_phase_equivalent
                and topology == "topology2"
                and scenario_type == "fault"
                and target[0] < 0.0
            ):
                raw_reg = float(target[0])
                target[0] = raw_reg * np.cos(phase_shift_rad)
                target[1] = raw_reg * np.sin(phase_shift_rad)

            for _ in range(max(1, repeat)):
                extra_x.append(obs)
                extra_y.append(target)

    if not extra_x:
        return X, Y, 0
    return (
        np.concatenate([X, np.asarray(extra_x, dtype=np.float32)], axis=0),
        np.concatenate([Y, np.asarray(extra_y, dtype=np.float32)], axis=0),
        len(extra_x),
    )


def append_energy_teacher_trace_samples(
    X: np.ndarray,
    Y: np.ndarray,
    csv_path: Path | None,
    *,
    repeat: int,
    reg_limit: float,
    energy_limit: float,
    dynamic_reg_limit_topology1: float,
    dynamic_reg_limit_topology2: float,
    topology2_phase_equivalent: bool,
    phase_shift_rad: float,
    scenario_types: str,
    min_time: float,
) -> tuple[np.ndarray, np.ndarray, int]:
    if csv_path is None:
        return X, Y, 0
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    extra_x: list[np.ndarray] = []
    extra_y: list[np.ndarray] = []
    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if not _scenario_type_allowed(row, scenario_types):
                continue
            if min_time > 0.0 and float(row.get("t") or 0.0) < min_time:
                continue
            obs = np.asarray(
                [float(row[f"obs_{idx:02d}"]) for idx in range(1, OBS_DIM_HPT + 1)],
                dtype=np.float32,
            )
            topology = str(row.get("topology", "")).lower()
            dynamic_mode = str(row.get("scenario_type", "")).lower() != "steady"
            if "target_action_01" in row and str(row.get("target_action_01", "")).strip():
                target = np.zeros(ACT_DIM_HPT, dtype=np.float32)
                target[0] = float(np.clip(float(row.get("target_action_01") or 0.0), -reg_limit, reg_limit))
                target[1] = float(np.clip(float(row.get("target_action_02") or 0.0), -reg_limit, reg_limit))
            else:
                target = execution_guard_teacher_action(
                    obs,
                    reg_limit=reg_limit,
                    energy_limit=energy_limit,
                    dynamic_mode=dynamic_mode,
                    dynamic_reg_limit_topology1=dynamic_reg_limit_topology1,
                    dynamic_reg_limit_topology2=dynamic_reg_limit_topology2,
                )
                if (
                    topology2_phase_equivalent
                    and topology == "topology2"
                    and dynamic_mode
                    and target[0] < 0.0
                ):
                    raw_reg = float(target[0])
                    target[0] = raw_reg * np.cos(phase_shift_rad)
                    target[1] = raw_reg * np.sin(phase_shift_rad)

            target[2] = float(
                np.clip(float(row.get("target_action_03") or 0.0), -energy_limit, energy_limit)
            )
            target[3] = float(
                np.clip(float(row.get("target_action_04") or 0.0), -energy_limit, energy_limit)
            )
            for _ in range(max(1, repeat)):
                extra_x.append(obs)
                extra_y.append(target.astype(np.float32))

    if not extra_x:
        return X, Y, 0
    return (
        np.concatenate([X, np.asarray(extra_x, dtype=np.float32)], axis=0),
        np.concatenate([Y, np.asarray(extra_y, dtype=np.float32)], axis=0),
        len(extra_x),
    )


def augment_observation_noise(
    X: np.ndarray,
    Y: np.ndarray,
    *,
    noise_std: float,
    repeat: int,
    seed: int,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Add local observation-neighborhood samples with unchanged targets.

    This is useful after switch-level DAgger traces: the actor must output the
    same safe action not only on the exact logged waveform, but also on nearby
    closed-loop states that it may induce itself.  Binary flags are kept
    unchanged.
    """

    if noise_std <= 0.0 or repeat <= 0 or X.size == 0:
        return X, Y, 0
    rng = np.random.default_rng(seed)
    noisy_x: list[np.ndarray] = []
    noisy_y: list[np.ndarray] = []
    mask = np.ones((OBS_DIM_HPT,), dtype=np.float32)
    # sag/swell/topology/fault/recovery flags should remain categorical.
    mask[12:18] = 0.0
    for _ in range(repeat):
        noise = rng.normal(0.0, noise_std, size=X.shape).astype(np.float32)
        x_aug = np.clip(X + noise * mask[None, :], -5.0, 5.0)
        noisy_x.append(x_aug.astype(np.float32))
        noisy_y.append(Y.astype(np.float32))
    return (
        np.concatenate([X, *noisy_x], axis=0),
        np.concatenate([Y, *noisy_y], axis=0),
        int(X.shape[0] * repeat),
    )


def build_or_load_model(args: argparse.Namespace, scenarios, config: HPTVoltageEnvConfig) -> SAC:
    vec = DummyVecEnv(
        [
            lambda: HPTVoltageSACEnv(
                scenarios,
                config=config,
                seed=args.seed,
                train_mode=True,
            )
        ]
    )
    if args.init_model is not None and args.init_model.exists():
        return SAC.load(str(args.init_model), env=vec, device=pick_device())
    return SAC(
        "MlpPolicy",
        vec,
        learning_rate=3e-4,
        buffer_size=100_000,
        batch_size=256,
        tau=0.005,
        gamma=0.99,
        train_freq=1,
        gradient_steps=1,
        policy_kwargs=dict(net_arch=[256, 256, 256]),
        device=pick_device(),
        seed=args.seed,
        verbose=0,
    )


def train_actor_bc(
    model: SAC,
    X: np.ndarray,
    Y: np.ndarray,
    *,
    epochs: int,
    batch_size: int,
    lr: float,
    seed: int,
    action_weights: tuple[float, float, float, float] = (4.0, 1.0, 0.5, 0.5),
    energy_head_only: bool = False,
) -> dict:
    device = model.policy.device
    obs = torch.as_tensor(X, dtype=torch.float32, device=device)
    target_action = torch.as_tensor(Y, dtype=torch.float32, device=device)
    act_low = torch.as_tensor(model.action_space.low, dtype=torch.float32, device=device)
    act_high = torch.as_tensor(model.action_space.high, dtype=torch.float32, device=device)
    target = 2.0 * (target_action - act_low) / torch.clamp(act_high - act_low, min=1e-6) - 1.0
    target = torch.clamp(target, -1.0, 1.0)
    weights = torch.as_tensor(action_weights, dtype=torch.float32, device=device)
    trainable_params = list(model.policy.actor.parameters())
    if energy_head_only:
        trainable_params = [
            parameter
            for name, parameter in model.policy.actor.named_parameters()
            if "mu.energy_head" in name
        ]
        if not trainable_params:
            raise ValueError(
                "energy_head_only BC requires a split-head actor with mu.energy_head parameters"
            )
    opt = torch.optim.Adam(trainable_params, lr=lr)
    rng = np.random.default_rng(seed)
    losses: list[float] = []
    n = X.shape[0]
    for _ in range(epochs):
        order = rng.permutation(n)
        for start in range(0, n, batch_size):
            idx = torch.as_tensor(order[start : start + batch_size], dtype=torch.long, device=device)
            pred = model.policy.actor(obs[idx], deterministic=True)
            loss = torch.mean(((pred - target[idx]) * weights) ** 2)
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(trainable_params, 5.0)
            opt.step()
            losses.append(float(loss.detach().cpu().item()))
    with torch.no_grad():
        pred = model.policy.actor(obs, deterministic=True)
        pred_action = act_low + 0.5 * (pred + 1.0) * (act_high - act_low)
        mse = torch.mean((pred_action - target_action) ** 2, dim=0).detach().cpu().numpy()
    return {
        "final_loss": float(losses[-1]) if losses else float("nan"),
        "mean_loss_tail": float(np.mean(losses[-min(50, len(losses)) :])) if losses else float("nan"),
        "action_mse": [float(v) for v in mse],
        "samples": int(n),
        "energy_head_only": bool(energy_head_only),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--curriculum",
        choices=[
            "all",
            "steady_step4",
            "topology2_fault",
            "switch_fault_transition",
            "expanded_fault_transition",
            "topology2_lvrt_family_v1",
            "topology2_lvrt_family_holdout_v1",
            "topology1_lvrt_balanced_family_v1",
        ],
        default="steady_step4",
    )
    parser.add_argument("--teacher-source", choices=["table", "execution_guard"], default="table")
    parser.add_argument("--seed", type=int, default=20260715)
    parser.add_argument("--episodes-per-scenario", type=int, default=24)
    parser.add_argument("--noise-std", type=float, default=0.08)
    parser.add_argument("--feedback-gain-topology1", type=float, default=1.2)
    parser.add_argument("--feedback-gain-topology2", type=float, default=0.0)
    parser.add_argument("--feedforward-scale-topology1", type=float, default=1.0)
    parser.add_argument("--feedforward-scale-topology2", type=float, default=1.0)
    parser.add_argument("--step4-correction-csv", type=Path, default=None)
    parser.add_argument("--step4-correction-repeat", type=int, default=512)
    parser.add_argument("--switch-trace-csv", type=Path, default=None)
    parser.add_argument("--switch-trace-repeat", type=int, default=4)
    parser.add_argument("--switch-trace-scenario-types", choices=["all", "steady", "fault"], default="all")
    parser.add_argument("--switch-trace-topologies", default="all")
    parser.add_argument("--switch-trace-condition-classes", default="all")
    parser.add_argument("--switch-trace-case-contains", default="all")
    parser.add_argument("--switch-trace-window-zones", default="all")
    parser.add_argument("--switch-trace-fixed-target", default=None)
    parser.add_argument("--switch-trace-energy-vdc-feedback-gain", type=float, default=0.0)
    parser.add_argument("--switch-trace-energy-vdc-ref-pu", type=float, default=1.0)
    parser.add_argument(
        "--switch-trace-energy-two-zone",
        action="store_true",
        help=(
            "Relabel energy-head targets from Vdc state: low-Vdc support and "
            "high-Vdc suppression use separate signed d/q gains."
        ),
    )
    parser.add_argument(
        "--switch-trace-energy-two-zone-all-topologies",
        action="store_true",
        help="Apply the two-zone energy relabeling to all topologies instead of topology2 only.",
    )
    parser.add_argument("--switch-trace-energy-vdc-low-pu", type=float, default=0.95)
    parser.add_argument("--switch-trace-energy-vdc-high-pu", type=float, default=1.12)
    parser.add_argument("--switch-trace-energy-low-d-gain", type=float, default=-2.0)
    parser.add_argument("--switch-trace-energy-low-q-gain", type=float, default=1.0)
    parser.add_argument("--switch-trace-energy-high-d-gain", type=float, default=0.20)
    parser.add_argument("--switch-trace-energy-high-q-gain", type=float, default=-0.80)
    parser.add_argument("--switch-trace-energy-dvdc-d-gain", type=float, default=0.0)
    parser.add_argument("--switch-trace-energy-dvdc-q-gain", type=float, default=-0.20)
    parser.add_argument("--switch-trace-energy-d-min", type=float, default=-0.95)
    parser.add_argument("--switch-trace-energy-d-max", type=float, default=0.95)
    parser.add_argument("--switch-trace-energy-q-min", type=float, default=-0.95)
    parser.add_argument("--switch-trace-energy-q-max", type=float, default=0.95)
    parser.add_argument("--switch-trace-q-gate-lv-min-pu", type=float, default=0.0)
    parser.add_argument("--switch-trace-q-gate-time-min-s", type=float, default=0.0)
    parser.add_argument("--switch-trace-q-gate-vdc-min-pu", type=float, default=0.0)
    parser.add_argument("--switch-trace-q-gate-vdc-max-pu", type=float, default=float("inf"))
    parser.add_argument("--switch-trace-q-gate-mode", choices=["binary", "continuous"], default="binary")
    parser.add_argument("--switch-trace-q-gate-lv-full-pu", type=float, default=float("inf"))
    parser.add_argument("--switch-trace-q-gate-time-full-s", type=float, default=float("inf"))
    parser.add_argument(
        "--switch-trace-fault-window-repeat-mult",
        type=int,
        default=1,
        help="Extra repeat multiplier for switch-trace samples with window_zone=fault.",
    )
    parser.add_argument(
        "--switch-trace-recovery-window-repeat-mult",
        type=int,
        default=1,
        help="Extra repeat multiplier for switch-trace samples with window_zone=recovery.",
    )
    parser.add_argument(
        "--switch-trace-pre-window-repeat-mult",
        type=int,
        default=1,
        help="Extra repeat multiplier for switch-trace samples with window_zone=pre.",
    )
    parser.add_argument(
        "--switch-trace-target-profile",
        choices=[
            "csv",
            "csv_file",
            "zero",
            "constant",
            "step",
            "ramp",
            "two_stage",
            "two_stage_window",
            "fault_window",
            "fault_recovery",
        ],
        default="csv",
        help="Relabel switch trace states with a generated trajectory profile instead of CSV action columns.",
    )
    parser.add_argument(
        "--switch-trace-target-columns",
        choices=["action", "actor_action"],
        default="action",
        help="When --switch-trace-target-profile=csv, choose executed action_* or raw actor_action_* trace columns.",
    )
    parser.add_argument("--switch-trace-profile-csv", type=Path, default=None)
    parser.add_argument("--switch-trace-profile-dt", type=float, default=0.002)
    parser.add_argument("--switch-trace-profile-stop-time", type=float, default=0.24)
    parser.add_argument("--switch-trace-profile-base-action", type=float, nargs=4, default=[0.0, 0.0, 0.0, 0.0])
    parser.add_argument("--switch-trace-profile-start-action", type=float, nargs=4, default=[0.0, 0.0, 0.0, 0.0])
    parser.add_argument("--switch-trace-profile-action", type=float, nargs=4, default=[0.0, 0.0, 0.0, 0.0])
    parser.add_argument("--switch-trace-profile-step-time", type=float, default=0.04)
    parser.add_argument("--switch-trace-profile-ramp-start", type=float, default=0.035)
    parser.add_argument("--switch-trace-profile-ramp-end", type=float, default=0.045)
    parser.add_argument("--switch-trace-profile-down-start", type=float, default=None)
    parser.add_argument("--switch-trace-profile-down-end", type=float, default=None)
    parser.add_argument("--switch-trace-topology2-phase-equivalent", action="store_true")
    parser.add_argument("--switch-trace-phase-shift-rad", type=float, default=0.55)
    parser.add_argument("--raw-smoke-correction-csv", type=Path, default=None)
    parser.add_argument("--raw-smoke-correction-repeat", type=int, default=512)
    parser.add_argument("--raw-smoke-correction-scenario-types", choices=["all", "steady", "fault"], default="all")
    parser.add_argument("--energy-teacher-trace-csv", type=Path, default=None)
    parser.add_argument("--energy-teacher-trace-repeat", type=int, default=16)
    parser.add_argument("--energy-teacher-trace-scenario-types", choices=["all", "steady", "fault"], default="all")
    parser.add_argument("--energy-teacher-min-time", type=float, default=0.0)
    parser.add_argument(
        "--anchor-dataset",
        type=Path,
        default=None,
        help=(
            "Optional .npz with observations/actions arrays.  This is used to "
            "clone switch-level supported trajectory anchors into a SAC-format "
            "actor checkpoint."
        ),
    )
    parser.add_argument("--anchor-dataset-repeat", type=int, default=1)
    parser.add_argument(
        "--bc-obs-noise-std",
        type=float,
        default=0.0,
        help="Gaussian observation noise for local BC robustness augmentation.",
    )
    parser.add_argument(
        "--bc-obs-noise-repeat",
        type=int,
        default=0,
        help="Number of noisy copies per BC sample.",
    )
    parser.add_argument(
        "--zero-energy-targets",
        action="store_true",
        help="Force BC targets action_03/action_04 to zero while validating regulating-bridge specialists.",
    )
    parser.add_argument(
        "--action-weights",
        default="4,1,0.5,0.5",
        help="Comma-separated BC loss weights for action_01..04.",
    )
    parser.add_argument("--epochs", type=int, default=240)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--reg-limit", type=float, default=0.80)
    parser.add_argument("--energy-limit", type=float, default=0.95)
    parser.add_argument("--teacher-prior-weight", type=float, default=30.0)
    parser.add_argument("--init-model", type=Path, default=None)
    parser.add_argument("--model-out", type=Path, default=MODELS / "hpt_voltage_sac_bc_warmstart.zip")
    args = parser.parse_args()

    run_id = args.run_id or f"hpt_sac_bc_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir = RESULTS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    args.model_out.parent.mkdir(parents=True, exist_ok=True)

    scenarios = select_scenarios(args.curriculum)
    config = make_env_config(args)
    X, Y = collect_teacher_samples(
        scenarios,
        config,
        episodes_per_scenario=args.episodes_per_scenario,
        noise_std=args.noise_std,
        feedback_gain_topology1=args.feedback_gain_topology1,
        feedback_gain_topology2=args.feedback_gain_topology2,
        feedforward_scale_topology1=args.feedforward_scale_topology1,
        feedforward_scale_topology2=args.feedforward_scale_topology2,
        teacher_source=args.teacher_source,
        seed=args.seed,
    )
    X, Y = append_step4_corrections(
        X,
        Y,
        args.step4_correction_csv,
        repeat=args.step4_correction_repeat,
        reg_limit=args.reg_limit,
    )
    X, Y, anchor_dataset_samples = append_anchor_dataset_samples(
        X,
        Y,
        args.anchor_dataset,
        repeat=args.anchor_dataset_repeat,
    )
    X, Y, switch_trace_samples = append_switch_trace_samples(
        X,
        Y,
        args.switch_trace_csv,
        repeat=args.switch_trace_repeat,
        topology2_phase_equivalent=args.switch_trace_topology2_phase_equivalent,
        phase_shift_rad=args.switch_trace_phase_shift_rad,
        scenario_types=args.switch_trace_scenario_types,
        topologies=args.switch_trace_topologies,
        condition_classes=args.switch_trace_condition_classes,
        case_contains=args.switch_trace_case_contains,
        window_zones=args.switch_trace_window_zones,
        fixed_target=args.switch_trace_fixed_target,
        energy_vdc_feedback_gain=args.switch_trace_energy_vdc_feedback_gain,
        energy_vdc_ref_pu=args.switch_trace_energy_vdc_ref_pu,
        energy_two_zone_enable=args.switch_trace_energy_two_zone,
        energy_two_zone_topology2_only=not args.switch_trace_energy_two_zone_all_topologies,
        energy_vdc_low_pu=args.switch_trace_energy_vdc_low_pu,
        energy_vdc_high_pu=args.switch_trace_energy_vdc_high_pu,
        energy_low_d_gain=args.switch_trace_energy_low_d_gain,
        energy_low_q_gain=args.switch_trace_energy_low_q_gain,
        energy_high_d_gain=args.switch_trace_energy_high_d_gain,
        energy_high_q_gain=args.switch_trace_energy_high_q_gain,
        energy_dvdc_d_gain=args.switch_trace_energy_dvdc_d_gain,
        energy_dvdc_q_gain=args.switch_trace_energy_dvdc_q_gain,
        energy_d_min=args.switch_trace_energy_d_min,
        energy_d_max=args.switch_trace_energy_d_max,
        energy_q_min=args.switch_trace_energy_q_min,
        energy_q_max=args.switch_trace_energy_q_max,
        energy_limit=args.energy_limit,
        q_gate_lv_min_pu=args.switch_trace_q_gate_lv_min_pu,
        q_gate_time_min_s=args.switch_trace_q_gate_time_min_s,
        q_gate_vdc_min_pu=args.switch_trace_q_gate_vdc_min_pu,
        q_gate_vdc_max_pu=args.switch_trace_q_gate_vdc_max_pu,
        q_gate_mode=args.switch_trace_q_gate_mode,
        q_gate_lv_full_pu=args.switch_trace_q_gate_lv_full_pu,
        q_gate_time_full_s=args.switch_trace_q_gate_time_full_s,
        fault_window_repeat_mult=args.switch_trace_fault_window_repeat_mult,
        recovery_window_repeat_mult=args.switch_trace_recovery_window_repeat_mult,
        pre_window_repeat_mult=args.switch_trace_pre_window_repeat_mult,
        target_profile=args.switch_trace_target_profile,
        target_columns=args.switch_trace_target_columns,
        profile_csv=args.switch_trace_profile_csv,
        profile_dt=args.switch_trace_profile_dt,
        profile_stop_time=args.switch_trace_profile_stop_time,
        profile_base_action=args.switch_trace_profile_base_action,
        profile_start_action=args.switch_trace_profile_start_action,
        profile_action=args.switch_trace_profile_action,
        profile_step_time=args.switch_trace_profile_step_time,
        profile_ramp_start=args.switch_trace_profile_ramp_start,
        profile_ramp_end=args.switch_trace_profile_ramp_end,
        profile_down_start=args.switch_trace_profile_down_start,
        profile_down_end=args.switch_trace_profile_down_end,
    )
    X, Y, raw_smoke_samples = append_raw_smoke_corrections(
        X,
        Y,
        args.raw_smoke_correction_csv,
        repeat=args.raw_smoke_correction_repeat,
        energy_limit=args.energy_limit,
        topology2_phase_equivalent=args.switch_trace_topology2_phase_equivalent,
        phase_shift_rad=args.switch_trace_phase_shift_rad,
        scenario_types=args.raw_smoke_correction_scenario_types,
    )
    X, Y, energy_teacher_samples = append_energy_teacher_trace_samples(
        X,
        Y,
        args.energy_teacher_trace_csv,
        repeat=args.energy_teacher_trace_repeat,
        reg_limit=args.reg_limit,
        energy_limit=args.energy_limit,
        dynamic_reg_limit_topology1=config.dynamic_reg_limit_topology1,
        dynamic_reg_limit_topology2=config.dynamic_reg_limit_topology2,
        topology2_phase_equivalent=args.switch_trace_topology2_phase_equivalent,
        phase_shift_rad=args.switch_trace_phase_shift_rad,
        scenario_types=args.energy_teacher_trace_scenario_types,
        min_time=args.energy_teacher_min_time,
    )
    if args.zero_energy_targets:
        Y[:, 2:4] = 0.0
    X, Y, obs_noise_samples = augment_observation_noise(
        X,
        Y,
        noise_std=args.bc_obs_noise_std,
        repeat=args.bc_obs_noise_repeat,
        seed=args.seed + 17,
    )
    if X.shape[0] == 0:
        raise ValueError(
            "No BC training samples matched the requested sources/filters. "
            "Check switch_trace_case_contains, topology, scenario_type, and window_zone filters."
        )
    model = build_or_load_model(args, scenarios, config)
    metrics = train_actor_bc(
        model,
        X,
        Y,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        seed=args.seed,
        action_weights=tuple(float(v) for v in args.action_weights.split(",")),
    )
    model.save(str(args.model_out))

    sidecar = {
        "run_id": run_id,
        "controller": "hpt-voltage-sac-bc-warmstart",
        "observation_dim": OBS_DIM_HPT,
        "action_dim": ACT_DIM_HPT,
        "curriculum": args.curriculum,
        "scenario_summary": scenario_summary(scenarios),
        "init_model": str(args.init_model) if args.init_model else None,
        "model_path": str(args.model_out),
        "config": {
            key: str(value) if isinstance(value, Path) else value
            for key, value in vars(args).items()
        },
        "metrics": {
            **metrics,
            "anchor_dataset_samples": int(anchor_dataset_samples),
            "switch_trace_augmented_samples": int(switch_trace_samples),
            "raw_smoke_correction_samples": int(raw_smoke_samples),
            "energy_teacher_trace_samples": int(energy_teacher_samples),
            "obs_noise_augmented_samples": int(obs_noise_samples),
        },
    }
    args.model_out.with_suffix(".json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    (run_dir / "summary.json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_actor_bc_warmstart",
        config=sidecar["config"],
        topology_models=TOPOLOGY_MODELS,
        policy_checkpoint=args.model_out,
        extra={"summary_path": str(run_dir / "summary.json")},
    )
    print(json.dumps(sidecar, indent=2), flush=True)


if __name__ == "__main__":
    main()
