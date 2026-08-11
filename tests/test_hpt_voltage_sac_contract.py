import json

import numpy as np
import pytest

from sac.hpt_voltage_sac_env import (
    ACT_DIM_HPT,
    OBS_DIM_HPT,
    HPTVoltageEnvConfig,
    HPTVoltageSACEnv,
    HPTVoltageScenario,
    classify_hpt_operating_condition,
    execution_guard_teacher_action,
    teacher_action,
)
from sac.hybrid_dc_channel import DCChannelInputs, HybridDCLinkChannel


def test_hpt_sac_env_contract_is_24_obs_4_action():
    env = HPTVoltageSACEnv(
        [HPTVoltageScenario(topology="topology1", grid_pu=0.9)],
        train_mode=False,
    )

    obs, _ = env.reset()

    assert env.observation_space.shape == (OBS_DIM_HPT,) == (24,)
    assert env.action_space.shape == (ACT_DIM_HPT,) == (4,)
    assert obs.shape == (24,)
    assert np.all(np.isfinite(obs))
    assert obs[14] == 1.0
    assert obs[15] == 0.0


def test_proxy_reports_v3_l1_without_claiming_pcc_or_full_frt():
    env = HPTVoltageSACEnv(
        [
            HPTVoltageScenario(
                topology="topology1",
                grid_pu=0.90,
                category="LVRT",
                fault_type="sym3ph",
                duration_s=0.10,
                fault_duration_s=0.06,
            )
        ],
        config=HPTVoltageEnvConfig(use_switch_calibration=False),
        train_mode=False,
    )
    env.reset()
    _, _, _, _, info = env.step(np.zeros(4, dtype=np.float32))

    assert info["validator_schema"] == "hpt-frt-gates-v3-gbt19963.1"
    assert info["target_gate"] == "L1"
    assert info["scenario_valid_evaluated"] is False
    assert info["l2_grid_code_ride_through_evaluated"] is False
    assert info["l3_full_frt_evaluated"] is False


def test_proxy_rejects_unavailable_l2_training_target():
    with pytest.raises(ValueError, match="Unsupported HPT target gate"):
        HPTVoltageSACEnv(
            [HPTVoltageScenario(topology="topology1", grid_pu=0.90)],
            config=HPTVoltageEnvConfig(target_gate="L2"),
            train_mode=False,
        )


def test_hpt_sac_obs_marks_topology2_context():
    env = HPTVoltageSACEnv(
        [HPTVoltageScenario(topology="topology2", grid_pu=1.1)],
        train_mode=False,
    )

    obs, _ = env.reset()

    assert obs[14] == 0.0
    assert obs[15] == 1.0


def test_teacher_boosts_sag_and_absorbs_swell():
    sag_env = HPTVoltageSACEnv(
        [HPTVoltageScenario(topology="topology1", grid_pu=0.90)],
        train_mode=False,
    )
    sag_obs, _ = sag_env.reset()
    sag_action = teacher_action(sag_obs)

    swell_env = HPTVoltageSACEnv(
        [HPTVoltageScenario(topology="topology2", grid_pu=1.10)],
        train_mode=False,
    )
    swell_obs, _ = swell_env.reset()
    swell_action = teacher_action(swell_obs)

    assert sag_action.shape == (4,)
    assert swell_action.shape == (4,)
    assert sag_action[0] > 0.0
    assert swell_action[0] < 0.0


def test_execution_guard_teacher_matches_topology1_steady_projection():
    env = HPTVoltageSACEnv(
        [HPTVoltageScenario(topology="topology1", grid_pu=0.90)],
        train_mode=False,
    )
    obs, _ = env.reset()

    action = execution_guard_teacher_action(obs, dynamic_mode=False)

    assert action.shape == (4,)
    assert action[0] == pytest.approx(0.46)
    assert np.allclose(action[1:], 0.0)


def test_execution_guard_teacher_matches_topology2_dynamic_law():
    env = HPTVoltageSACEnv(
        [
            HPTVoltageScenario(
                topology="topology2",
                grid_pu=0.90,
                category="LVRT",
                fault_type="sym3ph",
                fault_start_s=0.035,
                fault_duration_s=0.09,
            )
        ],
        train_mode=False,
    )
    obs, _ = env.reset()
    obs = obs.copy()
    obs[0] = 0.98

    action = execution_guard_teacher_action(obs, dynamic_mode=True)

    assert action.shape == (4,)
    assert action[0] == pytest.approx(0.40, abs=1e-6)
    assert np.allclose(action[1:], 0.0)


def test_corrective_action_improves_voltage_error_on_sag():
    env = HPTVoltageSACEnv(
        [HPTVoltageScenario(topology="topology1", grid_pu=0.90)],
        train_mode=False,
    )
    obs, _ = env.reset()
    initial_error = abs(1.0 - obs[0])

    for _ in range(10):
        action = teacher_action(obs)
        obs, _, terminated, truncated, _ = env.step(action)
        assert not terminated
        if truncated:
            break

    assert abs(1.0 - obs[0]) < initial_error


def test_table_teacher_ignores_stale_pre_v3_switch_sweep_target():
    env = HPTVoltageSACEnv(
        [HPTVoltageScenario(topology="topology1", grid_pu=0.90)],
        config=HPTVoltageEnvConfig(teacher_prior_weight=1.0),
        train_mode=False,
    )
    env.reset()

    _, _, _, _, info = env.step(np.asarray([0.0, 0.0, 0.0, 0.0], dtype=np.float32))

    # The active proxy is intentionally empty until v3 recalibration.  The
    # environment must therefore use its bounded analytic fallback instead of
    # silently consuming the archived pre-v3 switch-sweep table (> 0.50).
    assert 0.0 < info["teacher_m_reg_d"] < 0.50


def test_fault_transition_features_latch_and_recover():
    env = HPTVoltageSACEnv(
        [
            HPTVoltageScenario(
                topology="topology1",
                grid_pu=0.85,
                duration_s=0.24,
                category="LVRT",
                fault_type="sym3ph",
                fault_start_s=0.04,
                fault_duration_s=0.08,
            )
        ],
        train_mode=False,
    )
    obs, _ = env.reset()
    assert obs[16] == 0.0

    saw_fault = False
    saw_recovery = False
    for _ in range(140):
        obs, _, terminated, truncated, _ = env.step(teacher_action(obs))
        assert not terminated
        saw_fault = saw_fault or bool(obs[16] > 0.5)
        saw_recovery = saw_recovery or bool(obs[17] > 0.5)
        if truncated:
            break

    assert saw_fault
    assert saw_recovery


def test_default_scenarios_cover_both_topologies_and_frt_types():
    from sac.hpt_voltage_sac_env import default_hpt_voltage_scenarios

    scenarios = default_hpt_voltage_scenarios()
    topologies = {s.topology for s in scenarios}
    categories = {s.category for s in scenarios}
    fault_types = {s.fault_type for s in scenarios}

    assert topologies == {"topology1", "topology2"}
    assert {"steady", "LVRT", "HVRT"} <= categories
    assert {"sym3ph", "1ph_g", "2ph", "2ph_g", "swell_3ph", "swell_1ph"} <= fault_types


def test_fault_condition_classifier_covers_sag_swell_and_asymmetry():
    assert classify_hpt_operating_condition(1.00, 0.00, grid_pu=1.00) == "nominal"
    assert classify_hpt_operating_condition(0.90, 0.00, grid_pu=0.90) == "sag"
    assert classify_hpt_operating_condition(1.10, 0.00, grid_pu=1.10) == "swell"
    assert classify_hpt_operating_condition(0.92, 0.08, grid_pu=0.90) == "asymmetric_sag"
    assert classify_hpt_operating_condition(1.08, 0.08, grid_pu=1.12) == "asymmetric_swell"


def test_hybrid_dc_channel_is_region_gated(tmp_path):
    model_path = tmp_path / "dc_model.json"
    model_path.write_text(
        json.dumps(
            {
                "schema": "hpt-proxy-v5-dc-link-energy-correction",
                "feature_names": ["bias"],
                "feature_mean": [0.0],
                "feature_scale": [1.0],
                "coef": [1.0],
                "tau_s": 0.02,
                "vdc_min": 0.45,
                "vdc_max": 1.30,
                "max_step_pu": 0.035,
            }
        ),
        encoding="utf-8",
    )
    cfg = HPTVoltageEnvConfig(
        use_switch_calibration=False,
        calibration_path="",
        hybrid_dc_channel_enable=True,
        hybrid_dc_model_path=str(model_path),
    )
    edge_env = HPTVoltageSACEnv(
        [
            HPTVoltageScenario(
                topology="topology2",
                grid_pu=0.825,
                duration_s=0.24,
                category="LVRT",
                fault_type="1ph_g",
                fault_start_s=0.04,
                fault_duration_s=0.12,
            )
        ],
        config=cfg,
        train_mode=False,
    )
    edge_env.reset()
    sources = []
    for _ in range(30):
        _, _, _, _, info = edge_env.step(np.zeros(4, dtype=np.float32))
        sources.append(info["hybrid_dc_channel_source"])

    assert "v4_default_dc" in sources
    assert "v5_boundary_dc" in sources

    non_edge_env = HPTVoltageSACEnv(
        [
            HPTVoltageScenario(
                topology="topology2",
                grid_pu=0.925,
                duration_s=0.18,
                category="LVRT",
                fault_type="1ph_g",
                fault_start_s=0.04,
                fault_duration_s=0.06,
            )
        ],
        config=cfg,
        train_mode=False,
    )
    non_edge_env.reset()
    non_edge_sources = []
    for _ in range(30):
        _, _, _, _, info = non_edge_env.step(np.zeros(4, dtype=np.float32))
        non_edge_sources.append(info["hybrid_dc_channel_source"])

    assert set(non_edge_sources) == {"v4_default_dc"}


def test_vdc_lower_barrier_can_terminate_rollout():
    env = HPTVoltageSACEnv(
        [HPTVoltageScenario(topology="topology2", grid_pu=0.90)],
        config=HPTVoltageEnvConfig(
            use_switch_calibration=False,
            calibration_path="",
            vdc_lower_barrier_reward_weight=10.0,
            vdc_lower_barrier_start_pu=0.84,
            vdc_lower_barrier_floor_pu=0.8125,
            vdc_low_terminal_enable=True,
            vdc_low_terminal_pu=0.8125,
            vdc_low_terminal_penalty=25.0,
        ),
        train_mode=False,
    )
    env.reset()
    env.vdc = 0.70

    _, reward, terminated, _, info = env.step(np.zeros(4, dtype=np.float32))

    assert terminated
    assert reward < -25.0
    assert info["cost_vdc_lower_barrier"] > 0.0


def test_hybrid_dc_channel_supports_delta_vdc_profile_blocks(tmp_path):
    model_path = tmp_path / "dc_delta_profile.json"
    model_path.write_text(
        json.dumps(
            {
                "schema": "hpt-proxy-v5-dc-link-energy-correction",
                "target": "delta_vdc",
                "feature_names": ["bias"],
                "feature_mean": [0.0],
                "feature_scale": [1.0],
                "coef": [-0.01],
                "tau_s": 0.0,
                "vdc_min": 0.45,
                "vdc_max": 1.30,
                "max_step_pu": 0.10,
                "blocks": [
                    {
                        "fault_pu": 0.825,
                        "duration_ms": 120.0,
                        "zone": "recovery",
                        "target": "delta_vdc",
                        "feature_names": ["bias"],
                        "feature_mean": [0.0],
                        "feature_scale": [1.0],
                        "coef": [0.05],
                        "tau_s": 0.0,
                        "max_step_pu": 0.10,
                        "profile_time_s": [0.0, 0.002],
                        "profile_next_vdc": [0.90, 0.88],
                        "profile_blend": 1.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    channel = HybridDCLinkChannel(model_path)
    pred = channel.predict_next_vdc(
        DCChannelInputs(
            vdc=1.0,
            grid_cmd=1.0,
            grid_v_mag=1.0,
            energy_v_mag=1.0,
            fault_flag=0.0,
            recovery_flag=1.0,
            time_in_fault=0.12,
            time_in_recovery=0.0,
            m_reg_d=0.0,
            m_reg_q=0.0,
            m_energy_d=0.0,
            m_energy_q=0.0,
            grid_i_d=0.0,
            grid_i_q=0.0,
            energy_i_d=0.0,
            energy_i_q=0.0,
            dt=0.002,
            fault_pu=0.825,
            duration_ms=120.0,
        )
    )

    assert pred == pytest.approx(0.90)


def test_slow_state_profile_correction_updates_proxy_state(tmp_path):
    model_path = tmp_path / "slow_state_correction.json"
    model_path.write_text(
        json.dumps(
            {
                "schema": "hpt-slow-state-family-profile-correction-v1",
                "blocks": [
                    {
                        "fault_pu": 0.825,
                        "duration_ms": 120.0,
                        "zone": "fault",
                        "time_s": [0.0, 0.002],
                        "profile_blend": 1.0,
                        "v_lv_correction": [0.05, 0.05],
                        "grid_i_mag_correction": [-0.10, -0.10],
                        "energy_i_mag_correction": [0.0, 0.0],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    env = HPTVoltageSACEnv(
        [
            HPTVoltageScenario(
                topology="topology2",
                grid_pu=0.825,
                duration_s=0.18,
                category="LVRT",
                fault_type="1ph_g",
                fault_start_s=0.0,
                fault_duration_s=0.12,
            )
        ],
        config=HPTVoltageEnvConfig(
            use_switch_calibration=False,
            calibration_path="",
            slow_state_correction_enable=True,
            slow_state_correction_path=str(model_path),
        ),
        train_mode=False,
    )
    env.reset()

    _, _, _, _, info = env.step(np.zeros(4, dtype=np.float32))

    assert info["slow_state_correction_source"] == "profile_correction"
    assert info["v_lv_pu"] == pytest.approx(0.875)
    assert info["grid_current_peak_pu"] < 1.23
