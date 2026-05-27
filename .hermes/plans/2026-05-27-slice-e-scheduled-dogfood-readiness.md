# Slice E Plan — Scheduled dogfood and final readiness reporting

> **For Hermes:** This follows `2026-05-27-slice-d-quality-retuning.md`. Do not change planner thresholds or mutation guards unless the scheduled dogfood artifacts show concrete actionability loss.

**Parent plans:**
- `.hermes/plans/2026-05-26-turn-trace-and-readiness-followup.md`
- `.hermes/plans/2026-05-25-self-improvement-role-redesign.md`
- `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`

**Goal:** Confirm the D4 readiness handoff under scheduled runtime conditions, then write the final readiness report for this redesign pass.

**Status — 2026-05-28:** Implemented / ready. Slice D D1/D2/D3/D4 are implemented, and scheduled dogfood confirmed the split `03:00` calibrate / `04:00` maintenance flow under the current `1200s` cron script timeout. Final readiness decision: `ready`.

**Manual dogfood observation — 2026-05-27 evening:**
- `self-improvement-calibrate.sh` was run directly in the plugin workdir and completed successfully, but only after exceeding the old 600s cron timeout budget (observed still running past 630s; final completion notification arrived later with exit code 0).
- Calibrate result: `Calibration: partial_update`; prompt overlay set promoted; evaluator skipped as `candidate_not_concrete`; candidate-set artifact `/Users/ryo.nakae/.hermes/self-improvement/evaluator/prompt-candidate-sets/20260527T111022Z-3e2a0ec82de3.json`.
- `self-improvement-maintenance.sh` was run directly and completed successfully, writing `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260527T111533Z.json`.
- Manual maintenance artifact included `skip_class_counts` and showed `actionability_loss 0` (`benign 45`, `needs_follow_up 2`).

**Scheduled dogfood observation — 2026-05-28 morning:**
- `self-improvement-calibrate` (`1f7b37aef65a`) ran at `2026-05-28 03:03:41` and completed with cron status `ok`, well within the `1200s` script timeout.
- Calibrate result: `Calibration: partial_update`; GEPA trigger yes; prompt overlay set promoted; changed 3; evaluator skipped safely as `candidate_not_concrete`; candidate-set artifact `/Users/ryo.nakae/.hermes/self-improvement/evaluator/prompt-candidate-sets/20260527T180339Z-2e99cd503818.json`.
- `self-improvement-autonomous-maintenance` (`1d8bff2395e2`) ran at `2026-05-28 04:03:11` and completed with cron status `ok`, without script timeout.
- Maintenance wrote `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260527T190256Z.json`.
- Scheduled maintenance artifact included `skip_class_counts` and showed `actionability_loss_count 0`, `safe_stop_count 0`, `needs_follow_up_skip_count 0`; skip classes were benign-only (`benign 47`, `not_selected_by_planner 47`).
- Action summary was `apply 0 / defer 0 / skip 70 / block 0`, with actual mutations `skill 0`, `memory 0`, and prompt overlay/evaluator unchanged during maintenance.

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

Slice E scheduled dogfood is complete and the final readiness decision is `ready`.

No planner threshold or mutation-guard change is indicated by the scheduled evidence. Continue normal daily split operation:
- `self-improvement-calibrate`: `0 3 * * *`
- `self-improvement-autonomous-maintenance`: `0 4 * * *`

Only reopen this slice if a future scheduled artifact shows concrete `actionability_loss_count > 0`, repeated same-theme `needs_follow_up`, or a new cron timeout.
