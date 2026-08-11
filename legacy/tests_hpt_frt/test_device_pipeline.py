"""test_device_pipeline — the device (ODE) training evaluation must route through
hpt_frt.common.frt_v2 (NOT legacy scalar formulas), record real measurements, and never coerce None
or count incomplete scenarios as certified passes (audit item 1)."""
import inspect
import numpy as np
from hpt_frt.device import frt_metrics as FM
from hpt_frt.device.frt_env import HPTFRTEnv
from hpt_frt.common import frt_v2 as FV2


class StubModel:
    """Deterministic zero action (4-D, matches HPTFRTEnv) — enough to drive a rollout."""
    def predict(self, obs, deterministic=True):
        return np.zeros(4, np.float32), None


SC = dict(scenario_id=1, family_id=1, category='LVRT', fault_type='1ph_g', target_V_pu=0.5,
          grid='weak', scr=3.0, t_fault=0.02, fault_dur=0.6, T_sim=2.5, random_seed=1)


def test_frt_metrics_imports_frt_v2_and_has_no_legacy_formula():
    src = inspect.getsource(FM)
    assert 'frt_v2' in src and 'FV2.evaluate' in src
    assert 'def frt_criteria' not in src                 # the legacy bool-criteria function is gone
    assert '>= 0.75' not in src and '<= 0.35' not in src  # no inline legacy thresholds


def test_evaluate_scenario_returns_frt_v2_contract_with_missing_current_i2():
    c = FM.evaluate_scenario(StubModel(), HPTFRTEnv, SC)
    assert c['kind'] == 'evaluated'                       # classification dict, not a bare result
    r = c['res']
    assert r['metrics_version'] == 'frt-v2'
    # the averaged ODE has no combined current and no I2 -> those mandatory criteria are NOT_EVALUATED
    assert r['limit']['status'] == FV2.NOT_EVALUATED
    assert r['survive']['status'] == FV2.NOT_EVALUATED
    # therefore the scenario cannot be CERTIFIED as a pass. A measurable FAIL still takes precedence
    # over missing current/I2 and yields False; otherwise incompleteness yields None.
    assert r['frt_pass'] in (False, None)
    assert r['connect']['status'] in (FV2.PASS, FV2.FAIL)   # connect always measurable
    # reactive may be NOT_EVALUATED when the (support-raised) residual leaves no sustained demand
    assert r['reactive']['status'] in (FV2.PASS, FV2.FAIL, FV2.NOT_EVALUATED)


def test_evaluate_frt_counts_status_separately_and_no_int_none():
    m = FM.evaluate_frt(StubModel(), [SC, {**SC, 'fault_type': 'sym3ph'}], HPTFRTEnv)
    assert m['metrics_version'] == 'frt-v2'
    assert m['n_requested'] == 2 and m['n_rollout_ok'] >= 1
    # ODE limit/survive always NOT_EVALUATED -> NO scenario is complete -> frt_pass_pct is None
    assert m['n_complete'] == 0
    assert m['n_incomplete'] >= 1
    assert m['frt_pass_pct'] is None                     # not coerced to 0/100 via int(None)
    assert m['limit'] is None and m['survive'] is None
    assert m['limit_not_eval_pct'] == 100.0 and m['survive_not_eval_pct'] == 100.0
    assert isinstance(m['partial_proxy_pct'], float) and 0.0 <= m['partial_proxy_pct'] <= 100.0


def test_ode_never_certifies_a_pass():
    # across scenarios, no ODE rollout may yield frt_pass=True (full FRT needs the switching harness)
    for ft in ('sym3ph', '1ph_g', '2ph', '2ph_g'):
        c = FM.evaluate_scenario(StubModel(), HPTFRTEnv, {**SC, 'fault_type': ft})
        if c['kind'] == 'evaluated':
            assert c['res']['frt_pass'] is not True


def test_run_episode_does_not_infer_missing_as_zero():
    tr = FM.run_episode(StubModel(), HPTFRTEnv([SC]))
    assert tr['i_peak'] is None and tr['idq_mag'] is None and tr['i2'] is None  # not zero-filled
    assert tr['t'].size > 1 and np.all(np.isfinite(tr['V1'])) and np.all(np.isfinite(tr['Vdc']))


def test_fmt_summary_is_none_safe():
    m = FM.evaluate_frt(StubModel(), [SC], HPTFRTEnv)
    s = FM.fmt_summary(m)                                 # must not raise on None criteria
    assert 'lim=n/e' in s and 'frt_pass=n/a' in s and 'frt-v2' in s
