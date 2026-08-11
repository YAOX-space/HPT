"""Plot corrected-current-window dq/SAC boundary matrices.

This utility combines one or more ``family_specialist_comparison_rows.csv``
files produced by ``run_hpt_family_specialist_matrix``.  It separates
``strong_dq``, ``family_seed_before_sac``, and ``family_sac_after_finetune``
from the evaluator output and renders depth-duration pass/fail matrices.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import ListedColormap


def controller_label(row: pd.Series) -> str:
    mode = str(row.get("mode", ""))
    if mode == "conventional_dq":
        return "strong_dq"
    actor_archive = str(row.get("actor_archive", ""))
    if "eval_seed" in actor_archive:
        return "family_seed_before_sac"
    if "eval_sac" in actor_archive:
        return "family_sac_after_finetune"
    return mode


def load_rows(csv_paths: Iterable[Path]) -> pd.DataFrame:
    frames = []
    for priority, path in enumerate(csv_paths):
        df = pd.read_csv(path)
        df["source_csv"] = str(path)
        df["source_priority"] = priority
        df["controller_label"] = df.apply(controller_label, axis=1)
        df["duration_ms"] = (df["fault_duration_s"].astype(float) * 1000.0).round().astype(int)
        df["depth_pu"] = df["fault_pu"].astype(float).round(6)
        df["pass_int"] = df["voltage_survival_pass"].astype(int)
        frames.append(df)
    all_rows = pd.concat(frames, ignore_index=True)
    # If the same cell appears in multiple runs, keep the last path on the
    # command line.  This lets a focused recheck override an earlier probe.
    all_rows = (
        all_rows.sort_values("source_priority")
        .drop_duplicates(["controller_label", "depth_pu", "duration_ms"], keep="last")
        .reset_index(drop=True)
    )
    return all_rows


def matrix_for(df: pd.DataFrame, controller: str, metric: str) -> pd.DataFrame:
    sub = df[df["controller_label"] == controller]
    if sub.empty:
        return pd.DataFrame()
    return sub.pivot(index="depth_pu", columns="duration_ms", values=metric).sort_index(ascending=False)


def plot_pass_matrix(ax, mat: pd.DataFrame, title: str) -> None:
    depths = list(mat.index)
    durations = list(mat.columns)
    arr = mat.to_numpy(dtype=float)
    masked = np.ma.masked_invalid(arr)
    cmap = ListedColormap(["#d95f5f", "#67b567"])
    cmap.set_bad("#e6e6e6")
    ax.imshow(masked, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    ax.set_title(title)
    ax.set_xlabel("fault duration (ms)")
    ax.set_ylabel("fault depth (pu)")
    ax.set_xticks(range(len(durations)))
    ax.set_xticklabels([str(d) for d in durations])
    ax.set_yticks(range(len(depths)))
    ax.set_yticklabels([f"{d:.3g}" for d in depths])
    for i, depth in enumerate(depths):
        for j, duration in enumerate(durations):
            value = mat.loc[depth, duration]
            label = "--" if pd.isna(value) else ("P" if int(value) else "F")
            ax.text(j, i, label, ha="center", va="center", fontsize=9, color="#111111")
    ax.grid(which="both", color="white", linewidth=1.5)


def write_controller_matrix(df: pd.DataFrame, controller: str, out_dir: Path, stem: str) -> None:
    cols = [
        "controller_label",
        "depth_pu",
        "duration_ms",
        "voltage_survival_pass",
        "voltage_survival_reason",
        "control_score",
        "vdc_min",
        "vdc_max",
        "grid_current_peak_pu",
        "grid_current_peak_global_pu",
        "recovery_violation_max_pu",
        "fault_lv_band_violation_max_pu",
        "source_csv",
    ]
    present = [c for c in cols if c in df.columns]
    df[df["controller_label"] == controller][present].sort_values(
        ["depth_pu", "duration_ms"]
    ).to_csv(out_dir / f"{stem}_{controller}_cells.csv", index=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", action="append", required=True, help="family_specialist_comparison_rows.csv path")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--stem", default="currentwindow_boundary")
    parser.add_argument("--dq-title", default="strong dq")
    parser.add_argument("--seed-title", default="family seed before SAC")
    parser.add_argument("--sac-title", default="family SAC after fine-tune")
    parser.add_argument(
        "--pass-title",
        default="Corrected current-window voltage-survival boundary",
    )
    parser.add_argument("--score-title", default="Boundary score matrix")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    df = load_rows([Path(p) for p in args.csv])
    df.to_csv(out_dir / f"{args.stem}_combined_cells.csv", index=False)

    preferred_controllers = [
        "strong_dq",
        "family_seed_before_sac",
        "family_sac_after_finetune",
    ]
    available = set(df["controller_label"].dropna().astype(str))
    controllers = [name for name in preferred_controllers if name in available]
    if not controllers:
        raise RuntimeError("No recognized controller rows were found")
    title_map = {
        "strong_dq": args.dq_title,
        "family_seed_before_sac": args.seed_title,
        "family_sac_after_finetune": args.sac_title,
    }
    fig, axes = plt.subplots(
        1,
        len(controllers),
        figsize=(4.8 * len(controllers), 4.6),
        constrained_layout=True,
        squeeze=False,
    )
    axes = axes.ravel()
    for ax, controller in zip(axes, controllers):
        mat = matrix_for(df, controller, "pass_int")
        plot_pass_matrix(ax, mat, title_map[controller])
        write_controller_matrix(df, controller, out_dir, args.stem)
    fig.suptitle(args.pass_title)
    fig.savefig(out_dir / f"{args.stem}_pass_matrix.png", dpi=180)
    plt.close(fig)

    # Also plot score matrices for dq and after-SAC, because pass/fail alone can
    # hide near-boundary deterioration.
    score_controllers = [
        name for name in ["strong_dq", "family_sac_after_finetune"] if name in available
    ]
    score_matrices = {
        controller: matrix_for(df, controller, "control_score")
        for controller in score_controllers
    }
    finite_scores = np.concatenate(
        [mat.to_numpy(dtype=float).ravel() for mat in score_matrices.values()]
    )
    finite_scores = finite_scores[np.isfinite(finite_scores)]
    score_vmin = float(np.min(finite_scores))
    score_vmax = float(np.max(finite_scores))
    fig, axes = plt.subplots(
        1,
        len(score_controllers),
        figsize=(5 * len(score_controllers), 4.6),
        constrained_layout=True,
        squeeze=False,
    )
    axes = axes.ravel()
    for ax, controller in zip(axes, score_controllers):
        mat = score_matrices[controller]
        im = ax.imshow(
            mat.to_numpy(dtype=float),
            aspect="auto",
            cmap="viridis",
            vmin=score_vmin,
            vmax=score_vmax,
        )
        ax.set_title(title_map[controller])
        ax.set_xlabel("fault duration (ms)")
        ax.set_ylabel("fault depth (pu)")
        ax.set_xticks(range(len(mat.columns)))
        ax.set_xticklabels([str(d) for d in mat.columns])
        ax.set_yticks(range(len(mat.index)))
        ax.set_yticklabels([f"{d:.3g}" for d in mat.index])
        for i, depth in enumerate(mat.index):
            for j, duration in enumerate(mat.columns):
                value = mat.loc[depth, duration]
                if pd.notna(value):
                    ax.text(j, i, f"{value:.0f}", ha="center", va="center", fontsize=8, color="white")
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="score (lower is better)")
    fig.suptitle(args.score_title)
    fig.savefig(out_dir / f"{args.stem}_score_matrix.png", dpi=180)
    plt.close(fig)

    summary_rows = []
    for controller in controllers:
        sub = df[df["controller_label"] == controller]
        summary_rows.append(
            {
                "controller": controller,
                "rows": int(len(sub)),
                "pass_count": int(sub["pass_int"].sum()),
                "grid_current_pass_count": int(sub.get("gbt_grid_current_limit_pass", pd.Series(dtype=float)).sum()),
                "vdc_pass_count": int(sub.get("gbt_vdc_survive_pass", pd.Series(dtype=float)).sum()),
                "score_mean": float(sub["control_score"].mean()),
                "score_min": float(sub["control_score"].min()),
                "score_max": float(sub["control_score"].max()),
            }
        )
    pd.DataFrame(summary_rows).to_csv(out_dir / f"{args.stem}_summary.csv", index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
