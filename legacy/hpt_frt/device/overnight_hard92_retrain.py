"""Compatibility wrapper for legacy hard-92 residual retraining.

Current pure-SAC work should use ``pure_sac_hard_curriculum.py``. Residual
repair experiments are archived under ``hpt_frt.device.legacy``.
"""
from __future__ import annotations

from .legacy.overnight_hard92_retrain import *  # noqa: F401,F403


if __name__ == "__main__":
    from .legacy.overnight_hard92_retrain import main

    main()

