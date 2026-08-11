"""Compatibility wrapper for the legacy P3 parallel sweep.

Current pure-SAC work should use ``pure_sac_hard_curriculum.py``. The old sweep
orchestrator lives in ``hpt_frt.device.legacy.run_sweep_parallel``.
"""
from __future__ import annotations

from .legacy.run_sweep_parallel import *  # noqa: F401,F403


if __name__ == "__main__":
    from .legacy.run_sweep_parallel import main

    main()
