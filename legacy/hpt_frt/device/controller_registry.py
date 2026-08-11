"""controller_registry.py — single source of truth for HPT-FRT controller modes (Python side).

Mirrors CONTROL_MODES.md (repo root). Canonical modes are 0-6. The Simulink HLC's INTERNAL
integer dispatch (mi==4/5/6/7/8/10/11/12/13/14) and the result filenames frt320_m{N}_* are
LEFT UNCHANGED (renumbering would force a full rebuild + re-validation of every result, which
would either invalidate results or require fabrication). This module exposes the canonical 0-6
system and a deprecation alias from legacy internal codes.

Main method = Mode 5 (online-gated multi-expert SAC). Mode 6 (MPC-assisted residual SAC) is an
EXTENSION, not the main method, and is NOT "pure SAC". See CONTROL_MODES.md §0/§6.

NO RESULT MAY BE COPIED FROM ONE MODE TO ANOTHER. Modes/variants not re-validated under the
unified protocol carry validity='pending' (待验证).
"""
from __future__ import annotations
import warnings

# canonical mode registry (id -> record). Keep in sync with CONTROL_MODES.md §1/§3.
MODES = {
    0: dict(name='Calibration / no-HLC', zh='标定/无高层控制', family='infra',
            learning=False, model_prior=False, oracle=False, deployable=None,
            period=None, action_dim=None, status='active-infra', main=False,
            internal=None, results=None, validity='n/a', paper_role='标定与模型自检'),
    1: dict(name='Tuned fixed-law controller', zh='最强固定律控制', family='fixed-law',
            learning=False, model_prior=False, oracle=False, deployable=True,
            period='20us', action_dim=3, status='active', main=False,
            internal=7, results='frt320_m7_*', validity='pending-frt-v2', score=None, legacy_frt_v1_score=64.06,  # 205/320
            paper_role='传统控制基线'),
    2: dict(name='One-step explicit MPC', zh='一步显式 MPC', family='model-based',
            learning=False, model_prior=True, oracle=False, deployable=True,
            period='2ms', action_dim=3, status='active', main=False,
            internal=8, results='frt320_m8_*', validity='pending-frt-v2', score=None, legacy_frt_v1_score=79.69,  # 255/320
            paper_role='模型驱动基线'),
    3: dict(name='Unified SAC', zh='单一 SAC', family='learning',
            learning=True, model_prior=False, oracle=False, deployable=True,
            period='2ms', action_dim=3, status='active', main=False,
            internal=11, results='frt320_m11_*', validity='pending-frt-v2', score=None, legacy_frt_v1_score=44.38,  # 142/320, 2026-06-18 switching full-320
            paper_role='单策略消融'),
    4: dict(name='Oracle-gated expert SAC', zh='Oracle 门控多专家 SAC', family='learning',
            learning=True, model_prior=False, oracle=True, deployable=False,
            period='2ms', action_dim=3, status='active', main=False,
            internal=15, results='frt320_m15_*', validity='pending-frt-v2', score=None, legacy_frt_v1_score=81.25,  # 260/320, 2026-06-18, ablation only
            paper_role='理想门控消融(性能上限)'),
    5: dict(name='Online-gated expert SAC', zh='在线门控多专家 SAC', family='learning',
            learning=True, model_prior=False, oracle=False, deployable=True,
            period='2ms', action_dim=3, status='active', main=True,         # ★ MAIN METHOD
            internal=12, results='frt320_m12_*',
            validity='pending-frt-v2',  # frt-v1 score 82.2 INVALIDATED (audit 2026-06-22); retrain+frt-v2 PENDING
            score=None, legacy_frt_v1_score=82.19, paper_role='★ 本文主方法'),  # 263/320
    6: dict(name='MPC-assisted residual SAC', zh='MPC 辅助残差 SAC', family='learning+model',
            learning=True, model_prior=True, oracle=False, deployable=True,
            period='dual-rate 20us/2ms', action_dim=3, status='active', main=False,
            internal=14, results='frt320_m14_*', validity='pending-frt-v2', score=None, legacy_frt_v1_score=96.25,  # 308/320
            paper_role='扩展性能方法(非主方法、非纯 SAC)'),
    7: dict(name='Expert-prior residual SAC', zh='专家先验残差 SAC(纯学习混合)', family='learning',
            learning=True, model_prior=False, oracle=False, deployable=True,
            period='2ms', action_dim=3, status='active', main=False,
            internal=17, results='p3_full320_sw_mi17',
            # NOTE: validity is the FROZEN governance marker (same convention as certified mi=14/7 which
            # also read 'pending-frt-v2'); the authoritative frt-v2 numbers live in FRT_V2_RESULTS.
            validity='pending-frt-v2', score=None,
            frt_v2_strict=42.5, frt_v2_nofail=82.2,               # 136/57/127 full-320 switching (CERTIFIED 2026-06-25, NEGATIVE result)
            paper_role='负结果：残差≈0(专家已饱和)，弱于 Mode 6 之 MPC 先验直流管理。见 docs/FRT_V2_RESULTS_2026-06-23.md ADDENDUM'),
}

# legacy internal HLC integer -> canonical mode (or None if deprecated with no canonical id).
# Deprecated entries map to a note; callers must migrate. See CONTROL_MODES.md §2.
_LEGACY = {
    7: 1, 8: 2, 11: 3, 12: 5, 14: 6, 15: 4,
    4: None,   # dq-legacy -> deprecated (failure-demo / historical 27.5%)
    5: None,   # Song-style -> deprecated historical
    6: None,   # Jia-style  -> deprecated historical
    10: None,  # fixed-setpoint probe -> calibration config (Mode 0 family)
    13: None,  # SAC/MPC hybrid -> deprecated (historical 88.4%)
}
_LEGACY_NOTE = {
    4: 'dq-legacy (deprecated, failure-demo; historical 27.5%)',
    5: 'Song-style fixed law (deprecated historical; see dq_variants_*)',
    6: 'Jia-style fixed law (deprecated historical; see dq_variants_*)',
    10: 'fixed-setpoint probe (deprecated; now a calibration configuration, Mode 0 family)',
    13: 'SAC/MPC domain-partition hybrid (deprecated; historical 88.4%)',
}


def resolve_legacy(internal_mode: int) -> int | None:
    """Map a legacy internal HLC integer to a canonical 0-6 mode, with a deprecation warning.
    Returns the canonical id, or None for deprecated-without-canonical (raises a clear warning)."""
    if internal_mode in _LEGACY:
        new = _LEGACY[internal_mode]
        if new is None:
            warnings.warn(f"[controller_registry] internal mode {internal_mode} is DEPRECATED: "
                          f"{_LEGACY_NOTE.get(internal_mode,'')}. It has no canonical 0-6 id and "
                          f"must not appear in papers/lectures.", DeprecationWarning, stacklevel=2)
            return None
        warnings.warn(f"[controller_registry] legacy internal mode {internal_mode} -> canonical "
                      f"Mode {new} ({MODES[new]['name']}). Use the canonical id.",
                      DeprecationWarning, stacklevel=2)
        return new
    raise KeyError(f"unknown internal mode {internal_mode}")


def main_method() -> int:
    return next(k for k, v in MODES.items() if v.get('main'))


if __name__ == '__main__':
    print("Canonical HPT-FRT controller modes (see CONTROL_MODES.md):")
    for k, v in MODES.items():
        tag = ' ★MAIN' if v.get('main') else ''
        sc = f" {v.get('score')}%" if v.get('score') else ''
        print(f"  Mode {k}: {v['name']} / {v['zh']} [{v['validity']}{sc}]{tag}")
    print(f"\nMain method = Mode {main_method()}")
