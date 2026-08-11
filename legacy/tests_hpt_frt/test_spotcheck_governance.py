"""test_spotcheck_governance — fill_spotcheck must FAIL-FAST on legacy frt-v1 MATs and only certify
frt-v2 MATs with a real time vector (audit round-4 A). Real MATs are constructed on disk and loaded
— this tests BEHAVIOR, not source strings."""
import numpy as np
import pytest
import scipy.io as sio
from hpt_frt.network import fill_spotcheck as FS


def _traj(n=400, t_f=0.1, dur=0.3, residual=0.5, Vnom=326.6):
    t = np.linspace(0.0, 1.0, n)
    # LV positive-seq rides at `residual` during the fault, recovers after
    v1 = np.where(t < t_f, 1.0, np.where(t <= t_f + dur, residual,
                  np.clip(residual + (1 - residual) * (t - (t_f + dur)) / 0.3, residual, 1.0)))
    # synthesize a balanced 3-phase set at the right magnitude (amplitude = v1*Vnom*sqrt(2)/...)
    w = 2 * np.pi * 50
    amp = v1 * Vnom * np.sqrt(2) / np.sqrt(3) * np.sqrt(3)   # peak phase amplitude ~ v1*Vnom
    Vabc = np.stack([amp * np.cos(w * t), amp * np.cos(w * t - 2 * np.pi / 3),
                     amp * np.cos(w * t + 2 * np.pi / 3)], axis=1)
    Vdc = np.full(n, 0.9 * 800.0)
    dq = np.stack([np.zeros(n), np.where((t >= t_f) & (t <= t_f + dur), 0.30 * FS.IBASE, 0.0)], axis=1)
    Ish = Vabc * 0.0
    return t, Vabc, Vdc, dq, Ish


def _save(path, *, version, with_time=True):
    t, Vabc, Vdc, dq, Ish = _traj()
    S = dict(label='S1_test', category='LVRT', fault_type='1ph_g', Vnom=326.6, Tsim=1.0,
             t_fault=0.1, dur=0.3, target_Vp=0.5, Vlv_abc=Vabc, Vmv_abc=Vabc, Vdc=Vdc, dq=dq,
             Ish_abc=Ish, crit=dict(frt=True, connect=True, reactive=True, limit=True,
                                    recover=True, survive=True, Vdcmin=0.9, Vdcmax=1.0,
                                    LVflt=0.5, iqf=0.3))
    if version is not None:
        S['metrics_version'] = version
    if with_time:
        S['tout'] = t
    sio.savemat(str(path), S)


def test_refuses_mat_without_metrics_version(tmp_path):
    p = tmp_path / 'noversion_sw_result.mat'; _save(p, version=None)
    with pytest.raises(FS.LegacyMatRefused, match='NO metrics_version'):
        FS.require_frt_v2_mat(str(p))


def test_refuses_frt_v1_version(tmp_path):
    p = tmp_path / 'v1_sw_result.mat'; _save(p, version='frt-v1-INVALIDATED')
    with pytest.raises(FS.LegacyMatRefused, match='!='):
        FS.require_frt_v2_mat(str(p))


def test_refuses_frt_v2_without_real_time(tmp_path):
    p = tmp_path / 'notime_sw_result.mat'; _save(p, version='frt-v2', with_time=False)
    with pytest.raises(FS.LegacyMatRefused, match='no REAL time'):
        FS.require_frt_v2_mat(str(p))


def test_accepts_frt_v2_and_recomputes_criteria(tmp_path):
    p = tmp_path / 'ok_sw_result.mat'; _save(p, version='frt-v2', with_time=True)
    r = FS.analyze_v2(str(p))
    assert r['metrics_version'] == 'frt-v2'
    # verdict is recomputed from the trajectory via frt_v2 (NOT the MAT's crit.frt=True);
    # current/I2 partly missing -> survive NOT_EVALUATED -> frt_pass None (never blindly True)
    assert r['frt_pass'] in (True, False, None)
    assert r['survive'] == 'NOT_EVALUATED'        # no i2 in the MAT -> cannot certify survive
    assert r['frt_pass'] is not True              # cannot certify a pass without survive


def test_run_default_does_not_touch_legacy(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(FS, 'SIM_DIR', tmp_path)               # empty -> no frt-v2 MATs
    monkeypatch.setattr(FS, 'LEGACY_DIR', tmp_path / 'legacy_pre_audit')
    out = FS.run()
    assert out == []
    assert 'PENDING' in capsys.readouterr().out                # does not fall back to legacy


def test_legacy_path_requires_env_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(FS, 'LEGACY_DIR', tmp_path)
    monkeypatch.delenv('HPT_ALLOW_LEGACY_FRT', raising=False)
    with pytest.raises(FS.LegacyMatRefused, match='HPT_ALLOW_LEGACY_FRT'):
        FS.run(legacy=True)
