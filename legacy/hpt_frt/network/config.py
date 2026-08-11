"""config.py — single source of truth for the Phase-2 network-robustness stress test.

This experiment is a SYSTEM-LEVEL ROBUSTNESS STRESS TEST (相量层/策略级), NOT system-level MARL
training. We embed the ALREADY-TRAINED single-device SAC-HPT controller (Mode 5: online-gated
multi-expert SAC, the paper's MAIN METHOD, pure SAC) into the IEEE 33-bus feeder and ask whether
it still produces sane commands under network-induced OOD sags, multi-HPT coupling and slow
recovery. See report.md.

Controller = canonical Mode 5 (CONTROL_MODES.md): 4 specialist SAC experts
{sym, asym, hvrt_sym, hvrt_asym} routed by an ONLINE sequence-component gate on measured (V2p,V2n)
— NO oracle, NO central coordinator, each HPT uses only its own local measurements.

All electrical quantities at the device are per-unit (1.0 = nominal terminal voltage / rated kVA).
The OpenDSS layer is a QUASI-STATIC PHASOR twin: it sees network power flow, fault propagation and
sag depth, but NOT PWM / IGBT / fast Vdc ripple. Switching-level dynamics are the L1 Simulink
spot-check (export_simulink_cases.py), which is a SAMPLE audit, not run for all scenarios.
"""
from __future__ import annotations
from pathlib import Path
from ..common import pu as PU                     # SINGLE SOURCE OF TRUTH for base values

# ── paths ─────────────────────────────────────────────────────────────────────
HERE      = Path(__file__).resolve().parent     # src/hpt_frt/network
REPO      = HERE.parents[2]                      # repo root (network -> hpt_frt -> src -> repo)
DSS_FILE  = HERE / 'ieee33.dss'                 # local copy of the validated feeder
MODELS    = REPO / 'data' / 'models'            # sac_{sym,asym,hvrt_sym,hvrt_asym}_best.zip
RESULTS   = HERE / 'results'
FIGURES   = RESULTS / 'figures'
TS_DIR    = RESULTS / 'per_hpt_timeseries'
for _d in (RESULTS, FIGURES, TS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── reproducibility ────────────────────────────────────────────────────────────
SEED = 20260621

# ── IEEE 33 / device ratings ────────────────────────────────────────────────────
BASE_KV    = 12.66
HPT_KVA    = PU.S_BASE_VA / 1e3       # 400.0 — derived from pu single-source (audit 一)
# canonical self-check anchors of ieee33.dss (Baran&Wu): min V 0.9038 @ bus18, losses 210.98 kW
# (reference values for the base-case sanity check; verified in report §1)

# ── HPT placement schemes (section 四) ──────────────────────────────────────────
PLACE_A = [7, 14, 25, 30]            # scheme A: single HPT, one at a time (electrical-position OOD)
PLACE_B = [7, 14, 25, 30]            # scheme B: 4 independent HPTs
PLACE_C = [4, 7, 10, 14, 17, 21, 24, 28, 31, 33]   # scheme C: 10 dense HPTs (stronger coupling)

# ── PV plants (penetration sweep) ───────────────────────────────────────────────
PV_BUSES   = [6, 11, 16, 20, 24, 30, 32]
PV_KW_BASE = 250.0                   # per-plant kW at penetration = 1.0

# ── DEPLOYMENT-SIDE action caps (section 六.5) ──────────────────────────────────
# mirror frt_env / residual_env deployment clips. Asym cap is tighter because measured 2ω peak
# ≈ cmd × k_2ω (k≈1.3-1.4): a sustained 0.27 cmd broke the 0.35 measured-peak limit on 1ph_g.
IQ_CAP        = 0.27                  # symmetric reactive-current command cap (pu)
IQ_CAP_ASYM   = 0.24                  # tighter cap on asymmetric faults (V2n>0.05 & undervoltage)
SE_MAX        = 0.20                  # series d/q injection cap (pu)
I_CONV_MAX    = PU.I_CONV_MAX_PU      # 0.35 — total shunt converter current limit (limit criterion line)
I_Q_MAX       = PU.IQ_PE_LIMIT_PU     # 0.30 — GB/T reactive droop saturation (= PE full, 120 kvar)
ASYM_FT       = ('1ph_g', '2ph', '2ph_g')

# ── device surrogate (phase-1 faithful-ODE constants, Simulink-calibrated ≤0.022) ──
# se_d > 0 == BOOST (same convention as frt_env / mpc_prior). Vdc_eq is the equilibrium the bus
# relaxes toward over the fault window with first-order time-constant DC_TAU.
SE_GAIN   = 0.47                      # series-injection → LV voltage effectiveness
K_Q_BASE  = 0.22                      # reactive → terminal-voltage gain (scaled by 1/SCR)
DC_TAU    = 0.0035 / 0.195            # effective Vdc relaxation time-constant (s)
VDC_CHOP  = 1.20                      # chopper clamp
VDC_FLOOR = 0.05

def vdc_eq(iq, se_d, se_q, v_local):
    """Phase-1 calibrated DC-bus equilibrium. se_d>0 = boost (DC drain). Re-verified vs Simulink
    (≤0.022, calibration_reverify_2026-06-17). |iq| reactive-headroom cost is mild; series boost
    dominates (≈1.9×); |se_q| mild."""
    return 1.0 - 0.08 * abs(iq) / max(0.3, v_local) - 1.9 * max(0.0, se_d) - 0.5 * abs(se_q)

# ── online gate (section 五) ─────────────────────────────────────────────────────
GATE_V2N_THR   = 0.05                 # negative-seq threshold: sym vs asym
GATE_LV_THR    = 0.90                 # V2p below → LVRT region
GATE_HV_THR    = 1.060                # V2p above → HVRT region
# hysteresis (chattering mitigation, for analysis): widen the V2n band + require dwell
GATE_V2N_HYST  = 0.02                 # ±band around GATE_V2N_THR
GATE_DWELL     = 2                    # min consecutive snapshots before a gate switch commits

# ── FRT criteria thresholds (section 八, FRT_SPEC §1 五条判据) ────────────────────
VDC_MIN_OK   = 0.75                   # survive: Vdc_min ≥ 0.75
VDC_MAX_OK   = 1.25                   # survive: Vdc_max ≤ 1.25
RECOVER_BAND = 0.07                   # recover: post-fault V within 1 ± 0.07 pu
REACTIVE_TOL = 0.12                   # reactive: |iq - iq_ref| ≤ 0.12
LIMIT_PU     = 0.35                   # limit: iq command/peak ≤ 0.35 pu
LOAD_STRICT  = 0.90                   # system load ride-through (strict)
LOAD_TOL     = 0.70                   # system load ride-through (tolerant)

# ── fixed-point coupling loop (section 七) ──────────────────────────────────────
FP_MAX_ITERS = 20
FP_Q_TOL     = 2.0                    # reactive-injection change tolerance (kvar)
FP_DAMP      = 0.5                    # damped update q = (1-d)*q_old + d*q_new

# ── time-domain sequence (section 五.6/七, slow recovery) ────────────────────────
DT_SNAP      = 0.02                   # snapshot step for time-series experiments (s)
T_PRE        = 0.10                   # pre-fault settle (s)
def duration_rule(min_v):
    """GB/T-envelope-coupled clearing time (s): deeper sag → faster protection."""
    if min_v < 0.20: return 0.15
    if min_v < 0.50: return 0.30
    return 0.625
