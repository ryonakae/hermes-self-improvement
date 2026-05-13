# Tool-mediated skill / memory mutation plan

Created: 2026-04-29 17:55 JST
Repository: `/Users/ryo.nakae/.hermes/plugins/hermes-self-improvement`
Status: completed / absorbed into later semantic mutation and memory-safety implementation

> **Current note (2026-04-30):** This plan is no longer an active implementation checklist. Its still-relevant direction—tool-mediated skill mutation, built-in memory through the official memory tool, external provider-native correction/delete tools, and no direct fallback—has been implemented or refined by the semantic mutation / real backend / memory rollback validation plans. Do not restart from the old draft/Slice wording.

## Goal

Move `hermes-self-improvement` skill and memory mutation away from direct file editing and toward Hermes-native tool/provider semantics.

The plugin should plan improvements at a provider-neutral level, then execute them through a constrained mutation worker that uses Hermes-supported tools only:

- skill mutation through `skill_manage` only;
- built-in memory mutation through the built-in `memory` tool only;
- external memory mutation through the active memory provider's exposed tools only;
- no normal-path direct file, database, or provider-internal edits for skill/memory mutation.

This keeps self-improvement aligned with Hermes validation, tool-event recording, memory provider philosophy, and public tool semantics.

## Current context

Recent work completed the simplified primary surface baseline and proposal eval asset layout:

- primary surface is `improve / calibrate / plan / apply / rollback / report / status`;
- `--execute` is the only user-facing mutation boundary;
- `evals/proposal/rubric.json` and `evals/proposal/cases.jsonl` are repo-tracked public proposal eval assets;
- runtime/private eval cases will live outside the repo;
- plugin users do not maintain or promote public eval seed cases.

The current design discussion focuses on replacing direct skill/memory mutation with a tool-mediated mutation worker.

## Decisions already made

### 1. Mutation model config

Introduce plugin-local `model.mutation` for the isolated mutation worker model, similar in ergonomics to `model.llm` / `model.gepa`.

Example shape:

```yaml
model:
  mutation:
    provider: auto
    model: ""
    base_url: ""
    api_key: ""
    timeout: 45
    max_tokens: 1000
    extra_body: {}
```

This belongs to the plugin-local config model, not Hermes core root config. Secrets must use the same safe placeholder / local-config pattern as existing model configs.

### 2. Mutation execution policy is separate from model config

`model.mutation` selects the model. Execution semantics are plugin policy and implementation, not model config.

User-facing config may expose a coarse backend selection only if needed, for example:

```yaml
mutation:
  backend: hermes_agent
```

Do not expose provider fallback semantics as user-editable config.

The worker should be isolated from the current main agent/session. Do not recursively reuse the current main agent conversation as the mutation executor, and do not fall back to the current main model/session when `model.mutation` is unavailable. If the configured mutation worker cannot be created, fail closed.

The mutation worker should run with minimal tool surface for the requested target kind:

- skill mutation: skills toolset / `skill_manage` only;
- memory mutation: memory/provider tool surface only;
- no terminal/file/database tools as a fallback path for skill or memory mutation.

### 3. `fallback_to_direct` is plugin-owned and effectively false

Direct file/database/provider-internal editing must not be a normal fallback for skill or memory mutation. In short: no direct fallback.

This is not a user-tunable option. It is part of the plugin safety contract:

- if tool-mediated mutation succeeds, record normal ledger/validation;
- if it fails, fail closed;
- do not silently fall back to editing skill files, memory markdown, provider SQLite/Postgres, or provider private APIs.

### 4. Skill mutation uses `skill_manage` only

Skill mutation should be implemented as exact tool-mediated operations through Hermes `skill_manage`.

Initial allowed operation families:

- create;
- patch;
- edit;
- delete;
- write_file;
- remove_file.

The worker should receive exact target identity and operation intent from the apply plan. It must not infer arbitrary skill targets or broaden edits.

### 5. Memory mutation is provider-aware

Memory mutation must respect both built-in memory semantics and the active external memory provider semantics.

Hermes memory architecture findings from docs and implementation:

- built-in memory is always active and uses `MEMORY.md` / `USER.md` through the `memory` tool;
- one external memory provider may be active alongside built-in memory;
- `MemoryProvider` does not define common CRUD methods;
- provider capability is exposed through each provider's `get_tool_schemas()` / `handle_tool_call()` and provider-specific tools;
- built-in memory writes notify external providers only for `add` / `replace`, not `remove`.

Therefore, the plugin should not assume universal `add/update/delete` support.

### 6. Provider capability table is plugin-owned policy

Provider fallback semantics such as unsupported delete behavior are not user-editable config. They are plugin-owned policy, derived from Hermes docs / provider implementation and maintained in code/tests.

Initial capability summary:

| Provider | Add/store | Update | Delete/forget | Notes |
|---|---:|---:|---:|---|
| built-in `memory` | yes: `add` | yes: `replace` | yes: `remove` | substring-based curated memory tool |
| Hindsight | yes: `hindsight_retain` | no native update | no native delete | retain / recall / reflect only |
| Honcho | yes: `honcho_conclude` | limited: peer card update | limited: conclusion delete | delete is documented for PII removal; normal correction should self-heal / add conclusion |
| Mem0 | yes: `mem0_conclude` | no native update | no native delete | profile/search/conclude only |
| Holographic | yes: `fact_store add` | yes: `fact_store update` | yes: `fact_store remove` | local SQLite fact store with explicit IDs |
| RetainDB | yes: `retaindb_remember` | no native update | yes: `retaindb_forget` | delete by memory id |
| ByteRover | yes: `brv_curate` | no native update | no native delete | LLM curate model |
| Supermemory | yes: `supermemory_store` | no native update | yes: `supermemory_forget` | delete by id or best-match query |
| OpenViking | yes: `viking_remember` | no native update | no native delete | remember is extracted/indexed on commit |

### 7. `memory_delete` is an abstract requested operation

Apply plans may request provider-neutral operations such as:

```json
{
  "operation": "memory_delete",
  "target": "outdated memory content or identifier",
  "reason": "stale"
}
```

During apply, the mutation executor resolves the operation against the active provider and plugin-owned policy:

- if the provider exposes native delete/forget/remove, use it;
- if the provider intentionally does not expose delete, transform stale/incorrect/duplicate deletion intent into provider-native correction/supersede storage;
- never bypass provider semantics via direct file/database edits.

### 8. Unsupported delete behavior is policy-driven, not plan-permission-driven

The apply plan does not need to explicitly permit a conversion from delete to correction. If the plan requests `memory_delete`, the mutation executor uses plugin-owned provider policy to decide the concrete tool operation.

Examples:

- Hindsight: `memory_delete` for stale/incorrect memory -> `hindsight_retain` a correction/superseding fact.
- ByteRover: `memory_delete` for stale/incorrect memory -> `brv_curate` a correction/superseding fact.
- OpenViking: `memory_delete` for stale/incorrect memory -> `viking_remember` a correction/superseding fact.
- built-in memory: `memory(action="remove", old_text=...)` when target is unambiguous.
- Supermemory: `supermemory_forget(id=...)` or query-based forget when policy allows and evidence is sufficient.
- RetainDB / Holographic: native ID-based delete/remove where target identity is known.
- Honcho: use native conclusion deletion only for PII/sensitive removal when a concrete conclusion id is available; otherwise prefer corrective conclusion for stale/incorrect memories.

### 9. Sensitive deletion is not the same as stale deletion

Do not convert all unsupported deletes into correction memories.

Deletion reason must distinguish at least:

- `stale` / `incorrect` / `duplicate`: may be transformed into correction/supersede storage when native delete is unsupported;
- `pii` / `secret` / `harmful_instruction` / `sensitive`: must not be preserved as a correction memory when native delete is unsupported.

For sensitive deletion:

- use native delete/forget/remove only when the provider exposes it and the target identity is sufficiently specific;
- otherwise fail closed and surface human/provider-native remediation;
- do not retain a correction that repeats the sensitive content.

### 10. Mutation worker is an executor, not a planner

The worker may choose provider-native tool calls within resolved policy, but must not broaden scope or invent targets.

The plugin should pass a constrained execution context:

```yaml
active_memory_provider: hindsight
requested_operation: memory_delete
resolved_strategy: retain_correction
allowed_tools:
  - hindsight_retain
  - hindsight_recall
  - hindsight_reflect
forbidden:
  - direct_file_edit
  - direct_db_edit
  - unsupported_provider_api
policy_note: |
  Hindsight does not expose delete. Represent stale deletion intent as a correction or superseding retained memory.
```

The worker's freedom is limited to rendering the concrete provider-native memory content and invoking allowed tools.

## Dig decisions

### Q1 — Provider context shape

Decision: **hybrid context resolution**.

The plugin resolves the active provider, abstract operation, deletion reason, and provider policy into a concrete `resolved_strategy` before invoking the worker. The worker receives the strategy, allowed tools, forbidden actions, and policy notes, then performs only strategy-local rendering and tool invocation.

Example:

```yaml
active_memory_provider: hindsight
requested_operation: memory_delete
deletion_reason: stale
resolved_strategy: retain_correction
allowed_tools:
  - hindsight_retain
  - hindsight_recall
  - hindsight_reflect
forbidden:
  - direct_file_edit
  - direct_db_edit
  - unsupported_provider_api
policy_note: |
  Hindsight does not expose delete. Represent stale deletion intent as a correction or superseding retained memory.
```

Rejected alternatives:

- Fully pre-rendering every tool argument in the plugin would reduce the value of an LLM mutation worker.
- Passing provider name plus a policy table and asking the worker to choose the strategy gives the worker too much planning authority.

### Q2 — Delete-to-correction wording

Decision: **typed template + worker polishing**.

When native delete is unsupported and the deletion reason is stale/incorrect/duplicate, the plugin should pass structured correction fields and wording constraints to the worker. The worker may polish the final provider-native memory text, but must stay within the typed correction intent.

Example context:

```yaml
resolved_strategy: retain_correction
correction_type: supersede
stale_claim: "Ryo prefers X"
current_claim: "Ryo prefers Y"
wording_constraints:
  - do not repeat sensitive values
  - state that stale_claim is outdated
  - make current_claim the only actionable fact
  - keep under 300 chars
```

The plugin owns the correction type taxonomy, for example:

- `supersede`: old claim is replaced by a newer current claim;
- `invalidate`: old claim should no longer be trusted, no replacement known;
- `duplicate`: duplicate/noisy memory should be ignored in favor of canonical memory;
- `scope_narrow`: broad memory is too broad and should be narrowed.

Rejected alternatives:

- Fully fixed templates are safe but too rigid for different provider styles.
- Free-form worker wording gives too much room to reinforce stale claims or add noise.

### Q3 — PII / secret / harmful memory deletion boundary

Decision: **provider-native delete when available; otherwise fail closed for sensitive deletion**.

Sensitive deletion is not treated as a normal stale-memory correction. The plugin is responsible for classification and safety gating, but not for bypassing provider storage semantics.

Responsibility split:

- The plugin classifies deletion intent/reason (`stale`, `incorrect`, `duplicate`, `pii`, `secret`, `harmful_instruction`, `sensitive`, etc.).
- The plugin resolves whether the active provider exposes a native delete/forget/remove tool suitable for that reason.
- If native delete exists and target identity is sufficiently specific, the plugin may route the mutation worker to that provider-native delete operation.
- If native delete does not exist, the plugin fails closed and reports that provider-native remediation is required.
- The plugin must not use direct file/database/provider-internal edits to force erasure.
- The plugin must not create correction/tombstone memories that repeat sensitive content.

Provider examples:

- Honcho: conclusion delete may be used for PII removal when a concrete `delete_id` is known, matching Honcho's documented semantics.
- Supermemory / RetainDB / Holographic: native forget/remove can be used when an ID/query target is sufficiently specific and policy permits.
- Hindsight / Mem0 / ByteRover / OpenViking: no native delete is exposed in Hermes tools, so sensitive delete fails closed and surfaces human/provider-native remediation.

Rejected alternatives:

- Always failing closed would ignore providers that intentionally expose native delete/forget tools.
- Writing a generic tombstone such as "ignore a previous sensitive memory" is unreliable and can create false confidence that erasure happened.

### Q4 — Skill vs memory executor boundary

Decision: **common orchestrator + target-specific executors**.

Use a shared mutation orchestration layer for plan item handling, dry-run/execute boundary, ledger integration, worker lifecycle, result normalization, and validation flow. Delegate target-specific behavior to separate executors:

```text
MutationOrchestrator
  - loads/validates plan item
  - enforces --execute boundary and apply policy
  - invokes target executor
  - records ledger/result

SkillMutationExecutor
  - builds skill_manage-only context
  - validates exact skill operation and target
  - forbids direct skill file fallback

MemoryMutationExecutor
  - resolves provider policy and strategy
  - builds provider-aware context
  - handles stale vs sensitive delete semantics
  - forbids direct memory/provider storage fallback
```

Worker model invocation helpers may be shared, but policy/context builders should remain target-specific.

Rejected alternatives:

- Fully separate executors without a shared orchestrator duplicate apply/ledger/worker lifecycle logic.
- A single large `MutationExecutor` with `target_kind` branches risks memory-provider complexity leaking into skill mutation and makes safety review harder.

### Q5 — Implementation slices

Decision: **mixed first slice: dry-run provider policy/context resolution plus a minimal executable skill patch pilot**.

The first implementation slice should not make external memory mutation executable yet. It should first lock down provider policy resolution and worker context shape in dry-run form, while also proving the real mutation worker/tool loop with the least risky skill mutation path.

First slice contents:

- Add provider policy table and strategy resolver.
- Add `model.mutation` config loading/example shape.
- Add mutation context builder snapshots for skill and memory.
- Add dry-run output that shows how abstract memory operations resolve to provider-native strategies.
- Keep memory mutation execution disabled/dry-run only.
- Add a minimal executable `skill_manage` patch pilot for an exact, low-risk skill patch operation.
- Verify the pilot does not use direct file fallback.

Rationale:

- Memory provider semantics are too varied to implement executable mutation before policy/context tests exist.
- A pure dry-run slice would not validate the worker/tool execution path.
- Skill patch is the safest real tool-mediated pilot because it has one canonical Hermes tool surface (`skill_manage`) and no provider-dependent semantics.

Rejected alternatives:

- Policy-only dry-run first would delay discovering worker/tool-loop issues.
- Starting with executable skill mutation only would leave memory semantics under-specified and risk later architecture churn.

## Open design points to dig next

No remaining high-level design questions from the initial five-point dig set. Implementation can proceed after reviewing the updated plan and, if needed, splitting the first slice into concrete tasks.

## Proposed implementation slices

### Slice 1 — Policy/context dry-run plus minimal skill patch pilot

This slice matches the Q5 decision: memory remains dry-run-only, while one low-risk skill patch path proves tool-mediated execution.

- Add provider policy table in code, with tests for capability resolution.
- Add provider strategy resolver for abstract memory operations.
- Add `model.mutation` config shape to `config.example.yaml` and config loader.
- Add mutation worker prompt/context builder snapshots for skill and memory operations.
- Record how abstract memory operations resolve into provider-native strategies.
- Keep memory mutation execution disabled/dry-run-only.
- Add a minimal executable `skill_manage` patch pilot for exact low-risk skill patch operations.
- Ensure the pilot cannot use direct file fallback.
- Update README / AGENTS / operations skill references.

### Slice 2 — Full skill mutation via `skill_manage`

- Expand from patch pilot to skill create/patch/edit/delete/write/remove through `skill_manage` only.
- Preserve preview-first behavior and ledger/rollback data.
- Tests should mock tool execution and verify no direct file fallback.
- Validate that target identity and operation are exact and cannot be broadened by the worker.

### Slice 3 — Built-in memory mutation via `memory`

- Route built-in memory add/replace/remove through the built-in `memory` tool.
- Handle char limits, duplicate entries, ambiguous `old_text`, and remove failures.
- Verify external provider mirroring behavior remains Hermes-owned and not assumed by plugin.
- Fail closed when the runtime does not expose the memory tool rather than direct-editing memory files.

### Slice 4 — Hindsight-first external memory mutation

- Implement active provider detection for Hindsight.
- Support stale/incorrect `memory_delete` -> `hindsight_retain` correction.
- Support sensitive delete -> fail closed because Hindsight exposes no native delete in Hermes tools.
- Add regression tests for Hindsight delete semantics.

### Slice 5 — Provider coverage expansion

Add and test policy mappings for Honcho, Mem0, ByteRover, OpenViking, Holographic, RetainDB, and Supermemory.

## Likely files to change

Exact file names may change after inspection, but likely areas are:

- `hermes_self_improvement/config.py`
- `hermes_self_improvement/apply_plan.py`
- `hermes_self_improvement/apply_engine.py`
- new module such as `hermes_self_improvement/mutation_policy.py`
- new module such as `hermes_self_improvement/mutation_worker.py`
- `config.example.yaml`
- `README.md`
- `AGENTS.md`
- `skills/operations/SKILL.md`
- `skills/operations/references/safety-and-apply.md`
- tests under `tests/`

## Validation targets

At minimum:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
hermes self-improvement status
```

Additional tests should cover:

- provider policy resolution for every built-in external provider;
- unsupported delete behavior for stale vs sensitive deletion;
- no direct fallback when tool-mediated mutation fails;
- skill mutation allowed tools exactly `skill_manage`;
- memory mutation allowed tools exactly provider-native tools;
- dry-run resolution output before any executable mutation path is enabled.

## Risks

- LLM worker may over-interpret requests unless the execution context is tightly structured.
- Correction memories can pollute provider memory if wording is sloppy or if sensitive content is repeated.
- Provider implementations may change; policy table must be backed by tests and docs references.
- Direct fallback is tempting for local built-in files but violates the design goal and must remain disallowed for this feature.
- Current cron/subagent contexts may not expose the built-in `memory` tool; unsupported runtime contexts must fail closed rather than direct-editing memory files.

## Notes

The current active memory provider in this local environment was observed as Hindsight, but the plugin design must support all Hermes-supported memory providers and must not hard-code this installation's provider.
