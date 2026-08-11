# HPT2.0 Curated Workspace

This directory was created as a clean Gate A migration from `E:\research_space\Hybrid-power-transformer`.

What is included:

- `sac`: maintained SAC/Python controller code.
- `simulink`: corrected `topology1`, `topology2`, evaluators, collectors, sweeps, and tests.
- `docs`: current autonomy state, architecture, logs, and migration notes.
- `docs/specs/algorithms/hpt-sac-controller`: SAC background, BibTeX references, and next-stage task plan.
- `tuition`: topology1 teaching model and acceptance report.
- Selected compact evidence for topology2 single-phase LVRT and proxy-2.0 diagnostics.
- Key SAC/HPT references from `references/week3`, `week5`, `week6`, `week7_full_action_sac`, `week8_family_sac`, and `week8_sac_main`.

What is intentionally not included:

- The original `.git` history.
- Python virtual environments, Simulink build cache, temporary folders.
- Full bulk archives and hundreds of unreviewed temporary actor/result files.
- `topoloty1`; only the corrected `topology1` path is kept.

Current research status:

- No SAC controller is promoted under the v3 validator.
- The active controller contract is `24-D observation / 4-D action`.
- The next step is Gate B: contract audit, then Gate C: proxy-2.0 dataset expansion.
