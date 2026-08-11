"""frt-v2 status model and exact GB/T LVRT boundary regressions."""
import numpy as np
import pytest
from hpt_frt.common import frt_v2 as F


def _complete(residual=0.5, t_fault=0.1, dur=0.3, post=0.5, dt=0.002):
    """A fully-measured trajectory that PASSES every criterion (used as the mutation baseline)."""
    t = np.arange(0.0, t_fault + dur + post + 1e-9, dt)
    tf = t_fault
    # V+ : 1.0 pre; = residual during hold; ramp back to 1.0 post-clear
    V1 = np.where(t < tf, 1.0,
         np.where(t <= tf + dur, residual,
         np.clip(residual + (1.0 - residual) * (t - (tf + dur)) / 0.3, residual, 1.0)))
    in_f = (t >= tf) & (t <= tf + dur)
    iq = np.where(in_f, 0.30, 0.0)            # ref droop at V=0.5 = 0.3 (capped) -> matches
    i_peak = np.full_like(t, 0.30)            # < 0.35
    Vdc = np.full_like(t, 0.90)              # within [0.75,1.25]
    i2 = np.zeros_like(t)                     # < 3 pu
    return dict(t=t, V1=V1, category='LVRT', residual=residual, t_fault=tf, dur=dur,
                Vdc=Vdc, iq=iq, i_peak=i_peak, i2=i2)


def test_complete_trajectory_passes():
    r = F.evaluate(**_complete())
    assert r['frt_pass'] is True
    for c in F.MANDATORY:
        assert r[c]['status'] == F.PASS, (c, r[c])


def test_missing_iq_current_vdc_i2_cannot_pass():
    for drop in ('iq', 'i_peak', 'Vdc', 'i2'):
        kw = _complete(); kw[drop] = None
        r = F.evaluate(**kw)
        assert r['frt_pass'] is None, f'dropping {drop} should give frt_pass None, got {r["frt_pass"]}'
    # dropping current entirely (both i_peak and idq_mag) -> limit NOT_EVALUATED
    kw = _complete(); kw['i_peak'] = None
    assert F.evaluate(**kw)['limit']['status'] == F.NOT_EVALUATED
    # dropping i2 -> survive NOT_EVALUATED (I2<=3pu is mandatory)
    kw = _complete(); kw['i2'] = None
    assert F.evaluate(**kw)['survive']['status'] == F.NOT_EVALUATED


def test_insufficient_recovery_window_cannot_pass():
    kw = _complete(post=0.02)                 # post window < RECOVER_MIN_COVER
    r = F.evaluate(**kw)
    assert r['recover']['status'] == F.NOT_EVALUATED
    assert r['frt_pass'] is None
    # no post window at all
    kw = _complete(post=0.0)
    assert F.evaluate(**kw)['recover']['status'] == F.NOT_EVALUATED


def test_connect_boundary_uses_fixed_gbt_floor_not_imposed_residual():
    base = _complete()
    tf, dur = base['t_fault'], base['dur']
    in_f = (base['t'] >= tf) & (base['t'] <= tf + dur)
    # The imposed 0.50-pu disturbance is above the fixed 0.20-pu GB/T floor.
    assert F.evaluate(**base)['connect']['status'] == F.PASS
    kw = _complete(); kw['V1'] = np.where(in_f, F.LVRT_FLOOR, kw['V1'])
    assert F.evaluate(**kw)['connect']['status'] == F.PASS
    kw = _complete(); kw['V1'] = np.where(in_f, F.LVRT_FLOOR - 0.01, kw['V1'])
    assert F.evaluate(**kw)['connect']['status'] == F.FAIL


def test_limit_catches_overcurrent_and_uses_combined_current():
    kw = _complete(); kw['i_peak'] = None
    kw['idq_mag'] = np.full_like(kw['t'], 0.40)          # sqrt(id^2+iq^2) over the line
    r = F.evaluate(**kw)
    assert r['limit']['status'] == F.FAIL and r['limit']['worst'] > 0.35


def test_survive_full_domain_vdc_and_i2():
    kw = _complete(); kw['Vdc'] = kw['Vdc'].copy(); kw['Vdc'][len(kw['t'])//2] = 0.6
    assert F.evaluate(**kw)['survive']['status'] == F.FAIL          # full-domain Vdc dip caught
    kw = _complete(); kw['i2'] = kw['i2'].copy(); kw['i2'][len(kw['t'])//2] = 3.5
    r = F.evaluate(**kw)
    assert r['survive']['status'] == F.FAIL and 'I2' in r['survive']['reason']


def test_input_validation_raises():
    base = _complete()
    with pytest.raises(ValueError):                      # length mismatch
        F.evaluate(base['t'], base['V1'][:-5], 'LVRT', 0.5, 0.1, 0.3,
                   Vdc=base['Vdc'], iq=base['iq'], i_peak=base['i_peak'], i2=base['i2'])
    with pytest.raises(ValueError):                      # non-monotonic time
        tbad = base['t'].copy(); tbad[10] = tbad[5]
        F.evaluate(tbad, base['V1'], 'LVRT', 0.5, 0.1, 0.3, Vdc=base['Vdc'], i2=base['i2'])
    with pytest.raises(ValueError):                      # non-finite
        Vbad = base['V1'].copy(); Vbad[3] = np.nan
        F.evaluate(base['t'], Vbad, 'LVRT', 0.5, 0.1, 0.3, Vdc=base['Vdc'], i2=base['i2'])
    with pytest.raises(ValueError):                      # empty fault window
        F.evaluate(base['t'], base['V1'], 'LVRT', 0.5, 99.0, 0.3, Vdc=base['Vdc'], i2=base['i2'])


def test_reactive_wrong_sign_fails():
    kw = _complete()
    in_f = (kw['t'] >= kw['t_fault']) & (kw['t'] <= kw['t_fault'] + kw['dur'])
    kw['iq'] = np.where(in_f, -0.2, 0.0)                 # absorbing under-voltage = wrong sign
    r = F.evaluate(**kw)
    assert r['reactive']['status'] == F.FAIL and 'sign' in r['reactive']['reason']


def test_status_precedence_fail_beats_missing():
    # one mandatory FAIL (Vdc dips) AND one mandatory missing (iq) -> frt_pass MUST be False (not None),
    # while the missing criterion is still recorded as NOT_EVALUATED.
    kw = _complete()
    kw['Vdc'] = kw['Vdc'].copy(); kw['Vdc'][len(kw['t'])//2] = 0.6   # survive FAIL
    kw['iq'] = None                                                  # reactive NOT_EVALUATED
    r = F.evaluate(**kw)
    assert r['survive']['status'] == F.FAIL
    assert r['reactive']['status'] == F.NOT_EVALUATED
    assert r['frt_pass'] is False                                    # FAIL takes precedence over None


def test_response_metric_separate_and_well_formed():
    import numpy as np
    r = F.evaluate(**_complete())
    assert 'response' not in r and 'frt_pass' in r                   # response never inside frt_pass

    def _step(rise_s, settled=1.0, base=0.5, T=0.2, dt=0.0005, overshoot=0.0, never=False):
        t = np.arange(0, T, dt); tev = 0.02
        out = np.full_like(t, base)
        for i, ti in enumerate(t):
            if ti >= tev:
                frac = min(1.0, (ti - tev) / rise_s)
                v = base + (settled - base) * frac
                if overshoot and frac >= 1.0:
                    v = settled + overshoot * (settled - base) * np.exp(-(ti - tev - rise_s) / 0.01)
                out[i] = v
        if never:
            out[t >= tev] += 0.1 * np.sin(40 * np.pi * t[t >= tev])   # keeps oscillating, never settles
        return t, out, tev

    # under 5 ms
    t, s, tev = _step(0.003)
    m = F.response_metrics(t, s, tev)
    assert m['status'] == 'settled' and m['settling_time_ms'] <= 5.0 and m['meets_5ms'] is True
    # over 5 ms
    t, s, tev = _step(0.030)
    m = F.response_metrics(t, s, tev)
    assert m['status'] == 'settled' and m['settling_time_ms'] > 5.0 and m['meets_5ms'] is False
    # overshoot then settle
    t, s, tev = _step(0.004, overshoot=0.3)
    m = F.response_metrics(t, s, tev)
    assert m['settled'] is True and m['overshoot'] > 0.1
    # never settled
    t, s, tev = _step(0.004, never=True)
    m = F.response_metrics(t, s, tev)
    assert m['status'] == 'not_settled' and m['settled'] is False
    # insufficient sampling resolution
    t = np.array([0.0, 0.01, 0.02]); s = np.array([0.5, 0.5, 1.0])
    m = F.response_metrics(t, s, 0.019)
    assert m['status'] == 'insufficient_resolution'
