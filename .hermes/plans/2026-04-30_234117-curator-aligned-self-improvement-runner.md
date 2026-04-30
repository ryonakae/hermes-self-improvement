# Curator-Aligned Self-Improvement Runner Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task if delegating. Do not implement broad rollback/apply-plan compatibility while following this plan.

**Goal:** Rework `hermes-self-improvement` from an apply-plan/rollback framework into a Curator-aligned runner for skill, memory, and scorer/evaluator self-improvement.

**Architecture:** Keep the plugin centered on four surfaces: `improve`, `calibrate`, `report`, and `status`. `improve` and `calibrate` mutate by default, with `--dry-run` as the only preview mode. Runtime hooks produce non-Curator evidence, an evidence-pack builder combines that with Curator skill telemetry, and runner steps use LLM prompts to decide skill/memory/scorer/evaluator changes. Rollback, plan/apply, and explicit outcome-recording surfaces are removed.

**Tech Stack:** Python plugin under `hermes_self_improvement/`, Hermes plugin manifest/tools, pytest, Hermes skill/memory tools, Curator telemetry from Hermes core where available.

**Current working tree note:** At plan creation, the repo already had unrelated/unreviewed modifications in `AGENTS.md`, `README.md`, `hermes_self_improvement/config.py`, `skills/operations/SKILL.md`, and an archived plan rename. Do not overwrite or revert those unless they are explicitly part of this redesign.

---

## Decisions to Preserve

- Scope is only `skill`, `memory`, `scorer`, and `evaluator`.
- Do not add a new configurable “actor” abstraction. Use runner steps and internal prompts.
- Curator-owned telemetry is not duplicated by hooks.
- Hooks capture only data Curator cannot know: tool failures, memory operations, user correction/outcome signals, subagent outcomes, LLM/API failure metadata.
- Evidence pack uses `likely_targets` as a lightweight rule-based hint only. Step LLMs decide whether evidence is accepted, rejected, or out of scope for the step.
- Skill improvement is Curator-aggressive for local mutable skills: patch, supporting-file update, merge B into A, archive B, demote narrow skills into references/templates/scripts.
- Skill mutation must go through `skill_manage` only. No direct file fallback.
- Memory improvement supports conceptual add/replace/remove. Provider capability and fallback are passed to the LLM; runner only rejects capability violations.
- Memory mutation must go through memory/provider tools only. No direct file or provider DB mutation.
- External memory providers use provider recall/search. Built-in memory is passed as full text.
- Skill-vs-memory classification follows Hermes official docs: memory = compact “what” facts/sticky notes injected every session; skill = procedural “how” workflows/recipes/reference docs loaded on demand.
- Scorer/evaluator self-improvement changes rubric/prompt and runtime-private eval cases only. Python implementation code is not self-mutated.
- Eval cases come from human correction/outcome signals and scorer/evaluator disagreement. Runtime-private only.
- Rollback is removed as a primary feature. Keep only Curator-style archive restore semantics where applicable.
- Primary CLI/tool surface is only `improve`, `calibrate`, `report`, `status`.
- Delete `plan`, `apply`, `rollback`, and `record_outcome` surfaces completely.
- `improve` mutates by default. `improve --dry-run` previews.
- `calibrate` mutates by default if regression gate passes. `calibrate --dry-run` previews.
- Calibration inside `improve` may update active evaluator/scorer, but the change is next-run effect and must not influence skill/memory decisions in the same run.
- User-facing output is Curator-style: what changed, concise. Detailed artifacts remain for audit/report/next evidence, not rollback.

---

## Task 1: Remove legacy surface from manifest and schemas

**Objective:** Make the plugin expose only the four primary tools and update tool schemas to default to mutation with `dry_run` preview.

**Files:**
- Modify: `plugin.yaml`
- Modify: `hermes_self_improvement/schemas.py`
- Test: `tests/test_plugin_tools.py` or the existing schema/tool registration tests

**Steps:**
1. Remove these from `plugin.yaml` `provides_tools`:
   - `self_improvement_plan`
   - `self_improvement_apply`
   - `self_improvement_rollback`
   - `self_improvement_record_outcome`
2. In `schemas.py`, delete schema definitions and tool specs for plan/apply/rollback/record_outcome.
3. Update `SELF_IMPROVEMENT_IMPROVE_SCHEMA`:
   - Remove `items`.
   - Remove `execute`.
   - Add `dry_run: boolean default false`.
   - Description: run self-improvement; mutates by default; `dry_run` previews.
4. Update `SELF_IMPROVEMENT_CALIBRATE_SCHEMA`:
   - Remove `execute`.
   - Add `dry_run: boolean default false`.
   - Description: calibrates evaluator/scorer; mutates by default if gates pass; `dry_run` previews.
5. Update tests that assert tool count or tool names.

**Verification:**

```bash
python -m pytest tests/test_plugin_tools.py -q
```

Expected: only four plugin tools are registered.

---

## Task 2: Simplify tool handlers to four handlers

**Objective:** Remove tool-handler paths for plan/apply/rollback/record_outcome and map `dry_run` to internal execution semantics.

**Files:**
- Modify: `hermes_self_improvement/tool_handlers.py`
- Test: `tests/test_plugin_tools.py`

**Steps:**
1. Remove imports used only by deleted handlers: `apply_plan`, `rollback_apply_ledger`, `build_apply_plan`, `write_apply_plan`, `record_review_outcome`, apply preview next actions, rollback status if no longer needed by status.
2. Delete handlers:
   - `_handle_self_improvement_plan_tool`
   - `_handle_self_improvement_apply_tool`
   - `_handle_self_improvement_rollback_tool`
   - `_handle_self_improvement_record_outcome_tool`
3. Keep only status/report/improve/calibrate handlers.
4. Update improve handler to call `run_improve(..., dry_run=bool(args.get("dry_run", False)))`.
5. Update calibrate handler to call `run_calibration(..., execute=not dry_run)` or introduce `dry_run` in `run_calibration` if cleaner.
6. Remove item-id handling if no remaining caller uses it.

**Verification:**

```bash
python -m pytest tests/test_plugin_tools.py -q
python -m py_compile hermes_self_improvement/tool_handlers.py hermes_self_improvement/schemas.py
```

---

## Task 3: Replace CLI surface and execution semantics

**Objective:** CLI commands are only `status`, `report`, `improve`, and `calibrate`; `improve`/`calibrate` mutate unless `--dry-run` is present.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Modify: `bin/hermes-self-improve` only if command help/wrapper behavior requires it
- Test: CLI parser tests, improve/calibrate tests

**Steps:**
1. Remove subcommands: `plan`, `apply`, `rollback`, `outcome` / `record-outcome`, and legacy GEPA/debug commands if still exposed as primary commands.
2. Remove `--execute` from `improve` and `calibrate`.
3. Add `--dry-run` to `improve` and `calibrate`.
4. Change `run_improve` signature from `execute: bool` to `dry_run: bool`.
5. Inside `run_improve`, compute `mutate = not dry_run`.
6. Ensure calibration inside improve uses `execute=mutate`, while skill/memory decisions use the evaluator state from the start of the run. If implementation order makes this ambiguous, snapshot/load evaluator config before calibration and pass that snapshot to skill/memory steps.
7. Update user-facing summary text:
   - dry run: “Self-improvement dry run”
   - real run: “Self-improvement result”
8. Remove item-specific apply options.

**Verification:**

```bash
bin/hermes-self-improve --help
bin/hermes-self-improve improve --dry-run
bin/hermes-self-improve calibrate --dry-run
python -m pytest tests -q
```

Expected: deleted commands are absent; dry-run commands do not mutate.

---

## Task 4: Remove apply-plan and rollback framework from primary code paths

**Objective:** Stop building apply plans and ledgers as the central execution model.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Modify/delete references in `hermes_self_improvement/apply_plan.py`, `apply_engine.py`, `ledger.py`, `recovery_engine.py`, `drift.py`, `drift_adjudicator.py`, `verification.py`, `next_actions.py` as appropriate
- Modify tests that exist only for removed behavior

**Steps:**
1. Remove `build_apply_plan`, `write_apply_plan`, and `apply_plan` calls from `run_improve`.
2. Introduce or reuse a lightweight run artifact writer, e.g. `write_run_artifact(result, config)`, under `${HERMES_HOME}/self-improvement/runs/`.
3. Artifact should include:
   - evidence pack id/path
   - step decisions
   - skill changes
   - memory changes
   - calibration result
   - dry_run flag
   - concise summary
4. Delete or quarantine modules that are only rollback/apply-plan infrastructure. Prefer deletion if no remaining imports need them.
5. Remove tests that assert rollback/apply-plan behavior. Replace with tests for run artifacts and Curator-style output.

**Verification:**

```bash
python -m pytest tests -q
python - <<'PY'
import hermes_self_improvement.cli as cli
print('cli import ok')
PY
```

Expected: no imports of removed primary modules from CLI/tool handlers.

---

## Task 5: Add evidence-pack builder

**Objective:** Convert hook JSONL plus Curator telemetry into a structured evidence pack without generating proposals.

**Files:**
- Modify: `hermes_self_improvement/analysis.py`
- Possibly create: `hermes_self_improvement/evidence.py`
- Test: new `tests/test_evidence_pack.py`

**Steps:**
1. Add an evidence-pack schema with:
   - `schema_name: self_improvement_evidence_pack`
   - `schema_version`
   - `window`
   - `summary`
   - `evidence[]`
   - `views` for `skill`, `memory`, `scorer`, `evaluator`
   - `curator_telemetry_summary`
2. Build evidence kinds:
   - `tool_failure_evidence`
   - `memory_evidence`
   - `correction_evidence`
   - `subagent_evidence`
   - `llm_api_evidence`
   - `scorer_evaluator_evidence`
3. Add rule-based `likely_targets` as hints only. Allowed internal targets:
   - `skill`
   - `memory`
   - `scorer`
   - `evaluator`
4. Add `ignored` / `ignored_reason` for dropped events instead of adding `ignore` as a target.
5. Drop Curator-redundant events from evidence:
   - successful `skill_view` usage count
   - successful `skills_list` usage count
   - successful skill usage/lifecycle telemetry that Curator already records
6. Keep skill/memory tool failures.
7. Read Curator telemetry from Hermes skill usage state where available. If unavailable, continue without failing.

**Verification:**

```bash
python -m pytest tests/test_evidence_pack.py -q
```

Expected: successful skill views do not become evidence; tool failures and memory events do.

---

## Task 6: Implement official skill-vs-memory classification prompt block

**Objective:** Use Hermes official docs classification consistently in skill, memory, and scorer/evaluator steps.

**Files:**
- Modify/create prompt constants in the module that drives improvement steps
- Possibly modify: `hermes_self_improvement/mutation_policy.py`, `mutation_worker.py`, or new runner module
- Test: prompt/unit tests if existing

**Shared block content:**

```text
Memory is factual “what” knowledge: compact key facts, user preferences, environment facts, project locations, stable corrections, sticky-note-sized facts injected every session.

Skills are procedural “how” knowledge: multi-step workflows, tool-specific instructions, reusable recipes, pitfalls, verification steps, and reference-document-sized guidance loaded on demand.

If it belongs on a sticky note, prefer memory. If it belongs in a reference document or repeatable recipe, prefer skill.
```

**Steps:**
1. Define the shared block once.
2. Include it in skill improvement prompts.
3. Include it in memory improvement prompts.
4. Include it in scorer/evaluator rubric prompt/context.
5. Do not create separate config knobs for this classification.

**Verification:**

```bash
python -m pytest tests -q
```

Expected: prompt tests or snapshots show one shared classification source.

---

## Task 7: Implement skill improvement step with Curator-level operations

**Objective:** Allow aggressive local mutable skill improvements through `skill_manage` only.

**Files:**
- Modify: `hermes_self_improvement/mutation_backend.py` / `mutation_worker.py` / `mutation_agent.py` or replacement runner module
- Test: skill mutation tests

**Steps:**
1. Accept skill-related evidence view and Curator telemetry.
2. LLM step returns decisions for evidence: accepted/rejected/out-of-scope, with reasons in artifact.
3. LLM may choose operations:
   - patch local mutable skill
   - edit local mutable skill
   - update supporting files through `skill_manage.write_file` / `remove_file`
   - merge B into A by updating A then archiving B
   - archive local mutable skill
   - demote narrow skill content into A supporting files then archive source skill
4. Enforce target scope before executing:
   - allow local mutable skill only
   - reject built-in, hub-installed, plugin-bundled, external dirs, arbitrary docs/config, Hermes core
5. Execute only via `skill_manage` or Curator-compatible archive helper if exposed as the official skill lifecycle path. No direct filesystem fallback.
6. Keep artifact records of what changed, not rollback snapshots.

**Verification:**

```bash
python -m pytest tests/test_mutation_agent.py tests/test_mutation_backend.py -q
```

Expected: merge updates survivor and archives source; external/plugin-bundled targets are rejected.

---

## Task 8: Implement memory improvement step with provider capabilities

**Objective:** Let the LLM choose provider-compatible memory changes from evidence, capability, and related memory context.

**Files:**
- Modify: `hermes_self_improvement/mutation_policy.py`
- Modify: `hermes_self_improvement/mutation_worker.py`
- Possibly create: `hermes_self_improvement/memory_context.py`
- Test: memory mutation/provider capability tests

**Steps:**
1. Build memory step input:
   - memory evidence view
   - provider capability object
   - built-in memory full text if built-in provider is active
   - external provider recall/search results if external provider is active
2. Capability shape:
   ```json
   {
     "provider": "...",
     "supports_add": true,
     "supports_replace": false,
     "supports_remove": false,
     "fallback": {
       "replace": "add_superseding_memory",
       "remove": "add_correction_memory"
     }
   }
   ```
3. LLM may choose conceptual add/replace/remove or fallback add.
4. Runner validates only capability compatibility and required fields.
5. Execute through memory/provider tools only.
6. No direct `USER.md` / `MEMORY.md` editing.
7. No rollback/compensating rollback path. If a change is wrong, future evidence should correct it.

**Verification:**

```bash
python -m pytest tests/test_mutation_policy.py tests/test_mutation_worker.py -q
```

Expected: unsupported delete becomes correction/superseding add if LLM selected fallback; raw unsupported remove is rejected.

---

## Task 9: Runtime-private scorer/evaluator eval cases

**Objective:** Keep scorer/evaluator self-improvement focused on rubric/prompt and runtime-private eval cases.

**Files:**
- Modify: `hermes_self_improvement/calibration.py`
- Modify: `hermes_self_improvement/scoring.py`
- Modify: `hermes_self_improvement/gepa_adapter.py` if needed
- Test: calibration/scorer tests

**Steps:**
1. Generate eval cases only from:
   - human correction/outcome signals captured by hooks/session evidence
   - scorer/evaluator disagreement
2. Store generated cases under runtime-private self-improvement state, not repo-tracked eval assets.
3. Do not write user-derived eval cases into `evals/proposal/`.
4. Calibrate mutates by default; `--dry-run` previews.
5. Keep regression gate. If insufficient evidence or regression failure, no-op.
6. Do not self-modify Python scorer/evaluator implementation code.

**Verification:**

```bash
python -m pytest tests/test_calibration.py tests/test_gepa_eval_assets.py tests/test_gepa_optimizer.py -q
```

Expected: runtime eval cases are private artifacts; repo eval assets are unchanged.

---

## Task 10: Curator-style reports and status

**Objective:** Make user-facing output concise and action-oriented, while preserving detailed artifacts.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Modify: README docs
- Test: CLI output tests if present

**Report format:**

```text
Self-improvement result

Skill improvements:
- patched 2 skills
- merged old-skill into new-skill
- archived 1 skill

Memory improvements:
- added 2 memories
- replaced 1 memory
- added 1 correction memory because provider cannot delete

Scorer/evaluator:
- collected 3 private eval cases
- active evaluator unchanged

Artifact: ~/.hermes/self-improvement/runs/...
```

**Steps:**
1. Replace plan/apply/hash-heavy summaries with Curator-style summary.
2. `report` shows past runs/evidence/eval summaries.
3. `status` shows current readiness, last run, event path, Curator compatibility, and whether builtin Curator appears enabled/paused if detectable.
4. Do not print item hashes, target hashes, ledger IDs, JSON, or policy internals in normal output.

**Verification:**

```bash
bin/hermes-self-improve status
bin/hermes-self-improve report --since-hours 24
bin/hermes-self-improve improve --dry-run
```

Expected: concise human-readable output.

---

## Task 11: Delete obsolete modules/tests/docs references

**Objective:** Remove the complexity that no longer belongs to the product.

**Files:**
- Delete or shrink modules only used for removed primary features:
  - `hermes_self_improvement/apply_plan.py`
  - `hermes_self_improvement/apply_engine.py`
  - `hermes_self_improvement/ledger.py`
  - `hermes_self_improvement/recovery_engine.py`
  - `hermes_self_improvement/skill_snapshot.py` if only rollback uses it
  - `hermes_self_improvement/drift.py` / `drift_adjudicator.py` / `verification.py` if only apply-plan gates use them
  - `hermes_self_improvement/outcome_store.py` if no longer used for runtime-private outcome evidence
  - `hermes_self_improvement/next_actions.py` if only plan/apply preview uses it
- Modify: tests importing these modules
- Modify: README, AGENTS.md, `skills/operations/SKILL.md`

**Steps:**
1. Use `search_files` to find all references to deleted commands/modules.
2. Remove imports and tests tied only to deleted behavior.
3. Keep reusable code only if it directly serves the new runner.
4. Update docs to the new surface:
   - `improve` mutates
   - `improve --dry-run` previews
   - `calibrate` mutates when gates pass
   - `calibrate --dry-run` previews
   - no plan/apply/rollback/record_outcome
5. Update plugin-bundled operations skill. If `skill_manage` cannot patch plugin-bundled skill, edit repo file directly because it is part of this plugin repo, not runtime skill mutation.

**Verification:**

```bash
search_files "self_improvement_plan|self_improvement_apply|self_improvement_rollback|self_improvement_record_outcome|--execute|rollback|ledger" hermes_self_improvement tests README.md AGENTS.md skills -n
python -m pytest tests -q
```

Expected: no user-facing references to removed surfaces remain; only historical/archive docs may mention old terms if explicitly marked obsolete.

---

## Task 12: Full validation and commit

**Objective:** Prove the simplified plugin works and commit the redesign.

**Files:**
- All changed files

**Steps:**
1. Run compile checks:
   ```bash
   python -m py_compile __init__.py hermes_self_improvement/*.py
   ```
2. Run tests:
   ```bash
   python -m pytest tests -q
   ```
3. Run plugin discovery smoke:
   ```bash
   python - <<'PY'
   from hermes_cli.plugins import discover_plugins, get_plugin_manager
   import json
   discover_plugins(force=True)
   info = [p for p in get_plugin_manager().list_plugins() if p['name'] == 'hermes-self-improvement']
   print(json.dumps(info, ensure_ascii=False, indent=2))
   PY
   ```
4. Run CLI smoke:
   ```bash
   bin/hermes-self-improve status
   bin/hermes-self-improve improve --dry-run
   bin/hermes-self-improve calibrate --dry-run
   bin/hermes-self-improve report --since-hours 24
   ```
5. Inspect git diff.
6. Commit:
   ```bash
   git add .
   git commit -m "refactor(self-improvement): align runner with curator"
   ```

**Expected:** Tests pass, plugin exposes four tools, CLI exposes four commands, dry-run does not mutate, normal `improve` and `calibrate` are ready to mutate through official tool boundaries.
