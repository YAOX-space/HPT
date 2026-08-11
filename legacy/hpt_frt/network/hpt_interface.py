"""hpt_interface.py — HPT device wrapper that couples a Mode-5 controller to the OpenDSS network.

Each HPT is a 400 kVA device at its MV bus. The interface (section 六):
  1-2. local three-phase voltage -> (Vp, Vn)               [sequence.py, done by the runner]
  3-5. build obs -> gated SAC actor -> action -> clip       [sac_wrapper.HPTController]
  6.   device DC surrogate updates Vdc                       [sac_wrapper / config.vdc_eq]
  7.   iq_ref -> equivalent reactive injection (kvar)        [iq_to_kvar]
  8.   series mse_d/mse_q -> LV-side compensated voltage     [lv_compensated]
  9.   record Vp,Vn,Vdc,iq,se_d,se_q,gate,clip,criteria

The OpenDSS equivalent injection of the shunt VSC is a controllable reactive source (Generator,
kw≈0, kvar=iq·kVA): undervoltage -> capacitive (kvar>0). The series VSC does NOT inject into the
MV network (it compensates the device's own LV load); its effect is the LV-side ride-through.
"""
from __future__ import annotations
import numpy as np
from . import config as C
from .sac_wrapper import HPTController


def iq_to_kvar(iq_pu):
    """SYSTEM-pu reactive-current command -> OpenDSS Generator kvar (capacitive +). Single source =
    pu.iq_pu_to_kvar (iq=0.3 -> 120 kvar = PE full). See audit 一 / common/pu.py."""
    return C.PU.iq_pu_to_kvar(float(iq_pu))


def lv_compensated(Vp, se_d):
    """LV-side positive-seq voltage after series compensation (se_d>0 = boost). Phase-1 SE_GAIN."""
    if Vp < 0.9:
        return float(min(1.10, Vp + C.SE_GAIN * max(0.0, se_d)))
    return float(Vp)


class HPT:
    """A single HPT device: controller + injection state + per-scenario trajectory log."""

    def __init__(self, bus, use_hysteresis=True, **ctrl_kw):
        self.bus = bus
        self.ctrl = HPTController(bus, use_hysteresis=use_hysteresis, **ctrl_kw)
        self.reset()

    def reset(self):
        self.ctrl.reset()
        self.kvar = 0.0
        self.log = []          # list of per-step dicts

    # ── steady (held-sag) command for the network fixed point ────────────────────
    def steady(self, Vp, Vn, fault_type=None):
        c = self.ctrl.steady_command(Vp, Vn, fault_type)
        self.kvar = iq_to_kvar(c['iq'])
        return c

    # ── one time-domain snapshot (gate chattering / recovery experiments) ─────────
    def step(self, Vp, Vn, t, in_fault, dt=C.DT_SNAP):
        c = self.ctrl.step(Vp, Vn, t, in_fault, dt=dt)
        self.kvar = iq_to_kvar(c['iq'])
        rec = dict(t=t, Vp=Vp, Vn=Vn, in_fault=int(in_fault),
                   v_load=lv_compensated(Vp, c['se_d']), **c)
        self.log.append(rec)
        return c

    # ── trajectory reductions for the FRT criteria (metrics.py consumes these) ────
    def trajectory(self):
        if not self.log:
            return None
        L = self.log
        fault = [r for r in L if r['in_fault']]
        post = [r for r in L if not r['in_fault'] and r['t'] > (fault[-1]['t'] if fault else 0)]
        vdc = np.array([r['Vdc'] for r in L])
        iqs = np.array([r['iq'] for r in L])
        ses = np.array([abs(r['se_d']) for r in L])
        return dict(
            bus=self.bus,
            Vp_min=float(min(r['Vp'] for r in (fault or L))),
            Vn_max=float(max(r['Vn'] for r in L)),
            Vdc_min=float(vdc.min()), Vdc_max=float(vdc.max()),
            iq_max=float(np.abs(iqs).max()), se_max=float(ses.max()),
            v_load_min=float(min(r['v_load'] for r in (fault or L))),
            iq_fault_mean=float(np.mean([r['iq'] for r in fault])) if fault else 0.0,
            iqref_fault_mean=float(np.mean([r['iq_ref'] for r in fault])) if fault else 0.0,
            v_post=float(np.mean([r['Vp'] for r in post[-3:]])) if post else None,
            iq_post=float(np.mean([abs(r['iq']) for r in post[-3:]])) if post else None,
            any_clipped=bool(any(r['clipped'] for r in L)),
            wrong_sign=bool(any(r['in_fault'] and r['Vp'] < 0.9 and r['iq'] < -1e-3 for r in L)),
            gate=self.ctrl.gate_stats(),
            log=L,
        )
