"""Compatibility wrapper for the legacy single SAC trainer.

Current pure-SAC work should use ``pure_sac_hard_curriculum.py``. The original
all-scenario trainer lives in ``hpt_frt.device.legacy.train_frt_sac``.
"""
from __future__ import annotations

# Training contract: legacy implementation routes env selection through train_common.select_env.
from .legacy.train_frt_sac import *  # noqa: F401,F403


if __name__ == "__main__":
    from .legacy.train_frt_sac import main

    main()
