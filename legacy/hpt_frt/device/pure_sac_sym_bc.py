"""Compatibility wrapper for legacy symmetric-fault behavior cloning.

Current pure-SAC work should use ``pure_sac_hard_curriculum.py``. BC warm-start
experiments are archived under ``hpt_frt.device.legacy``.
"""
from __future__ import annotations

from .legacy.pure_sac_sym_bc import *  # noqa: F401,F403


if __name__ == "__main__":
    from .legacy.pure_sac_sym_bc import main

    main()

