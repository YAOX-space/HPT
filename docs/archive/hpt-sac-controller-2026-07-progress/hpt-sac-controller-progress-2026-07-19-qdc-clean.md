# HPT SAC Progress 2026-07-19: Q/DC Clean Boundary

## 本轮目标

本轮继续推进 topology2 LVRT specialist SAC/full-action actor，重点回答两个问题：

1. 当前 SAC 偏差主要来自 proxy 不准，还是训练方法不够？
2. 在分 topology / 分故障训练后，能否得到真实 switch-level voltage-survival specialist？

## 已完成

1. 重新验证了 topology2 `0.92 pu` 和 `0.95 pu` LVRT 的局部动作边界。
   - `0.92 pu` 精扫 18 个 switch-level 点，7 个通过 voltage-survival 且 beat conventional。
   - `0.95 pu` 精扫 18 个 switch-level 点，3 个通过 voltage-survival 且 beat conventional。

2. 修正了 proxy/dataset 的污染问题。
   - 旧矩阵中存在一类错误 pass 标注：`m_energy_d` 为正时被认为 DC link 安全。
   - 新 switch-level 复验显示这些点会触发 `dc_link_bounds`。
   - 已从校准与训练源中排除旧的污染矩阵：
     - `frt_calibration_matrix_local_sweep_topology2_lvrt80_095_20260718_0210.csv`
     - `frt_calibration_matrix_success_bc_topology2_lvrt80_095_20260718_0210.csv`
     - `frt_calibration_matrix_switchval_counterexamples_topology2_lvrt_20260718_0156.csv`

3. 增强了 `success_bc_style` 训练器。
   - 新增 `--success-top-k` 参数。
   - 对窄动作岛使用 `--success-top-k 1`，避免多个 pass 动作平均后落入失败区。

4. 得到并验证了新的 switch-level 成功结果。
   - `topology2 / LVRT / 0.92 pu / 80 ms`
     - actor: `hpt_offline_qdc_clean2_top1_topo2_lvrt_byfault_20260719_topology2_lvrt_80ms_0p920pu_td3_bc_style.pt`
     - fixed-action switch-level voltage-survival pass: yes
     - beats conventional: yes
     - score: `132.400` vs conventional `285.096`
     - LV mean/recovery: `186.686 / 220.554 V`
     - Vdc min/max: `787.089 / 996.054 V`
   - `topology2 / LVRT / 0.95 pu / 80 ms`
     - actor: `hpt_offline_qdc_clean2_top1_topo2_lvrt_byfault_20260719_topology2_lvrt_80ms_0p950pu_success_bc_style.pt`
     - fixed-action switch-level voltage-survival pass: yes
     - beats conventional: yes
     - score: `129.356` vs conventional `239.881`
     - LV mean/recovery: `194.536 / 220.304 V`
     - Vdc min/max: `671.954 / 998.620 V`

5. 更新了 accepted specialist manifest。
   - 新增 `topology2_lvrt092_80ms`。
   - `0.95 pu` 已有更高分 accepted actor，因此本轮 top-1 actor 作为修复验证记录，不替换最佳 accepted 行。

## 关键判断

当前偏差主要不是单纯训练不够，而是两类问题叠加：

1. Proxy/dataset 中有旧 switch-level 数据污染，尤其 energy branch 的 DC-link 响应。
2. 在窄动作岛场景，连续 actor 如果模仿多个成功点的均值，可能插值到真实失败区域。

本轮证明：去除污染数据，并把窄动作岛的 behavior target 改成 top-1 后，proxy 训练结果可以转移到 switch-level，至少在 topology2 `0.92/0.95 pu` LVRT voltage-survival 目标下成立。

## 仍未完成

1. 这还不是 full FRT certified controller。
   - 两个成功点仍然失败于完整 FRT 判据：
     - `gbt_voltage_envelope`
     - `gbt_recover`
     - `grid_current_limit`
     - `reactive_wrong_sign`

2. 当前通过的是 voltage-survival specialist，不是满足并网无功支撑标准的最终控制器。

3. 还没有把同样的 clean/top-1 机制系统扩展到 topology1、HVRT、非对称故障和更长 fault-transition waveform。

## 下一步

1. 对 topology1/topology2 的每个 fault depth 建立 clean matrix source manifest，禁止混入旧污染矩阵。
2. 对每个窄动作岛默认使用 `success-top-k=1` 或支持投影训练；对宽动作岛保留 `top-k > 1`。
3. 扩展 switch-level validation matrix：
   - LVRT: `0.2/0.5/0.75/0.85/0.9/0.92/0.925/0.95 pu`
   - HVRT: `1.1/1.2/1.25/1.3 pu`
4. 在 voltage-survival 通过后，再单独优化 full-FRT current/reactive gates。
