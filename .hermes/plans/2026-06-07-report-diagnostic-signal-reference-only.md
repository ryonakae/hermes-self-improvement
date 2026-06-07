# Report Diagnostic Signal Reference-only Follow-up

**Goal:** Keep `report` heuristic output as diagnostic evidence only when it is fed into `improve --from-report`. Report scoring may highlight observations, but it must not provide planner-facing routing hints that look like mutation recommendations.

## Problem

The maintenance memo can show a mismatch such as `improve apply 0` while `report heuristic` says several items look apply-worthy. That is acceptable only if the report side is clearly advisory. The code path that attached report diagnostic signals to the evidence pack still added a synthetic `likely_targets=[{"target":"skill","weight":0.6}]`, which reintroduced a route-like hint from deterministic report scoring into Planner evidence.

## Contract

- `report` heuristic scores are for ordering / diagnostic attention only.
- `improve` Planner remains the sole semantic mutation decision maker.
- `from_report` diagnostic evidence may preserve `theme`, `severity`, `count`, `summary`, `suggested_attention`, and `evidence_refs`.
- `from_report` diagnostic evidence must not include `likely_targets`, `suggested_route`, `decision`, or other planner-routing / mutation-decision fields.

## Implementation status — 2026-06-07

Implemented:

- Strengthened `tests/test_report_improve_connection.py::test_run_improve_from_report_adds_reference_only_diagnostic_evidence` so the diagnostic evidence must be reference-only.
- Removed the synthetic `likely_targets` field from `_attach_diagnostic_signals_to_evidence_pack()`.

Verification:

```bash
.venv/bin/python -m pytest tests/test_report_improve_connection.py::test_run_improve_from_report_adds_reference_only_diagnostic_evidence -q
```

Result: `1 passed`.

Broader verification before commit:

```bash
.venv/bin/python -m pytest tests/test_report_improve_connection.py tests/test_knowledge_maintenance_planner.py -q
.venv/bin/python -m py_compile __init__.py hermes_self_improvement/*.py
.venv/bin/python -m pytest tests -q
git diff --check
```

Result: focused related suite `37 passed`; full suite `1009 passed, 2 skipped`; `py_compile` and `git diff --check` passed.
