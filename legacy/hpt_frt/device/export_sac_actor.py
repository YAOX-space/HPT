"""Export the SAC actor (deterministic mean) weights + obs/action specs to .mat for the Simulink HLC.

frt-v2 + PROVENANCE GATE (audit round-5 C): an export is allowed ONLY for a checkpoint that carries a
valid sidecar JSON (written by train_common.CheckpointSelector) whose run_id matches the current
corrected re-run. The export verifies obs=(20,), act=(3,), mu.weight=(3,256), metrics_version=frt-v2
and the checkpoint SHA256, and writes run_id / seed / checkpoint_step / validation_proxy / SHA256 into
the MAT so a stale or untraceable model can never reach Simulink.
"""
import json
from pathlib import Path
import numpy as np, scipy.io as sio
from .model_io import load_sac
from .train_common import sha256_file

ROOT = Path(__file__).resolve().parent
MODELS = ROOT.parents[2] / 'data' / 'models'
LAB = ROOT.parents[2] / 'lab'
LEGACY_VARIANT = 'frt-v1-legacy'


def current_run_id():
    f = LAB / 'results' / '.p3_current_runid'
    return f.read_text().strip() if f.exists() else None


def _require_sidecar(model_path, expected_run_id):
    """Load + validate the checkpoint sidecar (audit C.1/C.2). Returns the sidecar dict or raises."""
    side = Path(model_path).with_suffix('.json')
    if not side.exists():
        raise FileNotFoundError(f'{Path(model_path).name}: NO sidecar JSON — refusing to export an '
                                f'untraceable checkpoint (audit C.1). Re-run training with the fixed '
                                f'CheckpointSelector.')
    d = json.loads(side.read_text())
    if expected_run_id is not None and d.get('run_id') != expected_run_id:
        raise ValueError(f'{Path(model_path).name}: sidecar run_id={d.get("run_id")!r} != current '
                         f'run {expected_run_id!r} — checkpoint is not from this corrected re-run.')
    if d.get('metrics_version') != 'frt-v2':
        raise ValueError(f'{Path(model_path).name}: sidecar metrics_version={d.get("metrics_version")!r}')
    sha = sha256_file(model_path)
    if d.get('model_sha256') and d['model_sha256'] != sha:
        raise ValueError(f'{Path(model_path).name}: SHA256 mismatch vs sidecar (file changed).')
    d['_verified_sha256'] = sha
    return d


def export_actor(model_path, out_path, *, legacy=False, expected_run_id='__current__'):
    """Export one actor. legacy=False requires a valid frt-v2 sidecar from the current run."""
    model_path = Path(model_path)
    if expected_run_id == '__current__':
        expected_run_id = current_run_id()
    side = None if legacy else _require_sidecar(model_path, expected_run_id)
    m = load_sac(model_path, device='cpu')
    sd = m.policy.actor.state_dict()
    n_obs = int(np.prod(m.observation_space.shape)); n_act = int(np.prod(m.action_space.shape))
    mu_w = sd['mu.weight'].cpu().numpy()
    if not legacy and (n_obs != 20 or n_act != 3 or tuple(mu_w.shape) != (3, 256)):
        raise ValueError(f'{model_path.name}: contract {n_obs}/{n_act} mu{tuple(mu_w.shape)} != frt-v2 20/3 (3,256)')
    W = {k.replace('.', '_'): v.cpu().numpy().astype('float64')
         for k, v in sd.items() if ('latent_pi' in k or k.startswith('mu.'))}
    W['act_low'] = m.action_space.low.astype('float64')
    W['act_high'] = m.action_space.high.astype('float64')
    W['n_obs'] = np.array([[n_obs]], 'float64'); W['n_act'] = np.array([[n_act]], 'float64')
    W['metrics_version'] = LEGACY_VARIANT if legacy else 'frt-v2'
    if side is not None:                                   # provenance into the MAT (audit C.3)
        W['run_id'] = side['run_id']; W['policy_seed'] = np.array([[side['policy_seed']]], 'float64')
        W['checkpoint_step'] = np.array([[side['checkpoint_step']]], 'float64')
        W['validation_proxy'] = np.array([[side.get('validation_partial_proxy_pct') or np.nan]], 'float64')
        W['checkpoint_sha256'] = side['_verified_sha256']
        W['checkpoint_kind'] = side['kind']
    rng = np.random.default_rng(0)                        # fixed obs_test/act_test (audit C.4)
    obs_test = rng.uniform(-1, 1, size=(8, n_obs)).astype('float64'); obs_test[:, 0] = rng.uniform(0.4, 1.2, 8)
    W['obs_test'] = obs_test
    W['act_test'] = np.array([m.predict(o, deterministic=True)[0] for o in obs_test], dtype='float64')
    sio.savemat(str(out_path), W)
    tag = '' if legacy else f' run={side["run_id"]} step={side["checkpoint_step"]} proxy={side.get("validation_partial_proxy_pct")}'
    print(f'exported {model_path.name}: {n_obs}/{n_act} ({W["metrics_version"]}){tag} -> {Path(out_path).name}')
    return W


def promote_single_sac(run_id='__current__'):
    """Promote the frt-v2 single-SAC ablation FINAL (Mode 3) to sac_frt_best/final, copying its
    sidecar too so provenance is preserved (audit C.5). Prefers *_final (this-run, sidecar'd)."""
    import shutil
    if run_id == '__current__':
        run_id = current_run_id()
    src = MODELS / 'ablation_single_final.zip'
    if not src.exists():
        src = MODELS / 'ablation_single_best.zip'
    _require_sidecar(src, run_id)                          # must be a valid this-run checkpoint
    for dst in ('sac_frt_best.zip', 'sac_frt_final.zip'):
        shutil.copyfile(src, MODELS / dst)
        shutil.copyfile(src.with_suffix('.json'), (MODELS / dst).with_suffix('.json'))
    print(f'promoted {src.name} -> sac_frt_best/final.zip (+sidecars) as Mode-3 production')
    return src


def choose_residual(run_id='__current__'):
    """Pick raw vs EMA residual by the FROZEN validation proxy in the sidecars; export the winner.
    Records both scores + the reason (audit C.6)."""
    if run_id == '__current__':
        run_id = current_run_id()
    cands = {}
    for kind, fn in (('raw', 'sac_residual_best.zip'), ('ema', 'sac_residual_ema_best.zip')):
        p = MODELS / fn
        if p.exists() and p.with_suffix('.json').exists():
            cands[kind] = (p, _require_sidecar(p, run_id))
    if not cands:
        raise FileNotFoundError('no residual checkpoint with a valid this-run sidecar')
    best = max(cands.items(), key=lambda kv: (kv[1][1].get('validation_partial_proxy_pct') or -1))
    kind, (p, side) = best
    scores = {k: v[1].get('validation_partial_proxy_pct') for k, v in cands.items()}
    print(f'residual choice: {kind} (val proxy {scores}) — reason: higher frozen-val proxy')
    return p, kind, scores


def main():
    rid = current_run_id()
    if not rid:
        raise RuntimeError('no current run_id (lab/results/.p3_current_runid) — run the re-sweep first')
    promote_single_sac(rid)
    export_actor(MODELS / 'sac_frt_best.zip', LAB / 'sac_actor_weights.mat', expected_run_id=rid)
    for nm in ('sym', 'asym', 'hvrt_sym', 'hvrt_asym'):
        export_actor(MODELS / f'sac_{nm}_best.zip', LAB / f'sac_{nm}_weights.mat', expected_run_id=rid)
    rp, kind, scores = choose_residual(rid)
    export_actor(rp, LAB / 'sac_residual_weights.mat', expected_run_id=rid)
    print(f'\nexported 6 frt-v2 weight MATs (residual={kind}); all provenance-gated to run {rid}')


if __name__ == '__main__':
    main()
