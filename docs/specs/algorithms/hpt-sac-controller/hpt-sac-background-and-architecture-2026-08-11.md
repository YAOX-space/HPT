# 面向混合式电力变压器故障穿越的 SAC 控制器背景与实现路线

日期：2026-08-11

## 1. 研究问题定位

本项目的目标不是证明“强化学习一定优于传统控制”，而是在混合式电力变压器（HPT/HDT）的故障穿越场景中，构造一个可以通过开关级 Simulink 验证的连续动作控制器。当前仓库状态以 `docs/autonomy/current_research_state.json` 为准：

- 当前没有 v3 validator 下的 promoted SAC 控制器。
- 当前可训练目标是 L1 voltage-survival，而不是完整 L2/L3 FRT 认证。
- 控制器合同为 24 维观测、4 维动作。
- 动作为 `[m_reg_d, m_reg_q, m_energy_d, m_energy_q]`。
- 一个故障族只能使用一个未改动 checkpoint，不能用每个工况单独 actor 或隐藏 runtime selector。

因此，论文或报告中应把 claim 写成：

> 研究一种面向 HPT 故障电压支撑的 SAC 连续动作控制器，并通过开关级模型验证其在给定故障族边界上的 voltage-survival 能力。

暂时不要写成：

> SAC 已经实现完整 FRT，或 SAC 全局优于 dq/PI 控制。

## 2. 为什么 HPT 是一个适合 SAC 的控制对象

HPT/HDT 通常由工频变压器和部分额定功率的电力电子变换器组成。综述文献指出，这类结构的动机是保留传统变压器高效率、高可靠、大容量的优点，同时用部分功率变换器补足电压调节、电能质量治理和功率流控制能力 [Carreno et al., 2021](https://ideas.repec.org/a/gam/jeners/v14y2021i5p1215-d504683.html)。

近期 HDT 控制论文也强调，传统工频配电变压器缺少主动功率流控制、电压调节和故障隔离能力；HDT 通过串联变换器和并联/取能变换器可以进行电压支撑、电能质量改善、双向功率流和故障隔离 [Lai et al., 2025](https://strathprints.strath.ac.uk/94943/1/Lai-etal-IEEE-TPE-2025-Enhancing-transient-performance-of-hybrid-distribution-transformer.pdf)。

对 SAC 来说，HPT 的难点和机会在这里：

1. 控制量天然连续。调控变换器的 d/q 轴串联注入、取能变换器的 d/q 轴能量调节都不是离散开关命令，而是连续调制/电流参考。
2. 目标是多约束优化。低压侧电压、直流母线、调制幅值、电流限值、故障恢复时间都要同时满足。
3. 工况分布宽。LVRT、HVRT、单相、两相、三相、不同深度和持续时间会导致同一 PI 参数难以覆盖所有边界。
4. 不能在线危险探索。真实电力电子系统不能让 RL 随意探索 DC-link collapse、过流或错误无功支撑，所以必须使用 proxy、离线数据、support 约束和开关级 promotion gate。

## 3. 传统控制背景与不足

HDT 传统控制通常按“串联变换器管电压、并联/取能变换器管 DC-link 或功率流”的思路设计。Lai 等的 2025 IEEE TPE 论文把串联变换器输出电压/并联变换器电流作为控制对象，并比较 PI、PR、MPC、SMC、FLC、RC 等策略。该文还指出重复控制适合周期谐波抑制，但在突发大扰动下响应较慢，因为其校正依赖一个基波周期的误差信息 [Lai et al., 2025](https://strathprints.strath.ac.uk/94943/1/Lai-etal-IEEE-TPE-2025-Enhancing-transient-performance-of-hybrid-distribution-transformer.pdf)。

这给本项目留下了合理切入点：

- dq/PI 是必须保留的强 baseline。
- SAC 不应替代底层电流环、PWM、保护限幅，而应作为高层连续动作决策器。
- SAC 的价值应体现在边界工况：传统 dq 在特定深度/持续时间下因为 DC-link、恢复电压或动作限幅失败，而 SAC 通过协调调控/取能桥找到更好的动作分配。

## 4. SAC 基础架构

原始 SAC 是 maximum entropy 框架下的 off-policy actor-critic 算法。其核心思想是同时最大化期望回报和策略熵，从而提升样本效率和训练稳定性 [Haarnoja et al., 2018](https://arxiv.org/abs/1801.01290)。后续 SAC Algorithms and Applications 版本加入了更工程化的稳定训练机制，包括自动温度调节等，使 SAC 成为连续控制任务中常用基线 [Haarnoja et al., 2019](https://arxiv.org/abs/1812.05905)。

对本项目，SAC 的最小可解释架构是：

```text
24-D observation
  -> stochastic actor pi_theta(a | s)
  -> 4-D physical action [m_reg_d, m_reg_q, m_energy_d, m_energy_q]
  -> proxy rollout / Simulink validation

critic Q_phi(s, a)
  -> estimate voltage-survival reward
  -> train actor with entropy term and support/safety terms
```

部署时不使用随机采样，而使用导出的 deterministic actor。PWM 门极、dq 坐标变换、电流闭环、调制限幅仍留在 Simulink/电力电子执行层。

## 5. 最新 SAC 相关论文给我们的启发

### 5.1 DSAC-T：分布式 critic，面向尾部风险

DSAC-T 用连续 Gaussian value distribution 替代单一均值 Q，并通过 expected value substitution、twin value distribution learning 和 variance-based critic gradient adjustment 改善 Q 值估计稳定性；其 2025 年版本已发表于 IEEE TPAMI [Duan et al., 2025](https://arxiv.org/abs/2310.05858)。

对 HPT 的意义：

- FRT 的失败通常是尾部事件，不是平均性能差一点。
- DC-link collapse、过流、恢复失败都应该被 critic 的风险/分布信息看见。
- 当前阶段可以先记录 reward/cost 分布；后续再把 twin scalar Q 升级为 distributional critic。

### 5.2 CSAC-LB：把约束从 reward shaping 中拆出来

CSAC-LB 提出 constrained SAC with smoothed log barrier，用额外 safety critic 和自适应惩罚处理约束；论文指出真实控制问题常常更适合同时写成 reward 和 constraint，而不是把所有目标塞进手调 reward [Zhang et al., 2024](https://arxiv.org/abs/2403.14508)。

对 HPT 的意义：

- 电压 envelope、Vdc 上下界、电流限值、动作上限应作为 cost/constraint 单独记录。
- reward 可以优化电压质量和动作平滑，但 promotion 必须由 gate 判断。
- 当前代码已经记录大量 `cost_*`，下一步可以把它们从“日志指标”推进到 safety critic 或 Lagrange multiplier。

### 5.3 DR-SAC：面向 transition uncertainty 的鲁棒 SAC

DR-SAC 是 2025/2026 的新近方向，它把 SAC 扩展到分布鲁棒 RL，在 KL 约束的不确定转移模型集合中最大化 entropy-regularized reward，并声称适用于连续动作离线学习 [Cui et al., 2026](https://arxiv.org/abs/2506.12622)。

对 HPT 的意义：

- 我们最核心的问题正是 proxy 与开关级 Simulink 不一致。
- topology1/topology2、不同故障族、参数扰动都可视为 transition uncertainty。
- 但 DR-SAC 不应作为第一步直接重写。当前更实际的是 proxy-2.0 transition dataset、holdout alignment、uncertainty penalty，之后再升级为 DR-SAC 形式。

### 5.4 Conservative SAC / trust-region SAC：控制 actor 更新幅度

2025 年 Conservative SAC 方向把 entropy regularization 与 relative entropy regularization 结合，用来减少过激策略更新并改善控制任务稳定性 [Shang et al., 2026](https://arxiv.org/abs/2505.03356)。这和 HPT 的需求很接近：故障控制不能让 actor 一次更新跳出已验证动作域。

对 HPT 的意义：

- 保留 SAC 主更新，但给 actor 加 support/behavior/trust-region 约束。
- 每次训练都记录 actor drift、raw action、projected action 和 support distance。
- 训练中可以探索，promotion 时必须使用未改动 checkpoint。

### 5.5 Continuous SAC：时间离散化敏感性

NeurIPS 2025 的 Continuous SAC 关注 SAC 对环境时间步长的敏感性，并提出连续时间/空间下的 off-policy actor-critic 框架 [Han & Ji, 2025](https://proceedings.neurips.cc/paper_files/paper/2025/hash/6ac12f42db406e6be14d669884e73212-Abstract-Conference.html)。

对 HPT 的意义：

- HPT 有至少三种时间尺度：PWM 开关周期、Simulink solver 步长、SAC 决策周期。
- 当前实现应先固定决策周期，例如 2 ms，再做所有对照。
- 未来可做时间尺度消融：1 ms、2 ms、5 ms 下同一 actor 或重训 actor 的表现差异。

### 5.6 CQL、BRAC、MOPO、REDQ 是实现辅助，不是论文主 claim

CQL 针对离线 RL 中 dataset-policy distribution shift 导致的 Q 过估计问题，通过 conservative Q regularizer 让 Q 成为保守下界 [Kumar et al., 2020](https://arxiv.org/abs/2006.04779)。BRAC 说明行为正则化可以让 actor 不离开固定离线数据支持域 [Wu et al., 2019](https://arxiv.org/abs/1911.11361)。MOPO 在模型型离线 RL 中用 dynamics uncertainty 对 reward 施加惩罚，以处理离线模型偏差 [Yu et al., 2020](https://arxiv.org/abs/2005.13239)。REDQ 则用 Q ensemble、高 update-to-data ratio 和随机子集 target minimization 改善样本效率和 Q 稳定性 [Chen et al., 2021](https://arxiv.org/abs/2101.05982)。

这些文献在本项目里的位置是：

- CQL/BRAC：防止 SAC 选择 Simulink 未支持的动作。
- MOPO：防止 SAC 利用 proxy 漏洞。
- REDQ/DSAC-T：改善 critic 稳定性。
- 它们是 SAC 架构增强项，不应把主线改名成“离线 RL 控制器”。

## 6. 当前仓库中的 SAC 架构

当前维护入口是：

- `sac/hpt_voltage_sac_env.py`
- `sac/offline/train_hpt_voltage_sac.py`
- `sac/campaigns/run_hpt_family_specialist_matrix.py`
- `simulink/evaluators/eval_hpt_v2_control_comparison.m`

当前实现要点：

1. `HPTVoltageSACEnv` 使用 24-D fault-transition-aware observation。
2. action 是 4-D physical action：`[m_reg_d, m_reg_q, m_energy_d, m_energy_q]`。
3. `SplitHeadSACActor` 把最终输出头拆为 regulating bridge head 和 energy bridge head。
4. `SupportRegularizedSAC` 在 SAC actor loss 中加入 support regularization。
5. `RewardTraceCallback` 记录 reward、actor/critic loss、entropy、support loss 和各类 `cost_*`。
6. 训练结果只是 proxy candidate，必须导出并经过开关级 Simulink validator 才能 promotion。

可以把当前实现概括为：

```text
strong-dq / switch-supported traces
        |
        v
support dataset / anchor dataset
        |
        v
Split-head SAC actor
  - reg head:    [m_reg_d, m_reg_q]
  - energy head: [m_energy_d, m_energy_q]
        |
        v
SupportRegularizedSAC
  actor loss = SAC actor loss + lambda_support * support_action_error
        |
        v
export actor -> Simulink switch-level matrix -> L1 gate
```

## 7. 推荐实现路线

### 第一步：先把当前 SAC 写成“可审计实现”

不急着更换算法。先完成最小闭环：

- 更新旧 16-D 架构文档，统一为 24-D observation。
- 在训练 manifest 中固定：fault family、scenario split、seed、proxy hash、model hash、actor hash。
- 每次训练输出：
  - reward mean/std；
  - unscaled reward；
  - actor loss；
  - critic loss；
  - entropy coefficient；
  - support loss；
  - action drift；
  - `cost_vdc_bounds`、`cost_envelope`、`cost_grid_current`、`cost_action_limit`。

### 第二步：把 support regularization 做成主线

当前代码已经接近 BRAC 思路。下一步建议固定公式：

```text
L_actor =
    E_s[alpha * log pi(a|s) - min(Q1, Q2)(s, a)]
  + lambda_support * E_(s,a_ref)[w(s) * ||scale(a_actor) - scale(a_ref)||^2]
```

其中：

- `a_ref` 来自 strong-dq 或 switch-supported action。
- `w(s)` 按 switch-level margin 加权，越接近故障边界权重越大。
- `scale()` 必须把 physical action 映射到 SB3 actor 的 `[-1, 1]` 空间。

### 第三步：把 safety cost 从 reward 中拆出

当前 reward 已经惩罚很多安全项，但它们仍混在一个 scalar reward 里。建议下一版实现：

```text
reward: 电压跟踪、恢复质量、动作平滑
cost_vdc: Vdc 越界
cost_envelope: 电压包络越界
cost_current: 电流越界
cost_action: 调制/动作越界
```

短期实现可以是 Lagrangian SAC：

```text
L_actor_safe =
    L_actor
  + beta_vdc * E[cost_vdc]
  + beta_env * E[cost_envelope]
  + beta_i * E[cost_current]
  + beta_a * E[cost_action]
```

长期再升级为 CSAC-LB 或 WCSAC 风格 safety critic。

### 第四步：解决 proxy-to-switch mismatch

这一步是当前项目最关键。推荐顺序：

1. 扩充 proxy-2.0 timestep transition dataset，而不是只用 summary row。
2. 做 train/validation/holdout split。
3. 同时报告 fixed-action alignment 和 trajectory-rollout ranking alignment。
4. 对 off-support action 加 MOPO/CQL 风格 pessimistic penalty。
5. 每个候选 actor 都立即做小矩阵开关级 spot check。

### 第五步：再考虑最新 SAC 升级

当 support-regularized SAC 能稳定跑通后，再按优先级升级：

1. CSAC-LB / Lagrangian SAC：优先，因为 HPT 是硬约束问题。
2. DSAC-T：用于 DC-link collapse、过流等尾部风险。
3. REDQ：用于 critic 不稳定或样本效率不足。
4. DR-SAC：用于 topology/proxy uncertainty。
5. Continuous SAC：用于决策周期与开关级时间尺度不匹配。

## 8. 建议的论文方法表述

可以写：

> 本文采用一种 support-regularized SAC 控制器。Actor 接收由低压侧电压、网侧正/负序电压、直流母线、电流、故障检测状态、拓扑标志和上一时刻动作构成的 24 维观测，输出调控变换器与取能变换器的 4 维 d/q 轴连续调制指令。为避免离线/代理模型训练中出现 unsupported action，本文在 SAC actor objective 中加入基于开关级可行轨迹的 support regularization。训练阶段使用校准代理模型提高样本效率，最终性能仅以未改动 actor 在开关级 Simulink 故障族矩阵中的结果为准。

不要写：

> 本文提出全新的 SAC 算法。

除非我们真的实现并消融了新的 critic、安全约束或鲁棒目标。

## 9. References

Carreno, A., Perez, M., Baier, C., Huang, A., Rajendran, S., & Malinowski, M. (2021). Configurations, power topologies and applications of hybrid distribution transformers. *Energies, 14*(5), 1215. https://ideas.repec.org/a/gam/jeners/v14y2021i5p1215-d504683.html

Chen, X., Wang, C., Zhou, Z., & Ross, K. (2021). Randomized ensembled double Q-learning: Learning fast without a model. *ICLR 2021*. https://arxiv.org/abs/2101.05982

Cui, M., Zhou, D., Han, Y., Hanasusanto, G. A., Wang, Q., Zhang, H., & Zhou, Z. (2026). DR-SAC: Distributionally robust Soft Actor-Critic for reinforcement learning under uncertainty. *ICLR 2026*. https://arxiv.org/abs/2506.12622

Duan, J., Wang, W., Xiao, L., Gao, J., Li, S. E., Liu, C., Zhang, Y.-Q., Cheng, B., & Li, K. (2025). Distributional Soft Actor-Critic with three refinements. *IEEE Transactions on Pattern Analysis and Machine Intelligence, 47*(5), 3935-3946. https://arxiv.org/abs/2310.05858

Haarnoja, T., Zhou, A., Abbeel, P., & Levine, S. (2018). Soft Actor-Critic: Off-policy maximum entropy deep reinforcement learning with a stochastic actor. *ICML 2018*. https://arxiv.org/abs/1801.01290

Haarnoja, T., Zhou, A., Hartikainen, K., Tucker, G., Ha, S., Tan, J., Kumar, V., Zhu, H., Gupta, A., Abbeel, P., & Levine, S. (2019). Soft Actor-Critic algorithms and applications. https://arxiv.org/abs/1812.05905

Han, H., & Ji, S. (2025). Continuous Soft Actor-Critic: An off-policy learning method robust to time discretization. *NeurIPS 2025*. https://proceedings.neurips.cc/paper_files/paper/2025/hash/6ac12f42db406e6be14d669884e73212-Abstract-Conference.html

Kumar, A., Zhou, A., Tucker, G., & Levine, S. (2020). Conservative Q-learning for offline reinforcement learning. https://arxiv.org/abs/2006.04779

Lai, C., et al. (2025). Enhancing transient performance of hybrid distribution transformer using event-triggered proportional-integral repetitive controller. *IEEE Transactions on Power Electronics*. https://strathprints.strath.ac.uk/94943/1/Lai-etal-IEEE-TPE-2025-Enhancing-transient-performance-of-hybrid-distribution-transformer.pdf

Shang, Z., Yuan, X., Huang, W., Cui, Y., Chen, D., & Zhu, M. (2026). Effective reinforcement learning control using conservative Soft Actor-Critic. https://arxiv.org/abs/2505.03356

Wu, Y., Tucker, G., & Nachum, O. (2019). Behavior regularized offline reinforcement learning. https://arxiv.org/abs/1911.11361

Yu, T., Thomas, G., Yu, L., Ermon, S., Zou, J., Levine, S., Finn, C., & Ma, T. (2020). MOPO: Model-based offline policy optimization. *NeurIPS 2020*. https://arxiv.org/abs/2005.13239

Zhang, B., Zhang, Y., Frison, L., Brox, T., & Bödecker, J. (2024). Constrained reinforcement learning with smoothed log barrier function. https://arxiv.org/abs/2403.14508
