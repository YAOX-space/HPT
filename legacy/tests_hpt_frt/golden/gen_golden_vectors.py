"""gen_golden_vectors.py — generate frt-v2 golden vectors (inputs + Python frt_v2.evaluate expected
outputs) for the MATLAB frt_v2_evaluate.m parity test (audit round-5 E.12). Run:
    python -m tests.golden.gen_golden_vectors
Writes tests/golden/frt_v2_golden.mat (cell array of case structs)."""
import os
import numpy as np
import scipy.io as sio
from pathlib import Path
from hpt_frt.common import frt_v2 as F

DEFAULT_GOLDEN = Path(__file__).resolve().parent / 'frt_v2_golden.mat'


def base(residual=0.5, t_fault=0.1, dur=0.3, post=0.5, dt=0.002):
    t = np.arange(0.0, t_fault + dur + post + 1e-9, dt)
    tf = t_fault
    V1 = np.where(t < tf, 1.0, np.where(t <= tf + dur, residual,
                  np.clip(residual + (1 - residual) * (t - (tf + dur)) / 0.3, residual, 1.0)))
    in_f = (t >= tf) & (t <= tf + dur)
    return dict(t=t, V1=V1, category='LVRT', residual=residual, t_fault=tf, dur=dur,
                Vdc=np.full_like(t, 0.9), iq=np.where(in_f, 0.30, 0.0),
                i_peak=np.full_like(t, 0.30), i2=np.zeros_like(t), in_f=in_f)


def hvrt(swell=1.25, t_fault=0.1, dur=0.4, post=0.5, dt=0.002):
    t = np.arange(0.0, t_fault + dur + post + 1e-9, dt)
    tf = t_fault
    V1 = np.where((t >= tf) & (t <= tf + dur), swell, 1.0)
    in_f = (t >= tf) & (t <= tf + dur)
    return dict(t=t, V1=V1, category='HVRT', residual=swell, t_fault=tf, dur=dur,
                Vdc=np.full_like(t, 0.95), iq=np.where(in_f, -0.225, 0.0),
                i_peak=np.full_like(t, 0.22), i2=np.zeros_like(t), in_f=in_f)


def make_cases():
    cases = {}
    c = base(); cases['complete_pass'] = c
    c = base(); c['V1'] = np.where(c['in_f'], c['residual'] - 0.07, c['V1']); cases['connect_fail'] = c
    c = base(); c['iq'] = np.where(c['in_f'], 0.30 * 0.4, 0.0); cases['reactive_under'] = c
    c = base(); c['iq'] = np.where(c['in_f'], -0.2, 0.0); cases['reactive_wrongsign'] = c
    c = base(); c['i_peak'] = np.full_like(c['t'], 0.40); cases['limit_fail'] = c
    c = base(); c['Vdc'] = c['Vdc'].copy(); c['Vdc'][len(c['t']) // 2] = 0.6; cases['survive_vdc_fail'] = c
    c = base(); c['i2'] = c['i2'].copy(); c['i2'][len(c['t']) // 2] = 3.5; cases['survive_i2_fail'] = c
    c = base(post=0.02); cases['recover_insufficient'] = c
    c = base(); c['iq'] = None; cases['missing_iq'] = c
    c = base(); c['i_peak'] = None; cases['missing_current'] = c
    c = base(); c['Vdc'] = None; cases['missing_vdc'] = c
    c = base(); c['i2'] = None; cases['missing_i2'] = c
    # FAIL + missing -> frt_pass False (precedence)
    c = base(); c['Vdc'] = c['Vdc'].copy(); c['Vdc'][len(c['t']) // 2] = 0.6; c['iq'] = None
    cases['fail_beats_missing'] = c
    cases['hvrt_pass'] = hvrt()
    c = hvrt(); c['iq'] = np.where(c['in_f'], 0.2, 0.0); cases['hvrt_wrongsign'] = c
    return cases


def evaluate(c):
    return F.evaluate(c['t'], c['V1'], c['category'], c['residual'], c['t_fault'], c['dur'],
                      Vdc=c.get('Vdc'), iq=c.get('iq'), i_peak=c.get('i_peak'),
                      idq_mag=c.get('idq_mag'), i2=c.get('i2'))


def build_records():
    """Build the golden case records (inputs + Python frt_v2 expected outputs) — no file I/O."""
    out = []
    for name, c in make_cases().items():
        r = evaluate(c)
        empty = np.zeros(0)
        rec = dict(
            name=name, t=c['t'], V1=c['V1'], category=c['category'], residual=float(c['residual']),
            t_fault=float(c['t_fault']), dur=float(c['dur']),
            Vdc=c['Vdc'] if c.get('Vdc') is not None else empty,
            iq=c['iq'] if c.get('iq') is not None else empty,
            i_peak=c['i_peak'] if c.get('i_peak') is not None else empty,
            i2=c['i2'] if c.get('i2') is not None else empty,
            exp_connect=r['connect']['status'], exp_reactive=r['reactive']['status'],
            exp_limit=r['limit']['status'], exp_recover=r['recover']['status'],
            exp_survive=r['survive']['status'],
            exp_frt_pass=('None' if r['frt_pass'] is None else ('True' if r['frt_pass'] else 'False')),
            exp_connect_worst=float(r['connect']['worst']),
            exp_limit_worst=(float(r['limit']['worst']) if np.isfinite(r['limit']['worst']) else np.nan),
            exp_survive_worst=(float(r['survive']['worst']) if np.isfinite(r['survive']['worst']) else np.nan),
        )
        out.append(rec)
    return out


def main(out_path=None):
    """Write the golden vectors. Output path precedence: explicit arg > $HPT_GOLDEN_OUT > repo default.
    Returns (path, n_cases). Tests pass a temp path so they never require repo write access."""
    out = build_records()
    p = Path(out_path or os.environ.get('HPT_GOLDEN_OUT') or DEFAULT_GOLDEN)
    sio.savemat(str(p), {'cases': np.array(out, dtype=object)})
    print(f'wrote {len(out)} golden cases -> {p}')
    return p, len(out)


if __name__ == '__main__':
    main()
