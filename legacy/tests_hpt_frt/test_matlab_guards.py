"""test_matlab_guards — result-producing MATLAB scripts that still run LEGACY frt-v1 criteria must
NOT be able to silently execute or emit files mistakable for frt-v2 (audit item 3). Static text
checks (no MATLAB needed)."""
from pathlib import Path
import pytest

SIM = Path(__file__).resolve().parents[1] / 'lab' / 'simulink'


def _read(name):
    return (SIM / name).read_text(encoding='utf-8', errors='ignore')


def test_guard_helpers_exist():
    assert (SIM / 'frt_v2_guard.m').exists()
    assert (SIM / 'assert_metrics_version.m').exists()


def test_frt_v2_guard_fails_fast_and_redirects_to_legacy():
    g = _read('frt_v2_guard.m')
    assert 'HPT:PENDING_FRT_V2' in g                       # throws by default
    assert 'HPT_ALLOW_LEGACY_FRT' in g                     # only an explicit flag enables it
    assert 'legacy_pre_audit' in g                         # output forced into legacy folder


@pytest.mark.parametrize('script', ['validate_mode_full.m', 'run_spotcheck.m'])
def test_legacy_result_producers_are_guarded(script):
    src = _read(script)
    assert 'frt_v2_guard(' in src, f'{script} must call frt_v2_guard before producing results'
    assert 'metrics_version' in src, f'{script} must tag results with metrics_version'
    # the guard must appear before the first save() so legacy criteria cannot run unguarded
    gi = src.index('frt_v2_guard(')
    si = src.find('save(')
    assert si == -1 or gi < si, f'{script}: guard must precede the first save()'


def test_legacy_producers_no_longer_write_active_results_path():
    # validate_mode_full must write under legacy_pre_audit, not the active ../results/frt320 path
    v = _read('validate_mode_full.m')
    assert "legacy_root" in v and "frt320_m%d_%s" in v
    assert "'../results/frt320_m%d_%s'" not in v          # the old active path is gone
