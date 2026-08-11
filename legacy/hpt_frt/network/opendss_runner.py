"""opendss_runner.py — L3 network layer + L2 OpenDSS<->HPT coupling loop (sections 三 & 七).

OpenDSS is the quasi-static phasor twin: power flow, fault injection by type/resistance, sag
propagation, slow recovery. The coupling loop (section 七) iterates solve -> read local (Vp,Vn) ->
each HPT's gated SAC produces a steady command -> reactive injection written back -> resolve, until
the fixed point (|Δq|<tol) or FP_MAX_ITERS; convergence / oscillation / wrong-sign are recorded.

Faults (genuine sequence imbalance so V2n>0 on asymmetric types):
  sym3ph : 3-phase           New Fault bus1=B phases=3
  1ph_g  : SLG (a-g)         New Fault bus1=B.1 phases=1
  2ph    : LL  (b-c)         New Fault bus1=B.2 bus2=B.3 phases=1
  2ph_g  : LLG (b-c-g)      common-point 2-phase-to-ground
"""
from __future__ import annotations
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import numpy as np
import opendssdirect as dss
from . import config as C
from . import sequence as SQ


def _fault_cmds(bus, ftype, r):
    b = int(bus)
    if ftype == 'sym3ph':
        return [f'New Fault.f1 bus1={b} phases=3 r={r:.4f}']
    if ftype == '1ph_g':
        return [f'New Fault.f1 bus1={b}.1 phases=1 r={r:.4f}']
    if ftype == '2ph':
        return [f'New Fault.f1 bus1={b}.2 bus2={b}.3 phases=1 r={r:.4f}']
    if ftype == '2ph_g':
        # LLG (b-c-g) at a COMMON fault point (audit M4): one Fault object connecting phases 2,3 to
        # ground through r each — NOT two independent SLG faults (which mis-represents the coupling).
        return [f'New Fault.f1 bus1={b}.2.3 bus2={b}.0.0 phases=2 r={r:.4f}']
    raise ValueError(ftype)


def build_network(sc, hpt_buses, q_kvar, fault=True, source_pu=1.0):
    """Compile the feeder, set load/PV, place HPTs (kvar injections), apply fault (or recovery
    source depression), solve. Returns dict with per-HPT (Vp,Vn), feeder minV, all-bus means."""
    dss.Text.Command(f'compile "{C.DSS_FILE}"')
    dss.Text.Command(f'set loadmult={sc["load_lvl"]}')
    if abs(source_pu - 1.0) > 1e-6:
        dss.Text.Command(f'Edit Vsource.source pu={source_pu:.5f}')
    for b in C.PV_BUSES:
        kw = C.PV_KW_BASE * sc['pv_pen']
        if kw > 0:
            dss.Text.Command(f'New Generator.pv{b} bus1={b} phases=3 kv={C.BASE_KV} '
                             f'kw={kw:.1f} pf=1 model=1 vminpu=0.05 vmaxpu=1.5')
    for i, b in enumerate(hpt_buses):
        dss.Text.Command(f'New Generator.hpt{b} bus1={b} phases=3 kv={C.BASE_KV} kw=0.001 '
                         f'kvar={q_kvar[i]:.3f} model=1 vminpu=0.05 vmaxpu=1.5')
    if fault:
        for cmd in _fault_cmds(sc['fault_bus'], sc['fault_type'], sc['r_fault']):
            dss.Text.Command(cmd)
    dss.Text.Command('set mode=snapshot')
    dss.Solution.Solve()
    if not dss.Solution.Converged():
        return None
    out = {'converged': True}
    seqs = {}
    for b in hpt_buses:
        Vp, Vn, _ = SQ.seq_components(b)
        seqs[str(b)] = (Vp, Vn)
    out['seq'] = seqs
    out['minV'] = SQ.network_min_v()
    out['all_mean'] = {b: SQ.mean_vmag(b) for b in dss.Circuit.AllBusNames()}
    return out


def solve_fixed_point(sc, hpts, fault=True, source_pu=1.0, slew_kvar=None, max_iters=None):
    """Section 七 coupling loop: damped fixed point of (network <-> independent HPT controllers).

    hpts: list of hpt_interface.HPT. Returns (per-HPT steady command dict, info). Each HPT resets
    its device state inside steady() so the map q=f(V) is a clean function -> well-posed fixed
    point. Records convergence, residual history, oscillation, wrong-sign."""
    buses = [h.bus for h in hpts]
    q = np.zeros(len(hpts))
    resid_hist, last_v = [], None
    converged = False
    for _ in range(max_iters or C.FP_MAX_ITERS):
        net = build_network(sc, buses, list(q), fault=fault, source_pu=source_pu)
        if net is None:
            return None, dict(converged=False, nonconverged=True, resid_hist=resid_hist)
        last_v = net
        cmds = []
        for i, h in enumerate(hpts):
            Vp, Vn = net['seq'][str(h.bus)]
            cmds.append(h.steady(Vp, Vn, sc['fault_type']))
        q_new = np.array([h.kvar for h in hpts])
        if slew_kvar is not None:                          # deployment slew: cap |Δq| per iteration
            q_new = q + np.clip(q_new - q, -slew_kvar, slew_kvar)
        resid = float(np.max(np.abs(q_new - q))) if len(q) else 0.0
        resid_hist.append(resid)
        if resid < C.FP_Q_TOL:
            q = q_new; converged = True
            net = build_network(sc, buses, list(q), fault=fault, source_pu=source_pu)
            last_v = net
            for i, h in enumerate(hpts):       # final consistent commands
                Vp, Vn = net['seq'][str(h.bus)]
                cmds[i] = h.steady(Vp, Vn, sc['fault_type'])
            break
        q = (1 - C.FP_DAMP) * q + C.FP_DAMP * q_new
    # oscillation: residual not (near-)monotonically decreasing in the tail
    osc = False
    if len(resid_hist) >= 4 and not converged:
        tail = resid_hist[-4:]
        osc = any(tail[i + 1] > tail[i] + 1e-6 for i in range(len(tail) - 1))
    wrong = 0
    for i, h in enumerate(hpts):
        Vp, Vn = last_v['seq'][str(h.bus)]
        if Vp < 0.9 and cmds[i]['iq'] < -1e-3:
            wrong += 1
    info = dict(converged=bool(converged), nonconverged=False, iters=len(resid_hist),
                resid_final=resid_hist[-1] if resid_hist else 0.0, resid_hist=resid_hist,
                oscillation=bool(osc), wrong_sign=int(wrong),
                minV=last_v['minV'], all_mean=last_v['all_mean'], seq=last_v['seq'])
    return cmds, info


def simulate(sc, hpts, recovery='instant', t_recover=0.6, kind='exp', extra_post=0.4, dt=None):
    """Time-domain quasi-static sequence (sections 七 & 五.6): pre -> fault -> clear -> (slow)recovery.

    Each snapshot solves the network with the PREVIOUS step's injections (lagged explicit coupling),
    reads local (Vp,Vn), and steps every HPT's stateful controller (Vdc dynamics + gate history
    preserved across steps -> exposes gate chattering and recovery transients). `recovery`:
      'instant' : source restored to 1.0 immediately at clearing (Exp B representative series);
      'slow'    : substation source pu ramps v_fault_p -> 1.0 over t_recover (Exp C FIDVR-like).
    Returns per-HPT trajectories (HPT.trajectory()) + sequence info."""
    dt = dt or C.DT_SNAP
    for h in hpts:
        h.reset()
    buses = [h.bus for h in hpts]
    # determine global fault depth (no HPT) to set duration + recovery start level
    pre = build_network(sc, buses, [0.0] * len(hpts), fault=True)
    minV = pre['minV'] if pre else 0.0
    dur = C.duration_rule(minV)
    v_fault_p = max(0.2, min(0.95, minV))                    # recovery starts from depressed level
    t_clear = C.T_PRE + dur
    t_end = t_clear + (t_recover + extra_post if recovery == 'slow' else extra_post)
    grid = np.arange(0.0, t_end + 1e-9, dt)
    q = np.zeros(len(hpts))
    nonconv = 0
    for t in grid:
        if t < C.T_PRE:
            fault, src = False, 1.0
        elif t < t_clear:
            fault, src = True, 1.0
        else:                                                # cleared
            fault = False
            src = (SQ.recovery_curve(t, t_clear, t_recover, v_fault_p, kind=kind)
                   if recovery == 'slow' else 1.0)
        net = build_network(sc, buses, list(q), fault=fault, source_pu=src)
        if net is None:
            nonconv += 1
            continue
        for i, h in enumerate(hpts):
            Vp, Vn = net['seq'][str(h.bus)]
            h.step(Vp, Vn, float(t), in_fault=fault, dt=dt)
        q = np.array([h.kvar for h in hpts])
    return dict(dur=dur, minV=minV, t_clear=t_clear, t_end=float(t_end), nonconv=nonconv,
                trajectories=[h.trajectory() for h in hpts])


def sag_at_buses(sc, buses):
    """No-HPT sag depth (Vp) at the given buses under the scenario fault (for the heatmap)."""
    net = build_network(sc, [], [], fault=True)
    if net is None:
        return None
    out = {}
    for b in buses:
        Vp, Vn, _ = SQ.seq_components(b)
        out[b] = (Vp, Vn)
    return out
