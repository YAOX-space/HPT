"""frt_env_v2.py — frt-v2 training-environment INTERFACE fixes (audit H1, H2).

Subclasses the legacy HPTFRTEnv but corrects the agent-facing interface so it is FAIR and matches
deployment:
  * TRUE 3-D action [iq, mse_d, mse_q] — the vestigial i_sh_d dim is removed (H2).
  * FULLY DE-PRIVILEGED observation — the fault-class one-hot, the in_fault flag AND the elapsed-time
    fraction are produced by an ONLINE detector/classifier on the MEASURED (V2p, V2n) only. The
    observation NEVER reads the scenario fault type, the true onset t_fault, the future fault
    duration, the target residual or the clearing time. The environment still uses the scenario's
    t_fault to drive the PLANT (the grid) — that is the world, not the agent's information.

⚠️ Models trained on the legacy 4-D / label-one-hot / true-time interface are NOT compatible with
this obs/action; their scores (82.2% etc.) are frt-v1. Re-training under this interface is PENDING
(P3, CHANGE_REPORT). This module exists so the interface is testable and the retrain is well-defined.
"""
from __future__ import annotations
import numpy as np
from gymnasium import spaces
from .frt_env import HPTFRTEnv, I_Q_ACT, V_SE_MAX, F2I, TSCALE
from ..common import frt_v2 as FV2

# online gate thresholds (must match the deployment HLC / network sac_wrapper)
GATE_V2N_THR = 0.05
GATE_LV, GATE_HV = 0.90, 1.060
ELAPSED_NORM = 0.5            # normalisation for the elapsed-since-detected-onset fraction (s)
HVRT_RECOVERY_HOLD = 0.45     # online-measured hold after HVRT clears; no scenario labels/timing
HVRT_RECOVERY_DEADBAND = 0.025

# frt-v2 OBSERVATION DIMENSION — defined explicitly (audit item 5). The last-action block is the TRUE
# 3-D action [iq, mse_d, mse_q]; no dummy 4th element is retained to pad to 21. Layout (20):
#   [Vdc, V2p, V2n, |iq|, 0, 0, vdev, iq_err, iq, probs(6), tfrac, in_fault, last_a(3)]
N_ACT_V2 = 3
OBS_DIM_V2 = 9 + 6 + 2 + N_ACT_V2     # = 20


def online_fault_class(V2p, V2n, recent_hvrt=False):
    """Deployment-identical online classifier on MEASURED sequence voltages -> fault-class index
    into FRT_FAULTS (normal0 sym3ph1 1ph_g2 2ph3 2ph_g4 swell5). No labels, no true time.

    NOTE (audit 2026-06-25): classification keys on V2p bands, while `is_fault_measured` ALSO trips on
    V2n>GATE_V2N_THR. So in the band V2p∈[0.90,1.10] with V2n>thr this returns `normal` even though a
    (shallow) asymmetric fault is present — those route to the sym/general expert. This is BENIGN BY
    CONSTRUCTION for the in-scope Δ-Yg topology: any asym fault deep enough to matter drives
    V2p=(2+targetV)/3 < 0.90 (1ph_g targetV≤0.2 → 0.73) and IS caught here; only the cosmetically
    shallow 1ph_g@0.75 (V2p≈0.917) falls in-band, and those ride through (frt-v2: 1ph_g = 20T/0F/40NE).
    ⚠️ If the topology changes (independent H-bridge / deeper reachable asym residual, see §5-9), add a
    `V2n>GATE_V2N_THR` asym branch here — but that changes obs/routing and FORCES a retrain + frt-v2
    full-320 re-run, so it is a deliberate experiment, not a silent edit."""
    if recent_hvrt or V2p > GATE_HV:
        return F2I['swell']                       # HVRT (sym/asym share index 5, as in deployment)
    if V2p < GATE_LV:
        return F2I['1ph_g'] if V2n > GATE_V2N_THR else F2I['sym3ph']
    return F2I['normal']


def is_fault_measured(V2p, V2n):
    """Online fault-present detector from measured sequence voltages (no labels/time)."""
    return (V2p < GATE_LV) or (V2p > GATE_HV) or (V2n > GATE_V2N_THR)


class OnlineFaultDetector:
    """Stateful online detector: latches the DETECTED onset time from measured (V2p,V2n), reports
    elapsed-since-detected-onset, and resets when the measurement returns to the normal band. It uses
    only the agent's own clock `t` and measurements — never the true scenario onset/duration."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.detected = False
        self.onset_t = None
        self.seen_hvrt = False
        self.last_hvrt_t = None
        self.recent_hvrt = False

    def update(self, t, V2p, V2n):
        """Advance one step. Returns (in_fault_online: bool, elapsed_s: float)."""
        measured = is_fault_measured(V2p, V2n)
        if V2p > GATE_HV:
            self.seen_hvrt = True
            self.last_hvrt_t = t
        if is_fault_measured(V2p, V2n):
            if not self.detected:
                self.detected = True
                self.onset_t = t
            self.recent_hvrt = self.seen_hvrt
        elif (
            self.seen_hvrt
            and self.last_hvrt_t is not None
            and (t - self.last_hvrt_t) <= HVRT_RECOVERY_HOLD
            and abs(V2p - 1.0) > HVRT_RECOVERY_DEADBAND
        ):
            # Keep the post-clear recovery segment visible as an HVRT state using only measured
            # voltage history. This prevents shallow recovery points from being misrouted as LVRT.
            self.detected = True
            if self.onset_t is None:
                self.onset_t = self.last_hvrt_t
            self.recent_hvrt = True
        else:
            self.detected = False
            self.onset_t = None
            self.seen_hvrt = False
            self.last_hvrt_t = None
            self.recent_hvrt = False
        elapsed = (t - self.onset_t) if self.detected else 0.0
        return self.detected, float(max(0.0, elapsed))


class HPTFRTEnvV2(HPTFRTEnv):
    """True 3-D action + fully de-privileged online observation (frt-v2 interface)."""

    def __init__(self, scenarios, seed=0, train_mode=True):
        self._detector = OnlineFaultDetector()
        self._last_a3 = np.zeros(N_ACT_V2, np.float32)     # TRUE 3-D last action (no dummy 4th)
        super().__init__(scenarios, seed=seed, train_mode=train_mode)
        # 3-D action: [iq, mse_d, mse_q]  (no i_sh_d)
        self.action_space = spaces.Box(
            low=np.array([-I_Q_ACT, -V_SE_MAX, -V_SE_MAX], np.float32),
            high=np.array([I_Q_ACT, V_SE_MAX, V_SE_MAX], np.float32))
        # 20-D observation (explicit, item 5) — overrides the parent's 21-D space
        self.observation_space = spaces.Box(-5.0, 5.0, (OBS_DIM_V2,), np.float32)

    # ── versioned trip/criterion boundary (audit round-4 B): the V2 env trips (and therefore its
    #    connect-reward term) on the SAME definition as common.frt_v2 — NOT the legacy residual-0.05 /
    #    static-1.32. The env runs in TSCALE-compressed time, so map t_rel back to real seconds for
    #    the frt_v2 envelopes. solver_tol is ONLY the numeric float-compare guard. ──
    def _lvrt_floor(self, t_rel):
        return FV2.lvrt_lower_env(t_rel / TSCALE, float(self._sc['target_V_pu']))

    def _hvrt_ceiling(self, t_rel):
        return FV2.hvrt_upper_env(t_rel / TSCALE)

    def _trip_tol(self):
        return FV2.DEFAULT_SOLVER_TOL          # numeric guard only; never a physical margin

    def reset(self, *, seed=None, options=None):
        self._detector.reset()
        self._last_a3 = np.zeros(N_ACT_V2, np.float32)
        return super().reset(seed=seed, options=options)

    def step(self, action):
        a = np.asarray(action, np.float32)
        self._last_a3 = a.copy()                           # 3-D last action for the next obs
        # map 3-D -> the parent's 4-D plant call with i_sh_d=0 (parent discards it anyway)
        a4 = np.array([0.0, a[0], a[1], a[2]], np.float32)
        return super().step(a4)

    def _obs(self):
        """OBS_DIM_V2 (=20) layout. The fault one-hot, in_fault flag AND elapsed-time fraction ALL
        come from the ONLINE detector/classifier on measured (V2p,V2n) — no labels, no true
        onset/duration. The last-action block is the TRUE 3-D action (no dummy 4th)."""
        vdev = 0.9 - self.V2p
        iq_err = self._iq_ref() - self._iq
        infault_online, elapsed = self._detector.update(self.t, self.V2p, self.V2n)
        fc = online_fault_class(self.V2p, self.V2n, self._detector.recent_hvrt)
        probs = np.zeros(6, np.float32)
        if infault_online and fc != 0:
            probs[fc] = 0.92; probs[0] += 0.08
        else:
            probs[0] = 1.0
        tfrac = min(1.0, max(0.0, elapsed / ELAPSED_NORM))     # elapsed since DETECTED onset (not true)
        o = np.array([
            self.Vdc, self.V2p, self.V2n, abs(self._iq),
            0.0, 0.0, vdev, iq_err, self._iq,
            *probs, tfrac, float(infault_online), *self._last_a3,
        ], dtype=np.float32)
        assert o.shape == (OBS_DIM_V2,), o.shape
        return np.clip(o, -5, 5)
