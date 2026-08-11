# Topology2 Tutorial

This folder contains the tutorial version of the paper-style HPT topology2
model.

- `hpt_topology2_tutorial.slx`: final topology2 tutorial Simulink model.
- `complete_hpt_topology2_tutorial.m`: rebuilds the tutorial model from the
  maintained `simulink/topology2` switch-level source.
- `organize_hpt_topology2_tutorial_root.m`: hides implementation details so the
  model root exposes a clean teaching-level block set.
- `run_hpt_topology2_tutorial_tests.m`: tutorial acceptance test runner.
- `hpt_topology2_tutorial_acceptance_report.md`: latest acceptance report.
- `hpt_topology2_tutorial_acceptance_tests.csv`: latest acceptance table.

Topology2 uses a W1/W2 main transformer, a secondary-side parallel energy
converter path, and a W5/W6 series transformer driven by the regulating
converter. It does not use the topology1 W3 tertiary energy winding.

The final root view separates the transformer-related teaching blocks into:

- `ElectromagneticTransformer`: W1/W2 main transformer.
- `CouplingTransformer`: secondary-side parallel energy-coupling transformer
  path for the energy converter.
- `SeriesTransformer`: W5/W6 series injection transformer path for the
  regulating converter.

`SeriesTransformer` exposes only physical power ports at the root level. Its
current and voltage measurement signals are hidden with Simulink `Goto`/`From`
tags and collected inside `MeasurementAndLogging`.
