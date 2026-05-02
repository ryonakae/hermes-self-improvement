# Planner Hint Weighting and Cluster Evidence Plan

**Status:** completed

## Goal

Improve the next self-improvement planner slice in two focused ways:

1. Make target hints less noisy by teaching the planner and deterministic fallback to treat hint sources with different strengths.
2. Add compact cluster-level evidence so the planner sees recurring patterns, not only many raw tool events.

This builds on the completed target-hints slice, where dry-run improved from:

```text
attached_candidate_count: 1 -> 4
unmatched_evidence_count: 47 -> 0
```

The remaining issue is precision: `hint_tool_class` currently dominates the attachment counts.

```text
attachments_by_match_kind:
  bare_name: 3
  hint_alias: 5
  hint_path: 8
  hint_tool_class: 49
cluster_evidence_count: 0
```

## Non-goals

- Do not broaden mutation scope beyond skill / memory / scorer / evaluator.
- Do not make tool-class hints mutation permission.
- Do not pass full raw tool outputs, full transcripts, or full skill content to the planner.
- Do not introduce hook-time LLM calls or heavy analysis.
- Do not reintroduce old approval/apply CLI surfaces.
- Do not edit Hermes core or plugin runtime config as mutation targets.

## Current context

Current flow:

```text
runtime hooks
-> analysis/evidence pack
-> build_skill_planner_digest()
-> target_hints.extract_target_hints()
-> LLM planner / deterministic fallback
-> editor tasks
```

Relevant files:

- `hermes_self_improvement/target_hints.py`
  - deterministic explicit / alias / path / tool-class hints
  - currently ranks by confidence/source but all hint attachments are still mostly advisory metadata
- `hermes_self_improvement/planner.py`
  - `build_skill_planner_digest()` attaches evidence to Curator skill candidates
  - `_call_planner_llm()` embeds the digest and short planner instructions
  - `_fallback_plan_from_digest()` currently runs editor for every attached candidate
  - `build_planner_quality_report()` reports attachment counts and match kinds
- `hermes_self_improvement/analysis.py`
  - `analyze_events()` already builds `tool_error_cluster` findings
  - `propose_from_findings()` maps findings to proposal classes
  - cluster findings are not yet added as planner digest evidence

## Design principles

### Hint strength is not binary

Treat matches in this order:

```text
exact explicit > bare explicit > alias/path > proposal_cluster > tool_class
```

Suggested strengths:

```text
exact / bare_name: strong
hint_alias: medium
hint_path: medium
hint_proposal_cluster: medium
hint_tool_class: weak
```

`hint_tool_class` should usually be evidence context, not enough by itself to trigger `run_editor` unless it is reinforced by cluster evidence or the planner gives a very specific small procedural edit.

### Cluster evidence should compress repeated raw events

Instead of showing the planner 49 generic tool-class attachments as equal weight, add compact synthetic evidence like:

```json
{
  "id": "cluster-patch-schema_or_validation",
  "kind": "tool_error_cluster_evidence",
  "source": "analysis_cluster",
  "tool_name": "patch",
  "error_kind": "schema_or_validation",
  "count": 12,
  "severity": "medium",
  "target_hints": [...],
  "examples": [... capped and redacted ...]
}
```

This lets the planner reason over “recurring patch validation failures” rather than many individual patch failures.

## Proposed implementation tasks

### Task 1: Add hint strength metadata

Add a small normalization layer, likely in `target_hints.py` or `planner.py`, that maps `evidence_match` / `target_hint_source` to:

```python
hint_strength = "strong" | "medium" | "weak"
hint_weight = 3 | 2 | 1
hint_selection_guidance = "..."
```

Rules:

- `exact`, `bare_name` => strong
- `hint_alias`, `hint_path`, `hint_proposal_cluster` => medium
- `hint_tool_class` => weak
- unknown hint types => weak

Add this metadata into each `evidence_resolution` item and candidate row summary.

Candidate row should expose compact aggregate counts:

```json
{
  "evidence_strength_counts": {"strong": 1, "medium": 2, "weak": 5},
  "strong_evidence_count": 1,
  "medium_evidence_count": 2,
  "weak_evidence_count": 5
}
```

### Task 2: Tighten planner prompt around hint strength

Update `_call_planner_llm()` prompt so the planner explicitly understands:

- exact/bare evidence is strongest
- alias/path/cluster evidence is advisory but usually useful
- tool-class evidence is weak by default
- do not select `run_editor` on weak-only evidence unless the edit is small, procedural, and directly supported by representative evidence
- prefer `skip` over noisy umbrella-skill edits
- prefer `human_review` only when ambiguous/destructive/sensitive, not as a generic escape hatch

The prompt should stay compact. Do not add long rubric prose.

### Task 3: Make deterministic fallback conservative

Update `_fallback_plan_from_digest()` so it does not blindly `run_editor` for every attached candidate.

Suggested fallback rule:

```text
run_editor if candidate has at least one strong or medium evidence item
run_editor if candidate has cluster evidence with count >= 2 and at least medium severity
skip if candidate only has weak tool-class evidence
```

This matters because fallback can run when the LLM planner fails.

### Task 4: Add cluster evidence builder

Add a pure function, likely in `analysis.py` or a new `cluster_evidence.py`:

```python
build_cluster_evidence(findings: list[dict[str, Any]], *, candidate_names: list[str]) -> list[dict[str, Any]]
```

Input: existing `tool_error_cluster` findings from `analyze_events()`.

Output: compact evidence items with:

```text
id
kind = tool_error_cluster_evidence
source = analysis_cluster
tool_name
error_kind
count
total
rate
severity
proposal_target / proposal_action if available
examples capped to 2-3 compact events
target_hints
```

Rules:

- only include clusters with `count >= 2` or severity `medium|high`
- cap cluster evidence count, e.g. top 10
- redact previews using existing redaction helpers
- do not include raw huge outputs
- use existing `extract_target_hints()` and/or a cluster-specific mapping to attach to existing mutable candidates only

### Task 5: Feed cluster evidence into planner digest

Modify evidence-pack / runner step at the point where `build_skill_planner_digest()` receives the pack.

Two acceptable implementation options:

1. Add `cluster_evidence` into `evidence_pack["evidence"]` and include their ids in `views["skill"]`.
2. Keep raw pack unchanged and let `build_skill_planner_digest()` synthesize cluster evidence from `evidence_pack["findings"]` / `proposals` if those are available.

Preferred: option 1 if there is a clear evidence-pack builder; option 2 if it avoids larger runner refactors.

The digest should mark cluster attachments as:

```text
evidence_match: hint_proposal_cluster
target_hint_source: proposal_cluster
target_hint_confidence: medium
target_hint_reason: recurring <tool> <error_kind> cluster
hint_strength: medium
```

### Task 6: Extend quality metrics

Extend `planner_quality` with:

```text
evidence_strength_counts
selected_by_strength
weak_only_candidate_count
weak_only_selected_count
cluster_evidence_count
cluster_attached_candidate_count
cluster_selected_count
```

Keep existing metrics:

```text
hint_attached_evidence_count
hint_attached_candidate_count
attachments_by_match_kind
unmatched_by_reason
editor_prompt_chars
```

Dry-run summary should stay compact, for example:

```text
- target hints: hint-attached evidence 62, candidates 4, cluster evidence 3
- evidence strength: strong 3 / medium 16 / weak 33; weak-only selected 0
```

Compact tool result should include the same counts but not full cluster examples.

### Task 7: Add tests

Add or update tests in:

- `tests/test_target_hints.py`
- `tests/test_skill_planner.py`
- `tests/test_analysis.py` or new `tests/test_cluster_evidence.py`
- `tests/test_plugin_tools.py` if compact tool result shape changes

Specific tests:

1. `hint_tool_class` resolution is `weak`.
2. `exact` / `bare_name` resolution is `strong`.
3. `hint_path` / `hint_alias` are `medium`.
4. fallback skips weak-only candidates.
5. fallback runs editor when medium/strong evidence exists.
6. cluster evidence is generated from repeated `tool_error_cluster` findings.
7. cluster evidence is capped and redacted.
8. cluster evidence attaches only to existing mutable candidates.
9. planner quality reports `weak_only_selected_count`.
10. CLI/tool compact summaries expose strength/cluster counts without bloating output.

## Files likely to change

- `hermes_self_improvement/target_hints.py`
  - add strength mapping or expose helper
- `hermes_self_improvement/planner.py`
  - add strength metadata into digest
  - tighten planner prompt
  - make fallback conservative
  - add quality metrics
- `hermes_self_improvement/analysis.py` or new `hermes_self_improvement/cluster_evidence.py`
  - build synthetic cluster evidence
- runner/evidence-pack assembly file
  - exact path to confirm during implementation; likely where `run_skill_improvement_step()` assembles `evidence_pack`
- `hermes_self_improvement/cli.py`
  - dry-run summary lines
- `hermes_self_improvement/tool_handlers.py`
  - compact tool result quality counts
- `README.md`
- `skills/operations/SKILL.md`
- `skills/operations/references/architecture.md`
- tests listed above

## Validation

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
bin/hermes-self-improve status
bin/hermes-self-improve improve --dry-run
bin/hermes-self-improve improve --dry-run --json
```

Plugin registration smoke:

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

Compact tool result smoke:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY - <<'PY'
from hermes_self_improvement.tool_handlers import handle_self_improvement_improve
payload = handle_self_improvement_improve({"dry_run": True})
print(len(str(payload)))
print(payload.get("artifact_path"))
PY
```

Also run:

```bash
git diff --check
```

## Expected dry-run outcome

The desired result is not necessarily fewer total attachments. It is better separation of evidence strength.

Expected direction:

```text
cluster_evidence_count: 0 -> >0 when clusters exist
weak_only_selected_count: 0
hint_tool_class remains visible but planner treats it as weak
selected_with_evidence == selected_for_editor
compact tool result remains small, ideally < 3KB
```

Compare against current baseline:

```text
attached_candidate_count: 4
unmatched_evidence_count: 0
selected_with_evidence: 3-4 depending run
hint_attached_evidence_count: 62
hint_attached_candidate_count: 4
cluster_evidence_count: 0
attachments_by_match_kind:
  bare_name: 3
  hint_alias: 5
  hint_path: 8
  hint_tool_class: 49
```

A good post-change summary would look like:

```text
attached_candidate_count: 4-6
unmatched_evidence_count: low, not necessarily 0
cluster_evidence_count: >0
weak_only_selected_count: 0
selected_with_evidence == selected_for_editor
```

## Risks and mitigations

### Risk: planner becomes too conservative

Mitigation:

- allow weak-only `run_editor` only when planner rationale is specific and low-risk
- keep exact/bare/path/alias as usable evidence
- inspect dry-run selected list, not just counts

### Risk: cluster evidence duplicates raw event evidence and overweights the same issue

Mitigation:

- mark cluster evidence separately with `source = analysis_cluster`
- count `cluster_selected_count`
- cap cluster evidence and examples
- planner prompt should treat cluster evidence as pattern context, not proof of a specific file edit

### Risk: context growth

Mitigation:

- cluster examples capped to 2-3
- redacted previews only
- aggregate counts in compact tool result
- full details remain in artifact / CLI `--json`

### Risk: wrong umbrella skill gets selected

Mitigation:

- cluster hints attach only to existing mutable Curator candidates
- weak-only selected count must stay 0 unless explicitly justified
- editor still has hard stops and must inspect current skill with `skill_view`

## Suggested commit split

```text
feat: weight planner target hints
feat: add cluster evidence to skill planner
fix: surface planner hint strength metrics
```

If implementation gets large, do Task 1-3 first, run dry-run, then add cluster evidence in a second commit.

## Implementation result

Implemented:

- Added per-resolution evidence strength metadata: `strong` for exact/bare matches, `medium` for alias/path/proposal-cluster hints, and `weak` for generic tool-class hints.
- Added candidate-level strength counts to planner digest rows.
- Tightened planner instructions so weak tool-class evidence is advisory and should not drive broad umbrella-skill edits by itself.
- Made deterministic fallback conservative: weak-only candidates are skipped with `weak_only_evidence`; strong/medium attached evidence can still produce editor tasks.
- Added compact `tool_error_cluster_evidence` generation from repeated tool failures, capped and redacted, with proposal-cluster target hints attached only to existing mutable candidates.
- Extended planner quality metrics with `evidence_strength_counts`, `selected_by_strength`, `weak_only_candidate_count`, `weak_only_selected_count`, `cluster_attached_candidate_count`, and `cluster_selected_count`.
- Updated CLI dry-run summary and compact tool result to surface evidence strength and weak-only / cluster metrics without returning full payloads.

Verification snapshot will be recorded in the implementation summary after the full test/dry-run pass.

