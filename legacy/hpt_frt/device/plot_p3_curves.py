"""plot_p3_curves.py — P3 frt-v2 SAC training curves from EXISTING logs only (no training, no Simulink,
no full-320). Generates the success-rate curve (B) and the constraint-violation curve (C).

There is NO reward/return data anywhere (no monitor.csv / tensorboard events / progress.csv; the logs and
model sidecars have no reward field), so the reward curve (A) is NOT produced — see
docs/P3_CONVERGENCE_DATA_AVAILABILITY_2026-06-25.md.

IMPORTANT framing: the y-axis is the ODE EVALUATION success rate (partial_proxy_pct over the criteria the
ODE can evaluate: connect/reactive/recover). limit & survive are NOT_EVALUATED in the ODE. This is NOT a
certified switching frt-v2 pass rate, and training convergence here does NOT imply the switching full-320
pass rate converges.

    python -m hpt_frt.device.plot_p3_curves
"""
from __future__ import annotations
import re
import csv
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[3]
JOBS = ROOT / 'lab' / 'results' / 'p3par_20260623_015450_jobs'
FIGDIR = ROOT / 'lab' / 'results' / 'figures'

SR_DISCLAIMER = 'ODE evaluation success rate, not certified switching frt-v2 pass rate'

FNAME = re.compile(r'^(?:seed_)?expert_(?P<name>hvrt_sym|hvrt_asym|sym|asym)_sd(?P<seed>\d+)\.log$')
ABL = re.compile(r'^ablation_single_sd(?P<seed>\d+)\.log$')
RES = re.compile(r'^residual_single_sd(?P<seed>\d+)\.log$')

STEP = re.compile(r'step=\s*([\d,]+)\s+proxy=(\d+)%')
COUNTS = re.compile(r'\[req(\d+) ok(\d+) cmpl(\d+) incmpl(\d+) fail(\d+) unev(\d+)\]')
CRIT = re.compile(r'\(con=(\d+|n/e) rea=(\d+|n/e) lim=(\d+|n/e) rec=(\d+|n/e) sur=(\d+|n/e)\)')
BEST = re.compile(r'best_proxy=(\d+)(?:/(\d+))?%')


def _num(x):
    return None if x == 'n/e' else float(x)


def parse_log(path):
    rows = []
    for line in path.read_text(encoding='utf-8', errors='ignore').splitlines():
        m = STEP.search(line)
        if not m:
            continue
        step = int(m.group(1).replace(',', '')); proxy = float(m.group(2))
        b = BEST.search(line); best = float(b.group(2) or b.group(1)) if b else None
        cm = COUNTS.search(line); cc = CRIT.search(line)
        cnt = dict(req=int(cm.group(1)), ok=int(cm.group(2)), cmpl=int(cm.group(3)),
                   incmpl=int(cm.group(4)), fail=int(cm.group(5)), unev=int(cm.group(6))) if cm else {}
        crit = dict(con=_num(cc.group(1)), rea=_num(cc.group(2)), lim=_num(cc.group(3)),
                    rec=_num(cc.group(4)), sur=_num(cc.group(5))) if cc else {}
        rows.append(dict(step=step, proxy=proxy, best=best, **{f'n_{k}': v for k, v in cnt.items()},
                         **{f'c_{k}': v for k, v in crit.items()}))
    return rows


def collect():
    data = {}
    for p in sorted(JOBS.glob('*.log')):
        m = FNAME.match(p.name) or ABL.match(p.name) or RES.match(p.name)
        if not m:
            continue
        if ABL.match(p.name):
            expert, seed = 'ablation_single', int(m.group('seed'))
        elif RES.match(p.name):
            expert, seed = 'residual', int(m.group('seed'))
        else:
            expert, seed = m.group('name'), int(m.group('seed'))
        rows = parse_log(p)
        if rows:
            data.setdefault(expert, {})[seed] = rows
    return data


PANELS = [('sym', 'sym expert (LVRT 3φ)'), ('asym', 'asym expert (1ph_g/2ph/2ph_g)'),
          ('hvrt_sym', 'hvrt_sym expert (swell 3φ)'), ('hvrt_asym', 'hvrt_asym expert (swell 1φ)'),
          ('__ablsingle__', 'single-SAC / residual ablation (seed 42)')]
SEED_ORDER = [42, 7, 123, 2024, 31]


def _seed_colour():
    cmap = plt.get_cmap('tab10')
    return {s: cmap(i % 10) for i, s in enumerate(SEED_ORDER)}


# ---------------- B: success rate ----------------
def plot_success_rate(data):
    col = _seed_colour()
    fig, axes = plt.subplots(2, 3, figsize=(16, 9)); axes = axes.ravel()
    for ax, (key, title) in zip(axes, PANELS):
        if key == '__ablsingle__':
            for expert, c in (('ablation_single', 'tab:blue'), ('residual', 'tab:red')):
                for seed, rows in sorted(data.get(expert, {}).items()):
                    xs = [r['step'] for r in rows]
                    ax.plot(xs, [r['proxy'] for r in rows], '-', color=c, lw=2,
                            label=('single-SAC' if expert == 'ablation_single' else 'residual'))
                    if any(r['best'] is not None for r in rows):
                        ax.plot(xs, [r['best'] for r in rows], '--', color=c, lw=1, alpha=0.6)
        else:
            for seed in SEED_ORDER:
                rows = data.get(key, {}).get(seed)
                if not rows:
                    continue
                xs = [r['step'] for r in rows]
                ax.plot(xs, [r['proxy'] for r in rows], '-', color=col[seed], lw=1.8, label=f'seed {seed}')
                if any(r['best'] is not None for r in rows):
                    ax.plot(xs, [r['best'] for r in rows], '--', color=col[seed], lw=0.9, alpha=0.5)
        ax.set_title(title, fontsize=11); ax.set_xlabel('training steps')
        ax.set_ylabel('ODE success rate (%)'); ax.set_ylim(-5, 105); ax.grid(True, alpha=0.3)
        ax.legend(fontsize=7, loc='lower right', ncol=2)
        ax.text(0.02, 0.04, 'solid = success rate · dashed = running best', transform=ax.transAxes,
                fontsize=7, color='0.4')
    ax = axes[5]; ax.axis('off')
    ax.text(0.0, 0.92, 'P3 frt-v2 SAC — ODE success-rate convergence', fontsize=12, weight='bold', va='top')
    ax.text(0.0, 0.72, (f'⚠ {SR_DISCLAIMER}.\n\n'
        'success rate = partial_proxy_pct = fraction of evaluable criteria passed\n'
        '(connect / reactive / recover). limit & survive are NOT_EVALUATED in the\n'
        'ODE, so this does NOT imply the switching full-320 pass rate.\n\n'
        'Certified switching full-320 (separate, NOT shown converging):\n'
        '  residual SAC mi=14:  strict 53.1% / no-fail 89.4% / fail 10.6%\n'
        '  see docs/FRT_V2_RESULTS_2026-06-23.md'), fontsize=9, va='top', family='monospace')
    fig.suptitle(f'P3 frt-v2 multi-seed SAC — success rate vs steps  ({SR_DISCLAIMER})',
                 fontsize=13, weight='bold')
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    p = FIGDIR / 'p3_success_rate_convergence.png'; fig.savefig(p, dpi=140); plt.close(fig)
    return p


# ---------------- C: constraint violation ----------------
def plot_violation(data):
    """Per-expert mean violation (= 100 - pass%) for connect/reactive/recover; limit/survive NOT_EVALUATED."""
    fig, axes = plt.subplots(2, 3, figsize=(16, 9)); axes = axes.ravel()
    cseries = [('c_con', 'connect violation', 'tab:green'),
               ('c_rea', 'reactive violation', 'tab:orange'),
               ('c_rec', 'recover violation', 'tab:purple')]
    keys = ['sym', 'asym', 'hvrt_sym', 'hvrt_asym']
    titles = dict(PANELS)
    for ax, key in zip(axes, keys):
        # union of steps across seeds; mean violation where the criterion is evaluated
        for ck, label, colr in cseries:
            steps, viol = _mean_violation(data.get(key, {}), ck)
            if steps:
                ax.plot(steps, viol, '-o', ms=2.5, color=colr, lw=1.6, label=label)
        ax.set_title(titles[key], fontsize=11); ax.set_xlabel('training steps')
        ax.set_ylabel('violation (%) = 100 − pass%'); ax.set_ylim(-5, 105); ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8, loc='upper right')
        ax.text(0.02, 0.92, 'limit & survive: NOT_EVALUATED (ODE)', transform=ax.transAxes,
                fontsize=8, color='tab:red')
    # ablation/residual violation panel
    ax = axes[4]
    for expert, c in (('ablation_single', 'tab:blue'), ('residual', 'tab:red')):
        steps, viol = _mean_violation(data.get(expert, {}), 'c_rea')
        if steps:
            ax.plot(steps, viol, '-o', ms=2.5, color=c, lw=1.6,
                    label=('single-SAC' if expert == 'ablation_single' else 'residual') + ' reactive viol.')
    ax.set_title('single-SAC / residual — reactive violation (seed 42)', fontsize=11)
    ax.set_xlabel('training steps'); ax.set_ylabel('violation (%)'); ax.set_ylim(-5, 105)
    ax.grid(True, alpha=0.3); ax.legend(fontsize=8, loc='upper right')
    ax = axes[5]; ax.axis('off')
    ax.text(0.0, 0.92, 'P3 frt-v2 SAC — key constraint-violation convergence', fontsize=12, weight='bold', va='top')
    ax.text(0.0, 0.70, ('violation = 100 − criterion pass% (ODE eval, per checkpoint), mean over seeds.\n\n'
        'connect / reactive / recover : plotted.\n'
        'limit / survive               : NOT_EVALUATED in the ODE (no switching\n'
        '                                current / DC bus) → not plotted, not zero-filled.\n\n'
        f'⚠ {SR_DISCLAIMER}.\nSwitching-level failures (limit/survive) live in the certified\n'
        'full-320, not here: docs/FRT_V2_ERROR_ANALYSIS_2026-06-24.md.'), fontsize=9, va='top', family='monospace')
    fig.suptitle('P3 frt-v2 SAC — key constraint violation vs steps  (connect/reactive/recover; limit & survive NOT_EVALUATED)',
                 fontsize=12, weight='bold')
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    p = FIGDIR / 'p3_constraint_violation_convergence.png'; fig.savefig(p, dpi=140); plt.close(fig)
    return p


def _mean_violation(seed_rows, ck):
    """mean (100 - pass%) at each step across seeds, skipping NOT_EVALUATED (None) entries."""
    from collections import defaultdict
    acc = defaultdict(list)
    for seed, rows in seed_rows.items():
        for r in rows:
            v = r.get(ck)
            if v is not None:
                acc[r['step']].append(100.0 - v)
    steps = sorted(acc)
    return steps, [sum(acc[s]) / len(acc[s]) for s in steps]


# ---------------- CSVs ----------------
def write_csvs(data):
    sr = ROOT / 'lab' / 'results' / 'p3_success_rate_convergence.csv'
    vi = ROOT / 'lab' / 'results' / 'p3_constraint_violation_convergence.csv'
    with sr.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['expert', 'seed', 'step', 'success_rate_pct', 'best_success_rate_pct',
                    'n_req', 'n_ok', 'n_fail', 'n_incomplete', 'metric_note'])
        for e in sorted(data):
            for s in sorted(data[e]):
                for r in data[e][s]:
                    w.writerow([e, s, r['step'], r['proxy'], r.get('best', ''),
                                r.get('n_req', ''), r.get('n_ok', ''), r.get('n_fail', ''),
                                r.get('n_incmpl', ''), SR_DISCLAIMER])
    with vi.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['expert', 'seed', 'step', 'connect_violation_pct', 'reactive_violation_pct',
                    'recover_violation_pct', 'limit_status', 'survive_status', 'metric_note'])
        for e in sorted(data):
            for s in sorted(data[e]):
                for r in data[e][s]:
                    cv = '' if r.get('c_con') is None else round(100 - r['c_con'], 1)
                    rv = '' if r.get('c_rea') is None else round(100 - r['c_rea'], 1)
                    rcv = '' if r.get('c_rec') is None else round(100 - r['c_rec'], 1)
                    w.writerow([e, s, r['step'], cv, rv, rcv, 'NOT_EVALUATED', 'NOT_EVALUATED',
                                SR_DISCLAIMER])
    return sr, vi


def main():
    data = collect()
    if not data:
        raise SystemExit(f'no parseable logs under {JOBS}')
    FIGDIR.mkdir(parents=True, exist_ok=True)
    print('reward data found: NONE (no monitor.csv / tensorboard / progress.csv / reward field) -> A skipped')
    sr_csv, vi_csv = write_csvs(data)
    sr_png = plot_success_rate(data)
    vi_png = plot_violation(data)
    print(f'experts: {sorted(data)}')
    print(f'wrote {sr_png}\nwrote {sr_csv}')
    print(f'wrote {vi_png}\nwrote {vi_csv}')


if __name__ == '__main__':
    main()
