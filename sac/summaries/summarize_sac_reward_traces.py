"""Summarize SAC reward traces and switch-level promotion scores.

Protected SAC campaigns spawn one training run per chunk, so the raw reward
CSV files live beside the campaign directory rather than inside it.  This
utility turns those scattered traces into a standard combined CSV and a
convergence figure that can be cited in reports.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "lab" / "results"


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def _chunk_from_path(path: Path, run_name: str) -> int:
    text = str(path.parent.name)
    match = re.search(re.escape(run_name) + r"_chunk(\d+)_train", text)
    if match:
        return int(match.group(1))
    match = re.search(r"chunk(\d+)", text)
    if match:
        return int(match.group(1))
    return 0


def _find_trace_files(run_dir: Path) -> list[Path]:
    files: list[Path] = []
    direct = run_dir / "sac_training_reward_trace.csv"
    if direct.exists():
        files.append(direct)
    files.extend(sorted(run_dir.rglob("sac_training_reward_trace.csv")))
    sibling_pattern = f"{run_dir.name}_chunk*_train"
    for chunk_dir in sorted(run_dir.parent.glob(sibling_pattern)):
        trace = chunk_dir / "sac_training_reward_trace.csv"
        if trace.exists():
            files.append(trace)
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in files:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _combine_reward_traces(run_dir: Path) -> tuple[pd.DataFrame, Path]:
    rows: list[dict[str, Any]] = []
    for trace in _find_trace_files(run_dir):
        df = _read_csv(trace)
        if df.empty:
            continue
        chunk = _chunk_from_path(trace, run_dir.name)
        for idx, item in df.iterrows():
            row = item.to_dict()
            row["source_trace"] = str(trace)
            row["source_run"] = trace.parent.name
            row["chunk"] = int(chunk)
            row["episode_index_in_source"] = int(idx)
            rows.append(row)
    out_csv = run_dir / "sac_training_reward_trace_combined.csv"
    _write_csv(out_csv, rows)
    return pd.DataFrame(rows), out_csv


def _plot_reward_and_switch(
    reward_df: pd.DataFrame,
    chunks_df: pd.DataFrame,
    out_png: Path,
) -> None:
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 1, figsize=(9.2, 6.6), constrained_layout=True)

    ax = axes[0]
    if reward_df.empty:
        ax.text(0.5, 0.5, "No SAC reward trace found", ha="center", va="center")
        ax.set_axis_off()
    else:
        plot_df = reward_df.copy()
        plot_df["episode_return"] = pd.to_numeric(plot_df["episode_return"], errors="coerce")
        plot_df["global_episode"] = range(1, len(plot_df) + 1)
        ax.plot(
            plot_df["global_episode"],
            plot_df["episode_return"],
            lw=1.4,
            marker="o",
            markersize=2.8,
            color="#1f77b4",
            label="episode return",
        )
        if "chunk" in plot_df and plot_df["chunk"].max() > 0:
            chunk_mean = (
                plot_df.groupby("chunk", as_index=False)["episode_return"]
                .mean(numeric_only=True)
                .rename(columns={"episode_return": "mean_episode_return"})
            )
            x_pos = []
            for chunk in chunk_mean["chunk"]:
                sub = plot_df[plot_df["chunk"] == chunk]
                x_pos.append(float(sub["global_episode"].mean()))
            ax.plot(
                x_pos,
                chunk_mean["mean_episode_return"],
                lw=2.2,
                marker="s",
                color="#ff7f0e",
                label="chunk mean",
            )
        ax.set_title("SAC reward trace")
        ax.set_xlabel("Episode")
        ax.set_ylabel("Episode return")
        ax.grid(True, alpha=0.25)
        ax.legend(frameon=False)

    ax = axes[1]
    if chunks_df.empty or "sac_score" not in chunks_df:
        if not reward_df.empty and "envelope_violation_pu" in reward_df:
            x = pd.Series(range(1, len(reward_df) + 1))
            for col, label in (
                ("envelope_violation_pu", "envelope"),
                ("fault_lv_band_violation_pu", "fault LV band"),
                ("recovery_violation_pu", "recovery"),
            ):
                if col in reward_df:
                    ax.plot(
                        x,
                        pd.to_numeric(reward_df[col], errors="coerce"),
                        lw=1.2,
                        label=label,
                    )
            ax.set_title("Proxy-side violation trace")
            ax.set_xlabel("Episode")
            ax.set_ylabel("Violation (pu)")
            ax.grid(True, alpha=0.25)
            ax.legend(frameon=False)
        else:
            ax.text(0.5, 0.5, "No switch-level promotion CSV found", ha="center", va="center")
            ax.set_axis_off()
    else:
        chunks = chunks_df.copy()
        chunks["chunk"] = pd.to_numeric(chunks["chunk"], errors="coerce")
        chunks["sac_score"] = pd.to_numeric(chunks["sac_score"], errors="coerce")
        ax.plot(
            chunks["chunk"],
            chunks["sac_score"],
            lw=1.8,
            marker="o",
            color="#2ca02c",
            label="SAC switch-level score",
        )
        if "conventional_score" in chunks:
            conv = pd.to_numeric(chunks["conventional_score"], errors="coerce").dropna()
            if not conv.empty:
                ax.axhline(
                    float(conv.iloc[0]),
                    color="#7f7f7f",
                    linestyle="--",
                    lw=1.2,
                    label="conventional baseline",
                )
        if "sac_pass" in chunks:
            pass_mask = chunks["sac_pass"].astype(str).str.lower().isin(["true", "1", "yes"])
            ax.scatter(
                chunks.loc[pass_mask, "chunk"],
                chunks.loc[pass_mask, "sac_score"],
                s=55,
                color="#1f77b4",
                zorder=3,
                label="switch-level pass",
            )
            if (~pass_mask).any():
                ax.scatter(
                    chunks.loc[~pass_mask, "chunk"],
                    chunks.loc[~pass_mask, "sac_score"],
                    s=55,
                    color="#d62728",
                    zorder=3,
                    label="switch-level fail",
                )
        ax.set_title("Switch-level promotion trace")
        ax.set_xlabel("SAC fine-tune chunk")
        ax.set_ylabel("Control score (lower is better)")
        ax.grid(True, alpha=0.25)
        ax.legend(frameon=False)

    fig.suptitle("SAC training reward and switch-level promotion evidence", fontsize=12)
    fig.savefig(out_png, dpi=220, bbox_inches="tight")
    plt.close(fig)


def summarize_sac_reward_traces(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    reward_df, combined_csv = _combine_reward_traces(run_dir)
    chunks_csv = run_dir / "protected_sac_finetune_chunks.csv"
    chunks_df = _read_csv(chunks_csv)
    figure = run_dir / "sac_reward_and_switch_score_convergence.png"
    _plot_reward_and_switch(reward_df, chunks_df, figure)
    summary = {
        "schema": "hpt-sac-reward-trace-summary-v1",
        "run_dir": str(run_dir),
        "reward_trace_files": [str(path) for path in _find_trace_files(run_dir)],
        "combined_reward_csv": str(combined_csv),
        "reward_trace_rows": int(len(reward_df)),
        "protected_chunks_csv": str(chunks_csv) if chunks_csv.exists() else "",
        "protected_chunks_rows": int(len(chunks_df)),
        "convergence_figure": str(figure),
    }
    (run_dir / "sac_reward_trace_summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="SAC train/campaign result directory")
    args = parser.parse_args()
    print(json.dumps(summarize_sac_reward_traces(args.run_dir), indent=2))


if __name__ == "__main__":
    main()
