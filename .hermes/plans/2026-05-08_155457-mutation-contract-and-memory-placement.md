# Mutation Contract and Memory Placement Plan

> **For Hermes:** Keep this implementation deliberately small. Do not add a new command, lane, queue, approval mode, planner, scoring subsystem, or standalone inventory subsystem. Extend the existing `improve` loop with a few evidence fields, LLM-facing guidance, and stricter execution/result validation.

**Goal:** Make `improve` execute selected skill edits reliably, stop raw tool output from becoming memory, and let the LLM decide whether facts belong in `USER.md`, `MEMORY.md`, or a Skill according to Hermes Agent best practices.

**Grounding:** Hermes memory docs describe two bounded injected stores: `MEMORY.md` for the agent's personal notes such as environment facts, conventions, and things learned; `USER.md` for the user's preferences, communication style, and expectations. Hermes tips summarize the boundary as: memory is for facts/what; skills are for procedures/how, multi-step workflows, tool-specific instructions, and reusable recipes.

**Architecture:** Keep the current pipeline:

```text
evidence pack -> target resolver -> planner -> bounded skill/memory mutation -> artifact summary
```

The program collects compact evidence and hard safety metadata. The LLM decides fuzzy placement and operation intent. Execution remains through official Hermes tools only.

---

## Non-goals

- No direct edits to `MEMORY.md`, `USER.md`, skill files, provider DBs, or Hermes core.
- No separate memory-audit command.
- No new approval queue or apply mode.
- No deterministic classifier that decides USER vs MEMORY vs Skill. Deterministic code may only collect entries, redact, group obvious duplicates, and enforce hard stops.
- No automatic Skill creation for vague advice. New skill creation remains only for durable procedural workflows.

---

## Phase 1: Fix selected mutation execution without loosening safety

### Task 1: Normalize mutation worker outcome aliases

**Problem:** The latest mutating run selected real skill editor tasks, but two worker results returned `outcome: "changed"` and were rejected as `mutation_agent_result_invalid_outcome`.

**Simple fix:** Treat `changed` as an alias for `applied` only when the rest of the result contract is valid.

**Files:**

- Modify: `hermes_self_improvement/mutation_agent.py`
- Tests: `tests/test_mutation_agent.py` or nearby existing mutation-agent tests

**Acceptance:**

- `success=true, outcome="changed", changed_skills=[...]` normalizes to `outcome="applied"`.
- `success=true, outcome="changed"` without `used_tools`, `changed_skills`, `verification_notes`, etc. still fails closed.
- Prompt text says the canonical mutating outcome is `applied`; `changed` is accepted only as legacy/model alias.

### Task 2: Record useful limit diagnostics

**Problem:** `mutation_agent_limits_exceeded` does not explain which tool loop caused the limit.

**Simple fix:** Include compact trace counts and last safe step in the failed result.

**Files:**

- Modify: `hermes_self_improvement/mutation_backend.py`
- Tests: mutation backend tests

**Acceptance:**

- Limit exceeded result includes `tool_call_count`, `tool_call_counts_by_name`, and `last_tool` where available.
- CLI summary can show top rejected reasons without opening the artifact.

---

## Phase 2: Stop raw tool output from becoming memory

### Task 3: Reject raw tool-output memory candidates before execution

**Problem:** The latest mutating run attempted `memory_add` operations where content was raw `terminal` / `search_files` JSON output and target was missing.

**Simple fix:** Add a small quality gate before memory operation execution. This is not a semantic classifier; it only rejects obvious non-memory payloads.

**Files:**

- Modify: `hermes_self_improvement/runner_steps.py` or the helper that extracts memory operations
- Tests: `tests/test_runner_steps.py` / memory operation tests

**Acceptance:**

- Raw JSON blobs, tool result dumps, traceback-like output, and missing-target `memory_add` are rejected as `memory_payload_not_fact` or existing `memory_target_missing`.
- Human-readable compact facts with explicit `target` still pass.
- Rejected raw output remains available as skill/workflow evidence, not memory mutation.

---

## Phase 3: LLM-based USER/MEMORY/Skill placement review

### Task 4: Add compact memory-placement inventory evidence

**Problem:** Some current `USER.md` entries look like environment/plugin facts, and some `MEMORY.md` entries look like user preferences. Some entries may belong in Skills instead.

**Simple fix:** Add a compact `memory_placement_candidate` evidence item to the existing inventory evidence. Do not create a new lane.

**LLM-facing input per entry:**

```json
{
  "entry_id": "...",
  "current_store": "user|memory",
  "content": "redacted compact text",
  "official_boundary": "USER=user preferences/style/expectations; MEMORY=agent notes/environment/conventions/things learned; Skill=procedural how-to/workflows/tool instructions",
  "near_duplicates": [],
  "related_skill_hints": []
}
```

**LLM may recommend:**

```text
keep
move_user_to_memory
move_memory_to_user
merge_with_existing
convert_to_skill_update
convert_to_new_skill
skip_noise
```

Then the existing planner maps this to `apply / defer / skip / block`.

**Files:**

- Modify: `hermes_self_improvement/evidence.py`
- Modify: `hermes_self_improvement/planner.py` prompt/digest fields only as needed
- Tests: memory inventory / planner digest tests

**Acceptance:**

- Existing USER/MEMORY entries are visible to the LLM with current store and official boundary text.
- Program does not decide fuzzy placement; it only supplies evidence.
- Secrets are redacted and never summarized.
- Capacity information is included so the LLM can prefer merge/replace over add when stores are nearly full.

### Task 5: Execute clear move/merge operations through official tools

**Simple execution mapping:**

- `move_user_to_memory`: add to `memory`, then remove from `user` only after add succeeds.
- `move_memory_to_user`: add to `user`, then remove from `memory` only after add succeeds.
- `merge_with_existing`: replace the chosen old entry in its target store.
- `convert_to_skill_update`: planner must select an existing Hermes-created mutable skill; editor applies through `skill_manage`.
- `convert_to_new_skill`: allowed only when the LLM identifies a durable repeatable procedure and no existing Hermes-created skill fits.

**Hard stops:**

- Missing exact `old_text` for remove/replace -> defer.
- Ambiguous target store -> defer.
- Skill target is built-in/hub/plugin-bundled/external/ambiguous provenance -> block or defer, not patch.
- Entry contains credentials/secrets/private payload -> block with redacted artifact only.

**Files:**

- Modify: `hermes_self_improvement/runner_steps.py`
- Modify: `hermes_self_improvement/mutation_policy.py` if current target mapping lacks cross-store move support
- Tests: memory mutation tests

**Acceptance:**

- Cross-store moves use only official `memory` tool actions.
- Remove happens only after successful add/replace.
- Dry-run shows the planned move/merge without mutating.

---

## Phase 4: Make summaries explain execution results

### Task 6: Show planned vs executed results

**Problem:** `Would apply` can be confusing after a mutating run that changes nothing.

**Simple fix:** Extend the existing summary with compact execution result buckets.

Example:

```text
Planned:
- run_editor: 4, memory operations: 0, defer: 1, skip: 27, block: 13
Executed:
- changed: 0, valid no-op: 1, rejected: 3
Rejected reasons:
- mutation_agent_limits_exceeded: 1
- mutation_agent_result_invalid_outcome: 2
```

**Files:**

- Modify: `hermes_self_improvement/cli.py`
- Tests: CLI summary tests

---

## Implementation order

1. Task 1: mutation outcome alias + tests.
2. Task 2: limit diagnostics + tests.
3. Task 3: raw tool-output memory filter + tests.
4. Task 6: planned vs executed summary + tests.
5. Task 4: LLM memory-placement inventory evidence + tests.
6. Task 5: safe cross-store move/merge execution + tests.
7. Full validation:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
hermes self-improvement status
git diff --check
hermes self-improvement improve --dry-run
```

Only after dry-run looks safe, run one mutating dogfood pass.

---

## Success criteria

- A mutating run no longer rejects valid worker responses merely because the model said `changed` instead of `applied`.
- Raw terminal/search output is not proposed as memory content.
- Dry-run can surface entries that appear to belong in the other built-in store or in a Skill.
- LLM performs the fuzzy USER/MEMORY/Skill judgment; deterministic code only provides evidence and hard safety gates.
- Clear cross-store moves are executable via official `memory` tool, with add-before-remove ordering.
- The implementation remains small: existing pipeline, existing planner/editor, existing official tools, existing action semantics.
