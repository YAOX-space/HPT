"""residual_expert_env.py — env for the NEW 4-expert + residual SAC (pure-learning hybrid).

PRIOR = online-gated specialist expert output (the frozen Mode-5 experts, train_experts.py); the
agent learns ONE bounded GLOBAL residual on top. Unlike Mode 6 (residual on the ANALYTIC MPC prior,
residual_env.py), the prior here is the 4-expert ensemble — so the controller stays PURE LEARNING
(no analytic MPC) while gaining the residual's cross-domain correction. Intended as a new canonical
mode (HLC dispatch mi==17 — mi==16 is already the deployment-projected mode-14) and a candidate MAIN
METHOD.

Design (locked 2026-06-25, see docs/RESIDUAL_EXPERT_PLAN_2026-06-25.md):
  total = clip( gated_expert(obs) + residual(obs) )      # experts FROZEN, only the residual learns
  gate  = gate_to_expert(V2p,V2n)  — IDENTICAL to deployment network/sac_wrapper.gate_raw
The de-privileged 3-D action + 20-D online observation + versioned trip envelope are inherited from
HPTFRTEnvV2 (so train==deploy on the interface). The same asym reactive cap as residual_env applies.

Expert loading is LAZY (first step) so env_contract / assert_fresh_contract can probe the spaces
without loading any SB3 model. Pass `experts=` (a shared dict) to avoid 8× reloads under DummyVecEnv.

NOTE (training fidelity, see plan): the ODE is structurally blind to the swell_3ph switching DC
undershoot (HVRT survive-FAIL) — anti-boost uses negative V_se_d so sag_se=0. The residual cannot
learn that failure from this env; it is handled at deployment (swell_1ph wrong-sign clip via
safety_projection) or accepted as a documented single-port limit. This env targets the LVRT/asym
fine-tuning + the reactive-sign correction the experts leave on the table.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
from gymnasium import spaces
from .frt_env import V_SE_MAX, TSCALE
from .frt_env_v2 import (HPTFRTEnvV2, N_ACT_V2, GATE_LV, GATE_HV, GATE_V2N_THR)
from .residual_env import IQ_CAP, IQ_CAP_ASYM, RES_IQ, RES_MSE, ASYM_FT

EXPERT_NAMES = ('sym', 'asym', 'hvrt_sym', 'hvrt_asym')
MODELS = Path(__file__).resolve().parents[3] / 'data' / 'models'   # repo_root/data/models


def gate_to_expert(V2p, V2n):
    """Online gate -> expert name. IDENTICAL to deployment network/sac_wrapper.gate_raw:
    HVRT band -> hvrt_{asym|sym} by V2n; LVRT band -> {asym|sym} by V2n; deadband 'normal' routes to
    the sym actor (as in deployment). Keep this in lockstep with gate_raw or train != deploy."""
    if V2p > GATE_HV:
        return 'hvrt_asym' if V2n > GATE_V2N_THR else 'hvrt_sym'
    if V2p < GATE_LV:
        return 'asym' if V2n > GATE_V2N_THR else 'sym'
    return 'sym'


def load_frozen_experts(device='cpu'):
    """Load the four frozen specialist actors (deterministic inference only)."""
    from stable_baselines3 import SAC
    experts = {}
    for n in EXPERT_NAMES:
        p = MODELS / f'sac_{n}_best.zip'
        if not p.exists():
            raise FileNotFoundError(f'expert weights missing: {p} — run train_experts.py first')
        experts[n] = SAC.load(str(p), device=device)
    return experts


class HPTFRTResidualExpertEnvV2(HPTFRTEnvV2):
    """frt-v2 RESIDUAL-ON-EXPERTS env: bounded 3-D residual on the online-gated frozen-expert prior.
    Inherits the 3-D action / 20-D de-privileged obs / versioned envelope from HPTFRTEnvV2."""

    def __init__(self, scenarios, seed=0, train_mode=True, experts=None):
        super().__init__(scenarios, seed=seed, train_mode=train_mode)
        self._experts = experts                      # None => lazy-load on first step (keeps probe cheap)
        # residual authority mirrors residual_env (Mode 6): ±0.10 iq, ±0.06 series
        self.action_space = spaces.Box(
            low=np.array([-RES_IQ, -RES_MSE, -RES_MSE], np.float32),
            high=np.array([RES_IQ, RES_MSE, RES_MSE], np.float32))

    def _expert_prior(self):
        """3-D prior = the gated frozen expert's deterministic action on the CURRENT de-privileged obs
        (the same obs the residual policy acted on this step)."""
        if self._experts is None:
            self._experts = load_frozen_experts()
        obs = self._obs()                            # idempotent detector update at current t (see frt_env_v2)
        name = gate_to_expert(self.V2p, self.V2n)
        a, _ = self._experts[name].predict(obs, deterministic=True)
        return np.asarray(a, np.float32).reshape(N_ACT_V2)

    def step(self, action):
        res = np.asarray(action, np.float32).reshape(N_ACT_V2)
        tot = self._expert_prior() + res
        cap = IQ_CAP_ASYM if (self._sc['category'] == 'LVRT'
                              and self._sc['fault_type'] in ASYM_FT) else IQ_CAP
        tot[0] = float(np.clip(tot[0], -cap, cap))            # iq
        tot[1] = float(np.clip(tot[1], -V_SE_MAX, V_SE_MAX))  # mse_d
        tot[2] = float(np.clip(tot[2], -V_SE_MAX, V_SE_MAX))  # mse_q
        obs, r, done, trunc, info = super().step(tot)
        s = self._sc
        if s['category'] == 'LVRT':                           # criteria-aligned connect margin (as Mode 6)
            in_fault = s['t_fault'] <= self.t <= s['t_fault'] + s['fault_dur'] * TSCALE
            if in_fault:
                r += -8.0 * max(0.0, float(s['target_V_pu']) - 0.02 - self.V2p)
        return obs, float(r), done, trunc, info
