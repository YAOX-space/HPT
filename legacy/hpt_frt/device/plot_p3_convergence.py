"""plot_p3_convergence.py — P3 frt-v2 SAC training convergence figure from EXISTING logs only
(no training / no Simulink / no re-run). Parses lab/results/p3par_20260623_015450_jobs/*.log and plots
the ODE selection proxy vs training steps, per expert and seed.

IMPORTANT: the y-axis is the ODE SELECTION PROXY (partial_proxy_pct over connect/reactive/recover; limit
and survive are NOT_EVALUATED in the ODE). It is NOT a certified frt-v2 / GB-T switching pass rate. The
switching-level certified result lives in docs/FRT_V2_RESULTS_2026-06-23.md and
lab/results/p3_full320_switching_summary.json.

    python -m hpt_frt.device.plot_p3_convergence
writes lab/results/figures/p3_sac_ode_proxy_convergence.{png,pdf} and
lab/results/p3_sac_ode_proxy_convergence.csv .
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
CSVOUT = ROOT / 'lab' / 'results' / 'p3_sac_ode_proxy_convergence.csv'

DISCLAIMER = 'ODE selection proxy, not certified frt-v2 pass rate'

# filename -> (expert, seed)
FNAME = re.compile(r'^(?:seed_)?expert_(?P<name>hvrt_sym|hvrt_asym|sym|asym)_sd(?P<seed>\d+)\.log$')
ABL = re.compile(r'^ablation_single_sd(?P<seed>\d+)\.log$')
RES = re.compile(r'^residual_single_sd(?P<seed>\d+)\.log$')
# a step line: step= 25,000 ... proxy=83% ... best_proxy=82%@25000  OR  best_proxy=83/85%
STEP = re.compile(r'step=\s*([\d,]+)\s+proxy=(\d+)%')
BEST = re.compile(r'best_proxy=([\d]+)(?:/([\d]+))?%')


def parse_log(path):
    """Return list of (step:int, proxy:float, best:float) from one log."""
    rows = []
    for line in path.read_text(encoding='utf-8', errors='ignore').splitlines():
        m = STEP.search(line)
        if not m:
            continue
        step = int(m.group(1).replace(',', ''))
        proxy = float(m.group(2))
        b = BEST.search(line)
        best = float(b.group(2) or b.group(1)) if b else None   # residual: take EMA (2nd); else the value
        rows.append((step, proxy, best))
    return rows


def collect():
    """expert -> seed -> [(step, proxy, best)]"""
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


def write_csv(data):
    CSVOUT.parent.mkdir(parents=True, exist_ok=True)
    with CSVOUT.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['expert', 'seed', 'step', 'ode_selection_proxy_pct', 'best_proxy_pct',
                    'metric_note'])
        for expert in sorted(data):
            for seed in sorted(data[expert]):
                for step, proxy, best in data[expert][seed]:
                    w.writerow([expert, seed, step, proxy, '' if best is None else best, DISCLAIMER])
    return CSVOUT


def plot(data):
    FIGDIR.mkdir(parents=True, exist_ok=True)
    panels = [('sym', 'sym expert (LVRT 3φ)'), ('asym', 'asym expert (1ph_g / 2ph / 2ph_g)'),
              ('hvrt_sym', 'hvrt_sym expert (swell 3φ)'), ('hvrt_asym', 'hvrt_asym expert (swell 1φ)'),
              ('__ablsingle__', 'single-SAC / residual ablation (seed 42)')]
    fig, axes = plt.subplots(2, 3, figsize=(16, 9))
    axes = axes.ravel()
    seeds_all = sorted({s for e in data.values() for s in e})
    cmap = plt.get_cmap('tab10')
    colour = {s: cmap(i % 10) for i, s in enumerate(seeds_all)}

    for ax, (key, title) in zip(axes, panels):
        if key == '__ablsingle__':
            for expert, style in (('ablation_single', '-'), ('residual', '-')):
                for seed, rows in sorted(data.get(expert, {}).items()):
                    xs = [r[0] for r in rows]; ys = [r[1] for r in rows]
                    bs = [r[2] for r in rows]
                    lbl = 'single-SAC (ablation)' if expert == 'ablation_single' else 'residual (EMA)'
                    c = 'tab:blue' if expert == 'ablation_single' else 'tab:red'
                    ax.plot(xs, ys, style, color=c, lw=2, label=f'{lbl}')
                    if any(b is not None for b in bs):
                        ax.plot(xs, [b for b in bs], '--', color=c, lw=1, alpha=0.6,
                                label=f'{lbl} best')
        else:
            for seed in seeds_all:
                rows = data.get(key, {}).get(seed)
                if not rows:
                    continue
                xs = [r[0] for r in rows]; ys = [r[1] for r in rows]; bs = [r[2] for r in rows]
                ax.plot(xs, ys, '-', color=colour[seed], lw=1.8, label=f'seed {seed}')
                if any(b is not None for b in bs):
                    ax.plot(xs, [b for b in bs], '--', color=colour[seed], lw=0.9, alpha=0.5)
        ax.set_title(title, fontsize=11)
        ax.set_xlabel('training steps')
        ax.set_ylabel('ODE selection proxy (%)')
        ax.set_ylim(-5, 105)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=7, loc='lower right', ncol=2)
        ax.text(0.02, 0.04, 'solid = proxy · dashed = running best', transform=ax.transAxes,
                fontsize=7, color='0.4')

    # 6th panel: methodology note
    ax = axes[5]; ax.axis('off')
    ax.text(0.0, 0.95, 'P3 frt-v2 SAC training — ODE selection proxy convergence', fontsize=12,
            weight='bold', va='top')
    ax.text(0.0, 0.80, (
        f'⚠ {DISCLAIMER}.\n\n'
        'Policy: 20-D de-privileged observation, 3-D action [iq, mse_d, mse_q].\n'
        'y-axis = partial_proxy_pct over connect/reactive/recover; limit & survive are\n'
        'NOT_EVALUATED in the ODE, so this is a SELECTION proxy, not a switching pass rate.\n\n'
        'Certified switching-level result (full-320):\n'
        '  residual SAC mi=14:  strict 53.1% / no-fail 89.4% / fail 10.6%\n'
        '  dq fixed-law mi=7:   strict 39.7% / no-fail 68.1% / fail 31.9%\n'
        '  → see docs/FRT_V2_RESULTS_2026-06-23.md +\n'
        '    lab/results/p3_full320_switching_summary.json'),
        fontsize=9, va='top', family='monospace')

    fig.suptitle(f'P3 frt-v2 multi-seed SAC — ODE selection proxy vs steps  ({DISCLAIMER})',
                 fontsize=13, weight='bold')
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    png = FIGDIR / 'p3_sac_ode_proxy_convergence.png'
    pdf = FIGDIR / 'p3_sac_ode_proxy_convergence.pdf'
    fig.savefig(png, dpi=140); fig.savefig(pdf)
    plt.close(fig)
    return png, pdf


def main():
    data = collect()
    if not data:
        raise SystemExit(f'no parseable logs under {JOBS}')
    csvp = write_csv(data)
    png, pdf = plot(data)
    # short console summary
    print(f'parsed experts: {sorted(data)}')
    for e in sorted(data):
        seeds = sorted(data[e])
        finals = {s: data[e][s][-1][1] for s in seeds}
        print(f'  {e:16s} seeds={seeds} final_proxy={finals}')
    print(f'wrote {csvp}')
    print(f'wrote {png}')
    print(f'wrote {pdf}')


if __name__ == '__main__':
    main()
