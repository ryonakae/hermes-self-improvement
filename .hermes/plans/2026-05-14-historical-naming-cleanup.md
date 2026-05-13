# Historical Naming Cleanup Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Remove or quarantine historical names in `hermes-self-improvement` that no longer match current runtime behavior, so code, docs, tests, telemetry, and operator guidance all use the current mental model.

**Architecture:** Treat this as a bounded cleanup inside the plugin repo only. First add regression tests that distinguish canonical names from allowed historical aliases, then rename runtime routing / docs / tests in small slices. Keep intentional compatibility normalizers only where they protect LLM output or existing local observations, but mark them as legacy input normalization and prevent them from being described as current behavior.

**Tech Stack:** Python, pytest, Hermes plugin CLI, Hermes auxiliary LLM routing, repo-tracked `.hermes/plans/` docs.

---

## Scope

Clean current, non-archived plugin surfaces under:

- `hermes_self_improvement/`
- `tests/`
- `skills/operations/`
- `defaults/`
- `README.md`
- `AGENTS.md`
- `config.example.yaml`
- `plugin.yaml`
- `pyproject.toml`
- `.hermes/plans/README.md`

Do not rewrite historical archive docs except when the active index incorrectly describes them as current. Archived plans under `.hermes/plans/archive/` may keep historical terms.

## Naming decisions

### Canonical current names

| Concept | Canonical name |
|---|---|
| self-improvement auxiliary task | `self_improvement` |
| planning LLM site / model role | `improvement_planner` / `model.improvement_planner` |
| skill mutation agent | `skill_agent` / `model.skill_agent` |
| memory mutation agent | `memory_agent` / `model.memory_agent` |
| evaluator / GEPA calibration | `evaluator` / `model.evaluator` |
| skill mutation decision | `mutate_skill` |
| skill maintenance subtype | `maintenance_action: patch|merge` |
| memory mutation decision | `mutate_memory` |
| evaluator calibration decision | `calibrate_evaluator` |
| primary CLI | `hermes self-improvement ...` |
| runtime root | `${HERMES_HOME:-~/.hermes}/self-improvement` |

### Historical names to remove from active docs and canonical outputs

- `skills_hub` as self-improvement LLM routing task
- `model.planner`, `model.editor`, `model.llm`, `model.mutation`, `model.gepa`
- `llm_scorer`, `llm_scorer_error`, `--scorer llm`, `--scorer gepa`, `--scorer compare` as current behavior
- `run_editor`, `editor_instructions`, `selected_for_editor`, `planner_editor`, `planner-editor`, `native_skill_tool_editor`
- `memory_candidate`, `evaluator_candidate` as planner decisions
- `patch_skill`, `merge_skills` as canonical planner decisions
- `approval_required` as normal execution/recommendation vocabulary
- `bin/hermes-self-improve` / `hermes-self-improve` as active invocation
- `${HERMES_HOME}/reports/self-improvement` as active runtime path

### Allowed legacy appearances

These are allowed, but should be narrow and tested:

- Archived plans and historical notes that explicitly describe past behavior.
- Negative tests that assert legacy commands/tools are absent.
- Input normalizers that accept LLM-produced old decisions such as `patch_skill` / `merge_skills` and convert them to `mutate_skill + maintenance_action`, provided prompts/docs do not tell the LLM to emit old values.
- Target hint aliases for old skill names if they map old observations to current mutable targets, provided comments make that compatibility purpose explicit.
- Runtime artifacts/logs under `${HERMES_HOME}` are not part of this repo cleanup.

---

## Phase 0: Baseline and inventory

### Task 0.1: Capture current status and legacy-name inventory

**Objective:** Record the starting point before touching files.

**Files:**
- Read only: repo tree

**Step 1: Check worktree**

Run:

```bash
git status --short
git log --oneline --max-count=5
```

Expected: no unrelated changes, current branch at latest local `main`.

**Step 2: Run active legacy-name inventory**

Run:

```bash
git grep -n -I -E 'skills_hub|model\.planner|model\.editor|model\.llm|model\.mutation|model\.gepa|llm_scorer|llm_scorer_error|--scorer (llm|gepa|compare)|run_editor|editor_instructions|selected_for_editor|planner_editor|planner-editor|native_skill_tool_editor|memory_candidate|evaluator_candidate|patch_skill|merge_skills|approval_required|hermes-self-improve|reports/self-improvement' -- hermes_self_improvement tests skills defaults README.md AGENTS.md config.example.yaml plugin.yaml pyproject.toml
```

Expected: known hits only. Save the output in the implementation notes or PR summary, not in a new artifact file.

**Step 3: Confirm plan index references current roadmap**

Run:

```bash
git grep -n '2026-05-14-historical-naming-cleanup' -- .hermes/plans/README.md || true
```

Expected before implementing this plan: no hit or a single entry if this plan was already indexed.

---

## Phase 1: Add regression tests for naming drift

### Task 1.1: Add active-surface naming guard test

**Objective:** Create a test that fails while stale current-behavior names remain in active docs/code.

**Files:**
- Create or modify: `tests/test_historical_naming_cleanup.py`

**Step 1: Add the test file**

Create `tests/test_historical_naming_cleanup.py` with helpers that scan only active surfaces, excluding `.hermes/plans/archive/` and allowed negative/compatibility tests.

Suggested structure:

```python
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_PATHS = [
    "hermes_self_improvement",
    "skills/operations",
    "defaults",
    "README.md",
    "AGENTS.md",
    "config.example.yaml",
    "plugin.yaml",
    "pyproject.toml",
]

FORBIDDEN_ACTIVE_TERMS = {
    "task=\"skills_hub\"": "self-improvement LLM calls must use task=\"self_improvement\"",
    "task='skills_hub'": "self-improvement LLM calls must use task='self_improvement'",
    "model.planner": "use model.improvement_planner",
    "model.editor": "use model.skill_agent / model.memory_agent",
    "model.llm": "retired model role",
    "model.mutation": "retired model role",
    "model.gepa": "retired model role",
    "llm_scorer_error": "LLM scorer is retired",
    "run_editor": "use mutate_skill",
    "editor_instructions": "use skill_agent_instructions",
    "planner_editor": "use skill_agent",
    "planner-editor": "use skill-agent",
    "native_skill_tool_editor": "use native_skill_tool",
    "evaluator_candidate": "use calibrate_evaluator",
    "hermes-self-improve": "use hermes self-improvement",
    "reports/self-improvement": "use self-improvement runtime root",
}

ALLOWED_SUBSTRINGS = {
    # If kept, document why next to the code before adding here.
}


def _active_files() -> list[Path]:
    files: list[Path] = []
    for rel in ACTIVE_PATHS:
        path = ROOT / rel
        if path.is_file():
            files.append(path)
            continue
        files.extend(p for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    return files


def test_active_surfaces_do_not_describe_retired_names_as_current_behavior():
    hits: list[str] = []
    for path in _active_files():
        text = path.read_text(encoding="utf-8")
        for term, reason in FORBIDDEN_ACTIVE_TERMS.items():
            if term in text and not any(allowed in str(path) for allowed in ALLOWED_SUBSTRINGS):
                hits.append(f"{path.relative_to(ROOT)}: contains {term!r}: {reason}")
    assert not hits, "\n".join(hits)
```

**Step 2: Run the new test and verify failure**

Run:

```bash
python3 -m pytest tests/test_historical_naming_cleanup.py -q
```

Expected: FAIL, listing current stale names.

### Task 1.2: Add canonical auxiliary task test

**Objective:** Lock self-improvement LLM routing to `task="self_improvement"`.

**Files:**
- Modify: `tests/test_target_resolver.py` or `tests/test_llm_telemetry.py`
- Modify: add coverage for `memory_extractor` and `improvement_planner` if no suitable existing test exists

**Step 1: Update telemetry expectation**

In `tests/test_llm_telemetry.py`, change the example `task` from `skills_hub` to `self_improvement`.

**Step 2: Add/adjust monkeypatched call tests**

For each LLM site:

- `hermes_self_improvement/improvement_planner.py::_call_improvement_planner_llm`
- `hermes_self_improvement/memory_extractor.py::_call_memory_extractor_llm`
- `hermes_self_improvement/target_resolver.py::_call_resolver_llm`

Monkeypatch `agent.auxiliary_client.call_llm` and assert the captured kwargs include:

```python
assert captured["task"] == "self_improvement"
```

If existing tests already monkeypatch these calls, update them instead of adding duplicates.

**Step 3: Run focused tests and verify failure**

Run:

```bash
python3 -m pytest tests/test_llm_telemetry.py tests/test_target_resolver.py tests/test_memory_extractor.py tests/test_skill_planner.py -q
```

Expected before implementation: FAIL where `skills_hub` is still emitted.

---

## Phase 2: Rename self-improvement auxiliary task

### Task 2.1: Change runtime LLM calls from `skills_hub` to `self_improvement`

**Objective:** Stop borrowing the Skills Hub auxiliary routing slot for self-improvement LLM calls.

**Files:**
- Modify: `hermes_self_improvement/improvement_planner.py`
- Modify: `hermes_self_improvement/memory_extractor.py`
- Modify: `hermes_self_improvement/target_resolver.py`
- Modify: `tests/test_llm_telemetry.py`

**Step 1: Replace runtime task values**

In the three runtime files, replace only these call/telemetry values:

```python
task="skills_hub"
```

with:

```python
task="self_improvement"
```

Do not rename real Hermes core Skills Hub code.

**Step 2: Update tests**

Update telemetry expectations from `skills_hub` to `self_improvement`.

**Step 3: Run focused tests**

Run:

```bash
python3 -m pytest tests/test_llm_telemetry.py tests/test_target_resolver.py tests/test_memory_extractor.py tests/test_skill_planner.py -q
```

Expected: PASS.

### Task 2.2: Add Hermes core config support for `auxiliary.self_improvement` only if needed

**Objective:** Ensure `call_llm(task="self_improvement")` can use explicit per-task routing if configured.

**Files:**
- Inspect only first: `/Users/ryo.nakae/.hermes/hermes-agent/hermes_cli/config.py`
- Modify Hermes core only if Ryo explicitly approves core changes or if this plugin must rely on missing default config behavior

**Step 1: Verify current fallback behavior**

Read `_get_auxiliary_task_config()` and `_resolve_task_provider_model()` in Hermes core. If missing task config cleanly falls back to `auto`, plugin runtime works without core changes.

**Step 2: Decide boundary**

Default plan: do **not** change Hermes core in this cleanup. Add plugin docs explaining that `self_improvement` task falls back to auto unless Hermes core later adds `auxiliary.self_improvement` defaults.

If explicit routing is required later, make it a separate core plan, not part of this plugin cleanup.

---

## Phase 3: Clean active operations docs and bundled skill references

### Task 3.1: Update `skills/operations/SKILL.md` model role and decision language

**Objective:** Make the primary operational skill match the current code.

**Files:**
- Modify: `skills/operations/SKILL.md`
- Test: `tests/test_bundled_skills.py` if assertions need updating

**Step 1: Replace model role text**

Change any text like:

```text
model.planner / model.editor / model.evaluator
```

to:

```text
model.improvement_planner / model.skill_agent / model.memory_agent / model.evaluator
```

**Step 2: Replace canonical planner decision text**

Where the skill says planner selects `patch_skill / merge_skills`, rewrite to:

```text
Planner は `mutate_skill / archive_skill / create_skill / mutate_memory / calibrate_evaluator / skip / defer` を選ぶ。Skill の patch / merge は `decision: "mutate_skill"` に `maintenance_action: "patch" | "merge"` を付けて表す。
```

**Step 3: Preserve target resolver vocabulary only where current**

`attach_existing_skill / memory_candidate / unresolved / skip_noise` may stay if it is target resolver output, not planner decision. If the text is ambiguous, say explicitly “target resolver output”.

**Step 4: Run tests**

Run:

```bash
python3 -m pytest tests/test_bundled_skills.py tests/test_historical_naming_cleanup.py -q
```

Expected: PASS for this slice or fewer naming-guard failures.

### Task 3.2: Rewrite `skills/operations/references/architecture.md` scorer/planner sections

**Objective:** Remove stale architecture claims about `llm_scorer`, `run_editor`, and old decisions.

**Files:**
- Modify: `skills/operations/references/architecture.md`

**Step 1: Replace `## Scorer paths`**

Current section incorrectly says `llm` is the default proposal scorer. Rewrite to:

```markdown
## Proposal scoring and diagnostic signals

`hermes_self_improvement/scoring.py` now provides only deterministic heuristic proposal scoring for report ordering and diagnostic signals. It does not make mutation decisions and does not call an LLM. The historical `_call_llm_scorer` path was retired after `improvement_planner` became the decision owner.

LLM judgment happens in current named sites such as `target_resolver`, `memory_extractor`, `improvement_planner`, `skill_agent`, and `memory_agent`. Those calls route through Hermes auxiliary LLM support with the plugin task name `self_improvement`.

GEPA / DSPy are not live proposal scorers. They belong to `calibrate`, where they improve runtime-private evaluator / prompt / rubric artifacts for later planner and agent runs. Scoring remains advisory and never grants mutation permission.
```

**Step 2: Replace `## Global skill planner`**

Rewrite old `run_editor` language to current flow:

```markdown
## Improvement planner and mutation agents

`improve` runs skill and memory changes as `evidence builder -> target_resolver / memory_extractor -> improvement_planner -> skill_agent / memory_agent`. The planner receives a compact redacted digest of mutable skill candidates, memory candidates, target-resolution metadata, evidence ids/previews, and unmatched evidence counts.

Planner decisions are `mutate_skill`, `archive_skill`, `create_skill`, `mutate_memory`, `calibrate_evaluator`, `skip`, or `defer`. Skill patch/merge semantics are represented by `decision: "mutate_skill"` plus `maintenance_action: "patch" | "merge"`.

Dry-run executes planning and writes the planner payload plus digest into the run artifact, but does not execute mutation agents. Mutating runs send `mutate_skill` decisions to `skill_agent` with `skill_agent_instructions` and selected `evidence_ids`, and send `mutate_memory` decisions to `memory_agent`. Planner fallback remains deterministic and evidence-attached; weak-only evidence does not grant mutation permission.
```

**Step 3: Update normalization paragraph**

Replace `run_editor_without_attached_evidence`, `editor_instructions`, and `editor prompt length` language with current equivalents:

- `mutate_skill_without_attached_evidence`
- `skill_agent_instructions`
- `skill_agent prompt length`

If the code uses a different exact reason key, use the code's actual key.

**Step 4: Run docs/naming tests**

Run:

```bash
python3 -m pytest tests/test_bundled_skills.py tests/test_historical_naming_cleanup.py -q
```

Expected: PASS or remaining failures only from later phases.

---

## Phase 4: Clean code-level legacy vocabulary without breaking compatibility

### Task 4.1: Reclassify `patch_skill` / `merge_skills` as legacy input only

**Objective:** Keep compatibility normalizers, but prevent old decisions from looking canonical.

**Files:**
- Modify: `hermes_self_improvement/improvement_planner.py`
- Modify: `hermes_self_improvement/evidence.py` if `recommended_actions` is ambiguous
- Modify: `tests/test_knowledge_maintenance_planner.py`
- Modify: `tests/test_evidence_inventory_candidates.py`

**Step 1: Inspect current normalization**

Read the block around `improvement_planner.py` lines where `decision == "patch_skill"` and `decision == "merge_skills"`.

**Step 2: Add comments and tests that old decisions are normalized**

Add or update tests to assert:

```python
{"decision": "patch_skill"}
```

normalizes to:

```python
{"decision": "mutate_skill", "maintenance_action": "patch"}
```

and similarly for `merge_skills`.

**Step 3: Rename inventory hint if needed**

If `evidence.py` `recommended_actions` is LLM-facing as a planner action list, change `merge_skills` to either:

```python
"mutate_skill_merge"
```

or keep `merge_skills` only if the prompt clearly labels it as a recommended maintenance subtype, not a planner decision.

Recommended approach: keep `recommended_actions` as hints, but change active docs to say it is not a decision enum. Avoid broad schema churn unless tests show the hint leaks into planner output as a decision.

**Step 4: Run focused tests**

Run:

```bash
python3 -m pytest tests/test_knowledge_maintenance_planner.py tests/test_evidence_inventory_candidates.py tests/test_historical_naming_cleanup.py -q
```

Expected: PASS.

### Task 4.2: Replace `approval_required` recommendation vocabulary

**Objective:** Remove approval-queue language from current proposal output.

**Files:**
- Modify: `hermes_self_improvement/analysis.py`
- Modify: `tests/test_analysis_reclassification.py`

**Step 1: Decide replacement values**

Use current vocabulary:

- For high-risk memory compression: `recommendation: "defer"`, `reason_code: "manual_planner_review_required"`
- For destructive skill lifecycle actions that should not auto-apply: `recommendation: "block"` if unsupported/destructive, or `"defer"` if planner can later decide safely.
- Keep `auto_apply: False`.

**Step 2: Update tests first**

Change assertions from:

```python
assert proposal["recommendation"] == "approval_required"
```

to the selected current value, and assert the explicit reason code.

**Step 3: Update implementation**

Replace `approval_required` strings in `analysis.py` with the current values.

**Step 4: Run tests**

Run:

```bash
python3 -m pytest tests/test_analysis_reclassification.py tests/test_historical_naming_cleanup.py -q
```

Expected: PASS.

### Task 4.3: Review old skill-name aliases

**Objective:** Keep only aliases that intentionally map historical observations to current targets.

**Files:**
- Modify: `hermes_self_improvement/target_hints.py`
- Modify: `tests/test_target_hints.py`

**Step 1: Inspect current aliases**

Check uses of:

```python
"hermes-self-improvement-plugin"
```

**Step 2: Decide alias status**

If this alias is still needed for old observations, keep it but rename comments/tests to make it explicit:

```text
legacy_alias_to_current_operational_skill
```

If it is not needed, remove it and update tests to use the current skill target.

Recommended default: keep it as a compatibility alias, but ensure naming guard test allows it only in `target_hints.py` and `tests/test_target_hints.py` with comments proving why.

**Step 3: Run tests**

Run:

```bash
python3 -m pytest tests/test_target_hints.py tests/test_historical_naming_cleanup.py -q
```

Expected: PASS.

---

## Phase 5: Clean GEPA/proposal-scorer wording

### Task 5.1: Update stale `--scorer gepa` docstrings

**Objective:** Make GEPA docstrings describe current calibrate/evaluator behavior, not removed proposal-scorer CLI behavior.

**Files:**
- Modify: `hermes_self_improvement/dspy_program.py`
- Modify: `hermes_self_improvement/gepa_adapter.py`
- Modify: tests only if they assert docstrings or errors

**Step 1: Replace stale docstrings**

In `dspy_program.py`, change text like:

```text
Runtime `--scorer gepa` uses the real DSPy program
```

to:

```text
Runtime evaluator calibration uses the real DSPy program through `calibrate`; proposal scoring no longer exposes `--scorer gepa`.
```

In `gepa_adapter.py`, change:

```text
User-facing ``--scorer gepa`` no longer runs ...
```

to:

```text
The historical proposal-scorer CLI path is retired. Runtime evaluator scoring/calibration uses this adapter through `calibrate`.
```

**Step 2: Run focused tests**

Run:

```bash
python3 -m pytest tests/test_dspy_program.py tests/test_gepa_offline_scorer.py tests/test_gepa_optimizer.py tests/test_historical_naming_cleanup.py -q
```

Expected: PASS.

### Task 5.2: Confirm CLI/help surfaces do not expose retired scorer flags

**Objective:** Verify old scorer flags are not still user-facing.

**Files:**
- Modify only if needed: `hermes_self_improvement/cli.py`
- Test: `tests/test_cli_surface.py`

**Step 1: Run CLI surface tests**

Run:

```bash
python3 -m pytest tests/test_cli_surface.py -q
```

**Step 2: If failures or grep hits show user-facing old flags, update CLI/help**

Remove active help text that says `--scorer llm/gepa/compare`. Keep negative tests that assert removal.

**Step 3: Run focused tests again**

Run:

```bash
python3 -m pytest tests/test_cli_surface.py tests/test_historical_naming_cleanup.py -q
```

Expected: PASS.

---

## Phase 6: README / AGENTS / plan index alignment

### Task 6.1: Refresh README and AGENTS wording

**Objective:** Make human-facing repo guidance describe only current commands and model roles.

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`

**Step 1: Search active docs**

Run:

```bash
git grep -n -I -E 'model\.planner|model\.editor|llm_scorer|run_editor|hermes-self-improve|reports/self-improvement|--scorer' -- README.md AGENTS.md
```

**Step 2: Update wording**

Ensure docs mention:

- `hermes self-improvement status/report/improve/calibrate`
- `model.improvement_planner`, `model.skill_agent`, `model.memory_agent`, `model.evaluator`
- runtime root `${HERMES_HOME:-~/.hermes}/self-improvement`
- `improve` owns skill/memory changes; `calibrate` owns evaluator / runtime-private prompt overlay calibration

**Step 3: Run docs tests**

Run:

```bash
python3 -m pytest tests/test_scheduled_execution_docs.py tests/test_historical_naming_cleanup.py -q
```

Expected: PASS.

### Task 6.2: Update `.hermes/plans/README.md`

**Objective:** Make the plan index point at this cleanup as current/active and preserve the previous latest plan as completed.

**Files:**
- Modify: `.hermes/plans/README.md`

**Step 1: Add current active plan entry near the top**

Add after the long-term roadmap block:

```markdown
The current active cleanup plan is:

- `2026-05-14-historical-naming-cleanup.md`
  - **Status:** planned.
  - Cleans up historical names that survived earlier refactors: `skills_hub` auxiliary routing, old model role docs, removed `llm_scorer` / `run_editor` architecture text, `patch_skill` / `merge_skills` canonical-decision confusion, approval-queue vocabulary, and retired wrapper/path references.
```

**Step 2: Keep previous latest plan as completed**

Do not delete the `2026-05-13-self-improvement-cron-no-agent.md` entry.

**Step 3: Run grep check**

Run:

```bash
git grep -n '2026-05-14-historical-naming-cleanup' -- .hermes/plans/README.md
```

Expected: one entry.

---

## Phase 7: Final validation and commit sequence

### Task 7.1: Run full validation

**Objective:** Prove cleanup did not break plugin runtime or tests.

**Files:**
- Read only after implementation

**Step 1: Python compile**

Run:

```bash
python3 -m py_compile __init__.py hermes_self_improvement/*.py
```

Expected: exit 0.

**Step 2: Full tests**

Run:

```bash
python3 -m pytest tests -q
```

Expected: PASS. If known pre-existing YAML failures occur, document exact failures and run the focused test set from this plan successfully.

**Step 3: Runtime status**

Run:

```bash
hermes self-improvement status
```

Expected: command exits 0 and shows runtime setup / active evaluator / prompt overlay readiness.

**Step 4: Naming grep gate**

Run:

```bash
git grep -n -I -E 'task="skills_hub"|task='"'"'skills_hub'"'"'|model\.planner|model\.editor|model\.llm|model\.mutation|model\.gepa|llm_scorer_error|run_editor|editor_instructions|selected_for_editor|planner_editor|planner-editor|native_skill_tool_editor|evaluator_candidate|hermes-self-improve|reports/self-improvement' -- hermes_self_improvement tests skills defaults README.md AGENTS.md config.example.yaml plugin.yaml pyproject.toml
```

Expected: no hits except explicitly allowed compatibility/negative-test locations documented in `tests/test_historical_naming_cleanup.py`.

**Step 5: Diff check**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only intended files changed.

### Task 7.2: Commit in reviewable slices

**Objective:** Keep the large cleanup understandable.

Recommended commit sequence:

```bash
git add .hermes/plans/2026-05-14-historical-naming-cleanup.md .hermes/plans/README.md
git commit -m "docs(self-improvement): plan historical naming cleanup"

git add tests/test_historical_naming_cleanup.py tests/test_llm_telemetry.py tests/test_target_resolver.py tests/test_memory_extractor.py tests/test_skill_planner.py
git commit -m "test(self-improvement): guard against historical naming drift"

git add hermes_self_improvement/improvement_planner.py hermes_self_improvement/memory_extractor.py hermes_self_improvement/target_resolver.py tests/test_llm_telemetry.py tests/test_target_resolver.py tests/test_memory_extractor.py tests/test_skill_planner.py
git commit -m "refactor(self-improvement): use dedicated auxiliary task name"

git add skills/operations/SKILL.md skills/operations/references/architecture.md README.md AGENTS.md tests/test_bundled_skills.py tests/test_scheduled_execution_docs.py
git commit -m "docs(self-improvement): align operations docs with current naming"

git add hermes_self_improvement/analysis.py hermes_self_improvement/improvement_planner.py hermes_self_improvement/evidence.py hermes_self_improvement/dspy_program.py hermes_self_improvement/gepa_adapter.py hermes_self_improvement/target_hints.py tests
git commit -m "refactor(self-improvement): quarantine legacy decision vocabulary"
```

If a slice becomes too large, split docs and code further. Do not use `--no-verify`.

---

## Non-goals

- Do not edit Hermes core unless a separate explicit plan is approved.
- Do not rewrite archived plans for aesthetic cleanup.
- Do not migrate existing runtime artifacts/logs under `${HERMES_HOME}`.
- Do not add new surfaces, approval queues, lanes, or policy modes.
- Do not change mutation safety boundaries.
- Do not change GEPA promotion gates.

## Acceptance criteria

- Active runtime LLM calls use `task="self_improvement"`, not `task="skills_hub"`.
- Active operations docs no longer describe `llm_scorer`, `run_editor`, `memory_candidate`, or `evaluator_candidate` as current behavior.
- Active model-role docs use `model.improvement_planner`, `model.skill_agent`, `model.memory_agent`, and `model.evaluator`.
- Planner decisions are documented as `mutate_skill / archive_skill / create_skill / mutate_memory / calibrate_evaluator / skip / defer`.
- `patch_skill` / `merge_skills` are either absent from active canonical docs or explicitly described as legacy-normalized inputs / maintenance subtypes.
- `approval_required` is removed from active proposal outputs or replaced with current `defer` / `block` vocabulary plus explicit reason codes.
- `hermes-self-improve` and old `reports/self-improvement` paths are absent from active guidance.
- `python3 -m py_compile __init__.py hermes_self_improvement/*.py` passes.
- `python3 -m pytest tests -q` passes or any unrelated pre-existing failure is documented with focused cleanup tests passing.
- `hermes self-improvement status` exits 0.
