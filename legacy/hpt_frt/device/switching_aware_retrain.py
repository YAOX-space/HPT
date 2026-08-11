"""Compatibility wrapper for legacy switching-aware retraining.

Current pure-SAC work should use ``pure_sac_hard_curriculum.py``. Switching
aware repair experiments are archived under ``hpt_frt.device.legacy``.
"""
from __future__ import annotations

from .legacy.switching_aware_retrain import *  # noqa: F401,F403


if __name__ == "__main__":
    from .legacy.switching_aware_retrain import main

    main()

