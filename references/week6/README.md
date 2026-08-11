# Limited-data RL references for HPT SAC

This folder collects papers for the HPT problem where switch-level Simulink
rollouts are expensive, the averaged proxy has model bias, and the final target
is still a direct SAC-like controller for the HPT.

## Papers

| File | Method family | Main idea | Relevance to HPT |
| --- | --- | --- | --- |
| `pets_probabilistic_ensembles_trajectory_sampling_neurips2018.pdf` | Model-based RL | Learn probabilistic ensemble dynamics and plan with trajectory sampling. | Good template for a data-efficient learned training proxy with uncertainty. |
| `mopo_model_based_offline_policy_optimization_neurips2020.pdf` | Model-based offline RL | Penalize synthetic rollouts by model uncertainty. | Directly addresses proxy/Simulink mismatch and limited rollout data. |
| `morel_model_based_offline_reinforcement_learning_neurips2020.pdf` | Pessimistic model-based offline RL | Route uncertain state-action regions to a low-reward absorbing state. | Useful safety guard for DC-link collapse, overcurrent, and out-of-support fault actions. |
| `combo_conservative_offline_model_based_policy_optimization_neurips2021.pdf` | Conservative model-based offline RL | Mix real and model-generated rollouts while regularizing Q-values conservatively. | Good second-stage option if ensemble uncertainty is noisy or too conservative. |
| `cql_conservative_q_learning_offline_rl_neurips2020.pdf` | Offline model-free RL | Learn conservative lower-bound Q-values to avoid out-of-dataset actions. | Strong baseline, but does not fix dynamics mismatch by itself. |
| `iql_implicit_q_learning_offline_rl_arxiv2110.06169.pdf` | Offline model-free RL | Avoid evaluating out-of-dataset actions; train policy by advantage-weighted regression. | Stable baseline from conventional-controller trajectories. |
| `bcq_off_policy_deep_rl_without_exploration_icml2019.pdf` | Batch-constrained offline RL | Constrain policy actions to the support of the dataset. | Safe if data is good, but can be too conservative when strong corrective actions are missing. |
| `td3_bc_minimalist_offline_rl_arxiv2106.06860.pdf` | Offline model-free baseline | TD3 plus behavior-cloning regularization. | Simple baseline before complex robust SAC variants. |

## Recommended route for this project

1. Keep the final deployed controller as a direct continuous-action controller.
   Do not add a residual controller around it.
2. Replace the hand-tuned averaged proxy with a data-calibrated learned dynamics
   proxy trained from switch-level Simulink rollouts.
3. Use PETS-style ensembles to estimate uncertainty for each transition.
4. Train SAC/DSAC/DR-SAC on the learned proxy with MOPO- or MOReL-style
   pessimism so the policy avoids unsupported fault transitions.
5. Benchmark against IQL and TD3+BC trained only from the Simulink dataset.
6. Validate the selected policy on the switch-level topology1 and topology2
   models under steady, sag, swell, and fault-transition scenarios.

The key point is that the learned proxy is only a training environment. The
final controller can still output direct HPT control actions.

## 2026-07-17 implementation decision

The current HPT v2 bottleneck is not lack of SAC epochs.  The reward-alignment
matrix shows that the hand-built proxy can mis-rank the best switch-level
actions, especially HVRT energy actions and joint regulating/energy actions.

The near-term method is therefore:

1. Use switch-level Simulink FRT matrix data as the reward source of truth.
2. Learn a supervised reward-correction model from proxy/action/scenario
   features to the switch-level reward-like score.
3. Use the corrected score for candidate screening, teacher ranking, and
   offline data construction.
4. Train specialist actors from corrected/Simulink-labeled data before returning
   to SAC-style online optimization.
5. Keep MOPO/MOReL/COMBO as the next step once we have enough transition data
   to learn a dynamics ensemble with uncertainty.

This follows the conservative offline RL message from IQL, TD3+BC, CQL, BCQ,
MOPO, MOReL, and COMBO: when real rollouts are expensive and the simulator proxy
is biased, first constrain or correct the action-value signal with real
switch-level labels instead of letting SAC freely exploit the proxy.
