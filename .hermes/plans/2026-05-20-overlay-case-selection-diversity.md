# Overlay Case Selection Diversity Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Increase prompt-overlay GEPA optimizer cases from 3 to 5 and make selected runtime eval cases more diverse across source episodes / case types / targets, so calibration uses more of the 4000+ generated cases without blowing up runtime.

**Architecture:** Keep the existing `build_overlay_set_runtime_eval_cases(...) -> select_overlay_eval_cases(...) -> optimize_overlay_candidate_set(...)` flow. Change the default operator knob from `gepa_evaluator.overlay_max_cases: 3` to `5`, then improve only the deterministic selector so a single high-signal episode cannot consume most of the small optimizer budget. Do not add a new scoring subsystem, storage format, queue, or evaluator gate.

**Tech Stack:** Python, pytest, existing Hermes self-improvement runtime artifacts, DSPy/GEPA adapter.

---

## Current observation

**Status:** implemented. TDD focused tests, full pytest, status smoke, selector live-sample verification, and timed `calibrate --dry-run` passed. The five-case dry-run completed in 332.44s, produced `optimizer_case_count: 5`, and selected 5 distinct source keys across 4 overlay targets.

A recent `calibrate --dry-run` before this change produced:

- `runtime_eval_case_count`: 4081
- `optimizer_case_count`: 3
- selected cases:
  - `improvement_planner_overlay-daea87607218`
  - `skill_agent_overlay-ea1a80307991`
  - `memory_agent_overlay-9edd572100e8`
- all three selected cases came from the same episode: `episode-6f06a63570bcfa34`
- all three represented the same duplicate-skill archive event for `hermes-sandbox-permission-workflow -> sandbox-permission-workflow`

This means the current selector is signal-driven enough, but not diverse enough when the optimizer budget is tiny.

## Scope

Implement this slice only:

1. Default optimizer case budget: `3 -> 5`.
2. Selection diversity: prefer distinct `source_episode_id` / source identity before taking multiple cases from the same episode.
3. Preserve target balancing and high-signal preference.
4. Add compact selected-case source identity to existing candidate artifacts (`selected_case_signals[*].source_key` and, when present, `source_episode_id`) so dry-run diversity can be audited without large payloads. Do not expand tool summaries with full case bodies.

## Non-goals

- Do not delete old runtime eval cases or runtime artifacts.
- Do not change runtime eval case schema.
- Do not change GEPA scoring semantics, prompt overlay promotion gates, active pointer validation, or regression runner behavior.
- Do not increase `max_full_evals` in this slice.
- Do not run all 4081 cases through GEPA.

---

## Task 1: Lock the default case-budget change with tests

**Objective:** Make `overlay_max_cases` default to 5 and prevent accidental regression to 3.

**Files:**
- Modify: `hermes_self_improvement/config.py`
- Test: `tests/test_config_precedence.py` or existing config-default test location
- Optional docs: `config.example.yaml`

**Step 1: Write failing test**

Add or update a config-default test asserting:

```python
from hermes_self_improvement.config import load_config


def test_default_gepa_overlay_max_cases_is_five(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    config = load_config(None)
    assert config["gepa_evaluator"]["overlay_max_cases"] == 5
```

If `load_config(None)` is not the existing pattern, use the project’s current default-config test helper.

**Step 2: Verify failure**

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_config_precedence.py -q
```

Expected before implementation: failure showing current default is `3`.

**Step 3: Minimal implementation**

Change:

```python
"overlay_max_cases": 3,
```

to:

```python
"overlay_max_cases": 5,
```

in `hermes_self_improvement/config.py`.

**Step 4: Verify pass**

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_config_precedence.py -q
```

Expected: pass.

---

## Task 2: Add selector regression for episode diversity

**Objective:** Prove the selector does not spend a 5-case budget on multiple roles from the same episode before considering other high-signal episodes.

**Files:**
- Modify: `tests/test_prompt_gepa_adapter.py`
- Modify later: `hermes_self_improvement/prompt_gepa_adapter.py`

**Step 1: Extend test helper if needed**

Update `overlay_case(...)` test helper to accept source identity fields without making existing tests noisy:

```python
def overlay_case(..., source_episode_id=None, case_type=None, source_kind="episode"):
    ...
    case = {
        ...,
        "case_type": case_type or f"{target}_from_episode",
        "source_episode_id": source_episode_id,
        "source": {"kind": source_kind, "episode_id": source_episode_id},
        ...
    }
```

Keep existing default behavior stable.

**Step 2: Write failing diversity test**

Add a test like:

```python
def test_select_overlay_eval_cases_prefers_distinct_episodes_with_five_case_budget():
    cases = [
        overlay_case("improvement_planner_overlay", case_hash="sha256:e1-planner", source_episode_id="episode-1", changed=True, executed=True, expected={"decision": "archive_skill"}),
        overlay_case("skill_agent_overlay", case_hash="sha256:e1-skill", source_episode_id="episode-1", changed=True, executed=True, expected={"mutation": "changed"}),
        overlay_case("memory_agent_overlay", case_hash="sha256:e1-memory", source_episode_id="episode-1", changed=True, executed=True, expected={"mutation": "changed"}),
        overlay_case("evaluator_overlay", case_hash="sha256:e2-evaluator", source_episode_id="episode-2", outcome="rejected_by_user", expected={"recommendation": "defer"}),
        overlay_case("skill_agent_overlay", case_hash="sha256:e3-skill", source_episode_id="episode-3", changed=True, executed=True, expected={"mutation": "changed"}),
        overlay_case("improvement_planner_overlay", case_hash="sha256:e4-planner", source_episode_id="episode-4", outcome="failed", expected={"decision": "skip"}, decision="skip"),
    ]

    selected = select_overlay_eval_cases(cases, max_cases=5)

    assert len(selected) == 5
    assert len({case.get("source_episode_id") for case in selected}) >= 4
    assert [case["case_hash"] for case in selected[:4]] != [
        "sha256:e1-planner",
        "sha256:e1-skill",
        "sha256:e1-memory",
        "sha256:e2-evaluator",
    ]
```

The exact expected order should reflect the final deterministic algorithm, but the test must fail under the current selector that can take several high-signal cases from the same source before broadening.

**Step 3: Verify failure**

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_prompt_gepa_adapter.py::test_select_overlay_eval_cases_prefers_distinct_episodes_with_five_case_budget -q
```

Expected before implementation: fail.

---

## Task 3: Implement deterministic diversity-aware selection

**Objective:** Keep high-signal / target-balanced behavior while spreading a small budget across distinct sources.

**Files:**
- Modify: `hermes_self_improvement/prompt_gepa_adapter.py`
- Test: `tests/test_prompt_gepa_adapter.py`

**Implementation approach:**

Add a small source identity helper:

```python
def _case_source_key(case: dict[str, Any]) -> str:
    source_episode_id = str(case.get("source_episode_id") or "").strip()
    if source_episode_id:
        return f"episode:{source_episode_id}"
    source = case.get("source") if isinstance(case.get("source"), dict) else {}
    for key in ("episode_id", "run_id", "cluster_id", "artifact_path", "path"):
        value = str(source.get(key) or "").strip()
        if value:
            return f"{key}:{value}"
    return str(case.get("case_hash") or case.get("id") or id(case))
```

Then adapt `select_overlay_eval_cases(...)` so selection has two passes:

1. First pass: choose at most one case per source key, still cycling through `OVERLAY_TARGETS` and preferring high signal inside each target bucket.
2. Second pass: if budget remains, allow additional cases from already-used sources with the existing target-balanced behavior.

Important constraints:

- Preserve dedupe by `case_hash` / `id`.
- Preserve deterministic ordering by original input index for final output, as existing tests expect.
- Preserve existing behavior when fewer than `max_cases` distinct source keys exist.
- Define source identity consistently across all generated case families:
  - episode cases: `episode:<source_episode_id>` or `episode:<source.episode_id>`
  - improve-run cases: `run_id:<source.run_id>`
  - recurring unmatched cases: `cluster_id:<source.cluster_id>`
  - fallback: `artifact_path:<source.artifact_path>`, then `path:<source.path>`, then case hash/id
- Do not drop `extras` target handling.

**Step 1: Implement helper and first-pass source diversity**

Keep helper private in `prompt_gepa_adapter.py`.

**Step 2: Run focused tests**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_prompt_gepa_adapter.py -q
```

Expected: pass.

---

## Task 4: Propagate the 5-case default through candidate artifacts

**Objective:** Ensure live candidate generation uses 5 cases by default and records `optimizer_case_count: 5` when enough cases exist.

**Files:**
- Modify: `tests/test_prompt_candidate_optimizer.py`
- Modify if needed: `hermes_self_improvement/prompt_candidate_optimizer.py`

**Step 1: Add/adjust test**

Add a test using default config without an explicit `overlay_max_cases` override:

```python
def test_generate_overlay_candidate_set_uses_default_five_optimizer_cases(...):
    ...
    config = load_config(None)
    ...
    assert selected_cases == [(100, 5)]
    assert candidate_set["optimizer_case_count"] == 5
```

If the existing fake optimizer test is easier to extend, keep the explicit override test for `7` and add a separate default-budget test.

**Step 2: Verify**

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_prompt_candidate_optimizer.py -q
```

Expected: pass after Task 1; no extra implementation should be needed unless a fallback literal `or 3` still shadows the default.

**Step 3: Remove the stale fallback literal (mandatory)**

`prompt_candidate_optimizer.py` currently contains a fallback that can preserve the old budget when partial config or test fixtures omit the default:

```python
max_cases = int(gepa_config.get("overlay_max_cases") or 3)
```

Change it in the same slice as the default update:

```python
max_cases = int(gepa_config.get("overlay_max_cases") or 5)
```

This is not optional: leaving `or 3` would make the “default is 5” contract inconsistent outside fully normalized config paths. Do not introduce a second constant unless there is already a config constants pattern.

---

## Task 5: Document the operator knob lightly and expose compact source audit metadata

**Objective:** Make the 5-case budget discoverable and make selected-case diversity auditable without large artifacts in tool summaries.

**Files:**
- Modify: `config.example.yaml`
- Modify: `hermes_self_improvement/prompt_candidate_optimizer.py`
- Modify: `tests/test_prompt_candidate_optimizer.py`
- Modify: `README.md` only if it already has a calibration tuning section that mentions GEPA case counts

**Step 1: Add commented example**

In `config.example.yaml`, add a small commented block near calibration tuning:

```yaml
# Optional: tune GEPA prompt-overlay optimization cost/coverage.
# Default is 5. Higher values improve case diversity but can increase
# calibrate runtime and should stay within cron.script_timeout_seconds.
# gepa_evaluator:
#   overlay_max_cases: 5
```

**Step 2: Add compact audit fields to selected case signals**

Update `_selected_case_signal(...)` so each selected case signal includes:

```python
{
    "source_key": _case_source_key(case),
    "source_episode_id": case.get("source_episode_id") or source.get("episode_id"),
}
```

Only include compact identifiers. Do not include full `input`, full `expected`, full source paths, or raw evidence payloads in CLI/tool summaries.

Add a focused test asserting `selected_case_signals` carries `source_key` for default candidate generation.

**Step 3: Avoid over-documentation**

Do not list all `gepa_evaluator` defaults. Keep only the operator-relevant knob.

---

## Task 6: Full verification and dry-run timing check

**Objective:** Verify the change is safe and check whether 5 cases still fits the 600-second cron timeout.

**Commands:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests/test_prompt_gepa_adapter.py tests/test_prompt_candidate_optimizer.py tests/test_config_precedence.py -q
$PY -m pytest tests -q
hermes self-improvement status
git diff --check
```

Then run a timed dry-run with a timeout above the cron timeout for observation only:

```bash
/usr/bin/time -p hermes self-improvement calibrate --dry-run
```

Expected:

- no `regression_runner_not_configured`
- `optimizer_case_count` should be `5` when enough cases exist
- selected cases should not all come from the same `source_episode_id` when diverse candidates exist
- candidate artifact `selected_case_signals` should include compact `source_key` values for audit
- runtime should ideally remain below 600 seconds; if it exceeds 600 seconds, do not raise cron timeout blindly—first report the measured time and inspect whether the added cases or GEPA variance caused it

---

## Review checklist

- [ ] TDD tests fail before implementation and pass after.
- [ ] Default case budget is exactly 5, not hidden behind duplicate literals.
- [ ] Selector still prioritizes high-signal cases.
- [ ] Selector avoids same-episode clustering for tiny budgets.
- [ ] Existing target-balancing behavior remains covered.
- [ ] Dry-run artifact remains compact; no large case payloads in tool summaries.
- [ ] `selected_case_signals` exposes compact source keys for audit.
- [ ] No old runtime cases are deleted in this slice.
- [ ] 600-second cron timeout remains sufficient based on measured dry-run timing.
