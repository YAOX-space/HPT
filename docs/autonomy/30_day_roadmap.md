# 30-Day Roadmap

## Week 1 - Reproducible Platform

- Audit Git status, file layout, public entry points, and existing tests.
- Establish MATLAB Engine smoke runner and dry-run test.
- Document architecture, interface contracts, and migration policy.
- Confirm current conventional dq and SAC validation commands.

## Week 2 - Core Evidence

- Refresh or verify FRT calibration matrix.
- Run conventional dq versus active RL controller on representative topology1
  and topology2 voltage-survival cases.
- Build balanced and unbalanced boundary cases where SAC can be compared
  against the strongest conventional dq baseline.
- Re-run proxy gap, reward alignment, and rollout alignment after any interface
  change.

## Week 3 - Robustness

- Select depth-duration LVRT/HVRT grid for generalization.
- Add parameter/grid uncertainty only after baseline gates are stable.
- Analyze failed transfer cases and run targeted ablations.
- Defer full FRT certification gates until the voltage-survival and
  beat-conventional boundary matrix is stable.

## Week 4 - Paper Draft

- Draft IEEE-style introduction, method, experiments, discussion, and
  conclusion.
- Link every quantitative statement to a result report or manifest.
- Freeze limitations and future-work language.
