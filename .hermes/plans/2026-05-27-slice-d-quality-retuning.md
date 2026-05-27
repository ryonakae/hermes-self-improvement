# Slice D Detailed Plan — Quality retuning on the trace/index substrate

> **For Hermes:** This is the implementation-ready Slice D child plan for `2026-05-26-turn-trace-and-readiness-followup.md`. Keep changes small and TDD-first. Do not widen mutation scope just to increase apply counts.

**Parent plans:**
- `.hermes/plans/2026-05-26-turn-trace-and-readiness-followup.md`
- `.hermes/plans/2026-05-25-self-improvement-role-redesign.md`
- `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`

**Goal:** Make the new turn-trace → cluster summary → evidence index/detail substrate observable enough to tune planner behavior from real runs, then improve only the evidence/actionability boundaries that are proven too weak or too conservative.

**Status — 2026-05-27:** Active. D1 implemented and D2 observed. Planner quality counters now count first-class `cluster_evidence` entries and target-skill attachments from the index, not only legacy `evidence_resolution` rows. Latest dry-run (`run-20260527T070120Z`) shows the all-skip result is mostly legitimate duplicate/noise/diagnostic handling plus one safe no-evidence stop; do not relax mutation guards just to raise apply count. Validation: full suite `826 passed, 2 skipped`.

---

## Baseline observation

Dry-run artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260527T064547Z.json`

Observed summary:
- `action_summary`: `apply=0`, `defer=0`, `skip=63`, `block=0`.
- Skill decisions: 46 skips; 2 exact duplicate coverage skips, 44 local inventory candidates not selected by planner.
- Memory decisions: 17 skips; raw tool output / workflow-to-skill / diagnostic-only classifications look appropriate.
- New `cluster_evidence` is present in the run artifact and planner digest, but the planner quality report reported `cluster_evidence_count: 0` before D1 because it only counted legacy `evidence_resolution` rows.

Interpretation:
- The all-skip dry-run is not automatically wrong. Many skips are legitimate duplicate/noise/diagnostic outcomes.
- Before changing planner thresholds, the new substrate must be visible in quality/readiness metrics so future dry-runs show whether the planner is seeing and selecting trace-derived cluster evidence.

---

## D1 — Count index/detail cluster evidence in planner quality

**Status:** Implemented.

**Objective:** Make `planner_quality` reflect first-class cluster evidence from `digest.cluster_evidence.entries`.

**TDD:**
- Added `tests/test_planner_cluster_digest.py::TestPlannerRuntimeDigestClusterEvidence::test_quality_report_counts_index_cluster_evidence`.
- RED: `cluster_evidence_count` was `0` for a digest with two cluster index entries.
- GREEN: `build_planner_runtime_quality_report()` now counts cluster ids from `digest.cluster_evidence.entries`, attaches `target_skill` to `cluster_attached_candidate_count`, and counts selected cluster-backed skills.

**Verification:**
- `PY=${PYTHON:-.venv/bin/python}; $PY -m pytest tests/test_planner_cluster_digest.py::TestPlannerRuntimeDigestClusterEvidence::test_quality_report_counts_index_cluster_evidence -q` → `1 passed`.
- Focused compatibility: `tests/test_planner_cluster_digest.py` plus two existing planner quality tests → `10 passed`.

---

## D2 — Re-run dry-run and inspect quality deltas

**Status:** Implemented / observed.

**Objective:** Confirm runtime artifacts now show non-zero cluster-quality counters when cluster evidence exists.

**Dry-run artifact:** `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260527T070120Z.json`

Observed deltas:
- `action_summary`: `apply=0`, `defer=0`, `skip=69`, `block=0`.
- `cluster_evidence.entries`: 1.
- `planner_quality.cluster_evidence_count`: 1.
- `planner_quality.cluster_attached_candidate_count`: 1.
- `planner_quality.cluster_selected_count`: 0.
- `planner_quality.selected_with_evidence`: 0.
- `planner_quality.unmatched_evidence_count`: 56.

Skip classification:
- Skill decisions: 46 skips.
  - 2 are exact duplicate coverage skips (`timeout-workflow`, `terminal-preflight-workflow`).
  - 1 is `mutate_skill_without_attached_evidence` for `safe-patch-usage`; inspection showed that digest row had `attached_evidence_count: 0`, so the skip is a correct safety stop, not a threshold bug.
  - 43 are local inventory candidates not selected by planner.
- Memory decisions: 23 skips.
  - raw tool output / workflow-to-skill / diagnostic-only classifications look appropriate.

Interpretation:
- D1 fixed the structural observability bug: cluster evidence is now counted.
- The current all-skip run is mostly legitimate duplicate/noise/diagnostic behavior plus one safe stop for no attached evidence.
- Do not relax mutation guards just to increase apply count.

**Verification:**
- `hermes self-improvement improve --dry-run --json` completed and wrote `run-20260527T070120Z.json`.

**Exit criteria:** Met. The next work should target reporting/readiness classification or wait for stronger observed evidence, not force a mutation from this artifact.

---

## D3 — Tune only proven handoff/threshold defects

**Objective:** Improve decision quality without unsafe scope widening.

Allowed changes:
- Fix missing attachment between cluster evidence and existing mutable/reference coverage when the index has a concrete `target_skill`.
- Improve reporting so legitimate duplicate/noise skips are separated from actionability loss.
- Adjust deterministic thresholds only when artifact evidence shows the current threshold hides a durable, reusable procedural gap.

Not allowed:
- Create changes merely to reduce skip count.
- Treat generic terminal failures as actionable without workflow boundary or representative context.
- Add new roles, queues, approval lanes, or mutation targets.

---

## D4 — Readiness handoff

After D2/D3 are validated, update the parent follow-up plan, role redesign plan, roadmap, and README with:
- latest validation result,
- latest dry-run artifact path,
- whether remaining skip/unknown behavior is acceptable, blocked, or needs another focused D-slice.
