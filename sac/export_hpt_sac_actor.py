"""Export HPT voltage SAC actor weights for Simulink.

The exported MAT file matches the MATLAB Function forward pass used by
``simulink``:

- observation dimension: 24
- action dimension: 4
- actor hidden layers: [256, 256, 256]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import scipy.io as sio

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from .hpt_voltage_sac_env import ACT_DIM_HPT, OBS_DIM_HPT
from .runtime_utils import load_sac


MODELS = ROOT / "data" / "models"
SIMULINK_V2 = ROOT / "simulink"


def _actor_dict(model) -> dict:
    sd = model.policy.actor.state_dict()
    n_obs = int(np.prod(model.observation_space.shape))
    n_act = int(np.prod(model.action_space.shape))
    if "mu.weight" in sd:
        mu_w = sd["mu.weight"].cpu().numpy()
        mu_b = sd["mu.bias"].cpu().numpy()
    elif "mu.reg_head.weight" in sd and "mu.energy_head.weight" in sd:
        mu_w = np.concatenate(
            [
                sd["mu.reg_head.weight"].cpu().numpy(),
                sd["mu.energy_head.weight"].cpu().numpy(),
            ],
            axis=0,
        )
        mu_b = np.concatenate(
            [
                sd["mu.reg_head.bias"].cpu().numpy(),
                sd["mu.energy_head.bias"].cpu().numpy(),
            ],
            axis=0,
        )
    else:
        keys = ", ".join(sorted(sd))
        raise KeyError(f"Actor state dict does not contain an exportable mu head: {keys}")
    if n_obs != OBS_DIM_HPT or n_act != ACT_DIM_HPT or tuple(mu_w.shape) != (ACT_DIM_HPT, 256):
        raise ValueError(
            f"Expected HPT SAC contract {OBS_DIM_HPT}/{ACT_DIM_HPT} with "
            f"mu=({ACT_DIM_HPT},256), got {n_obs}/{n_act} mu={tuple(mu_w.shape)}"
        )
    out = {
        k.replace(".", "_"): v.cpu().numpy().astype("float64")
        for k, v in sd.items()
        if "latent_pi" in k
    }
    out["mu_weight"] = mu_w.astype("float64")
    out["mu_bias"] = mu_b.reshape(-1, 1).astype("float64")
    out["act_low"] = model.action_space.low.astype("float64")
    out["act_high"] = model.action_space.high.astype("float64")
    out["n_obs"] = np.array([[n_obs]], dtype="float64")
    out["n_act"] = np.array([[n_act]], dtype="float64")
    out["controller"] = "hpt-voltage-sac"
    return out


def placeholder_actor_dict() -> dict:
    """Create a zero-output actor for Simulink compile/interface tests."""

    h = 256
    out = {
        "latent_pi_0_weight": np.zeros((h, OBS_DIM_HPT), dtype="float64"),
        "latent_pi_0_bias": np.zeros((h, 1), dtype="float64"),
        "latent_pi_2_weight": np.zeros((h, h), dtype="float64"),
        "latent_pi_2_bias": np.zeros((h, 1), dtype="float64"),
        "latent_pi_4_weight": np.zeros((h, h), dtype="float64"),
        "latent_pi_4_bias": np.zeros((h, 1), dtype="float64"),
        "mu_weight": np.zeros((ACT_DIM_HPT, h), dtype="float64"),
        "mu_bias": np.zeros((ACT_DIM_HPT, 1), dtype="float64"),
        "act_low": np.array([[-0.8], [-0.8], [-0.95], [-0.95]], dtype="float64"),
        "act_high": np.array([[0.8], [0.8], [0.95], [0.95]], dtype="float64"),
        "n_obs": np.array([[OBS_DIM_HPT]], dtype="float64"),
        "n_act": np.array([[ACT_DIM_HPT]], dtype="float64"),
        "controller": "hpt-voltage-sac-placeholder",
    }
    return out


def export_hpt_actor(model_path: Path, out_path: Path) -> dict:
    model = load_sac(model_path, device="cpu")
    data = _actor_dict(model)
    sidecar = Path(model_path).with_suffix(".json")
    if sidecar.exists():
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        data["run_id"] = meta.get("run_id", "")
        data["training_steps"] = np.array([[meta.get("steps", np.nan)]], dtype="float64")
    else:
        data["run_id"] = ""
        data["training_steps"] = np.array([[np.nan]], dtype="float64")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sio.savemat(str(out_path), data)
    return data


def export_placeholder(out_path: Path) -> dict:
    data = placeholder_actor_dict()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sio.savemat(str(out_path), data)
    return data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=MODELS / "hpt_voltage_sac_best.zip")
    parser.add_argument("--out", type=Path, default=SIMULINK_V2 / "hpt_sac_actor_weights.mat")
    parser.add_argument("--placeholder", action="store_true")
    args = parser.parse_args()

    if args.placeholder:
        export_placeholder(args.out)
        print(f"exported placeholder HPT SAC actor -> {args.out}")
    else:
        export_hpt_actor(args.model, args.out)
        print(f"exported HPT SAC actor {args.model} -> {args.out}")


if __name__ == "__main__":
    main()
