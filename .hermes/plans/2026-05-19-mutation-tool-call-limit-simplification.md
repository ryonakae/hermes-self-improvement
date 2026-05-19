# Mutation Tool Call Limit Simplification Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Remove the plugin-facing `mutation.max_iterations` setting and make `mutation.max_tool_calls` the single operator-facing limit for native skill/memory mutation agents.

**Architecture:** The plugin keeps a small internal LLM-round safety budget, but derives it from `max_tool_calls` instead of exposing a second config knob. Skill-agent and memory-agent share the same policy: real mutation tool calls are limited by `max_tool_calls`, and internal LLM rounds are `max_tool_calls + 2` to leave room for final `submit_mutation_result`. This does not read Hermes core `agent.max_turns`; the plugin's native mutation editor loop is smaller and separate from the normal Hermes agent loop.

**Tech Stack:** Python, pytest, Hermes plugin config loader, native tool-calling mutation backends.

---

## Context

The current plugin defaults define two mutation limits:

```python
# hermes_self_improvement/config.py
"mutation": {
    "backend": "native_skill_tool",
    "enabled": True,
    "max_tool_calls": 8,
    "max_iterations": 6,
}
```

Both native backends also carry matching dataclass fallbacks:

```python
# hermes_self_improvement/skill_agent_backend.py
class SkillAgentBackendLimits:
    max_tool_calls: int = 8
    max_iterations: int = 6

# hermes_self_improvement/memory_agent_backend.py
class MemoryAgentBackendLimits:
    max_tool_calls: int = 8
    max_iterations: int = 6
```

This is internally inconsistent: the plugin allows up to 8 mutation tool calls but only 6 LLM rounds. Because the final `submit_mutation_result` also consumes an LLM round, a run can successfully execute memory/skill tools and still fail with `max_iterations_exceeded` before final accounting.

Recent observed failure shape:

```text
memory tool calls succeeded
last action: remove
error: memory_agent_limits_exceeded / max_iterations_exceeded
run summary: memory_changes 0
```

Ryo's decision for this plan:

- Do **not** read Hermes core `agent.max_turns` for this plugin loop.
- Do **not** keep backward compatibility for `mutation.max_iterations`; the plugin is unreleased.
- Remove `max_iterations` as a public/config concept completely.
- Keep only `mutation.max_tool_calls` as the operator-facing knob.
- Prefer default `max_tool_calls = 12`.

---

## Scope

In scope:

- Remove `mutation.max_iterations` from plugin defaults and examples.
- Remove `max_iterations` fields from `SkillAgentBackendLimits` and `MemoryAgentBackendLimits`.
- Derive internal LLM round budget as `max_tool_calls + 2` inside each native backend run loop.
- Rename error/reporting surfaces away from `max_iterations_exceeded` to an internal-round name such as `max_llm_rounds_exceeded`.
- Apply the same policy to both skill-agent and memory-agent.
- Update tests to enforce the new public contract.

Out of scope:

- Reading Hermes core `agent.max_turns`.
- Adding partial-applied accounting when the finalizer is missing.
- Changing memory candidate generation, skill target resolution, or `tool_failure_evidence` aggregation.
- Changing memory-agent candidate cap behavior; that was already handled separately in commit `5141a01`.

---

## Desired contract

Operator-facing config:

```yaml
mutation:
  enabled: true
  max_tool_calls: 12
```

Internal policy:

```python
max_tool_calls = mutation.max_tool_calls or 12
max_llm_rounds = max_tool_calls + 2
```

Meaning:

- `max_tool_calls` counts only real mutation tools:
  - skill-agent: `skills_list`, `skill_view`, `skill_manage` if currently counted by the backend loop
  - memory-agent: `memory`
- `submit_mutation_result` remains an end sentinel, not a mutation tool call.
- The backend loop may call the LLM up to `max_tool_calls + 2` times so the agent can consume tool results and submit the final structured result.
- If the loop still fails to submit, the run fails with `max_llm_rounds_exceeded`, preserving `used_tools` / `last_tool` diagnostics.

---

## Task 1: Remove `mutation.max_iterations` from config defaults

**Objective:** Make `max_tool_calls` the only mutation limit in the default config.

**Files:**

- Modify: `hermes_self_improvement/config.py`
- Test: `tests/test_config_precedence.py` or the nearest existing config-default test file

**Step 1: Write failing test**

Add or update a config test that asserts:

```python
def test_default_config_exposes_only_max_tool_calls_for_mutation_limits():
    cfg = load_config(default_path=tmp_path / "missing.yaml")

    assert cfg["mutation"]["max_tool_calls"] == 12
    assert "max_iterations" not in cfg["mutation"]
```

Use the existing test fixture style in the config tests. If `load_config()` expects a plugin-local default path, use an empty temp config path that does not exist or a temp config file with `{}` depending on existing patterns.

**Step 2: Verify RED**

Run:

```bash
python -m pytest tests/test_config_precedence.py -q
```

Expected: FAIL because `mutation.max_iterations` still exists and `max_tool_calls` is still `8`.

**Step 3: Implement minimal code**

Change `_default_config()`:

```python
"mutation": {
    "backend": "native_skill_tool",
    "enabled": True,
    "max_tool_calls": 12,
},
```

Do not add compatibility normalization for `max_iterations`.

**Step 4: Verify GREEN**

Run:

```bash
python -m pytest tests/test_config_precedence.py -q
```

Expected: PASS.

---

## Task 2: Remove `max_iterations` from backend limit dataclasses

**Objective:** Ensure memory-agent and skill-agent no longer expose `max_iterations` in their limits objects.

**Review notes:** When removing the field, also update each backend limit `check()` method so it no longer references `self.max_iterations` or emits `max_iterations_must_be_positive`. Do not touch unrelated `gepa_evaluator.max_iterations`; that is a separate GEPA optimizer setting, not this mutation loop setting.

**Files:**

- Modify: `hermes_self_improvement/skill_agent_backend.py`
- Modify: `hermes_self_improvement/memory_agent_backend.py`
- Test: `tests/test_mutation_backend.py`
- Test: `tests/test_memory_agent.py`

**Step 1: Write failing tests**

For skill-agent backend:

```python
def test_skill_agent_limits_only_configures_tool_calls_and_timeout():
    limits = SkillAgentBackendLimits.from_config({"mutation": {"max_tool_calls": 12}})

    assert limits.max_tool_calls == 12
    assert not hasattr(limits, "max_iterations")
```

For memory-agent backend:

```python
def test_memory_agent_limits_only_configures_tool_calls_and_timeout():
    limits = MemoryAgentBackendLimits.from_config({"mutation": {"max_tool_calls": 12}})

    assert limits.max_tool_calls == 12
    assert not hasattr(limits, "max_iterations")
```

**Step 2: Verify RED**

Run:

```bash
python -m pytest \
  tests/test_mutation_backend.py::test_skill_agent_limits_only_configures_tool_calls_and_timeout \
  tests/test_memory_agent.py::test_memory_agent_limits_only_configures_tool_calls_and_timeout \
  -q
```

Expected: FAIL because both dataclasses still have `max_iterations`.

**Step 3: Implement minimal code**

In both dataclasses:

- Remove the `max_iterations` field.
- Stop reading `mutation.max_iterations` in `from_config()`.
- Keep `max_tool_calls` and `timeout_seconds` validation.

Example shape:

```python
@dataclass(frozen=True)
class MemoryAgentBackendLimits:
    max_tool_calls: int = 12
    timeout_seconds: int = 45

    @classmethod
    def from_config(cls, config: dict[str, Any] | None = None) -> "MemoryAgentBackendLimits":
        mutation = config.get("mutation") if isinstance(config, dict) and isinstance(config.get("mutation"), dict) else {}
        model = config.get("model") if isinstance(config, dict) and isinstance(config.get("model"), dict) else {}
        model_memory = model.get("memory_agent") if isinstance(model.get("memory_agent"), dict) else {}
        return cls(
            max_tool_calls=max(0, _coerce_int(mutation.get("max_tool_calls"), cls.max_tool_calls)),
            timeout_seconds=max(1, _coerce_int(model_memory.get("timeout") or mutation.get("timeout_seconds"), cls.timeout_seconds)),
        )
```

Mirror the same policy in `SkillAgentBackendLimits`.

**Step 4: Verify GREEN**

Run the focused tests again. Expected: PASS.

---

## Task 3: Derive internal LLM round budget from `max_tool_calls`

**Objective:** Keep an internal safety guard without exposing `max_iterations`.

**Files:**

- Modify: `hermes_self_improvement/skill_agent_backend.py`
- Modify: `hermes_self_improvement/memory_agent_backend.py`
- Test: `tests/test_mutation_backend.py`
- Test: `tests/test_memory_agent.py`

**Step 1: Write failing tests**

Add behavior tests proving the backend can use all allowed tool calls and still submit.

Memory-agent example:

```python
def test_memory_backend_allows_submit_after_max_tool_calls():
    responses = [
        _tool_call_message("memory", {"action": "add", "target": "memory", "content": f"fact {i}"}, call_id=f"call_{i}")
        for i in range(12)
    ]
    responses.append(_tool_call_message("submit_mutation_result", success_result(changed_memories=[f"fact {i}" for i in range(12)]), call_id="call_submit"))
    fake_responses = iter(responses)

    backend = NativeMemoryAgentBackend(
        tool_executor=MemoryToolExecutor(memory_tool_fn=lambda **args: json.dumps({"success": True})),
        llm_call=lambda messages, *, tools, config, timeout, max_tokens: next(fake_responses),
        limits=MemoryAgentBackendLimits(max_tool_calls=12, timeout_seconds=10),
    )

    result = MemoryAgentRunner(backend=backend).run(task(), config={})

    assert result["success"] is True
    assert len(result["used_tools"]) == 12
```

Skill-agent equivalent should use the existing `_tool_response` helper and a small harmless sequence such as repeated `skill_view` calls followed by `submit_mutation_result`, or a shorter explicit limit such as `max_tool_calls=2` to avoid a large fixture.

**Step 2: Verify RED**

Run the focused tests. Expected: FAIL because the current loop uses `self.limits.max_iterations`, which is removed or too low.

**Step 3: Implement minimal code**

Inside each backend `run()` method, derive:

```python
max_llm_rounds = self.limits.max_tool_calls + 2
for _iteration in range(max_llm_rounds):
    ...
```

Do not store this on the public limits dataclass unless tests need to inspect it; prefer a local variable to keep it internal.

**Step 4: Verify GREEN**

Run focused tests. Expected: PASS.

---

## Task 4: Rename limit-exceeded diagnostics away from `max_iterations`

**Objective:** Remove the old public/internal name from runtime result surfaces.

**Review notes:** Update existing exhausted-loop tests as well as adding new assertions. In particular, any test named like `test_native_backend_stops_after_max_iterations` should be renamed and rewritten around the derived `max_llm_rounds` behavior.

**Files:**

- Modify: `hermes_self_improvement/skill_agent_backend.py`
- Modify: `hermes_self_improvement/memory_agent_backend.py`
- Test: `tests/test_mutation_backend.py`
- Test: `tests/test_memory_agent.py`

**Step 1: Write failing tests**

For both backends, force the LLM to keep requesting tools and assert the terminal reason is:

```python
"max_llm_rounds_exceeded"
```

not:

```python
"max_iterations_exceeded"
```

Example expectation:

```python
assert result["success"] is False
assert result["error"] == "memory_agent_limits_exceeded"
assert result["reasons"] == ["max_llm_rounds_exceeded"]
```

**Step 2: Verify RED**

Expected: FAIL because current code returns `max_iterations_exceeded`.

**Step 3: Implement minimal code**

Change only the final loop-exhaustion reason:

```python
return _with_last_safe_step({
    "success": False,
    "error": "memory_agent_limits_exceeded",
    "reasons": ["max_llm_rounds_exceeded"],
}, actual_used)
```

Mirror for skill-agent while preserving existing error prefix (`skill_agent_limits_exceeded`).

**Step 4: Verify GREEN**

Run focused tests. Expected: PASS.

---

## Task 5: Remove docs/example references to `mutation.max_iterations`

**Objective:** Ensure active docs/config samples do not teach the removed knob.

**Files:**

- Modify: `config.example.yaml`
- Modify: `config.yaml` if it contains an active or commented `mutation.max_iterations` example
- Modify: `README.md` / `skills/operations/SKILL.md` only if active docs mention the knob
- Test: add or update a naming/config surface test if one exists

**Step 1: Search active surfaces**

Run:

```bash
rg -n "mutation:|max_iterations|max_tool_calls" \
  config.yaml config.example.yaml README.md skills hermes_self_improvement tests
```

**Step 2: Write failing guard if appropriate**

If there is an existing config/docs surface guard, add:

```python
def test_active_config_examples_do_not_document_mutation_max_iterations():
    active_paths = [Path("config.example.yaml"), Path("config.yaml"), Path("README.md"), Path("skills/operations/SKILL.md")]
    for path in active_paths:
        if path.exists():
            assert "max_iterations" not in path.read_text()
```

Keep allowlists for unrelated GEPA/delegation/core references if the searched scope includes them. Do not overreach into archived plans.

**Step 3: Verify RED**

Expected: FAIL if active docs still mention `mutation.max_iterations`.

**Step 4: Update docs minimally**

Document the public knob as:

```yaml
mutation:
  enabled: true
  max_tool_calls: 12
```

Do not mention `max_llm_rounds` unless the operations docs need an implementation note.

**Step 5: Verify GREEN**

Run the guard/focused docs tests. Expected: PASS.

---

## Task 6: Full verification and commit

**Objective:** Verify the refactor did not regress mutation accounting or plugin surfaces.

**Files:**

- No new functional files unless tests/docs revealed a missing surface.

**Step 1: Run focused tests**

```bash
python -m pytest \
  tests/test_memory_agent.py \
  tests/test_memory_agent_dispatch.py \
  tests/test_mutation_backend.py \
  tests/test_config_precedence.py \
  -q
```

Expected: PASS.

**Step 2: Run full verification**

```bash
python -m py_compile __init__.py hermes_self_improvement/*.py
python -m pytest tests -q
git diff --check
```

Expected: PASS. Current baseline after cap-removal commit was `692 passed, 2 skipped`.

**Step 3: Inspect result surfaces**

Run a safe dry run if runtime state is available:

```bash
hermes self-improvement improve --dry-run --json
```

Check that the output no longer exposes `mutation.max_iterations`, and that memory-agent preview still reports candidate counts without per-kind cap omissions.

**Step 4: Commit**

```bash
git add \
  hermes_self_improvement/config.py \
  hermes_self_improvement/skill_agent_backend.py \
  hermes_self_improvement/memory_agent_backend.py \
  tests/test_config_precedence.py \
  tests/test_mutation_backend.py \
  tests/test_memory_agent.py \
  config.example.yaml config.yaml README.md skills/operations/SKILL.md

git commit -m "refactor: simplify mutation tool call limits"
git push
```

Only include docs files that actually changed.

---

## Risks and decisions

### Why not use Hermes core `agent.max_turns`?

The native mutation backends do not spawn a full `AIAgent` loop. They use `agent.auxiliary_client.call_llm()` directly and expose only a tiny tool set. Hermes core `agent.max_turns` is designed for normal full-agent tool-calling conversations and is too broad for this bounded mutation editor loop.

### Why not keep `max_iterations` compatibility?

The plugin is unreleased, and Ryo explicitly decided compatibility is unnecessary. Keeping a hidden compatibility path would preserve an obsolete concept and complicate future reasoning.

### Why `max_tool_calls = 12`?

`8` was too low once candidate caps were removed and memory capacity recovery can consume multiple calls (`add` failure -> `remove` -> retry `add`). `12` still keeps unattended mutation bounded while allowing several small memory/skill changes in one run. Larger defaults such as `20+` are not recommended until dogfood proves the mutation agent reliably self-limits.

### Why `max_tool_calls + 2` internal LLM rounds?

One final LLM round is needed for `submit_mutation_result` after the last allowed tool result. The extra round provides a small buffer for provider/tool-call behavior without turning the editor into a long-running agent.

---

## Implementation result

Implemented in this slice:

- Removed `mutation.max_iterations` from default config and active config examples.
- Set `mutation.max_tool_calls` default to `12`.
- Removed `max_iterations` from `SkillAgentBackendLimits` and `MemoryAgentBackendLimits`.
- Derived each native backend's internal LLM round guard as `max_tool_calls + 2`.
- Preserved `submit_mutation_result` as a non-counted finalizer, so one allowed mutation/tool call can still be followed by final structured reporting.
- Replaced the terminal loop fallback reason with `max_llm_rounds_exceeded`; repeated real tool calls still fail earlier with `max_tool_calls_exceeded`, which is the intended primary safety boundary.
- Updated `config.yaml` / `config.example.yaml` to expose only `max_tool_calls` under `mutation`.

Validation:

- Focused tests: `98 passed` (`tests/test_memory_agent.py`, `tests/test_memory_agent_dispatch.py`, `tests/test_mutation_backend.py`, `tests/test_config_precedence.py`).
- Full verification: `python -m py_compile __init__.py hermes_self_improvement/*.py`, `python -m pytest tests -q` (`698 passed, 2 skipped`), and `git diff --check` passed.
- Dry-run artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260519T061607Z.json` showed memory-agent preview with 39 candidates and no omitted per-kind counts; mutating apply was intentionally not run because it would write real memories.

---

## Completion criteria

- `mutation.max_iterations` no longer exists in code defaults, backend limit dataclasses, or active config examples.
- `mutation.max_tool_calls` default is `12`.
- Skill-agent and memory-agent derive internal LLM rounds from `max_tool_calls + 2`.
- Limit-exceeded diagnostics say `max_llm_rounds_exceeded`, not `max_iterations_exceeded`.
- Focused and full tests pass.
- Plan index updated to include this plan.
