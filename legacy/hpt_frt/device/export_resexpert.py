"""export_resexpert.py — export the 4-expert+residual hybrid's RESIDUAL actor (raw best vs EMA best —
picks the higher ODE proxy) to sac_resexpert_weights.mat for HLC mode-17, and copy into simulink/.

The 4 EXPERT weights are exported separately by export_experts.py (sac_{sym,asym,hvrt_sym,hvrt_asym}
_weights.mat); HLC mi==17 loads the gated expert as the PRIOR + this residual on top. Mirror of
export_residual.py but: reads the frt-v2 residual-expert train JSON, writes a 20-D obs_test (frt-v2),
and emits sac_resexpert_weights.mat.
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import json, shutil
from pathlib import Path
import numpy as np, scipy.io as sio
from stable_baselines3 import SAC

ROOT = Path(__file__).resolve().parent
MODELS = ROOT.parents[2] / 'data' / 'models'
LAB = ROOT.parents[2] / 'lab'
TRAIN_JSON = LAB / 'results' / 'residual_expert_train.json'


def main():
    if TRAIN_JSON.exists():
        j = json.loads(TRAIN_JSON.read_text())
        pick = ('sac_resexpert_ema_best.zip' if j.get('best_ema', -1) >= j.get('best_raw', -1)
                else 'sac_resexpert_best.zip')
        print(f"ODE bests: raw={j.get('best_raw')} ema={j.get('best_ema')} -> exporting {pick}")
    else:
        pick = 'sac_resexpert_best.zip'
        print(f'{TRAIN_JSON.name} absent -> defaulting to {pick}')
    m = SAC.load(str(MODELS / pick), device='cpu')
    assert m.observation_space.shape == (20,) and m.action_space.shape == (3,), \
        f'expected 20-D/3-D frt-v2 residual, got {m.observation_space.shape}/{m.action_space.shape}'
    sd = m.policy.actor.state_dict()
    W = {k.replace('.', '_'): v.cpu().numpy().astype('float64')
         for k, v in sd.items() if 'latent_pi' in k or k.startswith('mu.')}
    W['act_low'] = m.action_space.low.astype('float64')
    W['act_high'] = m.action_space.high.astype('float64')
    W['n_obs'] = np.array([[20]], 'float64'); W['n_act'] = np.array([[3]], 'float64')
    W['metrics_version'] = 'frt-v2'
    # provenance into the MAT (mirror export_sac_actor.export_actor field names exactly — the HLC,
    # spotcheck and full-320 read run_id / checkpoint_sha256 / etc. from the .mat for traceability).
    side = json.loads((MODELS / pick).with_suffix('.json').read_text(encoding='utf-8'))
    W['run_id'] = side['run_id']
    W['policy_seed'] = np.array([[side['policy_seed']]], 'float64')
    W['checkpoint_step'] = np.array([[side['checkpoint_step']]], 'float64')
    W['validation_proxy'] = np.array([[side.get('validation_partial_proxy_pct') or np.nan]], 'float64')
    W['checkpoint_sha256'] = side['model_sha256']
    W['checkpoint_kind'] = side['kind']
    rng = np.random.default_rng(0)
    ot = rng.uniform(-1, 1, (4, 20)).astype('float64'); ot[:, 0] = rng.uniform(0.4, 1.2, 4)   # 20-D (frt-v2)
    W['obs_test'] = ot
    W['act_test'] = np.array([m.predict(o, deterministic=True)[0] for o in ot], 'float64')
    sio.savemat(str(LAB / 'sac_resexpert_weights.mat'), W)
    shutil.copy(str(LAB / 'sac_resexpert_weights.mat'), str(LAB / 'simulink' / 'sac_resexpert_weights.mat'))
    print('exported + copied sac_resexpert_weights.mat  act_test[0]=', W['act_test'][0])


if __name__ == '__main__':
    main()
