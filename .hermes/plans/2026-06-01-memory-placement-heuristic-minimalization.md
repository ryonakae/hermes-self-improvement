# Memory Placement Heuristic Minimalization Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task. This is a north-star refactor plan: keep each implementation slice simple, but do not stop until planner-facing semantic routing is owned by the LLM and programmatic code only provides observations plus hard safety guards.

**Goal:** Replace the current `suggested_route` / marker-driven memory placement classifier with a minimal observation-only handoff, so USER/MEMORY/Skill semantic placement is decided by the Planner LLM while destructive execution remains protected by small hard guards.

**Architecture:** Keep the existing one Planner → one Knowledge Editor canonical transaction path. Thin the evidence layer from “recommend route” to “show current store, exact text, official boundary, and bounded observations.” The prompt asks the LLM to decide semantic destination. The normalizer/executor enforce only invariants that prevent destructive or impossible changes.

**Tech Stack:** Python, pytest, Hermes self-improvement plugin, existing `knowledge_transactions`, `planner_runtime`, `prompts`, memory placement evidence, dry-run/replay artifacts.

---

## Current mismatch with the desired design

Ryo’s desired design:

- LLM owns semantic judgment: USER vs MEMORY vs Skill.
- Programmatic logic should be as thin as possible.
- Heuristics may remain only as minimal observations, not recommendations.
- Hard guards should protect destructive execution, not classify meaning.
- Simpler code is better.

Current implementation conflicts:

1. `hermes_self_improvement/evidence.py::_memory_placement_route_hint()` is a marker-based semantic classifier.
   - It returns `likely_move_user_to_memory`, `likely_move_memory_to_user`, `likely_memory_to_skill`, `likely_defer`, or `likely_keep`.
   - Marker lists (`user_markers`, `runtime_markers`, `procedural_markers`, `diary_markers`) encode semantic policy in code.
   - This produced the bad direction where a USER policy containing `plugin`/`障害`/`PR` can be treated as runtime MEMORY material.

2. `suggested_route` is planner-facing and structurally powerful.
   - `planner_runtime.py` carries it into digest rows.
   - `prompts.py` renders it in the prompt.
   - `prompts.py` sorts by it and gives `likely_memory_to_skill` a priority section.
   - Tests assert specific `likely_*` outcomes.

3. Cross-store duplicate cleanup relies on the same route heuristic.
   - `_canonical_store_for_memory_text()` calls `_memory_placement_route_hint()` and derives a canonical USER/MEMORY store.
   - That can convert marker mistakes into cleanup hints.

4. Existing direction hardening is necessary but not sufficient.
   - `2026-06-01-memory-placement-direction-validation.md` stops impossible move directions.
   - It does not remove the semantic classifier that made the route hint misleading in the first place.

This plan supersedes the heuristic-heavy placement tuning line. Do not add more markers to fix individual misclassifications.

---

## Final ideal shape

### Evidence candidate shape

Planner-facing memory placement candidates should look like this:

```json
{
  "evidence_id": "memory_place_...",
  "current_store": "user",
  "old_text": "Hermes/plugin障害: 相談語は調査設計のみ、明示OKまで変更禁止...",
  "summary": "bounded summary or same text",
  "official_boundary": "USER=...; MEMORY=...; Skill=...",
  "placement_observations": [
    "mentions_plugin_or_runtime_term",
    "contains_policy_or_preference_language"
  ],
  "allowed_decisions": ["keep", "move_user_to_memory", "memory_to_skill", "skip", "defer"]
}
```

Rules:

- No `suggested_route` in planner-facing digest/prompt.
- No `likely_*` values in planner-facing digest/prompt.
- Observation names must not contain a destination or recommendation, e.g. avoid `should_move_to_memory`.
- `allowed_decisions` is allowed because it is direction safety, not semantic classification.
- `official_boundary` must stay visible because the LLM needs the actual semantic rule.

### Prompt contract

The planner prompt should say:

```text
Placement observations are observations, not recommendations.
Do not follow them mechanically.
Decide semantic destination from old_text, current_store, official_boundary, and the full context.
If mixed or unclear, keep current store or defer.
Only emit a move when the content clearly belongs in the opposite store.
Use memory_to_skill only when the content is reusable procedural guidance and an exact editable target skill is known or can be safely deferred with target unresolved.
```

### Programmatic hard guards that remain

Keep these; they are not semantic heuristics:

- A placement move must match candidate `current_store`:
  - `current_store=user` allows only `move_user_to_memory`.
  - `current_store=memory` allows only `move_memory_to_user`.
- Destructive source removal requires a valid `source_evidence_id` / `evidence_ids` link.
- Destructive source removal requires exact `source_old_text` matching current entry text.
- Add-before-remove for USER↔MEMORY moves.
- Skill-update-before-memory-remove for `memory_to_skill`.
- Target skill must be local/editable/unprotected when mutating a skill.
- Dry-run must not mutate.
- Stale source blocks mutation.
- Unknown/malformed transaction blocks or defers with bounded diagnostics.

### Programmatic heuristics to remove or demote

Remove from planner-facing decision flow:

- `suggested_route`
- `route_reasons` as route reasons
- `likely_move_user_to_memory`
- `likely_move_memory_to_user`
- `likely_memory_to_skill`
- `likely_keep`
- `likely_defer`
- priority sorting by `suggested_route`
- the priority `likely_memory_to_skill` prompt section
- `_canonical_store_for_memory_text()` using route hints for cleanup decisions

A compatibility shim may temporarily read old artifacts containing `suggested_route`, but it must translate them into neutral observations and must not sort or recommend from them.

---

## Non-goals

- Do not add another role, queue, scorer, confidence subsystem, or approval lane.
- Do not add new marker lists to patch individual examples.
- Do not expand mutation authority.
- Do not directly edit built-in memory files; memory mutations still go through official tools.
- Do not remove existing executor safety guards.
- Do not implement broad memory inventory redesign outside placement-route minimalization.

---

## Completion criteria

- Planner-facing digest and prompt contain no `suggested_route`, `route_reasons`, or `likely_*` placement route values.
- `evidence.py` no longer returns placement route recommendations for memory placement candidates.
- Placement candidates expose neutral `placement_observations` only.
- Prompt explicitly delegates USER/MEMORY/Skill semantic judgment to the LLM and labels observations as non-authoritative.
- Prompt no longer prioritizes or sorts candidates by heuristic route.
- Cross-store duplicate cleanup no longer derives canonical USER/MEMORY store from placement route heuristics.
- Existing direction/source/stale/add-before-remove guards still pass focused tests.
- Regression tests cover the known mixed USER policy/runtime-word example.
- Full test suite passes.
- A dry-run smoke confirms placement candidates are still visible, but no planner-facing `suggested_route` remains in the digest/prompt/run diagnostics.

---

## Relationship to the existing direction-validation plan

`2026-06-01-memory-placement-direction-validation.md` remains useful as a safety slice, but this plan is the larger correction.

Implementation order should be:

1. First ensure direction/source hard guards are present and green. If the direction-validation plan is not implemented yet, implement its hard-guard pieces before or as Task 1 here.
2. Then remove semantic route recommendations from evidence/digest/prompt.
3. Then remove tests and prompt surfaces that enshrine `likely_*` routing.

If direction-validation implementation already landed by the time this plan is executed, keep its guard tests and adapt names/fixtures to the new observation-only candidate shape.

---

## Task 1: Lock the hard-guard boundary before deleting heuristics

**Objective:** Confirm the safety invariants are tested independently of route heuristics, so deleting `suggested_route` cannot loosen execution safety.

**Files:**

- Modify: `tests/test_skill_planner.py`
- Modify: `tests/test_knowledge_transactions.py` or existing transaction normalizer tests if present
- Modify only if needed: `hermes_self_improvement/planner_runtime.py`
- Modify only if needed: `hermes_self_improvement/knowledge_transactions.py`

**Step 1: Write/verify focused tests for direction safety**

Keep or add tests asserting:

```python
def test_memory_placement_user_candidate_cannot_move_memory_to_user():
    # candidate current_store=user
    # raw planner emits move_memory_to_user
    # normalization returns None, skip/block/defer, or a non-executable transaction
    # it must not return executable placement_move builtin_memory -> builtin_user
```

```python
def test_memory_placement_memory_candidate_cannot_move_user_to_memory():
    # candidate current_store=memory
    # raw planner emits move_user_to_memory
    # normalization rejects it
```

```python
def test_memory_placement_valid_direction_preserves_evidence_id_and_old_text():
    # current_store=user + move_user_to_memory
    # normalized transaction keeps evidence id and exact source_old_text
```

**Step 2: Run focused tests**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_skill_planner.py -q -k 'memory_placement and direction'
```

Expected: PASS if the direction-validation slice already landed; otherwise RED until guard code is implemented.

**Step 3: Implement only missing hard guards**

If tests fail, implement the smallest guard in normalization:

- Resolve placement candidate by evidence id.
- Determine allowed move operation from `current_store`.
- Reject mismatched operation before generic canonical transaction normalization.
- Preserve evidence id when accepted.
- Require exact `source_old_text` equality if both candidate and raw transaction include text.

Do not add semantic markers.

**Step 4: Verify**

```bash
$PY -m pytest tests/test_skill_planner.py tests/test_knowledge_transactions.py -q -k 'memory_placement or placement_move'
```

Expected: PASS.

---

## Task 2: Replace `_memory_placement_route_hint()` with neutral observations

**Objective:** Remove program-owned semantic route recommendations from evidence generation.

**Files:**

- Modify: `hermes_self_improvement/evidence.py`
- Test: `tests/test_evidence_inventory_candidates.py`

**Step 1: Write RED tests for neutral candidate shape**

Replace route-specific assertions with observation-only assertions.

Add this regression:

```python
def test_memory_placement_candidate_user_policy_with_runtime_words_has_no_suggested_route():
    memory_paths = make_memory_paths(
        user_entries=[
            "Hermes/plugin障害: 相談語は調査設計のみ、明示OKまで変更禁止。PR取込test失敗は独自修正せず上流比較。"
        ],
        memory_entries=[],
    )

    candidates = collect_memory_placement_candidates(memory_paths)
    inventory = candidates[0]["inventory"]

    assert inventory["current_store"] == "user"
    assert "suggested_route" not in inventory
    assert "route_reasons" not in inventory
    assert "likely_move_user_to_memory" not in str(inventory)
    assert "placement_observations" in inventory
    assert "official_boundary" in inventory
```

Add another regression:

```python
def test_memory_placement_candidate_runtime_fact_is_observation_not_recommendation():
    # A MEMORY or USER entry with ~/.hermes / cron / plugin terms may expose observations,
    # but it must not expose likely_move_* or likely_keep.
```

**Step 2: Verify RED**

```bash
$PY -m pytest tests/test_evidence_inventory_candidates.py -q -k 'memory_placement_candidate'
```

Expected: FAIL because current candidates still expose `suggested_route` / `route_reasons`.

**Step 3: Implement `_memory_placement_observations()`**

In `evidence.py`, replace `_memory_placement_route_hint()` with a smaller helper:

```python
def _memory_placement_observations(old_text: str) -> list[str]:
    lowered = old_text.lower()
    observations: list[str] = []
    if any(marker in lowered for marker in ("~/", "/users/", "/opt/")):
        observations.append("contains_path_like_text")
    if any(marker in lowered for marker in ("cron", "config", "socket", "provider", "gateway", "docker", "compose", "api", "token", "plugin")):
        observations.append("mentions_runtime_or_tooling_term")
    if any(marker in lowered for marker in ("prefers", "preference", "expects", "好む", "望む", "文体", "明示ok", "相談", "依頼")):
        observations.append("contains_user_policy_or_preference_language")
    if any(marker in lowered for marker in ("when ", "before ", "after ", "run ", "check ", "verify", "restart", "troubleshoot", "workflow", "手順", "検証", "確認", "運用")):
        observations.append("contains_procedural_language")
    if len(old_text) > 300:
        observations.append("long_entry")
    return observations
```

Constraints:

- Do not return a route.
- Do not use `current_store` inside the observation helper.
- Keep names descriptive but non-decisional.
- Avoid adding special-case phrases beyond the minimal broad observations above unless a test proves a structural need.

In `collect_memory_placement_candidates()`, replace:

```python
**_memory_placement_route_hint(current_store, old_text),
```

with:

```python
"placement_observations": _memory_placement_observations(old_text),
```

Remove or rename `allowed_recommendations` to neutral `action_vocabulary` if still needed.

**Step 4: Verify GREEN**

```bash
$PY -m pytest tests/test_evidence_inventory_candidates.py -q -k 'memory_placement_candidate'
```

Expected: PASS after test updates.

---

## Task 3: Delete route-derived canonical-store cleanup

**Objective:** Prevent marker-based canonical store guesses from producing cleanup hints. This is mandatory, not optional.

**Files:**

- Modify: `hermes_self_improvement/evidence.py`
- Test: `tests/test_evidence_inventory_candidates.py`

**Step 1: Write RED tests**

Add a test for same text duplicated in USER and MEMORY where semantic store is not programmatically obvious:

```python
def test_cross_store_duplicate_does_not_choose_canonical_store_from_placement_observations():
    # Same exact text appears in user and memory.
    # Text contains mixed user policy + runtime/plugin terms.
    # Inventory group must not emit suggested_action=apply memory_remove based on canonical store.
    # It should defer/review with no concrete memory_operation_hint.
```

Add a source-search regression or assertion that the route-derived helper is gone from active code:

```python
def test_no_route_derived_canonical_store_helper_remains():
    source = Path("hermes_self_improvement/evidence.py").read_text()
    assert "def _canonical_store_for_memory_text" not in source
    assert "_memory_placement_route_hint(\"memory\"" not in source
    assert "_memory_placement_route_hint(\"user\"" not in source
```

**Step 2: Implement mandatory cleanup change**

Delete `_canonical_store_for_memory_text()`.

Delete `_cross_store_duplicate_action_hint()` if it only exists to choose canonical USER/MEMORY store, or reduce it to always return `None` so `_duplicate_memory_group_action_hint()` falls back to defer/review.

Required target behavior:

```python
def _cross_store_duplicate_action_hint(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    return None
```

Preferred target behavior: delete `_cross_store_duplicate_action_hint()` entirely and simplify `_duplicate_memory_group_action_hint()` so cross-store duplicate groups use the same defer path as other semantic duplicates.

Do **not** keep a branch that tries to identify canonical USER/MEMORY store from text markers, observations, path-like text, preference words, or procedural words. Choosing USER vs MEMORY for duplicate removal is semantic and belongs to the LLM.

**Step 3: Verify**

```bash
$PY -m pytest tests/test_evidence_inventory_candidates.py -q -k 'duplicate or memory_inventory or canonical_store'
```

Expected: PASS.

---

## Task 4: Remove `suggested_route` from planner digest

**Objective:** Ensure planner runtime digest consumes observation-only evidence and does not revive `likely_*` defaults.

**Files:**

- Modify: `hermes_self_improvement/planner_runtime.py`
- Test: `tests/test_skill_planner.py`

**Step 1: Write RED tests**

Update `test_planner_digest_exposes_memory_placement_candidates`:

```python
def test_planner_digest_exposes_memory_placement_candidates_without_suggested_route():
    pack_data = pack()
    pack_data["evidence"].append({
        "id": "memory-place-user-runtime",
        "kind": "memory_placement_candidate",
        "inventory": {
            "group_kind": "placement_review",
            "current_store": "user",
            "old_text": "Gmail observer=~/.hermes/automations/gmail-purchase-observer.",
            "summary": "Gmail observer path.",
            "placement_observations": ["contains_path_like_text", "mentions_runtime_or_tooling_term"],
            "official_boundary": "USER=...; MEMORY=...; Skill=...",
        },
    })

    digest = build_planner_digest(pack_data)
    row = digest["memory_placement_candidates"]["candidates"][0]

    assert row["current_store"] == "user"
    assert row["placement_observations"] == ["contains_path_like_text", "mentions_runtime_or_tooling_term"]
    assert "suggested_route" not in row
    assert "route_reasons" not in row
    assert "likely_" not in str(row)
```

**Step 2: Implement digest migration**

In `_memory_placement_candidates_digest()`:

- Read `placement_observations` from inventory.
- Stop defaulting missing route to `likely_defer`.
- Include `official_boundary` if present, clipped.
- Keep `allowed_decisions = memory_placement_allowed_decisions(current_store)`.
- Keep `candidate_target_skills` only if there is procedural observation or text-token overlap, but do not require `likely_memory_to_skill`.

Replace:

```python
"suggested_route": str(inventory.get("suggested_route") or "likely_defer"),
"route_reasons": route_reasons or ["missing_route_reason"],
```

with:

```python
"placement_observations": observations,
"official_boundary": _redacted_preview(inventory.get("official_boundary") or MEMORY_PLACEMENT_BOUNDARY, max_chars=320),
```

If importing `MEMORY_PLACEMENT_BOUNDARY` would create an undesirable dependency, keep the boundary in evidence inventory and omit the fallback here.

**Step 3: Verify**

```bash
$PY -m pytest tests/test_skill_planner.py -q -k 'memory_placement_candidates'
```

Expected: PASS after updating tests.

---

## Task 5: Rewrite the planner prompt section around LLM judgment

**Objective:** Remove route-priority prompt behavior and make the prompt plainly ask for semantic judgment.

**Files:**

- Modify: `hermes_self_improvement/prompts.py`
- Test: `tests/test_skill_planner.py`

**Step 1: Write RED tests**

Add/update prompt rendering test:

```python
def test_render_planner_messages_treats_placement_observations_as_non_authoritative():
    digest = build_planner_digest(pack())
    digest["memory_placement_candidates"] = {
        "candidate_count": 1,
        "omitted_count": 0,
        "candidates": [{
            "evidence_id": "memory-place-user-policy",
            "current_store": "user",
            "old_text": "Hermes/plugin障害: 相談語は調査設計のみ、明示OKまで変更禁止。",
            "summary": "User policy with runtime terms.",
            "placement_observations": ["mentions_runtime_or_tooling_term", "contains_user_policy_or_preference_language"],
            "official_boundary": "USER=user preferences; MEMORY=agent notes; Skill=procedures.",
            "allowed_decisions": ["keep", "move_user_to_memory", "memory_to_skill", "skip", "defer"],
        }],
    }

    rendered = render_planner_messages(digest=digest)
    user_content = rendered["messages"][1]["content"]

    assert "Placement observations are observations, not recommendations" in user_content
    assert "suggested_route" not in user_content
    assert "likely_" not in user_content
    assert "Priority placement candidates" not in user_content
    assert "mentions_runtime_or_tooling_term" in user_content
    assert "contains_user_policy_or_preference_language" in user_content
```

**Step 2: Implement prompt simplification**

In `_render_memory_placement_candidates_section()`:

- Delete the `Priority placement candidates requiring semantic judgment` section.
- Delete `priority_order` sorting by `suggested_route`.
- Render candidates in stable input order, or by evidence id only if needed for determinism.
- Render:
  - `evidence_id`
  - `current_store`
  - `placement_observations`
  - `allowed_decisions`
  - `official_boundary`
  - `old_text`
- Include one concise instruction block:

```text
Placement observations are observations, not recommendations. Decide semantic destination yourself from old_text/current_store/official_boundary. If mixed or unclear, keep current store or defer. Only use a move operation when the opposite store is clearly correct and the operation is listed in allowed_decisions.
```

- Keep move template generated by `placement_move_operation_for_current_store(current_store)`.
- Keep keep/skip and defer templates.
- Do not include a memory_to_skill apply template unless target skill is exact and editable; otherwise let the planner emit defer or normal memory_to_skill only when known.

**Step 3: Verify**

```bash
$PY -m pytest tests/test_skill_planner.py -q -k 'render_planner_messages and memory_placement'
```

Expected: PASS.

---

## Task 6: Update normalizer compatibility without reviving route authority

**Objective:** Keep old artifacts/test fixtures readable while preventing legacy `suggested_route` from controlling new behavior.

**Files:**

- Modify: `hermes_self_improvement/planner_runtime.py`
- Test: `tests/test_skill_planner.py`

**Step 1: Write compatibility tests**

Add a test where legacy evidence includes `suggested_route`, but digest output does not:

```python
def test_legacy_suggested_route_is_not_planner_facing():
    pack_data = pack()
    pack_data["evidence"].append({
        "id": "legacy-place",
        "kind": "memory_placement_candidate",
        "inventory": {
            "current_store": "user",
            "old_text": "Hermes runtime root is ~/.hermes.",
            "suggested_route": "likely_move_user_to_memory",
            "route_reasons": ["contains_runtime_path"],
        },
    })

    digest = build_planner_digest(pack_data)
    row = digest["memory_placement_candidates"]["candidates"][0]

    assert "suggested_route" not in row
    assert "route_reasons" not in row
    assert "legacy_route_hint_present" in row["placement_observations"]
```

**Step 2: Implement legacy demotion**

If `inventory` still has legacy fields:

- Do not forward them.
- Optionally add neutral observations:
  - `legacy_route_hint_present`
  - `legacy_route_reason_present`
- Do not sort or template based on legacy values.

**Step 3: Verify**

```bash
$PY -m pytest tests/test_skill_planner.py -q -k 'legacy_suggested_route or memory_placement_candidates'
```

Expected: PASS.

---

## Task 7: Clean up tests that encode programmatic semantic classification

**Objective:** Convert tests from “program picks the semantic destination” to “program exposes evidence + LLM prompt + hard guards.”

**Files:**

- Modify: `tests/test_evidence_inventory_candidates.py`
- Modify: `tests/test_skill_planner.py`
- Modify: any tests found by searching `suggested_route`, `route_reasons`, `likely_`

**Step 1: Search for old assumptions**

```bash
search_terms='suggested_route|route_reasons|likely_move_user_to_memory|likely_move_memory_to_user|likely_memory_to_skill|likely_keep|likely_defer'
rg "$search_terms" tests hermes_self_improvement -n
```

Use `search_files` instead of shell `rg` if working through Hermes tools.

**Step 2: Update/remove tests**

Replace tests like:

- `test_memory_placement_candidate_hints_user_runtime_fact_should_move_to_memory`
- `test_memory_placement_candidate_hints_memory_user_preference_should_move_to_user`
- `test_memory_placement_candidate_hints_procedural_memory_should_route_to_skill`
- `test_memory_placement_candidate_keeps_user_preference_even_with_runtime_words`
- `test_memory_placement_candidate_defers_user_diary_even_with_ryo_and_reports_words`

with tests like:

- mixed USER policy/runtime words expose multiple observations but no route
- procedural language exposes `contains_procedural_language` but no `memory_to_skill` recommendation
- long entry exposes `long_entry` but no `likely_defer`
- diary-ish text exposes `contains_stale_or_session_history_language` only if retained, but no route
- prompt tells LLM to decide and defer/keep if unclear

**Step 3: Verify no planner-facing route remnants**

```bash
$PY -m pytest tests/test_evidence_inventory_candidates.py tests/test_skill_planner.py -q
```

Expected: PASS.

---

## Task 8: Remove source references and route-based diagnostics from active code paths

**Objective:** Ensure the implementation actually converges on the ideal shape, not just tests, including run artifacts and quality diagnostics.

**Files:**

- Modify: `hermes_self_improvement/evidence.py`
- Modify: `hermes_self_improvement/planner_runtime.py`
- Modify: `hermes_self_improvement/prompts.py`
- Modify: `hermes_self_improvement/markdown_artifacts.py` if it renders placement briefs
- Modify: docs/plan index only as status update

**Step 1: Search active code**

Use `search_files` for:

```text
suggested_route
route_reasons
likely_move_user_to_memory
likely_move_memory_to_user
likely_memory_to_skill
likely_keep
likely_defer
_memory_placement_route_hint
_canonical_store_for_memory_text
by_suggested_route
default_defer_by_route
unhandled_by_route
```

Known current active-code targets include:

- `planner_runtime.py::_memory_placement_candidates_digest()` reading `route_reasons`, emitting `suggested_route`, and branching on `likely_memory_to_skill` for `candidate_target_skills`.
- `planner_runtime.py` memory placement actionability diagnostics around `by_route`, `default_defer_by_route`, `unhandled_by_route`, `by_suggested_route`, and `default_defer_details[*].suggested_route` / `route_reasons`.
- `prompts.py::_render_memory_placement_candidates_section()` priority route section, route sorting, and route rendering.
- `evidence.py::_memory_placement_route_hint()` and `_canonical_store_for_memory_text()`.

**Step 2: Remove or quarantine**

Allowed remnants:

- Tests that explicitly assert legacy inputs are demoted and not planner-facing.
- Archived plans/docs are allowed to mention historical terms.
- Bounded compatibility code may read old fields only to add neutral `legacy_*` observations.
- Non-placement memory-agent internals such as `planner_memory.py` may keep unrelated `suggested_route` fields for memory extractor filtering only if they are not part of memory placement candidates, planner placement digest, placement prompt, or run placement diagnostics. If such names are confusing, add a follow-up cleanup note but do not expand this slice unless tests prove conflict.

Not allowed in active memory placement evidence/digest/prompt/diagnostics behavior:

- route-based sorting
- route-based template selection
- route-based canonical store selection
- route-specific expected values in current candidate tests
- route-named artifact fields such as `by_suggested_route`, `default_defer_by_route`, `unhandled_by_route`, `suggested_route`, or `route_reasons` under `memory_placement_actionability`

**Step 3: Replace route diagnostics with neutral diagnostics**

In planner runtime quality/actionability reporting, replace route buckets with neutral observation/current-store buckets:

```python
by_current_store: dict[str, int]
default_defer_by_current_store: dict[str, int]
unhandled_by_current_store: dict[str, int]
default_defer_details[*].placement_observations
```

If grouping by observations is useful, use names like:

```python
by_observation: dict[str, int]
default_defer_by_observation: dict[str, int]
```

Do not compute these from legacy `suggested_route`; compute them from `current_store` and `placement_observations` only.

**Step 4: Add source-search regression**

Add a focused test that loads active placement files and fails if forbidden placement-route strings remain outside explicit legacy-demotion test fixtures. Minimum assertion:

```python
def test_memory_placement_active_code_has_no_route_heuristic_contracts():
    active_paths = [
        Path("hermes_self_improvement/evidence.py"),
        Path("hermes_self_improvement/planner_runtime.py"),
        Path("hermes_self_improvement/prompts.py"),
    ]
    source = "\n".join(path.read_text() for path in active_paths)
    forbidden = [
        "_memory_placement_route_hint",
        "_canonical_store_for_memory_text",
        "likely_move_user_to_memory",
        "likely_move_memory_to_user",
        "likely_memory_to_skill",
        "likely_keep",
        "likely_defer",
        "by_suggested_route",
        "default_defer_by_route",
        "unhandled_by_route",
    ]
    for token in forbidden:
        assert token not in source
```

If the implementation needs a legacy demotion helper that mentions `suggested_route` or `route_reasons`, keep that helper isolated and make the test allow only that helper by checking exact file/function slices. Do not allow those names in prompt rendering or actionability diagnostics.

**Step 5: Verify search results**

Document remaining allowed hits in the implementation commit message or plan status update. The final dry-run artifact must not expose route-named memory placement diagnostics.

---

## Task 9: Dry-run smoke and artifact inspection

**Objective:** Prove the new flow still gives the LLM enough context while removing heuristic authority.

**Files:**

- No code unless smoke reveals a bug.
- Update: `.hermes/plans/2026-06-01-memory-placement-heuristic-minimalization.md`
- Update: `.hermes/plans/README.md`

**Step 1: Run verification**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
git diff --check
hermes self-improvement status
hermes self-improvement improve --dry-run --json
```

Expected:

- py_compile passes.
- full pytest passes.
- diff check clean.
- status ok.
- dry-run writes a run artifact without mutation.

**Step 2: Inspect the latest run artifact**

Check:

- placement candidates remain present if inventory has USER/MEMORY entries.
- no planner-facing `suggested_route` / `likely_*` appears in digest/prompt diagnostics.
- `allowed_decisions` is direction-valid.
- any rejected placement direction appears as bounded diagnostics, not executable mutation.
- memory/skill changes are zero for dry-run.

**Step 3: Update plan status**

Record:

- exact test counts
- dry-run artifact path
- whether any legacy route fields remain and why
- remaining follow-up, if any

---

## Task 10: Independent review before commit/push

**Objective:** Confirm the refactor did not hide semantic logic elsewhere or loosen destructive guards.

**Files:**

- No planned code edits unless reviewer blocks.

**Review prompt checklist:**

Ask the independent reviewer to inspect the final diff for:

1. Any active planner-facing `suggested_route` / `likely_*` remnants.
2. Any new marker-based semantic classifier introduced under another name.
3. Whether prompt language clearly says observations are non-authoritative.
4. Whether direction/source/stale/add-before-remove hard guards remain.
5. Whether cross-store duplicate cleanup no longer uses route heuristics to pick canonical USER/MEMORY store.
6. Whether tests cover the mixed USER policy + runtime/plugin terms regression.
7. Whether the code stayed simple and avoided new roles/lanes/scorers.

If review returns BLOCKED:

- Patch the smallest specific issue.
- Add/adjust focused regression if needed.
- Rerun focused tests, full suite, and review.
- Do not mark the plan complete until review passes.

---

## Expected commit sequence

Keep commits small and reversible:

1. `test: lock memory placement hard guards`
2. `refactor: replace memory placement routes with observations`
3. `refactor: remove route-priority planner prompt`
4. `test: update placement regressions for llm judgment`
5. `docs: update memory placement heuristic plan status`

If Task 1 direction-validation work is already implemented, start at commit 2 and reference the existing hard-guard commit in the plan status.

---

## Review status

Initial independent plan review: **BLOCKED**.

Resolved review blockers:

1. Task 3 now makes route-derived canonical-store cleanup deletion mandatory; cross-store duplicate cleanup must defer/review instead of choosing USER/MEMORY from text markers.
2. Task 8 now explicitly removes/neutralizes route-named memory placement diagnostics from planner runtime/run artifacts, including `by_suggested_route`, `default_defer_by_route`, `unhandled_by_route`, `suggested_route`, and `route_reasons` under memory placement actionability.

Second independent plan review: **PASS**.

Implementation status: completed, independently re-reviewed after post-push skepticism, and patched for review blockers in this worktree.

Post-push review follow-up:

- Ryo challenged the completion claim, so the implementation was re-checked against this plan and an independent reviewer was run on `HEAD~2..HEAD`.
- Review result: **BLOCKED** because memory placement preview/diagnostic paths still exposed `suggested_route` (`placement_review` / `memory_planner` / `none`) and placement candidates still carried legacy `allowed_recommendations`.
- Follow-up fix removed `allowed_recommendations` from memory placement candidate inventory and editor handoff, replaced it with direction-valid `allowed_decisions`, and removed memory-placement `suggested_route` from preview/default keep/defer diagnostics.

Verification:

- `.venv/bin/python -m pytest tests/test_skill_planner.py -q -k 'memory_placement or cross_store_duplicate'` → 17 passed.
- `.venv/bin/python -m pytest tests/test_evidence_inventory_candidates.py tests/test_skill_planner.py -q` → 86 passed.
- `.venv/bin/python -m pytest -q` → 949 passed, 2 skipped.
- Initial source-directed dry-run from this repo with `PYTHONPATH=$PWD .venv/bin/python` wrote `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260601T113151Z.json`; artifact scan found zero `suggested_route`, `route_reasons`, `likely_*` placement routes, `by_suggested_route`, `default_defer_by_route`, or `unhandled_by_route`.
- Post-review dry-run from this repo wrote `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260601T132421Z.json`; run artifact scan found zero `suggested_route`, `route_reasons`, `likely_*`, `by_suggested_route`, `default_defer_by_route`, `unhandled_by_route`, or `allowed_recommendations`. Latest evidence artifact still contains route strings only inside ignored historical tool/result previews, while live `memory_placement_candidate` inventory has `allowed_decisions` / `placement_observations` and no `allowed_recommendations` / `suggested_route`.
