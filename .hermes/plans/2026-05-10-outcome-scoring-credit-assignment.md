# Outcome Scoring / Credit Assignment Hardening Plan

> **For Hermes:** This is Slice E from `2026-05-10-self-improvement-long-term-roadmap.md`. Start here after mutation accounting, duplicate no-ops, reporting, and skill-quality summaries are trustworthy.

**Status:** planned / next.

**Goal:** Connect self-improvement changes to later outcomes, so executed mutations and prompt-overlay generations are treated as unproven until recurrence or improvement signals are observed.

**Architecture:** Use existing run artifacts, episode ledgers, and runtime eval cases. Add compact outcome windows and credit-assignment metadata; do not add a new mutation lane or approval queue.

---

## Scope

In scope:

- Track immediate / short / medium outcome windows for changed skills, memory mutations, and overlay generations.
- Record whether the same failure cluster or user correction recurs after a mutation.
- Distinguish `executed`, `validated`, `quality_good`, and `outcome_proven`.
- Feed useful outcome cases into calibration/runtime eval material.

Out of scope:

- Statistical proof over long histories.
- Reverting mutations automatically.
- Changing mutation policy based on a single outcome.

---

## Suggested Tasks

1. Inspect `episode_ledger.py`, `runtime_eval_cases.py`, and recent run artifacts.
2. Add RED tests for a changed skill whose failure cluster recurs and one whose cluster does not recur.
3. Add compact outcome fields such as:
   - `outcome_status: unknown | improved | regressed | recurring | insufficient_window`
   - `credit_window: immediate | short | medium`
   - `related_episode_ids`
4. Surface outcome status in summaries without overstating success.
5. Update roadmap/index after verification.

## Expected summary shape

```text
Outcomes:
- tracked: 3, proven improved: 1, recurring: 1, unknown: 1
- unproven changes remain under observation
```
