# Knowledge Transaction Source-of-Truth Cleanup Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task. This is a cleanup/hardening child plan after `2026-05-28-unified-knowledge-planner-editor-execution.md`; do not loosen mutation gates or add new memory/skill candidate behavior while implementing it.

**Goal:** Make `knowledge_transactions` the single source of truth for improve artifacts, summaries, episodes, compact tool results, and replay-like runtime reporting, so old split skill/memory lanes cannot silently influence current behavior.

**Architecture:** Keep the existing unified planner/editor execution path. This plan removes or quarantines legacy split-lane readers (`step_decisions.skill`, `step_decisions.memory`, `step_decisions.memory_to_skill`) from current run/report surfaces and moves any still-needed historical replay support behind explicit legacy helpers. Canonical transaction objects and `transaction_result` remain the runtime contract; skill and memory are distinguished by `transaction_kind`, `target_store`, and `operation`, not by separate lanes.

**Tech Stack:** Python, pytest, Hermes standalone plugin runtime artifacts, current `run_knowledge_improvement_step`, `execute_knowledge_transaction`, CLI/tool summary helpers, episode ledger.

---

## Why this plan exists

The unified execution path now works in both dry-run and scheduled mutating cron:

- Dry-run hardening artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260528T173940Z.json`
  - no split `step_decisions.skill` / `memory` / `memory_to_skill` lanes
  - `action_summary {'apply': 1, 'block': 0, 'defer': 0, 'skip': 45}`
  - `skill_editor_task_count: 1`
  - `actionability_loss_count: 0`
- Scheduled 2026-05-29 04:00 maintenance artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260528T190237Z.json`
  - job status `ok`
  - actual mutations: `skill_changes: ['safe-patch-usage']`, `memory_changes: []`
  - `actionability_loss_count: 0`
  - no split final `step_decisions.skill` / `memory` / `memory_to_skill` lanes

However, code inspection still finds legacy split-lane readers and helpers:

- `runner_steps.py` still defines `run_skill_improvement_step(...)`, `run_memory_improvement_step(...)`, and `apply_memory_to_skill_migrations(...)`.
- `tool_handlers.py` still falls back to `step_decisions.get('skill')` and computes skill lifecycle from split decisions.
- `episodes.py` still has split `skill` / `memory` episode loops for non-canonical paths.
- `cli.py` still contains historical/read-only summaries and replay paths that reconstruct split `memory_to_skill` state.
- `runtime_eval_cases.py` still falls back to split `step_decisions.skill.planner_quality` when canonical `knowledge_quality` is absent.
- Some source still uses `planner_skill` as a compatibility/default transaction kind.

This is acceptable as transitional code, but it is the next complexity risk. Future work such as memory candidate expansion should not be built on top of split-lane fallbacks.

---

## Non-goals

- Do not change planner safety/evidence gates.
- Do not make memory candidates more or less likely to be selected.
- Do not force a mutating dogfood just to prove `apply > 0`.
- Do not remove lower-level skill or memory editor helpers if `execute_knowledge_transaction(...)` still uses them internally.
- Do not break historical report reading for old artifacts without an explicit fallback label.
- Do not reset runtime artifacts unless a test or smoke run proves current runtime data blocks the canonical path.
- Do not edit Hermes core, plugin config, cron jobs, or runtime prompt overlays as part of this cleanup.

---

## Desired final contract

For current `improve` / `report` / plugin tool outputs:

1. Current-run source of truth is:
   - top-level `knowledge_transactions`
   - `step_decisions.knowledge_transactions`
   - `step_decisions.knowledge_quality`
   - `step_decisions.knowledge_routing`
   - `step_decisions.editor_validation`
2. Split `step_decisions.skill`, `step_decisions.memory`, and `step_decisions.memory_to_skill` are not read by current summaries when canonical transactions are present.
3. Any support for old artifacts is explicit and isolated behind helper names such as `legacy_split_*`, with tests proving it is not used for canonical artifacts. Historical split artifacts remain read-only/report/replay compatibility only; they must not become the current mutation source of truth.
4. Transaction kinds are canonical: `skill`, `memory`, `memory_to_skill`, `placement_move`, `none`, `unresolved`. No new runtime-facing `planner_skill` pseudo-kind should be emitted for canonical transactions.
5. Skill lifecycle, memory mutation counts, created/patched/archived skills, changed/removed memories, action buckets, episode records, and compact tool results derive from canonical transactions and `transaction_result`.

---

## Slice 0: Baseline guard and plan wiring

**Objective:** Record the current healthy baseline and wire this child plan into the plan index before code changes.

**Files:**
- Modify: `.hermes/plans/README.md`
- Create: `.hermes/plans/2026-05-29-knowledge-transaction-source-of-truth-cleanup.md`

**Steps:**
1. Add this plan to `.hermes/plans/README.md` as the current active cleanup/hardening follow-up after planner evidence-gate hardening.
2. Record the 2026-05-29 scheduled maintenance artifact as the baseline expected behavior.
3. Run `git diff --check`.
4. Ask an independent reviewer to check this plan before implementation.

**Exit criteria:**
- Plan/index clearly say this is a cleanup source-of-truth slice, not a gate-loosening or memory-candidate-expansion slice.
- Reviewer has no blocker, or blockers are incorporated before implementation.

---

## Slice 1: Add canonical-only summary guards

**Status:** Completed on 2026-05-29. Added canonical-vs-split regression coverage for compact tool results, CLI action/actual summaries, recent-run report actual summaries, episode recording, runtime eval case quality readers, nested canonical post-validation, duplicate memory-result counts, and archive transaction classification. Verification: `git diff --check && .venv/bin/python -m pytest -q` → 884 passed, 2 skipped.

**Objective:** Ensure current summaries fail tests if they read split lanes when canonical transactions exist.

**Files:**
- Modify: `tests/test_plugin_tools.py`
- Modify: `tests/test_report_improve_connection.py`
- Modify: `tests/test_cli_surface.py`
- Modify as needed: `tests/test_episode_ledger.py`
- Modify as needed: `tests/test_runtime_eval_cases.py` or existing runtime eval case tests

**RED tests:**
1. Build a synthetic result containing:
   - canonical `knowledge_transactions` with one skill apply, one memory skip, one memory-to-skill defer;
   - conflicting legacy `step_decisions.skill` / `memory` / `memory_to_skill` payloads with impossible counts.
2. Assert compact tool result uses canonical counts only.
3. Assert CLI action summary uses canonical counts only.
4. Assert actual-results summary reports changed skill/memory names from canonical `transaction_result`, not split decisions.
5. Assert episode recording uses canonical transactions first and ignores conflicting split lanes when canonical data exists.
6. Assert runtime eval case builders read canonical `knowledge_quality` when present and ignore conflicting split `step_decisions.skill.planner_quality`.

**Implementation notes:**
- Start with tests only. They should fail against any helper still preferring split payloads.
- Keep fixture payloads tiny and explicit.

**Verification commands:**
```bash
python -m pytest tests/test_plugin_tools.py tests/test_report_improve_connection.py tests/test_cli_surface.py tests/test_episode_ledger.py tests/test_runtime_eval_cases.py -q
```

**Commit:** `test(self-improvement): guard canonical transaction summaries`

---

## Slice 2: Refactor summary helpers to canonical transaction readers

**Status:** Completed on 2026-05-29. Extracted `canonical_transaction_view(...)` / `legacy_split_transaction_view(...)` into `knowledge_transactions.py`, updated compact tool summaries and CLI actual/action summaries to prefer canonical transactions over provided/split counts, isolated runtime eval split planner-quality fallback behind `legacy_split_planner_quality(...)`, preserved post-validation failure correction in the canonical adapter, and clarified memory semantics so `changed_memory_count` is distinct memory IDs while `memory_touch_count` is raw changed/removed result entries. Verification: focused canonical summary/runtime tests plus `python -m pytest -q` → 889 passed, 2 skipped.

**Objective:** Make tool/CLI/report summary helpers consume one canonical adapter rather than repeatedly falling back to split lanes.

**Files:**
- Modify: `hermes_self_improvement/tool_handlers.py`
- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/markdown_artifacts.py` if needed
- Modify: `hermes_self_improvement/runtime_eval_cases.py`
- Modify/Create: `hermes_self_improvement/knowledge_transactions.py` if helper extraction belongs there
- Test: tests from Slice 1

**Steps:**
1. Add or reuse a small helper such as `canonical_transaction_view(result_or_steps)` that returns:
   - `transactions`
   - action counts
   - by-kind counts
   - changed/created/archived skills
   - changed/removed memories
   - editor validation counts
2. Update `self_improvement_improve` compact tool result code to use the helper.
3. Update CLI improve/report summary paths to use the helper when canonical transactions exist.
4. Update runtime-eval-case planning/quality readers so canonical `knowledge_quality` is preferred, with split fallback only for old artifacts that lack canonical fields.
5. Keep old artifact support only as an explicit fallback helper, e.g. `legacy_split_transaction_view(...)`, and call it only when canonical transactions are absent.
6. Rename internal variables away from `skill_step` / `memory_step` in current paths where that hides canonical behavior.
7. Re-run focused tests.

**Exit criteria:**
- Canonical synthetic fixtures ignore conflicting split lanes.
- Current live artifacts still summarize to the same counts as before.
- Legacy split fallback, if retained, is visibly named and tested as legacy-only.

**Verification commands:**
```bash
python -m pytest tests/test_plugin_tools.py tests/test_report_improve_connection.py tests/test_cli_surface.py tests/test_runtime_eval_cases.py -q
python -m py_compile __init__.py hermes_self_improvement/*.py
```

**Commit:** `refactor(self-improvement): summarize from knowledge transactions`

---

## Slice 3: Refactor episode creation to canonical-first only

**Status:** Completed on 2026-05-29. Episode creation now keeps canonical transaction handling authoritative, maps canonical `decision=apply` through canonical `operation` for skill/memory episode decisions and actions, preserves safe operation metadata without serializing operation bodies, records canonical post-validation status, respects explicit canonical memory `target_id`, and isolates split skill/memory episode construction behind `_legacy_split_episodes_from_steps(...)` used only when canonical transactions are absent. Verification: `tests/test_episode_ledger.py`, `tests/test_report_improve_connection.py`, `tests/test_plugin_tools.py`, and full `python -m pytest -q` → 890 passed, 2 skipped.

**Objective:** Stop episode ledgers from silently rebuilding current episodes from split skill/memory decisions.

**Files:**
- Modify: `hermes_self_improvement/episodes.py`
- Test: `tests/test_episode_ledger.py`

**Steps:**
1. Add a canonical fixture with conflicting split decisions and assert only canonical episodes are emitted.
2. Ensure canonical episode target resolution accepts:
   - `target_id`
   - `target_store`
   - `transaction_kind`
   - `operation`
   - `transaction_result`
3. Move split skill/memory episode builders behind explicit legacy fallback used only when canonical transactions are absent.
4. Add a regression test that canonical memory and memory-to-skill transactions produce useful episode target/store metadata.

**Exit criteria:**
- Current run artifacts produce episodes from canonical transactions.
- Old split episode builders cannot run when canonical transactions exist.

**Verification commands:**
```bash
python -m pytest tests/test_episode_ledger.py -q
python -m pytest tests/test_report_improve_connection.py tests/test_plugin_tools.py -q
```

**Commit:** `refactor(self-improvement): record episodes from canonical transactions`

---

## Slice 4: Isolate legacy replay and split bridge compatibility

**Status:** Completed on 2026-05-29. Added a replay regression proving canonical dry-run artifacts do not invoke the legacy split `apply_memory_to_skill_migrations(...)` bridge, while split-only dry-run replay still works. Wrapped replay bridge execution behind `_legacy_split_replay_memory_to_skill_step(...)`, returning an explicit `skipped_canonical_transactions_present` step when canonical `knowledge_transactions` exist. Verification: `tests/test_report_improve_connection.py tests/test_memory_to_skill_migration.py` → 41 passed; full `python -m pytest -q` → 891 passed, 2 skipped; `git diff --check` passed.

**Objective:** Make historical replay compatibility explicit before touching public runner helpers.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/runner_steps.py`
- Test: replay/report tests that cover `run_replay_improve` or add a focused regression if missing

**Steps:**
1. Identify the current replay path that calls `apply_memory_to_skill_migrations(...)` from split `memory_step` input.
2. Rename or wrap that path with explicit `legacy_split_replay_*` helper names without changing behavior.
3. Add tests for two cases:
   - old split-only artifact can still be read/replayed through the explicit legacy path;
   - mixed canonical + split artifact uses canonical transactions and does not call the legacy split bridge.
4. Ensure legacy replay compatibility is read-only/explicit unless the existing replay command intentionally executes preview replay; do not allow it to become the current scheduled `improve` source of truth.
5. Keep `apply_memory_to_skill_migrations(...)` available if replay still needs it, but mark it as legacy split bridge in docstring/comment.

**Exit criteria:**
- Historical split artifact support remains deliberate and tested.
- Current canonical artifacts cannot accidentally route through `apply_memory_to_skill_migrations(...)`.

**Verification commands:**
```bash
python -m pytest tests/test_report_improve_connection.py tests/test_memory_to_skill_migration.py -q
```

**Commit:** `refactor(self-improvement): isolate legacy split replay`

---

## Slice 5: Quarantine split runner entry points

**Status:** Completed on 2026-05-29. Added a guard test that `run_improve` succeeds through canonical `run_knowledge_improvement_step(...)` while old split entry points are monkeypatched to raise. Marked retained split helpers with explicit legacy docstrings/comments: `run_skill_improvement_step(...)`, `run_memory_improvement_step(...)`, `apply_memory_to_skill_migrations(...)`, and `build_knowledge_transactions(...)`. Verification: `tests/test_runner_steps.py tests/test_memory_agent_dispatch.py tests/test_planner_cluster_digest.py tests/test_report_improve_connection.py tests/test_cli_improve_memory_current_entries.py` → 85 passed; full `python -m pytest -q` → 892 passed, 2 skipped; `git diff --check` passed.

**Objective:** Reduce the chance that future code accidentally calls old split runners as source-of-truth lanes, without deleting still-used public test/replay helpers in this cleanup slice.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Modify tests that directly import old runner functions only if they are current-contract tests
- Test: `tests/test_runner_steps.py`, `tests/test_memory_agent_dispatch.py`, `tests/test_planner_cluster_digest.py`

**Steps:**
1. Classify each old public helper:
   - still used as a lower-level helper by canonical execution;
   - legacy replay/testing only;
   - obsolete and safe to delete.
2. Add docstrings or leading comments for any retained legacy helpers: “legacy split-lane helper; not used by `run_improve` source-of-truth path”.
3. If safe, rename internal-only helpers with `_legacy_` prefix and update tests.
4. Prefer comments/docstrings and `_legacy_` wrapper names in this slice; delete only if the helper has no current tests, replay path, or lower-level reuse.
5. Add a guard test that `run_improve` still succeeds when old split end-to-end runner functions are monkeypatched to raise.
6. Do not delete lower-level editor/parser helpers still needed by `execute_knowledge_transaction(...)`.

**Exit criteria:**
- Future readers can tell which helpers are canonical and which are legacy.
- `run_improve` cannot accidentally regress to split-lane orchestration without tests failing.

**Verification commands:**
```bash
python -m pytest tests/test_runner_steps.py tests/test_memory_agent_dispatch.py tests/test_planner_cluster_digest.py tests/test_report_improve_connection.py -q
```

**Commit:** `refactor(self-improvement): quarantine split runner helpers`

---

## Slice 6: Remove `planner_skill` pseudo-kind from canonical runtime output

**Status:** Completed on 2026-05-29. Added regressions that current canonical knowledge transactions do not emit `planner_skill` and that the legacy split bridge defaults planner-origin skill transactions to `transaction_kind='skill'`. Production code no longer contains `planner_skill`; remaining occurrences are compatibility tests for old explicit artifacts. Verification: `tests/test_knowledge_transactions.py tests/test_report_improve_connection.py tests/test_plugin_tools.py tests/test_memory_to_skill_migration.py tests/test_runner_steps.py::test_run_knowledge_improvement_step_dry_run_returns_canonical_transactions` → 60 passed; full `python -m pytest -q` → 893 passed, 2 skipped; `git diff --check` passed.

**Objective:** Ensure canonical transaction grouping uses real transaction kinds and does not leak a `planner_skill` compatibility kind in current artifacts.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Modify: `hermes_self_improvement/planner_runtime.py` if normalization still synthesizes pseudo-kind
- Modify summary tests

**RED tests:**
1. Planner output with skill transactions lacking `transaction_kind` normalizes to `transaction_kind='skill'`, not `planner_skill`.
2. `by_kind` summaries for current artifacts group skill mutations under `skill`.
3. Legacy artifact readers may map old `planner_skill` to display as `skill`, but current run emission should not produce it.
4. Old artifacts containing `planner_skill` are parsed only through legacy display/fallback code and are not passed to `execute_knowledge_transaction(...)` as executable current transactions.

**Implementation notes:**
- This is a naming/source-of-truth cleanup only. Do not change evidence-gate behavior.
- If `planner_skill` is still needed for historical parsing, isolate it in the legacy fallback helper.

**Exit criteria:**
- Current dry-run artifact contains no runtime-facing `planner_skill` kind.
- Summary by-kind still matches previous action counts.

**Verification commands:**
```bash
python -m pytest tests/test_knowledge_transactions.py tests/test_report_improve_connection.py tests/test_plugin_tools.py -q
```

**Commit:** `refactor(self-improvement): use canonical skill transaction kind`

---

## Slice 7: Dogfood and close cleanup readiness

**Status:** Completed on 2026-05-29. Full verification passed after the final canonical normalization fix for targetless `skip` transactions and the post-review replay fix that executes canonical apply transactions while stripping stale split lanes from canonical replay payloads. Validation: `python -m py_compile __init__.py hermes_self_improvement/*.py`, full `python -m pytest tests -q` → 895 passed, 2 skipped, `hermes self-improvement improve --dry-run --json`, and `git diff --check`. Final cleanup dry-run artifact `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260529T032803Z.json` contains canonical `step_decisions.knowledge_transactions` only, no split `step_decisions.skill` / `memory` / `memory_to_skill` lanes, `by_kind {'none': 21, 'skill': 26}`, no `planner_skill`, no blank transaction kind, `actionability_loss_count: 0`, and `unexplained_cross_store_drop_count: 0`. After explicit approval, `hermes self-improvement improve --from-run /Users/ryo.nakae/.hermes/self-improvement/runs/run-20260529T032803Z.json` produced `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260529T091409Z.json` and patched `hermes-development-maintenance` through the official skill tool path; result: `skill_changes: 1`, `memory_changes: 0`, `apply: 1 / defer: 1 / skip: 45 / block: 0`, no next actions, runtime status healthy, plugin repo clean.

**Objective:** Prove behavior stayed the same while source-of-truth got simpler.

**Files:**
- Runtime artifact: `${HERMES_HOME}/self-improvement/runs/run-*.json`
- Modify: `.hermes/plans/README.md`
- Modify: this plan
- Modify: `2026-05-28-unified-knowledge-planner-editor-execution.md` only if it needs a forward pointer to this cleanup result

**Steps:**
1. Run full verification:
```bash
python -m py_compile __init__.py hermes_self_improvement/*.py
python -m pytest tests -q
hermes self-improvement status
hermes self-improvement improve --dry-run --json > /tmp/self-improvement-source-of-truth-cleanup-dryrun.json
git diff --check
```
2. Inspect the dry-run artifact:
```bash
python - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path('/tmp/self-improvement-source-of-truth-cleanup-dryrun.json').read_text())
run = Path(payload['artifact_path'])
data = json.loads(run.read_text())
steps = data.get('step_decisions') or {}
print('artifact', run)
print('action_summary', data.get('action_summary'))
print('step_keys', sorted(steps))
print('by_kind', (steps.get('knowledge_transactions') or {}).get('by_kind'))
print('legacy_split_present', {k: k in steps for k in ['skill', 'memory', 'memory_to_skill']})
print('actionability_loss_count', (steps.get('knowledge_quality') or {}).get('actionability_loss_count'))
print('unexplained_cross_store_drop_count', (steps.get('knowledge_routing') or {}).get('unexplained_cross_store_drop_count'))
PY
```
3. Expected result:
   - no split `step_decisions.skill` / `memory` / `memory_to_skill`
   - no runtime-facing `planner_skill` in current `by_kind`
   - `actionability_loss_count == 0` unless there is a concrete new evidence issue to investigate
   - `unexplained_cross_store_drop_count == 0`
   - no safety gate loosened
4. If dry-run naturally selects a low-risk executable mutation, do **not** run mutating dogfood in this cleanup slice unless Ryo explicitly asks. Ryo explicitly approved the final replay after cleanup; `run-20260529T091409Z.json` is the approved mutating proof for canonical replay execution.
5. Update plan/index with final validation and artifact path.
6. Run independent code review before commit/push if code changed.

**Commit:** `refactor(self-improvement): simplify knowledge transaction source of truth`

---

## Stop conditions

Stop and report instead of continuing if:

- A current summary can only be produced from split lanes because canonical `transaction_result` lacks necessary fields.
- Removing a fallback would break recent canonical artifacts rather than only old private artifacts.
- Tests reveal memory candidate behavior changed, not just summary/source-of-truth behavior.
- A fix would require weakening evidence gates or mutability/provenance checks.
- Full suite failures appear outside this cleanup scope.

---

## Reviewer checklist

Ask reviewers to check specifically:

- Does the plan preserve the existing safety/evidence gates?
- Does it avoid adding new memory/skill candidate semantics before simplifying source-of-truth?
- Are legacy split readers isolated rather than silently used for canonical artifacts?
- Are tests strong enough to catch conflicting canonical-vs-split payloads?
- Is `planner_skill` removed from current runtime output without breaking historical parsing?
- Is dogfood scoped to dry-run unless a separate explicit approval is given for mutation?
