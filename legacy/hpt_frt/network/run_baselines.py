"""run_baselines.py — Round-2 §5: minimal baselines so Mode 5 is not reported without comparison.

  B1 no_hpt     : no device (or action=0) — pure feeder response to the fault.
  B2 fixed_law  : conventional fixed GB/T droop iq + conservative fixed series budget (NO SAC).
  B3 mode5_sac  : the paper's main method (REUSES exp_B C10 aggregate — same 400-set, no re-run).
  B4 mode6_resid: MPC-assisted residual SAC (EXTENSION, NOT main, NOT pure SAC) — 48-subset only.

Run on the dense C10 scheme over the same 400 scenarios (B1/B2) so it is apples-to-apples with
exp_B (B3). Compares pass-rate / load ride-through / Vdc_min / wrong-sign / oscillation / minV.
Output: results/baseline_summary.csv + results/figures/fig11_baseline_comparison.png
"""
import os, sys, json
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE'); os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import numpy as np
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from . import config as C
from . import opendss_runner as R
from . import sequence as SQ
from . import scenarios as SCN
from . import metrics as M

HB = C.PLACE_C


def eval_no_hpt(scen):
    rows = []
    for sc in scen:
        net = R.build_network(sc, [], [], fault=True)
        if net is None:
            rows.append(dict(converged=False)); continue
        vh = []
        for b in HB:
            Vp, Vn, _ = SQ.seq_components(b); vh.append((Vp, Vn))
        per = [dict(v_load=v[0], vdc_min=1.0, survive=True, reactive=True,
                    connect=v[0] >= 0.2, limit=True, recover=True,
                    screen_pass=v[0] >= 0.2, kvar=0.0) for v in vh]
        info = dict(converged=True, oscillation=False, wrong_sign=0, minV=net['minV'], all_mean=net['all_mean'])
        rows.append(M.system_metrics(per, info))
    return M.aggregate(rows)


def eval_fixed_law(scen):
    rows = []
    for sc in scen:
        q = np.zeros(len(HB)); v = None
        for _ in range(C.FP_MAX_ITERS):
            v = R.build_network(sc, HB, list(q), fault=True)
            if v is None:
                break
            vh = np.array([v['seq'][str(b)][0] for b in HB])
            iq = np.clip(1.5 * (0.9 - vh), 0, C.IQ_CAP)            # fixed GB/T droop
            qn = iq * C.HPT_KVA
            if np.max(np.abs(qn - q)) < C.FP_Q_TOL:
                q = qn; break
            q = 0.5 * q + 0.5 * qn
        if v is None:
            rows.append(dict(converged=False)); continue
        dur = C.duration_rule(v['minV'])
        post = R.build_network(sc, HB, [0.0]*len(HB), fault=False)
        per = []
        for i, b in enumerate(HB):
            Vp, Vn = v['seq'][str(b)]
            iq = float(np.clip(1.5 * (0.9 - Vp), 0, C.IQ_CAP))
            se_d = float(min(C.SE_MAX, max(0.0, (1.0 - 0.82 - 0.08*iq/max(0.3, Vp)) / 1.9)))  # conservative budget
            vdc_min, vdc_max = M.vdc_window(C.vdc_eq(iq, se_d, 0.0, max(0.05, Vp)), dur)
            v_load = min(1.1, Vp + C.SE_GAIN*se_d) if Vp < 0.9 else Vp
            vpost = post['seq'][str(b)][0] if post else None
            crit = M.device_criteria(Vp=Vp, Vn=Vn, iq=iq, se_d=se_d, se_q=0.0,
                                     iq_ref=(min(C.I_Q_MAX, 1.5*(0.9-Vp)) if Vp < 0.9 else 0.0),
                                     vdc_min=vdc_min, vdc_max=vdc_max, v_load=v_load, gate='fixed',
                                     dur=dur, v_post=vpost, iq_post=0.0)
            per.append(dict(v_load=v_load, vdc_min=vdc_min, kvar=iq*C.HPT_KVA, **crit))
        info = dict(converged=True, oscillation=False, minV=v['minV'], all_mean=v['all_mean'],
                    wrong_sign=0)
        rows.append(M.system_metrics(per, info))
    return M.aggregate(rows)


def eval_mode6(scen):
    """MPC-assisted residual SAC (Mode 6 EXTENSION). Reuses the device DC surrogate + residual prior."""
    for s in ['', '.multiarray', '.numeric', '._multiarray_umath', '.umath', '.numerictypes']:
        try: sys.modules['numpy._core'+s] = __import__('numpy.core'+s, fromlist=['x'])
        except Exception: pass
    from gymnasium import spaces
    from stable_baselines3 import SAC
    from ..device.residual_env import mpc_prior3, IQ_CAP, IQ_CAP_ASYM, ASYM_FT, RES_IQ, RES_MSE
    from ..device.frt_env_v2 import (OBS_DIM_V2, N_ACT_V2, online_fault_class, is_fault_measured)
    obs_sp = spaces.Box(-5, 5, shape=(OBS_DIM_V2,), dtype=np.float32)            # frt-v2 20-D
    act_sp = spaces.Box(low=np.array([-RES_IQ, -RES_MSE, -RES_MSE], np.float32),  # frt-v2 3-D residual
                        high=np.array([RES_IQ, RES_MSE, RES_MSE], np.float32))
    co = {'observation_space': obs_sp, 'action_space': act_sp, 'lr_schedule': (lambda _: 3e-4),
          'clip_range': (lambda _: 0.2)}
    model = SAC.load(str(C.MODELS / 'sac_residual_ema_best'), device='cpu', custom_objects=co)
    if model.observation_space.shape != (OBS_DIM_V2,) or model.action_space.shape != (N_ACT_V2,):
        raise ValueError(f'sac_residual_ema_best is {model.observation_space.shape}/'
                         f'{model.action_space.shape}, expected frt-v2 (20,)/(3,)')

    def cmd(V2p, V2n, ft):
        last = np.zeros(N_ACT_V2, np.float32); Vdc = 1.0      # 3-D last action
        cap = IQ_CAP_ASYM if ft in ASYM_FT else IQ_CAP
        for _ in range(5):
            pri = mpc_prior3(V2p, Vdc)                         # 3-D analytic prior
            # DE-PRIVILEGED obs: fault class + in_fault from MEASURED (V2p,V2n), not the true ft
            fc = online_fault_class(V2p, V2n); infault = float(is_fault_measured(V2p, V2n))
            probs = np.zeros(6, np.float32)
            if infault > 0.5 and fc != 0:
                probs[fc] = 0.92; probs[0] += 0.08
            else:
                probs[0] = 1.0
            iqr = min(0.30, 1.5*(0.9-V2p)) if V2p < 0.9 else 0.0
            o = np.array([Vdc, V2p, V2n, abs(last[0]), 0, 0, 0.9-V2p, iqr-last[0], last[0],
                          *probs, 0.3, infault, *last], np.float32)   # tfrac=0.3 static fixed-point
            res, _ = model.predict(np.clip(o, -5, 5), deterministic=True)
            a = pri + res
            iq = float(np.clip(a[0], -cap, cap)); sd = float(np.clip(a[1], -C.SE_MAX, C.SE_MAX))
            sq = float(np.clip(a[2], -C.SE_MAX, C.SE_MAX))
            Vdc = min(C.VDC_CHOP, max(C.VDC_FLOOR, C.vdc_eq(iq, sd, sq, max(0.05, V2p))))
            last = np.array([iq, sd, sq], np.float32)
        return iq, sd, sq

    rows = []
    for sc in scen:
        q = np.zeros(len(HB)); v = None
        for _ in range(C.FP_MAX_ITERS):
            v = R.build_network(sc, HB, list(q), fault=True)
            if v is None:
                break
            vh = [v['seq'][str(b)] for b in HB]
            qn = np.array([cmd(max(0.03, Vp), Vn, sc['fault_type'])[0] * C.HPT_KVA for Vp, Vn in vh])
            if np.max(np.abs(qn - q)) < C.FP_Q_TOL:
                q = qn; break
            q = 0.5*q + 0.5*qn
        if v is None:
            rows.append(dict(converged=False)); continue
        dur = C.duration_rule(v['minV']); post = R.build_network(sc, HB, [0.0]*len(HB), fault=False)
        per = []
        for i, b in enumerate(HB):
            Vp, Vn = v['seq'][str(b)]; iq, sd, sq = cmd(max(0.03, Vp), Vn, sc['fault_type'])
            vdc_min, vdc_max = M.vdc_window(C.vdc_eq(iq, sd, sq, max(0.05, Vp)), dur)
            v_load = min(1.1, Vp + C.SE_GAIN*sd) if Vp < 0.9 else Vp
            vpost = post['seq'][str(b)][0] if post else None
            crit = M.device_criteria(Vp=Vp, Vn=Vn, iq=iq, se_d=sd, se_q=sq,
                                     iq_ref=(min(C.I_Q_MAX, 1.5*(0.9-Vp)) if Vp < 0.9 else 0.0),
                                     vdc_min=vdc_min, vdc_max=vdc_max, v_load=v_load, gate='resid',
                                     dur=dur, v_post=vpost, iq_post=0.0)
            per.append(dict(v_load=v_load, vdc_min=vdc_min, kvar=iq*C.HPT_KVA, **crit))
        info = dict(converged=True, oscillation=False, minV=v['minV'], all_mean=v['all_mean'], wrong_sign=0)
        rows.append(M.system_metrics(per, info))
    return M.aggregate(rows)


def run():
    scen = SCN.gen_scenarios()
    sub48 = SCN.debug_subset()
    out = {}
    print('=== Round-2 §5: baselines (C10 scheme) ===')
    out['B1_no_hpt'] = eval_no_hpt(scen); print('B1 no_hpt done')
    out['B2_fixed_law'] = eval_fixed_law(scen); print('B2 fixed_law done')
    # B3 mode5: reuse exp_B C10 (same 400-set)
    try:
        b = json.loads((C.RESULTS / 'exp_B_summary.json').read_text())['C10']
        out['B3_mode5_sac'] = b
        print('B3 mode5 reused from exp_B C10')
    except Exception as e:
        print('B3 mode5 reuse failed:', e)
    out['B4_mode6_resid_48'] = eval_mode6(sub48); print('B4 mode6 (48-subset) done')

    keys = ['screen_pass_pct', 'survive_pct', 'reactive_pct', 'load_strict_pct', 'load_tol_pct',
            'convergence_pct', 'oscillation_pct', 'wrong_sign_scn_pct', 'minV_mean']
    with open(C.RESULTS / 'baseline_summary.csv', 'w', newline='') as f:
        f.write('baseline,' + ','.join(keys) + '\n')
        for nm, a in out.items():
            f.write(nm + ',' + ','.join(f'{a.get(k, float("nan")):.3f}' if a.get(k) is not None else 'NA'
                                        for k in keys) + '\n')
    (C.RESULTS / 'baseline_summary.json').write_text(json.dumps(out, indent=1))
    for nm, a in out.items():
        print(f'  {nm:18s} FRT={a.get("screen_pass_pct",0):.1f}% surv={a.get("survive_pct",0):.1f}% '
              f'load≥.9={a.get("load_strict_pct",0):.1f}% load≥.7={a.get("load_tol_pct",0):.1f}% '
              f'wrong={a.get("wrong_sign_scn_pct",0):.1f}% osc={a.get("oscillation_pct",0):.1f}% '
              f'minV={a.get("minV_mean",0):.3f}')
    _fig11(out)
    print('saved baseline_summary.csv + fig11_baseline_comparison.png')


def _fig11(out):
    names = list(out.keys())
    fig, axs = plt.subplots(1, 2, figsize=(13, 4.6))
    met = ['screen_pass_pct', 'survive_pct', 'load_strict_pct', 'load_tol_pct']
    x = np.arange(len(met)); w = 0.2
    for i, nm in enumerate(names):
        axs[0].bar(x + (i - 1.5)*w, [out[nm].get(m, 0) for m in met], w, label=nm.replace('_', ' '))
    axs[0].set_xticks(x); axs[0].set_xticklabels(['FRT', 'survive', 'load≥.9', 'load≥.7'], fontsize=9)
    axs[0].set_ylabel('%'); axs[0].legend(fontsize=7); axs[0].set_title('Fig 11a. Baselines: pass / ride-through')
    met2 = ['wrong_sign_scn_pct', 'oscillation_pct']
    for i, nm in enumerate(names):
        axs[1].bar(np.arange(len(met2)) + (i - 1.5)*w, [out[nm].get(m, 0) for m in met2], w, label=nm.replace('_', ' '))
    axs[1].set_xticks(np.arange(len(met2))); axs[1].set_xticklabels(['wrong-sign%', 'oscillation%'], fontsize=9)
    axs[1].legend(fontsize=7); axs[1].set_title('Fig 11b. Baselines: anomalies')
    fig.tight_layout(); fig.savefig(C.FIGURES / 'fig11_baseline_comparison.png', dpi=130); plt.close(fig)


if __name__ == '__main__':
    run()
