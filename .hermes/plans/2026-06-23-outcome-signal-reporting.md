# Outcome Signal Reporting Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Make daily self-improvement reports distinguish strict `proven improved` from report-only weak/medium outcome signals, without loosening credit assignment used by calibration/GEPA.

**Architecture:** Keep `proven improved` conservative in `credit_assignment.py`. Add a small report-facing outcome signal summary that derives `early positive` / `needs stronger attribution` labels from compact credit-assignment fields. If the report needs medium positive evidence, expose existing scored components from `credit_assignment.py` in the compact summary as display-only counts; do not change `_outcome_status()`. Render those labels in `cli.py` daily reports and maintenance output so operators can tell whether `proven improved: 0` means “no evidence” or “some weak positive evidence, not enough for strict proof.”

**Tech Stack:** Python stdlib, existing `hermes_self_improvement.cli`, `credit_assignment`, pytest.

**Implementation status:** Implemented in this worktree. `_outcome_status()` remains unchanged; `credit_assignment` now exposes display-only `outcomes.early_positive` counts, and `_outcome_summary_lines()` renders `Outcome signals` beside the existing strict `Outcomes` block.

---

## Current diagnosis

Recent cron evidence shows the loop is working but the report is too binary:

- `proven improved` remains `0` after several cron runs.
- `unknown breakdown` is dominated by `no later comparable observation` with a small `weak usage only` count.
- `scored window coverage` has started to move from immediate-only into short-window observations.
- The strict credit-assignment behavior is desirable for prompt/evaluator learning, but daily reports need a softer operator-facing signal.

Do **not** make weak positive signals count as `improved` for GEPA / calibration. Add report-only visibility first.

## Non-goals

- Do not loosen `_outcome_status()` so `weak_usage_only` becomes `improved`.
- Do not add a new pipeline, lane, approval mode, or cron job.
- Do not change mutation safety gates, planner decisions, or executor behavior.
- Do not call LLMs from report rendering.
- Do not mutate plugin skills, memory, or runtime artifacts as part of report generation.

## Desired report shape

Add an `Outcome signals` block near the existing `Outcomes:` section:

```text
Outcome signals:
- strict proven improved: 0
- early positive: weak skill usage 1; medium memory useful 0; quiet window 0
- still recurring: 13
- needs stronger attribution: no later comparable observation 906; weak usage only 1; insufficient window 80
```

Signal definitions:

- `strict proven improved`: existing strict `outcomes.improved`.
- `early positive / weak skill usage`: existing `outcomes.skill_usage_under_observation`; this remains unknown for strict scoring.
- `early positive / medium memory useful`: display-only count derived from scored components containing `memory_retrieved_useful`. If absent, render `0`; do not invent this from `quality_under_observation`.
- `early positive / quiet window`: display-only count derived from scored components containing `cluster_absent`. If compact summary does not expose it yet, Task 2 must expose it as report-only data.
- `still recurring`: existing `outcomes.recurring`.
- `needs stronger attribution`: `unknown_reasons`, `insufficient_window`, `quality_under_observation`, and `missing_evidence_under_observation`. These are not positive evidence.

Do not treat `quality_under_observation` as `likely helped`; it means quality is still being watched, not that the change helped.

## Implementation tasks

### Task 1: Add tests for report-only outcome signal labels

**Objective:** Lock the desired daily-report wording before implementation.

**Files:**
- Modify: `tests/test_cli_surface.py`
- Possibly modify: `tests/test_report_integration.py`

**Steps:**
1. Add a focused test around `_outcome_summary_lines()` with a compact `credit_assignment` payload containing:
   - `outcomes.improved = 0`
   - `outcomes.recurring = 2`
   - `outcomes.unknown = 3`
   - `outcomes.insufficient_window = 1`
   - `outcomes.skill_usage_under_observation = 1`
   - `outcomes.quality_under_observation = 1`
   - `outcomes.missing_evidence_under_observation = 1`
   - `outcomes.unknown_reasons = {"no_later_comparable_observation": 2, "weak_usage_only": 1}`
   - `outcomes.credit_windows = {"immediate": 1, "short": 1, "medium": 0, "long": 0}`
   - any new display-only positive counts from Task 2, such as `outcomes.early_positive = {"memory_retrieved_useful": 1, "quiet_window": 1}`
2. Assert the output still includes the existing strict line:
   - `proven improved: 0`
3. Assert the output now includes an `Outcome signals:` block.
4. Assert `weak skill usage 1` appears under early positive, but strict `proven improved` remains `0`.
5. Assert `quality_under_observation` / missing evidence are rendered under attribution/observation, not as helped/improved.
6. Run the focused test and verify it fails before implementation.

**Verification command:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_cli_surface.py -q -k 'outcome'
```

Expected before implementation: failure because `Outcome signals:` is absent.

### Task 2: Expose display-only positive component counts

**Objective:** Make medium/quiet positive report signals available without changing strict scoring.

**Files:**
- Modify: `hermes_self_improvement/credit_assignment.py`
- Test: `tests/test_cli_surface.py` or a focused credit-assignment test if one exists

**Steps:**
1. In `_outcome_status_summary()` or `compact_credit_assignment_summary()`, derive display-only counts from existing scored row components:
   - `memory_retrieved_useful`: count rows whose components include positive `memory_retrieved_useful`.
   - `quiet_window`: count rows whose components include positive `cluster_absent`.
2. Store them under a clearly report-facing key, for example `outcomes.early_positive`.
3. Do not use these counts to change `_outcome_status()` or `outcome_status_counts`.
4. Add a regression proving a row with `memory_retrieved_useful` can appear in `early_positive` while strict `improved` remains whatever `_outcome_status()` currently decides.

### Task 3: Add a small report-facing outcome signal helper

**Objective:** Derive operator-facing labels from compact credit assignment without changing scoring semantics.

**Files:**
- Modify: `hermes_self_improvement/cli.py`

**Steps:**
1. Add a helper near `_outcome_summary_lines()` such as `_outcome_signal_lines(outcomes: dict[str, Any]) -> list[str]`.
2. Inputs come only from `credit_assignment["outcomes"]`.
3. Compute:
   - `strict_improved = outcomes["improved"]`
   - `weak_skill_usage = outcomes["skill_usage_under_observation"]`
   - `memory_useful = outcomes.get("early_positive", {}).get("memory_retrieved_useful", 0)`
   - `quiet_window = outcomes.get("early_positive", {}).get("quiet_window", 0)`
   - `still_recurring = outcomes["recurring"]`
   - attribution gaps from `unknown_reasons`, `insufficient_window`, `quality_under_observation`, and `missing_evidence_under_observation`
4. Keep wording conservative. Prefer “early positive” over “likely helped” unless the count has stronger evidence.
5. Do not feed this helper back into `credit_assignment` or persisted scoring state.

**Implementation note:** Start with a simple helper that renders counts. Avoid a second scoring model. If there is no positive/unknown/recurring signal, return `[]`.

### Task 4: Render `Outcome signals` in daily report and maintenance output

**Objective:** Make the new block visible wherever `_outcome_summary_lines()` is used.

**Files:**
- Modify: `hermes_self_improvement/cli.py`

**Steps:**
1. In `_outcome_summary_lines()`, keep the existing `Outcomes:` block unchanged for compatibility.
2. After the strict tracked/proven line and before or after unknown breakdown, append `_outcome_signal_lines(outcomes)`.
3. Keep old strings used by existing tests stable unless the test is intentionally updated.
4. Ensure the report still includes:
   - `unknown breakdown`
   - `scored window coverage`
   - `skill usage under observation`
   - `quality under observation`

**Verification command:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_cli_surface.py tests/test_report_integration.py -q -k 'outcome or report'
```

Expected: all touched report tests pass.

### Task 5: Add JSON/report artifact compatibility assertions

**Objective:** Ensure the new summary is presentation-only and does not rewrite scoring fields.

**Files:**
- Modify: `tests/test_cli_surface.py` or `tests/test_report_integration.py`

**Steps:**
1. Add an assertion that compact credit assignment still reports `outcomes.improved` unchanged when `skill_usage_under_observation` is present.
2. If a test fixture uses `render_report()`, assert that the `operational_reports.credit_assignment.outcomes` values are not normalized or overwritten by rendering.
3. Keep the persisted report JSON shape compatible: do not require a new top-level schema field unless the implementation already stores rendered report text only.

**Verification command:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_cli_surface.py tests/test_report_integration.py -q
```

### Task 6: Update operations docs / plan index wording

**Objective:** Make future operators interpret `proven improved: 0` correctly.

**Files:**
- Modify: `README.md` only if it already documents daily report fields.
- Modify: `skills/operations/SKILL.md` if it contains daily report interpretation guidance.
- Modify: `.hermes/plans/README.md` to mark this plan as active/in progress when implementation starts and completed after verification.

**Steps:**
1. Add a short note: `proven improved` is strict credit-assignment evidence; `Outcome signals` is operator-facing weak/medium evidence.
2. Explicitly say weak usage is not used as strict proof for GEPA.
3. Do not add broad design prose.

### Task 7: Full verification and dogfood

**Objective:** Prove the report changed without breaking self-improvement runtime.

**Commands:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests/test_cli_surface.py tests/test_report_integration.py -q
$PY -m pytest tests -q
git diff --check
hermes self-improvement status
hermes self-improvement report --since-hours 24
```

**Expected:**
- tests pass
- status remains healthy
- report includes both strict `Outcomes:` and new `Outcome signals:` block
- `proven improved` remains strict and unchanged

## Commit sequence

1. `test: cover outcome signal report labels`
2. `feat: add report-only outcome signal summary`
3. `docs: explain strict and weak outcome signals`

## Acceptance criteria

- Daily reports no longer make `proven improved: 0` look like the only progress signal.
- `proven improved` remains strict for credit assignment / GEPA.
- Weak positive evidence is visible but clearly labeled as not proven.
- Existing report consumers/tests that expect `Outcomes:` continue to work.
- Full plugin test suite passes.
