# Slice D Detailed Plan — Quality retuning on the trace/index substrate

> **For Hermes:** This is the implementation-ready Slice D child plan for `2026-05-26-turn-trace-and-readiness-followup.md`. Keep changes small and TDD-first. Do not widen mutation scope just to increase apply counts.

**Parent plans:**
- `.hermes/plans/2026-05-26-turn-trace-and-readiness-followup.md`
- `.hermes/plans/2026-05-25-self-improvement-role-redesign.md`
- `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`

**Goal:** Make the new turn-trace → cluster summary → evidence index/detail substrate observable enough to tune planner behavior from real runs, then improve only the evidence/actionability boundaries that are proven too weak or too conservative.

**Status — 2026-05-27:** D1/D2/D3/D4 implemented. Planner quality counters now count first-class `cluster_evidence` entries and target-skill attachments from the index, not only legacy `evidence_resolution` rows. Skip/readiness classification now separates benign duplicate/inventory skips, safety stops, actionability loss, and needs-follow-up in planner quality, CLI summaries, and compact tool payloads. D4 readiness decision is `acceptable_with_scheduled_dogfood`: do not relax mutation guards; use the separated `03:00` calibrate / `04:00` maintenance cron run as the next proof point. Latest dry-run (`run-20260527T090319Z`) showed `actionability_loss 0` with only benign/safe-stop/needs-follow-up skip classes. Validation: full suite `827 passed, 2 skipped`.

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

## D3 — Skip/readiness classification

**Status:** Implemented.

**Objective:** Improve decision quality visibility without unsafe scope widening.

Implemented changes:
- `planner_quality` now records `skip_class_counts`, `skip_reasons_by_class`, and per-class counters for `benign`, `safe_stop`, `actionability_loss`, and `needs_follow_up`.
- CLI `improve` summaries now print skip classification lines before the Skill planner section.
- Compact improve tool payloads expose the same skip classification fields under `steps.skill_planner.quality`.

Allowed / preserved boundaries:
- No changes were made merely to reduce skip count.
- Generic terminal failures are not treated as actionable without workflow boundary or representative context.
- No new roles, queues, approval lanes, or mutation targets were added.

Classification policy:
- Duplicate / existing-coverage / unselected inventory skips are benign.
- No-attached-evidence mutation attempts are safety stops.
- Action-like skipped plans or medium/high/critical cluster target skips are actionability loss.
- Other skips are needs-follow-up rather than silently benign.

**TDD / verification:**
- RED/GREEN: `tests/test_skill_planner.py::test_planner_quality_report_classifies_skip_readiness`.
- RED/GREEN: `tests/test_cli_surface.py::test_improve_summary_is_curator_style_and_mentions_private_eval_cases` for CLI rendering.
- RED/GREEN: `tests/test_plugin_tools.py::test_improve_tool_returns_compact_llm_facing_summary` for tool payload propagation.
- Related suite: `tests/test_skill_planner.py tests/test_cli_surface.py tests/test_plugin_tools.py` → `87 passed`.
- Full suite: `PY=${PYTHON:-.venv/bin/python}; $PY -m pytest tests -q` → `827 passed, 2 skipped`.
- Compile/check: `py_compile` and `git diff --check` passed.

**Runtime smoke:**
- JSON dry-run wrote `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260527T090040Z.json` with `action_summary {'apply': 0, 'block': 0, 'defer': 0, 'skip': 70}` and `planner_quality.skip_class_counts {'benign': 46}`.
- CLI smoke later showed `Skipped: 65` with `benign 43`, `safe-stop 1`, `actionability-loss 0`, `needs-follow-up 2`, proving the human-facing report separates healthy skips from follow-up signals.

---

## D4 — Readiness handoff

**Status:** Implemented as documentation / operating handoff.

**Readiness decision:** `acceptable_with_scheduled_dogfood`.

D1/D2/D3 are sufficient for this Slice D pass:
- The new trace/index substrate is observable in planner quality.
- Skip-heavy runs are no longer opaque: D3 separates benign skips, safety stops, actionability loss, and needs-follow-up.
- Latest D3 artifacts show no current actionability-loss signal that justifies loosening mutation guards.
- Remaining `unknown` outcome volume is an outcome-observation/dogfood maturity issue, not a reason to force planner/editor mutations.

Latest evidence:
- Runtime healthy: plugin enabled, editor backend available, DSPy available, active evaluator ready, prompt overlays ready.
- Latest status sample: `turn traces: 213`, cluster summaries/indexes: `7`, latest run `run-20260527T090319Z.json`.
- D3 JSON smoke: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260527T090040Z.json` with `apply=0`, `skip=70`, `skip_class_counts {'benign': 46}`.
- D3 CLI smoke: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260527T090319Z.json` with `apply=0`, `skip=65`, `benign 43`, `safe_stop 1`, `actionability_loss 0`, `needs_follow_up 2`.
- Cron schedule is now separated: `self-improvement-calibrate` at `03:00` daily and `self-improvement-autonomous-maintenance` at `04:00` daily.

Interpretation:
- `actionability_loss=0` means there is no current evidence that planner is dropping a concrete, actionable cluster-backed mutation.
- `safe_stop=1` is acceptable because it preserves the no-attached-evidence guard.
- `needs_follow_up=2` is acceptable for now because the examples are already-covered workflow references; they should be watched, not forced into mutation.
- The old maintenance timeout remains in cron history but is explained by the pre-split GEPA/maintenance coupling. The next scheduled run is the proof point.

Dogfood acceptance criteria for the next scheduled run:
- `self-improvement-calibrate` completes at `03:00` without corrupting active prompt overlays; `no_improvement` is acceptable.
- `self-improvement-autonomous-maintenance` completes at `04:00` without script timeout.
- The maintenance run writes a new run artifact with `skip_class_counts` present under `step_decisions.skill.planner_quality`.
- If `actionability_loss_count > 0`, inspect the concrete skill/cluster before changing thresholds.
- If the run only shows benign skips / safe stops / already-covered needs-follow-up, proceed to Slice E final steady-state dogfood/reporting.

Do not do next:
- Do not relax mutation guards to reduce skip count.
- Do not classify generic terminal failures as actionable without concrete workflow boundary evidence.
- Do not add roles, queues, approval lanes, or mutation targets.

**Verification for D4 docs-only handoff:**
- D4 uses the already-validated D3 code path: full suite `827 passed, 2 skipped`, `py_compile` OK, `git diff --check` OK.
- Additional D4 runtime checks: `hermes self-improvement status`, latest run artifact inspection, `cronjob list`, and `hermes self-improvement report --since-hours 12`.
