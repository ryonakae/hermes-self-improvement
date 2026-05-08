# Self-Improvement Review Outcome Feedback Loop Implementation Plan

> **Status:** completed on 2026-04-30. Implemented append-only outcome store, CLI `outcome`, read-only ledger inference, calibration/report/status integration, docs, and tests. Tool-native outcome recording was deliberately deferred to keep primary plugin tools at seven.

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task. Do not add a new broad command surface. Keep hooks observational and keep `--execute` as the only mutation boundary.

**Goal:** Teach `hermes-self-improvement` to record human/apply/rollback outcomes for proposals and feed those outcomes into calibration/evaluator evidence without enabling auto-apply.

**Architecture:** Add a plugin-owned outcome ledger under `${HERMES_HOME:-~/.hermes}/self-improvement/outcomes/`, plus CLI/tool/report integration that summarizes outcomes and exposes them to `collect_calibration_evidence()`. Outcome recording is explicit and append-only; it never mutates apply ledgers or proposals in place. Calibration consumes outcome summaries as advisory evidence only and remains regression-gated before any active evaluator promotion.

**Tech Stack:** Python 3.11, pytest, existing `hermes_self_improvement/{cli,calibration,observer,tool_handlers,schemas}.py`, runtime artifact helpers via `_reports_dir()`, JSON ledgers, existing `bin/hermes-self-improve` wrapper.

---

## Current Observed State

- `.hermes/plans/README.md` says there are no active unfinished implementation plans.
- `bin/hermes-self-improve status --json` reports:
  - `mutation_backend.available=true`
  - `merge_planner.available=true`
  - `memory_rollback.supported=false`, `execution=blocked`, preview-only modes.
- `calibration.collect_calibration_evidence()` currently counts:
  - scorer disagreements in apply plans
  - failed apply ledger items
  - rollback operation ledgers
  - scorer errors
- There is no first-class record of user review decisions like “accepted”, “rejected”, “edited before apply”, “ignored”, or “rolled back because bad proposal”.
- Existing outcome-like signals are scattered across apply ledgers and rollback results; they do not bind back cleanly to plan item IDs, proposal IDs, scorer disagreement, or human judgment.

## Non-goals

- Do not create an auto-apply permission system.
- Do not revive approval artifacts, `apply-low-risk`, `execution_mode`, or user-facing expected hashes.
- Do not mutate historical apply plans/ledgers in place.
- Do not run LLM/GEPA from hooks.
- Do not make calibration promote anything without the existing `calibrate --execute` regression gate.
- Do not store raw secrets or large content in outcome records.

## Outcome Model

Allowed outcome values:

```python
OUTCOME_VALUES = {
    "accepted_for_apply",
    "rejected_by_human",
    "edited_before_apply",
    "ignored_stale",
    "applied_successfully",
    "apply_failed",
    "rolled_back",
    "rollback_failed",
}
```

Recommended schema:

```json
{
  "schema_name": "self_improvement_review_outcome",
  "schema_version": "1.0",
  "created_by": {"plugin": "hermes-self-improvement", "plugin_version": "0.1.0"},
  "created_at": "2026-04-30T00:00:00+00:00",
  "outcome_id": "outcome-...",
  "plan_id": "plan-...",
  "item_id": "step-001",
  "proposal_id": "proposal-...",
  "ledger_id": "ledger-...",
  "outcome": "rejected_by_human",
  "reason": "too broad for unattended apply",
  "source": "cli|tool|ledger_inference|manual_import",
  "scorer": "compare-v0.1",
  "risk": "low|medium|high",
  "recommendation": "review_for_possible_low_risk_apply",
  "scorer_disagreement_count": 2,
  "target_kind": "skill|memory",
  "change_type": "skill_improve",
  "redacted_note": "short note only",
  "content_hashes": {"note_hash": "..."}
}
```

Store location:

```text
${HERMES_HOME:-~/.hermes}/self-improvement/outcomes/YYYY-MM-DD/*.json
```

---

## Phase 1: Outcome Schema and Append-only Store

**Objective:** Add a small outcome store module with validation, redaction, stable IDs, and summary loading.

**Files:**
- Create: `hermes_self_improvement/outcome_store.py`
- Test: `tests/test_outcome_store.py`

### Step 1: Write failing tests

Create `tests/test_outcome_store.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from hermes_self_improvement.outcome_store import (
    OUTCOME_VALUES,
    record_review_outcome,
    load_review_outcomes,
    summarize_review_outcomes,
)


def test_record_review_outcome_writes_append_only_redacted_payload(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = record_review_outcome(
        config=config,
        outcome={
            "plan_id": "plan-1",
            "item_id": "step-001",
            "proposal_id": "proposal-1",
            "outcome": "rejected_by_human",
            "reason": "secret token should not be stored: sk-abc123",
            "source": "cli",
            "risk": "high",
            "target_kind": "memory",
        },
    )

    assert result["status"] == "recorded"
    path = Path(result["path"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_name"] == "self_improvement_review_outcome"
    assert payload["outcome"] == "rejected_by_human"
    assert "sk-abc123" not in json.dumps(payload)
    assert payload["content_hashes"]["reason_hash"]


def test_record_review_outcome_rejects_unknown_outcome(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = record_review_outcome(config=config, outcome={"outcome": "approve_all"})
    assert result["status"] == "failed"
    assert "unknown_outcome" in result["reasons"]


def test_load_and_summarize_review_outcomes(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    record_review_outcome(config=config, outcome={"outcome": "applied_successfully", "plan_id": "p", "item_id": "1", "source": "cli"})
    record_review_outcome(config=config, outcome={"outcome": "rolled_back", "plan_id": "p", "item_id": "1", "source": "cli"})

    loaded = load_review_outcomes(config=config, limit=10)
    summary = summarize_review_outcomes(loaded)
    assert len(loaded) == 2
    assert summary["total"] == 2
    assert summary["by_outcome"]["rolled_back"] == 1
```

### Step 2: Run tests and verify failure

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_outcome_store.py -q
```

Expected: import failure for `hermes_self_improvement.outcome_store`.

### Step 3: Implement minimal outcome store

Create `hermes_self_improvement/outcome_store.py` with:

```python
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .observer import _reports_dir, _sha256_text, _stable_json
except Exception:
    from observer import _reports_dir, _sha256_text, _stable_json

PLUGIN_NAME = "hermes-self-improvement"
PLUGIN_VERSION = "0.1.0"
UTC = timezone.utc

OUTCOME_VALUES = {
    "accepted_for_apply",
    "rejected_by_human",
    "edited_before_apply",
    "ignored_stale",
    "applied_successfully",
    "apply_failed",
    "rolled_back",
    "rollback_failed",
}

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{6,}"),
    re.compile(r"(?i)(token|password|secret|api[_-]?key)\s*[:=]\s*\S+"),
]


def _redact(text: str) -> str:
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted[:500]


def _outcome_dir(config: dict[str, Any], now: datetime) -> Path:
    return _reports_dir(config) / "outcomes" / now.strftime("%Y-%m-%d")


def _normalize_outcome(raw: dict[str, Any], *, now: datetime) -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []
    outcome = str(raw.get("outcome") or "")
    if outcome not in OUTCOME_VALUES:
        reasons.append("unknown_outcome")
    reason = raw.get("reason")
    redacted_reason = _redact(str(reason)) if reason is not None else None
    payload = {
        "schema_name": "self_improvement_review_outcome",
        "schema_version": "1.0",
        "created_by": {"plugin": PLUGIN_NAME, "plugin_version": PLUGIN_VERSION},
        "created_at": now.isoformat(),
        "plan_id": raw.get("plan_id"),
        "item_id": raw.get("item_id"),
        "proposal_id": raw.get("proposal_id"),
        "ledger_id": raw.get("ledger_id"),
        "outcome": outcome,
        "source": raw.get("source") or "cli",
        "risk": raw.get("risk"),
        "recommendation": raw.get("recommendation"),
        "scorer": raw.get("scorer"),
        "target_kind": raw.get("target_kind"),
        "change_type": raw.get("change_type"),
        "redacted_reason": redacted_reason,
        "content_hashes": {},
    }
    if reason is not None:
        payload["content_hashes"]["reason_hash"] = _sha256_text(str(reason))
    payload["outcome_id"] = "outcome-" + _sha256_text(_stable_json(payload))[:12]
    if reasons:
        return None, reasons
    return payload, []


def record_review_outcome(*, config: dict[str, Any], outcome: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    payload, reasons = _normalize_outcome(outcome, now=now)
    if payload is None:
        return {"status": "failed", "reasons": reasons, "target_changed": False}
    out_dir = _outcome_dir(config, now)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{now.strftime('%Y%m%dT%H%M%SZ')}-{payload['outcome_id']}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "recorded", "path": str(path), "outcome_id": payload["outcome_id"], "target_changed": False}


def load_review_outcomes(*, config: dict[str, Any], limit: int = 100) -> list[dict[str, Any]]:
    root = _reports_dir(config) / "outcomes"
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("**/*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict) and payload.get("schema_name") == "self_improvement_review_outcome":
            payload["path"] = str(path)
            rows.append(payload)
        if len(rows) >= limit:
            break
    return rows


def summarize_review_outcomes(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    by_outcome = Counter(str(row.get("outcome") or "unknown") for row in outcomes)
    by_target_kind = Counter(str(row.get("target_kind") or "unknown") for row in outcomes)
    return {"total": len(outcomes), "by_outcome": dict(by_outcome), "by_target_kind": dict(by_target_kind)}
```

### Step 4: Run tests

```bash
$PY -m pytest tests/test_outcome_store.py -q
```

Expected: pass.

### Step 5: Commit

```bash
git add hermes_self_improvement/outcome_store.py tests/test_outcome_store.py
git commit -m "feat(self-improvement): add review outcome store"
git push
```

---

## Phase 2: CLI Surface for Explicit Outcome Recording

**Objective:** Add a small explicit command for recording review outcomes without expanding apply/approval flows.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Test: `tests/test_cli_surface.py`
- Test: `tests/test_outcome_store.py`

### Step 1: Write failing parser tests

Add to `tests/test_cli_surface.py`:

```python
def test_outcome_command_accepts_required_fields():
    cli = import_cli_module()
    parser = cli.build_parser()
    args = parser.parse_args([
        "outcome",
        "--outcome", "rejected_by_human",
        "--plan-id", "plan-1",
        "--item-id", "step-001",
        "--reason", "too broad",
        "--json",
    ])
    assert args.command == "outcome"
    assert args.outcome == "rejected_by_human"
    assert args.as_json is True
```

If the project uses a different parser helper name, follow existing CLI tests in `tests/test_cli_surface.py`.

### Step 2: Implement parser

In `hermes_self_improvement/cli.py`, add a subparser:

```python
p_outcome = subparsers.add_parser("outcome", help="Record a review/apply/rollback outcome")
p_outcome.add_argument("--outcome", required=True, choices=sorted(OUTCOME_VALUES))
p_outcome.add_argument("--plan-id")
p_outcome.add_argument("--item-id")
p_outcome.add_argument("--proposal-id")
p_outcome.add_argument("--ledger-id")
p_outcome.add_argument("--reason")
p_outcome.add_argument("--source", default="cli")
p_outcome.add_argument("--risk")
p_outcome.add_argument("--recommendation")
p_outcome.add_argument("--scorer")
p_outcome.add_argument("--target-kind")
p_outcome.add_argument("--change-type")
p_outcome.add_argument("--json", action="store_true", dest="as_json")
```

Import from `outcome_store`:

```python
from .outcome_store import OUTCOME_VALUES, record_review_outcome
```

### Step 3: Implement handler branch

In the CLI command handler:

```python
if args.command == "outcome":
    result = record_review_outcome(
        config=config,
        outcome={
            "outcome": args.outcome,
            "plan_id": args.plan_id,
            "item_id": args.item_id,
            "proposal_id": args.proposal_id,
            "ledger_id": args.ledger_id,
            "reason": args.reason,
            "source": args.source,
            "risk": args.risk,
            "recommendation": args.recommendation,
            "scorer": args.scorer,
            "target_kind": args.target_kind,
            "change_type": args.change_type,
        },
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("status") == "recorded" else 1
```

### Step 4: Run targeted tests and smoke

```bash
$PY -m pytest tests/test_cli_surface.py tests/test_outcome_store.py -q
bin/hermes-self-improve outcome --outcome rejected_by_human --plan-id demo --item-id step-001 --reason "demo" --json
```

Use a temp config in tests; do not write test artifacts to production runtime in unit tests.

### Step 5: Commit

```bash
git add hermes_self_improvement/cli.py tests/test_cli_surface.py tests/test_outcome_store.py
git commit -m "feat(self-improvement): record review outcomes from CLI"
git push
```

---

## Phase 3: Tool Surface for Outcome Recording

**Objective:** Expose outcome recording to Hermes tool callers while keeping the seven primary tools stable unless adding a new tool is intentionally accepted.

**Decision point:** Prefer not to add an eighth primary tool unless necessary. Instead, add an optional `outcome` object to `self_improvement_report` or `self_improvement_status` is wrong because those are read-only. The cleanest design is a new explicit tool `self_improvement_record_outcome`, but this does expand the tool surface. If avoiding an eighth tool is more important, skip this phase and keep CLI-only recording.

**Recommended choice:** Add `self_improvement_record_outcome` only if tool-native review feedback is needed from Slack/agent workflows. Otherwise defer.

**Files if enabled:**
- Modify: `hermes_self_improvement/schemas.py`
- Modify: `hermes_self_improvement/tool_handlers.py`
- Modify: `hermes_self_improvement/__init__.py`
- Test: `tests/test_plugin_tools.py`
- Docs: `README.md`, `skills/operations/SKILL.md`

### Step 1: Write failing registration test

```python
def test_register_exposes_record_outcome_tool_when_enabled():
    mod = load_plugin_module()
    ctx = RecordingContext()
    mod.register(ctx)
    names = {name for name, _kwargs in ctx.tools}
    assert "self_improvement_record_outcome" in names
```

If keeping exactly seven tools is desired, instead add a docs note that tool-native outcome recording is deferred.

### Step 2: Add schema and handler

Schema should accept only metadata fields and a short redacted reason. Handler calls `record_review_outcome()` directly, not the wrapper CLI.

### Step 3: Verify plugin registration

```bash
$PY -m pytest tests/test_plugin_tools.py -q
$PY - <<'PY'
from hermes_cli.plugins import discover_plugins, get_plugin_manager
import json
discover_plugins(force=True)
info = [p for p in get_plugin_manager().list_plugins() if p['name'] == 'hermes-self-improvement']
print(json.dumps(info, ensure_ascii=False, indent=2))
PY
```

### Step 4: Commit

```bash
git add hermes_self_improvement/schemas.py hermes_self_improvement/tool_handlers.py __init__.py tests/test_plugin_tools.py README.md skills/operations/SKILL.md
git commit -m "feat(self-improvement): expose review outcome recording tool"
git push
```

---

## Phase 4: Infer Outcomes From Apply and Rollback Ledgers

**Objective:** Add a read-only inference path that converts existing apply/rollback ledgers into outcome evidence summaries without writing outcome records automatically.

**Files:**
- Modify: `hermes_self_improvement/outcome_store.py`
- Test: `tests/test_outcome_store.py`
- Optional: `tests/test_apply_engine.py`

### Step 1: Write failing tests

```python
def test_infer_outcomes_from_apply_ledger_counts_applied_and_failed(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    ledger_dir = tmp_path / "self-improvement" / "ledgers" / "2026-04-30"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "ledger.json").write_text(json.dumps({
        "schema_name": "self_improvement_apply_ledger",
        "operation": "apply",
        "ledger_id": "ledger-1",
        "items": [
            {"item_id": "step-001", "status": "applied", "target_kind": "skill"},
            {"item_id": "step-002", "status": "failed", "target_kind": "memory"},
        ],
    }), encoding="utf-8")

    inferred = infer_review_outcomes_from_ledgers(config=config)
    assert inferred["summary"]["by_outcome"]["applied_successfully"] == 1
    assert inferred["summary"]["by_outcome"]["apply_failed"] == 1
```

### Step 2: Implement inference helper

```python
def infer_review_outcomes_from_ledgers(*, config: dict[str, Any], limit: int = 200) -> dict[str, Any]:
    # Read apply ledgers and rollback results from _reports_dir(config)/ledgers.
    # Return normalized outcome-like rows in memory only.
    # Do not write files.
```

Mapping:

- apply ledger item `status=applied` → `applied_successfully`
- apply ledger item `status=failed` → `apply_failed`
- rollback result item `status=rolled_back` → `rolled_back`
- rollback result item `status=failed` → `rollback_failed`

### Step 3: Verify

```bash
$PY -m pytest tests/test_outcome_store.py tests/test_apply_engine.py -q
```

### Step 4: Commit

```bash
git add hermes_self_improvement/outcome_store.py tests/test_outcome_store.py
git commit -m "feat(self-improvement): infer review outcomes from ledgers"
git push
```

---

## Phase 5: Feed Outcomes Into Calibration Evidence

**Objective:** Extend `collect_calibration_evidence()` so review outcomes affect calibration evidence counts.

**Files:**
- Modify: `hermes_self_improvement/calibration.py`
- Test: `tests/test_calibration.py`
- Test: `tests/test_outcome_store.py`

### Step 1: Write failing calibration evidence test

Add to `tests/test_calibration.py`:

```python
def test_collect_calibration_evidence_counts_review_outcomes(tmp_path):
    mod = load_plugin_module()
    import hermes_self_improvement.outcome_store as outcome_store
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    outcome_store.record_review_outcome(config=config, outcome={
        "outcome": "rejected_by_human",
        "plan_id": "plan-1",
        "item_id": "step-001",
        "source": "cli",
    })
    outcome_store.record_review_outcome(config=config, outcome={
        "outcome": "rolled_back",
        "plan_id": "plan-1",
        "item_id": "step-002",
        "source": "cli",
    })

    evidence = mod.collect_calibration_evidence(config)
    assert evidence["review_outcomes"] == 2
    assert evidence["bad_outcomes"] >= 2
```

### Step 2: Implement evidence integration

In `calibration.py`:

```python
try:
    from .outcome_store import load_review_outcomes, summarize_review_outcomes
except Exception:
    from outcome_store import load_review_outcomes, summarize_review_outcomes
```

In `collect_calibration_evidence()` after existing JSON scan:

```python
outcomes = load_review_outcomes(config=config, limit=1000)
outcome_summary = summarize_review_outcomes(outcomes)
summary["review_outcomes"] = outcome_summary["total"]
summary["review_outcome_summary"] = outcome_summary
bad_outcome_names = {"rejected_by_human", "apply_failed", "rolled_back", "rollback_failed"}
summary["bad_outcomes"] += sum(outcome_summary["by_outcome"].get(name, 0) for name in bad_outcome_names)
if outcome_summary["total"]:
    summary["total_events"] += outcome_summary["total"]
```

Be careful not to double-count inferred ledgers if Phase 4 output is also used. Explicit outcome records count; inferred ledger outcomes should be report-only unless explicitly configured.

### Step 3: Verify

```bash
$PY -m pytest tests/test_calibration.py tests/test_outcome_store.py -q
bin/hermes-self-improve calibrate --json
```

### Step 4: Commit

```bash
git add hermes_self_improvement/calibration.py tests/test_calibration.py tests/test_outcome_store.py
git commit -m "feat(self-improvement): include review outcomes in calibration evidence"
git push
```

---

## Phase 6: Report Integration

**Objective:** Make `report` and `status` show recent outcome counts without turning them into mutation commands.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/tool_handlers.py`
- Test: `tests/test_report_integration.py`
- Test: `tests/test_plugin_tools.py`

### Step 1: Write failing report test

```python
def test_report_includes_review_outcome_summary(tmp_path):
    mod = load_plugin_module()
    import hermes_self_improvement.outcome_store as outcome_store
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    outcome_store.record_review_outcome(config=config, outcome={"outcome": "rejected_by_human", "source": "cli"})

    result = mod.generate_report(config=config, since_hours=24, scorer="compare")
    assert result["review_outcomes"]["total"] == 1
```

Adjust function names to existing report helper names. If reports are CLI-only, test the CLI JSON output instead.

### Step 2: Implement summary loading

Use:

```python
outcomes = load_review_outcomes(config=config, limit=100)
summary = summarize_review_outcomes(outcomes)
```

Add to report JSON payload:

```json
"review_outcomes": {"total": 1, "by_outcome": {...}}
```

For human-readable markdown, add a short section:

```markdown
## Review outcomes

- total: 3
- rejected_by_human: 1
- rolled_back: 1
```

### Step 3: Verify

```bash
$PY -m pytest tests/test_report_integration.py tests/test_plugin_tools.py -q
bin/hermes-self-improve report --since-hours 24 --json
```

### Step 4: Commit

```bash
git add hermes_self_improvement/cli.py hermes_self_improvement/tool_handlers.py tests/test_report_integration.py tests/test_plugin_tools.py
git commit -m "feat(self-improvement): report review outcome summaries"
git push
```

---

## Phase 7: Docs and Operations Skill

**Objective:** Document the dogfood feedback loop and make clear that outcomes are advisory calibration evidence, not auto-apply permissions.

**Files:**
- Modify: `README.md`
- Modify: `skills/operations/SKILL.md`
- Optional modify: `skills/operations/references/operations.md`
- Test: `tests/test_scheduled_execution_docs.py`

### Step 1: Add docs assertions

Add checks that docs include:

- `review outcome`
- `calibration evidence`
- `does not grant auto-apply`

### Step 2: Update README

Add a short section near the self-improvement flow:

```markdown
### Review outcome feedback

After a plan item is accepted, rejected, applied, failed, or rolled back, the outcome can be recorded as an append-only review outcome. Outcomes are summarized in reports and counted as calibration evidence. They do not grant auto-apply permission; evaluator changes still require `calibrate --execute` and regression gates.
```

### Step 3: Update operations skill

Add operational guidance:

- Record outcomes when human review rejects or edits a plan.
- Record rollback reason after rollback.
- Do not put secrets in reasons; reasons are redacted and hashed.

### Step 4: Verify

```bash
$PY -m pytest tests/test_scheduled_execution_docs.py -q
```

### Step 5: Commit

```bash
git add README.md skills/operations/SKILL.md skills/operations/references/operations.md tests/test_scheduled_execution_docs.py
git commit -m "docs(self-improvement): document review outcome feedback loop"
git push
```

---

## Final Validation

Run after all phases:

```bash
uv sync --group dev
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
bin/hermes-self-improve status --json
bin/hermes-self-improve report --since-hours 24 --json
```

Final report should state:

- outcome store path
- CLI command added or deliberately skipped
- whether tool-native outcome recording was added or deferred
- calibration evidence impact
- full test result
- pushed commit list

## Acceptance Checklist

- [ ] Outcome records are append-only JSON files under runtime root.
- [ ] Unknown outcomes fail closed.
- [ ] Reasons are redacted and raw secret-like values are not stored.
- [ ] CLI can record outcomes explicitly.
- [ ] Optional tool-native recording is either implemented or explicitly deferred.
- [ ] Apply/rollback ledger inference is read-only.
- [ ] Calibration evidence counts review outcomes.
- [ ] Reports summarize recent outcomes.
- [ ] Outcomes do not grant auto-apply permission.
- [ ] Full tests pass.
- [ ] Commits are granular and pushed.

## Recommended Commit Sequence

1. `feat(self-improvement): add review outcome store`
2. `feat(self-improvement): record review outcomes from CLI`
3. Optional: `feat(self-improvement): expose review outcome recording tool`
4. `feat(self-improvement): infer review outcomes from ledgers`
5. `feat(self-improvement): include review outcomes in calibration evidence`
6. `feat(self-improvement): report review outcome summaries`
7. `docs(self-improvement): document review outcome feedback loop`
