# Skill Mutation Post-Validation Readback Implementation Plan

> **For Hermes:** Use this as the next slice from `2026-05-10-self-improvement-long-term-roadmap.md`. Keep the slice small: add read-back validation after skill create/patch through official skill tools, update artifacts and tests, then update the roadmap.

**Goal:** After a skill create or patch mutation, verify the target by reading it back through official skill tools and record compact `post_validation` status in the decision/result artifact.

**Architecture:** Extend the existing native skill-tool editor harness and validation path. Do not add a new command, approval queue, direct filesystem fallback, or separate maintenance lane. Use `skill_view` / official skill tool results as post-state evidence.

**Tech Stack:** Python, `NativeSkillToolEditorBackend`, `SkillToolExecutor`, `validate_backend_success_result`, pytest.

---

## Context

The long-term roadmap identifies mutation accounting / post-validation as the current reliability gap.

Recent fixes already landed:

- provider-compatible native editor tool context
- natural-language outcome normalization
- same-run trace-backed `created_skills` inference

But true post-validation is still thin. A tool trace can show that `skill_manage(create)` returned success, but artifacts should also show whether the created/changed skill can be read back and has enough structure to be trusted.

## Scope

In scope:

- After `skill_manage(create|patch|edit)` succeeds, call `skill_view(name)` through the same `SkillToolExecutor`.
- Add compact `post_validation` information to the backend final result.
- Require post-validation pass for `skill_create` accepted accounting where possible.
- Record failure as a validation reject, not a silent success.
- Add tests for success and failure.

Out of scope:

- Full semantic quality scoring of skill content.
- Duplicate/existing coverage classification.
- Memory post-validation.
- Direct filesystem reads of skill files.
- Retrospective correction of old run artifacts.

---

## Task 1: Add post-validation helper tests

**Objective:** Define what “post-validation passed” means for skill create/patch at this slice.

**Files:**
- Modify: `tests/test_mutation_backend.py`

**Step 1: Add failing test for create readback success**

Use a fake executor where `skill_manage(create)` succeeds and `skill_view(name)` after creation succeeds.

Expected final result includes:

```python
assert result["success"] is True
assert result["post_validation"]["status"] == "passed"
assert result["post_validation"]["target"] == "demo-created-skill"
assert result["post_validation"]["tool"] == "skill_view"
```

**Step 2: Add failing test for create readback failure**

Use a fake executor where `skill_manage(create)` succeeds but `skill_view(name)` returns `success=False`.

Expected:

```python
assert result["success"] is False
assert result["error"] == "mutation_agent_post_validation_failed"
assert result["post_validation"]["status"] == "failed"
```

**Step 3: Run RED tests**

```bash
python -m pytest tests/test_mutation_backend.py::test_native_backend_post_validates_created_skill -q
python -m pytest tests/test_mutation_backend.py::test_native_backend_rejects_create_when_post_validation_readback_fails -q
```

Expected: FAIL before implementation.

---

## Task 2: Implement compact skill post-validation

**Objective:** Add a helper that reads back target skill through `SkillToolExecutor.call("skill_view", {"name": target})`.

**Files:**
- Modify: `hermes_self_improvement/mutation_backend.py`

**Implementation sketch:**

Add helper:

```python
def _post_validate_skill_target(executor: SkillToolExecutor, *, target: str, task_kind: str) -> dict[str, Any]:
    result = executor.call("skill_view", {"name": target})
    ok = bool(isinstance(result, dict) and result.get("success"))
    content = result.get("content") if isinstance(result, dict) else ""
    content_text = str(content or "")
    has_frontmatter = content_text.lstrip().startswith("---")
    return {
        "status": "passed" if ok and (task_kind != "skill_create" or has_frontmatter) else "failed",
        "tool": "skill_view",
        "target": target,
        "read_success": ok,
        "has_frontmatter": has_frontmatter,
        "content_chars": len(content_text),
        "error": result.get("error") if isinstance(result, dict) else None,
    }
```

Keep it compact. Do not include full skill content.

---

## Task 3: Wire post-validation after finalizer before accepted return

**Objective:** Ensure final result is validated against actual readable target state.

**Files:**
- Modify: `hermes_self_improvement/mutation_backend.py`

**Implementation detail:**

In `NativeSkillToolEditorBackend.run`, when `SUBMIT_MUTATION_RESULT_TOOL` is received:

1. Build `final` as today.
2. Add inferred trace fields as today through `validate_backend_success_result`.
3. If validation succeeds and there are created/changed skills, run post-validation for the expected target.
4. Attach `post_validation` to the result.
5. If post-validation fails, return:

```python
{
  "success": False,
  "error": "mutation_agent_post_validation_failed",
  "post_validation": post_validation,
  "raw_result": validated_result_without_large_content,
}
```

For this slice, validate only `expected_target`, not every item in changed arrays.

---

## Task 4: Preserve trace accounting behavior

**Objective:** Ensure the previous fix still works.

**Files:**
- Modify: `tests/test_mutation_backend.py` if needed.

Run:

```bash
python -m pytest tests/test_mutation_backend.py::test_validate_create_skill_infers_created_skill_from_successful_create_trace -q
python -m pytest tests/test_mutation_backend.py::test_validate_create_skill_does_not_infer_created_skill_without_create_trace -q
```

Expected: PASS.

---

## Task 5: Verify full slice

Run:

```bash
python -m py_compile __init__.py hermes_self_improvement/*.py
python -m pytest tests/test_mutation_backend.py tests/test_runner_steps.py -q
python -m pytest -q
git diff --check
```

Expected current scale: around `539 passed, 2 skipped` or more.

---

## Task 6: Update roadmap and plan index

**Objective:** Keep current position and final goal visible.

**Files:**
- Modify: `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`
- Modify: `.hermes/plans/README.md`

Roadmap update after implementation:

- Mark Slice A as implemented or partially implemented.
- Add progress log entry with commit id.
- Set next active slice to duplicate/existing coverage classification.

Plan index update:

- Add this plan as current active / implemented.
- Link long-term roadmap as the source of truth.

---

## Task 7: Commit and push

Run:

```bash
git status --short --branch
git add hermes_self_improvement/mutation_backend.py tests/test_mutation_backend.py .hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md .hermes/plans/2026-05-10-skill-mutation-post-validation-readback.md .hermes/plans/README.md
git commit -m "fix(self-improvement): post-validate skill mutations"
git push origin main
git status --short --branch
```

---

## Review Notes

### Self-review pass 1

This slice is intentionally narrow. It does not solve skill quality, duplicate coverage, memory validation, or outcome scoring. That is acceptable because the current weakest reliability gap is “artifact says accepted/rejected based on finalizer output rather than verified tool state.”

### Safety checks

- Uses `skill_view`, not direct filesystem reads.
- Does not mark pre-existing skills as newly created without same-run create trace.
- Keeps content out of result payload; only compact metadata is stored.
- Fails closed on readback failure.

### Follow-up

After this slice, move to duplicate/existing coverage classification so `patch-tool-workflow -> safe-patch-usage` becomes a meaningful no-op instead of generic rejection.
