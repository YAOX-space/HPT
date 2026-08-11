"""run_sweep_parallel.py — run the 22 INDEPENDENT P3 trainings CONCURRENTLY.

The ODE training env is CPU-bound (the 256^3 net barely uses the GPU); the trainings are independent,
so running several at once fills the otherwise-idle cores. Each job is a `train_single` subprocess;
all share one HPT_RUN_ID, each writes its own log + provenance sidecar. Results are IDENTICAL to the
sequential sweep (same seeds, same FROZEN split) — only the wall-clock shrinks (~8h -> ~1.5h on 20
cores at 6 workers). MKL_THREADING_LAYER=SEQUENTIAL keeps each process single-threaded so workers do
not oversubscribe the BLAS pool.

    python -m hpt_frt.device.run_sweep_parallel               # 6 workers (default), 5 seeds, 300k
    python -m hpt_frt.device.run_sweep_parallel --workers 8 --steps 300000
"""
import argparse, json, os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from ..train_common import new_run_id, PRODUCTION_SEEDS

ROOT = Path(__file__).resolve().parents[4]   # repo root (src/hpt_frt/device/legacy/.. -> repo)
EXPERTS = ['sym', 'asym', 'hvrt_sym', 'hvrt_asym']


def build_jobs(seeds, steps):
    js = [('expert', nm, 42) for nm in EXPERTS]                       # seed-42 experts (deploy set)
    for s in [x for x in seeds if x != 42]:                          # seed-robustness experts
        js += [('seed_expert', nm, s) for nm in EXPERTS]
    js += [('ablation', '', 42), ('residual', '', 42)]               # single-SAC + residual
    return [(k, n, s, steps) for k, n, s in js]


def _final_model(job):
    """The *_final.zip a job produces (used to detect already-done jobs on resume)."""
    kind, name, seed, _ = job
    base = {'expert': f'sac_{name}', 'seed_expert': f'sd_{seed}_{name}',
            'ablation': 'ablation_single', 'residual': 'sac_residual'}[kind]
    return ROOT / 'data' / 'models' / f'{base}_final.zip'


def _already_done(job, run_id):
    """True if this job's final model exists WITH a sidecar from the SAME run_id (resume-safe)."""
    fp = _final_model(job); side = fp.with_suffix('.json')
    if not (fp.exists() and side.exists()):
        return False
    try:
        return json.loads(side.read_text()).get('run_id') == run_id
    except Exception:
        return False


def _migrate_stale_partials(job, before_epoch):
    """Before (re)running a not-done job, move any of its existing best/final checkpoints OLDER than
    the run start into legacy_pre_resweep so the CheckpointSelector fail-fast does not trip (a stale
    partial best from an interrupted earlier run). Preserves them; never deletes."""
    base = _final_model(job).name[:-len('_final.zip')]
    dst = ROOT / 'data' / 'models' / 'legacy_pre_resweep' / 'auto_migrated'
    moved = []
    for suf in ('_best.zip', '_best.json', '_final.zip', '_final.json'):
        p = ROOT / 'data' / 'models' / f'{base}{suf}'
        if p.exists() and p.stat().st_mtime < before_epoch:
            dst.mkdir(parents=True, exist_ok=True)
            p.rename(dst / p.name); moved.append(p.name)
    return moved


def run_job(job, run_id, logdir, use_gpu=False):
    kind, name, seed, steps = job
    tag = f'{kind}_{name or "single"}_sd{seed}'
    log = logdir / f'{tag}.log'
    env = {**os.environ, 'HPT_RUN_ID': run_id, 'HPT_RUN_LOG': str(log),
           'KMP_DUPLICATE_LIB_OK': 'TRUE', 'MKL_THREADING_LAYER': 'SEQUENTIAL', 'PYTHONUNBUFFERED': '1'}
    if not use_gpu:
        # CPU mode: hide the GPU ('-1' not '' — empty does NOT disable). Reliable but slower per model.
        env['CUDA_VISIBLE_DEVICES'] = '-1'; env['HPT_FORCE_CPU'] = '1'
    # GPU mode: keep CUDA visible. The orchestrator uses FEW workers + a big stagger so simultaneous
    # CUDA inits (which crash the laptop GPU at 6) never overlap. GPU makes the gradient ~free -> ~5x
    # faster per model than single-threaded CPU.
    cmd = [sys.executable, '-m', 'hpt_frt.device.train_single', '--kind', kind,
           '--seed', str(seed), '--steps', str(steps)] + (['--name', name] if name else [])
    t0 = time.time()
    with open(log, 'w') as f:
        rc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env=env, cwd=str(ROOT)).returncode
    return tag, rc, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=max(2, (os.cpu_count() or 4) // 3))
    ap.add_argument('--steps', type=int, default=300_000)
    ap.add_argument('--seeds', type=int, nargs='+', default=PRODUCTION_SEEDS)
    ap.add_argument('--gpu', action='store_true', help='train on GPU (few workers + big stagger)')
    ap.add_argument('--stagger', type=float, default=None, help='seconds between job launches')
    ap.add_argument('--resume', action='store_true', help='skip jobs already done in HPT_RUN_ID')
    a = ap.parse_args()
    stagger = a.stagger if a.stagger is not None else (10.0 if a.gpu else 2.0)
    run_id = os.environ.get('HPT_RUN_ID') or new_run_id('p3par')
    logdir = ROOT / 'lab' / 'results' / f'{run_id}_jobs'; logdir.mkdir(parents=True, exist_ok=True)
    (ROOT / 'lab' / 'results' / '.p3_current_runid').write_text(run_id)
    (ROOT / 'lab' / 'results' / '.p3_current_log').write_text(str(logdir))
    jobs = build_jobs(a.seeds, a.steps)
    if a.resume:                                         # skip jobs already done in THIS run_id
        all_n = len(jobs)
        jobs = [j for j in jobs if not _already_done(j, run_id)]
        jobs.sort(key=lambda j: 0 if j[0] in ('ablation', 'residual') else 1)   # deploy-critical first
        before = time.time()
        for j in jobs:                                   # clear stale partials so retries don't fail-fast
            mv = _migrate_stale_partials(j, before)
            if mv:
                print(f'  migrated stale partial(s) for {j[0]}-{j[1]}-{j[2]}: {mv}', flush=True)
        print(f'RESUME run={run_id}: {all_n - len(jobs)} jobs already done, {len(jobs)} remaining', flush=True)
    print(f'P3 PARALLEL run={run_id} | {len(jobs)} jobs | {a.workers} workers | '
          f'{"GPU" if a.gpu else "CPU"} | stagger={stagger}s | seeds={sorted(a.seeds)} | steps={a.steps} '
          f'| logs={logdir}', flush=True)
    t0, results = time.time(), []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {}
        for j in jobs:                                   # stagger submissions so CUDA inits never overlap
            futs[ex.submit(run_job, j, run_id, logdir, a.gpu)] = j; time.sleep(stagger)
        for fut in as_completed(futs):
            tag, rc, dt = fut.result(); results.append((tag, rc, dt))
            print(f'  [{len(results):2d}/{len(jobs)}] {tag:32s} rc={rc} {dt/60:4.0f}min', flush=True)
    nfail = sum(1 for _, rc, _ in results if rc != 0)
    print(f'\nPARALLEL SWEEP DONE run={run_id}: {len(results)-nfail}/{len(results)} ok, {nfail} failed, '
          f'wall={ (time.time()-t0)/60:.0f}min', flush=True)
    for tag, rc, _ in results:
        if rc != 0:
            print(f'  FAILED: {tag} (see {logdir / (tag + ".log")})', flush=True)
    sys.exit(1 if nfail else 0)


if __name__ == '__main__':
    main()
