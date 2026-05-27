# Slice E Plan — Scheduled dogfood and final readiness reporting

> **For Hermes:** This follows `2026-05-27-slice-d-quality-retuning.md`. Do not change planner thresholds or mutation guards unless the scheduled dogfood artifacts show concrete actionability loss.

**Parent plans:**
- `.hermes/plans/2026-05-26-turn-trace-and-readiness-followup.md`
- `.hermes/plans/2026-05-25-self-improvement-role-redesign.md`
- `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`

**Goal:** Confirm the D4 readiness handoff under scheduled runtime conditions, then write the final readiness report for this redesign pass.

**Status — 2026-05-27:** Planned / waiting for scheduled dogfood. Slice D D1/D2/D3/D4 are implemented. Current readiness decision is `acceptable_with_scheduled_dogfood`.

---

## E1 — Observe separated scheduled runs

**Objective:** Prove the new cron split works in real scheduler execution.

Expected schedule:
- `self-improvement-calibrate`: daily `03:00`, local delivery, no-agent script.
- `self-improvement-autonomous-maintenance`: daily `04:00`, local delivery, no-agent script.

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

Wait for the next scheduled `03:00` / `04:00` dogfood run, then inspect cron outputs and the new run artifact before changing code.
