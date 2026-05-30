# Memory Placement Planner Actionability Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Make USER.md / MEMORY.md placement candidates first-class planner decisions so clear USER↔MEMORY moves and MEMORY→Skill routes are evaluated explicitly instead of being hidden in evidence ID lists.

**Architecture:** Extend the existing evidence → planner digest → prompt → canonical transaction path. Do not add new roles, lanes, queues, confidence gates, or memory execution semantics. Deterministic placement hints are advisory only; the planner still decides, and the Knowledge Editor still executes only through official skill/memory tools.

**Tech Stack:** Python, `hermes_self_improvement/evidence.py`, `planner_runtime.py`, `prompts.py`, `knowledge_transactions.py` / existing normalization, pytest, source dry-run smoke.

---

## Current diagnosis

The latest source dry-run before this plan is:

- Run artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260530T141932Z.json`
- Evidence artifact: `/Users/ryo.nakae/.hermes/self-improvement/evidence/evidence-2026-05-30T14-18-26.676753-00-00.json`
- Result: `target_changed=False`, `action_summary={apply:0, defer:4, skip:46, block:0}`
- Canonical transaction shape: `knowledge_transactions.by_kind={memory:3, none:1, skill:46}`

The plugin already generated many `memory_placement_candidate` items, including entries that a human can plausibly classify as USER↔MEMORY moves or MEMORY→Skill candidates. However, the planner did not select placement/memory-to-skill actions.

Root causes to fix:

1. **Placement candidates are not first-class in the planner digest/prompt.**
   - `memory_placement_candidate` evidence exists, but the planner digest only exposes first-class `built_in_memory_inventory` and `memory_inventory_groups` sections.
   - The prompt contains `memory_place_*` ids only in a broad evidence id list, not as actionable rows with current store, text, suggested route, and exact `old_text`.

2. **There is no explicit per-placement decision requirement.**
   - Grouped memory inventory now says “one explicit decision per group”.
   - Placement candidates do not have the equivalent “one explicit decision per placement candidate”, so the planner can legitimately ignore them.

3. **USER-side entries are not surfaced in the detailed built-in inventory section.**
   - The latest built-in inventory detailed section contained 8 MEMORY entries and no USER entries.
   - USER entries existed as `memory_placement_candidate` evidence, so USER→MEMORY opportunities were present but not visible enough to drive decisions.

4. **Placement candidates lack deterministic heuristic hints.**
   - Current `candidate_reasons` are mostly `good_as_is`, with only obvious cases like `too_verbose` on one long MEMORY entry.
   - The planner needs advisory labels such as `likely_move_user_to_memory`, `likely_move_memory_to_user`, `likely_memory_to_skill`, `likely_keep`, and `likely_defer`, plus reasons like `contains_runtime_path`, `user_preference_language`, `procedural_workflow`, or `too_verbose`.

## Non-goals / safety boundaries

- Do not force a live memory mutation.
- Do not loosen memory/skill mutation safety gates.
- Do not edit built-in memory files or provider DBs directly.
- Do not add approval queues, confidence thresholds, new roles, or separate user-visible skill/memory lanes.
- Do not route to `external_memory` in this slice.
- Do not make heuristic hints executable authority. They are planner context only.

## Completion criteria

This plan is complete when:

- `memory_placement_candidate` evidence is rendered in a dedicated planner prompt section.
- Each rendered placement item includes bounded exact `old_text`, current store, suggested route, route reason, and allowed decisions.
- Planner prompt explicitly requires one decision per placement candidate.
- Deterministic route hints are present for representative USER→MEMORY, MEMORY→USER, MEMORY→Skill, keep, and defer/too-verbose cases.
- Existing canonical transaction normalization accepts placement decisions without a skill target.
- Focused RED/GREEN tests pass, full suite passes, `git diff --check` passes.
- Source dry-run remains `target_changed=False` and artifact inspection proves placement candidates are no longer hidden: either explicit placement/memory-to-skill decisions appear, or defer/skip reasons are attached per placement candidate.

---

## Task 1: Add deterministic placement hint tests

**Objective:** Lock the missing advisory labels before implementation.

**Files:**
- Modify: `tests/test_evidence_inventory_candidates.py`
- Target code: `hermes_self_improvement/evidence.py`

**Step 1: Write failing tests**

Add focused tests for `collect_memory_placement_candidates()`:

```python
def test_memory_placement_candidate_hints_user_runtime_fact_should_move_to_memory(tmp_path):
    user = tmp_path / "USER.md"
    user.write_text("Gmail observer=~/.hermes/automations/gmail-purchase-observer, cron=~/.hermes/cron/jobs.json.\n", encoding="utf-8")

    item = collect_memory_placement_candidates({"user": user, "memory": tmp_path / "MEMORY.md"})[0]
    inv = item["inventory"]

    assert inv["current_store"] == "user"
    assert inv["suggested_route"] == "likely_move_user_to_memory"
    assert "contains_runtime_path" in inv["route_reasons"]
    assert inv["old_text"].startswith("Gmail observer=")
```

```python
def test_memory_placement_candidate_hints_memory_user_preference_should_move_to_user(tmp_path):
    memory = tmp_path / "MEMORY.md"
    memory.write_text("Ryo prefers concise implementation reports with completed and remaining work clearly stated.\n", encoding="utf-8")

    item = collect_memory_placement_candidates({"memory": memory, "user": tmp_path / "USER.md"})[0]
    inv = item["inventory"]

    assert inv["current_store"] == "memory"
    assert inv["suggested_route"] == "likely_move_memory_to_user"
    assert "user_preference_language" in inv["route_reasons"]
```

```python
def test_memory_placement_candidate_hints_procedural_memory_should_route_to_skill(tmp_path):
    memory = tmp_path / "MEMORY.md"
    memory.write_text("Gateway restart: check host script, then KeepAlive, then verify logs before retrying.\n", encoding="utf-8")

    item = collect_memory_placement_candidates({"memory": memory, "user": tmp_path / "USER.md"})[0]
    inv = item["inventory"]

    assert inv["suggested_route"] == "likely_memory_to_skill"
    assert "procedural_or_operational_workflow" in inv["route_reasons"]
```

**Step 2: Run RED**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest \
  tests/test_evidence_inventory_candidates.py::test_memory_placement_candidate_hints_user_runtime_fact_should_move_to_memory \
  tests/test_evidence_inventory_candidates.py::test_memory_placement_candidate_hints_memory_user_preference_should_move_to_user \
  tests/test_evidence_inventory_candidates.py::test_memory_placement_candidate_hints_procedural_memory_should_route_to_skill \
  -q
```

Expected: fail because `suggested_route` / `route_reasons` are absent.

---

## Task 2: Implement minimal placement hint helper

**Objective:** Add deterministic, bounded, advisory placement routing hints.

**Files:**
- Modify: `hermes_self_improvement/evidence.py`
- Test: `tests/test_evidence_inventory_candidates.py`

**Implementation sketch:**

Add helper functions near `MEMORY_PLACEMENT_BOUNDARY`:

```python
def _memory_placement_route_hint(current_store: str, old_text: str) -> dict[str, Any]:
    lowered = old_text.lower()
    reasons: list[str] = []

    user_markers = ("prefers", "preference", "expects", "reports", "communication", "文体", "好む", "望む", "報告", "質問では")
    runtime_markers = ("~/", "/users/", "/opt/", "cron", "config", "socket", "provider", "gateway", "docker", "compose", "api", "token", "plugin")
    procedural_markers = ("when ", "before ", "after ", "run ", "check ", "verify", "restart", "troubleshoot", "workflow", "手順", "検証", "確認", "運用")
    diary_markers = ("completed", "fixed", "submitted", "merged", "phase", "done", "yesterday", "today", "pr ", "issue ")

    if any(marker in lowered for marker in diary_markers):
        return {"suggested_route": "likely_defer", "route_reasons": ["stale_or_diary_language"]}
    if any(marker in lowered for marker in procedural_markers):
        return {"suggested_route": "likely_memory_to_skill", "route_reasons": ["procedural_or_operational_workflow"]}
    if current_store == "user" and any(marker in lowered for marker in runtime_markers):
        return {"suggested_route": "likely_move_user_to_memory", "route_reasons": ["contains_runtime_path"]}
    if current_store == "memory" and any(marker in lowered for marker in user_markers):
        return {"suggested_route": "likely_move_memory_to_user", "route_reasons": ["user_preference_language"]}
    if len(old_text) > 300:
        return {"suggested_route": "likely_defer", "route_reasons": ["too_verbose"]}
    return {"suggested_route": "likely_keep", "route_reasons": ["store_matches_known_boundary_or_low_signal"]}
```

Then in `collect_memory_placement_candidates()`, add these fields to `inventory`:

```python
route_hint = _memory_placement_route_hint(current_store, old_text)
inventory.update(route_hint)
```

Keep existing `allowed_recommendations` unchanged.

**Step 3: Run GREEN**

Run the RED tests from Task 1. Expected: pass.

---

## Task 3: Add planner digest section for placement candidates

**Objective:** Make placement candidates first-class data in the planner digest.

**Files:**
- Modify: `tests/test_skill_planner.py`
- Modify: `hermes_self_improvement/planner_runtime.py`

**Step 1: Write failing test**

Add a test in `tests/test_skill_planner.py`:

```python
def test_planner_digest_exposes_memory_placement_candidates():
    pack_data = pack()
    pack_data["evidence"].append({
        "id": "memory-place-user-runtime",
        "kind": "memory_placement_candidate",
        "inventory": {
            "group_kind": "placement_review",
            "current_store": "user",
            "old_text": "Gmail observer=~/.hermes/automations/gmail-purchase-observer.",
            "summary": "Gmail observer path.",
            "suggested_route": "likely_move_user_to_memory",
            "route_reasons": ["contains_runtime_path"],
        },
        "likely_targets": [{"target": "memory", "weight": 0.7}, {"target": "skill", "weight": 0.3}],
    })

    digest = build_planner_digest(pack_data)
    placements = digest["memory_placement_candidates"]

    assert placements["candidate_count"] == 1
    row = placements["candidates"][0]
    assert row["evidence_id"] == "memory-place-user-runtime"
    assert row["current_store"] == "user"
    assert row["suggested_route"] == "likely_move_user_to_memory"
    assert row["route_reasons"] == ["contains_runtime_path"]
    assert row["old_text"] == "Gmail observer=~/.hermes/automations/gmail-purchase-observer."
```

**Step 2: Run RED**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_skill_planner.py::test_planner_digest_exposes_memory_placement_candidates -q
```

Expected: fail because digest key is absent.

**Step 3: Implement**

In `planner_runtime.py`, add `_memory_placement_candidates_digest(evidence_pack)` near the existing memory digest helpers.

Output shape:

```python
{
  "candidate_count": len(candidates),
  "omitted_count": omitted,
  "candidates": [
    {
      "evidence_id": "...",
      "current_store": "user" | "memory",
      "suggested_route": "likely_...",
      "route_reasons": [...],
      "old_text": "bounded exact old_text",
      "summary": "bounded summary",
      "allowed_decisions": [
        "keep", "move_user_to_memory", "move_memory_to_user",
        "memory_to_skill", "skip", "defer"
      ],
    }
  ]
}
```

Bounds:

- max candidates: 40
- `old_text`: `_redacted_preview(..., max_chars=260)`
- `summary`: `_redacted_preview(..., max_chars=180)`
- route reasons: max 6, max 80 chars each

Add to `build_planner_runtime_digest()`:

```python
"memory_placement_candidates": _memory_placement_candidates_digest(evidence_pack),
```

**Step 4: Run GREEN**

Run the test. Expected: pass.

---

## Task 4: Render placement candidates in planner prompt

**Objective:** Require one explicit decision per placement candidate.

**Files:**
- Modify: `tests/test_skill_planner.py`
- Modify: `hermes_self_improvement/prompts.py`

**Step 1: Write failing test**

Add:

```python
def test_render_planner_messages_exposes_memory_placement_candidates():
    digest = build_planner_digest(pack())
    digest["memory_placement_candidates"] = {
        "candidate_count": 1,
        "omitted_count": 0,
        "candidates": [{
            "evidence_id": "memory-place-user-runtime",
            "current_store": "user",
            "suggested_route": "likely_move_user_to_memory",
            "route_reasons": ["contains_runtime_path"],
            "old_text": "Gmail observer=~/.hermes/automations/gmail-purchase-observer.",
            "summary": "Gmail observer path.",
            "allowed_decisions": ["keep", "move_user_to_memory", "move_memory_to_user", "memory_to_skill", "skip", "defer"],
        }],
    }

    rendered = render_planner_messages(digest=digest)
    user_content = rendered["messages"][1]["content"]

    assert "## Memory placement candidates" in user_content
    assert "one explicit decision per memory placement candidate" in user_content
    assert "evidence_id=memory-place-user-runtime" in user_content
    assert "current_store=user" in user_content
    assert "suggested_route=likely_move_user_to_memory" in user_content
    assert "route_reasons=[contains_runtime_path]" in user_content
    assert "Gmail observer=~/.hermes/automations/gmail-purchase-observer." in user_content
```

**Step 2: Run RED**

Expected: fail because section is absent.

**Step 3: Implement**

Add `_render_memory_placement_candidates_section(digest)` in `prompts.py`.

Prompt language:

```text
## Memory placement candidates
These USER.md / MEMORY.md placement findings are first-class planner inputs. Return one explicit decision per memory placement candidate: keep, move_user_to_memory, move_memory_to_user, memory_to_skill, skip, or defer. Treat suggested_route as advisory, not authority. Use exact old_text when moving/removing. Defer if the entry is valuable but too broad, too long, or ambiguous.
```

For each row:

```text
- evidence_id=...; current_store=...; suggested_route=...; route_reasons=[...]; old_text=...
```

Include this section after `## Built-in memory inventory` and before `## Memory inventory cleanup groups` so placement and cleanup are both visible.

**Step 4: Run GREEN**

Run the new prompt test. Expected: pass.

---

## Task 5: Ensure canonical planner output accepts placement decisions

**Objective:** Confirm planner can emit placement decisions without falling into skill-target normalization.

**Files:**
- Modify: `tests/test_skill_planner.py`
- Possibly modify: `hermes_self_improvement/knowledge_transactions.py` or `planner_runtime.py` if tests reveal gaps

Existing coverage already includes `test_planner_accepts_memory_inventory_product_operations_without_skill_target()` for `move_user_to_memory`. Add targeted tests for `memory_to_skill` from placement candidate if not already covered.

**Step 1: Write failing or confirming test**

```python
def test_planner_accepts_memory_placement_memory_to_skill_without_skill_candidate_target():
    def fake_planner(*, digest, config):
        return {"knowledge_transactions": [{
            "decision": "apply",
            "operation": "memory_to_skill",
            "source_store": "builtin_memory",
            "target_store": "skill",
            "target_skill": "gateway-operations",
            "source_old_text": "Gateway restart: check host script, then KeepAlive, then verify logs before retrying.",
            "content": "Add gateway restart verification steps.",
            "evidence_ids": ["memory-place-procedure"],
            "reason": "procedural operational workflow belongs in a skill",
        }]}

    result = run_planner(build_planner_digest(pack()), config={"_planner_func": fake_planner})
    tx = result["knowledge_transactions"][0]

    assert tx["transaction_kind"] == "memory_to_skill"
    assert tx["decision"] == "apply"
    assert tx["source_store"] == "builtin_memory"
    assert tx["target_store"] == "skill"
    assert tx["target_skill"] == "gateway-operations"
```

**Step 2: Run**

If this already passes, treat it as confirming coverage. If it fails, implement the minimal normalization fix.

---

## Task 6: Add actionability/accounting visibility for placement candidates

**Objective:** Make the dry-run artifact/report reveal whether placement candidates were explicitly handled or silently omitted.

**Files:**
- Modify: likely `hermes_self_improvement/planner_runtime.py` quality/routing helpers or existing knowledge routing summary
- Tests: likely `tests/test_report_improve_connection.py` or `tests/test_skill_planner.py`

**Behavior:**

Add a planner-quality/readiness count such as:

```json
"memory_placement_actionability": {
  "candidate_count": 25,
  "selected_count": 3,
  "unhandled_count": 22,
  "by_suggested_route": {"likely_move_user_to_memory": 3, ...},
  "unhandled_by_route": {"likely_memory_to_skill": 4, ...}
}
```

Keep this diagnostic-only. Do not fail the run solely because count is nonzero unless an existing actionability-loss mechanism already does so.

**Tests:**

- Build a digest with two placement candidates.
- Planner returns one transaction referencing one evidence id.
- Quality/report helper counts one selected and one unhandled.

**Verification:**

Focused test should fail before implementation and pass after.

---

## Task 7: Source dry-run smoke and artifact inspection

**Objective:** Verify the worktree code produces materially better dry-run evidence without mutation.

**Commands:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest \
  tests/test_evidence_inventory_candidates.py \
  tests/test_skill_planner.py \
  tests/test_report_improve_connection.py \
  -q
$PY -m pytest tests -q
git diff --check
$PY -c 'import sys; from hermes_self_improvement.cli import main; sys.argv=["hermes-self-improvement","improve","--dry-run","--since-hours","24","--json"]; main()' > /tmp/hermes-si-placement-actionability-dryrun.json
```

Inspect:

- `target_changed` must be `False`.
- Run artifact path exists.
- Evidence artifact still includes `memory_placement_candidate` rows.
- Planner prompt/digest includes `memory_placement_candidates` section.
- Planner output includes either:
  - concrete `move_*` / `memory_to_skill` transactions for clear cases, or
  - explicit `defer` / `skip` decisions per placement candidate with reasons.
- Diagnostic should prove placement candidates are no longer only hidden in an evidence id list.

Do not consider the slice successful if placement candidates still only appear as `memory_place_*` ids in a generic evidence list.

---

## Task 8: Update plans/index and commit

**Objective:** Keep the repo-tracked roadmap accurate.

**Files:**
- Modify: `.hermes/plans/README.md`
- Modify: `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`
- Modify this plan’s Status/Result section after implementation

**Updates:**

- Add an update note that placement candidates are now first-class planner inputs.
- Record the source dry-run artifact and whether it produced apply/defer/skip decisions.
- State explicitly whether memory mutation was selected; do not overclaim.
- If all useful candidates still defer, record the concrete reasons and next follow-up.

**Commit:**

```bash
git status --short
git add .hermes/plans/README.md .hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md .hermes/plans/2026-05-30-memory-placement-planner-actionability.md hermes_self_improvement/evidence.py hermes_self_improvement/planner_runtime.py hermes_self_improvement/prompts.py tests/test_evidence_inventory_candidates.py tests/test_skill_planner.py tests/test_report_improve_connection.py
git commit -m "fix: expose memory placement decisions to planner"
git push
```

---

## Risks and guardrails

- **Risk:** Heuristics over-steer the planner.
  - Guardrail: prompt says hints are advisory, not authority; destructive operations still require exact `old_text`; ambiguous cases defer.

- **Risk:** `memory_to_skill` becomes too eager.
  - Guardrail: route hint only; planner must choose target skill and editor must validate through existing skill/memory execution path.

- **Risk:** Prompt gets too large.
  - Guardrail: cap placement candidates at 40, bound text, omit with `omitted_count`.

- **Risk:** The dry-run still returns no applies.
  - That is acceptable if every placement candidate now has an explicit defer/skip reason. The target improvement is actionability and accountability, not mutation count.

## Implementation result — 2026-05-30

Implemented and verified.

Code changes:

- `collect_memory_placement_candidates()` now adds deterministic advisory route hints:
  - `likely_move_user_to_memory`
  - `likely_move_memory_to_user`
  - `likely_memory_to_skill`
  - `likely_keep`
  - `likely_defer`
- `build_planner_runtime_digest()` now exposes `memory_placement_candidates` as a first-class section with bounded `old_text`, `current_store`, `suggested_route`, `route_reasons`, and allowed decisions.
- `render_planner_messages()` now renders `## Memory placement candidates` and asks for one explicit decision per placement candidate.
- Planner normalization now adds a safe canonical `defer` transaction for any unhandled placement candidate, so candidates cannot silently disappear even when the LLM omits them.
- Planner quality now reports `memory_placement_actionability` with candidate counts, selected/unhandled counts, route buckets, and default defer count.

Verification:

- Focused RED/GREEN hint tests: passed.
- Focused digest/prompt/actionability tests: passed.
- `py_compile`: passed.
- Related suite: `89 passed`.
- Full suite: `922 passed, 2 skipped`.
- `git diff --check`: passed.
- Source dry-run artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260530T161349Z.json`
  - `target_changed=False`
  - `dry_run=True`
  - `action_summary={'apply': 0, 'block': 0, 'defer': 27, 'skip': 73}`
  - `memory_placement_actionability={'candidate_count': 25, 'selected_count': 25, 'unhandled_count': 0, 'default_defer_count': 25}`
  - route buckets: `likely_keep=16`, `likely_move_user_to_memory=3`, `likely_move_memory_to_user=2`, `likely_memory_to_skill=3`, `likely_defer=1`

Interpretation:

- The implementation fixed the visibility/accountability gap: placement candidates are no longer hidden behind generic `memory_place_*` ids.
- The latest live planner still did not make semantic placement decisions for those 25 candidates; all were preserved by default defer as `memory_placement_candidate_not_selected_by_planner`.
- No memory/skill mutation was selected or executed.
- Next follow-up, if needed, should improve planner compliance with the placement section rather than loosening execution safety.

## Expected outcome

After this plan, the next dry-run should answer Ryo’s question directly:

- Which USER entries should move to MEMORY?
- Which MEMORY entries should move to USER?
- Which MEMORY entries should become Skill updates?
- Which entries are kept, skipped, or deferred, and why?

If the answer is still “none,” the artifact must show that as explicit planner/default-defer accounting per placement candidate, not as an omission.
