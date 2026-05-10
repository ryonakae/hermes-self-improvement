# Calibration grouped signal reporting

**Status:** implemented.

## Why

Actionable cluster groups already feed calibration signal strength, but the human-readable calibration summary only showed aggregate weak/medium/strong counts. That still made grouped workflow areas and non-actionable volume hard to understand without opening JSON artifacts.

## Scope

Small reporting slice: expose grouped signal material in `calibrate` summary output. No change to calibration scoring logic.

## Implemented behavior

When `signal_strength` contains grouped cluster metadata, calibration summaries now include:

- `Grouped signals:`
- actionable groups with counts and suggested coverage, for example:
  - `long_running_tool_execution 85 -> timeout-workflow`
  - `patch_tool 71 -> safe-patch-usage`
- non-actionable high-volume clusters separately, for example:
  - `tool_error:terminal:terminal_nonzero_exit 493`

This makes it clear which signals are usable workflow evidence and which are diagnostic noise.

## Verification

- Added a focused calibration summary test for actionable and non-actionable grouped signals.
- Focused test passes.
- Full suite, py_compile, and diff check were run before commit.
