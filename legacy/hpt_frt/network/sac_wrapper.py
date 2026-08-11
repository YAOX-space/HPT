"""sac_wrapper.py — Mode 5 (online-gated multi-expert SAC) deployed as a per-HPT controller.

The paper's MAIN METHOD (CONTROL_MODES.md §5, pure SAC). Four specialist actors
{sym, asym, hvrt_sym, hvrt_asym} are routed by an ONLINE sequence-component gate on MEASURED
(V2p, V2n) — no oracle label, no central coordinator. Each HPT instantiates its own HPTController
and uses only its local measurements.

Observation is the frt-v2 20-D vector (mirrors device/frt_env_v2.HPTFRTEnvV2._obs; OBS_DIM_V2=20).
Action is the frt-v2 3-D [iq, se_d, se_q] (N_ACT_V2=3). The fault one-hot, in_fault flag and elapsed
fraction are DE-PRIVILEGED — derived from MEASURED (V2p, V2n) via the same online detector/classifier
used in training, NOT a passed true-fault flag. Deployment clips: iq ±0.27 (sym) / ±0.24 (asym),
se_d/se_q ±0.20 (config). se_d>0 = boost.

Gate-chattering analysis (section 八.10 / 十二.8): we log the committed gate class at every step,
the switch count, the first-switch time, and a chattering flag. Two gate variants are supported:
  raw          : instantaneous (V2p,V2n) classifier — exposes chattering;
  hysteresis   : V2n band + dwell counter — the chattering MITIGATION to be analysed.
"""
from __future__ import annotations
import os, sys
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import numpy as np
from . import config as C
# frt-v2 contract + de-privileged online primitives (single source = device.frt_env_v2)
from ..device.frt_env_v2 import (OBS_DIM_V2, N_ACT_V2, ELAPSED_NORM, online_fault_class,
                                  is_fault_measured)
from ..device.frt_env import I_Q_ACT, V_SE_MAX

# numpy2->numpy1 pickle shim: OLD .zip actors were saved under numpy>=2 (env_recovery memo). The new
# frt-v2 experts are numpy-1.24 clean and load without it, but the shim stays harmless for old zips.
import numpy.core as _np_core            # noqa: F401
for _sub in ['', '.multiarray', '.numeric', '._multiarray_umath', '.umath', '.numerictypes']:
    try:
        sys.modules['numpy._core' + _sub] = __import__('numpy.core' + _sub, fromlist=['x'])
    except Exception:
        pass

EXPERT_NAMES = ['sym', 'asym', 'hvrt_sym', 'hvrt_asym']

_EXPERTS = None


def load_experts(device='cpu'):
    """Load the 4 frt-v2 specialist SAC actors once (20-D obs / 3-D action). custom_objects bypasses
    any numpy2-pickled gym spaces / schedules and PINS the frt-v2 contract so a dimension mismatch is
    impossible to load silently."""
    global _EXPERTS
    if _EXPERTS is not None:
        return _EXPERTS
    from gymnasium import spaces
    from stable_baselines3 import SAC
    obs_sp = spaces.Box(-5, 5, shape=(OBS_DIM_V2,), dtype=np.float32)        # 20-D
    act_sp = spaces.Box(low=np.array([-I_Q_ACT, -V_SE_MAX, -V_SE_MAX], np.float32),
                        high=np.array([I_Q_ACT, V_SE_MAX, V_SE_MAX], np.float32))   # 3-D
    co = {'observation_space': obs_sp, 'action_space': act_sp,
          'lr_schedule': (lambda _: 3e-4), 'clip_range': (lambda _: 0.2)}
    experts = {}
    for n in EXPERT_NAMES:
        m = SAC.load(str(C.MODELS / f'sac_{n}_best'), device=device, custom_objects=co)
        # hard contract check — refuse a model that is not the frt-v2 20/3 shape
        if m.observation_space.shape != (OBS_DIM_V2,) or m.action_space.shape != (N_ACT_V2,):
            raise ValueError(f'expert sac_{n}_best is {m.observation_space.shape}/{m.action_space.shape}, '
                             f'expected ({OBS_DIM_V2},)/({N_ACT_V2},) — re-export the frt-v2 expert')
        experts[n] = m
    _EXPERTS = experts
    return _EXPERTS


def gate_raw(V2p, V2n):
    """Instantaneous online gate: (V2p,V2n) -> expert class. No memory (exposes chattering)."""
    if V2p > C.GATE_HV_THR:                                   # HVRT
        return 'hvrt_asym' if V2n > C.GATE_V2N_THR else 'hvrt_sym'
    if V2p < C.GATE_LV_THR:                                   # LVRT
        return 'asym' if V2n > C.GATE_V2N_THR else 'sym'
    return 'normal'                                           # deadband: idle (route to sym actor)


def iq_ref_gbt(V2p):
    """GB/T reactive-droop reference (pu), capped at the PE limit."""
    if V2p < 0.9:
        return min(C.I_Q_MAX, 1.5 * (0.9 - V2p))
    if V2p > 1.1:
        return max(-C.I_Q_MAX, -1.5 * (V2p - 1.1))
    return 0.0


class HPTController:
    """Per-HPT Mode-5 controller: online gate + specialist actor + deployment clip + chattering log.

    Optional DEPLOYMENT-SIDE protections (no retraining; round-2 mitigation study):
      safety  : action projection — if the Vdc surrogate predicts Vdc_next < vdc_floor, shrink the
                series boost se_d FIRST (preserve GB/T reactive iq priority), then |se_q|. The
                projection magnitude is recorded (never silently altered).
      slew    : (diq_max, dmse_max) per-step rate limit on (iq, se_d, se_q) vs the last command.
      vp/vn_noise, meas_delay : measurement noise (std, pu) + delay (steps) on the gate/obs inputs,
                for the gate robustness sweep.
    """

    def __init__(self, bus, use_hysteresis=True, safety=False, vdc_floor=0.78,
                 slew=None, vp_noise=0.0, vn_noise=0.0, meas_delay=0, noise_seed=0):
        self.bus = bus
        self.use_hyst = use_hysteresis
        self.safety = safety
        self.vdc_floor = vdc_floor
        self.slew = slew                       # (diq_max, dmse_max) or None
        self.vp_noise = vp_noise; self.vn_noise = vn_noise; self.meas_delay = int(meas_delay)
        self._rng = np.random.default_rng(1000 + int(bus) + int(noise_seed))
        self.experts = load_experts()
        self.reset()

    def reset(self):
        self.last_a = np.zeros(N_ACT_V2, np.float32)        # 3-D last action [iq, se_d, se_q]
        self._onset_t = None                                 # online-detected fault onset (no true time)
        self.Vdc = 1.0
        self.iq = 0.0
        self.committed = 'normal'
        self._pending = None
        self._pending_n = 0
        self.gate_hist = []
        self.switch_count = 0
        self.first_switch_t = None
        self._t_last = None
        self._meas_buf = []                    # (Vp,Vn) delay buffer
        self.se_proj_total = 0.0; self.slew_clip_total = 0.0; self.se_proj_max = 0.0

    def _measure(self, V2p, V2n):
        """Apply measurement noise + delay to the gate/obs inputs (identity if disabled)."""
        if self.vp_noise > 0:
            V2p = V2p + float(self._rng.normal(0, self.vp_noise))
        if self.vn_noise > 0:
            V2n = max(0.0, V2n + float(self._rng.normal(0, self.vn_noise)))
        if self.meas_delay > 0:
            self._meas_buf.append((V2p, V2n))
            if len(self._meas_buf) > self.meas_delay:
                V2p, V2n = self._meas_buf.pop(0)
            else:
                V2p, V2n = self._meas_buf[0]
        return V2p, V2n

    def _project_safety(self, iq, se_d, se_q, Vp):
        """Shrink series boost so the Vdc surrogate equilibrium stays >= vdc_floor (iq kept)."""
        if not self.safety:
            return se_d, se_q, 0.0
        se_d0 = se_d
        # vdc_eq decreasing in se_d (boost) and |se_q|; solve for max se_d keeping eq>=floor
        for _ in range(6):
            veq = C.vdc_eq(iq, se_d, se_q, max(0.05, Vp))
            if veq >= self.vdc_floor or se_d <= 0:
                break
            se_d = max(0.0, se_d - 0.02)
        # if still below floor with se_d=0, trim |se_q|
        while C.vdc_eq(iq, 0.0 if se_d <= 0 else se_d, se_q, max(0.05, Vp)) < self.vdc_floor and abs(se_q) > 1e-3:
            se_q *= 0.8
        mod = abs(se_d0 - se_d)
        self.se_proj_total += mod; self.se_proj_max = max(self.se_proj_max, mod)
        return se_d, se_q, mod

    def _apply_slew(self, iq, se_d, se_q):
        if self.slew is None:
            return iq, se_d, se_q
        diq, dmse = self.slew
        liq, lsd, lsq = self.last_a[0], self.last_a[1], self.last_a[2]
        niq = float(np.clip(iq, liq - diq, liq + diq))
        nsd = float(np.clip(se_d, lsd - dmse, lsd + dmse))
        nsq = float(np.clip(se_q, lsq - dmse, lsq + dmse))
        self.slew_clip_total += abs(iq - niq) + abs(se_d - nsd) + abs(se_q - nsq)
        return niq, nsd, nsq

    # ── gate with optional hysteresis + dwell (chattering mitigation) ────────────
    def step_gate(self, V2p, V2n, t):
        if not self.use_hyst:
            new = gate_raw(V2p, V2n)
        else:
            # LV/HV region with hysteresis band on V2n for the sym/asym sub-decision
            if V2p > C.GATE_HV_THR:
                base, alt = 'hvrt_sym', 'hvrt_asym'
            elif V2p < C.GATE_LV_THR:
                base, alt = 'sym', 'asym'
            else:
                base, alt = 'normal', 'normal'
            cur_is_asym = self.committed in ('asym', 'hvrt_asym')
            if base == 'normal':
                proposed = 'normal'
            elif cur_is_asym:                       # stay asym unless V2n drops below lower band
                proposed = base if V2n < C.GATE_V2N_THR - C.GATE_V2N_HYST else alt
            else:                                    # stay sym unless V2n rises above upper band
                proposed = alt if V2n > C.GATE_V2N_THR + C.GATE_V2N_HYST else base
            # dwell: a new class must persist GATE_DWELL consecutive snapshots before committing
            if proposed == self.committed:
                self._pending, self._pending_n = None, 0
                new = self.committed
            else:
                if proposed == self._pending:
                    self._pending_n += 1
                else:
                    self._pending, self._pending_n = proposed, 1
                new = proposed if self._pending_n >= C.GATE_DWELL else self.committed
        if new != self.committed:
            self.switch_count += 1
            if self.first_switch_t is None:
                self.first_switch_t = t
            self.committed = new
        self.gate_hist.append(self.committed)
        self._t_last = t
        return self.committed

    # ── online detector: in_fault + elapsed-since-detected-onset (de-privileged, no true time) ──
    STEADY_TFRAC = 0.3            # representative mid-fault tfrac for the STATIC fixed-point sweep
                                  # (a held sag has no elapsed time; documented approximation)

    def _detect(self, V2p, V2n, t):
        faulted = is_fault_measured(V2p, V2n)
        if faulted:
            if self._onset_t is None:
                self._onset_t = t
            elapsed = max(0.0, t - self._onset_t)
        else:
            self._onset_t = None
            elapsed = 0.0
        return faulted, min(1.0, elapsed / ELAPSED_NORM)

    # ── frt-v2 20-D observation (mirrors device.frt_env_v2.HPTFRTEnvV2._obs) ──────
    def _obs(self, V2p, V2n, Vdc, tfrac, in_fault_online):
        iq_ref = iq_ref_gbt(V2p)
        iq_err = iq_ref - self.iq
        fc = online_fault_class(V2p, V2n)                    # de-privileged class from measurement
        probs = np.zeros(6, np.float32)
        if in_fault_online and fc != 0:
            probs[fc] = 0.92; probs[0] += 0.08
        else:
            probs[0] = 1.0
        o = np.array([Vdc, V2p, V2n, abs(self.iq), 0.0, 0.0,
                      0.9 - V2p, iq_err, self.iq, *probs,
                      tfrac, float(in_fault_online), *self.last_a], np.float32)   # last_a is 3-D
        assert o.shape == (OBS_DIM_V2,), o.shape
        return np.clip(o, -5, 5)

    def _clip(self, a, gate):
        """Deployment clip on the 3-D action [iq, se_d, se_q]. Asym cap is tighter (2ω peak headroom)."""
        cap = C.IQ_CAP_ASYM if gate in ('asym', 'hvrt_asym') else C.IQ_CAP
        iq = float(np.clip(a[0], -cap, cap))
        se_d = float(np.clip(a[1], -C.SE_MAX, C.SE_MAX))
        se_q = float(np.clip(a[2], -C.SE_MAX, C.SE_MAX))
        clipped = (abs(a[0]) > cap + 1e-6) or (abs(a[1]) > C.SE_MAX + 1e-6) or (abs(a[2]) > C.SE_MAX + 1e-6)
        return iq, se_d, se_q, clipped, cap

    def predict(self, V2p, V2n, Vdc, gate, tfrac, in_fault_online):
        actor = self.experts['sym' if gate == 'normal' else gate]
        a, _ = actor.predict(self._obs(V2p, V2n, Vdc, tfrac, in_fault_online), deterministic=True)
        return np.asarray(a, np.float32)

    # ── one quasi-static time step: gate -> predict -> clip -> evolve Vdc ─────────
    def step(self, V2p, V2n, t, in_fault=None, dt=C.DT_SNAP):
        # NOTE: `in_fault` is accepted for API back-compat but IGNORED — the in_fault flag and the
        # elapsed fraction are DE-PRIVILEGED (derived from the online detector on measured V2p/V2n).
        V2p_m, V2n_m = self._measure(V2p, V2n)          # measurement noise/delay on gate+obs inputs
        gate = self.step_gate(V2p_m, V2n_m, t)
        faulted, tfrac = self._detect(V2p_m, V2n_m, t)
        a = self.predict(V2p_m, V2n_m, self.Vdc, gate, tfrac, faulted)
        iq, se_d, se_q, clipped, cap = self._clip(a, gate)
        se_d, se_q, _ = self._project_safety(iq, se_d, se_q, V2p)     # safety projection (Vdc)
        iq, se_d, se_q = self._apply_slew(iq, se_d, se_q)             # slew rate limit
        self.iq = iq
        veq = C.vdc_eq(iq, se_d, se_q, max(0.05, V2p))
        veq = min(C.VDC_CHOP, max(C.VDC_FLOOR, veq))
        # first-order relax toward equilibrium over dt (sub-stepped)
        nsub = 5
        h = dt / nsub
        for _ in range(nsub):
            self.Vdc += (veq - self.Vdc) * (h / C.DC_TAU)
            self.Vdc = min(C.VDC_CHOP, max(C.VDC_FLOOR, self.Vdc))
        self.last_a = np.array([iq, se_d, se_q], np.float32)
        return dict(gate=gate, iq=iq, se_d=se_d, se_q=se_q, iq_ref=iq_ref_gbt(V2p),
                    Vdc=self.Vdc, vdc_eq=veq, clipped=clipped, cap=cap)

    # ── steady command at a held sag (Vdc fixed point) — for OOD sweep / fixed point ──
    def steady_command(self, V2p, V2n, fault_type=None, iters=6):
        """Reset device state and iterate the Vdc surrogate to its fixed point at a HELD sag.
        Used for the network coupling fixed point and the static OOD sweep."""
        self.Vdc, self.iq, self.last_a = 1.0, 0.0, np.zeros(N_ACT_V2, np.float32)
        # gate + in_fault are determined by the held (V2p,V2n); a held sag has no elapsed time, so a
        # representative mid-fault tfrac is used (STEADY_TFRAC) — a documented static-analysis choice.
        gate = gate_raw(V2p, V2n)
        faulted = is_fault_measured(V2p, V2n)
        last = None
        proj = 0.0
        for _ in range(iters):
            a = self.predict(V2p, V2n, self.Vdc, gate, self.STEADY_TFRAC, faulted)
            iq, se_d, se_q, clipped, cap = self._clip(a, gate)
            se_d, se_q, proj = self._project_safety(iq, se_d, se_q, V2p)   # safety projection (Vdc)
            self.iq = iq
            veq = min(C.VDC_CHOP, max(C.VDC_FLOOR, C.vdc_eq(iq, se_d, se_q, max(0.05, V2p))))
            self.Vdc = veq                                  # held-sag equilibrium
            self.last_a = np.array([iq, se_d, se_q], np.float32)
            last = dict(gate=gate, iq=iq, se_d=se_d, se_q=se_q, iq_ref=iq_ref_gbt(V2p),
                        Vdc=self.Vdc, clipped=clipped, cap=cap, se_proj=proj)
        return last

    # ── chattering summary ───────────────────────────────────────────────────────
    def gate_stats(self):
        hist = self.gate_hist
        n = len(hist)
        # chattering = a gate flips back and forth within a short window (A->B->A)
        flips = sum(1 for i in range(2, n) if hist[i] == hist[i - 2] and hist[i] != hist[i - 1])
        return dict(n_steps=n, switches=self.switch_count,
                    first_switch_t=self.first_switch_t,
                    back_and_forth=flips,
                    chattering=bool(flips >= 2 or self.switch_count > 4),
                    classes=sorted(set(hist)))
