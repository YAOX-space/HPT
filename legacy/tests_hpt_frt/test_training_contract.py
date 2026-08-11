"""test_training_contract — the training entrypoints must default to the frt-v2 V2 env contract
(20-D obs / 3-D action / de-privileged), residual included, and stamp run metadata. No training is
run — only env selection, a 1-5 step smoke, and the metadata block (audit round-4 C)."""
import importlib
import pytest
from hpt_frt.device import train_common as TC
from hpt_frt.device.frt_env import HPTFRTEnv
from hpt_frt.device.frt_env_v2 import HPTFRTEnvV2, OBS_DIM_V2, N_ACT_V2
from hpt_frt.device.residual_env import HPTFRTResidualEnv, HPTFRTResidualEnvV2


def test_default_env_is_v2_for_both_families():
    assert TC.select_env('frt') is HPTFRTEnvV2
    assert TC.select_env('residual') is HPTFRTResidualEnvV2
    assert TC.select_env('frt', legacy=True) is HPTFRTEnv
    assert TC.select_env('residual', legacy=True) is HPTFRTResidualEnv


@pytest.mark.parametrize('cls', [HPTFRTEnvV2, HPTFRTResidualEnvV2])
def test_v2_envs_are_20d_3d(cls):
    contract, obs, act = TC.env_contract(cls)
    assert contract == 'frt-v2' and obs == OBS_DIM_V2 == 20 and act == N_ACT_V2 == 3


@pytest.mark.parametrize('cls', [HPTFRTEnv, HPTFRTResidualEnv])
def test_legacy_envs_are_21d_4d(cls):
    contract, obs, act = TC.env_contract(cls)
    assert contract == 'frt-v1-legacy' and obs == 21 and act == 4


def test_assert_fresh_contract_rejects_legacy():
    TC.assert_fresh_contract(HPTFRTEnvV2)           # ok
    TC.assert_fresh_contract(HPTFRTResidualEnvV2)   # ok
    with pytest.raises(ValueError, match='frt-v1-legacy'):
        TC.assert_fresh_contract(HPTFRTEnv)


def test_run_metadata_has_required_fields():
    md = TC.run_metadata(HPTFRTEnvV2, seed=42, scenario_split='all-320')
    for k in ('metrics_version', 'env_contract', 'observation_dim', 'action_dim', 'seed',
              'scenario_split', 'env_class', 'training_status'):
        assert k in md, k
    assert md['metrics_version'] == 'frt-v2' and md['observation_dim'] == 20 and md['action_dim'] == 3
    assert 'PENDING' in md['training_status']        # never claims P3 done


@pytest.mark.parametrize('cls', [HPTFRTEnvV2, HPTFRTResidualEnvV2])
def test_smoke_5_steps_builds_v2_env(cls):
    info = TC.smoke(cls, steps=5)
    assert info['env_contract'] == 'frt-v2' and info['observation_dim'] == 20 and info['action_dim'] == 3


def test_entrypoints_import_select_env_and_pass_env_cls():
    # every training entrypoint must route through train_common.select_env (no hard-coded HPTFRTEnv)
    import inspect
    for mod in ('train_frt_sac', 'train_experts', 'train_seeds', 'train_ab', 'train_residual'):
        m = importlib.import_module(f'hpt_frt.device.{mod}')
        src = inspect.getsource(m)
        assert 'select_env' in src, f'{mod} must use train_common.select_env'
        # the legacy env must not be the silent default in vec construction
        assert 'DummyVecEnv([lambda: HPTFRTEnv(' not in src, f'{mod} still hard-codes legacy env'
        assert 'DummyVecEnv([lambda: HPTFRTResidualEnv(' not in src
