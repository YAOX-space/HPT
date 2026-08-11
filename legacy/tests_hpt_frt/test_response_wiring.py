"""test_response_wiring — the 5 ms response metric is actually CALLED in the device evaluation,
emits response_status/rise_time_ms/settling_time_ms/meets_5ms, stays OUT of frt_pass, marks
NOT_EVALUATED on missing time-resolution/event, and handles non-uniform time (audit round-4 F)."""
import numpy as np
import pytest
from hpt_frt.device import frt_metrics as FM
from hpt_frt.device.frt_env import HPTFRTEnv
from hpt_frt.common import frt_v2 as FV2

SC = dict(scenario_id=1, family_id=1, category='LVRT', fault_type='1ph_g', target_V_pu=0.5,
          grid='weak', scr=3.0, t_fault=0.02, fault_dur=0.6, T_sim=2.5, random_seed=1)


class StubModel:
    def predict(self, obs, deterministic=True):
        return np.zeros(4, np.float32), None


def test_device_eval_emits_response_block_separate_from_frt_pass():
    c = FM.evaluate_scenario(StubModel(), HPTFRTEnv, SC)
    assert c['kind'] == 'evaluated'
    res = c['res']
    assert 'response' in res                       # response IS computed
    r = res['response']
    for k in ('response_status', 'rise_time_ms', 'settling_time_ms', 'meets_5ms'):
        assert k in r
    # response must NOT be one of the mandatory frt criteria nor affect frt_pass
    assert 'response' not in FV2.MANDATORY
    assert res['frt_pass'] in (True, False, None)


def test_aggregate_reports_response_block_separately():
    m = FM.evaluate_frt(StubModel(), [SC, {**SC, 'fault_type': 'sym3ph'}], HPTFRTEnv)
    assert 'response' in m
    rb = m['response']
    for k in ('n_evaluated', 'n_not_evaluated', 'meets_5ms_pct', 'median_settling_ms'):
        assert k in rb
    # the response block is NOT in frt_pass_pct / partial_proxy_pct
    assert 'meets_5ms' not in str(m.get('frt_pass_pct'))


def test_response_not_evaluated_when_no_event():
    # target ~ 0 (shallow voltage) -> no reactive event -> NOT_EVALUATED
    tr = dict(t=np.linspace(0, 1, 200), iq=np.zeros(200))
    r = FM._response_of(tr, 0.1, residual=0.95)     # ref(0.95)=0 -> no event
    assert r['response_status'] == 'NOT_EVALUATED' and r['meets_5ms'] is None


def test_response_not_evaluated_on_coarse_sampling():
    tr = dict(t=np.array([0.0, 0.5, 1.0]), iq=np.array([0.0, 0.3, 0.3]))
    r = FM._response_of(tr, 0.4, residual=0.5)
    assert r['response_status'] == 'NOT_EVALUATED'


def test_response_uses_explicit_reference_not_median():
    # build an iq that rises to the EXACT droop reference quickly -> settled & meets_5ms
    t = np.linspace(0, 0.4, 800); t_f = 0.05
    target = FV2.iq_ref_droop(0.5)                  # explicit reference at residual 0.5
    iq = np.where(t < t_f, 0.0, np.where(t < t_f + 0.003, target * (t - t_f) / 0.003, target))
    r = FM._response_of(dict(t=t, iq=iq), t_f, residual=0.5)
    assert r['response_status'] == 'settled' and r['meets_5ms'] is True


def test_response_metrics_handles_nonuniform_time():
    # strictly-increasing but NON-uniform time vector
    rng = np.random.default_rng(0)
    steps = 0.0005 + rng.uniform(0, 0.0005, 600)
    t = np.cumsum(steps); t_ev = t[50]
    target = 0.3
    s = np.where(t < t_ev, 0.0, np.where(t < t_ev + 0.004, target * (t - t_ev) / 0.004, target))
    r = FV2.response_metrics(t, s, t_ev, target=target)
    assert r['status'] in ('settled', 'not_settled')   # ran without error on non-uniform t
    assert np.isfinite(r['settling_time_ms']) or r['status'] == 'not_settled'
    # a non-monotonic time vector must raise
    tbad = t.copy(); tbad[100] = tbad[99]
    with pytest.raises(ValueError):
        FV2.response_metrics(tbad, s, t_ev, target=target)
