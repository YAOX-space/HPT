"""test_network_screening — the network/metrics phasor layer is QUARANTINED screening, and must
never present itself as frt-v2 certification (audit item 2)."""
import inspect
from hpt_frt.network import metrics as M


def test_metrics_version_is_not_frt_v2():
    assert M.METRICS_VERSION == 'frt-v1-phasor-screening'
    assert M.METRICS_VERSION != 'frt-v2'
    assert M.EVALUATION_SCOPE == 'static-phasor-snapshot'


def test_device_criteria_never_emits_frt_pass_true():
    # even an all-pass screen returns screen_pass (a screening flag) and frt_pass tombstone None
    out = M.device_criteria(Vp=1.0, Vn=0.0, iq=0.0, se_d=0.0, se_q=0.0, iq_ref=0.0,
                            vdc_min=1.0, vdc_max=1.0, v_load=1.0, gate=1.0, dur=0.1)
    assert out['screen_pass'] is True                # screening flag may be True
    assert out['frt_pass'] is None                   # but the FRT verdict is NEVER True here
    assert 'frt_pass' not in {k for k, v in out.items() if v is True}
    assert out['metrics_version'] == 'frt-v1-phasor-screening'
    assert out['evaluation_scope'] == 'static-phasor-snapshot'


def test_aggregate_carries_scope_and_keeps_nonconverged_separate():
    rows = [
        M.system_metrics([dict(connect=True, reactive=True, limit=True, recover=True, survive=True,
                               screen_pass=True, v_load=1.0, kvar=10.0)],
                         dict(converged=True, minV=0.5)),
        M.system_metrics([dict(connect=False, reactive=False, limit=True, recover=True, survive=False,
                               screen_pass=False, v_load=0.0, kvar=0.0)],
                         dict(converged=False, minV=0.0)),   # non-converged
    ]
    agg = M.aggregate(rows)
    assert agg['metrics_version'] == 'frt-v1-phasor-screening'
    assert agg['evaluation_scope'] == 'static-phasor-snapshot'
    assert agg['frt_pass_pct'] is None               # never an FRT pass rate
    assert 'screen_pass_pct' in agg                  # screening rate is the only headline number
    assert agg['n_nonconverged'] == 1 and agg['convergence_pct'] == 50.0   # non-converged is visible


def test_source_never_sets_frt_pass_true():
    src = inspect.getsource(M)
    assert 'frt_pass=True' not in src and 'frt_pass = True' not in src
