# Evidence And Claim Protocol

## Evidence Passport

Every promoted result or quantitative paper claim must identify:

- exact claim and evidence rung;
- run id, Git commit, and dirty status;
- MATLAB/Simulink and required product versions;
- topology model, validator, actor, dataset, and calibration paths and hashes;
- gate configuration and scenario matrix;
- train, validation, and untouched holdout split;
- baseline identity and tuning budget;
- metrics, failures, and excluded claims.

Store machine metadata with `sac/experiment_metadata.py`; put missing
passport fields in its `extra` record.

## Claim Ladder

| Rung | Evidence |
| ---: | --- |
| 0 | Proposal only |
| 1 | Proxy diagnostic |
| 2 | Held-out proxy alignment |
| 3 | Switch-level single case |
| 4 | One unchanged actor across a fault-family matrix |
| 5 | Boundary expansion, robustness, or supported superiority |
| 6 | Full FRT with every declared voltage, current, reactive-support, recovery, DC-link, and device gate |

## Proxy Alignment Layers

Report observation/unit, fixed-action response, reward/pass-fail, and
trajectory-rollout ranking alignment separately. Fixed-action correlation does
not prove trajectory ranking near hard constraints.

## Decisions

Use `promote`, `diagnostic`, `rerun`, `debug`, or `retire`. Preserve negative
results and never strengthen a manuscript claim beyond its evidence rung.

The evidence-governance ideas are adapted for HPT from ARS-Codex:
https://github.com/Imbad0202/academic-research-skills-codex. ARS may support
literature, citation, and reviewer workflows, while `hpt-research-agent`
retains authority for code modification, autonomous debugging, experiments,
and switch-level promotion.
