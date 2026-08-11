# Interface Migration Policy

Protected interfaces:

- Python module paths under `sac`.
- MATLAB scripts under `simulink`.
- Simulink workspace variables prefixed `hpt_`.
- SAC 24-D observation / 4-D action contract.
- Dataset fields separating command and measured response semantics.

Before replacing an old interface:

1. Record old and new names in `migration_notes.md`.
2. Add wrappers or compatibility routes only when backward compatibility is
   required by the user or by active scripts.
3. Update tests before removing old assumptions.
4. Re-run MATLAB/Python smoke gates.
5. Re-run proxy and switch-level validation if observations, actions, reward,
   envelope metrics, logged signals, or actor export formats changed.
