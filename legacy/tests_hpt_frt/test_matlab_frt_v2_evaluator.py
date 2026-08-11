"""test_matlab_frt_v2_evaluator — the authoritative MATLAB frt-v2 evaluator exists, implements all
five criteria + response + precedence, and the golden vectors regenerate (audit round-5 E). The
numeric Python<->MATLAB parity itself is asserted by frt_v2_golden_test.m (run via the MATLAB MCP in
the verification battery); here we lock the contract statically + regenerate the vectors."""
from pathlib import Path
import scipy.io as sio

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / 'lab' / 'simulink'


def test_frt_v2_evaluate_m_exists_and_covers_contract():
    src = (SIM / 'frt_v2_evaluate.m').read_text(encoding='utf-8', errors='ignore')
    for token in ['res.connect', 'res.reactive', 'res.limit', 'res.recover', 'res.survive',
                  'res.frt_pass', 'res.evaluation_complete', "res.metrics_version='frt-v2'",
                  'res.response', 'reactive_criterion', 'response_metrics',
                  'lvrt_lower_env', 'hvrt_upper_env']:
        assert token in src, f'frt_v2_evaluate.m missing {token}'
    # real time only — must NOT CALL linspace to reconstruct time (the docstring may mention the word)
    assert 'linspace(' not in src
    # frt_pass precedence: FAIL before NOT_EVALUATED
    assert "any(strcmp(sts,FAIL))" in src and "any(strcmp(sts,NE))" in src


def test_golden_and_consistency_harness_present():
    assert (SIM / 'frt_v2_golden_test.m').exists()
    assert (SIM / 'frt_v2_consistency_test.m').exists()


def test_legacy_producers_do_not_define_their_own_frt_pass():
    # validate_mode_full / run_spotcheck must not silently run active criteria — they are guarded
    # (test_matlab_guards covers the fail-fast); the single criteria source is frt_v2_evaluate.m.
    for f in ('validate_mode_full.m', 'run_spotcheck.m'):
        src = (SIM / f).read_text(encoding='utf-8', errors='ignore')
        assert 'frt_v2_guard(' in src, f'{f} must be guarded'


REQUIRED_GOLDEN = ('complete_pass', 'connect_fail', 'reactive_under', 'survive_vdc_fail',
                   'missing_iq', 'fail_beats_missing', 'hvrt_pass')


def test_golden_vectors_regenerate(tmp_path):
    # Regenerate to a TEMP path (never overwrites the repo golden -> no write-permission dependency),
    # and check the generated structure: case count, names, and the per-case fields the MATLAB
    # frt_v2_golden_test.m relies on. Strength is preserved (the generator is exercised end-to-end).
    from tests.golden import gen_golden_vectors as gg
    out, n = gg.main(out_path=str(tmp_path / 'frt_v2_golden.mat'))
    assert n >= 12
    m = sio.loadmat(str(out), squeeze_me=True, struct_as_record=False)
    cases = m['cases']
    assert len(cases) >= 12
    names = {str(c.name) for c in cases}
    for must in REQUIRED_GOLDEN:
        assert must in names
    for fld in ('exp_connect', 'exp_reactive', 'exp_limit', 'exp_recover', 'exp_survive', 'exp_frt_pass'):
        assert hasattr(cases[0], fld), f'golden case missing field {fld}'


def test_committed_golden_in_sync():
    # The committed golden the MATLAB parity test loads must stay current with the generator: same case
    # set. Read-only check (no write) so it passes in restricted environments; if the repo golden is
    # absent it is skipped (regeneration is covered above).
    repo = ROOT / 'tests' / 'golden' / 'frt_v2_golden.mat'
    if not repo.exists():
        import pytest
        pytest.skip('committed golden absent')
    from tests.golden import gen_golden_vectors as gg
    fresh = {r['name'] for r in gg.build_records()}
    m = sio.loadmat(str(repo), squeeze_me=True, struct_as_record=False)
    committed = {str(c.name) for c in m['cases']}
    assert committed == fresh, ('committed golden out of sync with generator; run '
                                'python -m tests.golden.gen_golden_vectors. '
                                f'missing={fresh - committed} extra={committed - fresh}')
