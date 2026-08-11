"""Compatibility wrapper for the legacy expert trainer.

Current pure-SAC work should use ``pure_sac_hard_curriculum.py``. The original
expert-training implementation lives in ``hpt_frt.device.legacy.train_experts``.
"""
from __future__ import annotations

# Training contract: legacy implementation routes env selection through train_common.select_env.
from .legacy.train_experts import *  # noqa: F401,F403


if __name__ == "__main__":
    from .legacy.train_experts import main

    main()
