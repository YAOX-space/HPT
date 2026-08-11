# HPT Family SAC Literature Strategy

Date: 2026-07-28

## Current Problem

The Stage-7 topology2 LVRT family pilot showed a useful but uncomfortable
result:

- a single topology2 AB-LVRT seed generalized to 5 / 9 switch-level cases;
- a selector teacher that picks among validated balanced, A-phase, and
  AB-phase specialists reached 7 / 9;
- execution-guard BC was stable but only reached 3 / 9;
- direct raw full-action SAC on the proxy collapsed the first switch-level spot
  case, producing a low LV voltage and action-limit violation.

So the immediate problem is not "SAC has no value"; it is that direct
full-action SAC is being asked to learn family feasibility from an imperfect
proxy.  The literature points to a safer sequence.

## Literature Mapping to Our Issue

### 1. DAgger / On-Policy Imitation

DAgger addresses the core mismatch between training on expert states and
deploying on student-induced states.  This is exactly our trajectory problem:
one fixed point action or one expert trace is not enough because the HPT state
changes across fault inception, fault hold, and recovery.

Project translation:

- roll out the current family actor in proxy and switch-level smoke cases;
- collect the states it actually visits;
- relabel those states using the selector teacher or a constrained local
  trajectory search;
- retrain the actor on aggregated data.

### 2. Multiple Imperfect Experts

MEGA-DAgger is directly relevant because our "teacher" is not one perfect
controller.  It is a set of validated but local specialists: balanced LVRT,
A-phase LVRT, AB-phase LVRT, and later HVRT variants.

Project translation:

- do not average all specialist outputs blindly;
- select or weight specialists using scenario metadata and switch-level safety
  metrics;
- filter unsafe teacher demonstrations before adding them to the dataset.

### 3. Policy Distillation and Multitask Policy Learning

Policy distillation, Actor-Mimic, and Distral support using many task-specific
controllers to train one compact family actor.  This fits our goal of moving
from 12 exact specialists to fault-family controllers.

Project translation:

- train a single family actor from selector-teacher traces;
- keep topology/fault-family metadata in the observation;
- keep single-case specialists as regression gates, not as the final paper
  artifact.

### 4. Residual RL Instead of Direct Replacement

Residual RL papers are the closest match to our SAC fine-tune failure.  The
base policy provides robust feasible behavior, while RL learns only a small
correction.  This prevents the policy from leaving the support of known-safe
actions.

Project translation:

- freeze a BC/DAgger family actor as `pi_base(s)`;
- train SAC/TD3 residual `delta_pi(s)`;
- execute `a = projection(pi_base(s) + delta_pi(s))`;
- bound the residual by a state-dependent envelope derived from switch-level
  calibration and accepted trajectories.

### 5. Safe / Constrained RL

CPO, Lyapunov safe policy optimization, and power-system safe RL reviews all
support the same point: in grid-control tasks, unsafe exploration is not merely
a training nuisance; it invalidates the control claim.

Project translation:

- voltage envelope, recovery envelope, DC-link survival, and action bounds are
  hard promotion gates;
- unsafe proxy reward improvement is not accepted unless the switch-level gate
  passes;
- the execution layer needs projection/shielding during validation, not only a
  soft reward penalty during training.

## Superseded Direction Note

After the user's 2026-07-28 clarification, this document should be read only as
background for support-data construction.  DAgger/BC are not the main research
line.  The active main line is SAC debugging and SAC algorithm improvement,
documented in:

- `docs/specs/algorithms/hpt-sac-controller/hpt-sac-controller-sac-main-debug-plan-2026-07-28.md`

## Recommended Next Method

### Step A: Build Selector-Teacher Trajectory Dataset

Use the validated topology2 LVRT specialists as teachers:

- balanced rows -> topology2 balanced LVRT seed;
- one-phase rows -> topology2 A-LVRT seed, phase-normalized for B/C;
- two-phase rows -> topology2 AB-LVRT seed, phase-normalized for BC/CA.

For each scenario, collect trajectory-level state/action pairs across:

- pre-fault;
- fault onset;
- fault hold;
- clearing transient;
- recovery window.

Only keep traces that pass voltage-survival or whose failure mode is explicitly
being repaired by local search.

### Step B: Train Family BC Actor

Train one state-feedback actor on the aggregated selector-teacher traces.
Observation must include:

- topology id;
- fault type/family;
- phase-mode encoding;
- measured grid positive/negative sequence voltage;
- LV RMS and envelope error;
- DC-link voltage and rate;
- time-to-fault-clear / phase-in-window features.

Output should remain split-head:

- `reg_head`: `[m_reg_d, m_reg_q]`;
- `energy_head`: `[m_energy_d, m_energy_q]`.

### Step C: DAgger Relabeling

Roll out the family actor, collect the states it visits, then relabel with the
selector teacher and local trajectory repair.  Repeat until switch-level
regression stops improving.

The goal is not to prove DAgger as the final controller.  The goal is to create
a robust feasible base for SAC.

### Step D: Residual / Protected SAC Fine-Tune

Replace direct full-action SAC with residual SAC:

```text
a_base = pi_BC_DAgger(s)
delta_a = pi_SAC_residual(s)
a_exec = project(a_base + delta_a, constraints(s))
```

The residual must be small at first and expanded only when switch-level
promotion stays feasible.  Candidate chunks are promoted only if they beat the
BC/DAgger base and conventional dq under the same switch-level validator.

### Step E: Switch-Level Promotion and Failure Analysis

Promotion matrix:

- start with topology2 LVRT family holdout;
- then topology1 LVRT/HVRT family;
- then unbalanced expansion;
- keep full FRT certification out of scope until voltage-survival family
  control is stable.

For every rejected actor, save:

- proxy reward trace;
- switch-level score;
- envelope violation;
- recovery violation;
- DC-link min/max;
- action-limit violation;
- inferred failure class.

## What Not to Do Next

- Do not continue raw proxy SAC as the main training route.
- Do not claim a family SAC controller from selector-teacher results alone.
- Do not treat proxy reward gains as final evidence.
- Do not merge all topology/fault scenarios into one universal actor until the
  family-level actors are stable.

## Concrete Next Experiments

1. Generate selector-teacher traces for topology2 LVRT family.
2. Train a split-head BC family actor.
3. Run one DAgger relabel cycle on proxy plus a small switch-level smoke set.
4. Train residual SAC around the DAgger actor with residual bounds.
5. Compare four rows on the same holdout matrix:
   - conventional dq;
   - best single-case seed;
   - selector teacher;
   - BC/DAgger/residual-SAC family actor.
6. Promote only if the family actor passes switch-level voltage-survival and
   improves average score without regressing accepted representative cases.

## Sources Stored Locally

The PDFs and extracted text are stored under:

- `references/week8_family_sac/`
- `references/week8_family_sac/extracted_text/`
