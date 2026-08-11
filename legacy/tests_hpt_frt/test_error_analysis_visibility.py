"""Tests for automatic ODE-visible / ODE-blind routing in error analysis."""
from hpt_frt.common import frt_v2 as FV2
from hpt_frt.device import error_analysis_mi14 as EA


def _crit(status):
    return {'status': status, 'passed': status == FV2.PASS, 'worst': 0.0,
            't_worst': 0.0, 'reason': ''}


def _res(**overrides):
    statuses = {c: FV2.PASS for c in EA.CRITERIA}
    statuses.update(overrides)
    out = {c: _crit(statuses[c]) for c in EA.CRITERIA}
    out['frt_pass'] = False if FV2.FAIL in statuses.values() else True
    out['metrics_version'] = FV2.METRICS_VERSION
    return out


def test_ode_visibility_matches_failed_criterion_and_survive_proxy(monkeypatch):
    fails = [
        {'sid': 1, 'failed_criteria': 'reactive'},
        {'sid': 2, 'failed_criteria': 'survive'},
        {'sid': 3, 'failed_criteria': 'reactive'},
    ]
    monkeypatch.setattr(EA, 'load_frt_scenarios',
                        lambda path: [{'scenario_id': 1}, {'scenario_id': 2}, {'scenario_id': 3}])
    monkeypatch.setattr(EA, 'load_sac', lambda path: object())
    monkeypatch.setattr(EA, 'residual_model_path', lambda: EA.MODELS / 'stub.zip')

    def classify(model, env_cls, scenario):
        sid = int(scenario['scenario_id'])
        if sid == 1:
            return {'kind': 'evaluated', 'res': _res(reactive=FV2.FAIL)}
        if sid == 2:
            r = _res()
            r['survive']['status'] = FV2.NOT_EVALUATED
            r['vdc_survive_proxy'] = FV2.FAIL
            r['vdc_min'] = 0.7
            return {'kind': 'evaluated', 'res': r}
        return {'kind': 'evaluated', 'res': _res()}

    monkeypatch.setattr(EA, 'evaluate_scenario', classify)

    labels, summary = EA.classify_ode_visibility(fails)

    assert labels[1]['ode_visibility'] == 'VISIBLE'
    assert labels[1]['ode_matched_criteria'] == 'reactive'
    assert labels[2]['ode_visibility'] == 'VISIBLE'
    assert labels[2]['ode_matched_criteria'] == 'survive'
    assert labels[3]['ode_visibility'] == 'BLIND'
    assert summary['counts'] == {'VISIBLE': 2, 'BLIND': 1}
