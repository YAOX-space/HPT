# Week 8 Literature Set: Family SAC, Imitation, Residual RL, and Safe RL

Date: 2026-07-28

## Why This Set Exists

The Stage-7 topology2 LVRT family pilot exposed a specific failure mode:
direct full-action SAC fine-tuning on the proxy can destroy switch-level
voltage-survival, while a selector teacher assembled from validated
single-case specialists remains much more reliable.  This literature set
collects methods that can turn that observation into a stronger research path:
selector-teacher data generation, DAgger, policy distillation, residual RL, and
safe action constraints.

## Papers

| File | Main Use for HPT SAC |
|---|---|
| `dagger_no_regret_imitation_learning_aistats2011.pdf` | Use DAgger to reduce compounding distribution shift: the student visits states, then an expert/teacher labels those states. |
| `mega_dagger_multiple_imperfect_experts_arxiv2303.00638.pdf` | Matches our selector-teacher setting: multiple imperfect specialists can be filtered/combined using scenario metrics. |
| `mpc_via_on_policy_imitation_learning_l4dc2023.pdf` | Supports on-policy imitation of a constrained controller, useful for trajectory-level HPT control rather than one-shot actions. |
| `policy_distillation_arxiv1511.06295.pdf` | Distill several expert policies into one policy; directly relevant to replacing 12 specialists with a family actor. |
| `actor_mimic_multitask_transfer_rl_arxiv1511.06342.pdf` | Multi-teacher imitation for a single network; useful as a template for topology/fault-family actor training. |
| `distral_robust_multitask_rl_arxiv1707.04175.pdf` | Multitask RL with a shared distilled policy and task-specific workers; useful if a single universal actor is unstable. |
| `option_critic_temporal_abstraction_deep_rl_workshop2015.pdf` | Hierarchical/options view for fault-family selection or controller-head switching. |
| `constrained_residual_rl_mechatronic_control_arxiv2110.02566.pdf` | Strong support for residual RL around a robust baseline instead of replacing the whole controller action. |
| `residual_off_policy_rl_finetuning_bc_arxiv2509.19301.pdf` | Directly supports freezing a BC policy and learning a small residual correction with off-policy RL. |
| `constrained_policy_optimization_arxiv1705.10528.pdf` | Constrained policy optimization; relevant to voltage envelope, DC-link, and action-bound constraints. |
| `lyapunov_safe_policy_optimization_arxiv1901.10031.pdf` | Safe policy optimization and action projection; relevant to preventing unsafe SAC updates. |
| `safe_rl_power_system_control_review_arxiv2407.00681.pdf` | Power-system-specific safe RL review; supports the claim that direct unsafe exploration is unacceptable for grid control. |
| `safe_rl_modern_power_systems_review_arxiv2407.00304.pdf` | Broader safe RL review for modern power systems; useful for positioning HPT voltage-survival constraints. |
| `deep_rl_inverter_controller_gain_tuning_arxiv2411.01451.pdf` | Power-electronics/IBR RL example with Simulink integration and safety-oriented training penalties. |
| `voltage_ride_through_rl_distributed_generation_upc.pdf` | Early voltage ride-through RL material; useful for the FRT motivation, not as the main algorithmic template. |

## Immediate Takeaways

1. Direct SAC over the full action vector is not the most defensible next step
   because our proxy is imperfect and the switch-level plant has hard
   feasibility constraints.
2. The strongest path is: validated specialists -> selector teacher ->
   on-policy DAgger/trajectory relabeling -> distilled family actor -> bounded
   residual SAC fine-tune -> switch-level promotion.
3. The SAC part should be residual or strongly behavior-constrained.  The base
   actor should preserve voltage-survival; SAC should improve boundary
   generalization and score, not rediscover basic feasibility from scratch.
4. Safe action projection should be part of the execution layer during both
   training and validation.  In this project that means voltage-envelope,
   DC-link, and action-limit constraints remain hard switch-level gates.

## External Source Links

- DAgger: https://proceedings.mlr.press/v15/ross11a.html
- MEGA-DAgger: https://arxiv.org/abs/2303.00638
- MPC via On-Policy Imitation Learning: https://proceedings.mlr.press/v211/ahn23a.html
- Policy Distillation: https://arxiv.org/abs/1511.06295
- Actor-Mimic: https://arxiv.org/abs/1511.06342
- Distral: https://arxiv.org/abs/1707.04175
- Constrained Residual RL: https://arxiv.org/abs/2110.02566
- Residual Off-Policy RL for Fine-Tuning BC: https://arxiv.org/abs/2509.19301
- Constrained Policy Optimization: https://arxiv.org/abs/1705.10528
- Lyapunov Safe Policy Optimization: https://arxiv.org/abs/1901.10031
- Safe RL for Power System Control: https://arxiv.org/abs/2407.00681
- Safe RL for Modern Power Systems Review: https://arxiv.org/abs/2407.00304
- Deep RL for Inverter Controller Gain Tuning: https://arxiv.org/abs/2411.01451
