# HPT SAC 下一阶段项目整理与任务清单

日期：2026-08-11

## 0. 当前结论

当前项目应同时维护两条线：

1. `tuition/` 教学线：用于理解和演示 topology1 的 HPT 基础结构。
2. `` 研究线：用于 SAC/FRT 控制器、开关级验证和论文证据。

两条线不能混为一谈。`tuition/` 可以说“基础拓扑和基础控制已完成”；`` 目前不能说 SAC 已完成，因为当前 `current_research_state.json` 明确指出 v3 validator 下没有 promoted controller。

当前正式控制器合同为：

```text
observation_dim = 24
action_dim = 4
actions = [m_reg_d, m_reg_q, m_energy_d, m_energy_q]
```

当前正式目标为：

```text
training_target_gate = L1 voltage-survival
```

不是 L2/L3 full FRT，也不是 SAC 全局优于 dq/PI。

## Gate A：项目文件整理

### 目标

把当前工作区中的成果、实验产物和临时文件分层，避免后续实验和论文证据互相污染。

### 当前状态

- `tuition/` 目录是 untracked，但里面的 topology1 tutorial 测试报告已经显示基础测试通过。
- `simulink/topoloty1/` 已显示删除。
- `simulink/topology1/` 已出现为 untracked，说明错误拼写 `topoloty1` 到正确 `topology1` 的迁移已经在工作区发生，但还没有被 git 正式记录。
- 工作区有大量 untracked 模型、proxy、results、actor checkpoint，需要区分证据和临时输出。

### 完成标准

- `topoloty1` 不再作为当前路径使用。
- `topology1` 路径下文件完整：
  - `build_hpt_v2_1to1_switchlevel.m`
  - `hpt_v2_1to1_switchlevel.slx`
  - `hpt_sac_actor_weights_dynamic.mat`
  - `test_hpt_v2_1to1_pure_switchlevel.m`
- `tuition/` 明确标注为教学模型，不参与 v3 SAC promotion。
- 新增文档、BibTeX、tutorial 产物和正式研究产物分组清楚。

### 下一步动作

1. 做一次 git scope audit，只列出需要保留的路径。
2. 将 `topology1` 重命名迁移作为单独变更组。
3. 将 SAC 背景文档作为单独变更组。
4. 对大体量实验输出只保留 compact manifest、summary、关键 CSV，不把所有临时输出都当作论文证据。

## Gate B：24-D / 4-D 控制器合同审计

### 目标

确保 Python、MATLAB、Simulink、文档中的 SAC 接口完全一致。

### 当前状态

当前正式合同来自 `docs/autonomy/current_research_state.json`：

```text
observation_dim = 24
action_dim = 4
actions = [m_reg_d, m_reg_q, m_energy_d, m_energy_q]
```

旧文档中仍可能存在历史的 `16-D observation` 描述。这个描述只能作为历史阶段，不能再作为当前实现依据。

### 完成标准

- `sac/hpt_voltage_sac_env.py` 明确输出 24-D observation。
- `sac/offline/train_hpt_voltage_sac.py` 明确训练 24-D/4-D actor。
- Simulink SAC 接口测试覆盖 24-D observation 和 4-D action。
- 文档中如果提到 16-D，必须标注为 old/early/historical。
- 论文方法段只使用 24-D/4-D 合同。

### 下一步动作

1. 用 `rg "16-D|16D|observation.*16|24-D|OBS_DIM_HPT"` 全局扫描。
2. 更新旧架构文档。
3. 跑 Python contract tests。
4. 跑 Simulink interface tests。

## Gate C：proxy-2.0 timestep transition dataset

### 目标

解决当前最核心的问题：proxy-to-switch mismatch。

### 当前状态

已有 reduced Phase-A 4-case trajectory smoke：

```text
A x {0.825,0.900} pu x {60,120} ms
504 timestep rows
2944 strong-dq BC anchor samples
```

该数据只支持 diagnostic，不支持 promotion。

当前日志明确要求：

```text
Expand proxy-2.0 timestep transition dataset
Split into calibration / validation / untouched holdout
Integrate proxy-2.0 transition model into SAC environment
```

### 完成标准

- 数据不再只是 4-case smoke。
- 至少覆盖 topology2 single-phase LVRT 的声明故障族 split。
- 每条 transition row 至少包含：
  - fault context
  - time
  - state
  - action
  - next state
  - LV/Vdc/grid-current/sequence metrics
  - violation fields
- 数据集明确拆分为：
  - calibration/train
  - validation
  - untouched holdout
- 报告两个 alignment：
  - fixed-action alignment
  - trajectory-rollout ranking alignment

### 下一步动作

1. 从 strong-dq baseline trajectories 提取 transition rows。
2. 加入 accepted expert trajectories。
3. 在可行轨迹周围加入小扰动，扩展 action support。
4. 生成 dataset manifest，记录 source rows、hash、split rule。
5. 训练或拟合 proxy-2.0 transition model。
6. 在 holdout 上报告 one-step RMSE 和 autoregressive rollout ranking。

## Gate D：support-regularized SAC 小矩阵验证

### 目标

先证明当前 SAC 主线能在小矩阵上稳定工作，再谈更大的 family promotion。

### 背景依据

根据 SAC 背景调研，目前不应直接跳到 DSAC-T、DR-SAC 或 Continuous SAC。当前最合理的主线是：

```text
SplitHeadSACActor
+ SupportRegularizedSAC
+ switch-supported action dataset
+ switch-level validation gate
```

当前实现已经包含：

- regulating bridge head
- energy bridge head
- support regularization
- actor/critic/reward/cost tracing

### 推荐 actor loss

```text
L_actor =
    E_s[alpha * log pi(a|s) - min(Q1, Q2)(s,a)]
  + lambda_support * E_(s,a_ref)[w(s) * ||scale(a_actor) - scale(a_ref)||^2]
```

其中：

- `a_ref` 来自 strong-dq、DAgger 或 switch-supported action。
- `scale()` 必须把 physical action 映射到 SB3 actor 的 `[-1, 1]`。
- `w(s)` 应优先强化边界工况、恢复段和 Vdc 风险段。

### 完成标准

- SAC trainer 不再依赖 `--allow-uncalibrated-fault-proxy` 做主要 claim。
- 每次训练记录：
  - reward
  - unscaled reward
  - actor loss
  - actor base loss
  - critic loss
  - entropy coefficient
  - support loss
  - action drift
  - cost summaries
- 导出的未改动 actor 通过同一 switch-level small matrix。
- 同一矩阵中包含 strong-dq baseline 对照。

### 下一步动作

1. 固定一个 small matrix，例如 Phase-A LVRT 边界 8 到 12 个 cell。
2. 用 proxy-2.0 训练 support-regularized SAC。
3. 导出 actor。
4. 用 `eval_hpt_v2_control_comparison.m` 做开关级验证。
5. 如果 SAC 只在 proxy 上好、switch-level 不好，回到 Gate C。

## Gate E：safety cost / constrained SAC 升级

### 目标

把 HPT 的硬约束从普通 reward shaping 中拆出来，为 CSAC-LB / Lagrangian SAC 做准备。

### 背景依据

HPT 故障穿越不是简单最大化平均 reward 的任务。下列指标不能只作为软偏好：

- DC-link bounds
- load voltage envelope
- grid current limit
- action/modulation limit
- recovery band

CSAC-LB 一类 constrained SAC 文献说明，真实控制任务更适合将 reward 与 constraint cost 分开建模。

### 推荐结构

```text
reward:
  voltage quality
  recovery quality
  action smoothness

cost:
  cost_vdc
  cost_envelope
  cost_grid_current
  cost_action_limit
  cost_support
```

短期可做 Lagrangian SAC：

```text
L_actor_safe =
    L_actor
  + beta_vdc * E[cost_vdc]
  + beta_env * E[cost_envelope]
  + beta_i * E[cost_grid_current]
  + beta_a * E[cost_action_limit]
```

长期再升级为：

- CSAC-LB：log-barrier / safety critic
- DSAC-T：tail-risk critic
- DR-SAC：proxy/topology uncertainty
- Continuous SAC：time-discretization robustness

### 完成标准

- cost 与 reward 分开记录、分开汇总。
- promotion gate 仍由 switch-level validator 判断，不由 proxy reward 判断。
- safety cost 升级必须做 ablation：
  - base support-regularized SAC
  - + Lagrangian cost
  - + barrier/safety critic

## Gate F：family-level promotion

### 目标

从 diagnostic 进入可发表的 switch-level evidence。

### 完成标准

一个候选 SAC 控制器只有在满足以下条件时，才能进入 promotion 讨论：

- 一个故障族使用一个 unchanged checkpoint。
- 不使用 per-case actor。
- 不使用 hidden runtime selector。
- 使用同一 v3 evaluator。
- 使用同一 tuned conventional dq baseline。
- 所有行包含 current schema 与 `scenario_valid=true`。
- 报告通过数、失败原因、质量分数和关键约束。
- 能清楚说明 claim rung：
  - rung 3：switch-level single-case result
  - rung 4：unchanged actor passing switch-level fault-family matrix
  - rung 5：boundary expansion over tuned baseline

### 不能提前声称

在 Gate F 前不能写：

- SAC 完成 full FRT。
- SAC 全局优于 dq/PI。
- SAC 可迁移所有 12 个 fault families。
- proxy-only result 是最终控制器证据。

## 建议的执行顺序

```text
Gate A: 项目整理
  -> Gate B: 24-D/4-D contract audit
  -> Gate C: proxy-2.0 transition dataset
  -> Gate D: support-regularized SAC small-matrix validation
  -> Gate E: constrained/safety SAC upgrade
  -> Gate F: family-level promotion
```

## 最近一周最小行动计划

### Day 1：整理与合同审计

- 固定 `topology1` 正确目录。
- 标注 `tuition/` 为教学模型。
- 全局清理或标注旧 16-D 文档。
- 跑 Python contract tests。

### Day 2-3：proxy-2.0 数据扩展

- 从 strong-dq trajectory 提取 transition rows。
- 形成 train/validation/holdout split。
- 输出 dataset manifest。

### Day 4：proxy-2.0 alignment

- 训练 transition proxy。
- 报告 one-step RMSE。
- 报告 short-rollout ranking。
- 确认 proxy ranking 是否可用于 SAC。

### Day 5-6：small-matrix SAC

- 训练 support-regularized SAC。
- 导出 actor。
- 跑 switch-level small matrix。
- 与 strong-dq baseline 对比。

### Day 7：证据归档

- 写入 research log。
- 更新 current state。
- 归档失败候选原因。
- 只在通过 gate 后推进 claim rung。

## 当前优先级判断

最高优先级不是实现最新 SAC 变体，而是：

```text
proxy-2.0 transition data
+ support-regularized SAC
+ switch-level validation
```

DSAC-T、CSAC-LB、DR-SAC、Continuous SAC 都是下一阶段增强项。它们适合写在背景和 future extension 中；真正进入实现前，必须先有一个稳定的 support-regularized SAC 小矩阵闭环。
