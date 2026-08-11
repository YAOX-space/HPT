"""plot_reward_logging.py — diagnostic figures from a reward-logging run dir (train_reward_logging.py).
Reads monitor.csv / progress.csv / eval_curve.csv and writes:
  fig_reward_curve.png, fig_success_rate_curve.png, fig_constraint_violation_curve.png,
  fig_training_diagnostics_combined.png
into the SAME run dir. All figures carry: "ODE training diagnostics only; not certified switching
frt-v2 pass rate." No training / Simulink / full-320.

    python -m hpt_frt.device.plot_reward_logging --help
    python -m hpt_frt.device.plot_reward_logging [--rundir lab/results/reward_logging_YYYYMMDD_HHMMSS]
"""
from __future__ import annotations
import csv
import argparse
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / 'lab' / 'results'
BANNER = 'ODE training diagnostics only; not certified switching frt-v2 pass rate'


def latest_rundir():
    ds = sorted(RESULTS.glob('reward_logging_*'))
    if not ds:
        raise SystemExit('no reward_logging_* dir found — run train_reward_logging first')
    return ds[-1]


def _read_monitor(p):
    """SB3 monitor.csv: first line is a #json comment, then header r,l,t. Return (cum_steps, rewards)."""
    if not p.exists():
        return [], []
    lines = [ln for ln in p.read_text(encoding='utf-8').splitlines() if not ln.startswith('#')]
    if len(lines) < 2:
        return [], []
    rd = csv.DictReader(lines)
    cum, rew, c = [], [], 0
    for row in rd:
        try:
            c += int(float(row['l'])); cum.append(c); rew.append(float(row['r']))
        except (KeyError, ValueError):
            continue
    return cum, rew


def _read_progress(p):
    if not p.exists():
        return []
    rows = list(csv.DictReader(p.read_text(encoding='utf-8').splitlines()))
    return rows


def _read_eval(p):
    return list(csv.DictReader(p.read_text(encoding='utf-8').splitlines())) if p.exists() else []


def _col(rows, key):
    xs, ys = [], []
    for r in rows:
        v = r.get(key, '')
        t = r.get('time/total_timesteps', '')
        if v not in ('', None) and t not in ('', None):
            try:
                xs.append(float(t)); ys.append(float(v))
            except ValueError:
                continue
    return xs, ys


def _movavg(ys, w=9):
    if len(ys) < 2:
        return ys
    w = max(1, min(w, len(ys)))
    out = []
    for i in range(len(ys)):
        a = max(0, i - w + 1)
        out.append(sum(ys[a:i + 1]) / (i - a + 1))
    return out


def reward_axes(ax, monitor, progress):
    cum, rew = monitor
    xs_m, ys_m = _col(progress, 'rollout/ep_rew_mean')
    plotted = False
    if cum and rew:
        ax.plot(cum, rew, '.', ms=3, color='0.7', label='episode reward (raw)')
        ax.plot(cum, _movavg(rew, 21), '-', color='tab:blue', lw=1.6, label='episode reward (moving avg)')
        plotted = True
    if xs_m and ys_m:
        ax.plot(xs_m, ys_m, '-', color='tab:red', lw=2, label='rollout/ep_rew_mean (SB3)')
        plotted = True
    if not plotted:
        ax.text(0.5, 0.5, 'no reward data parsed', ha='center', transform=ax.transAxes)
    ax.set_xlabel('training steps'); ax.set_ylabel('episode reward'); ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8, loc='best'); ax.set_title('Reward convergence', fontsize=11)


def success_axes(ax, ev):
    xs = [float(r['step']) for r in ev]
    ys = [float(r['success_proxy_pct']) for r in ev]
    ax.plot(xs, ys, '-o', color='tab:green', lw=1.8, ms=4, label='ODE success proxy')
    ax.set_ylim(-5, 105); ax.set_xlabel('eval steps'); ax.set_ylabel('ODE success rate (%)')
    ax.grid(True, alpha=0.3); ax.legend(fontsize=8, loc='lower right')
    ax.set_title('Success-rate convergence (ODE proxy)', fontsize=11)


def violation_axes(ax, ev):
    series = [('connect_violation_pct', 'connect viol.', 'tab:green'),
              ('reactive_violation_pct', 'reactive viol.', 'tab:orange'),
              ('recover_violation_pct', 'recover viol.', 'tab:purple')]
    for key, lab, col in series:
        xs, ys = [], []
        for r in ev:
            v = r.get(key, '')
            if v not in ('', None):
                xs.append(float(r['step'])); ys.append(float(v))
        if xs:
            ax.plot(xs, ys, '-o', color=col, lw=1.6, ms=4, label=lab)
    ax.set_ylim(-5, 105); ax.set_xlabel('eval steps'); ax.set_ylabel('violation (%) = 100 − pass%')
    ax.grid(True, alpha=0.3); ax.legend(fontsize=8, loc='upper right')
    ax.text(0.02, 0.92, 'limit & survive: NOT_EVALUATED (ODE)', transform=ax.transAxes,
            fontsize=8, color='tab:red')
    ax.set_title('Key constraint-violation convergence', fontsize=11)


def main(rundir=None):
    rundir = Path(rundir) if rundir else latest_rundir()
    monitor = _read_monitor(rundir / 'monitor.csv')
    progress = _read_progress(rundir / 'progress.csv')
    ev = _read_eval(rundir / 'eval_curve.csv')
    if not ev:
        raise SystemExit(f'no eval_curve.csv in {rundir}')

    # 1) reward
    fig, ax = plt.subplots(figsize=(9, 5)); reward_axes(ax, monitor, progress)
    fig.suptitle(f'Reward curve — {rundir.name}\n{BANNER}', fontsize=11)
    fig.tight_layout(); fig.savefig(rundir / 'fig_reward_curve.png', dpi=140); plt.close(fig)
    # 2) success
    fig, ax = plt.subplots(figsize=(9, 5)); success_axes(ax, ev)
    fig.suptitle(f'Success rate — {rundir.name}\n{BANNER}', fontsize=11)
    fig.tight_layout(); fig.savefig(rundir / 'fig_success_rate_curve.png', dpi=140); plt.close(fig)
    # 3) violation
    fig, ax = plt.subplots(figsize=(9, 5)); violation_axes(ax, ev)
    fig.suptitle(f'Constraint violation — {rundir.name}\n{BANNER}', fontsize=11)
    fig.tight_layout(); fig.savefig(rundir / 'fig_constraint_violation_curve.png', dpi=140); plt.close(fig)
    # 4) combined
    fig, axes = plt.subplots(1, 3, figsize=(18, 5.5))
    reward_axes(axes[0], monitor, progress); success_axes(axes[1], ev); violation_axes(axes[2], ev)
    fig.suptitle(f'P3 small reward-logging retrain — training diagnostics ({rundir.name})   ⚠ {BANNER}',
                 fontsize=12, weight='bold')
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(rundir / 'fig_training_diagnostics_combined.png', dpi=140); plt.close(fig)

    print(f'rundir={rundir}')
    print(f'  monitor episodes parsed: {len(monitor[0])} | progress rows: {len(progress)} | eval points: {len(ev)}')
    for fn in ('fig_reward_curve.png', 'fig_success_rate_curve.png',
               'fig_constraint_violation_curve.png', 'fig_training_diagnostics_combined.png'):
        print(f'  wrote {rundir / fn}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Plot diagnostics from a reward-logging run dir.')
    ap.add_argument('--rundir', default=None, help='reward_logging_* dir (default: latest)')
    a = ap.parse_args()
    main(rundir=a.rundir)
