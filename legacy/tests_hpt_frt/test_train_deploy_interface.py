"""test_train_deploy_interface — frt-v2 env interface (audit H1, H2; acceptance 6): 3-D action,
de-privileged observation, and an ONLINE detector whose output is independent of the true t_fault."""
import inspect
import numpy as np
from hpt_frt.device import frt_env_v2 as V2
from hpt_frt.device.frt_env import F2I

SC = dict(scenario_id=1, family_id=1, category='LVRT', fault_type='1ph_g', target_V_pu=0.5,
          grid='weak', scr=3.0, Rg_ohm=26.35, Lg_H=0.2516, P_load=3e5, Q_load=1e5,
          power_factor=0.9, t_fault=0.05, fault_dur=0.3, recover_to_0p9_s=2.0, T_sim=1.0,
          trans_resistance=0.3, random_seed=1)


def test_action_is_true_3d():
    assert V2.HPTFRTEnvV2([SC]).action_space.shape == (3,)


def test_obs_uses_no_privileged_info():
    src = inspect.getsource(V2.HPTFRTEnvV2._obs)
    for forbidden in ('self._fp', "['fault_type']", "['t_fault']", "['fault_dur']",
                      "['target_V_pu']", '_sc['):
        assert forbidden not in src, f'obs must not read {forbidden}'


def test_online_classifier_is_pure_function_of_measured_seq():
    assert V2.online_fault_class(0.5, 0.0) == F2I['sym3ph']
    assert V2.online_fault_class(0.6, 0.10) == F2I['1ph_g']
    assert V2.online_fault_class(1.2, 0.0) == F2I['swell']
    assert V2.online_fault_class(1.0, 0.0) == F2I['normal']


def test_detector_elapsed_independent_of_true_onset():
    """Same measured (V2p,V2n) history shifted in absolute time -> identical elapsed-since-detection."""
    dt = 0.02
    # pattern: 5 normal samples, then fault (V2p 0.5) for 10, then recovery
    pat_v2p = [1.0] * 5 + [0.5] * 10 + [0.95] * 5
    pat_v2n = [0.0] * 20

    def run(t0):
        det = V2.OnlineFaultDetector(); out = []
        for k, (vp, vn) in enumerate(zip(pat_v2p, pat_v2n)):
            inf, el = det.update(t0 + k * dt, vp, vn)
            out.append((inf, round(el, 6)))
        return out
    a = run(0.05); b = run(0.37)           # different true onset times, same measured pattern
    assert a == b, 'detector output depends on absolute onset time (privileged)'
    # detection latches at the first faulted sample (index 5) and elapsed grows by dt
    assert a[5] == (True, 0.0) and a[6] == (True, round(dt, 6))
    assert a[15][0] is False                # reset after recovery to normal band


def test_detector_keeps_hvrt_visible_during_measured_recovery():
    det = V2.OnlineFaultDetector()
    assert det.update(0.00, 1.0, 0.0) == (False, 0.0)
    inf, _ = det.update(0.02, 1.18, 0.0)
    assert inf and det.recent_hvrt
    inf, _ = det.update(0.08, 0.92, 0.0)
    assert inf and det.recent_hvrt
    assert V2.online_fault_class(0.92, 0.0, det.recent_hvrt) == F2I['swell']
    inf, _ = det.update(0.12, 1.0, 0.0)
    assert not inf and not det.recent_hvrt


def test_obs_identical_for_same_measurement_different_true_tfault():
    """Two envs with identical measured state but different scenario t_fault produce identical obs."""
    e1 = V2.HPTFRTEnvV2([{**SC, 't_fault': 0.05}]); e1.reset()
    e2 = V2.HPTFRTEnvV2([{**SC, 't_fault': 0.50}]); e2.reset()
    for e in (e1, e2):                       # force identical measured internal state + clock
        e.t, e.V2p, e.V2n, e.Vdc, e._iq = 0.30, 0.5, 0.1, 0.9, 0.2
        e._last_a3 = np.zeros(V2.N_ACT_V2, np.float32)
        e._detector.reset(); e._detector.detected = True; e._detector.onset_t = 0.20
    o1, o2 = e1._obs(), e2._obs()
    assert o1.shape == (V2.OBS_DIM_V2,)      # explicit 20-D contract
    assert np.array_equal(o1, o2), 'obs differs despite identical measured state'
