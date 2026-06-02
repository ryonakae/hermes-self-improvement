# Placement Move Canonical Decision Follow-up Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Close the last dry-run actionability/schema gap where planner-produced `move_user_to_memory` / `move_memory_to_user` decisions can remain non-canonical decisions with `operation=none` instead of becoming executable `apply` `placement_move` transactions or clear fail-closed blocks.

**Architecture:** Keep semantic USER/MEMORY placement judgment in the Planner. Code should only normalize explicit planner decisions into the canonical transaction vocabulary (`apply` / `defer` / `skip` / `block`), validate direction against the memory placement candidate’s `current_store`, and fail closed when source identity/text is missing. Do not reintroduce route heuristics, confidence gates, approval queues, or split memory/skill lanes.

**Tech Stack:** Python, pytest, existing `hermes_self_improvement.knowledge_transactions`, `planner_runtime`, and `runner_steps` canonical transaction path.

## Completion note

- Status: implemented and verified on 2026-06-02.
- Final commit: this commit (`fix: canonicalize placement move decisions`).
- Focused tests: `.venv/bin/python -m pytest tests/test_knowledge_transactions.py tests/test_skill_planner.py tests/test_plugin_tools.py -q` → `109 passed`.
- Full validation: `.venv/bin/python -m py_compile __init__.py hermes_self_improvement/*.py`; `.venv/bin/python -m pytest tests -q` → `994 passed, 2 skipped`; `git diff --check`; `hermes self-improvement status --json`.
- Runtime setup repair: `hermes self-improvement setup --json` materialized active prompt overlays and restored `runtime_setup.initialized=true` without reset.
- Dogfood artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260602T051854Z.json` from `/tmp/hermes-si-placement-move-canonical-followup.json`.
- Dogfood result: `dry_run=true`, `target_changed=false`, `action_summary apply=6 / defer=15 / skip=71 / block=9`, `noncanonical_decision_count=0`, `move_decision_count=0`, `route_leaks=[]`.

---

## Current observed state

- Repo: `/Users/ryo.nakae/.hermes/plugins/hermes-self-improvement`
- Branch: `main`
- Baseline commit: `18635dc fix: harden semantic knowledge actionability`
- Pre-plan worktree: clean before this docs change.
- Source dry-run artifact:
  - CLI-captured JSON: `/tmp/hermes-si-actionability-followup-2.json`
  - Runtime artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260602T003415Z.json`
- Baseline dry-run summary:
  - `dry_run=true`
  - `target_changed=false`
  - `action_summary`: `apply=0 / defer=28 / skip=69 / block=9`
  - route leak strings: `[]`
  - `memory_to_skill` source misses: `0`
  - `memory_to_skill` without editor task: blocked with `memory_to_skill_missing_editor_task`
  - `placement_split`: exact text missing rows stayed non-mutating with `mixed_entry_needs_exact_split_text`
- Remaining concrete gap from the artifact:
  - Two planner-selected placement moves survived into final `knowledge_transactions` with non-canonical decisions:
    - `decision=move_user_to_memory`, `transaction_kind=memory`, `target_store=builtin_memory`, `operation=none`, `source_id=memory_place_bd8e594afd41`
    - `decision=move_memory_to_user`, `transaction_kind=""`, `target_store=user`, `operation=none`, `source_id=memory_place_e4613415ff97`
  - This is not a mutation safety failure in dry-run, but it is an artifact contract bug: final `knowledge_transactions[*].decision` should be only `apply`, `defer`, `skip`, or `block`.
  - The likely code smell is `knowledge_transactions._canonicalize()`: `memory_product_operation = operation or legacy_decision` treats planner `operation="none"` as a real operation, so legacy move decisions do not enter `_MEMORY_PRODUCT_OPERATIONS` normalization.

## Non-goals

- Do not loosen memory mutation safety.
- Do not force these exact live memories to mutate.
- Do not add deterministic semantic routing based on text content.
- Do not change `placement_split` execution requirements.
- Do not restore `suggested_route`, `likely_*`, `allowed_recommendations`, or route-named diagnostics.
- Do not introduce a new planner lane or executor surface.

## Completion criteria

- Final canonical transactions never expose `decision=move_user_to_memory` or `decision=move_memory_to_user`; those become `decision=apply`, `transaction_kind=placement_move`, `operation=move` when direction/source fields are valid.
- Direction stays context-checked against the referenced memory placement candidate’s `current_store` via `_normalize_context_checked_memory_placement_transaction()` / `placement_move_operation_for_current_store()`.
- Invalid or underspecified placement moves fail closed before memory tools are called.
- Compact summaries and action counts use the canonical `apply/defer/skip/block` vocabulary.
- A dry-run dogfood artifact after implementation has no non-canonical final decisions and no route-hint regressions.

---

## Task 1: Add RED unit coverage for `operation="none"` placement move decisions

**Objective:** Prove the artifact-shaped raw planner row currently fails canonical normalization when a move decision is paired with `operation="none"`.

**Files:**
- Modify: `tests/test_knowledge_transactions.py`
- Read: `hermes_self_improvement/knowledge_transactions.py:198-327`

**Step 1: Add failing tests**

Add two tests close to the existing normalization tests:

```python
def test_normalize_move_user_to_memory_decision_ignores_none_operation():
    from hermes_self_improvement.knowledge_transactions import normalize_knowledge_transaction

    tx = normalize_knowledge_transaction({
        "decision": "move_user_to_memory",
        "transaction_kind": "memory",
        "target_store": "builtin_memory",
        "target_id": "memory",
        "operation": "none",
        "source_id": "memory_place_bd8e594afd41",
        "source_old_text": "self-improvement design belongs in memory.",
        "evidence_ids": ["memory_place_bd8e594afd41"],
        "reason": "project_convention_belongs_in_memory",
    })

    assert tx["decision"] == "apply"
    assert tx["transaction_kind"] == "placement_move"
    assert tx["source_store"] == "builtin_user"
    assert tx["target_store"] == "builtin_memory"
    assert tx["target_id"] == "memory"
    assert tx["operation"] == "move"
    assert tx["source_id"] == "memory_place_bd8e594afd41"
    assert tx["transaction_result"]["outcome"] != "blocked" if "transaction_result" in tx else True


def test_normalize_move_memory_to_user_decision_ignores_none_operation():
    from hermes_self_improvement.knowledge_transactions import normalize_knowledge_transaction

    tx = normalize_knowledge_transaction({
        "decision": "move_memory_to_user",
        "target_store": "builtin_user",
        "target_id": "user",
        "operation": "none",
        "source_id": "memory_place_e4613415ff97",
        "source_old_text": "User prefers keeping Mac mini responsive.",
        "evidence_ids": ["memory_place_e4613415ff97"],
        "reason": "user_preference_belongs_in_user_store",
    })

    assert tx["decision"] == "apply"
    assert tx["transaction_kind"] == "placement_move"
    assert tx["source_store"] == "builtin_memory"
    assert tx["target_store"] == "builtin_user"
    assert tx["target_id"] == "user"
    assert tx["operation"] == "move"
    assert tx["source_id"] == "memory_place_e4613415ff97"
```

If the project already has a cleaner helper/assertion style in `tests/test_knowledge_transactions.py`, follow that style instead of copy-pasting exactly.

**Step 2: Verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_knowledge_transactions.py -q
```

Expected before implementation: at least one new test fails because `decision` remains `move_user_to_memory` / `move_memory_to_user` or `operation` remains `none`.

---

## Task 2: Canonicalize product move decisions before treating `operation="none"` as final

**Objective:** Normalize planner product decisions even when the planner also emits `operation="none"`.

**Files:**
- Modify: `hermes_self_improvement/knowledge_transactions.py:198-327`
- Test: `tests/test_knowledge_transactions.py`

**Step 1: Implement the minimal normalization fix**

In `_canonicalize()`, make `operation="none"` behave like an absent operation for `_MEMORY_PRODUCT_OPERATIONS` lookup. Keep real operations such as `move_user_to_memory`, `move_memory_to_user`, `replace_builtin_user`, and `remove_builtin_memory` working.

Suggested shape:

```python
legacy_decision = str(raw.get("decision") or "")
operation_for_product_lookup = "" if operation == "none" else operation
memory_product_operation = operation_for_product_lookup or legacy_decision
```

Then keep the existing `_MEMORY_PRODUCT_OPERATIONS` branch:

```python
if memory_product_operation in _MEMORY_PRODUCT_OPERATIONS:
    transaction_kind, source_store, target_store, operation = _MEMORY_PRODUCT_OPERATIONS[memory_product_operation]
    decision = "apply" if decision in {"apply", "accepted", "preview", memory_product_operation} else decision
    target_id = target_id or _BUILTIN_MEMORY_TARGET_IDS.get(target_store, "")
```

If this still leaves `decision` non-canonical, adjust `_canonical_decision()` so memory product decisions map to `apply` rather than returning raw strings. Prefer a small set-based change using `_MEMORY_PRODUCT_OPERATIONS` keys.

**Step 2: Verify focused tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_knowledge_transactions.py -q
```

Expected: all tests in that file pass.

---

## Task 3: Add planner-payload regression for artifact-shaped placement moves

**Objective:** Prove `_normalize_planner_payload()` / `run_planner()` does not leak `move_user_to_memory` or `move_memory_to_user` into final `knowledge_transactions`.

**Files:**
- Modify: `tests/test_skill_planner.py`
- Read: `hermes_self_improvement/planner_runtime.py:1316-1455`

**Step 1: Add a deterministic digest fixture**

Use the existing test helpers in `tests/test_skill_planner.py`. Add a test that constructs a digest with two `memory_placement_candidates`:

- user-source candidate:
  - `evidence_id="memory_place_bd8e594afd41"`
  - `source_evidence_id="memory_place_bd8e594afd41"`
  - `current_store="user"`
  - `old_text="self-improvement設計は1 Planner+1 Knowledge Editor。"`
- memory-source candidate:
  - `evidence_id="memory_place_e4613415ff97"`
  - `source_evidence_id="memory_place_e4613415ff97"`
  - `current_store="memory"`
  - `old_text="Hindsight tuning preference: keep Mac mini responsive."`

Then feed planner payload rows matching the artifact shape:

```python
{
    "decision": "move_user_to_memory",
    "transaction_kind": "memory",
    "target_store": "builtin_memory",
    "operation": "none",
    "source_id": "memory_place_bd8e594afd41",
    "source_old_text": "self-improvement設計は1 Planner+1 Knowledge Editor。",
    "reason": "project_convention_belongs_in_memory",
}
```

and:

```python
{
    "decision": "move_memory_to_user",
    "target_store": "user",
    "operation": "none",
    "source_id": "memory_place_e4613415ff97",
    "source_old_text": "Hindsight tuning preference: keep Mac mini responsive.",
    "reason": "user_preference_belongs_in_user_store",
}
```

Prefer using the public `run_planner()` test path if existing helpers make that cheap. If not, call `_normalize_planner_payload()` directly, as this is a regression for planner normalization rather than LLM behavior.

**Step 2: Assert canonical output**

Expected assertions:

```python
assert {tx["decision"] for tx in transactions} == {"apply"}
assert {tx["transaction_kind"] for tx in transactions} == {"placement_move"}
assert {tx["operation"] for tx in transactions} == {"move"}
assert {tx["source_store"] for tx in transactions} == {"builtin_user", "builtin_memory"}
assert {tx["target_store"] for tx in transactions} == {"builtin_memory", "builtin_user"}
assert "move_user_to_memory" not in {tx["decision"] for tx in transactions}
assert "move_memory_to_user" not in {tx["decision"] for tx in transactions}
```

**Step 3: Verify focused planner tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_skill_planner.py -q
```

Expected: new regression passes after Task 2.

---

## Task 4: Preserve fail-closed behavior for wrong-direction or missing-source placement moves

**Objective:** Ensure the normalization fix does not bypass placement direction/source safety.

**Files:**
- Modify: `tests/test_skill_planner.py`
- Modify if needed: `hermes_self_improvement/planner_runtime.py:1326-1351`
- Modify if needed: `hermes_self_improvement/knowledge_transactions.py:387-409`

**Step 1: Add wrong-direction regression**

Create a planner payload where the candidate has `current_store="user"` but the planner emits `decision="move_memory_to_user"` with that evidence id.

Expected behavior:

- It must not become an executable `apply` placement move.
- Acceptable fail-closed outcomes:
  - the raw row is dropped and the default memory placement defer covers the candidate, or
  - the row normalizes to `block` / `defer` with a concrete reason.
- It must not call memory mutation tools.

Use existing diagnostics if available:

```python
assert all(tx.get("decision") != "apply" for tx in transactions)
```

or more specific if the existing implementation exposes a stable reason.

**Step 2: Add missing-source regression**

Create a raw row with `decision="move_user_to_memory"`, valid target store, but missing `source_id` / `source_evidence_id` and missing `source_old_text`.

Expected:

- Final transaction is not an executable apply, or apply is blocked with `transaction_missing_source_fields` / `transaction_missing_source_evidence_id`.
- The executor is not reached with an underspecified apply.

If this is better covered in `tests/test_runner_steps.py`, add it there using the existing `execute_knowledge_transaction` monkeypatch pattern from `test_run_knowledge_improvement_step_dry_run_routes_apply_through_executor`.

**Step 3: Verify related tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_skill_planner.py tests/test_runner_steps.py::test_run_knowledge_improvement_step_dry_run_validates_malformed_placement_move_apply -q
```

Expected: all selected tests pass.

---

## Task 5: Add final artifact-contract / compact-summary regression

**Objective:** Ensure final run payloads and compact tool summaries cannot count non-canonical decisions as actions.

**Files:**
- Modify: `tests/test_report_improve_connection.py` or `tests/test_plugin_tools.py`
- Read: `hermes_self_improvement/tool_handlers.py:90-140`
- Read: `hermes_self_improvement/knowledge_transactions.py:53-120`

**Step 1: Add a small final-payload fixture**

Use an in-memory run result containing canonicalized placement move transactions and assert:

- `action_summary["apply"]` increments for canonical placement moves.
- `by_kind["placement_move"]` increments.
- No key or decision named `move_user_to_memory` / `move_memory_to_user` appears in the final compact result.

Suggested assertion shape:

```python
assert compact["action_summary"]["apply"] == 2
assert compact["steps"]["knowledge_transactions"]["by_kind"]["placement_move"] == 2
assert "move_user_to_memory" not in json.dumps(compact, ensure_ascii=False)
assert "move_memory_to_user" not in json.dumps(compact, ensure_ascii=False)
```

If the existing compact schema intentionally preserves operation names in a diagnostic-only section, narrow the assertion to `knowledge_transactions[*].decision` instead of banning all strings globally.

**Step 2: Verify focused report/tool tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_report_improve_connection.py tests/test_plugin_tools.py -q
```

Expected: selected tests pass.

---

## Task 6: Dogfood with dry-run and inspect the artifact

**Objective:** Prove the live self-improvement dry-run no longer leaks non-canonical placement move decisions.

**Files:**
- Runtime artifact only: `${HERMES_HOME}/self-improvement/runs/run-*.json`
- No code files unless the dogfood exposes a new gap.

**Step 1: Run full validation**

Run:

```bash
.venv/bin/python -m py_compile __init__.py hermes_self_improvement/*.py
.venv/bin/python -m pytest tests -q
git diff --check
hermes self-improvement status
```

Expected:

- Full pytest passes.
- Status remains readable. Existing `active_prompt_overlays_invalid` setup warning, if still present, is not part of this plan unless the status command itself fails.

**Step 2: Run dry-run dogfood**

Run:

```bash
hermes self-improvement improve --dry-run --json > /tmp/hermes-si-placement-move-canonical-followup.json
```

Expected:

- Command exits 0.
- Artifact reports `dry_run=true` and `target_changed=false`.

**Step 3: Inspect the dogfood result mechanically**

Use a small Python snippet rather than eyeballing the huge JSON:

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path
p = Path('/tmp/hermes-si-placement-move-canonical-followup.json')
data = json.loads(p.read_text())
transactions = data.get('knowledge_transactions') or []
noncanonical = [t for t in transactions if t.get('decision') not in {'apply', 'defer', 'skip', 'block'}]
move_decisions = [t for t in transactions if t.get('decision') in {'move_user_to_memory', 'move_memory_to_user'}]
route_leaks = []
text = json.dumps(data, ensure_ascii=False)
for needle in ['suggested_route', 'route_reasons', 'likely_', 'allowed_recommendations', 'default_defer_by_route', 'unhandled_by_route']:
    if needle in text:
        route_leaks.append(needle)
print(json.dumps({
    'run_id': data.get('run_id'),
    'action_summary': data.get('action_summary'),
    'noncanonical_decision_count': len(noncanonical),
    'move_decision_count': len(move_decisions),
    'route_leaks': route_leaks,
}, ensure_ascii=False, indent=2))
assert not noncanonical
assert not move_decisions
assert not route_leaks
assert data.get('dry_run') is True
assert data.get('target_changed') is False
PY
```

Expected:

- `noncanonical_decision_count=0`
- `move_decision_count=0`
- `route_leaks=[]`

---

## Task 7: Update plan index and commit

**Objective:** Record the implementation outcome and keep `.hermes/plans/README.md` as the source of truth.

**Files:**
- Modify: `.hermes/plans/README.md`
- Modify: `.hermes/plans/2026-06-02-placement-move-canonical-decision-followup.md`

**Step 1: Update this plan’s observed-state section after implementation**

Add a short completion note near the top with:

- final commit SHA
- focused tests run
- full validation result
- dogfood artifact path
- final noncanonical decision count
- final route leak count

**Step 2: Update `.hermes/plans/README.md`**

At the top, add this plan as the active/current follow-up while implementation is pending. After implementation, change it to latest completed follow-up.

**Step 3: Commit**

After all validation passes:

```bash
git status --short
git add hermes_self_improvement/knowledge_transactions.py hermes_self_improvement/planner_runtime.py tests/test_knowledge_transactions.py tests/test_skill_planner.py tests/test_runner_steps.py tests/test_report_improve_connection.py tests/test_plugin_tools.py .hermes/plans/README.md .hermes/plans/2026-06-02-placement-move-canonical-decision-followup.md
git commit -m "fix: canonicalize placement move decisions"
```

Do not push unless Ryo asks for push or this repo’s current workflow explicitly requires it.
