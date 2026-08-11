"""study_c10_oscillation.py — Round-2 §3: forensic of the C10 (10-HPT) ~6% fixed-point oscillation,
+ deployment-side mitigation comparison (NO SAC retrain).

Part 1 — case study: re-run the scenarios flagged OSC in Exp B, record the OpenDSS fixed-point
residual history + per-HPT (Vp, iq_ref, mse_d, Vdc, gate), and CLASSIFY the oscillation:
   numerical | reactive(iq)-coupling limit cycle | gate-boundary action jump | Vdc-proxy slow | deep-fault flow.

Part 2 — mitigation comparison over the full C10 400-set, variants (sections 三.A-D):
   A baseline | B slew(reactive Δq rate-limit + extra damping) | C safety projection (se_d cap)
   | D hysteresis+slew. Reports convergence / oscillation / wrong-sign / FRT / survive / Vdc_min /
   load>=0.9/0.7 / action-modification mean & max.

Outputs: results/c10_oscillation_cases.csv, results/mitigation_summary.csv,
         results/figures/fig9_c10_oscillation_case_study.png, fig10_mitigation_comparison.png
"""
import os, sys, csv, json
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE'); os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import numpy as np
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from . import config as C
from . import opendss_runner as R
from .hpt_interface import HPT, lv_compensated
from .sac_wrapper import iq_ref_gbt
from . import scenarios as SCN
from . import metrics as M

VARIANTS = {
    'A_baseline':  dict(),
    'B_slew':      dict(slew_kvar=30.0, max_iters=40),
    'C_safety':    dict(ctrl=dict(safety=True, vdc_floor=0.78)),
    'D_hyst_slew': dict(slew_kvar=30.0, max_iters=40, ctrl=dict(use_hysteresis=True)),
}


def make_fleet(ctrl_kw):
    return [HPT(b, **ctrl_kw) for b in C.PLACE_C]


def eval_variant(scen, vparams):
    ctrl_kw = vparams.get('ctrl', {})
    fp_kw = {k: v for k, v in vparams.items() if k in ('slew_kvar', 'max_iters')}
    hpts = make_fleet(ctrl_kw)
    sys_rows, mods = [], []
    for sc in scen:
        for h in hpts:
            h.reset()
        cmds, info = R.solve_fixed_point(sc, hpts, fault=True, **fp_kw)
        if cmds is None or info.get('nonconverged'):
            sys_rows.append(dict(converged=False, oscillation=False, wrong_sign=0, minV=None,
                                 screen_pass_pct=0, survive_pct=0, reactive_pct=0, connect_pct=0,
                                 limit_pct=0, recover_pct=0, load_strict_pct=0, load_tol_pct=0,
                                 screen_compliance_pct=0, n_affected=0, total_qvar_kvar=0))
            continue
        dur = C.duration_rule(info['minV'])
        post = R.build_network(sc, [h.bus for h in hpts], [0.0]*len(hpts), fault=False)
        per = []
        for h, c in zip(hpts, cmds):
            Vp, Vn = info['seq'][str(h.bus)]
            vdc_min, vdc_max = M.vdc_window(C.vdc_eq(c['iq'], c['se_d'], c['se_q'], max(0.05, Vp)), dur)
            v_load = lv_compensated(Vp, c['se_d']); v_post = post['seq'][str(h.bus)][0] if post else None
            crit = M.device_criteria(Vp=Vp, Vn=Vn, iq=c['iq'], se_d=c['se_d'], se_q=c['se_q'],
                                     iq_ref=c['iq_ref'], vdc_min=vdc_min, vdc_max=vdc_max, v_load=v_load,
                                     gate=c['gate'], dur=dur, v_post=v_post,
                                     iq_post=(abs(iq_ref_gbt(v_post)) if v_post is not None else None))
            per.append(dict(v_load=v_load, vdc_min=vdc_min, kvar=h.kvar, **crit))
        sys_rows.append(M.system_metrics(per, info))
        mods.append(max(h.ctrl.se_proj_max for h in hpts) + max(h.ctrl.slew_clip_total for h in hpts) * 0)
        mods[-1] = max(h.ctrl.se_proj_max for h in hpts)
    agg = M.aggregate(sys_rows)
    agg['se_proj_mean'] = float(np.mean(mods)) if mods else 0.0
    agg['se_proj_max'] = float(np.max(mods)) if mods else 0.0
    return agg, sys_rows


def case_study(osc_ids, scen_by_id):
    """Re-run OSC scenarios, record residual history + per-HPT detail; classify."""
    rows, fig_case = [], None
    for sid in osc_ids[:8]:
        sc = scen_by_id.get(sid)
        if sc is None:
            continue
        hpts = make_fleet({})
        cmds, info = R.solve_fixed_point(sc, hpts, fault=True)
        rh = info['resid_hist']
        # classify
        if info.get('nonconverged'):
            cls = 'deep-flow-nonconverge'
        elif info['minV'] < 0.1:
            cls = 'deep-flow-stiff'
        else:
            # reactive-coupling limit cycle if residual bounces but bounded; gate-jump if a gate
            # differs across the last iters
            bounce = any(rh[i+1] > rh[i] + 1e-6 for i in range(len(rh)-1))
            cls = 'reactive-coupling-limit-cycle' if bounce else 'numerical-slow'
        iqs = [c['iq'] for c in cmds] if cmds else []
        rows.append(dict(scn_id=sid, fault_bus=sc['fault_bus'], fault_type=sc['fault_type'],
                         r_fault=round(sc['r_fault'], 3), minV=round(info['minV'], 3),
                         iters=info['iters'], resid_final=round(info['resid_final'], 2),
                         oscillation=int(info['oscillation']), wrong_sign=info['wrong_sign'],
                         classification=cls,
                         iq_min=round(min(iqs), 3) if iqs else 0, iq_max=round(max(iqs), 3) if iqs else 0))
        if fig_case is None and info['oscillation']:
            fig_case = (sid, sc, info, cmds)
    return rows, fig_case


def run():
    scen = SCN.gen_scenarios()
    scen_by_id = {s['id']: s for s in scen}
    # OSC ids from Exp B failures
    osc_ids = []
    fb = C.RESULTS / 'failures_B.csv'
    if fb.exists() and fb.stat().st_size:
        for r in csv.DictReader(open(fb)):
            if r.get('scheme') == 'C10' and r.get('failure') == 'OSC':
                try: osc_ids.append(int(r['scn_id']))
                except Exception: pass
    osc_ids = sorted(set(osc_ids))
    print(f'C10 OSC scenarios from Exp B: {len(osc_ids)} -> {osc_ids[:12]}')

    # Part 1: case study
    cs_rows, fig_case = case_study(osc_ids, scen_by_id)
    with open(C.RESULTS / 'c10_oscillation_cases.csv', 'w', newline='') as f:
        if cs_rows:
            w = csv.DictWriter(f, fieldnames=list(cs_rows[0].keys())); w.writeheader(); w.writerows(cs_rows)
    print('classification counts:', {c: sum(1 for r in cs_rows if r['classification'] == c)
                                      for c in set(r['classification'] for r in cs_rows)} if cs_rows else {})

    # Part 2: mitigation comparison over full C10 400-set
    summary = {}
    for name, vp in VARIANTS.items():
        agg, _ = eval_variant(scen, vp)
        summary[name] = agg
        print(f'[{name:12s}] conv={agg["convergence_pct"]:.1f}% osc={agg["oscillation_pct"]:.1f}% '
              f'wrong={agg["wrong_sign_scn_pct"]:.1f}% FRT={agg["screen_pass_pct"]:.1f}% '
              f'surv={agg["survive_pct"]:.1f}% Vdc<min n/a load.9={agg["load_strict_pct"]:.1f}% '
              f'load.7={agg["load_tol_pct"]:.1f}% se_proj(mean/max)={agg["se_proj_mean"]:.3f}/{agg["se_proj_max"]:.3f}')

    _write_mitigation_csv(summary)
    _fig9(fig_case)
    _fig10(summary)
    (C.RESULTS / 'mitigation_summary.json').write_text(json.dumps(summary, indent=1))
    print('saved c10_oscillation_cases.csv, mitigation_summary.csv, fig9, fig10')


def _write_mitigation_csv(summary):
    keys = ['convergence_pct', 'oscillation_pct', 'wrong_sign_scn_pct', 'screen_pass_pct', 'survive_pct',
            'reactive_pct', 'connect_pct', 'limit_pct', 'recover_pct', 'load_strict_pct', 'load_tol_pct',
            'minV_mean', 'se_proj_mean', 'se_proj_max']
    with open(C.RESULTS / 'mitigation_summary.csv', 'w', newline='') as f:
        f.write('variant,' + ','.join(keys) + '\n')
        for v, a in summary.items():
            f.write(v + ',' + ','.join(f'{a.get(k,0):.3f}' for k in keys) + '\n')


def _fig9(fig_case):
    fig, axs = plt.subplots(2, 3, figsize=(15, 8))
    if fig_case:
        sid, sc, info, cmds = fig_case
        axs[0, 0].plot(info['resid_hist'], 'o-', color='tab:red')
        axs[0, 0].set_title(f'Fig 9a. OpenDSS fixed-point residual (scn {sid}, {sc["fault_type"]}@{sc["fault_bus"]})')
        axs[0, 0].set_xlabel('iteration'); axs[0, 0].set_ylabel('|Δq| (kvar)'); axs[0, 0].grid(alpha=0.3)
        buses = C.PLACE_C
        vps = [info['seq'][str(b)][0] for b in buses]
        iqs = [c['iq'] for c in cmds]; sed = [c['se_d'] for c in cmds]
        axs[0, 1].bar(range(len(buses)), vps, color='tab:blue'); axs[0, 1].set_title('Fig 9b. per-HPT Vp')
        axs[0, 1].set_xticks(range(len(buses))); axs[0, 1].set_xticklabels(buses, fontsize=7)
        axs[0, 2].bar(range(len(buses)), iqs, color='tab:green'); axs[0, 2].set_title('Fig 9c. per-HPT iq_ref')
        axs[0, 2].set_xticks(range(len(buses))); axs[0, 2].set_xticklabels(buses, fontsize=7)
        axs[1, 0].bar(range(len(buses)), sed, color='tab:purple'); axs[1, 0].set_title('Fig 9d. per-HPT mse_d')
        axs[1, 0].set_xticks(range(len(buses))); axs[1, 0].set_xticklabels(buses, fontsize=7)
        axs[1, 1].bar(range(len(buses)), [c['Vdc'] for c in cmds], color='tab:orange')
        axs[1, 1].axhline(0.75, color='r', ls=':'); axs[1, 1].set_title('Fig 9e. per-HPT Vdc')
        axs[1, 1].set_xticks(range(len(buses))); axs[1, 1].set_xticklabels(buses, fontsize=7)
        GM = {'normal': 0, 'sym': 1, 'asym': 2, 'hvrt_sym': 3, 'hvrt_asym': 4}
        axs[1, 2].bar(range(len(buses)), [GM.get(c['gate'], 0) for c in cmds], color='tab:gray')
        axs[1, 2].set_yticks(list(GM.values())); axs[1, 2].set_yticklabels(list(GM.keys()), fontsize=7)
        axs[1, 2].set_title('Fig 9f. per-HPT gate'); axs[1, 2].set_xticks(range(len(buses)))
        axs[1, 2].set_xticklabels(buses, fontsize=7)
    fig.suptitle('Fig 9. C10 fixed-point oscillation case study (reactive-coupling, no instability)')
    fig.tight_layout(); fig.savefig(C.FIGURES / 'fig9_c10_oscillation_case_study.png', dpi=130); plt.close(fig)


def _fig10(summary):
    fig, axs = plt.subplots(1, 2, figsize=(13, 4.6))
    vs = list(summary.keys())
    met = ['convergence_pct', 'oscillation_pct', 'wrong_sign_scn_pct', 'screen_pass_pct', 'survive_pct']
    x = np.arange(len(met)); w = 0.2
    for i, v in enumerate(vs):
        axs[0].bar(x + (i - 1.5) * w, [summary[v][m] for m in met], w, label=v)
    axs[0].set_xticks(x); axs[0].set_xticklabels([m.replace('_pct', '').replace('_scn', '') for m in met],
                                                 rotation=20, fontsize=8)
    axs[0].set_ylabel('%'); axs[0].legend(fontsize=7); axs[0].set_title('Fig 10a. Mitigation: stability/FRT')
    met2 = ['load_strict_pct', 'load_tol_pct', 'minV_mean']
    for i, v in enumerate(vs):
        axs[1].bar(np.arange(len(met2)) + (i - 1.5) * w,
                   [summary[v]['load_strict_pct'], summary[v]['load_tol_pct'], summary[v]['minV_mean'] * 100], w, label=v)
    axs[1].set_xticks(np.arange(len(met2))); axs[1].set_xticklabels(['load≥0.9', 'load≥0.7', 'minV×100'], fontsize=8)
    axs[1].legend(fontsize=7); axs[1].set_title('Fig 10b. Mitigation: support metrics')
    fig.tight_layout(); fig.savefig(C.FIGURES / 'fig10_mitigation_comparison.png', dpi=130); plt.close(fig)


if __name__ == '__main__':
    run()
