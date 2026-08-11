"""residual_env.py — environment for canonical Mode 6 (MPC-assisted residual SAC), the EXTENSION
(NOT the main method, NOT pure SAC; main method = Mode 5, frt_env.py). Internal HLC dispatch mi==14.
Action = MPC closed-form prior + bounded residual. Canonical naming per CONTROL_MODES.md.

ACTION INTERFACE: structurally 3-D — the vestigial dim 0 is bounded to ~0 (upper bound 0.01) and
zeroed in step(), so the train/deploy interface is consistent (no 4-D-vs-3-D mismatch), unlike the
Mode 3/5 frt_env.py which carries a vestigial 4th dim.

Literature basis: residual RL with a model-based prior (Residual-MPC'25, Residual-MPPI ICLR'25):
the prior provides a safe floor (here: the mode-8 analytic MPC, 79.7% full-320), the policy
learns only the residual — concentrating capacity on what the equilibrium model cannot express
(asymmetric 2ω dynamics, per-condition fine-tuning).

ONE policy for ALL 320 scenarios (the prior handles domain logic; tests whether the 4-expert
split is still needed once a strong prior exists).

Also adds the criteria-aligned connect-margin reward (the one criterion the base reward missed).
"""
from __future__ import annotations
import numpy as np
from gymnasium import spaces
from .frt_env import HPTFRTEnv, V_SE_MAX, I_Q_MAX, ASYM_IQ_MEAS_BIAS, effective_fault_dur, TSCALE
from .frt_env_v2 import HPTFRTEnvV2, N_ACT_V2

IQ_CAP   = 0.27          # total reactive cap (headroom rule, symmetric faults)
IQ_CAP_HVRT_RECOVER = I_Q_MAX  # symmetric HVRT post-clear fallback may use the physical 0.30 pu limit
IQ_CAP_ASYM = 0.24       # tighter cap on asymmetric faults: measured peak ≈ cmd × k_2ω (k≈1.3-1.4
                         # from m14-v1 forensics: sustained 0.27 cmd broke the 0.35 measured-peak
                         # limit on 1ph_g) — the ODE cannot see measurement ripple, so the limit
                         # criterion is enforced via this calibrated command-level cap instead.
RES_IQ   = 0.10          # residual authority on iq (pu)
RES_MSE  = 0.06          # residual authority on series d/q
ASYM_IQ_FF_GAIN = 1.20   # V2n feed-forward margin over the measured-iq bias proxy
ASYM_IQ_FF_EPS = 0.003

ASYM_FT = ('1ph_g', '2ph', '2ph_g')


def mpc_prior(V2p, Vdc):
    """Mode-8 analytic MPC law in ODE conventions (V_se_d>0 = boost). Returns 4-vector."""
    if V2p < 0.9:
        iq = min(IQ_CAP, 1.5 * (0.9 - V2p))
        sag_iq = 0.08 * iq / max(0.3, V2p)
        mb = min(0.2, max(0.0, (1.0 - 0.82 - sag_iq) / 1.9))
        fb = min(1.0, max(0.0, (Vdc - 0.80) / 0.04))      # measured-Vdc receding feedback
        return np.array([0.0, iq, mb * fb, 0.0], np.float32)
    if V2p > 1.1:
        iq = max(-IQ_CAP, -1.5 * (V2p - 1.1))
        mb = -min(0.2, 1.5 * (V2p - 1.1))                 # anti-boost (negative V_se_d)
        return np.array([0.0, iq, mb, 0.0], np.float32)
    return np.zeros(4, np.float32)


def mpc_prior3(V2p, Vdc):
    """Mode-8 analytic MPC law as the frt-v2 3-D vector [iq, mse_d, mse_q] (drops the vestigial i_d)."""
    p4 = mpc_prior(V2p, Vdc)
    return np.array([p4[1], p4[2], p4[3]], np.float32)


class HPTFRTResidualEnvV2(HPTFRTEnvV2):
    """frt-v2 RESIDUAL env (audit round-4 C.2): inherits the 3-D action + 20-D DE-PRIVILEGED obs +
    VERSIONED trip envelope from HPTFRTEnvV2 (NOT the legacy 4-D/21-D contract). The agent outputs a
    bounded 3-D residual [iq, mse_d, mse_q] on the analytic MPC prior."""

    def __init__(self, scenarios, seed=0, train_mode=True):
        super().__init__(scenarios, seed=seed, train_mode=train_mode)
        self.action_space = spaces.Box(
            low=np.array([-RES_IQ, -RES_MSE, -RES_MSE], np.float32),
            high=np.array([RES_IQ, RES_MSE, RES_MSE], np.float32))

    def step(self, action):
        res = np.asarray(action, np.float32).reshape(N_ACT_V2)
        tot = mpc_prior3(self.V2p, self.Vdc) + res
        cap = IQ_CAP_ASYM if (self._sc['category'] == 'LVRT'
                              and self._sc['fault_type'] in ASYM_FT) else IQ_CAP
        clear_t = float(self._sc['t_fault']) + effective_fault_dur(self._sc) * TSCALE
        hvrt_recover_window = (
            self._sc['category'] == 'HVRT'
            and self._sc['fault_type'] == 'swell_3ph'
            and self.t > clear_t
            and self.V2n <= 0.025
            and 0.90 <= self.V2p < 0.97
        )
        if hvrt_recover_window:
            cap = IQ_CAP_HVRT_RECOVER
        if (self._sc['category'] == 'LVRT' and self._sc['fault_type'] in ASYM_FT
                and self.V2n > 0.05 and self.V2p < 1.10):
            # The averaged plant's measured-iq proxy includes a negative-sequence bias. A small
            # V2n feed-forward floor keeps the MPC prior from entering the frt-v2 wrong-sign region;
            # the learned residual still tunes voltage/DC trade-offs around that floor.
            tot[0] = max(tot[0], ASYM_IQ_FF_GAIN * ASYM_IQ_MEAS_BIAS * self.V2n + ASYM_IQ_FF_EPS)
        tot[0] = float(np.clip(tot[0], -cap, cap))            # iq
        tot[1] = float(np.clip(tot[1], -V_SE_MAX, V_SE_MAX))  # mse_d
        tot[2] = float(np.clip(tot[2], -V_SE_MAX, V_SE_MAX))  # mse_q
        obs, r, done, trunc, info = super().step(tot)
        s = self._sc
        if s['category'] == 'LVRT':
            in_fault = s['t_fault'] <= self.t <= s['t_fault'] + effective_fault_dur(s) * 0.20
            if in_fault:
                r += -8.0 * max(0.0, float(s['target_V_pu']) - 0.02 - self.V2p)
        return obs, float(r), done, trunc, info


class HPTFRTResidualSwitchingAwareEnvV2(HPTFRTResidualEnvV2):
    """Residual env with switching-informed reward shaping.

    This is an experimental training env for the ODE-blind Simulink failures found in the selected
    switching spotcheck. It keeps the same observation/action contract as HPTFRTResidualEnvV2, but
    adds penalties for DC-link survival margin and post-clear recovery overshoot/undershoot that the
    averaged ODE otherwise under-represents.
    """

    LVRT_RECOVER_HIGH = 1.03
    HVRT_RECOVER_LOW = 0.97

    def step(self, action):
        obs, r, done, trunc, info = super().step(action)
        s = self._sc
        dur = effective_fault_dur(s) * TSCALE
        t_clear = float(s["t_fault"]) + dur
        post = self.t > t_clear
        post_win = post and self.t <= t_clear + 0.35 * TSCALE
        in_fault = float(s["t_fault"]) <= self.t <= t_clear

        sid = int(s.get("scenario_id", -1))
        ft = str(s["fault_type"])
        cat = str(s["category"])
        scr = float(s["scr"])
        target = float(s["target_V_pu"])
        vdc = float(info["Vdc"])
        v = float(info["V2p"])
        iq = float(info["iq"])
        mse_d = float(info["mse_d"])
        mse_q = float(info["mse_q"])

        # Hard switching failures get stronger pressure; the same terms still apply softly elsewhere.
        hard_lvrt = cat == "LVRT" and ft == "sym3ph" and scr >= 8.0 and 0.45 <= target <= 0.55
        hard_hvrt = cat == "HVRT" and ft in ("swell_3ph", "swell_1ph")
        weight = 3.0 if (hard_lvrt or hard_hvrt or sid in {225,226,227,228,233,234,235,236,237,238,239,240,
                                                           1441,1456,1500,1873,1875}) else 1.0

        penalty = 0.0
        if in_fault and hard_lvrt:
            # Do not let the switching-aware terms teach the policy to "solve" Vdc by abandoning
            # ride-through support. Smoke A-0 showed this failure mode immediately.
            floor = target + 0.005
            penalty += weight * 260.0 * max(0.0, floor - v) ** 2
            min_iq = max(0.0, 1.5 * (0.9 - v) - 0.12)
            penalty += weight * 18.0 * max(0.0, min_iq - iq) ** 2
            # The switching hard24 cases are exactly where positive series boost buys voltage at the
            # cost of DC-link collapse. Bias the policy toward the conservative passing family:
            # reactive support first, little/no positive series boost.
            penalty += weight * 55.0 * max(0.0, mse_d) ** 2

        # Switching survive margin: the Simulink failures appeared near/under 0.75, so train away from
        # the cliff and discourage positive series boost when the DC bus is already weak.
        penalty += weight * 120.0 * max(0.0, 0.78 - vdc) ** 2
        if in_fault and mse_d > 0.0:
            penalty += weight * 80.0 * max(0.0, 0.82 - vdc) * mse_d

        if in_fault and hard_hvrt:
            # Preserve HVRT absorption: the first A runs could trade away reactive absorption while
            # improving other proxy terms, which is not acceptable for frt-v2.
            demand = max(0.0, v - 1.1)
            if demand > 0.0:
                target_absorb = min(0.27, 1.5 * demand)
                penalty += weight * 30.0 * max(0.0, target_absorb + iq) ** 2

        if post_win and hard_lvrt:
            # Remaining hard24 switching failures recover high: V+ settles around 1.08-1.09. Penalize
            # post-clear over-voltage, lingering boost, and unnecessary reactive support after the event.
            over = max(0.0, v - self.LVRT_RECOVER_HIGH)
            penalty += weight * 160.0 * over ** 2
            penalty += weight * 10.0 * max(0.0, mse_d)
            penalty += weight * 4.0 * abs(mse_q)
            if v > 1.07:
                penalty += weight * 5.0 * max(0.0, iq)

        if post_win and hard_hvrt:
            # Selected HVRT failures split by recovery direction. Penalize whichever side leaves the
            # final band and keep the fix DC-aware.
            low = max(0.0, self.HVRT_RECOVER_LOW - v)
            high = max(0.0, v - 1.03)
            penalty += weight * 120.0 * low ** 2
            penalty += weight * 120.0 * high ** 2
            if low > 0.0 and vdc > 0.79:
                penalty += weight * 6.0 * max(0.0, -mse_d)
            if high > 0.0:
                penalty += weight * 6.0 * max(0.0, mse_d)

        return obs, float(r - penalty), done, trunc, info


class HPTFRTResidualEnv(HPTFRTEnv):
    """LEGACY frt-v1 residual env (4-D action / 21-D obs / privileged label obs / legacy envelope).
    Kept only for `--legacy` reproduction; new training uses HPTFRTResidualEnvV2. Do NOT use for P3."""

    def __init__(self, scenarios, seed=0, train_mode=True):
        super().__init__(scenarios, seed=seed, train_mode=train_mode)
        # dim 0 (i_sh_d) is dead in deployment; keep a tiny nonzero width to avoid divide-by-zero
        # in SB3's action scaling.
        self.action_space = spaces.Box(
            low=np.array([0.0, -RES_IQ, -RES_MSE, -RES_MSE], np.float32),
            high=np.array([0.01, RES_IQ,  RES_MSE,  RES_MSE], np.float32))

    def step(self, action):
        res = np.asarray(action, np.float32)
        pri = mpc_prior(self.V2p, self.Vdc)
        tot = pri + res
        # asym-aware reactive cap (deployment mirror: HLC clips at 0.24 when V2n>0.05 & V2p<0.9)
        cap = IQ_CAP_ASYM if (self._sc['category'] == 'LVRT'
                              and self._sc['fault_type'] in ASYM_FT) else IQ_CAP
        if (self._sc['category'] == 'LVRT' and self._sc['fault_type'] in ASYM_FT
                and self.V2n > 0.05 and self.V2p < 1.10):
            tot[1] = max(tot[1], ASYM_IQ_FF_GAIN * ASYM_IQ_MEAS_BIAS * self.V2n + ASYM_IQ_FF_EPS)
        tot[1] = float(np.clip(tot[1], -cap, cap))
        tot[2] = float(np.clip(tot[2], -V_SE_MAX, V_SE_MAX))
        tot[3] = float(np.clip(tot[3], -V_SE_MAX, V_SE_MAX))
        tot[0] = 0.0                                        # i_sh_d unused (discarded in Simulink)
        obs, r, done, trunc, info = super().step(tot)
        # criteria-aligned connect margin (the criterion the base reward missed): during an LVRT
        # fault keep V2p at/above the calibrated target tV (reference) with a small margin.
        s = self._sc
        if s['category'] == 'LVRT':
            in_fault = s['t_fault'] <= self.t <= s['t_fault'] + effective_fault_dur(s) * 0.20
            if in_fault:
                r += -8.0 * max(0.0, float(s['target_V_pu']) - 0.02 - self.V2p)
        return obs, float(r), done, trunc, info
