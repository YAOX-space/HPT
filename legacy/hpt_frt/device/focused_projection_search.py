"""Compatibility wrapper for legacy focused projection search.

Current pure-SAC work should use ``pure_sac_hard_curriculum.py``. Projection
repair experiments are archived under ``hpt_frt.device.legacy``.
"""
from __future__ import annotations

from .legacy.focused_projection_search import *  # noqa: F401,F403


if __name__ == "__main__":
    from .legacy.focused_projection_search import main

    main()

