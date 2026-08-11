"""Prototype a timestep-level HPT proxy calibration model.

This pilot intentionally does not replace ``HPTVoltageSACEnv``.  It uses
existing switch-level trajectory CSVs to test whether a control-step transition
model is more faithful than a window-statistic proxy for transient prediction.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import RidgeCV
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TRACE_CSV = (
    ROOT
    / "lab"
    / "results"
    / "hpt_trace_aggregates"
    / "hpt_t2_ab_deep_lvrt_r6_train_traces_20260803_r1"
    / "aggregate_trace.csv"
)
DEFAULT_OUT_DIR = (
    ROOT
    / "experts"
    / "topology2_single_phase_lvrt"
    / "proxy"
    / "proxy2_transition_pilot"
)


OBS_COLS = [f"obs_{i:02d}" for i in range(1, 25)]
ACTION_COLS = [f"action_{i:02d}" for i in range(1, 5)]
FAULT_COLS = ["fault_pu", "grid_pu", "fault_a_pu", "fault_b_pu", "fault_c_pu"]
STATE_EXTRA_COLS = ["lv_pu_inst", "vdc_pu_inst"]
TARGET_COLS = STATE_EXTRA_COLS + OBS_COLS
KEY_TARGETS = ["lv_pu_inst", "vdc_pu_inst", "obs_01", "obs_04"]
LITE_STATE_COLS = ["lv_pu_inst", "vdc_pu_inst"]


def _numeric_frame(df: pd.DataFrame, cols: Iterable[str]) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for col in cols:
        out[col] = pd.to_numeric(df[col], errors="coerce")
    return out


def load_trace_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [c for c in ["trace_source", "case_name", "t", *OBS_COLS, *ACTION_COLS] if c not in df.columns]
    if missing:
        raise ValueError(f"Trace CSV is missing required columns: {missing}")
    df = df.copy()
    df["lv_pu_inst"] = pd.to_numeric(df["lv_rms_inst"], errors="coerce") / 207.0
    df["vdc_pu_inst"] = pd.to_numeric(df["vdc_inst"], errors="coerce") / 800.0
    df["t"] = pd.to_numeric(df["t"], errors="coerce")
    df = df.sort_values(["trace_source", "t"]).reset_index(drop=True)
    return df


def build_transition_table(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str], list[str]]:
    rows: list[pd.DataFrame] = []
    for _, group in df.groupby("trace_source", sort=False):
        group = group.sort_values("t").reset_index(drop=True)
        if len(group) < 2:
            continue
        cur = group.iloc[:-1].copy()
        nxt = group.iloc[1:].copy()
        trans = pd.DataFrame(index=cur.index)
        trans["trace_source"] = cur["trace_source"].to_numpy()
        trans["case_name"] = cur["case_name"].to_numpy()
        trans["t"] = cur["t"].to_numpy()
        trans["dt"] = (nxt["t"].to_numpy() - cur["t"].to_numpy()).astype(float)
        trans["window_zone"] = cur.get("window_zone", pd.Series(["unknown"] * len(cur))).to_numpy()
        trans["action_source"] = cur.get("action_source", pd.Series(["unknown"] * len(cur))).to_numpy()

        for col in FAULT_COLS + OBS_COLS + STATE_EXTRA_COLS + ACTION_COLS:
            trans[col] = pd.to_numeric(cur[col], errors="coerce").to_numpy()
        for col in TARGET_COLS:
            trans[f"next_{col}"] = pd.to_numeric(nxt[col], errors="coerce").to_numpy()
        rows.append(trans)

    if not rows:
        raise ValueError("No transitions could be built from trace CSV.")

    transitions = pd.concat(rows, ignore_index=True)
    transitions = transitions.replace([np.inf, -np.inf], np.nan).dropna()
    categorical = pd.get_dummies(transitions[["window_zone", "action_source"]], prefix=["win", "src"])
    numeric_cols = ["t", "dt", *FAULT_COLS, *OBS_COLS, *STATE_EXTRA_COLS, *ACTION_COLS]
    feature_df = pd.concat([_numeric_frame(transitions, numeric_cols), categorical], axis=1)
    target_cols = [f"next_{c}" for c in TARGET_COLS]
    transitions = pd.concat(
        [
            transitions[["trace_source", "case_name", "t", "window_zone"]],
            feature_df.add_prefix("x__"),
            _numeric_frame(transitions, target_cols),
        ],
        axis=1,
    ).dropna()
    feature_cols = [c for c in transitions.columns if c.startswith("x__")]
    return transitions, feature_cols, target_cols


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(mean_squared_error(y_true, y_pred)))


def current_state_matrix(transitions: pd.DataFrame) -> np.ndarray:
    return transitions[[f"x__{c}" for c in TARGET_COLS]].to_numpy(dtype=float)


def target_matrix(transitions: pd.DataFrame, target_cols: list[str]) -> np.ndarray:
    return transitions[target_cols].to_numpy(dtype=float)


def apply_delta_and_clip(
    current: np.ndarray,
    delta: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
) -> np.ndarray:
    return np.clip(current + delta, lower, upper)


def one_step_metrics(
    transitions: pd.DataFrame,
    feature_cols: list[str],
    target_cols: list[str],
    model: Pipeline,
    test_mask: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
) -> list[dict[str, object]]:
    x_test = transitions.loc[test_mask, feature_cols].to_numpy(dtype=float)
    y_test = target_matrix(transitions.loc[test_mask], target_cols)
    x_now = current_state_matrix(transitions.loc[test_mask])
    y_pred = apply_delta_and_clip(x_now, model.predict(x_test), lower, upper)

    # Oracle window baseline: constant value per held-out case/window.  This is
    # intentionally generous to the window-statistic approach.
    y_window = np.zeros_like(y_test)
    test_rows = transitions.loc[test_mask, ["trace_source", "window_zone", *target_cols]].copy()
    for (_, _), idx in test_rows.groupby(["trace_source", "window_zone"]).groups.items():
        y_window[test_rows.index.get_indexer(idx)] = test_rows.loc[idx, target_cols].mean().to_numpy()

    rows: list[dict[str, object]] = []
    for label, pred in {
        "proxy2_transition": y_pred,
        "persistence": x_now,
        "oracle_window_mean": y_window,
    }.items():
        rows.append(
            {
                "model": label,
                "target": "all_targets",
                "rmse": rmse(y_test, pred),
                "mae": float(mean_absolute_error(y_test, pred)),
            }
        )
        for target in KEY_TARGETS:
            col = target_cols.index(f"next_{target}")
            rows.append(
                {
                    "model": label,
                    "target": target,
                    "rmse": rmse(y_test[:, col], pred[:, col]),
                    "mae": float(mean_absolute_error(y_test[:, col], pred[:, col])),
                }
            )
    return rows


def rollout_case(
    transitions: pd.DataFrame,
    feature_cols: list[str],
    target_cols: list[str],
    model: Pipeline,
    trace_source: str,
    bounds: dict[str, tuple[float, float]],
) -> pd.DataFrame:
    case = transitions[transitions["trace_source"] == trace_source].sort_values("t").copy()
    if case.empty:
        raise ValueError(f"Missing trace_source {trace_source}")

    pred_state = case.iloc[0][[f"x__{c}" for c in TARGET_COLS]].astype(float).copy()
    lower = np.asarray([bounds[name][0] for name in TARGET_COLS], dtype=float)
    upper = np.asarray([bounds[name][1] for name in TARGET_COLS], dtype=float)
    records: list[dict[str, float | str]] = []
    for _, row in case.iterrows():
        features = row[feature_cols].astype(float).copy()
        for x_col in [f"x__{name}" for name in TARGET_COLS]:
            features[x_col] = pred_state[x_col]
        delta = model.predict(features.to_numpy(dtype=float).reshape(1, -1))[0]
        y_next = apply_delta_and_clip(pred_state.to_numpy(dtype=float), delta, lower, upper)
        pred_next = dict(zip(target_cols, y_next))
        actual_next = row[target_cols].astype(float)
        rec: dict[str, float | str] = {
            "trace_source": trace_source,
            "case_name": str(row["case_name"]),
            "t": float(row["t"]),
        }
        for key in KEY_TARGETS:
            rec[f"actual_{key}"] = float(actual_next[f"next_{key}"])
            rec[f"pred_{key}"] = float(pred_next[f"next_{key}"])
            rec[f"err_{key}"] = float(pred_next[f"next_{key}"] - actual_next[f"next_{key}"])
        records.append(rec)
        for name in TARGET_COLS:
            pred_state[f"x__{name}"] = pred_next[f"next_{name}"]
    return pd.DataFrame.from_records(records)


def plot_rollout(rollout: pd.DataFrame, out_path: Path) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
    for ax, key, ylabel in [
        (axes[0], "lv_pu_inst", "LV pu"),
        (axes[1], "vdc_pu_inst", "DC-link pu"),
    ]:
        ax.plot(rollout["t"], rollout[f"actual_{key}"], label="switch-level trace", linewidth=2)
        ax.plot(rollout["t"], rollout[f"pred_{key}"], label="proxy2 rollout", linestyle="--")
        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.3)
    axes[1].set_xlabel("time [s]")
    axes[0].legend(loc="best")
    fig.tight_layout()
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def run_lite_proxy2(df: pd.DataFrame, out_dir: Path, holdout_trace: str) -> dict[str, object]:
    """Train a small two-state transition proxy for LV and DC-link only."""

    rows: list[pd.DataFrame] = []
    for _, group in df.groupby("trace_source", sort=False):
        group = group.sort_values("t").reset_index(drop=True)
        if len(group) < 2:
            continue
        cur = group.iloc[:-1].copy()
        nxt = group.iloc[1:].copy()
        trans = pd.DataFrame(
            {
                "trace_source": cur["trace_source"],
                "case_name": cur["case_name"],
                "t": cur["t"],
                "dt": nxt["t"].to_numpy() - cur["t"].to_numpy(),
                "window_zone": cur["window_zone"],
            }
        )
        for col in FAULT_COLS + LITE_STATE_COLS + ACTION_COLS:
            trans[col] = pd.to_numeric(cur[col], errors="coerce").to_numpy()
        for col in LITE_STATE_COLS:
            trans[f"next_{col}"] = pd.to_numeric(nxt[col], errors="coerce").to_numpy()
        rows.append(trans)

    trans = pd.concat(rows, ignore_index=True).replace([np.inf, -np.inf], np.nan).dropna()
    categorical = pd.get_dummies(trans[["window_zone"]], prefix=["win"])
    base_features = ["t", "dt", *FAULT_COLS, *LITE_STATE_COLS, *ACTION_COLS]
    x_df = pd.concat([_numeric_frame(trans, base_features), categorical], axis=1)
    target_cols = [f"next_{c}" for c in LITE_STATE_COLS]
    train_mask = trans["trace_source"] != holdout_trace
    test_mask = ~train_mask

    x_train = x_df.loc[train_mask].to_numpy(dtype=float)
    current_train = trans.loc[train_mask, LITE_STATE_COLS].to_numpy(dtype=float)
    y_train_abs = trans.loc[train_mask, target_cols].to_numpy(dtype=float)
    y_train_delta = y_train_abs - current_train

    model = Pipeline(
        [
            ("scale", StandardScaler()),
            ("ridge", RidgeCV(alphas=np.logspace(-5, 3, 13))),
        ]
    )
    model.fit(x_train, y_train_delta)

    train_abs = np.vstack([current_train, y_train_abs])
    margin = 0.10 * np.maximum(np.ptp(train_abs, axis=0), 1e-6)
    lower = np.min(train_abs, axis=0) - margin
    upper = np.max(train_abs, axis=0) + margin

    x_test = x_df.loc[test_mask].to_numpy(dtype=float)
    current_test = trans.loc[test_mask, LITE_STATE_COLS].to_numpy(dtype=float)
    y_test = trans.loc[test_mask, target_cols].to_numpy(dtype=float)
    y_pred = apply_delta_and_clip(current_test, model.predict(x_test), lower, upper)

    metric_rows = []
    for label, pred in {"proxy2_lite": y_pred, "persistence": current_test}.items():
        for i, target in enumerate(LITE_STATE_COLS):
            metric_rows.append(
                {
                    "model": label,
                    "target": target,
                    "rmse": rmse(y_test[:, i], pred[:, i]),
                    "mae": float(mean_absolute_error(y_test[:, i], pred[:, i])),
                }
            )

    case = trans[test_mask].sort_values("t").copy()
    pred_state = case.iloc[0][LITE_STATE_COLS].astype(float).to_numpy()
    rollout_rows = []
    for idx, row in case.iterrows():
        feat = x_df.loc[[idx]].copy()
        for state_col, value in zip(LITE_STATE_COLS, pred_state):
            feat[state_col] = value
        pred_state = apply_delta_and_clip(
            pred_state,
            model.predict(feat.to_numpy(dtype=float))[0],
            lower,
            upper,
        )
        rec = {"trace_source": holdout_trace, "case_name": str(row["case_name"]), "t": float(row["t"])}
        for i, key in enumerate(LITE_STATE_COLS):
            actual = float(row[f"next_{key}"])
            rec[f"actual_{key}"] = actual
            rec[f"pred_{key}"] = float(pred_state[i])
            rec[f"err_{key}"] = float(pred_state[i] - actual)
        rollout_rows.append(rec)

    rollout = pd.DataFrame.from_records(rollout_rows)
    rollout_metric_rows = []
    for key in LITE_STATE_COLS:
        rollout_metric_rows.append(
            {
                "model": "proxy2_lite_autoregressive",
                "target": key,
                "rmse": rmse(rollout[f"actual_{key}"].to_numpy(), rollout[f"pred_{key}"].to_numpy()),
                "mae": float(
                    mean_absolute_error(
                        rollout[f"actual_{key}"].to_numpy(),
                        rollout[f"pred_{key}"].to_numpy(),
                    )
                ),
            }
        )

    metrics_df = pd.DataFrame(metric_rows)
    rollout_metrics_df = pd.DataFrame(rollout_metric_rows)
    metrics_df.to_csv(out_dir / "proxy2_lite_one_step_metrics.csv", index=False)
    rollout_metrics_df.to_csv(out_dir / "proxy2_lite_rollout_metrics.csv", index=False)
    rollout.to_csv(out_dir / "proxy2_lite_holdout_rollout.csv", index=False)
    plot_rollout(rollout, out_dir / "proxy2_lite_holdout_rollout.png")
    joblib.dump(
        {
            "model": model,
            "feature_cols": list(x_df.columns),
            "target_cols": target_cols,
            "state_cols": LITE_STATE_COLS,
            "target_mode": "delta_plus_train_range_clip",
            "schema": "hpt-proxy2-lite-transition-pilot-v1",
        },
        out_dir / "proxy2_lite_transition_model.joblib",
    )
    return {
        "one_step_metrics_csv": str(out_dir / "proxy2_lite_one_step_metrics.csv"),
        "rollout_metrics_csv": str(out_dir / "proxy2_lite_rollout_metrics.csv"),
        "rollout_csv": str(out_dir / "proxy2_lite_holdout_rollout.csv"),
        "rollout_plot": str(out_dir / "proxy2_lite_holdout_rollout.png"),
        "model_path": str(out_dir / "proxy2_lite_transition_model.joblib"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-csv", type=Path, default=DEFAULT_TRACE_CSV)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--holdout-index", type=int, default=-1)
    args = parser.parse_args()

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    df = load_trace_csv(args.trace_csv)
    transitions, feature_cols, target_cols = build_transition_table(df)
    trace_sources = sorted(transitions["trace_source"].unique())
    if len(trace_sources) < 2:
        raise ValueError("Need at least two traces for train/holdout validation.")
    holdout = trace_sources[args.holdout_index]
    test_mask = (transitions["trace_source"] == holdout).to_numpy()
    train_mask = ~test_mask

    x_train = transitions.loc[train_mask, feature_cols].to_numpy(dtype=float)
    current_train = current_state_matrix(transitions.loc[train_mask])
    y_train_abs = target_matrix(transitions.loc[train_mask], target_cols)
    y_train_delta = y_train_abs - current_train
    model = Pipeline(
        [
            ("scale", StandardScaler()),
            ("ridge", RidgeCV(alphas=np.logspace(-5, 3, 13))),
        ]
    )
    model.fit(x_train, y_train_delta)

    train_abs = np.vstack([current_train, y_train_abs])
    margin = 0.10 * np.maximum(np.ptp(train_abs, axis=0), 1e-6)
    lower = np.min(train_abs, axis=0) - margin
    upper = np.max(train_abs, axis=0) + margin
    bounds = {name: (float(lower[i]), float(upper[i])) for i, name in enumerate(TARGET_COLS)}

    metrics = one_step_metrics(transitions, feature_cols, target_cols, model, test_mask, lower, upper)
    metrics_df = pd.DataFrame(metrics)
    rollout = rollout_case(transitions, feature_cols, target_cols, model, holdout, bounds)
    rollout_metrics = []
    for key in KEY_TARGETS:
        rollout_metrics.append(
            {
                "model": "proxy2_transition_autoregressive",
                "target": key,
                "rmse": rmse(rollout[f"actual_{key}"].to_numpy(), rollout[f"pred_{key}"].to_numpy()),
                "mae": float(
                    mean_absolute_error(
                        rollout[f"actual_{key}"].to_numpy(),
                        rollout[f"pred_{key}"].to_numpy(),
                    )
                ),
            }
        )
    rollout_metrics_df = pd.DataFrame(rollout_metrics)

    transitions.to_csv(out_dir / "proxy2_transition_dataset.csv", index=False)
    metrics_df.to_csv(out_dir / "proxy2_one_step_metrics.csv", index=False)
    rollout.to_csv(out_dir / "proxy2_holdout_rollout.csv", index=False)
    rollout_metrics_df.to_csv(out_dir / "proxy2_rollout_metrics.csv", index=False)
    joblib.dump(
        {
            "model": model,
            "feature_cols": feature_cols,
            "target_cols": target_cols,
            "target_mode": "delta_plus_train_range_clip",
            "bounds": bounds,
            "schema": "hpt-proxy2-transition-pilot-v1",
        },
        out_dir / "proxy2_transition_model.joblib",
    )
    plot_rollout(rollout, out_dir / "proxy2_holdout_rollout.png")
    lite_summary = run_lite_proxy2(df, out_dir, holdout)

    summary = {
        "schema": "hpt-proxy2-transition-pilot-summary-v1",
        "trace_csv": str(args.trace_csv),
        "out_dir": str(out_dir),
        "num_source_rows": int(len(df)),
        "num_transitions": int(len(transitions)),
        "num_traces": int(len(trace_sources)),
        "train_traces": int(len(trace_sources) - 1),
        "holdout_trace": holdout,
        "train_transitions": int(train_mask.sum()),
        "holdout_transitions": int(test_mask.sum()),
        "feature_dim": int(len(feature_cols)),
        "target_dim": int(len(target_cols)),
        "one_step_metrics_csv": str(out_dir / "proxy2_one_step_metrics.csv"),
        "rollout_metrics_csv": str(out_dir / "proxy2_rollout_metrics.csv"),
        "rollout_csv": str(out_dir / "proxy2_holdout_rollout.csv"),
        "rollout_plot": str(out_dir / "proxy2_holdout_rollout.png"),
        "model_path": str(out_dir / "proxy2_transition_model.joblib"),
        "lite_proxy2": lite_summary,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
