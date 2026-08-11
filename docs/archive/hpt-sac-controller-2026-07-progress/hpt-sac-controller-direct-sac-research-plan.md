# HPT Direct SAC Research Plan

Last updated: 2026-07-15

## 1. Goal

Build a final direct SAC-style controller for the version 2 hybrid power
transformer models:

- `simulink/topoloty1/hpt_v2_1to1_switchlevel.slx`
- `simulink/topology2/hpt_v2_topology2_paper.slx`

The final controller must control the HPT directly through converter modulation
commands. The learned proxy is only a training environment, not an added
residual controller and not a second control layer around SAC.

Final deployment interface:

```text
observation -> actor -> [m_reg_d, m_reg_q, i_energy_d_ref_pu, i_energy_q_ref_pu]
```

The deployment layer converts the regulating modulation commands and the
energy-converter current-reference commands to PWM/gate signals for the two
switch-level converters.

Final promotion must use `hpt_sac_guard_enable = 0`: execution-layer
teacher guards, topology-specific action overwrites, and conventional-like
fallback laws may be used for data generation and smoke baselines, but they are
not allowed in the final claimed controller. Hardware modulation saturation is
still allowed.

## 2. Current Evidence

Latest overnight run:

- Report: `lab/results/hpt_sac_overnight_20260715_124514/REPORT.md`
- Best steady switch-level result passed.
- Fault-transition validation still failed.

Important metrics from the current report:

| Case | Status | Key result |
| --- | --- | --- |
| Steady step4 | Pass | score `4.516`, max LV error `7.961 V`, min Vdc `724.020 V` |
| Fault transition | Fail | score `1003.597`, max LV error `48.512 V`, peak `296.732 V`, min LV RMS `114.740 V`, min Vdc near `0 V` |

Interpretation:

1. The switch-level controller path works for steady regulation.
2. The current training environment does not represent fault-transition energy
   dynamics well enough.
3. Pure SAC trained on the current proxy can exploit proxy errors and then fail
   on switch-level Simulink.
4. The research problem is now a data-efficient, uncertainty-aware training
   problem, not just a hyperparameter search problem.

## 3. Research Hypotheses

### H1: Proxy mismatch is the main failure source

The current averaged proxy is too optimistic during severe fault transitions.
The SAC actor learns commands that look useful in the proxy but collapse the
DC link or create excessive voltage excursions in switch-level Simulink.

Validation:

- Compare proxy and switch-level rollouts for the same initial condition,
  scenario, and action sequence.
- Measure one-step and multi-step errors in LV RMS, sequence voltage, Vdc, and
  action-to-voltage gain.

### H2: A learned dynamics proxy can reduce sample cost

A PETS-style probabilistic ensemble trained on switch-level rollouts can model
the transition dynamics better than the hand-tuned proxy while still running
fast enough for SAC training.

Validation:

- Hold out full scenarios from the Simulink dataset.
- Require the learned proxy to predict safety-critical trends:
  LV RMS recovery, Vdc droop, Vdc overshoot, and phase imbalance.

### H3: Uncertainty penalties are required

SAC will exploit any learned proxy if uncertainty is not represented. MOPO or
MOReL-style pessimism should reduce unsafe actions in poorly covered regions.

Validation:

- Compare SAC on learned proxy with and without uncertainty penalty.
- Measure Simulink pass rate and worst-case safety metric.

### H4: One unified actor is possible, but only if topology context is visible

One actor can cover topology1 and topology2 if the observation includes enough
context or normalized physical response variables. If not, topology-conditioned
fine-tuning or small per-topology adapters may be needed.

Validation:

- Train one shared actor on mixed topology data.
- Test topology1-only, topology2-only, and mixed validation sets.
- If one topology fails consistently, add an explicit topology/context feature
  before splitting the policy.

### H5: Offline baselines are needed as sanity checks

IQL, TD3+BC, and CQL should be trained from the same Simulink dataset to check
whether direct SAC is failing because of exploration, proxy bias, or action
support.

Validation:

- Run the same switch-level validation matrix for direct SAC and offline
  baselines.
- Use baselines to define a minimum acceptable behavior before online-style
  proxy training.

## 4. Controller Scope

### In scope

- Direct SAC-style continuous-action controller.
- Topology1 and topology2 support.
- Steady, sag, swell, and fault-transition scenarios.
- Learned ML proxy for training.
- Offline RL baselines for comparison.
- Switch-level Simulink validation as the source of truth.
- Git-managed experiment tracking.

### Out of scope for this research cycle

- Residual controller wrapped around SAC.
- Direct training from raw 20 us switch-level Simulink at large scale.
- Hardware deployment or real-time code generation.
- Replacing the physical switch-level model with a learned model for final
  claims.

## 5. Work Packages

### WP0: Git baseline and experiment hygiene

Goal:

Make every experiment reproducible from a Git commit, config file, dataset
manifest, and result folder.

Tasks:

1. Create a clean research branch once current useful changes are identified:

   ```powershell
   git switch -c research/hpt-direct-sac-v2
   ```

2. Do not commit generated bulk data by default.
3. Commit source code, specs, small config files, and summary reports.
4. Store large run outputs under `lab/results/...` with a metadata file that
   records the source commit.
5. Use one branch per risky experiment:

   ```text
   exp/sac-v2-data-collector
   exp/sac-v2-learned-proxy
   exp/sac-v2-mopo
   exp/sac-v2-iql-baseline
   exp/sac-v2-topology2-finetune
   ```

6. Merge only successful, reviewed experiment branches back into the research
   branch.

Deliverables:

- `docs/specs/algorithms/hpt-sac-controller/hpt-sac-controller-direct-sac-research-plan.md`
- Experiment metadata schema.
- Branch and commit naming rules.

Exit criteria:

- Each new experiment can answer:
  - Which code commit created it?
  - Which Simulink model version was used?
  - Which dataset was used?
  - Which random seeds were used?
  - Which policy checkpoint was evaluated?

### WP1: Freeze controller interface

Goal:

Prevent hidden interface drift while changing proxy and training algorithms.

Current action interface remains 4-D:

| Action | Meaning | Range |
| --- | --- | --- |
| `m_reg_d` | regulating converter d-axis modulation | `[-0.8, 0.8]` |
| `m_reg_q` | regulating converter q-axis modulation | `[-0.8, 0.8]` |
| `i_energy_d_ref_pu` | normalized TPFBVSC d-axis current reference | `[-0.95, 0.95]` |
| `i_energy_q_ref_pu` | normalized TPFBVSC q-axis current reference | `[-0.95, 0.95]` |

Observation options:

- Keep 16-D for steady-only compatibility.
- Use 24-D for fault-transition learning, as proposed in
  `hpt-sac-controller-fault-transition-research-plan.md`.

Recommendation:

- Use 24-D for the final fault-transition actor.
- Keep an adapter that can load old 16-D policies only for comparison.

Exit criteria:

- Python env, actor export, and Simulink loader reject mismatched dimensions.
- The observation definition is written once and imported by training and export
  scripts.

### WP2: Switch-level data collection

Goal:

Build a compact but useful dataset from topology1 and topology2 switch-level
Simulink models.

Scenarios:

| Class | Values |
| --- | --- |
| topology | topology1, topology2 |
| operating state | steady, sag, swell, fault entry, fault hold, clearing, recovery |
| balanced LVRT | 0.2, 0.5, 0.75, 0.85, 0.9 pu |
| balanced HVRT | 1.1, 1.2, 1.25, 1.3 pu |
| asymmetric fault | one-phase, two-phase, two-phase-ground approximations |
| grid strength | strong, nominal, weak |
| DC-link IC | low, nominal, high |
| action source | teacher, random around teacher, previous SAC, safe probing |

Logged signals:

- observation vector
- action vector
- next observation vector
- reward components
- LV phase RMS
- positive/negative sequence voltage
- Vdc
- converter currents if available
- safety flags
- topology and scenario metadata

Dataset format:

```text
data/hpt_switch_rollouts/
  dataset_YYYYMMDD_name/
    manifest.json
    train.parquet or train.npz
    val.parquet or val.npz
    test.parquet or test.npz
    README.md
```

Exit criteria:

- At least one balanced sag, one swell, one deep sag, and one recovery scenario
  for each topology.
- Dataset manifest contains Git commit, Simulink model path, model file hash,
  MATLAB version, solver settings, sample time, and scenario counts.

### WP3: Proxy gap measurement

Goal:

Quantify the gap before trying to fix it.

Metrics:

| Metric | Definition |
| --- | --- |
| one-step LV RMS error | `abs(v_lv_next_proxy - v_lv_next_sim)` |
| one-step Vdc error | `abs(vdc_next_proxy - vdc_next_sim)` |
| rollout LV RMS error | max/mean error over full scenario |
| rollout Vdc error | min/max Vdc mismatch over full scenario |
| safety classification accuracy | proxy predicts pass/fail vs Simulink pass/fail |
| action-gain error | mismatch between action change and voltage response |

Exit criteria:

- A table ranking where the proxy fails:
  topology, scenario, action region, and metric.
- A reproducible script that can be rerun after every proxy change.

### WP4: Learned probabilistic proxy

Goal:

Train a PETS-style probabilistic ensemble model from switch-level data.

Input:

```text
[obs_t, action_t, scenario_context]
```

Output:

```text
delta_obs = obs_{t+1} - obs_t
safety_metrics_{t+1}
```

Ensemble:

- 5 to 7 neural networks.
- Each predicts mean and variance.
- Bootstrap resampling per ensemble member.
- Normalize all inputs/outputs using dataset statistics.

Uncertainty:

- epistemic: ensemble disagreement
- aleatoric: predicted variance
- combined penalty input for MOPO/MOReL training

Exit criteria:

- Learned proxy beats current hand-tuned proxy on held-out Simulink scenarios.
- It does not hide dangerous Vdc collapse or LV overvoltage cases.
- It produces calibrated uncertainty: larger error regions should have higher
  ensemble disagreement.

### WP5: Offline baselines

Goal:

Create non-SAC baselines to separate policy-learning problems from proxy
problems.

Algorithms:

| Algorithm | Why |
| --- | --- |
| TD3+BC | simple strong offline baseline |
| IQL | stable offline learning without querying unseen actions |
| CQL | conservative Q-values for safety |

Training data:

- Same switch-level dataset from WP2.
- Teacher and safe-probing actions included.

Exit criteria:

- Each baseline can export the same 4-D action interface.
- Each baseline is evaluated on the same switch-level smoke matrix.
- If baselines fail like SAC, the issue is likely data/control authority.
- If baselines pass while SAC fails, the issue is likely SAC/proxy training.

### WP6: Direct SAC with pessimistic learned proxy

Goal:

Train the direct controller on the learned proxy while avoiding unsupported
actions.

Training variants:

| Variant | Description |
| --- | --- |
| SAC-proxy | direct SAC on learned proxy, no uncertainty penalty |
| SAC-MOPO | direct SAC with uncertainty reward penalty |
| SAC-MOReL | direct SAC with terminal unsafe state for high uncertainty |
| DSAC/DR-SAC | optional later robust SAC variants |

Reward:

```text
r =
  - voltage_tracking_error
  - dc_link_error
  - phase_unbalance
  - action_magnitude_penalty
  - action_slew_penalty
  - uncertainty_penalty
  - hard_safety_penalty
```

Hard termination:

- Vdc outside survival range.
- LV RMS outside safety envelope.
- non-finite state.
- uncertainty beyond support threshold.

Exit criteria:

- SAC-MOPO/MOReL beats SAC-proxy on switch-level fault-transition smoke tests.
- Candidate actor passes steady regulation before fault-transition promotion.

### WP7: Switch-level validation and promotion gate

Goal:

Only promote actors that pass switch-level Simulink tests.

Gate 1: smoke

- topology1 steady sag
- topology1 swell
- topology2 steady sag
- topology2 swell
- topology1 fault transition
- topology2 fault transition

Gate 2: expanded matrix

- balanced LVRT/HVRT
- asymmetric faults
- weak-grid cases
- DC-link IC variation

Pass criteria:

| Metric | Target |
| --- | --- |
| LV steady error | within agreed tolerance around 230 V RMS |
| post-clear recovery | within +/-7 percent |
| Vdc survival | no collapse; nominal target around 800 V |
| action bounds | no modulation bound violation |
| phase unbalance | bounded and improving after fault clear |
| wrong-sign support | none after detection delay |

Promotion rule:

- Never promote a policy only from proxy score.
- A promoted checkpoint must include its Git commit, dataset manifest, training
  config, and Simulink validation report.

### WP8: Topology transfer and final decision

Goal:

Decide whether one actor is enough or whether we need topology-specific
fine-tuning.

Decision ladder:

1. Try one actor with topology randomized data.
2. Add explicit topology/context observation if needed.
3. Fine-tune separate checkpoints only if one actor cannot pass both
   topologies.
4. Keep deployment interface identical even if checkpoints differ.

Final deliverables:

- best unified actor, if successful
- best topology1 actor, if needed
- best topology2 actor, if needed
- summary comparing unified vs fine-tuned policies

## 6. Git Experiment Management

### Branch roles

| Branch type | Purpose | Example |
| --- | --- | --- |
| `main` | stable project history | `main` |
| `research/*` | integrated research line | `research/hpt-direct-sac-v2` |
| `exp/*` | one risky experiment | `exp/sac-v2-mopo-v1` |
| `fix/*` | small correction | `fix/proxy-vdc-normalization` |

### Commit rules

Use small commits with one purpose:

```text
docs: add HPT direct SAC research plan
data: add switch rollout manifest schema
proxy: add probabilistic ensemble dynamics model
train: add MOPO uncertainty penalty to SAC env
eval: add topology2 fault-transition validation sweep
fix: correct Vdc normalization in learned proxy
```

Do not mix:

- code and large result files
- topology changes and controller changes
- training algorithm changes and reward changes
- generated reports and source edits unless the report is the intended
  deliverable

### Tags

Use lightweight tags for important frozen points:

```text
sac-v2-interface-24d-v1
sac-v2-dataset-v0.1
sac-v2-proxy-pets-v0.1
sac-v2-policy-mopo-smoke-pass-v0.1
sac-v2-policy-final-candidate-v0.1
```

### Experiment metadata

Every run folder should contain:

```text
metadata.json
config.json
summary.json
REPORT.md
```

Minimum `metadata.json` fields:

```json
{
  "git_commit": "<sha>",
  "git_branch": "<branch>",
  "dirty": true,
  "matlab_version": "<version>",
  "python_version": "<version>",
  "topology_models": {
    "topology1": "<path>",
    "topology2": "<path>"
  },
  "model_hashes": {
    "topology1": "<sha256>",
    "topology2": "<sha256>"
  },
  "dataset_manifest": "<path>",
  "training_config": "<path>",
  "random_seeds": [0],
  "policy_checkpoint": "<path>"
}
```

### Result storage rules

Commit:

- source code
- small config files
- manifest files
- markdown reports
- small CSV summaries

Do not commit by default:

- raw `.mat` traces
- long training logs
- large replay buffers
- generated plots unless selected for a report
- temporary files under `tmp/`

If a large artifact is necessary for reproducibility, either:

- use Git LFS, or
- store it outside Git and commit only a manifest with path/hash.

### Merge gate

An experiment branch can merge into `research/hpt-direct-sac-v2` only when:

1. Unit tests pass.
2. Proxy gap report is updated if proxy behavior changed.
3. Simulink smoke validation is run if actor behavior changed.
4. `REPORT.md` states what improved and what regressed.
5. The branch does not accidentally add bulk results.

## 7. Detailed Timeline

### Phase A: Setup and baseline, 0.5 to 1 day

- Create research branch.
- Add metadata schema.
- Freeze observation/action interface decision.
- Run current smoke validation once and record baseline.

Output:

- baseline report
- frozen interface document
- clean branch point

### Phase B: Dataset collection, 1 to 3 days

- Build switch-level data collector.
- Run small balanced sag/swell/fault dataset.
- Add weak-grid and topology2-focused cases.

Output:

- dataset v0.1
- dataset manifest
- dataset quality report

### Phase C: Proxy gap and learned proxy, 2 to 4 days

- Implement proxy-vs-Simulink comparator.
- Train PETS-style ensemble.
- Compare hand proxy vs learned proxy.

Output:

- proxy gap report
- learned proxy v0.1
- uncertainty calibration plot/report

### Phase D: Offline baselines, 2 to 4 days

- Train TD3+BC and IQL.
- Optionally train CQL if implementation cost is acceptable.
- Test on switch-level smoke matrix.

Output:

- baseline checkpoint(s)
- offline baseline comparison table

### Phase E: SAC with uncertainty penalty, 3 to 7 days

- Train SAC-proxy baseline.
- Train SAC-MOPO.
- Train SAC-MOReL.
- Promote only switch-level passing actors.

Output:

- SAC checkpoints
- Simulink validation report
- failure analysis for non-promoted actors

### Phase F: Full validation and paper-ready summary, 2 to 5 days

- Run expanded matrix.
- Compare topology1 vs topology2.
- Decide unified actor vs fine-tuned actors.
- Prepare figures and final report.

Output:

- final candidate actor(s)
- final topology comparison
- final HPT SAC research report

## 8. Acceptance Criteria For The Research Program

Minimum success:

- A direct actor passes steady sag/swell switch-level validation on both
  topology1 and topology2.
- Fault-transition behavior improves over the current overnight report.
- Results are reproducible from a Git commit and manifest.

Strong success:

- One unified actor passes steady and fault-transition smoke tests on both
  topologies.
- Learned proxy predicts pass/fail better than current hand proxy.
- SAC-MOPO or SAC-MOReL beats SAC-proxy in switch-level validation.

Final success:

- Unified or topology-conditioned direct SAC passes the full validation matrix.
- No non-physical average injection source is used for final validation.
- `hpt_sac_guard_enable = 0` for final switch-level validation; no
  execution-layer rule may overwrite actor actions except actuator saturation.
- The final report clearly separates training proxy results from physical
  switch-level Simulink results.

## 9. Main Risks And Mitigations

| Risk | Mitigation |
| --- | --- |
| Switch-level simulations are too slow | Use stratified short scenarios, cache rollouts, parallelize MATLAB runs, train on learned proxy |
| Learned proxy is exploited by SAC | Add MOPO/MOReL uncertainty pessimism and hard Simulink promotion gate |
| Dataset lacks corrective actions | Add teacher, safe probing, and previous SAC actions; use TD3+BC/IQL to test action support |
| One actor cannot cover both topologies | Add topology/context observation; then fine-tune while keeping interface identical |
| Fault-transition destroys DC link | Add Vdc survival reward, terminal penalty, and data focused on clearing/recovery |
| Experiment history becomes unclear | Use branch-per-experiment, metadata JSON, tags, and no bulk-result commits |

## 10. Immediate Next Steps

1. Make a clean Git research branch after deciding which current local changes
   are part of the baseline.
2. Add experiment metadata schema and a helper that writes `metadata.json` into
   every result directory.
3. Freeze the 24-D observation and 4-D action contract for fault-transition
   training.
4. Build the switch-level rollout collector for a small topology1/topology2
   dataset.
5. Implement proxy-vs-Simulink gap report before changing the SAC algorithm.
6. Train the first PETS-style learned proxy.
7. Run TD3+BC/IQL offline baselines.
8. Train SAC-MOPO/MOReL only after the learned proxy passes the gap gate.
