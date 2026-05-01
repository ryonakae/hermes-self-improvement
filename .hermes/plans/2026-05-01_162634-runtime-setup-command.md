# Runtime Setup Command Implementation Plan

> **For Hermes:** Implement directly in TDD slices. Keep the primary agent/tool surface at `status / report / improve / calibrate`; `setup` is CLI-only bootstrap/readiness, not a self-improvement runner.

**Goal:** Add an idempotent `bin/hermes-self-improve setup` command that creates a clean, current runtime layout under `${HERMES_HOME:-~/.hermes}/self-improvement`, seeds the evaluator/scorer defaults required by current code, and makes first install/readiness explicit. The existing local runtime contents may be deleted/reset during implementation verification.

**Current repo:** `/Users/ryo.nakae/.hermes/plugins/hermes-self-improvement`

**Runtime root:** `${HERMES_HOME:-~/.hermes}/self-improvement`

**Non-goals:** Do not add setup as an agent tool. Do not reintroduce `plan/apply/rollback/outcome` surfaces. Do not run LLM/GEPA optimization/memory mutation/skill mutation from setup. Do not make runtime root user-configurable beyond the existing private `_self_improvement_root` test hook.

---

## Target runtime layout

The setup command should create this shape:

```text
${HERMES_HOME}/self-improvement/
  state/
    events.jsonl                  # append-only observer telemetry; create empty if absent
    install.json                  # setup metadata and seeded asset hashes
  daily/                          # existing human daily/report markdown output
  runs/                           # improve runner artifacts
  evidence/                       # evidence packs written by improve/report pipeline
  outcomes/                       # review outcome artifacts read by calibration
  ledgers/                        # calibration ledgers and future approval-like audit artifacts
  evaluator/
    active.json                   # runtime pointer/state for active evaluator/scorer
    defaults/
      proposal-rubric.json        # copied from repo default seed
      proposal-cases.jsonl        # copied from repo public eval seed
      proposal-evaluator.json     # copied from repo default evaluator seed
    programs/                     # compiled DSPy/GEPA program candidates
    candidates/                   # non-active evaluator/scorer candidate metadata
    runtime-eval-cases/           # user/runtime-private eval cases; never repo-tracked
  cache/
    dspy/                         # DSPy cache controlled by DSPY_CACHEDIR
```

### Directory rationale

- `state/` is only durable observer/install state.
- `runs/`, `evidence/`, `daily/`, `outcomes/`, `ledgers/` stay at root because current code already reads/writes them through `_reports_dir(config)`.
- `evaluator/defaults/` holds runtime copies of repo defaults so runtime can be self-contained and hash-checkable.
- `evaluator/active.json` is the active runtime pointer. It may point to a default DSPy evaluator contract or to a compiled GEPA/DSPy program, but the directory name should describe the role, not the optimizer implementation.
- `evaluator/programs/` keeps the current compiled program output path after renaming the old `gepa/programs` path.
- `evaluator/runtime-eval-cases/` keeps user/private evidence out of repo `evals/`.

---

## Repo-tracked default assets

Add explicit repo defaults instead of relying only on code constants:

```text
defaults/
  evaluator/
    proposal-evaluator.json
    proposal-rubric.json
    proposal-cases.jsonl
```

Seed sources:

- `proposal-rubric.json`: copy current `evals/proposal/rubric.json` content.
- `proposal-cases.jsonl`: copy current `evals/proposal/cases.jsonl` content.
- `proposal-evaluator.json`: new small JSON describing the default evaluator contract:
  - schema name/version
  - evaluator id/version
  - program name: `ProposalScoringDspyProgram`
  - scorer target: proposal scoring
  - advisory-only safety flags
  - expected input fields: `proposal_json`, `findings_json`, `rubric_json`
  - output contract: score/risk/recommendation/confidence/rationale/auto_apply=false
  - prompt/rubric source path or embedded prompt text if needed

Keep `evals/proposal/*` as public regression fixtures. The new `defaults/evaluator/*` are install/runtime seed assets. If duplication feels ugly, tests should enforce the copied defaults are equivalent to `evals/proposal/*` until we intentionally diverge.

---

## CLI behavior

Add:

```bash
bin/hermes-self-improve setup
bin/hermes-self-improve setup --check
bin/hermes-self-improve setup --reset
bin/hermes-self-improve setup --json
```

Semantics:

- `setup`: create missing dirs/files and seed defaults if absent. Idempotent. Does not overwrite existing active evaluator/default copies unless a file is missing or invalid enough to fail readiness.
- `setup --check`: read-only readiness check. Must not create or modify files.
- `setup --reset`: delete/recreate `${HERMES_HOME}/self-improvement` contents, then seed from repo defaults. This is the explicit destructive mode. Use it during this implementation because the current local runtime content may be discarded.
- `setup --json`: print full payload for tests/automation.

Default human output should be short:

```text
hermes-self-improvement setup

Runtime:
- root: /Users/ryo.nakae/.hermes/self-improvement
- initialized: yes
- reset: no
Evaluator:
- active pointer: .../evaluator/active.json
- default evaluator: seeded
- rubric/cases: seeded
Readiness:
- writable: yes
- event log: ready
- DSPy cache: ready
```

---

## Active evaluator pointer contract

Create `evaluator/active.json` on setup when absent:

```json
{
  "schema_name": "self_improvement_active_evaluator_pointer",
  "schema_version": "1.0",
  "created_by": {
    "plugin": "hermes-self-improvement",
    "plugin_version": "0.1.0"
  },
  "created_at": "...",
  "updated_at": "...",
  "source": "repo_default_setup",
  "mode": "dspy_program_eval",
  "evaluator_id": "proposal-evaluator-default-v1",
  "evaluator_path": ".../evaluator/defaults/proposal-evaluator.json",
  "rubric_path": ".../evaluator/defaults/proposal-rubric.json",
  "eval_cases_path": ".../evaluator/defaults/proposal-cases.jsonl",
  "compiled_program_path": null,
  "hashes": {
    "evaluator": "sha256:...",
    "rubric": "sha256:...",
    "eval_cases": "sha256:..."
  },
  "safety": {
    "advisory_only": true,
    "auto_apply_grants_permission": false,
    "promotion_requires_regression_gate": true
  }
}
```

Important: current `gepa_adapter._resolve_compiled_program_path()` expects `compiled_program_path` or `candidate_path` for `compiled_program_eval`. For `dspy_program_eval`, the pointer is readiness/metadata only. Do not force compiled mode to use a non-compiled default.

---

## Implementation tasks

## Task 1: Add setup module and tests first

**Objective:** Define runtime layout and setup behavior without touching existing runner behavior.

**Files:**
- Add: `hermes_self_improvement/setup_runtime.py`
- Add: `tests/test_setup_runtime.py`

**Tests:**
1. `setup --check` equivalent reports missing runtime as not initialized and writes nothing.
2. normal setup creates all target directories and files under isolated `_self_improvement_root`.
3. normal setup is idempotent and preserves existing `evaluator/active.json`.
4. `reset=True` removes stale files under the isolated runtime root and recreates only the target layout/defaults.
5. seeded runtime defaults have hashes recorded in both `state/install.json` and `evaluator/active.json`.
6. setup never imports DSPy and never calls mutation/scoring backends.

**Core functions:**

```python
def runtime_layout(config: dict[str, Any]) -> dict[str, Path]: ...
def check_runtime_setup(config: dict[str, Any]) -> dict[str, Any]: ...
def run_setup(config: dict[str, Any], *, check: bool = False, reset: bool = False) -> dict[str, Any]: ...
```

Use existing `observer._self_improvement_root(config)` / `_event_path(config)` / `_reports_dir(config)` semantics rather than inventing a second root resolver.

---

## Task 2: Add repo default evaluator assets

**Objective:** Make first-install evaluator/scorer defaults explicit and versioned.

**Files:**
- Add: `defaults/evaluator/proposal-evaluator.json`
- Add: `defaults/evaluator/proposal-rubric.json`
- Add: `defaults/evaluator/proposal-cases.jsonl`
- Modify: `tests/test_gepa_eval_assets.py` or add `tests/test_default_evaluator_assets.py`

**Tests:**
1. default files exist and parse.
2. rubric has expected `version` and safety fields.
3. cases JSONL is non-empty and every case has `proposal`, `findings`, `expected`.
4. default rubric/cases are equivalent to current `evals/proposal/*` until intentionally changed.
5. evaluator asset has advisory-only safety and the current role/output contract.

---

## Task 3: Wire CLI `setup`

**Objective:** Expose setup through wrapper CLI only.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Modify: `tests/test_cli_surface.py`

**Steps:**
1. Import `run_setup`.
2. Add subparser:
   ```python
   p_setup = sub.add_parser("setup", help="Initialize self-improvement runtime files")
   p_setup.add_argument("--check", action="store_true")
   p_setup.add_argument("--reset", action="store_true")
   p_setup.add_argument("--json", action="store_true", dest="as_json")
   _add_config_argument(p_setup)
   p_setup.set_defaults(func=_handle_cli)
   ```
3. In `_handle_cli`, handle `cmd == "setup"` before status/report/improve/calibrate.
4. Render concise text and JSON payload.
5. Do not register a new plugin tool. `plugin.yaml`, `schemas.py`, `tool_handlers.py`, and primary tool tests should remain four-tool only.

---

## Task 4: Make `status` setup-aware

**Objective:** First-install problems should be visible before running `improve` or `calibrate`.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Modify: status tests, likely `tests/test_cli_surface.py` or new setup tests

**Steps:**
1. Add `setup_status = check_runtime_setup(config)` to status payload.
2. Human status should include a short runtime setup section:
   ```text
   Runtime setup:
   - initialized: yes/no
   - active evaluator: ready/missing/invalid
   - default assets: ready/missing/changed
   ```
3. If not initialized, show actionable next command:
   ```text
   Next: bin/hermes-self-improve setup
   ```
4. Do not make status mutate files.

---

## Task 5: Align calibration/evaluator reads with setup artifacts

**Objective:** Current paths still work, but missing setup becomes explicit and actionable.

**Files:**
- Modify: `hermes_self_improvement/calibration.py`
- Modify: `hermes_self_improvement/gepa_adapter.py` only if needed
- Modify: calibration/GEPA tests

**Steps:**
1. `run_calibration()` should include setup status in payload.
2. If active evaluator pointer/default assets are missing, calibration should not crash obscurely. It should return/report a clear `setup_required` or raise an actionable error only in paths that truly require the artifact.
3. Keep `dspy_program_eval` functional without a compiled artifact.
4. Keep `compiled_program_eval` fail-closed if no compiled program is active.
5. Do not make calibration auto-run setup; operator should run `setup` explicitly.

---

## Task 6: Reset current local runtime and verify real setup

**Objective:** Use the permission granted for this local runtime to prove a fresh install works.

**Commands:**

```bash
# after tests pass and setup command exists
rm -rf /Users/ryo.nakae/.hermes/self-improvement
bin/hermes-self-improve setup --json | python -m json.tool
bin/hermes-self-improve status
bin/hermes-self-improve report --since-hours 24 --json | python -m json.tool >/tmp/self_improve_report_after_setup.json
bin/hermes-self-improve calibrate --dry-run --json | python -m json.tool >/tmp/self_improve_calibrate_after_setup.json
```

Expected:
- runtime root recreated with the target layout
- status shows setup initialized
- report works with zero/empty telemetry if no events exist
- calibrate dry-run returns no candidate or setup-ready payload, not a missing-file crash

Use `rm -rf` only for `/Users/ryo.nakae/.hermes/self-improvement` after verifying the path exactly. Do not delete plugin repo files.

---

## Task 7: Docs and operational skill update

**Objective:** Make install/bootstrap discoverable without bloating the primary surface.

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `skills/operations/SKILL.md`
- Possibly modify: `skills/operations/references/operations.md`

**Content:**
- Add setup to quick-start/install section.
- Document runtime layout.
- State that `setup` is safe bootstrap and `--reset` is destructive.
- Keep primary tool surface described as exactly four tools.
- Mention default evaluator assets live in repo `defaults/evaluator/` and runtime copies live in `${HERMES_HOME}/self-improvement/evaluator/defaults/`.

---

## Task 8: Full validation

**Commands:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
bin/hermes-self-improve setup --check --json | python -m json.tool >/tmp/self_improve_setup_check.json
bin/hermes-self-improve status
bin/hermes-self-improve improve --dry-run --json | python -m json.tool >/tmp/self_improve_dry_run_after_setup.json
bin/hermes-self-improve calibrate --dry-run --json | python -m json.tool >/tmp/self_improve_calibrate_after_setup.json
git diff --check
```

Plugin registration check if CLI/parser files changed:

```bash
PY=${PYTHON:-python3}
$PY - <<'PY'
from hermes_cli.plugins import discover_plugins, get_plugin_manager
import json

discover_plugins(force=True)
info = [p for p in get_plugin_manager().list_plugins() if p['name'] == 'hermes-self-improvement']
print(json.dumps(info, ensure_ascii=False, indent=2))
PY
```

Expected: plugin enabled, error null, tools remain 4.

---

## Open decisions to keep simple

Recommended defaults for this implementation:

1. **Command name:** `setup`, not `init`, because it matches Hermes user-facing vocabulary.
2. **Tool exposure:** CLI-only. Do not add `self_improvement_setup` tool unless later explicitly requested.
3. **Reset flag:** `--reset`, not `--force`, because the danger is specific and obvious.
4. **Runtime default copies:** overwrite only in `--reset`; otherwise preserve local active pointer and report drift.
5. **Compiled evaluator:** do not fabricate compiled defaults. The default active pointer is metadata for `dspy_program_eval`; compiled mode still requires a real compiled program artifact.
