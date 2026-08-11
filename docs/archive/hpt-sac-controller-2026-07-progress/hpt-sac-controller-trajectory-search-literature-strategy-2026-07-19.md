# HPT SAC Trajectory Search Literature Strategy

Date: 2026-07-19

## Research Question

Can we let SAC directly search for a switch-level FRT trajectory that passes the
voltage envelope, DC-link, current-limit, and recovery constraints?

Short answer: yes, but the literature strongly suggests doing it through a
staged trajectory-search/offline-RL pipeline rather than raw model-free SAC
directly inside switch-level Simulink.

## Relevant Literature

### 1. Model-based trajectory search under limited expensive rollouts

- PETS: Chua et al., "Deep Reinforcement Learning in a Handful of Trials using
  Probabilistic Dynamics Models", NeurIPS 2018.
  https://arxiv.org/abs/1805.12114
  - Uses probabilistic ensembles and trajectory sampling.
  - Relevant because our switch-level Simulink rollouts are expensive and the
    proxy must carry uncertainty.

- MBPO: Janner et al., "When to Trust Your Model: Model-Based Policy
  Optimization", NeurIPS 2019.
  https://arxiv.org/abs/1906.08253
  - Uses short model rollouts branched from real data to limit model-bias
    accumulation.
  - Relevant because our proxy is reliable near calibrated fixed-action data but
    not yet over long dynamic action trajectories.

- CEM/trajectory optimization for MPC:
  Bharadhwaj et al., "Model-Predictive Control via Cross-Entropy and
  Gradient-Based Optimization", L4DC 2020.
  https://arxiv.org/abs/2004.08763
  - Interleaves sampling-based search with gradient-style refinement.
  - Relevant because our first search can optimize trajectory parameters
    rather than every 2-ms action directly.

- Safe trajectory sampling in MBRL:
  Zwane et al., "Safe Trajectory Sampling in Model-based Reinforcement
  Learning", IEEE CASE 2023.
  https://www.deisenroth.cc/publication/zwane-2023/
  - Explicitly evaluates sampled trajectories against safety constraints.
  - Relevant because our pass/fail is inherently trajectory-level:
    every timestep must respect the envelope.

### 2. Offline RL / behavior-constrained RL to avoid proxy exploitation

- TD3+BC: Fujimoto and Gu, "A Minimalist Approach to Offline Reinforcement
  Learning", NeurIPS 2021.
  https://arxiv.org/abs/2106.06860
  - Adds behavior cloning to actor updates.
  - Relevant because we need SAC/actor updates to stay near validated
    switch-level trajectory data.

- IQL: Kostrikov et al., "Offline Reinforcement Learning with Implicit
  Q-Learning", 2021.
  https://arxiv.org/abs/2110.06169
  - Avoids evaluating out-of-dataset actions during policy improvement.
  - Relevant because our current failures are strongly tied to OOD actions and
    proxy mismatch outside calibrated support.

- AWAC: Nair et al., "Accelerating Online Reinforcement Learning with Offline
  Datasets", 2020.
  https://arxiv.org/abs/2006.09359
  - Uses offline data to initialize and then fine-tune.
  - Relevant because validated Simulink trajectories can seed online SAC
    fine-tuning in the proxy.

- BRAC: Wu et al., "Behavior Regularized Offline Reinforcement Learning",
  2019.
  https://arxiv.org/abs/1911.11361
  - Regularizes learned policy toward behavior data.
  - Relevant to our need for explicit action-support constraints.

- CQL: Kumar et al., "Conservative Q-Learning for Offline Reinforcement
  Learning", NeurIPS 2020.
  https://arxiv.org/abs/2006.04779
  - Learns conservative Q-values to avoid overestimating unseen actions.
  - Relevant as a conservative baseline when the dataset is mixed-quality.

### 3. Model-based offline RL with uncertainty penalties

- MOPO: Yu et al., "MOPO: Model-based Offline Policy Optimization", NeurIPS
  2020.
  https://arxiv.org/abs/2005.13239
  - Penalizes reward by learned model uncertainty.
  - Directly addresses the "SAC exploits proxy errors" failure mode.

- MOReL: Kidambi et al., "MOReL: Model-Based Offline Reinforcement Learning",
  NeurIPS 2020.
  https://arxiv.org/abs/2005.05951
  - Builds a pessimistic MDP from offline data.
  - Relevant because unsafe/OOD trajectory branches should terminate into a bad
    absorbing state.

- COMBO: Yu et al., "Conservative Offline Model-Based Policy Optimization",
  NeurIPS 2021.
  https://proceedings.neurips.cc/paper/2021/file/f29a179746902e331572c483c45e5086-Paper.pdf
  - Notes that uncertainty estimates can be unreliable and uses conservative
    model-based value learning.
  - Relevant because our proxy looks accurate on matrix points but can still be
    misleading on dynamic trajectories.

### 4. Safe/constrained RL

- CPO: Achiam et al., "Constrained Policy Optimization", ICML 2017.
  https://arxiv.org/abs/1705.10528
  - Treats safety as constraints, not only reward penalties.
  - Relevant to full FRT criteria: envelope, current limit, and DC-link survival
    should be constraints.

- Shielded RL: Alshiekh et al., "Safe Reinforcement Learning via Shielding",
  AAAI 2018.
  https://arxiv.org/abs/1708.08611
  - Runtime shield blocks or corrects unsafe actions.
  - Relevant because final deployment may need an action shield even if SAC is
    the main controller.

- Safe RL for power systems review:
  Yu et al., "Safe Reinforcement Learning for Power System Control: A Review",
  2024.
  https://arxiv.org/abs/2407.00681
  - Summarizes why random exploration is dangerous in power systems and why
    safety layers/constrained RL matter.

### 5. Power/electronics voltage and FRT RL evidence

- Fathollahi et al., "Improving Voltage Ride-Through Procedures in Distributed
  Generation Systems by Reinforcement Learning", 2024.
  https://upcommons.upc.edu/bitstreams/cbd2e06d-57e3-4acc-9c72-33134fd71761/download
  - Uses RL for voltage perturbation / ride-through response.
  - Relevant as a domain precedent, though much simpler than our switch-level
    HPT.

- DRL inverter tuning with Simulink acceleration:
  "Deep Reinforcement Learning for Optimizing Inverter Control", 2024.
  https://arxiv.org/html/2411.01451v1
  - Uses a Simulink-developed inverter model converted to faster execution for
    RL.
  - Relevant because our main bottleneck is high-fidelity simulation cost.

## What This Means for Our HPT Problem

Our failure mode matches the literature:

1. Raw model-free SAC is too sample-expensive for switch-level Simulink.
2. A fixed-action calibrated proxy can rank fixed actions well but can be
   exploited or misused for dynamic trajectories.
3. Safety is trajectory-level; a single timestep envelope violation can fail the
   run, so the controller objective cannot be only average voltage reward.
4. Teacher/candidate data are still useful, but only if the teacher is a
   switch-level validated trajectory teacher, not a fixed-action table row.

## Recommended Next Strategy

### Stage A: Parameterized trajectory search

Use CEM/PETS-style search over a low-dimensional trajectory parameter vector:

```text
theta = [
  reg_d_pre, reg_d_boost, reg_d_hold, reg_d_recovery,
  reg_q_fault, reg_q_recovery,
  energy_d_fault, energy_d_recovery,
  energy_q_fault, energy_q_recovery,
  ramp_in_ms, hold_after_clear_ms, taper_ms
]
```

Evaluate candidates first in the calibrated proxy with uncertainty/OOD penalty,
then promote only the best few to switch-level Simulink.

### Stage B: Build a trajectory dataset

For every validated candidate, store the full 2-ms sequence:

```text
(obs_t, action_t, next_obs_t, reward_t, constraint_t, pass/fail labels)
```

Keep both command and measured/effective action fields:

```text
cmd_m_reg_d, cmd_m_reg_q, cmd_m_energy_d, cmd_m_energy_q
meas_reg_d, meas_reg_q, meas_energy_d, meas_energy_q
```

### Stage C: Train offline specialists before SAC fine-tuning

Train per topology / per fault family:

1. BC warm start from successful trajectory data.
2. TD3+BC or IQL as the first offline RL baselines.
3. SAC/AWAC fine-tuning in proxy with:
   - behavior regularization;
   - ensemble uncertainty penalty;
   - OOD action penalty;
   - hard constraint/shield for action and DC-link limits.

### Stage D: Switch-level promotion gate

Only promote a controller if it passes switch-level tests:

- no timestep voltage-envelope violation beyond selected tolerance/window;
- no recovery-envelope violation;
- DC link within bounds;
- grid current within limit;
- reactive-current requirement satisfied;
- better control score than strong conventional baseline.

## Immediate Implementation Plan

1. Add a trajectory-parameter generator:
   `sac/search_hpt_frt_trajectory_cem.py`.
2. Start with topology1, sag_0p90, 60 ms:
   - use `fault_settle_s = 0.02` only for research;
   - keep strict `fault_settle_s = 0.0` as the certification target.
3. Search joint reg + energy trajectory parameters.
4. Validate top candidates with `validate_hpt_trajectory_switchlevel.py`.
5. Convert successful trajectories into a dataset.
6. Train BC/TD3+BC/IQL specialist actors on that dataset.
7. Fine-tune with SAC only after trajectory-level data exists.

## Decision

Do not continue blind timestep SAC yet.  The next useful experiment is
trajectory-parameter search with switch-level validation, followed by offline
specialist training from successful trajectories.
