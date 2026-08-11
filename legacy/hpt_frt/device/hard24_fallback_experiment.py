"""Compatibility wrapper for legacy hard-24 fallback experiments.

Current pure-SAC work should use ``pure_sac_hard_curriculum.py``. Fallback
experiments are archived under ``hpt_frt.device.legacy``.
"""
from __future__ import annotations

from .legacy.hard24_fallback_experiment import *  # noqa: F401,F403


if __name__ == "__main__":
    from .legacy.hard24_fallback_experiment import main

    main()

