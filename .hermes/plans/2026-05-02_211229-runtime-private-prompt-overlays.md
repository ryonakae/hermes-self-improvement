# Runtime-Private Prompt Overlays Plan

**Status:** in_progress

## Goal

Split self-improvement prompts into two layers:

1. **Repo-managed base prompts** define the plugin's baseline quality, safety boundaries, schemas, and default behavior.
2. **Runtime-private user/environment prompt overlays** are generated and selected by calibration/GEPA/DSPy, stored outside git under `${HERMES_HOME:-~/.hermes}/self-improvement/`, and used by `improve` when active.

The intended model is:

```text
repo base prompt + repo regression seed
  -> stable plugin quality and public tests

runtime-private prompt candidates + runtime eval cases
  -> user/environment-specific improvement

active runtime prompt overlay
  -> optional override/patch loaded at improve-time
```

This keeps the repository clean and portable while allowing Ryo's local Hermes environment to learn prompt improvements from its own outcomes.

## Current context

### What exists now

Repo-managed prompt/rubric/eval pieces already exist:

- `hermes_self_improvement/planner.py`
  - `_call_planner_llm()` has the skill planner system/user prompt inline.
- `hermes_self_improvement/runner_steps.py`
  - `build_skill_agent_task()` builds the skill editor prompt inline.
- `hermes_self_improvement/scoring.py`
  - proposal scorer LLM prompt/rubric payload is inline.
- `hermes_self_improvement/prompts.py`
  - currently only contains shared skill-vs-memory classification guidance.
- `evals/proposal/rubric.json`
- `evals/proposal/cases.jsonl`
- `defaults/evaluator/*`

Runtime-private calibration/evaluator infrastructure also exists:

- `~/.hermes/self-improvement/evaluator/runtime-eval-cases/`
- `~/.hermes/self-improvement/evaluator/active.json`
- `~/.hermes/self-improvement/cache/dspy/`
- `hermes_self_improvement/calibration.py`
  - builds runtime eval cases from review outcomes.
  - promotes an active evaluator pointer only after regression passes.
- `hermes_self_improvement/gepa_adapter.py` and `dspy_program.py`
  - use Hermes auxiliary model routing and keep DSPy imports lazy.

### Gap

Planner/editor prompts are still effectively **repo-only**. They do not yet read a runtime-private active prompt overlay, and `calibrate` does not yet generate or promote prompt candidates for planner/editor roles.

So the target architecture is only partially implemented:

```text
proposal scorer/evaluator area: partially runtime-private aware
planner/editor prompt area: still repo-inline only
```

## Non-goals

- Do not put user-specific prompt candidates into git.
- Do not make runtime prompt overlays edit repo files.
- Do not let prompt overlays broaden mutation scope.
- Do not change the primary CLI/tool surface beyond existing `improve / calibrate / report / status`.
- Do not add plugin-specific provider credentials. Use Hermes model routing / auxiliary model configuration.
- Do not make hooks call LLM, DSPy, GEPA, or write prompt candidates.
- Do not allow failed/untested prompt candidates to become active.
- Do not make prompt optimization a prerequisite for normal `improve` runs.

## Design principles

### Base prompt belongs in repo

Base prompts should be versioned with code and tests. They define:

- role and safety constraints
- output schema
- allowed decisions/actions
- fail-closed behavior
- default strength/risk interpretation
- compact context budget expectations

Recommended home:

```text
hermes_self_improvement/prompts.py
```

This module should expose functions/constants for:

```python
BASE_PLANNER_PROMPT
BASE_PLANNER_USER_TEMPLATE
BASE_EDITOR_PROMPT_SECTIONS
BASE_SCORER_PROMPT
PROMPT_SCHEMA_VERSION
base_prompt_hash(role)
```

Avoid scattering prompt strings across planner/scoring/runner modules.

### Runtime-private prompt overlays belong under HERMES_HOME

Suggested layout:

```text
${HERMES_HOME}/self-improvement/evaluator/
  active-prompts.json
  prompt-candidates/
    planner/
      20260502Txxxxxx-<hash>.json
    editor/
      20260502Txxxxxx-<hash>.json
    scorer/
      20260502Txxxxxx-<hash>.json
  runtime-eval-cases/
    ...existing...
```

`active-prompts.json` should be a small pointer/index, not a huge payload:

```json
{
  "schema_name": "self_improvement_active_prompt_overlays",
  "schema_version": "1.0",
  "updated_at": "...",
  "roles": {
    "planner": {
      "active": true,
      "candidate_path": ".../prompt-candidates/planner/...json",
      "base_prompt_hash": "...",
      "candidate_hash": "...",
      "regression": {"status": "passed"}
    },
    "editor": {"active": false}
  }
}
```

The candidate file can contain fuller content:

```json
{
  "schema_name": "self_improvement_prompt_candidate",
  "schema_version": "1.0",
  "role": "planner|editor|scorer",
  "created_at": "...",
  "created_by": {"plugin": "hermes-self-improvement", "plugin_version": "..."},
  "base_prompt_hash": "...",
  "candidate_hash": "...",
  "candidate_prompt": {
    "system_addendum": "...",
    "user_addendum": "...",
    "replacement": null
  },
  "rationale": "...",
  "evidence_summary": {...},
  "regression": {...},
  "runtime_private": true
}
```

Prefer additive overlays first (`system_addendum`, `user_addendum`) rather than full replacement. Full replacement is riskier and can be deferred.

## Proposed implementation tasks

### Task 1: Refactor base prompts into a repo-managed prompt registry

Create or expand:

```text
hermes_self_improvement/prompts.py
```

Move prompt text from:

- `planner.py::_call_planner_llm()`
- `runner_steps.py::build_skill_agent_task()`
- optionally `scoring.py::_call_llm_scorer()`

into explicit repo-managed prompt definitions.

Suggested API:

```python
PromptRole = Literal["planner", "editor", "scorer"]

def base_prompt_spec(role: str) -> dict[str, Any]: ...
def prompt_spec_hash(spec: dict[str, Any]) -> str: ...
def render_planner_messages(*, digest: dict[str, Any], overlay: dict[str, Any] | None = None) -> list[dict[str, str]]: ...
def render_editor_instructions(*, skill_name: str, candidate: dict, planner_decision: dict, evidence: list[dict], overlay: dict[str, Any] | None = None) -> str: ...
```

Keep rendering deterministic and unit-testable.

### Task 2: Add runtime prompt overlay store

Add a new module, likely:

```text
hermes_self_improvement/prompt_overlays.py
```

Responsibilities:

- compute runtime paths from config / `_reports_dir(config)`
- read active prompt pointer
- load active overlay for a role
- validate overlay schema
- ignore overlay if base prompt hash mismatches, unless explicitly marked compatible
- write prompt candidate files
- promote active pointer after regression passes
- fail closed to repo base prompt on missing/invalid overlay

Suggested functions:

```python
def prompt_overlay_root(config: dict[str, Any]) -> Path: ...
def active_prompts_path(config: dict[str, Any]) -> Path: ...
def load_active_prompt_overlay(config: dict[str, Any], *, role: str, base_hash: str) -> dict[str, Any] | None: ...
def write_prompt_candidate(config: dict[str, Any], *, role: str, candidate: dict[str, Any]) -> Path: ...
def promote_prompt_candidate(config: dict[str, Any], *, role: str, candidate_path: Path, regression: dict[str, Any]) -> dict[str, Any]: ...
```

Schema validation should reject:

- unknown role
- missing candidate hash
- missing base prompt hash
- absolute paths outside runtime root
- huge prompt content
- secrets / credential-looking content
- overlays that try to modify tool permissions or mutation scope

### Task 3: Wire overlays into `improve`

At runtime:

- planner LLM call loads active planner overlay if valid
- editor task rendering loads active editor overlay if valid
- scorer LLM call may load active scorer overlay if this slice includes scorer

Initial slice can target planner/editor only, because that is the gap from the recent discussion.

Flow:

```text
base prompt spec -> base hash
load active overlay(role, base_hash)
render prompt with overlay addendum if present
record prompt source metadata in artifact/dry-run summary
```

Artifact metadata should include only compact prompt identity, not full prompt text by default:

```json
{
  "prompt_sources": {
    "planner": {
      "base_hash": "...",
      "overlay_active": true,
      "overlay_hash": "...",
      "overlay_path": "..."
    }
  }
}
```

Full prompt text can remain available in candidate files / runtime artifact only if necessary, but avoid returning it through agent tool results.

### Task 4: Add calibration prompt candidate generation

Extend `calibrate` so runtime evidence can produce prompt improvement candidates.

Candidate roles:

- `planner`: when planner decisions are rejected, weak-only choices appear, selected-with-evidence fails, or action-like skips appear.
- `editor`: when editor task fails, mutates wrong target, changes too much, ignores hard stops, or user rejects a skill edit.
- `scorer`: existing scorer/evaluator calibration can continue separately.

A simple first version can be rule/LLM-assisted rather than full GEPA optimization:

```text
collect evidence -> build prompt candidate proposal -> regression gate -> promote active overlay
```

But the direction should explicitly support GEPA/DSPy:

- prompt candidate generation can use DSPy/GEPA optimizer when dependencies are available
- non-available DSPy should fail closed / no-op
- all candidate files are runtime-private

### Task 5: Add regression gates for prompt overlays

Before promotion, run regression checks against:

1. repo-tracked public baseline cases
2. runtime-private eval cases if present
3. hard invariants

Hard invariants:

- output schema still parseable
- `run_editor` without evidence still normalizes to skip
- weak-only evidence should not be selected unless explicitly justified by test case
- destructive/sensitive/delete/merge/archive remains human_review/skip
- no broad mutation scope changes
- compact tool result remains compact

Regression result should be stored in candidate and active pointer metadata.

### Task 6: Add CLI/tool visibility without bloating context

`calibrate --dry-run` should show compact prompt-candidate status:

```text
Prompt overlays:
- planner: candidate yes/no, would promote yes/no, reason
- editor: candidate yes/no, would promote yes/no, reason
```

`self_improvement_calibrate` tool result should include compact counts/paths only:

```json
"prompt_overlays": {
  "planner": {"candidate": true, "promoted": false, "candidate_path": "..."},
  "editor": {"candidate": false}
}
```

Do not return full prompt candidate content through tool result.

`improve --dry-run` should show active prompt identity compactly:

```text
Prompts:
- planner: repo base + runtime overlay <hash> / or repo base only
- editor: repo base only
```

### Task 7: Tests

Add tests before implementation.

Suggested files:

- `tests/test_prompts.py`
- `tests/test_prompt_overlays.py`
- `tests/test_calibration.py`
- `tests/test_skill_planner.py`
- `tests/test_runner_steps.py`
- `tests/test_plugin_tools.py`

Test cases:

1. Base planner/editor prompts render from `prompts.py`, not inline duplicated strings.
2. Base prompt hash is stable and changes when prompt text changes.
3. Missing active overlay falls back to base prompt.
4. Invalid overlay fails closed and records reason.
5. Overlay with mismatched base hash is ignored.
6. Overlay content is capped and redacted / rejects secret-like content.
7. Active planner overlay addendum appears in planner messages.
8. Active editor overlay addendum appears in editor task instructions.
9. `calibrate --dry-run` reports prompt candidate preview without writing active pointer.
10. `calibrate` with failed regression writes no active overlay.
11. `calibrate` with passed regression promotes active prompt pointer under runtime root only.
12. compact tool result contains candidate path/hash, not full prompt text.
13. `improve --dry-run` artifact records prompt source metadata.
14. Existing full tests still pass.

## Files likely to change

Implementation:

- `hermes_self_improvement/prompts.py`
- `hermes_self_improvement/prompt_overlays.py` new
- `hermes_self_improvement/planner.py`
- `hermes_self_improvement/runner_steps.py`
- `hermes_self_improvement/scoring.py` maybe later / optional
- `hermes_self_improvement/calibration.py`
- `hermes_self_improvement/cli.py`
- `hermes_self_improvement/tool_handlers.py`
- `hermes_self_improvement/setup_runtime.py` if directories/checks need to know prompt-candidates

Docs:

- `README.md`
- `skills/operations/SKILL.md`
- `skills/operations/references/architecture.md`
- `.hermes/plans/README.md`

Tests:

- `tests/test_prompts.py` new
- `tests/test_prompt_overlays.py` new
- update existing tests listed above

## Validation

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
bin/hermes-self-improve status
bin/hermes-self-improve calibrate --dry-run
bin/hermes-self-improve improve --dry-run
bin/hermes-self-improve improve --dry-run --json
```

Plugin registration smoke:

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

Compact tool result smoke:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY - <<'PY'
from hermes_self_improvement.tool_handlers import _handle_self_improvement_improve_tool, _handle_self_improvement_calibrate_tool
import json
for fn, args in [(_handle_self_improvement_improve_tool, {"dry_run": True}), (_handle_self_improvement_calibrate_tool, {"dry_run": True})]:
    payload = json.loads(fn(args))
    print(payload["operation"], len(str(payload)))
PY
```

Also run:

```bash
git diff --check
```

## Success criteria

After implementation:

```text
repo base prompt exists and is tested
runtime-private prompt candidate store exists
active prompt overlay loading works with fail-closed fallback
planner/editor can use active runtime overlays
calibrate can preview prompt candidates
promotion requires regression pass
agent tool results stay compact
runtime prompt files are outside git
```

Operationally, `improve --dry-run` should make it obvious whether it used:

```text
planner: repo base only
planner: repo base + runtime overlay <hash>
editor: repo base only
editor: repo base + runtime overlay <hash>
```

## Risks and mitigations

### Risk: prompt overlay changes safety policy

Mitigation:

- overlays are additive initially
- schema validation rejects tool-permission / mutation-scope language where possible
- hard invariant regression before promotion
- base prompt remains fallback

### Risk: context growth

Mitigation:

- candidate files hold full content
- tool result and summaries include only hashes/paths/status
- overlay addenda have length caps

### Risk: GEPA/DSPy path becomes mandatory

Mitigation:

- keep lazy import
- if DSPy unavailable, calibration returns no-op / candidate generation skipped
- normal `improve` uses base prompt or existing active overlay without optimizer dependency

### Risk: base prompt hash mismatch disables useful overlays after repo update

Mitigation:

- fail closed by default
- artifact reports `overlay_ignored_base_hash_mismatch`
- future calibrate can regenerate overlay against the new base prompt

### Risk: user-specific data leaks into repo

Mitigation:

- all prompt candidates and runtime eval cases under `${HERMES_HOME}/self-improvement/evaluator/`
- tests assert candidate paths are outside repo
- docs warn not to commit runtime prompt candidates

## Implementation progress

### 2026-05-02 Slice 1 completed

Implemented the first slice: repo prompt registry + runtime overlay loading + improve-time use.

- Added repo-managed planner/editor prompt registry in `hermes_self_improvement/prompts.py` with deterministic rendering and base hashes.
- Added runtime-private overlay store in `hermes_self_improvement/prompt_overlays.py` under `${HERMES_HOME:-~/.hermes}/self-improvement/evaluator/`.
- Active overlay loading fails closed on missing/invalid schema, role mismatch, base hash mismatch, oversized content, or secret-like content.
- Planner and editor rendering now use base prompt + optional active runtime overlay.
- `improve` artifacts, CLI summary, and compact agent tool result expose prompt source/hash/path metadata only; full prompt text is not returned to LLM-facing tool results.
- Added tests for prompt registry, overlay validation/promotion, planner/editor overlay usage, artifact metadata, and compact tool result metadata.

Still pending for Slice 2:

- `calibrate` prompt candidate generation for planner/editor.
- GEPA/DSPy candidate optimization path.
- Regression-gated promotion workflow beyond the low-level `promote_prompt_candidate()` primitive.
- `calibrate --dry-run` prompt candidate preview.

## Suggested commit split

```text
feat: add repo prompt registry
feat: add runtime prompt overlay store
feat: load active planner and editor prompt overlays
feat: preview and promote prompt overlay candidates through calibration
fix: expose prompt overlay status compactly
```

If implementation gets large, do it in two slices:

1. Prompt registry + overlay loading + improve-time use.
2. Calibration/GEPA/DSPy candidate generation + promotion.

The first slice gives the architecture immediately; the second slice makes it self-improving.
