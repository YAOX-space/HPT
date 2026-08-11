# HPT Full-Action SAC Literature-Based Research Plan

Date: 2026-07-17

## Target

The final controller should directly output the complete continuous HPT action:

```text
[m_reg_d, m_reg_q, m_energy_d, m_energy_q]
```

No residual wrapper should be required in the final product.  A conventional dq
controller may provide data, warm start, behavior constraints, and comparison
baselines, but it should not remain as an execution-layer controller around SAC.

## Current Evidence

The latest project status shows three important facts.

1. The expanded calibrated proxy now matches the switch-level Simulink matrix
   in-sample for LV, Vdc, grid reactive current, current limit, and reward
   terms.  The 880-row expanded matrix reports near-zero environment rollout
   error on the calibrated surface.
2. Sparse interpolation outside that calibrated surface previously failed,
   especially for topology2 Vdc and grid `iq`.  Therefore SAC exploration must
   stay inside the calibrated support or trigger new Simulink sampling.
3. A meaningful conventional baseline now exists.  It has mixed pass/fail
   survival boundaries in 14 of 16 topology/category/duration groups, but full
   FRT still fails because of recovery, current limit, and reactive-current
   criteria.  This gives SAC a real target: beat the measured conventional
   boundary first, then improve strict full-FRT behavior.

The failed SAC attempts are also informative:

- plain SAC after alignment did not beat conventional;
- stronger teacher-prior SAC did not solve drift;
- the failure mode is actor update/exploration leaving the useful support, not
  simply missing PDF references or missing training epochs.

## Literature Lessons

| Paper group | Main lesson | HPT decision |
| --- | --- | --- |
| SAC base papers | Maximum-entropy SAC is a good continuous-action backbone but can over-explore. | Keep SAC as the final actor structure, reduce uncontrolled entropy during FRT training. |
| TD3+BC, BRAC, BCQ | Offline/limited-data RL needs behavior constraints to avoid extrapolation error. | Add behavior regularization around conventional and Simulink-labeled high-score actions. |
| IQL, AWAC | Advantage-weighted regression can improve over behavior without querying unsupported actions too aggressively. | Use IQL/AWAC-style pretraining before SAC fine-tuning. |
| CQL | Conservative Q-values reduce over-optimistic OOD actions. | Add CQL as a diagnostic baseline and possibly conservative critic regularization. |
| SACR2 | Demonstration and successful trajectory replay can improve SAC. | Seed replay with conventional boundary traces and high-score candidate traces. |
| PETS, MOPO, MOReL, COMBO | Learned/proxy dynamics need uncertainty or pessimism. | Use calibrated proxy only inside support; penalize or sample Simulink rows for off-support actions. |
| TRPO, CPO | Policy updates and safety constraints should be explicit. | Add trust-region-like actor update limits and separate cost constraints for Vdc, current, and FRT gates. |
| DSAC-T, DR-SAC, Continuous SAC | Robustness and time discretization matter after the basic pipeline is stable. | Treat these as second-stage improvements, not the first rescue step. |

## Research Hypothesis

SAC can beat the traditional dq baseline only if it is trained as a constrained
full-action policy:

```text
maximize switch-level-like FRT reward
subject to:
  action remains inside calibrated/sampled support early in training;
  Vdc/current/FRT violation costs remain bounded;
  policy updates are small enough to avoid destructive actor drift;
  off-support high-value actions are either pessimistically penalized or sent
  back to Simulink for labeling.
```

## Work Package 1: Literature And Data Index

Status: started and mostly complete.

Artifacts:

- `references/week7_full_action_sac/`
- `references/week7_full_action_sac/manifest.json`
- `references/week7_full_action_sac/extracted_text/`
- this research plan.

Deliverable:

- A readable literature bundle and method map that can be cited in the paper and
  used during implementation.

## Work Package 2: Baseline Dataset For "Beat Conventional"

Goal:

Build a training dataset where every row is tied to the same scenario,
topology, duration, and switch-level evaluator used by the traditional baseline.

Required rows:

- conventional dq action and score;
- calibrated candidate actions from baseline, regulating sweep, energy sweep,
  joint sweep;
- if possible, short local refinements around conventional boundary cases;
- full reward decomposition:
  - LV fault/recovery error;
  - Vdc min/max/survival;
  - grid `iq`, `iq_ref`, reactive shortfall, wrong sign;
  - grid current peak;
  - action magnitude and saturation;
  - `voltage_survival_pass`;
  - `full_frt_pass`.

Acceptance:

- A script can produce one dataset file for each topology/category/duration.
- The conventional action in the dataset reproduces the boundary report.
- Proxy reward and switch-level reward agree on all calibrated rows.

## Work Package 3: Full-Action Behavior-Regularized SAC

Goal:

Train SAC actor directly on the 4-D action while preventing early destructive
drift.

Actor output:

```text
a = [m_reg_d, m_reg_q, m_energy_d, m_energy_q]
```

Training changes:

1. Seed replay with conventional and high-score Simulink-labeled trajectories.
2. Add a behavior regularization term early in training:

```text
L_actor = L_SAC + lambda_bc(t) * ||a - a_ref||^2
```

where `a_ref` is the best switch-level labeled action for that
topology/category/duration state, not a final wrapper.

3. Anneal `lambda_bc` down only after the actor preserves conventional pass
   cases.
4. Lower entropy target during fault specialist training so SAC does not keep
   sampling unsafe off-support actions.
5. Add an OOD/support penalty:

```text
if action not in calibrated support:
    reward -= support_penalty
    mark proxy_ood_action = true
```

6. Candidate actions that look promising but are off-support should be queued
   for switch-level Simulink labeling instead of trusted immediately.

Acceptance:

- BC-only reproduction matches the conventional action and score.
- SAC after 1000 to 3000 steps does not lose any conventional survival-pass
  case.
- SAC improves score or boundary depth in at least one conventional-fail case
  on proxy and then on switch-level Simulink.

## Work Package 4: Offline Baselines

Goal:

Check whether the dataset itself contains enough information to beat
conventional before spending long online SAC time.

Methods:

- TD3+BC: first baseline because implementation is simple and action is
  continuous.
- IQL or AWAC: useful when we want improvement from advantage-weighted behavior
  data without evaluating many unseen actions.
- CQL: conservative critic baseline for OOD diagnosis.
- BCQ/BRAC: optional if the actor keeps leaving support.

Acceptance:

- At least one offline method preserves conventional pass cases.
- If none can improve conventional-fail boundary cases, the dataset lacks
  corrective actions and more Simulink samples are required.

## Work Package 5: Proxy Support And Active Simulink Sampling

Goal:

Avoid pretending the proxy is valid outside its sampled surface.

Loop:

1. Train actor on calibrated support.
2. Detect high-value off-support actions.
3. Run those actions in switch-level Simulink.
4. Add the results to calibration and training data.
5. Regenerate proxy calibration and reward alignment.

Acceptance:

- New off-support samples reduce proxy OOD flags over time.
- Simulink-labeled candidate actions improve, or the actor learns to avoid
  them because they fail physically.

## Work Package 6: Constraint-Aware Promotion Gate

Goal:

Separate training score from physical certification.

Promotion requires:

1. `voltage_survival_pass` improvement over conventional on the same scenario.
2. No worse Vdc minimum than conventional unless LV regulation improves enough
   and Vdc remains inside survival limits.
3. No grid-current limit violation.
4. Reactive-current sign and shortfall are not worse than conventional.
5. Full switch-level Simulink validation, not proxy-only validation.

Longer-term strict goal:

- Improve `full_frt_pass`, especially recovery, current limit, and dynamic
  reactive-current support.

## Proposed Experiment Sequence

### E0: Reproducibility Gate

Run:

- regenerate conventional boundary summary;
- verify proxy rollout alignment on the expanded 880-row matrix;
- confirm BC-only policy reproduces conventional actions.

Success:

- zero proxy/switch reward mismatch on calibrated rows;
- BC-only action error near zero;
- conventional pass/fail matrix unchanged.

### E1: Full-Action BC Warm Start

Train one specialist per topology/category/duration around the boundary cases.

Success:

- actor outputs 4-D actions directly;
- no residual wrapper;
- preserves conventional pass cases.

### E2: Behavior-Regularized SAC Fine-Tuning

Variants:

- `lambda_bc = 300 -> 30 -> 3`;
- lower entropy target;
- smaller actor learning rate;
- support penalty enabled.

Success:

- SAC does not drop below BC/conventional pass count;
- at least one conventional-fail near-boundary case improves in switch-level
  validation.

### E3: Offline Baseline Comparison

Train:

- TD3+BC;
- IQL/AWAC;
- CQL if time permits.

Success:

- compare against behavior-regularized SAC on the same data;
- identify whether SAC failure is an algorithm issue or dataset-support issue.

### E4: Active Support Expansion

For cases where SAC proposes high-value OOD actions:

- evaluate them in Simulink;
- add to matrix;
- recalibrate proxy;
- re-run E2.

Success:

- fewer OOD rejections;
- improved boundary result or clear evidence that the proposed action family is
  physically bad.

### E5: Switch-Level Candidate Promotion

Evaluate only candidates that pass E2/E3 on proxy support.

Success:

- one topology1 LVRT specialist beats conventional survival boundary;
- one topology1 HVRT specialist beats conventional survival boundary;
- one topology2 case either beats conventional or shows clearly documented
  physical limitation requiring topology/controller redesign.

## Immediate Next Implementation Tasks

1. Add a dataset builder for boundary-centered full-action offline data.
2. Add BC-only full-action pretraining and a report comparing actor actions to
   conventional/candidate labels.
3. Modify specialist SAC loss to include annealed behavior regularization and
   calibrated-support penalty.
4. Add TD3+BC baseline using the same dataset.
5. Run the first smoke campaign on boundary cases only:
   - topology1 LVRT 80 ms near `0.75/0.70 pu`;
   - topology1 HVRT 80 ms near `1.15/1.18 pu`;
   - topology2 LVRT 40 ms near `0.98/0.95 pu`;
   - topology2 HVRT 80 ms near `1.10/1.12 pu`.
6. Promote nothing until switch-level Simulink confirms improvement over
   `conventional_dq`.

## What This Plan Deliberately Avoids

- No final residual controller.
- No claim based on proxy-only success.
- No long SAC run before BC reproduction and proxy support gates pass.
- No comparison against a weak or all-fail baseline.  The conventional boundary
  matrix is the baseline to beat.

