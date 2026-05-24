# Memory-to-Skill Safe Migration Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Make `hermes-self-improvement` safely migrate procedural built-in memory entries into skills, then remove the source memory only after the skill mutation succeeds.

**Architecture:** Keep the existing two-lane model (`skill_agent` mutates skills, `memory_agent` mutates built-in memory) and add a small orchestration bridge after both lanes run. Memory-side procedural decisions stay non-mutating until the bridge converts them into bounded skill-agent tasks. Source memory removal happens only after a successful skill patch/create result, using exact `old_text` through the official memory tool.

**Tech Stack:** Python, pytest, Hermes `skill_manage` / `memory` tools, existing `run_skill_agent_task()` and `_execute_memory_context()` helpers.

---

## Context and current behavior

Official Hermes memory guidance says reusable procedures/workflows belong in skills, not built-in `USER.md` / `MEMORY.md`. The plugin already recognizes this boundary:

- `memory_agent.py` tells memory_agent to return `decision="convert_to_skill_proposal"` for procedural reusable knowledge.
- `runner_steps.py::_normalize_inventory_operation()` normalizes `convert_to_skill_update` to `memory_convert_to_skill_update`.
- `_memory_non_mutating_operation_decision()` currently emits `decision="skip"`, `reason="memory_convert_to_skill_update"`, `suggested_route="skill"`.
- Tests currently assert this as a non-mutating route (`test_memory_placement_convert_to_skill_update_is_skill_routed_skip`).

The gap: no bridge creates/patches a skill and then removes the stale memory entry. This leaves memory pressure unresolved and keeps procedural guidance in built-in memory.

## Safety invariants

1. Never remove a source memory before the skill mutation succeeds.
2. Remove source memory only with exact `old_text` from `current_entries` / inventory.
3. If skill patch/create fails, memory remains unchanged.
4. Do not invent a new approval queue, new command, or broad orchestration lane.
5. Use only official mutation surfaces: `skill_manage` via skill_agent and `memory` tool via existing memory helpers.
6. Keep dry-run as preview-only; no skill or memory mutation in dry-run.
7. If no safe skill target is known, keep the decision routed to skill but do not remove memory.

## Proposed design

Add a narrow post-step bridge in `cli.run_improve()` and `run_replay_improve()` with a dedicated internal artifact section `step_decisions["memory_to_skill"]`.

1. Run existing `skill_step` first, then `memory_step` as today.
2. Inspect `memory_step["decisions"]` for `reason == "memory_convert_to_skill_update"` or `suggested_route == "skill"` with exact `old_text` available in `operation.old_text` or decision-level `old_text`.
3. Build a skill-agent task from the memory decision:
   - If `skill_route` is present and points to a mutable local skill, use `skill_improve` targeting that skill.
   - If only a workflow boundary is present, defer for now with `reason="memory_to_skill_missing_skill_route"` rather than guessing a new skill name.
   - If future planner output provides an explicit `create_skill` target, support `skill_create`; this slice should implement patch-existing first and keep create as preview/defer unless a proposed skill name is already present in the decision.
4. The bridge result schema is stable and compact:

```python
{
  "status": "preview" | "completed" | "no_candidates",
  "changed": 0,
  "changed_skills": [],
  "removed_memories": [],
  "decisions": [{
      "evidence_id": "...",
      "decision": "memory_to_skill_preview" | "accepted" | "defer" | "rejected",
      "reason": "...",
      "changed": False,
      "source_target": "memory" | "user",
      "old_text": "exact source entry text",
      "skill_route": "target-skill",
      "task": {...},
      "skill_result": {...},        # mutate only
      "memory_remove_result": {...}, # mutate only after validated skill success
  }],
}
```

5. In dry-run, emit only `memory_to_skill_preview` decisions under `step_decisions["memory_to_skill"]`; do not mutate skill or memory.
6. In mutate mode:
   - call `run_skill_agent_task()` with the built task;
   - require validated skill-agent success, not raw success only: success must include an applied outcome and the target in `changed_skills` or `created_skills` after the existing skill-agent backend validation;
   - only then call memory remove with the source `target` (`memory` or `user`) and exact `old_text`;
   - record both results in the bridge decision.
7. Report bridge counts in the existing summaries without creating a new product command/tool/queue.
8. Replay is deterministic: `run_replay_improve()` acts only on explicit `memory_to_skill_preview` entries from the dry-run artifact and uses the stored `old_text` / `skill_route` / task data rather than recomputing target routing.

## Task 1: Add RED tests for existing-skill memory→skill migration

**Objective:** Prove the desired safe sequence is missing before production code changes.

**Files:**
- Modify: `tests/test_cli_improve_memory_current_entries.py` or create `tests/test_memory_to_skill_migration.py`
- Possibly use helper imports from `hermes_self_improvement.cli` / `runner_steps`

**Test behavior:**

Create a focused unit test for a helper that does not exist yet, e.g. `apply_memory_to_skill_migrations(...)`:

```python
def test_memory_to_skill_migration_patches_skill_before_removing_memory():
    calls = []

    class FakeSkillBackend:
        def run(self, prompt, task, config=None):
            calls.append(("skill", task))
            return {
                "success": True,
                "outcome": "applied",
                "used_tools": [{"tool": "skill_manage", "action": "patch", "name": "hermes-memory-and-live-context", "success": True}],
                "changed_skills": ["hermes-memory-and-live-context"],
                "created_skills": [],
                "deleted_skills": [],
                "verification_notes": ["patched target skill"],
                "rollback_hints": [],
            }

    def fake_memory(**args):
        calls.append(("memory", args))
        return {"success": True, "changed": True}

    memory_step = {
        "decisions": [{
            "evidence_id": "memory-place-skill",
            "decision": "skip",
            "reason": "memory_convert_to_skill_update",
            "suggested_route": "skill",
            "skill_route": "hermes-memory-and-live-context",
            "operation": {
                "operation": "memory_convert_to_skill_update",
                "target": "skill",
                "source_target": "memory",
                "old_text": "Use these exact steps for live context cleanup.",
                "content": "Live context cleanup procedure belongs in a skill.",
            },
        }],
    }

    result = apply_memory_to_skill_migrations(
        memory_step=memory_step,
        config={"_memory_tool_fn": fake_memory, "_skill_agent_backend": FakeSkillBackend()},
        mutate=True,
    )

    assert result["changed"] == 1
    assert calls[0][0] == "skill"
    assert calls[1] == ("memory", {"action": "remove", "target": "memory", "old_text": "Use these exact steps for live context cleanup."})
```

**Run to verify RED:**

```bash
python -m pytest tests/test_memory_to_skill_migration.py::test_memory_to_skill_migration_patches_skill_before_removing_memory -q
```

Expected: FAIL because `apply_memory_to_skill_migrations` does not exist.

## Task 2: Preserve memory if skill mutation fails

**Objective:** Lock the most important safety property.

**Files:**
- Modify: `tests/test_memory_to_skill_migration.py`

**Test behavior:**

```python
def test_memory_to_skill_migration_keeps_memory_when_skill_fails():
    memory_calls = []

    class FailingSkillBackend:
        def run(self, prompt, task, config=None):
            return {"success": False, "error": "skill_agent_failed"}

    result = apply_memory_to_skill_migrations(
        memory_step=memory_step_with_old_text_and_skill_route(),
        config={"_memory_tool_fn": lambda **args: memory_calls.append(args), "_skill_agent_backend": FailingSkillBackend()},
        mutate=True,
    )

    assert result["changed"] == 0
    assert memory_calls == []
    assert result["decisions"][0]["reason"] == "memory_to_skill_skill_failed"
```

**Run to verify RED:** same file, expected FAIL until implementation exists.

## Task 2b: Add RED tests for preview, missing target, invalid backend, exact text, and replay

**Objective:** Cover the full safety boundary identified during plan review.

**Files:**
- Modify: `tests/test_memory_to_skill_migration.py`
- Modify: `tests/test_cli_replay.py` or the existing CLI surface test file if replay tests live there.

**Required tests:**

1. Dry-run preview does not call skill or memory tools and returns `status="preview"` plus `decision="memory_to_skill_preview"`.
2. Missing `skill_route` returns `decision="defer"`, `reason="memory_to_skill_missing_skill_route"`, and does not remove memory.
3. Skill backend unavailable / invalid result returns rejected/defer and does not remove memory.
4. A skill success result without the target in `changed_skills` / `created_skills` does not remove memory.
5. Exact `old_text` survives into the remove call, including punctuation and non-ASCII text.
6. Replay acts only on stored `step_decisions["memory_to_skill"]` preview decisions and uses stored `old_text` / `task` rather than recomputing from current memory routing.

## Task 3: Add helper functions in `runner_steps.py`

**Objective:** Implement the migration bridge without coupling it to CLI rendering.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`

**Implementation outline:**

Add helpers near memory operation helpers:

- `_memory_to_skill_decision_candidates(memory_step: dict) -> list[dict]`
- `_build_memory_to_skill_task(decision: dict, *, config: dict | None) -> tuple[dict | None, str | None]`
- `apply_memory_to_skill_migrations(*, memory_step, config, mutate) -> dict`

Task shape for existing skill patch:

```python
{
  "type": "skill_agent_task",
  "task_kind": "skill_improve",
  "targets": {"primary_skill": skill_route},
  "observed_problem": "Procedural reusable guidance is currently stored in built-in memory.",
  "desired_outcome": "Move the reusable procedure into the target skill without broad rewrites.",
  "suggested_focus": [content],
  "non_goals": [
      "Do not remove or rewrite memory directly from the skill agent.",
      "Do not edit unrelated skills.",
      "Do not broaden the procedure beyond the memory entry evidence.",
  ],
  "evidence_ids": [evidence_id],
  "instructions": "Patch the target skill with the procedural guidance if it is not already covered. Return a non-mutating outcome if already covered or stale.",
  "constraints": [...existing skill-agent constraints...],
  "expected_outcome": {"memory_removal_after_skill_success": True},
}
```

Mutation sequence:

```python
skill_result = run_skill_agent_task(task, config=config, backend=build_skill_agent_backend(config))
if not skill_success_with_change(skill_result, target):
    return rejected, no memory remove
remove_operation = {"operation": "memory_delete", "target": source_target, "old_text": old_text}
context = build_memory_mutation_context(provider=_external_memory_provider(config), operation=remove_operation)
remove_result = _execute_memory_context(context, config, operation=remove_operation, external_provider=_external_memory_provider(config))
```

Do not remove memory on non-mutating skill outcomes such as `skipped_superseded`; those are useful evidence that the source memory still needs human/planner review, not proof it was migrated.

## Task 4: Wire helper into CLI improve and replay

**Objective:** Make normal `improve` and `--from-run` execution use the bridge.

**Files:**
- Modify: `hermes_self_improvement/cli.py`

**Implementation outline:**

In `run_improve()` after `memory_step`:

```python
memory_to_skill_step = apply_memory_to_skill_migrations(
    memory_step=memory_step,
    config={**config, "_memory_tool_fn": memory_config.get("_memory_tool_fn"), ...},
    mutate=mutate,
)
```

Attach result under `step_decisions_payload` as either:

- `"memory_to_skill": memory_to_skill_step` (preferred: visible and auditable), or
- include decisions into `skill` / `memory` summaries if existing report code assumes only skill/memory/evaluator.

Keep this small: a new internal `step_decisions["memory_to_skill"]` is acceptable, but do not expose a new command/tool.

Update `summary` / top-level result:

- `skill_changes` include bridge changed skills.
- `memory_changes` include bridge removed memory ids.
- `summary.skill_changes` / `summary.memory_changes` account for bridge changes.

In `run_replay_improve()`, run the same helper after replayed memory decisions so a dry-run artifact with `memory_convert_to_skill_update` can be safely applied.

## Task 5: Reporting and compact tool summaries

**Objective:** Make the bridge visible enough for daily reports without noise.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/tool_handlers.py` if compact tool output ignores unknown steps.
- Modify: tests around CLI surface if needed.

Add compact lines such as:

- `Memory-to-skill migrations: 1 applied, 0 deferred`
- For dry-run: `Memory-to-skill migrations: 1 preview`

Do not dump full memory content in summaries.

## Task 6: Full verification and docs

**Objective:** Keep operations docs and plan index honest.

**Files:**
- Modify: `.hermes/plans/README.md`
- Modify: `skills/operations/SKILL.md` only if the runtime operator workflow changes.

Verification commands:

```bash
python -m pytest tests/test_memory_to_skill_migration.py tests/test_memory_inventory_planner.py tests/test_memory_agent.py -q
python -m pytest -q
git diff --check
hermes self-improvement status
```

Expected:

- focused tests pass
- full suite passes
- status reports skill/memory agent backend available
- working tree has only intended repo changes

## Review checklist before implementation

Independent review completed before implementation. Result: **REQUEST_CHANGES**, then incorporated into this plan.

Reviewer-required changes now reflected here:

- dedicated `step_decisions["memory_to_skill"]` schema;
- deterministic replay from explicit preview entries;
- validated skill success gate before memory removal;
- expanded RED tests for dry-run, missing route, backend failure, exact `old_text`, and replay;
- no guessing skill names without explicit `skill_route`;
- bridge remains internal and bounded.

Implementation review should still check:

1. Does the code preserve source memory until skill mutation succeeds?
2. Does it avoid a new lane/queue/command?
3. Does it use official skill and memory tools only?
4. Is dry-run non-mutating?
5. Is replay behavior safe and deterministic?
6. Does it avoid guessing skill names when no explicit `skill_route` exists?

## Done definition

- [x] A procedural memory decision with explicit `skill_route` can patch an existing local skill and then remove the exact source memory.
- [x] Skill failure leaves memory untouched.
- [x] Dry-run previews the bridge without mutation.
- [x] Replay from dry-run artifact follows the same safety rules and acts only on stored `memory_to_skill_preview` decisions.
- [x] Memory-agent `convert_to_skill_proposal` results are normalized into bridge decisions.
- [x] Current-entry exact `old_text` is required before source memory removal.
- [x] Partial success is reported: if skill changes but memory removal fails, the skill change remains visible while memory removal is not counted.
- [x] Tests and status pass: `python -m pytest -q` => `776 passed, 2 skipped`; `git diff --check` ok; `hermes self-improvement status` ok.
- [x] Final Codex blocker review: no blockers found.
