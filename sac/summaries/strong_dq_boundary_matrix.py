"""Summarize a strong-dq family boundary scan as analysis-matrix artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle
from matplotlib.colors import ListedColormap


DEFAULT_RUN_DIR = Path(
    r"E:\research_space\Hybrid-power-transformer\experts"
    r"\topology2_single_phase_lvrt\results\v3_t2sp105_deep_dq_boundary_r1"
)


def truthy(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "pass", "passed"})


def first_existing_column(frame: pd.DataFrame, names: list[str]) -> str:
    for name in names:
        if name in frame.columns:
            return name
    raise KeyError(f"None of these columns exist: {names}")


def make_cell_table(rows: pd.DataFrame) -> pd.DataFrame:
    l1_col = first_existing_column(rows, ["l1_load_voltage_survival_pass", "voltage_survival_pass"])
    l2_col = first_existing_column(rows, ["l2_grid_code_ride_through_pass", "gbt_certifiable"])
    l3_col = first_existing_column(rows, ["l3_full_frt_pass", "full_frt_pass"])

    out = pd.DataFrame(
        {
            "phase": rows["fault_phase_key"].astype(str),
            "fault_pu": pd.to_numeric(rows["family_fault_pu"], errors="coerce"),
            "duration_ms": pd.to_numeric(rows["family_duration_ms"], errors="coerce").astype("Int64"),
            "l1_pass": truthy(rows[l1_col]),
            "l2_pass": truthy(rows[l2_col]),
            "l3_pass": truthy(rows[l3_col]),
            "envelope_pass": truthy(rows["gbt_voltage_envelope_pass"]),
            "recovery_pass": truthy(rows["gbt_recover_pass"]),
            "vdc_pass": truthy(rows["gbt_vdc_survive_pass"]),
            "grid_current_pass": truthy(rows["gbt_grid_current_limit_pass"]),
            "vdc_min_pu": pd.to_numeric(rows["gbt_vdc_pu_min"], errors="coerce"),
            "vdc_max_pu": pd.to_numeric(rows["gbt_vdc_pu_max"], errors="coerce"),
            "grid_current_peak_pu": pd.to_numeric(rows["grid_current_peak_pu"], errors="coerce"),
            "load_quality_violation_max_pu": pd.to_numeric(
                rows["load_quality_violation_max_pu"], errors="coerce"
            ),
            "recovery_violation_max_pu": pd.to_numeric(
                rows["recovery_violation_max_pu"], errors="coerce"
            ),
            "control_score": pd.to_numeric(rows["control_score"], errors="coerce"),
            "l1_reason": rows.get("l1_reason", ""),
            "l2_reason": rows.get("l2_reason", ""),
            "l3_reason": rows.get("l3_reason", ""),
            "source_csv": rows.get("source_csv", ""),
        }
    )
    return out.sort_values(["phase", "fault_pu", "duration_ms"]).reset_index(drop=True)


def collapse_duplicate_cells(cell_table: pd.DataFrame) -> pd.DataFrame:
    bool_cols = [
        "l1_pass",
        "l2_pass",
        "l3_pass",
        "envelope_pass",
        "recovery_pass",
        "vdc_pass",
        "grid_current_pass",
    ]
    agg = {col: "max" for col in bool_cols}
    agg.update(
        {
            "vdc_min_pu": "min",
            "vdc_max_pu": "max",
            "grid_current_peak_pu": "max",
            "load_quality_violation_max_pu": "max",
            "recovery_violation_max_pu": "max",
            "control_score": "min",
            "l1_reason": "first",
            "l2_reason": "first",
            "l3_reason": "first",
            "source_csv": "first",
        }
    )
    collapsed = (
        cell_table.groupby(["phase", "fault_pu", "duration_ms"], as_index=False)
        .agg(agg)
        .sort_values(["phase", "fault_pu", "duration_ms"])
        .reset_index(drop=True)
    )
    for col in bool_cols:
        collapsed[col] = collapsed[col].astype(bool)
    return collapsed


def write_pass_matrix(cell_table: pd.DataFrame, out_csv: Path) -> pd.DataFrame:
    matrix = cell_table.pivot_table(
        index=["phase", "fault_pu"],
        columns="duration_ms",
        values="l1_pass",
        aggfunc="max",
    )
    matrix = matrix.applymap(lambda value: "" if pd.isna(value) else int(bool(value))).reset_index()
    matrix.columns = [
        f"d{int(col)}ms" if isinstance(col, (int, np.integer)) else str(col)
        for col in matrix.columns
    ]
    matrix.to_csv(out_csv, index=False)
    return matrix


def write_boundary_tables(cell_table: pd.DataFrame, out_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    phase_duration_rows = []
    for (phase, duration), group in cell_table.groupby(["phase", "duration_ms"], sort=True):
        passing = group[group["l1_pass"]]
        phase_duration_rows.append(
            {
                "phase": phase,
                "duration_ms": int(duration),
                "tested_fault_pu_min": float(group["fault_pu"].min()),
                "tested_fault_pu_max": float(group["fault_pu"].max()),
                "deepest_l1_pass_pu": float(passing["fault_pu"].min()) if not passing.empty else np.nan,
                "l1_pass_count": int(passing.shape[0]),
                "tested_count": int(group.shape[0]),
            }
        )
    phase_duration = pd.DataFrame(phase_duration_rows)
    phase_duration.to_csv(out_dir / "strong_dq_boundary_by_phase_duration.csv", index=False)

    phase_depth_rows = []
    for (phase, fault_pu), group in cell_table.groupby(["phase", "fault_pu"], sort=True):
        passing = group[group["l1_pass"]]
        phase_depth_rows.append(
            {
                "phase": phase,
                "fault_pu": float(fault_pu),
                "max_l1_pass_duration_ms": int(passing["duration_ms"].max()) if not passing.empty else np.nan,
                "l1_pass_count": int(passing.shape[0]),
                "tested_count": int(group.shape[0]),
            }
        )
    phase_depth = pd.DataFrame(phase_depth_rows)
    phase_depth.to_csv(out_dir / "strong_dq_boundary_by_phase_depth.csv", index=False)
    return phase_duration, phase_depth


def draw_heatmap(cell_table: pd.DataFrame, out_png: Path) -> None:
    phases = list(cell_table["phase"].drop_duplicates())
    durations = sorted(int(v) for v in cell_table["duration_ms"].dropna().unique())
    depths = sorted((float(v) for v in cell_table["fault_pu"].dropna().unique()), reverse=True)

    cmap = ListedColormap(["#b00030", "#08783f"])
    cmap.set_bad("#d8d8d8")
    fig, axes = plt.subplots(1, len(phases), figsize=(4.2 * len(phases), 4.4), squeeze=False)
    for ax, phase in zip(axes[0], phases):
        phase_rows = cell_table[cell_table["phase"] == phase]
        grid = np.full((len(depths), len(durations)), np.nan)
        for i, depth in enumerate(depths):
            for j, duration in enumerate(durations):
                match = phase_rows[
                    (np.isclose(phase_rows["fault_pu"], depth))
                    & (phase_rows["duration_ms"].astype(int) == duration)
                ]
                if not match.empty:
                    grid[i, j] = 1.0 if bool(match.iloc[0]["l1_pass"]) else 0.0
        ax.imshow(np.ma.masked_invalid(grid), cmap=cmap, vmin=0, vmax=1, aspect="auto")
        ax.set_title(f"Phase {phase.upper()}")
        ax.set_xticks(range(len(durations)))
        ax.set_xticklabels([str(v) for v in durations], rotation=45)
        ax.set_yticks(range(len(depths)))
        ax.set_yticklabels([f"{v:.3g}" for v in depths])
        ax.set_xlabel("Duration (ms)")
        ax.set_ylabel("Fault voltage (pu)")
        for i in range(len(depths)):
            for j in range(len(durations)):
                value = grid[i, j]
                if np.isnan(value):
                    label = "N/T"
                    color = "black"
                else:
                    label = "PASS" if value == 1.0 else "FAIL"
                    color = "black" if value == 1.0 else "white"
                ax.text(j, i, label, ha="center", va="center", fontsize=8, color=color)
    fig.suptitle("Strong-dq Baseline L1 Boundary Matrix", fontsize=13)
    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def draw_oriented_boundary(cell_table: pd.DataFrame, out_png: Path) -> None:
    phases = list(cell_table["phase"].drop_duplicates())
    durations = sorted(int(v) for v in cell_table["duration_ms"].dropna().unique())
    depths = sorted((float(v) for v in cell_table["fault_pu"].dropna().unique()), reverse=True)

    cmap = ListedColormap(["#b00030", "#08783f"])
    cmap.set_bad("#d8d8d8")
    fig, axes = plt.subplots(1, len(phases), figsize=(4.5 * len(phases), 4.8), squeeze=False)
    for ax, phase in zip(axes[0], phases):
        phase_rows = cell_table[cell_table["phase"] == phase]
        grid = np.full((len(depths), len(durations)), np.nan)
        for i, depth in enumerate(depths):
            for j, duration in enumerate(durations):
                match = phase_rows[
                    (np.isclose(phase_rows["fault_pu"], depth))
                    & (phase_rows["duration_ms"].astype(int) == duration)
                ]
                if not match.empty:
                    grid[i, j] = 1.0 if bool(match.iloc[0]["l1_pass"]) else 0.0

        ax.imshow(np.ma.masked_invalid(grid), cmap=cmap, vmin=0, vmax=1, aspect="auto")
        ax.set_title(f"Phase {phase.upper()}", fontsize=12)
        ax.set_xticks(range(len(durations)))
        ax.set_xticklabels([str(v) for v in durations], rotation=0)
        ax.set_yticks(range(len(depths)))
        ax.set_yticklabels([f"{v:.3g}" for v in depths])
        ax.set_xlabel("Fault duration (ms)\nshorter  <-        ->  longer", fontsize=10)
        ax.set_ylabel("Fault voltage (pu)\nshallower up / deeper down", fontsize=10)

        for i in range(len(depths)):
            for j in range(len(durations)):
                value = grid[i, j]
                if np.isnan(value):
                    label = "N/T"
                    color = "black"
                else:
                    label = "PASS" if value == 1.0 else "FAIL"
                    color = "black" if value == 1.0 else "white"
                ax.text(j, i, label, ha="center", va="center", fontsize=8, color=color, weight="bold")
                if value == 1.0:
                    ax.add_patch(Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False, lw=2.8, ec="black"))

    fig.suptitle(
        "Strong-dq Baseline: Observed L1 Boundary\n"
        "Left = shorter fault duration; Up = shallower fault voltage",
        fontsize=14,
    )
    fig.tight_layout()
    fig.savefig(out_png, dpi=200)
    plt.close(fig)


def write_report(
    out_md: Path,
    *,
    run_dir: Path,
    cell_table: pd.DataFrame,
    phase_duration: pd.DataFrame,
    phase_depth: pd.DataFrame,
) -> None:
    pass_rows = cell_table[cell_table["l1_pass"]]
    lines = [
        "# Strong-dq Baseline Boundary Matrix",
        "",
        f"Source run: `{run_dir}`",
        "",
        f"Cells tested: {len(cell_table)}",
        f"L1 pass cells: {int(cell_table['l1_pass'].sum())}",
        f"L2 pass cells: {int(cell_table['l2_pass'].sum())}",
        f"L3 pass cells: {int(cell_table['l3_pass'].sum())}",
        "",
        "## L1 Passing Cells",
        "",
    ]
    if pass_rows.empty:
        lines.append("No L1 passing cells were found.")
    else:
        lines.append("| Phase | Fault pu | Duration ms | Vdc min pu | Grid current peak pu |")
        lines.append("|---|---:|---:|---:|---:|")
        for _, row in pass_rows.sort_values(["phase", "fault_pu", "duration_ms"]).iterrows():
            lines.append(
                "| {phase} | {fault_pu:.3g} | {duration_ms} | {vdc_min_pu:.3f} | {grid_current_peak_pu:.3f} |".format(
                    **row
                )
            )
    lines.extend(
        [
            "",
            "## Boundary Reading",
            "",
            "For LVRT, lower fault pu is more severe. The deepest passing pu is therefore the smallest tested pu that still passes L1.",
            "",
        ]
    )
    lines.append("| Phase | Duration ms | Deepest L1 pass pu |")
    lines.append("|---|---:|---:|")
    for _, row in phase_duration.sort_values(["phase", "duration_ms"]).iterrows():
        value = row["deepest_l1_pass_pu"]
        value_txt = "" if pd.isna(value) else f"{value:.3g}"
        lines.append(f"| {row['phase']} | {int(row['duration_ms'])} | {value_txt} |")
    lines.extend(
        [
            "",
            "## Maximum Passing Duration",
            "",
            "| Phase | Fault pu | Max L1 pass duration ms |",
            "|---|---:|---:|",
        ]
    )
    for _, row in phase_depth.sort_values(["phase", "fault_pu"]).iterrows():
        value = row["max_l1_pass_duration_ms"]
        value_txt = "" if pd.isna(value) else str(int(value))
        lines.append(f"| {row['phase']} | {row['fault_pu']:.3g} | {value_txt} |")
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--rows-csv", type=Path, nargs="*", default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    run_dir = args.run_dir
    row_csvs = args.rows_csv or [run_dir / "strong_dq_family_rows.csv"]
    out_dir = args.out_dir or run_dir / "analysis_matrix"
    out_dir.mkdir(parents=True, exist_ok=True)

    row_frames = []
    for rows_csv in row_csvs:
        frame = pd.read_csv(rows_csv)
        frame["analysis_source_rows_csv"] = str(rows_csv)
        row_frames.append(frame)
    rows = pd.concat(row_frames, ignore_index=True)
    cell_table = collapse_duplicate_cells(make_cell_table(rows))
    cell_csv = out_dir / "strong_dq_boundary_cells.csv"
    matrix_csv = out_dir / "strong_dq_l1_pass_matrix.csv"
    heatmap_png = out_dir / "strong_dq_l1_pass_matrix.png"
    oriented_png = out_dir / "strong_dq_l1_boundary_oriented.png"
    summary_json = out_dir / "strong_dq_boundary_summary.json"
    report_md = out_dir / "REPORT.md"

    cell_table.to_csv(cell_csv, index=False)
    matrix = write_pass_matrix(cell_table, matrix_csv)
    phase_duration, phase_depth = write_boundary_tables(cell_table, out_dir)
    draw_heatmap(cell_table, heatmap_png)
    draw_oriented_boundary(cell_table, oriented_png)
    phase_a_png = out_dir / "strong_dq_l1_boundary_phase_a.png"
    draw_oriented_boundary(cell_table[cell_table["phase"] == "a"].copy(), phase_a_png)
    write_report(
        report_md,
        run_dir=run_dir,
        cell_table=cell_table,
        phase_duration=phase_duration,
        phase_depth=phase_depth,
    )

    summary = {
        "schema": "hpt-strong-dq-boundary-analysis-matrix-v1",
        "source_rows_csv": [str(path) for path in row_csvs],
        "out_dir": str(out_dir),
        "cells": int(len(cell_table)),
        "phases": sorted(cell_table["phase"].dropna().unique().tolist()),
        "fault_pu": sorted(float(v) for v in cell_table["fault_pu"].dropna().unique()),
        "durations_ms": sorted(int(v) for v in cell_table["duration_ms"].dropna().unique()),
        "l1_pass_count": int(cell_table["l1_pass"].sum()),
        "l2_pass_count": int(cell_table["l2_pass"].sum()),
        "l3_pass_count": int(cell_table["l3_pass"].sum()),
        "deepest_l1_pass_pu_overall": (
            float(cell_table.loc[cell_table["l1_pass"], "fault_pu"].min())
            if bool(cell_table["l1_pass"].any())
            else None
        ),
        "max_l1_pass_duration_ms_overall": (
            int(cell_table.loc[cell_table["l1_pass"], "duration_ms"].max())
            if bool(cell_table["l1_pass"].any())
            else None
        ),
        "artifacts": {
            "cells_csv": str(cell_csv),
            "l1_pass_matrix_csv": str(matrix_csv),
            "boundary_by_phase_duration_csv": str(out_dir / "strong_dq_boundary_by_phase_duration.csv"),
            "boundary_by_phase_depth_csv": str(out_dir / "strong_dq_boundary_by_phase_depth.csv"),
            "heatmap_png": str(heatmap_png),
            "oriented_boundary_png": str(oriented_png),
            "phase_a_boundary_png": str(phase_a_png),
            "report_md": str(report_md),
        },
    }
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(matrix.to_string(index=False))


if __name__ == "__main__":
    main()
