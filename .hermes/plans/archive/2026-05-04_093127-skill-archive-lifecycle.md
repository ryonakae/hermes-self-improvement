# Skill archive lifecycle for hermes-self-improvement

**Status:** implemented; monitor real archive outcomes via credit assignment and daily reports
**Created:** 2026-05-04 09:31

## Goal

Make `hermes-self-improvement` decide and execute Curator-style skill archiving as part of the normal autonomous improvement loop.

The target behavior is not “report-only first” and not a local, user-specific cleanup heuristic. The ideal state is:

```text
observe skill + memory + scorer/evaluator outcomes
→ identify whether each skill should be edited, left alone, or archived
→ archive obsolete local mutable skills through the same lifecycle semantics Curator uses
→ exclude archived skills from future improvement candidates
→ record the archive decision as an episode/outcome source
→ use future evidence to improve archive judgment quality
```

Archive is a lifecycle transition, not delete. The plugin should not physically remove skill files as its normal lifecycle action.

## Current context

The plugin already has parts of this, but they are not connected into the main loop:

- `analysis.py` has `scan_skill_lifecycle_candidates(...)`, but it currently emits `action: skill_delete` for explicit deprecated/obsolete markers.
- `analysis.py` treats skill lifecycle proposals as approval-required high-risk items.
- `planner.py` lists `archive` under `human_review_for`, so archive is explicitly routed away from autonomous execution.
- `runner_steps.py` and `prompts.py` are centered on small edits via `run_editor`, not lifecycle transitions.
- `mutation_worker.py` supports `skill_manage` actions `create`, `patch`, `edit`, `delete`, `write_file`, `remove_file`; it does not expose `archive`.
- `curator_telemetry.py` already reads Curator lifecycle state and rejects already-archived skills from normal candidates.
- Operational assumption: built-in Curator is paused, not disabled, so the plugin can read Curator telemetry/lifecycle state while avoiding duplicate autonomous maintenance execution.
- `autonomous_policy.py` currently says destructive skill/memory changes are out of scope. That remains true for delete, but archive should become an allowed lifecycle transition with Curator semantics.

The missing abstraction is a first-class `skill_archive` decision path.

## Design principles

1. **Archive is a normal lifecycle action.**
   - Do not model archive as delete.
   - Do not call it destructive.
   - Do not require a separate approval/apply surface.

2. **Curator remains the lifecycle substrate.**
   - Curator should be paused, not disabled. Paused Curator still provides telemetry / lifecycle state as source of truth while avoiding a second autonomous maintenance actor making overlapping changes.
   - The plugin should produce smarter archive decisions and execute through the official skill lifecycle mechanism.
   - Archive execution should call the same Curator runtime primitive (`tools.skill_usage.archive_skill`) rather than direct file moves.

3. **General implementation only.**
   - No hardcoded `~/.hermes` paths except via `get_hermes_home()` / runtime config helpers.
   - No references to Ryo-specific job names, Slack channels, custom skills, or local report directories.
   - Active-reference detection must use generic Hermes surfaces: enabled cron job definitions, skill registry/provenance, plugin/skill metadata, and Curator telemetry.

4. **Single ideal flow, not staged half-measures.**
   - Dry-run shows what would be archived.
   - Normal `improve` archives when the policy and evidence support it.
   - Archived skills no longer appear as edit candidates.

5. **Preprocessing preserves judgment material.**
   - Programmatic preprocessing should reduce noise before the LLM, but it must not classify candidates into edit/archive/skip or become the real judge by silently dropping ambiguous or contradictory evidence.
   - Deterministic preprocessing should be high-recall and evidence-preserving: keep compact evidence snippets, match kinds, confidence, rejected/ambiguous reasons, and raw source pointers in artifacts.
   - The planner receives a compact digest plus enough representative evidence to make the decision itself. Preprocessing must not pre-decide edit vs archive vs skip except for hard invariant failures.
   - Hard filters are only for invariant violations such as pinned, already archived, non-local provenance, bundled/plugin/external skill, or unresolved target identity.
   - Soft evidence labels such as `deprecated_marker`, `successor_hint`, `possible_active_reference`, or `weak_alias_match` must be passed through with confidence and reason instead of being collapsed into a yes/no archive decision.

## Target behavior

Given a local mutable skill with:

- explicit deprecation/obsolete metadata or text,
- a canonical successor / absorbed-into relationship,
- duplicate bridge behavior,
- no active references in enabled jobs or active skill attachments,
- not pinned,
- not plugin-bundled / hub-installed / external / builtin,
- Curator lifecycle state `active` or `stale`,

`improve` should produce:

```json
{
  "skill": "old-skill-name",
  "decision": "archive_skill",
  "archive_reason": "superseded_by_canonical_skill",
  "successor": "canonical-skill-name",
  "evidence_ids": ["..."],
  "active_reference_count": 0
}
```

On non-dry-run, it should execute the lifecycle transition:

```text
skill active/stale → archived
```

and record an episode:

```json
{
  "target_kind": "skill",
  "decision": "archive_skill",
  "execution_status": "applied",
  "lifecycle_before": "active|stale",
  "lifecycle_after": "archived"
}
```

## Proposed implementation

### 1. Rename lifecycle semantics from delete to archive

Files:

- `hermes_self_improvement/analysis.py`
- tests around lifecycle candidates

Changes:

- Replace `skill_delete` lifecycle candidate generation with `skill_archive`.
- Rename helper intent from `_skill_delete_candidate_reason` to `_skill_archive_candidate_reason`.
- Expand explicit markers:
  - YAML/frontmatter-like:
    - `deprecated: true`
    - `obsolete: true`
    - `status: deprecated`
    - `status: obsolete`
    - `status: superseded`
    - `superseded_by: <skill>`
    - `absorbed_into: <skill>`
  - body markers:
    - `deprecated compatibility bridge`
    - `canonical name is now`
    - `absorbed into`
- Output fields:
  - `action: skill_archive`
  - `target_skill`
  - `successor_skill` when discoverable
  - `archive_reason`
  - `before_hash`

### 2. Add generic archive evidence preparation

Create:

- `hermes_self_improvement/skill_archive_evidence.py`
- `tests/test_skill_archive_evidence.py`

Purpose:

Prepare compact, generally distributable archive evidence for each candidate skill without turning preprocessing into a brittle local heuristic or a hidden decision engine.

Inputs:

- skill name
- optional qualified names / aliases from registry metadata
- loaded config object
- cron jobs file resolved via Hermes runtime home/config helpers
- plugin skill registry / Curator telemetry rows when available

Evidence classes:

- `active_cron_skill_attachment`
- `active_cron_prompt_reference`
- `paused_cron_reference`
- `skill_successor_reference`
- `deprecated_marker`
- `obsolete_marker`
- `superseded_by_marker`
- `absorbed_into_marker`
- `ambiguous_successor_hint`

Only these should block archive:

- enabled cron skill attachment
- enabled cron prompt reference with command/use semantics, if deterministically detected
- active config/preload reference
- pinned state
- bundled/hub/external/builtin provenance
- plugin-bundled provenance
- unresolved canonical skill name

These should not block archive by themselves:

- paused cron references
- archived artifacts
- historical reports
- logs
- old sessions
- arbitrary workspace files

Important distinction:

- **Blocking-reference checks** answer: “Would archiving this skill break an active configured dependency?” They should use stable, current runtime surfaces only: enabled cron skill attachments, active config/preload references, provenance, pinned state, and current lifecycle state.
- **Archive judgment evidence** answers: “Does the observation history suggest this skill is obsolete, superseded, or only a compatibility bridge?” This can and should use the plugin's existing observation pipeline, including summarized tool failures, session outcomes, user corrections, Curator telemetry, and historical maintenance artifacts when they are already part of the evidence pack.
- Historical/log/session/report-derived evidence must be compacted and labeled as observational evidence, not treated as an active dependency reference.

Preprocessing rules:

- Use deterministic parsing for frontmatter markers and registry/provenance data.
- Use stable Hermes helpers for current config/cron paths; do not hardcode user paths.
- Do not perform broad ad-hoc filesystem searches through logs, reports, old sessions, or arbitrary workspaces as part of archive gating.
- Do preserve observation-derived signals that are already collected by the plugin evidence pipeline, with `confidence` / `match_kind` / `reason` / `source_kind` / `source_pointer`.
- Keep uncertain items as evidence with `confidence` / `match_kind` / `reason`; do not discard them just because they are ambiguous.
- Provide representative evidence snippets and source pointers in artifacts, capped and redacted.
- Do not rank `archive_skill` above `run_editor`, or `run_editor` above `archive_skill`, in preprocessing. Present evidence neutrally and let the LLM planner choose one decision.
- The LLM planner should see enough context to make the edit/archive/skip decision directly, while execution preflight is limited to hard invariants.

Return compact evidence:

```json
{
  "target_skill": "old-skill-name",
  "canonical_skill_name_resolved": true,
  "archive_markers": [
    {"kind": "deprecated_marker", "match": "deprecated: true", "confidence": "high"}
  ],
  "active_reference_count": 0,
  "blocking_references": [],
  "non_blocking_references": [{"kind": "paused_cron_reference", "count": 1}],
  "successor_skill": "canonical-skill-name",
  "successor_validation": "valid_active_skill",
  "evidence_uncertainties": []
}
```

### 3. Add archive judgment to planner digest

Files:

- `hermes_self_improvement/planner.py`
- `hermes_self_improvement/evidence.py` if needed
- tests for planner digest / normalization

Changes:

- Include lifecycle/archive evidence in each skill candidate row:
  - `lifecycle_state`
  - `pinned`
  - `provenance`
  - `archive_markers`
  - `successor_skill`
  - `successor_validation`
  - `active_reference_count`
  - `blocking_reference_count`
  - `evidence_uncertainties`
  - `representative_evidence`
- Add allowed decision:

```text
archive_skill
```

- Remove archive from `human_review_for` in planner constraints.
- Keep `delete` and `merge` out of autonomous execution.
- Before execution, run a simple invariant/preflight check so `archive_skill` is only executed when:
  - target exists in candidate names
  - target has attached lifecycle/archive evidence
  - active references do not block archive
  - target is local mutable active/stale
  - target is not pinned
  - target is not archived already
  - canonical skill name is resolved
  - successor, if present, validates to an existing non-archived skill

If any invariant fails, mark that action as blocked with a reason such as:

```text
archive_blocked_by_active_reference
archive_blocked_by_provenance
archive_without_lifecycle_evidence
archive_blocked_by_unresolved_skill_name
archive_blocked_by_invalid_successor
```

The LLM planner may choose `archive_skill`, `run_editor`, or `skip`, but it must not invent archive targets outside the observed candidate set. Deterministic preprocessing supplies candidate facts and representative evidence neutrally; the LLM decides using those facts; the execution preflight only enforces hard invariants.

### 4. Update autonomous policy

File:

- `hermes_self_improvement/autonomous_policy.py`
- `tests/test_autonomous_policy.py`

Change `improve` policy from only edit/memory changes to include skill lifecycle archive:

```json
{
  "allowed_skill_lifecycle_actions": ["archive"],
  "skill_archive_requires": [
    "local_mutable_active_or_stale",
    "not_pinned",
    "not_archived",
    "not_bundled_hub_external_builtin",
    "archive_evidence_attached",
    "no_blocking_active_references",
    "tool_mediated_lifecycle_transition"
  ]
}
```

Do not add delete. Delete remains out of scope.

### 5. Add lifecycle executor

Files:

- `hermes_self_improvement/mutation_worker.py`
- `hermes_self_improvement/runner_steps.py`
- possible adapter module: `hermes_self_improvement/skill_lifecycle.py`
- tests for tool-mediated archive execution

Use Curator's existing runtime primitive:

```python
from tools import skill_usage
skill_usage.archive_skill(skill_name)
```

Current Hermes Curator behavior:

- archive directory is `${HERMES_HOME}/skills/.archive` — singular `.archive`, not `.archives`.
- `tools.skill_usage._archive_dir()` returns `_skills_dir() / ".archive"`.
- `tools.skill_usage.archive_skill(name)` moves the skill directory to `.archive/<skill>/` using `Path.rename(...)`, with `shutil.move(...)` fallback for cross-device moves.
- category nesting is flattened into `.archive/<skill>/`; collisions get a timestamp suffix.
- usage state is set to `archived` via `set_state(skill_name, STATE_ARCHIVED)`.
- restore is `tools.skill_usage.restore_skill(name)` / `hermes curator restore <name>`.

Expected function shape:

```python
def execute_skill_archive_operation(context: dict[str, Any], *, archive_fn=None) -> dict[str, Any]:
    ...
```

Input context:

```json
{
  "action": "archive",
  "name": "skill-name",
  "reason": "superseded_by_canonical_skill",
  "successor": "canonical-skill-name",
  "before_state": "active"
}
```

Output:

```json
{
  "success": true,
  "tool_name": "skill_usage.archive_skill",
  "message": "archived to ${HERMES_HOME}/skills/.archive/skill-name",
  "before_state": "active",
  "after_state": "archived"
}
```

Do not shell out to `mv` and do not implement a separate `.archives` path. The plugin should call the Curator lifecycle primitive, not duplicate filesystem behavior.

Do not add `archive` to `skill_manage` actions and do not call `skill_manage(action="archive")`. Archive is a dedicated Curator lifecycle primitive, not a skill content mutation.

### 6. Route archive decisions in improve

Files:

- `hermes_self_improvement/cli.py`
- `hermes_self_improvement/runner_steps.py`
- `hermes_self_improvement/episodes.py`
- tool compact summaries in `tool_handlers.py`

Changes:

- Split planner decisions into:
  - `run_editor`
  - `archive_skill`
  - `memory_candidate`
  - `evaluator_candidate`
  - `skip`
  - `defer`
- Run archive executor for `archive_skill` decisions during non-dry-run.
- In dry-run, show:

```text
Skill lifecycle:
- archive candidates N
- would archive M skills
```

- In normal run, show:

```text
Skill lifecycle:
- archived M skills
- blocked K skills
```

- Add compact tool result fields only as counts and artifact path:

```json
"skill_lifecycle": {
  "archive_candidates": 2,
  "archived": 1,
  "blocked": 1
}
```

No full skill content in tool results.

### 7. Ensure archived skills leave the improvement candidate set

Files:

- `hermes_self_improvement/curator_telemetry.py`
- tests around archived lifecycle state

Current code already rejects `state == "archived"`. Keep that behavior and add regression tests proving:

- archived skills are not editable candidates
- archived skills are not duplicate-prevention candidates
- archived skills are not restore candidates
- archive episodes can still be used as outcome evidence

### 8. Record archive decisions for existing outcome learning

Files:

- existing outcome scoring module, if a direct extension point exists
- `hermes_self_improvement/credit_assignment.py`
- tests

Archive episodes should preserve enough structured data for the existing outcome/credit loop to learn from future observations. Avoid building a separate archive-specific scoring subsystem unless the current outcome path already has a direct extension point.

Episode fields:

```json
{
  "decision": "archive_skill",
  "target_skill": "old-skill-name",
  "archive_reason": "superseded_by_canonical_skill",
  "successor_skill": "canonical-skill-name",
  "successor_validation": "valid_active_skill",
  "blocking_reference_count": 0,
  "evidence_uncertainties": [],
  "executor_result": {"success": true, "message": "archived to ..."},
  "lifecycle_before": "active",
  "lifecycle_after": "archived"
}
```

Future outcome interpretation can use:

Positive signals:

- no future active reference failures caused by missing skill
- replacement/successor skill receives successful use
- fewer lookup failures for old skill name after alias guidance disappears
- no manual restore/unarchive event

Negative signals:

- user asks for archived skill back
- enabled cron/config still referenced it and failed
- successor mapping was wrong
- archive caused repeated skill lookup misses

Credit assignment should bucket by:

- `archive_reason`
- `successor_present`
- `active_reference_count`
- `provenance`
- `lifecycle_state_before`
- `evidence_uncertainty_count`

### 9. Update prompts and docs

Files:

- `hermes_self_improvement/prompts.py`
- `skills/operations/SKILL.md`
- `README.md`
- tests that assert old wording does not say archive is human-review-only

Prompt changes:

- Planner prompt should explicitly distinguish:
  - edit skill content
  - archive obsolete skill
  - skip
- Editor prompt should not handle archive; archive is executor/lifecycle path, not editor path.
- Operations skill should say archived skills are out of normal improvement scope, but active/stale obsolete skills may be archived by `improve` through lifecycle transition.

### 10. Validation

Focused tests:

```bash
python3 -m pytest tests/test_skill_archive_evidence.py -q
python3 -m pytest tests/test_autonomous_policy.py tests/test_planner.py -q
python3 -m pytest tests/test_mutation_worker.py tests/test_runner_steps.py -q
python3 -m pytest tests/test_credit_assignment.py tests/test_episode_ledger.py -q
```

Full validation:

```bash
python3 -m py_compile __init__.py hermes_self_improvement/*.py
python3 -m pytest tests -q
bin/hermes-self-improve status
bin/hermes-self-improve improve --dry-run --scorer llm
bin/hermes-self-improve improve --dry-run --json
bin/hermes-self-improve calibrate --dry-run
python3 - <<'PY'
from hermes_cli.plugins import discover_plugins, get_plugin_manager
import json

discover_plugins(force=True)
info = [p for p in get_plugin_manager().list_plugins() if p['name'] == 'hermes-self-improvement']
print(json.dumps(info, ensure_ascii=False, indent=2))
PY
git diff --check
```

Expected dry-run should include lifecycle summary without huge tool result payloads.

## Files likely to change

- `hermes_self_improvement/analysis.py`
- `hermes_self_improvement/planner.py`
- `hermes_self_improvement/autonomous_policy.py`
- `hermes_self_improvement/mutation_worker.py`
- `hermes_self_improvement/runner_steps.py`
- `hermes_self_improvement/cli.py`
- `hermes_self_improvement/tool_handlers.py`
- `hermes_self_improvement/episodes.py`
- `hermes_self_improvement/credit_assignment.py`
- new `hermes_self_improvement/skill_archive_evidence.py`
- possible new `hermes_self_improvement/skill_lifecycle.py`
- `hermes_self_improvement/prompts.py`
- `skills/operations/SKILL.md`
- `README.md`
- tests covering the above

## Implementation status

Implemented commits through `e9cfb6b` plus the fake LLM archive fixture:

- lifecycle candidates emit `skill_archive`, not `skill_delete`;
- `archive_skill` is a planner decision and no longer routed to human review;
- archive execution calls `tools.skill_usage.archive_skill(...)` only;
- dry-run and agent tool summaries stay compact and point to artifacts;
- active cron/config/preload references are attached as evidence and block execution only in preflight;
- successor hints are validated when the planner selects one;
- archived skills are excluded from scanner / explicit candidate / Curator candidate paths;
- archive decisions are recorded as episodes with lifecycle metadata;
- credit assignment now groups archive outcomes by archive reason, successor presence/validation, blocking reference count, and lifecycle state;
- reports surface recent archive lifecycle counts and blocked reasons;
- fake LLM planner fixture proves an archive decision can flow through the LLM planner path without hitting an external model.

Follow-up monitoring:

- watch real archive outcomes in credit assignment after mutating `improve` starts archiving actual obsolete skills;
- adjust daily digest wording only if the current report lifecycle summary is too terse for operations.

## Non-goals

- No physical delete for normal lifecycle retirement.
- No user-specific archive rules.
- No separate approval/apply/rollback CLI surface.
- No direct filesystem fallback.
- No archive handling inside the editor prompt.
- No treatment of already archived skills as normal improvement candidates.

## Done criteria

The work is complete when:

1. `improve --dry-run` shows archive decisions for obsolete active/stale local mutable skills.
2. `improve` archives those skills through the official lifecycle mechanism.
3. Archived skills disappear from future edit candidates.
4. Archive decisions are recorded as episodes.
5. Archive outcomes feed credit assignment and future planner calibration.
6. Tool results remain compact.
7. The implementation contains no user-environment-specific paths, skill names, cron IDs, or local heuristics.
8. Programmatic preprocessing is high-recall, evidence-preserving, and decision-neutral: soft evidence labels and uncertainties are visible to the planner/artifact, while only hard invariants are filtered before LLM judgment.
