"""train_common.py — frt-v2 training-contract helpers shared by all training entrypoints
(audit round-4 C). Centralises (a) env selection — default = frt-v2 V2 env, `--legacy` = the legacy
21-D/4-D env — and (b) the run-metadata block that EVERY model/log/JSON must carry.

No training happens here. Loading an existing 21-D/4-D checkpoint to *continue* frt-v2 training is
forbidden: the obs/action contract differs, so the warm-start would be silently wrong.
"""
from __future__ import annotations
import math, json, time, uuid, hashlib, subprocess
from pathlib import Path
import numpy as np
from .frt_env import HPTFRTEnv
from .frt_env_v2 import HPTFRTEnvV2, OBS_DIM_V2, N_ACT_V2
from .residual_env import HPTFRTResidualEnv, HPTFRTResidualEnvV2
from .residual_expert_env import HPTFRTResidualExpertEnvV2
from ..common import frt_v2 as FV2

# (default frt-v2 env, legacy env) per family. 'residual_expert' is frt-v2 only (no legacy variant);
# the legacy slot reuses the v2 class so `--legacy` is a harmless no-op rather than a crash.
ENV_FAMILIES = {
    'frt':             (HPTFRTEnvV2, HPTFRTEnv),
    'residual':        (HPTFRTResidualEnvV2, HPTFRTResidualEnv),
    'residual_expert': (HPTFRTResidualExpertEnvV2, HPTFRTResidualExpertEnvV2),
}


def pick_device():
    """'cuda' if a GPU is available else 'cpu' (audit fix #9). HPT_FORCE_CPU=1 forces CPU — used by the
    parallel orchestrator so N concurrent workers don't fight over one laptop GPU (CUDA init crashes)."""
    import os, torch
    if os.environ.get('HPT_FORCE_CPU'):
        return 'cpu'
    return 'cuda' if torch.cuda.is_available() else 'cpu'


def env_seeds(base_seed, n_envs):
    """DETERMINISTIC per-env seeds derived from the run seed (audit fix #6) — replaces the global
    np.random.randint so a run is fully reproducible from (base_seed, n_envs) alone."""
    return [int(base_seed) * 1000 + i for i in range(n_envs)]


# the production seed set: >=5 distinct seeds for the robustness study (audit fix #6).
# seed 42 is trained by train_experts/train_frt_sac; train_seeds covers the rest.
PRODUCTION_SEEDS = [42, 7, 123, 2024, 31]

# FROZEN train/val split seed — INDEPENDENT of the policy seed. All policy seeds share the SAME
# held-out family partition, so the 5-seed spread isolates the POLICY-seed effect (init/exploration)
# and does NOT confound it with "which families were held out". (Fixes the per-seed-split issue.)
FROZEN_SPLIT_SEED = 777


def split_scenarios(scen, val_frac=0.2, seed=0):
    """Deterministic train/VAL split (audit fix #7) so the checkpoint proxy is on HELD-OUT scenarios,
    not the training set. Splits by `family_id` when present (held-out FAMILIES -> val is OOD w.r.t.
    the families seen in training); falls back to a scenario-level split when there is only one family.
    Returns (train, val), both non-empty."""
    import numpy as np
    scen = list(scen)
    if len(scen) < 2:
        return scen, scen
    rng = np.random.default_rng(seed)
    fams = sorted({s.get('family_id') for s in scen if s.get('family_id') is not None})
    if len(fams) > 1:
        n_val = max(1, int(round(len(fams) * val_frac)))
        val_fams = set(np.asarray(rng.choice(fams, n_val, replace=False)).tolist())
        train = [s for s in scen if s.get('family_id') not in val_fams]
        val = [s for s in scen if s.get('family_id') in val_fams]
    else:
        idx = rng.permutation(len(scen)); cut = max(1, int(len(scen) * val_frac))
        val = [scen[i] for i in idx[:cut]]; train = [scen[i] for i in idx[cut:]]
    if not train:
        train = val[:1]
    if not val:
        val = train[:1]
    return train, val


def select_env(family='frt', legacy=False):
    """Return the env class for `family`. Default = frt-v2 (20-D obs / 3-D action / de-privileged /
    versioned envelope). legacy=True returns the audited legacy env (21-D / 4-D)."""
    v2, leg = ENV_FAMILIES[family]
    return leg if legacy else v2


def env_contract(env_cls):
    """(env_contract_str, observation_dim, action_dim) read from the env spaces — never hard-coded."""
    probe = dict(scenario_id=0, family_id=0, category='LVRT', fault_type='1ph_g', target_V_pu=0.5,
                 grid='weak', scr=3.0, t_fault=0.02, fault_dur=0.6, T_sim=2.5, random_seed=0)
    e = env_cls([probe])
    obs_dim = int(np.prod(e.observation_space.shape))
    act_dim = int(np.prod(e.action_space.shape))
    legacy = obs_dim != OBS_DIM_V2 or act_dim != N_ACT_V2
    return ('frt-v1-legacy' if legacy else 'frt-v2'), obs_dim, act_dim


def run_metadata(env_cls, *, seed, scenario_split, legacy=False, **extra):
    """The metadata block stamped into every model sidecar / training JSON / log header."""
    contract, obs_dim, act_dim = env_contract(env_cls)
    md = dict(metrics_version=FV2.METRICS_VERSION,
              env_contract=contract,
              env_class=env_cls.__name__,
              observation_dim=obs_dim,
              action_dim=act_dim,
              seed=seed,
              scenario_split=scenario_split,
              legacy_run=bool(legacy),
              # the ODE retrain may complete, but the reported proxy is NOT a certified FRT pass rate:
              # limit/survive are NOT_EVALUATED in the averaged ODE, so Simulink frt-v2 certification
              # (P1 criteria rewrite + full-320) remains PENDING regardless of training completion.
              training_status='ODE-proxy training; Simulink frt-v2 certification (P1/full-320) PENDING '
                              '(proxy is NOT a certified pass rate)')
    md.update(extra)
    return md


def assert_fresh_contract(env_cls):
    """Guard: refuse to (warm-)start frt-v2 training on a non-20/3 env contract."""
    contract, obs_dim, act_dim = env_contract(env_cls)
    if contract != 'frt-v2':
        raise ValueError(f'{env_cls.__name__} is {contract} (obs={obs_dim}/act={act_dim}); frt-v2 '
                         f'training requires a 20-D/3-D env. Use --legacy explicitly for legacy runs.')


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Checkpoint provenance + selection (audit round-5 A): every saved model gets a sidecar JSON that
# makes it traceable to run_id / seed / split / step / validation metrics; the selector fixes the
# best=0 / `>best` bug (first eval ALWAYS saved; ties keep the EARLIER checkpoint; rule recorded).
# ──────────────────────────────────────────────────────────────────────────────────────────────

def working_tree_fingerprint():
    """git commit + dirty flag if available, else a hash of the src tree — for checkpoint provenance."""
    root = Path(__file__).resolve().parents[2]
    try:
        head = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                                       stderr=subprocess.DEVNULL).decode().strip()
        dirty = bool(subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain'],
                                             stderr=subprocess.DEVNULL).decode().strip())
        return f'{head}{"+dirty" if dirty else ""}'
    except Exception:
        h = hashlib.sha256()
        for p in sorted((root / 'src' / 'hpt_frt').rglob('*.py')):
            h.update(p.read_bytes())
        return 'srchash:' + h.hexdigest()[:16]


def sha256_file(path):
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return h.hexdigest()


def new_run_id(tag='p3'):
    return f'{tag}_{int(time.time())}_{uuid.uuid4().hex[:8]}'


def make_run_context(*, run_id, policy_seed, env_cls, scenario_split, train_scn, val_scn,
                     n_envs, total_steps, source_log=None):
    """Frozen provenance for a training run — embedded into every sidecar."""
    contract, obs_dim, act_dim = env_contract(env_cls)
    tr_fams = sorted({s.get('family_id') for s in train_scn if s.get('family_id') is not None})
    va_fams = sorted({s.get('family_id') for s in val_scn if s.get('family_id') is not None})
    split_hash = hashlib.sha256(json.dumps({'train': tr_fams, 'val': va_fams}).encode()).hexdigest()[:16]
    return dict(
        run_id=run_id, created_at=time.strftime('%Y-%m-%dT%H:%M:%S'), created_at_epoch=time.time(),
        metrics_version=FV2.METRICS_VERSION, env_contract=contract, env_class=env_cls.__name__,
        observation_dim=obs_dim, action_dim=act_dim, policy_seed=int(policy_seed),
        deterministic_env_seeds=env_seeds(policy_seed, n_envs), scenario_split=scenario_split,
        train_family_ids=tr_fams, val_family_ids=va_fams, split_hash=split_hash,
        n_train=len(train_scn), n_val=len(val_scn), total_steps=int(total_steps),
        working_tree_fingerprint=working_tree_fingerprint(), source_log=source_log)


def _metrics_provenance(m):
    """Pull the validation-metric block for a sidecar from an evaluate_frt result dict."""
    crit = {}
    for c in FV2.MANDATORY:
        crit[c] = {'pass_pct': m.get(c), 'not_eval_pct': m.get(c + '_not_eval_pct')}
    return dict(validation_partial_proxy_pct=m.get('partial_proxy_pct'),
                proxy_saturated=m.get('proxy_saturated'),
                proxy_criteria_evaluated_mean=m.get('proxy_criteria_evaluated_mean'),
                frt_pass_pct=m.get('frt_pass_pct'),
                n_requested=m.get('n_requested'), n_rollout_ok=m.get('n_rollout_ok'),
                n_complete=m.get('n_complete'), n_incomplete=m.get('n_incomplete'),
                n_unevaluable=m.get('n_unevaluable'), criteria=crit)


def write_sidecar(model_path, run_ctx, *, kind, checkpoint_step, metrics, selection_rule=None):
    """Write `<model>.json` provenance next to a saved checkpoint. Includes the model SHA256."""
    model_path = Path(model_path)
    side = dict(model_file=model_path.name, kind=kind, checkpoint_step=int(checkpoint_step),
                model_sha256=sha256_file(model_path), selection_rule=selection_rule,
                **run_ctx, **_metrics_provenance(metrics))
    model_path.with_suffix('.json').write_text(json.dumps(side, indent=2), encoding='utf-8')
    return side


def assert_no_stale_target(path, run_started_epoch):
    """fail-fast (audit A.7): if the target best/final already exists and is OLDER than this run's
    start, it is a stale candidate that must be migrated first — refuse to silently keep/overwrite it
    in a way that could pollute selection."""
    p = Path(path)
    if p.exists() and p.stat().st_mtime < run_started_epoch:
        raise RuntimeError(f'STALE checkpoint {p.name} (mtime {time.strftime("%H:%M:%S", time.localtime(p.stat().st_mtime))} '
                           f'< run start {time.strftime("%H:%M:%S", time.localtime(run_started_epoch))}). '
                           f'Migrate it to data/models/legacy_pre_resweep/ before re-running (audit A.8).')


class CheckpointSelector:
    """Fixes the best=0 / `proxy>best` pollution bug (audit A.1-A.3):
      * best initialised to -inf;
      * the FIRST evaluation is ALWAYS saved (even if proxy=0);
      * thereafter overwrite ONLY if proxy is STRICTLY greater than the current best;
      * ties keep the EARLIER checkpoint (documented, never silent).
    Writes a provenance sidecar on every save. Never reads a pre-existing best as a candidate."""
    RULE = ('best=-inf; first eval always saved; overwrite iff proxy STRICTLY > best; '
            'ties keep EARLIER checkpoint (earlier step wins)')

    def __init__(self, best_path, run_ctx, run_started_epoch):
        self.best_path = Path(best_path)
        self.run_ctx = run_ctx
        assert_no_stale_target(self.best_path, run_started_epoch)   # fail-fast on un-migrated stale best
        self.best = -math.inf
        self.best_step = None
        self.n_evals = 0

    def consider(self, model, proxy, step, metrics):
        improved = (self.n_evals == 0) or (proxy > self.best)      # first eval always; ties do NOT overwrite
        self.n_evals += 1
        if improved:
            self.best = float(proxy); self.best_step = int(step)
            model.save(str(self.best_path))
            write_sidecar(self.best_path, self.run_ctx, kind='best', checkpoint_step=step,
                          metrics=metrics, selection_rule=self.RULE)
        return improved

    def save_final(self, model, final_path, step, metrics):
        model.save(str(final_path))
        write_sidecar(final_path, self.run_ctx, kind='final', checkpoint_step=step, metrics=metrics,
                      selection_rule=self.RULE)


def smoke(env_cls, steps=5, seed=0):
    """1-5 step smoke roll-out proving the env is constructible + steppable. Returns the metadata.
    Does NOT train a policy (random actions). For the verification battery."""
    contract, obs_dim, act_dim = env_contract(env_cls)
    probe = dict(scenario_id=0, family_id=0, category='LVRT', fault_type='1ph_g', target_V_pu=0.5,
                 grid='weak', scr=3.0, t_fault=0.02, fault_dur=0.6, T_sim=2.5, random_seed=seed)
    e = env_cls([probe]); o, _ = e.reset(seed=seed)
    assert o.shape == e.observation_space.shape, (o.shape, e.observation_space.shape)
    rng = np.random.default_rng(seed)
    for _ in range(steps):
        a = rng.uniform(e.action_space.low, e.action_space.high).astype(np.float32)
        o, r, term, trunc, info = e.step(a)
        assert np.all(np.isfinite(o)) and np.isfinite(r)
        if term or trunc:
            o, _ = e.reset()
    return dict(env_class=env_cls.__name__, env_contract=contract,
                observation_dim=obs_dim, action_dim=act_dim, steps=steps)
