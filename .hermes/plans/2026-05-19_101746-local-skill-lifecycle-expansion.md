# Local Skill Lifecycle Expansion Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Expand `hermes-self-improvement` skill lifecycle handling so every Hermes-changeable local skill is eligible for patch / merge / absorption / Curator-style archive, while protected skills remain excluded and active references are updated rather than treated as blockers.

**Architecture:** Replace the current narrow `agent_created_report()`-only mutable candidate boundary with a resolver that classifies all discoverable skills by protection and changeability. Keep `improve`'s outer user-facing action summary as `apply / defer / skip / block`, but let the internal planner actively choose `mutate_skill` with `maintenance_action=patch|merge`, `archive_skill`, or `create_skill`. Reference coverage becomes duplicate-prevention and merge/patch context, not a reason to create a near-duplicate.

**Tech Stack:** Python plugin code under `hermes_self_improvement/`, pytest, Hermes skill tools (`skills_list`, `skill_view`, `skill_manage`), Curator skill usage/lifecycle helpers, cron/job JSON inspection.

---

## Current context

The 2026-05-19 run created `hermes-sandbox-permission-workflow` even though `sandbox-permission-workflow` already existed locally. Root cause:

- `sandbox-permission-workflow` was not present in the mutable candidate list.
- Alias coverage added it to `reference_skill_coverage` as `mutable: false`, `provenance: reference`.
- The planner saw `no_existing_skill_fit` and created a Hermes-specific duplicate.
- Validation checked skill shape, not semantic duplication against reference coverage.

Ryo's corrected desired boundary:

- Do **not** try to distinguish “user-created” vs “Hermes-created” as a primary criterion; Hermes cannot know this perfectly.
- Skills are editable if they are in a Hermes-changeable local skill location and are not protected.
- Protected means: built-in, hub/vendor-installed, plugin-bundled, external read-only, Curator pinned, Curator archived, or ambiguous/unresolvable.
- Editing includes patching, absorbing into another skill, merging duplicates, updating references, and Curator-style archive.
- If a skill is referenced by cron jobs, prompts, other skills, or config, prefer updating those references to the successor instead of stopping. Only defer/block when references are ambiguous or cannot be safely updated.

## Non-goals

- Do not reintroduce legacy `plan / apply / rollback / outcome` CLI surfaces.
- Do not add a new approval lane or queue.
- Do not edit Hermes core.
- Do not direct-delete skill directories. Archive must be Curator-style / reversible.
- Do not mutate built-in, hub/vendor, plugin-bundled, external read-only, pinned, archived, or ambiguous skills.
- Do not treat historical logs/reports as active references that block archive.

## Acceptance criteria

1. `sandbox-permission-workflow`-class local skills appear as editable candidates unless explicitly protected.
2. `reference_skill_coverage` no longer implies “not editable”; it is duplicate/coverage context. If the covered skill is local and unprotected, it is also a candidate.
3. `create_skill` is blocked/deferred when `reference_positive_skills` or `coverage_fit` identifies an existing local unprotected skill, unless the planner states a concrete durable gap not covered by that existing skill.
4. Merge/archive can be selected and executed through official tools, with references updated first where possible.
5. Active references in cron jobs, cron prompts, skill markdown, and configured prompt files are scanned and either rewritten to successor or explicitly reported as unresolved.
6. Dry-run clearly shows: editable candidates, protected exclusions, reference rewrites that would occur, merge/archive previews, and create-skill duplicate blockers.
7. Mutating run records actual changes and episodes: patched skills, archived skills, rewritten references, skipped/deferred unresolved references, and post-validation status.
8. Existing tests remain green and new regression tests cover the 2026-05-19 duplicate creation case.

---

## Task 1: Update documented policy and remove the outdated agent-created boundary

**Objective:** Align repo guidance with Ryo's corrected boundary before changing code.

**Files:**
- Modify: `AGENTS.md`
- Modify: `skills/operations/SKILL.md`
- Modify: `.hermes/plans/README.md`
- Modify: `hermes_self_improvement/markdown_artifacts.py`
- Modify if still stale: `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`

**Steps:**

1. Replace wording like `Hermes-created local mutable skill` with `Hermes-changeable local skill` or `local unprotected skill`.
2. Specifically update `skills/operations/SKILL.md` line 21 policy text, which currently says skill mutation is limited to `local mutable active/stale Hermes-created skills`.
3. Update `AGENTS.md` safety-boundary text with the same new boundary.
4. Update `hermes_self_improvement/markdown_artifacts.py` wording such as `Mutate only allowed Hermes-created local mutable skills...` so generated reports do not preserve the stale policy.
5. Define protected skill classes exactly: built-in, hub/vendor-installed, plugin-bundled, external read-only, pinned, archived, ambiguous/unresolvable.
6. State that edit includes patch, merge/absorb, reference rewrite, and Curator-style archive.
7. State that active references should be rewritten to successor when deterministic and safe; they are blockers only when ambiguous or unsupported.
8. Add this plan as the current active hardening plan in `.hermes/plans/README.md`.

**Verification:**

```bash
rg -n "Hermes-created local mutable|agent-created|agent_created" AGENTS.md skills/operations/SKILL.md hermes_self_improvement/markdown_artifacts.py .hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md
```

Expected: any remaining matches are historical descriptions or implementation identifiers, not policy boundaries.

---

## Task 2: Introduce a local skill ownership/changeability classifier

**Objective:** Build one deterministic function that decides whether a skill is editable, protected, ambiguous, or reference-only.

**Files:**
- Modify: `hermes_self_improvement/curator_telemetry.py`
- Possibly create: `hermes_self_improvement/skill_inventory.py`
- Test: `tests/test_curator_telemetry.py` or new `tests/test_skill_inventory.py`

**Inventory source decision, based on current Hermes code inspection:**

Do **not** use `skills_list` or `hermes skills list --source local` as the primary implementation source.

Observed current behavior:

- Agent tool `tools.skills_tool.skills_list()` returns only `name`, `description`, and `category`; it does **not** return resolved `SKILL.md` path, root, source directory, pinned/archive state, or enough provenance to distinguish `$HERMES_HOME/skills` from `skills.external_dirs`.
- CLI `hermes skills list --source local` is display-only Rich table output. It has no `--json` flag today, and it also does not show paths.
- CLI `--source local` classifies everything not hub-installed and not bundled-manifest built-in as `local`; because it uses `_find_all_skills()`, which scans both `$HERMES_HOME/skills` and `skills.external_dirs`, external-dir skills can appear as `local` in this CLI view.
- Internal helper `tools.skills_tool._find_all_skills()` is also insufficient as-is because it scans local + external dirs, deduplicates by name, and drops path/root metadata.
- Useful internal primitives do exist: `hermes_constants.get_skills_dir()` / `get_hermes_home()`, `agent.skill_utils.get_external_skills_dirs()`, `agent.skill_utils.get_all_skills_dirs()`, and `agent.skill_utils.iter_skill_index_files()`. These should be used to build a plugin-local inventory adapter with explicit path/root classification.

Implementation direction:

1. Create a plugin-local inventory adapter that scans `get_skills_dir()` directly with `iter_skill_index_files(local_root, "SKILL.md")` and records each resolved `SKILL.md` path.
2. Use `get_external_skills_dirs()` only to classify/exclude external read-only skills and detect ambiguous names, not to create editable candidates.
3. Keep Curator telemetry as usage/lifecycle metadata that is merged onto path-resolved inventory records.
4. Do not shell out to `hermes skills list` for primary inventory unless Hermes later adds stable JSON output with resolved path/root metadata.
5. Do not rely on agent tool `skills_list` for this lifecycle scanner; it is useful for LLM progressive disclosure, not for mutation safety.

Important filtering rule: only skills whose resolved `SKILL.md` path is under the active `$HERMES_HOME/skills/` tree are editable candidates. Skills under `skills.external_dirs` are read-only/protected even if `hermes skills list --source local` displays them as local. Use `hermes_constants.get_skills_dir()` / `get_hermes_home()`; do not hardcode `~/.hermes`.

**Design:**

Create a normalized record shape such as:

```python
{
    "name": "sandbox-permission-workflow",
    "state": "active",
    "changeability": "editable" | "protected" | "ambiguous",
    "mutable": True | False,
    "protection_reason": None | "pinned" | "archived" | "builtin" | "hub" | "plugin_bundled" | "external_readonly" | "ambiguous_name" | "unknown_location",
    "source": "local_skill_registry" | "curator" | "coverage_alias",
    "path": "/Users/.../.hermes/skills/sandbox-permission-workflow/SKILL.md",
    "usage": {...},
}
```

Candidate inclusion rule:

```python
editable = (
    skill_is_in_hermes_changeable_local_skill_area
    and not pinned
    and state not in {"archived"}
    and provenance/source not in protected_classes
    and name_resolution_is_unambiguous
)
```

Important: “user-created” vs “Hermes-created” is not required.

Keep Curator telemetry as a usage/lifecycle subset, not the complete candidate source. `curator_telemetry.py::_normalize_one()` may still reject non-agent-created rows for Curator-specific reporting, but the new inventory merge must add local unprotected skills that Curator telemetry omits.

Add canonical merge/deduplication rules:

1. Canonical identity is the resolved skill name + concrete local `SKILL.md` path.
2. If Curator telemetry and local inventory name/path refer to the same skill, merge records and prefer Curator usage fields.
3. If two different paths resolve to the same canonical name, mark both as `ambiguous_name` and exclude from mutation candidates until disambiguated.
4. If a coverage alias names the same skill as a local editable record, annotate coverage on the editable record instead of creating a separate reference-only candidate.

**Tests:**

- local unpinned active skill under `$HERMES_HOME/skills/` => editable
- local unpinned stale skill under `$HERMES_HOME/skills/` => editable
- skill returned by `hermes skills list --source local` but resolved under `skills.external_dirs` => protected `external_readonly`
- skill returned without path/source metadata => protected/ambiguous, not editable, unless internal API can resolve its path
- pinned local skill => protected `pinned`
- archived local skill => protected `archived`
- hub/built-in/plugin-bundled/external read-only => protected
- ambiguous duplicate name => ambiguous/protected and not LLM-facing editable
- missing provenance but local changeable path => editable, not rejected as `ambiguous_provenance`
- Curator + local inventory duplicate same path => one candidate with usage metadata retained
- same name from two paths => both excluded as `ambiguous_name`

**Verification:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_curator_telemetry.py tests/test_skill_inventory.py -q
```

Expected: all focused tests pass.

---

## Task 3: Feed all editable local skills into evidence pack candidate lists

**Objective:** Ensure the planner sees existing local unprotected skills, not only Curator `agent_created_report()` rows.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/curator_telemetry.py` or new `skill_inventory.py`
- Modify: `hermes_self_improvement/evidence.py`
- Test: `tests/test_runner_steps.py`, `tests/test_target_resolver.py`, and inventory tests

**Steps:**

1. Load Curator telemetry as before for usage/lifecycle facts.
2. Load local skill inventory through the new path-aware adapter, not through `skills_list` / `hermes skills list` table output.
3. Scan `get_skills_dir()` directly and record resolved `SKILL.md` path, skill dir, category, name, description, state, and root.
4. Scan `get_external_skills_dirs()` separately for collision/protection metadata; mark matching names as `external_readonly` or `ambiguous_name` where appropriate, but do not create editable candidates from external dirs.
5. Filter inventory so only skills under `$HERMES_HOME/skills/` become editable candidates.
6. Merge Curator telemetry with the filtered local skill inventory.
7. Preserve Curator usage metadata when available.
8. Include all editable active/stale local skills in `evidence_pack["skill_candidates"]`.
9. Include protected skills in a compact `protected_skill_references` or rejected list for reporting, not as mutation candidates.
10. If a coverage alias matches an editable skill, keep it in `skill_candidates` and annotate coverage fit; do not put it only in `reference_skill_coverage`.
11. Replace stale copy such as `no Hermes-created local mutable skill matches this boundary` in `evidence.py` with the new local-unprotected boundary language.
12. Cap the LLM-facing editable candidate list to a bounded size, for example the top 50 by relevance/usage plus all directly matched coverage/evidence targets. Record any overflow count and excluded names in artifacts, not prompt text.

**Regression fixture:**

- Editable inventory contains `sandbox-permission-workflow`.
- Evidence contains `theme: sandbox_permission_workflow`.
- `build_target_resolution_digest` must put `sandbox-permission-workflow` in `skill_targets` or `skill_targets_other_names`, not only `reference_skill_coverage`.

**Verification:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_target_resolver.py tests/test_runner_steps.py -q
```

Expected: target resolver can attach or at least surface the existing editable skill.

---

## Task 4: Make duplicate/reference coverage a hard create-skill guard

**Objective:** Prevent the exact 2026-05-19 duplicate creation failure.

**Files:**
- Modify: `hermes_self_improvement/improvement_planner.py`
- Modify: `hermes_self_improvement/prompts.py`
- Test: `tests/test_improvement_planner.py`, `tests/test_target_resolver.py`

**Required prompt/context updates:**

- Replace hard-boundary text such as `Only Hermes-created local mutable active/stale skills are mutation targets.` with the new `local unprotected skill` boundary.
- Replace `Reference skills are duplicate/coverage context only and must not be patched, merged into, archived, or created over.` with: reference/coverage skills are duplicate-prevention context; if they resolve to local unprotected skills, they can be patch/merge/archive targets; if protected, they remain read-only blockers for create.

**Rule:**

If a planner decision is `create_skill` and any of these is true:

- `coverage_fit.kind in {"exact_duplicate", "partial_overlap", "reference_only"}` and fit skill is editable/local-unprotected;
- `target_fit_signals.reference_positive_skills` contains a local unprotected skill;
- `reference_skill_coverage` names an editable skill for the same workflow boundary;

then normalize to one of:

- `mutate_skill` with `maintenance_action="patch"` if the existing skill should be extended;
- `mutate_skill` with `maintenance_action="merge"` if a duplicate candidate already exists and should be absorbed;
- `skip` if existing skill fully covers the gap;
- `defer` if the gap is real but successor/patch target is ambiguous.

Only allow `create_skill` when the planner includes a concrete field such as:

```json
"existing_skill_gap": "specific durable capability not covered by sandbox-permission-workflow"
```

and deterministic validation accepts that the gap is not a restatement of the existing skill.

**Regression test:**

Input mirrors the run artifact:

- coverage candidate: `sandbox_permission_workflow`
- reference/local skill: `sandbox-permission-workflow`
- planner attempts `create_skill` named `hermes-sandbox-permission-workflow`

Expected: output is not accepted create; it becomes `mutate_skill`/`defer`/`skip` with reason `duplicates_existing_local_skill` or equivalent.

**Verification:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_improvement_planner.py tests/test_target_resolver.py -q
```

---

## Task 5: Expand merge/absorb semantics in the skill agent task

**Objective:** Let the planner ask for merge/absorption and let the skill agent perform it through official skill tools.

**Status:** implemented in this slice. The task now carries `{source_skill, target_skill}` for merge, the skill-agent prompt requires reading both skills and patching only the successor, the native backend validates merge result structure and tool traces, rejects self-successor/source-mutation merges, and post-validates the patched successor.

**Files:**
- Modify: `hermes_self_improvement/prompts.py`
- Modify: `hermes_self_improvement/skill_agent.py`
- Modify: `hermes_self_improvement/skill_agent_backend.py`
- Test: `tests/test_skill_agent.py`, `tests/test_mutation_backend.py`

**Expected behavior:**

For `mutate_skill` + `maintenance_action="merge"`:

1. Read source skill and target/successor skill.
2. Patch the successor with only non-duplicative useful content.
3. Do not mutate the source in this step; source cleanup belongs to reference-rewrite/archive follow-up.
4. Do not delete the source.
5. Return structured result:

```json
{
  "changed_skills": ["sandbox-permission-workflow"],
  "merged_from": ["hermes-sandbox-permission-workflow"],
  "archive_candidates": ["hermes-sandbox-permission-workflow"]
}
```

**Tests:**

- merge task requires `target_skill` / successor
- merge where source skill equals `target_skill` is rejected or normalized to patch/skip; it must never archive the same skill as its own successor
- skill agent must read both source and target before patch
- duplicate content is not blindly appended
- result includes `merged_from` / `archive_candidates`
- direct delete remains forbidden unless planner selected archive and archive executor handles it

**Verification:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_skill_agent.py tests/test_mutation_backend.py -q
```

---

## Task 6: Implement active reference scanning and deterministic reference rewrite planning

**Objective:** Treat active references as rewrite work, not automatic archive blockers.

**Status:** implemented in this slice. Added deterministic rewrite planning for active cron skills/prompt/script references, Hermes config skill lists, and local skill Markdown/references; historical report mentions are explicitly ignored. Archive dry-runs now include the reference rewrite plan, and mutating archive is deferred when unresolved active references remain. Actual rewrite application is left to Task 7 before archive execution.

**Files:**
- Modify: `hermes_self_improvement/skill_archive_evidence.py`
- Possibly create: `hermes_self_improvement/skill_reference_rewriter.py`
- Modify: `hermes_self_improvement/cli.py`
- Test: `tests/test_skill_archive_evidence.py`, new `tests/test_skill_reference_rewriter.py`

**Reference surfaces:**

Scan at least:

- `~/.hermes/cron/jobs.json`: `skills`, prompt text, `context_from`, and scripts referenced by active jobs
- scripts only when they are explicitly referenced by active cron jobs or active config entries; do **not** scan the entire `~/.hermes/scripts/` directory opportunistically
- `~/.hermes/config.yaml` skill-related fields if present
- local skill markdown under `~/.hermes/skills/**/SKILL.md` and `references/` for exact old skill names
- plugin prompt overlays / runtime prompt files only when they are active operational inputs

**Rewrite plan shape:**

```json
{
  "skill": "hermes-sandbox-permission-workflow",
  "successor": "sandbox-permission-workflow",
  "references": [
    {"surface": "cron_jobs", "path": "~/.hermes/cron/jobs.json", "field": "jobs[].skills", "rewrite": "replace_exact"}
  ],
  "unresolved_references": [],
  "historical_references_ignored": []
}
```

**Execution policy:**

- Dry-run: report planned rewrites.
- Mutating run: apply deterministic exact rewrites before archive.
- If any active reference is ambiguous or unsupported, defer archive and report exact blocker.
- Historical reports/logs are ignored as blockers.

**Tests:**

- cron `skills: [old]` rewrites to `new`
- cron prompt exact old skill name rewrites only when safe and bounded
- historical output/log paths are ignored
- ambiguous substring reference causes `defer_unresolved_reference`
- no reference found allows archive preview/execution path

**Verification:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_skill_archive_evidence.py tests/test_skill_reference_rewriter.py -q
```

---

## Task 7: Wire archive execution after merge and reference rewrites

**Objective:** Allow active cleanup: merge, update references, then archive duplicate/superseded source skills through official Curator-style archive.

**Status:** implemented in this slice. Mutating archive now applies deterministic active reference rewrites only after the official archive hook is available and before archive execution; unresolved/failed rewrites defer archive. Merge results with validated `archive_candidates` now rewrite references to `target_skill`, archive merged source candidates through the official archive hook, and record `merge_archive_result` with archived skills and rewritten references. Dry-run remains preview-only.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/mutation_worker.py`
- Modify: `hermes_self_improvement/improvement_planner.py`
- Test: `tests/test_runner_steps.py`, `tests/test_mutation_worker.py`, archive tests

**Flow:**

1. Planner selects `archive_skill` or merge result produces `archive_candidates`.
2. Validate archive target:
   - editable local skill
   - not pinned
   - not archived
   - not protected
   - successor exists if archive is due to merge/duplicate
3. Build reference rewrite plan.
4. If deterministic rewrites are possible, apply rewrites.
5. Execute archive via official `tools.skill_usage.archive_skill` / injected archive function.
6. Record outcome and episode.

**Important:**

The existing skill says archive may preview when official tool is absent. Keep that behavior for unavailable tool. Do not direct-move files. Reversibility belongs to the official Curator-style archive implementation; this plugin should not invent its own archive storage or filesystem fallback.

**Tests:**

- archive blocked when pinned
- archive blocked when protected
- archive blocked/deferred when unresolved active reference remains
- archive proceeds when references rewritten successfully
- dry-run never mutates references or archive state
- mutating run records `archived_skills` / `rewritten_references`

**Verification:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_runner_steps.py tests/test_mutation_worker.py tests/test_skill_archive_evidence.py tests/test_skill_reference_rewriter.py -q
```

---

## Task 8: Improve reporting and daily digest inputs

**Objective:** Make lifecycle activity visible without confusing candidates with executed mutations.

**Status:** implemented in this slice. Actual-result summaries now distinguish `skill archived` and `references rewritten` from created/patched skill changes, include archived skill names, and carry lifecycle counts into operational report sections and compact tool output (`skill_lifecycle`). Dry-run remains expressed as would-archive previews rather than executed mutations.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/tool_handlers.py`
- Modify: read-only report renderer tests
- Possibly update: `~/.hermes/automations/daily-ops-digest/templates/slack-template.md` after implementation, if daily wording needs new fields

**Report additions:**

Add compact fields/lines:

```text
Skill lifecycle:
- merged 1, archived 1, references rewritten 2, deferred references 0
- archived skills: hermes-sandbox-permission-workflow -> sandbox-permission-workflow
```

Keep existing mutation summary stable:

```text
Actual results:
- actual mutations: skill created N, skill patched N, skill archived N, references rewritten N, memory N
```

**Tests:**

- dry-run says `would merge`, `would rewrite`, `would archive`
- mutating run says `merged`, `rewrote`, `archived`
- daily-friendly output includes skill names but stays bounded
- create candidates are not reported as executed mutations

**Verification:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_cli.py tests/test_tool_handlers.py -q
```

---

## Task 9: Dogfood against the 2026-05-19 duplicate case

**Status:** implemented and dogfooded. Regression coverage now prevents `hermes-*` prefixed duplicate create when a canonical editable local skill exists, emits deterministic duplicate lifecycle archive evidence for `hermes-sandbox-permission-workflow -> sandbox-permission-workflow`, and keeps duplicate archive decisions selected even when the LLM planner omits or skips them. Mutating dogfood archived the duplicate through `skill_usage.archive_skill` and rewrote four active references before archive.

**Objective:** Prove the new behavior would not recreate `hermes-sandbox-permission-workflow`, and can clean it up if it already exists.

**Files:**
- Test fixtures under `tests/fixtures/` if applicable
- Possibly new test: `tests/test_duplicate_skill_lifecycle_regression.py`

**Scenario A: before duplicate exists**

Input:

- existing editable `sandbox-permission-workflow`
- evidence theme `sandbox_permission_workflow`
- proposed duplicate name `hermes-sandbox-permission-workflow`

Expected:

- no `create_skill`
- planner chooses patch existing / skip / defer
- reason mentions existing editable skill coverage

**Scenario B: after duplicate exists**

Input:

- `sandbox-permission-workflow` and `hermes-sandbox-permission-workflow` both editable
- overlap/duplicate evidence
- no unresolved active refs to duplicate

Expected:

- merge duplicate into survivor or skip if content fully redundant
- archive duplicate through official archive path when safe
- reference rewrites happen before archive

**Verification:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_duplicate_skill_lifecycle_regression.py -q
```

---

## Task 10: Full validation and operational rollout

**Objective:** Confirm the plan is implemented safely and ready for the 04:00 cron run.

**Commands:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
git diff --check
hermes self-improvement status
hermes self-improvement improve --dry-run --json > /tmp/self-improvement-local-skill-lifecycle-dry-run.json
```

Inspect the dry-run JSON:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY - <<'PY'
import json
p='/tmp/self-improvement-local-skill-lifecycle-dry-run.json'
data=json.load(open(p))
print(data.get('summary'))
print(data.get('step_decisions', {}).get('skill', {}).get('planner', {}).get('summary'))
PY
```

Expected:

- no unguarded duplicate `create_skill` for existing local skills
- protected exclusions are visible and bounded
- merge/archive candidates include successor and reference-rewrite state
- no unexpected file changes from dry-run

Final implementation checklist:

```bash
git status --short
git diff --stat
git diff -- . ':!.hermes/plans/*'
```

Commit only after tests and dry-run pass.

---

## Implementation progress

### 2026-05-19 first slice

Implemented Tasks 1-4 foundation:

- Updated active policy/docs wording from the old `Hermes-created` boundary to `$HERMES_HOME/skills/` local unprotected skills.
- Added path-aware local skill inventory in `curator_telemetry.py` that scans the active local skills directory, merges usage metadata, marks editable local skills as `local_unprotected`, and protects pinned / archived / bundled / hub / external read-only / ambiguous names.
- Updated evidence filtering so `local_unprotected` / `local_skill_inventory` candidates are LLM-visible mutation targets.
- Fed editable local skills into target-resolution and planner flows; `sandbox-permission-workflow`-class skills are now editable targets, not reference-only coverage.
- Added a deterministic duplicate-create guard: a proposed `create_skill` that overlaps an existing local unprotected skill is normalized to a no-op skip with `create_skill_duplicates_existing_local_skill`, unless the planner supplies a concrete `existing_skill_gap`.

Validation so far:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_skill_inventory.py tests/test_curator_telemetry.py tests/test_target_resolver.py tests/test_skill_planner.py -q
# 57 passed
```

Remaining tasks: Task 5 merge/absorb semantics, Task 6 active reference rewrite planning, Task 7 archive execution after rewrites, Task 8 lifecycle reporting, Task 9 dogfood against the duplicate case, Task 10 full validation/rollout.


## Review checklist for this plan

- Does the plan remove the false “agent-created only” boundary?
- Does it avoid using unverifiable user-vs-Hermes creation provenance?
- Does it keep protected sources safe?
- Does it make archive/merge active enough, rather than report-only forever?
- Does it update references instead of stopping whenever a reference exists?
- Does it preserve dry-run/no-agent cron safety?
- Does it avoid new primary CLI surfaces or new approval lanes?
- Does it include regression coverage for the exact 2026-05-19 failure?
