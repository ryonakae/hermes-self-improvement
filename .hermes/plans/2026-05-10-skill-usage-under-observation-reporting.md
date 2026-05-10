# Skill usage under-observation reporting

## Status

implemented

## Parent roadmap

`2026-05-10-self-improvement-long-term-roadmap.md` — Milestone 5 / 6 / 7.

## Goal

Later skill usage should contribute weak positive credit, but it should not by itself be reported as `proven improved`. Add an explicit under-observation count for skill usage-only positives.

## Implementation plan

1. Adjust credit-assignment status classification so `skill_used_without_correction` alone remains `unknown` / under observation unless accompanied by stronger positive evidence.
2. Add `skill_usage_under_observation` to compact outcome summaries.
3. Show the count in CLI/calibrate report surfaces next to other under-observation counts.
4. Add focused tests and run the full suite.
5. Update roadmap and plan index.

## Verification

- `python -m pytest tests/test_credit_assignment.py::test_credit_assignment_keeps_skill_usage_only_under_observation tests/test_cli_surface.py::test_improve_summary_outcomes_show_quality_under_observation tests/test_calibration.py::test_calibration_summary_reports_quality_under_observation tests/test_report_integration.py::test_operational_report_sections_show_quality_under_observation -q` — 4 passed.
- Full-suite / py_compile / diff-check results are recorded in the session summary after commit.
