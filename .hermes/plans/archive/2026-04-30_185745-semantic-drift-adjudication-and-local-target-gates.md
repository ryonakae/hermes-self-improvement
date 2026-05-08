> **Status:** Completed 2026-04-30. Implemented plan-time mutable-local skill target gates, content drift classification, semantic drift adjudication routing, mutation-agent stale/conflict stop outcomes, and ledger/report/calibration visibility for drift outcomes.

# Semantic Drift Adjudication and Local Target Gates Implementation Plan

> This plan reopened the apply safety slice after `archive/2026-04-30_155711-static-validation-next-actions-outcome-feedback.md`.

## Goal

Make skill / memory plan application less brittle without weakening safety:

1. Reject non-mutable-local skill targets mechanically during plan construction.
2. Keep apply-time target identity / provenance validation.
3. Replace “any target hash drift blocks everything” with structured drift classification and bounded semantic adjudication.
4. Give the mutation agent explicit stop authority when the current skill / memory no longer matches the plan premise.
5. Record skipped/stopped drift outcomes in apply summaries, ledgers, reports, and calibration evidence.

The intended result is a safer “good balance”: machine-checkable invalid targets are rejected early, recent harmless drift can be handled, stale/conflicting plans are stopped, and ambiguous semantic cases are routed to review instead of being forced through.

## Non-goals

- Do not revive approval artifacts, `execution_mode`, `apply-low-risk`, or user-facing expected-hash confirmation.
- Do not allow direct filesystem / DB / provider-internal forward mutation.
- Do not make LLM judgment a mutation permission bypass.
- Do not make plugin-owned docs/config/plans/bundled skills mutable targets.
- Do not enable memory rollback execution; `memory_rollback.supported=false` remains until the separate store/cache/session proof is complete.
- Do not auto-apply destructive / lifecycle operations such as `skill_delete`, `skill_rename`, `skill_merge`, `memory_delete`, or evaluator promotion.

## Current Context

- Hard static invariants already reject plugin-owned targets, arbitrary docs/config targets, direct forward mutation types, provider-internal exact restore, and sensitive delete re-add.
- Forward skill mutation uses a bounded semantic mutation agent with only `skills_list`, `skill_view`, and `skill_manage`.
- Built-in memory mutation uses the official `memory` tool; external memory mutation uses provider-native correction/delete tools only.
- `--execute` is the only user-facing mutation boundary.
- Current target hash drift is currently treated as a hard blocker. This is safe but too coarse for plans that sit for minutes or hours while other sessions / cron may update skills or memory.

## Key Decisions

### 1. Mutable-local skill target is a plan-time gate

A skill proposal must resolve to a mutable local skill during apply-plan construction. This is a deterministic provenance check, not an LLM/scorer decision and not an `apply_policy` knob.

Plan construction should reject as `rejected_by_planner` when the target is:

- missing or ambiguous;
- built-in;
- hub-installed;
- plugin-bundled;
- from external read-only skill dirs;
- an absolute path, `..`, or root-escape target;
- plugin-owned `skills/operations/**`;
- otherwise not confirmed by Hermes internal registry / provenance as mutable local.

Do not shell out to `hermes skills list --source local` for this decision. Use the same internal registry / provenance path the runtime uses.

Apply execution must still re-check target identity and provenance because the target can be deleted, shadowed, or resolved differently after plan creation.

### 2. Target identity drift remains a hard stop

If apply-time resolution shows that the target is no longer the same logical target, stop before starting the mutation agent.

Examples:

- same skill name now resolves to a different source;
- mutable local skill became non-local or read-only;
- target disappeared;
- a path / source / registry identity no longer matches the plan baseline;
- memory provider/store identity changed.

These are not semantic questions. LLM adjudication must not override identity/provenance failure.

### 3. Content hash drift should be classified, not always rejected

When the target identity is stable but content hash changed, first classify the drift mechanically.

Suggested drift classes:

- `no_drift`: baseline hash matches current target.
- `non_overlapping_drift`: target changed outside the planned edit region / anchor.
- `compatible_drift`: nearby content changed, but the planned intent may still apply.
- `superseded`: current target already contains an equivalent improvement.
- `conflicting_drift`: current target changed in a way that conflicts with the plan.
- `target_identity_drift`: target identity / provenance changed; hard stop.
- `unknown_drift`: insufficient evidence to classify safely.

Hard mechanical stops:

- `target_identity_drift`;
- sensitive memory drift;
- destructive / lifecycle drift;
- missing baseline/current content needed for safe comparison;
- patch anchor gone and no safe semantic rebase path exists.

### 4. Use LLM only for semantic drift adjudication

LLM judgment is useful for “good balance” cases, but only after deterministic gates have passed.

LLM drift adjudication may decide routing, not directly mutate targets. Allowed outcomes:

- `apply_original`: current target still supports the original planned mutation.
- `skip_superseded`: the intended change is already present or no longer needed.
- `rebase_with_semantic_mutation_agent`: let the bounded mutation agent re-express the same plan intent against current content.
- `needs_review`: unclear or risky; do not apply unattended.
- `reject`: stale/conflicting; do not apply.

The adjudicator input should be narrow and auditable:

- plan item id;
- target kind (`skill` / `memory`);
- target identity/provenance summary;
- plan creation time and elapsed time;
- baseline excerpt / anchor;
- current excerpt / relevant diff;
- planned change intent and rationale;
- mechanical drift class;
- scorer risk/recommendation/confidence;
- memory sensitivity flags when present.

The adjudicator output must include a short reason and cite which evidence drove the decision. It must not produce arbitrary new improvements beyond the plan item.

### 5. Time since plan creation affects strictness

Elapsed time should influence routing.

Recommended initial policy:

- `0-10m`: strict hash match is preferred; harmless non-overlapping drift may still continue.
- `10m-2h`: drift requires mechanical classification; compatible drift can use LLM adjudication.
- `2h-24h`: drift generally requires LLM adjudication; memory drift trends to `needs_review`.
- `>24h`: default to stale / re-plan unless adjudication confidently returns `skip_superseded` or a very narrow low-risk skill rebase.

These thresholds can be config defaults later, but hard safety invariants remain non-configurable.

### 6. Skill and memory drift use different strictness

Skill drift is often rebaseable because skills are structured Markdown and can be inspected through `skill_view`.

Memory drift should be stricter because memory can be short, provider-specific, cached, session-visible, or semantically superseded by newer user preferences.

For memory targets with content drift:

- prefer `skip_superseded`, `needs_review`, or `reject`;
- avoid `apply_original` unless drift is trivial and provider policy is explicit;
- never use delete/re-add as a workaround;
- keep sensitive memory as a hard stop.

### 7. Mutation agent receives explicit stale/conflict stop instructions

Even after plugin-side drift checks, the actual mutation agent must have a final semantic safety brake.

Before applying any mutation, the agent must:

1. read the current target through its allowed tools;
2. compare current content with the plan baseline excerpt, rationale, and intended change;
3. stop without mutating if the current target is materially different from the plan premise, already fixed, stale, contradictory, or uncertain.

The agent must not invent broader improvements to make the plan fit, edit unrelated sections, or use direct filesystem/provider internals.

Allowed mutation-agent outcomes:

- `applied`;
- `skipped_superseded`;
- `stopped_stale_target`;
- `stopped_conflict`;
- `stopped_uncertain_needs_review`;
- existing structured failure outcomes for tool/backend errors.

These outcomes must be structured and ledgered.

### 8. Ledger/report/calibration must preserve drift decisions

Apply summaries and ledgers should record:

- baseline hash;
- current hash used for classification;
- target identity/provenance summary;
- drift class;
- elapsed time bucket;
- adjudicator outcome when used;
- mutation-agent stop/skip outcome when used;
- final mutation status;
- reason, redacted where needed.

Reports should surface skipped/stopped items as useful outcomes, not only as failures. Calibration evidence should distinguish:

- hard invariant rejection;
- target identity/provenance rejection;
- content drift classification;
- LLM adjudication routing;
- mutation-agent stopped/skipped outcomes;
- human review outcomes.

## Proposed Implementation Phases

### Phase 0: Tests and terminology lock

**Objective:** Freeze expected statuses and reason codes before implementation.

**Files likely touched:**

- `tests/test_static_validation.py`
- `tests/test_apply_plan.py`
- `tests/test_apply_engine.py` or equivalent apply execution tests
- `tests/test_mutation_backend.py` / `tests/test_mutation_worker.py`
- `tests/test_report_integration.py`
- `tests/test_calibration.py`

**Tasks:**

1. Add tests for non-local skill targets becoming `rejected_by_planner` during plan construction.
2. Add tests for stable identity + content drift producing drift classification rather than unconditional rejection.
3. Add tests that identity/provenance drift remains a hard stop.
4. Add tests for mutation-agent stop outcomes being treated as non-mutating ledgered outcomes.

### Phase 1: Plan-time mutable-local skill gate

**Objective:** Move mutable-local skill validation into apply-plan construction.

**Expected behavior:**

- Valid mutable local skill proposal can become `ready` if all other policy checks pass.
- Non-local / ambiguous / plugin-bundled / external / built-in skill target becomes `rejected_by_planner`.
- Plan item stores stable target identity/provenance metadata needed for apply-time revalidation.

**Likely files:**

- `hermes_self_improvement/static_validation.py`
- `hermes_self_improvement/apply_plan.py`
- target resolver / skill snapshot modules if already present
- tests around skill target resolution

### Phase 2: Drift classification model

**Objective:** Introduce a structured drift classifier for stable-identity content drift.

**Expected behavior:**

- `no_drift` continues existing ready path.
- `target_identity_drift` remains hard stop.
- non-overlapping / compatible / superseded / conflicting / unknown classes are represented explicitly.
- memory drift defaults stricter than skill drift.

**Likely files:**

- new `hermes_self_improvement/drift.py` or similar
- `hermes_self_improvement/apply_engine.py`
- `hermes_self_improvement/apply_plan.py`
- ledger models / helpers

### Phase 3: Semantic drift adjudicator

**Objective:** Add an LLM-backed, narrow routing planner for compatible/unknown drift cases.

**Expected behavior:**

- Adjudicator never sees direct mutation tools.
- Adjudicator returns one of the allowed routing outcomes.
- Adjudicator cannot override hard invariant / identity / provenance failures.
- If LLM/provider is unavailable, fail closed to `needs_review` rather than applying.

**Likely files:**

- new `hermes_self_improvement/drift_adjudicator.py`
- `hermes_self_improvement/config.py` for thresholds/model config if needed
- `hermes_self_improvement/apply_engine.py`
- tests with fake LLM/adjudicator only; no live provider dependency

### Phase 4: Mutation-agent stale/conflict stop instruction

**Objective:** Give the tool-using mutation agent explicit authority and schema to stop safely.

**Expected behavior:**

- The mutation prompt requires reading current target before mutation.
- The agent compares current content with baseline/rationale/intent.
- The agent returns structured non-mutating outcomes when target is stale, conflicting, superseded, or uncertain.
- `skill_manage` / `memory` / provider tools are not called for stop/skip outcomes.

**Likely files:**

- `hermes_self_improvement/mutation_backend.py`
- `hermes_self_improvement/mutation_worker.py`
- mutation result schema definitions
- tests for structured outcomes and tool trace absence when stopped

### Phase 5: Ledger, report, and calibration integration

**Objective:** Make drift outcomes visible and useful for future evaluator improvement.

**Expected behavior:**

- Apply preview and execute summaries show drift class and next action.
- Ledgers store drift/adjudication/agent stop metadata.
- Reports distinguish skipped/stopped outcomes from hard failures.
- Calibration evidence can learn from stale/conflict/superseded outcomes.

**Likely files:**

- `hermes_self_improvement/ledger.py`
- `hermes_self_improvement/outcome_store.py` if explicit outcome records are reused
- `hermes_self_improvement/report` / CLI reporting helpers
- `hermes_self_improvement/calibration.py`
- `hermes_self_improvement/next_actions.py`

### Phase 6: Documentation and operational skill update

**Objective:** Align docs with the new target gate and drift semantics.

**Files:**

- `README.md`
- `AGENTS.md`
- `skills/operations/SKILL.md`
- `skills/operations/references/safety-and-apply.md` if needed
- `.hermes/plans/README.md`

**Docs must say:**

- mutable-local skill target is validated at plan construction and revalidated at apply;
- content drift is classified, not blindly rejected;
- identity/provenance drift remains a hard stop;
- LLM adjudication is routing only, not mutation permission;
- mutation agent has final stale/conflict stop authority;
- memory drift is stricter than skill drift.

## Suggested Status / Reason Codes

Use stable machine-readable names so report/calibration can aggregate them.

### Plan-time rejection reasons

- `skill_target_not_mutable_local`
- `skill_target_ambiguous`
- `skill_target_missing`
- `skill_target_plugin_bundled`
- `skill_target_builtin`
- `skill_target_hub_installed`
- `skill_target_external_readonly`
- `skill_target_path_escape`

### Drift classes

- `no_drift`
- `non_overlapping_drift`
- `compatible_drift`
- `superseded`
- `conflicting_drift`
- `target_identity_drift`
- `unknown_drift`

### Adjudicator outcomes

- `apply_original`
- `skip_superseded`
- `rebase_with_semantic_mutation_agent`
- `needs_review`
- `reject`

### Mutation-agent outcomes

- `applied`
- `skipped_superseded`
- `stopped_stale_target`
- `stopped_conflict`
- `stopped_uncertain_needs_review`

## Verification Checklist

Run from repository root.

```bash
uv sync --group dev
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
bin/hermes-self-improve status
```

For plugin registration/tool surface changes, also run:

```bash
$PY - <<'PY'
from hermes_cli.plugins import discover_plugins, get_plugin_manager
import json

discover_plugins(force=True)
info = [p for p in get_plugin_manager().list_plugins() if p['name'] == 'hermes-self-improvement']
print(json.dumps(info, ensure_ascii=False, indent=2))
PY
```

Expected: plugin enabled, `error: null`. Tool count should remain unchanged unless a later implementation explicitly changes schema.

## Commit Strategy

Use small commits by behavior boundary:

1. `test(self-improvement): cover mutable local target gates`
2. `feat(self-improvement): reject non-local skill targets during planning`
3. `feat(self-improvement): classify apply target drift`
4. `feat(self-improvement): adjudicate semantic drift before mutation`
5. `feat(self-improvement): stop stale mutation agent applications`
6. `feat(self-improvement): report drift apply outcomes`
7. `docs(self-improvement): document semantic drift apply policy`

Only push after tests pass for the completed slice. If a later slice exposes hidden coupling, split fixes into the smallest coherent commit.

## Open Questions

- Exact elapsed-time thresholds should start as defaults, but should they be config-visible immediately or kept internal until dogfooded?
- How much baseline excerpt should be stored for memory targets without over-retaining user content?
- Should `non_overlapping_drift` ever be auto-ready for memory, or always require adjudication/review?
- What is the best source of stable skill identity/provenance in current Hermes runtime APIs?
- Should `skip_superseded` automatically record an append-only outcome, or only ledger the skipped apply attempt?
