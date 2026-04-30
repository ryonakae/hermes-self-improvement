# Obsolete internal legacy cleanup plan

## Goal

Continue the Curator-aligned self-improvement runner cleanup after the public surface has already been reduced to four commands/tools. Remove or shrink legacy internal apply-plan / apply-engine / rollback / outcome helpers without reintroducing `plan`, `apply`, `rollback`, `outcome`, `--execute`, or `--items` as user-facing surfaces.

## Current context

- Primary CLI surface is already `status`, `report`, `improve`, `calibrate`.
- Primary plugin tools are already `self_improvement_status`, `self_improvement_report`, `self_improvement_improve`, `self_improvement_calibrate`.
- Historical modules still exist because older report/calibration readers and tests reference old artifacts:
  - `hermes_self_improvement/apply_plan.py`
  - `hermes_self_improvement/apply_engine.py`
  - `hermes_self_improvement/ledger.py`
  - `hermes_self_improvement/recovery_engine.py`
  - `hermes_self_improvement/drift.py`
  - `hermes_self_improvement/drift_adjudicator.py`
  - `hermes_self_improvement/verification.py`
  - `hermes_self_improvement/outcome_store.py`
  - `hermes_self_improvement/next_actions.py`
- `skill_snapshot.py` is not purely legacy: current skill runner safety gates still use it through `mutation_agent.py`.

## Non-goals

- Do not restore legacy primary surfaces.
- Do not delete historical artifact readers blindly if calibration/report still need them.
- Do not reintroduce rollback as a product feature.
- Do not direct-edit memory stores or skill files outside official tool-mediated paths.

## Proposed slices

### Slice 1: stop stale next-action guidance

Problem: `next_actions.py` still emits deleted commands such as `apply ... --execute` and `outcome --from-plan-item ...`. Even if legacy artifacts remain readable, reports must not tell the operator to run removed commands.

Files:

- `hermes_self_improvement/next_actions.py`
- `hermes_self_improvement/cli.py` if needed
- `tests/test_next_actions.py`
- `tests/test_report_integration.py`

Steps:

1. Keep `render_next_actions()` as a generic renderer.
2. Change `build_next_actions_for_apply_preview()` / `build_next_actions_for_plan()` / `build_next_actions_for_improve()` so they only recommend current four-command workflows:
   - inspect historical artifact / latest run artifact
   - `bin/hermes-self-improve improve --dry-run`
   - `bin/hermes-self-improve improve`
   - `bin/hermes-self-improve report --since-hours 24`
3. Remove command strings containing `apply`, `outcome`, `--execute`, or `--from-plan-item`.
4. Update tests to assert the absence of legacy command guidance.

Validation:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile hermes_self_improvement/next_actions.py hermes_self_improvement/cli.py tests/test_next_actions.py tests/test_report_integration.py
$PY -m pytest tests/test_next_actions.py tests/test_report_integration.py tests/test_cli_surface.py -q
```

### Slice 2: remove unused runtime imports/re-exports

Files:

- `hermes_self_improvement/cli.py`
- `hermes_self_improvement/__init__.py`
- tests that import package-level legacy symbols

Steps:

1. Remove unused imports from `cli.py`:
   - `apply_plan`, `rollback_apply_ledger`
   - `build_apply_plan`, `write_apply_plan`
   - unused outcome writer constants.
2. Remove package-level re-exports from `__init__.py` that only support removed primary surfaces.
3. Keep reader functions still used by `report`, `status`, and `calibration`.

Validation:

```bash
$PY -m py_compile __init__.py hermes_self_improvement/*.py tests/*.py
$PY -m pytest tests -q
```

### Slice 3: delete dead apply-plan/apply-engine modules and legacy-only tests

Likely delete after Slice 2 proves imports are gone:

- `hermes_self_improvement/apply_plan.py`
- `hermes_self_improvement/apply_engine.py`
- `hermes_self_improvement/ledger.py`
- `hermes_self_improvement/drift.py`
- `hermes_self_improvement/drift_adjudicator.py`

Likely delete or rewrite tests:

- `tests/test_apply_plan.py`
- `tests/test_apply_engine.py`
- `tests/test_evaluator_plan.py`
- legacy apply/rollback sections in `tests/test_mutation_policy.py`, `tests/test_ledger_report.py`, and `tests/test_skill_lifecycle_agent.py`

Keep historical artifact reader tests only where they prove `report` / `calibration` can read old runtime artifacts safely.

### Slice 4: shrink partial legacy modules

- Move or retain only `memory_rollback_status()` from `recovery_engine.py`; delete rollback planning/execution paths.
- Move or retain only `merge_judge_status()` from `verification.py`; delete apply-phase merge verification paths.
- Keep `outcome_store.py` read/summarize/infer functions for calibration/report compatibility; remove writer-only legacy command support when no tests/runtime need it.
- Keep `skill_snapshot.py` because current skill mutation safety uses it.

## Final verification

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py tests/*.py
$PY -m pytest tests -q
python - <<'PY'
from hermes_cli.plugins import discover_plugins, get_plugin_manager
import json
try:
    discover_plugins(force=True)
except TypeError:
    discover_plugins()
pm = get_plugin_manager()
plugins = getattr(pm, '_plugins', {})
plugin = plugins.get('hermes-self-improvement')
print(json.dumps({
    'enabled': bool(plugin and getattr(plugin, 'enabled', False)),
    'error': getattr(plugin, 'error', None) if plugin else 'not found',
    'tools': sorted(getattr(pm, '_plugin_tool_names', set()) & {
        'self_improvement_status',
        'self_improvement_report',
        'self_improvement_improve',
        'self_improvement_calibrate',
    }),
}, ensure_ascii=False))
PY
bin/hermes-self-improve status
bin/hermes-self-improve improve --dry-run
bin/hermes-self-improve calibrate --dry-run
bin/hermes-self-improve report --since-hours 24
```

Expected:

- tests pass;
- plugin still exposes exactly four tools;
- normal output does not mention legacy command paths;
- old runtime artifacts can still be read where intentionally supported;
- working tree is clean after commit/push.
