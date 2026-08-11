# SAC 主线文献整理与项目映射

日期：2026-07-28

## 1. 文献整理目标

本轮文献整理只服务一个问题：

> 如何让 SAC 成为 HPT fault voltage-survival 控制器的主线，而不是让
> DAgger/BC 成为主线？

因此，BC/DAgger 在本文档中只作为初始化、支持分布、对照实验或消融项。
真正要发展的算法是 SAC 本体：保守 SAC、约束 SAC、模型偏差感知 SAC，以及
critic 稳定化 SAC。

## 2. 基础 SAC 文献

### Soft Actor-Critic: Off-Policy Maximum Entropy Deep Reinforcement Learning with a Stochastic Actor

本项目用途：

- 定义 SAC 的基本 actor-critic 框架；
- actor 更新逻辑是最大化 Q 值，同时保持策略熵；
- critic 学习软 Bellman backup；
- 是我们所有 SAC 改进的基准。

对应问题：

- 当前 HPT actor 必须仍然是 SAC-updated actor；
- 不能把最终控制器说成 DAgger 或 BC。

项目转化：

- 论文方法章节需要明确写：
  `actor loss = entropy term - reward Q + constraint/support terms`；
- SAC reward trace、actor/critic loss、alpha 必须被记录。

### Soft Actor-Critic Algorithms and Applications

本项目用途：

- 说明自动温度调节、双 Q critic、target network 等工程实践；
- 作为检查我们 SAC 实现是否“健康”的基础。

对应问题：

- 当前 raw family SAC 可能存在 alpha/Q 值尺度不健康；
- 需要记录 alpha、Q 值分布和 critic loss。

项目转化：

- 先做 SAC instrumentation，再谈训练扩展。

## 3. Critic 稳定性：REDQ

### Randomized Ensembled Double Q-Learning

本项目用途：

- 用 ensemble critic 减轻 Q 估计不稳定；
- 高 update-to-data ratio 在连续控制上更高效；
- 可以避免单一 twin-Q 对 family fault distribution 估计过差。

对应问题：

- Stage-7 raw SAC return 出现 `-1e15` 量级；
- proxy SAC critic 很可能数值不稳定或目标尺度不健康。

项目转化：

- 增加 Q ensemble 诊断；
- 先实现轻量版 ensemble critic 或至少多 seed critic sanity check；
- 如果 Q 方差过大，就不能直接推广 family SAC。

## 4. Action Support / OOD：CQL 与 BRAC

### Conservative Q-Learning for Offline Reinforcement Learning

本项目用途：

- 降低 OOD action 的 Q 过估计；
- 使 critic 对数据支持外动作保持保守；
- 对 imperfect proxy 很重要。

对应问题：

- SAC 在 proxy 里学到 Simulink 不接受的动作；
- switch-level spot case 出现 `max|a| ~= 1.131`。

项目转化：

- 对 actor 采样动作、随机动作、support 边界外动作加 conservative Q penalty；
- 用 calibration sweep / accepted SAC chunks 构建 support action set；
- proxy 上 Q 高但 support 外的动作不能被 actor 采纳。

### Behavior Regularized Actor Critic

本项目用途：

- 在 actor 更新里显式惩罚偏离行为分布；
- 不是让 BC 成为主方法，而是让 SAC 在已知可行支撑内探索。

对应问题：

- 现有 behavior anchor 是训练后周期性拉回，效果不够；
- SAC update 本身仍然会把 actor 推出可行区域。

项目转化：

- 把行为约束写进 actor loss；
- 约束对象是 switch-supported action density，而不是单条 teacher trace；
- 这一步是 SAC 主线，不是 DAgger 主线。

## 5. Proxy Bias / Model Bias：MOPO 与 COMBO

### MOPO: Model-based Offline Policy Optimization

本项目用途：

- 对模型不确定区域施加 reward penalty；
- 防止 policy 利用 learned model/proxy 的漏洞。

对应问题：

- 我们的 averaged/calibrated proxy 不是 Simulink switch-level；
- topology2 energy/DC-link 动态最容易出现 proxy exploitation。

项目转化：

- 训练 proxy ensemble；
- 每个 action 输出 LV/Vdc/recovery 预测均值和不确定度；
- SAC reward target 加 uncertainty penalty。

### COMBO: Conservative Offline Model-Based Policy Optimization

本项目用途：

- 当不确定性估计不可靠时，用 conservative value 方法处理 model bias；
- 与 CQL 思路接近。

对应问题：

- HPT proxy ensemble 的 uncertainty 可能低估真实 Simulink 偏差；
- 需要 conservative Q 防止“看起来确定但实际错误”的 proxy 区域。

项目转化：

- 将 proxy uncertainty penalty 和 conservative Q penalty 并行比较；
- 以 switch-level holdout ranking 判断哪种更可靠。

## 6. Constraint / Safety SAC：WCSAC、PCPO、CSAC-LB

### WCSAC: Worst-Case Soft Actor Critic for Safety-Constrained Reinforcement Learning

本项目用途：

- 在 SAC 中加入 safety critic；
- 使用 worst-case / risk-sensitive 方式处理安全信号。

对应问题：

- HPT 的 pass 不是平均 reward 高，而是每个 timestep 不越 envelope；
- voltage-survival 是硬约束而不是偏好项。

项目转化：

- 训练 cost critic：
  - envelope cost；
  - recovery cost；
  - Vdc cost；
  - action/support cost；
- actor loss 中加入 cost critic 或 Lagrange multiplier；
- 不能只靠 reward penalty。

### Safe Policy Learning for Continuous Control

本项目用途：

- 通过投影保持策略更新满足约束；
- 对连续 action 控制任务有直接参考价值。

对应问题：

- HPT action 是连续调制量；
- Simulink promotion 前需要 projection/shield 防止明显不物理动作。

项目转化：

- 增加 action projection；
- 记录 raw action 和 projected action；
- 最终论文需要说明 projection 是安全执行层还是 SAC loss 的一部分。

### Constrained SAC with Smoothed Log Barrier

本项目用途：

- 用 barrier/safety critic 处理约束；
- 比简单 reward penalty 更接近 “不能越界” 的控制目标。

对应问题：

- 当前 reward 里 envelope/Vdc/action penalty 太软；
- 训练仍会生成越界动作。

项目转化：

- envelope、Vdc、action limit 分别作为 cost；
- SAC actor 更新时对 cost 趋近边界的动作提前惩罚。

## 7. 电力系统与电力电子安全 RL 文献

这些文献不是主算法来源，但有助于论文动机：

- power-system RL 不能接受 unsafe exploration；
- 仅在仿真 proxy 上表现好不足以说明控制器可靠；
- 并网控制必须把电压、电流、DC link 等作为安全约束。

项目转化：

- 最终证据必须来自 switch-level Simulink；
- proxy-only SAC 只能作为候选筛选；
- full FRT 之前先诚实声明 voltage-survival。

## 8. 和我们当前问题的直接对应

| 当前问题 | 文献方向 | 项目改法 |
|---|---|---|
| raw family SAC critic/reward 爆炸 | SAC implementation, REDQ | 记录 Q/alpha/loss，做 reward normalization 和 critic ensemble |
| SAC 生成 support 外动作 | BRAC, CQL | actor loss 加 support penalty，critic 对 OOD action 保守 |
| proxy 训练有效但 Simulink 崩 | MOPO, COMBO | proxy ensemble uncertainty penalty + conservative value |
| envelope/Vdc/action limit 是硬约束 | WCSAC, CSAC-LB, PCPO | reward/cost 分离，cost critic/Lagrange/action projection |
| topology2 energy branch 难学 | constrained SAC + split head | reg/energy head 分开，cost attribution 分开 |
| family 泛化差 | conservative SAC + scenario-conditioned actor | 不靠 DAgger 主线，用 support-conditioned SAC 训练 family actor |

## 9. 结论

下一步不应该是继续扩大 plain SAC，也不应该把 DAgger 变成主线。

最合理的研究路线是：

```text
诊断 plain SAC 失败
-> reward/cost 分离
-> BRAC/CQL 保守支持约束
-> constrained SAC cost critic
-> proxy uncertainty penalty
-> switch-level chunk promotion
```

这条路线仍然是 SAC，只是从 naive SAC 升级成 HPT 约束下可用的 SAC。
