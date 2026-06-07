# Planner-owned Knowledge Decision and Editor Execution Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task. This is a planning artifact only; do not implement production code until Ryo explicitly asks to proceed.

**Goal:** Make the Planner's USER/MEMORY/Skill and capacity decisions match a human Hermes reviewer, then make the Knowledge Editor execute the Planner's concrete plan through Hermes official tools without independent semantic override.

**Architecture:** Keep the product model as one Planner and one Knowledge Editor. The Planner owns all semantic decisions: store placement, whole move vs split, memory rewrite/compaction, duplicate cleanup, memory-to-skill routing, and whether capacity pressure makes a change not worth doing. The Knowledge Editor remains LLM-based because it composes exact skill patches and memory edits and calls Hermes built-in tools, but it may only execute, validate mechanical preconditions, and report execution status. Program code provides neutral facts, inventory, capacity state, skill coverage, and hard guards; it must not choose semantic routes.

**Tech Stack:** Python, pytest, Hermes official `memory` and `skill_manage` tool paths, existing canonical `knowledge_transactions`, `planner_runtime`, `prompts`, `runner_steps`, `editor_backend_memory`, `editor_backend_skill`, compact tool/report surfaces, and runtime artifacts under `${HERMES_HOME:-~/.hermes}/self-improvement/`.

---

## Source observations

- Repo: `/Users/ryo.nakae/.hermes/plugins/hermes-self-improvement`
- Branch state before this plan: `main...origin/main [ahead 1]`, worktree clean.
- Relevant cron artifact:
  - `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260603T190347Z.json`
  - cron summary: `apply=3 / defer=6 / skip=50 / block=8`
  - actual mutations: `skill=0`, `memory=0`
  - planner `apply` rows: 3 placement moves, all blocked at execution.
  - block reason for those applies: `memory_provider_tool_unavailable:...hindsight_retain:active_provider_missing` even though the intended target was built-in memory.
- Recent dry-runs showed variance:
  - `run-20260603T005436Z.json`: `apply=7 / defer=22 / skip=84`
  - `run-20260603T012442Z.json`: `apply=7 / defer=21 / skip=65`
  - `run-20260603T190347Z.json`: `apply=3 / defer=6 / skip=50 / block=8`
- Human/Hermes review of the latest artifact found:
  - Planner vs human on decisive non-skill rows: roughly 13/17 aligned, 1 partial, 3 disagree.
  - Disagreements are all Planner `apply placement_move` rows where whole-entry USER→MEMORY moves are too coarse.
  - Editor/execution vs human looked closer only because unsafe/invalid plans were blocked mechanically; this is not acceptable as the main semantic safety mechanism.

## Problem statement

The current system is safe mostly because execution blocks or capacity/provider paths fail, not because the Planner consistently produces human-equivalent, executable decisions.

Specific problems:

1. Planner sometimes selects whole-entry `placement_move` for mixed USER entries that should be `placement_split`, `memory_rewrite`, `keep_same_topic_different_store`, or `defer`.
2. Planner does not always emit a complete executable `editor_task` / capacity plan for `memory_to_skill`, `placement_split`, or capacity-sensitive memory changes.
3. Editor/execution can appear to veto Planner decisions, but the block reason is often mechanical or misrouted rather than semantic.
4. Built-in memory operations can leak into external-provider fallback wording (`hindsight_retain:active_provider_missing`), making block reasons misleading and hiding the real contract failure.
5. Report/dogfood metrics do not yet separate:
   - Planner semantic disagreement with human fixture
   - Planner underspecified task
   - Editor mechanical block
   - Editor semantic override
   - actual successful execution

## Desired product contract

### Planner owns semantic decision-making

The Planner must decide:

- USER vs MEMORY vs Skill vs none.
- Whole-entry move vs split vs rewrite vs keep.
- Whether a source entry is mixed.
- Whether capacity pressure makes the change worth compaction or should become defer/skip.
- Which exact existing memory entry to compact/replace/remove when capacity recovery is appropriate.
- Whether procedural content belongs in an existing editable skill, and the exact skill-side edit intent.
- Whether same-topic USER/MEMORY entries should both remain because they encode different semantics.

### Editor executes, does not re-decide

The Knowledge Editor must:

- Use Planner's decision and task as the source of truth.
- Compose exact tool calls through official Hermes tools.
- Preserve add-before-remove and skill-before-memory-removal ordering.
- Stop only on mechanical guard failures:
  - exact `old_text` mismatch
  - missing required fields
  - protected/non-editable skill
  - dry-run
  - official tool unavailable for the requested built-in/external target
  - capacity still unavailable after Planner-specified compaction
- Never convert an `apply` into a different semantic action.
- Never choose a different memory entry to remove/compact than Planner specified.
- If the Planner task is semantically underspecified, return `planner_task_invalid` / `planner_task_missing_exact_text`, not an alternate semantic decision.

### Program code supplies facts and guards only

Program code may:

- Read current memory inventory through official/current-entry paths.
- Read local editable skill inventory and bounded excerpts.
- Record capacity facts, current entries, usage, and exact old text.
- Validate target scope and exact text.
- Normalize canonical transaction shape.
- Summarize metrics.

Program code must not:

- Reintroduce `suggested_route`, `likely_*`, `route_reasons`, `allowed_recommendations`, or route-priority semantic labels.
- Pick canonical USER/MEMORY store by heuristic.
- Pick which memory entry to compact/remove by token overlap or store label.
- Treat external provider fallback as the default path for built-in memory moves.
- Add approval queues, new apply modes, or extra roles.

---

## Completion criteria

This plan is complete only when all are true:

- A deterministic golden fixture captures recent Ryo memory examples and expected human/Hermes decisions.
- Planner output for the fixture matches the human/Hermes expected decision class for the critical rows.
- Planner `apply` transactions require executable edit plans:
  - exact source identity/text
  - destination content or replacement content
  - explicit capacity plan when capacity is relevant
  - explicit skill patch task for `memory_to_skill`
- Mixed entries without exact split text become `defer`, not whole-entry moves.
- Editor records `semantic_override_count=0` and never changes Planner's semantic decision.
- Editor block reasons are mechanical and specific; built-in memory operations do not report missing external provider unless the Planner explicitly targeted external memory.
- Capacity recovery is Planner-led: Planner chooses compact/replace/remove/skill/defer/skip; executor only performs specified official tool calls.
- Reports expose Planner-vs-golden, editor override, blocked apply reasons, and actual mutations distinctly.
- Full tests pass, dry-run dogfood is inspected, and mutating dogfood is run only if the dry-run emits bounded exact operations and Ryo approves.

---

## Task 1: Add a human/Hermes golden fixture for planner semantic decisions

**Objective:** Make “Planner should decide like Hermes” testable before changing prompts or execution.

**Files:**
- Create or modify: `tests/test_planner_semantic_goldens.py`
- Modify if fixtures are centralized: `tests/fixtures/` or existing planner fixture helpers
- Read: `hermes_self_improvement/planner_runtime.py`
- Read: `hermes_self_improvement/prompts.py`
- Read: `tests/test_skill_planner.py`

**Step 1: Create fixture rows from the latest cron artifact**

Represent the critical entries from `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260603T190347Z.json` as deterministic memory inventory / placement candidates. Include at least:

```python
GOLDEN_MEMORY_CASES = [
    {
        "case_id": "google_workspace_policy",
        "current_store": "user",
        "old_text": "Google Workspace は read-only 認可優先。Hermes のデフォルト skill / built-in files は編集しない方針。",
        "expected_decision_class": {"defer", "placement_split", "memory_rewrite", "keep_same_topic_different_store"},
        "forbidden": {"whole_entry_placement_move"},
        "reason": "mixed user/workflow policy; whole USER->MEMORY move is too coarse",
    },
    {
        "case_id": "development_delivery_workflow",
        "current_store": "user",
        "old_text": "開発ではcommit/push可、外部可視前は停止。計画は`.hermes/plans/`+index更新、完了/未完了明示。関連懸念は別proof化。self-improvement計画はartifact・fixture重視。",
        "expected_decision_class": {"placement_split", "defer"},
        "forbidden": {"whole_entry_placement_move"},
        "reason": "authorization/preference plus operational convention are mixed",
    },
    {
        "case_id": "status_check_response_preference",
        "current_store": "user",
        "old_text": "Ryoの状況確認依頼ではplan/commit/repo/runtime/cron/runを確認し、完了/残件を答える。",
        "expected_decision_class": {"keep_user", "skip"},
        "forbidden": {"whole_entry_placement_move"},
        "reason": "response/reporting preference belongs in USER",
    },
    {
        "case_id": "self_improvement_architecture_fact",
        "current_store": "user",
        "old_text": "self-improvement設計は1 Planner+1 Knowledge Editor、skill/USER/MEMORY横断。semantic判断・容量時の統合/移動判断はLLM委任、programは事実提示/公式tool実行/hard guardのみ。dogfood報告は実変更/blocked/partialを分ける。",
        "expected_decision_class": {"memory_rewrite", "placement_move", "placement_split"},
        "reason": "mostly project architecture/current operational fact, but may need compact rewrite",
    },
]
```

Do not require exact wording for every LLM rationale. Test decision class and required/forbidden transaction shape.

**Step 2: Add assertion helpers**

Add helpers that classify normalized transactions into coarse human-comparable classes:

```python
def classify_transaction(tx: dict) -> str:
    if tx.get("transaction_kind") == "placement_move" and tx.get("operation") == "move":
        return "whole_entry_placement_move"
    if tx.get("transaction_kind") == "placement_split":
        return "placement_split"
    if tx.get("transaction_kind") == "memory_rewrite":
        return "memory_rewrite"
    if tx.get("transaction_kind") == "keep_same_topic_different_store":
        return "keep_same_topic_different_store"
    if tx.get("decision") in {"skip", "defer", "block"}:
        return tx.get("reason") or tx.get("decision")
    return tx.get("transaction_kind") or tx.get("decision") or "unknown"
```

Prefer project naming/style if existing helpers exist.

**Step 3: RED test**

Test current Planner normalization or fake planner payload classification if live LLM calls are not used in tests. Expected RED: current prompt/normalization allows forbidden whole moves for at least the status-check or development-delivery case.

Run:

```bash
.venv/bin/python -m pytest tests/test_planner_semantic_goldens.py -q
```

Expected before implementation: at least one fixture fails or is marked as current known gap.

---

## Task 2: Strengthen Planner contract for mixed entries and executable apply plans

**Objective:** Make the Planner output explicit, executable semantic plans rather than coarse `placement_move` decisions.

**Files:**
- Modify: `hermes_self_improvement/prompts.py`
- Modify if schema/normalization needs fields: `hermes_self_improvement/knowledge_transactions.py`
- Modify: `hermes_self_improvement/planner_runtime.py`
- Tests: `tests/test_skill_planner.py`, `tests/test_planner_semantic_goldens.py`

**Step 1: Update Planner prompt kernel**

Add or strengthen instructions:

```text
Planner is the final semantic decision maker.
Do not emit whole-entry placement_move for mixed entries.
If an entry contains both user preference/policy and operational/runtime facts, use placement_split only when exact source_replacement and destination_content are available; otherwise defer.
For apply, emit an executable editor_task/capacity_plan with exact old_text and exact replacement/add/remove text.
For memory_to_skill, emit target_skill plus concrete skill patch intent. If no concrete skill patch task exists, defer; do not emit apply.
For capacity pressure, decide compact/replace/remove/skill/defer/skip from current entries. Program code will not choose entries for you.
Same topic across USER and MEMORY is not duplicate when USER stores preference and MEMORY stores runtime/environment fact.
```

**Step 2: Add transaction fields without new lanes**

Allow canonical transactions to carry optional fields:

```python
"semantic_basis": "user_preference|environment_fact|mixed|procedure|duplicate|capacity_resolution",
"mixed_entry": True | False,
"whole_entry_move_allowed": True | False,
"editor_task": {...},
"capacity_plan": {
    "required": True | False,
    "target_store": "builtin_user|builtin_memory",
    "free_chars_needed": int | None,
    "actions": [...],
}
```

These are metadata on canonical transactions, not new decision lanes. If code does not need all fields immediately, keep them in artifacts/prompt tests first.

**Step 3: Normalize underspecified apply to block/defer before editor**

For final planner transactions:

- `placement_split apply` requires exact `source_old_text`, `destination_content`, and `source_replacement`.
- `memory_rewrite apply` requires exact `source_old_text` and `replacement_content` / `content`.
- `duplicate_cleanup apply` requires exact source identity and exact remove/replace operation.
- `memory_to_skill apply` requires target skill plus concrete `editor_task` / `skill_task`.
- `placement_move apply` requires `whole_entry_move_allowed=true` or equivalent exact evidence that the whole entry belongs in the destination.

If missing, convert to `block` or `defer` with specific reason such as:

```text
planner_task_missing_exact_split_text
planner_task_missing_editor_task
planner_task_whole_move_not_allowed_for_mixed_entry
```

**Step 4: Verify**

Run:

```bash
.venv/bin/python -m pytest tests/test_skill_planner.py tests/test_planner_semantic_goldens.py -q
```

Expected: golden fixture no longer allows forbidden whole moves for the critical cases.

---

## Task 3: Make memory capacity an input to Planner, not an editor/runtime surprise

**Objective:** Ensure Planner can decide compaction, replacement, memory-to-skill, defer, or skip before Editor hits capacity errors.

**Files:**
- Modify: `hermes_self_improvement/planner_runtime.py`
- Modify: `hermes_self_improvement/prompts.py`
- Modify if capacity helpers exist: `hermes_self_improvement/runner_steps.py`
- Tests: `tests/test_memory_capacity_fallback.py`, `tests/test_skill_planner.py`, `tests/test_memory_inventory_planner.py`

**Step 1: Add current capacity facts to planner digest**

Planner digest should include bounded facts for each built-in store:

```json
"built_in_memory_capacity": {
  "builtin_user": {
    "usage": "1329/1375",
    "remaining_chars_estimate": 46,
    "entries": [{"entry_id": "...", "old_text": "...", "chars": 123}]
  },
  "builtin_memory": {
    "usage": "2146/2200",
    "remaining_chars_estimate": 54,
    "entries": [{"entry_id": "...", "old_text": "...", "chars": 180}]
  }
}
```

If exact usage is only available from tool errors, include approximate char counts from current entries and label them estimates.

**Step 2: Render capacity as facts**

Prompt section:

```text
## Built-in memory capacity facts
These are facts, not recommendations. Planner must decide whether a proposed add/move is worth the capacity cost. If capacity is tight, emit canonical memory_rewrite / duplicate_cleanup / memory_to_skill / placement_split / defer / skip transactions with exact text. Do not expect Editor or program code to choose compaction targets.
```

**Step 3: Add tests for capacity-aware plan**

Fixture:

- `builtin_memory` has low remaining capacity.
- Candidate USER entry is mixed and long.
- Expected Planner class: `placement_split` or `defer`, not blind `placement_move`.

Also test a clear compactable destination entry:

- Planner can emit `memory_rewrite` for exact existing memory entry followed by `placement_move` only when both exact operations are present.

**Step 4: Verify**

```bash
.venv/bin/python -m pytest tests/test_memory_capacity_fallback.py tests/test_skill_planner.py tests/test_memory_inventory_planner.py -q
```

Expected: capacity facts appear in prompt; no route labels; underspecified capacity resolution fails closed.

---

## Task 4: Enforce Editor as LLM executor, not semantic reviewer

**Objective:** Keep Editor LLM-based for patch composition and official tool calls, while preventing semantic overrides.

**Files:**
- Modify: `hermes_self_improvement/editor.py`
- Modify: `hermes_self_improvement/editor_memory.py`
- Modify: `hermes_self_improvement/editor_skill.py`
- Modify: `hermes_self_improvement/editor_backend_memory.py`
- Modify: `hermes_self_improvement/editor_backend_skill.py`
- Tests: `tests/test_memory_to_skill_migration.py`, `tests/test_memory_capacity_fallback.py`, `tests/test_runner_steps.py`

**Step 1: Add editor contract in prompt/context**

Editor prompt/context should say:

```text
You are the Knowledge Editor executor. Do not reconsider Planner's semantic decision. Execute the specified canonical transaction through the allowed Hermes tools. If the task is underspecified or unsafe, return execution_status=blocked with a mechanical reason. Do not choose a different target store, different skill, or different memory entry.
```

**Step 2: Record semantic override count**

Add accounting:

```json
"editor_validation": {
  "semantic_override_count": 0,
  "planner_task_invalid_count": N,
  "mechanical_block_count": N
}
```

If an editor response attempts to change decision/target semantics, normalize it to blocked:

```text
editor_semantic_override_forbidden
```

**Step 3: Tests**

Add fake editor outputs that attempt to:

- Move a USER item to MEMORY when Planner said `skip`.
- Remove a different memory entry than Planner's `capacity_plan.actions[0].old_text`.
- Patch a different skill than Planner's `target_skill`.

Expected:

- No official tool calls.
- Transaction blocked with `editor_semantic_override_forbidden` or `planner_task_invalid`.
- `semantic_override_count` increments only as diagnostic; the semantic decision is not changed.

**Step 4: Verify**

```bash
.venv/bin/python -m pytest tests/test_memory_to_skill_migration.py tests/test_memory_capacity_fallback.py tests/test_runner_steps.py -q
```

---

## Task 5: Fix built-in memory execution path and block reasons

**Objective:** Built-in USER/MEMORY operations must use the built-in memory tool path and must not report missing external provider unless the target is explicitly external memory.

**Files:**
- Modify: `hermes_self_improvement/editor_backend_memory.py`
- Modify: `hermes_self_improvement/runner_steps.py`
- Modify: `hermes_self_improvement/mutation_policy.py` if target routing is there
- Tests: `tests/test_builtin_memory_tool_semantics.py`, `tests/test_memory_capacity_fallback.py`, `tests/test_runner_steps.py`

**Step 1: Add regression for latest block reason**

Fixture based on latest cron:

```python
def test_builtin_memory_move_does_not_route_to_external_provider_when_memory_store_available(...):
    tx = {
        "decision": "apply",
        "transaction_kind": "placement_move",
        "source_store": "builtin_user",
        "target_store": "builtin_memory",
        "source_old_text": "...",
        "content": "...",
    }
    # fake built-in memory tool unavailable/capacity paths separately
    # assert no hindsight_retain/external provider tool is requested
```

Expected block reasons:

- `memory_capacity_exceeded`
- `builtin_memory_tool_unavailable`
- `planner_task_missing_exact_text`

Forbidden for built-in targets:

- `hindsight_retain:active_provider_missing`
- `external_provider_missing`

**Step 2: Route by target store**

Ensure:

- `builtin_user` / `user` -> official memory tool target `user`
- `builtin_memory` / `memory` -> official memory tool target `memory`
- `external_memory` -> active external provider tool if configured

Do not fallback from built-in to external provider automatically during placement moves. If built-in target is full, Planner must decide whether to compact or route to skill/external in a later explicit transaction.

**Step 3: Verify**

```bash
.venv/bin/python -m pytest tests/test_builtin_memory_tool_semantics.py tests/test_memory_capacity_fallback.py tests/test_runner_steps.py -q
```

---

## Task 6: Add Planner-vs-human and Editor-vs-Planner reporting metrics

**Objective:** Make daily dogfood answer the question Ryo asked: where is the disagreement?

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/tool_handlers.py`
- Modify: `hermes_self_improvement/runner_steps.py`
- Tests: `tests/test_plugin_tools.py`, `tests/test_report_improve_connection.py`

**Step 1: Add compact metrics**

Add bounded fields:

```json
"planner_quality": {
  "golden_cases_evaluated": 4,
  "golden_match": 3,
  "golden_partial": 1,
  "golden_disagree": 0,
  "whole_move_for_mixed_entry": 0,
  "apply_missing_editor_task": 0
},
"editor_execution": {
  "semantic_override_count": 0,
  "planner_apply_count": 3,
  "executed_apply_count": 0,
  "mechanical_block_count": 3,
  "blocked_apply_reasons": {"memory_capacity_exceeded": 3}
}
```

Golden fixture metrics may be test-only or dogfood-only initially; do not expose full memory text in Slack/tool payload.

**Step 2: CLI/report wording**

Add lines similar to:

```text
Planner quality: golden match 3 / partial 1 / disagree 0; mixed whole-move 0
Editor execution: semantic override 0; planner apply 3, executed 0, mechanical blocked 3
Blocked apply reasons: memory_capacity_exceeded 3
```

**Step 3: Tests**

Assert compact tool output includes counts, not full memory entries.

Run:

```bash
.venv/bin/python -m pytest tests/test_plugin_tools.py tests/test_report_improve_connection.py -q
```

---

## Task 7: Dogfood protocol before any mutating run

**Objective:** Prove Planner has improved before enabling execution changes to mutate real memory.

**Step 1: Preflight**

```bash
git status --short
hermes self-improvement status --json > /tmp/hermes-si-status-planner-owned.json
shasum -a 256 ~/.hermes/memories/USER.md ~/.hermes/memories/MEMORY.md > /tmp/hermes-si-memory-hashes-before.txt
```

Expected:

- worktree clean except intended code/docs
- runtime initialized
- prompt overlays ready

**Step 2: Dry-run**

```bash
hermes self-improvement improve --dry-run --json > /tmp/hermes-si-planner-owned-dry-run.json
```

Inspect mechanically:

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path
p = Path('/tmp/hermes-si-planner-owned-dry-run.json')
data = json.loads(p.read_text())
text = json.dumps(data, ensure_ascii=False)
transactions = data.get('knowledge_transactions') or []
print(json.dumps({
    'run_id': data.get('run_id'),
    'action_summary': data.get('action_summary'),
    'target_changed': data.get('target_changed'),
    'planner_quality': data.get('steps', {}).get('planner_quality') or data.get('planner_quality'),
    'editor_execution': data.get('steps', {}).get('editor_execution') or data.get('editor_execution'),
    'whole_moves': [t.get('source_id') for t in transactions if t.get('transaction_kind') == 'placement_move' and t.get('decision') == 'apply'],
    'missing_editor_task_applies': [t.get('transaction_id') for t in transactions if t.get('decision') == 'apply' and t.get('transaction_kind') == 'memory_to_skill' and not t.get('editor_task') and not t.get('skill_task')],
    'route_leaks': [n for n in ['suggested_route','route_reasons','likely_','allowed_recommendations','default_defer_by_route','unhandled_by_route'] if n in text],
}, ensure_ascii=False, indent=2))
PY
```

Pass criteria:

- `target_changed=false`
- route leaks empty
- no `apply memory_to_skill` without concrete editor task
- no whole-entry `placement_move apply` for known mixed USER entries
- editor semantic override count is zero
- Planner either emits bounded exact operations or clear defer/skip/block reasons

**Step 3: Mutating run only after Ryo approval**

Do not run mutation automatically from this plan. If Ryo approves after reviewing the dry-run artifact, run:

```bash
hermes self-improvement improve --json > /tmp/hermes-si-planner-owned-mutation.json
shasum -a 256 ~/.hermes/memories/USER.md ~/.hermes/memories/MEMORY.md > /tmp/hermes-si-memory-hashes-after.txt
diff -u /tmp/hermes-si-memory-hashes-before.txt /tmp/hermes-si-memory-hashes-after.txt || true
```

Pass criteria:

- Any memory/skill change is listed in actual results.
- No source memory removal without successful destination add or skill patch.
- No editor semantic override.
- Blocked applies have mechanical reasons only.

---

## Task 8: Full validation and docs/index update

**Objective:** Close the implementation with tests, artifact evidence, and plan index state.

**Files:**
- Modify: `.hermes/plans/README.md`
- Modify: this plan file
- Modify if product contract changed: `skills/operations/SKILL.md`
- Modify if user-facing docs changed: `README.md`

**Step 1: Full validation**

```bash
.venv/bin/python -m py_compile __init__.py hermes_self_improvement/*.py
.venv/bin/python -m pytest tests -q
git diff --check
hermes self-improvement status --json
```

Expected:

- py_compile ok
- full pytest passes
- diff check ok
- status readable and initialized

**Step 2: Update completion note**

Add to this plan:

- final commit SHA
- tests run
- dry-run artifact path
- mutating artifact path if approved/run
- planner quality counts
- editor semantic override count
- blocked apply reasons
- memory hash before/after outcome

**Step 3: Update plan index**

At `.hermes/plans/README.md` top:

- mark this plan as active while pending
- after implementation, move it to latest completed follow-up
- explicitly state whether `2026-06-02-llm-led-memory-capacity-recovery.md` is superseded, absorbed, or still active only for lower-level capacity plumbing

**Step 4: Commit**

```bash
git status --short
git add hermes_self_improvement/prompts.py hermes_self_improvement/planner_runtime.py hermes_self_improvement/knowledge_transactions.py hermes_self_improvement/runner_steps.py hermes_self_improvement/editor.py hermes_self_improvement/editor_memory.py hermes_self_improvement/editor_skill.py hermes_self_improvement/editor_backend_memory.py hermes_self_improvement/editor_backend_skill.py hermes_self_improvement/cli.py hermes_self_improvement/tool_handlers.py tests/test_planner_semantic_goldens.py tests/test_skill_planner.py tests/test_memory_capacity_fallback.py tests/test_memory_inventory_planner.py tests/test_memory_to_skill_migration.py tests/test_builtin_memory_tool_semantics.py tests/test_runner_steps.py tests/test_plugin_tools.py tests/test_report_improve_connection.py .hermes/plans/README.md .hermes/plans/2026-06-07-planner-owned-knowledge-decision-and-editor-execution.md
git commit -m "fix: make planner own knowledge decisions"
```

Do not push unless Ryo asks.

---

## Relationship to existing plans

- `2026-06-02-llm-led-memory-capacity-recovery.md` is implemented through capacity follow-up plumbing. This new plan supersedes it at the product-contract layer: capacity is not merely a follow-up artifact; it is a Planner-owned semantic decision with exact compaction/rewrite/skill/defer plan.
- `2026-06-01-llm-semantic-knowledge-review.md` remains the base semantic transaction vocabulary plan.
- `2026-06-02-semantic-review-actionability-followup.md` remains valid for fail-closed underspecified `memory_to_skill` / `placement_split`, but this plan raises the bar: Planner should avoid emitting those underspecified applies in the first place.
- `2026-06-02-placement-move-canonical-decision-followup.md` remains valid for canonical transaction shape. This plan focuses on whether the canonical transaction is the right semantic decision.

## Recommended next-session start

1. Open `run-20260603T190347Z.json` and this plan.
2. Start with Task 1 only: write the golden fixture and make the current disagreement visible.
3. Do not fix the built-in memory provider/block path before Planner golden behavior is improved; otherwise bad whole-entry moves may start executing.
4. After Planner golden behavior passes, then fix Editor execution/block reasons.


---

## Implementation status — 2026-06-07 initial slice

Implemented in the first coding slice:

- Task 1: deterministic planner semantic golden fixture added in `tests/test_planner_semantic_goldens.py`.
- Task 2: planner/transaction contract now fails closed for explicit mixed-entry whole moves and underspecified memory rewrites; planner prompt states Planner owns semantic decisions and apply plans must be executable.
- Task 3: planner digest now exposes `built_in_memory_capacity` facts and planner prompt renders them as facts, not recommendations.
- Task 4/6 initial slice: Knowledge Editor prompt now treats Planner semantic decision as source of truth; run output includes `editor_validation.execution` with semantic override count, planner apply count, executed apply count, mechanical blocks, and blocked apply reasons.
- Task 5 verification: existing memory-to-skill execution tests confirm built-in source removal uses the official `memory` tool path (`action=remove`, target `memory`) after skill patch success.

Verification run from repo worktree:

```bash
.venv/bin/python -m py_compile __init__.py hermes_self_improvement/*.py
.venv/bin/python -m pytest tests -q
git diff --check
```

Result: `1009 passed, 2 skipped`.

Dogfood dry-run:

- Managed `self_improvement_improve(dry_run=True)` artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260607T013003Z.json`; `target_changed=false`; apply 5 / defer 26 / skip 90 / block 4. This appears to have used the host-managed/stale plugin runtime because `editor_validation.execution` was absent.
- Source-directed repo run artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260607T013035Z.json`; `target_changed=false`; apply 8 / defer 0 / skip 49 / block 0; `editor_validation.execution.semantic_override_count=0`, `planner_apply_count=8`, `executed_apply_count=0`, `mechanical_block_count=8`, `blocked_apply_reasons={"dry_run_would_execute_knowledge_transaction": 8}`; whole-entry placement moves `[]`; known mixed whole moves `[]`; memory-to-skill applies missing editor task `[]`; route leaks `[]`.

No mutating self-improvement run has been executed from this implementation slice. Mutating run still requires Ryo approval after reviewing the dry-run artifact.
