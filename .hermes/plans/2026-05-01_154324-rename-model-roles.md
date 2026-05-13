# Rename Model Roles Implementation Plan

> **For Hermes:** Implement directly in TDD slices. Do not preserve compatibility for old unreleased model keys.

**Goal:** Rename `model.llm`, `model.mutation`, and `model.gepa` to role-based `model.planner`, `model.editor`, and `model.evaluator`, in that order, and remove old names from runtime code, config examples, docs, tests, and local config.

**Architecture:** The plugin should expose model routing by responsibility rather than implementation technology. `planner` scores/evaluates evidence and proposals, `editor` powers skill/memory mutation agents, and `evaluator` powers DSPy/GEPA scorer/evaluator optimization. No aliasing or fallback for old names should remain because this plugin is still local/unreleased and the current cleanup policy is current-schema-only.

**Tech Stack:** Python, YAML config, pytest, Hermes auxiliary client, DSPy/GEPA adapter.

---

## Canonical mapping

| Old key | New key | Responsibility |
| --- | --- | --- |
| `model.llm` | `model.planner` | LLM proposal/evidence scoring, risk/recommendation judgment, compare scorer LLM side |
| `model.mutation` | `model.editor` | Mutation agent / skill-memory editor model used by `mutation_backend` |
| `model.gepa` | `model.evaluator` | DSPy/GEPA scoring/evaluation/optimization model |

Canonical YAML order:

```yaml
model:
  planner:
    provider: codex
    model: gpt-5.4-mini
  editor:
    provider: codex
    model: gpt-5.4-mini
  evaluator:
    provider: codex
    model: gpt-5.4-mini
```

Do not keep `llm`, `mutation`, or `gepa` under `model` as accepted aliases.

---

## Task 1: Add failing config tests for role names only

**Objective:** Make the expected config shape explicit before implementation.

**Files:**
- Modify: `tests/test_config_precedence.py`
- Modify: `tests/test_llm_scorer.py`
- Modify: `tests/test_gepa_optimizer.py`

**Steps:**
1. In `tests/test_config_precedence.py`, update YAML fixtures and assertions:
   - `model.llm` -> `model.planner`
   - `model.mutation` -> `model.editor`
   - `model.gepa` -> `model.evaluator`
   - assert default `list(config["model"].keys()) == ["planner", "editor", "evaluator"]` or equivalent order-preserving check.
   - assert old role keys are absent from normalized config.
2. In `tests/test_llm_scorer.py`, update injected config checks to `config["model"]["planner"]`.
3. In `tests/test_gepa_optimizer.py`, update expected redacted config summary from `model.gepa` to `model.evaluator`.
4. Run expected RED:
   ```bash
   python -m pytest tests/test_config_precedence.py tests/test_llm_scorer.py tests/test_gepa_optimizer.py -q
   ```
   Expected: failures showing code still uses old keys.

---

## Task 2: Rename code defaults and config normalization

**Objective:** `_default_config()` and normalized runtime config expose only `planner`, `editor`, `evaluator`.

**Files:**
- Modify: `hermes_self_improvement/config.py`

**Steps:**
1. Change `_default_config()["model"]` order to:
   ```python
   "model": {
       "planner": {... timeout 60, max_tokens 1800 ...},
       "editor": {... timeout 45, max_tokens 1000 ...},
       "evaluator": {... timeout 120, max_tokens 1800 ...},
   }
   ```
2. Keep `_normalize_model_config()` current-only:
   - deep merge defaults with provided `model`
   - do not translate old keys
   - after merge, keep only default role keys so stale `llm` / `gepa` / `mutation` are dropped.
3. Run:
   ```bash
   python -m pytest tests/test_config_precedence.py -q
   ```

---

## Task 3: Rename planner model usage in scoring

**Objective:** LLM proposal scoring uses `model.planner` and no old variable names leak into docs/artifacts.

**Files:**
- Modify: `hermes_self_improvement/scoring.py`
- Modify: tests touching LLM scorer config

**Steps:**
1. Rename local helper variables where useful:
   - `llm_config` -> `planner_config`
   - keep function names like `_call_llm_scorer` only if they describe the scorer implementation, but avoid model key references to `llm`.
2. In `_call_llm_scorer()`, read:
   ```python
   model_config = config.get("model") if isinstance(config.get("model"), dict) else {}
   planner_config = model_config.get("planner") if isinstance(model_config.get("planner"), dict) else {}
   ```
3. Preserve behavior: provider defaults to `auto`, model empty becomes `None`, timeout `60`, max_tokens `1800`.
4. Run:
   ```bash
   python -m pytest tests/test_llm_scorer.py tests/test_scorer_compare.py tests/test_prompt_classification.py -q
   ```

---

## Task 4: Rename editor model usage in mutation backend and readiness wording

**Objective:** Mutation-agent/editor model config uses `model.editor`; status surfaces should no longer say `model.mutation`.

**Files:**
- Modify: `hermes_self_improvement/mutation_backend.py`
- Modify: `hermes_self_improvement/verification.py`
- Modify: `tests/test_mutation_backend.py`
- Modify: `tests/test_merge_planner.py`

**Steps:**
1. Rename `_model_mutation_config()` to `_model_editor_config()`.
2. In `MutationBackendLimits.from_config()`, read `model.editor` for timeout-related defaults.
3. In `_call_hermes_auxiliary()`, pass `model.editor` config to `call_llm()`.
4. In `verification.merge_planner_status()`, change `model_source` from `model.mutation` to `model.editor`.
5. Update tests to expect `model.editor`.
6. Run:
   ```bash
   python -m pytest tests/test_mutation_backend.py tests/test_merge_planner.py tests/test_runner_steps.py -q
   ```

---

## Task 5: Rename evaluator model usage in DSPy/GEPA path

**Objective:** GEPA/DSPy model routing reads `model.evaluator` while `gepa_scorer` remains the non-model evaluator/scorer settings block.

**Files:**
- Modify: `hermes_self_improvement/dspy_program.py`
- Modify: `hermes_self_improvement/gepa_adapter.py`
- Modify: GEPA/DSPy tests

**Steps:**
1. Rename `_gepa_model_config()` to `_evaluator_model_config()` in `dspy_program.py`.
2. Read `model.evaluator`, not `model.gepa`.
3. In `gepa_adapter.py`, update `_model_config(config, "gepa")` calls to `"evaluator"`.
4. Rename local variables where they describe model role:
   - `gepa_model_config` -> `evaluator_model_config`
   - keep `gepa_config` for `gepa_scorer` settings, because that block still configures GEPA scorer behavior, not model routing.
5. Update redacted config summary tests to expect `model.evaluator`.
6. Run:
   ```bash
   python -m pytest tests/test_gepa_offline_scorer.py tests/test_gepa_optimizer.py tests/test_gepa_eval_assets.py tests/test_gepa_compiled_artifact.py tests/test_dspy_program.py -q
   ```

---

## Task 6: Update YAML examples, local config, docs, and bundled skill references

**Objective:** Human-facing config and docs show only `planner`, `editor`, `evaluator` in that order.

**Files:**
- Modify: `config.example.yaml`
- Modify: `config.yaml` if present locally
- Modify: `README.md`
- Modify: `skills/operations/SKILL.md`
- Modify: `skills/operations/references/*.md`
- Modify: `.hermes/plans/README.md` only if it mentions old model names

**Steps:**
1. In `config.example.yaml`, update optional model example to:
   ```yaml
   # model:
   #   planner:
   #     provider: openrouter
   #     model: anthropic/claude-sonnet-4
   #   editor:
   #     provider: openrouter
   #     model: anthropic/claude-sonnet-4
   #   evaluator:
   #     provider: openrouter
   #     model: anthropic/claude-sonnet-4
   ```
2. In local `config.yaml`, update active config to:
   ```yaml
   model:
     planner:
       provider: codex
       model: gpt-5.4-mini
     editor:
       provider: codex
       model: gpt-5.4-mini
     evaluator:
       provider: codex
       model: gpt-5.4-mini
   ```
3. Update README/config docs to describe responsibilities:
   - `planner`: proposal/evidence judgment
   - `editor`: mutation agent/editor
   - `evaluator`: DSPy/GEPA evaluator/scorer calibration
4. Do not add migration notes that preserve old names. A short “current model roles” description is enough.
5. Run:
   ```bash
   python -m pytest tests/test_config_precedence.py tests/test_scheduled_execution_docs.py -q
   ```

---

## Task 7: Strict old-name search and full validation

**Objective:** Prove old model role names are gone as config roles.

**Commands:**
```bash
python -m py_compile __init__.py hermes_self_improvement/*.py tests/*.py
python -m pytest tests -q
hermes self-improvement status
hermes self-improvement improve --dry-run --json | python -m json.tool >/tmp/self_improve_dry_run.json
hermes self-improvement calibrate --dry-run --json | python -m json.tool >/tmp/self_improve_calibrate_dry_run.json
git diff --check
```

Strict searches:

```bash
rg 'model\.llm|model\.gepa|model\.mutation|\["llm"\]|\["gepa"\]|\["mutation"\]|\['"'"'llm'"'"'\]|\['"'"'gepa'"'"'\]|\['"'"'mutation'"'"'\]' hermes_self_improvement tests README.md config.example.yaml config.yaml skills .hermes/plans/README.md
rg 'llm_config|gepa_model_config|_gepa_model_config|mutation_config|_model_mutation_config|model_source.: .model\.mutation' hermes_self_improvement tests README.md config.example.yaml config.yaml skills
```

Expected:
- No `model.llm`, `model.gepa`, or `model.mutation` references.
- No `model["llm"]`, `model["gepa"]`, or `model["mutation"]` lookups.
- Remaining standalone words `mutation` and `gepa_scorer` are allowed only for top-level mutation settings and GEPA scorer behavior, not model role names.
- Remaining function names like `_call_llm_scorer` may be kept if they refer to scorer implementation rather than config role, but prefer current role wording where easy.

---

## Task 8: Commit and push

**Objective:** Land the rename as one coherent current-schema refactor.

**Commands:**
```bash
git status --short
git diff --stat
git add .
git commit -m "refactor(self-improvement): rename model roles"
git push
```

Final report should include:
- Mapping from old to new names.
- Confirmation that no old model role keys remain.
- Test/smoke results.
- Commit hash.
