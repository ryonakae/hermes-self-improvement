# Slice C Detailed Plan — Make planner consume evidence index/detail, not event-derived digests

> **For Hermes:** This plan refines Slice C from `2026-05-26-turn-trace-and-readiness-followup.md`. Use strict TDD. After each completed task, update the parent follow-up plan, the long-term roadmap, and `.hermes/plans/README.md`.

**Parent plans:**
- `.hermes/plans/2026-05-26-turn-trace-and-readiness-followup.md`
- `.hermes/plans/2026-05-25-self-improvement-role-redesign.md`
- `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`

**Goal:** Make the planner LLM read the evidence index first and drill into details only for selected clusters, replacing the current event-window-first handoff.

**Status — 2026-05-26:** ✅ Complete. PlannerRuntimeDigest accepts cluster artifacts, cluster_evidence section in digest, planner prompt renders cluster evidence as Markdown, skill improvement step wired. 825 tests passing.

**Architecture:** The current planner path is `events.jsonl → build_evidence_pack → build_planner_runtime_digest → render_planner_messages → LLM`. The new path adds `cluster_summary → evidence_index → evidence_detail` as the planner's primary context source, while keeping the evidence pack available as a compatibility/audit layer.

**Key insight from investigation:** `run_improve` already builds and persists `cluster_summary` and `evidence_index`, but does NOT pass them to the planner pipeline. They are only recorded in the run artifact. Slice C wires them into `run_skill_improvement_step` and the planner digest.

**Tech Stack:** Python, pytest, existing `evidence.py` builders, `planner_runtime.py` digest assembly, `runner_steps.py` pipeline.

---

## Scope boundaries

### In scope
- Thread cluster_summary and evidence_index into planner digests.
- Add bounded detail selection for high-value clusters to planner context.
- Make evidence_index the planner's primary context source.
- Retain evidence_pack as a compatibility/audit pass-through (not removed).
- Update planner prompt rendering to include cluster-level evidence.
- Add TDD tests for each layer.

### Out of scope
- Removing `build_evidence_pack` or `events.jsonl` flow (migration later).
- Changing the planner LLM prompt overlay format (keep existing overlay structure).
- Adding new roles, approval lanes, or side queues.
- Changing editor, evaluator, or calibrator paths.

---

## Task breakdown

### Task C1: Understand current planner flow

**Done.** Key findings:
- `planner_runtime.build_planner_runtime_digest(evidence_pack)` builds digest from event-derived evidence pack.
- It reads `evidence_pack["views"]["skill"]`, `evidence_pack["evidence"]`, `evidence_pack["skill_candidates"]`.
- `run_skill_improvement_step(evidence_pack=evidence_pack, config=config, mutate=mutate)` is the entry point.
- `cluster_summary_path` and `evidence_index_path` are recorded but not consumed.
- `build_evidence_detail` exists but has no consumer or persister yet.

### Task C2: RED tests — planner digests include cluster/index data

Write failing tests that verify:
1. `build_planner_runtime_digest` (or a new `build_planner_cluster_digest`) receives `cluster_summary` and `evidence_index` and surfaces them in the digest under `cluster_evidence`.
2. The digest includes `evidence_index_entries` (compact list from index).
3. For high-severity clusters, `evidence_detail` for selected clusters is bounded (max 3 clusters, max 5 traces each).
4. The digest retains `available_skill_evidence_ids` for compatibility but marks the source as `cluster_derived`.
5. `run_skill_improvement_step` accepts and passes `cluster_summary` and `evidence_index` kwargs.

### Task C3: GREEN — Add `cluster_evidence` section to planner digest

Implement:
1. Add `cluster_summary` and `evidence_index` parameters to `build_planner_runtime_digest` (keyword, optional, defaulting to empty).
2. When provided, build a `cluster_evidence` section:
   - `cluster_count`: from index
   - `entries`: from index.entries (compact, no detail bodies)
   - `high_severity_detail_count`: number of clusters with detail data
3. For clusters with severity `high` or `medium` (configurable), load evidence detail via `build_evidence_detail`.
4. Bound detail to max 3 clusters, 5 traces per cluster.
5. Add `cluster_evidence` to the digest dict alongside existing fields.

### Task C4: GREEN — Wire cluster artifacts into improve pipeline

1. Pass `cluster_summary` and `evidence_index` (already built in `run_improve`) to `run_skill_improvement_step`.
2. Thread through `runner_steps.py` to `build_planner_runtime_digest`.
3. Ensure `cluster_summary_path` and `evidence_index_path` remain in run artifact.

### Task C5: Update planner prompt rendering

1. In `prompts.py` (or wherever planner messages are rendered), add a section for cluster-level evidence.
2. Render `cluster_evidence` as Markdown:
   - Header with cluster count
   - Table of severity / tool / error_kind / count / target_skill
   - For clusters with detail, a compact "Detail" sub-section (max 3 traces, bounded)
3. Keep existing evidence pack rendering as a compatibility section (label it "Full event evidence (compat)").

### Task C6: Deprecation markings + tests

1. Add `# Deprecated: Slice C migration — use cluster_evidence instead` comments on the event-derived digest code path.
2. Ensure all tests pass: `pytest tests/ -q` must be 818+ passed.
3. Run `hermes self-improvement improve --dry-run --json` and verify the run artifact includes populated `cluster_evidence` in the planner digest.

### Task C7: plan/index updates + commit/push

Update:
- This plan status → implemented
- Follow-up plan → Slice C complete
- Long-term roadmap → Slice C status
- README.md → updated index
- Git commit + push

---

## Exit criteria

- Planner digest includes `cluster_evidence` section with index entries and bounded detail for high-severity clusters.
- `run_skill_improvement_step` receives `cluster_summary` and `evidence_index`.
- Old event-window-first path is still present but marked deprecated; no functionality is removed.
- `hermes self-improvement improve --dry-run --json` shows populated `cluster_evidence` in the planner digest.
- 818+ tests passing.