"""Pilot a physical-state ODE proxy using timestep-level Simulink traces.

This diagnostic uses the upgraded trajectory collector columns:
grid command voltage, measured grid voltage/current dq, load-side voltage,
energy-converter voltage/current dq, regulating-branch current, HBC capacitor
voltage, series injection voltage, estimated DC-link capacitor current, Vdc,
and dq action commands.
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
    / "p2_t2sp_a12_ode_v2_20260804"
    / "raw_traces"
)
DEFAULT_OUT_DIR = (
    ROOT
    / "experts"
    / "topology2_single_phase_lvrt"
    / "proxy"
    / "proxy_ode_v3_measured_state_pilot"
)

STATE_COLS = [
    "v_lv",
    "vdc",
    "grid_i_d",
    "grid_i_q",
    "energy_i_d",
    "energy_i_q",
    "grid_v_mag",
    "energy_v_mag",
]
HIDDEN_COLS = [
    "reg_i_d",
    "reg_i_q",
    "hbc_cap_v_mag",
    "series_inj_v_mag",
    "idc_cap",
]
ACTION_COLS = ["m_reg_d", "m_reg_q", "m_energy_d", "m_energy_q"]


@dataclass
class Scaler:
    mean: np.ndarray
    scale: np.ndarray

    @classmethod
    def fit(cls, x: np.ndarray) -> "Scaler":
        mean = np.mean(x, axis=0)
        scale = np.std(x, axis=0)
        scale[scale < 1e-9] = 1.0
        return cls(mean, scale)

    def transform(self, x: np.ndarray) -> np.ndarray:
        return (x - self.mean) / self.scale


@dataclass
class TargetOdeFit:
    scaler: Scaler
    coef: np.ndarray
    taus: np.ndarray
    feature_names: list[str]
    state_names: list[str]

    def equilibrium(self, features: np.ndarray) -> np.ndarray:
        xs = self.scaler.transform(features.reshape(1, -1))
        return (xs @ self.coef).reshape(-1)

    def to_jsonable(self) -> dict[str, object]:
        return {
            "schema": "hpt-proxy-ode-v3-measured-state-target-ode",
            "feature_names": self.feature_names,
            "state_names": self.state_names,
            "taus_s": self.taus.tolist(),
            "feature_mean": self.scaler.mean.tolist(),
            "feature_scale": self.scaler.scale.tolist(),
            "coef": self.coef.tolist(),
        }


@dataclass
class HiddenFit:
    scaler: Scaler
    coef: np.ndarray
    feature_names: list[str]
    hidden_names: list[str]

    def predict(self, features: np.ndarray) -> np.ndarray:
        xs = self.scaler.transform(features.reshape(1, -1))
        return (xs @ self.coef).reshape(-1)

    def to_jsonable(self) -> dict[str, object]:
        return {
            "schema": "hpt-proxy-ode-v3-hidden-state-estimator",
            "feature_names": self.feature_names,
            "hidden_names": self.hidden_names,
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


def read_physical_params(trace_dir: Path) -> dict[str, float]:
    candidates = sorted(trace_dir.glob("*_physical_params.json"))
    if not candidates:
        return {}
    raw = json.loads(candidates[0].read_text(encoding="utf-8"))
    return {k: float(v) for k, v in raw.items() if isinstance(v, (int, float))}


def load_trace(path: Path, *, startup_skip_s: float) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = [
        "t",
        "window_zone",
        "lv_v_mag_pu_inst",
        "vdc_pu_inst",
        "grid_cmd_v_mag_pu_inst",
        "grid_v_mag_pu_inst",
        "grid_i_d_pu_inst",
        "grid_i_q_pu_inst",
        "energy_v_mag_pu_inst",
        "energy_i_d_pu_inst",
        "energy_i_q_pu_inst",
        "reg_i_d_pu_inst",
        "reg_i_q_pu_inst",
        "hbc_cap_v_mag_pu_inst",
        "series_inj_v_mag_pu_inst",
        "idc_cap_inst",
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
    df = df.dropna(subset=required).sort_values("t")
    df = df[df["t"] >= startup_skip_s].reset_index(drop=True)
    if len(df) < 4:
        raise ValueError(f"Not enough rows after startup skip: {path}")

    fault_pu, duration_ms = parse_case(path)
    out = pd.DataFrame(index=df.index)
    out["trace_source"] = str(path)
    out["case_name"] = path.stem
    out["fault_pu"] = fault_pu
    out["duration_ms"] = duration_ms
    out["t"] = df["t"].astype(float)
    out["t_ms"] = out["t"] * 1000.0
    out["zone"] = df["window_zone"].astype(str)
    out["fault_flag"] = (out["zone"] == "fault").astype(float)
    out["recovery_flag"] = (out["zone"] == "recovery").astype(float)
    out["time_in_fault"] = np.maximum(0.0, out["t"] - 0.035)
    out["grid_cmd"] = df["grid_cmd_v_mag_pu_inst"].astype(float)
    out["grid_v_mag"] = df["grid_v_mag_pu_inst"].astype(float)
    out["v_lv"] = df["lv_v_mag_pu_inst"].astype(float)
    out["vdc"] = df["vdc_pu_inst"].astype(float)
    out["grid_i_d"] = df["grid_i_d_pu_inst"].astype(float)
    out["grid_i_q"] = df["grid_i_q_pu_inst"].astype(float)
    out["energy_v_mag"] = df["energy_v_mag_pu_inst"].astype(float)
    out["energy_i_d"] = df["energy_i_d_pu_inst"].astype(float)
    out["energy_i_q"] = df["energy_i_q_pu_inst"].astype(float)
    out["reg_i_d"] = df["reg_i_d_pu_inst"].astype(float)
    out["reg_i_q"] = df["reg_i_q_pu_inst"].astype(float)
    out["hbc_cap_v_mag"] = df["hbc_cap_v_mag_pu_inst"].astype(float)
    out["series_inj_v_mag"] = df["series_inj_v_mag_pu_inst"].astype(float)
    out["idc_cap"] = df["idc_cap_inst"].astype(float) / 500.0
    out["m_reg_d"] = df["cmd_action_01"].astype(float)
    out["m_reg_q"] = df["cmd_action_02"].astype(float)
    out["m_energy_d"] = df["cmd_action_03"].astype(float)
    out["m_energy_q"] = df["cmd_action_04"].astype(float)
    return out.replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)


def features(row: pd.Series, phys: dict[str, float]) -> tuple[np.ndarray, list[str]]:
    s = {name: float(row[name]) for name in STATE_COLS}
    h = {name: float(row[name]) for name in HIDDEN_COLS}
    a = {name: float(row[name]) for name in ACTION_COLS}
    grid_cmd = float(row["grid_cmd"])
    fault = float(row["fault_flag"])
    recovery = float(row["recovery_flag"])
    time_fault = float(row["time_in_fault"])
    grid_i_mag = float(np.hypot(s["grid_i_d"], s["grid_i_q"]))
    energy_i_mag = float(np.hypot(s["energy_i_d"], s["energy_i_q"]))
    reg_i_mag = float(np.hypot(h["reg_i_d"], h["reg_i_q"]))
    reg_mag = float(np.hypot(a["m_reg_d"], a["m_reg_q"]))
    energy_mag = float(np.hypot(a["m_energy_d"], a["m_energy_q"]))
    vdc_mrd = s["vdc"] * a["m_reg_d"]
    vdc_mrq = s["vdc"] * a["m_reg_q"]
    vdc_med = s["vdc"] * a["m_energy_d"]
    vdc_meq = s["vdc"] * a["m_energy_q"]
    p_grid = s["grid_v_mag"] * s["grid_i_d"]
    q_grid = s["grid_v_mag"] * s["grid_i_q"]
    p_energy = s["energy_v_mag"] * s["energy_i_d"]
    q_energy = s["energy_v_mag"] * s["energy_i_q"]
    cdc = phys.get("dc_link_c_f", 0.0022)
    lhbc = phys.get("hbc_filter_l_h", 0.002)
    lenergy = phys.get("energy_filter_l_h", 0.0015)

    names = [
        "bias",
        *STATE_COLS,
        *ACTION_COLS,
        "grid_cmd",
        "fault",
        "recovery",
        "time_in_fault",
        "grid_cmd_minus_grid_v",
        "lv_minus_grid",
        "vdc_minus_1",
        "grid_i_mag",
        "energy_i_mag",
        "reg_mag",
        "energy_mag",
        "vdc_m_reg_d",
        "vdc_m_reg_q",
        "vdc_m_energy_d",
        "vdc_m_energy_q",
        "p_grid_proxy",
        "q_grid_proxy",
        "p_energy_proxy",
        "q_energy_proxy",
        "dc_energy_term",
        "reg_voltage_over_l",
        "energy_voltage_over_l",
        "fault_m_reg_d",
        "fault_m_reg_q",
    ]
    values = np.asarray(
        [
            1.0,
            *(s[name] for name in STATE_COLS),
            *(a[name] for name in ACTION_COLS),
            grid_cmd,
            fault,
            recovery,
            time_fault,
            grid_cmd - s["grid_v_mag"],
            s["v_lv"] - s["grid_v_mag"],
            s["vdc"] - 1.0,
            grid_i_mag,
            energy_i_mag,
            reg_mag,
            energy_mag,
            vdc_mrd,
            vdc_mrq,
            vdc_med,
            vdc_meq,
            p_grid,
            q_grid,
            p_energy,
            q_energy,
            (p_grid - p_energy) / max(cdc, 1e-9),
            (vdc_mrd - s["v_lv"]) / max(lhbc, 1e-9),
            (vdc_med - s["energy_v_mag"]) / max(lenergy, 1e-9),
            fault * a["m_reg_d"],
            fault * a["m_reg_q"],
        ],
        dtype=float,
    )
    return values, names


def hidden_features(row: pd.Series) -> tuple[np.ndarray, list[str]]:
    s = {name: float(row[name]) for name in STATE_COLS}
    a = {name: float(row[name]) for name in ACTION_COLS}
    grid_cmd = float(row["grid_cmd"])
    fault = float(row["fault_flag"])
    recovery = float(row["recovery_flag"])
    names = [
        "bias",
        *STATE_COLS,
        *ACTION_COLS,
        "grid_cmd",
        "fault",
        "recovery",
        "vdc_m_reg_d",
        "vdc_m_reg_q",
        "vdc_m_energy_d",
        "vdc_m_energy_q",
        "grid_cmd_minus_grid_v",
        "lv_minus_grid",
    ]
    values = np.asarray(
        [
            1.0,
            *(s[name] for name in STATE_COLS),
            *(a[name] for name in ACTION_COLS),
            grid_cmd,
            fault,
            recovery,
            s["vdc"] * a["m_reg_d"],
            s["vdc"] * a["m_reg_q"],
            s["vdc"] * a["m_energy_d"],
            s["vdc"] * a["m_energy_q"],
            grid_cmd - s["grid_v_mag"],
            s["v_lv"] - s["grid_v_mag"],
        ],
        dtype=float,
    )
    return values, names


def build_rows(
    traces: list[pd.DataFrame], phys: dict[str, float]
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str]]:
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
            x, names = features(cur, phys)
            feature_names = names
            x_rows.append(x)
            state_rows.append(cur[STATE_COLS].astype(float).to_numpy())
            next_rows.append(nxt[STATE_COLS].astype(float).to_numpy())
            dt_rows.append(dt)
    if feature_names is None:
        raise RuntimeError("No ODE rows built.")
    return (
        np.vstack(x_rows),
        np.vstack(state_rows),
        np.vstack(next_rows),
        np.asarray(dt_rows, dtype=float),
        feature_names,
    )


def build_hidden_rows(traces: list[pd.DataFrame]) -> tuple[np.ndarray, np.ndarray, list[str]]:
    x_rows: list[np.ndarray] = []
    y_rows: list[np.ndarray] = []
    feature_names: list[str] | None = None
    for trace in traces:
        for _, row in trace.iterrows():
            x, names = hidden_features(row)
            feature_names = names
            x_rows.append(x)
            y_rows.append(row[HIDDEN_COLS].astype(float).to_numpy())
    if feature_names is None:
        raise RuntimeError("No hidden-state rows built.")
    return np.vstack(x_rows), np.vstack(y_rows), feature_names


def fit_hidden(x: np.ndarray, y: np.ndarray, feature_names: list[str], *, ridge: float) -> HiddenFit:
    scaler = Scaler.fit(x)
    xs = scaler.transform(x)
    coef = np.linalg.solve(xs.T @ xs + ridge * np.eye(xs.shape[1]), xs.T @ y)
    return HiddenFit(scaler=scaler, coef=coef, feature_names=feature_names, hidden_names=HIDDEN_COLS)


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
    tau_grid = np.geomspace(0.002, 0.35, 160)
    coefs: list[np.ndarray] = []
    taus: list[float] = []
    for idx in range(state.shape[1]):
        best_rmse = float("inf")
        best_tau = float(tau_grid[0])
        best_coef = np.zeros(xs.shape[1])
        for tau in tau_grid:
            beta = np.clip(1.0 - np.exp(-dt / tau), 1e-4, 1.0)
            eq_target = (next_state[:, idx] - (1.0 - beta) * state[:, idx]) / beta
            coef = np.linalg.solve(xs.T @ xs + ridge * np.eye(xs.shape[1]), xs.T @ eq_target)
            pred = (1.0 - beta) * state[:, idx] + beta * (xs @ coef)
            rmse = float(np.sqrt(np.mean((pred - next_state[:, idx]) ** 2)))
            if rmse < best_rmse:
                best_rmse = rmse
                best_tau = float(tau)
                best_coef = coef
        taus.append(best_tau)
        coefs.append(best_coef)
    return TargetOdeFit(
        scaler=scaler,
        coef=np.vstack(coefs).T,
        taus=np.asarray(taus, dtype=float),
        feature_names=feature_names,
        state_names=STATE_COLS,
    )


def add_estimated_hidden(row: pd.Series, hidden_model: HiddenFit) -> pd.Series:
    row = row.copy()
    pred = hidden_model.predict(hidden_features(row)[0])
    for name, value in zip(HIDDEN_COLS, pred):
        row[name] = float(value)
    return row


def rollout(trace: pd.DataFrame, model: TargetOdeFit, hidden_model: HiddenFit, phys: dict[str, float]) -> pd.DataFrame:
    state = trace.iloc[0][STATE_COLS].astype(float).to_numpy()
    records: list[dict[str, float | str]] = []
    for idx in range(len(trace)):
        row = trace.iloc[idx].copy()
        for name, value in zip(STATE_COLS, state):
            row[name] = float(value)
        row = add_estimated_hidden(row, hidden_model)
        sim_state = trace.iloc[idx][STATE_COLS].astype(float)
        sim_hidden = trace.iloc[idx][HIDDEN_COLS].astype(float)
        records.append(
            {
                "t_ms": float(trace.iloc[idx]["t_ms"]),
                "zone": str(trace.iloc[idx]["zone"]),
                "sim_v_lv": float(sim_state["v_lv"]),
                "model_v_lv": float(state[0]),
                "sim_vdc": float(sim_state["vdc"]),
                "model_vdc": float(state[1]),
                "sim_grid_i_mag": float(np.hypot(sim_state["grid_i_d"], sim_state["grid_i_q"])),
                "model_grid_i_mag": float(np.hypot(state[2], state[3])),
                "sim_energy_i_mag": float(np.hypot(sim_state["energy_i_d"], sim_state["energy_i_q"])),
                "model_energy_i_mag": float(np.hypot(state[4], state[5])),
                "sim_grid_v_mag": float(sim_state["grid_v_mag"]),
                "model_grid_v_mag": float(state[6]),
                "sim_energy_v_mag": float(sim_state["energy_v_mag"]),
                "model_energy_v_mag": float(state[7]),
                "sim_reg_i_mag": float(np.hypot(sim_hidden["reg_i_d"], sim_hidden["reg_i_q"])),
                "model_reg_i_mag": float(np.hypot(row["reg_i_d"], row["reg_i_q"])),
                "sim_hbc_cap_v_mag": float(sim_hidden["hbc_cap_v_mag"]),
                "model_hbc_cap_v_mag": float(row["hbc_cap_v_mag"]),
                "sim_series_inj_v_mag": float(sim_hidden["series_inj_v_mag"]),
                "model_series_inj_v_mag": float(row["series_inj_v_mag"]),
                "sim_idc_cap": float(sim_hidden["idc_cap"]),
                "model_idc_cap": float(row["idc_cap"]),
            }
        )
        if idx >= len(trace) - 1:
            break
        dt = float(trace.iloc[idx + 1]["t"] - trace.iloc[idx]["t"])
        eq = model.equilibrium(features(row, phys)[0])
        beta = np.clip(1.0 - np.exp(-dt / model.taus), 1e-4, 1.0)
        state = (1.0 - beta) * state + beta * eq
        state[0] = np.clip(state[0], 0.0, 1.4)
        state[1] = np.clip(state[1], 0.0, 1.5)
        state[2:6] = np.clip(state[2:6], -3.0, 3.0)
        state[6:8] = np.clip(state[6:8], 0.0, 1.5)
    return pd.DataFrame(records)


def metric(y_true: pd.Series, y_pred: pd.Series) -> dict[str, float]:
    err = y_pred.to_numpy(dtype=float) - y_true.to_numpy(dtype=float)
    return {
        "rmse": float(np.sqrt(np.mean(err * err))),
        "mae": float(np.mean(np.abs(err))),
        "max_abs": float(np.max(np.abs(err))),
    }


def summarize(comp: pd.DataFrame) -> dict[str, dict[str, float]]:
    return {
        "v_lv_pu": metric(comp["sim_v_lv"], comp["model_v_lv"]),
        "vdc_pu": metric(comp["sim_vdc"], comp["model_vdc"]),
        "grid_current_mag_pu": metric(comp["sim_grid_i_mag"], comp["model_grid_i_mag"]),
        "energy_current_mag_pu": metric(comp["sim_energy_i_mag"], comp["model_energy_i_mag"]),
        "reg_current_mag_pu": metric(comp["sim_reg_i_mag"], comp["model_reg_i_mag"]),
        "grid_voltage_mag_pu": metric(comp["sim_grid_v_mag"], comp["model_grid_v_mag"]),
        "energy_voltage_mag_pu": metric(comp["sim_energy_v_mag"], comp["model_energy_v_mag"]),
        "hbc_cap_voltage_mag_pu": metric(comp["sim_hbc_cap_v_mag"], comp["model_hbc_cap_v_mag"]),
        "series_injection_voltage_mag_pu": metric(comp["sim_series_inj_v_mag"], comp["model_series_inj_v_mag"]),
        "idc_cap_500a_pu": metric(comp["sim_idc_cap"], comp["model_idc_cap"]),
    }


def plot(comp: pd.DataFrame, out_png: Path, title: str) -> None:
    specs = [
        ("sim_v_lv", "model_v_lv", "Load-side voltage (pu)"),
        ("sim_vdc", "model_vdc", "DC-link voltage (pu)"),
        ("sim_grid_i_mag", "model_grid_i_mag", "Grid current |i| (pu)"),
        ("sim_energy_i_mag", "model_energy_i_mag", "Energy current |i| (pu)"),
        ("sim_reg_i_mag", "model_reg_i_mag", "Reg current |i| (pu)"),
    ]
    fig, axes = plt.subplots(len(specs), 1, figsize=(7.6, 7.2), dpi=200, sharex=True, facecolor="white")
    fault = comp["zone"] == "fault"
    for ax, (sim, model, ylabel) in zip(axes, specs):
        if fault.any():
            ax.axvspan(comp.loc[fault, "t_ms"].min(), comp.loc[fault, "t_ms"].max(), color="#f0c36a", alpha=0.2)
        ax.plot(comp["t_ms"], comp[sim], color="#111111", lw=1.7, label="Simulink trace")
        ax.plot(comp["t_ms"], comp[model], color="#d62728", lw=1.5, ls="--", label="Physical ODE v3")
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-dir", type=Path, default=DEFAULT_TRACE_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--holdout", default="pu0825_d120ms")
    parser.add_argument("--startup-skip-s", type=float, default=0.040)
    parser.add_argument("--ridge", type=float, default=1e-3)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    phys = read_physical_params(args.trace_dir)
    paths = sorted(args.trace_dir.glob("trajectory_trace_*.csv"))
    if not paths:
        raise FileNotFoundError(f"No trace CSV files in {args.trace_dir}")
    traces = [(path, load_trace(path, startup_skip_s=args.startup_skip_s)) for path in paths]
    matches = [(path, trace) for path, trace in traces if args.holdout.lower() in path.stem.lower()]
    if not matches:
        raise ValueError(f"No holdout matched: {args.holdout}")
    holdout_path, holdout_trace = matches[0]
    train_traces = [trace for path, trace in traces if path != holdout_path]
    hx, hy, hidden_feature_names = build_hidden_rows(train_traces)
    hidden_model = fit_hidden(hx, hy, hidden_feature_names, ridge=args.ridge)
    x, state, next_state, dt, feature_names = build_rows(train_traces, phys)
    model = fit_target_ode(x, state, next_state, dt, feature_names, ridge=args.ridge)
    comp = rollout(holdout_trace, model, hidden_model, phys)

    comp_csv = args.out_dir / "holdout_rollout_comparison.csv"
    fig_png = args.out_dir / "holdout_physical_ode_v3_vs_simulink.png"
    model_json = args.out_dir / "ode_proxy_v3_model.json"
    summary_json = args.out_dir / "summary.json"
    comp.to_csv(comp_csv, index=False)
    plot(comp, fig_png, f"Physical ODE Proxy v3 vs Switch-Level Holdout\n{holdout_path.stem}")
    model_json.write_text(
        json.dumps(
            {
                "ode": model.to_jsonable(),
                "hidden_estimator": hidden_model.to_jsonable(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    summary = {
        "schema": "hpt-proxy-ode-v3-measured-state-pilot",
        "trace_dir": str(args.trace_dir),
        "out_dir": str(args.out_dir),
        "startup_skip_s": float(args.startup_skip_s),
        "ridge": float(args.ridge),
        "n_traces": len(traces),
        "n_train_traces": len(train_traces),
        "holdout_trace": str(holdout_path),
        "state_cols": STATE_COLS,
        "action_cols": ACTION_COLS,
        "physical_params_used": phys,
        "metrics_holdout_free_rollout": summarize(comp),
        "notes": [
            "Stable target ODE over measured physical timestep states.",
            "Uses grid command voltage as external input and measured grid/energy/regulating dq states as dynamic states.",
            "Idc_cap is currently Cdc*dVdc/dt, normalized by 500 A for model fitting.",
        ],
        "artifacts": {
            "comparison_csv": str(comp_csv),
            "figure_png": str(fig_png),
            "model_json": str(model_json),
        },
    }
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
