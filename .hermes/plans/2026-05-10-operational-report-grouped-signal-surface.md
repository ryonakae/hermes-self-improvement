# Operational report grouped signal surface

**Status:** implemented.

## Why

Calibration summaries now expose grouped actionable/non-actionable signals, but read-only `report` output still only showed aggregate calibration evidence. The daily Slack digest depends on operational report text and template guidance, so grouped signal meaning could still be lost before the morning report.

## Scope

Small reporting slice:

- expose grouped calibration signals in operational report sections;
- update the daily Slack template guidance so actionable workflow groups are separated from non-actionable diagnostic volume.

No scoring logic changes.

## Implemented behavior

Operational report `## Calibration summary` now includes, when available:

- `grouped actionable: patch_tool 71 -> safe-patch-usage`
- `non-actionable volume: tool_error:terminal:terminal_nonzero_exit 493`

The Slack template now tells the digest writer to keep actionable workflow areas and non-actionable volume separate in `🛠️ 運用メモ`.

## Verification

- Added a focused operational report test for grouped calibration signals.
- Focused test passes.
- Full suite, py_compile, and diff check were run before commit.
