# Target-Based Memory Mutation Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Status:** completed and archived on 2026-05-01. Implemented target-based memory routing and verified with full tests. Do not continue this plan directly; create a new plan for follow-up slices.

**Goal:** Rework `hermes-self-improvement` memory mutation so tool selection is driven by the intended edit target, not by a single `active_memory_provider` value.

**Architecture:** Keep the plugin as a Hermes-runtime tool selector, not a memory-provider client. Evidence is classified into a natural target: built-in user profile, built-in memory, external memory provider, skill, or scorer/evaluator. Built-in memory targets use the `memory` tool; external memory targets use the active provider's Hermes tool; skill and scorer/evaluator paths stay within their existing bounded runners.

**Tech Stack:** Python, pytest, Hermes plugin runtime tools, existing `hermes_self_improvement` modules.

---

## Context

The current memory mutation path still has a provider-first shape:

- `runner_steps._memory_provider(config)` resolves one provider, falling back to `built-in`.
- `run_memory_improvement_step()` passes that provider into `build_memory_mutation_context()` for every memory operation.
- `mutation_policy.build_memory_mutation_context()` treats `provider == "built-in"` as the condition for using the `memory` tool, and non-built-in providers as external provider operations.

That is wrong for Hermes's memory model. Hermes has two layers:

```text
built-in memory:
  MEMORY.md / USER.md
  edited by the memory tool
  always exists when enabled

external memory provider:
  Hindsight / Honcho / Mem0 / etc.
  additive provider selected by memory.provider
  edited by provider-specific Hermes tools
```

The implementation should follow the design agreed in this thread:

```text
Target decides tool.
Provider config only matters after target == external_memory.
```

## Decisions already made

- Content determines the natural target. Do not add a priority between built-in and external memory.
- Built-in user/profile facts use the `memory` tool with `target=user`.
- Built-in environment/repo/tool facts use the `memory` tool with `target=memory`.
- External provider memories are for searchable/reconstructable context that should not be injected every session.
- External provider memories use provider-specific tools such as `hindsight_retain`.
- External provider can be chosen automatically from content, not only from explicit user instruction.
- `memory.provider` is not a replacement for built-in memory.
- Mutation runs through Hermes agent runtime tool surface. Standalone CLI remains report/dry-run/eval/calibration oriented and must not directly edit memory files or provider internals.
- Plugin mutation scope remains only: memory, skill, scorer/evaluator.
- Do not add Curator canary/parallel-observer/comparison mechanisms. Operator decides when to pause/disable Curator.

## Non-goals

- Do not edit Hermes core.
- Do not add direct Hindsight/Honcho/Mem0 API clients.
- Do not directly edit `MEMORY.md`, `USER.md`, provider DBs, or provider internals.
- Do not revive legacy plan/apply/rollback/outcome surfaces.
- Do not add Curator comparison/canary infrastructure.
- Do not broaden mutation targets to runtime config, prompt/tool policy, docs, gateway, cron, or arbitrary repo files.

## Current working tree note

At plan creation time, there are already uncommitted edits from an earlier false start:

```text
M hermes_self_improvement/config.py
M tests/test_config_precedence.py
M tests/test_runner_steps.py
```

Before implementation, inspect these diffs and either adapt them to this plan or revert the parts that encode provider-first behavior. Do not blindly keep or delete them.

---

## Proposed target model

Use a small, explicit target vocabulary. Avoid a large topology abstraction.

```text
builtin_user
builtin_memory
external_memory
skill
evaluator
scorer
none
```

For memory mutation code, only these three are relevant:

```text
builtin_user     -> memory tool, target=user
builtin_memory   -> memory tool, target=memory
external_memory  -> active external provider tool
```

Suggested operation shape:

```python
{
    "operation": "memory_add" | "memory_replace" | "memory_delete",
    "target": "builtin_user" | "builtin_memory" | "external_memory",
    "content": "...",
    "old_text": "...",
    "provider": "hindsight" | None,
}
```

Compatibility fields may still be accepted while normalizing:

```text
target_layer=builtin|external
target_store=user|memory
memory_target=user|memory
target_kind=builtin_user|builtin_memory|external_memory
provider=hindsight|honcho|...
tool_name=memory|hindsight_retain|...
```

But mutation decisions should use the normalized target, not `active_memory_provider`.

---

## Task 1: Freeze target-based behavior with failing tests

**Objective:** Add regression tests that express the agreed behavior before changing implementation.

**Files:**
- Modify: `tests/test_runner_steps.py`
- Modify: `tests/test_mutation_policy.py`
- Modify: `tests/test_config_precedence.py`

**Steps:**

1. Inspect current uncommitted diffs:

   ```bash
   git diff -- hermes_self_improvement/config.py tests/test_config_precedence.py tests/test_runner_steps.py
   ```

2. Keep or rewrite the existing failing tests so they assert target-based semantics, not provider-first semantics.

3. Add/ensure tests for these cases:

   - `memory.provider: hindsight` plus operation target `builtin_user` resolves to:

     ```text
     tool_name=memory
     tool_args.action=add
     tool_args.target=user
     active external provider may be present in config, but it does not change the tool
     ```

   - `memory.provider: hindsight` plus operation target `builtin_memory` resolves to:

     ```text
     tool_name=memory
     tool_args.target=memory
     ```

   - `memory.provider: hindsight` plus operation target `external_memory` resolves to:

     ```text
     tool_name=hindsight_retain
     tool_args.content=<content>
     ```

   - `memory.provider: hindsight` without any explicit/derived target must not default to Hindsight or built-in just because provider exists.

   - `tool_name=memory` evidence is normalized as a built-in memory operation.

   - `tool_name=hindsight_retain` evidence is normalized as an external memory operation.

4. Run targeted tests and confirm the relevant ones fail for the current provider-first implementation:

   ```bash
   PY=${PYTHON:-.venv/bin/python}
   $PY -m pytest tests/test_runner_steps.py tests/test_mutation_policy.py tests/test_config_precedence.py -q
   ```

**Expected before implementation:** At least one target-based test fails because current code passes a single provider into `build_memory_mutation_context()`.

**Commit after green later:** not yet; this task only establishes RED.

---

## Task 2: Add memory operation target normalization

**Objective:** Introduce one small helper that converts evidence/operation fields into a normalized target.

**Files:**
- Modify: `hermes_self_improvement/mutation_policy.py`
- Test: `tests/test_mutation_policy.py`

**Steps:**

1. Add a small helper near existing memory policy helpers:

   ```python
   BUILTIN_USER_TARGETS = {"user", "profile", "user_profile", "builtin_user", "built_in_user"}
   BUILTIN_MEMORY_TARGETS = {"memory", "note", "builtin_memory", "built_in_memory"}
   EXTERNAL_MEMORY_TARGETS = {"external", "external_memory", "provider", "memory_provider"}

   def normalize_memory_target(operation: dict[str, Any]) -> str | None:
       ...
   ```

2. Resolution order should be simple:

   ```text
   explicit target_kind / target_layer / target first
   then target_store / memory_target for built-in store
   then tool_name if present
   then None
   ```

3. Implement mapping rules:

   ```text
   target_kind=builtin_user -> builtin_user
   target_kind=builtin_memory -> builtin_memory
   target_kind=external_memory -> external_memory

   target_layer=builtin + target_store=user -> builtin_user
   target_layer=builtin + target_store=memory -> builtin_memory
   target_layer=external -> external_memory

   target_store=user/profile -> builtin_user
   target_store=memory -> builtin_memory

   tool_name=memory -> builtin_memory unless tool args target=user says builtin_user
   tool_name=hindsight_retain/honcho_conclude/... -> external_memory
   ```

4. Do not infer target from `memory.provider`.

5. Add tests for each mapping above.

6. Run:

   ```bash
   PY=${PYTHON:-.venv/bin/python}
   $PY -m pytest tests/test_mutation_policy.py -q
   ```

---

## Task 3: Rework `build_memory_mutation_context()` around target, not provider

**Objective:** Make tool resolution depend on normalized target.

**Files:**
- Modify: `hermes_self_improvement/mutation_policy.py`
- Test: `tests/test_mutation_policy.py`

**Steps:**

1. Change or extend function signature to accept target-aware data while preserving test/backward compatibility where practical:

   ```python
   def build_memory_mutation_context(*, operation: dict[str, Any], provider: str | None = None) -> dict[str, Any]:
   ```

   `provider` remains the external provider name only. It must not decide whether built-in memory is used.

2. At the top, compute:

   ```python
   target = normalize_memory_target(operation)
   requested = ...
   external_provider = normalize_memory_provider(operation.get("provider") or provider)
   ```

3. For `target in {"builtin_user", "builtin_memory"}`:

   - support `memory_add`, `memory_replace`, `memory_delete`
   - call `build_memory_tool_context()`
   - map target:

     ```text
     builtin_user -> target=user
     builtin_memory -> target=memory
     ```

   - return executable context with:

     ```text
     target_kind=memory
     target_layer=built_in
     normalized_target=builtin_user|builtin_memory
     tool_name=memory
     active_memory_provider should not drive behavior
     ```

4. For `target == "external_memory"`:

   - require external provider to be known and supported
   - use existing provider policy functions for Hindsight/Honcho/Mem0/etc.
   - support add/retain path, not only delete/correction
   - sensitive deletes remain fail-closed as current policy already intends

5. For `target is None`:

   - return blocked:

     ```text
     execution_enabled=False
     reason=memory_target_missing
     ```

6. Update tests so Hindsight active + built-in target uses `memory`, and Hindsight active + external target uses `hindsight_retain`.

7. Run:

   ```bash
   PY=${PYTHON:-.venv/bin/python}
   $PY -m pytest tests/test_mutation_policy.py -q
   ```

---

## Task 4: Normalize memory operation extraction in runner

**Objective:** Ensure `run_memory_improvement_step()` passes target-aware operations into the policy layer.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Test: `tests/test_runner_steps.py`

**Steps:**

1. Replace `_memory_provider(config)` usage as the main decision input.

2. Keep a helper only for external provider lookup, with a clearer name:

   ```python
   def _external_memory_provider(config: dict[str, Any] | None) -> str | None:
       ...
   ```

3. `_external_memory_provider()` may read:

   ```text
   config["memory_runtime"]["external"]["provider"]
   config["memory"]["provider"]
   config["memory_provider"]
   ```

   but must not return `built-in` as a fallback. Unknown means `None`.

4. Enrich `_memory_operation_from_evidence()` so it preserves useful target hints from evidence:

   ```text
   event.tool_name
   args_preview.target
   args_preview.action
   args_preview.content
   result_preview memory_operation
   provider
   ```

5. When calling `build_memory_mutation_context()`, pass:

   ```python
   context = build_memory_mutation_context(
       operation=operation,
       provider=external_provider,
   )
   ```

6. Related-memory lookup should use the external provider only when useful. It should not make built-in operation look external.

7. Return artifact fields should avoid provider-first naming:

   ```text
   external_provider: hindsight|null
   decisions[*].context.normalized_target: builtin_user|builtin_memory|external_memory
   ```

   Keep old `provider` in output only if tests/docs require it, but do not use it for decisions.

8. Run:

   ```bash
   PY=${PYTHON:-.venv/bin/python}
   $PY -m pytest tests/test_runner_steps.py -q
   ```

---

## Task 5: Add provider add/retain contexts for external memory

**Objective:** External memory add operations should be executable through provider tools when the runtime tool function exists.

**Files:**
- Modify: `hermes_self_improvement/mutation_policy.py`
- Modify if needed: `hermes_self_improvement/mutation_worker.py`
- Test: `tests/test_mutation_policy.py`
- Test: `tests/test_runner_steps.py`

**Steps:**

1. Add provider add context builder, parallel to correction/delete helpers:

   ```python
   def build_provider_add_tool_context(provider: str, operation: dict[str, Any]) -> dict[str, Any]:
       ...
   ```

2. Map at least existing provider policies:

   ```text
   hindsight -> hindsight_retain {content, context, tags}
   honcho -> honcho_conclude {conclusion}
   mem0 -> mem0_conclude {conclusion}
   holographic -> fact_store {action=add, content, ...}
   retaindb -> retaindb_remember {content, ...}
   byterover -> brv_curate {content}
   supermemory -> supermemory_store {content, metadata}
   openviking -> viking_remember {content}
   ```

3. Keep direct fallback forbidden.

4. If provider is missing/unsupported, block with:

   ```text
   external_memory_provider_missing
   unsupported_memory_provider
   ```

5. Ensure `execute_memory_provider_tool_operation()` is still the only executor for external provider contexts.

6. Run:

   ```bash
   PY=${PYTHON:-.venv/bin/python}
   $PY -m pytest tests/test_mutation_policy.py tests/test_runner_steps.py -q
   ```

---

## Task 6: Keep config loading only as runtime context, not as decision shortcut

**Objective:** Preserve useful Hermes config loading without reviving provider-first behavior.

**Files:**
- Modify: `hermes_self_improvement/config.py`
- Test: `tests/test_config_precedence.py`

**Steps:**

1. Review the current uncommitted `_runtime_memory_overlay()` implementation.

2. Keep only the parts that describe runtime availability/context:

   ```text
   memory_runtime.built_in.memory_enabled
   memory_runtime.built_in.user_profile_enabled
   memory_runtime.built_in.tool=memory
   memory_runtime.external.provider
   memory_runtime.external.enabled
   ```

3. Do not expose or rely on a single `active_memory_provider` for mutation decisions.

4. Ensure config precedence remains:

   ```text
   defaults
   plugin config
   plugin local config
   env config
   CLI config
   Hermes runtime config overlay
   ```

   If a test asserts different precedence because of the earlier false start, update it to match target-based design.

5. Run:

   ```bash
   PY=${PYTHON:-.venv/bin/python}
   $PY -m pytest tests/test_config_precedence.py -q
   ```

---

## Task 7: Update artifact/report wording away from `active_memory_provider`

**Objective:** Make outputs explain target/tool decisions clearly.

**Files:**
- Search first: `hermes_self_improvement/*.py`, `tests/*.py`, `README.md`, `skills/operations/SKILL.md`
- Likely modify: `hermes_self_improvement/runner_steps.py`
- Likely modify: report-related tests if they assert old wording
- Modify docs only if they currently describe provider-first behavior

**Steps:**

1. Search:

   ```bash
   rg "active_memory_provider|resolved_strategy|memory provider|provider-first" hermes_self_improvement tests README.md skills/operations/SKILL.md
   ```

2. Keep `resolved_strategy` if useful, but ensure it is derived from target/tool.

3. Replace user-facing provider-first wording with:

   ```text
   normalized_target
   target_layer
   tool_name
   external_provider
   ```

4. Do not perform a broad docs rewrite. Only update stale or misleading statements.

5. Run relevant tests:

   ```bash
   PY=${PYTHON:-.venv/bin/python}
   $PY -m pytest tests/test_report_integration.py tests/test_cli_surface.py tests/test_scheduled_execution_docs.py -q
   ```

---

## Task 8: Full validation

**Objective:** Prove the change does not break plugin behavior outside memory target selection.

**Files:**
- No code changes expected unless validation reveals failures.

**Steps:**

1. Compile:

   ```bash
   PY=${PYTHON:-.venv/bin/python}
   $PY -m py_compile __init__.py hermes_self_improvement/*.py
   ```

2. Run full tests:

   ```bash
   PY=${PYTHON:-.venv/bin/python}
   $PY -m pytest tests -q
   ```

3. Run plugin status:

   ```bash
   bin/hermes-self-improve status
   ```

4. Run dry-run improve to inspect artifact shape:

   ```bash
   bin/hermes-self-improve improve --dry-run
   ```

5. Verify output/artifacts show target-based decisions:

   ```text
   built-in targets use memory
   external targets use provider tool
   no direct file/provider internals
   no Curator canary/comparison mode added
   ```

---

## Task 9: Commit and push

**Objective:** Save the completed implementation in a clean commit.

**Steps:**

1. Review diff:

   ```bash
   git status --short
   git diff --stat
   git diff
   ```

2. Commit with a message like:

   ```bash
   git add hermes_self_improvement tests README.md skills/operations/SKILL.md .hermes/plans
   git commit -m "fix(self-improvement): route memory mutations by target"
   ```

   Only include docs/skill files if actually modified.

3. Push:

   ```bash
   git push
   ```

---

## Risks and guardrails

- **Risk:** Reintroducing provider-first logic under a new helper name.
  - **Guardrail:** Tests must prove Hindsight active + built-in target still uses `memory`.

- **Risk:** Overbuilding a topology abstraction.
  - **Guardrail:** Use a small normalized target string. Do not add new framework layers unless tests require them.

- **Risk:** Standalone CLI starts mutating provider internals directly.
  - **Guardrail:** External mutation still requires runtime tool functions. Direct API/file/db fallback remains forbidden.

- **Risk:** Existing delete/correction safety regresses.
  - **Guardrail:** Keep sensitive delete tests and provider-native identity checks. Add tests if current coverage is insufficient.

- **Risk:** The current uncommitted false-start changes encode the wrong model.
  - **Guardrail:** Start by reviewing those diffs and reshape them before writing implementation.

## Acceptance criteria

- `memory.provider: hindsight` no longer causes built-in memory operations to route to Hindsight.
- Built-in USER/MEMORY operations call `memory` with the correct `target`.
- External memory operations call provider-specific tools.
- Unknown target does not silently fall back to built-in or external.
- `active_memory_provider` is not used for mutation routing.
- No direct memory file/provider DB mutation is introduced.
- No Curator comparison/canary system is introduced.
- Full tests pass.
