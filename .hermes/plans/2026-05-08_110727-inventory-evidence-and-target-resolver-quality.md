# Knowledge Inventory Coverage and Target Resolver Quality Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task. Keep the work inside the existing `improve` loop; do not add a new CLI command, approval queue, apply mode, or separate inventory lane.

**Goal:** Move `improve` from “tool failure guardrail generator” toward a knowledge-base health engine: detect duplicate/stale/under-covered skill and memory knowledge, surface durable workflow coverage gaps, and resolve each observation into existing skill / new skill / memory / defer / skip without forcing generic evidence into the only visible skill.

**Architecture:** Candidate generation stays evidence-preserving and decision-neutral. Program code may collect compact health signals, coverage gaps, target fit signals, negative fit signals, and create-skill affordances; LLM planner/resolver decides semantic outcomes. Candidate collection must filter immutable/non-local skill targets before anything reaches the LLM. Mutations continue only through official skill/memory tools.

**Tech Stack:** Python, pytest, Hermes plugin runtime, `bin/hermes-self-improve improve --dry-run`, runtime artifacts under `${HERMES_HOME:-~/.hermes}/self-improvement/`, official Hermes `skill_manage`, `memory`, and active provider memory tools.

---

## Current context

Latest implemented baseline:

- Latest commit at planning time: `dafebf3 fix: reconcile memory gap candidates`.
- `improve --dry-run` now shows `Action summary: Would apply / Deferred / Skipped / Blocked` in normal CLI output.
- Conversation memory gap add candidates are reconciled against existing built-in memory; duplicate/ambiguous extension adds are no longer emitted as memory evidence.
- Existing skill candidate filtering removes built-in / hub / plugin-bundled / external-dir / pinned / non-mutable / ambiguous-provenance skills before planner-facing candidate lists.
- Existing target resolver receives `unmatched_improvement_candidate`, `tool_error_cluster_evidence`, and `conversation_memory_gap_candidate`, plus filtered mutable skill targets.
- Current dry-run still tends to select `herm-tui-development` because the strongest attached evidence is exact/bare-name and most other evidence is weak/unmatched. Inventory evidence is currently `0`, so the system is still closer to “tool failure guardrail generator” than “knowledge base organizer”.

Important constraints:

- Do not touch Hermes core.
- Do not add a new lane, queue, mode, command, or human approval workflow.
- Do not expose excluded skill targets to the LLM; keep only aggregate filtered counts/reasons in artifacts.
- Skill patch/archive targets are Hermes-created local mutable active/stale skills only.
- New skill creation is allowed only through `skill_manage(action="create")`, only for durable recurring procedural workflows with no suitable existing Hermes-created skill.
- Memory changes remain official memory tool / active provider tool only.
- Program code should not decide fuzzy semantic outcomes; it should supply better evidence and hard invariants.

---

## Design upgrade from the previous draft

The previous plan treated “inventory” mostly as duplicate/stale cleanup. That is useful but too narrow. This plan upgrades it to **knowledge inventory and coverage evidence**.

The system should reason about four classes of knowledge health:

1. **Duplication / overlap**
   - memory duplicates / near-duplicates;
   - similar Hermes-created skills;
   - stale skill singletons;
   - obsolete bridge/canonical fragments.
2. **Coverage gaps**
   - repeated workflow with no skill;
   - repeated user preference with no memory;
   - repeated operational pitfall not captured in skill or memory;
   - recurring correction not persisted.
3. **Freshness / contradiction**
   - stale paths;
   - obsolete commands;
   - renamed terms, e.g. old schema/key terminology;
   - facts contradicted by newer memory, plan, or runtime artifact.
4. **Usage health**
   - frequently used skill that still attracts failures;
   - stale skill whose domain still appears in observations;
   - skill patched repeatedly and becoming too broad;
   - umbrella/concrete skill boundary pressure.

Target resolution should also become more explicit. Instead of only answering “which skill?”, resolver output should classify each candidate into:

```text
attach_existing_skill
create_new_skill
memory_candidate
defer_unresolved
skip_noise
```

The existing `target_kind` / `decision_hint` fields can remain for compatibility, but `resolution_kind` should be the primary semantic shape in artifacts and summaries.

---

## Desired dry-run outcome

After implementation, a dry-run should show compact proof like:

```text
Knowledge inventory:
- skill visible 1 / raw 4, filtered: external 2, pinned 1
- memory entries 18, duplicate groups 2, stale pairs 1
Coverage gaps:
- recurring workflows without skill: 2
- repeated preferences without memory: 1
- stale facts / renamed terms: 3
Target resolution:
- attached existing skill: 1
- create-skill candidates: 2
- memory candidates: 1
- deferred unresolved: 3
- skipped noise: 8
Action summary:
- Would apply: 0, Deferred: 3, Skipped: 8, Blocked: 1
```

Acceptable behavior:

- exact/bare-name evidence can still attach strongly;
- generic tool failures should not be forced into the only visible skill;
- repeated procedural gaps should become `create_new_skill` candidates or defer with a clear reason;
- preference/environment facts should become `memory_candidate`, not skill patches;
- one-off/transient noise should become `skip_noise`;
- excluded skills remain absent from LLM-facing candidate rows.

---

## Task 1: Add knowledge inventory health snapshot to evidence pack

**Objective:** Give `improve` a compact baseline of skill/memory inventory health even when no actionable inventory evidence is emitted.

**Files:**

- Modify: `hermes_self_improvement/evidence.py`
- Test: `tests/test_evidence_inventory_candidates.py`

**Step 1: Write failing tests**

Add tests:

```python
def test_build_evidence_pack_includes_inventory_health_snapshot_for_skills_and_memory():
    pack = build_evidence_pack(
        [], since, until,
        curator_telemetry={"available": True, "candidates": [
            {"name": "local-a", "mutable": True, "state": "active", "provenance": "agent_created"},
            {"name": "builtin", "mutable": False, "state": "active", "provenance": "builtin"},
        ], "summary": {"candidate_count": 2}},
        memory_paths={"memory": memory_path, "user": user_path},
    )

    health = pack["inventory_health"]
    assert health["skill_candidates"]["llm_visible_count"] == 1
    assert health["skill_candidates"]["filtered_by_reason"]["non_mutable"] == 1
    assert health["memory"]["entry_count"] >= 1
    assert health["memory"]["near_duplicate_group_count"] == 0
```

Also assert `summary.inventory_health` has compact counts, not full memory text.

**Step 2: Verify RED**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_evidence_inventory_candidates.py::test_build_evidence_pack_includes_inventory_health_snapshot_for_skills_and_memory -q
```

Expected: FAIL because `inventory_health` does not exist.

**Step 3: Implement snapshot helper**

Add helper:

```python
def build_inventory_health_snapshot(*, raw_skill_candidates, filtered_skill_candidate_count_by_reason, skill_candidates, memory_entries, inventory_evidence) -> dict[str, Any]:
    ...
```

Keep it count-only:

- `skill_candidates.raw_count`
- `skill_candidates.llm_visible_count`
- `skill_candidates.filtered_by_reason`
- `memory.entry_count`
- `memory.near_duplicate_group_count`
- `memory.exact_duplicate_group_count`
- `memory.stale_pair_count`
- `inventory_evidence_count`

Do not include full memory text or full skill bodies.

**Step 4: Wire into `build_evidence_pack()`**

- Reuse already computed `skill_candidates`, `filtered_skill_candidate_count_by_reason`, `memory_inventory_evidence`.
- Refactor `_memory_entries()` so entry parsing can be reused by inventory health and candidate generation without rereading files unnecessarily.

**Step 5: Verify GREEN**

```bash
$PY -m pytest tests/test_evidence_inventory_candidates.py -q
```

**Step 6: Commit**

```bash
git add hermes_self_improvement/evidence.py tests/test_evidence_inventory_candidates.py
git commit -m "feat: summarize knowledge inventory health"
```

---

## Task 2: Improve memory inventory parsing and relation detection

**Objective:** Make memory inventory evidence catch real built-in memory maintenance opportunities without relying on identical lines only.

**Files:**

- Modify: `hermes_self_improvement/evidence.py`
- Test: `tests/test_evidence_inventory_candidates.py`

**Step 1: Write failing tests**

Add tests:

```python
def test_collect_memory_inventory_candidates_splits_section_separator_entries(tmp_path):
    path = tmp_path / "MEMORY.md"
    path.write_text("Hermes runtime root is ~/.hermes.\n§\nHermes root is /opt/data.\n", encoding="utf-8")

    items = collect_memory_inventory_candidates({"memory": path})

    assert items
    assert items[0]["inventory"]["group_kind"] in {"near_duplicate", "stale_fact_pair"}
```

```python
def test_collect_memory_inventory_candidates_marks_stale_current_fact_pairs(tmp_path):
    path = tmp_path / "MEMORY.md"
    path.write_text("Hermes runtime root is /opt/data.\n§\nHermes runtime root is ~/.hermes.\n", encoding="utf-8")

    item = collect_memory_inventory_candidates({"memory": path})[0]

    assert item["inventory"]["group_kind"] == "stale_fact_pair"
    assert any("replace" in hint or "stale" in hint for hint in item["inventory"]["hints"])
```

**Step 2: Verify RED**

```bash
$PY -m pytest tests/test_evidence_inventory_candidates.py::test_collect_memory_inventory_candidates_splits_section_separator_entries tests/test_evidence_inventory_candidates.py::test_collect_memory_inventory_candidates_marks_stale_current_fact_pairs -q
```

Expected: FAIL if `_memory_entries()` still only reads lines and overlap is too shallow.

**Step 3: Implement safer memory entry parsing**

Refactor `_memory_entries()`:

- Split by `§` first.
- For each chunk, drop headings and empty lines.
- Join remaining lines into one compact memory entry.
- Keep `target`, `old_text`, `summary`, `hash`.
- Redact and skip secret-like content.

**Step 4: Implement relation helper**

Add:

```python
def _memory_inventory_relation(left: str, right: str) -> str | None:
    ...
```

Rules:

- exact same text -> `semantic_duplicate`
- high token / SequenceMatcher similarity -> `near_duplicate`
- same early anchor tokens plus changed path/value-like tokens -> `stale_fact_pair`

Program code must not choose which fact is current. It can only label relation and pass both entries to the memory planner.

**Step 5: Verify GREEN**

```bash
$PY -m pytest tests/test_evidence_inventory_candidates.py tests/test_memory_inventory_planner.py -q
```

**Step 6: Commit**

```bash
git add hermes_self_improvement/evidence.py tests/test_evidence_inventory_candidates.py
git commit -m "feat: detect memory inventory maintenance signals"
```

---

## Task 3: Add knowledge coverage gap evidence

**Objective:** Emit compact evidence when repeated observations indicate missing skill/memory knowledge, not just duplicate/stale existing entries.

**Files:**

- Modify: `hermes_self_improvement/evidence.py`
- Test: `tests/test_evidence_inventory_candidates.py`
- Test: `tests/test_unmatched_evidence_candidates.py`

**Step 1: Write failing tests**

Add tests for repeated procedural workflow without a skill:

```python
def test_collect_knowledge_coverage_candidates_emits_repeated_workflow_gap():
    evidence = [
        {"id": "u1", "kind": "unmatched_improvement_candidate", "theme": "sandbox_permission_workflow", "count": 5, "rationale": "Repeated sandbox permission failures"},
    ]

    items = collect_knowledge_coverage_candidates(evidence, skill_candidates=[], existing_memory_entries=[])

    assert items[0]["kind"] == "knowledge_coverage_candidate"
    assert items[0]["coverage"]["gap_kind"] == "recurring_workflow_without_skill"
    assert items[0]["target_resolution_hint"]["resolution_kind"] == "create_new_skill"
```

Add test for repeated preference without memory:

```python
def test_collect_knowledge_coverage_candidates_emits_preference_memory_gap():
    evidence = [{"id": "m1", "kind": "conversation_memory_gap_candidate", "memory": {"action": "defer", "candidate_fact": "User prefers X"}}]

    items = collect_knowledge_coverage_candidates(evidence, skill_candidates=[], existing_memory_entries=[])

    assert items[0]["coverage"]["gap_kind"] == "repeated_preference_without_memory"
    assert items[0]["target_resolution_hint"]["resolution_kind"] == "memory_candidate"
```

**Step 2: Verify RED**

```bash
$PY -m pytest tests/test_evidence_inventory_candidates.py::test_collect_knowledge_coverage_candidates_emits_repeated_workflow_gap tests/test_evidence_inventory_candidates.py::test_collect_knowledge_coverage_candidates_emits_preference_memory_gap -q
```

Expected: FAIL because helper does not exist.

**Step 3: Implement `knowledge_coverage_candidate` shape**

Add helper:

```python
def make_knowledge_coverage_candidate(...):
    return {
        "kind": "knowledge_coverage_candidate",
        "source": "knowledge_coverage",
        "coverage": {...},
        "target_resolution_hint": {...},
    }
```

Candidate fields:

- `coverage.gap_kind`
- `coverage.evidence_count`
- `coverage.representative_evidence_ids`
- `coverage.workflow_boundary` when procedural
- `coverage.not_memory_because` when procedural
- `coverage.not_existing_skill_because` when no skill target fits
- `coverage.stale_or_renamed_terms` when applicable

Do not emit secrets or full context dumps.

**Step 4: Implement collector**

```python
def collect_knowledge_coverage_candidates(evidence, *, skill_candidates, existing_memory_entries, limit=20):
    ...
```

Rules:

- recurring procedural theme with no candidate name/path overlap -> `recurring_workflow_without_skill`, resolution kind `create_new_skill`;
- recurring preference/memory gap not covered by existing memory -> `repeated_preference_without_memory`, resolution kind `memory_candidate`;
- stale path/renamed term patterns in evidence or memory inventory -> `stale_fact_or_renamed_term`, resolution kind `memory_candidate` or `attach_existing_skill` depending on available exact target;
- one-off/transient events should not become coverage candidates.

**Step 5: Wire into evidence pack**

After unmatched candidates and memory gap candidates are available, add coverage candidates to evidence and views:

- if resolution kind suggests skill/new skill, include in `views.skill`;
- if memory candidate, include in `views.memory`;
- update `summary.evidence_by_kind.knowledge_coverage_candidate` and `summary.coverage_candidate_count`.

**Step 6: Verify GREEN**

```bash
$PY -m pytest tests/test_evidence_inventory_candidates.py tests/test_unmatched_evidence_candidates.py -q
```

**Step 7: Commit**

```bash
git add hermes_self_improvement/evidence.py tests/test_evidence_inventory_candidates.py tests/test_unmatched_evidence_candidates.py
git commit -m "feat: surface knowledge coverage gaps"
```

---

## Task 4: Add skill usage-health inventory candidates

**Objective:** Use Curator telemetry to identify stale or under-covered Hermes-created skills without exposing non-mutable targets.

**Files:**

- Modify: `hermes_self_improvement/evidence.py`
- Test: `tests/test_evidence_inventory_candidates.py`

**Step 1: Write failing tests**

Add stale singleton test:

```python
def test_collect_skill_inventory_candidates_emits_stale_singleton_candidate():
    curator = {"candidates": [{
        "name": "old-local-workflow",
        "mutable": True,
        "state": "stale",
        "provenance": "agent_created",
        "description": "Old local workflow notes",
        "usage": {"last_used_days": 180, "view_count": 0},
    }]}

    items = collect_skill_inventory_candidates(curator)

    assert items
    assert items[0]["inventory"]["group_kind"] == "stale_singleton_skill"
```

Add external stale singleton guard:

```python
def test_collect_skill_inventory_candidates_does_not_emit_external_stale_singleton():
    curator = {"candidates": [{
        "name": "external-skill",
        "mutable": True,
        "state": "stale",
        "provenance": "external",
    }]}

    assert collect_skill_inventory_candidates(curator) == []
```

**Step 2: Verify RED**

```bash
$PY -m pytest tests/test_evidence_inventory_candidates.py::test_collect_skill_inventory_candidates_emits_stale_singleton_candidate tests/test_evidence_inventory_candidates.py::test_collect_skill_inventory_candidates_does_not_emit_external_stale_singleton -q
```

Expected: FAIL because current collector only emits groups of size >= 2.

**Step 3: Implement stale singleton / usage-health candidates**

Extend `collect_skill_inventory_candidates()`:

- keep filtering through `filter_llm_skill_candidates()` first;
- keep existing similar/stale group behavior;
- add singleton evidence only when local mutable Hermes-created skill is stale or has low/old usage signals;
- group kinds:
  - `stale_singleton_skill`
  - `used_but_failure_prone_skill` when attached failures repeatedly hit the same skill in later tasks;
  - `overgrown_skill_boundary_pressure` only if patch/use counts suggest it, without deciding archive/merge.

Hints must say planner may choose `archive_skill`, `run_editor`, or `skip`; program code must not decide.

**Step 4: Verify GREEN**

```bash
$PY -m pytest tests/test_evidence_inventory_candidates.py -q
```

**Step 5: Commit**

```bash
git add hermes_self_improvement/evidence.py tests/test_evidence_inventory_candidates.py
git commit -m "feat: surface skill usage health candidates"
```

---

## Task 5: Add create-skill boundary affordances

**Objective:** Give resolver/planner enough structure to choose `create_new_skill` safely when a recurring procedural workflow has no appropriate existing Hermes-created skill.

**Files:**

- Modify: `hermes_self_improvement/evidence.py`
- Modify: `hermes_self_improvement/target_resolver.py`
- Test: `tests/test_unmatched_evidence_candidates.py`
- Test: `tests/test_target_resolver.py`

**Step 1: Write failing tests**

Add evidence test:

```python
def test_unmatched_workflow_candidate_includes_create_skill_boundary_affordance():
    candidate = make_knowledge_coverage_candidate(... recurring workflow ...)

    affordance = candidate["target_resolution_hint"]["create_skill_affordance"]
    assert affordance["workflow_boundary"]
    assert affordance["not_memory_because"]
    assert affordance["not_existing_skill_because"]
    assert affordance["candidate_skill_name_seed"]
```

Add digest pass-through test:

```python
def test_target_resolution_digest_passes_create_skill_boundary_affordance():
    digest = build_target_resolution_digest(pack, skill_candidates=[])

    row = digest["candidates"][0]
    assert row["target_resolution_hint"]["resolution_kind"] == "create_new_skill"
    assert row["target_resolution_hint"]["create_skill_affordance"]["workflow_boundary"]
```

**Step 2: Verify RED**

```bash
$PY -m pytest tests/test_unmatched_evidence_candidates.py::test_unmatched_workflow_candidate_includes_create_skill_boundary_affordance tests/test_target_resolver.py::test_target_resolution_digest_passes_create_skill_boundary_affordance -q
```

Expected: FAIL.

**Step 3: Implement affordance fields**

Add compact metadata:

```json
{
  "target_resolution_hint": {
    "resolution_kind": "create_new_skill",
    "create_skill_affordance": {
      "workflow_boundary": "...",
      "not_memory_because": "procedural recurring steps",
      "not_existing_skill_because": "no Hermes-created local mutable skill matches boundary",
      "evidence_count": 5,
      "representative_evidence_ids": ["..."],
      "candidate_skill_name_seed": "...",
      "disallowed_if": ["one_off", "belongs_in_memory", "duplicates_existing_skill", "would_patch_builtin_or_hub_skill"]
    }
  }
}
```

Do not create the skill here. This is only planner input.

**Step 4: Pass through resolver digest**

In `build_target_resolution_digest()`, include `target_resolution_hint` for unresolved and coverage candidates.

**Step 5: Verify GREEN**

```bash
$PY -m pytest tests/test_unmatched_evidence_candidates.py tests/test_target_resolver.py -q
```

**Step 6: Commit**

```bash
git add hermes_self_improvement/evidence.py hermes_self_improvement/target_resolver.py tests/test_unmatched_evidence_candidates.py tests/test_target_resolver.py
git commit -m "feat: expose create-skill boundary affordances"
```

---

## Task 6: Upgrade resolver schema to resolution-kind classification

**Objective:** Make target resolver classify each candidate as existing skill / new skill / memory / unresolved / noise, while preserving compatibility with existing `decision_hint` and planner paths.

**Files:**

- Modify: `hermes_self_improvement/target_resolver.py`
- Modify: `hermes_self_improvement/planner.py` if planner digest needs to consume `resolution_kind`
- Test: `tests/test_target_resolver.py`
- Test: `tests/test_skill_planner.py`

**Step 1: Write failing tests**

Add normalization test:

```python
def test_normalize_target_resolver_payload_accepts_resolution_kind_create_new_skill():
    out = normalize_target_resolver_payload(
        {"resolutions": [{
            "candidate_id": "u1",
            "resolution_kind": "create_new_skill",
            "target_kind": "skill",
            "target": "",
            "confidence": "high",
            "suggested_action": "apply",
            "reason": "Recurring workflow with no existing skill target",
            "create_skill_affordance": {"workflow_boundary": "Browser profile troubleshooting"},
        }]},
        known_skill_targets={},
    )

    assert out["resolutions"][0]["resolution_kind"] == "create_new_skill"
    assert out["resolutions"][0]["decision_hint"] == "apply"
```

Add low-confidence attach guard:

```python
def test_normalize_target_resolver_payload_defers_low_confidence_attach_existing_skill():
    out = normalize_target_resolver_payload(
        {"resolutions": [{
            "candidate_id": "u1",
            "resolution_kind": "attach_existing_skill",
            "target_kind": "skill",
            "target": "herm-tui-development",
            "confidence": "low",
            "suggested_action": "apply",
            "reason": "only visible target",
        }]},
        known_skill_targets={"herm-tui-development": {"name": "herm-tui-development", "mutable": True, "state": "active", "provenance": "agent_created"}},
    )

    assert out["resolutions"][0]["resolution_kind"] == "defer_unresolved"
    assert out["resolutions"][0]["decision_hint"] == "defer"
```

**Step 2: Verify RED**

```bash
$PY -m pytest tests/test_target_resolver.py::test_normalize_target_resolver_payload_accepts_resolution_kind_create_new_skill tests/test_target_resolver.py::test_normalize_target_resolver_payload_defers_low_confidence_attach_existing_skill -q
```

Expected: FAIL.

**Step 3: Implement resolution kind normalization**

Allowed values:

```python
ALLOWED_RESOLUTION_KINDS = {
    "attach_existing_skill",
    "create_new_skill",
    "memory_candidate",
    "defer_unresolved",
    "skip_noise",
}
```

Compatibility mapping:

- `attach_existing_skill` + valid target -> existing attach behavior.
- `create_new_skill` -> no existing target required; keep create-skill affordance.
- `memory_candidate` -> `target_kind=memory`, `decision_hint=apply|defer` based on confidence.
- `defer_unresolved` -> `decision_hint=defer`.
- `skip_noise` -> `decision_hint=skip`.

Hard blocks still win:

- unknown existing skill target;
- pinned / non-mutable / unsupported provenance;
- unsupported lifecycle;
- secrets if any candidate payload ever includes text that looks sensitive.

**Step 4: Update resolver LLM prompt**

Prompt should require JSON like:

```json
{"resolutions":[{"candidate_id":"...","resolution_kind":"attach_existing_skill|create_new_skill|memory_candidate|defer_unresolved|skip_noise", ...}]}
```

Add wording:

- “Do not assign evidence to the only visible skill merely because it is the only visible skill.”
- “Prefer `create_new_skill` when the observation is recurring procedural workflow and no listed skill fits.”
- “Prefer `memory_candidate` when the observation is stable preference/environment fact, not procedure.”
- “Prefer `defer_unresolved` when evidence is useful but target boundary is unclear.”
- “Prefer `skip_noise` for one-off/transient failures.”

**Step 5: Planner integration**

In `build_skill_planner_digest()`:

- attach evidence only for `resolution_kind == "attach_existing_skill"` and non-deferred/high-enough confidence;
- expose `create_new_skill` resolutions to planner digest as create-skill candidate context, not attached evidence to some existing skill;
- keep `memory_candidate` out of skill candidate attachment, but preserve in diagnostics / memory view if already routed elsewhere;
- keep deferred/noise evidence in unmatched diagnostics, not hidden.

**Step 6: Verify GREEN**

```bash
$PY -m pytest tests/test_target_resolver.py tests/test_skill_planner.py -q
```

**Step 7: Commit**

```bash
git add hermes_self_improvement/target_resolver.py hermes_self_improvement/planner.py tests/test_target_resolver.py tests/test_skill_planner.py
git commit -m "feat: classify target resolution outcomes"
```

---

## Task 7: Add target fit and negative-fit signals

**Objective:** Reduce over-attachment to visible skills by giving resolver compact positive and negative fit context.

**Files:**

- Modify: `hermes_self_improvement/target_resolver.py`
- Test: `tests/test_target_resolver.py`

**Step 1: Write failing tests**

Add test:

```python
def test_target_resolution_digest_includes_target_fit_and_negative_signals():
    digest = build_target_resolution_digest(pack, skill_candidates=[{
        "name": "herm-tui-development",
        "description": "Develop herm-tui locally",
        "state": "active",
        "mutable": True,
        "provenance": "agent_created",
        "usage": {"last_used_days": 1},
    }])

    target = digest["skill_targets"][0]
    assert "target_fit_signals" in target
    assert "negative_fit_signals" in target["target_fit_signals"]
```

**Step 2: Verify RED**

```bash
$PY -m pytest tests/test_target_resolver.py::test_target_resolution_digest_includes_target_fit_and_negative_signals -q
```

Expected: FAIL.

**Step 3: Implement fit signal fields**

For each candidate evidence row and visible skill target, program code can compute hints without deciding:

```json
{
  "target_fit_signals": {
    "name_overlap": 0.2,
    "description_overlap": 0.1,
    "path_overlap": 0.0,
    "command_overlap": 0.0,
    "loaded_skill_match": false,
    "single_visible_target": true,
    "positive_signals": ["bare_name_match"],
    "negative_fit_signals": ["generic_tool_failure", "single_visible_target_do_not_force_match"]
  }
}
```

Keep this compact. No full context dumps.

**Step 4: Add digest-level warning**

If only one skill target is visible, add:

```json
"resolver_warnings": ["single_visible_target_is_not_positive_evidence"]
```

**Step 5: Verify GREEN**

```bash
$PY -m pytest tests/test_target_resolver.py -q
```

**Step 6: Commit**

```bash
git add hermes_self_improvement/target_resolver.py tests/test_target_resolver.py
git commit -m "feat: add target fit signals to resolver digest"
```

---

## Task 8: Add dry-run proof summary for knowledge coverage and resolver quality

**Objective:** Make normal dry-run output and plugin compact tool result show inventory/coverage/resolution quality without artifact spelunking.

**Files:**

- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/tool_handlers.py`
- Test: `tests/test_cli_surface.py`
- Test: `tests/test_plugin_tools.py`

**Step 1: Write failing tests**

Add CLI summary test:

```python
def test_improve_summary_mentions_knowledge_inventory_coverage_and_resolution_kinds():
    text = _render_improve_summary(result_with_knowledge_inventory_and_resolution_summary)

    assert "Knowledge inventory:" in text
    assert "Coverage gaps:" in text
    assert "Target resolution:" in text
    assert "create-skill candidates" in text
    assert "deferred unresolved" in text
```

Add tool compact test:

```python
def test_compact_improve_tool_result_includes_knowledge_inventory_and_resolution_counts():
    payload = _compact_improve_tool_result(result)

    assert payload["knowledge_inventory"]["skill_candidates"]["llm_visible_count"] == 1
    assert payload["coverage_gaps"]["recurring_workflows_without_skill"] == 2
    assert payload["target_resolution"]["create_new_skill"] == 1
```

**Step 2: Verify RED**

```bash
$PY -m pytest tests/test_cli_surface.py::test_improve_summary_mentions_knowledge_inventory_coverage_and_resolution_kinds tests/test_plugin_tools.py::test_compact_improve_tool_result_includes_knowledge_inventory_and_resolution_counts -q
```

Expected: FAIL.

**Step 3: Implement compact display**

Add sections only when data exists:

```text
Knowledge inventory:
- skill visible 1 / raw 4, filtered: external 2, pinned 1
- memory entries 18, duplicate groups 2, stale pairs 1
Coverage gaps:
- recurring workflows without skill: 2
- repeated preferences without memory: 1
- stale facts / renamed terms: 3
Target resolution:
- attached existing skill: 1
- create-skill candidates: 2
- memory candidates: 1
- deferred unresolved: 3
- skipped noise: 8
```

Do not print full candidate text.

**Step 4: Verify GREEN**

```bash
$PY -m pytest tests/test_cli_surface.py tests/test_plugin_tools.py -q
```

**Step 5: Commit**

```bash
git add hermes_self_improvement/cli.py hermes_self_improvement/tool_handlers.py tests/test_cli_surface.py tests/test_plugin_tools.py
git commit -m "feat: summarize knowledge coverage and resolver quality"
```

---

## Task 9: Dogfood dry-run and tune only with evidence

**Objective:** Run actual dry-run and verify that knowledge inventory and resolver classification are useful, without hiding weak evidence or overfitting to the current `herm-tui-development` case.

**Files:**

- Modify only if needed after observing dry-run:
  - `hermes_self_improvement/evidence.py`
  - `hermes_self_improvement/target_resolver.py`
  - `hermes_self_improvement/planner.py`
  - `hermes_self_improvement/cli.py`
  - `hermes_self_improvement/tool_handlers.py`
  - `tests/*`
  - `README.md`
  - `skills/operations/SKILL.md`
  - `.hermes/plans/README.md`

**Step 1: Run full validation**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
bin/hermes-self-improve status
git diff --check
```

Expected:

```text
all tests pass
status OK
git diff --check has no output
```

**Step 2: Run dry-run**

```bash
bin/hermes-self-improve improve --dry-run --scorer llm | tee /tmp/hermes-self-improve-knowledge-inventory-resolver-dryrun.txt
```

Inspect:

- `Knowledge inventory` section;
- `Coverage gaps` section;
- `Target resolution` section;
- `Action summary` section;
- `Selected for editor` section;
- run artifact JSON.

**Step 3: Evaluate expected behavior**

Accept if:

- coverage gap counts appear when recurring procedural/preference/stale-term signals exist;
- resolver classification includes create-skill / memory / defer / skip buckets;
- generic unmatched observations are not attached to `herm-tui-development` solely because it is visible;
- exact/bare-name `herm-tui-development` evidence can still attach;
- memory add does not become noisy again;
- excluded skills remain absent from LLM-facing candidate rows.

Reject/tune if:

- `herm-tui-development` still absorbs generic evidence without exact/bare-name/path/scope support;
- coverage gap detection emits one-off transient errors;
- memory inventory emits too many broad near-duplicates;
- resolver blocks useful create-skill candidates due to lack of existing skill target;
- dry-run summary exposes full memory content or becomes noisy.

**Step 4: Update docs minimally**

If behavior changed, update:

- `README.md`: concise operational description.
- `skills/operations/SKILL.md`: safety boundary / verification notes.
- `.hermes/plans/README.md`: mark this plan status and link it as implemented/active follow-up.

**Step 5: Final commit and push**

```bash
git status --short
git add <changed files>
git commit -m "feat: improve knowledge inventory and target resolution"
git push
```

---

## Risks and mitigations

### Risk: Program code becomes a hidden semantic planner

Mitigation:

- Program code may label relation types, coverage gap kinds, and fit signals, but must not choose patch/archive/create outcomes.
- Keep fuzzy outcomes in resolver/planner LLM decisions.
- Hard stops only for safety/provenance/secret/unsupported target.

### Risk: Coverage evidence becomes noisy

Mitigation:

- Require recurrence or strong signal for coverage gaps.
- Emit count-only inventory health even when candidate generation is conservative.
- Use `skip_noise` and `defer_unresolved` as healthy outcomes, not failures.

### Risk: Resolver under-attaches useful evidence

Mitigation:

- Exact and bare-name matches remain strong.
- Medium hints still attach when alias/path/cluster/inventory group supports them.
- Low-confidence generic LLM resolver matches defer rather than disappear.

### Risk: Create-skill candidates duplicate existing skills

Mitigation:

- Candidate generation only provides affordance and boundary.
- Planner normalization and runner preflight still reject duplicate names and invalid skill names.
- Actual creation remains through bounded `skill_manage(action="create")` only.

### Risk: More output overwhelms dry-run

Mitigation:

- Normal CLI prints counts and buckets only.
- Full candidate details stay in artifacts.
- Tool result remains compact with artifact paths.

---

## Verification command set

Use this set before final push:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
bin/hermes-self-improve status
bin/hermes-self-improve improve --dry-run --scorer llm
git diff --check
git status --short --branch
```

Expected final state:

- full test suite passes;
- status OK;
- dry-run summary has readable knowledge inventory / coverage / target-resolution sections;
- excluded skills stay out of LLM-facing candidate rows;
- memory add does not become noisy again;
- repo is committed and pushed if the user asks to proceed with implementation.
