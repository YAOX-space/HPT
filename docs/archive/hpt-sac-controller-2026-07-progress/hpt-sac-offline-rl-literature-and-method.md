# HPT SAC Literature-to-Method Note

Updated: 2026-07-17

## Problem Restatement

The final target is still a direct controller:

```text
observation -> actor -> [m_reg_d, m_reg_q, i_energy_d_ref_pu, i_energy_q_ref_pu]
```

The switch-level Simulink models are the source of truth.  The averaged proxy is
useful for fast experiments, but it must not be trusted as the final reward
source unless its action ranking is aligned with switch-level FRT metrics.

## Reference Groups

### Offline model-free RL

Local references:

- `references/week6/iql_implicit_q_learning_offline_rl_arxiv2110.06169.pdf`
- `references/week6/td3_bc_minimalist_offline_rl_arxiv2106.06860.pdf`
- `references/week6/cql_conservative_q_learning_offline_rl_neurips2020.pdf`
- `references/week6/bcq_off_policy_deep_rl_without_exploration_icml2019.pdf`

HPT use:

- Use IQL and TD3+BC as the first offline baselines from Simulink-labeled
  teacher/candidate data.
- Use CQL/BCQ as conservative comparisons when the dataset is narrow.
- These methods are appropriate when we trust the dataset labels more than the
  proxy dynamics.

### Model-based offline RL and uncertainty

Local references:

- `references/week6/pets_probabilistic_ensembles_trajectory_sampling_neurips2018.pdf`
- `references/week6/mopo_model_based_offline_policy_optimization_neurips2020.pdf`
- `references/week6/morel_model_based_offline_reinforcement_learning_neurips2020.pdf`
- `references/week6/combo_conservative_offline_model_based_policy_optimization_neurips2021.pdf`

HPT use:

- PETS gives the learned ensemble proxy pattern.
- MOPO/MOReL add pessimism for out-of-support actions and proxy uncertainty.
- COMBO is a later option when we mix real switch-level rows with model-generated
  rollouts.
- These are the right long-term tools once we have enough transition traces, not
  only fixed-action summary rows.

### SAC robustness variants

Local references:

- `references/week5/dsac_t_distributional_soft_actor_critic_three_refinements_arxiv2310.05858.pdf`
- `references/week5/dr_sac_distributionally_robust_soft_actor_critic_arxiv2506.12622.pdf`
- `references/week5/continuous_soft_actor_critic_time_discretization_neurips2025.pdf`

HPT use:

- DSAC-T is relevant for rare high-cost events such as DC-link collapse.
- DR-SAC is relevant to topology and proxy uncertainty.
- Continuous SAC is relevant to the mismatch between SAC decision periods and
  switch-level time steps.
- These improve SAC, but they do not replace the need for switch-level reward
  alignment.

## Selected Method For The Current Iteration

The immediate issue is reward misalignment, not only dynamics misalignment.
Therefore the current implementation uses a supervised reward-correction stage:

```text
scenario + action + proxy_metrics -> predicted switch-level reward correction
corrected_return = proxy_return + predicted_correction
```

Inputs:

- topology/category/mode;
- grid depth;
- raw and averaged regulating/energy commands;
- proxy LV/Vdc/reward signals.

Excluded from deployment-time features:

- proxy-vs-Simulink error columns;
- switch-level LV/Vdc/pass/fail outputs.

The correction model is trained from the reward-alignment detail table generated
from the switch-level FRT calibration matrix.  It is used to repair action
ranking before SAC/offline RL training.

## Why This Is Better Than Continuing Proxy SAC

Pure proxy SAC assumes that higher proxy reward means a better switch-level
action.  The current evidence disproves that assumption in several HVRT and
joint-action groups.

The correction stage directly learns the missing mapping from proxy action
features to switch-level reward-like labels.  It does not solve all dynamics
problems, but it gives the training pipeline a reward signal that is much closer
to the switch-level plant before we spend more SAC training time.

## Next Algorithm Path

1. Use reward correction to re-rank candidate actions and teacher actions.
2. Train per-topology/per-fault specialist actors from corrected teacher data.
3. Validate every candidate actor on switch-level Simulink.
4. When per-step transition traces are broad enough, train a PETS-style learned
   proxy ensemble.
5. Add MOPO/MOReL pessimism for synthetic rollouts.
6. Compare against IQL and TD3+BC on the same Simulink-labeled dataset.

The final controller remains a direct actor.  The correction model and learned
proxy are training tools, not deployment wrappers.
