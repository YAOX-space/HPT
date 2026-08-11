# Tests

Active MATLAB smoke and regression scripts for the version-2 switch-level
models, v3 GB/T evaluator, and SAC interface.

- `test_hpt_gbt19963_envelope.m`: exact standard breakpoint regression.
- `test_hpt_pcc_assessment_voltage.m`: phase/line PCC signal-selection tests.
- `test_hpt_v2_sac_interface.m`: 24-observation/4-action interface contract.
- `test_hpt_v2_switch_models.m`: pure switch-level topology regressions.
- `smoke_hpt_v2_unbalanced_source.m`: unbalanced source diagnostic.

The old SAC fault-transition and steady-voltage performance tests asserted
pre-v3 load-voltage thresholds against an archived actor. They are preserved
under `archive/pre_gbt_v3_20260803/global/matlab_tests`, but they are
not current pass/fail tests and must not be included in promotion evidence.
