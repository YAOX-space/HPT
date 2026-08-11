"""Physics-informed DC-link correction channel for the HPT SAC proxy."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np


SCHEMA = "hpt-proxy-v5-dc-link-energy-correction"


@dataclass(frozen=True)
class DCChannelInputs:
    """One control-step state/action sample for the DC-link channel."""

    vdc: float
    grid_cmd: float
    grid_v_mag: float
    energy_v_mag: float
    fault_flag: float
    recovery_flag: float
    time_in_fault: float
    time_in_recovery: float
    m_reg_d: float
    m_reg_q: float
    m_energy_d: float
    m_energy_q: float
    grid_i_d: float
    grid_i_q: float
    energy_i_d: float
    energy_i_q: float
    dt: float
    fault_pu: float
    duration_ms: float


class HybridDCLinkChannel:
    """Region-gated DC-link model fitted from timestep-level Simulink traces."""

    def __init__(
        self,
        model_path: str | Path,
        *,
        fault_pu_max: float = 0.85,
        duration_ms_min: float = 100.0,
        duration_ms_max: float = 180.0,
    ) -> None:
        path = Path(model_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != SCHEMA:
            raise ValueError(f"Unsupported DC-link channel schema in {path}: {data.get('schema')!r}")
        self.model_path = path
        self.feature_names = [str(v) for v in data["feature_names"]]
        self.mean = np.asarray(data["feature_mean"], dtype=float)
        self.scale = np.asarray(data["feature_scale"], dtype=float)
        self.coef = np.asarray(data["coef"], dtype=float)
        self.target = str(data.get("target", "stable_vdc_equilibrium"))
        self.blocks = list(data.get("blocks", []))
        self.tau_s = float(data["tau_s"])
        self.vdc_min = float(data["vdc_min"])
        self.vdc_max = float(data["vdc_max"])
        self.max_step_pu = float(data["max_step_pu"])
        self.fault_pu_max = float(fault_pu_max)
        self.duration_ms_min = float(duration_ms_min)
        self.duration_ms_max = float(duration_ms_max)
        if len(self.feature_names) != self.mean.size or self.mean.size != self.scale.size:
            raise ValueError(f"Feature metadata length mismatch in {path}")
        if self.coef.size != self.mean.size:
            raise ValueError(f"Coefficient length mismatch in {path}")

    def applies_to(self, fault_pu: float, duration_ms: float) -> bool:
        """Use the learned DC correction only inside the validated boundary region."""

        return (
            float(fault_pu) <= self.fault_pu_max
            and self.duration_ms_min <= float(duration_ms) <= self.duration_ms_max
        )

    def predict_next_vdc(self, sample: DCChannelInputs) -> float | None:
        """Return the corrected next-step DC-link voltage, or None outside the gate."""

        if not self.applies_to(sample.fault_pu, sample.duration_ms):
            return None
        features = self._feature_values(sample)
        model = self._select_model(sample)
        feature_names = [str(v) for v in model.get("feature_names", self.feature_names)]
        mean = np.asarray(model.get("feature_mean", self.mean), dtype=float)
        scale = np.asarray(model.get("feature_scale", self.scale), dtype=float)
        coef = np.asarray(model.get("coef", self.coef), dtype=float)
        target = str(model.get("target", self.target))
        tau_s = float(model.get("tau_s", self.tau_s))
        max_step_pu = float(model.get("max_step_pu", self.max_step_pu))

        row = np.asarray([features.get(name, 0.0) for name in feature_names], dtype=float)
        scaled = (row - mean) / scale
        if target == "delta_vdc":
            raw = float(sample.vdc) + float(scaled @ coef)
        elif target == "next_vdc":
            raw = float(scaled @ coef)
        else:
            beta = float(
                np.clip(
                    1.0 - np.exp(-float(sample.dt) / max(tau_s, 1e-9)),
                    1e-4,
                    1.0,
                )
            )
            eq = float(np.clip(scaled @ coef, self.vdc_min, self.vdc_max))
            raw = (1.0 - beta) * float(sample.vdc) + beta * eq
        if "profile_time_s" in model and "profile_next_vdc" in model:
            model_raw = raw
            zone = str(model.get("zone", ""))
            if zone == "fault":
                profile_time = float(sample.time_in_fault) + float(sample.dt)
            else:
                profile_time = float(sample.time_in_recovery) + float(sample.dt)
            profile_target = float(
                self._action_local_profile_target(sample, model, zone, profile_time)
            )
            blend = float(model.get("profile_blend", 0.0))
            raw = (1.0 - blend) * raw + blend * profile_target
            residual_blend = float(model.get("profile_residual_blend", 0.0))
            if residual_blend:
                residual_limit = float(model.get("profile_residual_limit_pu", 0.02))
                residual = float(np.clip(model_raw - profile_target, -residual_limit, residual_limit))
                raw += residual_blend * residual
            if "profile_m_energy_d" in model:
                baseline_med = float(
                    np.interp(
                        profile_time,
                        np.asarray(model["profile_time_s"], dtype=float),
                        np.asarray(model["profile_m_energy_d"], dtype=float),
                    )
                )
                med_delta = float(sample.m_energy_d) - baseline_med
                med_gain = float(model.get("profile_m_energy_d_gain", 0.0))
                med_limit = float(model.get("profile_m_energy_d_step_limit_pu", 0.001))
                raw += float(np.clip(med_gain * med_delta, -med_limit, med_limit))
        limited = float(
            np.clip(
                raw,
                float(sample.vdc) - max_step_pu,
                float(sample.vdc) + max_step_pu,
            )
        )
        return float(np.clip(limited, self.vdc_min, self.vdc_max))

    def _action_local_profile_target(
        self,
        sample: DCChannelInputs,
        selected_model: dict,
        zone: str,
        profile_time: float,
    ) -> float:
        if float(selected_model.get("action_distance_weight", 0.0)) <= 0.0:
            return float(
                np.interp(
                    profile_time,
                    np.asarray(selected_model["profile_time_s"], dtype=float),
                    np.asarray(selected_model["profile_next_vdc"], dtype=float),
                )
            )
        fault_pu = float(sample.fault_pu)
        duration_ms = float(sample.duration_ms)
        candidates = [
            b
            for b in self.blocks
            if str(b.get("zone", "")) == zone
            and abs(float(b.get("fault_pu", fault_pu)) - fault_pu) <= 1e-9
            and abs(float(b.get("duration_ms", duration_ms)) - duration_ms) <= 1e-9
            and "profile_time_s" in b
            and "profile_next_vdc" in b
        ]
        if not candidates:
            candidates = [selected_model]
        distances: list[float] = []
        targets: list[float] = []
        for block in candidates:
            distance = self._action_profile_score(sample, block, zone)
            target = float(
                np.interp(
                    profile_time,
                    np.asarray(block["profile_time_s"], dtype=float),
                    np.asarray(block["profile_next_vdc"], dtype=float),
                )
            )
            distances.append(float(max(0.0, distance)))
            targets.append(target)
        d = np.asarray(distances, dtype=float)
        y = np.asarray(targets, dtype=float)
        if d.size == 0:
            return float(
                np.interp(
                    profile_time,
                    np.asarray(selected_model["profile_time_s"], dtype=float),
                    np.asarray(selected_model["profile_next_vdc"], dtype=float),
                )
            )
        if float(np.min(d)) < 1e-6:
            return float(y[int(np.argmin(d))])
        weights = 1.0 / (d * d + 1e-6)
        weights = weights / np.sum(weights)
        return float(np.sum(weights * y))

    def _select_model(self, sample: DCChannelInputs) -> dict:
        if not self.blocks:
            return {}
        zone = "fault" if float(sample.fault_flag) > 0.5 else "recovery"
        if float(sample.fault_flag) <= 0.5 and float(sample.recovery_flag) <= 0.5:
            zone = "tail"
        candidates = [b for b in self.blocks if str(b.get("zone", "")) == zone]
        if not candidates:
            candidates = self.blocks
        fault_pu = float(sample.fault_pu)
        duration_ms = float(sample.duration_ms)

        def score(block: dict) -> float:
            fault_duration_score = abs(float(block.get("fault_pu", fault_pu)) - fault_pu) / 0.025 + (
                abs(float(block.get("duration_ms", duration_ms)) - duration_ms) / 20.0
            )
            return fault_duration_score + self._action_profile_score(sample, block, zone)

        return min(candidates, key=score)

    @staticmethod
    def _action_profile_score(sample: DCChannelInputs, block: dict, zone: str) -> float:
        weight = float(block.get("action_distance_weight", 0.0))
        if weight <= 0.0:
            return 0.0
        action = np.asarray(
            [
                float(sample.m_reg_d),
                float(sample.m_reg_q),
                float(sample.m_energy_d),
                float(sample.m_energy_q),
            ],
            dtype=float,
        )
        feature_names = ["m_reg_d", "m_reg_q", "m_energy_d", "m_energy_q"]
        profile_time = np.asarray(block.get("profile_time_s", []), dtype=float)
        if profile_time.size > 0 and all((f"profile_{name}" in block) for name in feature_names):
            if zone == "fault":
                t = float(sample.time_in_fault) + float(sample.dt)
            else:
                t = float(sample.time_in_recovery) + float(sample.dt)
            baseline = np.asarray(
                [
                    float(np.interp(t, profile_time, np.asarray(block[f"profile_{name}"], dtype=float)))
                    for name in feature_names
                ],
                dtype=float,
            )
        elif "profile_action_mean" in block:
            baseline = np.asarray(block["profile_action_mean"], dtype=float)
            if baseline.size != 4:
                return 0.0
        else:
            return 0.0
        scales = np.asarray(block.get("action_distance_scales", [0.12, 0.12, 0.12, 0.12]), dtype=float)
        if scales.size != 4:
            scales = np.asarray([0.12, 0.12, 0.12, 0.12], dtype=float)
        scales = np.maximum(scales, 1e-6)
        delta = (action - baseline) / scales
        return float(weight * np.sqrt(np.mean(delta * delta)))

    @staticmethod
    def _feature_values(sample: DCChannelInputs) -> dict[str, float]:
        vdc = float(sample.vdc)
        grid_v = float(sample.grid_v_mag)
        energy_v = float(sample.energy_v_mag)
        grid_id = float(sample.grid_i_d)
        grid_iq = float(sample.grid_i_q)
        energy_id = float(sample.energy_i_d)
        energy_iq = float(sample.energy_i_q)
        mrd = float(sample.m_reg_d)
        mrq = float(sample.m_reg_q)
        med = float(sample.m_energy_d)
        meq = float(sample.m_energy_q)
        fault_flag = float(sample.fault_flag)
        recovery_flag = float(sample.recovery_flag)
        time_in_recovery = float(sample.time_in_recovery)
        chopper_thr_pu = 850.0 / 800.0

        values = {
            "bias": 1.0,
            "vdc": vdc,
            "vdc_minus_1": vdc - 1.0,
            "vdc_sq_minus_1": vdc * vdc - 1.0,
            "grid_cmd": float(sample.grid_cmd),
            "grid_v_mag": grid_v,
            "energy_v_mag": energy_v,
            "fault_flag": fault_flag,
            "recovery_flag": recovery_flag,
            "time_in_fault": float(sample.time_in_fault),
            "time_in_recovery": time_in_recovery,
            "m_reg_d": mrd,
            "m_reg_q": mrq,
            "m_energy_d": med,
            "m_energy_q": meq,
            "reg_action_mag": float(np.hypot(mrd, mrq)),
            "energy_action_mag": float(np.hypot(med, meq)),
            "grid_i_d": grid_id,
            "grid_i_q": grid_iq,
            "energy_i_d": energy_id,
            "energy_i_q": energy_iq,
            "grid_i_mag": float(np.hypot(grid_id, grid_iq)),
            "energy_i_mag": float(np.hypot(energy_id, energy_iq)),
        }
        values["p_grid_proxy"] = grid_v * grid_id
        values["q_grid_proxy"] = grid_v * grid_iq
        values["p_energy_terminal"] = energy_v * energy_id
        values["q_energy_terminal"] = energy_v * energy_iq
        values["p_reg_mod"] = vdc * (mrd * grid_id + mrq * grid_iq)
        values["p_energy_mod"] = vdc * (med * energy_id + meq * energy_iq)
        values["p_mod_balance"] = values["p_energy_mod"] - values["p_reg_mod"]
        values["p_terminal_balance"] = values["p_energy_terminal"] - values["p_grid_proxy"]
        values["chopper_excess_sq"] = max(0.0, vdc - chopper_thr_pu) ** 2
        values["dc_loss_linear"] = vdc - 1.0
        values["recovery_p_balance"] = recovery_flag * values["p_mod_balance"]
        values["recovery_chopper"] = recovery_flag * values["chopper_excess_sq"]
        values["fault_p_balance"] = fault_flag * values["p_mod_balance"]
        values["recovery_time"] = recovery_flag * time_in_recovery
        values["recovery_time_sq"] = values["recovery_time"] * values["recovery_time"]
        values["recovery_vdc_error_time"] = values["recovery_time"] * values["vdc_minus_1"]
        values["fault_pu"] = float(sample.fault_pu)
        values["duration_s"] = float(sample.duration_ms) / 1000.0
        values["fault_pu_recovery"] = values["fault_pu"] * recovery_flag
        values["duration_recovery"] = values["duration_s"] * recovery_flag
        values["t_ms_recovery"] = (
            float(sample.time_in_fault) + float(sample.time_in_recovery)
        ) * recovery_flag
        values["vdc_recovery"] = vdc * recovery_flag
        values["energy_mag_recovery"] = values["energy_action_mag"] * recovery_flag
        return values
