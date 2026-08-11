"""fill_spotcheck.py — Experiment D analysis of the SWITCHING-level spot-check MATs.

frt-v2 GOVERNANCE (audit round-4 A): this analyser REFUSES to certify legacy frt-v1 MATs.
  * a MAT is accepted only if it carries `metrics_version == 'frt-v2'` AND a REAL time vector
    (`tout`, or a `*_time`/`Time` signal). No `linspace` time reconstruction.
  * the MAT's own `crit.frt` (legacy frt-v1 verdict) is NEVER trusted — criteria are recomputed from
    the trajectory through `hpt_frt.common.frt_v2.evaluate`.
  * the 20 unversioned MATs that used to sit in `results/simulink_cases/` are LEGACY and have been
    moved to `results/simulink_cases/legacy_pre_audit/`. They are readable ONLY with the explicit
    env flag `HPT_ALLOW_LEGACY_FRT=1`, output stays in that folder, and NO active CSV / fig7 is
    written and NO "FRT PASS" is printed for them.
Until the MATLAB run_spotcheck.m is rewritten to emit frt-v2 MATs (P1), the active path finds no
frt-v2 MATs and reports PENDING — it does NOT fall back to the legacy files.
"""
import os, csv, glob
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
import numpy as np
import scipy.io as sio
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from . import config as C
from ..common import frt_v2 as FV2

SIM_DIR = C.RESULTS / 'simulink_cases'
LEGACY_DIR = SIM_DIR / 'legacy_pre_audit'
REQUIRED_VERSION = 'frt-v2'
A = np.exp(1j * 2 * np.pi / 3.0); A2 = A * A
# measured dq currents are PEAK (amplitude-invariant Park) -> normalise by the PEAK base (I_sys_peak)
IBASE = C.PU.I_SYS_PEAK


class LegacyMatRefused(Exception):
    """Raised when a MAT is legacy frt-v1 (no metrics_version / wrong version / no real time)."""


def _mv(S):
    v = S.get('metrics_version', None)
    if v is None:
        return None
    return str(np.ravel(v)[0]) if isinstance(v, np.ndarray) else str(v)


def _real_time(S):
    """Return a REAL recorded time vector, or None. Accepts `tout`, `Time`, `t`, or `<sig>_time`."""
    for k in S:
        if k.startswith('__'):
            continue
        if k.lower() in ('tout', 'time', 't', 't_vec'):
            return np.ravel(S[k]).astype(float)
    return None


def require_frt_v2_mat(matpath):
    """Load a MAT and REFUSE it unless it is a frt-v2 result with a real time vector."""
    S = sio.loadmat(matpath, squeeze_me=True, struct_as_record=False)
    mv = _mv(S)
    if mv is None:
        raise LegacyMatRefused(f'{os.path.basename(matpath)}: NO metrics_version — legacy frt-v1 MAT. '
                               f'Refusing. Move to legacy_pre_audit/ and regenerate under frt-v2 (P1).')
    if mv != REQUIRED_VERSION:
        raise LegacyMatRefused(f'{os.path.basename(matpath)}: metrics_version={mv!r} != '
                               f'{REQUIRED_VERSION!r} — refusing.')
    if _real_time(S) is None:
        raise LegacyMatRefused(f'{os.path.basename(matpath)}: no REAL time vector (tout/Time) — '
                               f'linspace reconstruction is not allowed under frt-v2. Refusing.')
    return S


def seq_from_abc(va, vb, vc):
    V1 = (va + A * vb + A2 * vc) / 3.0
    V2 = (va + A2 * vb + A * vc) / 3.0
    return np.abs(V1), np.abs(V2)


def analyze_v2(matpath):
    """frt-v2 analysis: REAL time vector + criteria recomputed via frt_v2.evaluate (crit.frt ignored)."""
    S = require_frt_v2_mat(matpath)
    t = _real_time(S)
    label = str(S['label']); cat = str(S['category']); ft = str(S['fault_type'])
    Vnom = float(S['Vnom']); t_f = float(S['t_fault']); dur = float(S['dur'])
    residual = float(S['target_Vp']) if 'target_Vp' in S else float(S.get('target_V_pu', np.nan))
    Vlv = np.atleast_2d(S['Vlv_abc']); Vdc = np.ravel(S['Vdc']); dq = np.atleast_2d(S['dq'])
    Ish = np.atleast_2d(S['Ish_abc'])
    # positive/negative sequence magnitude trajectories from the recorded 3-phase LV voltage
    V1, V2 = seq_from_abc(Vlv[:, 0] + 0j, Vlv[:, 1] + 0j, Vlv[:, 2] + 0j)
    V1 = V1 / Vnom; V2 = V2 / Vnom
    # measured currents (peak base); combined |i| and per-component
    iq = dq[:, 1] / IBASE; idc = dq[:, 0] / IBASE
    idq_mag = np.hypot(idc, iq)
    Vdc_pu = Vdc / 800.0
    # criteria recomputed from the trajectory (NEVER S['crit'].frt)
    res = FV2.evaluate(t, V1, cat, residual, t_f, dur, V2=V2, Vdc=Vdc_pu, iq=iq, idq_mag=idq_mag)
    return dict(label=label, category=cat, fault_type=ft, dur=round(dur, 3),
                metrics_version=REQUIRED_VERSION,
                connect=res['connect']['status'], reactive=res['reactive']['status'],
                limit=res['limit']['status'], recover=res['recover']['status'],
                survive=res['survive']['status'], frt_pass=res['frt_pass'],
                iq_peak_measured=round(float(np.max(np.abs(iq))), 3),
                Vdc_min=round(float(np.min(Vdc_pu)), 3), Vdc_max=round(float(np.max(Vdc_pu)), 3),
                _t=t, _vdc=Vdc_pu, _iq=iq, _V1=V1)


def run(legacy=False):
    """Default: analyse only frt-v2 MATs in SIM_DIR (refuse legacy). legacy=True requires
    HPT_ALLOW_LEGACY_FRT=1, reads from legacy_pre_audit/, writes there, and never emits an active
    CSV/fig7 or a 'FRT PASS' line."""
    if legacy:
        return _run_legacy()
    files = sorted(glob.glob(str(SIM_DIR / '*_sw_result.mat')))
    if not files:
        print('fill_spotcheck: no frt-v2 *_sw_result.mat in', SIM_DIR.name,
              '— PENDING the frt-v2 run_spotcheck.m rewrite (P1). NOT reading legacy_pre_audit.')
        return []
    rows = [analyze_v2(f) for f in files]      # analyze_v2 raises LegacyMatRefused on any non-frt-v2 MAT
    rows.sort(key=lambda r: r['label'])
    cols = ['label', 'category', 'fault_type', 'dur', 'metrics_version', 'connect', 'reactive',
            'limit', 'recover', 'survive', 'frt_pass', 'iq_peak_measured', 'Vdc_min', 'Vdc_max']
    with open(C.RESULTS / 'simulink_spotcheck_table_filled.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore'); w.writeheader(); w.writerows(rows)
    n_pass = sum(1 for r in rows if r['frt_pass'] is True)
    n_none = sum(1 for r in rows if r['frt_pass'] is None)
    print(f'=== frt-v2 switching spot-check ({len(rows)} cases) ===')
    for r in rows:
        verdict = {True: 'PASS', False: 'FAIL', None: 'NOT_EVALUATED'}[r['frt_pass']]
        print(f'{r["label"]:24s} frt_pass={verdict:13s} iq_peak={r["iq_peak_measured"]:.3f} '
              f'Vdc[{r["Vdc_min"]:.2f},{r["Vdc_max"]:.2f}]')
    print(f'frt-v2 spot-check: {n_pass} pass / {n_none} not-evaluated / {len(rows)} total')
    _fig7(rows)
    return rows


def _run_legacy():
    if not os.environ.get('HPT_ALLOW_LEGACY_FRT'):
        raise LegacyMatRefused('legacy spot-check analysis requires HPT_ALLOW_LEGACY_FRT=1 (output '
                               'stays in legacy_pre_audit/, no active CSV/fig7, no FRT PASS).')
    files = sorted(glob.glob(str(LEGACY_DIR / '*_sw_result.mat')))
    LEGACY_DIR.mkdir(exist_ok=True)
    with open(LEGACY_DIR / 'legacy_spotcheck_raw.csv', 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['label', 'note'])
        for fp in files:
            w.writerow([os.path.basename(fp), 'legacy frt-v1 INVALIDATED — verdict not computed'])
    print(f'[legacy] listed {len(files)} legacy MATs -> {LEGACY_DIR.name}/legacy_spotcheck_raw.csv '
          f'(NO frt verdict, NO active fig7/CSV).')
    return files


def _fig7(rows):
    if not rows:
        return
    fig, ax = plt.subplots(figsize=(11, 5))
    x = np.arange(len(rows))
    colour = {True: '#55a868', False: '#c44e52', None: '#999999'}
    ax.bar(x, [r['iq_peak_measured'] for r in rows], color=[colour[r['frt_pass']] for r in rows])
    ax.axhline(0.35, color='r', ls='--', label='limit 0.35')
    ax.set_xticks(x); ax.set_xticklabels([r['label'][:10] for r in rows], rotation=60, fontsize=7)
    ax.set_ylabel('measured iq peak (pu)')
    ax.set_title('Fig 7. frt-v2 switching spot-check (green=PASS red=FAIL grey=NOT_EVALUATED)')
    ax.legend(fontsize=8); fig.tight_layout()
    fig.savefig(C.FIGURES / 'fig7_simulink_spotcheck.png', dpi=130); plt.close(fig)


if __name__ == '__main__':
    import sys
    run(legacy='--legacy' in sys.argv)
