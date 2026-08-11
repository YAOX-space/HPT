"""test_actor_contract — the frt-v2 actor shape contract across the three surfaces (audit item 5):
training actor (env spaces), exported .mat weights, and the MATLAB inference constants. No training:
the export path is exercised with a synthetic fake model + synthetic weights."""
from pathlib import Path
import numpy as np
import pytest
import scipy.io as sio
from hpt_frt.device import export_sac_actor as EX
from hpt_frt.device.frt_env_v2 import HPTFRTEnvV2, OBS_DIM_V2, N_ACT_V2

SIM = Path(__file__).resolve().parents[1] / 'lab' / 'simulink'
SC = dict(scenario_id=1, family_id=1, category='LVRT', fault_type='1ph_g', target_V_pu=0.5,
          grid='weak', scr=3.0, t_fault=0.02, fault_dur=0.6, T_sim=2.5, random_seed=1)


# ---- surface 1: the TRAINING actor (env spaces) ----
def test_training_env_is_3d_action_20d_obs():
    e = HPTFRTEnvV2([SC])
    assert e.action_space.shape == (N_ACT_V2,) == (3,)
    assert e.observation_space.shape == (OBS_DIM_V2,) == (20,)


# ---- a synthetic fake SB3 model so the exporter runs without training ----
class _T:
    def __init__(self, a): self.a = np.asarray(a, np.float64)
    def cpu(self): return self
    def numpy(self): return self.a
    @property
    def shape(self): return self.a.shape


class _Space:
    def __init__(self, n): self.shape = (n,); self.low = -0.3 * np.ones(n); self.high = 0.3 * np.ones(n)


class FakeModel:
    def __init__(self, n_obs, n_act, H=256):
        self.observation_space = _Space(n_obs)
        self.action_space = _Space(n_act)
        self._sd = {
            'latent_pi.0.weight': _T(np.zeros((H, n_obs))), 'latent_pi.0.bias': _T(np.zeros(H)),
            'latent_pi.2.weight': _T(np.zeros((H, H))),     'latent_pi.2.bias': _T(np.zeros(H)),
            'latent_pi.4.weight': _T(np.zeros((H, H))),     'latent_pi.4.bias': _T(np.zeros(H)),
            'mu.weight': _T(np.zeros((n_act, H))),          'mu.bias': _T(np.zeros(n_act)),
        }
        self.policy = type('P', (), {'actor': type('A', (), {'state_dict': lambda s: self._sd})()})()
        self.policy.actor._sd = self._sd
    def predict(self, o, deterministic=True):
        return np.zeros(self.action_space.shape[0], np.float64), None


def _patch(monkeypatch, n_obs, n_act):
    # export_actor loads via model_io.load_sac (robust loader) — patch that, not SAC.load
    monkeypatch.setattr(EX, 'load_sac', lambda *a, **k: FakeModel(n_obs, n_act))


import json


def _model_with_sidecar(tmp_path, *, run_id='r1', mv='frt-v2', step=100, proxy=50.0):
    mp = tmp_path / 'm.zip'; mp.write_bytes(b'dummy')
    mp.with_suffix('.json').write_text(json.dumps(dict(
        run_id=run_id, metrics_version=mv, policy_seed=42, checkpoint_step=step,
        validation_partial_proxy_pct=proxy, kind='best')))
    return mp


# ---- surface 2: the EXPORTED .mat weights (now PROVENANCE-GATED, audit C) ----
def test_export_v2_emits_3output_contract_with_provenance(tmp_path, monkeypatch):
    _patch(monkeypatch, 20, 3)
    mp = _model_with_sidecar(tmp_path, run_id='r1', step=175, proxy=60.0)
    out = tmp_path / 'w.mat'
    EX.export_actor(mp, out, legacy=False, expected_run_id='r1')
    W = sio.loadmat(str(out))
    assert int(W['n_obs']) == 20 and int(W['n_act']) == 3 and W['mu_weight'].shape == (3, 256)
    assert str(W['metrics_version'][0]) == 'frt-v2'
    assert str(W['run_id'][0]) == 'r1' and int(W['checkpoint_step']) == 175    # provenance in MAT (C.3)
    assert int(W['policy_seed']) == 42 and 'checkpoint_sha256' in W


def test_export_requires_sidecar(tmp_path, monkeypatch):
    _patch(monkeypatch, 20, 3)
    mp = tmp_path / 'nosidecar.zip'; mp.write_bytes(b'x')
    with pytest.raises(FileNotFoundError):               # no sidecar -> refuse (C.1)
        EX.export_actor(mp, tmp_path / 'o.mat', legacy=False, expected_run_id='r1')


def test_export_rejects_wrong_run_id(tmp_path, monkeypatch):
    _patch(monkeypatch, 20, 3)
    mp = _model_with_sidecar(tmp_path, run_id='OLD_run')
    with pytest.raises(ValueError, match='run_id'):       # sidecar from a different run -> refuse
        EX.export_actor(mp, tmp_path / 'o.mat', legacy=False, expected_run_id='r1')


def test_export_rejects_legacy_4d_unless_flagged(tmp_path, monkeypatch):
    _patch(monkeypatch, 21, 4)
    mp = _model_with_sidecar(tmp_path)
    with pytest.raises(ValueError):                       # 21/4 is not the frt-v2 contract
        EX.export_actor(mp, tmp_path / 'x.mat', legacy=False, expected_run_id='r1')
    EX.export_actor(mp, tmp_path / 'legacy.mat', legacy=True)   # legacy path: no sidecar gate
    W = sio.loadmat(str(tmp_path / 'legacy.mat'))
    assert str(W['metrics_version'][0]) == EX.LEGACY_VARIANT and int(W['n_act']) == 4


# ---- surface 3: the MATLAB inference constants ----
def test_matlab_hlc_declares_matching_contract():
    src = (SIM / 'frt_v2_hlc.m').read_text(encoding='utf-8', errors='ignore')
    assert 'OBS_DIM = 20' in src and 'N_ACT = 3' in src
    # the actor reshape must target the 3-output mu and 20-input layer
    assert 'reshape(W.mu_weight, N_ACT, H)' in src
    assert 'reshape(W.latent_pi_0_weight, H, OBS_DIM)' in src
