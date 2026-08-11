import numpy as np

from sac.hpt_voltage_sac_env import (
    HPTVoltageEnvConfig,
    HPTVoltageSACEnv,
    HPTVoltageScenario,
)


def _one_step(scale: float):
    scenario = HPTVoltageScenario(
        topology="topology2",
        grid_pu=0.60,
        neg_seq_pu=0.20,
        fault_phase_key="a",
        duration_s=0.365,
        category="LVRT",
        fault_type="1ph_g",
        fault_start_s=0.08,
        fault_duration_s=0.16,
    )
    env = HPTVoltageSACEnv(
        [scenario],
        config=HPTVoltageEnvConfig(reward_scale=scale, calibration_path=""),
        seed=7,
        train_mode=False,
    )
    env.reset(seed=7)
    return env.step(np.asarray([0.06, 0.0, 0.0, 0.60], dtype=np.float32))


def test_reward_scale_preserves_transition_and_scales_complete_reward() -> None:
    obs_one, reward_one, term_one, trunc_one, info_one = _one_step(1.0)
    obs_scaled, reward_scaled, term_scaled, trunc_scaled, info_scaled = _one_step(1e-3)

    np.testing.assert_allclose(obs_scaled, obs_one, rtol=0.0, atol=0.0)
    assert term_scaled == term_one
    assert trunc_scaled == trunc_one
    np.testing.assert_allclose(reward_scaled, reward_one * 1e-3, rtol=1e-7)
    np.testing.assert_allclose(info_one["reward_unscaled"], reward_one, rtol=1e-7)
    np.testing.assert_allclose(info_scaled["reward_unscaled"], reward_one, rtol=1e-7)
    assert info_scaled["reward_scale"] == 1e-3
