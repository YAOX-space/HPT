"""test_deployment_integration — round-5 production-chain fixes: the Mode-5 network wrapper loads the
new 20-D/3-D experts and runs de-privileged; the train/val split is held-out; the proxy flags
saturation; the robust loader works (audit items #1, #6, #7, #8, #4)."""
import numpy as np
import pytest
from hpt_frt.device import train_common as TC
from hpt_frt.device import frt_metrics as FM
from hpt_frt.common import frt_v2 as FV2


# ── #7 train/val split is held-out and deterministic ──
def test_split_is_holdout_and_deterministic():
    scen = [dict(family_id=f, scenario_id=i, category='LVRT', fault_type='sym3ph', target_V_pu=0.5,
                 grid='w', scr=3.0, t_fault=0.02, fault_dur=0.6, T_sim=2.5, random_seed=0)
            for f in range(10) for i in range(3)]
    tr, va = TC.split_scenarios(scen, val_frac=0.2, seed=1)
    tr_fams = {s['family_id'] for s in tr}; va_fams = {s['family_id'] for s in va}
    assert tr and va
    assert tr_fams.isdisjoint(va_fams)               # held-out FAMILIES (no leakage)
    tr2, va2 = TC.split_scenarios(scen, val_frac=0.2, seed=1)
    assert [s['scenario_id'] for s in va] == [s['scenario_id'] for s in va2]   # deterministic
    tr3, va3 = TC.split_scenarios(scen, val_frac=0.2, seed=2)
    assert {s['family_id'] for s in va3} != va_fams  # different seed -> different held-out families


def test_env_seeds_deterministic():
    assert TC.env_seeds(7, 4) == [7000, 7001, 7002, 7003]
    assert TC.env_seeds(7, 4) == TC.env_seeds(7, 4)   # reproducible
    assert len(TC.PRODUCTION_SEEDS) >= 5


# ── #8 proxy honesty: a 100% proxy on ODE must be flagged SATURATED ──
def _crit(s): return {'status': s, 'passed': s == FV2.PASS, 'worst': 0.0, 't_worst': 0.0, 'reason': ''}
def _res(st):
    d = {c: _crit(st[c]) for c in FV2.MANDATORY}
    sts = [d[c]['status'] for c in FV2.MANDATORY]
    d['frt_pass'] = (False if FV2.FAIL in sts else (None if FV2.NOT_EVALUATED in sts else True))
    return d


def test_proxy_saturation_flagged(monkeypatch):
    # ODE-like: connect+reactive PASS, limit+survive+recover NOT_EVALUATED -> proxy 100% but saturated
    ode = _res({'connect': FV2.PASS, 'reactive': FV2.PASS, 'limit': FV2.NOT_EVALUATED,
                'recover': FV2.NOT_EVALUATED, 'survive': FV2.NOT_EVALUATED})
    monkeypatch.setattr(FM, 'evaluate_scenario', lambda model, env_cls, sc: {'kind': 'evaluated', 'res': ode})
    m = FM.evaluate_frt(None, [0, 1], None)
    assert m['partial_proxy_pct'] == 100.0            # the misleading number
    assert m['proxy_saturated'] is True               # ...is flagged
    assert m['proxy_criteria_evaluated_mean'] == 2.0  # only 2/5 evaluable
    assert 'NOT an FRT pass rate' in m['proxy_note']


def test_proxy_not_saturated_when_all_evaluated(monkeypatch):
    full = _res({c: FV2.PASS for c in FV2.MANDATORY})
    monkeypatch.setattr(FM, 'evaluate_scenario', lambda model, env_cls, sc: {'kind': 'evaluated', 'res': full})
    m = FM.evaluate_frt(None, [0], None)
    assert m['proxy_saturated'] is False and m['proxy_criteria_evaluated_mean'] == 5.0


# ── #4 robust loader + #1 network wrapper load the new 20/3 experts ──
@pytest.mark.slow
def test_network_wrapper_loads_v2_experts_and_runs():
    pytest.importorskip('stable_baselines3')
    from pathlib import Path
    models = Path(__file__).resolve().parents[1] / 'data' / 'models'
    # need the full 4-expert set; during a re-run they are regenerated one at a time
    if not all((models / f'sac_{n}_best.zip').exists() for n in ('sym', 'asym', 'hvrt_sym', 'hvrt_asym')):
        pytest.skip('full expert set absent (re-run in progress or models migrated)')
    from hpt_frt.network import sac_wrapper as W
    ex = W.load_experts()
    assert set(ex) == {'sym', 'asym', 'hvrt_sym', 'hvrt_asym'}
    for m in ex.values():
        assert m.observation_space.shape == (20,) and m.action_space.shape == (3,)
    ctl = W.HPTController(bus=18, use_hysteresis=True)
    out = ctl.step(0.45, 0.18, t=0.05)               # de-privileged: derives in_fault from measurement
    assert np.isfinite(out['iq']) and np.isfinite(out['Vdc'])
    r = ctl.steady_command(0.10, 0.0)
    assert np.isfinite(r['iq']) and 0.0 < r['Vdc'] <= 1.25
