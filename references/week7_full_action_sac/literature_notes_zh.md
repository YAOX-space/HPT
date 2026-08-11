# Full-Action SAC 文献阅读笔记

日期：2026-07-17

本笔记基于 `references/week7_full_action_sac/` 中 18 篇 PDF 的全文抽取文本整理。重点不是泛泛总结 RL，而是判断它们如何帮助当前 HPT v2 目标：

```text
SAC actor 直接输出 [m_reg_d, m_reg_q, m_energy_d, m_energy_q]
```

## 1. SAC 基础

### Soft Actor-Critic, 2018

文件：

- `sac_maximum_entropy_deep_rl_arxiv1801.01290.pdf`

核心内容：

- 提出 maximum entropy RL 下的 SAC。
- 同时最大化回报和策略熵。
- 使用 off-policy actor-critic 和 stochastic actor，提高样本效率和稳定性。

对 HPT 的意义：

- 我们的动作是连续 4 维耦合动作，SAC 的形式是合适的。
- 但 HPT 的故障穿越不是普通探索任务，过高熵探索会直接导致 DC-link collapse、过流、错误无功响应。

结论：

- SAC 可以作为最终 actor backbone。
- 不能直接用 plain SAC 长时间乱探索。

### Soft Actor-Critic Algorithms and Applications, 2019

文件：

- `sac_algorithms_and_applications_arxiv1812.05905.pdf`

核心内容：

- 给出更实用的 SAC 版本。
- 包括自动温度调节、稳定训练技巧和应用实验。

对 HPT 的意义：

- 自动温度可以减少手调，但我们的 FRT 场景仍然需要更保守的 entropy target。
- SAC 的 off-policy 机制适合复用 Simulink 产生的旧数据。

结论：

- 采用 SAC 结构时，应明确调小故障场景 entropy，并用 replay buffer 复用传统控制和候选动作数据。

## 2. 行为约束与离线 RL

### TD3+BC

文件：

- `td3_bc_minimalist_offline_rl_arxiv2106.06860.pdf`

核心内容：

- 在 TD3 actor loss 中加入 behavior cloning 项。
- 一个很简单的改动就能在离线 RL 中取得强基线。
- 关键原因是限制 actor 不要选择 dataset 外的动作，减少 extrapolation error。

对 HPT 的意义：

- 这与我们当前失败模式完全对应：SAC actor 离开 conventional/candidate 支持域后，proxy 可能给出假高分。
- TD3+BC 本身可以作为 baseline，也可以把 BC 项迁移到 SAC actor loss。

结论：

- 下一轮 full-action SAC 必须先做 BC reproduction，再做带退火 BC 权重的 SAC fine-tuning。

### IQL

文件：

- `iql_implicit_q_learning_offline_rl_arxiv2110.06169.pdf`

核心内容：

- 不直接评估策略产生的 OOD 动作。
- 用 expectile value 和 advantage-weighted regression 学策略。

对 HPT 的意义：

- 当 Simulink 数据有限时，IQL 比在线 SAC 更稳。
- 它能告诉我们：如果 dataset 本身有足够好动作，离线算法能不能超过 conventional。

结论：

- IQL/AWAC 类方法应该作为“数据够不够”的诊断工具。

### CQL

文件：

- `cql_conservative_q_learning_offline_rl_neurips2020.pdf`

核心内容：

- 通过 conservative Q regularizer 压低 OOD 动作的 Q 值。
- 目标是让学到的 Q 值成为保守下界，避免策略被虚高 Q 值吸引。

对 HPT 的意义：

- HPT proxy 出现假高分时，CQL 的思想很直接。
- 适合用作 conservative critic 或对照 baseline。

结论：

- CQL 不一定作为第一实现，但应作为判断 SAC 是否过度乐观的对照。

### BCQ

文件：

- `bcq_off_policy_deep_rl_without_exploration_icml2019.pdf`

核心内容：

- 提出 batch-constrained RL。
- 通过生成模型和扰动模型把动作限制在 batch 数据附近。
- 重点解决 extrapolation error。

对 HPT 的意义：

- 我们也需要约束动作靠近校准矩阵支持域。
- 但 BCQ 的 VAE 动作生成结构对 4 维 HPT 动作可能偏重，初期不必优先实现。

结论：

- 采用其“batch support constraint”思想，不优先完整复现 BCQ。

### BRAC

文件：

- `brac_behavior_regularized_actor_critic_arxiv1911.11361.pdf`

核心内容：

- 系统比较行为正则项，包括 KL、MMD 等。
- 结论之一是很多复杂技巧不一定必要，简单行为正则常常很强。

对 HPT 的意义：

- 支持我们先做简单可解释的行为约束，而不是立即上复杂 learned proxy + SAC。
- 可用于 full-action SAC actor loss：

```text
L_actor = L_SAC + lambda * D(a_actor, a_ref)
```

结论：

- 下一步应优先实现简单 L2/KL 行为约束，并观察是否保持 conventional pass cases。

### AWAC

文件：

- `awac_accelerating_online_rl_with_offline_datasets_arxiv2006.09359.pdf`

核心内容：

- 用 advantage-weighted behavior cloning 从离线数据启动在线 RL。
- 不仅模仿专家，也能从次优数据中提取有价值动作。

对 HPT 的意义：

- 我们的数据不是全专家数据，包含 baseline、reg sweep、energy sweep、joint sweep 和失败动作。
- AWAC 思路适合：高 advantage 的动作更强模仿，低分动作少模仿。

结论：

- full-action SAC 的 warm-start 不应该只模仿 conventional，而应模仿每个场景中 switch-level 得分更好的动作。

### SACR2

文件：

- `sacr2_sac_with_reward_relabeling_arxiv2110.14464.pdf`

核心内容：

- 研究 demonstrations、BC loss、n-step loss、reward relabeling 对 SAC 的帮助。
- 强调成功轨迹 replay 和 reward relabeling。

对 HPT 的意义：

- 我们可以把 Simulink 中成功或相对更好的短轨迹放进 replay buffer。
- 对边界场景，可以对“比 conventional 更好”的动作给出额外 relabel reward。

结论：

- 不要只用 terminal pass/fail，应该把 survival margin、Vdc margin、reactive shortfall 改善量作为 relabel/advantage 信号。

## 3. 安全与信任域

### TRPO

文件：

- `trpo_trust_region_policy_optimization_arxiv1502.05477.pdf`

核心内容：

- 用 trust region 限制策略更新幅度，避免一次更新导致性能崩溃。

对 HPT 的意义：

- 我们不一定要改成 TRPO，但要限制 actor 每次更新不要跳太远。
- 可实现为：
  - 小 actor learning rate；
  - action-change penalty；
  - KL/action trust-region penalty；
  - candidate promotion gate。

结论：

- SAC 更新需要“慢下来”，尤其在 fault transition 和 topology2 上。

### CPO

文件：

- `cpo_constrained_policy_optimization_arxiv1705.10528.pdf`

核心内容：

- 把 reward 最大化和 safety constraints 分开建模。
- 训练过程中近似满足约束，而不是把所有东西都塞进 reward。

对 HPT 的意义：

- Vdc、grid current、action limit、wrong-sign reactive current 不应该只是 reward 小项。
- 它们应该作为 constraint cost 单独记录和门控。

结论：

- SAC reward 可以优化性能，但 promotion 必须用 constraint gate。

## 4. Proxy 与模型型离线 RL

### PETS

文件：

- `pets_probabilistic_ensembles_trajectory_sampling_neurips2018.pdf`

核心内容：

- 用 probabilistic ensemble 学 dynamics。
- 通过 trajectory sampling 传播不确定性。
- 强调少量真实样本下的样本效率。

对 HPT 的意义：

- 是未来 learned proxy 的基本模板。
- 但我们现在的校准 proxy 是表面查表/插值，不是真正 learned dynamics ensemble。

结论：

- 当我们积累足够 per-step transition trace 后，应训练 PETS-style proxy。

### MOPO

文件：

- `mopo_model_based_offline_policy_optimization_neurips2020.pdf`

核心内容：

- 模型型离线 RL 中，对模型不确定区域施加 reward penalty。

对 HPT 的意义：

- 正好对应 proxy exploitation。
- 如果 actor 提出 off-support 高分动作，不能相信 proxy，应给 pessimistic penalty 或送 Simulink 标注。

结论：

- 当前应实现 calibrated-support penalty；以后用 ensemble uncertainty 替代手工 support distance。

### MOReL

文件：

- `morel_model_based_offline_reinforcement_learning_neurips2020.pdf`

核心内容：

- 构造 pessimistic MDP。
- 不确定区域进入低回报 HALT 状态。

对 HPT 的意义：

- 对 DC-link collapse、过流、未知拓扑耦合非常合适。
- 可作为 proxy OOD 的硬失败机制。

结论：

- 对超出校准面的动作，不应该简单 clamp，而应 fail/penalize 并触发 Simulink resampling。

### COMBO

文件：

- `combo_conservative_offline_model_based_policy_optimization_neurips2021.pdf`

核心内容：

- 混合真实数据和模型 rollouts，同时对 Q 值做 conservative regularization。
- 减少对显式 uncertainty 估计质量的依赖。

对 HPT 的意义：

- 如果 learned proxy uncertainty 不稳定，COMBO 思路比纯 MOPO 更稳。

结论：

- 第二阶段使用，不作为下一步最小实现。

## 5. 鲁棒 SAC 变体

### DSAC-T

文件：

- `dsac_t_distributional_soft_actor_critic_three_refinements_arxiv2310.05858.pdf`

核心内容：

- 用 distributional critic 改善 Q 估计。
- 面向 return distribution，而不只看均值。

对 HPT 的意义：

- FRT 中 rare but severe failure 很关键，例如 Vdc collapse 或 current-limit fault。
- Distributional critic 有助于显式关心尾部风险。

结论：

- 在普通 full-action SAC 跑通后，可作为风险敏感升级。

### DR-SAC

文件：

- `dr_sac_distributionally_robust_soft_actor_critic_arxiv2506.12622.pdf`

核心内容：

- 在 transition model uncertainty 下做 distributionally robust SAC。
- 关注最坏情况转移模型。

对 HPT 的意义：

- topology1/topology2、proxy/Simulink mismatch、参数扰动都属于模型不确定性。

结论：

- 很适合论文 long-term direction，但当前先实现行为约束和支持域控制。

### Continuous SAC

文件：

- `continuous_soft_actor_critic_time_discretization_neurips2025.pdf`

核心内容：

- 讨论 SAC 对时间离散化的敏感性，并提出 continuous-time SAC 思路。

对 HPT 的意义：

- 我们有 SAC 决策周期、PWM 周期、switch-level 仿真步长之间的尺度差。
- 这解释了为什么直接把高层动作扔进开关级模型可能不稳定。

结论：

- 当前先固定 2 ms decision interval 和 0.22 s episode；之后再研究时间尺度鲁棒性。

## 总结判断

目前最适合我们任务的路线不是“纯 SAC 无约束探索”，也不是“残差控制器”。最合理路线是：

1. final actor 仍然输出完整 4 维动作；
2. 用 conventional dq 和 Simulink candidate 数据做 warm start；
3. 用 TD3+BC/BRAC/AWAC/IQL 思想限制早期策略不要离开有效动作支持域；
4. 用 MOPO/MOReL 思想处理 proxy OOD 和不确定性；
5. 用 CPO/TRPO 思想把安全约束和更新幅度显式化；
6. 最终只以 switch-level Simulink 验证结果判断是否成功。

