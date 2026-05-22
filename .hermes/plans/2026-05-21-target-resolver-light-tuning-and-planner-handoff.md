# Constrained LLM Role Tooling and Resolver Handoff Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task after Ryo explicitly approves implementation.

**Goal:** Simplify self-improvement LLM role execution around Hermes' built-in tool permission surfaces, while allowing `target_resolver` and `planner` to inspect skills read-only and keeping mutation authority limited to editor roles.

**Architecture:** Use the existing self-improvement pipeline, but make role permissions explicit: resolver/planner get read-only skill inspection (`skills_list`, `skill_view`), editor roles get mutation-capable toolsets (`skills` or `memory`), evaluator/GEPA stay tool-free and receive prepared context. Avoid bespoke tool-call loops except where Hermes lacks a direct surface; prefer `AIAgent(enabled_toolsets=...)` plus optional tool-name whitelist over custom parser/executor machinery.

**Tech Stack:** Python, pytest, Hermes `AIAgent`, `model_tools.get_tool_definitions`, `hermes_cli.plugins.set_thread_tool_whitelist`, plugin LLM facade (`ctx.llm.complete_structured`) where tool-free structured inference is enough, existing `hermes_self_improvement` modules.

**Parent roadmap:** `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`

---

## Final design decision from discussion

The role permission matrix is now:

| Role | Allowed tools | Mutation? | Notes |
|---|---|---:|---|
| `target_resolver` | `skills_list`, `skill_view` | No | May inspect existing skills to attach or mark `no_existing_skill_fit`; must not create/patch/delete. |
| `memory_extractor` | none | No | Host code passes memory/context inventory into the prompt. |
| `improvement_planner` | `skills_list`, `skill_view` | No | May inspect skills before deciding `create_skill`, `mutate_skill`, `mutate_memory`, `skip`, `defer`, etc.; no mutation tools. |
| `skill_editor` / `skill_agent` | `skills` toolset (`skills_list`, `skill_view`, `skill_manage`) | Yes | Only role allowed to mutate skills through official Hermes skill tools. |
| `memory_editor` / `memory_agent` | `memory` toolset (`memory`) | Yes | Only role allowed to mutate built-in memory through official Hermes memory tool. |
| `evaluator` | none | No | Receives diffs/artifacts/results as input; evaluates adoption/quality. |
| `GEPA` / `prompt_optimizer` | none | No | Generates prompt/overlay candidates only. |
| `promote/apply` | no LLM | Yes, deterministic | Saves/promotes a winner after evaluation gates pass. |

Important nuance:

- “No tools” does **not** mean the LLM sees no information. Host pipeline code reads required files/artifacts/inventories and passes compact context into the prompt.
- Tool-name permission should use Hermes surfaces. Fine-grained semantic constraints should primarily be prompt instructions and evaluator feedback, not heavy bespoke validators.
- Keep implementation simple: no new lanes, no approval queues, no extra scorer hierarchy, no duplicate agent loop unless a concrete Hermes limitation forces it.

---

## Hermes API / implementation findings

Relevant existing Hermes surfaces:

1. `AIAgent(..., enabled_toolsets=[...], disabled_toolsets=[...])`
   - `agent/agent_init.py` stores `enabled_toolsets` / `disabled_toolsets` and calls `get_tool_definitions(...)`.
   - This is the simplest surface for tool-calling editor/read-only agents.

2. `model_tools.get_tool_definitions(enabled_toolsets=..., disabled_toolsets=...)`
   - Filters tool schemas by toolset.
   - Plugin-registered tools also respect the normal toolset path.

3. `hermes_cli.plugins.set_thread_tool_whitelist(...)`
   - Optional runtime hard-block by tool name for the current thread.
   - Existing Hermes background skill/memory review uses this with `enabled_toolsets=["memory", "skills"]`.
   - This is appropriate for resolver/planner read-only skill inspection: expose `skills` toolset, whitelist only `skills_list` and `skill_view`.

4. `PluginContext.llm.complete_structured(...)`
   - Good for tool-free structured calls.
   - It does not provide a general tool-calling loop, so it is not enough for resolver/planner if we want them to call `skills_list` / `skill_view` themselves.

Existing self-improvement code currently uses direct `agent.auxiliary_client.call_llm(...)` in resolver/planner/memory_extractor/prompt_optimizer and custom native loops in `skill_agent_backend.py` / `memory_agent_backend.py`. The simplification target is to move role execution toward Hermes-native constrained agents where tools are needed, and structured no-tool calls where tools are not.

---

## Complexity guardrails

These are design guardrails for this roadmap and future sessions:

1. **Tool surface first.** Before adding a custom validator/loop, ask: can `enabled_toolsets` plus optional whitelist express the boundary?
2. **Mutation belongs to editors only.** Resolver/planner/evaluator/optimizer may reason, but only skill/memory editor roles get mutation tools.
3. **Read-only is not mutation-lite.** `skills_list` / `skill_view` are acceptable for resolver and planner because they improve judgment without changing state.
4. **Prompt before policy code.** For action-level preferences such as “do not delete in this task,” prefer prompt instructions and evaluator review unless there is a proven repeated failure.
5. **No new lanes.** Feed richer evidence into existing `improve` / `calibrate`; do not add queues, side channels, or special-case agent families.
6. **Deterministic apply stays small.** Promotion/application should be a tiny code path that saves the already-selected candidate, not another LLM decision.
7. **Tests lock simplicity.** Add regression tests proving role tool surfaces stay narrow, so future work does not drift back to all-tools or custom-loop designs.
8. **Existing bespoke loops are debt.** When touching `skill_agent_backend.py` or `memory_agent_backend.py`, prefer deleting/replacing plugin-owned tool-call replay, parser, and dispatcher layers with Hermes-native constrained agents. Keep post-validation/accounting; remove duplicated execution machinery.

---

## Non-goals

- Do not mutate Hermes core unless this repo proves the plugin API lacks the required surface.
- Do not add argument-level enforcement for every `skill_manage` action unless a concrete failure proves prompt/evaluator gates are insufficient.
- Do not give resolver/planner `skill_manage`, `memory`, `file`, `terminal`, `patch`, `execute_code`, `web`, `session_search`, or `delegation`.
- Do not let GEPA/optimizer write active overlays directly.
- Do not revive resolver `create_new_skill` as a resolver output. Resolver can say `unresolved / no_existing_skill_fit`; planner decides `create_skill`.

---

## Task 1: Add a central role permission matrix

**Objective:** Make allowed tools per LLM role explicit, testable, and hard to accidentally widen.

**Files:**
- Create or modify: `hermes_self_improvement/role_tool_permissions.py`
- Test: `tests/test_role_tool_permissions.py`

**Step 1: Write failing tests**

```python
def test_role_tool_permissions_matrix_is_minimal():
    from hermes_self_improvement.role_tool_permissions import ROLE_TOOL_PERMISSIONS

    assert ROLE_TOOL_PERMISSIONS["target_resolver"].allowed_tool_names == {"skills_list", "skill_view"}
    assert ROLE_TOOL_PERMISSIONS["improvement_planner"].allowed_tool_names == {"skills_list", "skill_view"}
    assert ROLE_TOOL_PERMISSIONS["skill_agent"].enabled_toolsets == ("skills",)
    assert ROLE_TOOL_PERMISSIONS["memory_agent"].enabled_toolsets == ("memory",)
    assert ROLE_TOOL_PERMISSIONS["evaluator"].allowed_tool_names == set()
    assert ROLE_TOOL_PERMISSIONS["prompt_optimizer"].allowed_tool_names == set()
```

Also assert no non-editor role has mutation tools:

```python
def test_only_editor_roles_can_have_mutation_tools():
    from hermes_self_improvement.role_tool_permissions import ROLE_TOOL_PERMISSIONS

    mutation_tools = {"skill_manage", "memory"}
    for role, spec in ROLE_TOOL_PERMISSIONS.items():
        if role not in {"skill_agent", "memory_agent"}:
            assert spec.allowed_tool_names.isdisjoint(mutation_tools)
```

**Step 2: Run RED**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_role_tool_permissions.py -q
```

Expected: fail because the module does not exist.

**Step 3: Implement minimal matrix**

Use a small dataclass; avoid abstraction beyond the current need.

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoleToolPermission:
    enabled_toolsets: tuple[str, ...] = ()
    allowed_tool_names: frozenset[str] = frozenset()
    tool_free: bool = False


ROLE_TOOL_PERMISSIONS = {
    "target_resolver": RoleToolPermission(
        enabled_toolsets=("skills",),
        allowed_tool_names=frozenset({"skills_list", "skill_view"}),
    ),
    "improvement_planner": RoleToolPermission(
        enabled_toolsets=("skills",),
        allowed_tool_names=frozenset({"skills_list", "skill_view"}),
    ),
    "skill_agent": RoleToolPermission(
        enabled_toolsets=("skills",),
        allowed_tool_names=frozenset({"skills_list", "skill_view", "skill_manage"}),
    ),
    "memory_agent": RoleToolPermission(
        enabled_toolsets=("memory",),
        allowed_tool_names=frozenset({"memory"}),
    ),
    "memory_extractor": RoleToolPermission(tool_free=True),
    "evaluator": RoleToolPermission(tool_free=True),
    "prompt_optimizer": RoleToolPermission(tool_free=True),
}
```

Keep names aligned with existing role/site names (`target_resolver`, `improvement_planner`, `skill_agent`, `memory_agent`, `memory_extractor`, `evaluator`, `prompt_optimizer`).

**Step 4: Run GREEN**

```bash
$PY -m pytest tests/test_role_tool_permissions.py -q
```

---

## Task 2: Add a tiny constrained-agent runner helper

**Objective:** Provide one small helper for roles that need Hermes tool calls, instead of duplicating hand-written tool-call loops.

**Files:**
- Create or modify: `hermes_self_improvement/constrained_agent.py`
- Test: `tests/test_constrained_agent.py`

**Step 1: Write tests with fakes**

Test that the helper constructs `AIAgent` with the role's `enabled_toolsets` and wraps execution in `set_thread_tool_whitelist` when `allowed_tool_names` is non-empty.

```python
def test_constrained_agent_uses_role_toolsets_and_whitelist(monkeypatch):
    calls = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            calls["agent_kwargs"] = kwargs
        def run_conversation(self, **kwargs):
            calls["run_kwargs"] = kwargs
            return {"final_response": "{}"}

    monkeypatch.setattr("hermes_self_improvement.constrained_agent.AIAgent", FakeAgent)
    monkeypatch.setattr("hermes_self_improvement.constrained_agent.set_thread_tool_whitelist", lambda allowed, deny_msg_fmt=None: calls.setdefault("allowed", allowed))
    monkeypatch.setattr("hermes_self_improvement.constrained_agent.clear_thread_tool_whitelist", lambda: calls.setdefault("cleared", True))

    result = run_constrained_role_agent(
        role="target_resolver",
        user_message="{}",
        system_message="resolver",
        config={},
    )

    assert calls["agent_kwargs"]["enabled_toolsets"] == ["skills"]
    assert calls["allowed"] == {"skills_list", "skill_view"}
    assert calls["cleared"] is True
```

**Step 2: Implement helper**

Keep it thin:

- Resolve role permission from Task 1.
- Instantiate `AIAgent` only for non-tool-free roles.
- Pass `enabled_toolsets=list(spec.enabled_toolsets)`.
- Set `quiet_mode=True`, `skip_memory=True`, `skip_context_files=True` for these internal role agents unless a concrete role needs ambient context.
- Use `set_thread_tool_whitelist(set(spec.allowed_tool_names), ...)` around `run_conversation`.
- Always clear whitelist in `finally`.

Do **not** add retry engines, approval queues, custom dispatchers, or argument validators here.

**Step 3: Verify**

```bash
$PY -m pytest tests/test_constrained_agent.py -q
```

---

## Task 3: Let target_resolver use read-only skill tools

**Objective:** Allow resolver to inspect existing skills with `skills_list` / `skill_view`, while keeping resolver output attachment-only.

**Files:**
- Modify: `hermes_self_improvement/target_resolver.py`
- Test: `tests/test_target_resolver.py`

**Step 1: Write tests**

Add a test proving resolver uses the constrained role runner when model config is present and that its role is `target_resolver`.

```python
def test_target_resolver_uses_read_only_skill_agent(monkeypatch):
    calls = {}

    def fake_run(*, role, system_message, user_message, config, **kwargs):
        calls["role"] = role
        return {"final_response": '{"resolutions": []}'}

    monkeypatch.setattr("hermes_self_improvement.target_resolver.run_constrained_role_agent", fake_run)

    result = run_target_resolver({"skill_targets": []}, config={"model": {"target_resolver": {}}})

    assert calls["role"] == "target_resolver"
    assert result["resolutions"] == []
```

Keep existing tests that reject resolver-owned creation/mutation decisions.

**Step 2: Implement minimal change**

Replace direct `call_llm(...)` in `_call_resolver_llm()` with the constrained role runner. Parse `final_response` the same way existing code parses LLM text.

Prompt update: explicitly say resolver may call `skills_list` / `skill_view` to inspect existing skill coverage, but must output only the allowed resolution kinds:

- `attach_existing_skill`
- `mutate_memory`
- `unresolved`
- `skip_noise`

Resolver must not call `skill_manage` and must not output `create_skill` / `create_new_skill`.

**Step 3: Verify**

```bash
$PY -m pytest tests/test_target_resolver.py -q
```

---

## Task 4: Let planner use read-only skill tools

**Objective:** Allow planner to inspect skills before deciding the action, without giving it mutation authority.

**Files:**
- Modify: `hermes_self_improvement/improvement_planner.py`
- Test: `tests/test_knowledge_maintenance_planner.py` or `tests/test_improvement_planner.py`

**Step 1: Write tests**

```python
def test_improvement_planner_uses_read_only_skill_agent(monkeypatch):
    calls = {}

    def fake_run(*, role, system_message, user_message, config, **kwargs):
        calls["role"] = role
        return {"final_response": '{"decisions": []}'}

    monkeypatch.setattr("hermes_self_improvement.improvement_planner.run_constrained_role_agent", fake_run)

    result = _call_improvement_planner_llm(digest={"skill_candidates": []}, config={"model": {"improvement_planner": {}}})

    assert calls["role"] == "improvement_planner"
    assert result["decisions"] == []
```

Add or keep a permission-matrix test proving planner cannot see `skill_manage`.

**Step 2: Implement minimal change**

Replace direct `call_llm(...)` in `_call_improvement_planner_llm()` with the constrained role runner.

Prompt update: planner may use `skills_list` / `skill_view` to check coverage or current skill content, but must not mutate. It should return a task manifest / decision only.

**Step 3: Verify**

```bash
$PY -m pytest tests/test_knowledge_maintenance_planner.py tests/test_role_tool_permissions.py -q
```

---

## Task 5: Keep tool-free roles tool-free, but clarify host-provided context

**Objective:** Prevent confusion that evaluator/optimizer/memory_extractor are blind. They should receive prepared context, not file tools.

**Files:**
- Modify: `hermes_self_improvement/memory_extractor.py`
- Modify if needed: `hermes_self_improvement/dspy_program.py`
- Modify if needed: `hermes_self_improvement/autonomous_evaluator.py`
- Test: existing role/tool permission tests

**Step 1: Add tests**

```python
def test_tool_free_roles_have_no_enabled_toolsets():
    from hermes_self_improvement.role_tool_permissions import ROLE_TOOL_PERMISSIONS

    for role in ["memory_extractor", "evaluator", "prompt_optimizer"]:
        spec = ROLE_TOOL_PERMISSIONS[role]
        assert spec.tool_free is True
        assert spec.enabled_toolsets == ()
        assert spec.allowed_tool_names == frozenset()
```

**Step 2: Documentation/prompt comments only**

Add concise comments/docstrings where useful:

- host code reads artifacts/inventory;
- LLM receives compact JSON/context;
- LLM has no file write/read tools.

Do not add code paths unless existing code accidentally gives these roles tools.

**Step 3: Verify**

```bash
$PY -m pytest tests/test_role_tool_permissions.py -q
```

---

## Task 6: Remove/simplify existing bespoke editor loops

**Objective:** Treat the already-complex native skill/memory agent loops as technical debt and refactor them toward Hermes-native constrained agents, without losing the simple role boundary: skill editor gets `skills`, memory editor gets `memory`.

This is a complexity-reduction slice, not a feature expansion. The success condition is less plugin-owned tool-loop machinery, fewer custom parser/executor paths, and no new general-purpose agent framework inside `hermes-self-improvement`.

**Files:**
- Modify: `hermes_self_improvement/skill_agent_backend.py`
- Modify: `hermes_self_improvement/memory_agent_backend.py`
- Test: existing skill/memory agent backend tests

**Step 1: Add characterization tests before refactor**

Lock current externally visible behavior:

- successful skill create/patch returns `used_tools`, changed/created skill names, verification notes;
- memory add/replace/remove returns changed/removed memory accounting;
- no direct file/terminal tools are available;
- dry-run still does not mutate.

**Step 2: Refactor one backend at a time, deleting complexity as you go**

Start with `skill_agent_backend.py`:

- Render the same task prompt.
- Run `AIAgent(enabled_toolsets=["skills"])` via constrained helper with role `skill_agent`.
- Keep only the post-validation/readback/accounting logic that proves what actually changed.
- Remove plugin-owned tool-call replay/parsing/dispatch code when Hermes has already executed the official tools.
- Do not preserve custom loop layers merely for compatibility if tests show the Hermes-native path covers the behavior.

Then do `memory_agent_backend.py` similarly with `enabled_toolsets=["memory"]`:

- Keep official memory-tool execution and post-validation/accounting.
- Remove duplicate provider/tool-call loop code that is replaced by the constrained Hermes agent surface.

**Important:** This task is a refactor/hardening slice. If it becomes large, split into two child plans:

- `skill_agent` simplification
- `memory_agent` simplification

Do not build a new general agent framework inside the plugin.

**Progress so far:**

- Role tool-surface constants now come from `ROLE_TOOL_PERMISSIONS` for both editor backends.
- Shared native tool-call parsing, provider-compatible tool-result messages, result normalization, and output redaction have been extracted into `native_tool_harness.py`, so `memory_agent_backend.py` no longer imports helper machinery from `skill_agent_backend.py`.
- `native_tool_harness.py` can now recover a compact mutation/tool trace from Hermes `AIAgent.run_conversation(...)["messages"]`, including both native `role="tool"` results and provider-compatible user-role tool-result context. `constrained_agent.py` attaches this trace to normalized role-agent results when messages are available.
- `NativeSkillAgentBackend` now has a thin constrained-agent adapter path: when a constrained runner is supplied, it sends the existing skill-agent task context through `run_constrained_role_agent(role="skill_agent")`, parses the final JSON response, injects recovered `tool_trace` as `used_tools`, and reuses the existing target validation / post-validation / accounting logic.
- `NativeMemoryAgentBackend` now has the same thin constrained-agent adapter shape: when a constrained runner is supplied, it sends the existing memory-agent task context through `run_constrained_role_agent(role="memory_agent")`, parses the final JSON response, injects recovered memory `tool_trace` as `used_tools`, and reuses the existing memory result validation/accounting contract.
- `build_skill_agent_backend()` and `build_memory_agent_backend()` now default to the constrained Hermes agent paths. The old bespoke native loops remain available only for direct/injected backend tests or explicit construction while the default route uses Hermes `AIAgent(enabled_toolsets=...)` plus role whitelisting.
- The legacy plugin-owned native loops no longer have a live auxiliary-LLM fallback: they require an injected `llm_call` and fail closed otherwise. This prevents accidental production drift back to bespoke tool-call replay while keeping deterministic injected tests for legacy behavior.
- The unused `_call_hermes_auxiliary_native` fallback functions and their `agent.auxiliary_client.call_llm` imports were removed from both editor backends. Tests now assert the editor backends do not carry this auxiliary fallback surface.
- Production-facing editor tool schema helpers now expose only real Hermes tools (`skills_list` / `skill_view` / `skill_manage` for skill agent, `memory` for memory agent). The synthetic `submit_mutation_result` schema is isolated behind legacy injected-loop schema helpers, so default constrained agents use final JSON instead of a custom submit tool.
- Default prompt-overlay seeds for `skill_agent` and `memory_agent` now describe the final-JSON contract and no longer instruct agents to call `submit_mutation_result`.
- Remaining work is physical cleanup of the injected-test-only loop bodies once mutation-bearing real-run evidence confirms constrained trace completeness and final JSON accounting.

**Step 3: Verify**

```bash
$PY -m pytest tests/test_skill_agent_backend.py tests/test_memory_agent_backend.py -q
```

---

## Task 7: Keep GEPA optimizer candidate generation separate from deterministic promote/apply

**Objective:** Clarify and test that GEPA creates candidates, evaluator scores them, and deterministic code promotes only the selected passing candidate.

**Files:**
- Modify if needed: `hermes_self_improvement/calibration.py`
- Test: `tests/test_calibration.py`

**Step 1: Add/keep tests**

Assert optimizer output alone does not update active overlay pointers. Active pointer changes only in the promotion/apply function after evaluation gates pass.

**Step 2: Add comments/docs**

Document the split:

```text
optimizer: propose candidates
 evaluator: score candidates
 promote/apply: deterministic save of selected winner
```

**Step 3: Verify**

```bash
$PY -m pytest tests/test_calibration.py -q
```

---

## Task 8: Resolver → planner handoff remains broad-entry / planner-owned exit

**Objective:** Keep prior design intent: resolver may discover `no_existing_skill_fit`, but planner chooses `create_skill` / `mutate_skill` / `skip` / `defer`.

**Files:**
- Modify if needed: `hermes_self_improvement/improvement_planner.py`
- Test: `tests/test_knowledge_maintenance_planner.py`

**Step 1: Add regression tests**

Cases:

1. Resolver `unresolved / no_existing_skill_fit` with high confidence and enough evidence becomes planner material.
2. Planner can choose `create_skill` for that material.
3. Resolver output containing `create_new_skill` is still rejected/normalized away.
4. Low-confidence/generic resolver output remains unresolved/deferred.

**Step 2: Implement only if missing**

If current implementation already has part of this, add tests first and make the smallest missing change.

**Step 3: Verify**

```bash
$PY -m pytest tests/test_target_resolver.py tests/test_knowledge_maintenance_planner.py -q
```

---

## Task 9: Roadmap and index update

**Objective:** Ensure future sessions do not drift back to complex bespoke loops.

**Files:**
- Modify: `.hermes/plans/README.md`
- Modify: `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`

**Required updates:**

- Current active hardening plan points to this file.
- Roadmap principles include “role tool surfaces are explicit and minimal.”
- Final loop explains resolver/planner read-only skill inspection and editor-only mutation.
- Active slice queue includes this constrained role tooling slice.

**Verify:**

```bash
git diff --check
```

---

## Task 10: Full validation

**Objective:** Prove the plan's implementation is safe and does not regress current self-improvement behavior.

**Commands:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests/test_role_tool_permissions.py tests/test_constrained_agent.py tests/test_target_resolver.py tests/test_knowledge_maintenance_planner.py -q
$PY -m pytest tests -q
git diff --check
hermes self-improvement status --json
hermes self-improvement improve --dry-run --json > /tmp/self-improvement-constrained-role-tools-dry-run.json
```

Expected:

- Resolver/planner can inspect skills read-only.
- Resolver/planner cannot mutate skills or memory.
- Skill mutations still happen only through `skill_agent` / official skill tools.
- Memory mutations still happen only through `memory_agent` / official memory tool.
- Evaluator/GEPA remain tool-free and use prepared artifacts/context.
- Dry-run remains non-mutating.

---

## Review checklist

- [ ] `target_resolver` allowed tools are exactly `skills_list`, `skill_view`.
- [ ] `improvement_planner` allowed tools are exactly `skills_list`, `skill_view`.
- [ ] `skill_agent` is the only skill mutation role.
- [ ] `memory_agent` is the only memory mutation role.
- [ ] evaluator / memory_extractor / prompt_optimizer have no tools.
- [ ] No `file`, `terminal`, `patch`, `execute_code`, `web`, `session_search`, or `delegation` appears in role permission specs.
- [ ] GEPA candidate generation and deterministic promotion remain separate.
- [ ] No new queues, lanes, approval systems, or custom general-purpose agent loops were added.
- [ ] Roadmap and plan index reflect the simplified design.
