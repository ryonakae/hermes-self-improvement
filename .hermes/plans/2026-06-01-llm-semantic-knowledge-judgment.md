# LLM Semantic Knowledge Judgment Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task. This is a follow-up child plan to `2026-06-01-memory-placement-heuristic-minimalization.md`: the previous plan removes route heuristics; this plan gives the Planner enough relation evidence and transaction vocabulary to make human-review-quality USER/MEMORY/Skill judgments without moving semantic logic back into code.

**Goal:** Make `hermes-self-improvement` dry-runs produce the same class of judgment a good Hermes reviewer would make when reviewing built-in memory and skills: move clear environment facts to `MEMORY.md`, keep user preferences in `USER.md`, split mixed entries, preserve same-topic entries that have different USER/MEMORY meanings, move reusable procedures into existing skills, detect skill ambiguity, and avoid unnecessary skill creation.

**Architecture:** Keep the existing one Planner → one Knowledge Editor path and canonical `knowledge_transactions`. Programmatic code only builds neutral evidence, relation bundles, allowed transaction shapes, and destructive-operation guards. The Planner LLM decides semantics. The Knowledge Editor executes only tool-mediated changes through official memory and skill tools.

**Tech Stack:** Python, pytest, Hermes self-improvement plugin, existing evidence pack / planner digest / prompt rendering / canonical transaction normalization / Knowledge Editor execution / dry-run artifacts.

---

## Current context

The latest direction is correct but incomplete.

Already done / covered by earlier plans:

- Built-in `USER.md` / `MEMORY.md` current entries are visible to the planner.
- `knowledge_transactions` are the canonical source of truth.
- `placement_move` and `memory_to_skill` execution have add-before-remove and source-staleness guards.
- Planner-facing `suggested_route`, `likely_*`, and `allowed_recommendations` route hints have been removed from the latest dry-run artifact.
- Programmatic marker-based routing is being minimized by `2026-06-01-memory-placement-heuristic-minimalization.md`.

Remaining product gap:

- The Planner can choose simple `placement_move`, but lacks first-class vocabulary for mixed entries, same-topic USER/MEMORY separation, relationship evidence, and skill ambiguity cleanup.
- As a result, human-review-correct cases still collapse into overly broad `USER -> MEMORY` moves.
- The plugin must become better at *asking the LLM the right question*, not at classifying semantics in Python.

---

## Design principle

Do **not** add marker lists or deterministic classifiers such as:

- `plugin` ⇒ MEMORY
- `好む` ⇒ USER
- path-like text ⇒ MEMORY
- workflow words ⇒ Skill
- duplicated theme ⇒ remove one side

Instead, expose neutral observations and relation bundles:

- exact current text
- current store
- official USER/MEMORY/Skill boundary
- nearby same-topic entries in the other store
- existing skill coverage candidates
- skill ambiguity information
- mixed-entry observations
- safe transaction templates

The Planner LLM owns the semantic decision.

---

## Target behavior from the motivating human review

Use this live-memory review fixture as the first dogfood acceptance target.

### Clear USER -> MEMORY move

Input entry from `USER.md`:

```text
opencode-go契約済みで極力活用。OpenAI互換はprovider=openai+base_url。Skill編集はprotected保護、localはpatch可。Safehouse注意はagent名でなく環境一般で書く。Gmail observer=~/.hermes/automations/gmail-purchase-observer、cron=~/.hermes/cron/jobs.json。
```

Expected Planner judgment:

- `placement_move` or `memory_rewrite + placement_move`
- Source: `builtin_user`
- Target: `builtin_memory`
- Reason: environment / tool / runtime convention, not primarily user profile
- Optional rewrite: compact but do not lose the durable facts

### Clear USER -> MEMORY move or compact rewrite

Input entry from `USER.md`:

```text
self-improvement設計は1 Planner+1 Knowledge Editor、skill/USER/MEMORY横断。semantic判断はLLM委任、hard guardは破壊的不変条件のみ。dogfood報告は実変更/blocked/partialを分ける。
```

Expected Planner judgment:

- `placement_move` or `memory_rewrite + placement_move`
- Reason: project/plugin design convention
- Keep wording compact; avoid over-expanding built-in memory

### Mixed entry: split, not move

Input entry from `USER.md`:

```text
Hermes/plugin障害: 相談語は調査設計のみ、明示OKまで変更禁止。PR取込test失敗は上流比較。正常経路ログ追加不要。実行環境ファイルは必要ならリセット可、環境由来エラーを回避で済ませない。context通知は末尾/inline。
```

Expected Planner judgment:

- `placement_split`
- Keep USER-shaped content in `USER.md`:
  -明示OKまで変更禁止
  -環境由来エラーを回避で済ませない
  -context通知は末尾/inline
- Move or compact MEMORY/Skill-shaped content:
  - PR取込test失敗は上流比較
  - 正常経路ログ追加不要
- Do **not** emit a simple `placement_move` for the whole entry

### Same topic, different store semantics: keep both

Inputs:

`USER.md`:

```text
Google Workspace は read-only 認可優先。Hermes のデフォルト skill / built-in files は編集しない方針。
```

`MEMORY.md`:

```text
Google Workspace は built-in `google-workspace` skill を既定にし、`~/.hermes/google_token.json` を使う。古い `~/.hermes/gws` 前提は legacy。
```

Expected Planner judgment:

- `keep_same_topic_different_store`
- Reason:
  - USER entry is Ryo preference / policy
  - MEMORY entry is environment / path / operational fact
- Do not mark as duplicate cleanup

### MEMORY -> Skill candidates

Examples from `MEMORY.md`:

- Gateway operational details
- Hindsight operational details
- Hermes live context operational details

Expected Planner judgment:

- Prefer `memory_to_skill` or `skill_patch_candidate` for existing matching skills
- Keep a short MEMORY fact if it is useful on every session start
- Avoid new skill creation when an existing umbrella skill covers the topic

### Skill ambiguity

Observed ambiguous loads:

- `hermes-memory-hygiene`
- `gmail-purchase-live-context`

Expected Planner judgment:

- `skill_ambiguity_cleanup` candidate
- Not `delete_skill`
- Not blind `skill_patch`
- Include conflicting paths and suggested cleanup direction for human/editor review

### Skill creation

Expected Planner judgment for this fixture:

- In this motivating fixture, a good Planner should usually avoid `create_skill` because existing skills appear to cover the relevant topics.
- This is a dogfood expectation for the fixture, not a programmatic gate: if the Planner has strong uncovered-workflow evidence, it may still choose `create_skill` with a concrete reason.

---

## New / extended transaction vocabulary

Keep the existing `decision` set (`apply / defer / skip / block`) and extend `transaction_kind` / operation payloads. Do not introduce approval queues or new lanes.

### 1. `placement_move`

Already exists. Keep it for whole-entry moves only.

Required fields:

```json
{
  "decision": "apply|defer|skip|block",
  "transaction_kind": "placement_move",
  "operation": "move",
  "source_store": "builtin_user|builtin_memory",
  "target_store": "builtin_memory|builtin_user",
  "source_id": "memory_place_...",
  "source_old_text": "exact current entry text",
  "content": "destination content, defaults to source_old_text only when semantically whole-entry move is intended",
  "reason": "planner semantic reason"
}
```

Hard guards:

- current store must match source store
- direction must match current store
- source old text must still be current
- destination add before source remove

### 2. `placement_split`

New. Use when one memory entry contains both USER-shaped and MEMORY/Skill-shaped fragments.

Required fields:

```json
{
  "decision": "apply|defer|skip|block",
  "transaction_kind": "placement_split",
  "operation": "split",
  "source_store": "builtin_user|builtin_memory",
  "source_id": "memory_place_...",
  "source_old_text": "exact current entry text",
  "source_replacement": "text that remains in the source store, or empty if removing source",
  "destination_store": "builtin_user|builtin_memory|null",
  "destination_content": "text to add/replace in destination store when applicable",
  "target_skill": "existing skill name when skill patch is part of the split, optional",
  "skill_task": "bounded editor task when target_skill is set, optional",
  "reason": "why split is semantically better than whole-entry move"
}
```

Execution order:

1. Validate source old text is current.
2. If `target_skill` is present, patch/verify skill first.
3. If `destination_store` is present, add/replace destination content next.
4. Replace/remove source only after destination/skill side succeeds.
5. If any destination step fails, leave source unchanged and report `partial` / `blocked`.

Do not support multi-destination fanout in the first implementation. If more than one destination is needed, Planner should defer with a concrete reason or emit one split plus a follow-up candidate.

### 3. `memory_rewrite`

New or existing-normalized. Use when content belongs in the same store but needs compaction, stale wording cleanup, or clearer declarative style.

Required fields:

```json
{
  "decision": "apply|defer|skip|block",
  "transaction_kind": "memory_rewrite",
  "operation": "replace",
  "target_store": "builtin_user|builtin_memory",
  "source_id": "memory_inventory_...|memory_place_...",
  "source_old_text": "exact current entry text",
  "replacement_content": "new compact entry text",
  "reason": "why rewrite keeps same semantic store"
}
```

### 4. `duplicate_cleanup`

New. Use for exact or clearly redundant cross-store duplicates. Do not use for same-topic/different-semantics pairs.

Required fields:

```json
{
  "decision": "apply|defer|skip|block",
  "transaction_kind": "duplicate_cleanup",
  "operation": "remove|replace|merge",
  "canonical_store": "builtin_user|builtin_memory",
  "source_store": "builtin_user|builtin_memory",
  "source_id": "...",
  "source_old_text": "exact text to remove or replace",
  "replacement_content": "optional replacement for source store",
  "related_evidence_ids": ["..."],
  "reason": "why this is true duplicate cleanup rather than same-topic separation"
}
```

### 5. `keep_same_topic_different_store`

New no-op transaction. Use when Planner explicitly judges that two entries are related but should both remain.

Required fields:

```json
{
  "decision": "skip",
  "transaction_kind": "keep_same_topic_different_store",
  "operation": "keep",
  "source_id": "...",
  "related_evidence_ids": ["..."],
  "reason": "USER entry expresses preference/policy; MEMORY entry expresses environment fact"
}
```

This is not an apply. It exists so healthy no-op semantic judgments are visible and not mistaken for planner omission.

### 6. `memory_to_skill`

Already exists. Extend Planner context so it prefers existing skill patch over new skill creation.

Required / normalized fields:

```json
{
  "decision": "apply|defer|skip|block",
  "transaction_kind": "memory_to_skill",
  "operation": "patch_skill_then_remove_memory|patch_skill_then_rewrite_memory|defer_target_unresolved",
  "source_store": "builtin_user|builtin_memory",
  "source_id": "...",
  "source_old_text": "exact current memory text",
  "target_skill": "existing editable local skill name",
  "skill_task": "bounded patch task",
  "source_replacement": "optional compact memory fact to leave behind",
  "reason": "why this belongs in an existing skill"
}
```

Execution remains skill-update-before-memory-remove.

### 7. `skill_patch`

Already conceptually exists as skill transaction. Use for direct skill maintenance without source-memory deletion.

### 8. `skill_ambiguity_cleanup`

New no-op or bounded patch candidate. Use when skill discovery reports ambiguous names / path collisions.

Required fields:

```json
{
  "decision": "defer|apply|skip|block",
  "transaction_kind": "skill_ambiguity_cleanup",
  "operation": "rename_reference_file|patch_skill_docs|defer_manual_review",
  "ambiguous_name": "hermes-memory-hygiene",
  "conflicting_paths": ["..."],
  "target_skill": "optional editable skill if one side is editable and exact cleanup is safe",
  "reason": "why this is ambiguity cleanup, not delete"
}
```

First implementation can normalize/report this transaction without executing mutation. Execution can follow only after an exact editable target and safe action are proven.

---

## Evidence model changes

### Existing candidate stays

`memory_placement_candidate` should keep:

- `evidence_id`
- `current_store`
- `old_text`
- `summary`
- `official_boundary`
- `placement_observations`
- `allowed_decisions`
- `candidate_target_skills` when available

It should not contain directional recommendations.

### Add `mixed_entry_candidate`

Purpose: help Planner notice that one entry may contain multiple knowledge facets without deciding the split or destination in code.

Shape:

```json
{
  "kind": "mixed_entry_candidate",
  "evidence_id": "mixed_memory_...",
  "source_evidence_id": "memory_place_...",
  "current_store": "user|memory",
  "old_text": "exact current entry text",
  "observations": [
    "contains_multiple_policy_or_convention_phrases",
    "mentions_tool_project_or_runtime_terms",
    "mentions_procedure_or_operational_terms"
  ],
  "official_boundary": "...",
  "notes": "Observations are not recommendations. Planner decides keep/move/split/defer."
}
```

Implementation guidance:

- Keep detection broad, cheap, and destination-neutral.
- It is okay if some false positives appear; Planner can skip/defer.
- Do not extract destination fragments programmatically in this slice.
- Do not emit labels that encode USER/MEMORY/Skill destination such as `user_preference`, `runtime_fact`, `skill_workflow`, or `should_split`. The labels above are surface observations only; the Planner decides whether they matter.

### Add `cross_store_related_pair`

Purpose: prevent same-topic pairs from being collapsed into duplicate cleanup when their semantics differ.

Shape:

```json
{
  "kind": "cross_store_related_pair",
  "evidence_id": "cross_store_pair_...",
  "user_evidence_id": "...",
  "memory_evidence_id": "...",
  "user_text": "...",
  "memory_text": "...",
  "relation_observations": ["shared_topic_terms", "shared_named_entities", "bounded_text_overlap"],
  "official_boundary": "...",
  "notes": "Planner may choose duplicate_cleanup, keep_same_topic_different_store, rewrite, or defer."
}
```

Implementation guidance:

- Use simple token/substring overlap to generate candidates, but do not label canonical store or likely semantic relationship.
- Cap pairs aggressively, e.g. top 20 by overlap / exact topic anchors.
- Include Google Workspace fixture as regression.
- Do not generate labels like `different_store_semantics_possible` in code; the prompt may explain that related pairs can be duplicates, same-topic/different-store facts, rewrite candidates, or defer cases.

### Add or extend `skill_coverage_candidate`

Purpose: let Planner see existing skills as advisory context before it decides among `create_skill`, `memory_to_skill`, `skill_patch`, `skip`, or `defer`. Coverage is not a hard gate.

Shape:

```json
{
  "kind": "skill_coverage_candidate",
  "evidence_id": "skill_cov_...",
  "source_evidence_id": "memory_place_...",
  "source_old_text": "...",
  "matching_skills": [
    {
      "name": "hindsight-operations",
      "editable": true,
      "protected_reason": null,
      "match_reason": "title/reference/topic overlap",
      "excerpt": "bounded excerpt"
    }
  ],
  "notes": "Advisory context only. Planner decides whether existing skill coverage is enough, needs patch, has no fit, or whether a new skill is still justified by strong uncovered evidence."
}
```

Implementation guidance:

- Reuse existing skill inventory / coverage-fit code where possible.
- Do not use `skills_list` as mutation source of truth.
- Protected/non-editable skills may appear as reference-only context but must not become mutation targets.

### Add `skill_ambiguity_candidate`

Purpose: detect ambiguous skill loads/path collisions as improvement candidates.

Shape:

```json
{
  "kind": "skill_ambiguity_candidate",
  "evidence_id": "skill_ambiguous_...",
  "ambiguous_name": "gmail-purchase-live-context",
  "conflicting_paths": [".../gmail-purchase-live-context/SKILL.md", ".../references/gmail-purchase-live-context.md"],
  "observations": ["skill_view_ambiguous", "reference_basename_collides_with_skill_name"],
  "notes": "Planner may defer, patch docs, or propose reference rename; do not delete blindly."
}
```

Implementation guidance:

- Source candidates from tool-failure / ambiguous skill evidence if already collected.
- Also optionally scan local skill/reference basenames for collisions in a bounded inventory pass.
- First execution can be preview/report-only.

---

## Planner prompt changes

Add a dedicated section after memory placement candidates, before generic transaction templates:

```text
Semantic knowledge judgment rules:
- You decide semantics. Observations are not recommendations.
- Do not move a whole entry if it contains mixed USER-shaped and MEMORY/Skill-shaped content. Use placement_split or defer.
- Do not treat same topic across USER and MEMORY as duplicate by default. If USER expresses preference/policy and MEMORY expresses environment/runtime fact, use keep_same_topic_different_store.
- Use placement_move only when the whole source entry clearly belongs in the opposite built-in store.
- Use memory_rewrite when content stays in the same store but should be compacted or clarified.
- Use memory_to_skill when reusable procedure/workflow belongs in an existing editable skill. Prefer patching existing skills over creating new ones.
- Use skill_ambiguity_cleanup for skill-name/path collisions. Do not delete skills to solve ambiguity unless a later explicit lifecycle plan proves it safe.
- If exact target or safe split text is unclear, defer with a concrete reason rather than forcing a move.
```

Add transaction templates for:

- `placement_split`
- `memory_rewrite`
- `duplicate_cleanup`
- `keep_same_topic_different_store`
- `skill_ambiguity_cleanup`

Remove or avoid any prompt wording that implies observations dictate action.

---

## Implementation phases

### Phase 0: Plan/index hygiene

**Objective:** Make this plan the active follow-up without losing the completed heuristic-minimalization context.

**Files:**

- Create: `.hermes/plans/2026-06-01-llm-semantic-knowledge-judgment.md`
- Modify: `.hermes/plans/README.md`

**Steps:**

1. Add this plan.
2. Update the plan index current source-of-truth section with a short note:
   - heuristic minimalization removes route hints
   - this follow-up adds relation evidence and transaction vocabulary
   - no implementation yet
3. Verify docs diff only:
   - `git diff -- .hermes/plans/README.md .hermes/plans/2026-06-01-llm-semantic-knowledge-judgment.md`

**Exit criteria:** Plan and index are readable and point to the correct next implementation slice.

---

### Phase 1: Canonical transaction schema and normalizer support

**Objective:** Ensure new Planner outputs survive normalization and appear in dry-run artifacts before adding execution.

**Files likely to change:**

- `hermes_self_improvement/knowledge_transactions.py`
- `hermes_self_improvement/planner.py`
- `hermes_self_improvement/planner_runtime.py`
- `hermes_self_improvement/cli.py`
- `tests/test_knowledge_transactions.py`
- `tests/test_knowledge_transaction_view.py`
- `tests/test_skill_planner.py`

**Step 1: Add RED tests for transaction normalization**

Add tests that feed raw planner payloads for:

- `placement_split`
- `memory_rewrite`
- `duplicate_cleanup`
- `keep_same_topic_different_store`
- `skill_ambiguity_cleanup`

Expected:

- normalized transaction keeps `transaction_kind`
- preserves `source_evidence_id` / `evidence_ids`
- preserves exact `source_old_text`
- does not drop no-op `keep_same_topic_different_store`
- unknown/missing required destructive fields become `block` or `defer`, not malformed `apply`

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_knowledge_transactions.py tests/test_knowledge_transaction_view.py -q
```

Expected first run: fail for unsupported new kinds.

**Step 2: Implement minimal normalization**

Implementation notes:

- Do not execute anything yet.
- Treat `keep_same_topic_different_store` as a valid no-op skip transaction.
- Treat `skill_ambiguity_cleanup` as report/preview unless operation and target are definitely executable.
- Preserve `reason`, `semantic_boundary_notes`, and source fields for artifacts.

**Step 3: Update action summaries**

Summaries should count by `transaction_kind` without pretending all new transactions are memory changes.

Expected summary categories:

- skill
- built-in memory
- placement move
- placement split
- memory rewrite
- duplicate cleanup
- memory-to-skill
- skill ambiguity cleanup
- no-op semantic keep
- deferred/skipped/blocked

**Step 4: Run focused tests**

```bash
$PY -m pytest tests/test_knowledge_transactions.py tests/test_knowledge_transaction_view.py tests/test_skill_planner.py -q
```

---

### Phase 2: Evidence builder relation candidates

**Objective:** Give the Planner the same context a human reviewer used, without deterministic semantic routing.

**Files likely to change:**

- `hermes_self_improvement/evidence.py`
- `hermes_self_improvement/planner_memory.py`
- `hermes_self_improvement/planner_targets.py`
- `hermes_self_improvement/planner_runtime.py`
- `tests/test_evidence_inventory_candidates.py`
- `tests/test_evidence_pack.py`
- `tests/test_knowledge_planner_digest.py`

**Step 1: Add RED tests for mixed entry evidence**

Fixture: the `Hermes/plugin障害...` USER entry.

Expected:

- evidence includes a memory placement candidate with exact old text
- evidence may include `mixed_entry_candidate`
- evidence does **not** include `suggested_route`, `likely_*`, or destination recommendation
- observations are neutral

Run:

```bash
$PY -m pytest tests/test_evidence_inventory_candidates.py::test_mixed_memory_entry_candidate_is_observation_only -q
```

**Step 2: Implement mixed-entry observations**

Implementation notes:

- Keep it broad and bounded.
- Observations can be label-only, e.g. `contains_user_preference_or_policy_language`, `contains_runtime_or_project_policy_language`, `contains_workflow_or_procedure_language`.
- Do not extract exact split fragments in code.

**Step 3: Add RED tests for cross-store related pairs**

Fixture: Google Workspace USER/MEMORY entries.

Expected:

- `cross_store_related_pair` exists
- includes both exact texts or bounded versions plus evidence ids
- relation observations are neutral
- no canonical store is assigned by code

**Step 4: Implement bounded cross-store related pair generation**

Implementation notes:

- Use simple shared tokens/topic anchors.
- Cap result count.
- Stable sort by evidence id or pair key, not route priority.

**Step 5: Add RED tests for skill coverage candidates**

Fixtures:

- Gateway memory entry should surface `hermes-gateway-and-sessions` / related existing skills as coverage context when inventory is available.
- Hindsight memory entry should surface `hindsight-operations`.
- Existing skill coverage should be shown as advisory context, not as a hard `create_skill` blocker.

**Step 6: Implement / reuse skill coverage context**

Implementation notes:

- Reuse path-aware inventory if present.
- Reference-only protected skills can be shown as context; mutation target must remain local/unprotected.
- Keep excerpts bounded.

**Step 7: Add RED tests for skill ambiguity candidates**

Fixture:

- `hermes-memory-hygiene` ambiguity or synthetic colliding skill/reference basename.

Expected:

- `skill_ambiguity_candidate` appears with conflicting paths
- candidate is not a delete recommendation
- candidate is bounded

**Step 8: Implement ambiguity candidate collection**

Implementation notes:

- Prefer existing ambiguous-skill-resolution event sources if available.
- Bounded local scan is acceptable if cheap.
- No mutation execution in this phase.

**Step 9: Run focused tests**

```bash
$PY -m pytest tests/test_evidence_inventory_candidates.py tests/test_evidence_pack.py tests/test_knowledge_planner_digest.py -q
```

---

### Phase 3: Planner digest and prompt templates

**Objective:** Let the Planner choose the richer transaction types from neutral evidence.

**Files likely to change:**

- `hermes_self_improvement/planner_runtime.py`
- `hermes_self_improvement/prompts.py`
- `tests/test_knowledge_planner_digest.py`
- `tests/test_skill_planner.py`
- `tests/test_memory_inventory_planner.py`

**Step 1: Add RED prompt rendering tests**

Expected prompt contains:

- semantic knowledge judgment rules
- `placement_split` template
- `memory_rewrite` template
- `duplicate_cleanup` template
- `keep_same_topic_different_store` template
- `skill_ambiguity_cleanup` template
- explicit sentence: observations are not recommendations

Expected prompt does not contain:

- `suggested_route`
- `likely_move_user_to_memory`
- `likely_move_memory_to_user`
- `likely_memory_to_skill`
- route-priority wording

**Step 2: Render relation evidence in digest**

Add bounded sections:

- Mixed memory entries
- Cross-store related memory pairs
- Existing skill coverage for memory entries
- Skill ambiguity candidates

Do not sort by semantic destination.

**Step 3: Add transaction examples to Planner prompt**

Examples should be short and structural, not hardcoded to current Ryo entries.

Include guidance:

- whole-entry move only when clear
- split mixed entries
- same-topic different store can be a healthy no-op
- existing skill patch before create skill
- defer when split text or target skill is uncertain

**Step 4: Run focused prompt tests**

```bash
$PY -m pytest tests/test_knowledge_planner_digest.py tests/test_skill_planner.py tests/test_memory_inventory_planner.py -q
```

---

### Phase 4: Dry-run artifact and reporting support

**Objective:** Make richer semantic judgments visible in artifacts and compact summaries even before execution is added.

**Files likely to change:**

- `hermes_self_improvement/cli.py`
- `hermes_self_improvement/runner_steps.py`
- `hermes_self_improvement/episodes.py`
- `hermes_self_improvement/tool_handlers.py`
- `tests/test_cli_surface.py`
- `tests/test_plugin_tools.py`
- `tests/test_episode_ledger.py`
- `tests/test_report_improve_connection.py`

**Step 1: Add artifact tests for no-op semantic keep**

Expected:

- `keep_same_topic_different_store` appears in `knowledge_transactions`
- action summary counts it as skip/no-op, not missing planner decision
- compact tool payload exposes bounded count, not full memory text

**Step 2: Add artifact tests for split preview**

Expected dry-run:

- `placement_split` apply/defer is preserved
- source/destination proposed text appears in full artifact
- compact tool result only shows counts and ids

**Step 3: Add reporting lines**

Suggested compact categories:

```text
Knowledge changes: placement_split preview 1, same-topic keep 1, skill ambiguity 2
Memory placement: move 2, split 1, duplicate cleanup 0, same-topic keep 1
```

Keep Slack/tool summaries short. Full text stays in run artifacts.

**Step 4: Run focused reporting tests**

```bash
$PY -m pytest tests/test_cli_surface.py tests/test_plugin_tools.py tests/test_report_improve_connection.py -q
```

---

### Phase 5: Knowledge Editor execution for safe memory operations

**Objective:** Execute only the safe built-in memory operations needed for the new transaction types.

**Files likely to change:**

- `hermes_self_improvement/editor.py`
- `hermes_self_improvement/editor_memory.py`
- `hermes_self_improvement/editor_backend_memory.py`
- `hermes_self_improvement/runner_steps.py`
- `tests/test_runner_steps.py`
- `tests/test_cli_improve_memory_current_entries.py`
- `tests/test_memory_to_skill_migration.py`

**Step 1: Add RED tests for `memory_rewrite` execution**

Expected:

- exact source match required
- memory tool called with `replace`
- stale source blocks before mutation
- dry-run does not mutate

**Step 2: Implement `memory_rewrite` execution**

Use official memory tool path only. Do not direct-edit files.

**Step 3: Add RED tests for `duplicate_cleanup` execution**

Expected:

- source old text required
- remove/replace only applies to source store
- near-duplicate without exact source text blocks/defer

**Step 4: Implement safe `duplicate_cleanup` execution**

Keep operation support narrow:

- `remove`
- `replace`

Do not implement merge fanout yet.

**Step 5: Add RED tests for `placement_split` execution**

Expected:

- source old text current check happens before destination add
- destination add/skill patch happens before source replacement/removal
- destination failure leaves source intact
- source replacement failure after destination success reports partial
- dry-run shows intended calls but does not mutate

**Step 6: Implement first-slice `placement_split` execution**

Scope:

- built-in USER ↔ MEMORY split
- optional source replacement
- no multi-destination fanout
- no skill patch inside split until Phase 6 unless trivial to reuse existing `memory_to_skill` path safely

**Step 7: Run focused execution tests**

```bash
$PY -m pytest tests/test_runner_steps.py tests/test_cli_improve_memory_current_entries.py tests/test_memory_to_skill_migration.py -q
```

---

### Phase 6: Existing skill-first memory-to-skill and skill ambiguity handling

**Objective:** Improve skill-side judgment without creating unnecessary new skills or destructive ambiguity fixes.

**Files likely to change:**

- `hermes_self_improvement/planner_targets.py`
- `hermes_self_improvement/planner_runtime.py`
- `hermes_self_improvement/editor_skill.py`
- `hermes_self_improvement/editor_backend_skill.py`
- `hermes_self_improvement/runner_steps.py`
- `tests/test_duplicate_skill_lifecycle_regression.py`
- `tests/test_memory_to_skill_migration.py`
- `tests/test_target_resolver.py`
- `tests/test_unmatched_evidence_candidates.py`

**Step 1: Add RED test: existing skill beats create_skill**

Fixture: procedural MEMORY entry plus matching existing skill coverage.

Expected:

- Planner prompt shows existing skill coverage
- normalized transaction can be `memory_to_skill` or `defer target unresolved`
- prompt says existing coverage is advisory context and the Planner must explain any `create_skill` despite apparent coverage

**Step 2: Improve existing skill coverage rendering**

Keep it bounded and non-authoritative.

**Step 3: Add RED test for `skill_ambiguity_cleanup` preview**

Expected:

- ambiguous skill candidate normalizes to `skill_ambiguity_cleanup`
- default execution is defer/preview unless exact editable file action is available
- no delete action is emitted by default

**Step 4: Implement report-only ambiguity cleanup path**

First implementation should not rename files. It should:

- record candidate
- expose conflicting paths
- let Planner defer with concrete reason
- optionally produce `skill_patch` only if an editable skill doc can be safely clarified without file rename

**Step 5: Run focused skill tests**

```bash
$PY -m pytest tests/test_duplicate_skill_lifecycle_regression.py tests/test_memory_to_skill_migration.py tests/test_target_resolver.py tests/test_unmatched_evidence_candidates.py -q
```

---

### Phase 7: Golden fixture / dogfood dry-run quality gate

**Objective:** Prove the plugin can emit human-review-like judgments on the motivating examples before any mutating replay.

**Files likely to change:**

- `tests/fixtures/` or existing fixture module
- `tests/test_memory_inventory_planner.py`
- `tests/test_knowledge_planner_digest.py`
- `tests/test_cli_improve_memory_current_entries.py`
- `.hermes/plans/README.md`
- This plan file progress section

**Step 1: Add deterministic fixture test for the human review examples**

Use a fake Planner response if needed to test end-to-end normalization/artifact behavior without relying on live LLM.

Fixture entries:

- opencode-go USER entry
- self-improvement design USER entry
- Hermes/plugin障害 mixed USER entry
- Google Workspace USER/MEMORY pair
- Gateway/Hindsight/live context MEMORY entries
- ambiguous skill names

Expected normalized transaction shape:

- opencode-go → ideally `placement_move`; `memory_rewrite + placement_move` is also acceptable if the Planner preserves the same durable facts.
- self-improvement design → `placement_move` or `memory_rewrite + placement_move`.
- Hermes/plugin障害 → ideally `placement_split`; `defer` is acceptable if the Planner says the split text is uncertain. A whole-entry `placement_move` should be treated as a judgment-quality regression.
- Google Workspace pair → ideally `keep_same_topic_different_store`; `defer` is acceptable if the Planner cannot verify the distinction. `duplicate_cleanup` without acknowledging different USER/MEMORY semantics is a regression.
- Gateway/Hindsight/live context → `memory_to_skill` candidate, `skill_patch` candidate, or defer with existing skill coverage context.
- ambiguous skill names → `skill_ambiguity_cleanup` or defer with ambiguity details.
- in the motivating fixture, `create_skill` should normally be 0 unless the Planner gives a strong uncovered-workflow reason.

These are quality expectations for this fixture, not deterministic Python classifiers. Tests should verify that the allowed transaction vocabulary and evidence attachments survive normalization, that forbidden route hints do not leak, and that bad whole-entry moves / duplicate cleanups are detectable as planner-quality regressions.

**Step 2: Run live-artifact route-leak regression**

Do not use a broad `rg` over the repo or this plan file: historical docs, compatibility code, and explicit forbidden-string examples can produce false positives. Instead, parse the generated dry-run artifact and any captured rendered planner prompt / compact tool payload produced by the test.

Example artifact check:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY - <<'PY'
import json
from pathlib import Path
run_path = Path('REPLACE_WITH_LATEST_DRY_RUN_ARTIFACT.json')
forbidden = [
    'suggested_route',
    'likely_move_user_to_memory',
    'likely_move_memory_to_user',
    'likely_memory_to_skill',
    'allowed_recommendations',
    'by_suggested_route',
    'default_defer_by_route',
    'unhandled_by_route',
]
data = json.loads(run_path.read_text())
blob = json.dumps(data, ensure_ascii=False)
for item in forbidden:
    assert item not in blob, item
print('route leak check passed:', run_path)
PY
```

Expected:

- No forbidden route fields in live dry-run artifacts, rendered planner prompt payloads, or compact tool payloads.
- Historical docs/tests may mention forbidden strings only as explicit legacy/negative examples.
- Compatibility code may read old runtime-private artifacts, but must not render those fields into new Planner-facing payloads.

**Step 3: Run full validation**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
git diff --check
hermes self-improvement status
hermes self-improvement improve --dry-run --json
```

**Step 4: Inspect latest dry-run artifact**

Check:

- `knowledge_transactions` includes new kinds when Planner selects them
- no forbidden route fields in live run artifact
- compact tool payload is bounded
- full artifact includes enough source/destination text for review
- dry-run did not mutate skills or memory

**Step 5: Add canonical replay coverage before mutating dogfood**

Add a synthetic `--from-run` / canonical replay test that includes the new transaction kinds without relying on a live LLM:

- `memory_rewrite`
- `duplicate_cleanup`
- `placement_split`
- `keep_same_topic_different_store`
- `skill_ambiguity_cleanup`

Expected:

- canonical replay preserves and reports the new kinds;
- executable memory transactions run only through the safe editor path when mutate is enabled;
- no-op/report-only transactions remain no-op/report-only;
- replay does not fall back to legacy split lanes;
- stale or missing source text blocks before mutation.

Likely test targets:

- `tests/test_report_improve_connection.py`
- `tests/test_runner_steps.py`
- `tests/test_cli_surface.py`

**Step 6: Update plan/index**

Record:

- validation result
- dry-run artifact path
- selected transaction counts
- replay test result
- whether live LLM matched the golden fixture expectation
- remaining mismatch, if any

Do not run mutating replay until a low-risk apply exists and Ryo explicitly approves.

---

## Files / surfaces checklist

When implementing, inspect and update all relevant surfaces. Do not fix only the primary prompt path.

Likely source files:

- `hermes_self_improvement/evidence.py`
- `hermes_self_improvement/planner_memory.py`
- `hermes_self_improvement/planner_targets.py`
- `hermes_self_improvement/planner_runtime.py`
- `hermes_self_improvement/planner.py`
- `hermes_self_improvement/prompts.py`
- `hermes_self_improvement/knowledge_transactions.py`
- `hermes_self_improvement/runner_steps.py`
- `hermes_self_improvement/editor.py`
- `hermes_self_improvement/editor_memory.py`
- `hermes_self_improvement/editor_backend_memory.py`
- `hermes_self_improvement/editor_skill.py`
- `hermes_self_improvement/editor_backend_skill.py`
- `hermes_self_improvement/cli.py`
- `hermes_self_improvement/tool_handlers.py`
- `hermes_self_improvement/episodes.py`
- `hermes_self_improvement/runtime_eval_cases.py`

Likely tests:

- `tests/test_evidence_inventory_candidates.py`
- `tests/test_evidence_pack.py`
- `tests/test_knowledge_planner_digest.py`
- `tests/test_skill_planner.py`
- `tests/test_knowledge_transactions.py`
- `tests/test_knowledge_transaction_view.py`
- `tests/test_memory_inventory_planner.py`
- `tests/test_runner_steps.py`
- `tests/test_cli_improve_memory_current_entries.py`
- `tests/test_memory_to_skill_migration.py`
- `tests/test_duplicate_skill_lifecycle_regression.py`
- `tests/test_target_resolver.py`
- `tests/test_cli_surface.py`
- `tests/test_plugin_tools.py`
- `tests/test_report_improve_connection.py`
- `tests/test_memory_agent_dispatch.py`
- `tests/test_episode_ledger.py`

Docs / plans:

- `.hermes/plans/README.md`
- `.hermes/plans/2026-06-01-memory-placement-heuristic-minimalization.md`
- `.hermes/plans/2026-06-01-llm-semantic-knowledge-judgment.md`
- `skills/operations/SKILL.md` only if implementation changes user-facing operation guidance

---

## Risks and guardrails

### Risk: transaction vocabulary becomes a new hidden policy layer

Mitigation:

- Transaction templates are allowed operations, not recommendations.
- Evidence names must remain neutral.
- Tests should assert prompt says observations are non-authoritative.

### Risk: too many candidates bloat Planner prompt

Mitigation:

- Cap relation candidates.
- Put full details in artifacts; render bounded snippets in prompt.
- Prefer representative examples over exhaustive relation graph.

### Risk: split execution causes partial memory loss

Mitigation:

- Destination/skill side first.
- Source exact-text check before mutation.
- Source replacement/removal last.
- Partial success is reported honestly.

### Risk: same-topic pair generation creates false duplicate pressure

Mitigation:

- Name the evidence `related_pair`, not `duplicate_pair`.
- Prompt explicitly says same-topic can mean keep both.
- `keep_same_topic_different_store` is a valid success/no-op.

### Risk: skill ambiguity cleanup accidentally deletes or renames useful files

Mitigation:

- First implementation is report/defer/preview only.
- No delete by default.
- Any future rename requires exact editable target and separate execution proof.

---

## Implementation progress (2026-06-01)

| Phase | Status | Notes |
|-------|--------|-------|
| 1: Canonical transaction schema + normalizer | ✅ Complete | All 6 new kinds survive normalization. `placement_split`, `memory_rewrite`, `duplicate_cleanup`, `keep_same_topic_different_store`, `skill_ambiguity_cleanup` + `placement_move` existing. |
| 2: Evidence builder relation candidates | ✅ Complete | `mixed_entry_candidate`, `cross_store_related_pair`, `skill_coverage_candidate`, `skill_ambiguity_candidate` in evidence pack / planner digest. Neutral observations, no route recommendations. |
| 3: Planner digest + prompt templates | ✅ Complete | `_render_semantic_knowledge_section` pipes candidates into planner prompt. Template examples, explicit "Observations are not recommendations". |
| 4: Dry-run artifact + reporting | ✅ Complete | `_canonical_knowledge_change_counts` now exposes `semantic_memory_placement` bounded counts. No full text / conflicting_paths leaks in compact tool payload. |
| 5: Knowledge Editor execution | ✅ Complete | `memory_rewrite`, `duplicate_cleanup`, `placement_split` execution dispatch. add/replace/remove via official memory tool. Source staleness check, add-before-remove for split. |
| 6: Existing skill-first + ambiguity | ⬜ Pending | Planner-facing existing skill coverage, skill ambiguity cleanup preview, avoid unnecessary create_skill. |
| 7: Golden fixture / dogfood quality gate | ⬜ Pending | Deterministic fixture test for motivating examples, end-to-end dry-run artifact quality check. |

**Latest verification:** `tests/test_plugin_tools.py tests/test_knowledge_transactions.py tests/test_knowledge_transaction_view.py tests/test_evidence_inventory_candidates.py tests/test_evidence_pack.py tests/test_knowledge_planner_digest.py tests/test_skill_planner.py tests/test_memory_inventory_planner.py tests/test_memory_to_skill_migration.py tests/test_cli_improve_memory_current_entries.py tests/test_runner_steps.py` → **263 passed in 8.21s**.

---

## Completion criteria

The plan is complete when:

1. The Planner prompt/digest contains relation evidence and templates for:
   - `placement_split`
   - `memory_rewrite`
   - `duplicate_cleanup`
   - `keep_same_topic_different_store`
   - `skill_ambiguity_cleanup`
2. No live planner-facing surface reintroduces route recommendations.
3. Normalizer preserves all new transaction kinds and evidence ids.
4. Dry-run artifacts can show human-review-like judgments for the motivating fixture.
5. Safe execution exists for:
   - `memory_rewrite`
   - `duplicate_cleanup` remove/replace
   - first-slice built-in `placement_split`
6. Skill ambiguity cleanup is at least visible/reportable and not destructive.
7. Existing skill coverage is visible as advisory context, and unnecessary `create_skill` proposals are reduced by Planner judgment rather than a hard programmatic gate.
8. Full validation passes:
   - `py_compile`
   - full `pytest tests -q`
   - `git diff --check`
   - `hermes self-improvement status`
   - `hermes self-improvement improve --dry-run --json`
9. `.hermes/plans/README.md` and this plan record the final dry-run artifact path and remaining mismatches.

---

## Out of scope

- No Hermes core changes.
- No new roles, queues, canary modes, confidence gates, or approval layers.
- No direct built-in memory file edits.
- No direct provider DB edits.
- No arbitrary docs/config/runtime mutation beyond skill/memory/evaluator scope.
- No automatic skill deletion for ambiguity cleanup.
- No forced mutating replay just to prove `apply > 0`.

---

## Recommended commit slicing

1. `docs: plan semantic knowledge judgment follow-up`
   - plan + README index only
2. `feat: preserve semantic knowledge transaction kinds`
   - Phase 1
3. `feat: add relation evidence for memory judgment`
   - Phase 2
4. `feat: teach planner semantic knowledge transactions`
   - Phase 3 + Phase 4 preview/reporting
5. `feat: execute safe memory rewrite and split transactions`
   - Phase 5
6. `feat: surface existing skill coverage and ambiguity cleanup`
   - Phase 6
7. `test: add semantic knowledge judgment dogfood fixture`
   - Phase 7 + plan/index update

Each commit should run focused tests first. Run the full gate before reporting the whole plan complete.
