"""Pure-SAC hard-case curriculum for the canonical Mode-5 controller (mi==12).

CURRENT MAINLINE (2026-07-11): use this runner for pure-SAC training,
pass-set experiments, and Simulink export. Older training entrypoints are kept
under ``hpt_frt.device.legacy`` for audit/reproduction only.

This runner intentionally does NOT use the residual/MPC controller and does NOT add deployment-time
rules. It trains the four pure SAC experts on the frt-v2 ODE environment, with hard-case
oversampling and reward shaping only inside the training environment. The exported Simulink
controller remains the normal online-gated four-actor SAC path.

Typical overnight run:

    python -m hpt_frt.device.pure_sac_hard_curriculum --steps 120000 --n-envs 4 --promote --export
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import time
from collections import Counter
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("MKL_THREADING_LAYER", "SEQUENTIAL")

import numpy as np
from stable_baselines3 import SAC
from stable_baselines3.common.vec_env import DummyVecEnv

from hpt_frt.common import frt_v2 as FV2
from .export_sac_actor import export_actor
from .frt_env import effective_fault_dur, load_frt_scenarios
from .frt_env_v2 import HPTFRTEnvV2
from .frt_metrics import CRITERIA, evaluate_frt, evaluate_scenario
from .model_io import load_sac
from .train_common import (
    CheckpointSelector,
    FROZEN_SPLIT_SEED,
    env_seeds,
    make_run_context,
    new_run_id,
    pick_device,
    split_scenarios,
)


ROOT = Path(__file__).resolve().parents[3]
LAB = ROOT / "lab"
RESULTS = LAB / "results"
MODELS = ROOT / "data" / "models"
EXPANDED = LAB / "frt_scenarios_expanded.csv"
FULL320 = LAB / "frt_scenarios.csv"
HARD_ANALYSIS = RESULTS / "p3_expanded_baseline_only_error_analysis.csv"
HARD24 = RESULTS / "hard24_sym3ph_vdc.csv"
TRADITIONAL_ONLY = RESULTS / "traditional_only_72_shallow_hvrt_20260711.csv"
BOTH_FAIL_HVRT_RECOVER = RESULTS / "both_fail_hvrt_recover_215_gate1075_20260711.csv"

EXPERTS = {
    "sym": lambda s: s["category"] == "LVRT" and s["fault_type"] == "sym3ph",
    "asym": lambda s: s["category"] == "LVRT" and s["fault_type"] in ("1ph_g", "2ph", "2ph_g"),
    "hvrt_sym": lambda s: s["category"] == "HVRT" and s["fault_type"] == "swell_3ph",
    "hvrt_asym": lambda s: s["category"] == "HVRT" and s["fault_type"] == "swell_1ph",
}

SWITCHING_FAIL_IDS = {
    225, 226, 227, 228,
    233, 234, 235, 236, 237, 238, 239, 240,
    1441, 1456, 1481, 1500, 1873, 1875,
}

SHALLOW_HVRT_TARGETS = {
    ("swell_3ph", 1.1),
    ("swell_1ph", 1.2),
    ("swell_1ph", 1.3),
}
HVRT_ROUTE_ON_VP = 1.060
SIMFAIL_REPAIR_SCALE = float(os.environ.get("HPT_SIMFAIL_REWARD_SCALE", "0.0"))


class PureSACHardEnv(HPTFRTEnvV2):
    """Training-only reward shaping for hard visible failures.

    The action applied to the plant is still the raw SAC action from HPTFRTEnvV2. These terms only
    change the learning signal so the actor sees the Vdc/recover and wrong-sign reactive failures
    that the aligned ODE now exposes.
    """

    def step(self, action):
        obs, reward, done, trunc, info = super().step(action)
        s = self._sc
        t_sample = max(0.0, float(info["t"]) - 0.002)
        clear_t = float(s["t_fault"]) + effective_fault_dur(s) * 0.20
        in_fault = float(s["t_fault"]) <= t_sample <= clear_t
        post_clear = clear_t < t_sample <= clear_t + (0.45 if s["category"] == "HVRT" else 0.08)
        v2p = float(info["V2p"])
        vdc = float(info["Vdc"])
        iq = float(info["iq"])
        iq_cmd = float(info.get("iq_cmd", iq))
        mse_d = float(info["mse_d"])
        mse_q = float(info["mse_q"])
        labels = label_set(s)

        if in_fault and s["category"] == "LVRT":
            floor = self._lvrt_floor(t_sample - float(s["t_fault"]))
            connect_short = max(0.0, floor + 0.006 - v2p)
            reward += -260.0 * connect_short
            min_support = max(0.0, FV2.iq_ref_droop(v2p) - FV2.REACTIVE_TOL + 0.006)
            reward += -90.0 * max(0.0, min_support - iq)
            reward += -90.0 * max(0.0, -iq - FV2.REACTIVE_SIGN_EPS)
            if labels:
                if "reactive" in labels:
                    reward += -360.0 * max(0.0, min_support + 0.012 - iq)
                    reward += -300.0 * max(0.0, -iq - FV2.REACTIVE_SIGN_EPS)
                    reward += -120.0 * max(0.0, -iq_cmd - FV2.REACTIVE_SIGN_EPS)
                if "recover" in labels:
                    reward += -130.0 * max(0.0, 0.92 - v2p) * (1.0 + float(post_clear))
                    reward += -55.0 * max(0.0, -mse_d)
                if "survive" in labels:
                    reward += -420.0 * max(0.0, 0.80 - vdc)
                    reward += -140.0 * max(0.0, mse_d) * (1.0 + 6.0 * max(0.0, 0.80 - vdc))
                    reward += -18.0 * abs(mse_q)
            if SIMFAIL_REPAIR_SCALE > 0.0 and s["fault_type"] == "sym3ph" and v2p < 0.25:
                # Simulink spotcheck S1/S4 failure mode: deep 3ph LVRT can keep the voltage envelope
                # while holding measured iq on the wrong side and collapsing Vdc. Make both visible.
                reward += SIMFAIL_REPAIR_SCALE * (
                    -620.0 * max(0.0, -iq - FV2.REACTIVE_SIGN_EPS)
                    -220.0 * max(0.0, min_support + 0.018 - iq)
                    -520.0 * max(0.0, 0.82 - vdc)
                    -260.0 * max(0.0, mse_d) * (1.0 + 8.0 * max(0.0, 0.82 - vdc))
                    -35.0 * abs(mse_q)
                )
            if s["fault_type"] == "sym3ph" and float(s["scr"]) >= 8.0 and float(s["target_V_pu"]) <= 0.55:
                if connect_short <= 0.002:
                    reward += -130.0 * max(0.0, 0.765 - vdc)
                else:
                    reward += -18.0 * max(0.0, 0.765 - vdc)
                    reward += -70.0 * max(0.0, -mse_d) * min(0.08, connect_short)
                reward += -80.0 * max(0.0, float(s["target_V_pu"]) + 0.004 - v2p)
                reward += -10.0 * abs(mse_q)

        if in_fault and s["category"] == "HVRT":
            wrong_absorb = max(0.0, iq - FV2.REACTIVE_SIGN_EPS)
            over_margin = max(0.0, v2p - 1.095)
            reward += -150.0 * wrong_absorb * (1.0 + 20.0 * over_margin)
            ref = FV2.iq_ref_droop(v2p)
            target_key = (s["fault_type"], round(float(s["target_V_pu"]), 3))
            if target_key in SHALLOW_HVRT_TARGETS and abs(ref) > 0.02:
                max_allowed_iq = ref + FV2.REACTIVE_TOL - 0.015
                under_absorb = max(0.0, iq - max_allowed_iq)
                reward += -240.0 * under_absorb * (1.0 + 8.0 * max(0.0, v2p - 1.10))
                reward += -18.0 * max(0.0, -0.30 - iq)
            if target_key in SHALLOW_HVRT_TARGETS and t_sample >= float(s["t_fault"]) + FV2.REACTIVE_DELAY:
                meas_wrong = max(0.0, iq - FV2.REACTIVE_SIGN_EPS)
                cmd_wrong = max(0.0, iq_cmd - FV2.REACTIVE_SIGN_EPS)
                reward += -850.0 * meas_wrong * (1.0 + 10.0 * max(0.0, v2p - 1.10))
                reward += -420.0 * cmd_wrong
            reward += -100.0 * max(0.0, 0.765 - vdc)
            if s["fault_type"] == "swell_3ph":
                reward += -10.0 * max(0.0, mse_d)
            else:
                reward += -8.0 * abs(mse_q)
            if labels:
                if "reactive" in labels:
                    ref_margin = FV2.iq_ref_droop(v2p) + FV2.REACTIVE_TOL - 0.018
                    reward += -430.0 * max(0.0, iq - ref_margin)
                    reward += -360.0 * max(0.0, iq_cmd - ref_margin)
                    reward += -220.0 * wrong_absorb
                if "survive" in labels:
                    reward += -520.0 * max(0.0, 0.80 - vdc)
                    reward += -180.0 * max(0.0, mse_d)
                    reward += -45.0 * abs(mse_q)

        if post_clear:
            reward += -100.0 * max(0.0, 0.765 - vdc)
            reward += -65.0 * max(0.0, v2p - 1.10)
            reward += -65.0 * max(0.0, 0.90 - v2p)
            if labels:
                recover_excess_all = max(0.0, abs(1.0 - v2p) - (FV2.RECOVER_BAND - 0.006))
                if "recover" in labels:
                    reward += -650.0 * recover_excess_all
                    reward += -100.0 * abs(1.0 - v2p)
                    if v2p < 0.93:
                        reward += -190.0 * max(0.0, -iq - FV2.REACTIVE_SIGN_EPS)
                    if v2p > 1.07:
                        reward += -190.0 * max(0.0, iq - FV2.REACTIVE_SIGN_EPS)
                if "survive" in labels:
                    reward += -360.0 * max(0.0, 0.80 - vdc)
            if s["category"] == "HVRT":
                recover_err = 1.0 - v2p
                recover_excess = max(0.0, abs(recover_err) - (FV2.RECOVER_BAND - 0.005))
                reward += -760.0 * recover_excess
                reward += -60.0 * abs(recover_err)
                if SIMFAIL_REPAIR_SCALE > 0.0 and is_shallow_hvrt(s):
                    reward += SIMFAIL_REPAIR_SCALE * -520.0 * max(0.0, abs(recover_err) - 0.045)
                # Direction-only learning signal for the actor: support low post-clear voltage with
                # positive iq and pull high post-clear voltage down with negative iq.
                reward += -180.0 * max(0.0, -recover_err * iq)
                if v2p > 1.07:
                    reward += -120.0 * max(0.0, iq - FV2.REACTIVE_SIGN_EPS)
                    reward += -45.0 * max(0.0, -0.18 - iq)
                    reward += -35.0 * max(0.0, mse_d)
                elif v2p < 0.93:
                    reward += -120.0 * max(0.0, -iq - FV2.REACTIVE_SIGN_EPS)
                    if SIMFAIL_REPAIR_SCALE > 0.0 and is_shallow_hvrt(s):
                        reward += SIMFAIL_REPAIR_SCALE * (
                            -260.0 * max(0.0, 0.08 - iq)
                            -160.0 * max(0.0, 0.93 - v2p)
                            -90.0 * max(0.0, 0.77 - vdc)
                        )

        return obs, float(reward), done, trunc, info


class ExpertRouter:
    """Small ODE-evaluation wrapper for the four mi12 SAC experts."""

    def __init__(self, models: dict[str, SAC]):
        self.models = models

    def _name(self, obs):
        v2p = float(obs[1])
        v2n = float(obs[2])
        probs = obs[9:15]
        if v2p >= HVRT_ROUTE_ON_VP or float(probs[5]) > 0.5:
            return "hvrt_asym" if v2n > 0.05 else "hvrt_sym"
        if v2p < 0.90 or v2n > 0.05:
            return "asym" if v2n > 0.05 else "sym"
        return "sym"

    def predict(self, obs, deterministic=True):
        return self.models[self._name(obs)].predict(obs, deterministic=deterministic)


def read_hard_ids() -> set[int]:
    ids = set(SWITCHING_FAIL_IDS)
    if HARD_ANALYSIS.exists():
        with HARD_ANALYSIS.open(newline="", encoding="utf-8") as f:
            ids.update(int(r["scenario_id"]) for r in csv.DictReader(f))
    return ids


def read_scenario_ids(path: Path) -> set[int]:
    if not path or not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as f:
        return {int(r["scenario_id"]) for r in csv.DictReader(f)}


def read_repair_labels(path: Path) -> dict[int, dict]:
    if not path or not path.exists():
        return {}
    labels: dict[int, dict] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if "scenario_id" not in r:
                continue
            sid = int(r["scenario_id"])
            labels[sid] = {
                "_sim_failed_criteria": r.get("sim_failed_criteria", ""),
                "_ode_blind_failed_criteria": r.get("ode_blind_failed_criteria", ""),
                "_sim_target_group": r.get("target_group", r.get("source", "")),
                "_sim_repair_source": r.get("source", ""),
            }
    return labels


def attach_repair_labels(scenarios: list[dict], labels: dict[int, dict]) -> list[dict]:
    if not labels:
        return scenarios
    out = []
    for s in scenarios:
        sid = int(s["scenario_id"])
        if sid in labels:
            ns = dict(s)
            ns.update(labels[sid])
            out.append(ns)
        else:
            out.append(s)
    return out


def label_set(s: dict) -> set[str]:
    parts = []
    for key in ("_sim_failed_criteria", "_ode_blind_failed_criteria"):
        parts.extend(str(s.get(key, "")).split("+"))
    return {p for p in parts if p}


def is_shallow_hvrt(s: dict) -> bool:
    return s["category"] == "HVRT" and (s["fault_type"], round(float(s["target_V_pu"]), 3)) in SHALLOW_HVRT_TARGETS


def is_deep_sym_lvrt(s: dict) -> bool:
    return (
        s["category"] == "LVRT"
        and s["fault_type"] == "sym3ph"
        and float(s["target_V_pu"]) <= 0.55
    )


def weight_train_scenarios(
    train_scn,
    hard_ids: set[int],
    traditional_only_ids: set[int],
    hard_weight: int,
    switch_weight: int,
    traditional_only_weight: int,
    shallow_hvrt_weight: int,
    deep_sym_weight: int,
):
    out = list(train_scn)
    tags = Counter(base=len(out))
    for s in train_scn:
        sid = int(s["scenario_id"])
        target_weight = 1
        if is_shallow_hvrt(s):
            target_weight = max(target_weight, shallow_hvrt_weight)
        if is_deep_sym_lvrt(s):
            target_weight = max(target_weight, deep_sym_weight)
        if sid in hard_ids:
            target_weight = max(target_weight, hard_weight)
        if sid in SWITCHING_FAIL_IDS:
            target_weight = max(target_weight, switch_weight)
        if sid in traditional_only_ids:
            target_weight = max(target_weight, traditional_only_weight)
        extra = max(0, target_weight - 1)
        if extra:
            out.extend([s] * extra)
        if is_shallow_hvrt(s):
            tags["shallow_hvrt_extra"] += max(0, shallow_hvrt_weight - 1)
        if is_deep_sym_lvrt(s):
            tags["deep_sym_extra"] += max(0, deep_sym_weight - 1)
        if sid in hard_ids:
            tags["hard_extra"] += max(0, hard_weight - 1)
        if sid in SWITCHING_FAIL_IDS:
            tags["switching_extra"] += max(0, switch_weight - 1)
        if sid in traditional_only_ids:
            tags["traditional_only_extra"] += max(0, traditional_only_weight - 1)
    return out, dict(tags)


def backup_existing(run_id: str):
    backup = MODELS / f"pure_sac_backup_{run_id}"
    backup.mkdir(parents=True, exist_ok=True)
    for name in EXPERTS:
        for suffix in ("best.zip", "best.json", "final.zip", "final.json"):
            p = MODELS / f"sac_{name}_{suffix}"
            if p.exists():
                shutil.move(str(p), str(backup / p.name))
    for p in [LAB / f"sac_{name}_weights.mat" for name in EXPERTS]:
        if p.exists():
            shutil.copy2(p, backup / p.name)
    return backup


def source_checkpoint_for(name, args):
    explicit = getattr(args, f"source_{name}", None)
    if explicit:
        return Path(explicit)
    if args.source_dir:
        return Path(args.source_dir) / f"sac_{name}_best.zip"
    return MODELS / f"sac_{name}_best.zip"


def selection_score(last_m: dict, target_m: dict | None, args) -> float:
    """Checkpoint score with broad-validation protection.

    Earlier repair screens used target_proxy*10 + val_proxy, which let a shallow-HVRT target subset
    overwrite checkpoints even when broad HVRT validation collapsed. Keep the broad validation proxy as
    the primary score; add only a small target bonus once the broad proxy is above a configurable floor.
    """
    val = float(last_m.get("partial_proxy_pct") or 0.0)
    if not target_m:
        return val
    target = float(target_m.get("partial_proxy_pct") or 0.0)
    if val < float(args.min_val_proxy_for_target_bonus):
        return val
    return val + float(args.target_bonus_weight) * target


def selector_metrics(last_m: dict, target_m: dict | None, score: float) -> dict:
    metrics = {**last_m, "selection_score": score}
    if target_m:
        metrics["traditional_only_target"] = target_m
    return metrics


def train_expert(name, scenarios, hard_ids, traditional_only_ids, args, run_id, run_dir, model_dir, source_ckpt=None):
    base_scn = [s for s in scenarios if EXPERTS[name](s)]
    target_scn = [s for s in base_scn if int(s["scenario_id"]) in traditional_only_ids]
    train_scn, val_scn = split_scenarios(base_scn, val_frac=0.2, seed=FROZEN_SPLIT_SEED)
    train_scn, tags = weight_train_scenarios(
        train_scn,
        hard_ids,
        traditional_only_ids,
        args.hard_weight,
        args.switch_weight,
        args.traditional_only_weight,
        args.shallow_hvrt_weight,
        args.deep_sym_weight,
    )
    rc = make_run_context(
        run_id=run_id,
        policy_seed=args.seed,
        env_cls=PureSACHardEnv,
        scenario_split=(
            "pure-SAC hard curriculum on expanded scenarios; held-out family validation; "
            f"hard_weight={args.hard_weight}; switch_weight={args.switch_weight}; "
            f"traditional_only_weight={args.traditional_only_weight}; "
            f"shallow_hvrt_weight={args.shallow_hvrt_weight}; "
            f"deep_sym_weight={args.deep_sym_weight}; "
            f"simfail_repair_scale={SIMFAIL_REPAIR_SCALE}; "
            f"target_bonus_weight={args.target_bonus_weight}; "
            f"min_val_proxy_for_target_bonus={args.min_val_proxy_for_target_bonus}"
        ),
        train_scn=train_scn,
        val_scn=val_scn,
        n_envs=args.n_envs,
        total_steps=args.steps,
        source_log=str(run_dir / "run.log"),
    )
    vec = DummyVecEnv([
        (lambda s=s: PureSACHardEnv(train_scn, seed=s, train_mode=True))
        for s in env_seeds(args.seed, args.n_envs)
    ])
    device = pick_device()
    if args.warm_start and source_ckpt is not None and source_ckpt.exists():
        model = load_sac(source_ckpt, device=device, env=vec)
        model.learning_rate = args.lr
        model.lr_schedule = lambda _: args.lr
        for opt in (model.actor.optimizer, model.critic.optimizer, model.ent_coef_optimizer):
            if opt is not None:
                for group in opt.param_groups:
                    group["lr"] = args.lr
    else:
        model = SAC(
            "MlpPolicy",
            vec,
            learning_rate=args.lr,
            buffer_size=args.buffer_size,
            batch_size=args.batch_size,
            tau=0.005,
            gamma=0.99,
            train_freq=1,
            gradient_steps=args.gradient_steps,
            ent_coef="auto",
            policy_kwargs=dict(net_arch=[256, 256, 256]),
            device=device,
            verbose=0,
            seed=args.seed,
        )
    model_dir.mkdir(parents=True, exist_ok=True)
    sel = CheckpointSelector(model_dir / f"sac_{name}_best.zip", rc, time.time())
    last_m = evaluate_frt(model, val_scn, HPTFRTEnvV2, n_eval=None)
    target_m = evaluate_frt(model, target_scn, HPTFRTEnvV2, n_eval=None) if target_scn else None
    score = selection_score(last_m, target_m, args)
    sel.consider(model, score, 0, selector_metrics(last_m, target_m, score))
    initial_status = {
        "expert": name,
        "step": 0,
        "best_proxy": sel.best,
        "best_step": sel.best_step,
        "val": last_m,
        "traditional_only_target": target_m,
        "selection_score": score,
        "train_n_weighted": len(train_scn),
        "val_n": len(val_scn),
        "target_n": len(target_scn),
        "tags": tags,
    }
    (run_dir / f"{name}_status.json").write_text(json.dumps(initial_status, indent=2), encoding="utf-8")
    print(json.dumps({k: initial_status[k] for k in ("expert", "step", "best_proxy", "best_step", "tags")}), flush=True)
    step = 0
    while step < args.steps:
        chunk = min(args.eval_freq, args.steps - step)
        model.learn(total_timesteps=chunk, reset_num_timesteps=False)
        step += chunk
        last_m = evaluate_frt(model, val_scn, HPTFRTEnvV2, n_eval=None)
        target_m = evaluate_frt(model, target_scn, HPTFRTEnvV2, n_eval=None) if target_scn else None
        score = selection_score(last_m, target_m, args)
        sel.consider(model, score, step, selector_metrics(last_m, target_m, score))
        status = {
            "expert": name,
            "step": step,
            "best_proxy": sel.best,
            "best_step": sel.best_step,
            "val": last_m,
            "traditional_only_target": target_m,
            "selection_score": score,
            "train_n_weighted": len(train_scn),
            "val_n": len(val_scn),
            "target_n": len(target_scn),
            "tags": tags,
        }
        (run_dir / f"{name}_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
        print(json.dumps({k: status[k] for k in ("expert", "step", "best_proxy", "best_step", "tags")}), flush=True)
    sel.save_final(model, model_dir / f"sac_{name}_final.zip", step, last_m)
    return {"best_proxy": sel.best, "best_step": sel.best_step, "tags": tags}


def available_pass(res: dict) -> bool:
    if res.get("vdc_survive_proxy") != FV2.PASS:
        return False
    statuses = [res[c]["status"] for c in CRITERIA if res[c]["status"] != FV2.NOT_EVALUATED]
    return bool(statuses) and all(s == FV2.PASS for s in statuses)


def row_eval(router, scenarios, env_cls=HPTFRTEnvV2):
    rows = []
    fail_criteria = Counter()
    for s in scenarios:
        c = evaluate_scenario(router, env_cls, s)
        if c["kind"] != "evaluated":
            fails = [c["kind"]]
            vdc_min = None
        else:
            res = c["res"]
            fails = [k for k in CRITERIA if res[k]["status"] == FV2.FAIL]
            if res.get("vdc_survive_proxy") == FV2.FAIL:
                fails.append("vdc_survive_proxy")
            vdc_min = res.get("vdc_min")
        for f in fails:
            fail_criteria[f] += 1
        rows.append({
            "scenario_id": int(s["scenario_id"]),
            "category": s["category"],
            "fault_type": s["fault_type"],
            "scr": float(s["scr"]),
            "target_V_pu": float(s["target_V_pu"]),
            "passed": not fails,
            "failed_criteria": "+".join(fails),
            "vdc_min": vdc_min,
        })
    n_pass = sum(1 for r in rows if r["passed"])
    return {
        "n": len(rows),
        "pass_count": n_pass,
        "fail_count": len(rows) - n_pass,
        "pass_pct": round(100.0 * n_pass / len(rows), 3) if rows else 0.0,
        "fail_criteria": dict(fail_criteria),
        "rows": rows,
    }


def export_experts(run_id, model_dir):
    for name in EXPERTS:
        export_actor(
            model_dir / f"sac_{name}_best.zip",
            LAB / f"sac_{name}_weights.mat",
            expected_run_id=run_id,
        )


def rel_to_root(path: Path) -> str:
    p = path if path.is_absolute() else ROOT / path
    try:
        return str(p.resolve().relative_to(ROOT))
    except ValueError:
        return str(p.resolve())


def write_combo_json(run_id: str, model_dir: Path, source: dict[str, Path], trained: set[str], run_dir: Path) -> Path:
    model_paths = {}
    for name in EXPERTS:
        candidate = model_dir / f"sac_{name}_best.zip" if name in trained else source[name]
        model_paths[name] = rel_to_root(candidate)
    combo = {
        "run_id": run_id,
        "pure_sac": True,
        "deployment_mode": "mi12 online-gated four-expert SAC",
        "no_deployment_rules": True,
        "model_paths": model_paths,
        "trained_experts": sorted(trained),
    }
    path = run_dir / f"pure_sac_combo_{run_id}.json"
    path.write_text(json.dumps(combo, indent=2), encoding="utf-8")
    return path


def jsonable_args(args):
    out = {}
    for k, v in vars(args).items():
        out[k] = str(v) if isinstance(v, Path) else v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", type=Path, default=Path(os.environ.get("HPT_SCENARIO_CSV", EXPANDED)))
    ap.add_argument("--steps", type=int, default=120_000)
    ap.add_argument("--eval-freq", type=int, default=20_000)
    ap.add_argument("--n-envs", type=int, default=4)
    ap.add_argument("--seed", type=int, default=20260709)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--batch-size", type=int, default=512)
    ap.add_argument("--buffer-size", type=int, default=200_000)
    ap.add_argument("--gradient-steps", type=int, default=2)
    ap.add_argument("--hard-weight", type=int, default=16)
    ap.add_argument("--switch-weight", type=int, default=32)
    ap.add_argument("--traditional-only-csv", type=Path, default=TRADITIONAL_ONLY,
                    help="Backward-compatible CSV of pass-set target scenarios.")
    ap.add_argument("--repair-target-csv", type=Path, default=None,
                    help="CSV of target scenarios to oversample and use for checkpoint selection.")
    ap.add_argument("--traditional-only-weight", type=int, default=48,
                    help="Oversampling weight for traditional-only scenarios.")
    ap.add_argument("--shallow-hvrt-weight", type=int, default=8,
                    help="Oversampling weight for all shallow HVRT boundary scenarios.")
    ap.add_argument("--deep-sym-weight", type=int, default=4,
                    help="Oversampling weight for deep symmetric LVRT scenarios.")
    ap.add_argument("--target-bonus-weight", type=float, default=0.25,
                    help="Small checkpoint-selection bonus for repair-target proxy once broad validation is healthy.")
    ap.add_argument("--min-val-proxy-for-target-bonus", type=float, default=80.0,
                    help="Disable target bonus below this broad validation partial proxy.")
    ap.add_argument("--experts", nargs="+", default=list(EXPERTS), choices=list(EXPERTS))
    ap.add_argument("--warm-start", action="store_true", default=True)
    ap.add_argument("--no-warm-start", action="store_false", dest="warm_start")
    ap.add_argument("--source-dir", type=Path, default=None,
                    help="Optional directory containing sac_<expert>_best.zip warm-start checkpoints.")
    ap.add_argument("--source-sym", type=Path, default=None,
                    help="Optional explicit warm-start checkpoint for the sym expert.")
    ap.add_argument("--source-asym", type=Path, default=None,
                    help="Optional explicit warm-start checkpoint for the asym expert.")
    ap.add_argument("--source-hvrt-sym", type=Path, default=None,
                    help="Optional explicit warm-start checkpoint for the hvrt_sym expert.")
    ap.add_argument("--source-hvrt-asym", type=Path, default=None,
                    help="Optional explicit warm-start checkpoint for the hvrt_asym expert.")
    ap.add_argument("--export", action="store_true", help="export sac_*_weights.mat after all selected experts train")
    ap.add_argument("--promote", action="store_true", help="replace data/models/sac_<expert> checkpoints")
    args = ap.parse_args()

    run_id = os.environ.get("HPT_RUN_ID") or new_run_id("pure_sac")
    run_dir = RESULTS / f"pure_sac_hard_curriculum_{time.strftime('%Y%m%d_%H%M%S')}_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (RESULTS / ".p3_current_runid").write_text(run_id, encoding="utf-8")
    scenarios = load_frt_scenarios(args.scenarios)
    hard_ids = read_hard_ids()
    repair_target_csv = args.repair_target_csv or args.traditional_only_csv
    traditional_only_ids = read_scenario_ids(repair_target_csv)
    repair_labels = read_repair_labels(repair_target_csv)
    scenarios = attach_repair_labels(scenarios, repair_labels)
    source = {name: source_checkpoint_for(name, args) for name in EXPERTS}
    backup = None
    if args.promote:
        backup = backup_existing(run_id)
    model_dir = MODELS if args.promote else run_dir / "models"

    summary = {
        "run_id": run_id,
        "pure_sac": True,
        "deployment_mode": "mi12 online-gated four-expert SAC",
        "no_deployment_rules": True,
        "scenario_file": str(args.scenarios),
        "n_scenarios": len(scenarios),
        "hard_ids_n": len(hard_ids),
        "traditional_only_ids_n": len(traditional_only_ids),
        "repair_label_ids_n": len(repair_labels),
        "traditional_only_csv": str(args.traditional_only_csv),
        "repair_target_csv": str(repair_target_csv),
        "args": jsonable_args(args),
        "backup": str(backup) if backup else None,
        "model_dir": str(model_dir),
        "experts": {},
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("run_id", "deployment_mode", "scenario_file", "n_scenarios")}), flush=True)

    for name in args.experts:
        summary["experts"][name] = train_expert(
            name, scenarios, hard_ids, traditional_only_ids, args, run_id, run_dir, model_dir, source.get(name)
        )
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if args.export:
        export_experts(run_id, model_dir)
        summary["exported"] = True

    combo_path = write_combo_json(run_id, model_dir, source, set(args.experts), run_dir)
    summary["combo_json"] = str(combo_path)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    models = {name: load_sac(model_dir / f"sac_{name}_best.zip", device="cpu") for name in args.experts}
    if set(args.experts) == set(EXPERTS):
        router = ExpertRouter(models)
        full320 = load_frt_scenarios(FULL320)
        hard24 = load_frt_scenarios(HARD24) if HARD24.exists() else []
        hard92 = [s for s in scenarios if int(s["scenario_id"]) in hard_ids]
        traditional_only = [s for s in scenarios if int(s["scenario_id"]) in traditional_only_ids]
        summary["ode_eval"] = {
            "full320": evaluate_frt(router, full320, HPTFRTEnvV2, n_eval=None),
            "expanded2040": evaluate_frt(router, scenarios, HPTFRTEnvV2, n_eval=None),
            "hard24_rows": row_eval(router, hard24) if hard24 else None,
            "hard92_rows": row_eval(router, hard92),
            "traditional_only_rows": row_eval(router, traditional_only),
        }
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"wrote {run_dir}", flush=True)


if __name__ == "__main__":
    main()
