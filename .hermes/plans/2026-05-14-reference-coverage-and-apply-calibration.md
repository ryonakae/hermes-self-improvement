# Reference Coverage and Apply Calibration Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Make self-improvement less confusing and less artificially conservative by feeding existing reference-skill coverage into planning, keeping rationale/reason coherent, and allowing bounded apply decisions when evidence is strong and no existing coverage exists.

**Architecture:** Keep the existing `improve` flow. Do not add a new lane, approval queue, or mutation mode. Program code should collect compact reference coverage and enforce hard safety boundaries; the LLM planner should decide `apply / defer / skip / block` with better context. Executor-side duplicate prevention remains as a final safety net, but duplicate/reference coverage should normally be visible before execution.

**Tech Stack:** Python, pytest, existing `hermes_self_improvement` modules (`target_resolver.py`, `improvement_planner.py`, `runner_steps.py`, `evidence.py`, CLI summary rendering).

**Parent roadmap:** `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`

**Related implemented milestones:**
- `.hermes/plans/2026-05-10-milestone-2-duplicate-existing-coverage.md`
- `.hermes/plans/2026-05-10-milestone-4-knowledge-inventory-maintenance.md`
- `.hermes/plans/2026-05-10-milestone-6-trustworthy-reporting.md`

**Implementation status:** implemented on 2026-05-14.

**Implemented summary:**
- Added shared workflow coverage aliases (`patch-tool-workflow -> safe-patch-usage`, timeout and sandbox/permission variants) and reference-skill coverage extraction from evidence packs without adding reference skills to mutation `skill_candidates`.
- Target resolution now separates mutable positives from `reference_positive_skills`; reference coverage is visible but never a valid attach/mutation target.
- Planner coverage fit and create-skill normalization now use alias/reference coverage, producing coherent no-op decisions with program-owned `rationale` and `next_action`.
- Runner duplicate/alias guards overwrite stale create rationales, keeping executor fail-closed while avoiding contradictory artifacts.
- CLI unresolved summaries group `create_skill_covered_by_existing_skill` as duplicate-prevented and include covered skill / next action details.

**Verification:**
- RED tests added first and failed for reference coverage, alias coverage, duplicate rationale, runner stale rationale, CLI coverage summary, and evidence-pack reference coverage.
- Focused tests: `141 passed` across target resolver, skill planner, runner steps, CLI surface, unmatched evidence, and knowledge-maintenance planner.
- Full verification: `python -m py_compile __init__.py hermes_self_improvement/*.py` and `python -m pytest tests -q` passed (`671 passed, 2 skipped`).
- Runtime smoke: `hermes self-improvement status --json` ready; `hermes self-improvement improve --dry-run --json` completed with `dry_run=True`, skill/memory changes 0 for the current window.

---

## Investigation Summary

The 2026-05-14 run produced:

- `timeout-workflow`: planner proposed `create_skill`; runner skipped with `reason=create_skill_duplicate_existing_skill` because the skill exists locally.
- The recorded `planner_decision.rationale` still said “no existing fit; new skill justified,” so the final decision looked internally inconsistent.
- `safe-patch-usage` exists as an available reference/root skill, but `patch-tool-workflow` is only covered via `CREATE_SKILL_COVERAGE_ALIASES` in `runner_steps.py`, after planning.

Root cause:

1. `target_resolver.build_target_resolution_digest()` only receives mutable `skill_candidates` from the evidence pack.
2. It intentionally drops non-mutable/reference skills from attach candidates, which is correct for mutation safety.
3. But it also fails to show those reference skills as coverage context, so the resolver/LLM can say `no_existing_skill_fit` even when `timeout-workflow`, `safe-patch-usage`, or `sandbox-permission-workflow` exists and should prevent creation.
4. `improvement_planner.build_improvement_planner_digest()` has a `reference_skills` concept, but it only sees `raw_candidates` already present in the evidence pack. The daily run's pack did not include root/built-in/external available skills, so reference coverage was incomplete.
5. `_normalize_create_skill_decision()` strips raw rationale only when it normalizes to skip at planner time. Runner-side duplicate skips preserve `base_decision.rationale` from the planner create proposal, causing reason/rationale mismatch.

Design stance:

- “入口は広げる、材料は弱・中・強に分ける、出口は厳しくする.”
- Strong repeated workflow evidence should reach planner/create when there is no existing editable or reference coverage.
- Existing non-mutable/reference skills should not be mutation targets, but they should prevent duplicate create proposals or convert them into coherent no-op/coverage accounting.
- Keep executor duplicate prevention as a fail-closed guard, but make it rare rather than the normal correction path.

---

## Non-goals

- Do not mutate built-in, hub, plugin-bundled, external-dir, or ambiguous-provenance skills.
- Do not add `auto_apply_with_ledger`, approval queues, or extra decision modes.
- Do not turn every timeout/patch/permission cluster into a new skill. One-off or weak clusters still skip/defer.
- Do not edit Hermes core for this slice.

---

## Subagent Review Adjustments

Three subagent reviews agreed the direction is sound, but the implementation plan must be tightened before coding:

1. Keep `skill_candidates` semantically narrow: **local mutable Hermes-created mutation candidates only**. Do not mix built-in / hub / plugin-bundled / external / ambiguous-provenance skills into that list.
2. Add a separate bounded field for non-mutating coverage context, named `reference_skill_coverage` or `reference_coverage_skills`, not `reference_skill_coverage`. Reference entries are never valid attach/mutation targets.
3. Split target-fit signals by semantics:
   - `positive` / `positive_skills`: mutable attach candidates only.
   - `reference_positive_skills`: non-mutating coverage only.
   - `recommendation=attach_existing_skill` is allowed only from mutable positives.
4. Archived reference skills must not block new skill creation. Active/stale pinned or built-in/reference skills may be shown as coverage, but never mutation targets.
5. Move workflow alias coverage, such as `patch-tool-workflow -> safe-patch-usage`, out of runner-only constants into a shared coverage utility used by planner/runner/reporting.
6. `create_skill_preview` is a dry-run/report presentation outcome only. Do not add it as a canonical planner decision. The canonical planner action remains `create_skill`.
7. Duplicate/reference no-op decisions must have program-owned top-level `rationale` / `next_action`; stale planner rationale may remain only under `planner_decision` and must not be rendered in CLI/daily summaries.
8. Report rows should answer “what actually happened?” by evidence theme: observed signal, strength, coverage, decision, actual outcome, and next action.

---

## Task 1: Add reference-skill coverage to target resolution digest

**Objective:** Let target resolution see non-mutable/reference skills as coverage context without making them attach/mutation targets.

**Files:**
- Modify: `hermes_self_improvement/target_resolver.py`
- Test: `tests/test_target_resolver.py`

**Step 1: Write failing test**

Add a test similar to:

```python
def test_target_resolution_digest_includes_reference_coverage_without_attach_target():
    pack = {"evidence": [{
        "id": "coverage_timeout",
        "kind": "knowledge_coverage_candidate",
        "theme": "timeout_workflow",
        "count": 8,
        "coverage": {"workflow_boundary": "timeout workflow", "evidence_count": 8},
    }]}
    skill_candidates = [
        {"name": "timeout-workflow", "description": "Long running timeout workflow", "mutable": False, "provenance": "builtin"},
        {"name": "herm-tui-development", "description": "Herm TUI workflow", "mutable": True, "provenance": "curator_agent_created"},
    ]

    digest = build_target_resolution_digest(pack, skill_candidates=skill_candidates)

    assert digest["reference_skill_coverage"] == [{
        "name": "timeout-workflow",
        "description": "Long running timeout workflow",
        "provenance": "builtin",
        "mutable": False,
    }]
    assert "timeout-workflow" not in [item["name"] for item in digest["skill_targets"]]
    signals = digest["candidates"][0]["target_fit_signals"]
    assert signals["reference_positive_skills"] == ["timeout-workflow"]
    assert signals.get("positive_skills", []) == []
    assert signals["recommendation"] == "unresolved"
```

**Step 2: Verify RED**

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_target_resolver.py::test_target_resolution_digest_includes_reference_coverage_without_attach_target -q
```

Expected: fail because `reference_skill_coverage` / `reference_positive_skills` do not exist.

**Step 3: Implement minimal code**

In `build_target_resolution_digest()`:

- Keep current `skill_targets` / `skill_targets_other_names` as mutable-only attach targets.
- Add `reference_skill_coverage` with relevant non-mutable/reference skills only; do not call these entries targets.
- Extend `_target_fit_signals()` to distinguish:
  - `positive` / `positive_skills`: mutable positive fits only
  - `reference_positive_skills`: reference/non-mutable coverage fits only
  - `negative`: existing negative signals
- Do not let reference positives make `recommendation=attach_existing_skill`.
- If only reference positives exist, recommendation must stay `unresolved` with a non-mutating hint such as `coverage_hint="covered_by_reference"` inside `target_fit_signals`; do not add a resolver decision mode.

**Step 4: Verify GREEN**

Run:

```bash
$PY -m pytest tests/test_target_resolver.py::test_target_resolution_digest_includes_reference_coverage_without_attach_target -q
$PY -m pytest tests/test_target_resolver.py -q
```

Expected: pass.

---

## Task 2: Feed reference coverage into planner digest before LLM planning

**Objective:** Make `improvement_planner` see that a create proposal overlaps an existing reference/root skill, so the planner can skip/no-op coherently instead of proposing creation. Note: exact non-mutable skills already present in `skill_candidates` may already become `reference_skills`; the RED test for this task should target alias/reference coverage that is currently missing, especially `patch_tool_workflow -> safe-patch-usage`, or should be treated as an integration test after Task 3.

**Files:**
- Modify: `hermes_self_improvement/improvement_planner.py`
- Test: `tests/test_skill_planner.py`

**Step 1: Write failing test**

Add a test where the evidence pack has a `knowledge_coverage_candidate` for `timeout workflow`, and `skill_candidates` contains a non-mutable `timeout-workflow` reference skill. Assert that `knowledge_maintenance.maintenance_candidates[0].coverage_fit` is `reference_only` and contains `timeout-workflow`.

```python
def test_planner_digest_marks_coverage_candidate_as_reference_only_when_reference_skill_exists():
    pack_data = pack()
    pack_data["skill_candidates"].append({
        "name": "timeout-workflow",
        "description": "Long-running timeout workflow",
        "mutable": False,
        "provenance": "builtin",
    })
    pack_data["evidence"].append({
        "id": "coverage_timeout",
        "kind": "knowledge_coverage_candidate",
        "theme": "timeout_workflow",
        "coverage": {
            "workflow_boundary": "timeout workflow",
            "evidence_count": 8,
        },
        "target_resolution_hint": {
            "maintenance_affordance": {"workflow_boundary": "timeout workflow"},
        },
        "likely_targets": [{"target": "skill", "weight": 0.8}],
    })
    pack_data["views"]["skill"].append("coverage_timeout")

    digest = build_improvement_planner_digest(pack_data)
    coverage_fit = digest["knowledge_maintenance"]["maintenance_candidates"][-1]["coverage_fit"]

    assert coverage_fit["kind"] == "reference_only"
    assert coverage_fit["fit_skills"] == ["timeout-workflow"]
    assert coverage_fit["match_target"] == "reference"
```

**Step 2: Verify RED**

Run:

```bash
$PY -m pytest tests/test_skill_planner.py::test_planner_digest_marks_coverage_candidate_as_reference_only_when_reference_skill_exists -q
```

Expected: fail if reference skills are not carried into `coverage_fit` for this shape.

**Step 3: Implement minimal code**

- Ensure `build_improvement_planner_digest()` treats non-candidate/non-mutable skills in `raw_candidates` as `reference_skills` and passes their names to `compute_coverage_fit_for_name()`.
- If the evidence pack lacks root/reference skills, add a bounded hook/config injection point for tests and runtime collection rather than shelling out from planner code. Candidate collection should remain outside planner normalization.

**Step 4: Verify GREEN**

Run:

```bash
$PY -m pytest tests/test_skill_planner.py::test_planner_digest_marks_coverage_candidate_as_reference_only_when_reference_skill_exists -q
$PY -m pytest tests/test_skill_planner.py -q
```

Expected: pass.

---

## Task 3: Collect available reference skill names for knowledge coverage

**Objective:** Prevent daily runs from missing obvious root/reference skills such as `timeout-workflow`, `safe-patch-usage`, and `sandbox-permission-workflow`.

**Files:**
- Modify: `hermes_self_improvement/evidence.py` as the primary evidence-pack assembly point.
- Modify: `hermes_self_improvement/runner_steps.py` only if runner-side final duplicate coverage needs shared alias helpers.
- Test: `tests/test_evidence.py` or an existing focused evidence-pack test; if the project has no suitable file, use `tests/test_runner_steps.py` only for runner integration.

**Design constraint:** `evidence_pack["skill_candidates"]` remains local mutable Hermes-created mutation candidates only. Add reference/root skill coverage through a separate field such as `reference_skill_coverage`, then render it into planner/target-resolution digests as coverage context.

**Step 1: Locate collection point**

Search for where `skill_candidates` is assembled and where Curator candidates are merged into the evidence pack. Do not call `skills_list` from hooks; this is runner/improve-time only.

**Step 2: Write failing test**

Use injected skill inventory / skill list function so tests do not depend on the real local environment. The test should assert that:

- mutable Hermes-created skills remain candidate mutation targets;
- non-mutable/root/reference skills are included as reference coverage context;
- reference skills are not eligible for mutation.

**Step 3: Implement minimal code**

- At improve-time, merge bounded skill inventory from the existing skill tool/Curator source into a separate `reference_skill_coverage` field, not into `skill_candidates`.
- Mark built-in/root/external/plugin skills as `mutable=False` and provenance `builtin`, `external`, `plugin-bundled`, etc.; expose them only as coverage context.
- Cap the reference list for LLM context. Prefer relevant names/descriptions only; do not dump all 100+ skills into the prompt.
- Include at least exact/alias candidates for observed workflow themes:
  - `timeout_workflow` → `timeout-workflow`
  - `patch_tool_workflow` / `patch-tool-workflow` → `safe-patch-usage`
  - `sandbox_permission_workflow` / `permission_denied` → `sandbox-permission-workflow` and/or Safehouse-specific skills when present
- Exclude archived references from duplicate blocking. Active/stale pinned or built-in/reference skills may be coverage only.

**Step 4: Verify GREEN**

Run the focused test and then:

```bash
$PY -m pytest tests/test_runner_steps.py tests/test_skill_planner.py tests/test_target_resolver.py -q
```

Expected: pass.

---

## Task 4: Normalize duplicate/reference create decisions coherently at planner time

**Objective:** If the planner still emits `create_skill` for an existing/reference-covered skill, the normalized decision should carry coherent no-op rationale and next action.

**Files:**
- Modify: `hermes_self_improvement/improvement_planner.py`
- Test: `tests/test_skill_planner.py`

**Step 1: Write failing tests**

Add or extend tests for:

1. exact duplicate mutable skill;
2. exact duplicate reference skill;
3. alias coverage (`patch-tool-workflow` covered by `safe-patch-usage`).

Assertions:

```python
assert decision["decision"] == "skip"
assert decision["noop_outcome"] in {"duplicate_prevented", "covered_by_existing_skill"}
assert decision["covered_by_existing_skill"] == "timeout-workflow"  # or covered_by_reference_skill
assert "new skill justified" not in decision.get("rationale", "").lower()
assert decision["next_action"] in {
    "use_existing_reference_skill",
    "patch_existing_mutable_skill_when_evidence_is_additive",
    "no_mutation_needed_existing_coverage",
}
```

**Step 2: Verify RED**

Run the new tests. Expected: fail because duplicate skip currently drops or preserves confusing rationale depending on where it is normalized.

**Step 3: Implement minimal code**

- In `_normalize_create_skill_decision()`, when create is blocked by duplicate/reference coverage, set a program-owned `rationale` and `next_action`.
- Preserve the raw planner rationale under a debug-only field such as `planner_rationale` only if needed, but do not show it as the main rationale in final decision summaries.
- Add alias coverage before executor through a shared coverage alias utility. `CREATE_SKILL_COVERAGE_ALIASES` in `runner_steps.py` should not be the only place that knows `patch-tool-workflow -> safe-patch-usage`; planner, runner, and reporting should use the same source of truth.

**Step 4: Verify GREEN**

Run:

```bash
$PY -m pytest tests/test_skill_planner.py -q
```

Expected: pass.

---

## Task 5: Make runner-side duplicate prevention overwrite stale create rationale

**Objective:** Keep executor fail-closed duplicate protection, but make its final artifact internally consistent even when the planner missed coverage.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Test: `tests/test_runner_steps.py`

**Step 1: Write failing test**

Extend the existing duplicate-create runner test to include a planner decision with `rationale="no existing fit; new skill justified"`. Assert the final runner decision does not expose that as top-level `rationale`.

**Step 2: Verify RED**

Run:

```bash
$PY -m pytest tests/test_runner_steps.py::test_skill_step_skips_create_skill_when_local_skill_already_exists -q
```

Expected: fail after adding the stronger assertion.

**Step 3: Implement minimal code**

When `_local_skill_exists(skill_name)` or alias coverage blocks creation:

- set top-level `rationale` to a program-owned coverage statement;
- optionally include `planner_rationale` inside `planner_decision` only, not as final top-level explanation;
- set `next_action` to `no_mutation_needed_existing_coverage` or `use_existing_reference_skill`.

**Step 4: Verify GREEN**

Run:

```bash
$PY -m pytest tests/test_runner_steps.py -q
```

Expected: pass.

---

## Task 6: Calibrate apply/defer behavior for strong uncovered workflow evidence

**Objective:** Avoid making the system too timid. Strong repeated workflow evidence with no editable or reference coverage should become an actionable `create_skill` proposal, not indefinite defer.

**Files:**
- Modify: `hermes_self_improvement/improvement_planner.py`
- Modify if needed: `defaults/prompt-overlays/improvement_planner.md` only if this is seed/default behavior, not runtime-private learned state.
- Test: `tests/test_skill_planner.py`, possibly `tests/test_knowledge_maintenance_planner.py`

**Step 1: Write failing test**

Add a deterministic/injected LLM-normalization test where:

- evidence is `knowledge_coverage_candidate` or unresolved maintenance affordance;
- `coverage_fit.kind == "no_existing_fit"`;
- evidence_count >= 5 for strong evidence, or >= 3 for medium preview-only evidence;
- no secrets/PII/destructive action;
- proposed skill name is valid and absent.

Assert planner normalization accepts `create_skill` with attached evidence.

**Step 2: Verify RED**

Run focused test. Expected: if current normalization already accepts it, the RED should instead target summary/reporting: ensure it is surfaced as actionable rather than hidden under generic defer.

**Step 3: Implement minimal code/prompt adjustment**

- Keep low recurrence as skip/defer.
- For `no_existing_fit` + medium/strong recurrence + reusable workflow boundary + valid evidence ids, let `create_skill` through.
- For `reference_only`, default to no-op/skip with coverage accounting. A companion skill is allowed only when repeated evidence demonstrates a specific uncovered sub-workflow outside the reference skill boundary, with explicit `reference_insufficient_reason`, no duplicate/alias overlap, and no secret/PII/destructive content.
- For `partial_overlap` with editable target, prefer `mutate_skill` patch over create.

**Step 4: Verify GREEN**

Run:

```bash
$PY -m pytest tests/test_skill_planner.py tests/test_knowledge_maintenance_planner.py -q
```

Expected: pass.

---

## Task 7: Improve unresolved/duplicate reporting language

**Objective:** Daily/report surfaces should answer “why no mutation?” without making healthy no-ops look like failure or contradiction.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Test: `tests/test_cli_surface.py`

**Step 1: Write failing test**

Create a summary fixture with:

- `reason=create_skill_duplicate_existing_skill`
- `covered_by_existing_skill=timeout-workflow`
- program-owned coherent `rationale`
- `next_action=no_mutation_needed_existing_coverage`

Assert the unresolved summary renders something like:

```text
duplicate prevented: 1; covered by timeout-workflow; next action: no mutation needed
```

and does not include stale “new skill justified” rationale.

**Step 2: Verify RED**

Run:

```bash
$PY -m pytest tests/test_cli_surface.py::test_unresolved_summary_renders_duplicate_coverage_next_action -q
```

Expected: fail until renderer is updated.

**Step 3: Implement minimal code**

- Keep existing reason buckets.
- Add `create_skill_covered_by_existing_skill` to the duplicate-prevented bucket if it is not already grouped.
- For duplicate/reference coverage, include `covered_by_*` and `next_action` compactly.
- Prefer evidence-theme rows that answer: observed signal, evidence strength (`weak|medium|strong`), coverage fit, decision, actual outcome, and next action.
- Do not expand the report with long planner prose.

Example report wording:

```text
timeout workflow: no mutation; strong evidence covered by reference skill timeout-workflow; duplicate create prevented; next action: use existing reference skill
patch tool workflow: no mutation; covered by reference skill safe-patch-usage; next action: no mutation needed
new recurring workflow: create_skill preview; strong uncovered evidence x6; no existing mutable/reference coverage
```

**Step 4: Verify GREEN**

Run:

```bash
$PY -m pytest tests/test_cli_surface.py -q
```

Expected: pass.

---

## Task 8: Runtime dry-run smoke against current evidence

**Objective:** Verify the specific 2026-05-14 confusion is resolved before any mutating run.

**Files:**
- No code files unless smoke reveals a gap.

**Step 1: Run static verification**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
git diff --check
```

Expected: all pass.

**Step 2: Run read-only status/report**

```bash
hermes self-improvement status
hermes self-improvement report --since-hours 24
```

Expected: status ok; report renders duplicate/reference coverage coherently.

**Step 3: Run improve dry-run**

```bash
hermes self-improvement improve --dry-run --json
```

Expected for current class of evidence:

- `timeout-workflow` is not proposed as a new skill when existing reference coverage is detected.
- `safe-patch-usage` coverage is visible for patch-tool evidence.
- If no mutation occurs, the reason is coherent: existing coverage / reference-only / no mutation needed, not “no existing fit; new skill justified.”
- If a genuinely uncovered recurring workflow appears in dry-run/reporting, it can be rendered as `create_skill_preview` / `would_create_skill` rather than indefinite defer; the canonical planner action remains `create_skill`.

---

## Task 9: Update plan index and roadmap status

**Objective:** Keep repo-tracked planning current.

**Files:**
- Modify: `.hermes/plans/README.md`
- Modify: `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`

**Steps:**

1. Add this plan under current active/follow-up plan in the index.
2. In the long-term roadmap, note this as a Milestone 2/4/6 hardening slice: reference coverage + apply/defer calibration.
3. After implementation, update status with exact verification counts.

---

## Exit Criteria

- Existing reference skills are visible as coverage context but not mutation targets.
- `timeout-workflow`, `safe-patch-usage`, and permission/sandbox workflow coverage do not produce contradictory `create_skill` → duplicate skip artifacts.
- Duplicate/reference no-ops have coherent top-level `reason`, `rationale`, `covered_by_*`, and `next_action`.
- Strong recurring uncovered workflow evidence can still become canonical `create_skill` with attached evidence; dry-run/report surfaces may render it as `create_skill_preview` / `would_create_skill`.
- Focused tests and full `pytest tests -q` pass.
- `hermes self-improvement improve --dry-run --json` shows the current daily evidence class is reported coherently.
