# LLM Model Routing Spec and Memory Extractor Role Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Make self-improvement LLM model routing explicit, test-backed, and easy to explain; promote `memory_extractor` to a first-class tool-free model role instead of leaving it as an implicit `auto/None` fallback.

**Architecture:** Keep the current simple role split. Tool-using roles run through Hermes-native constrained agents with explicit toolsets/whitelists. DSPy/GEPA and `memory_extractor` remain tool-free LLM calls with host-prepared context. Model routing is configured through plugin `model.<role>` entries, while Hermes `auto` resolves to the active Hermes model routing.

**Tech Stack:** Hermes standalone plugin, `config.py`, `memory_extractor.py`, `dspy_program.py`, `prompt_gepa_adapter.py`, `llm_telemetry.py`, bundled operations docs, pytest.

---

## Current state

- `target_resolver`, `improvement_planner`, `skill_agent`, `memory_agent`, and `evaluator` are present in `_default_config()["model"]`.
- `memory_extractor.py` already tries to read `config["model"]["memory_extractor"]`, but `memory_extractor` is not present in default config or `config.example.yaml`.
- DSPy proposal scoring already uses `model.evaluator` through `dspy_program._evaluator_model_config()`.
- Prompt overlay GEPA already uses `model.evaluator` through `prompt_gepa_adapter._model_config()` and has a test for student/reflection LM routing.
- Some docs still describe LLM calls too broadly, especially `skills/operations/references/architecture.md`, and do not clearly separate:
  - constrained tool-using LLM roles,
  - tool-free auxiliary LLM roles,
  - DSPy/GEPA LM adapter calls,
  - deterministic host-side promotion/setup/status.

## Desired role contract

| Role/site | Model config key | Tool access | Execution shape |
|---|---|---|---|
| `target_resolver` | `model.target_resolver` | `skills_list`, `skill_view` only | Hermes constrained agent |
| `improvement_planner` | `model.improvement_planner` | `skills_list`, `skill_view` only | Hermes constrained agent |
| `skill_agent` | `model.skill_agent` | skill tools, mutation allowed only here | Hermes constrained agent |
| `memory_agent` | `model.memory_agent` | memory tool, mutation allowed only here | Hermes constrained agent |
| `memory_extractor` | `model.memory_extractor` | none | Hermes auxiliary LLM call, host-prepared context |
| DSPy evaluator scoring | `model.evaluator` | none | DSPy program using Hermes auxiliary LM bridge |
| GEPA prompt optimizer | `model.evaluator` | none | DSPy/GEPA using Hermes auxiliary LM bridge |
| setup/status/promote/apply | none | none | deterministic host-side code |

`provider: auto`, `model: ""` means the plugin asks Hermes to use its normal auto/main routing. The plugin should record requested routing, and if Hermes exposes resolved provider/model later, telemetry can add it as a follow-up without changing this contract.

## Non-goals

- Do not convert `memory_extractor` into a constrained agent. It does not need tools.
- Do not give DSPy/GEPA Hermes tools.
- Do not add a new approval queue, route, lane, or command.
- Do not pin concrete default models in repo config.
- Do not change Hermes core model routing in this slice.
- Do not make telemetry-resolved model capture a blocker unless Hermes already exposes it cheaply.

---

## Task 1: Add RED tests for model role coverage

**Objective:** Make the expected model role list fail until `memory_extractor` is first-class and docs/examples mention it.

**Files:**
- Modify: `tests/test_config_precedence.py`
- Modify: `tests/test_historical_naming_cleanup.py` or add a focused docs/spec test if cleaner

**Steps:**

1. Update config model-key expectations from:

```python
["improvement_planner", "target_resolver", "skill_agent", "memory_agent", "evaluator"]
```

to:

```python
[
    "improvement_planner",
    "target_resolver",
    "skill_agent",
    "memory_agent",
    "memory_extractor",
    "evaluator",
]
```

2. Add/adjust a config example test that parses `config.example.yaml` and asserts the commented example includes `memory_extractor:` near the other model roles.

3. Add a small docs guard that active docs include these facts:
   - `model.evaluator` powers DSPy/GEPA / evaluator calibration.
   - `model.memory_extractor` powers memory gap extraction.
   - `memory_extractor` has no tools.

**Run:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_config_precedence.py tests/test_historical_naming_cleanup.py -q
```

**Expected:** FAIL because `memory_extractor` is not yet in default config / example / docs.

---

## Task 2: Promote `model.memory_extractor` to first-class config

**Objective:** Add `memory_extractor` to default config and normalization so its model routing is no longer implicit.

**Files:**
- Modify: `hermes_self_improvement/config.py`
- Modify: `config.example.yaml`
- Test: `tests/test_config_precedence.py`

**Implementation notes:**

1. In `_default_config()["model"]`, insert `memory_extractor` after `memory_agent` and before `evaluator`:

```python
"memory_extractor": {
    "provider": "auto",
    "model": "",
    "base_url": "",
    "api_key": "",
    "timeout": 60,
    "max_tokens": 1800,
    "extra_body": {},
},
```

2. Keep the same model config fields as other roles so `_normalize_model_config()` and local override merging continue to work without special cases.

3. In `config.example.yaml`, add a commented `memory_extractor` example and describe it as a tool-free memory gap extraction LLM.

**Run:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_config_precedence.py -q
```

**Expected:** PASS.

---

## Task 3: Make `memory_extractor` LLM call use the first-class role cleanly

**Objective:** Keep behavior the same, but make the fallback explicit and testable.

**Files:**
- Modify: `hermes_self_improvement/memory_extractor.py`
- Modify: `tests/test_memory_extractor.py`

**Implementation notes:**

1. Extract a tiny helper if useful:

```python
def _memory_extractor_model_config(config: dict[str, Any]) -> dict[str, Any]:
    model_config = config.get("model") if isinstance(config.get("model"), dict) else {}
    return model_config.get("memory_extractor") if isinstance(model_config.get("memory_extractor"), dict) else {}
```

2. `_call_memory_extractor_llm()` should continue to use:
   - `provider = cfg.get("provider") or "auto"`
   - `model = cfg.get("model") or None`
   - `timeout`, `max_tokens`, `extra_body` if already supported or trivial to add

3. Keep `task="self_improvement"` unless there is already a canonical task id policy for this site. Do not create a new auxiliary task name in this slice unless tests/docs are updated and the benefit is explicit.

4. Add a test with a fake LLM call / monkeypatch that proves `model.memory_extractor` values are passed to `call_llm` and to `record_llm_call`.

**Run:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_memory_extractor.py -q
```

**Expected:** PASS.

---

## Task 4: Strengthen DSPy/GEPA evaluator routing tests

**Objective:** Make the existing `model.evaluator` behavior impossible to accidentally regress.

**Files:**
- Modify: `tests/test_dspy_program.py`
- Modify: `tests/test_gepa_optimizer.py` only if the existing test needs a clearer assertion name or additional fields

**Implementation notes:**

1. Keep the existing GEPA optimizer test:

```python
def test_optimize_gepa_uses_model_evaluator_for_student_and_reflection_lm(...):
```

2. Add or strengthen a `dspy_program.py` test that calls `score_with_dspy_program(config={"model": {"evaluator": ...}})` with fake DSPy shape and asserts the constructed Hermes auxiliary LM receives the evaluator model config.

3. Assert provider/model/max_tokens/timeout at least once. Do not require a real provider call.

**Run:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_dspy_program.py tests/test_gepa_optimizer.py -q
```

**Expected:** PASS.

---

## Task 5: Rewrite role/model routing docs to remove ambiguity

**Objective:** Make docs match the actual model/tool contract so future discussion does not depend on memory.

**Files:**
- Modify: `README.md`
- Modify: `skills/operations/SKILL.md`
- Modify: `skills/operations/references/architecture.md`

**Required content:**

1. Add/refresh a compact role table matching the Desired role contract above.

2. Replace the broad architecture sentence:

```text
LLM judgment happens in current named sites ... Those calls route through Hermes auxiliary LLM support with the plugin task name `self_improvement`.
```

with a more accurate split:

```text
Tool-using LLM roles (`target_resolver`, `improvement_planner`, `skill_agent`, `memory_agent`) run through Hermes constrained agents with role-specific model config and tool whitelists. Tool-free LLM sites (`memory_extractor`, DSPy evaluator scoring, GEPA prompt optimization) receive host-prepared context and call Hermes auxiliary LLM routing through their role config. DSPy/GEPA use `model.evaluator`; `memory_extractor` uses `model.memory_extractor`.
```

3. Explicitly say `memory_extractor` does not mutate memory. It only proposes normalized `memory_gap_candidate` items; `memory_agent` decides and executes memory mutation through the official memory tool.

4. Explicitly say `provider: auto`, empty `model`, means Hermes auto/main routing, not a plugin-pinned model.

**Run:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_historical_naming_cleanup.py -q
```

**Expected:** PASS.

---

## Task 6: Optional telemetry wording cleanup, not resolved-model capture

**Objective:** Avoid claiming telemetry records the final resolved provider/model when it currently records requested routing.

**Files:**
- Inspect: `hermes_self_improvement/llm_telemetry.py`
- Modify only if current labels are misleading.
- Test: focused telemetry test if labels change.

**Implementation notes:**

1. If telemetry fields are named simply `provider` / `model`, either leave them as-is but docs say “requested provider/model”, or add non-breaking companion labels such as `requested_provider` / `requested_model` only if existing consumers tolerate it.

2. Do not block this plan on final resolved model capture. That depends on Hermes auxiliary/client internals and is a separate follow-up if needed.

**Run:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests -q
```

**Expected:** PASS.

---

## Task 7: Full verification and docs state update

**Objective:** Prove the routing contract and docs are green, then update plan/roadmap status.

**Files:**
- Modify: `.hermes/plans/README.md`
- Modify: `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`
- Modify: this plan file after implementation

**Run:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
hermes self-improvement status --json
hermes self-improvement improve --dry-run --json
hermes self-improvement calibrate --dry-run --json

git diff --check
```

**Expected:**

- Full pytest passes.
- `status` remains healthy.
- `improve --dry-run --json` still succeeds.
- `calibrate --dry-run --json` still succeeds or produces a valid no-op/candidate-set artifact depending on evidence gates.
- No active docs imply DSPy/GEPA or `memory_extractor` have Hermes tools.

**Commit:**

```bash
git add hermes_self_improvement config.example.yaml README.md skills/operations tests .hermes/plans
git commit -m "refactor(self-improvement): formalize llm role model routing"
git push origin main
```

---

## Acceptance criteria

- `load_config()["model"]` contains `memory_extractor` as a first-class role.
- `memory_extractor` uses `model.memory_extractor` and remains tool-free.
- DSPy evaluator scoring and GEPA prompt optimization are test-backed as using `model.evaluator`.
- Docs clearly separate constrained tool-using roles from tool-free LLM calls.
- No new command, lane, approval flow, or concrete default model is introduced.
- Full tests and dry-runs pass before commit/push.
