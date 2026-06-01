# Memory Placement Direction Validation Implementation Plan

> **For Hermes:** Use test-driven-development and requesting-code-review. Implement task-by-task; do not start a later task until the focused RED/GREEN check for the current task has passed.

**Goal:** Prevent the planner/normalizer from turning “this entry belongs in USER/MEMORY” into an impossible USER↔MEMORY move when the entry is already in that store.

**Architecture:** Keep the existing one Planner → one Knowledge Editor transaction model. Fix the problem at the LLM prompt boundary and the normalizer boundary, not only at executor time. The planner should see only store-valid move options for each memory placement candidate, and normalization must verify every placement decision against the candidate’s `current_store` before it can become an executable `placement_move`.

**Tech Stack:** Python, pytest, Hermes self-improvement run artifacts, existing `knowledge_transactions`, `planner_runtime`, `prompts`, and memory placement evidence.

---

## Triggering incident

Source dry-run artifact:

- `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260601T000243Z.json`

Observed bad normalized transaction:

```json
{
  "transaction_kind": "placement_move",
  "decision": "apply",
  "operation": "move",
  "source_store": "builtin_memory",
  "target_store": "builtin_user",
  "source_id": "memory_place_2217e1ddb538",
  "source_old_text": "日本語docsは日本語中心、英語は必要時のみ。",
  "evidence_ids": []
}
```

But the corresponding evidence candidate was:

```json
{
  "id": "memory_place_2217e1ddb538",
  "kind": "memory_placement_candidate",
  "inventory": {
    "current_store": "user",
    "suggested_route": "likely_keep",
    "route_reasons": ["store_matches_known_boundary_or_low_signal"],
    "old_text": "日本語docsは日本語中心、英語は必要時のみ。"
  }
}
```

Root cause:

1. The LLM treated “this content is USER-shaped” as “move it to USER,” ignoring `current_store=user`.
2. The prompt rendered both move templates for every candidate, including impossible directions.
3. The digest listed both `move_user_to_memory` and `move_memory_to_user` in `allowed_decisions` for every candidate.
4. The normalizer accepted a placement action without consulting the candidate’s `current_store` and produced `source_store=builtin_memory` even though the candidate said the entry was already in user memory.
5. The normalized transaction lost evidence linkage (`evidence_ids=[]`), making the bad transformation harder to diagnose.

This is not solved by executor stale-source blocking alone. Executor blocking is a last-resort guard; planner/normalizer must not create impossible placement moves.

---

## Non-goals

- Do not add a new planner role, approval queue, confidence score, or separate placement lane.
- Do not loosen existing safety gates.
- Do not route to `external_memory` in this slice.
- Do not implement broad memory lifecycle cleanup.
- Do not remove the executor stale-source guard added by the previous hardening slice; keep it as defense-in-depth.

---

## Completion criteria

- A placement candidate with `current_store=user` cannot normalize to `move_memory_to_user`.
- A placement candidate with `current_store=memory` cannot normalize to `move_user_to_memory`.
- Store-valid opposite moves still work:
  - `current_store=user` + `move_user_to_memory` can become `builtin_user -> builtin_memory`.
  - `current_store=memory` + `move_memory_to_user` can become `builtin_memory -> builtin_user`.
- `likely_keep` candidates can be explicitly skipped/kept without producing executable move transactions.
- Placement apply transactions must retain attached evidence id(s), or else block/defer with an explicit reason.
- Artifact diagnostics must expose invalid placement direction counts/details in a bounded form.
- Focused tests and full suite pass.
- A dry-run or replay smoke confirms the known bad artifact no longer yields an executable invalid move.

---

## Pre-implementation review result

Independent review returned **BLOCKED** before implementation. The plan was patched to address these blockers:

1. Planner-runtime validation alone is too narrow if generic transaction normalization can still turn raw placement operations into executable moves without candidate context.
2. The exact incident pattern must be covered at the public planner path, not only helper-level normalization.
3. Prompt and digest must share one store-direction helper, or the two surfaces can drift.
4. Diagnostics should distinguish planner-emitted but normalization-rejected placement decisions.

The implementation tasks below include those corrections.

Second independent review returned **PASS**. Non-blocking suggestions to carry into implementation:

- Keep the invalid-direction block shape consistent with existing non-executable transaction shapes.
- Prefer one public-path regression using an existing `run_planner` monkeypatch harness in addition to `_normalize_planner_payload()` unit coverage.

---

## Task 1: Add shared placement-direction helpers and narrow allowed decisions

**Objective:** Stop telling the LLM that impossible move directions are allowed, using one helper shared by digest and prompt rendering.

**Files:**

- Modify: `hermes_self_improvement/knowledge_transactions.py`
- Modify: `hermes_self_improvement/planner_runtime.py`
- Modify: `hermes_self_improvement/prompts.py`
- Test: `tests/test_skill_planner.py`

**Step 1: Write failing tests**

Add tests near existing memory placement digest tests:

```python
def test_planner_digest_limits_memory_placement_move_decisions_by_current_store():
    digest = build_planner_digest(pack(evidence=[
        {
            "id": "memory-place-user",
            "kind": "memory_placement_candidate",
            "inventory": {
                "current_store": "user",
                "old_text": "日本語docsは日本語中心、英語は必要時のみ。",
                "suggested_route": "likely_keep",
                "route_reasons": ["store_matches_known_boundary_or_low_signal"],
                "summary": "Japanese docs preference.",
            },
        },
        {
            "id": "memory-place-memory",
            "kind": "memory_placement_candidate",
            "inventory": {
                "current_store": "memory",
                "old_text": "Hermes runtime root is ~/.hermes.",
                "suggested_route": "likely_keep",
                "route_reasons": ["store_matches_known_boundary_or_low_signal"],
                "summary": "Runtime root.",
            },
        },
    ]))

    by_id = {row["evidence_id"]: row for row in digest["memory_placement_candidates"]["candidates"]}

    assert "move_user_to_memory" in by_id["memory-place-user"]["allowed_decisions"]
    assert "move_memory_to_user" not in by_id["memory-place-user"]["allowed_decisions"]
    assert "move_memory_to_user" in by_id["memory-place-memory"]["allowed_decisions"]
    assert "move_user_to_memory" not in by_id["memory-place-memory"]["allowed_decisions"]
```

**Step 2: Verify RED**

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_skill_planner.py::test_planner_digest_limits_memory_placement_move_decisions_by_current_store -q
```

Expected: FAIL because both move directions are currently present.

**Step 3: Implement minimal shared helpers**

In `knowledge_transactions.py`, add small pure helpers that are safe to import from both `planner_runtime.py` and `prompts.py`:

```python
def placement_move_operation_for_current_store(current_store: str) -> str | None:
    normalized = {"builtin_user": "user", "builtin_memory": "memory"}.get(current_store, current_store)
    if normalized == "user":
        return "move_user_to_memory"
    if normalized == "memory":
        return "move_memory_to_user"
    return None


def memory_placement_allowed_decisions(current_store: str) -> list[str]:
    decisions = ["keep"]
    if operation := placement_move_operation_for_current_store(current_store):
        decisions.append(operation)
    decisions.extend(["memory_to_skill", "skip", "defer"])
    return decisions
```

Then replace the fixed list at `planner_runtime.py` memory placement candidate construction with `memory_placement_allowed_decisions(current_store)`. `prompts.py` must use the same `placement_move_operation_for_current_store()` helper in Task 2.

**Step 4: Verify GREEN**

Run the focused test and the nearby digest tests:

```bash
$PY -m pytest tests/test_skill_planner.py::test_planner_digest_limits_memory_placement_move_decisions_by_current_store tests/test_skill_planner.py::test_planner_digest_exposes_memory_placement_candidates -q
```

Expected: PASS.

---

## Task 2: Render only store-valid placement move templates

**Objective:** Make the LLM-facing prompt unambiguous: “move to USER” is only valid if the current store is memory, and vice versa.

**Files:**

- Modify: `hermes_self_improvement/prompts.py`
- Test: `tests/test_skill_planner.py`

**Step 1: Write failing tests**

Update or add a prompt rendering test:

```python
def test_render_planner_messages_only_shows_store_valid_memory_placement_move_templates():
    digest = build_planner_digest(pack())
    digest["memory_placement_candidates"] = {
        "candidate_count": 2,
        "omitted_count": 0,
        "candidates": [
            {
                "evidence_id": "memory-place-user",
                "current_store": "user",
                "suggested_route": "likely_keep",
                "route_reasons": ["store_matches_known_boundary_or_low_signal"],
                "old_text": "日本語docsは日本語中心、英語は必要時のみ。",
                "summary": "Japanese docs preference.",
                "allowed_decisions": ["keep", "move_user_to_memory", "memory_to_skill", "skip", "defer"],
            },
            {
                "evidence_id": "memory-place-memory",
                "current_store": "memory",
                "suggested_route": "likely_keep",
                "route_reasons": ["store_matches_known_boundary_or_low_signal"],
                "old_text": "Hermes runtime root is ~/.hermes.",
                "summary": "Runtime root.",
                "allowed_decisions": ["keep", "move_memory_to_user", "memory_to_skill", "skip", "defer"],
            },
        ],
    }

    rendered = render_planner_messages(digest=digest)
    content = rendered["messages"][1]["content"]

    user_block = content.split("evidence_id=memory-place-user", 1)[1].split("evidence_id=memory-place-memory", 1)[0]
    memory_block = content.split("evidence_id=memory-place-memory", 1)[1]

    assert '"operation":"move_user_to_memory"' in user_block
    assert '"operation":"move_memory_to_user"' not in user_block
    assert '"operation":"move_memory_to_user"' in memory_block
    assert '"operation":"move_user_to_memory"' not in memory_block
```

**Step 2: Verify RED**

Run:

```bash
$PY -m pytest tests/test_skill_planner.py::test_render_planner_messages_only_shows_store_valid_memory_placement_move_templates -q
```

Expected: FAIL because `prompts.py` currently renders both move templates for each candidate.

**Step 3: Implement minimal rendering change**

In `prompts.py`, import and use `placement_move_operation_for_current_store()` from `knowledge_transactions.py`. Replace the unconditional `move template` line with store-aware rendering:

- If helper returns `move_user_to_memory`, render only that operation.
- If helper returns `move_memory_to_user`, render only that operation.
- If helper returns `None`, render no move template; keep/defer remain available.

Also add a consistency assertion test: for every rendered candidate block, the rendered move operation must be either absent or present in that row’s `allowed_decisions`.

Adjust the section guidance to say:

```text
Move operations are directions from the current store: use move_user_to_memory only when current_store=user; use move_memory_to_user only when current_store=memory. If the entry already belongs where it is, use the keep/skip template.
```

**Step 4: Verify GREEN**

Run:

```bash
$PY -m pytest tests/test_skill_planner.py::test_render_planner_messages_only_shows_store_valid_memory_placement_move_templates tests/test_skill_planner.py::test_render_planner_messages_includes_memory_placement_transaction_templates -q
```

Expected: PASS after updating older assertions to match the new store-specific template wording.

---

## Task 3: Normalize placement decisions against candidate current_store

**Objective:** Make the normalizer fail closed when the LLM still emits an impossible direction.

**Files:**

- Modify: `hermes_self_improvement/planner_runtime.py`
- Modify only if needed: `hermes_self_improvement/knowledge_transactions.py`
- Test: `tests/test_skill_planner.py`

**Step 1: Write failing tests**

Add tests around `_normalize_planner_payload` / planner runtime normalization:

```python
def test_run_planner_blocks_invalid_memory_placement_direction_for_current_store():
    digest = build_planner_digest(pack())
    digest["memory_placement_candidates"] = {
        "candidate_count": 1,
        "omitted_count": 0,
        "candidates": [{
            "evidence_id": "memory-place-user",
            "current_store": "user",
            "suggested_route": "likely_keep",
            "route_reasons": ["store_matches_known_boundary_or_low_signal"],
            "old_text": "日本語docsは日本語中心、英語は必要時のみ。",
            "summary": "Japanese docs preference.",
            "allowed_decisions": ["keep", "move_user_to_memory", "memory_to_skill", "skip", "defer"],
        }],
    }

    result = _normalize_planner_payload({
        "knowledge_transactions": [{
            "operation": "move_memory_to_user",
            "source_evidence_id": "memory-place-user",
            "source_old_text": "日本語docsは日本語中心、英語は必要時のみ。",
            "reason": "placement_boundary",
        }]
    }, digest)

    tx = result["knowledge_transactions"][0]
    assert tx["decision"] == "block"
    assert tx["reason"] == "invalid_memory_placement_direction_for_current_store"
    assert tx["evidence_ids"] == ["memory-place-user"]
    assert tx["operation"] == "none"
```

Also add the symmetric memory-store case and the exact incident-path regression:

```python
def test_run_planner_blocks_user_to_memory_when_candidate_current_store_is_memory():
    ... current_store="memory" ... operation="move_user_to_memory" ...


def test_run_planner_rejects_incident_pattern_without_executable_placement_move(monkeypatch):
    digest = build_planner_digest(pack())
    digest["memory_placement_candidates"] = {
        "candidate_count": 1,
        "omitted_count": 0,
        "candidates": [{
            "evidence_id": "memory_place_2217e1ddb538",
            "current_store": "user",
            "suggested_route": "likely_keep",
            "route_reasons": ["store_matches_known_boundary_or_low_signal"],
            "old_text": "日本語docsは日本語中心、英語は必要時のみ。",
            "summary": "日本語docsは日本語中心、英語は必要時のみ。",
            "allowed_decisions": ["keep", "move_user_to_memory", "memory_to_skill", "skip", "defer"],
        }],
    }

    result = _normalize_planner_payload({
        "knowledge_transactions": [{
            "operation": "move_memory_to_user",
            "source_evidence_id": "memory_place_2217e1ddb538",
            "source_old_text": "日本語docsは日本語中心、英語は必要時のみ。",
            "reason": "placement_boundary",
        }]
    }, digest)

    assert not [
        tx for tx in result["knowledge_transactions"]
        if tx.get("decision") == "apply" and tx.get("transaction_kind") == "placement_move"
    ]
    assert not [tx for tx in result["knowledge_transactions"] if tx.get("decision") == "apply" and not tx.get("evidence_ids")]
```

If there is an existing public `run_planner` test harness that monkeypatches the LLM response, add the same incident payload there too, so the regression covers `_call_planner_runtime_llm()` → `_normalize_planner_payload()` → `_planner_result()` rather than only the private helper.

**Step 2: Verify RED**

Run:

```bash
$PY -m pytest tests/test_skill_planner.py::test_run_planner_blocks_invalid_memory_placement_direction_for_current_store tests/test_skill_planner.py::test_run_planner_blocks_user_to_memory_when_candidate_current_store_is_memory -q
```

Expected: FAIL because the current normalizer accepts canonical memory operations without candidate validation.

**Step 3: Implement context-aware normalization gate**

In `knowledge_transactions.py`, add a context-aware helper rather than relying on generic `normalize_knowledge_transaction()` for raw LLM placement moves:

```python
def normalize_memory_placement_transaction(
    raw: dict[str, Any],
    *,
    placement_by_evidence_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    ...
```

Contract:

- It extracts one placement evidence id from `source_evidence_id`, `source_id`, `evidence_id`, or `evidence_ids`.
- It requires that id to exist in `placement_by_evidence_id` for `move_user_to_memory` / `move_memory_to_user`.
- It compares raw operation/decision with candidate `current_store`:
  - `move_user_to_memory` requires `current_store == "user"`.
  - `move_memory_to_user` requires `current_store == "memory"`.
- On mismatch it returns a normalized blocked transaction with:
  - `decision="block"`
  - `target_store="none"` and `transaction_kind="none"` if that is the project’s established non-executable shape, otherwise use the existing block shape consistently
  - `operation="none"`
  - `evidence_ids=[evidence_id]`
  - `source_id=evidence_id`
  - `source_old_text` from raw or candidate
  - `reason="invalid_memory_placement_direction_for_current_store"`
- On missing evidence id it returns block reason `memory_placement_move_missing_evidence_id`.
- On unknown evidence id it returns block reason `memory_placement_move_unknown_evidence_id`.
- On valid move it calls `normalize_knowledge_transaction()` with canonical `evidence_ids=[evidence_id]`, `source_id=evidence_id`, exact `source_old_text`, and store-specific source/target implied by the operation.

In `planner_runtime.py`:

1. Build `placement_by_evidence_id` before the raw transaction loop.
2. Route all memory placement product operations through `normalize_memory_placement_transaction()` before the generic `_is_canonical_knowledge_transaction(raw)` path.
3. Add a regression that `_normalize_planner_payload()` no longer calls the generic canonical path for `move_user_to_memory` / `move_memory_to_user` without placement context.

**Important:** `normalize_knowledge_transaction()` may remain a structural canonicalizer for already-trusted internal transactions, but raw planner placement moves must use the context-aware helper. The implementation and tests must make that boundary explicit.

**Step 4: Verify GREEN**

Run:

```bash
$PY -m pytest tests/test_skill_planner.py::test_run_planner_blocks_invalid_memory_placement_direction_for_current_store tests/test_skill_planner.py::test_run_planner_blocks_user_to_memory_when_candidate_current_store_is_memory -q
```

Expected: PASS.

---

## Task 4: Preserve evidence linkage for valid placement moves

**Objective:** Valid placement applies must carry the candidate id into canonical transactions and diagnostics.

**Files:**

- Modify: `hermes_self_improvement/knowledge_transactions.py`
- Modify: `hermes_self_improvement/planner_runtime.py`
- Test: `tests/test_skill_planner.py`

**Step 1: Write failing tests**

```python
def test_run_planner_preserves_evidence_id_for_valid_memory_placement_move():
    digest = build_planner_digest(pack())
    digest["memory_placement_candidates"] = {
        "candidate_count": 1,
        "omitted_count": 0,
        "candidates": [{
            "evidence_id": "memory-place-memory",
            "current_store": "memory",
            "suggested_route": "likely_move_memory_to_user",
            "route_reasons": ["user_preference_language"],
            "old_text": "Ryo prefers concise replies.",
            "summary": "User preference in MEMORY.",
            "allowed_decisions": ["keep", "move_memory_to_user", "memory_to_skill", "skip", "defer"],
        }],
    }

    result = _normalize_planner_payload({
        "knowledge_transactions": [{
            "operation": "move_memory_to_user",
            "source_evidence_id": "memory-place-memory",
            "source_old_text": "Ryo prefers concise replies.",
            "reason": "placement_boundary",
        }]
    }, digest)

    tx = result["knowledge_transactions"][0]
    assert tx["decision"] == "apply"
    assert tx["transaction_kind"] == "placement_move"
    assert tx["source_store"] == "builtin_memory"
    assert tx["target_store"] == "builtin_user"
    assert tx["evidence_ids"] == ["memory-place-memory"]
    assert tx["source_id"] == "memory-place-memory"
```

**Step 2: Verify RED**

Run the test. Expected: FAIL because current normalization can drop `evidence_ids`.

**Step 3: Implement evidence preservation**

The helper from Task 3 should set `evidence_ids` and `source_id` explicitly before calling `normalize_knowledge_transaction()`.

**Step 4: Verify GREEN**

Run:

```bash
$PY -m pytest tests/test_skill_planner.py::test_run_planner_preserves_evidence_id_for_valid_memory_placement_move -q
```

Expected: PASS.

---

## Task 5: Add bounded diagnostics for invalid placement directions

**Objective:** Future artifacts should explain why a raw planner placement decision was blocked/dropped.

**Files:**

- Modify: `hermes_self_improvement/planner_runtime.py`
- Test: `tests/test_skill_planner.py`

**Step 1: Write failing test**

Extend the invalid-direction test to assert diagnostics:

```python
placement = result["knowledge_quality"]["memory_placement_actionability"]
assert placement["invalid_direction_count"] == 1
assert placement["invalid_direction_details"] == [{
    "evidence_id": "memory-place-user",
    "current_store": "user",
    "operation": "move_memory_to_user",
    "reason": "invalid_memory_placement_direction_for_current_store",
    "diagnosis": "planner_emitted_but_normalization_rejected",
}]
```

Use whatever public quality shape `_planner_result()` already returns; if `knowledge_quality.memory_placement_actionability` is assembled separately, add compact fields there rather than a parallel top-level section. Also assert that existing `dropped_raw_decision_count` / `raw_memory_placement_decision_ids` semantics remain understandable: the raw decision should count as seen, but not as an executable apply.

**Step 2: Verify RED**

Expected: FAIL because no such diagnostics exist.

**Step 3: Implement compact diagnostics**

- Track invalid placement direction details while normalizing raw decisions.
- Add at most 20 bounded entries.
- Include only id, current store, operation, reason, and diagnosis; do not include full old_text.
- Add count even when details are truncated.
- Classify invalid-direction details as `planner_emitted_but_normalization_rejected`, not as benign skip or default defer.

**Step 4: Verify GREEN**

Run:

```bash
$PY -m pytest tests/test_skill_planner.py::test_run_planner_blocks_invalid_memory_placement_direction_for_current_store -q
```

Expected: PASS.

---

## Task 6: Artifact smoke against the known bad run

**Objective:** Prove the specific 2026-06-01 failure mode is no longer executable.

**Files:**

- No permanent production file required.
- Optionally add a fixture-based regression if helper extraction makes it small.

**Step 1: Run focused and related tests**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_skill_planner.py tests/test_memory_to_skill_migration.py tests/test_report_improve_connection.py -q
```

Expected: PASS.

**Step 2: Run source-directed smoke**

Use the existing dry-run artifact and the helper path that normalizes planner output if a replay-from-artifact unit path exists. If not, run a fresh dry-run and inspect placement diagnostics:

```bash
$PY -m hermes_self_improvement.cli improve --dry-run --json
```

Then inspect the new artifact:

- No `placement_move` apply with empty `evidence_ids`.
- No `move_memory_to_user` for a candidate whose `current_store=user`.
- Invalid placement direction, if produced by the LLM, is reported as blocked with `invalid_memory_placement_direction_for_current_store`.

Do not run mutating replay as part of this plan unless the dry-run summary is semantically safe and the user explicitly approves replay.

---

## Task 7: Full verification, review, docs, commit

**Objective:** Land the fix only after tests, smoke, docs, and independent review are clean.

**Files:**

- Modify: `.hermes/plans/README.md`
- Modify: `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md` if the roadmap current-position note needs this follow-up linked.

**Step 1: Run full verification**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
git diff --check
```

Expected: PASS.

**Step 2: Run independent review**

Ask an independent reviewer to check:

- impossible move directions are blocked before executor;
- valid opposite-store moves still work;
- evidence ids are retained;
- diagnostics are bounded and useful;
- no new approval lane / confidence gate / external memory route was added;
- executor stale-source guard remains defense-in-depth.

If the reviewer reports blockers, add RED tests for each blocker before patching.

**Step 3: Update plan status**

Update this plan and the plan index with:

- focused tests result;
- full suite result;
- artifact/smoke result;
- review verdict;
- commit hash.

**Step 4: Commit and push**

```bash
git add hermes_self_improvement/knowledge_transactions.py hermes_self_improvement/planner_runtime.py hermes_self_improvement/prompts.py tests/test_skill_planner.py .hermes/plans/2026-06-01-memory-placement-direction-validation.md .hermes/plans/README.md .hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md
git commit -m "fix: validate memory placement directions"
git push
```

---

## Review checklist before implementation

- Is `allowed_decisions` store-specific at the digest boundary?
- Do prompt rendering and digest construction share the same placement-direction helper?
- Does the prompt explain that move operation names are source→target directions, not target-category labels?
- Does context-aware normalizer validation use candidate `current_store` instead of trusting raw LLM operation names?
- Is the generic structural normalizer bypassed for raw LLM `move_user_to_memory` / `move_memory_to_user` decisions unless candidate context is available?
- Does the exact incident pattern end with no executable `placement_move` apply and no apply with empty `evidence_ids`?
- Does a bad LLM decision become `block`/`defer`, not an executable `placement_move`?
- Are evidence ids preserved on valid moves and on invalid-direction blocks?
- Are diagnostics compact, free of full memory text, and labeled `planner_emitted_but_normalization_rejected`?
- Are valid moves still executable through existing add-before-remove + stale-source executor checks?

## Expected next implementation slice

Start with Task 1 RED. Do not begin implementation from executor code; the root bug is planner/normalizer direction semantics.

---

## Implementation progress

- [x] Task 1 — Added shared placement-direction helpers and narrowed digest `allowed_decisions` by `current_store`.
- [x] Task 2 — Prompt rendering now shows only the store-valid move template for each memory placement candidate.
- [x] Task 3 — Public `run_planner` path now rejects placement move decisions whose direction conflicts with candidate `current_store`, preserves raw diagnostics, and defaults the candidate to bounded defer diagnostics.

Verification so far:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_skill_planner.py -q
# 55 passed

$PY -m py_compile __init__.py hermes_self_improvement/*.py && $PY -m pytest -q && git diff --check && git status --short
# 943 passed, 2 skipped
```

Known-incident smoke:

- Replayed the incident-shaped public planner path with `memory_place_2217e1ddb538`, `current_store=user`, `suggested_route=likely_keep`, and a bad planner-emitted `move_memory_to_user` transaction.
- Current result: no executable `placement_move`; normalized output is a single `defer` transaction with `reason=memory_placement_candidate_not_selected_by_planner`.
- Diagnostics preserve `raw_memory_placement_decision_ids=["memory_place_2217e1ddb538"]` and report `diagnosis=planner_emitted_but_normalization_rejected`.

Follow-up cleanup slice:

- Added clear cross-store duplicate cleanup hints: when the same exact text exists in USER and MEMORY and the text has a clear canonical store, the duplicate side receives an apply-oriented `memory_remove` hint.
- Planner prompt now renders canonical cleanup templates such as `remove_builtin_memory` for apply-safe duplicate cleanup groups.
- Canonical transaction normalization preserves `source_evidence_id` in `evidence_ids` for source-directed memory cleanup operations.
- Prompt guidance now explicitly says existing skill coverage is not a skip reason when source cleanup is needed: use `memory_to_skill` to update/verify the skill and remove source memory after the skill-side change is safe.
- Dry-run `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260601T065204Z.json` produced `apply=4 / defer=29 / skip=66 / block=0`, with three `memory_to_skill` candidates selected for existing skills (`hermes-gateway-and-sessions`, `hindsight-operations`, `hermes-lcm`) and zero dropped memory-routed-to-skill candidates.
