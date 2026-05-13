# Self-Improvement Resolver and Knowledge Promotion Plan

> **For Hermes:** This is a broader roadmap-style implementation plan, but each implementation slice must stay simple. Use the existing `improve` loop. Do not add a new command, lane, approval queue, apply mode, planner, or separate inventory subsystem.

**Goal:** Move the latest dry-run from “safe but mostly deferred” toward “understandable, explainable, and able to promote a small number of clear candidates” while keeping the design simple and tool-mediated.

**Architecture:** Keep the current pipeline: evidence pack → target resolver → planner → bounded skill/memory mutation. Add better evidence labels, summaries, and hints inside those existing structures. LLMs continue to make semantic decisions; deterministic code only supplies compact proof, hard safety metadata, and simple guardrails.

**Tech Stack:** Python, pytest, existing `hermes self-improvement improve --dry-run`, runtime artifacts under `${HERMES_HOME:-~/.hermes}/self-improvement/`, official Hermes `skill_manage`, built-in `memory`, and active external memory provider tools.

---

## Current context

Latest pushed baseline:

- `94d6e23 feat: add knowledge inventory resolver signals`
- Latest dry-run showed:

```text
Knowledge inventory:
- skills visible to LLM: 1/1, filtered: none
- memory entries: 26, duplicates: exact 0, near 2, stale pairs 1
Coverage gaps:
- candidates: 3
Target resolution:
- recommendations: defer_unresolved 6
Action summary:
- Would apply: 0, Deferred: 0, Skipped: 1, Blocked: 11
```

This is a real improvement over the older behavior. Generic tool failures are no longer forced into the only visible skill. The next goal is to make the unresolved group explainable and gradually promote clear cases into one of the existing five resolver outcomes:

```text
attach_existing_skill
create_new_skill
memory_candidate
defer_unresolved
skip_noise
```

The plan can be broad, but implementation must stay intentionally simple.

---

## Design constraints

Keep these hard constraints:

- Do not touch Hermes core.
- Do not add a new primary CLI command.
- Do not add a new lane, queue, approval mode, apply mode, or planner stage.
- Do not split inventory into a separate subsystem; inventory signals are evidence-pack inputs only.
- Do not introduce a new scoring framework.
- Keep user-facing action semantics as `apply / defer / skip / block`.
- Keep resolver semantic outcomes to the existing five choices.
- Skill patch/archive targets remain Hermes-created local mutable active/stale skills only.
- New skill creation is allowed only through `skill_manage(action="create")`.
- Memory changes are allowed only through the official `memory` tool or active provider-native memory tool.

Implementation style:

- Prefer small helper functions over new classes.
- Prefer adding fields to existing candidate dictionaries over introducing new object models.
- Prefer compact counts and top 3 examples in CLI output.
- Keep full detail in artifacts, not normal summaries.
- If a change needs a new subsystem, stop and write a separate follow-up plan.

---

## Desired end state

A good dry-run should answer four questions:

1. What did Hermes observe?
2. Which knowledge inventory issues exist?
3. Which unresolved candidates are close to skill creation, memory update, attach, or skip?
4. Why did Hermes still defer anything?

Example output:

```text
Knowledge inventory:
- skills visible to LLM: 1/1, filtered: none
- memory entries: 26, duplicates: exact 0, near 2, stale pairs 1
Coverage gaps:
- candidates: 3, recurring workflows 2, stale facts 1
Target resolution:
- recommendations: create_new_skill 1, memory_candidate 1, defer_unresolved 3, skip_noise 1
- deferred themes: timeout_workflow 2, terminal_preflight_workflow 1
- create-skill leaning: sandbox_permission_workflow 1
- memory leaning: stale_fact_pair 1
Action summary:
- Would apply: 0, Deferred: 3, Skipped: 1, Blocked: 8
```

This plan does **not** require automatic mutation to increase immediately. A dry-run that says “still deferred, and here is why” is acceptable if the explanation is useful.

---

## Phase 1: Explain unresolved candidates better

### Task 1: Add deferred theme breakdown to dry-run summary

**Objective:** Make `defer_unresolved` explain itself without changing mutation behavior.

**Files:**

- Modify: `hermes_self_improvement/cli.py`
- Test: `tests/test_cli_surface.py`

**Steps:**

1. Add failing test:

```python
def test_improve_summary_lists_deferred_target_resolution_themes():
    cli = load_cli_module()
    text = cli._render_improve_summary({
        "dry_run": True,
        "summary": {},
        "step_decisions": {"skill": {"target_resolution_digest": {"candidates": [
            {"theme": "timeout_workflow", "target_fit_signals": {"recommendation": "defer_unresolved"}},
            {"theme": "timeout_workflow", "target_fit_signals": {"recommendation": "defer_unresolved"}},
            {"theme": "sandbox_permission_workflow", "target_fit_signals": {"recommendation": "create_new_skill"}},
        ]}}}},
        "evidence_pack": {"summary": {}},
    })

    assert "- recommendations: create_new_skill 1, defer_unresolved 2" in text
    assert "- deferred themes: timeout_workflow 2" in text
    assert "- create-skill leaning: sandbox_permission_workflow 1" in text
```

2. Verify RED:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_cli_surface.py::test_improve_summary_lists_deferred_target_resolution_themes -q
```

3. Implement a small helper in `cli.py`:

```python
def _target_resolution_summary_lines(candidates: list[dict[str, Any]]) -> list[str]:
    ...
```

Rules:

- Count `target_fit_signals.recommendation`.
- Count `theme` for `defer_unresolved`.
- Count `theme` for `create_new_skill`.
- Count `theme` for `memory_candidate`.
- Count `theme` for `skip_noise`.
- Show at most 3 entries per category.
- Do not print full evidence snippets or context windows.

4. Verify GREEN:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_cli_surface.py::test_improve_summary_lists_deferred_target_resolution_themes tests/test_cli_surface.py::test_improve_summary_reads_nested_skill_target_resolution_digest -q
```

---

## Phase 2: Improve promotion hints without auto-applying

### Task 2: Add simple promotion hints to coverage-gap candidates

**Objective:** Help the LLM identify obvious create-skill candidates using existing evidence fields.

**Files:**

- Modify: `hermes_self_improvement/evidence.py`
- Test: `tests/test_unmatched_evidence_candidates.py`
- Test: `tests/test_target_resolver.py`

**Steps:**

1. Add failing test:

```python
def test_coverage_candidate_marks_create_skill_promotion_hints():
    items = collect_knowledge_coverage_candidates([
        {"id": "u1", "kind": "unmatched_improvement_candidate", "theme": "sandbox_permission_workflow", "count": 5, "rationale": "Repeated sandbox failures"}
    ], skill_candidates=[], existing_memory_entries=[])

    hints = items[0]["target_resolution_hint"]["promotion_hints"]
    assert hints == {
        "recurring": True,
        "has_workflow_boundary": True,
        "no_existing_skill_fit": True,
    }
```

2. Implement `promotion_hints` in `make_knowledge_coverage_candidate()`:

```python
"promotion_hints": {
    "recurring": evidence_count >= 2,
    "has_workflow_boundary": bool(workflow_boundary),
    "no_existing_skill_fit": resolution_kind == "create_new_skill",
}
```

3. Ensure `build_target_resolution_digest()` preserves these hints via existing `target_resolution_hint` pass-through.

4. Verify:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_unmatched_evidence_candidates.py tests/test_target_resolver.py -q
```

### Task 3: Add simple negative promotion hints

**Objective:** Help the resolver avoid promotion when evidence is too weak.

**Files:**

- Modify: `hermes_self_improvement/target_resolver.py`
- Test: `tests/test_target_resolver.py`

**Steps:**

1. Add tests for two negative hints:

```python
def test_target_fit_signals_mark_low_recurrence_as_skip_leaning():
    pack = {"evidence": [{"id": "u1", "kind": "unmatched_improvement_candidate", "theme": "terminal_preflight_workflow", "count": 1}]}
    digest = build_target_resolution_digest(pack, skill_candidates=[])
    signals = digest["candidates"][0]["target_fit_signals"]
    assert "low_recurrence" in signals["negative"]
    assert signals["recommendation"] == "skip_noise"
```

```python
def test_target_fit_signals_keep_generic_repeated_failure_deferred_without_boundary():
    pack = {"evidence": [{"id": "u1", "kind": "unmatched_improvement_candidate", "theme": "timeout_workflow", "count": 5}]}
    digest = build_target_resolution_digest(pack, skill_candidates=[])
    signals = digest["candidates"][0]["target_fit_signals"]
    assert "missing_workflow_boundary" in signals["negative"]
    assert signals["recommendation"] == "defer_unresolved"
```

2. Implement by extending existing `_target_fit_signals()` only.

Simple rules:

- `count <= 1` → `skip_noise` recommendation.
- repeated generic failure without `coverage.workflow_boundary` → `defer_unresolved`.
- do not block LLM from choosing differently; this is a recommendation only.

3. Verify:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_target_resolver.py -q
```

---

## Phase 3: Make resolver prompt explicit but short

### Task 4: Extract and simplify target resolver prompt helper

**Objective:** Nudge the LLM to use the existing five outcomes correctly without adding a rubric engine.

**Files:**

- Modify: `hermes_self_improvement/target_resolver.py`
- Test: `tests/test_target_resolver.py`

**Steps:**

1. Add failing test:

```python
def test_target_resolver_prompt_keeps_simple_five_choice_guidance():
    prompt = build_target_resolver_prompt({"candidates": [], "skill_targets": []})

    assert "attach_existing_skill" in prompt
    assert "create_new_skill" in prompt
    assert "memory_candidate" in prompt
    assert "defer_unresolved" in prompt
    assert "skip_noise" in prompt
    assert "approval" not in prompt.lower()
    assert "lane" not in prompt.lower()
    assert "queue" not in prompt.lower()
```

2. Extract current inline prompt into:

```python
def build_target_resolver_prompt(digest: dict[str, Any]) -> str:
    ...
```

3. Keep the guidance compact:

```text
attach_existing_skill: only listed skill with positive fit.
create_new_skill: recurring procedural workflow with boundary and no existing skill fit.
memory_candidate: durable fact/preference/environment detail.
defer_unresolved: useful evidence but target unclear.
skip_noise: one-off, transient, or already-handled noise.
```

4. Verify:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_target_resolver.py -q
```

---

## Phase 4: Make memory inventory candidates actionable without adding machinery

### Task 5: Promote clear stale memory pairs into existing memory mutation planning

**Objective:** If a stale memory pair is clear enough, let the existing planner/memory mutation path choose `apply` through the official memory tool. Do not stop at a permanent “defer hint” just because memory is sensitive.

**Files:**

- Modify: `hermes_self_improvement/evidence.py`
- Modify: `hermes_self_improvement/planner.py` or existing memory planner path only if needed
- Test: `tests/test_evidence_inventory_candidates.py`
- Test: `tests/test_memory_inventory_planner.py` or the closest existing memory planner test

**Simple rule:**

A stale memory pair may be `apply`-leaning only when all of these are true:

- exactly two entries are involved;
- both entries have the same target (`memory` or `user`), not mixed;
- one entry looks newer/current by deterministic evidence already available in the pair ordering or source metadata;
- both entries share a strong subject phrase;
- neither entry looks like a secret, credential, temporary task state, or uncertain design draft.

Otherwise it remains `defer`.

This is intentionally not a new scoring system. It is a small preflight that separates “obvious stale replacement” from “needs planner judgment”.

**Steps:**

1. Add failing test for an apply-leaning stale pair:

```python
def test_clear_stale_memory_pair_has_apply_leaning_memory_candidate_hint(tmp_path):
    memory = tmp_path / "MEMORY.md"
    memory.write_text("Hermes runtime root is /opt/data.\n§\nHermes runtime root is ~/.hermes.\n", encoding="utf-8")

    item = collect_memory_inventory_candidates(memory_paths={"memory": memory})[0]

    assert item["inventory"]["group_kind"] == "stale_fact_pair"
    assert item["target_resolution_hint"]["resolution_kind"] == "memory_candidate"
    assert item["target_resolution_hint"]["suggested_action"] == "apply"
    assert item["target_resolution_hint"]["memory_operation_hint"]["operation"] in {"memory_replace", "memory_delete"}
```

2. Add failing test for an ambiguous stale pair staying deferred:

```python
def test_ambiguous_stale_memory_pair_stays_deferred(tmp_path):
    memory = tmp_path / "MEMORY.md"
    memory.write_text("Project X may use path A.\n§\nProject X may use path B.\n", encoding="utf-8")

    item = collect_memory_inventory_candidates(memory_paths={"memory": memory})[0]

    assert item["target_resolution_hint"]["resolution_kind"] == "memory_candidate"
    assert item["target_resolution_hint"]["suggested_action"] == "defer"
```

3. Implement a tiny helper in `evidence.py`:

```python
def _stale_memory_pair_action_hint(entries: list[dict[str, Any]]) -> dict[str, Any]:
    ...
```

Return either:

```python
{"suggested_action": "apply", "memory_operation_hint": {"operation": "memory_replace", ...}}
```

or:

```python
{"suggested_action": "defer", "reason": "ambiguous_stale_pair"}
```

Keep it conservative, but not toothless. If the pair is clearly obsolete → current, expose an apply-leaning operation hint.

4. Ensure the existing memory planner can consume the hint without a new path. If the current memory planner already reads inventory candidates, add only the minimum field mapping needed. If it does not, add a focused test and small adapter to translate `memory_operation_hint` into the existing `memory_replace` / `memory_delete` operation shape.

5. Verify:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_evidence_inventory_candidates.py tests/test_memory_inventory_planner.py -q
```

### Task 6: Add memory leaning summary line

**Objective:** Show stale memory candidates in dry-run summary without exposing memory contents, including whether any are apply-leaning.

**Files:**

- Modify: `hermes_self_improvement/cli.py`
- Test: `tests/test_cli_surface.py`

**Steps:**

1. Add a summary test with a `memory_candidate` recommendation and theme `stale_fact_pair`.
2. Expect:

```text
- memory leaning: stale_fact_pair 1
```

3. Reuse `_target_resolution_summary_lines()` from Task 1.

---

## Phase 5: Keep create-skill conservative but visible

### Task 7: Add create-skill candidate preview details to dry-run artifact only

**Objective:** Make create-skill leaning candidates inspectable without bloating CLI output.

**Files:**

- Modify: `hermes_self_improvement/evidence.py` or existing candidate payload shape only if needed.
- Test: `tests/test_unmatched_evidence_candidates.py`

**Steps:**

1. Ensure `create_skill_affordance` already includes:

```text
workflow_boundary
not_memory_because
not_existing_skill_because
evidence_count
candidate_skill_name_seed
disallowed_if
```

2. Add or update test asserting all fields exist.
3. Do not add another preview object unless existing affordance is insufficient.
4. Do not add a new CLI section unless dry-run remains hard to interpret after Task 1.

---

## Phase 6: Dogfood and tune with one dry-run artifact

### Task 8: Full validation

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
hermes self-improvement status
git diff --check
```

Expected:

- All tests pass.
- status OK.
- diff check clean.

### Task 9: Dry-run dogfood

Run:

```bash
hermes self-improvement improve --dry-run --scorer llm
```

Expected:

- `Target resolution` includes aggregate recommendations.
- `defer_unresolved` includes theme breakdown.
- Any `create_new_skill` leaning item has recurrence + boundary + no existing skill fit.
- Any `memory_candidate` leaning item is represented without full memory text in CLI output.
- No skill or memory mutation occurs in dry-run.

### Task 10: Inspect artifact if needed

Only if the summary looks suspicious, inspect:

- `step_decisions.skill.target_resolution_digest.candidates`
- `evidence_pack.summary.coverage_candidate_count`
- `evidence_pack.summary.inventory_health`

Do not broaden implementation based on one dry-run unless the evidence shape is clearly wrong.

### Task 11: Docs and commit

Docs likely to update:

- `README.md`
- `skills/operations/SKILL.md`
- `.hermes/plans/README.md`

Commit:

```bash
git add hermes_self_improvement/evidence.py hermes_self_improvement/target_resolver.py hermes_self_improvement/cli.py tests README.md skills/operations/SKILL.md .hermes/plans/
git commit -m "feat: explain deferred self-improvement targets"
git push
```

---

## Risks and guardrails

### Risk: The resolver over-promotes weak candidates

Guardrails:

- Promotion hints are evidence fields only.
- No new auto-apply rule.
- Mutating run still goes through planner and official tools.

### Risk: CLI output gets noisy

Guardrails:

- Top 3 themes only.
- Counts, not snippets.
- Full details stay in artifact.

### Risk: stale memory pair looks safer than it is

Guardrails:

- `suggested_action` is `defer`, not `apply`.
- Actual mutation still requires planner + official memory tool.

### Risk: complexity creeps back in

Guardrails:

- No new classes unless unavoidable.
- No new command/lane/queue/mode.
- No new scoring subsystem.
- If a change needs a subsystem, stop and write a separate plan.

---

## Completion criteria

This plan is complete when:

- Dry-run explains unresolved candidates by theme.
- Coverage-gap candidates expose small promotion hints.
- Resolver prompt uses the five choices clearly and briefly.
- Low recurrence can become skip-leaning.
- Clear stale memory pairs become deferred memory-candidate hints.
- Full tests pass.
- Dry-run is easier to interpret without increasing mutation risk.
