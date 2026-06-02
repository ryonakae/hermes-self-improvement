# LLM-led Memory Capacity Recovery Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task. This is a planning artifact only; do not implement production code until Ryo explicitly asks to proceed.

**Goal:** Make mutating memory placement runs recover from `memory_capacity_exceeded` by returning the capacity problem to the LLM Planner / Knowledge Editor for semantic judgment, while program code stays limited to bounded facts, hard safety guards, official tool execution, and verification.

**Architecture:** Keep `run_knowledge_improvement_step` as the single canonical improve flow. When a canonical `apply` memory transaction is blocked by destination capacity, the executor must record a structured capacity-blocked result and build a compact follow-up planning context; a later planner/editor pass decides whether to compact, replace, split, route to skill, defer, or keep current state. Program code must not choose which memory entry to remove/replace based on heuristics. Existing add-before-remove and stale-source checks remain mandatory.

**Tech Stack:** Python, pytest, Hermes built-in memory tool, existing `planner_runtime`, `prompts`, `runner_steps`, `knowledge_transactions`, and run artifact/report surfaces.

---

## Source artifact and current observed state

- Repo: `/Users/ryo.nakae/.hermes/plugins/hermes-self-improvement`
- Branch: `main`
- Baseline commit: `37f6c8a fix: canonicalize placement move decisions`
- Runtime was repaired non-destructively before the dogfood run: `hermes self-improvement setup --json` restored `runtime_setup.initialized=true` and prompt overlays ready.
- Dry-run source artifact:
  - `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260602T051854Z.json`
  - `dry_run=true`, `target_changed=false`
  - `action_summary`: `apply=6 / defer=15 / skip=71 / block=9`
  - final transaction contract: `noncanonical_decision_count=0`, `move_decision_count=0`, `route_leaks=[]`
- Mutating replay artifact:
  - `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260602T055107Z.json`
  - `dry_run=false`, `execute=true`, `target_changed=false`
  - `action_summary`: `apply=6 / defer=15 / skip=71 / block=9`
  - all six `placement_move` applies attempted `memory_add` into `builtin_memory` and blocked with `memory_capacity_exceeded`
  - `changed_memories=[]`, `removed_memories=[]`, source USER entries stayed intact
  - memory file hashes stayed unchanged after replay
- Normal mutating run artifact:
  - `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260602T055011Z.json`
  - `apply=0 / defer=19 / skip=91 / block=0`, no mutations

## Product judgment from dogfood

- Good:
  - Planner can identify plausible USER→MEMORY placement moves.
  - Executor preserves add-before-remove safety: destination add failed, source USER removal did not happen.
  - Final artifact vocabulary stayed canonical.
- Gap:
  - Capacity recovery is not yet LLM-led enough. The executor currently records `capacity_recovery` with `compaction_changed=0` and `fallback_reason=external_memory_provider_missing`, but it does not re-present the blocked move plus current memory inventory to an LLM for semantic resolution.
  - A human/Hermes would decide among compact/replace/split/skill/defer from the actual current entries. That judgment must belong to Planner / Knowledge Editor, not deterministic code.

---

## Non-goals / guardrails

- Do not add deterministic route heuristics such as `likely_*`, `suggested_route`, `route_reasons`, `allowed_recommendations`, `default_defer_by_route`, or `unhandled_by_route`.
- Do not let program code decide which memory to remove, replace, merge, split, or move based on token overlap or store labels.
- Do not loosen source validation: placement moves still add destination before removing source, and stale `source_old_text` blocks before any source removal.
- Do not edit built-in memory files directly. Use official memory tool / provider path only.
- Do not add approval queues, new user-facing lanes, confidence gates, or extra apply modes. Keep canonical decisions `apply / defer / skip / block`.
- Do not mutate skills/memory during `--dry-run`.
- Do not rely on runtime artifacts as test fixtures. Reduce artifact shapes into repo-local deterministic fixtures.

## Target behavior

When a mutating canonical memory transaction fails with `memory_capacity_exceeded`:

1. The current transaction result records a safe blocked outcome with compact structured diagnostics.
2. The run artifact exposes a bounded `capacity_blocked_transactions` / `memory_capacity_followups` section with:
   - blocked transaction id / kind / source id
   - source store, target store, exact `source_old_text` or bounded old_text
   - attempted destination content
   - current destination entries from the memory tool, bounded and with exact `old_text`
   - tool failure reason and usage (`2,131/2,200`-style budget when available)
   - allowed LLM decisions/templates: `memory_rewrite`, `duplicate_cleanup`, `placement_split`, `memory_to_skill`, `placement_move`, `skip`, `defer`, `block`
3. A follow-up planner/editor pass can decide one of:
   - replace/compact an existing same-store memory entry, then retry the original add
   - rewrite the source entry first and then move/keep
   - route procedural content to an existing skill via `memory_to_skill`
   - keep current store / skip because the move is not worth capacity pressure
   - defer with a concrete reason when exact safe text is unclear
4. Program code executes only the LLM-chosen canonical transaction(s), validates fields, and fails closed if underspecified.
5. Reports clearly distinguish:
   - selected but blocked by capacity
   - LLM follow-up selected and applied
   - LLM follow-up deferred/skipped
   - no partial mutation

---

## Implementation approach

Use a two-pass model, but keep it simple:

```text
planner emits canonical apply placement_move
  -> executor tries official memory add
  -> memory_capacity_exceeded
  -> executor records capacity-blocked follow-up context, no source remove
  -> same run may optionally call Planner/Knowledge Editor once with capacity follow-up context
  -> LLM emits canonical transactions
  -> executor applies those canonical transactions, then retries the blocked move only if the LLM explicitly requested retry semantics
```

The first implementation should prefer **artifact-visible follow-up context and replayable dry-run** over automatic same-run recursion if that is simpler. A same-run second planner pass is acceptable only if bounded to one pass and if tests prove no deterministic semantic decision sneaks in.

Recommended minimal first slice:

- record capacity-blocked context as first-class artifact data;
- render it in planner prompt as `Memory capacity blocked transactions`;
- feed those records into the **normal planning path** (`run_improve` / `build_planner_runtime_digest`) or add an explicit bounded replan entrypoint;
- keep `--from-run` replay as execution-only unless the implementation deliberately changes that contract with tests;
- only then consider one same-run LLM follow-up pass if needed.

Important architecture note from subagent review: current `--from-run` replay replays existing canonical transactions and does **not** re-invoke the Planner. Do not assume `--from-run` by itself can consume `digest["memory_capacity_followups"]`. Either wire capacity follow-ups into the next normal `improve` evidence/planner run, or add a separate explicit “replan from capacity artifact” path and test that the Planner actually runs.

---

## Task 1: Add RED fixture for capacity-blocked placement moves in canonical execution

**Objective:** Capture the dogfood failure shape as a deterministic unit/integration fixture.

**Files:**
- Modify: `tests/test_memory_to_skill_migration.py`
- Modify if better fit: `tests/test_runner_steps.py`
- Read: `hermes_self_improvement/runner_steps.py:691-761`
- Read: `hermes_self_improvement/runner_steps.py:1726-1799`
- Read: `hermes_self_improvement/runner_steps.py:2258-2274`

**Step 1: Write failing test for capacity-blocked placement move accounting**

Add a test using a fake memory tool:

```python
def test_knowledge_step_records_capacity_blocked_placement_move_followup(monkeypatch, tmp_path):
    calls = []

    def fake_memory(**args):
        calls.append(args)
        if args.get("action") == "add" and args.get("target") == "memory":
            return {
                "success": False,
                "error": "memory_capacity_exceeded",
                "usage": "2,131/2,200",
                "current_entries": [
                    {"target": "memory", "old_text": "Old durable runtime fact.", "summary": "runtime fact"},
                    {"target": "memory", "old_text": "Obsolete duplicate detail.", "summary": "duplicate"},
                ],
            }
        return {"success": True, "changed": True}

    # Planner emits the same canonical shape as run-20260602T051854Z.
    config = {
        "_planner_runtime_func": lambda digest, config=None: {
            "status": "completed",
            "knowledge_transactions": [{
                "decision": "apply",
                "transaction_kind": "placement_move",
                "operation": "move",
                "source_store": "builtin_user",
                "target_store": "builtin_memory",
                "source_id": "memory_place_capacity",
                "source_old_text": "Project convention belongs in MEMORY.",
                "content": "Project convention belongs in MEMORY.",
                "reason": "project_convention_belongs_in_memory",
            }],
        },
        "_memory_tool_fn": fake_memory,
        "_memory_current_entries": [
            {"target": "user", "old_text": "Project convention belongs in MEMORY."},
            {"target": "memory", "old_text": "Old durable runtime fact."},
            {"target": "memory", "old_text": "Obsolete duplicate detail."},
        ],
    }

    result = run_knowledge_improvement_step(
        evidence_pack={"evidence": []},
        config=config,
        mutate=True,
    )

    assert result["changed_memories"] == []
    tx = result["knowledge_transactions"][0]
    assert tx["transaction_result"]["outcome"] == "blocked"
    assert tx["transaction_result"]["reason"] == "memory_capacity_exceeded"
    assert result["memory_capacity_followups"]["blocked_count"] == 1
    assert result["memory_capacity_followups"]["items"][0]["source_id"] == "memory_place_capacity"
    assert calls == [{"action": "add", "target": "memory", "content": "Project convention belongs in MEMORY."}]
```

Adjust helper names to actual project style. Expected RED: `memory_capacity_followups` key does not exist yet.

**Step 2: Run RED**

```bash
.venv/bin/python -m pytest tests/test_runner_steps.py::test_knowledge_step_records_capacity_blocked_placement_move_followup -q
```

Expected: fails on missing follow-up summary.

---

## Task 2: Build bounded capacity follow-up records without semantic choices

**Objective:** Add a pure data-shaping helper that turns blocked memory transaction results into LLM-ready facts, without deciding what to remove/replace.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Test: `tests/test_runner_steps.py` or `tests/test_memory_to_skill_migration.py`

**Step 1: Add helper**

Add a helper near `_knowledge_transaction_result_summary`:

```python
def build_memory_capacity_followups(transactions: list[dict[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for tx in transactions:
        if not isinstance(tx, dict):
            continue
        result = tx.get("transaction_result") if isinstance(tx.get("transaction_result"), dict) else {}
        if result.get("reason") != "memory_capacity_exceeded" and result.get("error") != "memory_capacity_exceeded":
            continue
        add_result = result.get("add_result") if isinstance(result.get("add_result"), dict) else result
        memory_result = add_result.get("memory_result") if isinstance(add_result.get("memory_result"), dict) else {}
        current_entries = []
        for entry in memory_result.get("current_entries") or []:
            if isinstance(entry, str):
                current_entries.append({"old_text": entry[:500], "target": tx.get("target_store")})
            elif isinstance(entry, dict):
                old_text = str(entry.get("old_text") or entry.get("content") or "")
                if old_text:
                    current_entries.append({
                        "target": str(entry.get("target") or tx.get("target_store") or ""),
                        "old_text": old_text[:500],
                        "summary": str(entry.get("summary") or "")[:180],
                    })
        items.append({
            "transaction_id": str(tx.get("transaction_id") or ""),
            "transaction_kind": str(tx.get("transaction_kind") or ""),
            "source_id": str(tx.get("source_id") or tx.get("source_evidence_id") or ""),
            "source_store": str(tx.get("source_store") or ""),
            "target_store": str(tx.get("target_store") or ""),
            "operation": str(tx.get("operation") or ""),
            "source_old_text": str(tx.get("source_old_text") or "")[:500],
            "attempted_content": str(tx.get("content") or tx.get("source_old_text") or "")[:500],
            "failure_reason": "memory_capacity_exceeded",
            "usage": str(memory_result.get("usage") or add_result.get("usage") or ""),
            "current_entries": current_entries[:12],
            "allowed_followup_decisions": ["apply", "defer", "skip", "block"],
            "allowed_transaction_kinds": ["memory_rewrite", "duplicate_cleanup", "placement_split", "memory_to_skill", "placement_move", "keep_same_topic_different_store"],
            "program_notes": "Facts only. LLM must decide compact/replace/split/skill/defer/skip. Program must not choose an entry to remove.",
        })
    return {"blocked_count": len(items), "items": items}
```

Keep names/shape project-consistent if an existing summary convention is better. Do not include route labels or program-generated recommendations.

**Step 2: Wire into `run_knowledge_improvement_step` return**

After transaction execution, include:

```python
capacity_followups = build_memory_capacity_followups(transactions)
...
"memory_capacity_followups": capacity_followups,
```

**Step 3: Verify focused test**

```bash
.venv/bin/python -m pytest tests/test_runner_steps.py::test_knowledge_step_records_capacity_blocked_placement_move_followup -q
```

Expected: pass.

---

## Task 3: Render capacity follow-ups in the Planner prompt as facts, not recommendations

**Objective:** Give the Planner enough context to make semantic capacity decisions on replay/next run.

**Files:**
- Modify: `hermes_self_improvement/prompts.py`
- Modify if digest needs field propagation: `hermes_self_improvement/planner_runtime.py`
- Test: `tests/test_skill_planner.py`

**Step 1: Add prompt section renderer**

Add a function near `_render_memory_placement_candidates_section`:

```python
def _render_memory_capacity_followups_section(digest: dict[str, Any]) -> str:
    raw = digest.get("memory_capacity_followups")
    followups = raw if isinstance(raw, dict) else {}
    items = [item for item in followups.get("items") or [] if isinstance(item, dict)]
    if not items:
        return "## Memory capacity blocked transactions\n- n/a\n"
    lines = [
        "## Memory capacity blocked transactions",
        "These are failed official memory-tool attempts from prior execution. They are facts, not recommendations. The Planner must decide semantics: compact/replace existing memory, split source text, route procedural content to skill, keep current store, defer, or block. Program code must not choose which memory to remove.",
        "Only emit canonical knowledge_transactions with decision apply/defer/skip/block. Use exact old_text for replace/remove. If exact safe text is unclear, defer.",
    ]
    for item in items[:10]:
        lines.append(
            f"- blocked_transaction_id={_clip(item.get('transaction_id'), max_chars=80)}; source_id={_clip(item.get('source_id'), max_chars=80)}; source_store={_clip(item.get('source_store'), max_chars=40)}; target_store={_clip(item.get('target_store'), max_chars=40)}; failure={_clip(item.get('failure_reason'), max_chars=80)}; usage={_clip(item.get('usage'), max_chars=40)}; attempted_content={_clip(item.get('attempted_content'), max_chars=260)}"
        )
        for entry in (item.get("current_entries") or [])[:8]:
            if isinstance(entry, dict):
                lines.append(f"  - current_destination_entry target={_clip(entry.get('target'), max_chars=40)}; old_text={_clip(entry.get('old_text'), max_chars=220)}")
        lines.append("  - examples: memory_rewrite, duplicate_cleanup, placement_split, memory_to_skill, skip keep_current_store, defer capacity_resolution_unclear")
    return "\n".join(lines).rstrip() + "\n"
```

Add this section into `render_planner_messages(...)` before semantic knowledge rules or immediately after memory placement candidates.

**Step 2: Add RED/PASS test**

In `tests/test_skill_planner.py`:

```python
def test_render_planner_messages_capacity_followups_are_facts_not_routes():
    digest = build_planner_digest(pack())
    digest["memory_capacity_followups"] = {
        "blocked_count": 1,
        "items": [{
            "transaction_id": "kt-capacity",
            "source_id": "memory_place_capacity",
            "source_store": "builtin_user",
            "target_store": "builtin_memory",
            "failure_reason": "memory_capacity_exceeded",
            "usage": "2,131/2,200",
            "attempted_content": "Project convention belongs in MEMORY.",
            "current_entries": [{"target": "memory", "old_text": "Old durable runtime fact."}],
        }],
    }

    content = render_planner_messages(digest=digest)["messages"][1]["content"]

    assert "## Memory capacity blocked transactions" in content
    assert "memory_capacity_exceeded" in content
    assert "Project convention belongs in MEMORY" in content
    assert "Old durable runtime fact" in content
    assert "facts, not recommendations" in content
    for forbidden in ("suggested_route", "likely_", "route_reasons", "allowed_recommendations"):
        assert forbidden not in content
```

**Step 3: Run focused test**

```bash
.venv/bin/python -m pytest tests/test_skill_planner.py::test_render_planner_messages_capacity_followups_are_facts_not_routes -q
```

Expected: pass.

---

## Task 4: Feed capacity follow-ups into the normal planner digest, not plain replay

**Objective:** Make a blocked mutating run actionable in a later Planner run without requiring runtime-specific manual inspection. Plain `--from-run` replay currently executes existing transactions and does not replan, so this task must target the normal `run_improve` evidence/planner path or introduce an explicit replan mode.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/planner_runtime.py`
- Test: `tests/test_plugin_tools.py` or a CLI/improve runner test if available

**Current code contract:** `hermes self-improvement improve --from-run <artifact>` exists, but it is replay-oriented. Treat it as a source of prior artifact facts, not as the automatic LLM replan mechanism. The new follow-up records should become available to `build_planner_runtime_digest(...)` only through a path that actually calls the Planner.

**Step 1: Locate the actual planner entry and replay boundary**

Search/inspect:

```bash
rg "from_run|from-run|run_replay_improve|run_improve|build_planner_runtime_digest|run_knowledge_improvement_step" hermes_self_improvement/cli.py hermes_self_improvement/*.py
```

Confirm which path calls the Planner and which path only replays transactions. The implementation must not rely on replay-only code to perform LLM judgment.

**Step 2: Add deterministic artifact extraction helper**

Add a helper in the appropriate module, likely `cli.py` or `planner_runtime.py`:

```python
def extract_memory_capacity_followups_from_run(run: dict[str, Any]) -> dict[str, Any]:
    existing = run.get("memory_capacity_followups")
    if isinstance(existing, dict) and existing.get("items"):
        return existing
    transactions = [item for item in run.get("knowledge_transactions") or [] if isinstance(item, dict)]
    return build_memory_capacity_followups(transactions)
```

If importing from `runner_steps.py` would create a cycle, move the pure helper into a small neutral module such as `knowledge_transactions.py` or a new `capacity_followups.py`. Keep it pure and unit-tested.

**Step 3: Attach to the normal planner digest**

In `build_planner_runtime_digest(...)`, preserve a precomputed field when available in `evidence_pack`, e.g.:

```python
"memory_capacity_followups": evidence_pack.get("memory_capacity_followups") if isinstance(evidence_pack.get("memory_capacity_followups"), dict) else {"blocked_count": 0, "items": []},
```

Attach extracted followups to the evidence pack or config used by the normal Planner run. If an explicit replan-from-artifact command/flag is added, it must call Planner with the extracted followups and must not execute the old artifact’s transactions blindly.

**Step 4: Add test**

Test both sides of the boundary:

- a normal Planner run with injected prior capacity followups yields a planner prompt containing the capacity section and current entries;
- plain `--from-run` replay remains replay-only unless an explicit replan mode is requested.

**Step 5: Verify**

```bash
.venv/bin/python -m pytest tests/test_skill_planner.py tests/test_plugin_tools.py -q
```

Expected: existing tests plus new replay-handoff test pass.

---

## Task 5: Let LLM-selected capacity resolutions execute through existing canonical transactions

**Objective:** Avoid adding special capacity-executor semantics; execute only the canonical transactions the LLM emits from a path that actually invoked the Planner. Do not assume replay-only artifacts can invent these transactions.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py` only if existing canonical executors need small field support
- Tests: `tests/test_memory_to_skill_migration.py`, `tests/test_runner_steps.py`

**Allowed LLM outputs:**

- `memory_rewrite` with `operation=replace`, exact `source_old_text`, `replacement_content`
- `duplicate_cleanup` with `operation=remove`, exact `source_old_text` / related ids
- `placement_split` with exact `destination_content` and `source_replacement`
- `memory_to_skill` with `target_skill` and executable `skill_task` / `editor_task`
- `placement_move` retry only after the LLM has created enough capacity through an earlier canonical transaction in the same planner output / explicit replan output
- `skip` / `defer` / `block`

**Step 1: Add test for LLM-chosen memory rewrite before retry**

Create a test where planner emits two apply transactions:

1. `memory_rewrite` replacing a destination memory entry with a shorter compact version.
2. `placement_move` retrying the previously blocked USER→MEMORY move.

Fake memory tool behavior:

- `replace` succeeds and flips an internal `capacity_available=True`.
- subsequent `add` succeeds only after replacement.
- `remove` source USER succeeds after add.

Expected:

```python
assert result["changed_memories"]
assert calls == [
    {"action": "replace", "target": "memory", "old_text": "Old long entry", "content": "Old compact entry"},
    {"action": "add", "target": "memory", "content": "Project convention belongs in MEMORY."},
    {"action": "remove", "target": "user", "old_text": "Project convention belongs in MEMORY."},
]
```

This test proves sequencing works through canonical transactions, not special hidden recovery logic.

**Step 2: Add test for underspecified LLM resolution fail-closed**

If LLM emits `memory_rewrite` without exact `source_old_text` or `replacement_content`, assert:

```python
assert tx["transaction_result"]["outcome"] == "blocked"
assert tx["transaction_result"]["reason"] in {"knowledge_transaction_missing_required_fields", "memory_rewrite_missing_exact_text"}
assert memory_tool_calls == []
```

**Step 3: Implement only small missing support**

If existing executors already support these transaction kinds, do not add new executor paths. If they are missing exact field aliases from prompt templates, add field normalization in `normalize_knowledge_transaction(...)` or the specific executor and cover with tests.

---

## Task 6: Remove or quarantine old injected `_memory_capacity_planner_fn` recovery from active production path

**Objective:** Ensure old programmatic capacity recovery cannot become the semantic decision-maker.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py:665-688` and `691-761`
- Tests: `tests/test_memory_inventory_planner.py`, `tests/test_runner_steps.py`

**Current code:**

`_capacity_compaction_operations(...)` has a compatibility hook `_memory_capacity_planner_fn`. It is acceptable for old unit tests, but production must not use it as a hidden semantic planner.

**Step 1: Add guard test**

```python
def test_capacity_recovery_does_not_call_programmatic_planner_without_test_injection():
    called = False
    def forbidden(**kwargs):
        nonlocal called
        called = True
        return [{"action": "remove", "target": "memory", "old_text": "some entry"}]

    config = {"_memory_capacity_planner_fn": forbidden, "_allow_test_capacity_planner": False}
    # Execute blocked add path.
    ...
    assert called is False
```

If existing tests depend on injection, require an explicit test-only flag such as `_allow_test_capacity_planner=True` or move those tests to the new LLM-followup fixture.

**Step 2: Production behavior**

In `_capacity_compaction_operations(...)`:

```python
if not config.get("_allow_test_capacity_planner"):
    return []
```

or delete the hook after migrating tests. Prefer deletion if tests can be updated cleanly.

**Step 3: Update old tests**

Tests such as `test_memory_inventory_move_compacts_destination_before_removing_source` and `test_memory_capacity_recovery_records_placement_options_and_uses_fallback_after_compaction` currently encode program-provided compaction operations. Update them to either:

- mark as legacy compatibility with explicit `_allow_test_capacity_planner=True`, or
- replace with canonical LLM-output transaction tests from Task 5.

**Step 4: Verify no hidden route terms**

```bash
rg "_memory_capacity_planner_fn|capacity_planner|suggested_route|likely_|route_reasons|allowed_recommendations" hermes_self_improvement tests
```

Expected:

- `_memory_capacity_planner_fn` appears only in quarantined legacy tests or is gone.
- forbidden route terms are absent from active production/prompt surfaces except explicit negative tests.

---

## Task 7: Update compact summaries and reports for capacity-blocked vs resolved outcomes

**Objective:** Make dogfood reports answer “what actually happened?” without opening huge JSON.

**Files:**
- Modify: `hermes_self_improvement/tool_handlers.py`
- Modify: `hermes_self_improvement/cli.py`
- Modify report renderer if separate
- Tests: `tests/test_plugin_tools.py`, `tests/test_report_improve_connection.py`

**Desired summary language:**

- `capacity blocked: 6 placement moves, 0 partial removals`
- `capacity follow-up: deferred/skipped/applied counts`
- `memory changed: 0` when add-before-remove blocked all changes
- `partial: 0` when no source deletion happened

**Step 1: Add compact payload fields**

In compact improve result, include bounded counts only:

```json
"memory_capacity": {
  "blocked": 6,
  "followup_items": 6,
  "resolved": 0,
  "partial": 0
}
```

Do not include full memory entries in tool result. Full entries stay in the run artifact.

**Step 2: Add test**

Use a small in-memory raw result with capacity followups. Assert compact output has counts and does not include full `current_entries` text.

**Step 3: Verify**

```bash
.venv/bin/python -m pytest tests/test_plugin_tools.py tests/test_report_improve_connection.py -q
```

---

## Task 8: Dogfood sequence with safety checks

**Objective:** Prove the plugin can make an LLM-led capacity decision or explicitly defer, without partial mutation or heuristic routing.

**Step 1: Preflight**

```bash
git status --short
hermes self-improvement status --json > /tmp/hermes-si-status-capacity.json
shasum -a 256 ~/.hermes/memories/USER.md ~/.hermes/memories/MEMORY.md > /tmp/hermes-si-memory-hashes-before.txt
```

Expected:

- repo clean or only intended changes
- runtime initialized true
- prompt overlays ready

**Step 2: Planner dry-run with blocked artifact facts**

Use the new normal-planner or explicit replan path from Task 4. Do **not** use plain `--from-run` unless Task 4 deliberately changed it to call the Planner under an explicit replan mode.

```bash
hermes self-improvement improve <new-explicit-capacity-replan-args-or-normal-run-injection> --dry-run --json > /tmp/hermes-si-capacity-followup-dry-run.json
```

Inspect:

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path
p = Path('/tmp/hermes-si-capacity-followup-dry-run.json')
data = json.loads(p.read_text())
text = json.dumps(data, ensure_ascii=False)
transactions = data.get('knowledge_transactions') or []
print(json.dumps({
    'run_id': data.get('run_id'),
    'action_summary': data.get('action_summary'),
    'capacity_followups': data.get('memory_capacity_followups', {}).get('blocked_count'),
    'apply_kinds': [t.get('transaction_kind') for t in transactions if t.get('decision') == 'apply'],
    'noncanonical': sum(1 for t in transactions if t.get('decision') not in {'apply','defer','skip','block'}),
    'route_leaks': [n for n in ['suggested_route','route_reasons','likely_','allowed_recommendations','default_defer_by_route','unhandled_by_route'] if n in text],
}, ensure_ascii=False, indent=2))
PY
```

Pass criteria:

- `noncanonical=0`
- `route_leaks=[]`
- Planner either chooses a specific canonical resolution with exact text or defers with a concrete reason.
- No dry-run mutation.

**Step 3: Mutating run only if the Planner dry-run is bounded**

Only run mutation if the Planner dry-run contains exact fields for every `apply` and no suspicious broad remove. If bounded, run the corresponding mutating path that reuses the approved planner output or re-plans deterministically enough to preserve the same bounded decisions:

```bash
hermes self-improvement improve <same-explicit-capacity-replan-args-or-approved-artifact-path> --json > /tmp/hermes-si-capacity-followup-mutation.json
```

Inspect hashes and artifact:

```bash
shasum -a 256 ~/.hermes/memories/USER.md ~/.hermes/memories/MEMORY.md > /tmp/hermes-si-memory-hashes-after.txt
diff -u /tmp/hermes-si-memory-hashes-before.txt /tmp/hermes-si-memory-hashes-after.txt || true
```

Pass criteria:

- Any changes are recorded in `memory_changes` / `changed_memories` / `removed_memories`.
- No partial source removal without successful destination add or validated skill patch.
- Capacity-blocked results are counted as blocked/partial honestly.

---

## Task 9: Full validation and docs update

**Objective:** Close the plan with verified code, updated source of truth, and no stale active-plan pointer.

**Files:**
- Modify: `.hermes/plans/README.md`
- Modify: this plan file
- Modify if needed: `README.md` / `skills/operations/SKILL.md` only if user-facing operations changed

**Step 1: Full validation**

```bash
.venv/bin/python -m py_compile __init__.py hermes_self_improvement/*.py
.venv/bin/python -m pytest tests -q
git diff --check
hermes self-improvement status --json
```

Expected:

- py_compile ok
- full pytest passes
- diff check ok
- runtime status readable and initialized, or repaired with non-reset `hermes self-improvement setup --json` and rechecked

**Step 2: Update this plan**

Add completion note with:

- final commit SHA
- tests run
- dry-run artifact path
- mutating artifact path if run
- memory hash before/after result
- capacity follow-up counts
- whether the LLM applied, deferred, or skipped

**Step 3: Update plan index**

At top of `.hermes/plans/README.md`, change this plan from active to latest completed follow-up when implemented.

**Step 4: Commit**

```bash
git status --short
git add hermes_self_improvement/runner_steps.py hermes_self_improvement/planner_runtime.py hermes_self_improvement/prompts.py hermes_self_improvement/tool_handlers.py hermes_self_improvement/cli.py tests/test_runner_steps.py tests/test_memory_to_skill_migration.py tests/test_skill_planner.py tests/test_plugin_tools.py tests/test_report_improve_connection.py .hermes/plans/README.md .hermes/plans/2026-06-02-llm-led-memory-capacity-recovery.md
git commit -m "fix: route memory capacity recovery through planner"
```

Do not push unless Ryo asks.

---

## Completion criteria

This plan is complete only when all of the following are true:

- Capacity-blocked memory transactions produce compact artifact follow-up records.
- Planner prompt receives capacity-blocked context as facts, with current entries and exact old_text.
- No active production code chooses memory compaction/removal/replacement semantically without LLM output.
- Canonical transaction execution handles LLM-selected capacity resolutions through existing transaction kinds.
- Add-before-remove and stale-source safety are preserved.
- Compact summaries distinguish blocked capacity, resolved capacity, partial outcomes, and actual memory changes.
- Dogfood from the blocked artifact proves either safe LLM-led mutation or explicit LLM defer/skip.
- Full test suite passes and plan index is updated.

## Recommended next-session start

1. Open this plan and artifact `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260602T055107Z.json`.
2. Start with Task 1/2 only: artifact-shaped capacity follow-up records.
3. Do not implement same-run second planner pass until after artifact-visible follow-up and replay path are proven.
4. If in doubt, defer rather than adding deterministic capacity heuristics.
