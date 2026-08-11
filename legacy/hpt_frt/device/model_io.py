"""model_io.py — robust SAC checkpoint loading shared by ALL export scripts (audit fix #4).

Old June-18 checkpoints were pickled under numpy>=2 and reference `numpy._core`, which does not exist
in the locked .venv (numpy 1.24.4) -> a plain `SAC.load` raises `No module named numpy._core`. The
new frt-v2 experts are numpy-1.24 clean and load plainly, but to make EVERY export path reproducible
regardless of which checkpoint it touches, route all loads through `load_sac`, which installs the
numpy2->numpy1 module shim and passes `custom_objects` to bypass numpy2-pickled gym spaces/schedules.
"""
from __future__ import annotations
import os, sys
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')

# numpy2 -> numpy1 module alias shim (must run before unpickling any numpy2 checkpoint)
import numpy.core as _np_core            # noqa: F401
for _sub in ['', '.multiarray', '.numeric', '._multiarray_umath', '.umath', '.numerictypes']:
    try:
        sys.modules['numpy._core' + _sub] = __import__('numpy.core' + _sub, fromlist=['x'])
    except Exception:
        pass


def load_sac(path, device='cpu', env=None):
    """Load a SAC checkpoint robustly across numpy1/numpy2 pickles. Returns the SAC model."""
    from stable_baselines3 import SAC
    co = {'lr_schedule': (lambda _: 3e-4), 'clip_range': (lambda _: 0.2)}
    return SAC.load(str(path), device=device, env=env, custom_objects=co)
