# Real Mutation Agent Hardening Detailed Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task. This is a follow-up/detail plan after the first real mutation backend commits landed. Keep fail-closed behavior. Do not mutate Hermes core.

**Goal:** Harden the current real mutation backend / merge judge implementation until it is not just present, but operationally trustworthy: runtime callable resolution is verified, output surfaces are consistent, tool traces are auditable, live smoke is isolated, and docs match actual behavior.

**Architecture:** Keep the existing split. `apply_engine.py` owns apply/ledger/rollback orchestration. `mutation_backend.py` owns bounded skill tool execution and auxiliary-model tool loop. `verification.py` owns deterministic lifecycle checks plus auxiliary merge judge. Rollback remains ledger-bound deterministic restore; forward mutation remains skills-only via `skills_list`, `skill_view`, `skill_manage`.

**Current observed state:**

- Repo: `/Users/ryo.nakae/.hermes/plugins/hermes-self-improvement`
- Recent commits already include:
  - `2428aaf feat(self-improvement): add auxiliary mutation backend loop`
  - `e857ba9 feat(self-improvement): wire mutation backend into apply`
  - `7a8b30e feat(self-improvement): add auxiliary merge judge`
  - `eae0e40 feat(self-improvement): report mutation backend readiness`
  - `ae58570 test(self-improvement): add mutation backend smoke coverage`
  - `425e84d docs(self-improvement): clarify mutation recovery readiness`
- Targeted validation run:
  - `.venv/bin/python -m py_compile __init__.py hermes_self_improvement/*.py` passed.
  - `.venv/bin/python -m pytest tests/test_mutation_backend.py tests/test_merge_judge.py tests/test_real_mutation_backend_smoke.py -q` → `22 passed, 1 skipped`.
  - `bin/hermes-self-improve status` reports `mutation_backend.available=true` and `merge_judge.available=true`.
  - `bin/hermes-self-improve status --json` currently fails because `status` prints JSON by default and has no `--json` flag.

**Non-negotiable constraints:**

- Do not modify Hermes core.
- Do not add broad terminal/file/git/direct filesystem fallback to perform skill mutation.
- Do not widen mutation-agent tools beyond exactly `skills_list`, `skill_view`, `skill_manage`.
- Do not let merge judge alone authorize source deletion; deterministic checks must pass too.
- Do not make memory rollback look supported. Built-in/external memory rollback remains fail-closed unless a separate store-validation proof is completed.
- Do not expose item hash / target hash / approval artifact as user-facing mutation options.
- Every code task below starts with tests, then implementation, then targeted validation, then commit.

---

## Slice 0: Baseline Guardrail Snapshot

**Objective:** Freeze the actual current behavior before changing anything, so later fixes do not accidentally regress the already-implemented path.

**Files:**

- Modify: no production file expected
- Test: existing tests only unless a tiny regression fixture is needed

**Steps:**

1. Run:

   ```bash
   git status --short
   PY=${PYTHON:-.venv/bin/python}
   $PY -m py_compile __init__.py hermes_self_improvement/*.py
   $PY -m pytest tests/test_mutation_backend.py tests/test_apply_engine.py tests/test_merge_judge.py tests/test_real_mutation_backend_smoke.py -q
   bin/hermes-self-improve status
   ```

2. Record in implementation notes:
   - whether worktree is clean
   - current status output fields
   - skipped smoke reason, if any

3. If only notes are updated, commit is optional. If a regression fixture is added:

   ```bash
   git add tests
   git commit -m "test(self-improvement): capture mutation backend baseline"
   git push
   ```

---

## Slice 1: Make Status Output Contract Explicit

**Objective:** Remove ambiguity around `status --json`. The command already prints JSON; either support `--json` as a harmless alias or update all docs/tests to stop claiming it exists. Recommended: support `--json` for consistency with other commands.

**Files:**

- Modify: `hermes_self_improvement/cli.py`
- Modify: `README.md` if command examples mention status JSON
- Modify: `skills/operations/SKILL.md` if examples mention status JSON
- Test: `tests/test_cli.py` or the nearest existing CLI parser test

**Step 1: Write failing test**

Add or extend a CLI parser/handler test:

```python
def test_status_accepts_json_flag_as_noop(capsys):
    # invoke parser/main with ["status", "--json"] or the project’s existing CLI helper
    # assert exit code is 0 and output parses as JSON
```

Expected before implementation: argparse rejects `--json`.

**Step 2: Implement**

In the `status` subparser, add:

```python
status_parser.add_argument("--json", action="store_true", help="Print JSON output (default for status).")
```

Do not add a second human output mode in this slice.

**Step 3: Verify**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_cli.py -q
bin/hermes-self-improve status
bin/hermes-self-improve status --json
```

Both status commands should produce parseable JSON.

**Step 4: Commit/push**

```bash
git add hermes_self_improvement/cli.py README.md skills/operations/SKILL.md tests/test_cli.py
git commit -m "fix(self-improvement): accept status json flag"
git push
```

---

## Slice 2: Verify Runtime Skill Tool Resolver, Not Just Importability

**Objective:** Ensure `mutation_backend_status(...).available=true` means the runtime can call the expected official skill tool handlers with the expected signatures, not merely import modules from `tools.*`.

**Files:**

- Modify: `hermes_self_improvement/mutation_backend.py`
- Test: `tests/test_mutation_backend.py`

**Current risk:** `resolve_skill_tool_executor()` imports `tools.skills_tool.skills_list`, `tools.skills_tool.skill_view`, and `tools.skill_manager_tool.skill_manage`. That may be acceptable, but availability currently means “callables imported”, not “tool boundary can actually execute expected calls”.

**Step 1: Write failing tests**

Add tests:

```python
def test_runtime_skill_tool_resolver_marks_callables_available_with_source(monkeypatch): ...
def test_runtime_skill_tool_resolver_fails_closed_when_one_callable_missing(monkeypatch): ...
def test_mutation_backend_status_includes_tool_executor_source_and_probe_state(monkeypatch): ...
def test_skill_tool_executor_normalizes_string_json_results_from_registry(): ...
```

Use `monkeypatch` to install fake modules in `sys.modules` for `tools.skills_tool` and `tools.skill_manager_tool`; do not depend on the developer’s global Hermes install in unit tests.

**Step 2: Implement a non-mutating readiness probe**

Add a method or helper such as:

```python
def check_skill_tool_executor_readiness(executor: SkillToolExecutor) -> dict[str, Any]:
    ...
```

Rules:

- It may call `skills_list` with a minimal read-only argument set only if that handler is known read-only.
- It must not call `skill_manage` during status, because status must not mutate.
- It should verify all three callables are present.
- It should report:

```json
{
  "available": true,
  "tool_executor": "hermes_tool_registry",
  "readiness": "callables_resolved"
}
```

If the `skills_list` probe is used and fails, report `skills_list_probe_failed` with detail.

**Step 3: Wire status**

Update `mutation_backend_status()` to include the readiness detail without changing existing keys:

```json
{
  "configured": "hermes_auxiliary_tool_loop",
  "available": true,
  "tool_executor": "hermes_tool_registry",
  "readiness": "callables_resolved"
}
```

**Step 4: Verify**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_mutation_backend.py tests/test_plugin_tools.py -q
bin/hermes-self-improve status
```

**Step 5: Commit/push**

```bash
git add hermes_self_improvement/mutation_backend.py tests/test_mutation_backend.py tests/test_plugin_tools.py
git commit -m "test(self-improvement): verify mutation skill tool resolver"
git push
```

---

## Slice 3: Make Tool Trace Verification Real

**Objective:** Replace the current `tool_trace_verified: False` placeholder with actual checks, or rename it so it cannot be misread as a future TODO that got forgotten. Recommended: implement actual trace verification.

**Files:**

- Modify: `hermes_self_improvement/mutation_backend.py`
- Modify: `hermes_self_improvement/apply_engine.py`
- Test: `tests/test_mutation_backend.py`
- Test: `tests/test_apply_engine.py`

**Step 1: Write failing tests**

Add tests:

```python
def test_backend_records_tool_trace_with_result_statuses(): ...
def test_apply_verification_marks_tool_trace_verified_for_allowed_targets(): ...
def test_apply_verification_rejects_trace_target_not_in_allowed_skill_names(): ...
def test_apply_verification_rejects_success_without_mutating_tool_for_improve_task(): ...
```

**Step 2: Extend backend output**

In `HermesAuxiliaryMutationBackend.run()`, record actual trace entries with:

```json
{
  "tool": "skill_manage",
  "action": "patch",
  "name": "demo",
  "success": true
}
```

Keep `used_tools` for compatibility, but add `tool_trace` as the richer field.

**Step 3: Validate trace in apply engine**

In `_verify_skill_agent_result()`:

- Check every trace tool is in `ALLOWED_MUTATION_AGENT_TOOLS`.
- Check every trace `name` is in allowed target skill names, when `name` exists.
- For non-lifecycle mutation tasks that claim changed skills, require at least one successful `skill_manage` trace unless a test-injected backend is explicitly marked as trusted.
- Set `tool_trace_verified` to true only when these checks pass.

Do not require `skill_manage` for read-only preflight traces; require it only when the task claims a skill changed.

**Step 4: Verify**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_mutation_backend.py tests/test_apply_engine.py tests/test_real_mutation_backend_smoke.py -q
```

**Step 5: Commit/push**

```bash
git add hermes_self_improvement/mutation_backend.py hermes_self_improvement/apply_engine.py tests/test_mutation_backend.py tests/test_apply_engine.py tests/test_real_mutation_backend_smoke.py
git commit -m "feat(self-improvement): verify mutation tool traces"
git push
```

---

## Slice 4: Harden Auxiliary Tool Loop Protocol

**Objective:** Make model/tool loop failures deterministic and easier to diagnose. The model must not be able to “succeed” with vague final JSON.

**Files:**

- Modify: `hermes_self_improvement/mutation_backend.py`
- Test: `tests/test_mutation_backend.py`

**Step 1: Write failing tests**

Add tests:

```python
def test_auxiliary_backend_rejects_final_with_changed_skill_outside_task_targets(): ...
def test_auxiliary_backend_rejects_final_without_verification_notes_on_success(): ...
def test_auxiliary_backend_rejects_tool_call_missing_required_name_for_skill_view(): ...
def test_auxiliary_backend_rejects_skill_manage_action_outside_allowed_actions(): ...
def test_auxiliary_backend_includes_last_safe_step_in_failure_context(): ...
```

**Step 2: Add argument validation**

Before calling `SkillToolExecutor.call()`:

- `skill_view` must have `name` as a non-empty string.
- `skill_manage` must have `action` in `{create, patch, edit, delete, write_file, remove_file}`.
- `skill_manage` must have `name` as a non-empty string.
- `skills_list` args must be an object and must not contain unsupported path-like escape fields.

Return fail-closed errors such as:

- `skill_view_name_missing`
- `skill_manage_action_missing`
- `skill_manage_action_not_allowed`
- `skill_manage_name_missing`

**Step 3: Add final-result validation against task targets**

If task contains `targets`, ensure `changed_skills`, `created_skills`, and `deleted_skills` are subset of the task’s target skill names, except for explicit create/rename target allowances already modeled in `apply_engine`.

**Step 4: Improve failure context**

Failures may include a bounded `last_step` / `last_tool` field, but must not dump full skill contents or secrets.

**Step 5: Verify**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_mutation_backend.py tests/test_apply_engine.py -q
```

**Step 6: Commit/push**

```bash
git add hermes_self_improvement/mutation_backend.py tests/test_mutation_backend.py tests/test_apply_engine.py
git commit -m "fix(self-improvement): harden mutation agent tool protocol"
git push
```

---

## Slice 5: Tighten Merge Judge Availability and Failure Semantics

**Objective:** Make merge judge readiness and runtime failures honest. `merge_judge_status().available=true` should mean the auxiliary client import path exists, while execution failures remain explicit in apply results.

**Files:**

- Modify: `hermes_self_improvement/verification.py`
- Modify: `hermes_self_improvement/apply_engine.py` only if result surfacing needs adjustment
- Test: `tests/test_merge_judge.py`
- Test: `tests/test_skill_lifecycle_agent.py`

**Step 1: Write failing tests**

Add tests:

```python
def test_merge_judge_status_reports_model_config_source(): ...
def test_merge_judge_failure_reasons_are_preserved_in_apply_result(): ...
def test_merge_judge_rejects_passed_true_with_any_boolean_gate_false(): ...
def test_merge_judge_truncates_large_snapshots_with_marker(): ...
```

**Step 2: Implement**

- Include `model_source: "model.mutation"` in judge status.
- Preserve `judge_result.reasons` in lifecycle failure result, not only `merge_judge_failed`.
- Keep `_compact_snapshot` truncation bounded and visible.

**Step 3: Verify**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_merge_judge.py tests/test_skill_lifecycle_agent.py -q
```

**Step 4: Commit/push**

```bash
git add hermes_self_improvement/verification.py hermes_self_improvement/apply_engine.py tests/test_merge_judge.py tests/test_skill_lifecycle_agent.py
git commit -m "fix(self-improvement): clarify merge judge readiness and failures"
git push
```

---

## Slice 6: Strengthen Safe Smoke Coverage

**Objective:** Prove the real backend can run against disposable skills without risking production skills. Default tests stay fake-LLM/offline; live smoke stays opt-in.

**Files:**

- Modify: `tests/test_real_mutation_backend_smoke.py`
- Optionally create: `scripts/smoke_mutation_backend.py`
- Modify: `README.md`
- Modify: `skills/operations/SKILL.md`

**Step 1: Inspect current smoke test**

Read `tests/test_real_mutation_backend_smoke.py` and identify whether it checks:

- temp `HERMES_HOME`
- temp local skill root
- no writes to `~/.hermes/skills`
- rollback restores exact pre-hash
- live smoke skips cleanly when backend/model unavailable

**Step 2: Add missing assertions**

Recommended test names:

```python
def test_fake_llm_smoke_uses_temp_skill_root_only(tmp_path): ...
def test_live_smoke_requires_explicit_env_and_temp_home(monkeypatch, tmp_path): ...
def test_smoke_rollback_restores_original_file_set_hash(tmp_path): ...
```

**Step 3: Optional script**

Only create `scripts/smoke_mutation_backend.py` if pytest setup is too awkward for manual operators. If created, it must default to temp dirs and require an explicit `--live` flag for real LLM.

**Step 4: Verify**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_real_mutation_backend_smoke.py -q
```

Optional, only if temp isolation and model config are known safe:

```bash
HERMES_SELF_IMPROVE_LIVE_MUTATION_SMOKE=1 $PY -m pytest tests/test_real_mutation_backend_smoke.py -q
```

If skipped, record exact skip reason.

**Step 5: Commit/push**

```bash
git add tests/test_real_mutation_backend_smoke.py scripts/smoke_mutation_backend.py README.md skills/operations/SKILL.md
git commit -m "test(self-improvement): harden mutation backend smoke isolation"
git push
```

---

## Slice 7: Update Operations Docs to Match Actual Runtime Boundaries

**Objective:** Ensure docs say exactly what is implemented: real backend exists, but it is bounded; memory rollback remains unsupported; status exposes readiness; live smoke is opt-in.

**Files:**

- Modify: `README.md`
- Modify: `skills/operations/SKILL.md`
- Modify: `skills/operations/references/mutation-agent-and-recovery.md`
- Modify: `skills/operations/references/safety-and-apply.md` if safety text is stale
- Test: `tests/test_scheduled_execution_docs.py` or docs-related tests

**Step 1: Search for stale wording**

```bash
rg "fake|unavailable|merge_judge_unavailable|status --json|memory.*rollback|rollback.*memory|tool_trace_verified|real backend" README.md skills tests hermes_self_improvement
```

**Step 2: Update wording**

Use this stance:

> Real semantic skill mutation backend is implemented through a bounded auxiliary-model tool loop. It may execute only `skills_list`, `skill_view`, and `skill_manage`. If runtime tool handlers or auxiliary model routing are unavailable, apply fails closed. Rollback is ledger-bound deterministic restore for skill snapshots. Memory rollback remains fail-closed pending separate store-validation proof.

**Step 3: Add/update docs tests if existing tests assert operational docs**

Ensure docs tests do not imply cron or unattended jobs should run `improve --execute` without review.

**Step 4: Verify**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_scheduled_execution_docs.py tests/test_memory_recovery.py -q
```

**Step 5: Commit/push**

```bash
git add README.md skills/operations/SKILL.md skills/operations/references/mutation-agent-and-recovery.md skills/operations/references/safety-and-apply.md tests/test_scheduled_execution_docs.py tests/test_memory_recovery.py
git commit -m "docs(self-improvement): align mutation backend runtime boundaries"
git push
```

---

## Slice 8: Full Regression, Discovery Check, and Final Push

**Objective:** Prove the whole plugin remains healthy after hardening.

**Files:** none expected except fixes.

**Step 1: Full validation**

```bash
uv sync --group dev
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
bin/hermes-self-improve status
```

Expected:

- py_compile passes
- all tests pass
- status JSON includes `mutation_backend` and `merge_judge`
- no status command mismatch (`status --json` passes if Slice 1 implemented)

**Step 2: Plugin discovery validation**

```bash
PY=${PYTHON:-python3}
$PY - <<'PY'
from hermes_cli.plugins import discover_plugins, get_plugin_manager
import json

discover_plugins(force=True)
info = [p for p in get_plugin_manager().list_plugins() if p['name'] == 'hermes-self-improvement']
print(json.dumps(info, ensure_ascii=False, indent=2))
PY
```

Expected:

- plugin appears
- enabled is true
- error is null
- primary tool surface remains exactly the seven tools:
  - `self_improvement_status`
  - `self_improvement_report`
  - `self_improvement_improve`
  - `self_improvement_calibrate`
  - `self_improvement_plan`
  - `self_improvement_apply`
  - `self_improvement_rollback`

**Step 3: Optional live smoke**

Only if safe temp isolation is confirmed:

```bash
HERMES_SELF_IMPROVE_LIVE_MUTATION_SMOKE=1 $PY -m pytest tests/test_real_mutation_backend_smoke.py -q
```

If skipped, final report must say skipped and why.

**Step 4: Diff audit**

```bash
git status --short
git diff --stat origin/main..HEAD
git diff --name-only origin/main..HEAD
```

Check:

- no Hermes core files changed
- no `.env`, secrets, runtime ledger/report artifacts committed
- no production skills mutated by tests
- no `__pycache__` / `.pytest_cache` committed

**Step 5: Push**

If not already pushed per slice:

```bash
git push
```

**Step 6: Final report in Japanese**

Include only:

- pushed commit list
- final test result
- backend readiness
- merge judge readiness
- live smoke run/skipped
- memory rollback status

---

## Acceptance Checklist

- [ ] `status` output contract is explicit; `status --json` either works or docs/tests no longer mention it.
- [ ] Runtime skill tool resolver has unit coverage independent from the developer’s local Hermes install.
- [ ] Backend readiness is not just module import success; status includes a meaningful readiness/source field.
- [ ] Tool trace records actual calls and result statuses.
- [ ] Apply verification checks tool trace against allowed targets and allowed tools.
- [ ] Auxiliary loop rejects malformed step JSON, disallowed tools, invalid tool args, invalid final schema, and target escape.
- [ ] Merge judge exposes availability/source honestly and preserves failure reasons.
- [ ] Live smoke cannot touch production `~/.hermes/skills` by default.
- [ ] Docs match actual implementation and do not overclaim memory rollback.
- [ ] Full pytest suite passes.
- [ ] Plugin discovery still works.
- [ ] Commits are granular and pushed.

---

## Recommended Commit Sequence

1. `fix(self-improvement): accept status json flag`
2. `test(self-improvement): verify mutation skill tool resolver`
3. `feat(self-improvement): verify mutation tool traces`
4. `fix(self-improvement): harden mutation agent tool protocol`
5. `fix(self-improvement): clarify merge judge readiness and failures`
6. `test(self-improvement): harden mutation backend smoke isolation`
7. `docs(self-improvement): align mutation backend runtime boundaries`

Do not squash unless two adjacent slices end up changing the same tiny parser/doc area. Keep backend, trace verification, judge, smoke, and docs reviewable as separate commits.
