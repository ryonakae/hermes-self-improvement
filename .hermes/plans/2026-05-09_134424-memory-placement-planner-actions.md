# Memory Placement Planner Actions Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Status:** implemented 2026-05-09. Full test passed (`533 passed, 2 skipped`), `git diff --check` passed, and dry-run verification produced `Would apply: 0 / Deferred: 8 / Skipped: 28 / Blocked: 0` with `Memory placement: kept in current store: memory 20`, `needs memory planner: 7`, diagnostic raw output, and skill-routed workflow lines. No mutating dogfood was run.

**Goal:** Reduce the current `needs memory planner` backlog by turning obvious memory placement reviews into concrete no-op, move, merge, replace, skill-route, or skip decisions while keeping side effects bounded to the existing official memory/skill tool paths.

**Architecture:** Keep the current `improve` flow and user-facing `apply / defer / skip / block` buckets. Do not add a new lane, approval queue, or apply mode. Add a small memory placement planner layer inside the existing memory step: deterministic fast-paths for obvious `keep` and stale-pair cases, LLM planner output normalization for fuzzy placement cases, and compact summary lines that distinguish `kept`, `would move`, `would merge/replace`, `routed to skill`, and `still needs planner`.

**Tech Stack:** Python, pytest, existing `bin/hermes-self-improve` CLI, existing `run_memory_improvement_step()`, official Hermes memory tool path, existing skill planner/knowledge maintenance route for procedural candidates.

---

## Current context

Latest verified dry-run artifact:

```text
/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260509T043931Z.json
```

Action summary:

```text
Would apply: 0
Deferred: 26
Skipped: 9
Blocked: 0
```

The memory placement routing slice worked: raw tool output is diagnostic skip, workflow gaps route to skill maintenance, and unsafe cases are no longer inflated as blocks. The remaining weak spot is that the memory placement review emits too many generic defers:

```text
memory_placement_needs_routing: 25
memory_inventory_needs_planner: 1
```

Most of those 25 placement candidates are existing USER/MEMORY entries such as stable environment facts, stable user preferences, or procedural-ish conventions. Many should simply be marked `keep` / no-op; a few may need `move_user_to_memory`, `move_memory_to_user`, `merge_with_existing`, `replace`, or `convert_to_skill_update`.

The plugin already has a memory inventory planner hook:

```python
_memory_inventory_operations(evidence, config)
_call_memory_inventory_planner_llm(evidence=evidence, config=config)
render_memory_placement_markdown(evidence)
```

But in practice, candidates without operation hints still fall back to `memory_placement_needs_routing`. The next slice should make that planner useful without turning every review item into mutation.

## Non-goals

- Do not create a separate memory review command or approval queue.
- Do not add new user-facing action buckets beyond `apply / defer / skip / block`.
- Do not let report artifacts execute mutation decisions.
- Do not route raw logs or run JSON into memory.
- Do not directly edit `USER.md`, `MEMORY.md`, provider DBs, or skill files.
- Do not make LLM-authored Markdown a machine-control protocol.
- Do not delete memory entries unless exact `old_text`, clear lower value/staleness, and existing safety checks pass.
- Do not force all 26 current defers into mutations. High-quality `keep` / `skip` is a good outcome.

## Desired behavior

### Decision vocabulary inside memory step

Keep final semantic buckets simple, but allow memory placement decisions to carry precise reasons:

```text
keep_current_memory              -> skip, suggested_route=none
keep_current_user                -> skip, suggested_route=none
memory_replace_stale_fact        -> accepted in dry-run / executed in mutate via memory_replace
memory_merge_with_existing       -> accepted in dry-run / executed as one replace + optional remove when exact old_text exists
memory_move_user_to_memory       -> accepted in dry-run / executed add-before-remove
memory_move_memory_to_user       -> accepted in dry-run / executed add-before-remove
memory_convert_to_skill_update   -> skip, suggested_route=skill
memory_skip_noise                -> skip, suggested_route=none
memory_placement_needs_planner   -> defer only when exact operation is still ambiguous
```

### Summary output

The existing `Memory placement:` section should become more useful:

```text
Memory placement:
- kept in current store: memory 12, user 10
- would move: user -> memory 1, memory -> user 1
- would merge/replace: 1
- routed to skill maintenance: patch tool workflow 2, sandbox permission workflow 2, timeout workflow 2, placement review 1
- diagnostic only: raw tool output 2
- still needs memory planner: 2
```

Exact counts will vary. The important part is that obvious `keep` no longer appears as `Deferred`.

### LLM planner contract

When the LLM planner is used, ask it for structured operations only:

```json
{
  "operations": [
    {
      "evidence_id": "memory_place_...",
      "operation": "keep",
      "target": "memory",
      "reason": "stable environment fact already belongs in MEMORY"
    },
    {
      "evidence_id": "memory_place_...",
      "operation": "move_user_to_memory",
      "old_text": "...exact old_text...",
      "content": "...same or improved compact fact...",
      "reason": "environment fact belongs in MEMORY"
    },
    {
      "evidence_id": "memory_place_...",
      "operation": "convert_to_skill_update",
      "skill_route": "hermes-memory-and-live-context",
      "content": "procedural guidance summary",
      "reason": "reusable procedure belongs in skill"
    }
  ]
}
```

Hard rules:

- `keep`, `skip_noise`, and `convert_to_skill_update` are non-mutating in the memory step.
- `move_*`, `replace`, `remove`, and `merge_with_existing` require exact `old_text` from evidence.
- `convert_to_skill_update` does not mutate a skill in the memory step; it records route metadata for the existing skill/knowledge maintenance planner.
- Unknown operations fail closed as rejected/blocked.

---

## Step-by-step implementation plan

### Task 1: Add regression tests for explicit keep/no-op placement decisions

**Objective:** Make obvious placement reviews become explainable skips, not generic defers.

**Files:**
- Modify: `tests/test_memory_inventory_planner.py`
- Modify: `hermes_self_improvement/runner_steps.py`

**Step 1: Write failing test**

Add a memory placement candidate that already belongs in MEMORY:

```python
def _placement_evidence(*, evidence_id="memory-place-keep", current_store="memory", old_text="Hermes runtime root は `~/.hermes`。"):
    return {
        "id": evidence_id,
        "kind": "memory_placement_candidate",
        "inventory": {
            "group_kind": "placement_review",
            "current_store": current_store,
            "old_text": old_text,
            "summary": old_text,
            "allowed_recommendations": [
                "keep",
                "move_user_to_memory",
                "move_memory_to_user",
                "merge_with_existing",
                "convert_to_skill_update",
                "skip_noise",
            ],
        },
    }
```

Then assert planner `keep` becomes a skip/no-op:

```python
def test_memory_placement_keep_decision_is_skip_noop_not_defer():
    config = {"_memory_inventory_planner_fn": lambda evidence, config=None, placement_markdown=None: [{
        "evidence_id": "memory-place-keep",
        "operation": "keep",
        "target": "memory",
        "reason": "stable environment fact already belongs in MEMORY",
    }]}

    result = run_memory_improvement_step(
        evidence_pack=_pack([_placement_evidence()]),
        config=config,
        mutate=False,
    )

    assert result["changed"] == 0
    assert result["decisions"] == [{
        "evidence_id": "memory-place-keep",
        "decision": "skip",
        "reason": "keep_current_memory",
        "suggested_route": "none",
        "changed": False,
        "operation": {"operation": "memory_keep", "target": "memory", "reason": "stable environment fact already belongs in MEMORY"},
    }]
```

**Step 2: Run RED**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_memory_inventory_planner.py::test_memory_placement_keep_decision_is_skip_noop_not_defer -q
```

Expected: FAIL because `keep` is not normalized yet.

**Step 3: Implement minimal normalization**

In `hermes_self_improvement/runner_steps.py`, extend `_normalize_inventory_operation()` to accept:

```text
keep -> memory_keep
skip_noise -> memory_skip
convert_to_skill_update -> memory_convert_to_skill_update
```

For `memory_keep`:

- target must be `memory` or `user` when supplied;
- no `old_text` required;
- no mutation context is built;
- dry-run and mutate both emit `skip` / no-op.

**Step 4: Run GREEN**

```bash
$PY -m pytest tests/test_memory_inventory_planner.py -q
```

Expected: pass.

---

### Task 2: Add non-mutating skill-route and skip-noise placement operations

**Objective:** Let the memory planner say “not memory; route to skill” or “skip noise” without creating block/defer noise.

**Files:**
- Modify: `tests/test_memory_inventory_planner.py`
- Modify: `hermes_self_improvement/runner_steps.py`

**Step 1: Write failing tests**

```python
def test_memory_placement_convert_to_skill_update_is_skill_routed_skip():
    config = {"_memory_inventory_planner_fn": lambda evidence, config=None, placement_markdown=None: [{
        "evidence_id": "memory-place-skill",
        "operation": "convert_to_skill_update",
        "target": "skill",
        "skill_route": "hermes-memory-and-live-context",
        "content": "Move procedural live-context placement guidance into a skill.",
        "reason": "procedural guidance belongs in skill",
    }]}

    result = run_memory_improvement_step(evidence_pack=_pack([_placement_evidence(evidence_id="memory-place-skill")]), config=config, mutate=False)

    assert result["decisions"][0]["decision"] == "skip"
    assert result["decisions"][0]["reason"] == "memory_convert_to_skill_update"
    assert result["decisions"][0]["suggested_route"] == "skill"
    assert result["decisions"][0]["skill_route"] == "hermes-memory-and-live-context"
```

```python
def test_memory_placement_skip_noise_is_skip_noop():
    config = {"_memory_inventory_planner_fn": lambda evidence, config=None, placement_markdown=None: [{
        "evidence_id": "memory-place-noise",
        "operation": "skip_noise",
        "target": "memory",
        "reason": "temporary session detail",
    }]}

    result = run_memory_improvement_step(evidence_pack=_pack([_placement_evidence(evidence_id="memory-place-noise")]), config=config, mutate=False)

    assert result["decisions"][0]["decision"] == "skip"
    assert result["decisions"][0]["reason"] == "memory_skip_noise"
    assert result["decisions"][0]["suggested_route"] == "none"
```

**Step 2: Run RED**

```bash
$PY -m pytest tests/test_memory_inventory_planner.py::test_memory_placement_convert_to_skill_update_is_skill_routed_skip tests/test_memory_inventory_planner.py::test_memory_placement_skip_noise_is_skip_noop -q
```

Expected: FAIL until non-mutating operation handling exists.

**Step 3: Implement non-mutating operation branch**

In `run_memory_improvement_step()`, before `build_memory_mutation_context()`, branch on normalized operations:

```text
memory_keep
memory_skip
memory_convert_to_skill_update
```

Emit compact decisions; never call memory tool for these operations.

**Step 4: Run GREEN**

```bash
$PY -m pytest tests/test_memory_inventory_planner.py -q
```

---

### Task 3: Make stale-pair inventory produce one concrete replace/remove preview

**Objective:** Turn the current single `memory_inventory_needs_planner` stale pair into an actionable dry-run operation when planner output is available.

**Files:**
- Modify: `tests/test_memory_inventory_planner.py`
- Modify: `hermes_self_improvement/runner_steps.py` only if normalization gaps appear

**Step 1: Add a stale-pair planner test**

The current `_inventory_evidence()` already models a stale/current pair. Add a planner response that replaces the stale entry with the better compact current text and removes the duplicate only when exact `old_text` is present.

```python
def test_memory_inventory_stale_pair_replace_preview_is_actionable():
    config = {"_memory_inventory_planner_fn": lambda evidence, config=None, placement_markdown=None: [{
        "evidence_id": "mem-inv-1",
        "operation": "replace",
        "target": "memory",
        "old_text": "Hermes root is /opt/data",
        "content": "Hermes runtime root は `~/.hermes`。旧 Docker-style root は current runtime ではない。",
        "reason": "replace stale runtime root fact",
    }]}

    result = run_memory_improvement_step(evidence_pack=_pack([_inventory_evidence()]), config=config, mutate=False)

    assert result["decisions"][0]["decision"] == "accepted"
    assert result["decisions"][0]["reason"] == "dry_run_would_execute_memory_tool"
    assert result["decisions"][0]["operation"]["operation"] == "memory_replace"
```

This mostly documents current expected behavior; if it already passes, keep it as regression coverage.

**Step 2: Ensure exact-old-text guards stay intact**

Run:

```bash
$PY -m pytest tests/test_memory_inventory_planner.py::test_memory_inventory_rejects_remove_without_old_text tests/test_memory_inventory_planner.py::test_memory_inventory_rejects_secret_old_text -q
```

Expected: pass. Do not weaken these guards.

---

### Task 4: Strengthen the LLM memory planner prompt and output normalization

**Objective:** Make real dry-runs less dependent on injected test planners by telling the LLM to output `keep` for obvious correct placement and only emit mutations when exact fields are present.

**Files:**
- Modify: `tests/test_memory_inventory_planner.py`
- Modify: `hermes_self_improvement/runner_steps.py`
- Modify: `hermes_self_improvement/markdown_artifacts.py`

**Step 1: Test prompt includes operation schema and keep-first guidance**

Extend `test_memory_inventory_planner_receives_markdown_placement_context()` or add a new test against `_call_memory_inventory_planner_llm` via monkeypatch if convenient. At minimum assert `placement_markdown` contains:

```text
## Output operations
- keep
- move_user_to_memory
- move_memory_to_user
- merge_with_existing
- replace
- remove
- convert_to_skill_update
- skip_noise
```

and:

```text
If the current store is already correct, output keep instead of a mutation.
```

**Step 2: Update `render_memory_placement_markdown()`**

Add a compact schema section. Keep it human-readable Markdown; do not parse it later.

**Step 3: Update `_call_memory_inventory_planner_llm()` system prompt**

Replace the vague “Convert fuzzy memory inventory and placement evidence into concrete memory tool operations” with a sharper contract:

```text
Return JSON only: {"operations": [...]}.
Allowed operation values: keep, add, replace, remove, move_user_to_memory, move_memory_to_user, merge_with_existing, convert_to_skill_update, skip_noise.
Use keep for entries already in the right store.
Use convert_to_skill_update for procedural reusable guidance; do not invent a skill mutation here.
Use move/replace/remove only with exact old_text copied from evidence.
Omit only cases that genuinely need more context.
```

**Step 4: Run targeted tests**

```bash
$PY -m pytest tests/test_memory_inventory_planner.py tests/test_markdown_artifacts.py -q
```

---

### Task 5: Update memory placement summary for keep/move/merge/skill-route details

**Objective:** Make dry-run output show progress: many review candidates were intentionally kept, not deferred.

**Files:**
- Modify: `tests/test_cli_surface.py`
- Modify: `hermes_self_improvement/cli.py`
- Possibly modify: `hermes_self_improvement/tool_handlers.py` if agent-facing compact summaries should expose the same object

**Step 1: Extend CLI summary test**

In `tests/test_cli_surface.py`, add decisions:

```python
{"decision": "skip", "reason": "keep_current_memory", "target": "memory"}
{"decision": "skip", "reason": "keep_current_user", "target": "user"}
{"decision": "accepted", "reason": "dry_run_would_execute_memory_tool", "operation": {"operation": "memory_move", "source": "user", "target": "memory"}}
{"decision": "accepted", "reason": "dry_run_would_execute_memory_tool", "operation": {"operation": "memory_replace", "target": "memory"}}
{"decision": "skip", "reason": "memory_convert_to_skill_update", "suggested_route": "skill", "skill_route": "hermes-memory-and-live-context"}
```

Expected output includes:

```text
Memory placement:
- kept in current store: memory 1, user 1
- would move: user -> memory 1
- would merge/replace: 1
- routed to skill maintenance: hermes-memory-and-live-context 1
```

**Step 2: Update `_memory_placement_summary_lines()`**

Count:

- `keep_current_memory` / `keep_current_user`
- `memory_move` operations by source/target
- `memory_replace` / `memory_remove` / merge-like operations
- `memory_convert_to_skill_update` by `skill_route` or fallback `placement review`
- remaining `memory_inventory_needs_planner` / `memory_placement_needs_routing`

Keep lines compact and omit zero counts.

**Step 3: Run GREEN**

```bash
$PY -m pytest tests/test_cli_surface.py -q
```

---

### Task 6: Dogfood dry-run and inspect whether `Deferred` actually drops

**Objective:** Verify the change on real recent evidence without mutating memory or skills.

**Commands:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
git diff --check
bin/hermes-self-improve improve --dry-run
```

Expected shape:

```text
Would apply: 0 or small N
Deferred: materially below 26
Skipped: higher, with many keep/no-op entries
Blocked: 0 unless a genuine hard invariant appears
Memory placement:
- kept in current store: ...
- still needs memory planner: fewer than before
```

If `Deferred` remains around 26, inspect the artifact before changing code. Likely causes:

- `_call_memory_inventory_planner_llm()` is not being invoked in the real config path;
- the LLM response is malformed and silently returns `[]`;
- normalization rejects `keep` / `convert_to_skill_update` / `merge_with_existing`;
- candidate IDs in planner output do not match evidence IDs.

Do not paper over this with a heuristic that auto-keeps everything. Stable keep is fine only when the planner or a narrow deterministic fast-path can justify it.

---

### Task 7: Commit and push one coherent milestone

**Objective:** Keep repo state clean and reviewable.

**Commands:**

```bash
git status --short
git diff --check
git add \
  hermes_self_improvement/runner_steps.py \
  hermes_self_improvement/markdown_artifacts.py \
  hermes_self_improvement/cli.py \
  hermes_self_improvement/tool_handlers.py \
  tests/test_memory_inventory_planner.py \
  tests/test_markdown_artifacts.py \
  tests/test_cli_surface.py \
  .hermes/plans/README.md \
  .hermes/plans/2026-05-09_134424-memory-placement-planner-actions.md
git commit -m "fix: make memory placement planner actionable"
git push
```

Only stage files actually changed.

---

## Files likely to change

Core:

- `hermes_self_improvement/runner_steps.py`
  - normalize `keep`, `skip_noise`, `convert_to_skill_update`, and possibly `merge_with_existing`
  - emit non-mutating decisions without memory tool execution
  - preserve exact-old-text guards for mutating operations
- `hermes_self_improvement/markdown_artifacts.py`
  - add output operation schema / keep-first guidance to memory placement Markdown
- `hermes_self_improvement/cli.py`
  - extend `Memory placement:` summary with kept/move/merge/skill-route counts
- `hermes_self_improvement/tool_handlers.py`
  - optional compact summary parity for agent-facing tool output

Tests:

- `tests/test_memory_inventory_planner.py`
- `tests/test_markdown_artifacts.py`
- `tests/test_cli_surface.py`

Docs/plans:

- `.hermes/plans/README.md`
- `.hermes/plans/2026-05-09_134424-memory-placement-planner-actions.md`

## Risks and mitigations

### Risk: Auto-keeping entries that actually belong elsewhere

Mitigation:

- Do not add a broad deterministic “all current entries are keep” rule.
- Prefer LLM planner `keep` output or narrow obvious cases.
- Keep fuzzy cases as `memory_placement_needs_routing` if no planner decision exists.

### Risk: LLM emits unsafe delete/remove

Mitigation:

- Existing `_normalize_inventory_operation()` exact `old_text` and sensitive-text guards remain mandatory.
- Delete/remove still uses official memory tool path only.
- Unknown or malformed operation remains rejected/block-like, not coerced.

### Risk: Skill-route operation looks like a skill mutation

Mitigation:

- `convert_to_skill_update` in memory step is non-mutating.
- It only emits `suggested_route=skill` metadata.
- Existing skill planner/knowledge maintenance owns actual skill patch/create/merge decisions.

### Risk: Summary grows noisy

Mitigation:

- Show counts and top 3 skill routes/move routes only.
- Full details remain in run artifacts.

## Success criteria

- Targeted tests pass.
- Full suite passes.
- `git diff --check` passes.
- Dry-run still has `Blocked: 0` unless a real hard invariant appears.
- `memory_placement_needs_routing` count drops materially from 25, ideally because obvious entries become `keep_current_memory` / `keep_current_user` no-op decisions.
- The summary makes the result legible without opening artifacts:

```text
Memory placement:
- kept in current store: ...
- still needs memory planner: ...
```

This is the right next step because it turns the current visibility work into action-quality placement judgment without over-mutating memory or inventing another workflow surface.
