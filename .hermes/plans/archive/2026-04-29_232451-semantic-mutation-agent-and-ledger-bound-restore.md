# Semantic mutation agent and ledger-bound restore implementation plan

> **Status: completed / absorbed into later real-backend hardening as of 2026-04-30.** This plan established the current architecture, but it is not an active checklist. The relevant work landed across the semantic mutation commits, real mutation backend plan, hardening plan, and memory rollback validation plan. Use `.hermes/plans/README.md` as the current source of truth.

> **For Hermes:** Historical implementation record. Do not restart this plan from Slice 1; create a new follow-up plan if new semantic mutation work is needed.

**Goal:** Move skill and memory mutation from low-level mutation dict execution toward semantic mutation-agent tasks, while making rollback a plugin-owned deterministic `ledger_bound_restore` path.

**Architecture:** Forward mutation is semantic and agent-driven: the plugin creates bounded task intents and a Hermes mutation agent executes them with official Hermes skill/memory tools only. Verification, policy, scope checks, ledgers, and rollback remain plugin-owned. Rollback is not agent-driven; `self_improvement_rollback` / CLI reads a verified ledger and performs deterministic restore from snapshots via a dedicated recovery engine.

**Tech Stack:** Python, pytest, Hermes plugin tools, Hermes skill tools (`skills_list`, `skill_view`, `skill_manage`), Hermes memory/provider tools, existing `bin/hermes-self-improve` CLI.

---

## Scope and decisions captured

### Decisions

1. **Forward skill mutation uses semantic mutation-agent tasks.**
   - Applies to `skill_create`, `skill_improve`/small edits, `skill_large_rewrite`, `skill_delete`, `skill_rename`, `skill_merge`, `skill_write_file`, and `skill_remove_file`.
   - The plugin should not try to be a low-level patch planner for lifecycle operations.
   - The mutation agent receives a task such as “rename local skill A to B” or “merge source skill B into destination skill A”.

2. **The mutation agent runs using official Hermes features only.**
   - Prefer Hermes subagent/delegation behavior with restricted toolset.
   - Allowed skill tools: `skills_list`, `skill_view`, `skill_manage`.
   - Disallowed: terminal, file tools, git, direct filesystem mutation, direct DB/API/provider internals, plugin docs/config mutation.
   - If the runtime cannot provide a sufficiently bounded agent/tool surface, fail closed or keep item in `needs_review` rather than broadening tools.

3. **The plugin verifies agent results.**
   - Agent self-report is not authoritative.
   - The plugin checks target existence, scope, hashes, frontmatter validity, source deletion, destination content, declared operations, and allowed-tool usage.
   - Merge verification uses both checklist validation and an LLM planner.

4. **Rename/merge source deletion is immediate in final state, but verify-before-delete internally.**
   - Phase 1 mutation agent creates/updates/copies content and returns `ready_to_delete_source: true`.
   - Plugin runs checklist + LLM planner before source deletion.
   - Commit phase deletes the old/source skill after verification.
   - Final user-visible state is simple: rename means old gone/new exists; merge means source gone/destination integrated.

5. **Rollback is not handled by mutation agent.**
   - Rollback is deterministic recovery from ledger snapshots.
   - Implement as `ledger_bound_restore` in plugin-owned code.
   - This is separate from forward direct file mutation. Forward direct file/DB mutation remains prohibited.

6. **Rollback storage policy.**
   - Skill rollback uses full snapshots: `SKILL.md`, supporting files, existence map, category/path metadata, before/after hashes.
   - Built-in memory rollback can be programmatic if store format, locking, hashes, and cache invalidation are validated.
   - External memory provider rollback never touches provider internals directly; use provider-native/capability path only or mark unsupported/compensating correction.
   - Sensitive/secret/PII deletion is not rolled back by re-adding sensitive content.

7. **Mutable skill scope remains narrow.**
   - Only skills Hermes internally classifies as mutable local are eligible.
   - Do not mutate plugin-bundled, hub-installed, built-in, or external read-only skill dirs.
   - Do not shell out to `hermes skills list --source local` for plugin decisions.

### Non-goals for this implementation series

- Do not modify Hermes core.
- Do not add new actions to Hermes core `skill_manage`.
- Do not reintroduce generic forward direct file mutation.
- Do not make rollback behavior user-configurable beyond explicit `rollback --execute` intent.
- Do not mutate plugin README/AGENTS/config as self-improvement targets.

---

## Current baseline to preserve

Repository: `/Users/ryo.nakae/.hermes/plugins/hermes-self-improvement`

Known current modules:

- `hermes_self_improvement/apply_plan.py`
  - Produces apply plan items and currently supports tool-mediated mutation types.
  - Currently marks `skill_rename` / `skill_merge` unsupported.
- `hermes_self_improvement/apply_engine.py`
  - Executes ready plan items.
  - Current executable mutation types are `skill_manage_patch`, `skill_manage_operation`, `memory_tool_operation`, `memory_provider_tool_operation`.
  - Current rollback uses skill_manage-style rollback actions; this should be replaced or superseded by `ledger_bound_restore`.
- `hermes_self_improvement/mutation_worker.py`
  - Contains constrained tool-mediated executors for `skill_manage`, built-in memory, and provider memory tools.
- `hermes_self_improvement/mutation_policy.py`
  - Provider-aware memory capability/resolution policy.
- `hermes_self_improvement/ledger.py`
  - Pending ledger helper, currently schema `1.0` for pending item ledger.
- `hermes_self_improvement/cli.py`, `tool_handlers.py`, `schemas.py`
  - Primary command/tool surface.
- `tests/test_apply_plan.py`, `tests/test_apply_engine.py`, `tests/test_mutation_policy.py`, `tests/test_apply_ledger.py`, `tests/test_plugin_tools.py`, `tests/test_report_integration.py`
  - Existing tests around plan/apply/rollback/tool surface.

Required validation after each meaningful slice:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
bin/hermes-self-improve status
```

---

## Proposed implementation slices

### Slice 1: Document and freeze the new architecture

**Objective:** Make the new semantic-agent / ledger-bound-restore boundary explicit before touching runtime behavior.

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `skills/operations/SKILL.md`
- Modify: `skills/operations/references/safety-and-apply.md`
- Create or append: `skills/operations/references/mutation-agent-and-recovery.md` if the safety reference becomes too long
- Test: `tests/test_scheduled_execution_docs.py` or a new docs assertion test if existing docs tests cover operational docs

**Steps:**

1. Add a concise architecture section:
   - Forward mutation = semantic mutation agent with official Hermes tools only.
   - Rollback = plugin-owned `ledger_bound_restore` recovery engine.
   - Forward direct file/DB mutation remains forbidden.

2. Add explicit lifecycle definitions:
   - `skill_create`: mutation agent creates a valid skill.
   - `skill_improve`: mutation agent patches/edits as needed.
   - `skill_delete`: mutation agent or commit phase deletes only eligible local skill.
   - `skill_rename`: phase 1 create/copy new; verify; commit delete old.
   - `skill_merge`: phase 1 integrate into destination; verify; commit delete source.

3. Add rollback definitions:
   - skill snapshots are full snapshots.
   - built-in memory direct/programmatic restore is allowed only after store/locking/hash validation.
   - external memory provider internals are never touched.
   - sensitive delete has no re-add rollback.

4. Run doc grep to ensure no text says plugin executes `hermes skills list --source local`:

```bash
rg "hermes skills list --source local|direct file fallback|ledger_bound_restore|mutation agent" README.md AGENTS.md skills/operations
```

5. Commit:

```bash
git add README.md AGENTS.md skills/operations
git commit -m "docs(self-improvement): define mutation agent recovery architecture"
```

---

### Slice 2: Add schema types for semantic skill mutation tasks

**Objective:** Introduce structured task intent without executing it yet.

**Files:**
- Modify: `hermes_self_improvement/apply_plan.py`
- Modify: `hermes_self_improvement/config.py`
- Modify: `tests/test_apply_plan.py`
- Possibly modify: `tests/test_apply_policy.py`

**New mutation type:**

```json
{
  "type": "skill_agent_task",
  "task_kind": "skill_create|skill_improve|skill_delete|skill_rename|skill_merge|skill_write_file|skill_remove_file|skill_large_rewrite",
  "targets": {
    "primary_skill": "destination-or-target",
    "source_skill": "source-for-merge-or-rename",
    "new_skill": "new-name-for-rename-create"
  },
  "instructions": "semantic task prompt",
  "constraints": [
    "Use only skills_list, skill_view, skill_manage.",
    "Do not use terminal/file/git/direct filesystem tools.",
    "Operate only on mutable local skills resolved by the plugin."
  ],
  "expected_outcome": {
    "target_exists": true,
    "source_deleted_after_commit": true,
    "frontmatter_name": "..."
  },
  "verification_contract": {
    "checklist_required": true,
    "llm_planner_required": false
  }
}
```

**Behavior:**

- Keep existing `skill_manage_patch` / `skill_manage_operation` as compatibility path for low-risk simple mutations during transition.
- For lifecycle/broad semantic skill changes, generate `skill_agent_task` instead of `unsupported_skill_manage_operation`.
- Do not make `skill_agent_task` unattended-ready by default unless policy explicitly allows and execution engine supports it.
- `skill_rename` / `skill_merge` should become plan-able as `needs_review` or approval-required, not executable yet.

**Tests:**

1. `test_build_apply_plan_plans_skill_rename_as_agent_task_needs_review`
   - Proposal with `action: skill_rename`, `source_skill`, `new_skill`.
   - Expect mutation type `skill_agent_task`, `task_kind: skill_rename`.
   - Expect status `needs_review` / approval-required, not unattended.

2. `test_build_apply_plan_plans_skill_merge_as_agent_task_with_llm_planner_contract`
   - Proposal with source/destination.
   - Expect `verification_contract.llm_planner_required is True`.

3. `test_skill_agent_task_refuses_non_mutable_skill_targets`
   - Hub/built-in/external/plugin-bundled targets must not become executable.

4. `test_skill_agent_task_has_no_file_or_terminal_tools_in_constraints`
   - Check generated constraints.

**Validation:**

```bash
.venv/bin/python -m pytest tests/test_apply_plan.py tests/test_apply_policy.py -q
```

**Commit:**

```bash
git add hermes_self_improvement/apply_plan.py hermes_self_improvement/config.py tests/test_apply_plan.py tests/test_apply_policy.py
git commit -m "feat(self-improvement): plan semantic skill mutation tasks"
```

---

### Slice 3: Add snapshot model for skill rollback and verification

**Objective:** Capture full skill snapshots before semantic mutation so rollback can be deterministic.

**Files:**
- Create: `hermes_self_improvement/skill_snapshot.py`
- Modify: `hermes_self_improvement/apply_plan.py` or `apply_engine.py` where before snapshots are prepared
- Modify: `tests/test_apply_plan.py` or create `tests/test_skill_snapshot.py`

**Snapshot schema:**

```json
{
  "schema_name": "self_improvement_skill_snapshot",
  "schema_version": "1.0",
  "skill_name": "example-skill",
  "skill_path": "relative-or-absolute-resolved-path",
  "category": "optional-category",
  "skill_md": {
    "exists": true,
    "content": "---\nname: example-skill\n...",
    "sha256": "..."
  },
  "supporting_files": [
    {
      "path": "references/foo.md",
      "exists": true,
      "content": "...",
      "sha256": "..."
    }
  ],
  "file_set_hash": "hash over all files and paths"
}
```

**Implementation details:**

- Snapshot only mutable local skills.
- Reject symlinks and path traversal.
- Only include supporting files under `references/`, `templates/`, `scripts/`, `assets/`.
- Preserve empty supporting file content.
- Do not include hidden metadata directories except explicitly allowed supporting dirs.
- Compute stable hash via `_stable_json` + `_sha256_text` or bytes hash for content.

**Tests:**

1. Snapshot includes `SKILL.md` and supporting files.
2. Snapshot rejects skill outside mutable local root.
3. Snapshot rejects symlink escape.
4. Snapshot file_set_hash changes when content changes.
5. Snapshot excludes plugin-bundled/external skill path.

**Validation:**

```bash
.venv/bin/python -m pytest tests/test_skill_snapshot.py -q
```

**Commit:**

```bash
git add hermes_self_improvement/skill_snapshot.py tests/test_skill_snapshot.py
git commit -m "feat(self-improvement): capture skill rollback snapshots"
```

---

### Slice 4: Add `recovery_engine.py` and `ledger_bound_restore` for skills

**Objective:** Implement deterministic skill rollback from snapshots without mutation agents.

**Files:**
- Create: `hermes_self_improvement/recovery_engine.py`
- Modify: `hermes_self_improvement/apply_engine.py` rollback path to call recovery engine
- Modify: `hermes_self_improvement/cli.py` if rollback output changes
- Modify: `hermes_self_improvement/tool_handlers.py` if tool payload changes
- Test: create `tests/test_recovery_engine.py`
- Update: `tests/test_apply_engine.py`, `tests/test_plugin_tools.py` if old rollback expectations change

**Concept names:**

- Recovery action type: `ledger_bound_restore`
- Recovery mode: `skill_full_snapshot_restore`
- Do not call it `direct_file_mutation`.

**Recovery input:**

```json
{
  "type": "ledger_bound_restore",
  "target_kind": "skill",
  "restore_mode": "skill_full_snapshot_restore",
  "before_snapshot": {...},
  "expected_current_snapshot_hash": "...",
  "scope": {
    "mutable_local_skill_only": true,
    "skill_name": "..."
  }
}
```

**Algorithm:**

1. Load ledger.
2. Verify ledger hash.
3. Verify item hash / batch hash where applicable.
4. Resolve current target(s).
5. Verify current snapshot hash matches ledger expected current hash.
6. Verify target paths are within mutable local skill root and not plugin/hub/built-in/external.
7. Restore from full snapshot:
   - If snapshot says skill existed:
     - Create/replace skill dir contents exactly for allowed files.
     - Write `SKILL.md` and supporting files atomically.
     - Remove files that exist now but did not exist in snapshot, only under the skill directory and allowed supporting dirs.
   - If snapshot says skill did not exist:
     - Remove created skill dir, after verifying it matches expected created snapshot.
8. Verify final snapshot hash equals before snapshot hash.
9. Clear skill prompt cache if available, best-effort.
10. Write rollback ledger event.

**Important distinction:**

- This direct programmatic restore is allowed only in rollback path after ledger/hash/scope validation.
- Do not expose this machinery to apply/forward mutation.

**Tests:**

1. `test_ledger_bound_restore_recreates_deleted_skill_from_snapshot`
2. `test_ledger_bound_restore_reverts_modified_skill_md`
3. `test_ledger_bound_restore_restores_supporting_files_existence_map`
4. `test_ledger_bound_restore_rejects_ledger_hash_mismatch`
5. `test_ledger_bound_restore_rejects_current_hash_drift`
6. `test_ledger_bound_restore_rejects_external_skill_path`
7. `test_ledger_bound_restore_is_not_available_from_apply_mutation_path`

**Validation:**

```bash
.venv/bin/python -m pytest tests/test_recovery_engine.py tests/test_apply_engine.py tests/test_plugin_tools.py -q
```

**Commit:**

```bash
git add hermes_self_improvement/recovery_engine.py hermes_self_improvement/apply_engine.py hermes_self_improvement/cli.py hermes_self_improvement/tool_handlers.py tests/test_recovery_engine.py tests/test_apply_engine.py tests/test_plugin_tools.py
git commit -m "feat(self-improvement): add ledger-bound skill restore"
```

---

### Slice 5: Add mutation-agent task runner abstraction

**Objective:** Provide an execution abstraction for semantic mutation tasks without embedding low-level tool sequencing in apply engine.

**Files:**
- Create: `hermes_self_improvement/mutation_agent.py`
- Modify: `hermes_self_improvement/config.py`
- Modify: `hermes_self_improvement/apply_engine.py`
- Test: `tests/test_mutation_agent.py`

**Runner responsibilities:**

- Accept `skill_agent_task` mutation context.
- Build a self-contained agent prompt.
- Restrict tools to skills-only surface if runtime supports it.
- Return structured JSON result.
- Never fall back to current main conversation or broad tools.
- Fail closed if a bounded agent cannot be created.

**Prompt contract:**

The runner prompt must require JSON output like:

```json
{
  "success": true,
  "task_kind": "skill_merge",
  "used_tools": [
    {"tool": "skill_view", "target": "source"},
    {"tool": "skill_manage", "action": "edit", "name": "destination"}
  ],
  "changed_skills": ["destination"],
  "created_skills": [],
  "deleted_skills": [],
  "ready_to_delete_source": true,
  "merged_points": ["..."],
  "removed_as_duplicate": ["..."],
  "conflicts_resolved": ["..."],
  "supporting_files_moved": [
    {"from": "source:references/a.md", "to": "destination:references/source-a.md"}
  ],
  "verification_notes": ["..."],
  "rollback_hints": []
}
```

**Tool constraints in prompt:**

- Use only `skills_list`, `skill_view`, `skill_manage`.
- Do not use terminal/file/git/browser/web/delegation/cron/memory unless this is a memory task.
- Do not modify plugin files or arbitrary docs/config.
- Do not edit hub/built-in/plugin-bundled/external skills.
- Stop and return failure if asked to operate outside allowed targets.

**Implementation note:**

- First implementation may use existing Hermes delegation if it can restrict toolsets sufficiently.
- If `delegate_task` is not available inside plugin runtime, implement an adapter that returns `mutation_agent_unavailable` and leaves items failed/needs_review. Do not silently execute low-level sequence as fallback.
- Keep the runner behind a small interface so future Hermes-native agent execution can replace the adapter.

**Tests:**

1. Runner builds prompt with only allowed skill names and constraints.
2. Runner rejects task with non-local targets before launching agent.
3. Runner fails closed if bounded agent backend unavailable.
4. Runner parses structured JSON and rejects non-JSON/invalid schema.
5. Runner rejects self-reported disallowed tools.

**Validation:**

```bash
.venv/bin/python -m pytest tests/test_mutation_agent.py -q
```

**Commit:**

```bash
git add hermes_self_improvement/mutation_agent.py hermes_self_improvement/config.py hermes_self_improvement/apply_engine.py tests/test_mutation_agent.py
git commit -m "feat(self-improvement): add semantic mutation agent runner"
```

---

### Slice 6: Execute non-destructive semantic skill tasks through mutation agent

**Objective:** Start using the mutation agent for create/improve/write/remove operations while keeping lifecycle delete/rename/merge gated.

**Files:**
- Modify: `hermes_self_improvement/apply_engine.py`
- Modify: `hermes_self_improvement/apply_plan.py`
- Modify: `tests/test_apply_engine.py`
- Modify: `tests/test_plugin_tools.py`

**Behavior:**

- `skill_agent_task` with task kinds that do not delete source can execute when policy allows.
- Keep low-risk `skill_manage_patch` path temporarily for compatibility, but add deprecation note in comments/docs.
- Before executing, capture skill snapshots for rollback.
- After agent returns success, plugin verifies:
  - all changed skills are allowed targets;
  - no disallowed tool was reported;
  - `SKILL.md` valid frontmatter where applicable;
  - expected target exists/content changed;
  - snapshots/hashes captured.

**Tests:**

1. Apply preview reports would run mutation agent but does not mutate.
2. Apply execute with fake mutation agent updates skill and writes ledger.
3. Apply execute rejects agent result with disallowed tool.
4. Apply execute rejects agent result that claims success but target did not change.
5. Apply execute writes snapshot rollback data.

**Validation:**

```bash
.venv/bin/python -m pytest tests/test_apply_engine.py tests/test_plugin_tools.py -q
```

**Commit:**

```bash
git add hermes_self_improvement/apply_engine.py hermes_self_improvement/apply_plan.py tests/test_apply_engine.py tests/test_plugin_tools.py
git commit -m "feat(self-improvement): execute semantic skill mutation tasks"
```

---

### Slice 7: Implement two-phase rename and merge

**Objective:** Support `skill_rename` and `skill_merge` with verify-before-delete and immediate final deletion.

**Files:**
- Modify: `hermes_self_improvement/apply_plan.py`
- Modify: `hermes_self_improvement/apply_engine.py`
- Modify: `hermes_self_improvement/mutation_agent.py`
- Create or modify: `hermes_self_improvement/verification.py`
- Test: `tests/test_skill_lifecycle_agent.py`
- Update: `tests/test_apply_plan.py`, `tests/test_apply_engine.py`

**Two-phase flow:**

1. Capture snapshots:
   - rename: old source snapshot; new pre-existence snapshot (must normally not exist).
   - merge: source snapshot; destination before snapshot.
2. Launch mutation agent phase 1:
   - rename: create new skill, copy supporting files, do not delete old.
   - merge: integrate source into destination, copy/merge supporting files, do not delete source.
3. Plugin verification:
   - checklist verification.
   - LLM planner for merge.
4. Commit delete:
   - If verification passes, plugin performs source deletion.
   - This commit delete can use `skill_manage delete` or recovery-engine-controlled deletion with ledger binding; choose the simpler safe path and document it. Prefer `skill_manage delete` for forward commit because it is still forward mutation and official tool-mediated.
5. Final verification:
   - source gone;
   - destination/new exists;
   - hashes recorded.
6. Ledger finalization:
   - include snapshots, agent result, verification, planner result, commit delete result.

**Checklist verification:**

Rename:

- `new_skill` exists.
- `old_skill` still exists before commit delete.
- new `SKILL.md` valid.
- frontmatter `name` equals new name.
- new content not empty.
- supporting files declared by agent exist.
- no extra target skills changed.

Merge:

- destination exists.
- source still exists before commit delete.
- destination `SKILL.md` valid.
- destination content hash changed from before.
- `merged_points` non-empty.
- `removed_as_duplicate`, `conflicts_resolved`, `supporting_files_moved` present as lists.
- supporting files declared by agent exist.

LLM planner for merge:

Inputs:

- source before `SKILL.md` and supporting file summaries.
- destination before and after.
- agent `merged_points`, duplicates, conflicts.

Planner should output structured JSON:

```json
{
  "passed": true,
  "source_information_preserved": true,
  "no_obvious_contradictions": true,
  "no_major_duplicate_guidance": true,
  "safe_to_delete_source": true,
  "reasons": []
}
```

Fail closed on malformed planner output or negative result.

**Tests:**

1. Rename phase 1 success + verification + commit delete yields old gone/new exists.
2. Rename fails if new frontmatter name is wrong.
3. Rename does not delete old if verification fails.
4. Merge phase 1 success + checklist + planner pass deletes source.
5. Merge planner fail leaves source intact and marks item failed/needs_review.
6. Merge rejects empty `merged_points`.
7. Merge rejects unsupported/disallowed tool use in agent result.
8. Rollback after rename restores old and removes new via recovery engine.
9. Rollback after merge restores destination and source via recovery engine.

**Validation:**

```bash
.venv/bin/python -m pytest tests/test_skill_lifecycle_agent.py tests/test_apply_engine.py tests/test_apply_plan.py -q
```

**Commit:**

```bash
git add hermes_self_improvement/apply_plan.py hermes_self_improvement/apply_engine.py hermes_self_improvement/mutation_agent.py hermes_self_improvement/verification.py tests/test_skill_lifecycle_agent.py tests/test_apply_plan.py tests/test_apply_engine.py
git commit -m "feat(self-improvement): support semantic skill rename and merge"
```

---

### Slice 8: Built-in memory rollback research and implementation

**Objective:** Implement deterministic built-in memory rollback only if the store format and safe restore semantics are clear.

**Files:**
- Investigate Hermes built-in memory implementation in active Hermes source.
- Possibly create: `hermes_self_improvement/builtin_memory_restore.py`
- Modify: `hermes_self_improvement/recovery_engine.py`
- Modify: `hermes_self_improvement/mutation_policy.py`
- Test: `tests/test_memory_recovery.py`

**Research tasks:**

1. Locate built-in memory storage and write path.
2. Confirm whether `USER.md` / `MEMORY.md` are the actual mutable stores in this runtime path.
3. Confirm locking/atomic write/cache invalidation requirements.
4. Confirm whether direct programmatic restore is acceptable inside plugin rollback without breaking Hermes runtime.

**Implementation if safe:**

- Snapshot built-in memory before mutation:
  - target (`user` or `memory`), content, hash, file path/store id, schema/version if available.
- Restore in rollback:
  - verify ledger hash;
  - verify current hash;
  - write exact before content atomically;
  - invalidate/reload cache if available;
  - verify final hash.

**If unsafe or unclear:**

- Mark built-in memory rollback as `unsupported_pending_store_validation`.
- Keep rollback via `memory` tool only for reversible non-sensitive operations until safe direct restore is proven.
- Document the reason.

**External provider policy:**

- Do not direct-restore external providers.
- Provider-native correction/forget only.
- Sensitive delete rollback remains unsupported.

**Tests:**

1. Built-in memory snapshot captures user/memory target.
2. Restore verifies current hash before writing.
3. Restore refuses drift.
4. Restore refuses sensitive delete re-add.
5. External provider direct restore is rejected.

**Validation:**

```bash
.venv/bin/python -m pytest tests/test_memory_recovery.py tests/test_mutation_policy.py -q
```

**Commit:**

```bash
git add hermes_self_improvement/recovery_engine.py hermes_self_improvement/builtin_memory_restore.py hermes_self_improvement/mutation_policy.py tests/test_memory_recovery.py
git commit -m "feat(self-improvement): add ledger-bound built-in memory restore"
```

Use this commit message only if direct built-in restore is implemented. If not, use:

```bash
git commit -m "test(self-improvement): document memory restore safety boundaries"
```

---

### Slice 9: Replace legacy rollback path with `ledger_bound_restore`

**Objective:** Make `self_improvement_rollback` / CLI use recovery engine as the primary rollback path.

**Files:**
- Modify: `hermes_self_improvement/apply_engine.py`
- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/tool_handlers.py`
- Modify: `hermes_self_improvement/schemas.py` if payload schema changes
- Test: `tests/test_apply_engine.py`, `tests/test_apply_cli.py`, `tests/test_plugin_tools.py`

**Behavior:**

- `rollback <ledger-id>` preview shows planned ledger-bound restore actions.
- `rollback <ledger-id> --execute` performs deterministic restore.
- Refuse rollback when:
  - ledger hash mismatch;
  - current target hash drift;
  - missing snapshots;
  - target outside mutable local skill root;
  - external memory provider requires direct internals;
  - sensitive delete would be re-added.
- No mutation agent is launched by rollback.
- No `skill_manage` low-level reconstruction rollback remains as the primary path for snapshot-capable skill operations.

**Tests:**

1. CLI preview reports `ledger_bound_restore` actions.
2. CLI execute restores skill snapshot.
3. Tool handler returns `target_changed` true only after successful restore.
4. Rollback never calls mutation agent.
5. Rollback fails closed on tampered ledger.

**Validation:**

```bash
.venv/bin/python -m pytest tests/test_apply_engine.py tests/test_apply_cli.py tests/test_plugin_tools.py tests/test_recovery_engine.py -q
```

**Commit:**

```bash
git add hermes_self_improvement/apply_engine.py hermes_self_improvement/cli.py hermes_self_improvement/tool_handlers.py hermes_self_improvement/schemas.py tests/test_apply_engine.py tests/test_apply_cli.py tests/test_plugin_tools.py tests/test_recovery_engine.py
git commit -m "refactor(self-improvement): route rollback through ledger-bound restore"
```

---

### Slice 10: Retire or isolate old low-level skill mutation execution paths

**Objective:** Prevent the codebase from having two competing forward mutation models.

**Files:**
- Modify: `hermes_self_improvement/apply_plan.py`
- Modify: `hermes_self_improvement/apply_engine.py`
- Modify: `hermes_self_improvement/mutation_worker.py`
- Tests: existing apply/mutation tests

**Behavior:**

- Keep low-level `skill_manage_patch` only if needed for truly low-risk typo/pitfall additions during transition.
- Make lifecycle and broad skill changes agent-task only.
- Remove or mark deprecated any code that plans direct `skill_manage_operation` lifecycle sequences outside mutation-agent tasks.
- Keep memory provider worker path as currently tool-mediated unless/until a memory mutation-agent path is explicitly implemented.

**Tests:**

1. `skill_rename` / `skill_merge` never generate direct low-level operation sequence.
2. `skill_delete` either becomes semantic agent task or remains explicitly commit-phase controlled; document choice.
3. Generic direct file mutation remains unsupported.
4. Rollback recovery engine is not callable from apply execution.

**Validation:**

```bash
.venv/bin/python -m pytest tests/test_apply_plan.py tests/test_apply_engine.py tests/test_mutation_policy.py -q
```

**Commit:**

```bash
git add hermes_self_improvement/apply_plan.py hermes_self_improvement/apply_engine.py hermes_self_improvement/mutation_worker.py tests/test_apply_plan.py tests/test_apply_engine.py tests/test_mutation_policy.py
git commit -m "refactor(self-improvement): isolate legacy skill mutation paths"
```

---

### Slice 11: End-to-end integration tests and docs sync

**Objective:** Prove the final design works together and update operational docs.

**Files:**
- Modify/add integration tests:
  - `tests/test_report_integration.py`
  - `tests/test_plugin_tools.py`
  - `tests/test_apply_cli.py`
  - new `tests/test_skill_lifecycle_agent.py`
  - new `tests/test_recovery_engine.py`
- Modify docs:
  - `README.md`
  - `AGENTS.md`
  - `skills/operations/SKILL.md`
  - `skills/operations/references/safety-and-apply.md`
  - possible `skills/operations/references/mutation-agent-and-recovery.md`

**End-to-end scenarios:**

1. Create skill via semantic mutation agent, rollback deletes it.
2. Improve skill via semantic mutation agent, rollback restores before snapshot.
3. Rename skill via two-phase agent + plugin verification + commit delete, rollback restores old/removes new.
4. Merge skill via two-phase agent + checklist + LLM planner + commit delete, rollback restores source and destination.
5. Built-in memory rollback behavior matches chosen implementation/unsupported state.
6. External provider direct rollback is rejected.

**Full validation:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
bin/hermes-self-improve status
```

**Optional plugin discovery validation if tool schemas changed:**

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

**Commit:**

```bash
git add README.md AGENTS.md skills/operations tests hermes_self_improvement

git commit -m "docs(self-improvement): document mutation agent recovery workflow"
```

---

## Open implementation questions for the next session

These are implementation details, not design blockers:

1. **How exactly can the plugin launch a bounded Hermes mutation agent from inside plugin runtime?**
   - First inspect current Hermes plugin/delegation APIs.
   - If no safe bounded runner exists, implement an adapter that fails closed and plan the runtime integration separately.

2. **Can tool-call transcript be captured from mutation agent?**
   - Ideal: plugin records actual tool calls.
   - Minimum: agent returns structured `used_tools`, and plugin independently verifies final state. If actual transcript cannot be captured, mark ledger field `tool_trace_verified: false` and keep item higher-risk.

3. **Should commit-phase source deletion use `skill_manage delete` or recovery engine internal deletion?**
   - Since it is forward mutation, prefer `skill_manage delete`.
   - Recovery engine should be rollback-only.

4. **How to run LLM planner?**
   - Prefer existing Hermes auxiliary model path.
   - Do not invent plugin-specific API keys.
   - Fail closed on unavailable planner for merge execution.

5. **What to do with existing `skill_manage_patch` low-risk path?**
   - Keep short-term for compatibility.
   - Move toward `skill_agent_task` for all skill mutations after semantic runner is stable.

---

## Safety checklist for implementers

Before marking any slice complete, verify:

- [ ] No Hermes core files were modified.
- [ ] No forward direct file/DB/provider-internal mutation was introduced.
- [ ] Plugin docs/config are not self-improvement mutation targets.
- [ ] Only mutable local skills are eligible for skill mutation.
- [ ] External/built-in/hub/plugin-bundled skills are rejected.
- [ ] Mutation agent uses only allowed tools or fails closed.
- [ ] Rollback does not invoke mutation agent.
- [ ] Rollback verifies ledger hash and current target hash before restore.
- [ ] Rollback verifies final hash after restore.
- [ ] Sensitive memory delete is not restored by re-adding content.
- [ ] Full test command passes before commit/push.

---

## Suggested first implementation order in the new session

1. Start with Slice 1 docs, because it locks the architecture language.
2. Implement Slice 3 snapshots before agent execution; rollback needs snapshots.
3. Implement Slice 4 recovery engine for skills.
4. Only then implement Slice 5+ mutation agent runner.
5. Add rename/merge after recovery and verification are solid.

Do not start with rename/merge execution. That would create complex forward mutations before rollback safety exists.
