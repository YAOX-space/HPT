# Week 8 SAC-Main Literature Set

Date: 2026-07-28

## Purpose

This folder is for the SAC-centered route requested after the Stage-7 topology2
LVRT family pilot.  DAgger/BC are not treated as the main method here.  The
problem to solve is why SAC itself failed when moved from single-case protected
fine-tuning to family-level control, and how to modify SAC so it remains
switch-level feasible.

## Papers and Project Relevance

| File | Relevance to HPT SAC |
|---|---|
| `sac_maximum_entropy_deep_rl_arxiv1801.01290.pdf` | Original SAC objective: stochastic actor, entropy maximization, off-policy critic updates.  Baseline for all changes. |
| `sac_algorithms_and_applications_arxiv1812.05905.pdf` | Practical SAC details: automatic entropy tuning and stability-oriented implementation choices. |
| `redq_randomized_ensembled_double_q_arxiv2101.05982.pdf` | Ensemble critics and high update-to-data ratios.  Useful for our exploding/unstable Q estimates. |
| `cql_conservative_q_learning_arxiv2006.04779.pdf` | Conservative Q-values to avoid over-estimating OOD actions.  Directly relevant to proxy exploitation and action-support violations. |
| `brac_behavior_regularized_actor_critic_arxiv1911.11361.pdf` | Behavior-regularized actor-critic.  Useful for keeping SAC near switch-supported action regions without making DAgger the main method. |
| `mopo_model_based_offline_policy_optimization_arxiv2005.13239.pdf` | Model-bias-aware policy optimization using uncertainty penalties.  Relevant because our proxy is not identical to Simulink. |
| `combo_conservative_offline_model_based_policy_optimization_arxiv2102.08363.pdf` | Conservative offline model-based RL; useful when explicit uncertainty is unreliable. |
| `wcsac_worst_case_soft_actor_critic_aaai2021.pdf` | Extends SAC with a safety critic and worst-case/CVaR-like constraint handling.  Closest to timestep voltage-survival constraints. |
| `safe_policy_learning_continuous_control_pcpo_uai2021.pdf` | Policy/action projection for continuous-control safety.  Useful for making hard voltage/DC/action constraints part of SAC updates. |
| `csac_lb_constrained_soft_actor_critic_log_barrier_arxiv2403.14508.pdf` | Constrained SAC with a log-barrier style safety critic.  Relevant to replacing soft reward penalties with constraint-aware SAC. |

## Main Takeaway

The next SAC route should not be "plain SAC with a larger reward penalty".
The literature suggests a combined SAC fix:

```text
Conservative/BRAC action support
+ ensemble or conservative critics
+ model-uncertainty penalty for proxy bias
+ constrained SAC cost critics for voltage/DC/action violations
+ switch-level promotion after every candidate chunk
```

In the paper narrative, BC/DAgger can still appear as baselines or
initialization tools, but the core method should be a constrained,
conservative SAC update that directly optimizes the HPT control objective.

## External Source Links

- SAC: https://arxiv.org/abs/1801.01290
- SAC Algorithms and Applications: https://arxiv.org/abs/1812.05905
- REDQ: https://arxiv.org/abs/2101.05982
- CQL: https://arxiv.org/abs/2006.04779
- BRAC: https://arxiv.org/abs/1911.11361
- MOPO: https://arxiv.org/abs/2005.13239
- COMBO: https://arxiv.org/abs/2102.08363
- WCSAC: https://link.springer.com/article/10.1007/s10994-022-06187-8
- PCPO / Safe Policy Learning: https://proceedings.mlr.press/v155/chow21a.html
- CSAC-LB: https://arxiv.org/abs/2403.14508
