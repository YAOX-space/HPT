"""train_reward_logging.py — SMALL ODE reward-logging retrain for TRAINING DIAGNOSTICS ONLY.

Purpose: the P3 run did not persist a reward time-series, so this re-runs a small ODE training with
SB3 Monitor + CSV + TensorBoard logging to capture reward / ep_rew_mean / actor-critic loss / entropy /
alpha, plus the ODE success proxy and constraint violation. It is NOT a new frt-v2 full-320 experiment,
does NOT run Simulink, does NOT touch any certified result or model, and its numbers are diagnostics —
NOT a performance conclusion. The certified switching full-320 result is unchanged (residual SAC mi=14
strict 53.1% / no-fail 89.4% / fail 10.6%).

Everything is written to a NEW dir: lab/results/reward_logging_<YYYYMMDD_HHMMSS>/ (monitor.csv,
progress.csv, tensorboard/, eval_curve.csv, config.json, train.log, final_model.zip). data/models/ is
NEVER touched.

    python -m hpt_frt.device.train_reward_logging --help
    python -m hpt_frt.device.train_reward_logging --controller residual --seed 42 --steps 100000 --eval 10000
"""
import os
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
os.environ.setdefault('MKL_THREADING_LAYER', 'SEQUENTIAL')
import sys
import json
import time
import csv
import argparse
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / 'lab' / 'results'
DIAG_BANNER = 'ODE training diagnostics only; not certified switching frt-v2 pass rate'


def main(controller='residual', seed=42, total_steps=100_000, eval_freq=10_000, n_envs=4, ts=None):
    from stable_baselines3 import SAC
    from stable_baselines3.common.vec_env import DummyVecEnv, VecMonitor
    from stable_baselines3.common.logger import configure, TensorBoardOutputFormat
    from .frt_env import load_frt_scenarios
    from .frt_metrics import evaluate_frt
    from .train_common import select_env, env_seeds, pick_device, split_scenarios, FROZEN_SPLIT_SEED

    ts = ts or datetime.now().strftime('%Y%m%d_%H%M%S')
    rundir = RESULTS / f'reward_logging_{ts}'
    (rundir / 'tensorboard').mkdir(parents=True, exist_ok=True)
    env_cls = select_env(controller)            # 'residual' -> HPTFRTResidualEnvV2 (20-D obs / 3-D action)

    scen = load_frt_scenarios(ROOT / 'lab' / 'frt_scenarios.csv')
    train_scn, val_scn = split_scenarios(scen, val_frac=0.2, seed=FROZEN_SPLIT_SEED)
    vec = DummyVecEnv([(lambda s=s: env_cls(train_scn, seed=s)) for s in env_seeds(seed, n_envs)])
    vec = VecMonitor(vec, filename=str(rundir / 'monitor.csv'))   # episode reward -> monitor.csv + logger

    lr = lambda p: 3e-5 + (3e-4 - 3e-5) * p
    sac = SAC('MlpPolicy', vec, learning_rate=lr, buffer_size=100_000, batch_size=512, tau=0.005,
              gamma=0.99, train_freq=1, gradient_steps=2, ent_coef='auto',
              policy_kwargs=dict(net_arch=[256, 256, 256]), device=pick_device(), verbose=0, seed=seed)
    # SB3 logger: progress.csv + stdout in rundir, TensorBoard events in rundir/tensorboard/ (optional)
    logger = configure(str(rundir), ['stdout', 'csv'])
    tb_ok = False
    try:
        logger.output_formats.append(TensorBoardOutputFormat(str(rundir / 'tensorboard')))
        tb_ok = True
    except (AssertionError, ImportError) as e:
        (rundir / 'tensorboard' / 'NOT_AVAILABLE.txt').write_text(
            f'TensorBoard output skipped: {e}\nInstall with: pip install tensorboard, then re-run.\n'
            'monitor.csv + progress.csv still contain reward / ep_rew_mean / losses.\n', encoding='utf-8')
    sac.set_logger(logger)

    config = dict(purpose='small ODE reward-logging retrain — TRAINING DIAGNOSTICS ONLY',
                  banner=DIAG_BANNER, not_a_full320=True, certified_unchanged=True,
                  certified_full320=dict(residual_SAC_mi14=dict(strict=53.1, no_fail=89.4, fail=10.6)),
                  controller=controller, env_class=env_cls.__name__,
                  observation_dim=int(vec.observation_space.shape[0]),
                  action_dim=int(vec.action_space.shape[0]), seed=seed, total_steps=total_steps,
                  eval_freq=eval_freq, n_envs=n_envs, device=pick_device(),
                  split_seed=FROZEN_SPLIT_SEED, n_train=len(train_scn), n_val=len(val_scn),
                  started_at=ts)
    (rundir / 'config.json').write_text(json.dumps(config, indent=2), encoding='utf-8')

    tlog = (rundir / 'train.log').open('w', encoding='utf-8')
    def emit(s):
        print(s, flush=True); tlog.write(s + '\n'); tlog.flush()
    emit(f'=== reward-logging retrain: {controller} seed={seed} steps={total_steps} eval={eval_freq} '
         f'n_envs={n_envs} -> {rundir.name} ===')
    emit(f'[{DIAG_BANNER}]')

    eval_rows, step, t0 = [], 0, time.time()
    while step < total_steps:
        chunk = min(eval_freq, total_steps - step)
        sac.learn(total_timesteps=chunk, reset_num_timesteps=False)
        step += chunk
        m = evaluate_frt(sac, val_scn, env_cls, n_eval=min(80, len(val_scn)))
        con, rea, rec = m.get('connect'), m.get('reactive'), m.get('recover')
        viol = lambda v: None if v is None else round(100.0 - v, 1)
        row = dict(step=step, success_proxy_pct=m['partial_proxy_pct'],
                   connect_pass_pct=con, reactive_pass_pct=rea, recover_pass_pct=rec,
                   connect_violation_pct=viol(con), reactive_violation_pct=viol(rea),
                   recover_violation_pct=viol(rec), limit_status='NOT_EVALUATED',
                   survive_status='NOT_EVALUATED', n_fail=m['n_decided_fail'],
                   n_incomplete=m['n_incomplete'])
        eval_rows.append(row)
        # mirror eval metrics into the SB3 logger (progress.csv + tensorboard)
        sac.logger.record('eval/success_proxy', m['partial_proxy_pct'])
        for k, v in (('connect', con), ('reactive', rea), ('recover', rec)):
            if v is not None:
                sac.logger.record(f'eval/{k}_violation', 100.0 - v)
        sac.logger.record('eval/n_fail', m['n_decided_fail'])
        sac.logger.dump(step)
        emit(f'  step={step:7,} success_proxy={m["partial_proxy_pct"]:.0f}% '
             f'con={con} rea={rea} rec={rec} n_fail={m["n_decided_fail"]} '
             f'incmpl={m["n_incomplete"]} {(time.time()-t0)/60:.0f}min')

    sac.save(str(rundir / 'final_model.zip'))     # NEW dir only — never data/models
    with (rundir / 'eval_curve.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(eval_rows[0].keys()) + ['metric_note'])
        w.writeheader()
        for r in eval_rows:
            w.writerow({**r, 'metric_note': DIAG_BANNER})
    emit(f'DONE -> {rundir}')
    tlog.close()
    print(f'RUNDIR={rundir}')
    return rundir


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Small ODE reward-logging retrain (diagnostics only; no Simulink/full-320).')
    ap.add_argument('--controller', default='residual', choices=['residual', 'frt'],
                    help="which controller env to train (default residual = HPTFRTResidualEnvV2)")
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--steps', type=int, default=100_000, help='total training steps')
    ap.add_argument('--eval', type=int, default=10_000, help='ODE eval interval (steps)')
    ap.add_argument('--n_envs', type=int, default=4)
    ap.add_argument('--ts', default=None, help='override the run-dir timestamp tag')
    a = ap.parse_args()
    main(controller=a.controller, seed=a.seed, total_steps=a.steps, eval_freq=a.eval,
         n_envs=a.n_envs, ts=a.ts)
