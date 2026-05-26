# Turn-trace and Readiness Follow-up Plan

> **For Hermes:** This is the next implementation follow-up after `2026-05-25-self-improvement-role-redesign.md`. Keep slices small and TDD-first. Update this plan, the parent roadmap, and `.hermes/plans/README.md` after every landed slice.

**Parent plans:**
- `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`
- `.hermes/plans/2026-05-25-self-improvement-role-redesign.md`

**Goal:** Finish the unfinished part of the redesign: replace event-centric observation persistence with a first-class turn-trace/evidence-index model, then prove the runtime reaches a trustworthy steady state.

**Architecture:** Keep the current `planner / editor / evaluator / calibrator` role split and the current runtime safety boundaries. Do not add new roles, approval lanes, or side queues. Replace the observation substrate under the existing `improve`/`calibrate` flows: persist canonical turn-trace artifacts, build deterministic cluster summaries and evidence index/detail views from those traces, make planner read the index rather than raw event-derived digests, and then dogfood the resulting runtime long enough to judge quality/readiness from actual outcomes.

**Tech Stack:** Hermes standalone plugin, Python, pytest, existing observer hooks, self-improvement runtime artifacts under `~/.hermes/self-improvement/`, existing planner/editor/evaluator/calibrator prompt surfaces.

---

## Why this follow-up exists

As of 2026-05-26:

- Structural migration is mostly done.
- Runtime is healthy.
- Full suite is green.
- `improve --dry-run --json` produces evidence packs, run artifacts, and episodes.

But the redesign is still incomplete because:

1. Canonical observation persistence is still `state/events.jsonl`.
2. Planner still receives event-derived compact digests instead of a first-class evidence index/detail model.
3. Recent dry-runs still skew heavily toward `skip`, and outcome maturity is still mostly `unknown`.
4. Steady-state readiness is not yet proven by dogfood evidence.

This plan is therefore **not another naming cleanup**. It is the remaining execution path for the redesign.

---

## Current status snapshot

### Already done

- Public/runtime role surface is `planner / editor / evaluator / calibrator`.
- Old role names, module names, and primary artifact keys are gone from active runtime surfaces.
- Runtime setup is healthy (`initialized: yes`, active evaluator ready, prompt overlays ready).
- Validation baseline is green (`779 passed, 2 skipped`).

### Not done yet

- First-class stored turn traces.
- First-class cluster summary artifact.
- First-class evidence index/detail artifact and planner drilldown flow.
- Proof that the resulting planner produces better-than-current skip/unknown-heavy behavior.
- Final readiness report for the long-term roadmap.

---

## Slice map

### Slice A — Persist canonical turn-trace artifacts

**Objective:** Make per-turn trace artifacts the canonical persisted observation unit instead of relying on `events.jsonl` as the source of truth.

**Scope:**
- Add a runtime artifact directory for turn traces under `~/.hermes/self-improvement/`.
- Persist one turn-trace artifact per completed observed turn.
- Preserve enough structure to reconstruct tool/LLM/session behavior without rereading raw event logs.
- Keep `events.jsonl` only as compatibility/input during migration, not as the target model.

**Required fields:**
- turn_id
- session_id
- created_at
- platform
- user message preview / assistant response preview (redacted)
- ordered tool/LLM/api steps
- tool names, statuses, error kinds, preview hashes
- per-step provider/model/finish_reason when available
- outcome summary fields needed for later clustering

**Files likely touched:**
- `hermes_self_improvement/observer.py`
- `hermes_self_improvement/config.py`
- `hermes_self_improvement/evidence.py`
- `tests/test_observer.py`
- new focused trace tests

**Exit criteria:**
- A dry-run writes turn-trace artifacts.
- Trace ids are deterministic enough for replay/cluster tests.
- Existing report/improve/calibrate behavior does not regress.

---

### Slice B — Build deterministic cluster summary + evidence index/detail artifacts

**Objective:** Materialize the redesign’s observation layers as first-class runtime artifacts.

**Scope:**
- Build `cluster summary` from turn traces.
- Build `evidence index` from cluster summary.
- Build `evidence detail` records for selected clusters.
- Keep deterministic ordering, representative selection, and stable ids.

**Rules:**
- No LLM summarizer.
- No raw trace body in planner-facing index.
- Full raw trace remains audit/debug only.

**Files likely touched:**
- `hermes_self_improvement/evidence.py`
- `hermes_self_improvement/cli.py`
- `hermes_self_improvement/episodes.py`
- artifact rendering helpers / tests

**Exit criteria:**
- Re-running on the same trace set yields byte-stable cluster/index ids and ordering.
- CLI/report can point to cluster/index/detail artifacts.
- Planner-facing data can be built entirely from the new trace-derived artifacts.

---

### Slice C — Make planner consume evidence index/detail, not event-derived digests

**Objective:** Replace the current event/window-derived planner handoff with the new evidence-index/detail model.

**Scope:**
- Change planner digest builder to read the new evidence index.
- Add bounded detail-view selection for high-value clusters.
- Remove planner dependence on raw event windows as the primary context source.

**Important:**
- Keep planner context compact.
- Do not hand raw trace bodies to planner.
- Preserve deterministic target resolution / provenance helpers.

**Files likely touched:**
- `hermes_self_improvement/planner.py`
- `hermes_self_improvement/planner_runtime.py`
- `hermes_self_improvement/planner_memory.py`
- `hermes_self_improvement/planner_targets.py`
- `hermes_self_improvement/prompts.py`
- focused planner tests

**Exit criteria:**
- Planner input is index-first.
- Planner detail access is bounded and explicit.
- Old event-window-first handoff is no longer the canonical path.

---

### Slice D — Re-tune decision quality on top of the new observation model

**Objective:** Improve the practical behavior of the loop once planner is reading the right substrate.

**Scope:**
- Inspect why recent dry-runs skew to `skip`.
- Tighten evidence/actionability thresholds where they are too weak or too conservative.
- Improve `unknown` / `under observation` attribution quality only where supported by data.
- Do not widen mutation scope unsafely just to make `apply` counts go up.

**Data to watch:**
- `action_summary`
- `mutation_ready_count`
- `outcomes.improved / recurring / unknown`
- evidence counts by kind
- post-validation outcomes

**Exit criteria:**
- A dry-run no longer collapses into “almost everything skip” for reasons caused only by weak handoff structure.
- Outcome summaries become easier to interpret from actual runs, not just tests.

---

### Slice E — Steady-state dogfood and final readiness report

**Objective:** Convert the code-complete state into a trustworthy operational-complete state.

**Scope:**
- Run scheduled maintenance long enough to observe multiple windows.
- Check timeout behavior, apply/skip mix, outcome windows, and overlay generation summaries.
- Produce a repo-tracked readiness note that says either:
  - ready enough to call the roadmap complete, or
  - exactly what blocker remains.

**Output:**
- repo-tracked readiness report
- updated parent roadmap status
- updated plans index

**Exit criteria:**
- Readiness is judged from observed runs, not inferred from green tests.
- The roadmap is either explicitly completed or explicitly blocked with named reasons.

---

## Recommended implementation order

1. Slice A — canonical turn traces
2. Slice B — cluster/index/detail artifacts
3. Slice C — planner handoff migration
4. Slice D — quality retuning on new substrate
5. Slice E — steady-state readiness proof

Do not start Slice D before Slice C is in place. Otherwise quality tuning will optimize the wrong substrate.

---

## What to update after each slice

After each landed slice, update:

- this follow-up plan
- `.hermes/plans/2026-05-25-self-improvement-role-redesign.md`
- `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`
- `.hermes/plans/README.md`

Minimum status fields to update:
- implemented / partial / not started
- latest validation command/result
- latest runtime/dogfood artifact if relevant
- remaining blocker for the next slice

---

## Current next slice

**Start with Slice A — Persist canonical turn-trace artifacts.**

That is the first slice that changes the real unfinished core of the redesign. Everything after that depends on it.
