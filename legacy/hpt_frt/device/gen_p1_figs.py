"""gen_p1_figs.py — phase-1 visualizations.

⚠️ LEGACY frt-v1 / DISABLED (audit 2026-06-22): the hard-coded ladder values (27.5/64.1/79.7/82.2/
88.4/96.3) are INVALIDATED frt-v1 scores. Regenerating these figures would reintroduce invalid
rankings, so main() refuses to run unless `HPT_ALLOW_LEGACY_FIGS=1` is set. Re-enable only after the
frt-v2 re-validation (P1/P3) produces new numbers; then replace the hard-coded `vals` with values
read from the regenerated result files.
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
FIG = HERE.parents[2] / 'docs' / 'figs'


def fig_ladder():
    names = ['dq-legacy', 'strongest\nfixed (m7)', 'MPC (m8)', 'SAC 4-expert\n(m12)',
             'Hybrid\nSAC+MPC (m13)', 'Residual-SAC\n(m14)']
    # ⚠️ legacy frt-v1 numbers (INVALIDATED 2026-06-22) — figure retained for history only;
    #    do NOT cite as current. Current frt-v2 results: docs/FRT_V2_RESULTS_2026-06-23.md.
    vals = [27.5, 64.06, 79.69, 82.19, 88.4, 96.25]
    kind = ['fixed law', 'fixed law', 'online opt.', 'learning', 'hybrid', 'learning+opt.']
    cols = {'fixed law': '#9aa', 'online opt.': '#86c', 'learning': '#e74',
            'hybrid': '#f9b', 'learning+opt.': '#258'}
    fig, ax = plt.subplots(figsize=(10, 5))
    x = range(len(names))
    ax.bar(x, vals, color=[cols[k] for k in kind], edgecolor='k', width=0.62)
    for i, v in enumerate(vals):
        ax.text(i, v + 1.2, f'{v:.1f}', ha='center', fontweight='bold')
        ax.text(i, 3, kind[i], ha='center', fontsize=8, color='white', rotation=90, va='bottom')
    ax.plot(x, vals, 'k--', lw=0.8, alpha=0.5)
    ax.set_xticks(list(x)); ax.set_xticklabels(names, fontsize=9)
    ax.set_ylabel('full-320 FRT pass rate (%)'); ax.set_ylim(0, 105); ax.grid(axis='y', alpha=0.3)
    ax.set_title('[legacy frt-v1 — INVALIDATED 2026-06-22] Phase-1 decision-law spectrum\n'
                 '(switching-level, consistent calibration); see frt-v2 for current results')
    import matplotlib.patches as mp
    handles = [mp.Patch(color=c, label=k) for k, c in cols.items()]
    ax.legend(handles=handles, loc='upper left', fontsize=8)
    fig.tight_layout(); fig.savefig(FIG / 'fig_p1_ladder.png', dpi=150); plt.close(fig)
    print('A ladder saved')


def fig_residual():
    from stable_baselines3 import SAC
    from residual_env import mpc_prior, IQ_CAP, IQ_CAP_ASYM
    from frt_env import F2I
    model = SAC.load(str(HERE.parents[2] / 'data' / 'models' / 'sac_residual_ema_best.zip'), device='cpu')

    def cmd(V2p, V2n, ft):
        last_a = np.zeros(4, np.float32); Vdc = 1.0
        cap = IQ_CAP_ASYM if ft in ('1ph_g', '2ph', '2ph_g') else IQ_CAP
        fp = F2I.get(ft, 1)
        for _ in range(4):
            pri = mpc_prior(V2p, Vdc)
            vdev = 0.9 - V2p
            iq = last_a[1]
            iq_ref = min(.3, 1.5 * (.9 - V2p)) if V2p < .9 else 0.0
            probs = np.zeros(6, np.float32); probs[fp] = .92; probs[0] += .08
            obs = np.clip(np.array([Vdc, V2p, V2n, abs(iq), 0, 0, vdev, iq_ref - iq, iq,
                                    *probs, .3, 1.0, *last_a], np.float32), -5, 5)
            res, _ = model.predict(obs, deterministic=True)
            a = pri + res
            a1 = float(np.clip(a[1], -cap, cap)); a2 = float(np.clip(a[2], -.2, .2))
            last_a = np.array([0, a1, a2, float(np.clip(a[3], -.2, .2))], np.float32)
            Vdc = 1 - .08 * abs(a1) / max(.3, V2p) - 1.9 * max(0, a2)
        return pri[1], a1, pri[2], a2          # prior_iq, total_iq, prior_se, total_se

    V = np.linspace(0.2, 0.95, 16)
    P = np.array([cmd(v, 0.0, 'sym3ph') for v in V])
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
    # iq panel
    ax = axes[0]
    ax.plot(V, P[:, 0], 's-', color='#888', label='MPC prior')
    ax.plot(V, P[:, 1], 'o-', color='#c33', lw=1.6, label='total (prior+residual)')
    ax.bar(V, P[:, 1] - P[:, 0], bottom=P[:, 0], width=0.025, color='#fc8', alpha=0.7,
           label='learned residual')
    ax.set_xlabel('V2p (pu)'); ax.set_ylabel('reactive iq (pu)'); ax.set_title('reactive channel')
    ax.grid(alpha=0.3); ax.legend(fontsize=8); ax.invert_xaxis()
    # se panel
    ax = axes[1]
    ax.plot(V, P[:, 2], 's-', color='#888', label='MPC prior')
    ax.plot(V, P[:, 3], 'o-', color='#27a', lw=1.6, label='total (prior+residual)')
    ax.bar(V, P[:, 3] - P[:, 2], bottom=P[:, 2], width=0.025, color='#8cf', alpha=0.7,
           label='learned residual')
    ax.set_xlabel('V2p (pu)'); ax.set_ylabel('series boost (pu)'); ax.set_title('series channel')
    ax.grid(alpha=0.3); ax.legend(fontsize=8); ax.invert_xaxis()
    fig.suptitle('Residual-SAC (m14) anatomy: analytic MPC prior + small learned residual = champion\n'
                 '(prior gives the floor & domain logic; residual adds per-condition adaptation)', fontsize=11)
    fig.tight_layout(); fig.savefig(FIG / 'fig_p1_residual_decomp.png', dpi=150); plt.close(fig)
    print('B residual decomposition saved')


def main():
    if os.environ.get('HPT_ALLOW_LEGACY_FIGS') != '1':
        raise SystemExit(
            'gen_p1_figs is DISABLED: its hard-coded scores are LEGACY frt-v1 (invalidated 2026-06-22).\n'
            'Regenerating would reintroduce invalid rankings. Set HPT_ALLOW_LEGACY_FIGS=1 to override\n'
            '(only after frt-v2 re-validation; then replace hard-coded vals with re-read result values).')
    FIG.mkdir(parents=True, exist_ok=True)
    fig_ladder(); fig_residual()
    print('PHASE-1 FIGS (LEGACY frt-v1) ->', FIG)


if __name__ == '__main__':
    main()
