"""Compatibility wrapper for legacy seed-robustness experiments.

Current pure-SAC work should use ``pure_sac_hard_curriculum.py``. The old seed
sweep driver lives in ``hpt_frt.device.legacy.train_seeds``.
"""
from __future__ import annotations

# Training contract: legacy implementation routes env selection through train_common.select_env.
from .legacy.train_seeds import *  # noqa: F401,F403


if __name__ == "__main__":
    from .legacy.train_seeds import main

    main()
