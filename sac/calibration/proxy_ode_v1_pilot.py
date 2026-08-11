"""Pilot a physics-structured averaged ODE proxy for HPT fault trajectories.

This is a calibration/diagnostic script, not the production SAC environment.
It tests whether a small averaged dq-style ODE can roll out load voltage,
DC-link voltage, and converter current from real switch-level traces.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TRACE_DIR = (
    ROOT
    / "experts"
    / "topology2_single_phase_lvrt"
    / "data"
    / "proxy2_transition"
    / "p2_t2sp_a12_20260804"
    / "raw_traces"
)
DEFAULT_OUT_DIR = (
    ROOT
    / "experts"
    / "topology2_single_phase_lvrt"
    / "proxy"
    / "proxy_ode_v1_pilot"
)

NOMINAL_LV_RMS = 207.0
NOMINAL_VDC = 800.0
STATE_COLS = ["v_lv", "vdc", "i_d", "i_q", "v_dot"]
TARGET_STATE_COLS = ["v_lv", "vdc", "i_d", "i_q"]
ACTION_COLS = ["m_reg_d", "m_reg_q", "m_energy_d", "m_energy_q"]


@dataclass
class Scaler:
    mean: np.ndarray
    scale: np.ndarray

    def transform(self, x: np.ndarray) -> np.ndarray:
        return (x - self.mean) / self.scale

    @classmethod
    def fit(cls, x: np.ndarray) -> "Scaler":
        mean = np.mean(x, axis=0)
        scale = np.std(x, axis=0)
        scale[scale < 1e-9] = 1.0
        return cls(mean=mean, scale=scale)


@dataclass
class LinearOdeFit:
    scaler: Scaler
    coef: np.ndarray
    feature_names: list[str]
    target_names: list[str]

    def predict_derivative(self, features: np.ndarray) -> np.ndarray:
        x = self.scaler.transform(features.reshape(1, -1))
        return (x @ self.coef).reshape(-1)

    def to_jsonable(self) -> dict[str, object]:
        return {
            "feature_names": self.feature_names,
            "target_names": self.target_names,
            "feature_mean": self.scaler.mean.tolist(),
            "feature_scale": self.scaler.scale.tolist(),
            "coef": self.coef.tolist(),
        }


@dataclass
class TargetOdeFit:
    scaler: Scaler
    coef: np.ndarray
    taus: np.ndarray
    feature_names: list[str]
    state_names: list[str]

    def predict_equilibrium(self, features: np.ndarray) -> np.ndarray:
        x = self.scaler.transform(features.reshape(1, -1))
        return (x @ self.coef).reshape(-1)

    def to_jsonable(self) -> dict[str, object]:
        return {
            "ode_form": "dx_dt=(x_eq(phi)-x)/tau",
            "feature_names": self.feature_names,
            "state_names": self.state_names,
            "taus_s": self.taus.tolist(),
            "feature_mean": self.scaler.mean.tolist(),
            "feature_scale": self.scaler.scale.tolist(),
            "coef": self.coef.tolist(),
        }


def parse_case(path: Path) -> tuple[float, int]:
    text = path.stem.lower()
    pu_match = re.search(r"pu(\d{4})", text)
    dur_match = re.search(r"d(\d{3})ms", text)
    fault_pu = float(pu_match.group(1)) / 1000.0 if pu_match else float("nan")
    duration_ms = int(dur_match.group(1)) if dur_match else -1
    return fault_pu, duration_ms


def load_trace(path: Path, *, startup_skip_s: float) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = [
        "t",
        "window_zone",
        "lv_rms_inst",
        "vdc_inst",
        "obs_07",
        "obs_08",
        "cmd_action_01",
        "cmd_action_02",
        "cmd_action_03",
        "cmd_action_04",
    ]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise KeyError(f"{path} is missing columns: {missing}")

    for col in required:
        if col != "window_zone":
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["t", "lv_rms_inst", "vdc_inst"]).sort_values("t")
    df = df[df["t"] >= startup_skip_s].reset_index(drop=True)
    if len(df) < 4:
        raise ValueError(f"Not enough samples after startup skip: {path}")

    fault_pu, duration_ms = parse_case(path)
    out = pd.DataFrame(index=df.index)
    out["trace_source"] = str(path)
    out["case_name"] = path.stem
    out["fault_pu"] = fault_pu
    out["duration_ms"] = duration_ms
    out["t"] = df["t"].astype(float)
    out["t_ms"] = out["t"] * 1000.0
    out["dt"] = out["t"].diff().fillna(out["t"].diff().median()).astype(float)
    out["zone"] = df["window_zone"].astype(str)
    out["fault_flag"] = (out["zone"] == "fault").astype(float)
    out["recovery_flag"] = (out["zone"] == "recovery").astype(float)
    out["grid_eff"] = np.where(out["fault_flag"] > 0.5, fault_pu, 1.0)
    out["v_lv"] = df["lv_rms_inst"].astype(float) / NOMINAL_LV_RMS
    out["vdc"] = df["vdc_inst"].astype(float) / NOMINAL_VDC
    out["i_d"] = df["obs_07"].astype(float)
    out["i_q"] = df["obs_08"].astype(float)
    out["m_reg_d"] = df["cmd_action_01"].astype(float)
    out["m_reg_q"] = df["cmd_action_02"].astype(float)
    out["m_energy_d"] = df["cmd_action_03"].astype(float)
    out["m_energy_q"] = df["cmd_action_04"].astype(float)
    out["v_dot"] = np.gradient(out["v_lv"].to_numpy(), out["t"].to_numpy())
    return out.replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)


def ode_features(row: pd.Series) -> tuple[np.ndarray, list[str]]:
    v_lv = float(row["v_lv"])
    vdc = float(row["vdc"])
    i_d = float(row["i_d"])
    i_q = float(row["i_q"])
    v_dot = float(row["v_dot"])
    mrd = float(row["m_reg_d"])
    mrq = float(row["m_reg_q"])
    med = float(row["m_energy_d"])
    meq = float(row["m_energy_q"])
    grid = float(row["grid_eff"])
    fault = float(row["fault_flag"])
    recovery = float(row["recovery_flag"])

    p_energy = vdc * (med * i_d + meq * i_q)
    p_reg_proxy = vdc * (mrd * i_d + mrq * i_q)
    current_sq = i_d * i_d + i_q * i_q
    reg_sq = mrd * mrd + mrq * mrq
    energy_sq = med * med + meq * meq

    names = [
        "bias",
        "v_lv",
        "vdc",
        "i_d",
        "i_q",
        "v_dot",
        "grid",
        "fault",
        "recovery",
        "vdc_m_reg_d",
        "vdc_m_reg_q",
        "vdc_m_energy_d",
        "vdc_m_energy_q",
        "p_energy_proxy",
        "p_reg_proxy",
        "current_sq",
        "reg_action_sq",
        "energy_action_sq",
        "fault_m_reg_d",
        "fault_m_reg_q",
        "recovery_m_energy_d",
        "recovery_m_energy_q",
    ]
    values = np.asarray(
        [
            1.0,
            v_lv,
            vdc,
            i_d,
            i_q,
            v_dot,
            grid,
            fault,
            recovery,
            vdc * mrd,
            vdc * mrq,
            vdc * med,
            vdc * meq,
            p_energy,
            p_reg_proxy,
            current_sq,
            reg_sq,
            energy_sq,
            fault * mrd,
            fault * mrq,
            recovery * med,
            recovery * meq,
        ],
        dtype=float,
    )
    return values, names


def target_ode_features(row: pd.Series) -> tuple[np.ndarray, list[str]]:
    v_lv = float(row["v_lv"])
    vdc = float(row["vdc"])
    i_d = float(row["i_d"])
    i_q = float(row["i_q"])
    mrd = float(row["m_reg_d"])
    mrq = float(row["m_reg_q"])
    med = float(row["m_energy_d"])
    meq = float(row["m_energy_q"])
    grid = float(row["grid_eff"])
    fault = float(row["fault_flag"])
    recovery = float(row["recovery_flag"])

    p_energy = vdc * (med * i_d + meq * i_q)
    p_reg_proxy = vdc * (mrd * i_d + mrq * i_q)
    current_sq = i_d * i_d + i_q * i_q
    reg_sq = mrd * mrd + mrq * mrq
    energy_sq = med * med + meq * meq
    names = [
        "bias",
        "v_lv",
        "vdc",
        "i_d",
        "i_q",
        "grid",
        "fault",
        "recovery",
        "vdc_m_reg_d",
        "vdc_m_reg_q",
        "vdc_m_energy_d",
        "vdc_m_energy_q",
        "p_energy_proxy",
        "p_reg_proxy",
        "current_sq",
        "reg_action_sq",
        "energy_action_sq",
        "fault_m_reg_d",
        "fault_m_reg_q",
        "recovery_m_energy_d",
        "recovery_m_energy_q",
    ]
    values = np.asarray(
        [
            1.0,
            v_lv,
            vdc,
            i_d,
            i_q,
            grid,
            fault,
            recovery,
            vdc * mrd,
            vdc * mrq,
            vdc * med,
            vdc * meq,
            p_energy,
            p_reg_proxy,
            current_sq,
            reg_sq,
            energy_sq,
            fault * mrd,
            fault * mrq,
            recovery * med,
            recovery * meq,
        ],
        dtype=float,
    )
    return values, names


def build_ode_training_rows(traces: list[pd.DataFrame]) -> tuple[np.ndarray, np.ndarray, list[str]]:
    x_rows: list[np.ndarray] = []
    y_rows: list[np.ndarray] = []
    feature_names: list[str] | None = None
    for trace in traces:
        for idx in range(len(trace) - 1):
            cur = trace.iloc[idx]
            nxt = trace.iloc[idx + 1]
            dt = float(nxt["t"] - cur["t"])
            if dt <= 0:
                continue
            features, names = ode_features(cur)
            feature_names = names
            # State derivative target. For v_lv, the ODE state equation is
            # dv_lv/dt = v_dot, so the learned target uses acceleration.
            deriv = np.asarray(
                [
                    (float(nxt["vdc"]) - float(cur["vdc"])) / dt,
                    (float(nxt["i_d"]) - float(cur["i_d"])) / dt,
                    (float(nxt["i_q"]) - float(cur["i_q"])) / dt,
                    (float(nxt["v_dot"]) - float(cur["v_dot"])) / dt,
                ],
                dtype=float,
            )
            x_rows.append(features)
            y_rows.append(deriv)
    if not x_rows or feature_names is None:
        raise ValueError("No ODE training rows were built.")
    return np.vstack(x_rows), np.vstack(y_rows), feature_names


def fit_linear_ode(x: np.ndarray, y: np.ndarray, feature_names: list[str], *, ridge: float) -> LinearOdeFit:
    scaler = Scaler.fit(x)
    xs = scaler.transform(x)
    coef = np.linalg.solve(xs.T @ xs + ridge * np.eye(xs.shape[1]), xs.T @ y)
    return LinearOdeFit(
        scaler=scaler,
        coef=coef,
        feature_names=feature_names,
        target_names=["dvdc_dt", "di_d_dt", "di_q_dt", "dv_dot_dt"],
    )


def build_target_ode_rows(traces: list[pd.DataFrame]) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    x_rows: list[np.ndarray] = []
    state_rows: list[np.ndarray] = []
    next_rows: list[np.ndarray] = []
    dt_rows: list[float] = []
    feature_names: list[str] | None = None
    for trace in traces:
        for idx in range(len(trace) - 1):
            cur = trace.iloc[idx]
            nxt = trace.iloc[idx + 1]
            dt = float(nxt["t"] - cur["t"])
            if dt <= 0:
                continue
            features, names = target_ode_features(cur)
            feature_names = names
            x_rows.append(features)
            state_rows.append(cur[TARGET_STATE_COLS].astype(float).to_numpy())
            next_rows.append(nxt[TARGET_STATE_COLS].astype(float).to_numpy())
            dt_rows.append(dt)
    if not x_rows or feature_names is None:
        raise ValueError("No target ODE training rows were built.")
    return (
        np.vstack(x_rows),
        np.vstack(state_rows),
        np.vstack(next_rows),
        np.asarray(dt_rows, dtype=float),
        feature_names,
    )


def fit_target_ode(
    x: np.ndarray,
    state: np.ndarray,
    next_state: np.ndarray,
    dt: np.ndarray,
    feature_names: list[str],
    *,
    ridge: float,
) -> TargetOdeFit:
    scaler = Scaler.fit(x)
    xs = scaler.transform(x)
    tau_grid = np.geomspace(0.002, 0.25, 120)
    coefs: list[np.ndarray] = []
    taus: list[float] = []
    for idx in range(state.shape[1]):
        best: tuple[float, float, np.ndarray] | None = None
        for tau in tau_grid:
            beta = 1.0 - np.exp(-dt / tau)
            beta = np.clip(beta, 1e-4, 1.0)
            eq_target = (next_state[:, idx] - (1.0 - beta) * state[:, idx]) / beta
            coef = np.linalg.solve(xs.T @ xs + ridge * np.eye(xs.shape[1]), xs.T @ eq_target)
            eq_pred = xs @ coef
            pred = (1.0 - beta) * state[:, idx] + beta * eq_pred
            rmse = float(np.sqrt(np.mean((pred - next_state[:, idx]) ** 2)))
            if best is None or rmse < best[0]:
                best = (rmse, float(tau), coef)
        assert best is not None
        taus.append(best[1])
        coefs.append(best[2])
    return TargetOdeFit(
        scaler=scaler,
        coef=np.vstack(coefs).T,
        taus=np.asarray(taus, dtype=float),
        feature_names=feature_names,
        state_names=TARGET_STATE_COLS,
    )


def rollout_target(trace: pd.DataFrame, model: TargetOdeFit) -> pd.DataFrame:
    records: list[dict[str, float | str]] = []
    state = trace.iloc[0][TARGET_STATE_COLS].astype(float).to_numpy()
    for idx in range(len(trace)):
        row = trace.iloc[idx].copy()
        for name, value in zip(TARGET_STATE_COLS, state):
            row[name] = float(value)
        records.append(
            {
                "t_ms": float(trace.iloc[idx]["t_ms"]),
                "zone": str(trace.iloc[idx]["zone"]),
                "sim_v_lv": float(trace.iloc[idx]["v_lv"]),
                "model_v_lv": float(state[0]),
                "sim_vdc": float(trace.iloc[idx]["vdc"]),
                "model_vdc": float(state[1]),
                "sim_i_mag": float(np.hypot(trace.iloc[idx]["i_d"], trace.iloc[idx]["i_q"])),
                "model_i_mag": float(np.hypot(state[2], state[3])),
            }
        )
        if idx >= len(trace) - 1:
            break
        dt = float(trace.iloc[idx + 1]["t"] - trace.iloc[idx]["t"])
        eq = model.predict_equilibrium(target_ode_features(row)[0])
        beta = 1.0 - np.exp(-dt / model.taus)
        beta = np.clip(beta, 1e-4, 1.0)
        next_state = (1.0 - beta) * state + beta * eq
        next_state[0] = float(np.clip(next_state[0], 0.0, 1.4))
        next_state[1] = float(np.clip(next_state[1], 0.0, 1.4))
        next_state[2] = float(np.clip(next_state[2], -2.0, 2.0))
        next_state[3] = float(np.clip(next_state[3], -2.0, 2.0))
        state = next_state
    return pd.DataFrame(records)


def rollout(trace: pd.DataFrame, model: LinearOdeFit) -> pd.DataFrame:
    records: list[dict[str, float | str]] = []
    state = trace.iloc[0][STATE_COLS].astype(float).to_numpy()
    for idx in range(len(trace)):
        row = trace.iloc[idx].copy()
        for name, value in zip(STATE_COLS, state):
            row[name] = float(value)
        records.append(
            {
                "t_ms": float(trace.iloc[idx]["t_ms"]),
                "zone": str(trace.iloc[idx]["zone"]),
                "sim_v_lv": float(trace.iloc[idx]["v_lv"]),
                "model_v_lv": float(state[0]),
                "sim_vdc": float(trace.iloc[idx]["vdc"]),
                "model_vdc": float(state[1]),
                "sim_i_mag": float(np.hypot(trace.iloc[idx]["i_d"], trace.iloc[idx]["i_q"])),
                "model_i_mag": float(np.hypot(state[2], state[3])),
            }
        )
        if idx >= len(trace) - 1:
            break
        dt = float(trace.iloc[idx + 1]["t"] - trace.iloc[idx]["t"])
        deriv = model.predict_derivative(ode_features(row)[0])
        # Semi-implicit Euler. v_lv uses the explicit derivative state, while
        # vdc and current follow the fitted averaged dq/power-balance rates.
        next_state = state.copy()
        next_state[1] = state[1] + dt * deriv[0]
        next_state[2] = state[2] + dt * deriv[1]
        next_state[3] = state[3] + dt * deriv[2]
        next_state[4] = state[4] + dt * deriv[3]
        next_state[0] = state[0] + dt * next_state[4]
        next_state[0] = float(np.clip(next_state[0], 0.0, 1.4))
        next_state[1] = float(np.clip(next_state[1], 0.0, 1.4))
        next_state[2] = float(np.clip(next_state[2], -2.0, 2.0))
        next_state[3] = float(np.clip(next_state[3], -2.0, 2.0))
        next_state[4] = float(np.clip(next_state[4], -80.0, 80.0))
        state = next_state
    return pd.DataFrame(records)


def metric(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    err = np.asarray(y_pred, dtype=float) - np.asarray(y_true, dtype=float)
    return {
        "rmse": float(np.sqrt(np.mean(err * err))),
        "mae": float(np.mean(np.abs(err))),
        "max_abs": float(np.max(np.abs(err))),
    }


def summarize_rollout(comp: pd.DataFrame) -> dict[str, dict[str, float]]:
    return {
        "v_lv_pu": metric(comp["sim_v_lv"], comp["model_v_lv"]),
        "vdc_pu": metric(comp["sim_vdc"], comp["model_vdc"]),
        "i_energy_mag_pu": metric(comp["sim_i_mag"], comp["model_i_mag"]),
    }


def plot_rollout(comp: pd.DataFrame, out_png: Path, *, title: str) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(7.4, 6.0), dpi=200, sharex=True, facecolor="white")
    for ax, sim, model, ylabel in zip(
        axes,
        ["sim_v_lv", "sim_vdc", "sim_i_mag"],
        ["model_v_lv", "model_vdc", "model_i_mag"],
        ["Load-side voltage (pu)", "DC-link voltage (pu)", "Energy current |i| (pu)"],
    ):
        fault = comp["zone"] == "fault"
        if fault.any():
            ax.axvspan(comp.loc[fault, "t_ms"].min(), comp.loc[fault, "t_ms"].max(), color="#f0c36a", alpha=0.2)
        ax.plot(comp["t_ms"], comp[sim], color="#111111", lw=1.7, label="Simulink trace")
        ax.plot(comp["t_ms"], comp[model], color="#d62728", lw=1.5, ls="--", label="ODE proxy v1")
        ax.set_ylabel(ylabel, fontsize=9)
        ax.grid(True, color="#dddddd", lw=0.6)
        ax.tick_params(labelsize=8)
    axes[-1].set_xlabel("Time (ms)", fontsize=9)
    axes[0].legend(loc="best", fontsize=8, frameon=True)
    fig.suptitle(title, fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(out_png, facecolor="white", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-dir", type=Path, default=DEFAULT_TRACE_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--holdout", default="pu0825_d120ms")
    parser.add_argument("--startup-skip-s", type=float, default=0.040)
    parser.add_argument("--ridge", type=float, default=1e-4)
    parser.add_argument("--ode-form", choices=["target", "direct"], default="target")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    paths = sorted(args.trace_dir.glob("trajectory_trace_*.csv"))
    if not paths:
        raise FileNotFoundError(f"No trajectory_trace_*.csv files in {args.trace_dir}")

    traces = [(path, load_trace(path, startup_skip_s=args.startup_skip_s)) for path in paths]
    holdout_matches = [(path, trace) for path, trace in traces if args.holdout.lower() in path.stem.lower()]
    if not holdout_matches:
        raise ValueError(f"No holdout trace matched {args.holdout!r}")
    holdout_path, holdout_trace = holdout_matches[0]
    train_traces = [trace for path, trace in traces if path != holdout_path]
    if not train_traces:
        raise ValueError("Need at least one training trace besides holdout.")

    if args.ode_form == "target":
        x, state, next_state, dt, feature_names = build_target_ode_rows(train_traces)
        model = fit_target_ode(x, state, next_state, dt, feature_names, ridge=args.ridge)
        comp = rollout_target(holdout_trace, model)
        model_note = "Stable target ODE: dx/dt=(x_eq(phi)-x)/tau."
    else:
        x, y, feature_names = build_ode_training_rows(train_traces)
        model = fit_linear_ode(x, y, feature_names, ridge=args.ridge)
        comp = rollout(holdout_trace, model)
        model_note = "Direct derivative ODE: fitted d[vdc,id,iq,vdot]/dt."
    comp_csv = args.out_dir / "holdout_rollout_comparison.csv"
    comp.to_csv(comp_csv, index=False)
    figure = args.out_dir / "holdout_ode_proxy_v1_vs_simulink.png"
    plot_rollout(
        comp,
        figure,
        title=f"ODE Proxy v1 vs Switch-Level Holdout\n{holdout_path.stem}",
    )

    summary = {
        "schema": "hpt-proxy-ode-v1-pilot",
        "trace_dir": str(args.trace_dir),
        "out_dir": str(args.out_dir),
        "startup_skip_s": float(args.startup_skip_s),
        "ridge": float(args.ridge),
        "ode_form": args.ode_form,
        "n_traces": int(len(traces)),
        "n_train_traces": int(len(train_traces)),
        "holdout_trace": str(holdout_path),
        "train_traces": [str(path) for path, _ in traces if path != holdout_path],
        "state_cols": STATE_COLS,
        "action_cols": ACTION_COLS,
        "metrics_holdout_free_rollout": summarize_rollout(comp),
        "notes": [
            model_note,
            "Current uses obs_07/obs_08 energy-converter dq current because the trace lacks time-resolved grid current.",
            "The fitted derivatives use averaged dq voltage terms Vdc*m and proxy power-balance terms Vdc*m*i.",
        ],
        "artifacts": {
            "comparison_csv": str(comp_csv),
            "figure_png": str(figure),
            "model_json": str(args.out_dir / "ode_proxy_v1_model.json"),
        },
    }
    (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (args.out_dir / "ode_proxy_v1_model.json").write_text(
        json.dumps(model.to_jsonable(), indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
