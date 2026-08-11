"""Export a selected pure-SAC mi12 four-expert combination to Simulink MAT weights."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import scipy.io as sio

from .export_sac_actor import export_actor
from .model_io import load_sac
from .train_common import sha256_file


ROOT = Path(__file__).resolve().parents[3]
LAB = ROOT / "lab"
RESULTS = LAB / "results"
MODELS = ROOT / "data" / "models"


def ensure_sidecar(path: Path, *, run_id: str, expert: str, note: str):
    side = path.with_suffix(".json")
    if side.exists():
        return json.loads(side.read_text(encoding="utf-8"))
    model = load_sac(path, device="cpu")
    sidecar = {
        "model_file": path.name,
        "kind": "selected",
        "checkpoint_step": 0,
        "model_sha256": sha256_file(path),
        "selection_rule": "manual pure-SAC combo selection after ODE gate experiments",
        "run_id": run_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "created_at_epoch": time.time(),
        "metrics_version": "frt-v2",
        "env_contract": "frt-v2",
        "env_class": "HPTFRTEnvV2",
        "observation_dim": int(model.observation_space.shape[0]),
        "action_dim": int(model.action_space.shape[0]),
        "policy_seed": 20260710,
        "deterministic_env_seeds": [],
        "scenario_split": note,
        "train_family_ids": [],
        "val_family_ids": [],
        "split_hash": "manual",
        "n_train": None,
        "n_val": None,
        "total_steps": None,
        "working_tree_fingerprint": "manual-selected-dirty",
        "source_log": None,
        "validation_partial_proxy_pct": None,
        "proxy_saturated": True,
        "proxy_criteria_evaluated_mean": None,
        "frt_pass_pct": None,
        "n_requested": None,
        "n_rollout_ok": None,
        "n_complete": None,
        "n_incomplete": None,
        "n_unevaluable": None,
        "expert": expert,
    }
    side.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    return sidecar


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", type=Path, required=True)
    ap.add_argument("--asym", type=Path, required=True)
    ap.add_argument("--hvrt-sym", type=Path, required=True)
    ap.add_argument("--hvrt-asym", type=Path, required=True)
    ap.add_argument("--run-id", default=f"pure_sac_combo_{time.strftime('%Y%m%d_%H%M%S')}")
    args = ap.parse_args()
    paths = {
        "sym": args.sym,
        "asym": args.asym,
        "hvrt_sym": args.hvrt_sym,
        "hvrt_asym": args.hvrt_asym,
    }
    note = "pure-SAC combo selected for Simulink spotcheck; no residual/MPC/runtime rule layer"
    (RESULTS / ".p3_current_runid").write_text(args.run_id, encoding="utf-8")
    for expert, path in paths.items():
        ensure_sidecar(path, run_id=args.run_id, expert=expert, note=note)
        mat_path = LAB / f"sac_{expert}_weights.mat"
        W = export_actor(path, mat_path, expected_run_id=None)
        # Keep the codegen MAT structs identical across experts. Detailed source
        # provenance stays in the combo manifest; Simulink reads this deployment id.
        W["run_id"] = args.run_id
        sio.savemat(str(mat_path), W)
    manifest = {
        "run_id": args.run_id,
        "pure_sac": True,
        "deployment_mode": "mi12 online-gated four-expert SAC",
        "model_paths": {k: str(v) for k, v in paths.items()},
        "mat_files": {k: str(LAB / f"sac_{k}_weights.mat") for k in paths},
    }
    out = RESULTS / f"pure_sac_combo_export_{args.run_id}.json"
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
