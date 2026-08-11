"""test_scenario_usage — every random CSV field must be consumed by the model or be a documented
decorative field (audit M1). Fails if a NEW unused random column appears."""
import inspect
import re
from hpt_frt.device import gen_frt_scenarios
from hpt_frt.device import frt_env

META_FIELDS = {'scenario_id', 'family_id', 'category', 'fault_type', 'grid', 'random_seed'}
KNOWN_DECORATIVE = {'Rg_ohm', 'Lg_H', 'P_load', 'Q_load', 'power_factor',
                    'recover_to_0p9_s', 'trans_resistance'}


def _csv_columns():
    src = inspect.getsource(gen_frt_scenarios.build)
    return set(re.findall(r"'([A-Za-z0-9_]+)':", src))


def test_no_undocumented_unused_random_field():
    cols = _csv_columns()
    env_src = inspect.getsource(frt_env)
    consumed = {c for c in cols if f"'{c}'" in env_src and c not in META_FIELDS}
    unused = cols - META_FIELDS - consumed
    undocumented = unused - KNOWN_DECORATIVE
    assert not undocumented, (
        f'NEW unused random CSV field(s) {undocumented}: feed into the model or remove (audit M1).')


def test_decorative_list_maintained():
    assert KNOWN_DECORATIVE          # resolution (feed or drop) is PENDING P5 — see CHANGE_REPORT
