# Pre-release Role Simplification Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task after Ryo explicitly approves implementation.

**Goal:** Remove pre-release legacy compatibility from the self-improvement LLM role path, keep every role on the simple Hermes-native permission model, and make the remaining resolver/planner/evaluator work explicit.

**Architecture:** There is no public compatibility contract yet, so legacy injected editor loops and synthetic submit tools should be deleted rather than preserved. Tool-using LLM roles run through Hermes `AIAgent(enabled_toolsets=...)` plus tool-name whitelist. Tool-free roles receive host-prepared context. Mutation remains exclusive to editor roles.

**Tech Stack:** Python, pytest, Hermes `AIAgent`, `set_thread_tool_whitelist`, `ROLE_TOOL_PERMISSIONS`, official `skills` and `memory` toolsets, runtime-private prompt overlays, existing `improve` / `calibrate` / `status` surfaces.

**Parent roadmap:** `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`

---

## Current state

As of commit `557ab29`, the active/default path is already constrained:

- `target_resolver`: `skills` toolset, whitelist `skills_list` / `skill_view`, no mutation tools.
- `improvement_planner`: `skills` toolset, whitelist `skills_list` / `skill_view`, no mutation tools.
- `skill_agent`: `skills` toolset, whitelist `skills_list` / `skill_view` / `skill_manage`.
- `memory_agent`: `memory` toolset, whitelist `memory`.
- `memory_extractor`, `evaluator`, `prompt_optimizer` / GEPA: no LLM-executed tools; host code prepares context/artifacts.

Current progress:

- Task 1 is implemented: `NativeSkillAgentBackend` and `NativeMemoryAgentBackend` no longer expose `llm_call`, legacy schema helpers, synthetic `submit_mutation_result`, or bespoke injected LLM/tool loops.
- Editor backend execution has one path: Hermes constrained agents returning final JSON plus recovered `tool_trace`.
- Tests that depended on injected provider loops were removed or rewritten to constrained-runner / helper coverage.
- Validation: focused backend/smoke tests passed, full suite passed (`743 passed, 2 skipped`), and `improve --dry-run --json` passed with `run-20260522T064635Z`.

Task 2 is also implemented for active surfaces:

- Added a guard that scans `hermes_self_improvement`, `defaults/prompt-overlays`, `skills/operations`, and `tests` for the removed synthetic finalizer name.
- Rewrote remaining active tests so they no longer carry the literal removed tool name.
- Validation: `git grep -n "submit_mutation_result" -- hermes_self_improvement defaults skills tests` returns no active hits.

Task 3 is implemented:

- Human-readable `status` now prints runtime setup reasons such as `active_prompt_overlays_invalid` before the `hermes self-improvement setup` next step.
- Added a CLI guard confirming there is still no `repair` subcommand; `setup` remains the single init/repair surface.
- Validation: `tests/test_cli_surface.py` passed (`44 passed`), full suite passed (`745 passed, 2 skipped`), `setup --check --json` reported initialized, and `improve --dry-run --json` passed with `run-20260522T065035Z`.

Remaining debt is now Task 4: add `target_resolver` as a thin runtime-private overlay target while keeping resolver mutation-free.

---

## Non-goals

- Do not add `repair`; `setup` remains the single initialize/repair surface.
- Do not add approval queues, new lanes, or fallback execution modes.
- Do not reintroduce plugin-owned tool dispatch for production/default editor execution.
- Do not give resolver/planner/evaluator mutation tools.
- Do not make resolver a heavy planner-equivalent role. Resolver stays broad-entry / attachment-oriented.

---

## Task 1: Delete old injected editor loops

**Objective:** Remove test-only bespoke editor execution loops from skill and memory backends so editor LLM execution has exactly one path: Hermes constrained agents.

**Files:**

- Modify: `hermes_self_improvement/skill_agent_backend.py`
- Modify: `hermes_self_improvement/memory_agent_backend.py`
- Modify: `tests/test_mutation_backend.py`
- Modify: `tests/test_memory_agent.py`
- Possibly modify: `tests/test_real_mutation_backend_smoke.py`

**Step 1: Add RED guard tests**

Add tests that fail while old compatibility remains:

```python
def test_skill_backend_has_no_injected_llm_loop_surface():
    import inspect
    import hermes_self_improvement.skill_agent_backend as backend

    source = inspect.getsource(backend)
    assert "llm_call" not in source
    assert "legacy_skill_agent_tool_schemas" not in source
    assert "skill_agent_legacy_loop_requires_injected_llm_call" not in source
    assert "submit_mutation_result" not in source


def test_memory_backend_has_no_injected_llm_loop_surface():
    import inspect
    import hermes_self_improvement.memory_agent_backend as backend

    source = inspect.getsource(backend)
    assert "llm_call" not in source
    assert "legacy_memory_agent_tool_schemas" not in source
    assert "memory_agent_legacy_loop_requires_injected_llm_call" not in source
    assert "submit_mutation_result" not in source
```

Keep existing tests that prove the default builders use `run_constrained_role_agent`.

**Step 2: Run RED**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_mutation_backend.py::test_skill_backend_has_no_injected_llm_loop_surface tests/test_memory_agent.py::test_memory_backend_has_no_injected_llm_loop_surface -q
```

Expected: FAIL because legacy loop symbols still exist.

**Step 3: Remove old loop code**

In `skill_agent_backend.py`, remove:

- `SUBMIT_MUTATION_RESULT_TOOL`
- `legacy_skill_agent_tool_schemas()`
- `llm_call` field from `NativeSkillAgentBackend`
- `_llm()` helper
- all code after the constrained-agent branch that manually loops over LLM tool calls
- old prompt string that instructs `submit_mutation_result`
- imports only used by the deleted loop

`NativeSkillAgentBackend.run()` should become:

1. validate limits
2. check `tool_executor.available()`
3. build `task_manifest`, `markdown_brief`, `user_context`
4. build final-JSON `system_message`
5. call `_run_constrained_agent(...)`
6. reuse `_validate_final_result(...)`

In `memory_agent_backend.py`, do the analogous deletion:

- remove `SUBMIT_MUTATION_RESULT_TOOL`
- remove `legacy_memory_agent_tool_schemas()`
- remove `llm_call` field / `_llm()` helper
- remove manual LLM/tool loop
- keep `_run_constrained_agent(...)` and `validate_memory_agent_success_result(...)`

**Step 4: Replace tests that depended on the old loop**

For behavior previously tested via injected `llm_call`, move coverage to one of these shapes:

- pure helper tests for argument validation helpers
- constrained-runner fake tests that return `final_response` JSON plus `tool_trace`
- `native_tool_harness.py` tests for message/tool-trace extraction
- backend validation tests using direct `_validate_final_result(...)` or public `run()` with fake constrained runner

Do not keep a fake provider loop just to support old fixtures.

**Step 5: Verify**

```bash
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests/test_mutation_backend.py tests/test_memory_agent.py tests/test_native_tool_harness.py tests/test_constrained_agent.py -q
```

Expected: focused tests pass and no `submit_mutation_result` appears in `hermes_self_improvement/skill_agent_backend.py` or `hermes_self_improvement/memory_agent_backend.py`.

---

## Task 2: Remove synthetic submit-tool remnants from active code and docs

**Objective:** Make `submit_mutation_result` a deleted historical artifact, not a legacy concept in live source.

**Files:**

- Modify: `tests/test_mutation_backend.py`
- Modify: `tests/test_memory_agent.py`
- Modify: `tests/test_real_mutation_backend_smoke.py`
- Modify if needed: `defaults/prompt-overlays/skill_agent.md`
- Modify if needed: `defaults/prompt-overlays/memory_agent.md`
- Modify if needed: `skills/operations/SKILL.md`
- Modify if needed: `skills/operations/references/architecture.md`

**Step 1: Add active-surface naming guard**

Add a single active-source guard test, for example in `tests/test_role_tool_permissions.py` or `tests/test_mutation_backend.py`:

```python
def test_submit_mutation_result_is_not_in_active_plugin_surfaces():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    active_paths = [
        root / "hermes_self_improvement",
        root / "defaults" / "prompt-overlays",
        root / "skills" / "operations",
    ]
    allowed = {
        # Plan files and git history are intentionally not scanned here.
        # If a temporary migration note is required, add the exact file here with a removal date.
    }
    hits = []
    for base in active_paths:
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".md", ".yaml", ".yml"} and path not in allowed:
                text = path.read_text(encoding="utf-8")
                if "submit_mutation_result" in text:
                    hits.append(str(path.relative_to(root)))
    assert hits == []
```

**Step 2: Run RED**

```bash
$PY -m pytest tests/test_mutation_backend.py::test_submit_mutation_result_is_not_in_active_plugin_surfaces -q
```

Expected: FAIL until old backend/tests/docs references are removed or narrowed out of active source.

**Step 3: Delete or rewrite remaining references**

- Remove tests that construct `_tool_response("submit_mutation_result", ...)`.
- Replace old smoke tests with constrained-agent `final_response` + `tool_trace` tests.
- Update docs to say editor agents return final JSON and Hermes recovers tool traces from native messages.
- Do not add a `legacy` allowlist unless there is a concrete retained file that is not imported and is clearly scheduled for deletion.

**Step 4: Verify grep is clean**

```bash
git grep -n "submit_mutation_result" -- hermes_self_improvement defaults skills tests
```

Expected: no output, or only a deliberately named deleted-history fixture if one is unavoidable. Prefer no output.

---

## Task 3: Keep setup/status simple, no repair command

**Objective:** Preserve the single `setup` surface while making stale runtime prompt overlay status obvious and self-explanatory.

**Files:**

- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/setup_runtime.py` only if status needs a clearer reason field
- Test: `tests/test_cli_surface.py` or existing setup/status tests

**Step 1: Add tests for actionable status output**

Add a test for human-readable status rendering when `runtime_setup.initialized` is false because prompt overlays are invalid:

```python
def test_status_mentions_setup_when_prompt_overlays_invalid():
    payload = {
        "runtime_setup": {
            "initialized": False,
            "reasons": ["active_prompt_overlays_invalid"],
            "active_prompt_overlays": {"status": "missing", "roles": {"skill_agent": {"status": "missing"}}},
        }
    }
    text = _render_status_summary(payload)
    assert "active_prompt_overlays_invalid" in text
    assert "hermes self-improvement setup" in text
```

Also add a CLI surface guard:

```python
def test_self_improvement_has_no_repair_subcommand():
    parser = build_parser_somehow()
    help_text = parser.format_help()
    assert "repair" not in help_text
```

Use the project’s existing parser test helpers rather than inventing a new parser if they exist.

**Step 2: Implement minimal wording change**

If current status already says `next: hermes self-improvement setup`, keep code unchanged. If it hides the invalid reason, render:

```text
Runtime setup:
- initialized: no
- reasons: active_prompt_overlays_invalid
- active prompt overlays: missing
- next: hermes self-improvement setup
```

Do not add `repair`, `setup --repair`, or migration aliases.

**Step 3: Verify**

```bash
$PY -m pytest tests/test_cli_surface.py -q
hermes self-improvement status
hermes self-improvement setup --check --json
```

Expected: status is understandable; command list remains `{improve,status,setup,report,calibrate}`.

---

## Task 4: Add target_resolver as a thin runtime-private overlay target

**Objective:** Make resolver improvement first-class enough to evaluate and tune, but keep it lightweight and lower priority than planner/editor/evaluator.

**Why now:** Ryo wants the generally distributed plugin to adapt to user-specific skill names, workflow vocabulary, and memory-vs-skill boundaries. Resolver should be learnable, but not powerful.

**Files:**

- Modify: `hermes_self_improvement/prompt_overlays.py`
- Modify: `hermes_self_improvement/prompt_candidate_optimizer.py`
- Modify: `hermes_self_improvement/prompt_gepa_adapter.py`
- Modify: `hermes_self_improvement/calibration.py`
- Modify: `hermes_self_improvement/runtime_eval_cases.py`
- Modify: `hermes_self_improvement/prompts.py` if `base_prompt_hash("target_resolver")` is missing or incomplete
- Modify: `hermes_self_improvement/target_resolver.py`
- Add: `defaults/prompt-overlays/target_resolver.md`
- Tests: `tests/test_prompt_overlays.py`, `tests/test_prompt_candidate_optimizer.py`, `tests/test_runtime_eval_cases.py`, `tests/test_target_resolver.py`, `tests/test_role_tool_permissions.py`

**Design boundary:**

- Resolver overlay may adjust attachment and coverage judgment only.
- Resolver output remains schema-bound: attach existing skill, memory candidate, unresolved/no-existing-fit, skip noise.
- Resolver must not emit editor operations such as `create_skill`, `patch_skill`, `archive_skill`, `delete`, or `merge`.
- Planner still owns `create_skill` / `mutate_skill` / `mutate_memory` / `skip` / `defer`.
- Resolver gets no mutation tools; allowed tools remain exactly `skills_list` / `skill_view`.

**Step 1: Add RED tests for overlay role registration**

```python
def test_target_resolver_is_prompt_overlay_role_but_not_mutation_role():
    from hermes_self_improvement.prompt_overlays import ALLOWED_PROMPT_ROLES, DEFAULT_PROMPT_SEED_ROLES
    from hermes_self_improvement.role_tool_permissions import ROLE_TOOL_PERMISSIONS

    assert "target_resolver" in ALLOWED_PROMPT_ROLES
    assert "target_resolver" in DEFAULT_PROMPT_SEED_ROLES
    assert ROLE_TOOL_PERMISSIONS["target_resolver"].allowed_tool_names == frozenset({"skills_list", "skill_view"})
    assert "skill_manage" not in ROLE_TOOL_PERMISSIONS["target_resolver"].allowed_tool_names
```

**Step 2: Add default seed**

Create `defaults/prompt-overlays/target_resolver.md` with a short addendum:

```markdown
Resolver should keep the entry broad and evidence-preserving. Prefer unresolved/no_existing_skill_fit when no current skill clearly fits. Do not choose mutation operations; planner owns create_skill, mutate_skill, mutate_memory, skip, and defer. Use read-only skill inspection only to improve coverage judgment.
```

**Step 3: Wire overlay loading into resolver prompt**

In `target_resolver.py`, load active overlay using:

```python
overlay = load_active_prompt_overlay(config, role="target_resolver", base_hash=base_prompt_hash("target_resolver"))
```

Include overlay addendum in the resolver system prompt, same pattern as planner/editor/evaluator prompts.

**Step 4: Extend overlay-set target lists**

Add `target_resolver_overlay` to optimizer/evaluator target mappings, but keep it low-risk:

- candidate can be `changed` or `unchanged`
- no requirement that every GEPA run changes resolver
- eval cases should be sparse and resolver-specific
- acceptance gates remain the same artifact/hash/regression checks

**Step 5: Add resolver runtime eval cases**

Create cases only when there is evidence of resolver-specific failure, such as:

- repeated duplicate-create proposals where reference/local coverage was missed
- repeated wrong attach to an unrelated skill
- `no_existing_skill_fit` missed despite strong recurring workflow gap
- memory-shaped fact wrongly routed to skill coverage, or procedural workflow wrongly routed to memory

Do not generate resolver cases from every ordinary no-op.

**Step 6: Verify target_resolver remains bounded**

Add regression tests:

```python
def test_target_resolver_overlay_cannot_add_mutation_tools():
    # validate optimizer candidate text that tries to grant skill_manage is rejected


def test_target_resolver_output_create_skill_is_normalized_away():
    # resolver may signal no_existing_skill_fit, but create_skill belongs to planner
```

**Step 7: Verify**

```bash
$PY -m pytest tests/test_prompt_overlays.py tests/test_prompt_candidate_optimizer.py tests/test_runtime_eval_cases.py tests/test_target_resolver.py tests/test_role_tool_permissions.py -q
hermes self-improvement setup --json
hermes self-improvement status --json
hermes self-improvement calibrate --dry-run --json > /tmp/self-improvement-resolver-overlay-calibrate.json
hermes self-improvement improve --dry-run --json > /tmp/self-improvement-resolver-overlay-improve.json
```

Expected:

- `status` reports all prompt overlay roles ready, including `target_resolver`.
- Resolver/planner/editor/evaluator role tools remain unchanged.
- Dry-run does not mutate skills or memory.
- Resolver overlay is runtime-private prompt guidance only.

---

## Final validation for the whole plan

Run after Tasks 1〜4:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
git diff --check
hermes self-improvement status --json
hermes self-improvement improve --dry-run --json > /tmp/self-improvement-pre-release-role-simplification-dry-run.json
```

Expected:

- Full tests pass.
- `git grep -n "submit_mutation_result" -- hermes_self_improvement defaults skills tests` is clean.
- Every tool-using LLM role goes through Hermes-native toolsets and whitelist.
- No production/default editor path accepts injected provider calls or plugin-owned tool loops.
- Runtime setup remains initialized after prompt seed changes.

---

## Commit sequence

Recommended commits:

1. `refactor(self-improvement): remove legacy editor loops`
2. `refactor(self-improvement): delete submit mutation finalizer remnants`
3. `fix(self-improvement): clarify setup recovery status`
4. `feat(self-improvement): add target resolver prompt overlay target`

Keep each commit independently green.
