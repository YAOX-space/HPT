"""plot_results.py — figures for the Phase-2 network stress test (section 十).

Reads results/*.csv (+ recomputes the sag heatmap via OpenDSS) and writes results/figures/*.png:
  fig1_sag_heatmap          fault location × HPT bus -> local Vp
  fig2_ood_sweep            single-HPT iq/se_d/Vdc_min vs Vp (Exp A)
  fig3_multi_hpt_timeseries Vp/iq/se_d/Vdc of each HPT (Exp B representative)
  fig4_passrate_bars        single vs network, B4 vs C10, instant vs slow
  fig5_failures             3-5 failure cases, why they failed
  fig6_gate                 Mode-5 gate class timeseries, switch distribution, raw vs hysteresis
"""
import os, sys, csv, json, glob
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from . import config as C

FIG = C.FIGURES


def _read_csv(path):
    p = C.RESULTS / path
    if not p.exists() or p.stat().st_size == 0:
        return []
    with open(p, newline='') as f:
        return list(csv.DictReader(f))


def _f(row, k, default=np.nan):
    try:
        return float(row[k])
    except (KeyError, ValueError, TypeError):
        return default


# ── fig 1: sag-propagation heatmap ───────────────────────────────────────────────
def fig_sag_heatmap():
    import opendss_runner as R
    cols = C.PLACE_C
    rows = list(range(2, 34))
    Z = np.full((len(rows), len(cols)), np.nan)
    for i, fb in enumerate(rows):
        sc = dict(load_lvl=1.0, pv_pen=0.3, fault_bus=fb, fault_type='sym3ph', r_fault=0.5)
        sag = R.sag_at_buses(sc, cols)
        if sag is None:
            continue
        for j, cb in enumerate(cols):
            Z[i, j] = sag[cb][0]
    fig, ax = plt.subplots(figsize=(6.5, 8))
    im = ax.imshow(Z, aspect='auto', cmap='RdYlGn', vmin=0, vmax=1.0,
                   extent=[0, len(cols), rows[-1], rows[0]])
    ax.set_xticks(np.arange(len(cols)) + 0.5); ax.set_xticklabels(cols)
    ax.set_xlabel('HPT bus'); ax.set_ylabel('fault bus (3φ, r=0.5Ω)')
    ax.set_title('Fig 1. IEEE-33 fault-sag propagation: local Vp at each HPT')
    fig.colorbar(im, ax=ax, label='local positive-seq voltage Vp (pu)')
    fig.tight_layout(); fig.savefig(FIG / 'fig1_sag_heatmap.png', dpi=130); plt.close(fig)
    print('fig1_sag_heatmap.png')


# ── fig 2: single-HPT OOD sweep ──────────────────────────────────────────────────
def fig_ood_sweep():
    rows = _read_csv('exp_A_summary.csv')
    if not rows:
        return
    fig, axs = plt.subplots(1, 3, figsize=(15, 4.3))
    for ft, col in [('sym3ph', 'tab:blue'), ('1ph_g', 'tab:orange')]:
        sub = [r for r in rows if r['fault_type'] == ft]
        Vp = np.array([_f(r, 'Vp') for r in sub])
        for ax, key, ttl in [(axs[0], 'iq', 'iq_ref (reactive cmd)'),
                             (axs[1], 'se_d', 'mse_d (series boost)'),
                             (axs[2], 'vdc_min', 'Vdc_min (surrogate)')]:
            ax.scatter(Vp, [_f(r, key) for r in sub], s=7, alpha=0.4, color=col, label=ft)
    # reference lines
    vv = np.linspace(0.05, 0.9, 50)
    axs[0].plot(vv, np.minimum(0.30, 1.5 * (0.9 - vv)), 'k--', lw=1, label='GB/T droop ref')
    axs[0].axhline(C.IQ_CAP, color='r', ls=':', lw=1, label='cap 0.27')
    axs[0].axhline(0, color='gray', lw=0.6)
    axs[2].axhline(C.VDC_MIN_OK, color='r', ls=':', lw=1, label='survive 0.75')
    for ax, ttl in zip(axs, ['iq vs Vp', 'mse_d vs Vp', 'Vdc_min vs Vp']):
        ax.set_xlabel('local Vp (pu)'); ax.set_title('Fig 2. ' + ttl); ax.legend(fontsize=8); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(FIG / 'fig2_ood_sweep.png', dpi=130); plt.close(fig)
    print('fig2_ood_sweep.png')


# ── fig 3: multi-HPT coupling time series ────────────────────────────────────────
def fig_multi_timeseries():
    files = sorted(glob.glob(str(C.TS_DIR / 'B_9001_*_hpt*.csv')))
    if not files:
        return
    series = {}
    for fpath in files:
        bus = fpath.split('hpt')[-1].split('.')[0]
        with open(fpath, newline='') as f:
            series[bus] = list(csv.DictReader(f))
    fig, axs = plt.subplots(2, 2, figsize=(13, 7.5), sharex=True)
    keys = [('Vp', 'local Vp (pu)'), ('iq', 'iq_ref (pu)'),
            ('se_d', 'mse_d (pu)'), ('Vdc', 'Vdc (pu)')]
    for ax, (k, lab) in zip(axs.flat, keys):
        for bus, rs in series.items():
            t = [_f(r, 't') for r in rs]
            ax.plot(t, [_f(r, k) for r in rs], lw=1.1, label=f'HPT{bus}')
        ax.set_ylabel(lab); ax.grid(alpha=0.3)
    axs[1, 0].set_xlabel('t (s)'); axs[1, 1].set_xlabel('t (s)')
    axs[1, 1].axhline(C.VDC_MIN_OK, color='r', ls=':', lw=1)
    axs[0, 0].legend(ncol=5, fontsize=7, loc='lower right')
    fig.suptitle('Fig 3. Multi-HPT (10-unit) independent SAC — deep 3φ fault @bus6 (no coordinator)')
    fig.tight_layout(); fig.savefig(FIG / 'fig3_multi_hpt_timeseries.png', dpi=130); plt.close(fig)
    print('fig3_multi_hpt_timeseries.png')


# ── fig 4: pass-rate bars ────────────────────────────────────────────────────────
def fig_passrate():
    summ = {}
    try:
        summ = json.loads((C.RESULTS / 'exp_B_summary.json').read_text())
    except Exception:
        pass
    a = _read_csv('exp_A_summary.csv')
    a_uv = [r for r in a if _f(r, 'Vp') < 0.9]
    a_frt = 100 * np.mean([_f(r, 'screen_pass') for r in a_uv]) if a_uv else 0
    cats = ['single-HPT\n(Exp A, undervolt)',
            '4-HPT net\n(Exp B)', '10-HPT net\n(Exp B)']
    vals = [a_frt,
            summ.get('B4', {}).get('screen_pass_pct', 0),
            summ.get('C10', {}).get('screen_pass_pct', 0)]
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.3))
    bars = axs[0].bar(cats, vals, color=['#4c72b0', '#55a868', '#55a868'])
    for b, v in zip(bars, vals):
        axs[0].text(b.get_x() + b.get_width() / 2, v + 1, f'{v:.0f}%', ha='center', fontsize=9)
    axs[0].set_ylabel('FRT pass (%)'); axs[0].set_ylim(0, 105)
    axs[0].set_title('Fig 4a. FRT pass: single vs network')
    # criteria breakdown B4 vs C10
    crit = ['connect_pct', 'reactive_pct', 'limit_pct', 'recover_pct', 'survive_pct']
    labels = ['connect', 'reactive', 'limit', 'recover', 'survive']
    x = np.arange(len(crit)); w = 0.35
    for off, sch, col in [(-w / 2, 'B4', '#55a868'), (w / 2, 'C10', '#c44e52')]:
        d = summ.get(sch, {})
        axs[1].bar(x + off, [d.get(k, 0) for k in crit], w, label=sch, color=col)
    axs[1].set_xticks(x); axs[1].set_xticklabels(labels); axs[1].set_ylim(0, 105)
    axs[1].set_ylabel('pass (%)'); axs[1].legend(); axs[1].set_title('Fig 4b. Criteria: 4-HPT vs 10-HPT')
    fig.tight_layout(); fig.savefig(FIG / 'fig4_passrate_bars.png', dpi=130); plt.close(fig)
    print('fig4_passrate_bars.png')


# ── fig 5: failure-case analysis ─────────────────────────────────────────────────
def fig_failures():
    fr = _read_csv('failures_B.csv')
    fr = [r for r in fr if r.get('failure') and r.get('hpt_bus')]
    if not fr:
        return
    from collections import Counter
    cnt = Counter(r['failure'] for r in fr)
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.3))
    axs[0].bar(list(cnt.keys()), list(cnt.values()), color='#c44e52')
    axs[0].set_ylabel('# device-scenario failures'); axs[0].set_title('Fig 5a. Failure-mode breakdown (Exp B)')
    for i, (k, v) in enumerate(cnt.items()):
        axs[0].text(i, v, str(v), ha='center', va='bottom', fontsize=9)
    # scatter of failures in (Vp, vdc_min)
    Vp = [_f(r, 'Vp') for r in fr if r.get('Vp')]
    vd = [_f(r, 'vdc_min') for r in fr if r.get('vdc_min')]
    axs[1].scatter(Vp, vd, c=['#c44e52' if _f(r, 'survive') == 0 else '#dd8452' for r in fr
                                   if r.get('Vp') and r.get('vdc_min')], s=14, alpha=0.6)
    axs[1].axhline(C.VDC_MIN_OK, color='r', ls=':', label='survive 0.75')
    axs[1].set_xlabel('local Vp (pu)'); axs[1].set_ylabel('Vdc_min (surrogate)')
    axs[1].set_title('Fig 5b. Failures in (Vp, Vdc_min)'); axs[1].legend(fontsize=8); axs[1].grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(FIG / 'fig5_failures.png', dpi=130); plt.close(fig)
    print('fig5_failures.png')


# ── fig 6: Mode-5 gate behaviour ─────────────────────────────────────────────────
def fig_gate():
    GMAP = {'normal': 0, 'sym': 1, 'asym': 2, 'hvrt_sym': 3, 'hvrt_asym': 4}
    raw = sorted(glob.glob(str(C.TS_DIR / 'C_raw_3_*_hpt10.csv')))
    hys = sorted(glob.glob(str(C.TS_DIR / 'C_hyst_3_*_hpt10.csv')))
    rows = _read_csv('exp_C_summary.csv')
    fig, axs = plt.subplots(1, 3, figsize=(15, 4.3))
    # gate class timeseries raw vs hyst
    for files, lab, col in [(raw, 'raw', 'tab:red'), (hys, 'hysteresis', 'tab:blue')]:
        if files:
            with open(files[0], newline='') as f:
                rs = list(csv.DictReader(f))
            t = [_f(r, 't') for r in rs]
            axs[0].step(t, [GMAP.get(r['gate'], 0) for r in rs], where='post', label=lab, color=col, lw=1.4)
    axs[0].set_yticks(list(GMAP.values())); axs[0].set_yticklabels(list(GMAP.keys()))
    axs[0].set_xlabel('t (s)'); axs[0].set_title('Fig 6a. Gate class (1φ-g, slow recovery)')
    axs[0].legend(fontsize=8); axs[0].grid(alpha=0.3)
    # switch-count distribution raw vs hyst
    for gv, col in [('raw', 'tab:red'), ('hyst', 'tab:blue')]:
        sw = [_f(r, 'total_switches') for r in rows if r['gate'] == gv]
        axs[1].hist(sw, bins=8, alpha=0.55, label=gv, color=col)
    axs[1].set_xlabel('total gate switches / scenario (10 HPTs)'); axs[1].set_ylabel('# runs')
    axs[1].set_title('Fig 6b. Switch-count distribution'); axs[1].legend(fontsize=8)
    # chattering metric raw vs hyst
    gvs = ['raw', 'hyst']
    chat = [np.mean([_f(r, 'chatter_hpts') for r in rows if r['gate'] == gv]) for gv in gvs]
    smooth = [100 * np.mean([_f(r, 'smooth_exit') for r in rows if r['gate'] == gv]) for gv in gvs]
    x = np.arange(2); w = 0.35
    axs[2].bar(x - w / 2, chat, w, label='chatter HPTs/scn', color='tab:red')
    axs[2].bar(x + w / 2, [s / 100 for s in smooth], w, label='smooth-exit frac', color='tab:green')
    axs[2].set_xticks(x); axs[2].set_xticklabels(gvs)
    axs[2].set_title('Fig 6c. Chattering & smooth-exit'); axs[2].legend(fontsize=8)
    fig.tight_layout(); fig.savefig(FIG / 'fig6_gate.png', dpi=130); plt.close(fig)
    print('fig6_gate.png')


def run():
    fig_ood_sweep(); fig_multi_timeseries(); fig_passrate(); fig_failures(); fig_gate()
    fig_sag_heatmap()                      # last (needs OpenDSS, slowest)
    print(f'all figures -> {FIG}')


if __name__ == '__main__':
    run()
