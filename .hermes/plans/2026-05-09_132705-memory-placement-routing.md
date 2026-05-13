# Memory Placement Routing Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Status:** implemented 2026-05-09. Full test passed (`527 passed, 2 skipped`), dry-run verification produced `Would apply: 0 / Deferred: 26 / Skipped: 9 / Blocked: 0` with explicit `Memory placement` routing lines, and no mutating dogfood was run.

**Goal:** Make memory-noise cleanup preserve useful learning signals by routing non-memory observations to the right next destination: skill maintenance, diagnostic evidence, duplicate/no-op, memory inventory defer, or actionable memory mutation.

**Architecture:** Keep the existing `improve` evidence -> resolver -> planner -> worker flow. Do not add a new lane, approval mode, or resolver mutation action. Add small routing metadata and summary buckets so the memory step can say “not memory, but route to skill/diagnostic/defer/duplicate” instead of collapsing everything into `memory_observation_not_mutation_ready`.

**Tech Stack:** Python, pytest, existing `hermes self-improvement` CLI, existing evidence pack / memory runner / skill planner digest. Mutation stays bounded to official memory and skill tools.

---

## Current context

Recent dry-run after `b217669 fix: reduce memory candidate noise`:

```text
Artifact: /Users/ryo.nakae/.hermes/self-improvement/runs/run-20260509T035725Z.json
Would apply: 0
Deferred: 3
Skipped: 32
Blocked: 2
```

The noise cleanup worked: `memory_operation_missing` and `memory_inventory_operation_missing` no longer inflate `Blocked`. The remaining concern is placement quality:

- `timeout workflow`, `patch tool workflow`, and `sandbox permission workflow` are correctly **not memory**, but should be clearly routed toward skill maintenance.
- raw `execute_code` JSON/run output is diagnostic evidence, not memory content.
- semantic duplicate memory candidates should become `skip` / no-op, not `memory_add`.
- memory inventory candidates without exact operations should remain `defer`, because LLM placement/planner still needs to decide exact add/replace/remove/move.

The current dry-run summary hides these differences under:

```text
skip: memory_observation_not_mutation_ready
```

That protects memory quality, but makes it hard to see whether useful information was preserved and routed.

## Non-goals

- Do not add a separate memory/skill routing lane.
- Do not add new user-facing action categories beyond `apply / defer / skip / block`.
- Do not reintroduce resolver mutation vocabulary such as `create_new_skill`.
- Do not auto-edit built-in, hub, plugin-bundled, external-dir, pinned, archived, or ambiguous-provenance skills.
- Do not parse LLM-authored Markdown as control state.
- Do not treat raw terminal/search/read/patch/execute output or run artifact dumps as memory facts.
- Do not run mutating dogfood as part of this slice unless a later user explicitly asks.

## Desired behavior

### Placement categories

Memory runner decisions should keep semantic `apply / defer / skip / block`, but include placement metadata:

```json
{
  "decision": "skip",
  "reason": "not_memory_workflow_to_skill",
  "suggested_route": "skill",
  "workflow_boundary": "patch tool workflow"
}
```

Recommended reason vocabulary:

```text
memory_duplicate_existing          -> skip
not_memory_raw_tool_output         -> skip
not_memory_workflow_to_skill       -> skip
not_memory_diagnostic_only         -> skip
memory_inventory_needs_planner     -> defer
memory_placement_needs_routing     -> defer
memory_observation_not_mutation_ready -> fallback only
```

### Summary output

Dry-run should expose compact placement lines without adding action buckets:

```text
Memory placement:
- duplicate existing memory: 1
- routed to skill maintenance: patch tool workflow 1, timeout workflow 1, sandbox permission workflow 1
- diagnostic only: raw execute_code output 2
- needs memory planner: 3
```

`Action summary` remains:

```text
Would apply: N, Deferred: N, Skipped: N, Blocked: N
```

### Routing principle

- **Memory:** stable user preference, environment fact, durable project convention, compact correction.
- **Skill:** reusable procedure, multi-step workflow, tool usage pitfall, troubleshooting recipe, decision flow.
- **Diagnostic evidence:** raw outputs, stack traces, run summaries, command transcripts, isolated failure observations.
- **Defer:** plausible memory/placement improvement but missing exact `old_text`, exact operation, or enough context.
- **Block:** sensitive content, unsupported target, unsafe delete, non-mutable target, or hard invariant failure.

---

## Step-by-step implementation plan

### Task 1: Add placement routing regression tests for memory runner decisions

**Objective:** Ensure non-memory observations are routed explicitly instead of being hidden behind generic `memory_observation_not_mutation_ready`.

**Files:**
- Modify: `tests/test_memory_inventory_planner.py`
- Modify: `hermes_self_improvement/runner_steps.py`

**Step 1: Write failing tests**

Add tests for three evidence kinds:

```python
def test_memory_step_routes_workflow_candidates_to_skill_not_memory():
    evidence = {
        "id": "coverage-patch",
        "kind": "knowledge_coverage_candidate",
        "source": "knowledge_coverage",
        "summary": "Observed 35 patch failures that likely need reusable patch/tool-editing workflow guidance.",
        "target_resolution_hint": {
            "resolution_kind": "unresolved",
            "maintenance_affordance": {
                "workflow_boundary": "patch tool workflow",
                "possible_actions": ["patch_existing_skill", "create_skill"],
            },
        },
    }
    result = run_memory_improvement_step(evidence_pack=_pack([evidence]), config={}, mutate=False)
    assert result["decisions"] == [{
        "evidence_id": "coverage-patch",
        "decision": "skip",
        "reason": "not_memory_workflow_to_skill",
        "suggested_route": "skill",
        "workflow_boundary": "patch tool workflow",
        "changed": False,
    }]
```

Add similar tests for:

```text
unmatched_improvement_candidate -> not_memory_workflow_to_skill
memory_placement_candidate with allowed_recommendations containing convert_to_skill_update -> memory_placement_needs_routing or not_memory_workflow_to_skill depending on exact evidence
```

**Step 2: Run RED**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_memory_inventory_planner.py::test_memory_step_routes_workflow_candidates_to_skill_not_memory -q
```

Expected: FAIL because current code emits generic `memory_observation_not_mutation_ready`.

**Step 3: Implement minimal routing helper**

In `hermes_self_improvement/runner_steps.py`, add a helper near memory decision logic:

```python
def _memory_non_operation_route(item: dict[str, Any]) -> dict[str, Any]:
    ...
```

It should return compact fields:

```python
{
    "decision": "skip" | "defer",
    "reason": "not_memory_workflow_to_skill" | "not_memory_diagnostic_only" | "memory_placement_needs_routing" | ...,
    "suggested_route": "skill" | "diagnostic" | "memory_planner" | "none",
    "workflow_boundary": optional,
}
```

Use existing evidence fields only. Do not call LLM here. This helper should classify obvious placement routes, not decide mutations.

**Step 4: Run GREEN**

```bash
$PY -m pytest tests/test_memory_inventory_planner.py -q
```

Expected: pass.

---

### Task 2: Route raw tool output as diagnostic skip instead of block

**Objective:** Make obvious raw tool/run output disappear from `Blocked` while preserving it as diagnostic evidence.

**Files:**
- Modify: `tests/test_memory_inventory_planner.py` or create `tests/test_memory_candidate_routing.py`
- Modify: `hermes_self_improvement/runner_steps.py`

**Step 1: Write failing test**

Create evidence shaped like the real blocked items:

```python
def test_raw_execute_code_output_is_diagnostic_skip_not_block():
    evidence = {
        "id": "raw-exec",
        "kind": "memory_evidence",
        "event": {
            "tool_name": "execute_code",
            "result_preview": "{\"status\": \"success\", \"output\": \"action_summary {'apply': 4}\"}",
        },
    }
    result = run_memory_improvement_step(evidence_pack=_pack([evidence]), config={}, mutate=False)
    assert result["decisions"][0]["decision"] == "skip"
    assert result["decisions"][0]["reason"] == "not_memory_raw_tool_output"
    assert result["decisions"][0]["suggested_route"] == "diagnostic"
```

**Step 2: Run RED**

```bash
$PY -m pytest tests/test_memory_inventory_planner.py::test_raw_execute_code_output_is_diagnostic_skip_not_block -q
```

Expected: FAIL because current `_reject_reason=memory_payload_not_fact` becomes `rejected` / block.

**Step 3: Implement minimal change**

In `run_memory_improvement_step()`, when `_memory_operation_from_evidence()` returns `_reject_reason == memory_payload_not_fact`, emit:

```python
{
    "decision": "skip",
    "reason": "not_memory_raw_tool_output",
    "suggested_route": "diagnostic",
    "changed": False,
    "operation": operation,
}
```

Keep secret/sensitive rejects as `rejected` / block. Only raw diagnostic non-facts move to skip.

**Step 4: Run GREEN**

```bash
$PY -m pytest tests/test_memory_inventory_planner.py -q
```

Expected: pass.

---

### Task 3: Preserve duplicate/no-op memory reason in evidence and summary

**Objective:** Make semantic duplicate suppression visible so users know memory facts were not lost, only deduped.

**Files:**
- Modify: `tests/test_conversation_memory_candidates.py`
- Modify: `hermes_self_improvement/conversation_memory.py`
- Possibly modify: `hermes_self_improvement/cli.py`

**Step 1: Write failing tests**

Extend existing duplicate test to assert explicit no-op metadata:

```python
candidate = out["candidates"][0]
assert candidate["action"] == "skip"
assert candidate["relation_to_existing"] == "duplicate_existing_memory"
assert candidate["skip_reason"] == "memory_duplicate_existing"
assert candidate["matched_existing_text"]
```

Also verify stale path replacement still works:

```python
assert candidate["action"] == "replace"
assert candidate["old_text"] == "Hermes runtime root is /opt/data."
```

**Step 2: Run RED**

```bash
$PY -m pytest tests/test_conversation_memory_candidates.py -q
```

Expected: FAIL because skip reason/matched text are not currently exposed.

**Step 3: Implement minimal metadata**

In `reconcile_memory_gap_payload_with_existing_memories()`:

- add `skip_reason: memory_duplicate_existing` for duplicate skip
- add redacted `matched_existing_text` for audit/debug
- keep replace logic for conflicting specific values

**Step 4: Run GREEN**

```bash
$PY -m pytest tests/test_conversation_memory_candidates.py -q
```

Expected: pass.

---

### Task 4: Add memory placement summary renderer

**Objective:** Show where non-memory candidates went without opening JSON artifacts.

**Files:**
- Modify: `tests/test_cli_surface.py`
- Modify: `hermes_self_improvement/cli.py`
- Possibly modify: `hermes_self_improvement/tool_handlers.py` for agent-facing tool summary parity

**Step 1: Write failing test**

Add a CLI summary test that feeds a result payload with memory decisions:

```python
step_decisions = {
    "memory": {
        "decisions": [
            {"decision": "skip", "reason": "not_memory_workflow_to_skill", "workflow_boundary": "patch tool workflow", "suggested_route": "skill"},
            {"decision": "skip", "reason": "not_memory_raw_tool_output", "suggested_route": "diagnostic"},
            {"decision": "defer", "reason": "memory_inventory_needs_planner"},
            {"decision": "skip", "reason": "memory_duplicate_existing"},
        ]
    }
}
```

Expected output contains:

```text
Memory placement:
- duplicate existing memory: 1
- routed to skill maintenance: patch tool workflow 1
- diagnostic only: raw tool output 1
- needs memory planner: 1
```

**Step 2: Run RED**

```bash
$PY -m pytest tests/test_cli_surface.py -q
```

Expected: FAIL until renderer includes placement section.

**Step 3: Implement compact renderer**

Add helper in `cli.py`:

```python
def _memory_placement_summary(step_decisions: dict[str, Any]) -> dict[str, Any]:
    ...
```

Render only non-empty lines. Keep max detail short:

- top 3 workflow boundaries
- count diagnostic-only
- count duplicate existing
- count needs planner/routing

Do not change `Action summary` buckets.

**Step 4: Tool result parity**

If agent-facing `self_improvement_improve` uses `tool_handlers.py` summaries, add the same compact `memory_placement` object there. Keep it compact; full details stay in run artifact.

**Step 5: Run GREEN**

```bash
$PY -m pytest tests/test_cli_surface.py tests/test_memory_inventory_planner.py -q
```

Expected: pass.

---

### Task 5: Feed skill-routed observations into skill planner digest more explicitly

**Objective:** Ensure “not memory, workflow to skill” observations are not merely skipped by memory runner but remain easy for the skill planner to act on.

**Files:**
- Modify: `tests/test_skill_planner.py` or `tests/test_knowledge_maintenance_planner.py`
- Modify: `hermes_self_improvement/planner.py` if needed
- Possibly modify: `hermes_self_improvement/evidence.py`

**Step 1: Inspect current behavior**

Read the latest evidence pack:

```text
/Users/ryo.nakae/.hermes/self-improvement/evidence/evidence-2026-05-09T03-56-21.977497-00-00.json
```

Confirm `unmatched_improvement_candidate` and `knowledge_coverage_candidate` already appear in the skill planner digest as `unresolved_observations` / `maintenance_candidates`.

**Step 2: Add regression test only if current digest is weak**

If the digest already exposes these candidates clearly, skip production changes and add a narrow test documenting it.

Expected assertion shape:

```python
km = digest["knowledge_maintenance"]
assert km["maintenance_candidates"][0]["workflow_boundary"] == "patch tool workflow"
assert km["maintenance_candidates"][0]["suggested_route"] == "skill"
```

**Step 3: Implement minimal metadata pass-through if needed**

Do not create a new routing lane. Add only compact fields that help the existing planner:

```text
suggested_route: skill
workflow_boundary
not_memory_because: procedural recurring workflow
```

**Step 4: Run GREEN**

```bash
$PY -m pytest tests/test_knowledge_maintenance_planner.py tests/test_skill_planner.py -q
```

Expected: pass.

---

### Task 6: Dry-run verification only, no mutating dogfood

**Objective:** Validate placement routing without applying changes.

**Commands:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
git diff --check
hermes self-improvement improve --dry-run
```

Expected dry-run shape:

```text
Action summary:
- Would apply: 0, Deferred: 3, Skipped: 34, Blocked: 0
Memory placement:
- routed to skill maintenance: patch tool workflow 1, sandbox permission workflow 1, timeout workflow 1
- diagnostic only: raw tool output 2
- needs memory planner: 3
```

The exact counts may vary with new observations, but important expectations are:

- raw tool output is not `Blocked`
- workflow gaps are visible as skill-routed
- duplicate memory candidates are no-op/skip, not add
- memory inventory without exact operation is defer, not block
- no mutating run is executed in this slice

---

### Task 7: Commit and push one coherent milestone

**Objective:** Keep repo clean and reviewable.

**Commands:**

```bash
git status --short
git diff --check
git add \
  hermes_self_improvement/runner_steps.py \
  hermes_self_improvement/conversation_memory.py \
  hermes_self_improvement/cli.py \
  hermes_self_improvement/tool_handlers.py \
  hermes_self_improvement/planner.py \
  tests/test_memory_inventory_planner.py \
  tests/test_conversation_memory_candidates.py \
  tests/test_cli_surface.py \
  tests/test_knowledge_maintenance_planner.py \
  .hermes/plans/README.md \
  .hermes/plans/2026-05-09_132705-memory-placement-routing.md
git commit -m "fix: clarify memory placement routing"
git push
```

Only stage files actually changed.

---

## Files likely to change

Core:

- `hermes_self_improvement/runner_steps.py`
  - classify non-memory observations with explicit route metadata
  - make raw tool output diagnostic skip rather than block
- `hermes_self_improvement/conversation_memory.py`
  - expose duplicate/no-op metadata
- `hermes_self_improvement/cli.py`
  - render compact `Memory placement` summary
- `hermes_self_improvement/tool_handlers.py`
  - optional agent-facing summary parity
- `hermes_self_improvement/planner.py`
  - only if skill planner digest needs explicit route pass-through

Tests:

- `tests/test_memory_inventory_planner.py`
- `tests/test_conversation_memory_candidates.py`
- `tests/test_cli_surface.py`
- `tests/test_knowledge_maintenance_planner.py` if planner digest pass-through needs coverage

Docs/plans:

- `.hermes/plans/README.md`
- `.hermes/plans/2026-05-09_132705-memory-placement-routing.md`

## Risks and mitigations

### Risk: Over-classifying non-memory evidence as skill work

Mitigation:

- Only route to skill for recurring workflow / maintenance-affordance evidence.
- Raw one-off logs stay diagnostic-only.
- Skill planner still decides whether to patch/create/merge/archive/skip/defer/block.

### Risk: Hiding real unsafe memory candidates by turning blocks into skips

Mitigation:

- Only `memory_payload_not_fact` from raw tool output becomes skip.
- Secrets, unsupported targets, unsafe deletes, sensitive text, and non-executable provider targets remain block/rejected.

### Risk: Duplicate detection suppresses useful refinements

Mitigation:

- Duplicate skip applies when similarity/topic overlap is strong and no conflicting specific values are present.
- Conflicting paths/files/versions remain replace candidates.
- Relation claims like `extends existing` without `old_text` still defer.

### Risk: Summary becomes noisy

Mitigation:

- Keep summary compact and count-based.
- Show only top 3 workflow boundaries.
- Preserve full details in artifacts.

## Success criteria

A good implementation should make dry-run answer the user’s concern directly:

```text
Memory placement:
- duplicate existing memory: N
- routed to skill maintenance: ...
- diagnostic only: ...
- needs memory planner: ...
```

This proves that memory cleanup is not just dropping information. It is preserving evidence and making the intended destination visible while keeping actual mutation decisions inside the existing planner/worker boundaries.
