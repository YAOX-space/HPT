# Week 7 Full-Action SAC Literature Bundle

Created: 2026-07-17

This folder collects the papers currently most relevant to the HPT v2 target:

```text
observation -> SAC actor -> [m_reg_d, m_reg_q, m_energy_d, m_energy_q]
```

The final controller should be a direct full-action actor.  Behavior cloning,
offline RL, trust-region updates, and model uncertainty are training tools, not
deployment wrappers.

## Files

| File | Source | Method family | Why it matters for HPT |
| --- | --- | --- | --- |
| `sac_maximum_entropy_deep_rl_arxiv1801.01290.pdf` | https://arxiv.org/pdf/1801.01290 | SAC | Base maximum-entropy actor-critic for continuous actions. |
| `sac_algorithms_and_applications_arxiv1812.05905.pdf` | https://arxiv.org/pdf/1812.05905 | SAC | More stable SAC formulation with automatic temperature tuning. |
| `td3_bc_minimalist_offline_rl_arxiv2106.06860.pdf` | local week6 copy | Offline RL | Simple behavior-cloning regularization for continuous-control offline data. |
| `iql_implicit_q_learning_offline_rl_arxiv2110.06169.pdf` | local week6 copy | Offline RL | Avoids evaluating unseen actions, useful when Simulink data are sparse. |
| `cql_conservative_q_learning_offline_rl_neurips2020.pdf` | local week6 copy | Conservative offline RL | Penalizes over-optimistic Q-values for out-of-distribution actions. |
| `bcq_off_policy_deep_rl_without_exploration_icml2019.pdf` | local week6 copy | Batch-constrained RL | Explicitly constrains actions to dataset support. |
| `brac_behavior_regularized_actor_critic_arxiv1911.11361.pdf` | https://arxiv.org/pdf/1911.11361 | Behavior-regularized RL | Direct template for keeping actor updates near trusted behavior data. |
| `awac_accelerating_online_rl_with_offline_datasets_arxiv2006.09359.pdf` | https://arxiv.org/pdf/2006.09359 | Offline-to-online RL | Uses advantage-weighted behavior cloning to warm-start online RL. |
| `sacr2_sac_with_reward_relabeling_arxiv2110.14464.pdf` | https://arxiv.org/pdf/2110.14464 | SAC with demonstrations | Uses demonstrations, behavior cloning loss, and reward relabeling ideas. |
| `trpo_trust_region_policy_optimization_arxiv1502.05477.pdf` | https://arxiv.org/pdf/1502.05477 | Trust-region policy optimization | Motivates limiting actor update size to avoid destructive jumps. |
| `cpo_constrained_policy_optimization_arxiv1705.10528.pdf` | https://arxiv.org/pdf/1705.10528 | Safe/constrained RL | Motivates treating Vdc, current, action bounds, and FRT gates as constraints. |
| `pets_probabilistic_ensembles_trajectory_sampling_neurips2018.pdf` | local week6 copy | Probabilistic model-based RL | Template for learned proxy ensembles and uncertainty. |
| `mopo_model_based_offline_policy_optimization_neurips2020.pdf` | local week6 copy | Pessimistic model-based offline RL | Penalizes model rollouts by uncertainty to reduce proxy exploitation. |
| `morel_model_based_offline_reinforcement_learning_neurips2020.pdf` | local week6 copy | Pessimistic model-based offline RL | Sends uncertain state-action regions to a pessimistic low-reward state. |
| `combo_conservative_offline_model_based_policy_optimization_neurips2021.pdf` | local week6 copy | Conservative model-based offline RL | Mixes model rollouts and real data while regularizing Q-values. |
| `dsac_t_distributional_soft_actor_critic_three_refinements_arxiv2310.05858.pdf` | local week5 copy | Distributional SAC | Relevant to rare severe costs such as Vdc collapse and current limit. |
| `dr_sac_distributionally_robust_soft_actor_critic_arxiv2506.12622.pdf` | local week5 copy | Distributionally robust SAC | Relevant to topology mismatch and parameter uncertainty. |
| `continuous_soft_actor_critic_time_discretization_neurips2025.pdf` | local week5 copy | Continuous-time SAC | Relevant to mismatch between SAC decision interval and switching-step simulation. |

Text extraction for searchable reading is under `extracted_text/`.  Page counts
and extracted text paths are recorded in `manifest.json`.

## Reading Conclusions For This Project

1. SAC is still a reasonable final controller form because the action is
   continuous and coupled across regulating and energy bridges.
2. Plain SAC is not enough here.  Our previous experiments already showed actor
   drift away from the calibrated action support and poor switch-level results.
3. The offline RL papers agree on the same practical point: when data are
   limited and out-of-distribution actions are risky, policy improvement needs
   behavior constraints, conservative Q-values, or pessimism.
4. The model-based offline RL papers are directly relevant to the proxy problem:
   the proxy can be used only if uncertainty or support checks stop the actor
   from exploiting proxy errors.
5. CPO/TRPO do not replace SAC, but their trust-region and constraint ideas are
   useful for limiting update size and treating Vdc/current/FRT violations as
   first-class constraints.
6. For HPT, the immediate best path is not a residual controller.  It is a
   full-action actor trained with behavior-regularized or offline-to-online
   methods, then promoted only by switch-level Simulink validation.

