# SAC Training Engine

`train_hpt_voltage_sac.py` is the maintained support-regularized SAC training
engine used by the family campaign. Despite the directory name, it is not an
independent promotion path: its checkpoints are only proxy-trained candidates
until exported and passed through the switch-level evaluator.

Obsolete per-case trainers, generic offline-RL comparisons, and offline action
promotion scripts were removed. Historical outputs remain in `lab/results/`.
