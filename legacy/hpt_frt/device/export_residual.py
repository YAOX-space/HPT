"""Export the residual-SAC actor (raw best vs EMA best — picks the higher ODE score) to
sac_residual_weights.mat for HLC mode-14, and copy into simulink/."""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import json, shutil, time
from pathlib import Path
import numpy as np, scipy.io as sio
from stable_baselines3 import SAC
from .train_common import sha256_file
from .frt_env import load_frt_scenarios
from .frt_metrics import evaluate_frt
from .residual_env import HPTFRTResidualEnvV2

ROOT = Path(__file__).resolve().parent
MODELS = ROOT.parents[2] / 'data' / 'models'
LAB = ROOT.parents[2] / 'lab'
TRAIN_JSON = LAB / 'results' / 'residual_train.json'
LEGACY_TRAIN_JSON = LAB / 'results' / 'legacy_pre_audit' / 'residual_train.json'
SELECTION_JSON = LAB / 'results' / 'residual_export_selection.json'
SCEN = LAB / 'frt_scenarios.csv'


def train_json_pick():
    train_json = TRAIN_JSON if TRAIN_JSON.exists() else LEGACY_TRAIN_JSON
    j = json.loads(train_json.read_text())
    raw_best = j.get('best_raw', j.get('best', -1))
    ema_best = j.get('best_ema', -1)
    pick = 'sac_residual_ema_best.zip' if ema_best >= raw_best else 'sac_residual_best.zip'
    return pick, train_json, dict(raw=raw_best, ema=ema_best)


def select_by_full320_ode():
    candidates = [MODELS / name for name in (
        'sac_residual_best.zip', 'sac_residual_ema_best.zip',
        'sac_residual_final.zip', 'sac_residual_ema_final.zip')
        if (MODELS / name).exists()]
    scenarios = load_frt_scenarios(SCEN)
    scores = {}
    best = None
    for path in candidates:
        model = SAC.load(str(path), device='cpu')
        metrics = evaluate_frt(model, scenarios, HPTFRTResidualEnvV2, n_eval=None)
        score = metrics['partial_proxy_pct']
        scores[path.name] = dict(partial_proxy_pct=score,
                                 vdc_survive_proxy_pct=metrics.get('vdc_survive_proxy_pct'),
                                 n_decided_fail=metrics.get('n_decided_fail'))
        print(f'full-320 ODE candidate {path.name}: proxy={score:.1f}% '
              f'vdc={metrics.get("vdc_survive_proxy_pct")}% fail={metrics.get("n_decided_fail")}')
        key = (score, path.name.endswith('_ema_final.zip'), path.name.endswith('_final.zip'))
        if best is None or key > best[0]:
            best = (key, path)
    if best is None:
        raise FileNotFoundError('no residual checkpoints available for full-320 ODE selection')
    return best[1].name, scores


def main():
    pick, train_json, train_scores = train_json_pick()
    selection = dict(selection_basis='frozen-val train JSON', train_scores=train_scores)
    if os.environ.get('HPT_RESIDUAL_EXPORT_SELECT_FULL320') == '1':
        pick, full_scores = select_by_full320_ode()
        selection = dict(selection_basis='full-320 ODE proxy', full320_scores=full_scores,
                         train_scores=train_scores)
    print(f"exporting {pick} ({train_json.name}; {selection['selection_basis']})")
    side_path = (MODELS / pick).with_suffix('.json')
    side = json.loads(side_path.read_text(encoding='utf-8')) if side_path.exists() else {}
    m = SAC.load(str(MODELS / pick), device='cpu')
    sd = m.policy.actor.state_dict()
    W = {k.replace('.', '_'): v.cpu().numpy().astype('float64')
         for k, v in sd.items() if 'latent_pi' in k or k.startswith('mu.')}
    W['act_low'] = m.action_space.low.astype('float64')
    W['act_high'] = m.action_space.high.astype('float64')
    W['n_obs'] = np.array([[int(np.prod(m.observation_space.shape))]], 'float64')
    W['n_act'] = np.array([[int(np.prod(m.action_space.shape))]], 'float64')
    W['metrics_version'] = side.get('metrics_version', 'frt-v2')
    if side:
        winner = side.get('winner') or {}
        source = Path(side.get('source_model', '')) if side.get('source_model') else None
        default_run = side.get('promoted_as') or side.get('model_file') or pick
        W['run_id'] = side.get('run_id') or f"promoted:{default_run}"
        W['policy_seed'] = np.array([[side.get('policy_seed', -1)]], 'float64')
        W['checkpoint_step'] = np.array([[side.get('checkpoint_step', -1)]], 'float64')
        val = (side.get('validation_partial_proxy_pct')
               or (winner.get('expanded2040') or {}).get('pass_pct')
               or np.nan)
        W['validation_proxy'] = np.array([[val]], 'float64')
        checkpoint_sha = side.get('model_sha256') or side.get('source_sha256')
        if not checkpoint_sha:
            checkpoint_sha = sha256_file(source) if source and source.exists() else sha256_file(MODELS / pick)
        W['checkpoint_sha256'] = checkpoint_sha
        W['checkpoint_kind'] = side.get('kind') or side.get('layer') or 'promoted'
    rng = np.random.default_rng(0)
    obs_dim = int(W['n_obs'][0, 0])
    ot = rng.uniform(-1, 1, (4, obs_dim)).astype('float64'); ot[:, 0] = rng.uniform(0.4, 1.2, 4)
    W['obs_test'] = ot
    W['act_test'] = np.array([m.predict(o, deterministic=True)[0] for o in ot], 'float64')
    sio.savemat(str(LAB / 'sac_residual_weights.mat'), W)
    shutil.copy(str(LAB / 'sac_residual_weights.mat'), str(LAB / 'simulink' / 'sac_residual_weights.mat'))
    SELECTION_JSON.write_text(json.dumps(dict(generated_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
                                              selected_model=pick, sidecar=side, **selection),
                                         indent=2), encoding='utf-8')
    print('exported + copied sac_residual_weights.mat  act_test[0]=', W['act_test'][0])
    print(f'wrote {SELECTION_JSON}')


if __name__ == '__main__':
    main()
