# Runtime Overlay Seed and Prompt Kernel Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Make repo-managed planner/editor/evaluator base prompts thin and stable, while moving rich operating guidance into runtime-private prompt overlays initialized from repo-tracked default seed prompts.

**Architecture:** Keep `hermes_self_improvement/prompts.py` as the small, versioned contract layer: role, schema, allowed tools/decisions, hard safety boundaries, and overlay loading semantics. Add repo-tracked Markdown default seeds as distribution assets, materialize them into `${HERMES_HOME:-~/.hermes}/self-improvement/evaluator/` only when no active overlay exists, and let DSPy/GEPA evolve the runtime-private overlay artifacts from there. Validate overlays with a unified `max_lines=150` and `max_chars=12000` limit.

**Tech Stack:** Python, pytest, existing `prompt_overlays.py`, `prompt_candidate_optimizer.py`, `prompts.py`, CLI setup/status/calibrate paths, repo docs.

---

## Context and decisions

- Ryo wants to trust LLM judgment for fuzzy self-improvement decisions rather than hard-code placement and apply rules in program logic.
- Repo-managed prompt text should become a thin kernel so base prompt hash changes are rare and existing active overlays remain usable.
- DSPy/GEPA improves runtime-private overlay prompts, so rich planner/editor/evaluator guidance should live there.
- Repo-tracked default seed prompts are allowed. They are distribution/bootstrap assets, not the active source of truth after materialization.
- Unified overlay limits:
  - `max_lines = 150`
  - `max_chars = 12000`
- Limits should use line count as the primary human-maintainability guard and character count as the hard abnormal-size guard.
- Do not introduce new command surfaces, approval queues, planner lanes, or scorer subsystems.

## Non-goals

- Do not make GEPA/DSPy run in `improve`; `calibrate` remains the prompt/evaluator improvement path.
- Do not support full prompt replacement. Continue additive overlay guidance only.
- Do not allow overlays to change hard safety boundaries, allowed tools, direct filesystem restrictions, secrets handling, or immutable skill scope.
- Do not move runtime active overlays into git.
- Do not edit Hermes core.

---

## Task 1: Add line-aware overlay validation tests

**Objective:** Define the new overlay limit behavior before changing validation.

**Files:**
- Modify: `tests/test_prompt_overlays.py`
- Modify if needed: `tests/test_prompt_candidate_optimizer.py`

**Steps:**
1. Add a test that a `system_addendum` with exactly 150 lines and fewer than 12000 chars is accepted.
2. Add a test that 151 lines raises a clear error, e.g. `prompt_content_too_many_lines:system_addendum`.
3. Add a test that a single long line over 12000 chars still raises `prompt_content_too_large:system_addendum`.
4. Add a test that both `system_addendum` and `user_addendum` are checked independently.
5. Run focused tests:
   ```bash
   PY=${PYTHON:-.venv/bin/python}
   $PY -m pytest tests/test_prompt_overlays.py tests/test_prompt_candidate_optimizer.py -q
   ```
   Expected: new tests fail before implementation.

---

## Task 2: Implement unified overlay limits

**Objective:** Replace character-only validation with line + character validation while keeping existing sensitive-content and replacement checks.

**Files:**
- Modify: `hermes_self_improvement/prompt_overlays.py`
- Modify: `hermes_self_improvement/prompt_candidate_optimizer.py`

**Implementation notes:**
- Introduce constants near the current `MAX_ADDENDUM_CHARS`:
  ```python
  MAX_ADDENDUM_LINES = 150
  MAX_ADDENDUM_CHARS = 12000
  ```
- Count lines with `value.splitlines()`.
  - Empty string is already ignored by callers or accepted as zero/one line; keep behavior simple.
  - Do not wrap or mutate text automatically.
- Error naming should be stable and testable:
  ```text
  prompt_content_too_many_lines:{key}
  prompt_content_too_large:{key}
  ```
- Keep `_redact_text(...)` sensitive-content validation unchanged.
- Update optimizer normalization so truncation respects the 12000 char cap. Do not silently trim to 150 lines inside validation; optimizer may truncate generated text if needed, but persisted candidates should validate exactly.

**Verification:**
```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_prompt_overlays.py tests/test_prompt_candidate_optimizer.py -q
```
Expected: focused tests pass.

---

## Task 3: Add repo-tracked Markdown default overlay seeds

**Objective:** Provide rich initial operating guidance without making `prompts.py` thick.

**Files:**
- Create: `defaults/prompt-overlays/planner.md`
- Create: `defaults/prompt-overlays/editor.md`
- Create: `defaults/prompt-overlays/evaluator.md`
- Create/modify tests as needed: `tests/test_default_prompt_overlay_seeds.py`

**Seed content guidelines:**
- Keep each seed under 150 lines and 12000 chars.
- Use Markdown headings and compact bullets.
- Treat seeds as general defaults, not Ryo-specific personal behavior.
- Include enough guidance to preserve current quality when base prompts become thin.

**Planner seed should cover:**
- `apply / defer / skip / block` operating semantics.
- Trust LLM judgment for fuzzy placement and improvement value.
- USER / MEMORY / Skill boundary using official Hermes docs:
  - USER: preferences, communication style, expectations, profile.
  - MEMORY: agent notes, environment/project/runtime facts, stable conventions.
  - Skill: reusable how-to procedures, workflows, pitfalls, verification.
- Create-skill vs attach-existing-skill judgment.
- Generic workflow vs project-specific skill judgment.
- Memory should not become raw log/tool-output storage.
- Low/medium-risk safe changes should not be over-deferred.

**Editor seed should cover:**
- Inspect target skill first.
- Make minimal durable procedural edits.
- Use official skill tools only.
- Return valid mutation result schema.
- Prefer no-op when evidence and target diverge.
- Do not broaden requested operation.

**Evaluator seed should cover:**
- Evaluate whether self-improvement made the agent more useful in this user’s environment.
- Penalize memory log pollution, over-defer, unsafe mutation, and stale/duplicate knowledge.
- Reward correct placement, useful skill creation, compact durable memories, and clear dry-run summaries.
- Feed lessons into overlay evolution rather than hard-coded program rules.

**Verification:**
- Add tests that read all three Markdown files and assert line/char limits.
- Add tests that required keywords are present enough to catch accidental empty/thin seeds, without overfitting prose.

---

## Task 4: Materialize default seeds into runtime-private overlays

**Objective:** On setup or preflight, create active runtime overlay candidates from default seeds only when no valid active overlay exists.

**Files:**
- Modify: `hermes_self_improvement/prompt_overlays.py`
- Modify likely: `hermes_self_improvement/setup.py` or the module that creates default evaluator assets
- Modify likely: `hermes_self_improvement/cli.py` if setup orchestration lives there
- Test: `tests/test_prompt_overlays.py` or new `tests/test_default_prompt_overlay_seeds.py`

**Design:**
- Add helper such as:
  ```python
  materialize_default_prompt_overlays(config: dict[str, Any], *, force: bool = False) -> dict[str, Any]
  ```
- It reads repo seed Markdown files and writes runtime prompt candidates using existing `write_prompt_candidate` / promotion helpers.
- It should set metadata fields such as:
  ```json
  {
    "source": "default_seed",
    "seed_path": "defaults/prompt-overlays/planner.md",
    "runtime_private": true
  }
  ```
- It must not overwrite valid active overlays unless `force=True` is explicitly passed by an internal test/helper. No user-facing force command is required in this slice.
- It should promote all three roles as one initial generation where possible, or at least ensure `active-prompts.json` has active entries for planner/editor/scorer.
- Keep current role naming compatibility: evaluator overlay target maps to role `scorer` in existing code. Docs can use “evaluator/scorer” where needed.

**Important:**
- The repo seed is not the active source of truth after materialization.
- Later GEPA/DSPy promotions should supersede the default seed active entries.
- If seed materialization fails, `improve` should still fail-safe to thin base prompt and report compact status, not crash normal read-only status.

**Verification:**
- Test first-run materialization creates active prompts for planner/editor/scorer.
- Test second run does not overwrite a manually/promoted active overlay.
- Test invalid seed over line/char limit fails closed with a clear status.

---

## Task 5: Kernelize repo-managed base prompts

**Objective:** Thin `prompts.py` so base prompt hash is stable and rich judgment guidance lives in runtime overlays.

**Files:**
- Modify: `hermes_self_improvement/prompts.py`
- Modify: `tests/test_prompts.py`
- Modify any tests expecting old exact prompt phrases.

**Planner base kernel should keep only:**
- Role identity.
- Follow output schema exactly.
- Allowed decisions: `run_editor`, `create_skill`, `skip`, `defer`, `memory_candidate`, `evaluator_candidate`.
- Hard safety boundaries are enforced by program logic; do not request bypasses.
- Use runtime-private overlay guidance when available.
- Return JSON only.

**Editor base kernel should keep only:**
- Role identity.
- Use only allowed skill tools and `submit_mutation_result`.
- Inspect target before mutation.
- Do not mutate out-of-scope targets or arbitrary files.
- Follow planner’s exact requested operation.
- Use runtime-private overlay guidance when available.
- Always submit structured result.

**Scorer/evaluator base kernel should keep only:**
- Role identity and classification context hook.
- Evaluate according to provided schema/rubric and runtime overlay guidance.
- Do not grant mutation permission; scoring is advisory unless existing code says otherwise.

**Verification:**
- Tests should assert essential contracts, not long exact prompt text.
- Run:
  ```bash
  PY=${PYTHON:-.venv/bin/python}
  $PY -m pytest tests/test_prompts.py tests/test_prompt_overlays.py -q
  ```

---

## Task 6: Make overlay source metadata visible without exposing prompt text

**Objective:** Dry-run/status artifacts should show whether guidance came from thin base only, default seed, GEPA/manual runtime overlay, or none, without leaking full prompt contents into compact tool results.

**Files:**
- Modify: `hermes_self_improvement/prompts.py`
- Modify likely: `hermes_self_improvement/cli.py`
- Modify tests: `tests/test_cli_surface.py`, `tests/test_episode_ledger.py`, `tests/test_feedback_loop.py` if needed

**Implementation notes:**
- Extend `_prompt_source(...)` metadata with fields such as:
  ```json
  {
    "overlay_source": "none|default_seed|optimizer|manual|unknown",
    "overlay_active": true,
    "overlay_generation_id": "...",
    "overlay_hash": "..."
  }
  ```
- Derive source from candidate payload fields. Do not include full `system_addendum` / `user_addendum` in compact summaries.
- Keep existing hash/path/generation metadata.

**Verification:**
- Existing run artifacts and episode records still include prompt hashes.
- Compact CLI/tool summaries include source/hash/path only, not prompt text.

---

## Task 7: Wire default materialization into setup/preflight

**Objective:** Ensure thin base prompts are not the normal quality path for initialized runtimes.

**Files:**
- Modify setup path found during implementation.
- Modify `bin/hermes-self-improve setup --check` behavior only if needed.
- Tests near setup/status if present.

**Behavior:**
- `setup` creates runtime directories and materializes default prompt overlays if active overlays are absent.
- `status` can report whether active overlays exist and their source, but should remain read-only.
- `improve --dry-run` may optionally warn if no active overlay exists; avoid silently mutating from dry-run unless existing setup/preflight already creates default assets. Prefer setup-time mutation.

**Verification:**
```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests -q
bin/hermes-self-improve setup --check
bin/hermes-self-improve status
bin/hermes-self-improve improve --dry-run
```

---

## Task 8: Update docs and bundled operations skill

**Objective:** Make the source-of-truth split obvious to future agents and users.

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md` if needed
- Modify: `skills/operations/SKILL.md`
- Modify: `skills/operations/references/architecture.md`
- Modify: `skills/operations/references/operations.md` if setup behavior changes
- Modify: `.hermes/plans/README.md`

**Docs should state:**
- Repo base prompts are thin kernels.
- Repo default seed Markdown files are bootstrap/distribution assets.
- Runtime-private overlays are the active source of truth after setup.
- DSPy/GEPA evolves runtime overlays through `calibrate`.
- Overlay guidance is limited to 150 lines and 12000 chars per role.
- Full prompt text stays in runtime artifacts, not compact tool results.

---

## Task 9: Full validation and dogfood

**Objective:** Prove the new prompt split works and is inspectable.

**Commands:**
```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
bin/hermes-self-improve status
git diff --check
bin/hermes-self-improve improve --dry-run
```

**Artifact checks:**
- Dry-run succeeds.
- Prompt sources show active overlay source metadata.
- Compact output does not include full overlay text.
- Existing active overlays are not overwritten unexpectedly in Ryo’s runtime.
- If no active overlay exists in a temp/test runtime, default seed materializes.

**Commit:**
```bash
git add defaults/prompt-overlays hermes_self_improvement tests README.md AGENTS.md skills/operations .hermes/plans
 git commit -m "feat: seed runtime prompt overlays"
 git push
```

---

## Risks and mitigations

- **Risk:** Kernelizing base prompts invalidates existing overlays because base hash changes.
  - **Mitigation:** This is expected once. Materialize default seeds for the new base hash and preserve metadata showing the transition.
- **Risk:** Default seed becomes mistaken as the active prompt source.
  - **Mitigation:** Docs and metadata say repo seed is bootstrap only; runtime active overlays are authoritative.
- **Risk:** Overlay guidance becomes too large and harms prompt budget.
  - **Mitigation:** 150-line + 12000-char validation, compact Markdown, source metadata only in summaries.
- **Risk:** Too much judgment moves back into program logic during implementation.
  - **Mitigation:** Program handles only hard invariants, seed loading, validation, metadata, and setup. Fuzzy judgment remains in overlay text and LLM decisions.
- **Risk:** Existing tests overfit old prompt wording.
  - **Mitigation:** Update tests to assert contracts and schema, not prose.

## Open questions

None blocking. The agreed initial limit is unified across roles: 150 lines and 12000 characters.
