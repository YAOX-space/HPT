# HPT SAC 主线研究执行计划

日期：2026-07-28

## 总目标

建立一个可以诚实写进论文的方法：

> SAC-updated HPT controller improves switch-level voltage-survival score over
> a tuned conventional dq baseline under representative fault-family cases.

注意：

- DAgger/BC 不是主方法；
- proxy-only improvement 不算最终成果；
- switch-level Simulink 是最终 gate；
- 当前阶段仍是 voltage-survival，不声明 full FRT certified。

## 当前基线

已有成果：

- 12 / 12 representative specialists 通过 switch-level voltage-survival；
- 12 / 12 beat conventional；
- 0 / 12 full FRT pass；
- 单 case protected SAC 可以带来小幅 score 改善；
- raw family SAC 在 topology2 LVRT family 上失败。

关键失败：

- raw family SAC return 数值爆炸；
- support 外动作；
- topology2 energy/DC-link proxy mismatch；
- reward penalty 不能保证 timestep envelope；
- family generalization 还不稳。

## 阶段 0：冻结主线与证据边界

目标：

- 明确论文主线为 SAC；
- DAgger/BC 只作为初始化/对照/消融；
- 不再把 selector teacher 结果当最终方法。

动作：

1. 在论文方法草稿中把方法名改为 SAC-centered；
2. 在实验表中分清：
   - init/source policy；
   - SAC-updated policy；
   - non-SAC baseline；
3. 每个 accepted actor 记录是否经过 SAC update。

通过标准：

- 每个实验结果都能回答：这个 actor 是否被 SAC 更新过？

## 阶段 1：SAC 失败诊断

目标：

先解释为什么 raw SAC 失败，再改算法。

要记录的信号：

- actor loss；
- critic loss；
- alpha / entropy；
- Q mean / Q min / Q max / Q std；
- raw action；
- projected action；
- action support distance；
- envelope cost；
- recovery cost；
- Vdc cost；
- action-limit cost；
- proxy uncertainty；
- switch-level promotion result。

实验：

1. 复现实验：`topology2_lvrt_family_v1`，3k steps，低学习率；
2. 对照：
   - plain SAC；
   - action projection on/off；
   - reward normalization on/off；
   - behavior support penalty logged but not enforced。

预期输出：

- 一个 SAC failure diagnosis table；
- 确认主要失败来自 critic instability、OOD action、proxy bias 还是 cost softness。

## 阶段 2：Reward / Cost 分离

目标：

不要再用一个 reward 混合所有东西。

设计：

- reward：
  - LV tracking；
  - recovery quality；
  - score improvement；
  - action smoothness；
- cost：
  - `cost_env`：timestep envelope；
  - `cost_recovery`：恢复阶段 envelope；
  - `cost_vdc`：DC link 生存；
  - `cost_action`：动作限幅和 support；
  - `cost_current`：保留给 full FRT 阶段。

实验：

1. 只重构日志，不改变策略；
2. 检查每个 failed episode 的主要 cost 来源；
3. 和 switch-level failure reason 对齐。

通过标准：

- proxy cost ranking 能解释 switch-level failure reason；
- 如果不能解释，先修 proxy/cost，不训练大 SAC。

## 阶段 3：BRAC-SAC / CQL-SAC

目标：

让 SAC 在 switch-supported action 区域内探索，而不是乱搜。

BRAC-SAC：

```text
L_actor = SAC_actor_loss + beta * support_distance(pi(a|s), D_support)
```

CQL-SAC：

```text
L_Q = Bellman_loss + alpha_cql * [Q(s,a_ood) - Q(s,a_data)]
```

support data 来源：

- accepted SAC specialist trajectories；
- calibration sweep；
- switch-level passed action chunks；
- failed actions作为 negative support。

实验顺序：

1. topology2 balanced LVRT 0.90 / 60ms；
2. topology2 A-LVRT 0.90 / 60ms；
3. topology2 AB-LVRT 0.90 / 60ms；
4. topology2 LVRT mini-family holdout。

通过标准：

- action-limit violation 明显下降；
- proxy-OOD action 明显下降；
- 至少不破坏原 accepted specialist；
- switch-level score 不低于 init actor。

## 阶段 4：Constrained SAC

目标：

把 voltage-survival 从 soft reward 变成 constrained objective。

方法：

```text
maximize reward
subject to:
  E[cost_env] <= eps_env
  E[cost_recovery] <= eps_rec
  E[cost_vdc] <= eps_vdc
  E[cost_action] <= eps_act
```

实现选项：

- SAC-Lagrangian；
- WCSAC-style safety critic；
- log-barrier cost；
- action projection 作为执行层。

实验：

1. 从 BRAC-SAC 最稳版本开始；
2. 加 cost critic；
3. 每 1k/3k/10k steps 做 switch-level spot promotion。

通过标准：

- envelope/recovery/Vdc/action failure 不再反复出现；
- 即使 score 改善小，也要先保证 feasibility。

## 阶段 5：Proxy Bias 修复

目标：

避免 SAC 利用 proxy 漏洞。

方法：

- proxy ensemble；
- holdout action-response alignment；
- trajectory-level proxy-vs-Simulink ranking；
- uncertainty penalty。

实验：

1. 对 topology2 energy branch 重建 action-response matrix；
2. 训练 5 个 proxy ensemble；
3. 对每个 SAC candidate 记录 disagreement；
4. 高 disagreement candidate 不进入 switch-level full matrix。

通过标准：

- proxy top candidate 在 Simulink 中不再频繁崩；
- proxy ranking Spearman correlation 在 holdout 上达到可接受水平；
- 如果 ranking 不可靠，只允许 proxy 做粗筛。

## 阶段 6：Family SAC 推广

目标：

从 single-case specialist 走向 fault-family SAC。

顺序：

1. topology2 LVRT family；
2. topology1 unbalanced LVRT/HVRT score optimization；
3. topology2 HVRT family；
4. balanced + unbalanced reduced boundary；
5. 630 matrix 的分层验证。

通过标准：

- 同一 family actor 能通过多个 depth/duration/phase case；
- SAC-updated actor 比 conventional 更优；
- SAC-updated actor 比 init actor 有可量化提升；
- reward/cost 收敛图能解释提升来源。

## 最小下一轮实验

我建议下一轮先做一个小而完整的闭环：

1. 选 case：`topology2 balanced LVRT 0.90 pu / 60 ms`；
2. 复现 plain SAC 失败或退化；
3. 加 instrumentation；
4. 加 BRAC support penalty；
5. 加 cost-separated logging；
6. 做 switch-level spot promotion；
7. 如果通过，再扩展到 A/AB LVRT。

这轮不是为了立刻跑 630 matrix，而是为了证明：

> 改进后的 SAC 机制能阻止 raw SAC 的失稳，并保留或提升 switch-level voltage-survival。

## 研究输出

每轮必须输出：

- config；
- reward/cost trace；
- actor/critic/alpha trace；
- proxy validation；
- switch-level validation；
- failure classification；
- 是否更新论文 claim。

如果某轮失败，也保留为 diagnostic evidence，不删除。
