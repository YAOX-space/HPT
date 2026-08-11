"""pu.py — SINGLE SOURCE OF TRUTH for the per-unit system, base values, dq/power conventions, and
unit conversions shared by the device ODE, the Simulink switching model, and the OpenDSS network.

Mirror in MATLAB: lab/simulink/pu_params.m (MUST stay numerically identical — tests check this).

────────────────────────────────────────────────────────────────────────────────────────────────
CONVENTIONS (explicit, per audit 2026-06-22 §B / item 一)
────────────────────────────────────────────────────────────────────────────────────────────────
Base = SYSTEM base (S_base = 400 kVA, VLL_base = 400 Vrms). All `pu` quantities are SYSTEM-pu
unless a name says `_pe`. The power-electronics (shunt VSC) is rated S_pe = 120 kVA = 0.3 pu.

** Meaning of the reactive-current command iq (the SAC/droop action) **
  iq is in SYSTEM per-unit. iq = 0.3 pu  ==  PE full reactive output
                                         ==  120 kVAr
                                         ==  173.2 A RMS  (line current)
                                         ==  244.9 A PEAK (line current)
  -> OpenDSS  kvar = iq * S_base_kVA = iq * 400   (iq=0.3 -> 120 kvar)  [CONSISTENT]
  -> physical RMS line current = iq * I_sys_rms
  -> physical PEAK line current = iq * I_sys_peak

** dq transform = AMPLITUDE-INVARIANT (2/3 Clarke) ** -> id, iq are PEAK phase-current amplitudes,
   and power uses the 3/2 factor:  P = 1.5*(vd*id + vq*iq),  Q = 1.5*(vq*id - vd*iq).
   Therefore a MEASURED dq current (peak) must be normalised by a PEAK current base
   (I_sys_peak or I_pe_peak), NOT an RMS base. The legacy MATLAB criteria divided peak dq by
   I_pe_rms (173.2) -> a peak/RMS mix of ~sqrt(2) (audit C3). frt-v2 uses the peak base below.
"""
from __future__ import annotations
import math

# ── system base ──────────────────────────────────────────────────────────────────
S_BASE_VA   = 400e3                      # system apparent-power base (VA)
VLL_BASE    = 400.0                      # LV line-line voltage base (V rms)
VLN_RMS     = VLL_BASE / math.sqrt(3)    # line-neutral rms (V)
VLN_PEAK    = math.sqrt(2) * VLN_RMS     # line-neutral peak (V)
F_NOM       = 50.0                       # Hz

I_SYS_RMS   = S_BASE_VA / (math.sqrt(3) * VLL_BASE)   # 577.35 A
I_SYS_PEAK  = math.sqrt(2) * I_SYS_RMS                # 816.50 A

# ── power-electronics (shunt VSC) rating ───────────────────────────────────────────
S_PE_VA     = 120e3                      # 120 kVA
S_PE_PU     = S_PE_VA / S_BASE_VA        # 0.30 pu (system)
I_PE_RMS    = S_PE_VA / (math.sqrt(3) * VLL_BASE)     # 173.21 A
I_PE_PEAK   = math.sqrt(2) * I_PE_RMS                 # 244.95 A

# ── action / criterion limits (SYSTEM-pu) ──────────────────────────────────────────
IQ_PE_LIMIT_PU = S_PE_PU                 # 0.30 pu = PE full reactive (droop saturation)
I_CONV_MAX_PU  = 0.35                    # total converter current limit (limit criterion line)
                                         #   = 0.35*I_sys_peak peak / 0.35*I_sys_rms rms

# ── current-base redesign (audit item 6): THREE DISTINCT roles, NEVER conflated ─────
# The legacy HLC used Imax = I_pe_rms (173.2) as BOTH the action scale AND the converter clip —
# wrong on two counts (rms vs peak; PE-rating vs action scale). Separate them:
I_ACTION_PEAK    = I_SYS_PEAK            # (1) ACTION current SCALE: iq_pu -> peak amps.  816.50 A
I_CONVERTER_PEAK = I_PE_PEAK            # (2) PHYSICAL PE converter PEAK limit (clip |I| here). 244.95 A
#                  (3) system-pu PE limit = S_PE_PU = 0.30.
# Required identity (verified in self_check + pu_selfcheck.m):
#   iq = 0.30 system-pu  ->  command = 0.30 * I_ACTION_PEAK = 244.95 A peak = I_CONVERTER_PEAK = I_pe_peak
#                        ->  120 kVAr.  The current controller clips the COMBINED vector to
#   I_CONVERTER_PEAK; it must NOT apply a second 0.3 to an already-PE-scaled current.

METRICS_VERSION = 'frt-v2'               # bump whenever a criterion definition changes


# ── conversions (named so a reader cannot mix bases) ───────────────────────────────
def iq_pu_to_kvar(iq_pu: float) -> float:
    """SYSTEM-pu reactive current -> kvar (capacitive +). iq=0.3 -> 120.0."""
    return iq_pu * (S_BASE_VA / 1e3)


def iq_pu_to_rms_amp(iq_pu: float) -> float:
    """SYSTEM-pu -> physical RMS line current (A). iq=0.3 -> 173.2."""
    return iq_pu * I_SYS_RMS


def iq_pu_to_peak_amp(iq_pu: float) -> float:
    """SYSTEM-pu -> physical PEAK line current (A). iq=0.3 -> 244.9."""
    return iq_pu * I_SYS_PEAK


def peak_amp_to_pu(i_peak: float) -> float:
    """Measured PEAK current (A, amplitude-invariant dq) -> SYSTEM-pu. Use for limit criterion."""
    return i_peak / I_SYS_PEAK


def action_iq_to_command_amp(iq_pu: float) -> float:
    """Actor reactive command (SYSTEM-pu) -> PEAK line-current command (A). Scale = I_ACTION_PEAK.
    iq=0.3 -> 244.95 A peak (= I_CONVERTER_PEAK = I_pe_peak). The ONLY action->amp scaling; there is
    no second 0.3 multiply downstream."""
    return iq_pu * I_ACTION_PEAK


def clip_converter_current(id_peak_a: float, iq_peak_a: float):
    """Clip the COMBINED dq current vector (peak amps) to the PE converter peak limit
    (I_CONVERTER_PEAK), preserving direction. Returns (id, iq). The current controller uses THIS as
    the physical limit — it must not multiply an already-PE-scaled current by another 0.3."""
    mag = math.hypot(id_peak_a, iq_peak_a)
    if mag <= I_CONVERTER_PEAK or mag == 0.0:
        return id_peak_a, iq_peak_a
    s = I_CONVERTER_PEAK / mag
    return id_peak_a * s, iq_peak_a * s


def rms_amp_to_pu(i_rms: float) -> float:
    """Measured RMS current (A) -> SYSTEM-pu."""
    return i_rms / I_SYS_RMS


# ── amplitude-invariant Clarke/Park + power (the ONE definition everyone uses) ──────
def clarke(a, b, c):
    """Amplitude-invariant (2/3) Clarke. alpha/beta keep the phase peak amplitude."""
    alpha = (2.0 / 3.0) * (a - 0.5 * b - 0.5 * c)
    beta = (2.0 / 3.0) * (math.sqrt(3) / 2.0) * (b - c)
    return alpha, beta


def park(alpha, beta, theta):
    """alpha/beta -> d/q at angle theta (d aligned with the rotating reference)."""
    d = alpha * math.cos(theta) + beta * math.sin(theta)
    q = -alpha * math.sin(theta) + beta * math.cos(theta)
    return d, q


def dq_power(vd, vq, id_, iq):
    """Three-phase active/reactive power from dq (amplitude-invariant -> 3/2 factor)."""
    P = 1.5 * (vd * id_ + vq * iq)
    Q = 1.5 * (vq * id_ - vd * iq)
    return P, Q


def self_check(verbose=True):
    """Verify the power formula on a synthetic balanced 3-phase set and the headline identity
    iq=0.3 pu -> 120 kvar -> 173.2 A rms. Returns dict of checks (all should be ~0 error)."""
    import numpy as np
    w = 2 * math.pi * F_NOM
    t = np.linspace(0, 0.02, 2001)
    # balanced voltages at VLN_PEAK, currents at I_PE_PEAK lagging 90° (pure reactive, inductive)
    Vp, Ip = VLN_PEAK, I_PE_PEAK
    va, vb, vc = Vp*np.cos(w*t), Vp*np.cos(w*t-2*math.pi/3), Vp*np.cos(w*t+2*math.pi/3)
    ia, ib, ic = (Ip*np.cos(w*t-math.pi/2), Ip*np.cos(w*t-2*math.pi/3-math.pi/2),
                  Ip*np.cos(w*t+2*math.pi/3-math.pi/2))
    # instantaneous power should equal the analytic 3-phase Q for a balanced reactive load
    P_inst = va*ia + vb*ib + vc*ic
    Q_analytic = 3 * VLN_RMS * I_PE_RMS                      # = 3*231*173.2 = 120 kVAr
    # dq at theta=w*t with d aligned to V: vd=Vp, vq=0; iq should be -Ip (inductive)
    th = w*t[1000]
    al_v, be_v = clarke(va[1000], vb[1000], vc[1000]); vd, vq = park(al_v, be_v, th)
    al_i, be_i = clarke(ia[1000], ib[1000], ic[1000]); idd, iqq = park(al_i, be_i, th)
    P_dq, Q_dq = dq_power(vd, vq, idd, iqq)
    checks = {
        'iq0.3_to_kvar': abs(iq_pu_to_kvar(0.3) - 120.0),
        'iq0.3_to_rms_A': abs(iq_pu_to_rms_amp(0.3) - I_PE_RMS),
        'Q_analytic_kVAr': abs(Q_analytic/1e3 - 120.0),
        'P_inst_mean_W': abs(float(np.mean(P_inst))),                 # ~0 (pure reactive)
        'Q_dq_vs_analytic_kVAr': abs(abs(Q_dq)/1e3 - 120.0),         # dq power == 120 kVAr
        'vd_eq_VLNpeak': abs(vd - VLN_PEAK),
        'peak_amp_roundtrip': abs(peak_amp_to_pu(iq_pu_to_peak_amp(0.3)) - 0.3),
        # ── current-base redesign end-to-end round trip (item 6) ──
        'action_iq0.3_eq_I_pe_peak': abs(action_iq_to_command_amp(0.3) - I_PE_PEAK),     # 244.95 A
        'action_iq0.3_roundtrip_kVAr': abs(iq_pu_to_kvar(peak_amp_to_pu(
                                            action_iq_to_command_amp(0.3))) - 120.0),     # ->120 kVAr
        'converter_clip_caps_at_pe_peak': abs(math.hypot(*clip_converter_current(300.0, 300.0))
                                              - I_PE_PEAK),                               # clip to 244.95
        'converter_clip_passes_small': abs(math.hypot(*clip_converter_current(100.0, 50.0))
                                          - math.hypot(100.0, 50.0)),                     # below limit: unchanged
    }
    if verbose:
        print('pu.self_check (all errors should be ~0):')
        for k, v in checks.items():
            print(f'  {k:26s} err={v:.4g}')
        print(f'  I_sys_rms={I_SYS_RMS:.2f}A I_sys_peak={I_SYS_PEAK:.2f}A '
              f'I_pe_rms={I_PE_RMS:.2f}A I_pe_peak={I_PE_PEAK:.2f}A')
    return checks


if __name__ == '__main__':
    self_check()
