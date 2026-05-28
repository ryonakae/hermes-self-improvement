# Knowledge Transaction Unification Implementation Plan

> **For Hermes:** Implement this plan completely, in small TDD slices. Do not stop after visibility-only counters if planner/editor still route skill and memory independently.

**Goal:** Finish the `planner / editor` redesign so skills and memory are handled as one knowledge transaction system, not two parallel runners with weak handoff.

**Architecture:** Replace the current split behavior (`skill step` plus `memory step`) with an explicit knowledge transaction layer. The planner classifies evidence into a target store (`skill`, `builtin_user`, `builtin_memory`, `external_memory`, `unresolved`, `none`) and can produce cross-store transactions such as memory-to-skill migration. The editor executes the resulting transaction through official skill and memory/provider tools with add-before-remove semantics, then artifacts/reporting show whether matched evidence was selected, routed, applied, or intentionally skipped.

**Tech Stack:** Python, pytest, Hermes standalone plugin runtime artifacts, official `skill_manage` and memory/provider tool surfaces, existing `improve` / `calibrate` flows.

---

## Why this plan exists

The 2026-05-28 scheduled dogfood artifact (`~/.hermes/self-improvement/runs/run-20260527T190256Z.json`) looked healthy at a shallow readiness level:

- `actionability_loss_count: 0`
- `skip_class_counts: benign 47`
- `skill_changes: 0`
- `memory_changes: 0`

But deeper inspection showed the redesign is still incomplete:

- 11 skill candidates had attached evidence, yet all were skipped with the generic reason `not_selected_by_planner`.
- Memory had 43 candidates, but the mutating result was rejected with `skill_editor_result_changed_skills_missing`, which is a memory/editor schema mix-up.
- Memory decisions included 8 `not_memory_workflow_to_skill` skips for timeout, patch, terminal preflight, and sandbox workflows.
- The corresponding skill-side candidates were also skipped, so memory-routed workflow evidence could fall between the two lanes.

This is not a request to loosen mutation gates or inflate apply counts. It is a request to complete the architecture that was already intended: a planner that reasons over knowledge placement across skills and memory, and an editor that executes a bounded transaction across both stores.

---

## Non-negotiable completion criteria

This plan is not complete until all four outcomes below are true:

1. Artifacts honestly expose matched-but-not-selected and memory-to-skill routing outcomes.
2. Planner produces one knowledge transaction plan rather than independently losing skill/memory handoffs.
3. Editor can execute mixed skill/memory transactions with official tools and add-before-remove semantics.
4. Old split schema/reporting leaks are gone enough that memory editor failures cannot appear as `skill_editor_result_*`, and prompt/runtime naming no longer implies two independent editors.

Partial visibility-only work may be committed as an intermediate slice, but the parent roadmap must remain **not ready** until all four are implemented and dogfooded.

## Compatibility and runtime reset policy

This redesign does **not** preserve old split skill/memory planner or editor compatibility. The plugin is unreleased enough that carrying compatibility shims would make the new architecture ambiguous and harder to verify.

- Delete or rename old canonical artifact keys instead of maintaining dual execution paths.
- Do not keep old `skill.decisions` / `memory.decisions` as compatibility views once `knowledge_transactions` exists.
- Do not keep old `skill_editor_result_*` / `memory_editor_result_*` result contracts in runtime-facing artifacts.
- Tests should assert the new contract positively, not preserve old schemas.
- If existing runtime data under `${HERMES_HOME}/self-improvement` blocks clean setup or exposes legacy role residue, it is acceptable to reset/delete that runtime data and re-run setup. Preserve nothing for compatibility unless a later task explicitly asks for migration tooling.

---

## Target model

### Planner target vocabulary

Every actionable or reviewed candidate should normalize to exactly one of:

- `skill`: reusable workflow/procedure, including procedural content currently duplicated in memory.
- `builtin_user`: user identity, durable preference, response-style preference, stable personal fact.
- `builtin_memory`: stable environment/repo/tool convention that should be injected regularly.
- `external_memory`: longer background, implementation history, research context, or searchable context that should not be injected every turn.
- `unresolved`: evidence is real but target/action is ambiguous.
- `none`: diagnostic/noise/no durable target.

### Planner transaction shape

The planner should emit bounded transaction plans like:

```json
{
  "decision": "apply",
  "transaction_id": "txn_memory_to_skill_timeout_workflow",
  "target_store": "skill",
  "target_id": "timeout-workflow",
  "source_store": "builtin_memory",
  "source_ids": ["memory-entry-id-or-old_text-hash"],
  "operation": "memory_to_skill",
  "editor_steps": [
    {"tool": "skill_manage", "action": "patch", "target": "timeout-workflow"},
    {"tool": "memory", "action": "replace_or_remove", "target": "memory"}
  ],
  "preconditions": [
    "target skill is local mutable or operation is create_skill",
    "source memory old_text still matches before removal",
    "memory removal happens only after skill mutation verifies"
  ],
  "evidence_ids": ["coverage_...", "unmatched_..."],
  "skip_if": []
}
```

The same schema should also represent memory-only and skill-only changes. Skill-only and memory-only are special cases of knowledge transactions, not separate reasoning lanes.

### Editor execution rule

The editor receives a validated transaction plan and executes only that plan.

- For skill operations, use official skill tools only.
- For built-in memory operations, use the official `memory` tool semantics.
- For external memory, use the active provider tool such as `hindsight_retain` when target is `external_memory`.
- For cross-store moves, perform destination add/patch/create first, verify, then source replace/remove.
- If any precondition fails, stop with a structured non-mutating outcome. Do not invent a substitute mutation.

---

## Implementation slices

### Slice 1 — Honest artifact/report visibility for matched-but-not-selected and routed evidence

**Status:** completed 2026-05-28.

**Validation:**
- Focused tests: `tests/test_skill_planner.py::test_planner_quality_report_exposes_matched_but_not_selected_reasons`, `tests/test_skill_planner.py::test_planner_quality_report_classifies_weak_matched_noop_separately`, `tests/test_memory_to_skill_migration.py::test_knowledge_routing_summary_reports_memory_to_skill_drop`, `tests/test_memory_to_skill_migration.py::test_knowledge_routing_summary_counts_memory_to_skill_preview_as_selected`, `tests/test_cli_surface.py::test_improve_summary_is_curator_style_and_mentions_private_eval_cases`, `tests/test_cli_surface.py::test_improve_summary_reports_memory_to_skill_migrations`, `tests/test_plugin_tools.py::test_improve_tool_returns_compact_llm_facing_summary` — passed.
- Related tests: `tests/test_skill_planner.py tests/test_memory_to_skill_migration.py tests/test_cli_surface.py tests/test_plugin_tools.py` — `102 passed`.
- Full suite: `831 passed, 2 skipped`.
- Dry-run smoke artifact: `~/.hermes/self-improvement/runs/run-20260528T023127Z.json`.
  - `matched_candidate_count: 10`
  - `matched_but_not_selected_count: 9`
  - `matched_but_not_selected_by_reason: {"Exact duplicate": 2, "not_selected_by_planner": 7}`
  - `matched_noop_class_counts: {"matched_existing_coverage": 2, "matched_needs_planner_rationale": 5, "matched_weak_or_generic": 2}`
  - `knowledge_routing.memory_routed_to_skill_count: 6`
  - `knowledge_routing.memory_routed_to_skill_dropped_count: 6`
  - `knowledge_routing.memory_routed_to_skill_dropped_by_reason: {"not_memory_workflow_to_skill": 6}`

**Objective:** Make the current loss modes visible before changing behavior.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Modify: `hermes_self_improvement/planner_runtime.py`
- Modify: `hermes_self_improvement/markdown_artifacts.py`
- Modify: CLI/report summary code if separate from markdown helpers
- Test: `tests/test_skill_planner.py`
- Test: memory/readiness/report tests covering planner-quality summaries

**Steps:**
1. Add failing tests for a run where a skill candidate has attached evidence but final planner decision is `skip/not_selected_by_planner`.
2. Add failing tests for memory decisions with `suggested_route: skill` that are not selected by the skill planner.
3. Add counters under planner quality / run artifact:
   - `matched_candidate_count`
   - `matched_but_not_selected_count`
   - `matched_but_not_selected_by_reason`
   - `memory_routed_to_skill_count`
   - `memory_routed_to_skill_selected_count`
   - `memory_routed_to_skill_dropped_count`
   - `cross_store_candidate_count`
4. Classify matched no-ops into at least:
   - `matched_existing_coverage`
   - `matched_weak_or_generic`
   - `matched_needs_planner_rationale`
   - `matched_actionability_loss`
5. Update compact tool payload and human report summaries so a future run cannot look simply `benign` when matched evidence was dropped without a specific no-op rationale.
6. Run focused tests, then full suite.

**Exit criteria:**
- The 2026-05-28 pattern would be reported as “matched evidence present, no mutation selected” rather than only `benign/not_selected_by_planner`.
- The report clearly separates benign no-op from weak/generic evidence and from dropped cross-store handoff.
- No mutation behavior changes yet.

---

### Slice 2 — Replace split planner decisions with knowledge transaction planning

**Status:** partially completed 2026-05-28; planner runtime now emits and consumes `knowledge_transactions` as the canonical planner output, and same-run artifacts now expose memory-to-skill cross-store candidates under top-level `knowledge_transactions`. Full planner-owned cross-store selection and unified editor execution remain for the next slice of work.

**Validation completed for planner-runtime contract:**
- RED/GREEN tests added for canonical planner output and quality-report consumption: `tests/test_skill_planner.py::test_planner_emits_knowledge_transactions_without_legacy_decisions_key`, `tests/test_skill_planner.py::test_planner_quality_report_reads_knowledge_transactions_as_canonical_contract`, `tests/test_skill_planner.py::test_render_planner_messages_requests_knowledge_transactions_contract`, `tests/test_runner_steps.py::test_skill_step_consumes_planner_knowledge_transactions_without_legacy_decisions`.
- Related focused tests: `tests/test_skill_planner.py tests/test_runner_steps.py tests/test_knowledge_maintenance_planner.py tests/test_markdown_artifacts.py tests/test_cli_surface.py` — passed.
- Full suite: `835 passed, 2 skipped`.
- Static checks: `python -m py_compile __init__.py hermes_self_improvement/*.py` and `git diff --check` passed.
- Dry-run smoke artifact: `~/.hermes/self-improvement/runs/run-20260528T040851Z.json`.
  - `planner_has_knowledge_transactions: true`
  - `planner_has_legacy_decisions: false`
  - `planner_status: completed`
  - `transaction_count: 45`

**Validation completed for cross-store artifact visibility:**
- RED/GREEN tests added for canonical memory-to-skill transaction surfacing: `tests/test_memory_to_skill_migration.py::test_knowledge_transactions_include_memory_to_skill_cross_store_candidate`, `tests/test_report_improve_connection.py::test_run_improve_exposes_cross_store_knowledge_transactions`.
- Related focused tests: `tests/test_memory_to_skill_migration.py tests/test_report_improve_connection.py tests/test_skill_planner.py tests/test_runner_steps.py tests/test_markdown_artifacts.py tests/test_cli_surface.py` — `153 passed`.
- Full suite: `837 passed, 2 skipped`.
- Static checks: `python -m py_compile __init__.py hermes_self_improvement/*.py` and `git diff --check` passed.
- Dry-run smoke artifact: `~/.hermes/self-improvement/runs/run-20260528T041611Z.json`.
  - `knowledge_transactions` present in stdout and run artifact.
  - `transaction_count: 45`
  - `memory_to_skill_count: 0` in this live dry-run, so the cross-store behavior is covered by deterministic tests rather than dogfood data.
  - top-level legacy `decisions` absent from the run artifact.

**Objective:** Delete the split skill/memory planning contract as the canonical path and make one knowledge transaction plan the only planner output consumed by execution.

**Files:**
- Modify: `hermes_self_improvement/planner.py`
- Modify: `hermes_self_improvement/planner_runtime.py`
- Modify: `hermes_self_improvement/planner_memory.py`
- Modify: `hermes_self_improvement/planner_targets.py`
- Modify: `hermes_self_improvement/runner_steps.py`
- Modify: prompt overlay/default planner text if stored in repo defaults
- Test: planner schema / planner-runtime / memory inventory planner tests

**Steps:**
1. Add a `knowledge_transaction` / `knowledge_transactions` artifact schema that can represent skill-only, memory-only, and cross-store operations.
2. Change planner output so execution consumes `knowledge_transactions` as the canonical result. Delete the old skill-decision and memory-decision planner outputs from the execution contract instead of maintaining compatibility views.
3. Normalize target stores to `skill`, `builtin_user`, `builtin_memory`, `external_memory`, `unresolved`, `none`.
4. Convert `not_memory_workflow_to_skill` from a terminal memory skip into a cross-store candidate that the planner must resolve inside the transaction plan: apply, skip with a specific reason, defer, or block.
5. Ensure memory duplicate/procedural entries can become `memory_to_skill` transaction candidates with source memory provenance.
6. Preserve hard safety/provenance checks outside the LLM: mutable local skill eligibility, pinned/archive/reference-skill guardrails, memory target/provider capability, exact old_text requirement for source removal.
7. Update planner prompt/context so it asks for knowledge placement and transaction planning, not separate skill/memory mutation decisions.
8. Add regression tests that fail if execution still reads independent `skill.decisions` / `memory.decisions` as primary planner outputs after `knowledge_transactions` are available.
9. Add tests for:
   - procedural memory duplicated across entries becomes a `memory_to_skill` candidate;
   - existing skill coverage yields a bounded `patch_skill_then_remove_or_replace_memory` transaction only when evidence is specific;
   - weak workflow evidence becomes `skip/matched_weak_or_generic`, not silent drop;
   - durable user preference remains `builtin_user`, not skill;
   - long contextual background routes to `external_memory` when configured.

**Exit criteria:**
- Planner output contains a unified `knowledge_transactions` section and runner execution uses it as the primary input.
- Independent skill/memory planner decisions are removed, not retained as compatibility or reporting views.
- Memory-routed workflow evidence is not lost between memory and skill steps.
- `actionability_loss_count` or its successor can detect cross-store drops.

---

### Slice 3 — Unified editor execution for mixed knowledge transactions

**Status:** partially completed 2026-05-28; `memory_to_skill` now has a single knowledge-transaction executor with add-before-remove semantics, unified result fields, and the existing migration runner records `transaction_result` instead of only split `skill_result` / `memory_remove_result` details. Remaining work is to make all skill-only, memory-only, and cross-store execution use this editor contract as the only runtime path and remove split schema leakage from reports/prompts.

**Validation completed for memory-to-skill transaction execution:**
- RED/GREEN tests added for direct mixed transaction execution and runner wiring: `tests/test_memory_to_skill_migration.py::test_execute_knowledge_transaction_patches_skill_then_removes_memory`, `tests/test_memory_to_skill_migration.py::test_execute_knowledge_transaction_keeps_memory_when_skill_patch_fails`, `tests/test_memory_to_skill_migration.py::test_memory_to_skill_migration_patches_skill_before_removing_memory`.
- Related focused tests: `tests/test_memory_to_skill_migration.py tests/test_report_improve_connection.py tests/test_memory_inventory_planner.py tests/test_memory_agent_dispatch.py tests/test_runner_steps.py` — `105 passed`.
- Full suite: `839 passed, 2 skipped`.
- Static checks: `python -m py_compile __init__.py hermes_self_improvement/*.py` and `git diff --check` passed.
- Dry-run smoke artifact: `~/.hermes/self-improvement/runs/run-20260528T051420Z.json`.
  - `knowledge_transactions` present.
  - `transaction_count: 45`.
  - `memory_to_skill_count: 0` and `memory_to_skill.status: no_candidates` in this live dry-run, so add-before-remove transaction execution is covered by deterministic tests rather than dogfood data.
  - top-level legacy `decisions` absent from the run artifact.

**Objective:** Make the editor execute transaction plans across skills and memory instead of dispatching two independent editor contracts.

**Files:**
- Modify: `hermes_self_improvement/editor.py`
- Modify: `hermes_self_improvement/editor_skill.py`
- Modify: `hermes_self_improvement/editor_memory.py`
- Modify: `hermes_self_improvement/editor_backend.py`
- Modify: `hermes_self_improvement/editor_backend_skill.py`
- Modify: `hermes_self_improvement/editor_backend_memory.py`
- Modify: `hermes_self_improvement/runner_steps.py`
- Test: editor unit tests, memory editor tests, skill editor tests, integration tests for transaction execution

**Steps:**
1. Add failing tests for a mixed transaction: patch an existing skill, verify, then replace/remove the source memory entry.
2. Add failing tests for add-before-remove: if skill patch fails, memory source remains unchanged.
3. Add failing tests for stale source memory: if source `old_text` no longer matches, skill patch may remain but memory removal is skipped/reported as partial verification failure according to the transaction contract.
4. Add failing tests that a memory transaction result cannot be parsed/validated as `skill_editor_result_*`.
5. Implement a single editor result schema with fields such as:
   - `success`
   - `outcome`
   - `changed_skills`
   - `created_skills`
   - `changed_memories`
   - `removed_memories`
   - `executed_steps`
   - `verification_notes`
   - `rollback_hints`
6. Delete old skill-editor and memory-editor result naming from runtime-facing code and tests; do not keep compatibility adapters for old result names.
7. Wire runner execution so a transaction with both skill and memory steps uses one editor task and one final result.
8. Preserve official-tool-only execution. Do not direct-edit skill files or memory provider databases.

**Exit criteria:**
- Mixed skill/memory transactions execute through one editor contract.
- Memory editor failures no longer show `skill_editor_result_*`.
- A failed destination mutation never removes source memory.
- Artifacts show partial success/failure per transaction step.

---

### Slice 4 — Remove old split semantics from prompts, summaries, readiness, and roadmap state

**Status:** partially completed 2026-05-28; episode recording, CLI action summaries, human-facing CLI action detail lines, and compact tool results now read top-level canonical `knowledge_transactions` when present instead of requiring split `step_decisions.skill/memory/memory_to_skill`. Compact tool results now expose `steps.knowledge_transactions.total/apply/defer/skip/block/by_kind/cross_store`. Planner normalization now accepts canonical `memory_to_skill` transactions, the planner prompt documents the cross-store transaction shape, and knowledge routing treats canonical `memory_to_skill` plus explicit planner skill transactions as selected evidence. Unanswered maintenance candidates now become canonical deferred planner transactions instead of silently dropped routed evidence, selected coverage candidates mark their representative unmatched evidence as handled, and active runtime producers now use `memory_convert_to_skill_update` rather than the old terminal `not_memory_workflow_to_skill` reason. Unified `build_editor_backend` now normalizes native skill/memory backend errors to `editor_*` so runtime-facing backend failures do not leak `skill_editor_*` / `memory_editor_*` schema names. Knowledge routing also exposes `unexplained_cross_store_drop_count` / `unexplained_cross_store_drop_by_reason` and the CLI summary renders those drops so readiness cannot look benign when memory-to-skill work was silently dropped. Remaining work is to remove the rest of split prompt/report/readiness wording.

**Validation completed for canonical summary/episode surfaces:**
- RED/GREEN tests added for canonical-only episode recording: `tests/test_episode_ledger.py::test_record_run_episodes_uses_canonical_knowledge_transactions_without_split_steps`.
- RED/GREEN tests added for canonical-only CLI/tool summaries: `tests/test_report_improve_connection.py::test_cli_action_summary_counts_canonical_knowledge_transactions_without_split_steps`, `tests/test_report_improve_connection.py::test_cli_action_bucket_lines_describe_canonical_knowledge_transactions_without_split_steps`, `tests/test_report_improve_connection.py::test_compact_tool_result_summarizes_canonical_knowledge_transactions_without_split_steps`.
- RED/GREEN tests added for unexplained cross-store drop visibility: `tests/test_memory_to_skill_migration.py::test_knowledge_routing_summary_reports_memory_to_skill_drop`, `tests/test_cli_surface.py::test_improve_summary_reports_memory_to_skill_migrations`.
- RED/GREEN tests added for planner-owned cross-store selection and routing accounting: `tests/test_knowledge_maintenance_planner.py::test_planner_accepts_memory_to_skill_knowledge_transaction_for_maintenance_candidate`, `tests/test_knowledge_maintenance_planner.py::test_planner_prompt_exposes_knowledge_maintenance_candidates`, `tests/test_memory_to_skill_migration.py::test_knowledge_routing_summary_counts_planner_memory_to_skill_transaction_as_selected`, `tests/test_memory_to_skill_migration.py::test_knowledge_routing_summary_counts_explicit_planner_skill_decision_as_selected`.
- RED/GREEN tests added for maintenance-candidate fallback handling: `tests/test_knowledge_maintenance_planner.py::test_planner_defaults_unanswered_maintenance_candidate_to_canonical_defer`, `tests/test_memory_to_skill_migration.py::test_knowledge_routing_summary_counts_maintenance_representatives_as_selected`.
- Related focused tests: `tests/test_episode_ledger.py tests/test_report_improve_connection.py tests/test_memory_to_skill_migration.py tests/test_runner_steps.py` — `78 passed`; cross-store routing focused slice — `18 passed`; planner/routing surface focused slice — `86 passed`; latest planner/routing/CLI focused slice — `89 passed`; editor backend schema leak slice — `62 passed, 1 skipped`.
- Full suite: latest `850 passed, 2 skipped`.
- Static checks: `python -m py_compile __init__.py hermes_self_improvement/*.py` and `git diff --check` passed.
- Dry-run smoke artifacts:
  - `~/.hermes/self-improvement/runs/run-20260528T053715Z.json`.
    - `knowledge_transactions` present in stdout and artifact.
    - `transaction_count: 45`.
    - top-level legacy `decisions` absent.
    - `action_summary: {'apply': 0, 'block': 0, 'defer': 0, 'skip': 45}` from canonical transactions.
    - `episodes_count: 45`, confirming episode recording consumes canonical transactions in the live CLI path.
  - `~/.hermes/self-improvement/runs/run-20260528T055459Z.json`.
    - `knowledge_routing.memory_routed_to_skill_count: 6`.
    - `memory_routed_to_skill_selected_count: 0`.
    - `memory_routed_to_skill_dropped_count: 6`.
    - `unexplained_cross_store_drop_count: 6` with `unexplained_cross_store_drop_by_reason: {'not_memory_workflow_to_skill': 6}`.
    - This confirmed the old cross-store drop mode was visible rather than hidden as benign readiness.
  - `~/.hermes/self-improvement/runs/run-20260528T060925Z.json`.
    - `transaction_count: 45`.
    - `memory_to_skill_transactions: 0` and `planner_skill_transactions: 45`.
    - `knowledge_routing.memory_routed_to_skill_count: 6`.
    - `memory_routed_to_skill_selected_count: 2`.
    - `memory_routed_to_skill_dropped_count: 4`.
    - `unexplained_cross_store_drop_count: 4` with `unexplained_cross_store_drop_by_reason: {'not_memory_workflow_to_skill': 4}`.
    - This confirmed canonical planner skill decisions counted as selected routed evidence, while remaining drops needed a follow-up planner selection quality slice.
  - `~/.hermes/self-improvement/runs/run-20260528T061952Z.json`.
    - `transaction_count: 45`.
    - `knowledge_routing.memory_routed_to_skill_count: 6`.
    - `memory_routed_to_skill_selected_count: 6`.
    - `memory_routed_to_skill_dropped_count: 0`.
    - `unexplained_cross_store_drop_count: 0`.
    - This confirms the old `memory -> suggested_route skill -> dropped` pattern is now either handled by canonical planner evidence selection or classified by canonical maintenance fallback handling.
  - `~/.hermes/self-improvement/runs/run-20260528T063609Z.json`.
    - `transaction_count: 45`.
    - `knowledge_routing.memory_routed_to_skill_count: 6`.
    - `memory_routed_to_skill_selected_count: 6`.
    - `memory_routed_to_skill_dropped_count: 0`.
    - `unexplained_cross_store_drop_count: 0`.
    - Saved artifact text no longer contains `not_memory_workflow_to_skill`; active producers now emit `memory_convert_to_skill_update` for workflow-shaped memory facts routed to skill.
  - `~/.hermes/self-improvement/runs/run-20260528T064220Z.json`.
    - `transaction_count: 46`.
    - `knowledge_routing.memory_routed_to_skill_count: 6`.
    - `memory_routed_to_skill_selected_count: 6`.
    - `memory_routed_to_skill_dropped_count: 0`.
    - `unexplained_cross_store_drop_count: 0`.
    - Saved artifact text contains none of `not_memory_workflow_to_skill`, `skill_editor_result`, `memory_editor_result`, `invalid_skill_editor_task`, `invalid_memory_editor_task`, `skill_editor_unavailable`, or `memory_editor_unavailable`.

**Objective:** Finish the migration so future agents cannot think the redesign is complete while skill/memory are still separate lanes.

**Files:**
- Modify: prompt overlay defaults / runtime seed docs if repo-tracked
- Modify: `hermes_self_improvement/markdown_artifacts.py`
- Modify: `hermes_self_improvement/cli.py`
- Modify: `README.md` / `AGENTS.md` if they still describe split skill/memory editors
- Modify: `.hermes/plans/README.md`
- Modify: `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`
- Modify: `.hermes/plans/2026-05-25-self-improvement-role-redesign.md`
- Test: report/CLI snapshot or focused summary tests

**Steps:**
1. Search active source/tests/docs for stale runtime wording: `skill_agent`, `memory_agent`, `skill_editor`, `memory_editor`, `not_memory_workflow_to_skill` as a terminal no-op.
2. Delete stale runtime-facing wording and keys rather than preserving compatibility aliases. Keep historical plan text only where explicitly archived/historical; update active plans and current-state sections.
3. If live runtime artifacts or prompt overlays still expose legacy role/schema residue, reset `${HERMES_HOME}/self-improvement` and re-run setup instead of writing migration shims.
4. Update summaries to report:
   - `knowledge_transactions.total/apply/skip/defer/block`
   - skill-only / memory-only / cross-store counts
   - matched-but-not-selected counts
   - memory-routed-to-skill selected/dropped counts
   - editor step validation counts
5. Update readiness classification so “ready” requires no unexplained cross-store drops and no schema split leaks.
6. Run a dry-run smoke and inspect the run artifact for the 2026-05-28 failure mode.
7. Update this plan, parent roadmap, and plan index with final validation results.

**Exit criteria:**
- Active docs describe one knowledge planner/editor transaction model.
- CLI/tool summaries make the transaction state understandable without opening raw JSON.
- A dogfood artifact verifies the old `memory -> suggested_route skill -> dropped` pattern is either selected as a transaction or explicitly classified with a precise reason.

---

## Verification commands

Use the project venv or runtime Python consistently:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
git diff --check
hermes self-improvement status
hermes self-improvement improve --dry-run --json > /tmp/self-improvement-knowledge-transaction-dryrun.json
python3 - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path('/tmp/self-improvement-knowledge-transaction-dryrun.json').read_text())
run = Path(payload['artifact_path'])
data = json.loads(run.read_text())
print('artifact', run)
print('action_summary', data.get('action_summary'))
print('planner_quality', data.get('planner_quality') or data.get('step_decisions', {}).get('knowledge_quality'))
print('knowledge_transactions', data.get('step_decisions', {}).get('knowledge_transactions'))
print('legacy_skill_decisions_present', 'skill' in data.get('step_decisions', {}))
print('legacy_memory_decisions_present', 'memory' in data.get('step_decisions', {}))
PY
```

If runtime state contains legacy prompt overlays or stale artifact assumptions after code migration, reset the runtime explicitly instead of preserving schema compatibility:

```bash
hermes self-improvement setup --reset --yes
hermes self-improvement status
```

Expected final smoke:

- No `skill_editor_result_*` error from knowledge editor results.
- No legacy top-level split `step_decisions.skill` / `step_decisions.memory` execution artifacts remain in final smoke output.
- Cross-store workflow evidence is visible as selected, precisely skipped, deferred, or blocked.
- `memory_routed_to_skill_dropped_count` is zero or explained by a specific reason that is not `not_selected_by_planner` alone.
- No mutation scope is widened beyond local mutable skills and official memory/provider tools.

---

## Commit sequence

Use separate commits so review can stop safely without hiding an incomplete architecture:

1. `docs: plan knowledge transaction unification`
2. `feat(self-improvement): report matched evidence routing gaps`
3. `feat(self-improvement): replace split planner outputs with knowledge transactions`
4. `feat(self-improvement): execute unified knowledge editor transactions`
5. `docs(self-improvement): mark knowledge transaction readiness`

If implementation must pause after commit 2 or 3, leave the roadmap status as **not ready / transaction unification incomplete**. Do not mark readiness complete until Slice 4 dogfood passes.
