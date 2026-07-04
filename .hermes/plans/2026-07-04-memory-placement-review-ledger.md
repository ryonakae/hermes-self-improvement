# Memory Placement Review Ledger Implementation Plan

> **Status:** implemented and dogfooded on 2026-07-04. Final source-directed dry-run artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260704T234643Z.json` with `placement_review.status=completed`, `reviewed_count=16`, `valid_cached_count=9`, `actionable_to_planner_count=5`, `memory_changes=0`, `skill_changes=0`. Report smoke shows the compact `Memory placement review` counts line.
>
> **For Hermes:** This plan is complete. Use it as historical design context, not as an active task list.

**Goal:** Stop USER.md / MEMORY.md placement churn by adding a simple LLM-owned placement review ledger before the existing Planner sees memory placement candidates.

**Architecture:** Keep the existing evidence → Planner → canonical `knowledge_transactions` → Knowledge Editor path. Add one tool-free `memory_extractor` placement review step that classifies current USER/MEMORY entries, caches stable judgments by `normalized_text_hash + store`, and only forwards actionable medium/high-confidence items to the Planner. Add a short recent-run reversal guard keyed by `normalized_text_hash` so repeated USER↔MEMORY moves fail closed without lineage management.

**Tech Stack:** Python, pytest, Hermes plugin runtime, existing `memory_extractor` role/model routing, JSON run artifacts under `${HERMES_HOME:-~/.hermes}/self-improvement/`.

---

## Background

Recent scheduled runs showed high `memory_changes` counts that were mostly placement churn, not useful improvement. The root cause is not a single bad output: `collect_memory_placement_candidates()` currently emits all USER/MEMORY entries every run, `_render_memory_placement_candidates_section()` gives strong move/split templates per candidate, and there is no program-visible memory of prior placement judgments or recent reverse moves.

Ryo's selected design is intentionally simple:

- Do not define suspiciousness with more heuristics.
- Let the LLM review each current memory item and record its judgment.
- Validate only JSON shape and enum values, not judgment/reason-code combinations.
- Cache stable judgments by `normalized_text_hash + store`.
- Use recent mutation history, not lineage IDs, to stop back-and-forth moves.
- Keep implementation inside the current `improve` flow; do not add a new actor, approval mode, lane, queue, or config surface.

## Selected contract

### Placement review input

- Reads current built-in USER/MEMORY entries from the existing memory inventory/current-entry path.
- Reviews entries only when:
  - no ledger row exists for `normalized_text_hash + store`, or
  - previous judgment was `unclear` exactly once, or
  - text/store changed, which naturally creates a different ledger key.
- Does not re-review `valid_current_store/high` with the same text/store.
- Does not re-review `deferred_stable` or `planner_deferred_stable` with the same text/store.
- Overlay/prompt changes alone do not invalidate ledger rows.

### Placement review output

Strict JSON with a top-level `reviews` list. Each item:

```json
{
  "entry_key": "<normalized_text_hash>:<store>",
  "current_store": "user",
  "judgment": "valid_current_store",
  "canonical_store": "user",
  "confidence": "high",
  "reason_code": "user_preference_or_profile",
  "reason": "This records how the user wants Hermes to communicate."
}
```

Allowed enums:

- `current_store` / `canonical_store`: `user`, `memory`, `skill`, `none`, `unresolved`
- `judgment`: `valid_current_store`, `wrong_store`, `mixed_entry`, `procedural_belongs_in_skill`, `duplicate_or_overlap`, `unclear`
- `confidence`: `low`, `medium`, `high`
- `reason_code`: `user_preference_or_profile`, `agent_runtime_or_environment`, `project_or_tool_convention`, `procedural_belongs_in_skill`, `mixed_user_and_runtime`, `duplicate_or_overlap`, `unclear_boundary`, `recent_history_conflict`, `other`

Validation checks only:

- JSON object/list can be parsed.
- Required keys exist.
- `entry_key` exists in this review input.
- Enum values are known.
- `reason` is non-empty.

Do **not** validate combinations such as `judgment=valid_current_store` with `reason_code=unclear_boundary`. That is quality evidence, not a schema error.

### Planner handoff

Only pass entries that are all of:

- `judgment` in `wrong_store`, `mixed_entry`, `procedural_belongs_in_skill`, `duplicate_or_overlap`
- `confidence` in `medium`, `high`
- not blocked by recent reversal guard
- not `planner_deferred_stable`

Planner handoff includes:

- `entry_key`
- `old_text`
- `current_store`
- `judgment`
- `canonical_store`
- `confidence`
- `reason_code`
- `reason`
- `allowed_operations`

Do not pass concrete move/split JSON templates from placement review. Use allowed operations only:

- `wrong_store` → `placement_move`
- `mixed_entry` → `placement_split`
- `procedural_belongs_in_skill` → `memory_to_skill`
- `duplicate_or_overlap` → `duplicate_cleanup`, optionally `memory_rewrite` if the existing canonical transaction contract supports it

The Planner may use `old_text` to build exact operations, but its role is transactionization. It should not reclassify placement. If it cannot safely produce exact text/target skill/current-source operation, it defers for execution reasons only.

Allowed Planner defer reasons for this path:

- `exact_split_text_unclear`
- `target_skill_unclear`
- `old_text_mismatch`
- `capacity_or_store_state_unclear`
- `review_judgment_conflict_needs_recheck`

### Stable defer rules

- `unclear` reviews:
  - first `unclear`: save ledger and review once more on the next run
  - second consecutive `unclear` for same text/store: mark `deferred_stable`
  - `deferred_stable` is not sent to review or Planner until text/store changes
- Planner defer on actionable review:
  - first same-reason defer: keep actionable and try once more next run
  - second consecutive same-reason defer: mark `planner_deferred_stable`
  - `planner_deferred_stable` is not sent to Planner until text/store changes

### Reporting

Operator-facing report/summary should not show stable deferred entry bodies. It should show counts only:

- `placement_review_valid_cached`
- `placement_review_deferred_stable`
- `placement_review_planner_deferred_stable`
- `placement_review_actionable_to_planner`
- `placement_review_reversal_blocked`

This prevents `memory changes: N`-style churn from looking like useful work.

---

## Non-goals

- No lineage IDs.
- No same-text cross-store relation graph.
- No new config keys unless a test proves one is needed.
- No approval queue or new apply mode.
- No deterministic canonical store heuristic beyond hard safety validation and reversal guard.
- No direct edits to built-in memory files or provider DBs.
- No migration of old run artifacts.

---

## Files to inspect first

- `hermes_self_improvement/evidence.py`
  - `collect_memory_placement_candidates(...)`
  - `_memory_place_id_for_entry(...)`
  - `_memory_placement_observations(...)`
  - `build_evidence_pack(...)`
- `hermes_self_improvement/runner_steps.py`
  - `_memory_placement_agent_candidate_from_evidence(...)`
  - `_knowledge_memory_candidate_from_evidence(...)`
  - `build_knowledge_planner_digest(...)`
  - `run_knowledge_improvement_step(...)`
  - `build_knowledge_routing_summary(...)`
- `hermes_self_improvement/prompts.py`
  - `_render_memory_placement_candidates_section(...)`
- `hermes_self_improvement/planner_runtime.py`
  - planner role call and JSON parsing contract
- `hermes_self_improvement/llm_utils.py`
  - JSON extraction / repair helpers already available
- `hermes_self_improvement/setup_runtime.py`
  - runtime layout for adding `state/memory-placement-ledger.json`
- `hermes_self_improvement/cli.py` and reporting helpers
  - summary/report rendering and run artifact payload
- Tests:
  - `tests/test_evidence_inventory_candidates.py`
  - `tests/test_memory_agent_dispatch.py`
  - `tests/test_knowledge_transaction_view.py`
  - add new focused tests under `tests/test_memory_placement_review_ledger.py`

---

## Implementation tasks

### Task 1: Add normalized text key and ledger load/save helpers

**Objective:** Provide a tiny state helper for placement review cache keyed by `normalized_text_hash + store`.

**Files:**
- Create: `hermes_self_improvement/memory_placement_ledger.py`
- Test: `tests/test_memory_placement_review_ledger.py`

**Step 1: Write failing tests**

Add tests for:

- `normalize_memory_text_for_placement()` collapses whitespace and trims text.
- `placement_entry_key(text, store)` is stable for equivalent whitespace and distinct across stores.
- `load_placement_ledger(config)` returns empty on missing file.
- `save_placement_ledger(config, ledger)` writes sorted, pretty JSON to `${_self_improvement_root}/state/memory-placement-ledger.json` when `_self_improvement_root` is set in tests.

**Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/test_memory_placement_review_ledger.py -q
```

Expected: fails because module/functions do not exist.

**Step 3: Implement minimal helper**

Suggested API:

```python
def normalize_memory_text_for_placement(text: str) -> str: ...
def placement_text_hash(text: str) -> str: ...
def placement_entry_key(text: str, store: str) -> str: ...
def placement_ledger_path(config: dict[str, Any] | None = None) -> Path: ...
def load_placement_ledger(config: dict[str, Any] | None = None) -> dict[str, Any]: ...
def save_placement_ledger(config: dict[str, Any] | None, ledger: dict[str, Any]) -> Path: ...
```

Use existing `get_hermes_home()` or runtime root conventions; do not add a public config key.

**Step 4: Run GREEN**

```bash
.venv/bin/python -m pytest tests/test_memory_placement_review_ledger.py -q
```

Expected: pass.

---

### Task 2: Build placement review input from current entries and ledger

**Objective:** Decide which entries need LLM review without emitting all stable entries every run.

**Files:**
- Modify: `hermes_self_improvement/memory_placement_ledger.py`
- Test: `tests/test_memory_placement_review_ledger.py`

**Step 1: Write failing tests**

Cover:

- no ledger row → item is included for review
- ledger row `judgment=valid_current_store`, `confidence=high` → excluded
- ledger row `status=deferred_stable` → excluded
- ledger row `status=planner_deferred_stable` → excluded from Planner handoff and review
- ledger row `judgment=unclear`, `unclear_count=1` → included for one more review
- store changed → different key, included

**Step 2: Implement helper**

Suggested API:

```python
def build_placement_review_input(current_entries: list[dict[str, Any]], ledger: dict[str, Any]) -> dict[str, Any]: ...
```

Each review input item should include `entry_key`, `text_hash`, `current_store`, `old_text`, `entry_preview`, and existing neutral `placement_observations` if easy to reuse.

**Step 3: Run focused tests**

```bash
.venv/bin/python -m pytest tests/test_memory_placement_review_ledger.py -q
```

---

### Task 3: Add tool-free LLM placement review call with one repair retry

**Objective:** Use the existing `memory_extractor`-style model routing to classify review input and fail closed on invalid JSON.

**Files:**
- Modify: `hermes_self_improvement/memory_placement_ledger.py`
- Possibly modify: `hermes_self_improvement/planner_memory.py` or a small new module if current role-call helpers already live there
- Test: `tests/test_memory_placement_review_ledger.py`

**Step 1: Write failing tests with fake backend/callable**

Cover:

- valid JSON updates ledger rows.
- enum outside allowed set causes one repair call.
- repair success updates ledger.
- repair failure returns `status=failed`, `mutation_candidates=[]`, and does not throw.
- validation does not reject weird but enum-valid combinations.

**Step 2: Implement review runner**

Suggested API:

```python
def run_memory_placement_review(review_input: dict[str, Any], *, config: dict[str, Any] | None = None) -> dict[str, Any]: ...
```

Return compact payload:

```python
{
  "status": "completed" | "no_input" | "failed",
  "reviewed_count": 0,
  "invalid_reason": None,
  "ledger_updates": {...},
  "prompt_source": {... optional ...},
}
```

Use the existing JSON extraction helper. One repair retry is enough.

**Step 3: Run focused tests**

```bash
.venv/bin/python -m pytest tests/test_memory_placement_review_ledger.py -q
```

---

### Task 4: Convert review rows into Planner memory placement candidates

**Objective:** Replace all-entry placement dispatch with actionable review output.

**Files:**
- Modify: `hermes_self_improvement/memory_placement_ledger.py`
- Modify: `hermes_self_improvement/runner_steps.py`
- Tests:
  - `tests/test_memory_placement_review_ledger.py`
  - `tests/test_memory_agent_dispatch.py`

**Step 1: Write failing tests**

Cover:

- `valid_current_store/high` is not passed to Planner.
- `unclear/medium` is not passed to Planner.
- `wrong_store/medium` passes with `allowed_operations=["placement_move"]` and includes `old_text`.
- `mixed_entry/high` passes with `allowed_operations=["placement_split"]`.
- `procedural_belongs_in_skill/high` passes with `allowed_operations=["memory_to_skill"]`.
- `confidence=low` does not pass even when actionable.

**Step 2: Implement converter**

Suggested API:

```python
def actionable_placement_candidates_from_ledger(current_entries: list[dict[str, Any]], ledger: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]: ...
```

Then feed these items into `build_knowledge_planner_digest(...)` as `memory_placement_candidates` instead of raw all-entry `memory_placement_candidate` evidence.

Keep legacy `collect_memory_placement_candidates(...)` available if tests or markdown artifacts use it, but current `run_improve` path should use the review-gated list.

**Step 3: Run related tests**

```bash
.venv/bin/python -m pytest tests/test_memory_placement_review_ledger.py tests/test_memory_agent_dispatch.py -q
```

---

### Task 5: Remove move/split templates from the Planner placement section

**Objective:** Stop prompt-level template pressure from recreating churn.

**Files:**
- Modify: `hermes_self_improvement/prompts.py`
- Test: add or update prompt rendering tests, likely in existing planner prompt tests

**Step 1: Write failing test**

Assert rendered placement section:

- contains `allowed_operations`
- contains `judgment`, `canonical_store`, `confidence`, `reason_code`, and bounded `old_text`
- does not contain `move template:`
- does not contain `split template`
- does not contain `memory_to_skill template`
- tells Planner to transactionize review results and defer if exact operation is unsafe

**Step 2: Implement prompt update**

Change `_render_memory_placement_candidates_section(...)` so it renders reviewed actionable rows, not raw heuristic candidates with templates.

**Step 3: Run focused tests**

```bash
.venv/bin/python -m pytest tests -q -k 'placement and prompt'
```

If `-k` selects too little or too much, run the specific prompt test file plus `tests/test_memory_agent_dispatch.py`.

---

### Task 6: Add Planner defer feedback into ledger

**Objective:** Track repeated Planner execution defers and stabilize after the second same-reason defer.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Modify: `hermes_self_improvement/memory_placement_ledger.py`
- Test: `tests/test_memory_placement_review_ledger.py` or a focused runner-step test

**Step 1: Write failing tests**

Use fake transactions/results:

- first defer for actionable entry increments `planner_defer_count=1` and keeps status actionable
- second defer with same reason sets `status=planner_deferred_stable`
- different defer reason resets or records the new reason with count 1
- apply/preview success clears planner defer count for that key

**Step 2: Implement updater**

Suggested API:

```python
def update_ledger_from_planner_results(ledger: dict[str, Any], transactions: list[dict[str, Any]], results: list[dict[str, Any]]) -> dict[str, Any]: ...
```

Planner transactions need to preserve `entry_key` from the reviewed candidate. If the normalizer drops unknown fields, explicitly preserve `entry_key` for placement transactions in `knowledge_transactions.py`.

**Step 3: Run related tests**

```bash
.venv/bin/python -m pytest tests/test_memory_placement_review_ledger.py tests/test_knowledge_transaction_view.py -q
```

---

### Task 7: Add recent reversal guard keyed by text hash

**Objective:** Block USER→MEMORY→USER or MEMORY→USER→MEMORY churn without lineage IDs.

**Files:**
- Modify: `hermes_self_improvement/memory_placement_ledger.py`
- Modify: `hermes_self_improvement/runner_steps.py`
- Possibly modify report/run artifact helpers that load recent runs
- Test: `tests/test_memory_placement_review_ledger.py`

**Step 1: Write failing tests**

Construct recent mutation history records or run artifacts showing:

- one move `user -> memory` does not block the next same-direction operation
- reverse move within the recent window blocks new placement mutation for same `text_hash`
- unrelated text hash does not block
- blocked entry is counted as `placement_review_reversal_blocked`
- blocked entry is not sent to Planner as actionable

**Step 2: Implement helper**

Suggested API:

```python
def recent_reversal_text_hashes(config: dict[str, Any] | None = None, *, max_runs: int = 8) -> set[str]: ...
def apply_recent_reversal_guard(candidates: list[dict[str, Any]], reversal_hashes: set[str]) -> tuple[list[dict[str, Any]], int]: ...
```

Use a small fixed window in code (`8` recent runs is enough). Do not add a config knob. Read only compact `runs/*.json` artifacts and inspect canonical `knowledge_transactions` / `transaction_results` for successful or previewed placement moves where source/target stores are clear.

**Step 3: Run focused tests**

```bash
.venv/bin/python -m pytest tests/test_memory_placement_review_ledger.py -q
```

---

### Task 8: Persist review metadata into run artifact and summaries

**Objective:** Make review behavior inspectable without exposing stable memory text.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Modify: `hermes_self_improvement/cli.py` or summary renderer modules
- Tests: existing summary/report tests plus new focused assertions

**Step 1: Write failing tests**

Assert run result contains compact metadata such as:

```python
"placement_review": {
    "status": "completed",
    "reviewed_count": 2,
    "valid_cached_count": 10,
    "actionable_to_planner_count": 1,
    "deferred_stable_count": 1,
    "planner_deferred_stable_count": 0,
    "reversal_blocked_count": 0
}
```

Assert human summary/report shows counts only and does not include stable deferred entry bodies.

**Step 2: Implement summary propagation**

Add `placement_review` to `run_knowledge_improvement_step(...)` output and final `run_improve` artifact. Reuse existing summary rendering style; do not create a new report section if a compact `Memory placement` line is enough.

**Step 3: Run related tests**

```bash
.venv/bin/python -m pytest tests -q -k 'placement or summary or report'
```

---

### Task 9: End-to-end dry-run regression

**Objective:** Prove current dry-run no longer sends all stable USER/MEMORY entries to the Planner.

**Files:**
- Test: add an integration-style test near existing `run_improve` / knowledge step tests

**Step 1: Write failing test**

Scenario:

- current entries include one valid/high cached user preference and one wrong-store medium runtime fact
- fake placement review returns only the runtime fact as actionable
- fake planner sees only one placement candidate
- final result has `target_changed=False` in dry-run and `actionable_to_planner_count=1`

**Step 2: Implement wiring fixes until GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_memory_placement_review_ledger.py tests/test_memory_agent_dispatch.py -q
```

---

### Task 10: Real smoke and dogfood checks

**Objective:** Verify the plugin still works in the real Hermes runtime and artifacts show reduced churn.

**Commands:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
hermes self-improvement status
hermes self-improvement improve --dry-run --json
hermes self-improvement report --since-hours 24
走らせた後に直近 run artifact を開き、`placement_review` と `knowledge_transactions` を確認する。

git diff --check
```

Expected:

- full suite passes
- status is healthy
- dry-run writes a run artifact with `placement_review.status` either `completed` or `no_input`
- stable valid entries are not rendered as Planner placement candidates
- no mutating run is executed unless Ryo explicitly asks for it
- no `move template:` / `split template` strings remain in active Planner prompt rendering

---

## Completion criteria

- `memory-placement-ledger.json` is created under runtime `state/` only after a review run needs it.
- Stable `valid_current_store/high` entries stop reappearing in placement review and Planner prompts.
- `unclear` and Planner defer stabilize after two consecutive same-text/store outcomes.
- Actionable medium/high review rows reach Planner with `allowed_operations`, not JSON templates.
- Recent reverse moves are blocked by `text_hash` history before Planner mutation.
- Operator reports show counts for stable/deferred/reversal states without memory bodies.
- Full test suite, `py_compile`, `status`, `improve --dry-run --json`, `report --since-hours 24`, and `git diff --check` pass.

## Risks and guardrails

- **Risk:** accidental reintroduction of heuristic routing.  
  **Guard:** tests should grep/assert no `suggested_route`, `likely_*`, `allowed_recommendations`, or move/split template text appears in active placement handoff/prompt artifacts, except historical plan/archive files.

- **Risk:** ledger hides a bad judgment forever.  
  **Guard:** text/store change reopens review, and `unclear` gets one retry before becoming stable. No extra TTL/config until proven needed.

- **Risk:** review failure suppresses useful placement cleanup.  
  **Guard:** fail closed for placement mutation only; the rest of `improve` continues. Record `placement_review.status=failed` and retry normally next run.

- **Risk:** Planner normalizer drops `entry_key`.  
  **Guard:** add a regression before Task 6; preserve `entry_key` or equivalent `placement_entry_key` through normalized transactions/results.

## Suggested commit sequence

1. `test: cover memory placement ledger keys`
2. `feat: add memory placement review ledger`
3. `feat: gate placement candidates through review ledger`
4. `fix: remove placement templates from planner prompt`
5. `feat: stabilize placement defers and reversal guard`
6. `docs: update memory placement ledger plan status`

Do not commit or push until each slice is verified. No mutating `hermes self-improvement improve` run is part of this plan unless Ryo explicitly approves it.
