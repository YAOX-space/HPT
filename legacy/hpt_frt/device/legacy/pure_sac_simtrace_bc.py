"""Behavior-cloning repair from Simulink HLC observation traces.

The output is still a normal SAC checkpoint. Simulink traces are used only as
training samples so the actor learns actions for observations that the ODE
surrogate does not reproduce exactly.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("MKL_THREADING_LAYER", "SEQUENTIAL")

import numpy as np
import torch
from scipy.io import loadmat

from ..frt_env import I_Q_ACT, V_SE_MAX, load_frt_scenarios
from ..frt_env_v2 import HPTFRTEnvV2
from ..frt_metrics import evaluate_frt
from ..model_io import load_sac
from ..train_common import FROZEN_SPLIT_SEED, pick_device, sha256_file, split_scenarios


ROOT = Path(__file__).resolve().parents[4]
LAB = ROOT / "lab"
RESULTS = LAB / "results"
EXPANDED = LAB / "frt_scenarios_expanded.csv"
FULL320 = LAB / "frt_scenarios.csv"
HARD24 = RESULTS / "hard24_sym3ph_vdc.csv"


def scale_action(model, action):
    lo = np.array([-I_Q_ACT, -V_SE_MAX, -V_SE_MAX], np.float32)
    hi = np.array([I_Q_ACT, V_SE_MAX, V_SE_MAX], np.float32)
    return model.policy.scale_action(np.clip(np.asarray(action, np.float32), lo, hi)).astype(np.float32)


def scenarios_for(expert: str, path: Path):
    if expert == "sym":
        return [
            s for s in load_frt_scenarios(path)
            if s["category"] == "LVRT" and s["fault_type"] == "sym3ph"
        ]
    if expert == "asym":
        return [
            s for s in load_frt_scenarios(path)
            if s["category"] == "LVRT" and s["fault_type"] in ("1ph_g", "2ph", "2ph_g")
        ]
    if expert == "hvrt_sym":
        return [
            s for s in load_frt_scenarios(path)
            if s["category"] == "HVRT" and s["fault_type"] == "swell_3ph"
        ]
    if expert == "hvrt_asym":
        return [
            s for s in load_frt_scenarios(path)
            if s["category"] == "HVRT" and s["fault_type"] == "swell_1ph"
        ]
    raise ValueError(expert)


def _scenario_map():
    return {int(s["scenario_id"]): s for s in load_frt_scenarios(EXPANDED)}


def load_trace_samples(trace_mat: Path, model, *, expert: str, teacher_weight: float,
                       trace_sids: set[int] | None, teacher_action: np.ndarray,
                       teacher_mode: str, recover_gain: float, post_recover_stride: int,
                       recover_channel: str, teacher_actions_by_sid: dict[int, np.ndarray]):
    mat = loadmat(trace_mat, squeeze_me=True, struct_as_record=False)
    R = mat["R"]
    if not isinstance(R, np.ndarray):
        R = np.asarray([R])
    X, Y, W, tags = [], [], [], []
    scenarios = _scenario_map()
    fixed_teacher = scale_action(model, teacher_action)
    for rec in R:
        sid = int(rec.sid)
        if trace_sids and sid not in trace_sids:
            continue
        fixed_teacher_sid = (
            scale_action(model, teacher_actions_by_sid[sid])
            if sid in teacher_actions_by_sid else fixed_teacher
        )
        obs = np.asarray(rec.trace.obs, np.float32)
        act = np.asarray(rec.trace.actor_action, np.float32)
        t_obs = np.asarray(rec.trace.t_obs, np.float32)
        if obs.ndim != 2 or obs.shape[1] != 20:
            continue
        changed = np.r_[True, np.linalg.norm(np.diff(act, axis=0), axis=1) > 1e-7]
        v2p = obs[:, 1]
        v2n = obs[:, 2]
        infault = obs[:, 16]
        valid_obs = np.any(np.abs(obs) > 1e-8, axis=1)
        if teacher_mode in ("post_recover", "post_fixed"):
            s = scenarios[sid]
            clear_t = 0.08 + min(float(s["fault_dur"]), 0.5)
            route_mask = v2n > 0.05 if expert in ("asym", "hvrt_asym") else v2n < 0.05
            domain_mask = (t_obs >= clear_t) & (t_obs <= clear_t + 0.35) & (np.abs(v2p - 1.0) > 0.025)
            mask = valid_obs & domain_mask & route_mask
            idx = np.flatnonzero(mask)
            if post_recover_stride > 1:
                idx = idx[::post_recover_stride]
            for i in idx:
                if teacher_mode == "post_fixed":
                    teacher = fixed_teacher_sid
                else:
                    err = recover_gain * (1.0 - float(v2p[i]))
                    if recover_channel == "iq":
                        teacher = scale_action(model, [float(np.clip(err, -I_Q_ACT, I_Q_ACT)), 0.0, 0.0])
                    elif recover_channel == "mq":
                        teacher = scale_action(model, [0.0, 0.0, float(np.clip(err, -V_SE_MAX, V_SE_MAX))])
                    else:
                        teacher = scale_action(model, [0.0, float(np.clip(err, -V_SE_MAX, V_SE_MAX)), 0.0])
                X.append(obs[i].copy())
                Y.append(teacher.copy())
                W.append(teacher_weight)
                tags.append(f"simtrace_{teacher_mode}_sid{sid}")
            continue
        if expert == "asym":
            route_mask = v2n > 0.05
            domain_mask = v2p < 0.90
        elif expert == "sym":
            route_mask = v2n < 0.05
            domain_mask = v2p < 0.90
        elif expert == "hvrt_asym":
            route_mask = v2n > 0.05
            domain_mask = v2p > 1.08
        else:
            route_mask = v2n < 0.05
            domain_mask = v2p > 1.08
        mask = valid_obs & changed & (infault > 0.5) & domain_mask & route_mask
        idx = np.flatnonzero(mask)
        for i in idx:
            X.append(obs[i].copy())
            Y.append(fixed_teacher_sid.copy())
            W.append(teacher_weight)
            tags.append(f"simtrace_teacher_sid{sid}")
    return X, Y, W, tags


def collect_preserve_samples(model, scenarios, *, preserve_n: int, stride: int, weight: float):
    X, Y, W, tags = [], [], [], []
    rng = np.random.default_rng(20260710)
    pick = rng.choice(len(scenarios), size=min(preserve_n, len(scenarios)), replace=False)
    for j in pick:
        env = HPTFRTEnvV2([scenarios[int(j)]], seed=42, train_mode=False)
        obs, _ = env.reset()
        done = False
        k = 0
        while not done:
            cur, _ = model.predict(obs, deterministic=True)
            if k % stride == 0:
                X.append(obs.copy())
                Y.append(scale_action(model, cur))
                W.append(weight)
                tags.append("preserve")
            obs, _, term, trunc, _info = env.step(cur)
            done = term or trunc
            k += 1
    return X, Y, W, tags


def train_actor_bc(base_path: Path, out_path: Path, X, Y, W, *, lr: float, epochs: int, device: str):
    model = load_sac(base_path, device=device)
    actor = model.policy.actor
    actor.train()
    opt = torch.optim.Adam(actor.parameters(), lr=lr)
    Xt = torch.as_tensor(np.asarray(X, np.float32), device=model.device)
    Yt = torch.as_tensor(np.asarray(Y, np.float32), device=model.device)
    Wt = torch.as_tensor(np.asarray(W, np.float32)[:, None], device=model.device)
    bs = 512
    hist = []
    for epoch in range(epochs):
        perm = torch.randperm(len(X), device=model.device)
        total = 0.0
        for st in range(0, len(X), bs):
            idx = perm[st:st + bs]
            pred = actor(Xt[idx], deterministic=True)
            loss = ((pred - Yt[idx]) ** 2 * Wt[idx]).mean()
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(actor.parameters(), 1.0)
            opt.step()
            total += float(loss.detach().cpu())
        hist.append(total)
        if epoch in {0, 1, 2, 4, 9, epochs - 1}:
            print(f"epoch={epoch} loss={total:.6f}", flush=True)
    model.save(str(out_path))
    return model, hist


def summarize(model, scenarios):
    m = evaluate_frt(model, scenarios, HPTFRTEnvV2, n_eval=None)
    return {
        "n": len(scenarios),
        "partial_proxy_pct": m["partial_proxy_pct"],
        "connect": m["connect"],
        "reactive": m["reactive"],
        "recover": m["recover"],
        "vdc_survive_proxy_pct": m["vdc_survive_proxy_pct"],
        "n_decided_fail": m["n_decided_fail"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expert", choices=["sym", "asym", "hvrt_sym", "hvrt_asym"], default="sym")
    ap.add_argument("--base", type=Path, required=True)
    ap.add_argument("--trace", type=Path, required=True)
    ap.add_argument("--lr", type=float, default=3e-6)
    ap.add_argument("--epochs", type=int, default=24)
    ap.add_argument("--teacher-weight", type=float, default=160.0)
    ap.add_argument("--preserve-n", type=int, default=900)
    ap.add_argument("--preserve-weight", type=float, default=8.0)
    ap.add_argument("--trace-sids", default="",
                    help="Comma-separated scenario ids from the trace MAT to use as teacher samples.")
    ap.add_argument("--teacher-action", default="0.27,0,0",
                    help="Teacher action in actor convention: iq,mse_d,mse_q.")
    ap.add_argument("--teacher-actions-by-sid", default="",
                    help="Optional semicolon list sid:iq,md,mq;... overriding --teacher-action.")
    ap.add_argument("--teacher-mode", choices=["fixed", "post_recover", "post_fixed"], default="fixed")
    ap.add_argument("--recover-gain", type=float, default=1.2)
    ap.add_argument("--post-recover-stride", type=int, default=1,
                    help="Subsample stride for post_recover trace states after masking.")
    ap.add_argument("--recover-channel", choices=["iq", "md", "mq"], default="md",
                    help="Actor action channel used by post_recover teacher.")
    args = ap.parse_args()

    run_dir = RESULTS / time.strftime("pure_sac_simtrace_bc_%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    device = pick_device()
    base = load_sac(args.base, device=device)
    expanded = scenarios_for(args.expert, EXPANDED)
    full = scenarios_for(args.expert, FULL320)
    hard24 = load_frt_scenarios(HARD24) if HARD24.exists() else []
    train_scn, val_scn = split_scenarios(expanded, val_frac=0.2, seed=FROZEN_SPLIT_SEED)

    X, Y, W, tags = [], [], [], []
    trace_sids = {int(x) for x in args.trace_sids.split(",") if x.strip()} or None
    teacher_action = np.asarray([float(x) for x in args.teacher_action.split(",")], np.float32)
    if teacher_action.shape != (3,):
        raise SystemExit("--teacher-action must contain exactly three comma-separated numbers")
    teacher_actions_by_sid = {}
    if args.teacher_actions_by_sid.strip():
        for item in args.teacher_actions_by_sid.split(";"):
            item = item.strip()
            if not item:
                continue
            sid_txt, act_txt = item.split(":", 1)
            arr = np.asarray([float(x) for x in act_txt.split(",")], np.float32)
            if arr.shape != (3,):
                raise SystemExit("--teacher-actions-by-sid actions must contain exactly three numbers")
            teacher_actions_by_sid[int(sid_txt)] = arr
    for part in (
        collect_preserve_samples(base, train_scn, preserve_n=args.preserve_n, stride=2,
                                 weight=args.preserve_weight),
        load_trace_samples(args.trace, base, expert=args.expert,
                           teacher_weight=args.teacher_weight, trace_sids=trace_sids,
                           teacher_action=teacher_action, teacher_mode=args.teacher_mode,
                           recover_gain=args.recover_gain,
                           post_recover_stride=max(1, args.post_recover_stride),
                           recover_channel=args.recover_channel,
                           teacher_actions_by_sid=teacher_actions_by_sid),
    ):
        X.extend(part[0]); Y.extend(part[1]); W.extend(part[2]); tags.extend(part[3])

    out_model = run_dir / f"sac_{args.expert}_best.zip"
    model, hist = train_actor_bc(args.base, out_model, X, Y, W, lr=args.lr, epochs=args.epochs,
                                 device=device)
    result = {
        "model": str(out_model),
        "model_sha256": sha256_file(out_model),
        "base": str(args.base),
        "trace": str(args.trace),
        "dataset": {"n": len(X), "tags": dict(Counter(tags))},
        "train_loss": hist,
        "expert": args.expert,
        "val_expert": summarize(model, val_scn),
        "full320_expert": summarize(model, full),
        "hard24_proxy": summarize(model, hard24),
    }
    (run_dir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
