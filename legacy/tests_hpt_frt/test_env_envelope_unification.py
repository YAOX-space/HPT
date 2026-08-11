"""test_env_envelope_unification — HPTFRTEnvV2 must trip on the VERSIONED frt_v2 envelope, not the
legacy frt-v1 residual-0.05 / static-1.32 boundary (audit round-4 B)."""
import numpy as np
import pytest
from hpt_frt.common import frt_v2 as FV2
from hpt_frt.device import frt_env as L
from hpt_frt.device.frt_metrics import evaluate_scenario
from hpt_frt.device.frt_env_v2 import HPTFRTEnvV2
from hpt_frt.device.overnight_constrained_projection import ProjectionPolicy, ProjectionSpec
from hpt_frt.device.residual_env import HPTFRTResidualEnvV2

SC = dict(scenario_id=1, family_id=1, category='LVRT', fault_type='sym3ph', target_V_pu=0.5,
          grid='weak', scr=3.0, t_fault=0.02, fault_dur=0.6, T_sim=2.5, random_seed=1)


# ---- the unified versioned envelope interface ----
def test_lvrt_envelope_hold_625ms_and_reach_2s():
    res = 0.4
    assert FV2.lvrt_lower_env(0.0, res) == 0.20
    assert FV2.lvrt_lower_env(0.624, res) == 0.20
    assert FV2.lvrt_lower_env(0.625, res) == 0.20
    mid = FV2.lvrt_lower_env(1.3125, res)                       # halfway hold(0.625)->reach(2.0)
    assert 0.20 < mid < 0.9 and mid == pytest.approx(0.55, abs=1e-9)
    assert FV2.lvrt_lower_env(2.0, res) == pytest.approx(0.9)   # recovered to 0.9 by 2 s
    assert FV2.lvrt_lower_env(3.0, res) == pytest.approx(0.9)


def test_hvrt_envelope_500ms_1s_steps():
    assert FV2.hvrt_upper_env(0.4) == 1.30
    assert FV2.hvrt_upper_env(0.5) == 1.30                      # <=500 ms
    assert FV2.hvrt_upper_env(0.6) == 1.25                      # (500ms,1s]
    assert FV2.hvrt_upper_env(1.0) == 1.25
    assert FV2.hvrt_upper_env(1.1) == 1.20                      # (1s,10s]
    assert FV2.hvrt_upper_env(10.1) == 1.10                     # >10s


def test_within_envelope_uses_solver_tol_only():
    res = 0.5
    # exactly on boundary passes; below by more than tol fails
    assert FV2.within_envelope('LVRT', 0.1, res, 0.20)
    assert not FV2.within_envelope('LVRT', 0.1, res, 0.18)
    assert FV2.within_envelope('LVRT', 0.1, res, 0.20 - FV2.DEFAULT_SOLVER_TOL / 2)


# ---- the V2 ENV trips on the versioned boundary, not the legacy one ----
def _trip_at(env_cls, v2p, residual=0.5, t_rel_real=0.1):
    e = env_cls([{**SC, 'target_V_pu': residual}]); e.reset()
    e._sc = {**SC, 'target_V_pu': residual}
    e.t = SC['t_fault'] + t_rel_real * L.TSCALE   # compressed time for real t_rel
    e.V2p = v2p
    return e._lvrt_floor(e.t - e._sc['t_fault']), e._trip_tol()


def test_v2_floor_is_versioned_not_legacy():
    res = 0.5
    floor_v2, tol = _trip_at(HPTFRTEnvV2, res, residual=res)
    floor_legacy = L.lvrt_envelope(0.1 * L.TSCALE, res)
    assert floor_v2 == pytest.approx(0.20)                     # standard: fixed floor
    assert floor_legacy == pytest.approx(res - 0.05)           # legacy: residual - 0.05
    assert floor_v2 != floor_legacy
    assert tol == FV2.DEFAULT_SOLVER_TOL


def test_v2_accepts_voltage_above_fixed_standard_floor():
    res = 0.5
    e = HPTFRTEnvV2([{**SC, 'target_V_pu': res}]); e.reset()
    e._sc = {**SC, 'target_V_pu': res}
    t_rel_real = 0.1
    e.t = SC['t_fault'] + t_rel_real * L.TSCALE
    assert FV2.within_envelope('LVRT', t_rel_real, res, res - 0.04)
    e.V2p = res - 0.04
    tripped_v2 = e.V2p < e._lvrt_floor(e.t - e._sc['t_fault']) - e._trip_tol()
    assert tripped_v2 is False


def test_v2_hvrt_ceiling_is_time_varying():
    e = HPTFRTEnvV2([{**SC, 'category': 'HVRT', 'fault_type': 'swell_3ph'}]); e.reset()
    e._sc = {**SC, 'category': 'HVRT', 'fault_type': 'swell_3ph'}
    # at real 0.4 s -> 1.30 ; at real 0.9 s -> 1.25
    assert e._hvrt_ceiling(0.4 * L.TSCALE) == 1.30
    assert e._hvrt_ceiling(0.9 * L.TSCALE) == 1.25
    assert L.HPTFRTEnv([SC])._hvrt_ceiling(0.9 * L.TSCALE) == pytest.approx(1.32)  # legacy static


def test_asymmetric_boundary_measured_iq_can_expose_wrong_sign():
    sc = {**SC, 'category': 'LVRT', 'fault_type': '2ph', 'target_V_pu': 0.75,
          'scr': 3.0, 't_fault': 0.0, 'fault_dur': 0.5, 'T_sim': 1.0}
    e = HPTFRTEnvV2([sc]); e.reset()
    info = None
    for _ in range(30):
        _, _, _, _, info = e.step([0.02, 0.04, 0.0])
    assert info['iq_cmd'] > 0.0
    assert info['V2n'] > 0.05
    assert 0.82 <= info['V2p'] <= 0.91
    assert info['iq'] < 0.0


def test_residual_asym_prior_does_not_hide_shallow_measured_wrong_sign():
    sc = {**SC, 'category': 'LVRT', 'fault_type': '2ph', 'target_V_pu': 0.75,
          'scr': 3.0, 't_fault': 0.0, 'fault_dur': 0.5, 'T_sim': 1.0}
    e = HPTFRTResidualEnvV2([sc]); e.reset()
    info = None
    for _ in range(30):
        _, _, _, _, info = e.step([0.0, 0.0, 0.0])
    assert info['V2n'] > 0.05
    assert info['iq_cmd'] > 0.0
    assert info['iq'] < 0.0


def test_shallow_2phg_extra_bias_is_strong_grid_long_fault_only():
    sc = {**SC, 'category': 'LVRT', 'fault_type': '2ph_g', 'target_V_pu': 0.75,
          'scr': 3.0, 't_fault': 0.0, 'fault_dur': 0.5, 'T_sim': 1.0}
    weak = HPTFRTResidualEnvV2([sc]); weak.reset()
    weak_info = None
    for _ in range(30):
        _, _, _, _, weak_info = weak.step([0.0, 0.0, 0.0])
    assert weak_info['V2n'] > 0.05
    assert weak_info['iq'] >= 0.0

    strong = HPTFRTResidualEnvV2([{**sc, 'scr': 10.0}]); strong.reset()
    strong_info = None
    for _ in range(30):
        _, _, _, _, strong_info = strong.step([0.0, 0.0, 0.0])
    assert strong_info['V2n'] > 0.05
    assert strong_info['iq'] < 0.0


def test_stiff_sym_lvrt_dc_sink_exposes_deep_mid_survive_risk():
    sc = {**SC, 'category': 'LVRT', 'fault_type': 'sym3ph', 'target_V_pu': 0.2,
          'scr': 10.0, 't_fault': 0.0, 'fault_dur': 0.5, 'T_sim': 1.0}
    e = HPTFRTEnvV2([sc]); e.reset()
    vdc_min = 1.0
    info = None
    for _ in range(40):
        _, _, _, _, info = e.step([0.27, 0.0, 0.0])
        vdc_min = min(vdc_min, info['Vdc'])
    assert info['Vg_p'] == pytest.approx(0.2)
    assert vdc_min < 0.75


def test_weak_scr2_shallow_hvrt_recovery_stays_visible_to_ode():
    sc = {**SC, 'category': 'HVRT', 'fault_type': 'swell_3ph', 'target_V_pu': 1.10,
          'scr': 2.0, 't_fault': 0.02, 'fault_dur': 0.5, 'T_sim': 1.0}
    e = HPTFRTEnvV2([sc]); e.reset()
    info = None
    for _ in range(120):
        _, _, _, _, info = e.step([0.27, 0.12, 0.0])
    assert 0.90 < info['V2p'] < 0.93


def test_symmetric_hvrt_recovery_fallback_uses_physical_iq_cap():
    class ZeroResidual:
        action_space = None
        observation_space = None

        def predict(self, obs, deterministic=True):
            return np.zeros(3, np.float32), None

    sc = {**SC, 'category': 'HVRT', 'fault_type': 'swell_3ph', 'target_V_pu': 1.10,
          'scr': 2.0, 't_fault': 0.02, 'fault_dur': 0.5, 'T_sim': 1.0}
    spec = ProjectionSpec(
        name='hvrt_recover_iq30',
        lvrt_enable=False,
        fallback_enable=True,
        fallback_v_min=0.90,
        fallback_v_max=0.97,
        fallback_vdc_min=0.70,
        fallback_iq=0.30,
        fallback_md=0.118,
    )
    model = ProjectionPolicy(ZeroResidual(), spec)
    res = evaluate_scenario(model, HPTFRTResidualEnvV2, sc)['res']
    assert res['recover']['status'] == FV2.PASS
    assert res['vdc_survive_proxy'] == FV2.PASS
    assert res['vdc_min'] > 0.75


def test_single_phase_hvrt_sequence_bias_exposes_wrong_sign_boundary():
    sc = {**SC, 'category': 'HVRT', 'fault_type': 'swell_1ph', 'target_V_pu': 1.2,
          'scr': 3.0, 't_fault': 0.0, 'fault_dur': 0.5, 'T_sim': 1.0}
    e = HPTFRTEnvV2([sc]); e.reset()
    info = None
    for _ in range(40):
        _, _, _, _, info = e.step([0.0, 0.05, 0.0])
    assert info['V2n'] > 0.05
    assert info['V2p'] > 1.1
    assert info['iq_cmd'] == pytest.approx(0.0)
    assert info['iq'] > 0.0


def test_single_phase_hvrt_sequence_bias_is_weak_grid_only():
    sc = {**SC, 'category': 'HVRT', 'fault_type': 'swell_1ph', 'target_V_pu': 1.2,
          'scr': 10.0, 't_fault': 0.0, 'fault_dur': 0.5, 'T_sim': 1.0}
    e = HPTFRTEnvV2([sc]); e.reset()
    info = None
    for _ in range(40):
        _, _, _, _, info = e.step([0.0, 0.05, 0.0])
    assert info['V2n'] > 0.05
    assert info['V2p'] < 1.1
    assert info['iq'] == pytest.approx(info['iq_cmd'])
