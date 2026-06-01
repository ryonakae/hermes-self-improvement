# Semantic Review Actionability Follow-up Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Fix the two actionability gaps surfaced by `run-20260601T164953Z`: `memory_to_skill` transactions must preserve their source evidence id, and `placement_split` must become executable only when exact split text is supplied.

**Architecture:** Keep semantic judgment in the Planner. Code should only preserve planner-supplied canonical fields, render safer templates, validate exact source/destination text, and fail closed when required fields are absent. Do not add new roles, approval queues, scoring lanes, route heuristics, or direct memory/skill filesystem mutation.

**Tech Stack:** Python, pytest, Hermes `hermes self-improvement` CLI, official skill/memory tool execution paths.

---

## Current observed state

- Repo: `/Users/ryo.nakae/.hermes/plugins/hermes-self-improvement`
- Branch/upstream: `main` / `origin/main`
- Current HEAD when this plan was written: `b76af3b test: add semantic knowledge review dogfood fixture`
- Active parent plan: `.hermes/plans/2026-06-01-llm-semantic-knowledge-review.md`
- Parent plan status: implemented through Phase 7 and pushed.
- Source dry-run artifact:
  - `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260601T164953Z.json`
  - `dry_run=true`, `execute=false`, `target_changed=false`
  - `knowledge_transactions=101`
  - `action_summary={apply:0, block:8, defer:25, skip:68}`
  - route leaks: `[]`
- Two remaining gaps from the dry-run:
  1. `memory_to_skill` selected 8 times but every item blocked with `transaction_missing_source_evidence_id`.
  2. Raw planner emitted `placement_split` 9 times, but final transactions deferred with `mixed_entry_needs_exact_split_text` rather than producing exact executable split payloads.

## Scope

In scope:

- Planner prompt templates and allowed field list.
- Planner normalizer ordering/field preservation for `memory_to_skill`.
- `placement_split` canonical payload requirements and normalization validation.
- Focused regression tests and one dry-run dogfood check.
- Plan/index updates.

Out of scope:

- Hermes core changes.
- Runtime config / cron schedule changes.
- Direct edits to built-in memory files or provider DBs.
- Loosening mutation safety gates.
- Treating candidate target skills or observations as deterministic route commands.
- Forcing live mutation from the source dry-run artifact.

---

## Completion criteria

This plan is complete when all are true:

1. A planner `memory_to_skill` transaction that uses `source_evidence_id` and a valid existing editable `target_skill` normalizes to `decision=apply`, `transaction_kind=memory_to_skill`, `source_id=<source_evidence_id>`, not `block`.
2. A planner `memory_to_skill` transaction without `source_evidence_id` still blocks with `transaction_missing_source_evidence_id`.
3. The prompt field list and templates explicitly include `source_evidence_id`, `source_old_text`, `target_skill`, `skill_task`, and for split transactions `destination_store`, `destination_content`, and optional `source_replacement`.
4. `placement_split` stays `defer` unless it carries exact `source_old_text`, exact `destination_content`, and either exact `source_replacement` or an explicit no-source-replacement operation contract.
5. Executable `placement_split` keeps using official memory tool execution only, with existing source-staleness checks and add-before-remove / replace ordering.
6. The dry-run artifact after implementation has route leaks `[]`, and the two gap counters improve or fail closed with clearer reasons.

---

## Task 0: Baseline reproduction fixture

**Objective:** Turn the two dry-run findings into deterministic regression tests before touching code.

**Files:**

- Modify: `tests/test_skill_planner.py`
- Modify: `tests/test_knowledge_transactions.py`
- Optional helper reads: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260601T164953Z.json`

**Step 1: Extract the observed artifact shape into a small deterministic fixture**

Read `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260601T164953Z.json` and copy only the minimal raw transaction shapes that caused the two gaps into tests. Do not depend on the runtime artifact file at test time; tests must be deterministic and repo-local.

For the `memory_to_skill` case, the fixture should represent the actual blocked shape: `transaction_kind="memory_to_skill"`, `target_store="skill"`, valid `target_skill`, exact `source_old_text`, but missing `source_evidence_id`. The new positive fixture should then add only the missing explicit `source_evidence_id` and prove the same shape becomes actionable.

For the `placement_split` case, the fixture should represent the raw planner shape from the artifact: `transaction_kind="placement_split"`, `operation="split"`, source text present, but no exact destination/source split text.

**Step 2: Add tests for the observed dry-run gap**

Add tests near the existing Phase 7 / golden fixture section:

```python
def test_dogfood_memory_to_skill_with_source_evidence_id_is_actionable():
    raw = {
        "transaction_kind": "memory_to_skill",
        "decision": "apply",
        "source_evidence_id": "memory_place_298a033826ec",
        "source_store": "builtin_memory",
        "source_old_text": "When a workflow repeats, patch the existing skill first.",
        "target_store": "skill",
        "target_skill": "safe-patch-usage",
        "skill_task": {"maintenance_action": "patch"},
        "reason": "procedural_memory_belongs_in_skill",
    }

    normalized = normalize_knowledge_transaction(raw)

    assert normalized["decision"] == "apply"
    assert normalized["transaction_kind"] == "memory_to_skill"
    assert normalized["source_id"] == "memory_place_298a033826ec"
    assert normalized["evidence_ids"] == ["memory_place_298a033826ec"]
    assert normalized["target_id"] == "safe-patch-usage"
```

Add the planner-level version in `tests/test_skill_planner.py` using `_planner_func` so it passes through `run_planner()` normalization, not only `normalize_knowledge_transaction()`.

**Step 3: Add a RED test for the current normalizer branch ordering**

Use a fake planner that emits canonical `memory_to_skill` with `target_store="skill"`. The expected result is actionable. If it currently routes through `_normalize_context_checked_memory_placement_transaction()` and loses memory-to-skill-specific handling, the test should fail.

**Step 4: Add a RED test for executable split payload requirements**

In `tests/test_knowledge_transactions.py`, assert:

- `placement_split` with only `source_old_text` and no `destination_content` blocks/defer-normalizes with a compact reason such as `split_missing_destination_content` or remains current `mixed_entry_needs_exact_split_text`.
- `placement_split` with `source_evidence_id`, `source_old_text`, `destination_store="builtin_memory"`, `destination_content`, and `source_replacement` normalizes as `apply` and preserves all fields.

**Step 5: Run focused tests and confirm failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_knowledge_transactions.py tests/test_skill_planner.py::TestGoldenFixtureDogfood -q
```

Expected before implementation: at least one new test fails, proving the plan is testing the actual gap.

**Commit:** do not commit yet unless the project convention for RED-only commits is explicitly chosen. Prefer combining tests with the minimal fix unless the implementer wants a visible RED checkpoint.

---

## Task 1: Preserve `memory_to_skill` source identity through planner normalization

**Objective:** Make valid `memory_to_skill` planner output stay actionable without guessing source ids.

**Files:**

- Modify: `hermes_self_improvement/planner_runtime.py`
- Modify: `tests/test_skill_planner.py`
- Modify: `tests/test_knowledge_transactions.py`

**Current suspected issue:**

`run_planner()` currently checks `_is_canonical_knowledge_transaction(raw)` before the dedicated `transaction_kind == "memory_to_skill"` branch. `_is_canonical_knowledge_transaction()` returns true for `transaction_kind == "memory_to_skill" and target_store == "skill"`, so memory-to-skill rows can bypass `_normalize_memory_to_skill_transaction()`.

**Step 1: Reorder or narrow the canonical branch**

In `planner_runtime.py`, change the decision order so `memory_to_skill` is handled before generic canonical memory transactions:

```python
elif str(raw.get("transaction_kind") or "") == "memory_to_skill":
    item = _normalize_memory_to_skill_transaction(
        raw,
        candidate_names=candidate_names,
        available_evidence_ids=available_evidence_ids,
    )
elif _is_canonical_knowledge_transaction(raw):
    item = _normalize_context_checked_memory_placement_transaction(raw, memory_placement_by_id=memory_placement_by_id)
```

Do not make `_normalize_context_checked_memory_placement_transaction()` understand memory-to-skill unless a smaller change is impossible; keep the ownership clear.

**Step 2: Tighten `_normalize_memory_to_skill_transaction()`**

Ensure it accepts only explicit source identity:

- `source_id` or `source_evidence_id` is required.
- The selected source id must be in `available_evidence_ids` when that set is non-empty.
- `evidence_ids` should include the source id.
- Do not infer source id from unrelated `evidence_ids`, `target_skill`, or candidate target hints.
- Preserve `source_old_text`, `source_store`, `target_store`, `target_skill` / `target_id`, and `skill_task` / `editor_task`.

Add explicit tests for both task field spellings:

- `skill_task` supplied by the Planner is preserved into the normalized transaction editor payload.
- `editor_task` supplied by the Planner is also preserved.
- The same preservation is verified both at `normalize_knowledge_transaction()` level and through `run_planner(..., _planner_func=...)` so the dedicated `_normalize_memory_to_skill_transaction()` path cannot silently drop it.

Expected normalized shape:

```json
{
  "transaction_kind": "memory_to_skill",
  "decision": "apply",
  "source_store": "builtin_memory",
  "source_id": "memory_place_x",
  "source_old_text": "...",
  "target_store": "skill",
  "target_id": "safe-patch-usage",
  "operation": "move",
  "evidence_ids": ["memory_place_x"],
  "editor_task": {"maintenance_action": "patch"}
}
```

**Step 3: Preserve existing block tests**

Existing tests already assert missing source id blocks:

- `test_normalize_memory_to_skill_blocks_when_source_id_would_be_guessed_from_unrelated_evidence`
- `test_normalize_memory_to_skill_blocks_when_source_id_would_be_guessed_from_target_skill`

Keep these green. This is the safety boundary.

**Step 4: Run focused tests**

```bash
.venv/bin/python -m pytest tests/test_knowledge_transactions.py tests/test_knowledge_maintenance_planner.py tests/test_skill_planner.py -q
```

Expected: pass.

**Suggested commit:**

```bash
git add hermes_self_improvement/planner_runtime.py tests/test_knowledge_transactions.py tests/test_skill_planner.py
git commit -m "fix: preserve memory-to-skill source evidence"
```

---

## Task 2: Make memory-to-skill prompt templates harder to underspecify

**Objective:** Reduce future planner omissions by making source id and exact old text non-optional in the rendered prompt.

**Files:**

- Modify: `hermes_self_improvement/prompts.py`
- Modify: `tests/test_skill_planner.py`

**Step 1: Update the base planner field list**

In `hermes_self_improvement/prompts.py`, update the actual planner field list in `PLANNER_USER_PREFIX` so it includes all canonical fields the templates use. Do not target an invented base-section constant.

- `source_evidence_id`
- `source_old_text`
- `target_store`
- `target_skill`
- `skill_task`
- `destination_store`
- `destination_content`
- `source_replacement`
- `replacement_content`

Do not add old route vocabulary. If implementation later moves the field list out of `PLANNER_USER_PREFIX`, update the tests to assert the rendered prompt rather than the constant name.

**Step 2: Update memory-to-skill templates**

In `_render_memory_placement_candidates_section()` and `_render_knowledge_maintenance_section()`, keep examples explicit:

```json
{
  "transaction_kind": "memory_to_skill",
  "decision": "apply",
  "source_evidence_id": "<copy evidence_id exactly>",
  "source_store": "builtin_memory",
  "source_old_text": "<copy exact old_text>",
  "target_store": "skill",
  "target_skill": "<existing-editable-skill-name>",
  "skill_task": {"maintenance_action":"patch","instructions":"..."},
  "reason": "procedural_memory_belongs_in_skill"
}
```

**Step 3: Add prompt rendering assertions**

Add/extend tests in `tests/test_skill_planner.py` to assert the rendered prompt includes:

- `source_evidence_id`
- `source_old_text`
- `target_skill`
- `skill_task`
- `Do not infer source_evidence_id`

Also assert the memory placement / semantic split sections do not regress to `source_id`-only templates when the visible contract says `source_evidence_id`. `source_id` may still appear in normalized internals, but Planner-facing templates should make the source evidence id field explicit.

**Step 4: Run prompt tests**

```bash
.venv/bin/python -m pytest tests/test_skill_planner.py -q
```

Expected: pass.

**Suggested commit:**

```bash
git add hermes_self_improvement/prompts.py tests/test_skill_planner.py
git commit -m "test: harden memory-to-skill planner templates"
```

---

## Task 3: Define executable `placement_split` contract

**Objective:** Let the Planner produce executable split transactions only when it supplies exact split text; keep all other split candidates deferred.

**Files:**

- Modify: `hermes_self_improvement/knowledge_transactions.py`
- Modify: `hermes_self_improvement/prompts.py`
- Modify: `tests/test_knowledge_transactions.py`
- Modify: `tests/test_skill_planner.py`

**Contract:**

Executable `placement_split` requires:

- `transaction_kind="placement_split"`
- `decision="apply"`
- `operation="split"`
- `source_evidence_id` or `source_id`
- `source_store` in `builtin_user` / `builtin_memory`
- exact `source_old_text`
- `destination_store` in the opposite built-in store, or explicit same-store split if future tests require it
- exact `destination_content`
- one of:
  - exact `source_replacement` to replace the original source entry after extracting destination content, or
  - explicit `remove_source=true` only if the destination content fully replaces the source entry semantics. Prefer not adding this option unless current executor already supports it.

Recommended minimal first implementation: require `source_replacement`. That avoids full-source removal ambiguity.

**Step 1: Add normalizer validation**

In `knowledge_transactions.py`, extend validation for `transaction_kind == "placement_split"`:

- Missing `destination_content` blocks/defer-normalizes with `split_missing_destination_content`.
- Missing `source_replacement` blocks/defer-normalizes with `split_missing_source_replacement`.
- Missing `source_id`/`source_old_text` keeps existing source-field block behavior.

Use compact reasons. Do not include full text in reasons.

Add explicit unit tests for these exact reason strings. Do not leave the executor to collapse underspecified split payloads into generic `knowledge_transaction_missing_required_fields`, because the dry-run follow-up needs to distinguish planner underspecification from executor/runtime failure.

**Step 2: Preserve payload fields**

The canonicalizer already copies `source_replacement`, `destination_store`, and `destination_content`. Ensure tests lock this.

**Step 3: Update prompt template**

In `_render_semantic_knowledge_section()`, replace the current defer-only split template:

```python
{"transaction_kind":"placement_split","decision":"defer", ...}
```

with two templates:

1. executable template only when the planner can fill exact text:

```json
{
  "transaction_kind":"placement_split",
  "decision":"apply",
  "operation":"split",
  "source_evidence_id":"<copy source_evidence_id>",
  "source_store":"<current_store>",
  "source_old_text":"<copy exact old_text>",
  "destination_store":"builtin_memory",
  "destination_content":"<exact extracted durable environment/procedure text>",
  "source_replacement":"<exact remaining USER preference text>",
  "reason":"mixed_entry_split_exact_text"
}
```

2. defer template when exact text is not clear:

```json
{
  "transaction_kind":"placement_split",
  "decision":"defer",
  "operation":"none",
  "source_evidence_id":"<copy source_evidence_id>",
  "reason":"mixed_entry_needs_exact_split_text"
}
```

**Step 4: Add prompt tests**

Assert rendered prompt includes `destination_content`, `source_replacement`, and the instruction that exact text is required.

Also assert the prompt template uses `source_evidence_id` explicitly for split candidates. The current code has used a `source_id` field in the split template; this follow-up should make the Planner-facing field match the canonical source-evidence contract.

**Step 5: Run focused tests**

```bash
.venv/bin/python -m pytest tests/test_knowledge_transactions.py tests/test_skill_planner.py -q
```

Expected: pass.

**Suggested commit:**

```bash
git add hermes_self_improvement/knowledge_transactions.py hermes_self_improvement/prompts.py tests/test_knowledge_transactions.py tests/test_skill_planner.py
git commit -m "fix: require exact text for placement split"
```

---

## Task 4: Verify executor compatibility for executable split

**Objective:** Confirm existing executor already handles `destination_content` + `source_replacement`; if not, add the smallest official-tool-only fix.

**Files:**

- Inspect/modify: `hermes_self_improvement/editor_memory.py` or executor module containing `execute_knowledge_transaction()`
- Inspect/modify: `tests/test_memory_to_skill_migration.py` or existing memory execution tests
- Search target: `execute_knowledge_transaction`, `placement_split`, `destination_content`, `source_replacement`

**Step 1: Locate execution path**

Run:

```bash
python - <<'PY'
from pathlib import Path
for p in Path('hermes_self_improvement').glob('*.py'):
    text=p.read_text()
    if 'placement_split' in text or 'execute_knowledge_transaction' in text:
        print(p)
PY
```

**Step 2: Add or verify execution test**

Test that an executable split:

1. Adds `destination_content` to `destination_store` through the official memory tool.
2. Replaces the source entry with `source_replacement` through the official memory tool.
3. Does not remove/replace source if destination add fails.
4. Blocks if source current entry no longer matches `source_old_text`.

Use fake memory tool calls; do not touch real memory.

Also test that an underspecified split never reaches memory tool execution and reports the specific normalizer reason (`split_missing_destination_content` or `split_missing_source_replacement`) before the executor layer can turn it into a generic missing-fields failure.

Include a direct executor/replay-path regression, not only a normalizer unit test:

- Call `execute_knowledge_transaction()` or the nearest public runner helper with an underspecified `placement_split` payload.
- Assert the result reason is the specific split underspecification reason, not generic `knowledge_transaction_missing_required_fields`.
- Assert the fake memory tool received no calls.

If the executor currently accepts only already-normalized transactions, either normalize at the boundary inside the helper or document and test the boundary function that replay uses. The point is to prevent replay/direct-executor paths from bypassing the new fail-closed reason.

**Step 3: Implement only if needed**

If existing code already supports this, add only the regression test. If not, modify executor minimally. Preserve add-before-source-change ordering.

**Step 4: Run executor tests**

```bash
.venv/bin/python -m pytest tests/test_memory_to_skill_migration.py tests/test_knowledge_transactions.py -q
```

Expected: pass.

**Suggested commit:**

```bash
git add hermes_self_improvement/*.py tests/test_memory_to_skill_migration.py tests/test_knowledge_transactions.py
git commit -m "test: verify placement split execution safety"
```

---

## Task 5: Dogfood dry-run and artifact quality check

**Objective:** Prove the fixes improve the observed dry-run behavior without creating unsafe mutations.

**Files:**

- Modify: `.hermes/plans/2026-06-02-semantic-review-actionability-followup.md`
- Modify: `.hermes/plans/README.md`

**Step 1: Run full validation**

```bash
.venv/bin/python -m py_compile __init__.py hermes_self_improvement/*.py
.venv/bin/python -m pytest tests -q
git diff --check
hermes self-improvement status
```

Expected:

- full suite passes
- status ready
- no diff whitespace errors

**Step 2: Run dry-run dogfood**

```bash
hermes self-improvement improve --dry-run --json > /tmp/hermes-si-actionability-followup.json
```

Extract artifact path:

```bash
python - <<'PY'
import json
from pathlib import Path
out=json.loads(Path('/tmp/hermes-si-actionability-followup.json').read_text())
print(out.get('artifact_path'))
PY
```

**Step 3: Inspect artifact**

Use a script to report:

- `dry_run`, `execute`, `target_changed`
- `action_summary`
- counts by `transaction_kind`
- `memory_to_skill` block reasons
- `placement_split` apply/defer/block reasons
- route leak terms

Expected improvement:

- route leaks remain `[]`
- no unsafe apply in dry-run execution
- `memory_to_skill` no longer universally blocks with `transaction_missing_source_evidence_id` when planner supplied source id
- `placement_split` either has executable exact text or a clearer fail-closed reason (`split_missing_destination_content` / `split_missing_source_replacement`), not an ambiguous silent fallback

**Step 4: Update this plan and index**

Record latest verification and artifact path in:

- `.hermes/plans/2026-06-02-semantic-review-actionability-followup.md`
- `.hermes/plans/README.md`

**Suggested commit:**

```bash
git add .hermes/plans/2026-06-02-semantic-review-actionability-followup.md .hermes/plans/README.md
git commit -m "docs: record semantic actionability follow-up verification"
```

---

## Final verification before reporting complete

Run:

```bash
.venv/bin/python -m py_compile __init__.py hermes_self_improvement/*.py
.venv/bin/python -m pytest tests -q
hermes self-improvement status
git diff --check
git status --short
```

If the user authorizes external visibility, push:

```bash
git push origin main
```

Report:

- commits
- full test result
- dry-run artifact path
- memory_to_skill block count before/after
- placement_split apply/defer/block count before/after
- route leak scan
- remaining follow-up, if any

---

## Implementation progress

| Phase | Status | Notes |
|-------|--------|-------|
| 0: Baseline reproduction fixture | ⬜ Pending | Convert minimal raw shapes from `run-20260601T164953Z` into deterministic tests without runtime artifact dependency. |
| 1: Preserve `memory_to_skill` source identity | ⬜ Pending | Route canonical memory_to_skill through dedicated normalizer before generic canonical branch; preserve `skill_task` / `editor_task`. |
| 2: Harden memory-to-skill prompt templates | ⬜ Pending | Make `source_evidence_id` / exact `source_old_text` impossible to miss in templates. |
| 3: Executable placement_split contract | ⬜ Pending | Require exact `destination_content` and `source_replacement`; otherwise fail closed. |
| 4: Executor compatibility | ⬜ Pending | Verify official memory-tool ordering for split add + source replacement, and direct executor fail-closed reasons for underspecified split payloads. |
| 5: Dry-run dogfood | ⬜ Pending | Full suite + dry-run artifact scan and docs/index update. |

**Latest verification:** Plan only. No code changes implemented yet.
