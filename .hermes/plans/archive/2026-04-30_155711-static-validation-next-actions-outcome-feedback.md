> **Status:** Completed 2026-04-30. Implemented static invariant rejection, invariant/policy docs, non-interactive `next_actions`, strengthened outcome feedback, append-only `self_improvement_record_outcome` tool, and archived superseded plan noise.

# Static Validation, Next Actions, and Outcome Feedback Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task. Keep `improve` / `plan` / `apply` non-interactive. Do not revive approval artifacts, `apply-low-risk`, `execution_mode`, or user-facing expected-hash confirmation. Do not implement code while writing this plan.

**Goal:** Make the self-improvement loop safer and clearer by mechanically rejecting invalid mutation candidates before they can become ready items, adding non-interactive `next_actions` to preview outputs, and then adding outcome recording so rejected/accepted/applied/rolled-back decisions improve future calibration.

**Architecture:** Split the pipeline into three explicit layers: hard static invariants, configurable apply policy, and advisory scorer/GEPA judgment. Static validators run during apply-plan item construction and before execution, so machine-checkable invalid targets never become `ready`. `improve` remains a command that exits after preview unless `--execute` is passed; preview payloads and human-readable output include clear `next_actions`. Outcome recording stays append-only and feeds calibration evidence; it records human decisions but does not grant apply permission.

**Tech Stack:** Python 3.11, pytest, existing `hermes_self_improvement/{apply_plan,apply_engine,config,cli,outcome_store,schemas,tool_handlers}.py`, runtime artifacts under `${HERMES_HOME:-~/.hermes}/self-improvement/`, wrapper CLI `bin/hermes-self-improve`.

---

## Current Context

- Hook observation already records redacted runtime telemetry; hooks remain observational.
- `improve` without `--execute` currently generates calibration preview, proposals, apply plan, apply preview, and exits.
- `improve --execute` / `apply --execute` is the mutation boundary; policy and validation still decide what is applied.
- Review outcomes are currently recordable from CLI via `bin/hermes-self-improve outcome ...` and feed calibration evidence.
- Tool-native outcome recording was deliberately deferred to keep primary plugin tools at seven, but this plan reopens it as a bounded append-only feedback tool after static validation / next-actions UX is fixed.
- `.hermes/plans/README.md` currently says there are no active unfinished plans. This plan should become the sole active plan while being implemented.

## Key Design Decisions

### 1. Hard invariants are not policy

These must be enforced mechanically by code and should not rely on LLM/GEPA/scorer output:

- plugin-owned files (`README.md`, `AGENTS.md`, `config*`, `skills/operations/**`, `.hermes/plans/**`) are not self-improvement mutation targets.
- arbitrary docs/config files are not mutation targets.
- direct filesystem / DB / provider-internal mutation fallback is not allowed for forward apply.
- bounded skill tools unavailable means fail closed / `needs_review` or `rejected_by_planner`.
- rollback never starts the mutation agent.
- sensitive delete re-add is forbidden.
- external provider exact restore is forbidden.
- current target hash drift blocks apply / rollback.
- material scorer disagreement blocks unattended apply unless a later explicit policy feature defines a narrow allowed exception.

These are **static validation / execution invariant** concerns, not `apply_policy` knobs.

### 2. Apply policy controls only safe-range automation

`apply_policy` can expand what is unattended within the invariant boundary:

- max risk
- allowed target kinds
- allowed change types
- specific lifecycle operations allowed unattended
- narrow scorer-disagreement relaxation for low-risk prose if explicitly configured later

It must not override hard invariants.

### 3. `improve` remains non-interactive

No interactive approval UI. Preview commands exit. They should show next steps:

- review plan artifact
- execute ready items
- record rejection / accepted / ignored outcome
- run report / calibrate

### 4. Outcome recording is feedback, not approval

Outcome recording should be append-only evidence. It should not cause apply, bypass policy, or mark approval artifacts. It helps future calibration/scorer improvement.

### 5. Old plan noise should be removed safely

Do not blindly delete historical plans in the same implementation slice as safety logic. First add an archive/prune workflow with tests and index updates. Prefer moving old superseded plans to `.hermes/plans/archive/` or `.hermes/plans/superseded/` over hard deletion unless the user explicitly confirms deletion after seeing the archive list. If physical deletion is chosen, it should be a separate commit after the index summarizes retained decisions.

---

## Phase 0: Plan Index and Old-Plan Cleanup Strategy

**Objective:** Make this plan the active source of truth and define safe cleanup for old noisy plans.

**Files:**
- Modify: `.hermes/plans/README.md`
- Optional create: `.hermes/plans/archive/README.md`
- Optional move later: historical/superseded plan files under `.hermes/plans/archive/`

### Task 0.1: Update active plan index

**Steps:**
1. Add this file under `## Active plans` as priority first.
2. Keep completed canonical implementation records for recently completed work.
3. Add a note that old plan cleanup is included in this active plan.
4. Do not delete or move old plans yet.

**Verification:**

```bash
grep -n "static-validation-next-actions-outcome-feedback" .hermes/plans/README.md
```

Expected: the new plan appears under active plans.

### Task 0.2: Decide cleanup mechanism in code/docs, not ad hoc deletion

**Recommended default:** archive, not delete.

Create a clear rule in `.hermes/plans/README.md`:

- `active`: only unfinished current plans.
- `completed canonical`: plans that define current behavior.
- `archive`: superseded historical plans kept for audit but not loaded as active guidance.
- deletion is allowed only when the index has captured the retained lessons and the user explicitly asks for physical deletion.

**Commit:**

```bash
git add .hermes/plans/README.md .hermes/plans/2026-04-30_155711-static-validation-next-actions-outcome-feedback.md
git commit -m "docs(self-improvement): plan static validation and next actions"
```

---

## Phase 1: Static Invariant Validator Module

**Objective:** Add a dedicated validator so machine-checkable unsafe candidates cannot become `ready` apply-plan items.

**Files:**
- Create: `hermes_self_improvement/static_validation.py`
- Modify: `hermes_self_improvement/apply_plan.py`
- Test: `tests/test_static_validation.py`
- Test: `tests/test_apply_plan.py`

### Task 1.1: Write failing tests for plugin-owned target rejection

Create `tests/test_static_validation.py`:

```python
from __future__ import annotations

from pathlib import Path

from hermes_self_improvement.static_validation import validate_proposal_static_invariants


def test_rejects_plugin_owned_docs_target(tmp_path):
    plugin_root = tmp_path / "plugin"
    target = plugin_root / "README.md"
    target.parent.mkdir(parents=True)
    target.write_text("# plugin\n", encoding="utf-8")

    result = validate_proposal_static_invariants(
        proposal={"target_path": str(target), "target_kind": "docs", "change_type": "docs_update"},
        config={"_plugin_root": str(plugin_root)},
    )

    assert result["status"] == "rejected"
    assert "plugin_owned_target_forbidden" in result["reasons"]
```

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_static_validation.py::test_rejects_plugin_owned_docs_target -q
```

Expected: FAIL — module missing.

### Task 1.2: Implement minimal validator

Create `hermes_self_improvement/static_validation.py` with:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

PLUGIN_OWNED_RELATIVE_PREFIXES = (
    "README.md",
    "AGENTS.md",
    "config.json",
    "config.yaml",
    "config.local.json",
    "config.local.yaml",
    "plugin.yaml",
    ".hermes/plans",
    "skills/operations",
)
ARBITRARY_NON_MUTABLE_TARGET_KINDS = {"docs", "doc", "documentation", "config", "configuration", "evaluator"}
FORBIDDEN_DIRECT_MUTATION_TYPES = {
    "replace_text_once",
    "append_to_existing_section",
    "replace_entire_file",
    "create_file",
    "delete_file",
    "direct_file_mutation",
    "direct_db_mutation",
    "provider_internal_restore",
}


def _plugin_root(config: dict[str, Any] | None) -> Path:
    cfg = config or {}
    return Path(str(cfg.get("_plugin_root") or Path(__file__).resolve().parents[1])).expanduser().resolve()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _plugin_owned_reason(path_text: str | None, config: dict[str, Any] | None) -> str | None:
    if not path_text:
        return None
    root = _plugin_root(config)
    path = Path(str(path_text)).expanduser()
    if not _inside(path, root):
        return None
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return "plugin_owned_target_forbidden"
    for prefix in PLUGIN_OWNED_RELATIVE_PREFIXES:
        if rel == prefix or rel.startswith(prefix.rstrip("/") + "/"):
            return "plugin_owned_target_forbidden"
    return None


def validate_proposal_static_invariants(*, proposal: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    reasons: list[str] = []
    target_kind = str(proposal.get("target_kind") or proposal.get("target") or "").lower()
    change_type = str(proposal.get("change_type") or proposal.get("action") or "").lower()
    target_path = proposal.get("target_path") or proposal.get("path") or proposal.get("file_path") or proposal.get("skill_path")

    plugin_reason = _plugin_owned_reason(str(target_path) if target_path else None, config)
    if plugin_reason:
        reasons.append(plugin_reason)
    if target_kind in ARBITRARY_NON_MUTABLE_TARGET_KINDS:
        reasons.append("non_mutable_target_kind")
    if change_type in FORBIDDEN_DIRECT_MUTATION_TYPES:
        reasons.append("direct_mutation_type_forbidden")
    if proposal.get("provider_internal_restore") is True:
        reasons.append("provider_internal_restore_forbidden")
    if proposal.get("sensitive_delete") is True and change_type in {"memory_delete", "memory_remove"}:
        reasons.append("sensitive_delete_readd_forbidden")

    return {"status": "rejected" if reasons else "passed", "reasons": sorted(set(reasons)), "target_changed": False}
```

### Task 1.3: Add tests for mechanically forbidden categories

Add tests:

- docs/config target kind rejected.
- direct mutation type rejected.
- provider internal restore rejected.
- sensitive memory delete rejected.
- normal mutable-local skill proposal passes static validation.

Run:

```bash
$PY -m pytest tests/test_static_validation.py -q
```

Expected: PASS.

### Task 1.4: Integrate validator into apply plan item construction

In `apply_plan.py`, import validator:

```python
try:
    from .static_validation import validate_proposal_static_invariants
except Exception:
    from static_validation import validate_proposal_static_invariants
```

Find `_build_apply_plan_item(...)` and, after change type / target path are resolved but before marking an item `ready`, call:

```python
static_validation = validate_proposal_static_invariants(proposal=proposal, config=config)
if static_validation.get("status") == "rejected":
    item["status"] = "rejected_by_planner"
    item.setdefault("reasons", []).extend(static_validation.get("reasons") or [])
    item["static_validation"] = static_validation
    return item
```

If current item building is not structured around a mutable `item`, adapt this logic but preserve the behavior: static rejection becomes `rejected_by_planner`, never `ready`.

### Task 1.5: Regression tests in `tests/test_apply_plan.py`

Add tests that build an apply plan from proposals targeting:

- plugin README
- plugin config
- arbitrary docs target
- direct file mutation change type

Assertions:

```python
assert item["status"] == "rejected_by_planner"
assert "plugin_owned_target_forbidden" in item["reasons"]
assert item.get("mutation_plan") in (None, {}) or item["mutation_plan"].get("mutation_type") not in {...}
```

Run:

```bash
$PY -m pytest tests/test_static_validation.py tests/test_apply_plan.py -q
```

**Commit:**

```bash
git add hermes_self_improvement/static_validation.py hermes_self_improvement/apply_plan.py tests/test_static_validation.py tests/test_apply_plan.py
git commit -m "feat(self-improvement): reject invalid mutation targets statically"
```

---

## Phase 2: Separate Invariants from Apply Policy in Docs and Config

**Objective:** Make the code/docs distinction explicit so future contributors do not add hard safety boundaries as policy knobs.

**Files:**
- Modify: `hermes_self_improvement/config.py`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `skills/operations/SKILL.md`
- Modify: `skills/operations/references/safety-and-apply.md`
- Test: `tests/test_apply_policy.py`
- Test: `tests/test_scheduled_execution_docs.py`

### Task 2.1: Add invariant metadata to config output only if useful

Add constants in `config.py`:

```python
HARD_STATIC_INVARIANTS = {
    "plugin_owned_targets_forbidden": True,
    "arbitrary_docs_config_targets_forbidden": True,
    "direct_forward_mutation_forbidden": True,
    "provider_internal_restore_forbidden": True,
    "sensitive_delete_readd_forbidden": True,
    "rollback_agent_forbidden": True,
    "target_hash_drift_blocks_apply": True,
}
```

Do **not** make these configurable under `apply_policy`.

Expose in status/report only if needed later; this phase can keep them as code constants and docs.

### Task 2.2: Test policy cannot override invariants

In `tests/test_apply_policy.py`, add a plan/build test where config attempts to allow docs/config/direct mutation:

```python
config = {
    "apply_policy": {
        "max_risk": "critical",
        "allowed_target_kinds": ["skill", "memory", "docs", "config"],
        "allowed_change_types": ["direct_file_mutation"],
        "allow_destructive": True,
    }
}
```

Expected: static validator / apply plan still rejects.

### Task 2.3: Docs update

Docs must say:

- `apply_policy` expands automation only within invariant boundary.
- static invariants are programmatic and not LLM/GEPA suggestions.
- invalid candidates may appear as raw proposals but cannot become `ready` items.

Run:

```bash
$PY -m pytest tests/test_apply_policy.py tests/test_scheduled_execution_docs.py -q
```

**Commit:**

```bash
git add hermes_self_improvement/config.py README.md AGENTS.md skills/operations/SKILL.md skills/operations/references/safety-and-apply.md tests/test_apply_policy.py tests/test_scheduled_execution_docs.py
git commit -m "docs(self-improvement): separate invariants from apply policy"
```

---

## Phase 3: Add Non-Interactive Next Actions

**Objective:** Make preview commands exit normally while telling humans/cron/Slack exactly what to do next.

**Files:**
- Create: `hermes_self_improvement/next_actions.py`
- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/tool_handlers.py`
- Test: `tests/test_next_actions.py`
- Test: `tests/test_cli_surface.py`
- Test: `tests/test_report_integration.py`
- Test: `tests/test_plugin_tools.py`

### Task 3.1: Write failing tests for next actions from apply plan preview

Create `tests/test_next_actions.py`:

```python
from hermes_self_improvement.next_actions import build_next_actions_for_apply_preview


def test_next_actions_include_execute_review_and_outcome_commands():
    result = {
        "plan_id": "plan-1",
        "execute": False,
        "summary": {"would_apply": 2, "needs_review": 1, "failed": 0},
        "ledger_path": "/tmp/ledger.json",
    }
    actions = build_next_actions_for_apply_preview(result, command_prefix="bin/hermes-self-improve")

    kinds = {item["kind"] for item in actions}
    assert "execute_ready_items" in kinds
    assert "review_plan" in kinds
    assert "record_rejection_outcome" in kinds
    assert any("apply plan-1 --execute" in item.get("command", "") for item in actions)
```

Run expected FAIL: module missing.

### Task 3.2: Implement next action helpers

Create `hermes_self_improvement/next_actions.py`:

```python
from __future__ import annotations
from typing import Any


def build_next_actions_for_apply_preview(result: dict[str, Any], *, command_prefix: str = "bin/hermes-self-improve") -> list[dict[str, Any]]:
    plan_id = result.get("plan_id") or (result.get("apply_plan") or {}).get("plan_id")
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    actions: list[dict[str, Any]] = []
    if plan_id:
        actions.append({"kind": "review_plan", "description": "Review the apply plan artifact before executing."})
    if plan_id and int(summary.get("would_apply") or summary.get("ready") or 0) > 0:
        actions.append({
            "kind": "execute_ready_items",
            "command": f"{command_prefix} apply {plan_id} --execute",
            "description": "Execute policy-allowed ready items for this plan.",
        })
    if plan_id and int(summary.get("needs_review") or 0) > 0:
        actions.append({
            "kind": "record_rejection_outcome",
            "command": f"{command_prefix} outcome --outcome rejected_by_human --plan-id {plan_id} --item-id <item-id> --reason '<short reason>'",
            "description": "Record a human rejection/edit decision as calibration evidence.",
        })
    return actions


def build_next_actions_for_improve(result: dict[str, Any], *, command_prefix: str = "bin/hermes-self-improve") -> list[dict[str, Any]]:
    plan = result.get("plan") if isinstance(result.get("plan"), dict) else {}
    apply_result = result.get("apply") if isinstance(result.get("apply"), dict) else {}
    plan_id = plan.get("plan_id") or apply_result.get("plan_id")
    summary = apply_result.get("summary") if isinstance(apply_result.get("summary"), dict) else plan.get("summary", {})
    return build_next_actions_for_apply_preview({"plan_id": plan_id, "summary": summary, "execute": result.get("execute")}, command_prefix=command_prefix)
```

### Task 3.3: Attach next actions to CLI payloads

In `cli.py`:

- import helpers.
- `run_improve()` result includes `next_actions` when `execute=False`.
- `apply` preview result includes `next_actions` before printing JSON/human summary.
- `plan` result includes at least review/execute command after plan writing.

Human output should add a section:

```text
Next actions:
- Execute ready items: bin/hermes-self-improve apply <plan-id> --execute
- Record rejection: bin/hermes-self-improve outcome ...
```

No interactive prompt.

### Task 3.4: Tool handlers include next actions

`self_improvement_improve`, `self_improvement_apply`, and `self_improvement_plan` tool results should carry the same `next_actions` JSON.

### Task 3.5: Tests

Add/adjust tests:

- `tests/test_cli_surface.py`: `improve` preview handler prints `Next actions` and exits.
- `tests/test_report_integration.py`: report payload includes next actions for recent plan/apply if applicable.
- `tests/test_plugin_tools.py`: tool JSON includes `next_actions` for preview results.

Run:

```bash
$PY -m pytest tests/test_next_actions.py tests/test_cli_surface.py tests/test_report_integration.py tests/test_plugin_tools.py -q
```

**Commit:**

```bash
git add hermes_self_improvement/next_actions.py hermes_self_improvement/cli.py hermes_self_improvement/tool_handlers.py tests/test_next_actions.py tests/test_cli_surface.py tests/test_report_integration.py tests/test_plugin_tools.py
git commit -m "feat(self-improvement): show next actions for previews"
```

---

## Phase 4: Improve Outcome Recording for Rejected / Edited Decisions

**Objective:** Make it easy to record human rejection/edited/ignored outcomes after a preview, and ensure they improve later calibration.

**Files:**
- Modify: `hermes_self_improvement/outcome_store.py`
- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/calibration.py`
- Test: `tests/test_outcome_store.py`
- Test: `tests/test_calibration.py`
- Test: `tests/test_cli_surface.py`

### Task 4.1: Add plan/item binding validation for outcome recording

Outcome recording should remain append-only, but it can validate obvious malformed input.

Tests:

```python
def test_record_rejection_requires_plan_and_item_for_human_review(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    result = record_review_outcome(config=config, outcome={"outcome": "rejected_by_human", "reason": "too broad"})
    assert result["status"] == "failed"
    assert "plan_id_missing" in result["reasons"]
    assert "item_id_missing" in result["reasons"]
```

Apply/rollback inferred outcomes may still come from ledgers without human-supplied item id if ledger item IDs exist.

### Task 4.2: Add optional `--from-plan-item` convenience CLI

Optional but useful:

```bash
bin/hermes-self-improve outcome --outcome rejected_by_human --from-plan-item plan-id:step-002 --reason "too broad"
```

Parser fills `plan_id` and `item_id`. Keep explicit `--plan-id` / `--item-id` as canonical.

### Task 4.3: Calibration evidence distinguishes explicit human outcomes

Extend summary fields:

```json
"review_outcomes": 3,
"explicit_human_review_outcomes": 2,
"ledger_inferred_outcomes": 1,
"bad_outcomes": 2
```

Only explicit append-only outcomes should count as human review outcomes. Inferred ledger outcomes remain report-only unless explicitly configured later.

### Task 4.4: Next actions use outcome command examples

Ensure Phase 3 next actions produce valid commands for:

- rejected item
- edited before apply
- ignored stale

### Task 4.5: Tests and smoke

Run:

```bash
$PY -m pytest tests/test_outcome_store.py tests/test_calibration.py tests/test_cli_surface.py tests/test_next_actions.py -q
bin/hermes-self-improve outcome --outcome rejected_by_human --plan-id demo --item-id step-001 --reason "demo" --json --config /tmp/self-improve-outcome-smoke.json
```

Use temp config for smoke, not production runtime.

**Commit:**

```bash
git add hermes_self_improvement/outcome_store.py hermes_self_improvement/cli.py hermes_self_improvement/calibration.py tests/test_outcome_store.py tests/test_calibration.py tests/test_cli_surface.py tests/test_next_actions.py
git commit -m "feat(self-improvement): strengthen human outcome feedback"
```

---

## Phase 5: Optional Agent-Native Outcome Recording Tool

**Objective:** Add a bounded append-only plugin tool for outcome recording if the team accepts expanding tool surface from 7 to 8.

**Decision:** This phase is included in the plan because the user explicitly wants outcome recording after static validation / next actions. It should be implemented only after Phase 4. It intentionally expands the tool surface and docs must say why.

**Files:**
- Modify: `plugin.yaml`
- Modify: `hermes_self_improvement/schemas.py`
- Modify: `hermes_self_improvement/tool_handlers.py`
- Modify: `hermes_self_improvement/__init__.py`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `skills/operations/SKILL.md`
- Test: `tests/test_plugin_tools.py`

### Task 5.1: Write failing registration test

In `tests/test_plugin_tools.py`:

```python
def test_register_exposes_record_outcome_tool():
    mod = load_plugin_module()
    ctx = RecordingContext()
    mod.register(ctx)
    names = {name for name, _kwargs in ctx.tools}
    assert "self_improvement_record_outcome" in names
```

Expected: FAIL.

### Task 5.2: Add schema

In `schemas.py`, add `self_improvement_record_outcome` with fields:

- `outcome` required enum from `OUTCOME_VALUES`
- `plan_id`
- `item_id`
- `proposal_id`
- `ledger_id`
- `reason` short string
- `source` default `tool`
- `risk`
- `recommendation`
- `scorer`
- `target_kind`
- `change_type`
- `config_path`
- `config` test override

No file paths, no arbitrary content, no mutation options, no execute flag.

### Task 5.3: Add handler

In `tool_handlers.py`:

```python
def _handle_self_improvement_record_outcome_tool(args: dict[str, Any] | None = None, **_kw) -> str:
    args = args or {}
    try:
        result = record_review_outcome(config=_config_from_args(args), outcome={... source: args.get("source") or "tool"})
        if result.get("status") != "recorded":
            return tool_error("record_outcome_failed", reasons=result.get("reasons"), target_changed=False)
        return tool_result(result)
    except Exception as exc:
        return tool_error("record_outcome_failed", error_detail=str(exc), target_changed=False)
```

Import `record_review_outcome` directly. Do not shell out to wrapper CLI.

### Task 5.4: Register handler

Update `hermes_self_improvement/__init__.py` handler map and imports.

Expected plugin discovery after this phase:

- tools: 8
- hooks: 10
- error: null

### Task 5.5: Tests

- Handler writes append-only outcome under temp `_self_improvement_root`.
- Invalid outcome fails closed and `target_changed=false`.
- Plugin registration exposes 8 tools.
- Existing primary command surface remains unchanged.

Run:

```bash
$PY -m pytest tests/test_plugin_tools.py tests/test_outcome_store.py -q
python3 - <<'PY'
from hermes_cli.plugins import discover_plugins, get_plugin_manager
import json

discover_plugins(force=True)
info = [p for p in get_plugin_manager().list_plugins() if p['name'] == 'hermes-self-improvement']
print(json.dumps(info, ensure_ascii=False, indent=2))
PY
```

**Commit:**

```bash
git add plugin.yaml hermes_self_improvement/schemas.py hermes_self_improvement/tool_handlers.py hermes_self_improvement/__init__.py README.md AGENTS.md skills/operations/SKILL.md tests/test_plugin_tools.py
git commit -m "feat(self-improvement): expose outcome recording tool"
```

---

## Phase 6: Old Plan Archive / Deletion Cleanup

**Objective:** Reduce plan noise without losing canonical decisions needed for future maintenance.

**Files:**
- Modify: `.hermes/plans/README.md`
- Create: `.hermes/plans/archive/README.md`
- Move or delete old plan files after index summary is sufficient.

### Task 6.1: Classify existing plans

Current files to classify:

- Keep active until done:
  - `2026-04-30_155711-static-validation-next-actions-outcome-feedback.md`
- Keep completed canonical in root or archive with index summary:
  - `2026-04-30_114058-review-outcome-feedback-loop.md`
  - `2026-04-30_114059-memory-visibility-proof.md`
  - `2026-04-28_133233-simplified-self-improvement-surface.md`
- Archive superseded/historical:
  - `2026-04-26_185111-self-improvement-auto-apply-policy.md`
  - `2026-04-28_012243-dspy-gepa-integration.md`
  - `2026-04-29_175500-tool-mediated-skill-memory-mutation.md`
  - `2026-04-29_232451-semantic-mutation-agent-and-ledger-bound-restore.md`
  - `2026-04-30_003330-real-mutation-agent-and-judge.md`
  - `2026-04-30_080545-real-mutation-agent-hardening-detailed.md`
  - `2026-04-30_081449-memory-rollback-store-validation.md`
  - `2026-04-29_003219-self-improvement-runtime-home.md`
  - `2026-04-29_123816-gepa-eval-golden-cases.md`

### Task 6.2: Prefer archive move first

Move archived files:

```bash
mkdir -p .hermes/plans/archive
mv .hermes/plans/2026-04-26_185111-self-improvement-auto-apply-policy.md .hermes/plans/archive/
...
```

Update root `README.md` with short canonical summary and archive pointer.

Why archive first: historical plans encode design rationale and test references. Moving them out of root reduces noise while keeping auditability. Physical deletion can be done later if the user still wants it after seeing root cleaned up.

### Task 6.3: Tests / verification

Add or update a docs test if one exists; otherwise run:

```bash
find .hermes/plans -maxdepth 1 -type f -name '*.md' -print | sort
```

Expected root contains only:

- `README.md`
- active plan if still active
- maybe the newest completed canonical plans if the index says to keep them there

### Task 6.4: Mark this plan completed

After all phases finish:

- Update `.hermes/plans/README.md`: no active unfinished plans.
- Add completed note for this plan.
- Add a status note at top of this plan.

**Commit:**

```bash
git add .hermes/plans
git commit -m "docs(self-improvement): archive superseded implementation plans"
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
bin/hermes-self-improve improve --since-hours 24 --json
bin/hermes-self-improve report --since-hours 24 --json
python3 - <<'PY'
from hermes_cli.plugins import discover_plugins, get_plugin_manager
import json

discover_plugins(force=True)
info = [p for p in get_plugin_manager().list_plugins() if p['name'] == 'hermes-self-improvement']
print(json.dumps(info, ensure_ascii=False, indent=2))
PY
```

Expected:

- Full tests pass.
- `improve` without `--execute` exits and includes `next_actions`.
- No interactive UI appears.
- Invalid static targets become `rejected_by_planner`, never `ready`.
- `apply_policy` cannot override hard invariants.
- Outcome recording writes append-only records and feeds calibration evidence.
- If Phase 5 is implemented, plugin discovery shows tools `8`; otherwise docs explicitly say tool-native recording is still deferred.
- `.hermes/plans/` root is no longer noisy.

## Acceptance Checklist

- [ ] Static invariant validator exists and is tested.
- [ ] Plugin-owned docs/config targets cannot become ready items.
- [ ] Arbitrary docs/config targets cannot become ready items.
- [ ] Direct forward file/DB/provider-internal mutation types are mechanically rejected.
- [ ] Sensitive delete re-add and external provider exact restore are mechanically rejected.
- [ ] `apply_policy` expands only within hard invariant boundaries.
- [ ] `improve`, `plan`, and `apply` preview outputs include `next_actions` and exit normally.
- [ ] No interactive approval UI is introduced.
- [ ] Outcome recording can record rejection/edit/ignored decisions and feed calibration.
- [ ] Optional agent-native `self_improvement_record_outcome` is implemented or explicitly deferred with docs.
- [ ] Old plan noise is archived or deleted according to the chosen cleanup rule.
- [ ] Full tests pass.
- [ ] Changes are committed and pushed in logical slices.

## Recommended Commit Sequence

1. `docs(self-improvement): plan static validation and next actions`
2. `feat(self-improvement): reject invalid mutation targets statically`
3. `docs(self-improvement): separate invariants from apply policy`
4. `feat(self-improvement): show next actions for previews`
5. `feat(self-improvement): strengthen human outcome feedback`
6. Optional: `feat(self-improvement): expose outcome recording tool`
7. `docs(self-improvement): archive superseded implementation plans`
