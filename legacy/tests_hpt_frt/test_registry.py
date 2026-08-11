"""test_registry — no ACTIVE machine-readable registry may expose a legacy frt-v1 score as valid
(governance, audit G / acceptance: validity='pending-frt-v2', score=None)."""
import re
from pathlib import Path
from hpt_frt.device import controller_registry as REG

REPO = Path(__file__).resolve().parents[1]


def test_no_mode_exposes_live_numeric_score():
    for mid, rec in REG.MODES.items():
        assert rec.get('score') is None, f'Mode {mid} still has live score={rec.get("score")}'


def test_all_non_infra_modes_pending_frt_v2():
    for mid, rec in REG.MODES.items():
        v = rec.get('validity')
        assert v in ('pending-frt-v2', 'n/a', 'pending', None), \
            f'Mode {mid} validity={v} must be pending-frt-v2 (or n/a for infra)'
    # at least the controller modes carry pending-frt-v2 (not the old 'valid')
    assert any(r.get('validity') == 'pending-frt-v2' for r in REG.MODES.values())
    assert all(r.get('validity') != 'valid' for r in REG.MODES.values())


def test_matlab_registry_has_no_valid_scores():
    txt = (REPO / 'lab' / 'simulink' / 'controller_modes.m').read_text(encoding='utf-8')
    # the legacy 'valid NN%' status strings must be gone from the active table rows
    assert not re.search(r"'valid[ -]\d", txt), 'controller_modes.m still marks a mode valid with a score'
    assert 'pending-frt-v2' in txt
