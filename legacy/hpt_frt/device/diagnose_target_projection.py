"""Compatibility wrapper for legacy projection diagnostics.

Current pure-SAC work should use ``pure_sac_hard_curriculum.py``. This
projection diagnostic is archived under ``hpt_frt.device.legacy``.
"""
from __future__ import annotations

from .legacy.diagnose_target_projection import *  # noqa: F401,F403


if __name__ == "__main__":
    from .legacy.diagnose_target_projection import main

    main()

