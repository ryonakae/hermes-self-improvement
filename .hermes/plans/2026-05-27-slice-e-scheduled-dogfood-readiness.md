# Slice E Plan — Scheduled dogfood and final readiness reporting

> **For Hermes:** This follows `2026-05-27-slice-d-quality-retuning.md`. Do not change planner thresholds or mutation guards unless the scheduled dogfood artifacts show concrete actionability loss.

**Parent plans:**
- `.hermes/plans/2026-05-26-turn-trace-and-readiness-followup.md`
- `.hermes/plans/2026-05-25-self-improvement-role-redesign.md`
- `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`

**Goal:** Confirm the D4 readiness handoff under scheduled runtime conditions, then write the final readiness report for this redesign pass.

**Status — 2026-05-27:** Planned / partially observed via manual dogfood. Slice D D1/D2/D3/D4 are implemented. Current readiness decision is `acceptable_with_scheduled_dogfood`, but the manual calibrate run showed cron-timeout risk.

**Manual dogfood observation — 2026-05-27 evening:**
- `self-improvement-calibrate.sh` was run directly in the plugin workdir and completed successfully, but only after exceeding the old 600s cron timeout budget (observed still running past 630s; final completion notification arrived later with exit code 0).
- Calibrate result: `Calibration: partial_update`; prompt overlay set promoted; evaluator skipped as `candidate_not_concrete`; candidate-set artifact `/Users/ryo.nakae/.hermes/self-improvement/evaluator/prompt-candidate-sets/20260527T111022Z-3e2a0ec82de3.json`.
- `self-improvement-maintenance.sh` was run directly and completed successfully, writing `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260527T111533Z.json`.
- Manual maintenance artifact included `skip_class_counts` and showed `actionability_loss 0` (`benign 45`, `needs_follow_up 2`).

---

## E1 — Observe separated scheduled runs

**Objective:** Prove the new cron split works in real scheduler execution.

Expected schedule:
- `self-improvement-calibrate`: daily `03:00`, local delivery, no-agent script, current global script timeout `1200s`.
- `self-improvement-autonomous-maintenance`: daily `04:00`, local delivery, no-agent script, current global script timeout `1200s`.

Acceptance criteria:
- Calibrate completes or exits with a safe `no_improvement` result; active prompt overlays remain readable.
- Maintenance completes without script timeout.
- A new maintenance run artifact is written after 04:00.
- The run artifact contains `step_decisions.skill.planner_quality.skip_class_counts`.
- The run summary does not show `actionability_loss_count > 0` without a concrete skill/cluster that can be inspected.

If failed:
- If calibrate times out but maintenance is healthy, keep the split and tune calibrate trigger/runtime separately.
- If maintenance times out, inspect whether `improve` or `report` is slow before changing script timeout.
- If both contend for artifacts, adjust schedule spacing before changing plugin logic.

---

## E2 — Interpret skip/readiness results

**Objective:** Decide whether the scheduled all-skip/low-apply behavior is acceptable.

Acceptable:
- Most skips are `benign`.
- `safe_stop` is explainable by no attached evidence or a protected boundary.
- `needs_follow_up` is already-covered workflow material or low-confidence diagnostic material.
- `actionability_loss` is zero.

Needs focused follow-up:
- `actionability_loss_count > 0` and the related cluster has a concrete `target_skill` plus medium/high/critical severity.
- Repeated `needs_follow_up` refers to the same uncovered workflow across scheduled runs.
- `cluster_evidence_count > 0` but every cluster-backed mutable candidate remains unselected for a reason that is not benign or safe.

Do not treat as failure:
- `apply=0` by itself.
- `no_improvement` from GEPA.
- High `unknown` outcome count while observation windows are still immature.

---

## E3 — Final readiness reporting

**Objective:** Close the follow-up redesign pass with a compact operator-readable readiness state.

Update after scheduled dogfood:
- this plan,
- `.hermes/plans/2026-05-26-turn-trace-and-readiness-followup.md`,
- `.hermes/plans/2026-05-25-self-improvement-role-redesign.md`,
- `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`,
- `.hermes/plans/README.md`.

Final report should state:
- latest calibrate and maintenance cron outputs,
- latest run artifact path,
- whether `skip_class_counts` is present and readable,
- readiness decision: `ready`, `acceptable_with_follow_up`, or `blocked`,
- exact next follow-up if not `ready`.

---

## Current next action

Tomorrow morning, after the next scheduled `03:00` / `04:00` run pair:

1. Inspect `self-improvement-calibrate` cron output and confirm whether `1200s` is enough for a clean completion.
2. Inspect `self-improvement-autonomous-maintenance` cron output and confirm it still completes cleanly after the split.
3. Open the newest maintenance run artifact and verify:
   - `step_decisions.skill.planner_quality.skip_class_counts` is present,
   - `actionability_loss_count == 0` unless there is a concrete cluster-backed skill to inspect,
   - the summary is still understandable as benign/safe-stop/needs-follow-up rather than opaque all-skip noise.
4. If both jobs complete and the maintenance artifact stays non-actionable, update Slice E / parent plan / roadmap / README with the final readiness decision.
5. If calibrate still exceeds `1200s`, do not touch planner thresholds first; decide between a further timeout increase and stricter calibrate trigger/gating based on the new cron evidence.
