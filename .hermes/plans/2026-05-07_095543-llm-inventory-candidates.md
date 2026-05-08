# LLM Inventory Candidates Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task. Keep the design inside the existing `improve` loop; do not add a new user-facing command, approval queue, or separate “lane”.

**Goal:** Make `improve` consider fuzzy skill / memory cleanup candidates, not only tool failures, and auto-apply safe changes through the existing planner/editor/mutation tools.

**Architecture:** Add an inventory candidate source to the current evidence pack before planner execution. Program code only collects compact skill/memory inventory groups and hard safety metadata; the LLM planner/editor decide whether to patch/archive/replace/remove. Skill changes continue through `skill_manage` / Curator archive primitives, memory changes continue through `memory` / provider-native memory tools. Human confirmation is not a primary workflow; unsafe or under-evidenced items become `defer` / `skip` with artifact evidence.

**Tech Stack:** Python, pytest, Hermes plugin runtime, `bin/hermes-self-improve improve`, runtime artifacts under `${HERMES_HOME:-~/.hermes}/self-improvement/`, official Hermes skill/memory tools.

---

## Current baseline

Observed 2026-05-07:

- `run_improve()` builds `evidence_pack` in `hermes_self_improvement/cli.py` from runtime events plus Curator telemetry.
- `build_evidence_pack()` in `hermes_self_improvement/evidence.py` mostly emits tool-failure evidence and cluster evidence.
- `analysis.py` has exact duplicate-line memory compression and explicit marker-based skill lifecycle scanners, but the daily runs show `explicit_candidate_count: 0` and proposals are dominated by tool failures.
- `build_skill_planner_digest()` in `planner.py` already sends compact candidate rows and attached evidence to the LLM planner.
- `run_skill_improvement_step()` already executes planner `run_editor` through the native skill-tool editor harness, and `archive_skill` through Curator-style archive primitives.
- `run_memory_improvement_step()` currently executes memory operations only when an evidence item contains a concrete memory operation; it does not have an LLM planner/editor step for fuzzy memory cleanup.

## Scope

In scope:

- Add compact skill inventory candidates to the existing `improve` evidence pack.
- Add compact memory inventory candidates to the existing `improve` evidence pack.
- Let the existing LLM planner/editor decide fuzzy skill cleanup.
- Add a small LLM memory planner/editor path only if needed to convert fuzzy memory inventory candidates into concrete `memory` tool operations.
- Auto-apply by default when mutation is enabled and hard safety checks pass.
- Keep detailed candidate groups in artifacts; keep CLI/tool summaries compact.

Out of scope:

- No new CLI surface such as `inventory`, `review`, `approve`, or `apply`.
- No Hermes core changes.
- No direct filesystem edits to skill or memory stores.
- No plugin-bundled / hub / external-dir / pinned skill mutation.
- No heavy runtime hook work; inventory collection runs in `improve`, not in hooks.
- No broad rewrite of prompts or evaluator architecture.

## Safety model

Default posture: auto-apply safe changes; defer only when hard boundaries fail.

Auto-apply allowed after LLM decision and hard checks:

- Local mutable active/stale agent-created skill patch.
- Local mutable obsolete/superseded skill archive when successor/reference checks pass.
- Skill bridge thinning, stale path/command correction, old implementation step update, small pitfall/verification update.
- Built-in memory replace/remove/add through the `memory` tool when target and old text are specific.
- External memory correction through provider-native tool when supported.

Hard stops:

- Pinned, archived, plugin-bundled, hub-installed, external-dir, built-in, or ambiguous-provenance skill.
- Skill delete/rename/merge as destructive operations. Prefer patching canonical/bridge content or archive only when Curator-style archive is valid.
- Memory entry contains secret/credential/PII-like content.
- Memory remove/replace lacks a specific `old_text` or target store.
- Candidate cannot name a concrete target.
- Change would require editing config, repo docs, Hermes core, cron jobs, or arbitrary files.

---

## Task 1: Add inventory candidate schema helpers

**Objective:** Define compact evidence shapes for skill and memory inventory candidates without changing runtime behavior.

**Files:**

- Modify: `hermes_self_improvement/evidence.py`
- Modify: `tests/test_evidence_inventory_candidates.py` or create if absent

**Step 1: Write failing tests**

Create tests for helper output only:

```python
def test_skill_inventory_candidate_has_compact_shape():
    candidate = make_skill_inventory_candidate(
        candidate_id="skill-inv-1",
        group_kind="similar_skills",
        target_names=["alpha-workflow", "alpha-legacy"],
        rationale="similar names and overlapping descriptions",
        hints=["possible bridge/canonical cleanup"],
        risk="low",
    )

    assert candidate["kind"] == "skill_inventory_candidate"
    assert candidate["likely_targets"] == [{"target": "skill", "weight": 0.9}]
    assert candidate["inventory"]["group_kind"] == "similar_skills"
    assert candidate["inventory"]["target_names"] == ["alpha-workflow", "alpha-legacy"]
    assert "full_content" not in json.dumps(candidate)


def test_memory_inventory_candidate_has_compact_shape():
    candidate = make_memory_inventory_candidate(
        candidate_id="memory-inv-1",
        group_kind="semantic_duplicate",
        entries=[{"target": "memory", "old_text": "Old fact", "summary": "Old fact"}],
        rationale="semantic duplicate",
        hints=["replace or remove duplicate"],
        risk="medium",
    )

    assert candidate["kind"] == "memory_inventory_candidate"
    assert candidate["likely_targets"] == [{"target": "memory", "weight": 0.9}]
    assert candidate["inventory"]["entries"][0]["target"] == "memory"
```

**Step 2: Run tests and verify failure**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_evidence_inventory_candidates.py -q
```

Expected: fail because helpers do not exist.

**Step 3: Implement helpers**

Add small helper functions in `evidence.py`:

- `make_skill_inventory_candidate(...)`
- `make_memory_inventory_candidate(...)`
- compact IDs, `kind`, `likely_targets`, `inventory`, `rationale`, `hints`, `risk`
- no full skill/memory body fields
- use existing redaction helper where text snippets are included

**Step 4: Run tests and verify pass**

```bash
$PY -m pytest tests/test_evidence_inventory_candidates.py -q
```

Expected: pass.

**Step 5: Commit**

```bash
git add hermes_self_improvement/evidence.py tests/test_evidence_inventory_candidates.py
git commit -m "feat: add inventory candidate evidence shapes"
```

---

## Task 2: Collect compact skill inventory groups inside `improve`

**Objective:** Add programmatic collection of likely skill cleanup groups while leaving judgment to the LLM planner/editor.

**Files:**

- Modify: `hermes_self_improvement/evidence.py`
- Modify: `hermes_self_improvement/cli.py`
- Test: `tests/test_evidence_inventory_candidates.py`

**Step 1: Write failing tests**

Add tests for a pure collector:

```python
def test_collect_skill_inventory_candidates_groups_similar_mutable_skills():
    curator = {
        "candidates": [
            {"name": "hermes-browser-automation", "mutable": True, "state": "active", "provenance": "agent_created", "description": "Browser automation for Hermes"},
            {"name": "hermes-browser-automation-old", "mutable": True, "state": "stale", "provenance": "agent_created", "description": "Old browser automation notes"},
            {"name": "github-code-review", "mutable": True, "state": "active", "provenance": "agent_created", "description": "Review PRs"},
        ]
    }

    items = collect_skill_inventory_candidates(curator)

    assert any(item["kind"] == "skill_inventory_candidate" for item in items)
    group = items[0]["inventory"]
    assert group["group_kind"] in {"similar_skills", "possible_stale_skill"}
    assert "hermes-browser-automation" in group["target_names"]


def test_collect_skill_inventory_candidates_skips_non_mutable_and_pinned():
    curator = {"candidates": [
        {"name": "bundled", "mutable": False, "pinned": False, "description": "x"},
        {"name": "pinned", "mutable": True, "pinned": True, "description": "x"},
    ]}

    assert collect_skill_inventory_candidates(curator) == []
```

**Step 2: Run tests and verify failure**

```bash
$PY -m pytest tests/test_evidence_inventory_candidates.py -q
```

Expected: fail.

**Step 3: Implement collector**

Add `collect_skill_inventory_candidates(curator_telemetry, *, limit=20)`:

- Input: Curator telemetry candidates only.
- Filter: `mutable == True`, not pinned, state in `active|stale`, provenance/source not bundled/hub/external.
- Group heuristics are intentionally shallow:
  - same normalized prefix before `-old`, `-legacy`, `-plugin`, `-operations`, `-development`
  - same first two hyphen tokens when descriptions overlap
  - stale skill with active sibling-like name
  - explicit obsolete/superseded marker from existing scanner if available
- Output: compact inventory candidates with target names, descriptions, usage summaries, hints, and rationale.
- Do **not** decide merge/archive/patch in code.

**Step 4: Wire into evidence pack**

In `build_evidence_pack()`, after Curator candidates are known:

```python
inventory_evidence = collect_skill_inventory_candidates(curator_telemetry)
evidence.extend(inventory_evidence)
kind_counts["skill_inventory_candidate"] += len(inventory_evidence)
views = _views_for_evidence(evidence)
```

**Step 5: Verify with tests**

```bash
$PY -m pytest tests/test_evidence_inventory_candidates.py tests/test_analysis_reclassification.py -q
```

Expected: pass.

**Step 6: Commit**

```bash
git add hermes_self_improvement/evidence.py hermes_self_improvement/cli.py tests/test_evidence_inventory_candidates.py
git commit -m "feat: collect skill inventory candidates"
```

---

## Task 3: Let skill planner/editor auto-apply inventory-backed skill cleanup

**Objective:** Ensure LLM planner can select `run_editor` / `archive_skill` for inventory candidates and the editor has enough context to patch safely.

**Files:**

- Modify: `hermes_self_improvement/planner.py`
- Modify: `hermes_self_improvement/prompts.py`
- Modify: `tests/test_planner.py` or create focused tests in existing planner test file

**Step 1: Write failing tests**

Add tests that inventory evidence attaches to named skills and permits planner decisions:

```python
def test_skill_planner_digest_attaches_inventory_candidate_to_all_group_targets():
    pack = {
        "summary": {"event_count": 0, "evidence_count": 1, "ignored_count": 0},
        "views": {"skill": ["inv-1"]},
        "evidence": [{
            "id": "inv-1",
            "kind": "skill_inventory_candidate",
            "inventory": {
                "group_kind": "similar_skills",
                "target_names": ["alpha-main", "alpha-legacy"],
                "hints": ["legacy skill may be folded into canonical"],
            },
            "likely_targets": [{"target": "skill", "weight": 0.9}],
        }],
        "skill_candidates": [
            {"name": "alpha-main", "mutable": True, "state": "active", "provenance": "agent_created"},
            {"name": "alpha-legacy", "mutable": True, "state": "stale", "provenance": "agent_created"},
        ],
    }

    digest = build_skill_planner_digest(pack)

    rows = {row["name"]: row for row in digest["skill_candidates"]}
    assert rows["alpha-main"]["attached_evidence_count"] == 1
    assert rows["alpha-legacy"]["attached_evidence_count"] == 1
    assert rows["alpha-main"]["medium_evidence_count"] >= 1
```

Add normalization test:

```python
def test_planner_allows_run_editor_with_inventory_evidence():
    # Build digest with one inventory evidence id attached.
    # Normalize a raw planner decision {decision: run_editor, evidence_ids: ["inv-1"]}.
    # Assert decision remains run_editor.
```

**Step 2: Run tests and verify failure**

```bash
$PY -m pytest tests/test_planner.py -q
```

Expected: fail until inventory evidence is attached.

**Step 3: Implement planner digest attachment**

In `build_skill_planner_digest()`:

- For `skill_inventory_candidate`, read `inventory.target_names`.
- Attach the evidence to every candidate in that list if candidate exists.
- Mark `evidence_match = "inventory_group"` and strength medium.
- Include compact `inventory` in `representative_evidence` so the LLM sees why the group exists.

**Step 4: Prompt update**

In `PLANNER_SYSTEM_PROMPT` / `PLANNER_USER_PREFIX`, add minimal wording:

- Inventory candidates are LLM-evaluated cleanup suggestions, not conclusions.
- Prefer auto-applicable `run_editor` for local safe patches.
- Use `archive_skill` only for explicit obsolete/superseded/archive evidence and hard checks.
- Do not use `defer` merely because the signal is fuzzy; defer only when target/action is unclear or unsafe.

In `EDITOR_BASE_SECTIONS` / hard stops, add:

- For inventory evidence, inspect the target skill and make the smallest durable cleanup.
- Bridge/canonical cleanup should usually patch bridge/canonical wording, not delete/merge.

**Step 5: Verify tests**

```bash
$PY -m pytest tests/test_planner.py tests/test_prompt_overlays.py -q
```

Expected: pass.

**Step 6: Commit**

```bash
git add hermes_self_improvement/planner.py hermes_self_improvement/prompts.py tests/test_planner.py
git commit -m "feat: plan skill cleanup from inventory evidence"
```

---

## Task 4: Add compact memory inventory candidates

**Objective:** Collect fuzzy memory cleanup inputs without direct memory file mutation.

**Files:**

- Modify: `hermes_self_improvement/evidence.py`
- Modify: `hermes_self_improvement/config.py` if existing config needs path helpers
- Test: `tests/test_evidence_inventory_candidates.py`

**Step 1: Write failing tests**

Use temp memory files; do not touch real user memory:

```python
def test_collect_memory_inventory_candidates_groups_near_duplicates(tmp_path):
    memory = tmp_path / "MEMORY.md"
    user = tmp_path / "USER.md"
    memory.write_text("Hermes runtime root is ~/.hermes.\nHermes runtime lives under ~/.hermes.\n", encoding="utf-8")
    user.write_text("User prefers short Japanese responses.\n", encoding="utf-8")

    items = collect_memory_inventory_candidates(memory_paths={"memory": memory, "user": user})

    assert any(item["kind"] == "memory_inventory_candidate" for item in items)
    inv = items[0]["inventory"]
    assert inv["group_kind"] in {"semantic_duplicate", "near_duplicate"}
    assert all("old_text" in entry for entry in inv["entries"])


def test_collect_memory_inventory_candidates_redacts_and_limits_entries(tmp_path):
    memory = tmp_path / "MEMORY.md"
    memory.write_text("API_KEY=secret-value\nAPI_KEY=secret-value\n", encoding="utf-8")

    items = collect_memory_inventory_candidates(memory_paths={"memory": memory})

    assert items == [] or "secret-value" not in json.dumps(items)
```

**Step 2: Run tests and verify failure**

```bash
$PY -m pytest tests/test_evidence_inventory_candidates.py -q
```

Expected: fail.

**Step 3: Implement memory collector**

Add `collect_memory_inventory_candidates(memory_paths, *, limit=20)`:

- Read built-in `MEMORY.md` / `USER.md` only when passed explicitly by config/runtime helper.
- Split entries by non-empty lines or existing section boundaries.
- Produce compact groups for:
  - exact duplicate
  - near duplicate by normalized token overlap
  - stale-looking implementation fact with newer contradictory sibling only if both are in memory text
  - target placement mismatch hints (`user` preference-like text in memory, environment fact-like text in user)
- Skip secret-looking lines entirely.
- Output candidate entries with `target`, `old_text`, `summary`, `hash`, not full file dumps.

**Step 4: Wire into evidence pack**

Add optional parameter to `build_evidence_pack(..., memory_paths=None)` and pass from `run_improve()` using config/Hermes home helper.

If memory paths are missing or inaccessible, emit no candidate and do not fail `improve`.

**Step 5: Verify tests**

```bash
$PY -m pytest tests/test_evidence_inventory_candidates.py tests/test_analysis_reclassification.py -q
```

Expected: pass.

**Step 6: Commit**

```bash
git add hermes_self_improvement/evidence.py hermes_self_improvement/cli.py tests/test_evidence_inventory_candidates.py
git commit -m "feat: collect memory inventory candidates"
```

---

## Task 5: Add LLM memory planner for inventory candidates

**Objective:** Convert memory inventory evidence into concrete memory tool operations with LLM judgment, then auto-apply when safe.

**Files:**

- Modify: `hermes_self_improvement/runner_steps.py`
- Modify: `hermes_self_improvement/prompts.py`
- Possibly create: `hermes_self_improvement/memory_planner.py` if keeping `runner_steps.py` small
- Test: `tests/test_memory_inventory_planner.py`

**Step 1: Write failing tests**

Use fake planner output and injected memory function; do not call real LLM or real memory tool:

```python
def test_memory_inventory_replace_operation_executes_with_specific_old_text(monkeypatch):
    evidence_pack = {
        "views": {"memory": ["mem-inv-1"]},
        "evidence": [{
            "id": "mem-inv-1",
            "kind": "memory_inventory_candidate",
            "inventory": {
                "group_kind": "semantic_duplicate",
                "entries": [
                    {"target": "memory", "old_text": "Hermes root is /opt/data", "summary": "old root"},
                    {"target": "memory", "old_text": "Hermes runtime root is ~/.hermes", "summary": "current root"},
                ],
            },
        }],
    }

    config = {
        "_memory_inventory_planner_fn": lambda evidence, config=None: [{
            "evidence_id": "mem-inv-1",
            "operation": "replace",
            "target": "memory",
            "old_text": "Hermes root is /opt/data",
            "content": "Hermes runtime root is ~/.hermes.",
            "reason": "replace stale runtime root fact",
        }],
        "_memory_tool_fn": fake_memory_success,
    }

    result = run_memory_improvement_step(evidence_pack=evidence_pack, config=config, mutate=True)

    assert result["changed"] == 1
    assert result["decisions"][0]["operation"]["operation"] == "replace"
```

Add hard-stop tests:

- remove without `old_text` is rejected
- secret-looking old text is rejected
- target not `memory|user` is rejected
- dry-run returns accepted preview but changed false

**Step 2: Run tests and verify failure**

```bash
$PY -m pytest tests/test_memory_inventory_planner.py -q
```

Expected: fail.

**Step 3: Implement memory inventory planner function**

Add function that accepts memory inventory evidence and returns normalized operations:

- Test path uses injected `_memory_inventory_planner_fn`.
- Runtime path calls Hermes auxiliary LLM using `model.planner` or `model.editor` consistently with existing code.
- Prompt asks for JSON operations only:
  - `add`, `replace`, `remove`
  - `target: memory|user`
  - `old_text` required for replace/remove
  - `content` required for add/replace
  - `reason`
  - `evidence_id`
- The LLM is expected to auto-apply safe cleanup; not to ask for user confirmation.

**Step 4: Normalize and hard-check operations**

Before using `build_memory_mutation_context()`:

- Drop operation if evidence_id is not attached.
- Drop remove/replace if `old_text` does not exactly match one of the candidate entry `old_text` values.
- Drop secret/PII-like text.
- Drop overly broad content.
- Convert accepted operation into the existing memory operation shape consumed by `build_memory_mutation_context()`.

**Step 5: Wire into `run_memory_improvement_step()`**

Current behavior still handles direct memory operation evidence. Extend it:

- Existing concrete memory operation evidence first.
- Then memory inventory evidence through LLM planner.
- Combine decisions in one memory step summary.
- No new CLI surface.

**Step 6: Verify tests**

```bash
$PY -m pytest tests/test_memory_inventory_planner.py tests/test_memory_mutation_policy.py tests/test_runner_steps.py -q
```

Expected: pass.

**Step 7: Commit**

```bash
git add hermes_self_improvement/runner_steps.py hermes_self_improvement/prompts.py hermes_self_improvement/memory_planner.py tests/test_memory_inventory_planner.py
git commit -m "feat: auto-apply memory inventory improvements"
```

---

## Task 6: Keep reporting compact but visible

**Objective:** Show that inventory candidates affected the run without dumping full inventory or prompts.

**Files:**

- Modify: `hermes_self_improvement/cli.py`
- Modify: `tests/test_cli_surface.py`
- Modify: `README.md` if needed

**Step 1: Write failing tests**

Update CLI/tool summary tests to expect compact counts:

```python
def test_improve_summary_includes_inventory_candidate_counts_without_full_payload():
    payload = fake_run_result_with_inventory_counts()
    text = _render_improve_summary(payload)

    assert "inventory" in text
    assert "skill" in text
    assert "memory" in text
    assert "full_content" not in text
    assert "candidate_prompt" not in text
```

**Step 2: Run tests and verify failure**

```bash
$PY -m pytest tests/test_cli_surface.py -q
```

Expected: fail.

**Step 3: Implement compact counts**

Include in run artifacts and summary:

- `inventory_candidates.skill_count`
- `inventory_candidates.memory_count`
- `inventory_candidates.auto_applied_count`
- `inventory_candidates.deferred_count`
- artifact path to full evidence pack

Do not include full candidate groups in agent-facing tool result.

**Step 4: Verify tests**

```bash
$PY -m pytest tests/test_cli_surface.py tests/test_plugin_tools.py -q
```

Expected: pass.

**Step 5: Commit**

```bash
git add hermes_self_improvement/cli.py tests/test_cli_surface.py README.md
git commit -m "feat: summarize inventory improvements compactly"
```

---

## Task 7: Dogfood with dry-run, then mutating run

**Objective:** Prove the new input path finds real inventory candidates and can auto-apply safe changes.

**Files:**

- Runtime artifacts under `~/.hermes/self-improvement/`
- Modify plan with observed proof if code changes reveal follow-up work

**Step 1: Static verification**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
git diff --check
```

Expected: all pass.

**Step 2: Dry-run proof**

```bash
bin/hermes-self-improve improve --dry-run --since-hours 24 --scorer llm
```

Inspect latest run artifact compactly:

```bash
python3 - <<'PY'
import json
from pathlib import Path
runs = sorted((Path.home()/'.hermes/self-improvement/runs').glob('run-*.json'))
p = runs[-1]
data = json.loads(p.read_text())
print(p)
print(json.dumps({
  'summary': data.get('summary'),
  'evidence_summary': (data.get('evidence_pack') or {}).get('summary'),
  'inventory': data.get('inventory_candidates'),
  'skill_changes': data.get('skill_changes'),
  'memory_changes': data.get('memory_changes'),
}, ensure_ascii=False, indent=2))
PY
```

Expected:

- evidence summary includes `skill_inventory_candidate` and/or `memory_inventory_candidate` when candidates exist.
- dry-run does not change skill/memory.
- planner/editor decisions are visible in artifact.

**Step 3: Mutating dogfood**

Only after dry-run looks sane:

```bash
bin/hermes-self-improve improve --since-hours 24 --scorer llm
```

Expected:

- Safe changes auto-apply without user confirmation.
- Unsafe candidates become `skip` / `defer` with reasons.
- Changes happen only through `skill_manage`, Curator archive primitive, or memory/provider tools.

**Step 4: Post-run verification**

```bash
bin/hermes-self-improve status
bin/hermes-self-improve report --since-hours 24
git status --short
```

Expected:

- Plugin status healthy.
- Report mentions inventory candidate counts compactly.
- If skill files changed through `skill_manage`, inspect diffs and commit if repo-tracked.
- Runtime artifacts are not committed.

**Step 5: Commit implementation docs if changed**

```bash
git add README.md .hermes/plans/README.md .hermes/plans/2026-05-07_095543-llm-inventory-candidates.md
git commit -m "docs: plan LLM inventory self-improvement"
```

---

## Acceptance criteria

- `improve` still has one primary flow; no new user-facing command or approval queue.
- Daily self-improvement evidence is no longer dominated only by tool failures when skill/memory inventory issues exist.
- Skill inventory candidates reach the existing skill planner/editor path.
- Memory inventory candidates reach an LLM-evaluated memory operation path and then existing memory tool execution.
- Auto-apply is the default for safe, bounded changes.
- Hard safety checks stop only dangerous or unsupported changes.
- Agent-facing outputs stay compact.
- Full test suite passes.

## Verification commands

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
bin/hermes-self-improve status
bin/hermes-self-improve improve --dry-run --since-hours 24 --scorer llm
git diff --check
```
