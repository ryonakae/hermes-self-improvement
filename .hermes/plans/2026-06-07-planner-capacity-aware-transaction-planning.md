# Planner Capacity-Aware Transaction Planning Plan

**Status (2026-06-07):** Implemented and verified through dry-run dogfood. Planner digest now carries capacity pressure/limit/remaining facts, planned memory write costs, and prompt guidance for capacity-aware apply planning; executor blocks dependent memory applies when linked capacity recovery did not satisfy the dependency; capacity `memory_to_skill` still requires concrete editor task; compact reporting includes capacity-aware dependency counts without memory text. Verification: focused suites `157 passed`, full `pytest tests -q` → `1022 passed, 2 skipped`, `py_compile`, `git diff --check`, and dry-run artifact `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260607T141912Z.json` with `dry_run=true`, `target_changed=false`, no route leaks, `semantic_override_count=0`, `apply=3 / defer=6 / skip=64 / block=9`, planner capacity `builtin_user ok 0/2200`, `builtin_memory ok 1424/2200 remaining 776`, planned write costs `20` with `4` omitted. No mutating run was executed.

> **For Hermes:** Use test-driven-development. Implement task-by-task. This plan is about planning correctness, not forcing apply counts.

**Goal:** Make the Planner see built-in memory capacity before it emits apply transactions, so an apply that needs capacity is planned with preceding Planner-owned capacity work instead of failing later in Editor/executor.

**Architecture:** Extend the existing Planner digest/prompt and canonical transaction flow. Program code may expose capacity facts, approximate write costs, current exact entries, and mechanical dependency metadata. Planner remains responsible for deciding whether to compact, move to skill, clean duplicates, skip, defer, block, or apply. Editor/executor runs only the ordered canonical transactions and blocks mechanically unsafe plans.

**Tech Stack:** Python, pytest, `hermes_self_improvement/planner_runtime.py`, `prompts.py`, `knowledge_transactions.py`, `runner_steps.py`, `tool_handlers.py`, tests under `tests/`, dogfood artifacts under `~/.hermes/self-improvement/runs/`.

---

## Context and correction

Ryo's expectation is not “increase apply at all costs”. The problem is:

- Planner says a knowledge transaction should `apply`.
- Editor/executor later cannot apply because built-in memory is full.
- If memory is full, the system should plan capacity recovery — memory compression, duplicate cleanup, or skill move — before or alongside the original apply.

So the fix is not a more aggressive Editor. The fix is **capacity-aware Planner planning**.

Current state already has partial ingredients:

- `planner_runtime._built_in_memory_capacity_digest()` exposes approximate store capacity facts.
- `prompts._render_builtin_memory_capacity_section()` renders those facts.
- `memory_capacity_followups` records prior capacity failures.
- `capacity_resolution_transaction_id` protects retry ordering.

But the current flow is still mostly reactive:

- capacity facts are background context;
- apply may still be emitted without an explicit capacity precondition;
- capacity recovery appears as follow-up after failure;
- the dry-run `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260607T134704Z.json` showed no exact capacity rewrite and blocked two capacity-related `memory_to_skill` transactions because editor tasks were missing.

This plan moves the decision upstream: the Planner must plan capacity when it plans the apply.

---

## Non-goals

- Do not force `apply > 0`.
- Do not let Editor or program code choose compaction targets semantically.
- Do not introduce deterministic “pick longest entry” / “delete oldest entry” heuristics.
- Do not add same-run recursive LLM loops unless a later proof shows next-run planning cannot work.
- Do not fall back to external memory provider implicitly.
- Do not directly edit `USER.md` / `MEMORY.md`.
- Do not create a new approval stage, scoring system, or second Planner role.

---

## Completion criteria

- Planner digest includes explicit per-store capacity fields that are useful enough for planning:
  - `limit_chars` when known
  - `approx_chars_used`
  - `remaining_chars_estimate`
  - `pressure`: `ok` / `tight` / `full` / `unknown`
  - bounded exact current entries usable for Planner-selected rewrite/remove/skill move
- Planner digest includes approximate write-cost facts for candidate memory applies where available.
- Prompt says: when an apply targets a tight/full built-in store, the Planner must either:
  - emit a preceding capacity transaction (`memory_rewrite`, `duplicate_cleanup`, `memory_to_skill`, `placement_split`) and link the apply to it;
  - choose an apply that fits;
  - or `skip` / `defer` / `block` with a semantic reason.
- Ordered transaction dependencies are explicit enough for executor validation:
  - capacity transaction has stable `transaction_id`
  - dependent apply has `capacity_resolution_transaction_id`
  - unresolved dependent apply blocks before memory mutation calls
- `memory_to_skill` chosen for capacity recovery must be actionable:
  - exact source text
  - existing editable target skill
  - concrete `editor_task` / `skill_task`
  - otherwise it must defer/block semantically, not appear as a broken apply.
- Dry-run dogfood shows Planner capacity reasoning before execution, even if it chooses skip/defer/block. Mutating run remains gated on dry-run inspection.

---

## Task 1: RED test for real capacity fields in Planner digest

**Objective:** Prove the Planner receives actual capacity facts, not only vague approximate text.

**Files:**
- Modify: `tests/test_skill_planner.py`
- Read: `hermes_self_improvement/planner_runtime.py`

**Test outline:**

Add a test near existing built-in memory capacity tests:

```python
def test_planner_digest_exposes_capacity_pressure_and_limits():
    pack_data = pack()
    pack_data["evidence"] = [
        {
            "kind": "memory_inventory_candidate",
            "evidence_id": "memory_inventory_user",
            "inventory": {
                "group_kind": "built_in_memory_inventory",
                "entries": [
                    {"store": "builtin_user", "evidence_id": "user_1", "old_text": "A" * 900},
                    {"store": "builtin_memory", "evidence_id": "memory_1", "old_text": "B" * 2100},
                ],
            },
        }
    ]
    pack_data["built_in_memory_limits"] = {
        "builtin_user": {"limit_chars": 2200},
        "builtin_memory": {"limit_chars": 2200},
    }

    digest = build_planner_digest(pack_data)

    user = digest["built_in_memory_capacity"]["builtin_user"]
    memory = digest["built_in_memory_capacity"]["builtin_memory"]
    assert user["limit_chars"] == 2200
    assert user["remaining_chars_estimate"] == 1300
    assert user["pressure"] == "ok"
    assert memory["remaining_chars_estimate"] == 100
    assert memory["pressure"] in {"tight", "full"}
```

Run:

```bash
.venv/bin/python -m pytest tests/test_skill_planner.py::test_planner_digest_exposes_capacity_pressure_and_limits -q
```

Expected RED: current digest sets `remaining_chars_estimate=None` and has no `limit_chars` / `pressure`.

---

## Task 2: GREEN capacity digest from official/bounded facts

**Objective:** Add mechanical capacity facts without semantic route recommendations.

**Files:**
- Modify: `hermes_self_improvement/planner_runtime.py`

**Implementation guidance:**

Update `_built_in_memory_capacity_digest(evidence_pack)`:

- keep current inventory-derived `approx_chars_used` and exact bounded entries;
- read optional limits from `evidence_pack["built_in_memory_limits"]` if present;
- if limits are absent, use the configured known built-in memory limit only if the repo already has a constant or config value; otherwise keep `limit_chars=None` and `pressure="unknown"`;
- compute:

```python
remaining = limit_chars - approx_chars_used if limit_chars else None
pressure = "unknown"
if remaining is not None:
    if remaining <= 0:
        pressure = "full"
    elif remaining <= 250:
        pressure = "tight"
    else:
        pressure = "ok"
```

Do not add `recommended_action`, `suggested_route`, `likely_*`, or any compaction target choice.

Run:

```bash
.venv/bin/python -m pytest tests/test_skill_planner.py::test_planner_digest_exposes_capacity_pressure_and_limits -q
```

Expected GREEN: capacity facts exist.

---

## Task 3: RED test for candidate write-cost facts

**Objective:** Make the Planner see whether a proposed add/move is likely to fit before planning apply.

**Files:**
- Modify: `tests/test_skill_planner.py`
- Read: `hermes_self_improvement/planner_runtime.py`

**Test outline:**

Create evidence with one candidate that would write to `builtin_memory`:

```python
def test_planner_digest_exposes_memory_write_costs_for_candidates():
    pack_data = pack()
    pack_data["evidence"] = [
        {
            "kind": "memory_placement_candidate",
            "evidence_id": "memory_place_big",
            "source_store": "builtin_user",
            "target_store": "builtin_memory",
            "old_text": "Large durable fact." * 80,
        }
    ]
    pack_data["built_in_memory_limits"] = {"builtin_memory": {"limit_chars": 2200}}

    digest = build_planner_digest(pack_data)

    costs = digest["planned_memory_write_costs"]
    assert costs["items"][0]["source_id"] == "memory_place_big"
    assert costs["items"][0]["target_store"] == "builtin_memory"
    assert costs["items"][0]["estimated_add_chars"] > 0
```

Run:

```bash
.venv/bin/python -m pytest tests/test_skill_planner.py::test_planner_digest_exposes_memory_write_costs_for_candidates -q
```

Expected RED: no `planned_memory_write_costs` digest exists.

---

## Task 4: GREEN planned write-cost digest and prompt section

**Objective:** Expose write-cost facts as Planner input.

**Files:**
- Modify: `hermes_self_improvement/planner_runtime.py`
- Modify: `hermes_self_improvement/prompts.py`
- Test: `tests/test_skill_planner.py`

**Implementation guidance:**

Add `_planned_memory_write_costs_digest(evidence_pack)` that scans bounded evidence for canonical memory placement/add candidates and emits items like:

```python
{
    "source_id": "memory_place_big",
    "source_store": "builtin_user",
    "target_store": "builtin_memory",
    "estimated_add_chars": 1520,
    "candidate_text": "<exact or bounded old_text/content>",
}
```

Add to `build_planner_digest()`:

```python
"planned_memory_write_costs": _planned_memory_write_costs_digest(evidence_pack),
```

Add `_render_planned_memory_write_costs_section(digest)` with wording:

- facts, not recommendations;
- use these to decide whether an apply needs capacity recovery first;
- do not apply into a tight/full store unless the plan also frees capacity or the write clearly fits.

Run:

```bash
.venv/bin/python -m pytest tests/test_skill_planner.py::test_planner_digest_exposes_memory_write_costs_for_candidates -q
```

Expected GREEN.

---

## Task 5: RED prompt test for capacity-aware apply planning

**Objective:** Ensure the prompt requires the Planner to account for capacity before emitting apply.

**Files:**
- Modify: `tests/test_skill_planner.py`
- Read: `hermes_self_improvement/prompts.py`

**Test outline:**

Build a digest with:

- `builtin_memory.pressure="tight"`
- one write-cost item targeting `builtin_memory`
- exact current entries available for possible rewrite

Assert rendered prompt includes:

- `## Planned memory write costs`
- `capacity-aware apply planning`
- `If target store is tight/full, emit capacity recovery before dependent apply or skip/defer/block`
- `capacity_resolution_transaction_id`
- no route leaks

Run:

```bash
.venv/bin/python -m pytest tests/test_skill_planner.py::test_render_planner_messages_requires_capacity_aware_apply_planning -q
```

Expected RED, then GREEN with prompt change.

---

## Task 6: RED executor ordering test for capacity dependency

**Objective:** Make sure a dependent apply cannot run when its capacity resolution did not succeed.

**Files:**
- Modify: `tests/test_runner_steps.py`
- Read: `hermes_self_improvement/runner_steps.py`
- Read: `hermes_self_improvement/knowledge_transactions.py`

**Test outline:**

Fake Planner emits two transactions:

1. `memory_rewrite apply` with `transaction_id="capacity_free_1"` but transaction result will block mechanically because replacement text is missing or source is stale.
2. `placement_move apply` with `capacity_resolution_transaction_id="capacity_free_1"`.

Assert:

- capacity transaction blocks;
- dependent apply is not previewed/applied;
- dependent apply result reason is `capacity_resolution_not_satisfied` or equivalent;
- memory tool is not called for the dependent add/move.

Run:

```bash
.venv/bin/python -m pytest tests/test_runner_steps.py::test_dependent_memory_apply_waits_for_capacity_resolution_success -q
```

Expected RED if current dry-run preview allows both. GREEN by adding mechanical dependency validation after transaction execution results are known.

---

## Task 7: GREEN dependency validation without semantic choice

**Objective:** Execute ordered Planner transactions while respecting capacity dependencies.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`

**Implementation guidance:**

In the execution loop or immediately before executing each transaction:

- maintain a map of prior transaction id -> outcome;
- if a transaction has `capacity_resolution_transaction_id`:
  - require a prior transaction with that id;
  - require prior outcome in `{applied, preview}` for dry-run or `applied` for mutating run;
  - otherwise block dependent transaction with `capacity_resolution_not_satisfied`;
- this is mechanical validation only. Do not decide new compaction targets.

Run:

```bash
.venv/bin/python -m pytest tests/test_runner_steps.py::test_dependent_memory_apply_waits_for_capacity_resolution_success -q
```

Expected GREEN.

---

## Task 8: RED/GREEN memory_to_skill actionability for capacity planning

**Objective:** Prevent the Planner from outputting broken `memory_to_skill apply` for capacity recovery.

**Files:**
- Modify: `tests/test_runner_steps.py`
- Modify if needed: `hermes_self_improvement/knowledge_transactions.py`
- Modify if needed: `hermes_self_improvement/prompts.py`

**Test outline:**

Fake Planner emits capacity `memory_to_skill apply` with:

- `capacity_resolution_transaction_id`
- exact source text
- target skill
- missing `editor_task`

Assert it becomes `defer` or `block` with a clear reason before Editor execution, and dependent memory apply does not run.

Then add a positive test where `editor_task` exists and dry-run previews skill patch before dependent memory apply.

Run:

```bash
.venv/bin/python -m pytest tests/test_runner_steps.py::test_capacity_memory_to_skill_requires_editor_task_before_dependent_apply tests/test_runner_steps.py::test_capacity_memory_to_skill_with_editor_task_can_satisfy_dependent_apply -q
```

Expected GREEN after prompt/normalization/executor adjustment.

---

## Task 9: Compact reporting for capacity-aware planning

**Objective:** Let operations reports distinguish capacity-aware planning from reactive failure.

**Files:**
- Modify: `tests/test_plugin_tools.py`
- Modify: `hermes_self_improvement/tool_handlers.py`

Add compact counts, without memory text:

- `capacity_pressure_seen`
- `capacity_aware_applies`
- `capacity_dependencies_satisfied`
- `capacity_dependencies_blocked`
- `capacity_reactive_failures`

Keep existing fields.

Run:

```bash
.venv/bin/python -m pytest tests/test_plugin_tools.py::test_compact_improve_tool_result_reports_capacity_aware_planning_without_text -q
```

---

## Task 10: Verification and dogfood

Run focused tests:

```bash
.venv/bin/python -m pytest tests/test_skill_planner.py tests/test_runner_steps.py tests/test_plugin_tools.py -q
```

Run full verification:

```bash
.venv/bin/python -m py_compile __init__.py hermes_self_improvement/*.py
.venv/bin/python -m pytest tests -q
git diff --check
```

Run source-directed dry-run from the current relevant source artifact:

```bash
.venv/bin/python - <<'PY'
import json
from hermes_self_improvement.cli import load_config, run_improve
config = load_config()
result = run_improve(
    config=config,
    dry_run=True,
    capacity_followups_from_run='/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260607T100846Z.json',
)
print(json.dumps({
    'artifact_path': result.get('artifact_path'),
    'dry_run': result.get('dry_run'),
    'target_changed': result.get('target_changed'),
    'action_summary': result.get('action_summary'),
    'editor_execution': result.get('step_decisions', {}).get('editor_validation', {}).get('execution'),
}, ensure_ascii=False, indent=2))
PY
```

Inspect saved artifact for:

- `semantic_override_count=0`
- no route leaks
- capacity facts visible in planner digest
- capacity-aware dependency fields visible when used
- dependent applies not executed if capacity recovery fails
- if Planner chooses skip/defer/block because capacity pressure is not worth it, report that as a valid semantic outcome

---

## Task 11: Plan/index update and commit

Update:

- `.hermes/plans/2026-06-07-planner-capacity-aware-transaction-planning.md`
- `.hermes/plans/README.md`

Record:

- focused/full test results
- dry-run artifact path
- whether Planner saw capacity facts before apply
- whether capacity dependencies were satisfied/blocked
- whether mutating run is ready

Commit:

```bash
git add \
  .hermes/plans/2026-06-07-planner-capacity-aware-transaction-planning.md \
  .hermes/plans/README.md \
  hermes_self_improvement/planner_runtime.py \
  hermes_self_improvement/prompts.py \
  hermes_self_improvement/knowledge_transactions.py \
  hermes_self_improvement/runner_steps.py \
  hermes_self_improvement/tool_handlers.py \
  tests/test_skill_planner.py \
  tests/test_runner_steps.py \
  tests/test_plugin_tools.py

git commit -m "fix: make planner capacity-aware before memory apply"
git push
```

---

## Dogfood result

Source-directed dry-run after implementation:

- Artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260607T141912Z.json`
- Source follow-up artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260607T100846Z.json`
- `dry_run=true`, `target_changed=false`
- action summary: `apply=3 / defer=6 / skip=64 / block=9`
- editor execution: `semantic_override_count=0`, `planner_apply_count=3`, `executed_apply_count=0`, `mechanical_block_count=3`; dry-run previews only
- planner capacity: `builtin_user pressure=ok used=0 limit=2200 remaining=2200`; `builtin_memory pressure=ok used=1424 limit=2200 remaining=776`
- planned memory write costs: `20`, omitted `4`
- compact memory capacity counts: `capacity_pressure_seen=0`, `capacity_aware_applies=0`, `capacity_dependencies_satisfied=0`, `capacity_dependencies_blocked=0`, `capacity_reactive_failures=0`
- route leaks: none found for `suggested_route`, `route_reasons`, `likely_`, `allowed_recommendations`, `default_defer_by_route`, `unhandled_by_route`, or `by_suggested_route`
- capacity followups: `blocked_count=3`; two unresolved raw placement retries still blocked with `planner_task_capacity_followup_requires_explicit_resolution`; seven `memory_to_skill_missing_editor_task` blocks remain across Planner output

Decision: the capacity-aware planning slice is complete and safe. The dry-run shows Planner now sees bounded capacity facts and write-cost counts before apply. It also shows remaining actionability debt: `memory_to_skill` applies need concrete editor tasks before they can satisfy capacity or cleanup plans. Mutating run is **not ready** from this slice alone.

---

## Mutating run gate

Do not run mutating `improve` until dry-run shows one of these safe outcomes:

1. Planner emits capacity recovery then dependent apply, and dry-run proves exact text/actionability/dependency ordering.
2. Planner decides the apply is not worth capacity pressure and skips/blocks/defer with a semantic reason.
3. Planner emits an actionable `memory_to_skill` with concrete editor task and no source removal before skill patch success.

Before mutating:

```bash
shasum -a 256 ~/.hermes/memories/USER.md ~/.hermes/memories/MEMORY.md
hermes self-improvement improve --capacity-followups-from-run /Users/ryo.nakae/.hermes/self-improvement/runs/run-20260607T100846Z.json --json
shasum -a 256 ~/.hermes/memories/USER.md ~/.hermes/memories/MEMORY.md
```

After mutation, inspect artifact and report actual `memory_changes` / `skill_changes`, not just Planner `apply`.
