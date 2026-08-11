"""test_reactive_criterion — the reactive criterion is MINIMUM-SUPPORT with response delay, sustained
dwell, max-under-support and wrong-sign-immediate-FAIL (audit round-4 E). Consistent with FRT_SPEC and
common/frt_v2.reactive_criterion. NOT whole-window mean error."""
import numpy as np
import pytest
from hpt_frt.common import frt_v2 as F


def _scn(residual=0.4, t_f=0.1, dur=0.5, dt=0.002, iq_profile=None):
    t = np.arange(0.0, t_f + dur + 0.3, dt)
    V1 = np.where((t >= t_f) & (t <= t_f + dur), residual, 1.0)
    in_fault = (t >= t_f) & (t <= t_f + dur)
    ref = np.array([F.iq_ref_droop(v) for v in V1])           # ref during hold = min(0.3, 1.5*(0.9-res))
    iq = np.zeros_like(t)
    if iq_profile is not None:
        iq = iq_profile(t, V1, ref, in_fault, t_f)
    return t, V1, iq, in_fault, t_f, ref


def test_min_support_pass_when_demand_met():
    # inject exactly the demand for the whole fault -> PASS
    t, V1, iq, inf, tf, ref = _scn(iq_profile=lambda t, V1, ref, inf, tf: np.where(inf, ref, 0.0))
    st, worst, _, _, det = F.reactive_criterion(t, V1, iq, 'LVRT', inf, tf)
    assert st == F.PASS and worst == pytest.approx(0.0, abs=1e-9)
    assert det['met_fraction'] == 1.0


def test_over_injection_not_penalised_here():
    # iq above the demand (still within reactive range) is fine for the REACTIVE criterion
    t, V1, iq, inf, tf, ref = _scn(iq_profile=lambda t, V1, ref, inf, tf: np.where(inf, ref + 0.1, 0.0))
    st, worst, _, _, _ = F.reactive_criterion(t, V1, iq, 'LVRT', inf, tf)
    assert st == F.PASS                                       # bounded by LIMIT, not reactive


def test_under_support_fails_and_reports_shortfall():
    # inject only half the demand for the whole fault -> FAIL, with a positive max under-support
    t, V1, iq, inf, tf, ref = _scn(iq_profile=lambda t, V1, ref, inf, tf: np.where(inf, ref * 0.4, 0.0))
    st, worst, _, reason, det = F.reactive_criterion(t, V1, iq, 'LVRT', inf, tf)
    assert st == F.FAIL and worst > 0 and det['max_under_support'] > 0


def test_wrong_sign_immediate_fail():
    # absorbing (iq<0) during an under-voltage -> immediate FAIL regardless of magnitude
    t, V1, iq, inf, tf, ref = _scn(iq_profile=lambda t, V1, ref, inf, tf: np.where(inf, -0.2, 0.0))
    st, _, _, reason, det = F.reactive_criterion(t, V1, iq, 'LVRT', inf, tf)
    assert st == F.FAIL and det.get('wrong_sign') is True and 'wrong sign' in reason


def test_response_delay_tolerates_slow_start_if_sustained():
    # zero injection for the first 60 ms (response window) then full demand -> still PASS (dwell met)
    def prof(t, V1, ref, inf, tf):
        late = inf & (t >= tf + F.REACTIVE_DELAY)
        return np.where(late, ref, 0.0)
    t, V1, iq, inf, tf, ref = _scn(iq_profile=prof)
    st, _, _, _, det = F.reactive_criterion(t, V1, iq, 'LVRT', inf, tf)
    assert st == F.PASS and det['met_fraction'] >= 0.80


def test_brief_dropout_below_dwell_fails():
    # meet demand for only ~50% of the assessed window -> below dwell 0.80 -> FAIL
    def prof(t, V1, ref, inf, tf):
        first_half = inf & (t < tf + 0.25)
        return np.where(first_half, ref, 0.0)
    t, V1, iq, inf, tf, ref = _scn(dur=0.5, iq_profile=prof)
    st, _, _, _, det = F.reactive_criterion(t, V1, iq, 'LVRT', inf, tf)
    assert st == F.FAIL and det['met_fraction'] < 0.80


def test_hvrt_minimum_absorption():
    # HVRT: must absorb (iq<=ref+tol, ref<0). Sourcing positive iq during over-voltage = wrong sign.
    t = np.arange(0, 1.0, 0.002)
    V1 = np.where((t >= 0.1) & (t <= 0.6), 1.25, 1.0)
    inf = (t >= 0.1) & (t <= 0.6)
    ref = np.array([F.iq_ref_droop(v) for v in V1])           # ref ~ -0.225 during swell
    iq_ok = np.where(inf, ref, 0.0)
    st_ok, _, _, _, _ = F.reactive_criterion(t, V1, iq_ok, 'HVRT', inf, 0.1)
    assert st_ok == F.PASS
    iq_wrong = np.where(inf, 0.2, 0.0)                         # sourcing during over-voltage
    st_w, _, _, _, det = F.reactive_criterion(t, V1, iq_wrong, 'HVRT', inf, 0.1)
    assert st_w == F.FAIL and det.get('wrong_sign') is True


def test_not_whole_window_mean():
    # a profile whose MEAN error is small but which violates dwell must FAIL — proving it is not
    # mean-based. Inject 2x demand for 60% of the window, 0 for 40%: mean(|iq-ref|) is moderate but
    # under-support dwell is only 60% < 80% -> FAIL.
    def prof(t, V1, ref, inf, tf):
        on = inf & (t < tf + 0.30)
        return np.where(on, ref * 2.0, 0.0)
    t, V1, iq, inf, tf, ref = _scn(dur=0.5, iq_profile=prof)
    st, _, _, _, det = F.reactive_criterion(t, V1, iq, 'LVRT', inf, tf)
    assert st == F.FAIL and det['met_fraction'] < 0.80
