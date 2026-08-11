# SAC-Main Debug and Improvement Plan

Date: 2026-07-28

## Direction Correction

The main research line is SAC, not DAgger.  DAgger/BC may be used as:

- a diagnostic baseline;
- an initialization source;
- an ablation row;
- a support dataset for conservative SAC.

They are not the claimed final algorithm.  The claimed controller should be a
SAC-updated actor whose improvement is validated in switch-level Simulink.

## Current Failure Evidence

Stage-7 topology2 LVRT family raw SAC failed in a way that is too severe to
ignore:

- curriculum: `topology2_lvrt_family_v1`, 36 proxy scenarios;
- init actor: accepted topology2 AB-LVRT SAC specialist;
- training: 30k proxy SAC steps;
- proxy result: mean return around `-5.49e15`, `min_vdc_pu ~= 0.424`;
- behavior anchor MSE remained large, about `0.64-0.92` per action dimension;
- switch-level spot case `topology2 balanced LVRT 0.90 pu / 60 ms` collapsed:
  LV mean about `76.6 V`, Vdc min about `664 V`, max action about `1.131`,
  voltage-survival failed.

This is a SAC-system problem, not simply a missing-teacher problem.

## Hypotheses to Test

### H1: Critic / Q-value Instability

Symptoms:

- enormous negative returns;
- unstable actor movement despite behavior anchoring;
- plain two-critic SAC may not be enough for the family proxy.

Fix direction:

- REDQ-style critic ensemble;
- lower learning rate and UTD schedule;
- target-Q clipping / reward normalization;
- explicit critic-loss and Q-value diagnostics.

### H2: OOD Action and Support Violation

Symptoms:

- switch-level `max|a|` exceeded the accepted action envelope;
- family SAC moved away from switch-supported actions.

Fix direction:

- BRAC-style behavior regularization inside the actor loss;
- CQL-style conservative Q penalty for out-of-support actions;
- calibrated support classifier as a cost, not only a scalar reward penalty.

### H3: Proxy Exploitation / Model Bias

Symptoms:

- proxy training can report improvement-like behavior while switch-level
  validation collapses;
- energy/DC-link dynamics remain the highest-risk mismatch.

Fix direction:

- MOPO-style uncertainty penalty using proxy ensemble disagreement;
- COMBO/CQL-style conservative value penalty when uncertainty is unreliable;
- holdout action-response and trajectory-response alignment before promotion.

### H4: Constraint Handling Is Too Soft

Symptoms:

- reward penalties did not prevent voltage/DC/action failures;
- switch-level pass requires hard timestep envelope constraints.

Fix direction:

- constrained SAC with separate cost critics:
  - `J_env`: voltage-envelope cost;
  - `J_rec`: recovery-envelope cost;
  - `J_vdc`: DC-link survival cost;
  - `J_act`: action-limit/support cost;
- SAC-Lagrangian or WCSAC-style safety critic;
- PCPO/Lyapunov-style action projection during training and deployment.

### H5: Partial Observability Across Fault Phases

Symptoms:

- a family actor needs different actions before, during, and after the fault;
- raw SAC may not infer phase state reliably from instantaneous observations.

Fix direction:

- keep online detector features;
- add short observation history or recurrent SAC as a later experiment;
- log fault-onset/clear/recovery classification errors separately from actor
  errors.

### H6: Reg/Energy Coupling Is Poorly Conditioned

Symptoms:

- topology2 failures often involve recovery/DC-link behavior;
- one actor head over four actions can trade voltage and energy poorly.

Fix direction:

- keep split-head architecture:
  - `reg_head`: `[m_reg_d, m_reg_q]`;
  - `energy_head`: `[m_energy_d, m_energy_q]`;
- use separate critic-cost attribution for reg and energy actions;
- add per-head action scales and residual bounds.

## SAC-Main Algorithm Candidate

Working name:

```text
HPT-C2SAC: Conservative Constrained Soft Actor-Critic for HPT Voltage Survival
```

The actor update remains SAC:

```text
min_pi  E_s[ alpha log pi(a|s) - Q_reward(s,a) ]
```

but the update is modified by conservative and constrained terms:

```text
L_actor =
    E_s[ alpha log pi(a|s) - Q_reward(s,a) ]
  + lambda_env * E_s[C_env(s,a)]
  + lambda_vdc * E_s[C_vdc(s,a)]
  + lambda_act * E_s[C_act(s,a)]
  + beta_brac * D(pi(.|s), pi_support(.|s))
```

The critic side uses:

- reward critic ensemble `Q_i`;
- cost critics for envelope, Vdc, and action support;
- optional conservative Q penalty on sampled OOD actions;
- optional model-bias penalty from proxy ensemble disagreement.

## Experimental Sequence

### Step 1: SAC Instrumentation

Add diagnostics to the SAC runner:

- actor loss;
- critic loss;
- entropy temperature alpha;
- mean/std/min/max Q values;
- action support distance;
- projected versus raw action;
- per-cost episode sums;
- proxy uncertainty if available.

Success: raw SAC failure can be explained numerically, not just observed at the
switch-level gate.

### Step 2: Reward and Cost Refactor

Separate reward from constraints:

- reward: tracking quality and score improvement;
- costs: envelope, recovery, Vdc, current/action/support.

Do not hide hard constraints inside one large negative reward.  Keep them as
logged cost signals that can drive Lagrange multipliers or a safety critic.

Success: one run produces interpretable `reward_return` and `cost_return_*`
curves.

### Step 3: Conservative / Behavior-Regularized SAC

Implement two SAC variants:

1. `BRAC-SAC`: actor loss includes distance to switch-supported action density.
2. `CQL-SAC`: critic loss penalizes high Q on sampled OOD actions.

Support data comes from switch-level accepted specialists, calibration sweeps,
and successful SAC chunks.  This is not DAgger as main method; it is support
regularization for SAC.

Success: action-limit violations and proxy-OOD actions drop without eliminating
SAC exploration.

### Step 4: Constrained SAC

Implement SAC-Lagrangian / WCSAC-style update:

- train cost critics for envelope, recovery, Vdc, action/support;
- update Lagrange multipliers from cost violations;
- optionally use CVaR/worst-case cost for timestep envelope.

Success: switch-level candidates stop failing by envelope/Vdc/action limits
even if score improvement is modest.

### Step 5: Proxy-Bias-Aware SAC

Train or reuse an ensemble proxy:

- predict LV RMS, Vdc, envelope violation, recovery violation;
- compute ensemble disagreement;
- penalize actions with high disagreement in the SAC reward or critic target.

Success: proxy-winning but Simulink-failing actions are rejected earlier.

### Step 6: Switch-Level Promotion Loop

For every SAC chunk:

1. run proxy validation;
2. reject if cost or OOD is high;
3. run switch-level spot promotion;
4. only expand to family matrix after spot pass.

Promotion target:

- first: topology2 LVRT family;
- then: topology1 unbalanced score optimization;
- then: HVRT expansion.

## Near-Term Concrete Run Plan

1. Create a SAC diagnostics report from the failed Stage-7 raw family run.
2. Add SAC loss/Q/action-support logging to `train_hpt_voltage_sac.py`.
3. Run a 3k-step diagnostic replay on `topology2_lvrt_family_v1` with:
   - low learning rate;
   - action projection on;
   - behavior regularization logged but not yet enforced.
4. Implement `BRAC-SAC` actor penalty and rerun 3k/10k pilots.
5. Implement cost critics or Lagrangian penalties for envelope/Vdc/action.
6. Compare:
   - plain SAC;
   - protected SAC micro;
   - BRAC-SAC;
   - constrained SAC;
   - conservative + constrained SAC.

## Success Definition

The method is allowed to use support data and initialization, but it is
successful only if:

- the final actor has been updated by SAC;
- SAC reward/cost curves are logged;
- switch-level voltage-survival passes;
- the score improves over conventional and over the initialization on at least
  one boundary/family matrix;
- proxy-only improvement is never used as final evidence.

## Local References

- `references/week8_sac_main/`
- `references/week8_family_sac/`
