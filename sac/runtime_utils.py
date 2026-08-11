"""Runtime helpers for current HPT SAC scripts."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("MKL_THREADING_LAYER", "SEQUENTIAL")


def pick_device() -> str:
    """Return ``cuda`` when available unless ``HPT_FORCE_CPU`` is set."""

    if os.environ.get("HPT_FORCE_CPU"):
        return "cpu"
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def _install_numpy2_pickle_shim() -> None:
    """Allow old numpy>=2 pickled SB3 checkpoints to load under numpy 1.x."""

    import numpy.core as _np_core  # noqa: F401

    for submodule in (
        "",
        ".multiarray",
        ".numeric",
        "._multiarray_umath",
        ".umath",
        ".numerictypes",
    ):
        try:
            sys.modules["numpy._core" + submodule] = __import__(
                "numpy.core" + submodule,
                fromlist=["x"],
            )
        except Exception:
            pass


def load_sac(path, device: str = "cpu", env=None):
    """Load a Stable-Baselines3 SAC checkpoint with repository compatibility shims."""

    _install_numpy2_pickle_shim()
    from stable_baselines3 import SAC

    custom_objects = {
        "lr_schedule": lambda _: 3e-4,
        "clip_range": lambda _: 0.2,
    }
    return SAC.load(str(path), device=device, env=env, custom_objects=custom_objects)
