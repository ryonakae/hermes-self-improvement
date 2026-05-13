# hermes-self-improvement Simplified Surface Implementation Plan

> **Status: completed / canonical historical baseline as of 2026-04-28.** The simplified surface has been implemented, tested, documented, committed, and pushed. Keep this plan as the completed implementation record and design baseline. Future work should start from repo docs and current code, not from the older approval/mode phases.
>
> **For Hermes:** This plan is no longer an active implementation checklist. Do not reintroduce approval/mode/hash ceremony from older plans. If new work conflicts with this baseline, create a new plan and update `.hermes/plans/README.md`.

**Goal:** `hermes-self-improvement` を「観測 → 必要なら evaluator/scorer 調整 → 改善計画 → policy に従った適用 → 報告」の自己改善ループに整理し、CLI / command / tool / config / apply model を本質的で扱いやすい形へ単純化する。

**Architecture:** User-facing surface は `improve / calibrate / plan / apply / rollback / report / status` に集約する。`--execute` を唯一の実変更意思表示にし、hash は user input ではなく内部整合性・drift 検知・ledger 用に閉じ込める。`calibration` は evaluator/scorer 自己調整の設定、`apply_policy` は通常改善の適用範囲として分ける。

**Tech Stack:** Python 3.11, pytest, Hermes user plugin API, existing modules under `hermes_self_improvement/`, wrapper CLI `hermes self-improvement`.

---

## Plan status and relationship to older plans

**Status:** completed / canonical historical baseline. When this plan conflicts with older `.hermes/plans/` documents, this plan wins unless a newer plan explicitly supersedes it.

Older plans were reviewed and folded in as follows:

- `2026-04-26_185111-self-improvement-auto-apply-policy.md` is superseded for user-facing safety model, command names, execution-mode policy, approval artifacts, and expected-hash UX. Its still-useful ideas are retained here as internal invariants: preview-first execution, ledger/rollback data, target hash drift checks, policy-controlled scope, and repo docs as source of truth rather than skills.
- `2026-04-28_012243-dspy-gepa-integration.md` is superseded for command surface (`gepa-eval`, `gepa-optimize`, approval-gated evaluator promotion). Its still-useful ideas are retained here under `calibrate`: lazy DSPy imports, Hermes-authenticated model routing, plugin-local model config, GEPA/LLM comparison, regression cases, active evaluator pointer/rollback, and evaluator self-improvement from outcome evidence.

The older plans should not drive new implementation directly. Keep them only as historical rationale. The current implementation baseline is the simplified surface documented in README, AGENTS.md, bundled operations skill, and this completed plan.

## 1. Current context / assumptions

### Current repo state observed before planning

- `git status --short` は clean。
- 主な実装規模:
  - `hermes_self_improvement/cli.py`: 1121 lines
  - `hermes_self_improvement/approvals.py`: 978 lines
  - `hermes_self_improvement/apply_plan.py`: 846 lines
  - `hermes_self_improvement/ledger.py`: 786 lines
  - `hermes_self_improvement/config.py`: 426 lines
  - `hermes_self_improvement/tool_handlers.py`: 319 lines
  - `hermes_self_improvement/schemas.py`: 219 lines
- 現在の surface は approval / low-risk / retention / GEPA などが露出しすぎている。
- 現在の `execution_mode` / command allowlist / capability gate / confirmation flag / expected hash の組み合わせが複雑化の中心。
- 既存 test には `test_execution_policy.py`, `test_apply_plan.py`, `test_apply_low_risk.py`, `test_approvals.py`, `test_evaluator_promotion.py`, `test_plugin_tools.py`, GEPA 系 tests がある。

### Design decisions from the discussion

#### User-facing commands

Keep these commands:

```bash
hermes self-improvement improve [--execute]
hermes self-improvement calibrate [--execute]
hermes self-improvement plan
hermes self-improvement apply <plan-id> [--execute]
hermes self-improvement rollback <ledger-id>
hermes self-improvement report
hermes self-improvement status
```

Expose matching plugin tools:

```text
self_improvement_status
self_improvement_report
self_improvement_improve
self_improvement_calibrate
self_improvement_plan
self_improvement_apply
self_improvement_rollback
```

Remove / deprecate from primary surface:

```text
execution_mode
approve
apply-approved
apply-low-risk
rollback-low-risk
approval artifact
expected_item_hash / expected_batch_hash as user-facing inputs
dry_run in config
require_item_hash
require_target_hash
maintenance command/tool
```

Integrate or postpone:

```text
ledger-report -> report
approval-report / validate-approval -> remove with approval artifact model
retention-report / retention-prune -> advanced/debug or later, not primary surface
gepa-eval / gepa-optimize -> calibrate internals or advanced/debug, not primary surface
```

#### Execution boundary

All mutation-capable commands are preview-only unless `--execute` is present.

```bash
improve          # preview only
improve --execute
calibrate        # preview only
calibrate --execute
apply <plan-id>  # preview only
apply <plan-id> --execute
```

`--execute` is the only user-facing mutation intent. Config decides what is allowed, not whether the current invocation mutates.

#### Plan / apply model

- `plan` is not just a list of candidates; it is an ordered, conflict-resolved set of edit steps.
- Plan generation resolves conflicts or marks items `needs_review` / `rejected_by_planner`.
- `apply` does not decide how to edit. It validates and executes ready steps from the plan.
- `apply <plan-id>` defaults to all `status=ready` steps.
- `apply <plan-id> --items step-001,step-002` remains available for manual/debug narrowing.
- `apply --execute` permits partial success:
  - `applied`: executed successfully
  - `skipped_by_policy`: ready but not allowed by policy
  - `failed`: policy allowed it, but validation/mutation/post-validation failed
- Fine-grained item states are ledger/debug details; user summary should remain coarse.

#### Hash model

- `item_hash`: always internally verified; never required as user input.
- `target_hash`: always verified by apply engine; not configurable.
- Batch apply tracks per-target accepted baseline:
  - initial baseline = plan item `before_hash`
  - after successful mutation, baseline becomes `after_hash`
  - if current file hash differs from accepted baseline, treat as external drift and fail/skips that step
- `batch_hash`: audit/ledger only; not user input.

#### Configuration model

`apply_policy` controls normal skill/memory improvement application:

```yaml
apply_policy:
  max_risk: low
  allow_destructive: false
  allowed_target_kinds:
    - skill
    - memory
  denied_change_types: []
  allowed_change_types: []  # empty means all non-denied change types
```

`calibration` controls evaluator/scorer self-adjustment. It is intentionally separate from `apply_policy`; setting `calibration.enabled: false` disables evaluator/scorer self-adjustment even when normal skill/memory improvement remains enabled.

```yaml
calibration:
  enabled: true
  evidence:
    window_days: 30
    min_evidence_events: 20
    min_disagreements: 5
    min_bad_outcomes: 2
  optimizer:
    max_full_evals: 2
```

`model.llm` and `model.gepa` remain plugin-local evaluator/scorer model settings. Keep `config.example.yaml` tracked and local `config.yaml` ignored. Calls should go through Hermes-authenticated auxiliary routing; do not introduce plugin-specific `.env` files or direct provider credential UX.

```yaml
model:
  llm:
    provider: auto
    model: ""
    base_url: ""
    api_key: ""
    timeout: 60
    max_tokens: 1800
    extra_body: {}
  gepa:
    provider: auto
    model: ""
    base_url: ""
    api_key: ""
    timeout: 120
    max_tokens: 1800
    extra_body: {}
```

Do not add:

```yaml
calibration:
  min_interval_hours: ...        # cron/scheduler responsibility
  run_before_improve: ...        # improve semantics, not config
  auto_promote_in_improve: ...   # execute semantics, not config
  regression:
    require_pass: ...            # invariant, not config
```

#### Calibrate / evaluator loop

- `calibrate` uses outcome evidence: failed applies, rollback, user correction/rejection, LLM-GEPA disagreement, scorer errors, regression failures.
- `calibrate` may no-op if evidence is insufficient.
- `calibrate --execute` may promote active evaluator/scorer candidates if:
  - calibration is enabled
  - evidence thresholds are met
  - candidate generation succeeds
  - regression passes
  - rollback data is recorded
- `improve` orchestrates:
  1. `calibrate` phase
  2. `plan` phase
  3. `apply` phase
  4. summary/report
- `improve --execute` executes the full loop. `improve` previews the full loop.

---

## 2. Proposed implementation approach

Implement in thin, testable vertical slices. Do not try to delete all legacy code in one commit. First introduce new simple APIs beside legacy paths; then migrate CLI/tools/tests; then remove legacy surface.

Recommended order:

1. Add new config schema and policy helpers.
2. Define new command/result contracts.
3. Add plan model refinements for ordered ready steps.
4. Add unified apply engine.
5. Add calibration service.
6. Add `improve` orchestration.
7. Replace CLI surface.
8. Replace plugin tool surface.
9. Update reports/docs/skills.
10. Delete or quarantine legacy approval/mode code.

---

## 3. Files likely to change

### Core implementation

- Modify: `hermes_self_improvement/config.py`
  - Remove execution mode as primary policy model.
  - Add `apply_policy` and `calibration` defaults/normalization.
  - Add simple policy evaluators.

- Modify: `hermes_self_improvement/cli.py`
  - Replace parser surface with `improve`, `calibrate`, `plan`, `apply`, `rollback`, `report`, `status`.
  - Keep old commands only as temporary hidden compatibility aliases if needed during migration, then remove.

- Modify: `hermes_self_improvement/apply_plan.py`
  - Rename/refactor plan generation to produce ordered ready steps.
  - Ensure conflict handling occurs during plan generation.
  - Store item hashes internally.

- Modify: `hermes_self_improvement/ledger.py`
  - Add unified apply ledger for batch/partial success.
  - Rename low-risk-specific functions to generic apply/rollback concepts.
  - Preserve rollback data for applied steps.

- Modify/Create: `hermes_self_improvement/apply_engine.py`
  - Prefer creating this new module to keep `ledger.py` and `apply_plan.py` from growing.
  - Implement preview/execute, policy filtering, target baseline tracking, live validation, mutation, post-validation, and result summary.

- Modify/Create: `hermes_self_improvement/calibration.py`
  - Implement evaluator/scorer calibration orchestration.
  - Use existing GEPA/LLM/scoring modules where possible.
  - Keep heavy dependency imports lazy.

- Modify: `hermes_self_improvement/scoring.py`
  - Ensure default plan scoring remains LLM + GEPA compare where available.
  - Surface disagreement evidence for calibration.

- Modify: `hermes_self_improvement/gepa_adapter.py`
  - Reuse optimizer/eval internals for `calibrate`.
  - Ensure regression pass is mandatory before active promotion.

- Modify: `hermes_self_improvement/approvals.py`
  - Remove from primary paths.
  - Either delete after tests migrate or leave as temporary unused legacy module until cleanup task.

- Modify: `hermes_self_improvement/schemas.py`
  - Replace tool schemas with simplified seven-tool surface.

- Modify: `hermes_self_improvement/tool_handlers.py`
  - Replace handler map with simplified seven-tool surface.
  - Remove mode/expected-hash/approval-specific handlers.

- Modify: root `__init__.py`
  - Register only simplified tool schemas/handlers.
  - Keep plugin discovery thin.

- Modify: `plugin.yaml`
  - Update tool definitions if manifest lists them.

### Docs / operational skill

- Modify: `README.md`
- Modify: `AGENTS.md` if command examples need updating.
- Modify: `skills/operations/SKILL.md`
- Modify: `skills/operations/references/safety-and-apply.md`
- Modify: `skills/operations/references/architecture.md` if present.
- Modify: `skills/operations/references/operations.md` if present.
- Modify: `.hermes/plans/2026-04-26_185111-self-improvement-auto-apply-policy.md` or add a successor roadmap note if that plan should stay historical.

### Tests

Likely update/create:

- Modify: `tests/test_config_precedence.py`
- Replace or rewrite: `tests/test_execution_policy.py`
- Modify: `tests/test_apply_plan.py`
- Replace or rewrite: `tests/test_apply_low_risk.py`
- Modify: `tests/test_apply_ledger.py`
- Modify: `tests/test_evaluator_promotion.py`
- Modify: `tests/test_report_integration.py`
- Rewrite: `tests/test_plugin_tools.py`
- Modify: `tests/test_cli_scorer_defaults.py`
- Modify: `tests/test_scorer_compare.py`
- Keep/adjust: `tests/test_gepa_*`

Add new tests:

- Create: `tests/test_apply_engine.py`
- Create: `tests/test_calibration.py`
- Create: `tests/test_improve_cli.py`
- Create: `tests/test_simplified_tool_surface.py` or fold into `test_plugin_tools.py`

---

## 4. Detailed task plan

### Phase 0: Safety branch and baseline inventory

#### Task 0.1: Confirm clean baseline

**Objective:** Ensure implementation starts from a clean tree and current behavior is known.

**Files:** none.

**Steps:**

1. Run:

   ```bash
   git status --short
   ```

   Expected: no unrelated modifications.

2. Run current tests for baseline:

   ```bash
   PY=${PYTHON:-python3}
   $PY -m py_compile __init__.py hermes_self_improvement/*.py
   $PY -m pytest tests -q
   ```

3. Save failing baseline output if current tests already fail. Do not fix unrelated failures in this task.

---

### Phase 1: Configuration and policy simplification

#### Task 1.1: Add minimal `apply_policy` defaults

**Objective:** Introduce simple application policy independent of execution modes.

**Files:**

- Modify: `hermes_self_improvement/config.py`
- Test: `tests/test_config_precedence.py`
- Test: `tests/test_execution_policy.py` or new `tests/test_apply_policy.py`

**Implementation details:**

Add defaults like:

```python
"apply_policy": {
    "max_risk": "low",
    "allow_destructive": False,
    "allowed_target_kinds": ["skill", "memory"],
    "allowed_change_types": [],
    "denied_change_types": [],
}
```

Add helper candidates:

```python
RISK_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def normalize_apply_policy(config: dict[str, Any]) -> dict[str, Any]:
    ...


def apply_policy_allows_item(item: dict[str, Any], policy: dict[str, Any]) -> tuple[bool, list[str]]:
    ...
```

Rules:

- Unknown risk should fail closed as not allowed.
- `destructive=true` requires `allow_destructive=true`.
- `target_kind` must be in `allowed_target_kinds` if list is non-empty.
- `denied_change_types` wins over `allowed_change_types`.
- If `allowed_change_types` is empty, all non-denied change types are candidates.

**Tests:**

- Default policy allows low-risk skill/memory non-destructive items.
- Default policy denies high risk.
- Default policy denies destructive.
- Default policy denies evaluator targets because `allowed_target_kinds` does not include `evaluator`; evaluator/scorer updates are controlled by `calibration`, not normal apply policy.
- Config override can allow medium/high risk or additional normal target kinds when explicitly configured.

---

#### Task 1.2: Add minimal `calibration` defaults

**Objective:** Introduce calibration config without scheduler-like options.

**Files:**

- Modify: `hermes_self_improvement/config.py`
- Test: `tests/test_config_precedence.py`
- New/Modify: `tests/test_calibration.py`

**Implementation details:**

Add defaults:

```python
"calibration": {
    "enabled": True,
    "evidence": {
        "window_days": 30,
        "min_evidence_events": 20,
        "min_disagreements": 5,
        "min_bad_outcomes": 2,
    },
    "optimizer": {
        "max_full_evals": 2,
    },
}
```

Do not add:

- `min_interval_hours`
- `run_before_improve`
- `auto_promote_in_improve`
- `regression.require_pass`

**Tests:**

- Defaults present after `load_config()`.
- Local YAML overrides evidence thresholds.
- Unknown extra keys are preserved or ignored consistently with existing config style.
- `regression.require_pass` is not required for behavior; promotion logic later enforces regression pass as invariant.

---

#### Task 1.3: Add plugin-local model config for LLM/GEPA

**Objective:** Preserve the useful model-routing design from the DSPy/GEPA plan while keeping it separate from calibration thresholds.

**Files:**

- Modify: `.gitignore`
- Create/Modify: `config.example.yaml`
- Modify: `hermes_self_improvement/config.py`
- Test: `tests/test_config_precedence.py`

**Implementation details:**

- Track `config.example.yaml`.
- Ignore local `config.yaml` and `config.local.yaml`.
- Keep JSON compatibility during migration.
- Support `${ENV}` expansion in YAML values.
- Keep calls routed through Hermes-authenticated auxiliary client paths.
- Do not create plugin-specific `.env` / `.env.example`.

Default shape:

```yaml
model:
  llm:
    provider: auto
    model: ""
    base_url: ""
    api_key: ""
    timeout: 60
    max_tokens: 1800
    extra_body: {}
  gepa:
    provider: auto
    model: ""
    base_url: ""
    api_key: ""
    timeout: 120
    max_tokens: 1800
    extra_body: {}
```

**Tests:**

- `config.example.yaml` shape matches defaults.
- local YAML can override `model.llm` and `model.gepa`.
- explicit missing/invalid config still fails closed.
- artifacts/reports redact `api_key` values.

---

#### Task 1.4: Stop adding new behavior to `execution_mode`

**Objective:** Freeze old execution mode model and prepare removal.

**Files:**

- Modify: `hermes_self_improvement/config.py`
- Modify: `tests/test_execution_policy.py`

**Implementation details:**

- Mark `VALID_EXECUTION_MODES`, `DEFAULT_MODE_POLICY`, `validate_mode_action`, `_required_capability_for_command` as legacy if immediate deletion is too large.
- New commands must not call `validate_mode_action`.
- New tests should assert simplified commands rely on `--execute` + policy, not mode.

**Tests:**

- New `improve/apply/calibrate` paths do not require `mode`.
- Legacy mode tests can be deleted once old commands are removed.

---

### Phase 2: Plan item model as ordered edit steps

#### Task 2.1: Define plan statuses and result vocabulary

**Objective:** Standardize names before code paths multiply.

**Files:**

- Modify: `hermes_self_improvement/apply_plan.py`
- Modify: `hermes_self_improvement/ledger.py`
- Test: `tests/test_apply_plan.py`

**Plan statuses:**

```text
ready
needs_review
rejected_by_planner
```

**Apply result statuses:**

```text
would_apply
applied
skipped_by_policy
failed
```

Avoid `rejected` for apply execution failures.

**Tests:**

- Plan generation emits `ready` for fully resolved edits.
- Conflicting/ambiguous proposals become `needs_review` or `rejected_by_planner`.
- Apply result status vocabulary does not include ambiguous `rejected` for execution failures.

---

#### Task 2.2: Ensure plan generation orders steps

**Objective:** Make `plan` responsible for order and conflict resolution.

**Files:**

- Modify: `hermes_self_improvement/apply_plan.py`
- Test: `tests/test_apply_plan.py`

**Implementation details:**

Each ready item should carry:

```json
{
  "item_id": "step-001",
  "status": "ready",
  "order": 1,
  "target_kind": "skill",
  "target_path": ".../SKILL.md",
  "change_type": "typo_fix",
  "risk": "low",
  "destructive": false,
  "operation": "replace_text_once",
  "before_hash": "...",
  "item_hash": "...",
  "mutation": {...},
  "rollback_preview": {...},
  "evidence": [...]
}
```

If multiple proposals touch the same exact text range or incompatible mutation target:

- merge if deterministic and safe, or
- mark one/both as `needs_review`, or
- mark duplicate as `rejected_by_planner`.

Do not defer conflict resolution to apply except live validation.

**Tests:**

- Multiple independent edits to same target get increasing `order`.
- Duplicate typo fixes for same old text do not both become ready.
- Section append + typo fix to same file can both be ready in order.

---

#### Task 2.3: Make `plan` command generate user-friendly summary plus artifact

**Objective:** `plan` remains manual/debug but does not force users to understand JSON internals.

**Files:**

- Modify: `hermes_self_improvement/cli.py`
- Test: `tests/test_improve_cli.py` or `tests/test_apply_plan.py`

**Output shape:**

Non-JSON output should include:

```text
Plan written: <path>
Plan id: <id>
Ready improvements: N
Needs review: N
Rejected by planner: N
Top targets:
- skill: X
- memory: Y
```

JSON output should preserve full artifact.

---

### Phase 3: Unified apply engine

#### Task 3.1: Create `apply_engine.py`

**Objective:** Centralize apply preview/execute logic and remove low-risk/approved split.

**Files:**

- Create: `hermes_self_improvement/apply_engine.py`
- Test: `tests/test_apply_engine.py`

**Core API proposal:**

```python
def apply_plan(
    *,
    plan_id: str,
    config: dict[str, Any],
    item_ids: list[str] | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    ...
```

Return summary:

```json
{
  "schema_name": "self_improvement_apply_result",
  "plan_id": "...",
  "execute": false,
  "target_changed": false,
  "summary": {
    "would_apply": 3,
    "applied": 0,
    "skipped_by_policy": 2,
    "failed": 1,
    "needs_review": 1
  },
  "items": [...],
  "ledger_path": null
}
```

**Tests:**

- `execute=False` never mutates target file.
- `execute=True` mutates only policy-allowed ready steps.
- Policy-disallowed ready steps become `skipped_by_policy`.
- Validation/mutation failure becomes `failed`.
- Partial success is allowed.

---

#### Task 3.2: Implement internal item hash validation

**Objective:** Preserve item integrity without user-facing expected hash inputs.

**Files:**

- Modify: `hermes_self_improvement/apply_engine.py`
- Possibly modify: `hermes_self_improvement/apply_plan.py`
- Test: `tests/test_apply_engine.py`

**Rules:**

- Each plan item includes `item_hash` computed from canonical policy-relevant payload.
- Apply recomputes item hash before preview/execute.
- If mismatch, item status becomes `failed` with reason `item_hash_mismatch`.
- User never supplies the hash.

**Tests:**

- Tampering with item mutation after plan write causes `item_hash_mismatch`.
- Untampered item passes.

---

#### Task 3.3: Implement target hash accepted baseline tracking

**Objective:** Always detect external drift while allowing same-batch self-applied changes.

**Files:**

- Modify: `hermes_self_improvement/apply_engine.py`
- Test: `tests/test_apply_engine.py`

**Rules:**

For each target path:

```text
accepted_baseline[target] = item.before_hash initially
on successful mutation: accepted_baseline[target] = after_hash
before each item: current_hash must equal accepted_baseline[target]
```

If current hash does not match accepted baseline:

- mark item `failed`
- reason `target_hash_mismatch`
- do not mutate that item

**Tests:**

- Two ready items for same file apply in one invocation.
- If file is externally modified before apply, first item fails.
- If item A changes file and item B follows in same invocation, item B sees updated accepted baseline and can apply.

---

#### Task 3.4: Implement unified ledger for partial apply

**Objective:** Record what happened at coarse and detailed levels.

**Files:**

- Modify: `hermes_self_improvement/ledger.py`
- Modify: `hermes_self_improvement/apply_engine.py`
- Test: `tests/test_apply_ledger.py`

**Ledger should include:**

```json
{
  "ledger_id": "...",
  "operation": "apply",
  "plan_id": "...",
  "execute": true,
  "batch_hash": "...",
  "summary": {
    "applied": 3,
    "skipped_by_policy": 2,
    "failed": 1
  },
  "items": [
    {
      "item_id": "step-001",
      "status": "applied",
      "target_path": "...",
      "before_hash": "...",
      "after_hash": "...",
      "rollback_data": {...}
    }
  ]
}
```

**Tests:**

- Preview does not write applied ledger, or writes a clearly preview-only artifact if needed.
- Execute writes ledger with applied/skipped/failed statuses.
- Applied items include rollback data.
- Skipped/failed items do not claim target mutation.

---

#### Task 3.5: Replace `apply-low-risk` CLI with `apply`

**Objective:** Move user-facing apply command to unified engine.

**Files:**

- Modify: `hermes_self_improvement/cli.py`
- Test: `tests/test_improve_cli.py`
- Replace/update: `tests/test_apply_low_risk.py`

**CLI:**

```bash
hermes self-improvement apply <plan-id>
hermes self-improvement apply <plan-id> --execute
hermes self-improvement apply <plan-id> --items step-001,step-002
hermes self-improvement apply <plan-id> --items step-001,step-002 --execute
```

No `--expected-item-hash`.
No `--mode`.
No `--confirm-apply`.

---

### Phase 4: Calibration

#### Task 4.1: Create calibration evidence collector

**Objective:** Gather evaluator/scorer improvement evidence from existing artifacts.

**Files:**

- Create: `hermes_self_improvement/calibration.py`
- Modify: `hermes_self_improvement/ledger.py` if helper readers are needed
- Test: `tests/test_calibration.py`

**Evidence sources:**

- LLM/GEPA scorer disagreements from plan/report artifacts.
- Apply ledgers with failed outcomes.
- Rollback ledgers/events.
- User correction/rejection events if present in telemetry.
- Scorer errors.
- Regression failures.

**Config usage:**

```python
calibration = config.get("calibration", {})
evidence_cfg = calibration.get("evidence", {})
```

Use:

- `window_days`
- `min_evidence_events`
- `min_disagreements`
- `min_bad_outcomes`

**Tests:**

- `enabled=false` returns no-op.
- Insufficient evidence returns no-op.
- Enough disagreements produces candidate-needed decision.
- Enough bad outcomes produces candidate-needed decision.

---

#### Task 4.2: Implement calibration preview result

**Objective:** `calibrate` without `--execute` should explain what would happen, without active updates.

**Files:**

- Modify: `hermes_self_improvement/calibration.py`
- Modify: `hermes_self_improvement/cli.py`
- Test: `tests/test_calibration.py`

**Result shape:**

```json
{
  "schema_name": "self_improvement_calibration_result",
  "execute": false,
  "current_status": "no_op" | "would_update" | "failed",
  "evidence_summary": {...},
  "candidate": {...},
  "regression": {...},
  "active_changed": false
}
```

**Tests:**

- Preview does not write active evaluator pointer.
- Preview can write candidate/report artifact if useful, but target active state remains unchanged.

---

#### Task 4.3: Implement `calibrate --execute` active promotion

**Objective:** Allow evaluator/scorer active update only after regression pass.

**Files:**

- Modify: `hermes_self_improvement/calibration.py`
- Modify: `hermes_self_improvement/gepa_adapter.py`
- Possibly reuse: `hermes_self_improvement/approvals.py` promotion internals before deleting
- Test: `tests/test_calibration.py`
- Modify: `tests/test_evaluator_promotion.py`

**Rules:**

- If calibration disabled: no-op.
- If evidence insufficient: no-op.
- If candidate generation fails: failed.
- If regression fails: failed or no-op, but never promote.
- If regression passes: promote active evaluator/scorer.
- Record active-before hash/pointer and rollback data.
- Do not require approval artifact.
- Do not expose expected hashes as user inputs.

**Tests:**

- Regression pass required as invariant.
- Regression failure does not promote.
- Successful execute writes active pointer and rollback ledger.
- Rollback can restore active-before state.

---

#### Task 4.4: Add `calibrate` CLI

**Objective:** Expose dedicated evaluator/scorer adjustment command.

**Files:**

- Modify: `hermes_self_improvement/cli.py`
- Test: `tests/test_improve_cli.py` or `tests/test_calibration.py`

**CLI:**

```bash
hermes self-improvement calibrate
hermes self-improvement calibrate --execute
hermes self-improvement calibrate --json
```

Non-JSON output:

```text
Calibration: no-op
Evidence: 8 events, 2 disagreements, 0 bad outcomes
Reason: insufficient_evidence
```

or:

```text
Calibration: updated
Evidence: 42 events, 7 disagreements, 3 bad outcomes
Regression: passed
Active evaluator: <path>
```

---

### Phase 5: `improve` orchestration

#### Task 5.1: Implement orchestration function

**Objective:** Add high-level loop used by CLI and tool.

**Files:**

- Modify/Create: `hermes_self_improvement/cli.py` or new `hermes_self_improvement/improve.py`
- Test: `tests/test_improve_cli.py`

**API proposal:**

```python
def run_improve(
    *,
    config: dict[str, Any],
    since_hours: int = 24,
    execute: bool = False,
    scorer: str = "compare",
) -> dict[str, Any]:
    ...
```

Flow:

1. Run calibration preview or execute according to `execute`.
2. Run plan generation using current active evaluator/scorer.
3. Write plan artifact.
4. Run apply preview or execute against that plan.
5. Build summary.

**Tests:**

- `execute=False` changes no targets and reports preview.
- `execute=True` applies policy-allowed plan steps.
- Calibration no-op still proceeds to plan/apply.
- Calibration failure is reported but should not necessarily block normal plan/apply unless active evaluator state is corrupted. Use fail-safe defaults.

---

#### Task 5.2: Add `improve` CLI

**Objective:** Make `improve` the normal user operation.

**Files:**

- Modify: `hermes_self_improvement/cli.py`
- Test: `tests/test_improve_cli.py`

**CLI:**

```bash
hermes self-improvement improve
hermes self-improvement improve --execute
hermes self-improvement improve --since-hours 24
hermes self-improvement improve --json
```

No `--mode`.
No `--confirm-*`.
No `--expected-*hash`.

**Non-JSON output:**

```text
Self-improvement preview
Calibration: no-op
Plan: <plan-id> ready=3 needs_review=1
Apply preview: would_apply=2 skipped_by_policy=1 failed=0
```

Execute output:

```text
Self-improvement result
Calibration: updated/no-op/failed
Plan: <plan-id>
Applied: 2
Skipped by policy: 1
Failed: 0
Ledger: <ledger-path>
```

---

### Phase 6: Report simplification

#### Task 6.1: Integrate ledger summary into `report`

**Objective:** Replace separate `ledger-report` with general report output.

**Files:**

- Modify: `hermes_self_improvement/cli.py`
- Modify: report rendering helpers in `hermes_self_improvement/cli.py` or create `reporting.py`
- Modify: `tests/test_report_integration.py`
- Modify: `tests/test_ledger_report.py`

**Report should include:**

- Recent plan summary.
- Recent apply summary.
- Applied/skipped/failed counts.
- Calibration summary.
- Needs-review highlights.

Do not include approval sections after approval artifact removal.

---

#### Task 6.2: Remove approval report sections

**Objective:** Stop referencing approval artifacts in report output.

**Files:**

- Modify: `hermes_self_improvement/cli.py`
- Modify: `tests/test_report_integration.py`
- Delete or quarantine: approval-specific tests after migration

**Tests:**

- Report does not mention approval gate summary.
- Report does mention apply/calibration summaries when artifacts exist.

---

### Phase 7: Plugin tool surface

#### Task 7.1: Replace schemas with seven simplified tools

**Objective:** Prevent agents from choosing legacy low-risk/approved tools.

**Files:**

- Modify: `hermes_self_improvement/schemas.py`
- Test: `tests/test_plugin_tools.py`

**Schemas:**

```text
self_improvement_status
self_improvement_report
self_improvement_improve
self_improvement_calibrate
self_improvement_plan
self_improvement_apply
self_improvement_rollback
```

Suggested parameters:

`self_improvement_improve`:

```json
{
  "since_hours": 24,
  "execute": false,
  "scorer": "compare",
  "config_path": "optional"
}
```

`self_improvement_calibrate`:

```json
{
  "execute": false,
  "config_path": "optional"
}
```

`self_improvement_plan`:

```json
{
  "since_hours": 24,
  "scorer": "compare",
  "config_path": "optional"
}
```

`self_improvement_apply`:

```json
{
  "plan_id": "required",
  "items": ["optional"],
  "execute": false,
  "config_path": "optional"
}
```

`self_improvement_rollback`:

```json
{
  "ledger_id": "required",
  "execute": false,
  "config_path": "optional"
}
```

No `mode`, no `confirm_*`, no `expected_*hash`.

---

#### Task 7.2: Replace tool handlers

**Objective:** Route tools to same core functions as CLI.

**Files:**

- Modify: `hermes_self_improvement/tool_handlers.py`
- Modify: root `__init__.py`
- Test: `tests/test_plugin_tools.py`

**Rules:**

- Handlers must not shell out to wrapper CLI.
- Handlers must call core Python functions used by CLI.
- `execute=false` must be preview-only.
- Payloads must include `target_changed` truthfully.

**Tests:**

- Registered tool names exactly match seven-tool surface.
- `self_improvement_apply` preview does not mutate.
- `self_improvement_apply` execute mutates policy-allowed item.
- `self_improvement_calibrate` preview does not promote active evaluator.
- `self_improvement_improve` calls calibrate/plan/apply flow.

---

### Phase 8: Rollback simplification

#### Task 8.1: Rename rollback low-risk path to generic rollback

**Objective:** Rollback should operate on applied ledgers regardless of original risk class.

**Files:**

- Modify: `hermes_self_improvement/ledger.py`
- Modify: `hermes_self_improvement/cli.py`
- Test: `tests/test_apply_ledger.py`

**CLI:**

```bash
hermes self-improvement rollback <ledger-id>
hermes self-improvement rollback <ledger-id> --execute
```

Preview without `--execute`; actual restore only with `--execute`.

No `--expected-ledger-hash` user input.
Ledger hash remains internal integrity check.

**Tests:**

- Rollback preview does not mutate.
- Rollback execute restores applied targets.
- Ledger tampering causes rollback failure internally.
- Current target drift after apply causes rollback failure unless rollback strategy supports it safely.

---

### Phase 9: Remove approval artifact model from primary path

#### Task 9.1: Delete or isolate approval module usage

**Objective:** Ensure primary commands and tools no longer depend on approval artifacts.

**Files:**

- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/tool_handlers.py`
- Modify: `hermes_self_improvement/schemas.py`
- Modify: `hermes_self_improvement/approvals.py` or delete if no imports remain
- Modify: `tests/test_approvals.py`
- Modify: `tests/test_evaluator_promotion.py`

**Approach:**

- First remove imports from CLI/tools.
- Migrate evaluator promotion tests to `calibrate --execute`.
- Delete approval-specific tests after equivalent coverage exists.
- If deleting module is too risky in one slice, leave `approvals.py` unused and schedule cleanup.

**Tests:**

- Searching for `approve`, `apply-approved`, `approval artifact` in CLI/tool tests should only find migration docs or none.
- Plugin discovery still succeeds.

---

### Phase 10: Docs and operational skill updates

#### Task 10.1: Update README command docs

**Objective:** Make docs match simplified surface.

**Files:**

- Modify: `README.md`

**Content:**

- Explain normal flow:

  ```bash
  hermes self-improvement improve
  hermes self-improvement improve --execute
  ```

- Explain manual flow:

  ```bash
  hermes self-improvement calibrate
  hermes self-improvement plan
  hermes self-improvement apply <plan-id>
  hermes self-improvement apply <plan-id> --execute
  ```

- Document config:

  ```yaml
  apply_policy:
    max_risk: low
    allow_destructive: false
    allowed_target_kinds: [skill, memory]

  calibration:
    enabled: true
    evidence:
      window_days: 30
      min_evidence_events: 20
      min_disagreements: 5
      min_bad_outcomes: 2
    optimizer:
      max_full_evals: 2
  ```

- Remove old approval/apply-low-risk docs.

---

#### Task 10.2: Update bundled operations skill

**Objective:** Ensure future agents use simplified commands.

**Files:**

- Modify: `skills/operations/SKILL.md`
- Modify: `skills/operations/references/safety-and-apply.md`
- Modify: `skills/operations/references/operations.md` if present
- Modify: `skills/operations/references/architecture.md` if present

**Content changes:**

- Replace `execution_mode` guidance with `--execute` boundary.
- Replace approval/low-risk command examples with `improve/calibrate/plan/apply/rollback`.
- State that hash checks are internal.
- State regression pass is invariant for calibration promotion.
- State cron can run `improve --execute` if desired, and config policy controls allowed scope.

---

#### Task 10.3: Update AGENTS.md quick commands

**Objective:** Keep contributor quick reference aligned.

**Files:**

- Modify: `AGENTS.md`

**Content:**

Replace current apply/approval command list with simplified flow and validation commands.

---

### Phase 11: Tests cleanup and validation

#### Task 11.1: Rewrite plugin tool parity tests

**Objective:** Ensure tool surface stays small.

**Files:**

- Modify: `tests/test_plugin_tools.py`

**Assertions:**

```python
expected = {
    "self_improvement_status",
    "self_improvement_report",
    "self_improvement_improve",
    "self_improvement_calibrate",
    "self_improvement_plan",
    "self_improvement_apply",
    "self_improvement_rollback",
}
assert names == expected
```

Also assert none of these appear:

```text
self_improvement_approve
self_improvement_apply_approved
self_improvement_apply_low_risk
self_improvement_rollback_low_risk
self_improvement_retention_prune
```

---

#### Task 11.2: Rewrite CLI parser tests

**Objective:** Prevent legacy commands from creeping back.

**Files:**

- Create/Modify: `tests/test_improve_cli.py`
- Modify: `tests/test_cli_scorer_defaults.py`

**Tests:**

- `improve` parses with optional `--execute`.
- `calibrate` parses with optional `--execute`.
- `apply` parses with plan id, optional `--items`, optional `--execute`.
- Old commands fail parse or are absent after final cleanup.
- Default scorer for planning remains `compare` unless intentionally overridden.

---

#### Task 11.3: Full validation suite

**Objective:** Verify simplified design does not break plugin loading.

**Commands:**

```bash
PY=${PYTHON:-python3}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
hermes self-improvement status
hermes self-improvement improve --json
hermes self-improvement calibrate --json
```

Plugin discovery check:

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

Expected: plugin enabled, error null, simplified tools registered.

---

## 5. Proposed commit slices

Use small commits. Suggested sequence:

1. `refactor: add simplified policy config`
2. `feat: add unified apply engine`
3. `feat: add calibration command`
4. `feat: add improve orchestration`
5. `refactor: simplify cli surface`
6. `refactor: simplify plugin tools`
7. `refactor: replace approval flow with execute boundary`
8. `docs: update self-improvement operations guide`
9. `test: update simplified self-improvement coverage`

If a slice becomes too large, split by module + tests.

---

## 6. Risks and tradeoffs

### Risk: Removing approval artifacts may drop audit detail

Mitigation:

- Ledger must record enough detail: plan id, item hashes, target hashes, policy, before/after hashes, diff, rollback data, calibration candidate metadata.
- Preview output should be readable.

### Risk: `improve --execute` may do too much at once

Mitigation:

- `--execute` is explicit.
- `calibration.enabled=false` disables evaluator/scorer updates.
- `apply_policy` limits normal skill/memory edits.
- Summary clearly separates calibration from normal apply.

### Risk: Calibration can self-reinforce bad evaluators

Mitigation:

- Outcome evidence required.
- Regression pass is invariant.
- Active-before state and rollback data are mandatory.
- No update if evidence insufficient.

### Risk: Batch partial success surprises users

Mitigation:

- Coarse summary must show applied/skipped/failed counts.
- Detailed JSON/ledger available for debugging.
- Rollback supports applied items.

### Risk: Legacy tests and docs encode old surface deeply

Mitigation:

- Implement new surface first, then delete old tests.
- Keep temporary compatibility only if needed during transition, but final target must remove old user-facing commands/tools.

---

## 7. Open questions

1. Should `plan` write one plan per `improve` invocation even if no ready items exist?
   - Recommended: yes, for audit/debug, but summary should say no actionable items.

2. Should `calibrate` write candidate artifacts on preview?
   - Recommended: yes if candidate generation is non-trivial, but active pointer must remain unchanged.

3. Should retention cleanup disappear entirely or move to hidden debug/admin command?
   - Recommended for this simplification: postpone. Do not expose as primary command/tool.

4. Should old `approvals.py` be deleted immediately?
   - Recommended: remove primary imports first, migrate tests, then delete in a cleanup commit if no references remain.

5. Should `allowed_change_types` be included in v1 `apply_policy`?
   - Recommended: include both `allowed_change_types` and `denied_change_types`, but default `allowed_change_types=[]` means all non-denied change types.

---

## 8. Acceptance criteria

Implementation is complete when:

- `hermes self-improvement improve` previews full loop without mutating targets.
- `hermes self-improvement improve --execute` runs calibration/plan/apply and mutates only allowed changes.
- `hermes self-improvement calibrate --execute` can promote evaluator/scorer only after regression pass.
- `hermes self-improvement plan` writes ordered, conflict-resolved plan artifacts.
- `hermes self-improvement apply <plan-id> --execute` applies ready policy-allowed steps with partial success ledger.
- `hermes self-improvement rollback <ledger-id> --execute` restores applied changes when safe.
- User-facing CLI has no `approve`, `apply-approved`, `apply-low-risk`, `rollback-low-risk`, `execution_mode`, `expected_*hash`, or `maintenance` primary command.
- Plugin tool surface is exactly seven simplified tools.
- Docs and bundled operations skill no longer instruct users/agents to use approval/low-risk/mode/hash ceremony.
- Full tests and plugin discovery pass.
