"""Compatibility wrapper for legacy SAC A/B experiments.

Current pure-SAC work should use ``pure_sac_hard_curriculum.py``. The old A/B
experiment driver lives in ``hpt_frt.device.legacy.train_ab``.
"""
from __future__ import annotations

# Training contract: legacy implementation routes env selection through train_common.select_env.
from .legacy.train_ab import *  # noqa: F401,F403


if __name__ == "__main__":
    from .legacy.train_ab import main

    main()
