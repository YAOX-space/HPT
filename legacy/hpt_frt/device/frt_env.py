"""
frt_env.py — upgraded averaged-ODE training environment for STANDARD FRT (FRT_SPEC.md).

Differences vs ai/hpt_direct_env.py (the old single-sequence env):
  + positive AND negative sequence terminal voltage (true asymmetric faults)
  + reactive-priority current injection (shunt i_sh_q -> grid voltage support, ≤0.3 pu PE cap)
  + current limiting (reactive priority, active curtailed under the limit)
  + GB/T voltage-time ride-through envelope -> "stay-connected" criterion
  + 4-D action [i_sh_d, i_sh_q, m_se_d, m_se_q]; ~22-D observation

ACTION INTERFACE: nominally 4-D but EFFECTIVE 3-D = [i_q, m_se_d, m_se_q]. Action dim 0 (i_sh_d)
is a VESTIGIAL dim: it only enters the current-limit penalty, never the dynamics, and is discarded
at deployment (i_d is set by the Vdc outer loop). This env trains the SAC experts for canonical
Mode 3 (unified SAC, internal mi==11) and Mode 5 (online-gated multi-expert SAC = MAIN METHOD,
internal mi==12), and the Oracle-gated ablation Mode 4. A 3-D-action retrain (drop the vestigial
dim) is 待验证 (pending) — see CONTROL_MODES.md §5. Canonical naming per CONTROL_MODES.md.

ALL quantities in per-unit (1.0 = nominal terminal voltage / rated current).
This is a TRAINING SURROGATE (fast, approximate); Simulink remains the authority.

Time: a TSCALE factor compresses the GB/T seconds-scale curve so training episodes
stay short (the policy is scale-invariant for the relative criteria; absolute-time
fidelity is a Simulink-validation concern, see FRT_SPEC §"时间尺度").
"""
from __future__ import annotations
import math
import numpy as np
import gymnasium as gym
from gymnasium import spaces
from hpt_frt.common import frt_v2 as FV2

# ── per-unit constants ──────────────────────────────────────────────────────────
VDC_NOM   = 1.0                 # DC bus pu (nominal)
I_Q_MAX   = 0.30                # reactive current cap (PE 120 kVA ≈ 0.3 pu) [FRT_SPEC §2] (criterion/droop def)
I_Q_ACT   = 0.27                # ACTION bound for iq (< I_Q_MAX): leave transient headroom so measured
                                # peaks stay ≤0.35 in Simulink (limit criterion); fix for limit=58.3%
I_CONV_MAX= 0.35                # total shunt converter current limit, pu (reactive priority)
V_SE_MAX  = 0.20                # series injection ±20% [task book / Shang]
# NOTE: the damping-resistor bleeder (78 kW @ 800 V) is folded into the Simulink-calibrated
# static Vdc_eq map below — there is no standalone P_load coefficient in the faithful-ODE
# dynamics. (A former `K_DC` constant was unused dead code and has been removed, 2026-06-17.)
DC_TAU    = 2 * 704.0 / 400e3   # DC capacitor time const = 2·E_dc/P_base ≈ 3.5 ms
TAU_V2    = 0.010              # terminal-voltage first-order lag (s)
# ── Simulink-calibrated effectiveness gains (2026-06-09) ──────────────────────────
# Measured on hpt_frt_full.slx: shunt reactive iq=0.30pu → LV +2.2% at SCR=3
#   ⇒ K_q ≈ 0.073 at SCR=3, i.e. K_Q_BASE = 0.073·3 ≈ 0.22 (was 1.0 = ~4.5× too optimistic).
# Series m_se_d=0.10 → LV +4.7% ⇒ effective gain ≈ 0.47 (was 1.0 = ~2× too optimistic).
# This closes the ODE→Simulink optimism gap so the policy learns realistic actuator authority.
K_Q_BASE  = 0.22             # reactive→voltage gain (Simulink-calibrated; was 1.0 = ~4.5× optimistic)
SE_GAIN   = 0.47             # series-injection voltage effectiveness (Simulink-calibrated; was 1.0)
# ── DC bus faithfulness (2026-06-10): shunt active current is NOT a free Vdc lever (a[0] discarded
# in Simulink); it is auto-regulated by a Vdc PI loop but CAPPED by reactive-priority headroom AND
# the depressed grid voltage during the fault → single-port "starvation" (Vdc must sag on deep faults).
KP_VDC    = 0.6              # Vdc-restore PI demand gain (pu power per pu Vdc error)
SE_DRAIN  = 1.0              # series H-bridge DC-drain coefficient (P_se = SE_DRAIN·|V_se|)
VDC_CHOP  = 1.20             # chopper clamp (matches Simulink Vdc>1.20 bleeder)
# ── HVRT swell DC-undershoot model (Stage A switching calibration 2026-06-27, lab/results/
# dc_sweep_grid_s3ph.mat, 60 open-loop points, fit R²≈0.91 / RMSE 0.05). During over-voltage the
# CONVERTER (not the swell itself) drains the DC bus: reactive ABSORPTION drains it, +series compounds,
# and ANTI-BOOST (V_se_d<0) protects it — the absorb×series cross term dominates. The LVRT-calibrated
# sag terms are BLIND here (predict Vdc≈0.98); this map replaces them in the swell regime so the ODE
# can SEE the swell_3ph survive failure. Conservative: tracks the switching Vdc_min (worst-case).
SW_C0, SW_AB, SW_SE, SW_X, SW_DEP = 0.839, 0.583, 0.371, 4.028, 0.152
# HVRT clearing/release undershoot (2026-07-07 ODE-blind fix): switching mi=14 fails the weak-grid
# swell_3ph survive criterion after clearing (Vdc≈0.72), while the ODE recovered to ≈0.95. Model the
# missing release transient as a short post-clear DC sink proportional to the peak absorption during
# the preceding swell. This is intentionally narrow: category=HVRT, immediately after fault clearing.
HVRT_CLEAR_DROP = 2.25
HVRT_CLEAR_TAU  = 0.010
HVRT_CLEAR_WIN  = 0.030
# Stiff-grid balanced LVRT DC-link starvation (2026-07-07 ODE-blind fix): switching showed
# sym3ph/SCR=10 deep and mid faults can under-shoot Vdc even with little series boost. That is the
# current-limited active-power deficit during a low terminal voltage, which the previous averaged
# map missed because it was calibrated mostly on SCR=3 series-boost sweeps. Keep this narrow so
# shallow sym3ph and weak-grid cases are not over-penalised.
LVRT_STIFF_SCR0 = 8.0
LVRT_STIFF_VG_MAX = 0.55
LVRT_STIFF_DC_DROP = 0.33
# Expanded-grid impedance-shape correction (2026-07-09): selected Simulink spotchecks showed that
# cases with the same SCR but lower Rg / higher X component have materially worse DC survival and
# post-clear recovery. The old ODE used only SCR, so these cases stayed ODE-invisible. The scenario
# generator's maximum-R branch follows Rg_base ~= 138.675 / SCR; the factor below is 0 on that branch
# and grows as the same-SCR grid becomes more inductive.
GRID_R_BASE_AT_SCR1 = 138.675
LVRT_XR_DC_DROP = 0.08
LVRT_RECOVERY_BIAS0 = 0.045
LVRT_RECOVERY_XR_BIAS = 0.060
# Weak-grid deep asymmetric LVRT DC-link deficit (2026-07-12): switching full320 shows 2ph/2ph_g,
# SCR=3,target=0.2 can fail Vdc survive even without strong series boost. The averaged ODE was
# optimistic by roughly 0.10 pu because it lacks negative-sequence ripple/current-limiter coupling.
LVRT_WEAK_ASYM_DC_DROP = 0.12
LVRT_WEAK_ASYM_LONG_DC_DROP = 0.09
LVRT_WEAK_ASYM_LONG_DUR = 0.35
# Single-phase HVRT sequence/measurement correction (2026-07-07 ODE-blind fix): unbalanced swell
# has positive/negative-sequence coupling and PLL/current-measurement ripple. Switching saw
# swell_1ph/SCR=3 wrong-sign reactive failures near the 1.1-pu boundary; the ODE was too smooth
# (V+ stayed just below 1.1 and measured iq kept the command sign). These terms are only active for
# swell_1ph and are proportional to V2n.
HVRT_ASYM_V1_BIAS = 0.35
HVRT_ASYM_IQ_MEAS_BIAS = 0.70
HVRT_ASYM_SCR_MAX = 4.0
HVRT_RECOVERY_WEAK_UNDER = 0.125
HVRT_RECOVERY_XR_OVER = 0.130
HVRT_SHALLOW_SCR2_EXTRA_UNDER = 0.033
HVRT_1PH_RECOVERY_WEAK_UNDER = 0.180
HVRT_1PH_RECOVERY_XR_OVER = 0.100
# Strong-grid recovery measurement bias (2026-07-12 ODE/Simulink alignment): full320 switching
# results show SCR=10 post-clear V+ settles just above the 7% recovery band (typically +0.072..0.078)
# for many LVRT asym cases and all strong-grid HVRT swells. The averaged ODE was too ideal and pulled
# those tails back into band, hiding recover FAILs from training/error analysis. This bias is a
# measured terminal-voltage proxy only; it is restricted to strong-grid post-clear recovery.
STRONG_RECOVERY_SCR0 = 8.0
LVRT_STRONG_RECOVERY_OVER = 0.090
LVRT_ASYM_RECOVERY_DUR_MAX = 10.0
HVRT_STRONG_RECOVERY_OVER = 0.074
# Asymmetric LVRT boundary measured-iq proxy: switching reactive FAILs occur where the commanded
# support is tiny but negative-sequence ripple makes measured iq cross the wrong sign. Dynamics still
# use the command; reward/evaluation use the measured proxy in this narrow boundary band.
ASYM_IQ_MEAS_BIAS = 0.70
ASYM_BOUNDARY_V_LO, ASYM_BOUNDARY_V_HI = 0.82, 0.91
# Extra shallow-asym LVRT measurement ripple (2026-07-07 active-baseline ODE-blind fix): for
# 2ph/2ph_g at target=0.75 the residual prior's V2n feed-forward keeps the ODE measured iq positive,
# but switching still sees wrong-sign reactive current after sequence extraction/filtering. This term
# is deliberately narrow and only affects the measured criterion/reward, not plant dynamics.
ASYM_SHALLOW_FT = ('2ph', '2ph_g')
ASYM_SHALLOW_TARGET_MIN = 0.70
ASYM_SHALLOW_IQ_EXTRA_BIAS = 0.45
ASYM_SHALLOW_2PH_MIN_DUR = 0.37
ASYM_SHALLOW_2PHG_MIN_DUR = 0.45
ASYM_SHALLOW_2PHG_SCR_MIN = 8.0

FRT_FAULTS = ['normal', 'sym3ph', '1ph_g', '2ph', '2ph_g', 'swell']  # state fault classes
F2I = {f: i for i, f in enumerate(FRT_FAULTS)}

DT      = 2e-3                  # control step (s)
TSCALE  = 0.20                 # compress GB/T seconds-curve for training (see header)
MAX_SWITCHING_FAULT_DUR = 0.5   # frt_v2_full320_switching.m uses dur=min(fault_dur,0.5)


def effective_fault_dur(s):
    """Fault duration used by the certified switching harness and therefore by the ODE proxy."""
    return min(float(s['fault_dur']), MAX_SWITCHING_FAULT_DUR)


def fault_sequence(ftype: str, targetV: float):
    """Map fault type + residual/swell level → imposed grid positive/negative seq voltage (pu).
    Standard shunt-fault sequence approximations (documented in FRT_SPEC)."""
    if ftype in ('sym3ph',):            return targetV, 0.0
    if ftype in ('swell_3ph', 'swell'): return targetV, 0.0
    if ftype == '1ph_g':   return (2 + targetV) / 3.0, (1 - targetV) / 3.0
    if ftype == '2ph':     return (1 + targetV) / 2.0, (1 - targetV) / 2.0
    if ftype == '2ph_g':   return (1 + 2*targetV) / 3.0, (1 - targetV) / 3.0
    if ftype == 'swell_1ph': return (2 + targetV) / 3.0, abs(targetV - 1) / 3.0
    return 1.0, 0.0


def grid_xr_factor(s, scr):
    """0..1 proxy for same-SCR grid inductiveness from expanded scenario Rg.

    Original 320 scenarios do not carry Rg_ohm; they keep factor 0. Expanded scenarios do, and the
    selected switching failures line up with low-R/high-X branches that SCR alone cannot distinguish.
    """
    try:
        rg = float(s.get('Rg_ohm', 0.0))
    except (TypeError, ValueError, AttributeError):
        return 0.0
    if rg <= 0.0 or scr <= 0.0:
        return 0.0
    rg_base = GRID_R_BASE_AT_SCR1 / scr
    return min(1.0, max(0.0, 1.0 - rg / max(1e-9, rg_base)))


def lvrt_envelope(t_rel, residual, reach09=2.0, ts=TSCALE):
    """LEGACY frt-v1 LVRT lower boundary (compressed by ts). NOTE the `residual - 0.05` slack during
    the hold — this is the audited frt-v1 boundary and is INVALID under frt-v2 (the hold floor IS the
    residual). Kept only for the legacy HPTFRTEnv; HPTFRTEnvV2 overrides `_lvrt_floor` to use the
    versioned `common.frt_v2.lvrt_lower_env` instead. Do NOT use for new work."""
    hold = 0.625 * ts
    reach = reach09 * ts
    if t_rel < 0:        return 0.9
    if t_rel <= hold:    return max(0.0, residual - 0.05)        # frt-v1 slack (INVALID under frt-v2)
    if t_rel <= reach:   return residual + (0.9 - residual) * (t_rel - hold) / (reach - hold)
    return 0.9


class HPTFRTEnv(gym.Env):
    """Standard-FRT averaged-ODE environment. 4-D action, ~22-D observation."""
    def __init__(self, scenarios, seed=0, train_mode=True):
        super().__init__()
        self.scn = list(scenarios)
        self.rng = np.random.default_rng(seed)
        self.train_mode = train_mode
        self.action_space = spaces.Box(
            low=np.array([0.0, -I_Q_ACT, -V_SE_MAX, -V_SE_MAX], np.float32),
            high=np.array([I_CONV_MAX, I_Q_ACT, V_SE_MAX, V_SE_MAX], np.float32))
        self.observation_space = spaces.Box(-5, 5, shape=(21,), dtype=np.float32)
        self._i = 0

    # ── grid voltage imposed by the scenario at time t ──────────────────────────
    def _grid_seq(self, t):
        s = self._sc
        t_f, dur = s['t_fault'], effective_fault_dur(s) * TSCALE
        if t < t_f or t > t_f + dur:
            return 1.0, 0.0                      # pre/post fault: nominal
        return self._Vg_p, self._Vg_n

    def reset(self, *, seed=None, options=None):
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        s = self.scn[self._i % len(self.scn)]; self._i += 1
        self._sc = s
        self._Vg_p, self._Vg_n = fault_sequence(s['fault_type'], float(s['target_V_pu']))
        self.scr = float(s['scr'])
        self.K_q = K_Q_BASE / self.scr           # reactive→voltage gain (weak grid → larger)
        # state: [Vdc, V2p, V2n, xi]  (positive/negative seq terminal mag, integrator)
        self.Vdc = 1.0
        self.V2p = 1.0
        self.V2n = 0.0
        self.xi  = 0.0
        self.t   = 0.0
        self.tripped = False
        self._iq = 0.0
        self._last_a = np.zeros(4, np.float32)
        self._prev_in_fault = False
        self._hvrt_absorb_peak = 0.0
        self._hvrt_swell_peak = 1.0
        self._hvrt_clear_timer = math.inf
        self._fp = F2I.get('sym3ph' if s['category']=='LVRT' and s['fault_type']=='sym3ph'
                           else ('swell' if s['category']=='HVRT' else s['fault_type']), 0)
        return self._obs(), {}

    def _obs(self):
        s = self._sc
        in_fault = float(s['t_fault'] <= self.t <= s['t_fault'] + effective_fault_dur(s)*TSCALE)
        vdev = 0.9 - self.V2p
        iq_ref = self._iq_ref()
        iq_err = iq_ref - self._iq
        probs = np.zeros(6, np.float32)
        if in_fault: probs[self._fp] = 0.92; probs[0] += 0.08
        else: probs[0] = 1.0
        o = np.array([
            self.Vdc, self.V2p, self.V2n, abs(self._iq),
            0.0, 0.0,                       # dVdc, dV2 placeholders (filled by deltas if needed)
            vdev, iq_err, self._iq,
            *probs,
            min(1.0, max(0.0, (self.t - s['t_fault'])/ (0.5))), in_fault,
            *self._last_a,
        ], dtype=np.float32)
        return np.clip(o, -5, 5)

    # ── versioned-envelope hooks (overridden by HPTFRTEnvV2 to use common.frt_v2) ──────────────
    # Base class = LEGACY frt-v1 boundary (residual-0.05 hold slack / static HVRT 1.32). These are
    # the audited frt-v1 definitions and must NOT be used for new work; they exist only so the legacy
    # env still trips as it historically did. The trip tolerance is a NUMERIC guard, not a margin.
    def _lvrt_floor(self, t_rel):
        return lvrt_envelope(t_rel, float(self._sc['target_V_pu']))     # legacy: residual-0.05 slack

    def _hvrt_ceiling(self, t_rel):
        return 1.30 + 0.02                                             # legacy: static HVRT

    def _trip_tol(self):
        return 0.001                                                   # numeric float-compare guard

    def _iq_ref(self):
        """GB/T reactive droop reference (pu), capped at PE limit."""
        if self.V2p < 0.9:                       # LVRT: inject capacitive (positive)
            return min(I_Q_MAX, 1.5 * (0.9 - self.V2p))
        if self.V2p > 1.1:                       # HVRT: absorb (negative)
            return max(-I_Q_MAX, -1.5 * (self.V2p - 1.1))
        return 0.0

    def step(self, action):
        t_sample = self.t
        s = self._sc
        a = np.asarray(action, np.float32)
        i_sh_d, i_sh_q, m_se_d, m_se_q = [float(x) for x in a]
        # current limit (reactive priority): cap iq, then active fits under total limit
        i_sh_q = float(np.clip(i_sh_q, -I_Q_MAX, I_Q_MAX))
        id_max = math.sqrt(max(0.0, I_CONV_MAX**2 - i_sh_q**2))
        i_sh_d = float(np.clip(i_sh_d, 0.0, id_max))
        iq_cmd = i_sh_q

        Vg_p, Vg_n = self._grid_seq(self.t)
        in_fault_now = (s['t_fault'] <= t_sample <= s['t_fault'] + effective_fault_dur(s) * TSCALE)
        clear_t = s['t_fault'] + effective_fault_dur(s) * TSCALE
        post_clear = t_sample > clear_t
        xr = grid_xr_factor(s, self.scr)
        # series injection magnitude limited
        V_se_d = float(np.clip(m_se_d, -V_SE_MAX, V_SE_MAX))
        V_se_q = float(np.clip(m_se_q, -V_SE_MAX, V_SE_MAX))

        # ── positive-seq terminal voltage: grid + series support + reactive boost ──
        # actuator gains Simulink-calibrated (SE_GAIN, K_q) — see constants block
        V2p_ss = Vg_p + SE_GAIN * V_se_d + self.K_q * i_sh_q
        if (s['category'] == 'HVRT' and s['fault_type'] == 'swell_1ph'
                and self.scr <= HVRT_ASYM_SCR_MAX and Vg_n > 0.05):
            V2p_ss += HVRT_ASYM_V1_BIAS * Vg_n
        if post_clear:
            if (s['category'] == 'LVRT' and s['fault_type'] == 'sym3ph'
                    and self.scr >= LVRT_STIFF_SCR0 and float(s['target_V_pu']) <= LVRT_STIFF_VG_MAX):
                V2p_ss += LVRT_RECOVERY_BIAS0 + LVRT_RECOVERY_XR_BIAS * xr
            elif s['category'] == 'HVRT' and s['fault_type'] == 'swell_3ph':
                weak = max(0.0, (4.0 - self.scr) / 2.0)
                V2p_ss += -HVRT_RECOVERY_WEAK_UNDER * weak + HVRT_RECOVERY_XR_OVER * xr
                shallow = max(0.0, (1.15 - float(s['target_V_pu'])) / 0.05)
                shallow = min(1.0, shallow)
                scr2 = max(0.0, (2.5 - self.scr) / 0.5)
                scr2 = min(1.0, scr2)
                V2p_ss -= HVRT_SHALLOW_SCR2_EXTRA_UNDER * shallow * scr2
            elif s['category'] == 'HVRT' and s['fault_type'] == 'swell_1ph':
                weak = max(0.0, (4.0 - self.scr) / 2.0)
                V2p_ss += -HVRT_1PH_RECOVERY_WEAK_UNDER * weak + HVRT_1PH_RECOVERY_XR_OVER * xr
            strong_recovery = max(0.0, (self.scr - STRONG_RECOVERY_SCR0) / (10.0 - STRONG_RECOVERY_SCR0))
            strong_recovery = min(1.0, strong_recovery)
            if s['category'] == 'LVRT':
                is_asym = s['fault_type'] in ('1ph_g', '2ph', '2ph_g')
                asym_short = is_asym and float(s['fault_dur']) <= LVRT_ASYM_RECOVERY_DUR_MAX
                if s['fault_type'] == 'sym3ph' or asym_short:
                    V2p_ss += LVRT_STRONG_RECOVERY_OVER * strong_recovery
            elif s['category'] == 'HVRT':
                V2p_ss += HVRT_STRONG_RECOVERY_OVER * strong_recovery
        V2p_ss = max(0.0, V2p_ss)
        self.V2p += (V2p_ss - self.V2p) * (DT / TAU_V2)
        # ── negative-seq: imposed by the grid; series injection CANNOT cancel it (Simulink series
        # modulation is generated at the positive-seq PLL angle → pos-seq only; confirmed
        # ctrl_series_code L318). The old "−|V_se_q|" cancellation was a fake channel — removed.
        V2n_ss = Vg_n
        self.V2n += (V2n_ss - self.V2n) * (DT / TAU_V2)
        iq_meas = iq_cmd
        if (s['category'] == 'LVRT' and self.V2n > 0.05
                and ASYM_BOUNDARY_V_LO <= self.V2p <= ASYM_BOUNDARY_V_HI):
            iq_meas = iq_cmd - ASYM_IQ_MEAS_BIAS * self.V2n
            long_2ph = (s['fault_type'] == '2ph'
                        and float(s['fault_dur']) >= ASYM_SHALLOW_2PH_MIN_DUR)
            strong_long_2phg = (s['fault_type'] == '2ph_g'
                                and self.scr >= ASYM_SHALLOW_2PHG_SCR_MIN
                                and float(s['fault_dur']) >= ASYM_SHALLOW_2PHG_MIN_DUR)
            if (s['fault_type'] in ASYM_SHALLOW_FT
                    and float(s['target_V_pu']) >= ASYM_SHALLOW_TARGET_MIN
                    and (long_2ph or strong_long_2phg)):
                iq_meas -= ASYM_SHALLOW_IQ_EXTRA_BIAS * self.V2n
        if (s['category'] == 'HVRT' and s['fault_type'] == 'swell_1ph'
                and self.scr <= HVRT_ASYM_SCR_MAX
                and self.V2n > 0.05 and self.V2p > 1.05):
            iq_meas = iq_cmd + HVRT_ASYM_IQ_MEAS_BIAS * self.V2n
        self._iq = iq_meas

        # ── DC bus (Simulink-CALIBRATED, 2026-06-10): a[0]=i_sh_d is unused (discarded in Simulink; id
        # is set by the shunt's own Vdc PI loop, which holds Vdc near 1.0). Vdc is dragged down only by
        # (a) reactive current using converter headroom — MILD, worse at low voltage — and (b) SERIES
        # voltage BOOST, which pulls active power from the bus — DOMINANT, ≈1.9× the boost. Calibrated to
        # hpt_frt_full.slx mode-10 sweeps: no-series Vdc≈0.93–0.99 (all depths); series-boost 0.2→Vdc≈0.60.
        sag_iq = 0.08 * abs(i_sh_q) / max(0.3, Vg_p)       # reactive-headroom cost (mild)
        sag_se = 1.9 * max(0.0, V_se_d) + 0.5 * abs(V_se_q)  # series DC drain: d-boost dominant + mild q (Simulink-cal)
        # CALIBRATION RE-VERIFIED (2026-06-17, sim_compare.m): at SCR=3 sym3ph the 1.9 coeff reproduces
        # Simulink Vdc_min within ≤0.022 (boost 0/0.1/0.2 -> ODE 0.976/0.786/0.596 vs Sim 0.985/0.764/0.604);
        # the K_q=K_Q_BASE/scr scaling holds at SCR=10 (reactive ~no LV authority on a stiff grid). So this
        # term is faithful at the tested operating points — NOT an unvalidated extrapolation.
        # On LOAD-DEPENDENCE: P_se physically = V_se·I_line, but the scenario load fields (P_load/Q_load/pf,
        # FRT_SPEC §3) are DECORATIVE — used by NEITHER this env NOR the Simulink validator, which both run
        # at fixed RATED load. So load-independence here is faithful to the authority (not a sim-to-real gap);
        # making it load-dependent is only meaningful if the validator is first changed to vary load (future
        # work, would require re-calibration + re-train + re-validate). See report §5.
        if Vg_p > 1.1:                                     # HVRT swell: command-driven DC undershoot
            absb = max(0.0, -i_sh_q)                       # reactive ABSORPTION magnitude (iq<0)
            self._hvrt_absorb_peak = max(self._hvrt_absorb_peak, absb)
            self._hvrt_swell_peak = max(self._hvrt_swell_peak, Vg_p)
            Vdc_eq = (SW_C0 - SW_AB*absb - SW_SE*V_se_d - SW_X*absb*V_se_d - SW_DEP*(Vg_p - 1.25))
            Vdc_eq = min(VDC_CHOP, max(0.05, Vdc_eq))      # swell-regime map (Stage A); LVRT path unchanged
        else:
            stiff = max(0.0, (self.scr - LVRT_STIFF_SCR0) / (10.0 - LVRT_STIFF_SCR0))
            stiff = min(1.0, stiff)
            lvrt_stiff_drop = 0.0
            if (in_fault_now and s['category'] == 'LVRT' and s['fault_type'] == 'sym3ph'
                    and Vg_p <= LVRT_STIFF_VG_MAX):
                sev = max(0.0, 0.9 - Vg_p) / 0.7
                lvrt_stiff_drop = LVRT_STIFF_DC_DROP * stiff * sev
                lvrt_stiff_drop += LVRT_XR_DC_DROP * xr * stiff * sev
            lvrt_weak_asym_drop = 0.0
            if (in_fault_now and s['category'] == 'LVRT' and s['fault_type'] in ('2ph', '2ph_g')
                    and self.scr <= 3.0 and float(s['target_V_pu']) <= 0.2):
                sev = max(0.0, 0.9 - Vg_p) / 0.7
                lvrt_weak_asym_drop = LVRT_WEAK_ASYM_DC_DROP * sev
                if float(s['fault_dur']) >= LVRT_WEAK_ASYM_LONG_DUR:
                    lvrt_weak_asym_drop += LVRT_WEAK_ASYM_LONG_DC_DROP * sev
            Vdc_eq = min(VDC_CHOP, max(0.05, 1.0 - sag_iq - sag_se - lvrt_stiff_drop - lvrt_weak_asym_drop))
        if s['category'] == 'HVRT' and (not in_fault_now) and self._prev_in_fault:
            self._hvrt_clear_timer = 0.0
        if s['category'] == 'HVRT' and self._hvrt_clear_timer < HVRT_CLEAR_WIN:
            over = max(0.0, (self._hvrt_swell_peak - 1.1) / 0.2)
            release_drop = HVRT_CLEAR_DROP * self._hvrt_absorb_peak * min(1.0, over) * math.exp(-self._hvrt_clear_timer / HVRT_CLEAR_TAU)
            Vdc_eq = max(0.05, Vdc_eq - release_drop)
            self._hvrt_clear_timer += DT
        nsub = 10
        hsub = DT / nsub
        for _ in range(nsub):
            self.Vdc += (Vdc_eq - self.Vdc) * (hsub / DC_TAU)
            self.Vdc = min(VDC_CHOP, max(0.05, self.Vdc))

        self.t += DT
        self._last_a = a

        # ── envelope / trip check (boundary is INJECTED via overridable hooks so the versioned
        #    criterion is decoupled from the shared plant dynamics above; V2 overrides the hooks) ──
        # The voltage/current sample above was computed at t_sample. Checking the envelope at the
        # post-increment timestamp creates a one-step false trip around HVRT/LVRT boundary changes.
        t_rel = t_sample - s['t_fault']
        if s['category'] == 'LVRT':
            if self.V2p < self._lvrt_floor(t_rel) - self._trip_tol():
                self.tripped = True
        else:  # HVRT upper boundary
            if self.V2p > self._hvrt_ceiling(t_rel) + self._trip_tol():
                self.tripped = True
        self._prev_in_fault = in_fault_now

        # ── reward (FRT_SPEC §1 五条判据) ─────────────────────────────────────────
        iq_ref = self._iq_ref()
        r_connect = -20.0 if self.tripped else 0.0
        r_reactive = -8.0 * abs(iq_ref - iq_meas)   # strengthened (2026-06-10): force GB/T reactive injection,
        # decouple from V2p-raising (else agent uses cheap series V_se_d which drains Vdc in Simulink; see asym bug)
        # Criteria-aligned reactive shaping: the frt-v2 criterion immediately fails sustained wrong-sign
        # current after the response delay. Make that failure mode loud in the reward, especially for
        # asymmetric LVRT where measured iq can cross negative even when the command is small positive.
        assess_reactive = in_fault_now and (t_sample >= s['t_fault'] + FV2.REACTIVE_DELAY * TSCALE)
        if assess_reactive:
            if self.V2p < 0.9:
                min_support = max(0.0, iq_ref - FV2.REACTIVE_TOL)
                short = max(0.0, min_support - iq_meas)
                wrong = max(0.0, -iq_meas - FV2.REACTIVE_SIGN_EPS)
                r_reactive += -35.0 * short - 60.0 * wrong
            elif self.V2p > 1.1:
                max_absorb = iq_ref + FV2.REACTIVE_TOL
                short = max(0.0, iq_meas - max_absorb)
                wrong = max(0.0, iq_meas - FV2.REACTIVE_SIGN_EPS)
                r_reactive += -35.0 * short - 60.0 * wrong
        r_limit = -5.0 * max(0.0, math.hypot(i_sh_d, i_sh_q) - I_CONV_MAX)
        r_v2 = -5.0 * abs(1.0 - self.V2p) - 3.0 * self.V2n
        r_vdc = -10.0 * max(0.0, 0.82 - self.Vdc) - 5.0 * max(0.0, self.Vdc - 1.25)
        # 0.82 (not the 0.75 criterion line): safety margin so the policy doesn't ride the cliff edge
        # — Simulink ripple/transients sank 0.72-cases that ODE put exactly at 0.75
        reward = r_connect + r_reactive + r_limit + r_v2 + r_vdc + 1.0  # +1 alive

        done = self.t >= float(s['T_sim']) * TSCALE or self.tripped
        info = {'V2p': self.V2p, 'V2n': self.V2n, 'Vdc': self.Vdc, 'iq': iq_meas, 'iq_cmd': iq_cmd,
                'iq_ref': iq_ref, 'mse_d': V_se_d, 'mse_q': V_se_q,
                'Vdc_eq': Vdc_eq, 'Vg_p': Vg_p, 'Vg_n': Vg_n,
                'tripped': self.tripped, 't': self.t}
        return self._obs(), float(reward), bool(done), False, info


def load_frt_scenarios(csv_path):
    import csv
    rows = []
    text_fields = ('category', 'fault_type', 'grid', 'scenario_profile')
    with open(csv_path, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            rows.append({k: (float(v) if (v != '' and k not in text_fields) else v)
                         for k, v in r.items()})
    return rows
