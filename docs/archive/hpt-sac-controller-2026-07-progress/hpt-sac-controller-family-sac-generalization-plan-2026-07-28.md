# HPT Family-Level SAC Generalization Plan

Date: 2026-07-28

## Objective

Move from single-case specialists to a family-level SAC controller.  The 12
validated representative actors are no longer the final training target; they
serve as safe seeds, regression gates, and teacher-trace sources.  The next
claim to prove is:

> DAgger/trajectory warm-start provides a safe initial policy, while
> behavior-constrained SAC improves generalization across a fault family and
> preserves switch-level voltage-survival.

The first family target is `topology2_LVRT_family_SAC`, because topology2 LVRT
is the clearest setting where recovery dynamics, DC-link behavior, and
unbalanced cases stress the current single-case design.

## Current Evidence Baseline

The repaired 12-case representative matrix is:

- Manifest:
  `sac/experiments/stage6_recheck_manifest_current12_repaired_sac_20260728.csv`
- Switch-level result:
  `lab/results/hpt_stage6_recheck_current12_repaired_sac_20260728/accepted_specialist_validation.csv`
- Result:
  12 / 12 voltage-survival pass,
  12 / 12 beat conventional,
  0 / 12 full FRT pass.

This is a representative single-case matrix, not a family-level controller.

## Family Training Distribution

Start with topology2 LVRT only.

Training scenarios:

- topology: `topology2`
- category: `LVRT`
- fault depths: `0.85`, `0.90`, `0.95` pu
- durations: `40`, `60`, `80`, `120` ms
- phase modes:
  - balanced: `sym3ph`
  - A-phase: `1ph_g`
  - AB-phase: `2ph`

This gives 36 proxy scenarios.  The initial actor should be one of the
validated topology2 LVRT actors, preferably the strongest dynamic seed from:

- `t2_balanced_lvrt`
- `t2_a_lvrt`
- `t2_ab_lvrt`

The first run starts from the newest repaired AB-LVRT SAC actor because it is
state-feedback, recovery-aware, and already has SAC fine-tuning evidence.

## Holdout / Promotion Matrix

Holdout cases should not be identical to the training points:

- depth: `0.875`, `0.925` pu
- duration: `100` ms
- phase modes: balanced, B-phase, BC-phase

Representative regression cases remain:

- topology2 balanced LVRT `0.90 pu / 60 ms`
- topology2 A-LVRT `0.90 pu / 60 ms`
- topology2 AB-LVRT `0.90 pu / 60 ms`

The family actor is promoted only if:

1. it does not break the three representative topology2 LVRT regression cases;
2. it passes voltage-survival on the holdout cases;
3. it beats conventional on the holdout matrix average score;
4. each SAC chunk records reward traces and switch-level promotion results.

## Experiment Sequence

1. Add a `topology2_lvrt_family_v1` proxy curriculum.
2. Smoke-test the curriculum scenario count and training entry point.
3. Run a small protected family SAC pilot from the current `t2_ab_lvrt` SAC
   actor.
4. Export the best family actor and validate it on:
   - the three representative topology2 LVRT regression cases;
   - the balanced/B/BC holdout matrix.
5. Compare:
   - conventional dq;
   - pre-family single-case seed;
   - family SAC candidate.
6. If the family SAC candidate regresses, keep the run as diagnostic and reduce
   exploration / increase behavior anchoring before repeating.

## Success Definition

For this stage, success is not full FRT certification.  Success is:

- switch-level voltage-survival on the topology2 LVRT family validation matrix;
- lower score than conventional dq on the same matrix;
- no regression on the already accepted representative topology2 LVRT cases;
- SAC reward traces present for the training run.

Full FRT metrics, especially grid-current limit and reactive-current support,
remain a later phase.
