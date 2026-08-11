"""Compatibility wrapper for the legacy parallel-sweep worker.

Current pure-SAC work should use ``pure_sac_hard_curriculum.py``. The original
worker implementation lives in ``hpt_frt.device.legacy.train_single``.
"""
from __future__ import annotations

from .legacy.train_single import *  # noqa: F401,F403


if __name__ == "__main__":
    from .legacy.train_single import main

    main()
