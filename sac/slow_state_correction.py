"""Profile correction channel for slow HPT proxy states and diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np


SCHEMAS = {
    "hpt-slow-state-profile-correction-v1",
    "hpt-slow-state-family-profile-correction-v1",
    "hpt-slow-state-family-profile-correction-v2",
}


@dataclass(frozen=True)
class SlowStateCorrectionInputs:
    fault_pu: float
    duration_ms: float
    fault_flag: float
    recovery_flag: float
    time_in_fault: float
    time_in_recovery: float
    v_lv: float
    grid_i_mag: float
    energy_i_mag: float
    m_reg_d: float = 0.0
    m_reg_q: float = 0.0
    m_energy_d: float = 0.0
    m_energy_q: float = 0.0


class SlowStateProfileCorrection:
    """Nearest-block profile correction for LV voltage and current metrics."""

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
        if data.get("schema") not in SCHEMAS:
            raise ValueError(
                f"Unsupported slow-state correction schema in {path}: {data.get('schema')!r}"
            )
        self.model_path = path
        self.data = data
        self.blocks = list(data.get("blocks", []))
        self.action_features = list(
            data.get(
                "action_features",
                ["m_reg_d", "m_reg_q", "m_energy_d", "m_energy_q"],
            )
        )
        self.action_residual_gains = dict(data.get("action_residual_gains", {}))
        self.fault_pu_max = float(fault_pu_max)
        self.duration_ms_min = float(duration_ms_min)
        self.duration_ms_max = float(duration_ms_max)

    def applies_to(self, fault_pu: float, duration_ms: float) -> bool:
        return (
            float(fault_pu) <= self.fault_pu_max
            and self.duration_ms_min <= float(duration_ms) <= self.duration_ms_max
        )

    def correct(self, sample: SlowStateCorrectionInputs) -> dict[str, float] | None:
        if not self.applies_to(sample.fault_pu, sample.duration_ms):
            return None
        block = self._select_block(sample)
        if block is None:
            return None
        zone = str(block.get("zone", ""))
        t = float(sample.time_in_fault if zone == "fault" else sample.time_in_recovery)
        time_s = np.asarray(block.get("time_s", []), dtype=float)
        if time_s.size == 0:
            return None
        blend = float(block.get("profile_blend", 1.0))

        def apply(name: str, value: float) -> float:
            key = f"{name}_correction"
            if key not in block:
                return float(value)
            corr = np.asarray(block[key], dtype=float)
            correction = float(np.interp(t, time_s, corr))
            action_residual = self._action_residual(name, zone, t, time_s, block, sample)
            return float(value) + blend * correction + action_residual

        return {
            "v_lv": apply("v_lv", sample.v_lv),
            "grid_i_mag": max(0.0, apply("grid_i_mag", sample.grid_i_mag)),
            "energy_i_mag": max(0.0, apply("energy_i_mag", sample.energy_i_mag)),
            "source": 1.0,
        }

    def _select_block(self, sample: SlowStateCorrectionInputs) -> dict | None:
        if not self.blocks:
            return None
        zone = "fault" if float(sample.fault_flag) > 0.5 else "recovery"
        if float(sample.fault_flag) <= 0.5 and float(sample.recovery_flag) <= 0.5:
            zone = "tail"
        candidates = [b for b in self.blocks if str(b.get("zone", "")) == zone]
        if not candidates:
            candidates = self.blocks
        fault_pu = float(sample.fault_pu)
        duration_ms = float(sample.duration_ms)

        def score(block: dict) -> float:
            return abs(float(block.get("fault_pu", fault_pu)) - fault_pu) / 0.025 + (
                abs(float(block.get("duration_ms", duration_ms)) - duration_ms) / 20.0
            )

        return min(candidates, key=score)

    def _action_residual(
        self,
        name: str,
        zone: str,
        t: float,
        time_s: np.ndarray,
        block: dict,
        sample: SlowStateCorrectionInputs,
    ) -> float:
        gains_by_zone = self.action_residual_gains.get(str(zone), {})
        item = gains_by_zone.get(name)
        if not item:
            return 0.0
        gains = np.asarray(item.get("gains", []), dtype=float)
        if gains.size != len(self.action_features):
            return 0.0
        sample_action = {
            "m_reg_d": float(sample.m_reg_d),
            "m_reg_q": float(sample.m_reg_q),
            "m_energy_d": float(sample.m_energy_d),
            "m_energy_q": float(sample.m_energy_q),
        }
        deltas: list[float] = []
        for feature in self.action_features:
            profile_key = feature + "_profile"
            profile = np.asarray(block.get(profile_key, []), dtype=float)
            if profile.size != time_s.size:
                return 0.0
            baseline = float(np.interp(t, time_s, profile))
            deltas.append(float(sample_action.get(feature, 0.0)) - baseline)
        raw = float(np.dot(gains, np.asarray(deltas, dtype=float)))
        limit = float(item.get("limit", 0.0))
        if limit > 0.0:
            raw = float(np.clip(raw, -limit, limit))
        return raw
