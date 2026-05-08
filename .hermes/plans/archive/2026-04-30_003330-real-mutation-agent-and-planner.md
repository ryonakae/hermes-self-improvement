# Real Mutation Agent Backend and Planner Implementation Plan

> **Status: completed / implemented with follow-up hardening as of 2026-04-30.** The real backend, runtime resolver readiness, tool trace verification, protocol hardening, merge planner readiness/failure semantics, smoke isolation, and memory rollback follow-up have landed. This file is historical; use `.hermes/plans/README.md` for current direction.

> **For Hermes:** Historical implementation record. Do not treat unchecked boxes below as remaining work unless a newer plan explicitly reopens an item.

**Goal:** Make `hermes-self-improvement` execute semantic skill mutations in real Hermes runtime, not only with injected test backends, while preserving bounded tools, ledger-bound rollback, and fail-closed behavior.

**Architecture:** Keep the current split: apply/ledger/rollback stay plugin-owned; semantic forward mutation is delegated to a bounded skills-only mutation backend; merge safety is evaluated by a Hermes auxiliary-model planner; memory rollback remains fail-closed unless store semantics are proven. The next implementation must remove accidental “works only in tests” gaps without adding broad terminal/file/git fallback.

**Tech Stack:** Python plugin under `hermes_self_improvement/`, Hermes plugin tool registration, Hermes auxiliary model path via `agent.auxiliary_client.call_llm`, official tool-mediated skill operations via `skill_manage`, pytest, wrapper CLI `bin/hermes-self-improve`.

**Model config convention:** Mutation agent model settings must follow the existing `model.llm` / `model.gepa` shape as `model.mutation`, not `mutation.model`. The `mutation.*` section is reserved for backend/runtime controls such as `backend`, `enabled`, `max_tool_calls`, and `max_iterations`. `model.mutation` owns `provider`, `model`, `base_url`, `api_key`, `timeout`, `max_tokens`, and `extra_body`. Merge planner should use `model.mutation` as well unless a later plan proves a separate `model.planner` is needed.

---

## Current State

Repo: `/Users/ryo.nakae/.hermes/plugins/hermes-self-improvement`

Latest checked state:

- `git status --short`: clean
- Latest commits include:
  - `2eadad7 docs(self-improvement): document mutation recovery workflow`
  - `a4e800b test(self-improvement): document memory restore safety boundaries`
  - `2ec9f51 refactor(self-improvement): isolate legacy skill mutation paths`
  - `58cbae4 feat(self-improvement): support semantic skill rename and merge`
  - `f4e1ceb feat(self-improvement): execute semantic skill mutation tasks`
- Validation already passes:
  - `.venv/bin/python -m py_compile __init__.py hermes_self_improvement/*.py`
  - `.venv/bin/python -m pytest tests -q` → `239 passed`
  - `bin/hermes-self-improve status` → OK

Implemented but only partially real:

- `skill_agent_task` planning exists.
- `MutationAgentRunner` exists.
- `apply_engine` executes `skill_agent_task` only when config includes `_mutation_agent_backend`.
- Tests inject fake `_mutation_agent_backend` and fake `_merge_planner`.
- Without injected backend, real apply fails closed with `mutation_agent_unavailable`.
- Default merge planner fails closed with `merge_planner_unavailable`.
- Memory rollback intentionally fails closed with `unsupported_pending_store_validation`.

The implementation goal is **not** to make everything auto-apply. It is to make explicitly executed semantic mutation tasks actually runnable through a bounded real backend.

---

## Non-Negotiable Safety Constraints

- Do not modify Hermes core.
- Do not add new Hermes core `skill_manage` actions.
- Do not reintroduce forward direct file mutation.
- Do not shell out to terminal/file/git/direct filesystem to perform skill mutation.
- Do not mutate plugin README/AGENTS/config as self-improvement targets.
- Do not broaden the mutation agent tool surface beyond `skills_list`, `skill_view`, `skill_manage`.
- If a bounded skills-only runtime cannot be built, return `mutation_agent_unavailable` and leave item failed/needs-review.
- Rollback must not invoke the mutation agent.
- Rollback remains deterministic `ledger_bound_restore` only.
- External memory provider rollback must not touch provider internals directly.
- Sensitive memory deletion must not be restored by re-adding sensitive content.

---

## Desired End State

After this plan is implemented:

1. `apply_plan(..., execute=True)` can execute `skill_agent_task` without test-only `_mutation_agent_backend`, when runtime has a safe backend.
2. The real backend performs mutations through official skill tools only.
3. Backend output is structured JSON and is verified exactly like the fake backend path.
4. Merge tasks have a real auxiliary-model planner, not only injected `_merge_planner`.
5. If the real backend or planner is unavailable, the item fails closed with a clear reason.
6. CLI/tool output makes unsupported vs failed vs executed states obvious.
7. There is at least one safe smoke test path that proves a real local mutable skill can be improved and rolled back without touching production skills.
8. Memory rollback remains explicitly documented as unsupported, unless a separate proof task establishes safe store validation.

---

## Implementation Strategy

Build this in small slices:

1. **Runtime capability discovery** — detect whether the plugin is running inside a Hermes runtime that can provide tool-call execution.
2. **Tool-call backend interface** — replace test-only backend expectations with a structured backend that can call `skills_list`, `skill_view`, `skill_manage`.
3. **Real skill mutation agent** — use Hermes auxiliary model to produce a tool plan, execute only allowed skill tools, loop with strict limits, and return structured JSON.
4. **Real merge planner** — use Hermes auxiliary model to planner merge completeness/safety with strict JSON parsing.
5. **Wire backend into config/application** — `apply_engine` obtains the backend from config/runtime rather than only `_mutation_agent_backend` tests.
6. **Smoke tests and docs** — prove real behavior on temporary local skills, update docs/operations skill.
7. **Keep memory rollback separate** — write a short follow-up plan or explicit non-goal; do not sneak in unsafe memory restore.

The key design choice: **do not ask an unconstrained LLM to “do the work.”** The real backend should be a small tool-loop that exposes only three tool functions and verifies every requested tool call before executing it.

---

## Task 1: Add a Mutation Backend Contract Module

**Objective:** Make the backend contract explicit and separate from `mutation_agent.py`, so real and fake backends share the same shape.

**Files:**

- Create: `hermes_self_improvement/mutation_backend.py`
- Modify: `hermes_self_improvement/mutation_agent.py`
- Test: `tests/test_mutation_backend.py`

**Step 1: Write failing tests**

Create `tests/test_mutation_backend.py` with tests for:

- allowed tool names are exactly `skills_list`, `skill_view`, `skill_manage`
- backend result must include `success: bool`
- backend result must include `used_tools`, `changed_skills`, `created_skills`, `deleted_skills`, `verification_notes`, `rollback_hints` on success
- invalid JSON returns `mutation_agent_result_not_json`
- tool call count limit is enforced by backend config object

Expected test names:

```python
def test_backend_contract_allows_only_skill_tools(): ...
def test_backend_contract_rejects_non_json_result(): ...
def test_backend_contract_requires_success_schema_fields(): ...
def test_backend_limits_are_fail_closed(): ...
```

**Step 2: Run tests to verify failure**

```bash
.venv/bin/python -m pytest tests/test_mutation_backend.py -q
```

Expected: fail because module does not exist.

**Step 3: Implement minimal module**

`hermes_self_improvement/mutation_backend.py` should define:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

ALLOWED_MUTATION_AGENT_TOOLS = {"skills_list", "skill_view", "skill_manage"}

@dataclass(frozen=True)
class MutationBackendLimits:
    max_tool_calls: int = 8
    max_iterations: int = 6
    timeout_seconds: int = 45

class MutationBackend(Protocol):
    def run(self, prompt: str, task: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any] | str:
        ...
```

Move `ALLOWED_MUTATION_AGENT_TOOLS` from `mutation_agent.py` into this module and import it there. Keep backward-compatible behavior.

**Step 4: Run tests**

```bash
.venv/bin/python -m pytest tests/test_mutation_backend.py tests/test_mutation_agent.py -q
```

Expected: pass.

**Step 5: Commit**

```bash
git add hermes_self_improvement/mutation_backend.py hermes_self_improvement/mutation_agent.py tests/test_mutation_backend.py
git commit -m "refactor(self-improvement): define mutation backend contract"
```

---

## Task 2: Add Safe Tool Executor Abstraction for Skill Tools

**Objective:** Provide a small executor that can call only `skills_list`, `skill_view`, and `skill_manage`, while remaining testable without Hermes runtime.

**Files:**

- Modify: `hermes_self_improvement/mutation_backend.py`
- Modify: `hermes_self_improvement/mutation_worker.py`
- Test: `tests/test_mutation_backend.py`

**Step 1: Write failing tests**

Add tests:

```python
def test_skill_tool_executor_rejects_disallowed_tool(): ...
def test_skill_tool_executor_calls_injected_skill_manage(): ...
def test_skill_tool_executor_fails_closed_when_tool_unavailable(): ...
def test_skill_tool_executor_redacts_large_outputs(): ...
```

Use injected callables for unit tests:

```python
executor = SkillToolExecutor(
    skills_list_fn=lambda **kwargs: {"success": True, "skills": []},
    skill_view_fn=lambda **kwargs: {"success": True, "content": "..."},
    skill_manage_fn=lambda **kwargs: {"success": True},
)
```

**Step 2: Implement `SkillToolExecutor`**

Add a class:

```python
@dataclass
class SkillToolExecutor:
    skills_list_fn: Callable[..., Any] | None = None
    skill_view_fn: Callable[..., Any] | None = None
    skill_manage_fn: Callable[..., Any] | None = None

    def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        ...
```

Rules:

- reject any tool outside `ALLOWED_MUTATION_AGENT_TOOLS`
- normalize exceptions into `{success: False, error: "tool_call_failed", reasons: [...]}`
- if callable is missing, return `{success: False, error: "tool_unavailable", tool: tool}`
- do not use terminal/file/git fallback
- truncate or summarize large tool outputs before returning them to model loop

**Step 3: Wire existing skill manage executor**

Reuse `execute_skill_manage_operation()` for `skill_manage` where possible. Do **not** bypass `skill_manage` by editing files.

For `skills_list` and `skill_view`, prefer injected Hermes tool callables when runtime can supply them. If unavailable, fail closed for real backend. Do not synthesize these by reading skill files directly.

**Step 4: Run tests**

```bash
.venv/bin/python -m pytest tests/test_mutation_backend.py tests/test_mutation_policy.py -q
```

**Step 5: Commit**

```bash
git add hermes_self_improvement/mutation_backend.py hermes_self_improvement/mutation_worker.py tests/test_mutation_backend.py
git commit -m "feat(self-improvement): add bounded skill tool executor"
```

---

## Task 3: Implement Auxiliary-Model Tool Loop Backend

**Objective:** Implement a real backend that uses Hermes auxiliary model to select allowed tool calls, executes only those skill tools, and returns final structured JSON.

**Files:**

- Modify: `hermes_self_improvement/mutation_backend.py`
- Modify: `hermes_self_improvement/mutation_agent.py`
- Test: `tests/test_mutation_backend.py`

**Step 1: Write failing tests with fake LLM**

Add tests for a fake model function that returns JSON steps:

```python
def test_auxiliary_backend_executes_allowed_skill_tool_sequence(): ...
def test_auxiliary_backend_rejects_disallowed_tool_request(): ...
def test_auxiliary_backend_stops_after_max_iterations(): ...
def test_auxiliary_backend_requires_final_json_result(): ...
def test_auxiliary_backend_records_used_tools_from_actual_calls_not_only_self_report(): ...
```

Fake model protocol:

```python
def fake_llm(messages, **kwargs):
    return '{"type":"tool_call","tool":"skill_view","args":{"name":"demo"}}'
```

Then final response:

```json
{
  "type": "final",
  "success": true,
  "changed_skills": ["demo"],
  "created_skills": [],
  "deleted_skills": [],
  "verification_notes": ["patched demo"],
  "rollback_hints": []
}
```

**Step 2: Define backend protocol**

Use a simple loop:

1. Build system message from task prompt.
2. Ask model for JSON response.
3. If response is `{"type": "tool_call", "tool": ..., "args": ...}`:
   - validate tool name
   - validate args are object
   - call `SkillToolExecutor`
   - append compact result to messages
4. If response is `{"type": "final", ...}`:
   - add actual `used_tools`
   - return final result
5. If max iterations/tool calls exceeded:
   - return `{success: False, error: "mutation_agent_limits_exceeded"}`

**Step 3: Add class**

Suggested class:

```python
@dataclass
class HermesAuxiliaryMutationBackend:
    tool_executor: SkillToolExecutor
    llm_call: Callable[..., str] | None = None
    limits: MutationBackendLimits = MutationBackendLimits()

    def run(self, prompt: str, task: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        ...
```

If `llm_call` is not injected, call Hermes auxiliary model through `agent.auxiliary_client.call_llm`, following the pattern already used in `dspy_program.py:83-103`.

Use `config["model"]["mutation"]`:

- `provider`
- `model`
- `base_url`
- `api_key`
- `timeout`
- `max_tokens`
- `extra_body`

Task name should be something like `self_improvement_mutation_agent`.

**Step 4: Keep imports lazy**

Do not import `agent.auxiliary_client` at module import time. Import it inside the call path only.

Failure cases:

- missing Hermes auxiliary client → `mutation_agent_unavailable`
- model call exception → `mutation_agent_llm_failed`
- malformed JSON → `mutation_agent_step_not_json`
- disallowed tool → `disallowed_tool_requested`
- final schema missing fields → reuse existing parser error shape

**Step 5: Run tests**

```bash
.venv/bin/python -m pytest tests/test_mutation_backend.py tests/test_mutation_agent.py -q
```

**Step 6: Commit**

```bash
git add hermes_self_improvement/mutation_backend.py hermes_self_improvement/mutation_agent.py tests/test_mutation_backend.py
git commit -m "feat(self-improvement): add auxiliary mutation backend loop"
```

---

## Task 4: Wire Real Backend Selection Into Apply Execution

**Objective:** Make `apply_engine` build a real backend from config/runtime when `_mutation_agent_backend` is not injected.

**Files:**

- Modify: `hermes_self_improvement/apply_engine.py`
- Modify: `hermes_self_improvement/config.py`
- Modify: `hermes_self_improvement/cli.py` if needed for config plumbing
- Test: `tests/test_apply_engine.py`

**Step 1: Write failing tests**

Add tests:

```python
def test_apply_execute_builds_configured_mutation_backend_when_not_injected(monkeypatch, tmp_path): ...
def test_apply_execute_fails_closed_when_backend_disabled(tmp_path): ...
def test_apply_execute_fails_closed_when_backend_unavailable(tmp_path): ...
```

Test by monkeypatching a factory function, not by calling real LLM.

Expected factory:

```python
def build_mutation_backend(config: dict[str, Any]) -> MutationBackend | None:
    ...
```

**Step 2: Add config knobs**

Keep model selection under `model.mutation` and backend controls under `mutation`. Do not introduce `mutation.model`.

The expected default shape is:

```python
"model": {
    "mutation": {
        "provider": "auto",
        "model": "",
        "base_url": "",
        "api_key": "",
        "timeout": 45,
        "max_tokens": 1000,
        "extra_body": {},
    },
},
"mutation": {
    "backend": "hermes_auxiliary_tool_loop",
    "enabled": True,
    "max_tool_calls": 8,
    "max_iterations": 6,
}
```

Compatibility:

- Existing `"backend": "hermes_agent"` should map to the new backend or be normalized with a warning-like config field.
- `backend: "disabled"` or `enabled: false` should fail closed with `mutation_agent_backend_disabled`.
- Unknown backend should fail closed with `mutation_agent_backend_unknown`.

**Step 3: Implement backend factory**

Create in `mutation_backend.py`:

```python
def build_mutation_backend(config: dict[str, Any] | None = None) -> MutationBackend | None:
    ...
```

Rules:

- If `_mutation_agent_backend` exists in config, keep test/injection behavior.
- Otherwise read `config["mutation"]`.
- Build `HermesAuxiliaryMutationBackend` with `SkillToolExecutor`.
- If required tool callables cannot be resolved, return an unavailable backend that fails closed rather than `None` ambiguity.

**Step 4: Use factory in `apply_engine`**

Replace:

```python
backend = config.get("_mutation_agent_backend") if isinstance(config, dict) else None
```

with:

```python
backend = resolve_mutation_backend(config)
```

where injected backend still wins.

**Step 5: Run tests**

```bash
.venv/bin/python -m pytest tests/test_apply_engine.py tests/test_mutation_backend.py -q
```

**Step 6: Commit**

```bash
git add hermes_self_improvement/apply_engine.py hermes_self_improvement/config.py hermes_self_improvement/mutation_backend.py tests/test_apply_engine.py tests/test_mutation_backend.py
git commit -m "feat(self-improvement): wire real mutation backend into apply"
```

---

## Task 5: Resolve Official Skill Tool Callables in Runtime

**Objective:** Make the real backend actually call Hermes skill tools when available, without direct filesystem fallback.

**Files:**

- Modify: `hermes_self_improvement/mutation_backend.py`
- Modify: `hermes_self_improvement/__init__.py` if runtime context injection is needed
- Modify: `hermes_self_improvement/tool_handlers.py` if tool handler can pass context
- Test: `tests/test_plugin_tools.py`, `tests/test_mutation_backend.py`

**Important:** This is the most runtime-sensitive task. Investigate available plugin context first. Do not guess.

**Step 1: Inspect Hermes plugin context capabilities**

Read local Hermes plugin API docs/source if available. Look for:

- `ctx.register_tool`
- registered tool invocation APIs
- whether plugin handlers receive runtime context
- whether tool registry exposes handlers for `skills_list`, `skill_view`, `skill_manage`

Use read-only inspection only. Likely locations:

```bash
python - <<'PY'
import inspect
from hermes_cli.plugins import get_plugin_manager
print(get_plugin_manager())
PY
```

Do not modify Hermes core.

**Step 2: Decide supported runtime path**

Preferred order:

1. If plugin runtime exposes a safe tool invocation function, use it.
2. If skill tool handlers are importable through Hermes tool registry, call those handlers directly through the official registry boundary.
3. If neither exists, keep backend unavailable and document that Hermes core/plugin API needs a tool-invocation hook before real backend can run.

Do **not** implement direct skill file reads/writes as a substitute.

**Step 3: Write tests for whichever path exists**

If official registry path exists:

```python
def test_runtime_skill_tool_resolver_uses_official_tool_registry(monkeypatch): ...
def test_runtime_skill_tool_resolver_fails_closed_without_registry(): ...
```

If no path exists:

```python
def test_runtime_skill_tool_resolver_reports_unavailable_without_core_hook(): ...
```

**Step 4: Implement resolver**

Suggested API:

```python
def resolve_skill_tool_executor(config: dict[str, Any] | None = None) -> SkillToolExecutor:
    ...
```

Return an executor that either has real callables or returns `tool_unavailable` for all tools.

**Step 5: Update status/report visibility**

Add a field to `bin/hermes-self-improve status` output:

```json
"mutation_backend": {
  "configured": "hermes_auxiliary_tool_loop",
  "available": true,
  "tool_executor": "hermes_tool_registry"
}
```

If unavailable:

```json
"mutation_backend": {
  "configured": "hermes_auxiliary_tool_loop",
  "available": false,
  "reason": "skill_tool_registry_unavailable"
}
```

**Step 6: Run tests**

```bash
.venv/bin/python -m pytest tests/test_mutation_backend.py tests/test_plugin_tools.py -q
bin/hermes-self-improve status
```

**Step 7: Commit**

If real tool registry path is implemented:

```bash
git add hermes_self_improvement/mutation_backend.py hermes_self_improvement/__init__.py hermes_self_improvement/tool_handlers.py tests/test_mutation_backend.py tests/test_plugin_tools.py
git commit -m "feat(self-improvement): resolve runtime skill tools for mutation backend"
```

If no safe runtime path exists:

```bash
git add hermes_self_improvement/mutation_backend.py tests/test_mutation_backend.py README.md skills/operations/SKILL.md
git commit -m "docs(self-improvement): document missing runtime tool invocation hook"
```

This task is allowed to conclude “blocked by missing Hermes runtime hook,” but only after verifying the runtime API. Do not fake it.

---

## Task 6: Implement Real Merge Planner Through Hermes Auxiliary Model

**Objective:** Replace default `merge_planner_unavailable` with a real JSON-only auxiliary-model planner, while preserving fail-closed behavior.

**Files:**

- Modify: `hermes_self_improvement/verification.py`
- Modify: `hermes_self_improvement/config.py`
- Test: `tests/test_skill_lifecycle_agent.py`
- Test: create or extend `tests/test_merge_planner.py`

**Step 1: Write failing planner tests**

Add tests:

```python
def test_merge_planner_parses_auxiliary_json_pass(): ...
def test_merge_planner_rejects_malformed_json(): ...
def test_merge_planner_requires_safe_to_delete_source(): ...
def test_merge_planner_fails_closed_on_llm_exception(): ...
def test_merge_planner_uses_configured_mutation_model(): ...
```

Use injected fake LLM function. Do not call live model in unit tests.

**Step 2: Implement planner class/function**

Suggested API:

```python
def build_merge_planner(config: dict[str, Any] | None = None, llm_call: Callable[..., str] | None = None) -> Callable[..., dict[str, Any]]:
    ...

def auxiliary_merge_planner(*, source_before, destination_before, destination_after, agent_result, config=None, llm_call=None) -> dict[str, Any]:
    ...
```

Prompt should ask for strict JSON:

```json
{
  "passed": true,
  "source_information_preserved": true,
  "no_obvious_contradictions": true,
  "no_major_duplicate_guidance": true,
  "safe_to_delete_source": true,
  "reasons": []
}
```

Failure if:

- JSON malformed
- any required boolean missing
- `safe_to_delete_source` false
- model call fails
- content is too large and cannot be summarized safely

**Step 3: Use Hermes auxiliary model path**

Reuse helper patterns from `dspy_program.py` rather than inventing provider handling.

Use `config["model"]["mutation"]` or add `config["model"]["planner"]` only if there is a real need. Prefer `model.mutation` to avoid config sprawl.

Task name: `self_improvement_merge_planner`.

**Step 4: Wire into lifecycle verification**

In `apply_engine._run_lifecycle_skill_agent_mutation`, replace:

```python
planner=config.get("_merge_planner") if callable(config.get("_merge_planner")) else None
```

with:

```python
planner = resolve_merge_planner(config)
```

where injected `_merge_planner` still wins for tests.

**Step 5: Run tests**

```bash
.venv/bin/python -m pytest tests/test_merge_planner.py tests/test_skill_lifecycle_agent.py -q
```

**Step 6: Commit**

```bash
git add hermes_self_improvement/verification.py hermes_self_improvement/apply_engine.py hermes_self_improvement/config.py tests/test_merge_planner.py tests/test_skill_lifecycle_agent.py
git commit -m "feat(self-improvement): add auxiliary merge planner"
```

---

## Task 7: Improve CLI/Tool Reporting for Real vs Unavailable Backend

**Objective:** Make user-facing output honest. No more “implemented” ambiguity when backend or planner is unavailable.

**Files:**

- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/tool_handlers.py`
- Modify: `hermes_self_improvement/schemas.py` only if output schema needs explicit fields
- Test: `tests/test_cli.py` or existing CLI/report tests

**Step 1: Write tests**

Add tests that assert status/report/apply output contains:

- mutation backend configured backend
- available/unavailable
- unavailable reason
- merge planner available/unavailable
- semantic apply failure reason is surfaced in summary

Expected fields in machine JSON:

```json
{
  "mutation_backend": {
    "configured": "hermes_auxiliary_tool_loop",
    "available": false,
    "reason": "skill_tool_registry_unavailable"
  },
  "merge_planner": {
    "available": true,
    "source": "hermes_auxiliary"
  }
}
```

**Step 2: Implement status helpers**

Add small helper in `mutation_backend.py`:

```python
def mutation_backend_status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    ...
```

Add helper in `verification.py`:

```python
def merge_planner_status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    ...
```

**Step 3: Wire into status/report**

`bin/hermes-self-improve status` should include these fields. Human rendered report should mention only when unavailable or relevant.

**Step 4: Run tests**

```bash
.venv/bin/python -m pytest tests/test_plugin_tools.py tests/test_scheduled_execution_docs.py -q
bin/hermes-self-improve status
```

**Step 5: Commit**

```bash
git add hermes_self_improvement/cli.py hermes_self_improvement/tool_handlers.py hermes_self_improvement/mutation_backend.py hermes_self_improvement/verification.py tests
git commit -m "feat(self-improvement): report mutation backend readiness"
```

---

## Task 8: Add Safe End-to-End Smoke Test for Real Backend

**Objective:** Prove the real backend can mutate a disposable local skill and rollback it, without touching production skills.

**Files:**

- Create: `tests/test_real_mutation_backend_smoke.py` or `tests/test_integration_mutation_backend.py`
- Optionally create: `scripts/smoke_mutation_backend.py` only if useful
- Modify docs with command if smoke is opt-in

**Step 1: Decide test mode**

Unit tests should not call live LLM by default. Add two layers:

1. Default integration test with fake LLM but real tool executor shape.
2. Optional live smoke gated by env var:

```bash
HERMES_SELF_IMPROVE_LIVE_MUTATION_SMOKE=1 .venv/bin/python -m pytest tests/test_real_mutation_backend_smoke.py -q
```

**Step 2: Write default fake-LLM integration test**

Use a temporary skills root and injected official-like tool functions. Test:

- create disposable skill `demo-skill`
- run `skill_improve` through backend tool loop
- verify `SKILL.md` changed
- verify ledger rollback data exists
- run rollback
- verify original hash restored

**Step 3: Add optional live smoke**

Live smoke should:

- create temp Hermes home under `tmp_path`
- create local mutable skill under temp skill root
- configure mutation backend to real auxiliary loop
- skip if backend status unavailable
- execute one tiny improvement
- rollback

Do not run against `~/.hermes/skills` by default.

**Step 4: Run default test**

```bash
.venv/bin/python -m pytest tests/test_real_mutation_backend_smoke.py -q
```

**Step 5: Commit**

```bash
git add tests/test_real_mutation_backend_smoke.py
git commit -m "test(self-improvement): add mutation backend smoke coverage"
```

---

## Task 9: Revisit Memory Rollback as Explicit Non-Goal or Separate Proof

**Objective:** Avoid pretending memory rollback is done. Either document it as unsupported or write a separate proof plan.

**Files:**

- Modify: `skills/operations/SKILL.md`
- Modify: `skills/operations/references/mutation-agent-and-recovery.md`
- Modify: `README.md` if user-facing docs claim rollback completeness
- Optionally create: `.hermes/plans/YYYY-MM-DD_HHMMSS-memory-rollback-store-validation.md`
- Test: `tests/test_memory_recovery.py`, `tests/test_scheduled_execution_docs.py`

**Step 1: Audit docs for overclaiming**

Search:

```bash
rg "memory.*rollback|rollback.*memory|unsupported_pending_store_validation|external_provider_direct_restore" README.md skills hermes_self_improvement tests
```

**Step 2: Decide wording**

For this implementation series, recommended wording:

> Skill rollback is implemented via ledger-bound snapshots. Memory rollback remains fail-closed until built-in memory store validation and provider-native compensating correction semantics are proven.

**Step 3: Add tests if needed**

Ensure docs tests assert:

- built-in memory direct restore is unsupported
- sensitive delete re-add forbidden
- external provider direct restore forbidden

Existing `tests/test_memory_recovery.py` already covers this. Add docs test only if docs are changed.

**Step 4: Commit**

```bash
git add README.md skills/operations/SKILL.md skills/operations/references/mutation-agent-and-recovery.md tests/test_scheduled_execution_docs.py
git commit -m "docs(self-improvement): clarify memory rollback remains fail-closed"
```

---

## Task 10: Final Full Validation and Push

**Objective:** Validate the complete implementation and push in clean commits.

**Files:** none expected except any fixes.

**Step 1: Run full validation**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
bin/hermes-self-improve status
```

Expected:

- py_compile passes
- all tests pass
- status reports backend/planner readiness honestly

**Step 2: Run optional smoke only if safe**

Only if the real backend status says available and temp Hermes home is configured:

```bash
HERMES_SELF_IMPROVE_LIVE_MUTATION_SMOKE=1 .venv/bin/python -m pytest tests/test_real_mutation_backend_smoke.py -q
```

If skipped, say skipped and why. Do not fake success.

**Step 3: Review diffs**

```bash
git status --short
git diff --stat HEAD~10..HEAD
```

Check:

- no Hermes core files changed
- no accidental `.env` / secrets
- no generated runtime artifacts committed
- no production skill files mutated by tests

**Step 4: Push**

```bash
git push
```

**Step 5: Final report**

Report in Japanese, briefly:

- commits pushed
- backend status: real available / unavailable with reason
- planner status
- memory rollback status
- test results

---

## Acceptance Checklist

Before calling the implementation complete:

- [ ] Real semantic mutation backend exists, not only `_mutation_agent_backend` test injection.
- [ ] Backend uses Hermes auxiliary model or reports unavailable clearly.
- [ ] Backend can execute only `skills_list`, `skill_view`, `skill_manage`.
- [ ] Backend records actual tool calls, not only agent self-report.
- [ ] Disallowed tool request fails closed.
- [ ] Tool-call / iteration limits fail closed.
- [ ] `apply_engine` resolves backend without test-only config.
- [ ] Merge planner uses Hermes auxiliary model or reports unavailable clearly.
- [ ] Merge source deletion requires checklist + planner pass.
- [ ] Rollback still uses `ledger_bound_restore`, not mutation agent.
- [ ] Memory rollback is either safely implemented with proven store semantics or explicitly unsupported. For this plan, unsupported is acceptable.
- [ ] Status/report output distinguishes implemented, unavailable, failed, and skipped.
- [ ] Full tests pass.
- [ ] Optional live smoke is run or explicitly skipped with reason.
- [ ] Commits are appropriately granular and pushed.

---

## Risks and Mitigations

### Risk: Plugin runtime cannot call existing Hermes tools

Mitigation: Do not bypass tools. Keep backend unavailable and document required Hermes plugin API hook. This is better than smuggling direct file writes back in.

### Risk: Auxiliary model emits invalid JSON or unsafe tool calls

Mitigation: Strict JSON parsing, allowed-tool validation before execution, max loop limits, fail-closed reasons.

### Risk: Agent self-report lies about tools used

Mitigation: Backend records actual tool calls. `used_tools` in final result should be merged/replaced with actual trace.

### Risk: Merge planner overtrusts model

Mitigation: Planner is only one gate. Keep existing deterministic checklist. Source deletion requires both checklist and planner.

### Risk: Live smoke mutates production skills

Mitigation: Use temp Hermes home and temp mutable local skill root. Skip live smoke if isolation cannot be guaranteed.

### Risk: Memory rollback scope creep

Mitigation: Keep memory rollback fail-closed in this plan. Create a separate store-validation plan if needed.

---

## Recommended Commit Sequence

1. `refactor(self-improvement): define mutation backend contract`
2. `feat(self-improvement): add bounded skill tool executor`
3. `feat(self-improvement): add auxiliary mutation backend loop`
4. `feat(self-improvement): wire real mutation backend into apply`
5. `feat(self-improvement): resolve runtime skill tools for mutation backend` or `docs(self-improvement): document missing runtime tool invocation hook`
6. `feat(self-improvement): add auxiliary merge planner`
7. `feat(self-improvement): report mutation backend readiness`
8. `test(self-improvement): add mutation backend smoke coverage`
9. `docs(self-improvement): clarify memory rollback remains fail-closed`

Do not squash these unless the implementation ends up much smaller than expected. The boundary between backend contract, tool executor, LLM loop, apply wiring, and planner should stay reviewable.
