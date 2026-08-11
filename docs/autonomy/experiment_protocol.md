# Experiment Protocol

## Before Running

Record:

- falsifiable hypothesis and competing explanation;
- controller, topology, fault family, and scenario split;
- strong baseline and its tuning provenance;
- evidence claim rung and success gate;
- exact command, config, expected runtime, and result directory;
- Git state and hashes of model, evaluator, actor, data, and calibration;
- random seeds and software/toolbox versions when relevant.

Use a dry-run, one-case smoke, or reduced matrix before a long campaign.
Resolve the declared topology/category/phase family through
`sac.expert_workspace`; write its checkpoint and outputs under that
expert's `models/` and `results/` directories.

## During Running

- Capture stdout/stderr and structured training diagnostics.
- Preserve unscaled reward and every reward component.
- Preserve failed runs and partial artifacts.
- Do not modify an actor, model, evaluator, or gate during the same declared
  run. Start a new run id after a behavioral change.

## After Running

1. Validate artifact completeness and hashes.
2. Compare with strong dq, initialization, ablations, and previous promoted
   actor using the same validator.
3. Report per-cell metrics, not only averages.
4. Separate proxy results from switch-level results.
5. Assign `promote`, `diagnostic`, `rerun`, `debug`, or `retire`.
6. Record one evidence-driven next action.

## Metric Sets

Voltage-survival evidence requires the declared timestep voltage envelope,
fault/recovery gates, DC-link bounds, command bounds, and the active
current-window diagnostics. Report which checks are gates and which remain
diagnostic.

Full-FRT evidence additionally requires every declared grid-current limit,
reactive-current support, recovery, DC-link, device, asymmetry, and grid-code
criterion. Missing signals or unevaluated criteria are failures of evidence,
not passes.

Read `evidence_claim_protocol.md` for the evidence passport and promotion
claim ladder.
