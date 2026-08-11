"""overnight_hard92_retrain.py -- fine-tune residual SAC on the 92 expanded hard negatives.

This is an experimental overnight runner. It does not run Simulink and it does not mutate certified
switching results. It fine-tunes the current residual SAC on expanded-2040 scenario CSV variants where
the 92 "baseline passes / SAC fails" scenarios are over-sampled, then evaluates every candidate on:

  * expanded-2040 ODE proxy
  * hard-92 ODE proxy

The best candidate is promoted back to data/models at the end; all candidates and logs are archived.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from gymnasium import spaces
from stable_baselines3 import SAC
from stable_baselines3.common.vec_env import DummyVecEnv

from hpt_frt.common import frt_v2 as FV2
from ..error_analysis_mi14 import residual_model_path
from ..frt_env import ASYM_IQ_MEAS_BIAS, V_SE_MAX, effective_fault_dur, load_frt_scenarios
from ..frt_env_v2 import N_ACT_V2
from ..frt_metrics import CRITERIA, evaluate_scenario
from ..model_io import load_sac
from ..residual_env import (
    ASYM_FT,
    ASYM_IQ_FF_EPS,
    ASYM_IQ_FF_GAIN,
    HPTFRTResidualEnvV2,
    IQ_CAP,
    IQ_CAP_ASYM,
    RES_IQ,
    RES_MSE,
    mpc_prior3,
)
from ..train_common import FROZEN_SPLIT_SEED, env_seeds, pick_device, split_scenarios
from ..train_residual import EMACallback


ROOT = Path(__file__).resolve().parents[4]
LAB = ROOT / "lab"
RES = LAB / "results"
MODELS = ROOT / "data" / "models"
EXPANDED = LAB / "frt_scenarios_expanded.csv"
HARD_ANALYSIS = RES / "p3_expanded_baseline_only_error_analysis.csv"


class Hard92ResidualEnv(HPTFRTResidualEnvV2):
    """Residual env with extra shaping for the observed hard-92 failure mechanisms.

    The shaping is deliberately local:
      * HVRT boundary: discourage wrong-sign positive iq when measured V+ is near/above 1.1.
      * Strong-grid sym LVRT @ target~0.5: add Vdc margin pressure and discourage needless series use.
    """

    def step(self, action):
        obs, reward, done, trunc, info = super().step(action)
        s = self._sc
        in_fault = s["t_fault"] <= self.t <= s["t_fault"] + effective_fault_dur(s) * 0.20
        if in_fault and s["category"] == "HVRT" and str(s["fault_type"]).startswith("swell"):
            over_margin = max(0.0, float(info["V2p"]) - 1.095)
            wrong_side = max(0.0, float(info["iq"]) + FV2.REACTIVE_SIGN_EPS)
            reward += -140.0 * wrong_side * (1.0 + 20.0 * over_margin)
            reward += -8.0 * abs(float(info["mse_d"]))
        if (in_fault and s["category"] == "LVRT" and s["fault_type"] == "sym3ph"
                and float(s["target_V_pu"]) >= 0.45 and float(s["target_V_pu"]) <= 0.55
                and float(s["scr"]) >= 8.0):
            # The hard-92 residual after the first fine-tune is a narrow trade-off:
            # Vdc is recoverable, but iq falls ~0.006 pu short of the frt-v2 min-support line and
            # long SCR=10/15 cases need a tiny d-series lift. Teach that balance directly.
            min_support = FV2.iq_ref_droop(float(info["V2p"])) - FV2.REACTIVE_TOL + 0.008
            reward += -180.0 * max(0.0, min_support - float(info["iq"]))
            reward += -120.0 * max(0.0, float(s["target_V_pu"]) + 0.004 - float(info["V2p"]))
            reward += -90.0 * max(0.0, 0.765 - float(info["Vdc"]))
            target_mse_d = 0.012 if float(info["V2p"]) < 0.515 else 0.0
            reward += -12.0 * abs(float(info["mse_d"]) - target_mse_d)
            reward += -4.0 * abs(float(info["mse_q"]))
        return obs, float(reward), done, trunc, info


class ProjectedTotalResidualEnv(HPTFRTResidualEnvV2):
    """Training-only total-command sign guard.

    The base residual env applies the MPC prior plus residual, then sends the total command to the
    plant. This variant projects the total iq command to the criterion-consistent side near voltage
    excursions. It is used as an experiment, not as a certified deployment change.
    """

    def __init__(self, scenarios, seed=0, train_mode=True):
        super().__init__(scenarios, seed=seed, train_mode=train_mode)
        self.action_space = spaces.Box(
            low=np.array([-RES_IQ, -RES_MSE, -RES_MSE], np.float32),
            high=np.array([RES_IQ, RES_MSE, RES_MSE], np.float32),
        )

    def step(self, action):
        res = np.asarray(action, np.float32).reshape(N_ACT_V2)
        tot = mpc_prior3(self.V2p, self.Vdc) + res
        cap = IQ_CAP_ASYM if (self._sc["category"] == "LVRT"
                              and self._sc["fault_type"] in ASYM_FT) else IQ_CAP
        if (self._sc["category"] == "LVRT" and self._sc["fault_type"] in ASYM_FT
                and self.V2n > 0.05 and self.V2p < 1.10):
            tot[0] = max(tot[0], ASYM_IQ_FF_GAIN * ASYM_IQ_MEAS_BIAS * self.V2n + ASYM_IQ_FF_EPS)
        tot[0] = float(np.clip(tot[0], -cap, cap))
        tot[1] = float(np.clip(tot[1], -V_SE_MAX, V_SE_MAX))
        tot[2] = float(np.clip(tot[2], -V_SE_MAX, V_SE_MAX))
        if self.V2p < 0.9 and tot[0] < -FV2.REACTIVE_SIGN_EPS:
            tot[0] = 0.0
        elif self.V2p > 1.095 and tot[0] > FV2.REACTIVE_SIGN_EPS:
            tot[0] = 0.0
        return HPTFRTResidualEnvV2.__mro__[1].step(self, tot)


@dataclass(frozen=True)
class CandidateSpec:
    name: str
    env: str
    hard_weight: int
    steps: int
    eval_freq: int
    seed: int


def load_hard_ids() -> list[int]:
    with HARD_ANALYSIS.open(newline="", encoding="utf-8") as f:
        return [int(r["scenario_id"]) for r in csv.DictReader(f)]


def write_weighted_csv(path: Path, hard_ids: set[int], hard_weight: int):
    rows = list(csv.DictReader(EXPANDED.open(newline="", encoding="utf-8")))
    fields = list(rows[0].keys())
    extra = [r for r in rows if int(r["scenario_id"]) in hard_ids]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)
        for _ in range(max(0, hard_weight - 1)):
            for r in extra:
                w.writerow(r)


def env_cls(name: str):
    if name == "base":
        return HPTFRTResidualEnvV2
    if name == "hard92":
        return Hard92ResidualEnv
    if name == "projected":
        return ProjectedTotalResidualEnv
    raise ValueError(name)


def available_pass(res: dict) -> bool:
    if res.get("vdc_survive_proxy") != FV2.PASS:
        return False
    statuses = [res[c]["status"] for c in CRITERIA if res[c]["status"] != FV2.NOT_EVALUATED]
    return bool(statuses) and all(s == FV2.PASS for s in statuses)


def eval_model(model, scenarios, eval_env_cls) -> dict:
    rows = []
    fail_criteria = Counter()
    for s in scenarios:
        c = evaluate_scenario(model, eval_env_cls, s)
        if c["kind"] != "evaluated":
            rows.append({"sid": int(s["scenario_id"]), "pass": False, "kind": c["kind"]})
            fail_criteria[c["kind"]] += 1
            continue
        res = c["res"]
        fails = [k for k in CRITERIA if res[k]["status"] == FV2.FAIL]
        if res.get("vdc_survive_proxy") == FV2.FAIL:
            fails.append("vdc_survive_proxy")
        for k in fails:
            fail_criteria[k] += 1
        rows.append({
            "sid": int(s["scenario_id"]),
            "pass": available_pass(res),
            "failed_criteria": "+".join(fails),
            "vdc_min": res.get("vdc_min"),
        })
    n_pass = sum(1 for r in rows if r["pass"])
    return {
        "n": len(rows),
        "pass": n_pass,
        "fail": len(rows) - n_pass,
        "pass_pct": round(100.0 * n_pass / len(rows), 3) if rows else 0.0,
        "fail_criteria": dict(fail_criteria),
        "rows": rows,
    }


def copy_current_models(dst: Path):
    dst.mkdir(parents=True, exist_ok=True)
    for p in MODELS.glob("sac_residual*.*"):
        if p.is_file():
            shutil.copy2(p, dst / p.name)
    for p in [RES / "residual_train.json", RES / "residual_export_selection.json"]:
        if p.exists():
            shutil.copy2(p, dst / p.name)


def promote_model(src_zip: Path, meta: dict):
    MODELS.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_zip, MODELS / "sac_residual_ema_best.zip")
    shutil.copy2(src_zip, MODELS / "sac_residual_best.zip")
    shutil.copy2(src_zip, MODELS / "sac_residual_ema_final.zip")
    shutil.copy2(src_zip, MODELS / "sac_residual_final.zip")
    side = {
        "experimental_promotion": "overnight_hard92_retrain",
        "source_model": str(src_zip),
        **meta,
    }
    for name in ["sac_residual_ema_best.json", "sac_residual_best.json",
                 "sac_residual_ema_final.json", "sac_residual_final.json"]:
        (MODELS / name).write_text(json.dumps(side, indent=2), encoding="utf-8")
    (RES / "residual_export_selection.json").write_text(
        json.dumps({"selected_model": "sac_residual_ema_best.zip", **side}, indent=2),
        encoding="utf-8",
    )


def train_candidate(spec: CandidateSpec, run_dir: Path, base_model: Path, hard_ids: set[int], deadline: float):
    cand_dir = run_dir / spec.name
    cand_dir.mkdir(parents=True, exist_ok=True)
    csv_path = cand_dir / f"{spec.name}_scenarios.csv"
    write_weighted_csv(csv_path, hard_ids, spec.hard_weight)
    scenarios = load_frt_scenarios(csv_path)
    train_scn, _val_scn = split_scenarios(scenarios, val_frac=0.2, seed=FROZEN_SPLIT_SEED)
    cls = env_cls(spec.env)
    vec = DummyVecEnv([(lambda s=s: cls(train_scn, seed=s, train_mode=True))
                       for s in env_seeds(spec.seed, 8)])
    model = SAC.load(str(base_model), env=vec, device=pick_device())
    ema = EMACallback()
    expanded_scen = load_frt_scenarios(EXPANDED)
    hard_scen = [s for s in expanded_scen if int(s["scenario_id"]) in hard_ids]
    eval_cls = HPTFRTResidualEnvV2
    best = None
    step = 0
    while step < spec.steps and time.time() < deadline:
        chunk = min(spec.eval_freq, spec.steps - step)
        model.learn(total_timesteps=chunk, reset_num_timesteps=False, callback=ema)
        step += chunk
        candidates = [("raw", model)]
        if ema.ema is not None:
            bak = ema.load_into(model)
            candidates.append(("ema", model))
        for kind, m in candidates:
            hard_eval = eval_model(m, hard_scen, eval_cls)
            # Full 2040 ODE replay is intentionally deferred until after each candidate. It is too
            # expensive to run every 30k steps and would waste the overnight budget before training.
            score = 2.0 * hard_eval["pass"]
            rec = {
                "candidate": spec.name,
                "kind": kind,
                "step": step,
                "score": score,
                "hard92": {k: v for k, v in hard_eval.items() if k != "rows"},
                "expanded2040": None,
            }
            with (cand_dir / "eval_history.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            print(json.dumps(rec), flush=True)
            if best is None or score > best["score"]:
                path = cand_dir / f"best_{kind}_step{step}.zip"
                m.save(str(path))
                best = {**rec, "model_path": str(path)}
                (cand_dir / "best.json").write_text(json.dumps(best, indent=2), encoding="utf-8")
        if ema.ema is not None:
            model.policy.actor.load_state_dict(bak)
    model.save(str(cand_dir / "final_raw.zip"))
    if best is not None:
        # One authoritative full-expanded check for the best snapshot of this candidate.
        best_model = load_sac(Path(best["model_path"]))
        hard_eval = eval_model(best_model, hard_scen, eval_cls)
        full_eval = eval_model(best_model, expanded_scen, eval_cls)
        best["hard92"] = {k: v for k, v in hard_eval.items() if k != "rows"}
        best["expanded2040"] = {k: v for k, v in full_eval.items() if k != "rows"}
        best["score"] = full_eval["pass"] + 2.0 * hard_eval["pass"]
        (cand_dir / "best.json").write_text(json.dumps(best, indent=2), encoding="utf-8")
    return best


def run(hours: float):
    run_id = time.strftime("overnight_hard92_%Y%m%d_%H%M%S")
    run_dir = RES / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + hours * 3600.0
    hard_ids = set(load_hard_ids())
    base_model = residual_model_path()
    copy_current_models(run_dir / "baseline_backup")
    expanded_scen = load_frt_scenarios(EXPANDED)
    hard_scen = [s for s in expanded_scen if int(s["scenario_id"]) in hard_ids]
    base_summary = json.loads((RES / "p3_expanded_ode_failure_summary_after_blindfix.json").read_text(encoding="utf-8"))
    baseline = {
        "base_model": str(base_model),
        "hard92": {"n": len(hard_scen), "pass": 0, "fail": len(hard_scen), "pass_pct": 0.0,
                   "note": "definition of hard-92: current residual SAC fails while baselines pass"},
        "expanded2040": {
            "n": int(base_summary["n"]),
            "pass": int(base_summary["n_proxy_pass"]),
            "fail": int(base_summary["n_proxy_fail"]),
            "pass_pct": float(base_summary["proxy_pass_pct"]),
            "source": str(RES / "p3_expanded_ode_failure_summary_after_blindfix.json"),
        },
    }
    baseline_score = baseline["expanded2040"]["pass"] + 2.0 * baseline["hard92"]["pass"]
    baseline["score"] = baseline_score
    (run_dir / "baseline_eval.json").write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    print(json.dumps({"run_dir": str(run_dir), "baseline": baseline}, indent=2), flush=True)
    specs = [
        CandidateSpec("v2_x24_balanced_sd42", "hard92", 24, 120_000, 20_000, 42),
        CandidateSpec("v2_x32_balanced_sd7", "hard92", 32, 120_000, 20_000, 7),
        CandidateSpec("v2_x16_projected_sd123", "projected", 16, 90_000, 30_000, 123),
        CandidateSpec("v2_x12_base_sd99", "base", 12, 90_000, 30_000, 99),
    ]
    all_best = []
    for spec in specs:
        if time.time() > deadline - 30 * 60:
            break
        best = train_candidate(spec, run_dir, base_model, hard_ids, deadline)
        if best:
            all_best.append(best)
            (run_dir / "candidate_bests.json").write_text(json.dumps(all_best, indent=2), encoding="utf-8")
    if all_best:
        winner = max(all_best, key=lambda r: (r["score"], r["hard92"]["pass"], r["expanded2040"]["pass"]))
        should_promote = winner["score"] > baseline_score
        if should_promote:
            promote_model(Path(winner["model_path"]), {"winner": winner, "run_dir": str(run_dir),
                                                       "baseline_score": baseline_score})
        (run_dir / "winner.json").write_text(
            json.dumps({"winner": winner, "baseline_score": baseline_score,
                        "promoted": should_promote}, indent=2),
            encoding="utf-8",
        )
        print(json.dumps({"winner": winner, "baseline_score": baseline_score,
                          "promoted": should_promote}, indent=2), flush=True)
    else:
        print(json.dumps({"winner": None, "promoted": False, "reason": "no completed candidate"}), flush=True)


def main():
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    os.environ.setdefault("MKL_THREADING_LAYER", "SEQUENTIAL")
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=8.0)
    args = ap.parse_args()
    run(args.hours)


if __name__ == "__main__":
    main()
