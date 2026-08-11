# MATLAB And Simulink Tooling

Use the official MathWorks MATLAB MCP Server for toolbox detection, Code
Analyzer, short MATLAB execution, maintained script execution, and MATLAB unit
tests. Use Simulink Agentic Toolkit model tools when exposed for model
overview, read, edit, parameter resolution, diagnostics, checks, and persistent
tests.

Use canonical repository campaigns for long sweeps and SAC training because
they save metadata, hashes, logs, and summaries. MATLAB Engine and
`matlab -batch` remain fallbacks when MCP is unavailable or unsuitable for the
run duration.

## Current Environment Check

At the 2026-08-03 skill revision, official MATLAB MCP detection reported
MATLAB, Simulink, Simscape, and Simscape Electrical R2025a. Re-detect rather
than assuming this remains true in later sessions.

## Validation Sequence

1. Detect MATLAB and required products.
2. Inspect source, model, parameters, and callers.
3. Run Code Analyzer on edited MATLAB files.
4. Run the smallest MATLAB or Simulink regression test.
5. Run the affected switch-level evaluator when behavior changes.
6. Record versions, commands, hashes, outputs, and diagnostics.

On Windows, ensure the MATLAB MCP configuration forwards `WINDIR`. Existing
session mode also requires the MCP toolbox and `shareMATLABSession()`.

Upstream references:

- https://github.com/matlab/matlab-agentic-toolkit
- https://github.com/matlab/matlab-mcp-server
- https://github.com/matlab/simulink-agentic-toolkit
