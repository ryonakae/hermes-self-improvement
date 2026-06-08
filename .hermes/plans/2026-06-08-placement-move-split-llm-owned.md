# Placement Move/Split LLM-Owned Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Make `USER.md` / `MEMORY.md` placement cleanup treat both whole-entry moves and mixed-entry splits as Planner-owned semantic decisions, with the executor limited to exact-text, capacity, and atomicity guards.

**Architecture:** Keep the existing one Planner + one Knowledge Editor flow. Extend the canonical `knowledge_transactions` contract rather than adding a new lane, approval queue, or second apply phase. `placement_move` remains `source entry 1 -> target entry 1`; `placement_split` becomes `source entry 1 -> typed fragments[]`, where the LLM supplies every fragment text and target store.

**Tech Stack:** Python, pytest, existing Hermes `memory` / `skill_manage` tool paths, run artifacts under `~/.hermes/self-improvement/runs/`.

**Status:** Implemented through dry-run dogfood on 2026-06-08. Verified with focused related suite `171 passed`, full `pytest -q` → `1028 passed, 2 skipped`, `py_compile`, `git diff --check`, and dry-run `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260608T023405Z.json` (`dry_run=true`, `target_changed=false`, `semantic_override_count=0`, no route leaks, `placement_split` applies carry `fragments[]`). No mutating replay was executed; real memory edits still require explicit approval.

---

## Current finding

The 2026-06-08 mutating cron did not perform `MEMORY.md ↔ USER.md` placement cleanup. It selected one `placement_move`:

```text
Hindsight tuning preference: keep Mac mini responsive; accept Reflect ~30–40s rather than raising CPU/resources aggressively.
```

Planner classified it as `MEMORY.md -> USER.md`, which is semantically right, but the executor blocked because `USER.md` capacity needed explicit resolution.

The current code already has a `placement_split` transaction path, but the live placement flow does not make mixed USER/MEMORY entries actionable enough. The old contract is also too pairwise: `source_replacement` + one `destination_content`. For real memory entries, one source often needs multiple output fragments and sometimes a source removal rather than a source replacement.

## Product contract

### Move

Use `placement_move` when the whole source entry belongs in the other built-in store.

```json
{
  "decision": "apply",
  "transaction_kind": "placement_move",
  "operation": "move",
  "source_store": "builtin_memory",
  "target_store": "builtin_user",
  "source_id": "memory_place_e4613415ff97",
  "source_old_text": "Hindsight tuning preference: keep Mac mini responsive; accept Reflect ~30–40s rather than raising CPU/resources aggressively.",
  "content": "Hindsight tuning preference: keep Mac mini responsive; accept Reflect ~30–40s rather than raising CPU/resources aggressively.",
  "reason": "user performance preference belongs in USER.md"
}
```

### Split

Use `placement_split` when one source entry mixes user preference, environment facts, workflow rules, or skill-worthy procedure.

Canonical shape:

```json
{
  "decision": "apply",
  "transaction_kind": "placement_split",
  "operation": "split",
  "source_store": "builtin_user",
  "source_id": "memory_place_2353f96c4e17",
  "source_old_text": "opencode-go契約済みで極力活用。OpenAI互換はprovider=openai+base_url。Skill編集はprotected保護、localはpatch可。Safehouse注意はagent名でなく環境一般で書く。Gmail observer=~/.hermes/automations/gmail-purchase-observer、cron=~/.hermes/cron/jobs.json。",
  "fragments": [
    {
      "target_store": "builtin_user",
      "text": "opencode-go契約済みで、可能な場面では極力活用したい。"
    },
    {
      "target_store": "builtin_memory",
      "text": "OpenAI互換 provider は provider=openai+base_url。Gmail observer は ~/.hermes/automations/gmail-purchase-observer、cron は ~/.hermes/cron/jobs.json。"
    },
    {
      "target_store": "skill",
      "target_id": "hermes-skill-management",
      "text": "Skill編集は protected 保護、local は patch 可。Safehouse注意は環境一般で書く。"
    }
  ],
  "reason": "mixed user preference, runtime facts, and reusable skill-editing workflow"
}
```

Rules:

- Planner / Knowledge Editor own the semantic split and all fragment text.
- Program code must not infer a different target store, invent fragment text, or decide user-vs-memory semantics.
- Program code may normalize old pairwise fields into `fragments[]` for compatibility.
- Program code must fail closed when fragments are empty, target stores are unsupported, source exact text is stale, capacity cannot be satisfied, or a skill fragment lacks executable `editor_task`.
- `semantic_override_count` must remain `0`.

## Non-goals

- Do not add a new apply stage, approval queue, confidence gate, or separate split lane.
- Do not reintroduce route-derived semantic contracts such as `suggested_route` / `likely_*`.
- Do not edit Hermes core.
- Do not direct-edit `~/.hermes/memories/USER.md` or `MEMORY.md`; use official memory tool paths.
- Do not silently fall back to external memory when built-in capacity fails.

---

## Task 1: Add RED tests for fragment-shaped `placement_split` normalization

**Objective:** Prove the canonical `fragments[]` shape survives normalization and old pairwise split fields remain compatibility-only.

**Files:**
- Modify: `tests/test_knowledge_transactions.py`
- Modify later: `hermes_self_improvement/knowledge_transactions.py`

**Step 1: Add failing tests**

Add tests near the existing `test_normalize_new_semantic_memory_transactions_preserves_source_fields` coverage.

Expected assertions:

- `transaction_kind == "placement_split"`
- `decision == "apply"`
- `operation == "split"`
- `source_store` and `source_old_text` are preserved
- `fragments` remains a list of dicts with `target_store` and `text`
- supported target stores: `builtin_user`, `builtin_memory`, `skill`
- old `destination_store` + `destination_content` normalizes to one fragment for backward compatibility
- missing/empty fragments block with a mechanical reason instead of executing

**Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/test_knowledge_transactions.py -q
```

Expected: new fragment-shape assertions fail before implementation.

---

## Task 2: Normalize `placement_split.fragments[]` without semantic inference

**Objective:** Update canonicalization to preserve LLM-supplied split fragments and validate only shape/safety.

**Files:**
- Modify: `hermes_self_improvement/knowledge_transactions.py`
- Test: `tests/test_knowledge_transactions.py`

**Implementation notes:**

- In `_canonicalize()` when `transaction_kind == "placement_split"`:
  - preserve `fragments` if provided
  - if no `fragments`, convert legacy `{destination_store, destination_content}` into one fragment
  - preserve `source_replacement` for legacy compatibility but do not require it at normalization time
  - set `operation = "split"`
  - set `target_store` to `"unresolved"` or first non-source fragment only for summary compatibility; execution must use `fragments[]`
- In `_validate_apply_transaction()`:
  - block apply if no `source_store` / `source_old_text`
  - block apply if `fragments[]` is empty
  - block apply if a fragment target is outside `{builtin_user,builtin_memory,skill}`
  - block skill fragments unless they carry enough task data to route through the existing skill patch path, or explicitly defer skill fragments in this first slice

**Step 1: Implement minimal normalization**

Keep the helper small, e.g. `_normalize_split_fragments(raw)`.

**Step 2: Run GREEN**

```bash
.venv/bin/python -m pytest tests/test_knowledge_transactions.py -q
```

Expected: test file passes.

---

## Task 3: Strengthen Planner prompt contract for move vs split

**Objective:** Make the live Planner choose `placement_move` for whole-entry moves and `placement_split` for mixed entries, both as LLM-owned semantic decisions.

**Files:**
- Modify: `hermes_self_improvement/prompts.py`
- Test: `tests/test_skill_planner.py` or the current prompt-contract test file that asserts rendered planner guidance

**Prompt contract to add:**

- `placement_move`: use only when the entire exact `source_old_text` belongs in the other built-in store.
- `placement_split`: use when a single entry mixes user preference and environment/runtime/workflow facts.
- For `placement_split apply`, include `fragments[]`; each fragment must contain exact final text and `target_store`.
- Keep the source text semantics complete: every durable part of the old entry must appear in exactly one fragment or be intentionally omitted with reason `drop_temporary_or_redundant_text`.
- If exact split text is not clear, `defer`, not whole-entry move.
- Capacity pressure should be handled by selecting an explicit capacity-resolution transaction or by deferring; the executor must not decide compaction.

**Step 1: Add prompt tests**

Assertions should look for:

- `placement_split`
- `fragments`
- `whole source entry belongs`
- `mixed user preference and environment/runtime facts`
- no `suggested_route` / `likely_` route contract language

**Step 2: Run prompt tests**

```bash
.venv/bin/python -m pytest tests/test_skill_planner.py -q
```

Expected: RED then GREEN after prompt update.

---

## Task 4: Execute fragment-shaped split with preflight and no semantic fallback

**Objective:** Make `execute_knowledge_transaction()` handle `placement_split.fragments[]` safely while preserving the existing dry-run behavior.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Test: `tests/test_runner_steps.py`

**Execution model:**

1. Resolve `source_store` to memory target (`user` or `memory`).
2. Verify `source_old_text` is current before any mutation.
3. Partition fragments:
   - built-in fragments for `builtin_user` / `builtin_memory`
   - skill fragments for `skill`
4. For first implementation, either:
   - block skill fragments with `split_skill_fragment_requires_editor_task`, or
   - convert them to the existing `memory_to_skill` / skill patch execution path only if a concrete `editor_task` is present.
5. Preflight built-in capacity using current memory entries where available. If any add/replace would exceed capacity, block before mutation with `split_capacity_preflight_failed` and include the target store only, not raw text.
6. Apply non-source built-in fragments as memory adds.
7. Replace source with the source-store fragment if present; remove source if no source-store fragment remains.
8. Record all changed memory ids and executed steps.
9. On failure after a destination add, return `outcome="partial"` with rollback hints; do not pretend it was a clean no-op.

**Tests to add:**

- dry-run `placement_split` with fragments returns preview and no mutation
- mutate path blocks stale `source_old_text` before destination add
- mutate path blocks empty fragments
- mutate path blocks unsupported target store
- mutate path applies add-before-source-replace for valid user/memory split
- source-removal variant works when no fragment remains in the source store
- destination-add success + source-replace failure reports `partial` with rollback hints

**Step 1: Add RED tests**

```bash
.venv/bin/python -m pytest tests/test_runner_steps.py -q
```

Expected: fragment executor tests fail.

**Step 2: Implement minimal executor changes**

Keep compatibility with current pairwise `source_replacement` / `destination_content` behavior by converting it to fragments before execution.

**Step 3: Run GREEN**

```bash
.venv/bin/python -m pytest tests/test_runner_steps.py -q
```

Expected: runner tests pass.

---

## Task 5: Report move/split outcomes clearly in artifacts and daily inputs

**Objective:** Make operators see the difference between whole moves, split applies, split blocks, and capacity blocks.

**Files:**
- Modify: `hermes_self_improvement/knowledge_transactions.py`
- Modify: `hermes_self_improvement/markdown_artifacts.py` or current summary renderer
- Modify: `hermes_self_improvement/tool_handlers.py` if compact tool payloads expose transaction counts
- Tests: `tests/test_knowledge_transaction_view.py`, `tests/test_markdown_artifacts.py`, `tests/test_plugin_tools.py` as needed

**Reporting requirements:**

- `Knowledge changes:` includes separate counts for:
  - `placement moves`
  - `placement splits`
  - `memory-to-skill`
- `blocked apply` reasons distinguish:
  - `split_missing_fragments`
  - `split_capacity_preflight_failed`
  - `split_skill_fragment_requires_editor_task`
  - existing capacity/source-stale reasons
- Daily report inputs must not count heuristic recommendations as executed mutations.
- Compact report must not include full memory text.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_knowledge_transaction_view.py tests/test_markdown_artifacts.py tests/test_plugin_tools.py -q
```

Expected: focused report tests pass.

---

## Task 6: Add live-regression fixture from current USER/MEMORY entries

**Objective:** Ensure the current real mixed entries become actionable as split candidates without forcing a mutation during tests.

**Files:**
- Modify: `tests/test_planner_semantic_goldens.py`
- Possibly modify: `tests/test_knowledge_planner_digest.py`

**Fixtures to cover:**

1. Clear move candidate:

```text
Hindsight tuning preference: keep Mac mini responsive; accept Reflect ~30–40s rather than raising CPU/resources aggressively.
```

Expected class: `placement_move` or explicit capacity-aware block/defer if USER capacity is unavailable.

2. Mixed split candidate:

```text
opencode-go契約済みで極力活用。OpenAI互換はprovider=openai+base_url。Skill編集はprotected保護、localはpatch可。Safehouse注意はagent名でなく環境一般で書く。Gmail observer=~/.hermes/automations/gmail-purchase-observer、cron=~/.hermes/cron/jobs.json。
```

Expected class: `placement_split` or `defer` with exact split text missing; forbidden class: whole-entry `placement_move`.

3. Mixed trading candidate:

```text
hermes-trading: 利益目的。read-only→paper/demo→guarded live。open-market tradabilityはOpenD `acctradinginfo_query`(SIMULATE)のみ; quote推測禁止。cron `hermes-trading-cycle` は `no_agent:true` script-only、毎時30分でUS市場open(22:30JST)即runを好む; 確認用one-shot cronは常設1本と区別すれば可。cron側model設定は無関係。role LLMはplugin内 `HermesAuxiliaryRoleLLMClient` で `config.yaml` の `role_llm` 制御。
```

Expected class: `placement_split` or defer; forbidden class: whole-entry `placement_move`.

**Verification:**

```bash
.venv/bin/python -m pytest tests/test_planner_semantic_goldens.py tests/test_knowledge_planner_digest.py -q
```

Expected: semantic golden tests pass without network or live memory mutation.

---

## Task 7: Full validation and dry-run dogfood

**Objective:** Prove the change works against the latest real run without mutating memory first.

**Commands:**

```bash
.venv/bin/python -m py_compile __init__.py hermes_self_improvement/*.py
.venv/bin/python -m pytest tests -q
git diff --check
```

Then run source-directed dry-run against the latest mutating artifact:

```bash
.venv/bin/python - <<'PY'
from hermes_self_improvement.config import load_config
from hermes_self_improvement.runner_steps import run_improve

config = load_config()
result = run_improve(
    config=config,
    dry_run=True,
    capacity_followups_from_run='/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260607T190800Z.json',
)
print(result.get('artifact_path'))
print(result.get('action_summary'))
print(result.get('summary'))
PY
```

Inspect the dry-run artifact for:

- `semantic_override_count == 0`
- no `suggested_route`, `likely_`, `allowed_recommendations`, `by_suggested_route`
- `placement_split` transactions carry `fragments[]` when selected
- mixed entries are not converted into whole-entry `placement_move`
- capacity failures block before mutation
- `target_changed == false`

---

## Task 8: Optional mutating replay only after dry-run review

**Objective:** Keep the first implementation safe by requiring human review of the dry-run artifact before real memory edits.

**Entry criteria:**

- Full tests pass.
- Dry-run artifact has no route leaks.
- All selected `placement_split` transactions contain final fragment text.
- The Hindsight tuning move either has explicit capacity resolution or remains blocked/deferred.
- Ryo approves replay.

**Mutating command pattern:**

Use the repo's current supported replay surface if available. Do not invent a new CLI command. If replay from run is not supported for this transaction shape, run normal `hermes self-improvement improve` only after the dry-run artifact shows the live Planner now emits safe transactions.

**Post-mutation verification:**

- Read `~/.hermes/memories/USER.md` and `~/.hermes/memories/MEMORY.md` through official/current-entry path where possible.
- Confirm no raw duplicate source entry remains after successful split.
- Confirm every fragment landed in the intended store.
- Confirm daily report source summarizes split/move separately.

---

## Completion criteria

This plan is complete when:

- `placement_move` and `placement_split` are both LLM-owned canonical transactions.
- `placement_split` accepts `fragments[]` and does not require program-side semantic inference.
- The executor performs only hard guards and official tool calls.
- Mixed entries can become actionable without whole-entry moves.
- Capacity and stale-source failures block before destructive edits.
- `semantic_override_count` remains zero in dogfood.
- Full tests, `py_compile`, `git diff --check`, and source-directed dry-run pass.

## Implementation order / commit sequence

1. `test: cover fragment-shaped placement split normalization`
2. `feat: normalize placement split fragments`
3. `test: require planner move split contract`
4. `feat: render move split placement guidance`
5. `test: cover placement split fragment execution`
6. `feat: execute placement split fragments safely`
7. `feat: report placement move split outcomes`
8. `test: add current memory placement golden cases`
9. `docs: mark placement move split plan progress`

Do not squash the RED/GREEN slices during implementation; the intermediate commits make rollback and review easier.
