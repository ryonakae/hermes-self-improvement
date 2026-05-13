# Compact Self-Improvement Tool Results Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** `self_improvement_improve` / `self_improvement_calibrate` の agent tool 戻り値を短い summary + artifact pointer に寄せ、LLM が巨大 run payload をそのまま読む経路を塞ぐ。

**Architecture:** CLI は現状維持する。通常 CLI は短い human summary、`--json` は operator/debug 用の full payload のまま。Agent tool surface だけを compact response に変換し、詳細は既存の runtime artifact に保存された JSON を必要時に読む設計にする。`run_improve()` の内部 artifact と TDD fixture は保ち、tool handler 層で LLM-facing shape を制御する。

**Tech Stack:** Python, pytest, Hermes plugin tool handlers, existing runtime artifact under `${HERMES_HOME:-~/.hermes}/self-improvement/`.

---

## Current context

- `hermes self-improvement improve --dry-run` の通常出力は `_render_improve_summary()` 経由で短い。
- `hermes self-improvement improve --dry-run --json` は `run_improve()` の full payload を出すため長い。これは operator/debug 用として残す。
- `self_improvement_improve` tool は現在 `tool_result(run_improve(...))` をそのまま返す。つまり agent が tool を呼ぶと full payload が LLM context に入る。
- 今回の実測では通常出力は `609 chars / 23 lines`、`--json` は `45,859 chars / 1,115 lines`。
- `run_improve()` はすでに `artifact_path` を書くので、LLM-facing tool result は詳細を持たず artifact path に誘導できる。

## Non-goals

- `run_improve()` の full result shape を壊さない。
- CLI `--json` を短くしない。人間/CI/debug が full payload を取る escape hatch として残す。
- primary surface を増やさない。`status / report / improve / calibrate` の4 tool を維持する。
- token budget manager や汎用 truncation framework は作らない。まずはこの plugin tool の戻り値だけを明示的に compact 化する。
- skill / memory / scorer / evaluator の mutation semantics は変えない。

## Proposed response contract

### `self_improvement_improve` compact tool result

返す top-level は以下を基本にする。

```json
{
  "schema_name": "self_improvement_tool_result_summary",
  "schema_version": "1.0",
  "operation": "improve",
  "dry_run": true,
  "execute": false,
  "target_changed": false,
  "artifact_path": "/.../self-improvement/runs/run-....json",
  "summary": {
    "skill_changes": 0,
    "memory_changes": 0,
    "scorer_evaluator_changed": false
  },
  "curator_telemetry": {
    "available": true,
    "candidate_count": 9,
    "rejected_count": 0
  },
  "evidence": {
    "path": "/.../self-improvement/evidence/evidence-....json",
    "event_count": 771,
    "evidence_count": 16,
    "ignored_count": 755,
    "views": {
      "skill": 12,
      "memory": 4,
      "scorer": 3,
      "evaluator": 1
    },
    "skill_candidate_count": 9
  },
  "steps": {
    "proposals_considered": 5,
    "skill": {"status": "completed", "changed": 0, "decision_count": 9},
    "memory": {"status": "completed", "changed": 0, "decision_count": 4, "related_lookups": {"completed": 0, "unavailable": 0, "failed": 0, "skipped": 0}},
    "scorer": {"status": "calibration_only", "changed": 0},
    "evaluator": {"status": "calibration_only", "changed": 0}
  },
  "next_actions": [
    {"kind": "run_mutating_improve", "command": "hermes self-improvement improve", "description": "Run self-improvement with mutation enabled by default."}
  ],
  "full_payload": {
    "available": true,
    "read_with": "read_file",
    "path": "/.../self-improvement/runs/run-....json"
  }
}
```

重要: `step_decisions.proposals_considered` や `skill.decisions[].task.instructions` のような大きい中身は tool result に含めない。

### `self_improvement_calibrate` compact tool result

`calibrate` は今の payload が将来 GEPA / eval cases / ledgers で膨らむ可能性があるので、同じ設計で compact 化する。

```json
{
  "schema_name": "self_improvement_tool_result_summary",
  "schema_version": "1.0",
  "operation": "calibrate",
  "dry_run": true,
  "target_changed": false,
  "current_status": "...",
  "active_changed": false,
  "evidence_summary": {"total_events": 0, "disagreements": 0, "bad_outcomes": 0, "scorer_errors": 0},
  "regression": {"status": "..."},
  "active_evaluator_path": "...",
  "ledger_path": "...",
  "full_payload": {"available": false, "reason": "calibration currently does not always write a run artifact"}
}
```

もし `run_calibration()` が ledger/artifact path を返しているならそれを `full_payload.path` に使う。返していないならこの task では新規 artifact 化しない。まず tool result の compact 化に閉じる。

## Files likely to change

- Modify: `hermes_self_improvement/tool_handlers.py`
- Modify: `tests/test_plugin_tools.py`
- Maybe modify: `README.md`
- Maybe modify: `skills/operations/SKILL.md` if operational command guidance should mention compact tool results. This is plugin-bundled repo fileなので直接編集可。

## Task 1: Add tests for compact `self_improvement_improve` tool result

**Objective:** `self_improvement_improve` tool が full run payload を返さず、summary と artifact pointer だけを返す契約を先に固定する。

**Files:**
- Modify: `tests/test_plugin_tools.py`

**Step 1: Add failing test**

Add a test near `test_improve_tool_uses_core_loop_with_dry_run`.

```python
def test_improve_tool_returns_compact_llm_facing_summary(monkeypatch, tmp_path):
    mod = load_plugin_module()
    artifact = tmp_path / "self-improvement" / "runs" / "run.json"
    evidence = tmp_path / "self-improvement" / "evidence" / "evidence.json"

    large_instruction = "x" * 20000

    def fake_run_improve(**kwargs):
        return {
            "schema_name": "self_improvement_run_result",
            "schema_version": "1.0",
            "run_id": "run-test",
            "dry_run": kwargs["dry_run"],
            "execute": not kwargs["dry_run"],
            "target_changed": False,
            "artifact_path": str(artifact),
            "summary": {"skill_changes": 0, "memory_changes": 0, "scorer_evaluator_changed": False, "dry_run": kwargs["dry_run"]},
            "curator_telemetry": {"available": True, "candidate_count": 2, "rejected_count": 1, "reasons": ["ok"]},
            "evidence_pack": {
                "path": str(evidence),
                "summary": {"event_count": 10, "evidence_count": 3, "ignored_count": 7},
                "views": {"skill": ["ev1", "ev2"], "memory": ["ev3"], "scorer": [], "evaluator": []},
                "skill_candidates": [{"name": "a"}, {"name": "b"}],
            },
            "step_decisions": {
                "summary": {"total": 4, "skill": 2, "memory": 1, "scorer": 1, "evaluator": 0, "out_of_scope": 0},
                "proposals_considered": [{"id": "p1", "details": large_instruction}],
                "skill": {"status": "completed", "changed": 0, "changed_skills": [], "decisions": [{"task": {"instructions": large_instruction}}]},
                "memory": {"status": "completed", "changed": 0, "changed_memories": [], "decisions": [{"related_memory_lookup": {"status": "completed"}}]},
                "scorer": {"status": "calibration_only", "changed": 0},
                "evaluator": {"status": "calibration_only", "changed": 0},
            },
            "next_actions": [{"kind": "run_mutating_improve", "command": "hermes self-improvement improve"}],
        }

    mod._handle_self_improvement_improve_tool.__globals__["run_improve"] = fake_run_improve

    raw = mod._handle_self_improvement_improve_tool({"dry_run": True, "config": {"_self_improvement_root": str(tmp_path / "self-improvement")}})
    payload = parse_tool_payload(raw)

    assert payload["schema_name"] == "self_improvement_tool_result_summary"
    assert payload["operation"] == "improve"
    assert payload["dry_run"] is True
    assert payload["artifact_path"] == str(artifact)
    assert payload["full_payload"]["path"] == str(artifact)
    assert payload["evidence"]["views"] == {"skill": 2, "memory": 1, "scorer": 0, "evaluator": 0}
    assert payload["steps"]["proposals_considered"] == 4
    assert payload["steps"]["skill"]["decision_count"] == 1
    assert payload["steps"]["memory"]["related_lookups"]["completed"] == 1
    assert "proposals_considered" not in payload
    assert large_instruction not in raw
    assert len(raw) < 6000
```

**Step 2: Run focused test to verify failure**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_plugin_tools.py::test_improve_tool_returns_compact_llm_facing_summary -q
```

Expected: FAIL because the handler still returns full `self_improvement_run_result`.

## Task 2: Implement compact summary helper for improve

**Objective:** Add a small pure helper that converts `run_improve()` full result into an LLM-facing compact payload.

**Files:**
- Modify: `hermes_self_improvement/tool_handlers.py`

**Step 1: Add helper functions**

Add below `_coerce_int()`.

```python
def _list_count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _count_views(raw: Any) -> dict[str, int]:
    views = raw if isinstance(raw, dict) else {}
    return {name: _list_count(views.get(name)) for name in ("skill", "memory", "scorer", "evaluator")}


def _related_lookup_counts(memory_step: dict[str, Any]) -> dict[str, int]:
    counts = {"completed": 0, "unavailable": 0, "failed": 0, "skipped": 0}
    for decision in memory_step.get("decisions") or []:
        if not isinstance(decision, dict):
            continue
        lookup = decision.get("related_memory_lookup") if isinstance(decision.get("related_memory_lookup"), dict) else {}
        status = str(lookup.get("status") or "")
        if status in counts:
            counts[status] += 1
    return counts


def _compact_step(name: str, step: Any) -> dict[str, Any]:
    data = step if isinstance(step, dict) else {}
    out = {
        "status": data.get("status") or "unknown",
        "changed": int(data.get("changed") or 0),
        "decision_count": _list_count(data.get("decisions")),
    }
    if name == "memory":
        out["related_lookups"] = _related_lookup_counts(data)
    return out


def _compact_improve_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    evidence_pack = result.get("evidence_pack") if isinstance(result.get("evidence_pack"), dict) else {}
    evidence_summary = evidence_pack.get("summary") if isinstance(evidence_pack.get("summary"), dict) else {}
    step_decisions = result.get("step_decisions") if isinstance(result.get("step_decisions"), dict) else {}
    decision_summary = step_decisions.get("summary") if isinstance(step_decisions.get("summary"), dict) else {}
    curator = result.get("curator_telemetry") if isinstance(result.get("curator_telemetry"), dict) else {}
    artifact_path = result.get("artifact_path")

    return {
        "schema_name": "self_improvement_tool_result_summary",
        "schema_version": "1.0",
        "operation": "improve",
        "dry_run": bool(result.get("dry_run")),
        "execute": bool(result.get("execute")),
        "target_changed": bool(result.get("target_changed")),
        "artifact_path": artifact_path,
        "summary": result.get("summary") if isinstance(result.get("summary"), dict) else {},
        "curator_telemetry": {
            "available": bool(curator.get("available")),
            "candidate_count": int(curator.get("candidate_count") or 0),
            "rejected_count": int(curator.get("rejected_count") or 0),
        },
        "evidence": {
            "path": evidence_pack.get("path"),
            "event_count": int(evidence_summary.get("event_count") or 0),
            "evidence_count": int(evidence_summary.get("evidence_count") or 0),
            "ignored_count": int(evidence_summary.get("ignored_count") or 0),
            "views": _count_views(evidence_pack.get("views")),
            "skill_candidate_count": _list_count(evidence_pack.get("skill_candidates")),
        },
        "steps": {
            "proposals_considered": int(decision_summary.get("total") or 0),
            "skill": _compact_step("skill", step_decisions.get("skill")),
            "memory": _compact_step("memory", step_decisions.get("memory")),
            "scorer": _compact_step("scorer", step_decisions.get("scorer")),
            "evaluator": _compact_step("evaluator", step_decisions.get("evaluator")),
        },
        "next_actions": result.get("next_actions") if isinstance(result.get("next_actions"), list) else [],
        "full_payload": {
            "available": bool(artifact_path),
            "read_with": "read_file" if artifact_path else None,
            "path": artifact_path,
        },
    }
```

**Step 2: Use helper in improve tool handler**

Change `_handle_self_improvement_improve_tool` from returning `run_improve(...)` directly to:

```python
result = run_improve(
    config=_config_from_args(args),
    since_hours=_coerce_int(args.get("since_hours"), 24, 1),
    dry_run=bool(args.get("dry_run", False)),
    scorer=str(args.get("scorer") or "compare"),
)
return tool_result(_compact_improve_tool_result(result))
```

**Step 3: Run focused tests**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_plugin_tools.py::test_improve_tool_returns_compact_llm_facing_summary tests/test_plugin_tools.py::test_improve_tool_uses_core_loop_with_dry_run -q
```

Expected: new test passes. Existing `test_improve_tool_uses_core_loop_with_dry_run` will likely need expectation updates because schema changes from `self_improvement_run_result` to `self_improvement_tool_result_summary`.

**Step 4: Update existing test expectation**

In `test_improve_tool_uses_core_loop_with_dry_run`, keep call assertions, but assert:

```python
assert payload["schema_name"] == "self_improvement_tool_result_summary"
assert payload["operation"] == "improve"
assert payload["target_changed"] is False
assert payload["dry_run"] is True
```

## Task 3: Add compact calibrate tool result tests

**Objective:** Future calibration payload growth should not leak full GEPA/eval details into LLM context.

**Files:**
- Modify: `tests/test_plugin_tools.py`

**Step 1: Add failing test**

```python
def test_calibrate_tool_returns_compact_llm_facing_summary(monkeypatch, tmp_path):
    mod = load_plugin_module()
    large_details = "x" * 20000

    def fake_run_calibration(**kwargs):
        return {
            "schema_name": "self_improvement_calibration_result",
            "target_changed": False,
            "active_changed": False,
            "current_status": "dry_run",
            "evidence_summary": {"total_events": 5, "disagreements": 1, "bad_outcomes": 0, "scorer_errors": 0},
            "regression": {"status": "passed", "cases": [{"details": large_details}]},
            "active_evaluator_path": str(tmp_path / "active.json"),
            "ledger_path": str(tmp_path / "ledger.json"),
            "candidate": {"prompt": large_details},
        }

    mod._handle_self_improvement_calibrate_tool.__globals__["run_calibration"] = fake_run_calibration

    raw = mod._handle_self_improvement_calibrate_tool({"dry_run": True, "config": {"_self_improvement_root": str(tmp_path / "self-improvement")}})
    payload = parse_tool_payload(raw)

    assert payload["schema_name"] == "self_improvement_tool_result_summary"
    assert payload["operation"] == "calibrate"
    assert payload["dry_run"] is True
    assert payload["target_changed"] is False
    assert payload["active_changed"] is False
    assert payload["current_status"] == "dry_run"
    assert payload["evidence_summary"]["total_events"] == 5
    assert payload["regression"] == {"status": "passed"}
    assert payload["full_payload"]["path"] == str(tmp_path / "ledger.json")
    assert large_details not in raw
    assert len(raw) < 4000
```

**Step 2: Run focused test to verify failure**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_plugin_tools.py::test_calibrate_tool_returns_compact_llm_facing_summary -q
```

Expected: FAIL because handler still returns full calibration result.

## Task 4: Implement compact calibrate helper

**Objective:** Make `self_improvement_calibrate` tool return a bounded summary.

**Files:**
- Modify: `hermes_self_improvement/tool_handlers.py`
- Modify: `tests/test_plugin_tools.py`

**Step 1: Add helper**

```python
def _compact_calibrate_tool_result(result: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    evidence = result.get("evidence_summary") if isinstance(result.get("evidence_summary"), dict) else {}
    regression = result.get("regression") if isinstance(result.get("regression"), dict) else {}
    ledger_path = result.get("ledger_path") or result.get("artifact_path")
    return {
        "schema_name": "self_improvement_tool_result_summary",
        "schema_version": "1.0",
        "operation": "calibrate",
        "dry_run": bool(dry_run),
        "target_changed": bool(result.get("target_changed") or result.get("active_changed")),
        "active_changed": bool(result.get("active_changed")),
        "current_status": result.get("current_status") or result.get("status") or "unknown",
        "evidence_summary": {
            "total_events": int(evidence.get("total_events") or 0),
            "disagreements": int(evidence.get("disagreements") or 0),
            "bad_outcomes": int(evidence.get("bad_outcomes") or 0),
            "scorer_errors": int(evidence.get("scorer_errors") or 0),
        },
        "regression": {"status": regression.get("status")} if regression else {},
        "active_evaluator_path": result.get("active_evaluator_path"),
        "ledger_path": ledger_path,
        "full_payload": {
            "available": bool(ledger_path),
            "read_with": "read_file" if ledger_path else None,
            "path": ledger_path,
            **({"reason": "calibration did not return an artifact path"} if not ledger_path else {}),
        },
    }
```

**Step 2: Use helper in calibrate tool handler**

```python
dry_run = bool(args.get("dry_run", False))
try:
    result = run_calibration(config=_config_from_args(args), execute=not dry_run)
    return tool_result(_compact_calibrate_tool_result(result, dry_run=dry_run))
except Exception as exc:
    return tool_error("calibration_failed", error_detail=str(exc), target_changed=False)
```

**Step 3: Update existing calibrate tests**

Existing tests currently assert `schema_name == "self_improvement_calibration_result"`. Update to compact schema while preserving behavior assertions:

```python
assert payload["schema_name"] == "self_improvement_tool_result_summary"
assert payload["operation"] == "calibrate"
assert payload["active_changed"] is False
```

**Step 4: Run focused tests**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_plugin_tools.py -q
```

Expected: all plugin tool tests pass.

## Task 5: Add regression tests that CLI JSON remains full and CLI summary remains short

**Objective:** Prevent accidental breakage of the operator-facing CLI contract while fixing tool results.

**Files:**
- Modify: `tests/test_cli_surface.py`

**Step 1: Add test for CLI `--json` full payload**

Use monkeypatches similar to `test_improve_dry_run_summary_prints_next_actions` so the test is deterministic.

```python
def test_improve_cli_json_keeps_full_payload_for_operator_debug(monkeypatch, tmp_path, capsys):
    cli = load_cli_module()
    large_details = "x" * 12000
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: {"_self_improvement_root": str(tmp_path / "self-improvement")})
    monkeypatch.setattr(cli, "_load_events", lambda *args, **kwargs: [])
    monkeypatch.setattr(cli, "preview_curator_lifecycle", lambda **kwargs: {"status": "dry_run", "details": large_details})
    monkeypatch.setattr(cli, "load_curator_telemetry", lambda config: {"available": False, "source": "curator", "candidates": [], "rejected": [], "summary": {"candidate_count": 0, "rejected_count": 0}})
    monkeypatch.setattr(cli, "run_pipeline", lambda *args, **kwargs: {"proposals": [{"id": "p1", "details": large_details}], "summary": {}})
    monkeypatch.setattr(cli, "run_skill_improvement_step", lambda **kwargs: {"status": "skipped", "changed": 0, "changed_skills": [], "decisions": [{"task": {"instructions": large_details}}]})
    monkeypatch.setattr(cli, "run_memory_improvement_step", lambda **kwargs: {"status": "skipped", "changed": 0, "changed_memories": [], "decisions": []})

    args = build_parser().parse_args(["improve", "--dry-run", "--json"])
    cli._handle_cli(args)

    out = capsys.readouterr().out
    assert '"schema_name": "self_improvement_run_result"' in out
    assert large_details in out
```

**Step 2: Add/adjust summary shortness test**

Existing `test_improve_dry_run_summary_prints_next_actions` already covers human summary. Add one assertion that large internals are not printed if needed.

```python
assert "proposals_considered" not in out
assert "step_decisions" not in out
```

**Step 3: Run CLI tests**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_cli_surface.py -q
```

Expected: pass.

## Task 6: Update README / operational skill notes

**Objective:** Document the distinction clearly so future agents do not reintroduce full payload tool returns.

**Files:**
- Modify: `README.md`
- Maybe modify: `skills/operations/SKILL.md`

**Step 1: README update**

In `README.md` around Runner model lines 96-97, add a short note:

```markdown
Agent tool results are intentionally compact. `self_improvement_improve` and `self_improvement_calibrate` return LLM-facing summaries plus artifact paths; full details stay in runtime JSON artifacts. CLI `--json` remains the operator/debug escape hatch for full payload inspection.
```

**Step 2: Operations skill update**

Add a pitfall or command note:

```markdown
- Agent tool handlers must not return full run/calibration payloads. Return compact summaries with artifact paths; keep full payloads in runtime artifacts or CLI `--json` only.
```

**Step 3: Run doc-adjacent tests if any**

No dedicated docs test is expected. Run normal focused tests after code changes.

## Task 7: Full validation

**Objective:** Verify the compact tool result change without changing runner semantics.

**Files:**
- All touched files

**Step 1: Static compile**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
```

Expected: no output / exit 0.

**Step 2: Focused tests**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_plugin_tools.py tests/test_cli_surface.py -q
```

Expected: pass.

**Step 3: Full tests**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests -q
```

Expected: pass.

**Step 4: Runtime smoke**

```bash
hermes self-improvement status
hermes self-improvement improve --dry-run
hermes self-improvement improve --dry-run --json >/tmp/hermes-self-improve-dry-run.json
python3 - <<'PY'
from pathlib import Path
plain = Path('/tmp/hermes-self-improve-dry-run.json').read_text(encoding='utf-8')
print(len(plain))
assert 'self_improvement_run_result' in plain
PY
```

Expected:
- `status` succeeds.
- normal dry-run output remains short.
- `--json` remains full and valid.

**Step 5: Plugin tool smoke via Python handler**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY - <<'PY'
import importlib.util, json, sys
from pathlib import Path
plugin_init = Path('__init__.py').resolve()
spec = importlib.util.spec_from_file_location('self_improvement_tool_smoke', plugin_init)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
raw = mod._handle_self_improvement_improve_tool({'dry_run': True, 'since_hours': 24})
payload = json.loads(raw)
print(payload['schema_name'], payload['operation'], len(raw), payload.get('artifact_path'))
assert payload['schema_name'] == 'self_improvement_tool_result_summary'
assert payload['operation'] == 'improve'
assert len(raw) < 10000
assert payload.get('artifact_path')
PY
```

Expected: compact schema, length under 10KB, artifact path present.

**Step 6: Git diff hygiene**

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; only intended files changed.

## Risks and tradeoffs

- **Risk:** Some existing agent flow may expect full `self_improvement_run_result` from the tool.  
  **Mitigation:** The full payload remains available via `artifact_path`. Tool schema change should be explicit via `schema_name: self_improvement_tool_result_summary`.

- **Risk:** Compact summary might omit a field needed for quick decisions.  
  **Mitigation:** Include counts, status, changed flags, next actions, artifact path. Anything deeper should be read explicitly from artifact.

- **Risk:** `calibrate` may not always have a durable artifact path.  
  **Mitigation:** Do not invent storage in this slice. Return `full_payload.available: false` with reason if no path exists. A later plan can artifact calibration consistently if needed.

- **Risk:** CLI `--json` remains long.  
  **Mitigation:** This is intentional. The problematic path is LLM-facing tool output, not operator/debug output.

## Open questions

- Should `self_improvement_report` also be compacted further? It already drops the markdown `report`, but can still include findings/proposals/operational reports. Defer until we measure actual tool result size.
- Should calibration always write a dedicated artifact like `improve` does? Defer unless compact calibrate result lacks a useful `full_payload.path` in practice.

## Suggested commit sequence

1. `test: cover compact self-improvement tool results`
2. `fix: compact self-improvement tool outputs`
3. `docs: document compact tool result contract`

