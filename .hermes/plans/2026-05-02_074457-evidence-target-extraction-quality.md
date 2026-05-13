# Evidence Target Extraction Quality Plan

**Status:** completed

## Goal

Improve the analyzer/evidence-builder layer so the global planner receives more evidence that is attached to the correct mutable skill candidate.

The immediate problem is not that the planner cannot reason. The latest planner-quality dry-run shows the planner is receiving too little targeted evidence:

```text
evidence: 50
attached_candidate_count: 1
unmatched_evidence_count: 47
skill_target_missing: 37
skill_not_in_curator_candidates: 10
selected_with_evidence: 1
action_like_skips: 0
```

This plan improves target extraction and evidence attachment while keeping mutation scope unchanged.

## Non-goals

- Do not broaden mutation targets beyond skill / memory / scorer / evaluator.
- Do not make terminal failures directly mutate arbitrary workflow scripts, automations, runtime config, repo docs, or Hermes core.
- Do not pass full session transcripts or full tool outputs to the planner.
- Do not make Curator obsolete. Curator remains source of truth for skill lifecycle / mutable candidates.
- Do not implement semantic vector search or heavy LLM classification inside hooks. Hooks stay observation-only.
- Do not add compatibility for old plan/apply/approval surfaces.

## Current architecture summary

Current flow:

```text
runtime hooks -> event log -> analysis/evidence pack -> planner digest -> planner -> editor
```

Target attachment currently happens mostly by extracting skill names from evidence payloads:

- top-level `skill_name`, `target_skill`, `skill`
- event fields `skill_name`, `target_skill`, `skill`, `name`
- JSON parsed from `args_preview` / `result_preview` keys such as `name`, `skill_name`, `target_skill`, `skill`
- qualified candidate exact match first, then bare-name fallback

This works for direct `skill_view` / `skill_manage` failures that include a `name` field. It does not work well for:

- terminal commands operating inside a known project or automation path
- patch/read/search errors that imply a workflow skill but do not name it
- skill_manage failures against plugin-bundled names such as `hermes-self-improvement:operations`
- tool failures where the correct target is a class-level skill, not the exact missing skill name
- repeated tool-error clusters that should map to skill maintenance / file workflow / terminal workflow skills

## Design principle

Target extraction should produce **candidate evidence hints**, not mutation permission.

A stronger target hint only means:

```text
evidence can be shown to the planner/editor for this mutable skill candidate
```

It does not mean:

```text
this skill must be edited
```

The planner still decides, and the editor still reads current skill content and may skip.

## Desired outcome

After this work, dry-run proof counts should improve in a measurable way:

```text
attached_candidate_count: higher than current 1
unmatched_evidence_count: lower than current 47
selected_with_evidence: unchanged or higher
action_like_skips: 0
```

The exact target is not “attach everything.” A good result is fewer target-missing events because obvious class-level mappings are attached to reasonable mutable local skills.

## Target extraction tiers

### Tier 1: Explicit skill target

Already mostly implemented. Keep it as highest confidence.

Sources:

- `skill_view(name=...)`
- `skill_manage(name=...)`
- `args_preview.name`
- explicit event fields

Behavior:

- exact qualified candidate match first
- bare-name fallback second
- if multiple mutable candidates share bare name, attach to all and let planner decide

### Tier 2: Canonical alias / bundled-name mapping

Map known non-mutable or plugin-bundled names to the mutable operational skill that actually stores local procedure.

Examples from recent evidence:

```text
hermes-self-improvement:operations -> hermes-self-improvement-plugin or hermes-development-maintenance depending on evidence context
operations -> hermes-self-improvement-plugin only when tool/error context is self-improvement plugin operations
software-development:systematic-debugging -> no mutable candidate unless a local custom equivalent exists
```

Important: avoid hardcoding user-specific prefixes such as `hermes-custom:`. Alias rules should be generic and explainable.

Recommended implementation:

- Add a small `target_hints.py` module with deterministic rules.
- Each rule returns:

```python
{
  "target_skill": "...",
  "confidence": "high|medium|low",
  "source": "explicit|alias|tool_class|path|proposal_cluster",
  "reason": "..."
}
```

### Tier 3: Tool-class to workflow-skill mapping

Some failures imply a skill class rather than a named skill.

Examples:

- `patch` validation failures -> file workflow / software-development skill candidate
- `terminal` timeout / nonzero exit due command shape -> terminal workflow / debugging skill candidate
- `skill_view` / `skill_manage` not_found -> skill management / Hermes skill maintenance skill candidate
- memory provider failures -> memory hygiene / memory-and-live-context skill candidate

This should attach evidence only if a matching mutable local candidate exists. Candidate matching should use a ranked list of possible skill names and descriptions, not create new targets.

Candidate examples in this repo/user environment:

```text
hermes-skill-management
hermes-development-maintenance
hermes-standalone-plugin-development
hermes-memory-and-live-context
hermes-memory-hygiene
multi-agent-transcript-ingestion
```

### Tier 4: Path / command based hints

Terminal and file tools often include useful paths.

Examples:

```text
~/.hermes/automations/weather-status/weather_status.py
~/.hermes/automations/swarm-checkins-status/swarm_checkins_status.py
~/.hermes/plugins/hermes-self-improvement/...
```

Rules:

- Paths under the current plugin repo can hint `hermes-self-improvement-plugin` / `hermes-development-maintenance` depending on context.
- Paths under `~/.hermes/automations/gmail-newsletter-observer` can hint `gmail-newsletter-observer` if that mutable skill exists.
- Paths under `~/.hermes/automations/gmail-purchase...` can hint `gmail-purchase-live-context` if that mutable skill exists.
- Weather/Swarm automation paths should not auto-create or mutate arbitrary docs; they can produce low-confidence hints only if a matching existing mutable skill candidate is present.

Path hints should be low/medium confidence unless the path stem strongly matches a candidate name.

### Tier 5: Proposal-cluster hints

`analysis.py` already produces proposal targets such as:

```text
skill_maintenance_skills
file_workflow_skills
memory_or_recall_policy
browser_skills
```

These cluster findings should feed the planner digest as cluster-level evidence, not only as proposal scoring material. The planner can then decide if a class-level skill should receive an editor task.

Implementation idea:

- Convert high-signal tool error clusters into synthetic evidence records with `target_hints`.
- Keep them separate from raw event evidence:

```text
evidence.kind = "tool_error_cluster_evidence"
evidence.source = "analysis_cluster"
evidence.target_hints = [...]
```

## Proposed implementation tasks

### Task 1: Add target hint data model and tests

Create `hermes_self_improvement/target_hints.py`.

Core functions:

```python
extract_target_hints(event_or_evidence, *, candidate_names: list[str]) -> list[dict]
rank_target_hints(hints, *, candidate_names: list[str]) -> list[dict]
```

Tests:

- explicit `skill_manage(name="dir:skill")` yields exact/bare target hint
- plugin-bundled `hermes-self-improvement:operations` does not become a mutation target by itself
- `patch` validation error maps to file workflow candidate only if present
- `terminal` command with automation path maps to matching automation skill only if present
- no candidate means no attachable target

### Task 2: Integrate hints into planner digest attachment

Modify planner digest construction so evidence can attach via:

1. explicit skill name
2. target hints
3. cluster hints

Digest row should include target resolution metadata:

```json
{
  "evidence_match": "exact|bare_name|hint_alias|hint_tool_class|hint_path|cluster",
  "target_hint_source": "...",
  "target_hint_confidence": "...",
  "target_hint_reason": "..."
}
```

Keep unmatched evidence accounting, but split reasons more precisely:

```text
skill_target_missing
hint_no_candidate
hint_low_confidence
skill_not_in_curator_candidates
```

### Task 3: Add cluster evidence from analysis findings

Use `analysis.py` findings/proposals to add compact synthetic evidence into the evidence pack.

Requirements:

- no raw huge outputs
- include count, tool_name, error_kind, representative compact examples
- include target hints, not hard mutation decisions
- do not duplicate identical raw event ids into multiple unrelated candidates without reason

### Task 4: Add quality metrics for hint extraction

Extend `planner_quality` with:

```text
hint_attached_evidence_count
hint_attached_candidate_count
attachments_by_match_kind
unmatched_by_reason
cluster_evidence_count
```

Dry-run should show a compact form, for example:

```text
- proof: attached candidates 5, unmatched evidence 31, selected with evidence 2, action-like skips 0
- target hints: hint-attached evidence 12, cluster evidence 4, match kinds exact 3 / bare 2 / path 4 / tool-class 3
```

### Task 5: Tighten planner prompt around hinted evidence

Planner prompt should distinguish explicit evidence from inferred hints:

- Explicit exact/bare evidence is stronger.
- Hint/path/tool-class evidence is advisory and should be used conservatively.
- Do not select `run_editor` on weak hint-only evidence unless the improvement is small, local, and clearly procedural.
- If evidence is class-level, prefer `human_review` or `skip` unless a local umbrella skill is clearly the right target.

### Task 6: Manual comparison against Curator baseline

Add a dry-run inspection script or documented command that prints:

```text
Curator candidates: N
Raw evidence: N
Explicit attached: N
Hint attached: N
Cluster attached: N
Unmatched: N
Planner selected: N
```

Comparison framing:

- Curator still supplies candidate source-of-truth and lifecycle state.
- Target hints add evidence routing that Curator does not attempt to do.
- Success is not “planner beats Curator overall”; success is “planner sees actionable evidence attached to the right Curator candidates.”

## Tests to add

Suggested files:

- `tests/test_target_hints.py`
- `tests/test_skill_planner.py`
- `tests/test_runner_steps.py`
- possibly `tests/test_evidence_pack.py` if evidence-pack builder tests already exist

Test cases:

1. Explicit qualified skill name exact match beats bare fallback.
2. Bare skill name attaches to all matching mutable candidates.
3. Tool-class hint attaches patch validation failure to a file workflow candidate if present.
4. Terminal path hint attaches automation path to matching existing mutable skill.
5. Plugin-bundled skill names are not directly mutable targets.
6. Hint-only low confidence evidence does not cause `run_editor` unless planner explicitly returns valid evidence-backed decision.
7. Planner quality reports hint attachment counts and match-kind counts.
8. Dry-run summary includes target hint proof counts.

## Runtime verification

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
hermes self-improvement status
hermes self-improvement improve --dry-run
hermes self-improvement improve --dry-run --json
```

Manual expected inspection:

```text
attached_candidate_count should increase from 1
unmatched_evidence_count should decrease from 47
action_like_skips should remain 0
selected_with_evidence should remain equal to selected_for_editor for editor tasks
```

## Risks and mitigations

### Risk: over-attaching noisy evidence

Mitigation:

- record match kind and confidence
- planner prompt treats hints as weaker than explicit matches
- editor still reads current skill and can skip

### Risk: mutating the wrong umbrella skill

Mitigation:

- target hints attach evidence only to existing mutable Curator candidates
- no new skill creation in this slice
- no plugin-bundled/external/core mutation targets

### Risk: context growth

Mitigation:

- hints are compact metadata
- representative examples are capped and redacted
- full raw outputs remain in artifact only if already present; planner digest stays bounded

### Risk: hardcoded user environment

Mitigation:

- generic path-stem and candidate-name matching first
- only a small explainable alias table for known bundled skill naming patterns
- no `hermes-custom:` prefix assumption

## Implementation order

Recommended commit split:

```text
feat: add target hints for evidence attachment
fix: surface target hint quality metrics
```

If this becomes larger than expected, implement only Task 1 + Task 2 first, then run dry-run and inspect proof counts before adding cluster evidence.


## Implementation result

**Status:** completed for Task 1 + Task 2 + quality metrics. Cluster evidence remains a future refinement.

Implemented:

- Added `hermes_self_improvement/target_hints.py` with deterministic explicit, alias, tool-class, and path hints.
- Integrated target hints into `build_skill_planner_digest()`, preserving exact/bare explicit matching as the strongest path.
- Added per-candidate `evidence_resolution` metadata with match kind, target hint source/confidence/reason, and raw/normalized skill fields.
- Extended `planner_quality` with `hint_attached_evidence_count`, `hint_attached_candidate_count`, `attachments_by_match_kind`, and `cluster_evidence_count`.
- Updated CLI dry-run summary and compact tool result to expose target hint proof counts.
- Added regression tests for explicit fallback, plugin-bundled alias handling, tool-class hints, path hints, planner digest attachment, and quality metrics.

Latest verification snapshot after implementation:

```text
pytest: 289 passed, 2 skipped
dry-run proof: attached candidates 4, unmatched evidence 0, selected with evidence 3, action-like skips 0
target hints: hint-attached evidence 62, hint-attached candidates 4, cluster evidence 0
attachments_by_match_kind: bare_name 3, hint_alias 5, hint_path 8, hint_tool_class 49
```

Note: `hint_tool_class` is intentionally limited to one best matching mutable candidate per evidence item, and path hints suppress generic tool-class hints. The next refinement, if needed, is not more attachment but better precision/weighting in planner prompt and cluster evidence.
