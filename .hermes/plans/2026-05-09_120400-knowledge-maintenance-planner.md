# Knowledge Maintenance Planner Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Status:** implemented 2026-05-09. Full test passed (`521 passed, 2 skipped`), normal and report-context dry-runs were dogfooded, and the implementation was committed as `feat: add knowledge maintenance planning`.

**Goal:** Make `improve` automatically choose the right knowledge-base maintenance action — patch, merge, archive, create, memory mutation, skip, defer, or block — instead of only surfacing unresolved workflow gaps or over-focusing on new skill creation.

**Architecture:** Keep the existing `improve` loop and resolver/planner split. The resolver remains attachment-only and returns only `attach_existing_skill / memory_candidate / unresolved / skip_noise`; the planner owns all mutation decisions. Add richer maintenance affordances and inventory context to the existing evidence/planner digest, then let the existing planner/editor/memory mutation path execute safe choices through official tools.

**Tech Stack:** Python, pytest, existing `hermes self-improvement` CLI, existing planner/editor/mutation worker modules, official Hermes `skill_manage` / memory tools only.

---

## Current context

Recent dry-runs show the system now finds useful evidence but does not yet convert it into maintenance actions:

```text
hermes self-improvement improve --dry-run
Would apply: 0
Deferred: 1
Blocked: 35
Coverage gaps: 3
Target resolution: unresolved 6
```

Recurring workflow gaps are visible:

- timeout workflow: 147 events
- patch tool workflow: 36 events
- sandbox permission workflow: 12 events

The resolver is now correctly attachment-only:

```text
attach_existing_skill
memory_candidate
unresolved
skip_noise
```

The remaining problem is not “create more skills”. The goal is broader: the plugin should decide whether to update an existing skill, merge similar local skills, archive stale/duplicate local skills, create a new local skill only when warranted, mutate memory, skip noise, defer weak/ambiguous cases, or block unsafe ones.

## Non-goals

- Do not create a separate inventory lane, approval queue, or new user-facing apply mode.
- Do not reintroduce `create_new_skill` or `defer_unresolved` as resolver kinds.
- Do not edit built-in, hub-installed, plugin-bundled, external-dir, pinned, archived, or ambiguous-provenance skills.
- Do not make Hermes core changes or top-level `hermes self-improvement ...` CLI integration.
- Do not parse LLM-authored Markdown as control state.
- Do not treat raw tool output, terminal transcripts, or run artifact dumps as memory content.

## Desired behavior

### Resolver responsibility

Resolver only attaches or classifies observation target fit:

```text
attach_existing_skill: clear fit to an existing mutable local skill
memory_candidate: durable fact/preference/environment detail candidate
unresolved: potentially useful, but no clear existing target or needs planner judgment
skip_noise: transient/one-off/already-handled noise
```

Unsupported resolver vocabulary should continue to fail closed as `block_reason=unsupported_resolution_kind`.

### Planner responsibility

Planner decides maintenance actions:

```text
patch_skill
merge_skills
archive_skill
create_skill
memory_add / memory_replace / memory_remove only when safe
skip
defer
block
```

User-facing summaries stay semantic:

```text
apply / defer / skip / block
```

Internal action names can be richer, but do not add user-facing apply categories.

---

## Proposed data model changes

### Replace `create_skill_affordance` wording with maintenance-oriented affordance

Current coverage candidates expose:

```json
{
  "resolution_kind": "unresolved",
  "allow_create_skill": true,
  "create_skill_affordance": {...}
}
```

Change this to a broader planner hint:

```json
{
  "resolution_kind": "unresolved",
  "unresolved_reason": "no_existing_skill_fit",
  "maintenance_affordance": {
    "workflow_boundary": "patch tool workflow",
    "evidence_count": 36,
    "representative_evidence_ids": ["unmatched_..."],
    "not_memory_because": "procedural recurring workflow",
    "no_existing_editable_skill_fit": true,
    "possible_actions": [
      "patch_existing_skill",
      "merge_or_consolidate",
      "archive_stale_or_duplicate",
      "create_skill",
      "skip_as_noise"
    ],
    "create_skill_name_seed": "patch-tool-workflow"
  }
}
```

Keep `allow_create_skill` only if needed as a transition field inside artifacts/tests, but planner prompt and new tests should use `maintenance_affordance` as the primary concept.

### Skill inventory context

Keep hard mutation boundaries, but separate inventory roles:

```json
{
  "editable_skills": [
    "Hermes-created local mutable active/stale skills"
  ],
  "reference_skills": [
    "built-in/hub/plugin/external skills, summarized for duplicate/coverage checks only"
  ],
  "archival_candidates": [
    "Hermes-created local mutable stale/superseded candidates"
  ],
  "filtered_skill_counts": {
    "builtin": 12,
    "hub": 4,
    "plugin-bundled": 3
  }
}
```

Reference skills must not become mutation targets. They only help planner avoid duplicate new skill creation or understand coverage.

### Raw memory candidate guard

Before memory mutation planning, reject or reroute content that looks like:

- raw terminal output
- JSON run artifact snippets
- tool result blobs
- stack traces without distilled durable fact
- command transcript summaries

Preferred handling:

```text
raw tool/run output -> workflow/diagnostic evidence, not memory_add
```

---

## Step-by-step implementation plan

### Task 1: Add regression tests for maintenance affordance naming

**Objective:** Lock the shift from create-skill-specific hints to general maintenance hints.

**Files:**
- Modify: `tests/test_target_resolver.py`
- Modify: `tests/test_unmatched_evidence_candidates.py`

**Step 1: Write failing tests**

Add assertions that knowledge coverage candidates include `maintenance_affordance` and do not expose `create_skill_affordance` as the primary hint.

Expected behavior:

```python
candidate = make_knowledge_coverage_candidate(
    gap_kind="recurring_workflow_without_skill",
    evidence_ids=["u1"],
    evidence_count=5,
    workflow_boundary="browser profile troubleshooting",
    resolution_kind="unresolved",
    rationale="Repeated browser profile failures lack a suitable local skill.",
)

hint = candidate["target_resolution_hint"]
assert hint["resolution_kind"] == "unresolved"
assert hint["unresolved_reason"] == "no_existing_skill_fit"
assert "maintenance_affordance" in hint
assert "create_skill_affordance" not in hint
assert hint["maintenance_affordance"]["possible_actions"] == [
    "patch_existing_skill",
    "merge_or_consolidate",
    "archive_stale_or_duplicate",
    "create_skill",
    "skip_as_noise",
]
```

**Step 2: Run RED**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_target_resolver.py::test_knowledge_coverage_candidate_includes_maintenance_affordance -q
```

Expected: FAIL because current code still uses `create_skill_affordance`.

**Step 3: Implement minimal change**

Modify `hermes_self_improvement/evidence.py`:

- replace `create_skill_affordance` with `maintenance_affordance`
- rename `candidate_skill_name_seed` to `create_skill_name_seed`
- keep `resolution_kind: unresolved`
- keep `unresolved_reason: no_existing_skill_fit`
- preserve `likely_targets` and representative evidence ids

**Step 4: Run GREEN**

```bash
$PY -m pytest tests/test_target_resolver.py tests/test_unmatched_evidence_candidates.py -q
```

Expected: pass.

---

### Task 2: Add planner digest tests for editable/reference skill inventory

**Objective:** Give planner enough context to choose patch/merge/archive/create without making non-editable skills mutable targets.

**Files:**
- Modify: `tests/test_skill_planner.py` or create `tests/test_knowledge_maintenance_planner.py`
- Modify: `hermes_self_improvement/planner.py`
- Possibly modify: `hermes_self_improvement/evidence.py`

**Step 1: Write failing tests**

Create a digest with:

- one editable Hermes-created local skill
- one built-in/reference skill with related description
- one unresolved maintenance affordance

Assert planner digest includes separate sections:

```python
assert digest["knowledge_maintenance"]["editable_skills"][0]["name"] == "local-patch-workflow"
assert digest["knowledge_maintenance"]["reference_skills"][0]["name"] == "safe-patch-usage"
assert digest["knowledge_maintenance"]["reference_skills"][0]["mutation_allowed"] is False
assert digest["knowledge_maintenance"]["maintenance_candidates"][0]["possible_actions"]
```

Also assert reference skills are not added to `skill_candidates` selected for editor.

**Step 2: Run RED**

```bash
$PY -m pytest tests/test_knowledge_maintenance_planner.py -q
```

Expected: FAIL because the digest lacks `knowledge_maintenance` inventory sections.

**Step 3: Implement minimal digest builder changes**

In `planner.py`, add compact `knowledge_maintenance` context to `build_skill_planner_digest()`:

```python
knowledge_maintenance = {
    "editable_skills": [...],
    "reference_skills": [...],
    "archival_candidates": [...],
    "maintenance_candidates": [...],
    "hard_boundaries": [...],
}
```

Use existing candidate provenance filtering helpers where possible. Do not add a separate planning lane; this is extra context inside the existing planner digest.

**Step 4: Run GREEN**

```bash
$PY -m pytest tests/test_knowledge_maintenance_planner.py tests/test_skill_planner.py -q
```

Expected: pass.

---

### Task 3: Extend planner schema/prompt to support maintenance actions

**Objective:** Let the planner choose the correct maintenance action, while keeping the external action summary as apply/defer/skip/block.

**Files:**
- Modify: `hermes_self_improvement/planner.py`
- Modify: `hermes_self_improvement/prompts.py` if planner base prompt references action vocabulary
- Modify tests around planner normalization, likely `tests/test_skill_planner.py`

**Step 1: Write failing tests**

Add normalization tests for planner decisions:

```python
raw = {
    "decisions": [
        {
            "decision": "create_skill",
            "skill": "patch-tool-workflow",
            "source_evidence_ids": ["coverage_1"],
            "rationale": "No editable skill fits; recurring procedural workflow.",
            "risk": "low",
        },
        {
            "decision": "merge_skills",
            "skill": "old-skill",
            "target_skill": "newer-skill",
            "source_evidence_ids": ["inv_1"],
            "rationale": "Duplicate local mutable skills.",
            "risk": "medium",
        },
    ]
}
```

Expected:

- `create_skill`, `merge_skills`, `archive_skill`, `patch_skill` normalize as known maintenance decisions.
- unsafe or missing required fields become `block` or `defer`, not guessed.
- non-editable targets block.

**Step 2: Run RED**

```bash
$PY -m pytest tests/test_skill_planner.py -q
```

Expected: FAIL for unknown decisions.

**Step 3: Implement minimal schema/prompt changes**

Add or map planner decisions:

```text
patch_skill -> existing run_editor/editor path
merge_skills -> editor path with explicit merge instruction and successor target
archive_skill -> existing archive lifecycle path
create_skill -> existing skill_create worker/editor path, if already present; otherwise defer until Task 4
skip/defer/block -> existing summary buckets
```

Important:

- Do not resurrect resolver `create_new_skill`.
- Do not add user-facing `auto_apply_with_ledger` or similar modes.
- Planner prompt must say: “New skill creation is one option, not the default; prefer patch/merge/archive when evidence supports it.”

**Step 4: Run GREEN**

```bash
$PY -m pytest tests/test_skill_planner.py tests/test_target_resolver.py -q
```

Expected: pass.

---

### Task 4: Implement safe execution mapping for maintenance actions

**Objective:** Make mutating `improve --from-run` able to execute safe planner maintenance decisions through existing official tool paths.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Modify: `hermes_self_improvement/mutation_worker.py`
- Modify tests in `tests/test_mutation_worker.py`, `tests/test_skill_planner.py`, or new `tests/test_knowledge_maintenance_execution.py`

**Step 1: Write failing tests**

Test dry-run preview:

- `patch_skill` produces an editor preview, not direct filesystem edits.
- `merge_skills` produces an editor instruction for target skill and archive/skip instruction for source only when both are local mutable and evidence-backed.
- `archive_skill` uses existing Curator archive lifecycle path.
- `create_skill` uses `skill_manage(action="create")` through the constrained worker and validates post-state/tool trace.

Test hard blocks:

- target is built-in/hub/plugin/external -> block
- `merge_skills` source or destination unknown -> block/defer
- create skill duplicates reference skill -> defer or skip, not create

**Step 2: Run RED**

```bash
$PY -m pytest tests/test_knowledge_maintenance_execution.py -q
```

Expected: FAIL because execution mapping is incomplete.

**Step 3: Implement minimal mapping**

Prefer existing paths:

```text
patch_skill -> run_editor
merge_skills -> run_editor for target + optional archive source through existing archive path
archive_skill -> existing archive execution
create_skill -> official skill tool worker, with exact content generated by editor/planner and post-validation
```

If `create_skill` execution is not currently robust enough, implement it as dry-run preview first and leave mutating execution blocked with a clear reason. Do not fake success from natural language output.

**Step 4: Run GREEN**

```bash
$PY -m pytest tests/test_knowledge_maintenance_execution.py tests/test_mutation_worker.py tests/test_skill_planner.py -q
```

Expected: pass.

---

### Task 5: Filter raw tool/run output out of memory mutation candidates

**Objective:** Prevent JSON blobs and command transcripts from becoming `memory_add` candidates.

**Files:**
- Modify: `hermes_self_improvement/conversation_memory.py`
- Modify: `hermes_self_improvement/evidence.py` or memory candidate builder path
- Modify: `tests/test_conversation_memory_candidates.py`
- Possibly modify: `tests/test_memory_inventory_planner.py`

**Step 1: Write failing tests**

Add cases where candidate content includes:

```text
{"status":"success","output":"action_summary ..."}
terminal output with command logs
run artifact path + JSON dump
stack trace only
```

Expected:

- not emitted as `memory_add`
- either skipped with reason `raw_tool_output_not_memory` or routed as workflow/diagnostic evidence
- distilled durable fact still allowed when content is a clean user preference/environment fact

**Step 2: Run RED**

```bash
$PY -m pytest tests/test_conversation_memory_candidates.py -q
```

Expected: FAIL for raw blob filtering if currently absent.

**Step 3: Implement minimal guard**

Add helper such as:

```python
def looks_like_raw_tool_or_run_output(text: str) -> bool:
    ...
```

Keep it conservative. Block obvious blobs; do not overfit to every possible string.

**Step 4: Run GREEN**

```bash
$PY -m pytest tests/test_conversation_memory_candidates.py tests/test_memory_inventory_planner.py -q
```

Expected: pass.

---

### Task 6: Improve dry-run summary for maintenance decisions

**Objective:** Make dry-run output show what the plugin is trying to maintain without requiring artifact inspection.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Modify: `tests/test_cli_surface.py`

**Step 1: Write failing tests**

Expected summary examples:

```text
Knowledge maintenance:
- patch candidates: safe-patch-usage 1
- merge candidates: old-skill -> new-skill 1
- archive candidates: obsolete-skill 1
- create candidates: patch-tool-workflow 1
- unresolved: timeout_workflow 1
```

Do not add new action summary categories; keep:

```text
Action summary:
- Would apply: N, Deferred: N, Skipped: N, Blocked: N
```

**Step 2: Run RED**

```bash
$PY -m pytest tests/test_cli_surface.py -q
```

Expected: FAIL until summary renderer includes maintenance details.

**Step 3: Implement compact summary lines**

Add compact counters from planner decisions and maintenance candidates. Keep output short and stable.

**Step 4: Run GREEN**

```bash
$PY -m pytest tests/test_cli_surface.py -q
```

Expected: pass.

---

### Task 7: Dogfood with current dry-runs

**Objective:** Verify the system now turns current evidence into concrete, safe maintenance decisions or clear defer/block reasons.

**Files:**
- No code changes unless dogfood exposes a bug; if it does, add regression test first.

**Step 1: Run full tests**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
git diff --check
```

Expected: all pass.

**Step 2: Run normal dry-run**

```bash
hermes self-improvement improve --dry-run
```

Expected improvement over current baseline:

- recurring workflow gaps do not just disappear into `Deferred: 1`
- dry-run summary shows knowledge maintenance candidates/actions
- raw tool output memory candidates are not reported as blocked memory_add
- unresolved items have useful reason buckets

**Step 3: Run report-context dry-run**

```bash
hermes self-improvement improve --dry-run --from-report /Users/ryo.nakae/.hermes/self-improvement/daily/latest.json
```

Expected:

- report remains reference-only
- diagnostic signals may affect maintenance judgment, but do not become direct mutation decisions

**Step 4: Inspect artifacts**

Read the latest run artifact and confirm:

- resolver vocabulary contains no `create_new_skill` or `defer_unresolved`
- planner decisions include `patch_skill / merge_skills / archive_skill / create_skill / defer / skip / block` only where justified
- non-editable skills are never mutation targets
- raw output is not memory content

---

### Task 8: Commit and push in one coherent milestone

**Objective:** Keep the repo in a clean, reviewable state.

**Commands:**

```bash
git status --short
git diff --check
git add \
  hermes_self_improvement/evidence.py \
  hermes_self_improvement/planner.py \
  hermes_self_improvement/runner_steps.py \
  hermes_self_improvement/mutation_worker.py \
  hermes_self_improvement/conversation_memory.py \
  hermes_self_improvement/cli.py \
  tests/test_knowledge_maintenance_planner.py \
  tests/test_knowledge_maintenance_execution.py \
  tests/test_target_resolver.py \
  tests/test_unmatched_evidence_candidates.py \
  tests/test_conversation_memory_candidates.py \
  tests/test_cli_surface.py \
  README.md \
  skills/operations/SKILL.md \
  .hermes/plans/README.md \
  .hermes/plans/2026-05-09_120400-knowledge-maintenance-planner.md
git commit -m "feat: add knowledge maintenance planning"
git push
```

Only include files actually changed. Do not stage unrelated runtime artifacts under `~/.hermes/self-improvement/`.

---

## Files likely to change

Core:

- `hermes_self_improvement/evidence.py`
- `hermes_self_improvement/planner.py`
- `hermes_self_improvement/runner_steps.py`
- `hermes_self_improvement/mutation_worker.py`
- `hermes_self_improvement/conversation_memory.py`
- `hermes_self_improvement/cli.py`
- `hermes_self_improvement/prompts.py` if planner base prompt needs vocabulary updates

Tests:

- `tests/test_target_resolver.py`
- `tests/test_unmatched_evidence_candidates.py`
- `tests/test_skill_planner.py`
- `tests/test_conversation_memory_candidates.py`
- `tests/test_cli_surface.py`
- New: `tests/test_knowledge_maintenance_planner.py`
- New: `tests/test_knowledge_maintenance_execution.py` if execution mapping needs isolated coverage

Docs:

- `README.md`
- `skills/operations/SKILL.md`
- `.hermes/plans/README.md`

## Risks and mitigations

### Risk: Planner starts creating too many skills

Mitigation:

- Keep `create_skill` one option among patch/merge/archive/skip/defer/block.
- Require recurring evidence, workflow boundary, no editable skill fit, and duplicate/reference-skill check.
- Prefer defer when evidence is generic tool failure without workflow boundary.

### Risk: Reference skills accidentally become mutation targets

Mitigation:

- Add tests that reference skills appear only under `reference_skills` with `mutation_allowed=false`.
- Revalidate target provenance at execution time.

### Risk: Merge/archive becomes destructive

Mitigation:

- Only local mutable Hermes-created skills can be merged/archived.
- Archive requires existing lifecycle preflight and no active references.
- Merge should patch the successor first; archive source only if successor validation passes.

### Risk: Raw output filtering drops useful memory facts

Mitigation:

- Conservative filter: block obvious blobs/transcripts only.
- Clean distilled facts remain allowed.
- Add tests for both blocked blob and allowed distilled fact.

### Risk: Plan becomes a new “lane” in disguise

Mitigation:

- Keep everything inside existing `improve` evidence -> resolver -> planner -> worker flow.
- No new command, no approval queue, no separate inventory runner.
- Summary improvements are render-only.

## Success criteria

A successful implementation should make the next dry-run look more like this:

```text
Knowledge maintenance:
- patch candidates: ...
- merge candidates: ...
- archive candidates: ...
- create candidates: ...
- unresolved: ...
Action summary:
- Would apply: N, Deferred: N, Skipped: N, Blocked: N
```

And less like the current state:

```text
Coverage gaps: 3
Target resolution: unresolved 6
Would apply: 0
Deferred: 1
Blocked: raw memory_add blobs
```

The important measure is not “more new skills”. It is whether the plugin can autonomously choose the right knowledge maintenance action for each evidence cluster while respecting local mutable skill and official memory-tool boundaries.
