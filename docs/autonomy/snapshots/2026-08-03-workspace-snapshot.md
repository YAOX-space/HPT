# HPT Research Workspace Snapshot - 2026-08-03

## Purpose

This snapshot records the accumulated HPT FRT research workspace before the
next result-consolidation phase. It is a work-in-progress preservation point,
not a promoted scientific baseline or a full-FRT claim.

## Git scope

- Branch at snapshot start: `research/hpt-autonomy-skill`
- Previous HEAD: `40ba297` (`Add HPT autonomy research baseline`)
- Included: source code, tests, MATLAB/Simulink models and entry points,
  experiment manifests, compact datasets, accepted actor artifacts, paper
  sources and figures, research plans/logs, and literature PDFs.
- Included as current key evidence: the accepted topology2 A-phase LVRT r6
  actor and its fresh 10-by-6 switch-level comparison package.
- Excluded: virtual environments, Simulink build caches, extracted text,
  LaTeX auxiliary files, and bulk raw/generated experiment payloads already
  covered by `.gitignore`.

## Large local evidence inventory

The following directories remain local because placing their complete payload
in ordinary Git would make the repository impractical to clone and push:

| Directory | Files | Approximate size |
| --- | ---: | ---: |
| `data/` | 3,519 | 7.38 GB |
| `data/` | 145 | 120.2 MB |
| `lab/results/` | 39,131 | 8.44 GB |
| `tmp/` | 60 | 14.7 MB |
| `slprj/` | 51 | 1.1 MB |

These locations are not silently treated as remotely backed up. Compact
manifests, reports, comparison tables, figures, and the currently accepted
actor are committed so that scientific claims remain auditable. Complete raw
payload backup requires a separate artifact store or Git LFS repository with
adequate quota.

## Current accepted evidence

- Actor: `data/models/hpt_t2_a_lvrt_joint_support_family_sac_r6_20260803.zip`
- Actor SHA-256:
  `44dadac630f30d72555ae5ed363301296ac6b1ed2cd6201bfb1043ae1299cde5`
- Fresh switch-level run:
  `lab/results/hpt_family_specialist_t2_a_lvrt_r6_square60_currentwindow_20260803_r1`
- Matrix: topology2 A-phase LVRT, 10 depths by 6 durations, 60 paired cases.
- Result: r6 `46/60`, strong dq `48/60`; r6 has three local dq-fail/SAC-pass
  cells and lower control score in `45/60` cells.
- Claim boundary: switch-level voltage survival only; not full FRT.

## Restoration note

The Git commit containing this file is the canonical code/document snapshot.
The experiment report and comparison CSV record the hashes of the accepted
actor and Simulink model. Historical raw outputs remain preserved on the local
workspace and should be copied to a dedicated artifact archive before any
local cleanup.
