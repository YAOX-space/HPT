# SAC variants for HPT FRT control

This folder stores three SAC-related references for improving the HPT fault-ride-through controller.

| File | Reference | Source |
| --- | --- | --- |
| `dsac_t_distributional_soft_actor_critic_three_refinements_arxiv2310.05858.pdf` | Jingliang Duan et al., "Distributional Soft Actor-Critic with Three Refinements." IEEE TPAMI, 2025. Public preprint: arXiv:2310.05858. | https://arxiv.org/abs/2310.05858 |
| `dr_sac_distributionally_robust_soft_actor_critic_arxiv2506.12622.pdf` | Mingxuan Cui et al., "DR-SAC: Distributionally Robust Soft Actor-Critic for Reinforcement Learning under Uncertainty." arXiv:2506.12622, 2025/2026. | https://arxiv.org/abs/2506.12622 |
| `continuous_soft_actor_critic_time_discretization_neurips2025.pdf` | Huimin Han and Shaolin Ji, "Continuous Soft Actor-Critic: An Off-Policy Learning Method Robust to Time Discretization." NeurIPS 2025. | https://proceedings.neurips.cc/paper_files/paper/2025/hash/6ac12f42db406e6be14d669884e73212-Abstract-Conference.html |

Suggested use for this project:

- DSAC-T: model rare but high-cost transient failures by learning a value/return distribution instead of only an expected value.
- DR-SAC: reduce sensitivity to proxy-to-Simulink mismatch, topology parameter uncertainty, and unseen sag/swell cases.
- Continuous SAC: improve robustness when the SAC decision interval is much slower than the switching-level simulation step.
