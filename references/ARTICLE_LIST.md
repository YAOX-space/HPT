# Reference article list

整理日期：2026-07-27

## Overview

- `references/` 下共有 50 个 PDF 文件。
- 去除完全重复文件后，约 36 篇/份唯一参考资料。
- 另有 1 个项目任务书 `docx`、若干 README/manifest/抽取文本文件。
- `week7_full_action_sac/` 是当前最完整的 SAC/离线 RL 文献包；其中不少文件是 week5/week6 的副本。

## Duplicate Files

| 重复内容 | 重复位置 |
| --- | --- |
| 基于电流协同优化的柔直输电系统受端换流站故障穿越控制方法 | `week1/基于电流协同优化的柔直输电系统受端换流站故障穿越控制方法_贾科.pdf`; `week1/基于电流协同优化的柔直输电系统受端换流站故障穿越控制方法_贾科 (1).pdf` |
| Deep Reinforcement Learning for Optimizing Inverter Control: Fixed and Adaptive Gain Tuning Strategies for Power System Stability | `week2/2411.01451v1.pdf`; `week2/2411.01451v1+(1).pdf` |
| Online Multi-agent Reinforcement Learning for Decentralized Inverter-based Volt-VAR Control | `week2/2006.12841v2.pdf`; `week4/macsac_volt_var_arxiv2006.pdf` |
| week5 SAC variants | `week5/*.pdf`; same PDFs copied in `week7_full_action_sac/` |
| week6 limited-data/offline RL papers | `week6/*.pdf`; same PDFs copied in `week7_full_action_sac/` |

## Week 1 - HPT/FRT Chinese References

| 文件 | 识别题名 | 类型/主题 | 备注 |
| --- | --- | --- | --- |
| `week1/基于电流协同优化的柔直输电系统受端换流站故障穿越控制方法_贾科.pdf` | 基于电流协同优化的柔直输电系统受端换流站故障穿越控制方法 | 柔直输电；受端换流站；故障穿越 | 中国电机工程学报网络首发；DOI: `10.13334/j.0258-8013.pcsee.242707` |
| `week1/基于电流协同优化的柔直输电系统受端换流站故障穿越控制方法_贾科 (1).pdf` | 同上 | 重复文件 | 与上一文件 SHA256 完全一致 |
| `week1/基于自适应虚拟阻感比的构网型变流器故障穿越控制方法_贾科.pdf` | 基于自适应虚拟阻感比的构网型变流器故障穿越控制方法 | 构网型变流器；故障穿越 | 电网技术网络首发；DOI: `10.13335/j.1000-3673.pst.2025.1212` |
| `week1/混合式电力变压器多工作模式控制策略研究_宋幸.pdf` | 混合式电力变压器多工作模式控制策略研究 | 混合式电力变压器；多模式控制 | 硕士学位论文，2023 |
| `week1/GDKJXM20241002+...计划任务书-修改意见-已修改.docx` | 纳米晶及超级硅钢的多端口柔性配电变压器研究与交直流微网中应用，课题2任务书 | 项目任务书 | 非论文参考资料 |

## Week 2 - Power Electronics + RL/Volt-VAR

| 文件 | 识别题名 | 类型/主题 | 备注 |
| --- | --- | --- | --- |
| `week2/2006.12841v2.pdf` | Online Multi-agent Reinforcement Learning for Decentralized Inverter-based Volt-VAR Control | 多智能体 RL；逆变器 Volt-VAR | 与 `week4/macsac_volt_var_arxiv2006.pdf` 重复 |
| `week2/2008.04542v1.pdf` | An Intelligent Control Strategy for Buck DC-DC Converter via Deep Reinforcement Learning | DC-DC buck；DRL 控制 | arXiv:2008.04542 |
| `week2/2411.01451v1.pdf` | Deep Reinforcement Learning for Optimizing Inverter Control: Fixed and Adaptive Gain Tuning Strategies for Power System Stability | 逆变器控制增益整定；DRL | arXiv:2411.01451 |
| `week2/2411.01451v1+(1).pdf` | 同上 | 重复文件 | 与上一文件 SHA256 完全一致 |
| `week2/A_Novel_Nonlinear_Deep_Reinforcement_Learning_Controller_for_DCDC_Power_Buck_Converters.pdf` | A Novel Nonlinear Deep Reinforcement Learning Controller for DC-DC Power Buck Converters | DC-DC buck；非线性 DRL 控制 | IEEE TIE, 2021 |
| `week2/Soft_Actor-Critic_With_Integer_Actions.pdf` | Soft Actor-Critic With Integer Actions | SAC；整数动作 | L4DC, 2022 |
| `week2/Two-Stage_Deep_Reinforcement_Learning_for_Inverter-Based_Volt-VAR_Control_in_Active_Distribution_Networks.pdf` | Two-Stage Deep Reinforcement Learning for Inverter-Based Volt-VAR Control in Active Distribution Networks | 两阶段 DRL；Volt-VAR | IEEE TSG, 2021 |
| `week2/fan22a.pdf` | PowerGym: A Reinforcement Learning Environment for Volt-Var Control in Power Distribution Systems | RL 环境；配电网 Volt-VAR | L4DC, 2022 |
| `week2/含PQ控制逆变型分布式电源的配电网故障分析方法_潘国清.pdf` | 含 PQ 控制逆变型分布式电源的配电网故障分析方法 | 配电网故障分析；PQ 控制逆变器 | 中国电机工程学报，2014 |
| `week2/基于混合变压器电压支撑的双馈风电机组故障穿越控制策略_赖锦木.pdf` | 基于混合变压器电压支撑的双馈风电机组故障穿越控制策略 | 混合变压器；DFIG；故障穿越 | 电力自动化设备，2026 |

## Week 3 - MPC/HDT/FRT

| 文件 | 识别题名 | 类型/主题 | 备注 |
| --- | --- | --- | --- |
| `week3/mpc_hdt_grid_services_arxiv2602.00798.pdf` | Modeling and Control of Hybrid Distribution Transformers for Simultaneous Grid Services | HDT 建模与控制；并行电网服务 | arXiv:2602.00798 |
| `week3/mpc_hdt_voltage_pf_mdpi2024.pdf` | Operation Assessment of a Hybrid Distribution Transformer Compensating for Voltage and Power Factor Using Predictive Control | HDT；电压/功率因数补偿；预测控制 | Mathematics, 2024 |
| `week3/mpc_pmsg_frt_frontiers2023.pdf` | A Model Predictive Control Strategy for Enhancing Fault Ride Through in PMSG Wind Turbines Using SMES and Improved GSC | MPC；PMSG 风机；FRT | Frontiers, 2023 |
| `week3/mdpi.txt` | MDPI 相关文本/笔记 | 文本资料 | 非 PDF 论文文件 |

## Week 4 - Grid Code + HT Placement + MARL

| 文件 | 识别题名 | 类型/主题 | 备注 |
| --- | --- | --- | --- |
| `week4/GBT+19963.1-2021.pdf` | GB/T 19963.1-2021 | 并网技术规定/标准 | 标准文件，不是论文 |
| `week4/ht_optimal_placement_arxiv2507.pdf` | Optimal Placement of Smart Hybrid Transformers in Distribution Networks | 智能混合变压器；选址优化 | arXiv:2507 |
| `week4/macsac_volt_var_arxiv2006.pdf` | Online Multi-agent Reinforcement Learning for Decentralized Inverter-based Volt-VAR Control | 多智能体 RL；Volt-VAR | 与 `week2/2006.12841v2.pdf` 重复 |
| `week4/mapdn_active_voltage_marl_arxiv2110.pdf` | Multi-Agent Reinforcement Learning for Active Voltage Control on Power Distribution Networks | 多智能体 RL；主动电压控制 | arXiv:2110 |

## Week 5 - SAC Variants

| 文件 | 识别题名 | 类型/主题 | 备注 |
| --- | --- | --- | --- |
| `week5/dsac_t_distributional_soft_actor_critic_three_refinements_arxiv2310.05858.pdf` | Distributional Soft Actor-Critic with Three Refinements | Distributional SAC；价值分布 | IEEE TPAMI 2025 preprint；同 week7 副本 |
| `week5/dr_sac_distributionally_robust_soft_actor_critic_arxiv2506.12622.pdf` | DR-SAC: Distributionally Robust Soft Actor-Critic for Reinforcement Learning under Uncertainty | 鲁棒 SAC；不确定性 | ICLR 2026；同 week7 副本 |
| `week5/continuous_soft_actor_critic_time_discretization_neurips2025.pdf` | Continuous Soft Actor-Critic: An Off-Policy Learning Method Robust to Time Discretization | 连续时间/离散化鲁棒 SAC | NeurIPS 2025；同 week7 副本 |

## Week 6 - Limited-Data / Offline RL

| 文件 | 识别题名 | 类型/主题 | 备注 |
| --- | --- | --- | --- |
| `week6/pets_probabilistic_ensembles_trajectory_sampling_neurips2018.pdf` | Deep Reinforcement Learning in a Handful of Trials Using Probabilistic Dynamics Models | PETS；模型集成；样本效率 | 同 week7 副本 |
| `week6/mopo_model_based_offline_policy_optimization_neurips2020.pdf` | MOPO: Model-based Offline Policy Optimization | 模型式离线 RL；不确定性惩罚 | 同 week7 副本 |
| `week6/morel_model_based_offline_reinforcement_learning_neurips2020.pdf` | MOReL: Model-Based Offline Reinforcement Learning | 悲观模型式离线 RL | 同 week7 副本 |
| `week6/combo_conservative_offline_model_based_policy_optimization_neurips2021.pdf` | COMBO: Conservative Offline Model-Based Policy Optimization | 保守模型式离线 RL | 同 week7 副本 |
| `week6/cql_conservative_q_learning_offline_rl_neurips2020.pdf` | Conservative Q-Learning for Offline Reinforcement Learning | 保守 Q 学习；离线 RL | 同 week7 副本 |
| `week6/iql_implicit_q_learning_offline_rl_arxiv2110.06169.pdf` | Offline Reinforcement Learning with Implicit Q-Learning | IQL；离线 RL | 同 week7 副本 |
| `week6/bcq_off_policy_deep_rl_without_exploration_icml2019.pdf` | Off-Policy Deep Reinforcement Learning without Exploration | BCQ；batch-constrained RL | 同 week7 副本 |
| `week6/td3_bc_minimalist_offline_rl_arxiv2106.06860.pdf` | A Minimalist Approach to Offline Reinforcement Learning | TD3+BC；离线 RL 基线 | 同 week7 副本 |

## Week 7 - Full-Action SAC Literature Bundle

| 文件 | 识别题名 | 类型/主题 | 备注 |
| --- | --- | --- | --- |
| `week7_full_action_sac/sac_maximum_entropy_deep_rl_arxiv1801.01290.pdf` | Soft Actor-Critic: Off-Policy Maximum Entropy Deep Reinforcement Learning with a Stochastic Actor | SAC 基础算法 | arXiv:1801.01290 |
| `week7_full_action_sac/sac_algorithms_and_applications_arxiv1812.05905.pdf` | Soft Actor-Critic Algorithms and Applications | SAC 稳定版本；自动温度 | arXiv:1812.05905 |
| `week7_full_action_sac/td3_bc_minimalist_offline_rl_arxiv2106.06860.pdf` | A Minimalist Approach to Offline Reinforcement Learning | TD3+BC；离线 RL | week6 副本 |
| `week7_full_action_sac/iql_implicit_q_learning_offline_rl_arxiv2110.06169.pdf` | Offline Reinforcement Learning with Implicit Q-Learning | IQL；离线 RL | week6 副本 |
| `week7_full_action_sac/cql_conservative_q_learning_offline_rl_neurips2020.pdf` | Conservative Q-Learning for Offline Reinforcement Learning | CQL；保守离线 RL | week6 副本 |
| `week7_full_action_sac/bcq_off_policy_deep_rl_without_exploration_icml2019.pdf` | Off-Policy Deep Reinforcement Learning without Exploration | BCQ；离线 RL | week6 副本 |
| `week7_full_action_sac/brac_behavior_regularized_actor_critic_arxiv1911.11361.pdf` | Behavior Regularized Offline Reinforcement Learning | BRAC；行为正则 | arXiv:1911.11361 |
| `week7_full_action_sac/awac_accelerating_online_rl_with_offline_datasets_arxiv2006.09359.pdf` | AWAC: Accelerating Online Reinforcement Learning with Offline Datasets | AWAC；离线到在线 RL | arXiv:2006.09359 |
| `week7_full_action_sac/sacr2_sac_with_reward_relabeling_arxiv2110.14464.pdf` | Learning from Demonstrations with SACR2: Soft Actor-Critic with Reward Relabeling | SAC + demonstrations；reward relabeling | arXiv:2110.14464 |
| `week7_full_action_sac/trpo_trust_region_policy_optimization_arxiv1502.05477.pdf` | Trust Region Policy Optimization | TRPO；策略更新约束 | arXiv:1502.05477 |
| `week7_full_action_sac/cpo_constrained_policy_optimization_arxiv1705.10528.pdf` | Constrained Policy Optimization | CPO；安全/约束 RL | arXiv:1705.10528 |
| `week7_full_action_sac/pets_probabilistic_ensembles_trajectory_sampling_neurips2018.pdf` | Deep Reinforcement Learning in a Handful of Trials Using Probabilistic Dynamics Models | PETS；模型式 RL | week6 副本 |
| `week7_full_action_sac/mopo_model_based_offline_policy_optimization_neurips2020.pdf` | MOPO: Model-based Offline Policy Optimization | 模型式离线 RL | week6 副本 |
| `week7_full_action_sac/morel_model_based_offline_reinforcement_learning_neurips2020.pdf` | MOReL: Model-Based Offline Reinforcement Learning | 模型式离线 RL | week6 副本 |
| `week7_full_action_sac/combo_conservative_offline_model_based_policy_optimization_neurips2021.pdf` | COMBO: Conservative Offline Model-Based Policy Optimization | 保守模型式离线 RL | week6 副本 |
| `week7_full_action_sac/dsac_t_distributional_soft_actor_critic_three_refinements_arxiv2310.05858.pdf` | Distributional Soft Actor-Critic with Three Refinements | Distributional SAC | week5 副本 |
| `week7_full_action_sac/dr_sac_distributionally_robust_soft_actor_critic_arxiv2506.12622.pdf` | DR-SAC: Distributionally Robust Soft Actor-Critic for Reinforcement Learning under Uncertainty | 鲁棒 SAC | week5 副本 |
| `week7_full_action_sac/continuous_soft_actor_critic_time_discretization_neurips2025.pdf` | Continuous Soft Actor-Critic: An Off-Policy Learning Method Robust to Time Discretization | 连续时间/离散化鲁棒 SAC | week5 副本 |

## Suggested Reading Order For Current HPT SAC Work

1. HPT/FRT 背景：week1、week2 的中文 HPT/FRT/故障分析论文。
2. HDT/MPC 对照：week3、week4 的 HDT/MPC/混合变压器选址资料。
3. SAC 基线：`sac_maximum_entropy...`、`sac_algorithms_and_applications...`。
4. 数据受限训练：week6 的 PETS/MOPO/MOReL/COMBO/CQL/IQL/BCQ/TD3+BC。
5. 当前 full-action SAC 稳定化：week7 的 BRAC/AWAC/SACR2/TRPO/CPO，以及 DSAC/DR-SAC/Continuous SAC。
· 