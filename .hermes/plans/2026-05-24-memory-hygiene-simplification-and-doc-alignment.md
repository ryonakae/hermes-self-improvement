# Memory Hygiene Simplification and Doc Alignment Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Fix the remaining USER/MEMORY/Skill hygiene gaps found after the memory current-entry handoff and memory-to-skill bridge work, while keeping the implementation simple and tool-native.

**Architecture:** Keep the existing lanes: `memory_agent` decides built-in memory changes through the official memory tool, `skill_agent` mutates skills through official skill tools, and the existing `memory_to_skill` bridge only handles procedural memory migration. This plan removes stale prompt/docs contradictions, broadens placement review to the existing memory_agent instead of adding a new classifier, makes memory-agent mutations visible in artifacts/summaries, and narrows custom file parsing follow-up to a small proof slice.

**Tech Stack:** Python, pytest, Hermes built-in `memory` tool / `MemoryStore`, Hermes `skill_manage`, existing `hermes self-improvement` CLI.

---

## Background

The previous implementation finished the core safe ordering:

- current `USER.md` / `MEMORY.md` entries are handed to `memory_agent` with exact `old_text`;
- procedural memory can become a `memory_to_skill_preview`;
- mutating replay updates the skill first and removes source memory only after validated skill success;
- replay checks the current exact `old_text` before removing memory.

The follow-up audit found several remaining issues:

1. `prompts.py` still says `Memory` includes user preferences, contradicting official USER/MEMORY boundaries.
2. `defaults/prompt-overlays/memory_agent.md` still says USER↔MEMORY moves should `remove` then `add`, contradicting add-before-remove safety.
3. Placement candidates are over-filtered: plain user preferences or environment facts in the wrong store can be kept without reaching `memory_agent`.
4. Successful `memory_agent` mutations are counted internally but not reliably surfaced in `decisions`, `changed_memories`, summaries, or episodes.
5. Built-in memory current-entry reads still use a small custom `§` parser. This is read-only and not urgent, but should be isolated as a proof/follow-up rather than expanded.

## Non-goals

- Do not edit real `~/.hermes/memories/USER.md` or `MEMORY.md` in this implementation.
- Do not create a new approval queue, new planner lane, or new memory classifier.
- Do not add a second memory lifecycle system or full memory sweep.
- Do not reintroduce old `bin/hermes-self-improve` surfaces.
- Do not add direct filesystem mutation fallback for memory or skills.

## Safety invariants

1. Any mutation of built-in memory goes through the official `memory` tool / `MemoryStore` path.
2. USER↔MEMORY move remains destination-add-before-source-remove.
3. Procedural memory migration remains skill-success-before-memory-remove.
4. If a candidate is ambiguous, sensitive, stale, or lacks exact `old_text`, no mutation happens.
5. Broadening placement visibility must not broaden execution permissions; it only gives the existing bounded `memory_agent` more evidence.

---

## Task 1: Align the shared USER/MEMORY/Skill classification prompt

**Objective:** Remove the stale statement that user preferences belong to `Memory` and make the shared classification block match official Hermes memory guidance.

**Files:**
- Modify: `hermes_self_improvement/prompts.py`
- Test: `tests/test_prompt_classification.py`
- Test: `tests/test_prompts.py` only if shared prompt coverage is split there during implementation

**Review note:** Existing `tests/test_prompt_classification.py` asserts the old `"Memory is factual"` wording. Update that test in this task; do not leave it as an unrelated failure.

**Step 1: Write failing test**

Add a test that imports `SKILL_MEMORY_CLASSIFICATION_BLOCK` and asserts:

- `USER` is described as user profile / preferences / communication style / expectations.
- `MEMORY` is described as agent notes / environment facts / project conventions / learned operational facts.
- `Skill` is described as procedural workflows / recipes / tool instructions.
- The block does **not** contain the old phrase implying `user preferences` are part of `Memory`.

Example expected assertions:

```python
def test_skill_memory_classification_uses_official_user_memory_boundary():
    from hermes_self_improvement.prompts import SKILL_MEMORY_CLASSIFICATION_BLOCK

    text = SKILL_MEMORY_CLASSIFICATION_BLOCK
    assert "USER" in text and "preferences" in text and "communication" in text
    assert "MEMORY" in text and "environment" in text and "project conventions" in text
    assert "Skills" in text and "procedural" in text and "workflows" in text
    assert "Memory is factual" not in text
    assert "user preferences, environment facts" not in text
```

**Step 2: Run the focused test to verify RED**

```bash
python -m pytest tests/test_prompts.py -q
```

Expected before implementation: FAIL on the old prompt text.

**Step 3: Update the classification block**

Replace `SKILL_MEMORY_CLASSIFICATION_BLOCK` with a compact boundary, for example:

```python
SKILL_MEMORY_CLASSIFICATION_BLOCK = """USER is user-profile knowledge: preferences, communication style, expectations, stable personal details, and recurring working habits.

MEMORY is the agent's operational notes: environment facts, project conventions, paths, tool/runtime quirks, and stable lessons learned that should be injected every session.

Skills are procedural how-to knowledge: multi-step workflows, tool-specific instructions, reusable recipes, pitfalls, verification steps, and reference-document-sized guidance loaded on demand.

If it is about the person, prefer USER. If it is about the environment or operating facts, prefer MEMORY. If it is a repeatable procedure, prefer Skill."""
```

Keep it short; do not turn this into a long policy doc.

**Step 4: Verify**

```bash
python -m pytest tests/test_prompts.py -q
```

Expected: PASS.

---

## Task 2: Fix stale memory-agent overlay instructions

**Objective:** Make seed overlay docs match add-before-remove and memory-to-skill behavior.

**Files:**
- Modify: `defaults/prompt-overlays/memory_agent.md`
- Modify if needed: `tests/test_default_prompt_overlay_seeds.py` or `tests/test_prompts.py`

**Step 1: Write failing test**

Add assertions that the default memory agent overlay:

- does not contain `remove` then `add` for USER↔MEMORY moves;
- explicitly says move order is `add destination first`, then `remove source` only after success;
- keeps procedural knowledge routed to `convert_to_skill_proposal` / skill route instead of storing as memory.

Example:

```python
def test_memory_agent_overlay_uses_add_before_remove_for_moves():
    text = Path("defaults/prompt-overlays/memory_agent.md").read_text(encoding="utf-8")
    assert "remove` then `add" not in text
    assert "add" in text and "destination" in text and "remove" in text and "source" in text
```

**Step 2: Run RED**

```bash
python -m pytest tests/test_default_prompt_overlay_seeds.py tests/test_prompts.py -q
```

Expected: FAIL until the overlay text is updated.

**Step 3: Update overlay text**

Change the mutation-shape section from remove-then-add to destination-first wording:

```md
- To move an entry between `memory` and `user`, add the compact entry to the destination first, then remove the source with exact `old_text` only after the destination add succeeds. If the destination add fails, keep the source unchanged.
```

For capacity recovery, make it clear that removing a stale entry to make room is allowed only in the destination store and must not remove the source of a placement move early.

**Step 4: Verify**

```bash
python -m pytest tests/test_default_prompt_overlay_seeds.py tests/test_prompts.py -q
```

Expected: PASS.

---

## Task 3: Stop over-filtering memory placement candidates before memory_agent

**Objective:** Let `memory_agent` review all placement candidates with compact evidence, instead of only code/path/procedural-looking text.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Modify: `tests/test_memory_agent_dispatch.py`
- Possibly modify: `tests/test_memory_inventory_planner.py`

**Current problem:**

`_memory_placement_agent_candidate_from_evidence()` returns `None` unless `_placement_text_needs_memory_agent(text)` sees backticks, commands, paths, env vars, or file extensions. That means plain natural-language entries such as `Ryo prefers concise reports.` can stay in the wrong store without memory_agent judgment.

**Step 1: Write failing test**

Add a dispatch test proving plain placement candidates reach memory_agent. Cover both sides of the official boundary, not just one example:

- plain user preference currently in `memory` should reach memory_agent;
- plain environment/operational fact currently in `user` should reach memory_agent.

```python
def test_memory_placement_plain_user_preference_reaches_memory_agent():
    result = run_memory_improvement_step(
        evidence_pack=_pack([
            _placement_candidate(
                old_text="Ryo prefers concise reports.",
                current_store="memory",
            )
        ]),
        config={"_memory_agent_backend": FakePreviewOrBackend(), "_memory_current_entries": [...]},
        mutate=False,
    )

    block = result["memory_agent"]
    assert block["status"] == "preview"
    assert block["candidate_counts_by_kind"]["memory_placement_candidate"] == 1
    assert block["candidates"][0]["placement_text"] == "Ryo prefers concise reports."
```

Use existing test helpers in `tests/test_memory_agent_dispatch.py` where possible.

**Step 2: Run RED**

```bash
python -m pytest tests/test_memory_agent_dispatch.py -q
```

Expected: FAIL because the plain text placement candidate is omitted.

**Step 3: Simplify implementation**

Remove `_placement_text_needs_memory_agent()` as a hard gate, or keep it only as advisory metadata.

Keep the existing overall memory-agent caps / compacting path in place. Do not increase raw text length or pass raw memory files. If implementation reveals candidate volume growth, add a small per-kind cap/omitted count using the existing preview metadata rather than restoring semantic pre-filtering.

Preferred minimal change:

```python
def _memory_placement_agent_candidate_from_evidence(item: dict[str, Any]) -> dict[str, Any] | None:
    inventory = item.get("inventory") if isinstance(item.get("inventory"), dict) else {}
    text = str(inventory.get("old_text") or inventory.get("summary") or "").strip()
    current_store = str(inventory.get("current_store") or "").strip()
    if not text or current_store not in {"memory", "user"}:
        return None
    return {
        "candidate_id": item.get("id"),
        "candidate_kind": "memory_placement_candidate",
        "current_store": current_store,
        "placement_text": _redact_text(text, max_chars=360),
        "official_boundary": str(inventory.get("official_boundary") or ""),
        "allowed_recommendations": [...],
        "suggested_route": "placement_review",
        "risk": item.get("risk") or "medium",
    }
```

Do not add a new deterministic classifier. Let the existing bounded memory_agent decide.

**Step 4: Verify focused tests**

```bash
python -m pytest tests/test_memory_agent_dispatch.py tests/test_memory_inventory_planner.py -q
```

Expected: PASS.

---

## Task 4: Surface memory_agent mutations in decisions, changed_memories, summaries, and episodes

**Objective:** Ensure memory mutations performed by `memory_agent` are not hidden behind `memory_agent.changed` only.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Modify: `tests/test_memory_agent_dispatch.py`
- Modify if needed: `tests/test_cli_surface.py`, `tests/test_report_improve_connection.py`, `tests/test_episode_ledger.py`

**Step 1: Write failing test for changed_memories**

Use a fake memory-agent backend that returns a successful mutation:

```python
class FakeBackend:
    def run(self, prompt, task, config=None):
        return {
            "success": True,
            "outcome": "applied",
            "used_tools": [{"tool": "memory", "action": "replace", "success": True}],
            "changed_memories": ["mem-placement-1"],
            "removed_memories": [],
            "verification_notes": ["moved preference to USER"],
            "rollback_hints": [],
        }
```

Assert:

- `run_memory_improvement_step(..., mutate=True)["changed"] == 1`
- `changed_memories == ["mem-placement-1"]`
- `decisions` contains an accepted memory_agent decision with `changed: True`
- `memory_agent.result.changed_memories` is still preserved for audit

Add surface-level tests in addition to runner internals:

- CLI summary / result payload includes the memory-agent changed id in top-level `memory_changes`.
- episode recording sees the memory-agent mutation as a memory change, not only an opaque nested block.
- duplicate ids from `changed_memories` and `removed_memories` are de-duplicated or counted intentionally with a test documenting the chosen behavior.

**Step 2: Run RED**

```bash
python -m pytest tests/test_memory_agent_dispatch.py -q
```

Expected: FAIL because currently the changed memory id can be absent from top-level `changed_memories` / decisions.

**Step 3: Implement minimal accounting adapter**

In `run_memory_improvement_step()`, after a completed `memory_agent_block`, append one compact decision per changed/removed memory id.

Suggested helper:

```python
def _memory_agent_result_decisions(memory_agent_result: dict[str, Any]) -> list[dict[str, Any]]:
    decisions = []
    for memory_id in memory_agent_result.get("changed_memories") or []:
        decisions.append({
            "evidence_id": str(memory_id),
            "decision": "accepted",
            "reason": "memory_agent_applied",
            "changed": True,
            "operation": {"operation": "memory_agent", "target": "memory"},
            "result_source": "memory_agent",
        })
    for memory_id in memory_agent_result.get("removed_memories") or []:
        decisions.append({
            "evidence_id": str(memory_id),
            "decision": "accepted",
            "reason": "memory_agent_removed",
            "changed": True,
            "operation": {"operation": "memory_agent_remove", "target": "memory"},
            "result_source": "memory_agent",
        })
    return decisions
```

Keep this compact; do not duplicate full tool traces into every decision.

When `convert_to_skill_proposal` is returned, keep the existing skill-route decision, but avoid double-counting it as a memory mutation unless `changed_memories` / `removed_memories` is non-empty.

**Step 4: Verify summary and episode propagation**

Run:

```bash
python -m pytest tests/test_memory_agent_dispatch.py tests/test_cli_surface.py tests/test_episode_ledger.py -q
```

Expected: PASS, with top-level memory changes reflecting memory_agent changes.

---

## Task 5: Keep memory-to-skill bridge as-is, but reduce naming drift in summaries

**Objective:** Avoid unnecessary bridge refactor now, but make naming and summary behavior less confusing.

**Files:**
- Modify only if tests expose drift: `hermes_self_improvement/runner_steps.py`, `hermes_self_improvement/cli.py`, `hermes_self_improvement/tool_handlers.py`
- Test: `tests/test_memory_to_skill_migration.py`, `tests/test_cli_surface.py`, `tests/test_plugin_tools.py`

**Guidance:**

Do **not** create a new module in this slice unless Task 3/4 changes make `runner_steps.py` materially worse. The bridge is complex but already reviewed and validated. This task is only for small naming/summary cleanup if needed.

Allowed cleanup:

- Ensure `memory_to_skill_preview` counts as `apply` in dry-run summaries.
- Ensure accepted bridge decisions report both skill change and removed memory when both occurred.
- Ensure memory remove failure reports partial skill success clearly.

Disallowed cleanup:

- No new lane, queue, approval mode, broad schema migration, or replay redesign.

**Verification:**

```bash
python -m pytest tests/test_memory_to_skill_migration.py tests/test_cli_surface.py tests/test_plugin_tools.py -q
```

Expected: PASS.

---

## Task 6: Document the intentionally deferred MemoryStore read-path proof

**Objective:** Avoid mixing a low-risk read-path refactor into this fix. Capture it as a follow-up proof with clear entry criteria.

**Files:**
- Create: `.hermes/plans/2026-05-24-built-in-memory-read-path-proof.md`
- Modify: `.hermes/plans/README.md`

**Plan content:**

The follow-up plan should answer:

- Can `MemoryStore` expose structured current entries equivalent to the custom `§` parser without direct file parsing?
- Does it preserve exact multi-line `old_text` for remove/replace?
- Does it respect profiles / `get_hermes_home()` / configured store files?
- Can replay use the official current-entry source while still verifying exact current state?

Entry criteria:

- Tasks 1-4 are implemented and full tests pass.
- The proof is read-only first.
- No mutation behavior changes until equivalence tests pass.

Do not implement the proof in this plan.

---

## Task 7: Update operations docs and plan index

**Objective:** Keep repo-tracked docs aligned with the actual implementation.

**Files:**
- Modify: `skills/operations/SKILL.md`
- Modify: `.hermes/plans/README.md`
- Modify: this plan’s status section after implementation

**Required updates:**

- Mention that placement candidates now go to memory_agent broadly, not only code/path-shaped text.
- Mention memory_agent mutation results are reflected in decisions / changed_memories / summaries.
- Keep the MemoryStore read-path proof as a linked follow-up, not as completed behavior.
- Keep memory-to-skill bridge docs unchanged except for any naming/summary corrections actually implemented.

**Verification:**

```bash
python -m pytest tests/test_bundled_skills.py tests/test_markdown_artifacts.py -q
```

Expected: PASS.

---

## Task 8: Full verification and independent review

**Objective:** Prove the changes are safe, small, and consistent with Hermes built-in memory guidance.

**Commands:**

```bash
python -m py_compile __init__.py hermes_self_improvement/*.py
python -m pytest tests/test_prompts.py tests/test_default_prompt_overlay_seeds.py tests/test_memory_agent_dispatch.py tests/test_memory_inventory_planner.py tests/test_memory_to_skill_migration.py tests/test_cli_surface.py tests/test_plugin_tools.py tests/test_bundled_skills.py tests/test_markdown_artifacts.py -q
python -m pytest -q
git diff --check
hermes self-improvement status
```

Expected:

- focused tests pass;
- full suite passes;
- `git diff --check` has no output;
- `hermes self-improvement status` reports plugin enabled and skill/memory backends available.

**Independent review:**

Use `delegate_task` or Codex review on the final diff with this checklist:

- USER/MEMORY/Skill prompt boundary matches official docs.
- Placement candidates are no longer over-filtered before memory_agent.
- Memory mutation execution remains official-tool-only.
- USER↔MEMORY move still preserves add-before-remove.
- Memory-agent mutations are visible in artifact summary and changed_memories.
- No new broad classifier, lane, approval queue, or direct file mutation fallback was added.
- Docs match exactly what was implemented.

---

## Suggested commit sequence

1. `fix(self-improvement): align memory classification prompts`
   - Tasks 1-2.
2. `fix(self-improvement): route placement reviews through memory agent`
   - Tasks 3-4, plus small Task 5 cleanup if needed.
3. `docs(self-improvement): plan built-in memory read-path proof`
   - Tasks 6-7.

If implementation stays small, these can be squashed into one commit after review, but keep the work reviewable while developing.

## Review notes incorporated

Subagent review found no hard blocker, but requested the following refinements, now reflected above:

- update existing `tests/test_prompt_classification.py` instead of only adding new prompt tests;
- test both plain user-preference and plain environment-fact placement candidates reaching `memory_agent`;
- keep candidate volume bounded via existing compact/cap metadata rather than restoring semantic pre-filtering;
- add top-level surface/episode tests for memory-agent mutation visibility;
- keep Task 5 optional to avoid turning simplification into a broad bridge refactor.

## Done definition

- [x] Shared prompt no longer says user preferences belong in MEMORY.
- [x] Memory-agent overlay no longer instructs remove-before-add placement moves.
- [x] Plain USER/MEMORY placement candidates reach memory_agent preview.
- [x] Successful memory_agent mutations appear in `decisions`, `changed_memories`, summaries, and episodes.
- [x] Memory-to-skill safe ordering remains unchanged and tests still pass.
- [x] Built-in memory read-path refactor is documented as a separate proof, not half-implemented.
- [x] Operations docs and plan index reflect current behavior.
- [x] Focused tests, full tests, `git diff --check`, `hermes self-improvement status`, and independent review pass.

## Final validation

- Focused suite: `131 passed`.
- Full suite: `779 passed, 2 skipped`.
- `git diff --check`: passed.
- `hermes self-improvement status`: plugin enabled; skill and memory backends available. Runtime prompt overlays remain invalid/missing as a pre-existing setup state, not introduced by this slice.
- `hermes self-improvement improve --dry-run --json`: wrote `run-20260524T162647Z`; memory step completed with no actual changes in dry-run.
- Independent Codex blocker review: PASS; no blockers found.
