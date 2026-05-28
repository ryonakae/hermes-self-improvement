# Planner Evidence Gate Hardening Implementation Plan

> **For Hermes:** Implement only after review and explicit user approval. Use TDD and commit verified slices.

**Goal:** Preserve the unattended mutation safety gate while letting the unified planner pass legitimate maintenance-candidate / coverage-fit / representative-evidence backed `mutate_skill` decisions through to the editor.

**Architecture:** Keep `mutate_skill` evidence-gated; do not allow evidence-free skill mutation. Expand the allowed evidence set for an editable skill by tracing deterministic relationships already present in the planner digest: direct editable skill evidence, maintenance candidates whose `coverage_fit.fit_skills` includes that skill, representative evidence ids on those candidates, and explicit target/resolution hints. Separately, make inventory-only unselected skills legible as inventory omissions instead of noisy evidence-backed planner skips.

**Tech Stack:** Python, pytest, Hermes self-improvement planner/runtime artifacts.

**Status (2026-05-29):** implemented, post-review hardened, verified, and smoke-tested. The planner evidence gate is still fail-closed, but valid editable-skill maintenance evidence can now pass through deterministic maintenance-candidate / coverage-fit / representative-evidence relationships. Direct editable-skill evidence remains valid even when a maintenance candidate also exists. Non-mutable/reference/builtin targets are blocked before direct evidence can authorize mutation. Canonical planner-supplied skill transactions are accepted only after the same editable/evidence gate checks and retain executable `editor_task` / `skill_task`; inventory-only no-op rows remain canonical `skill` transactions with `inventory_not_selected_by_planner` instead of a `planner_skill` pseudo-kind.

**Validation (2026-05-29, post-review hardening):**

- `python -m pytest tests/test_knowledge_maintenance_planner.py::test_planner_blocks_non_mutable_direct_skill_evidence tests/test_knowledge_maintenance_planner.py::test_planner_allows_direct_skill_evidence_when_maintenance_candidate_also_exists tests/test_knowledge_maintenance_planner.py::test_planner_accepts_canonical_skill_apply_transaction -q` → `3 passed`
- `python -m pytest tests/test_knowledge_maintenance_planner.py tests/test_knowledge_transactions.py tests/test_report_improve_connection.py tests/test_memory_to_skill_migration.py -q` → `64 passed`
- `python -m pytest tests -q` → `876 passed, 2 skipped`
- `python -m py_compile __init__.py hermes_self_improvement/*.py` → passed
- `git diff --check` → passed
- `hermes self-improvement status` → passed / runtime ready
- `hermes self-improvement improve --dry-run` → passed; artifact `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260528T173940Z.json`

**Smoke artifact check:** `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260528T173940Z.json` has no split `step_decisions.skill` / `memory` / `memory_to_skill` lanes, reports `action_summary {'apply': 1, 'block': 0, 'defer': 0, 'skip': 45}`, keeps `skill_editor_task_count: 1`, and classifies inventory no-ops as `matched_inventory_not_selected`.

---

## Context

Latest live execution showed `apply:0 / defer:5 / skip:44 / block:0` even though the raw planner selected a reasonable `mutate_skill` for `safe-patch-usage`. The decision was stopped before editor execution because `_normalize_decision()` filters planner `evidence_ids` through `evidence_by_candidate[skill]`, and that map currently only includes evidence directly attached to `digest["skill_candidates"]` rows.

That is safe, but too narrow for the unified planner. The planner now reasons from:

- editable skill inventory
- reference skill coverage
- maintenance candidates
- coverage-fit relationships
- unmatched / representative evidence ids
- memory-to-skill and placement signals

The current failure mode is therefore:

1. Planner makes a bounded `mutate_skill` decision.
2. The cited evidence is valid in the maintenance-candidate graph.
3. The direct editable-skill evidence map does not include it.
4. Normalization converts the decision to `skip` with `mutate_skill_without_attached_evidence`.
5. Editor receives zero tasks.

Do **not** fix this by disabling evidence requirements.

---

## Scope

### In scope

- Expand allowed evidence for editable skill mutation using deterministic planner digest relationships.
- Preserve blocked behavior for unrelated evidence ids.
- Preserve blocked behavior for reference/non-mutable skills.
- Improve planner result/reporting shape so unselected inventory skips retain target identity and are distinguishable from evidence-backed deferred maintenance candidates.
- Add regression tests that reproduce the current failure and verify editor task handoff becomes possible.
- Update plan/index state after implementation and dogfood.

### Out of scope

- Changing planner prompt semantics broadly.
- Loosening mutation risk gates.
- Forcing live mutation just to prove `apply > 0`.
- Editing skills/memories as part of this implementation.
- Reintroducing split skill/memory lanes.

---

## Acceptance criteria

- A planner `mutate_skill` decision for editable skill `local-patch-workflow` with evidence from a matching maintenance candidate is normalized as `mutate_skill` / canonical `apply`, not `mutate_skill_without_attached_evidence`.
- The same decision with unrelated evidence remains `skip` with `mutate_skill_without_attached_evidence`.
- Candidate inventory auto-skips keep `skill` in planner-runtime output and become canonical transactions with `target_store: "skill"` and `target_id: <skill name>` or an equivalent bounded reporting field; they must not appear as empty `target_id: ""` rows.
- Reporting separates `inventory_not_selected_by_planner` from evidence-backed `maintenance_candidate_not_selected_by_planner` or exposes counts that make the distinction clear.
- Focused tests pass, full `tests -q` passes, `py_compile`, `git diff --check`, and `hermes self-improvement status` pass.
- Dry-run artifact inspection confirms no split `step_decisions.skill` / `memory` / `memory_to_skill` lanes return.
- A canonical `mutate_skill` transaction carries an executable `editor_task` / `skill_task`; dry-run preview alone is not sufficient if `mutate=True` would later block as `knowledge_transaction_missing_required_fields`.
- Summary output continues to count these rows under canonical `skill`, not a new `planner_skill` pseudo-kind.

---

## Task 1: Add RED test for maintenance-candidate evidence passing `mutate_skill`

**Objective:** Capture the exact failure: planner selects a mutable skill using evidence attached through `coverage_fit` / representative maintenance evidence, and normalization must keep the decision executable.

**Files:**
- Modify: `tests/test_knowledge_maintenance_planner.py`
- Read: `hermes_self_improvement/planner_runtime.py`

**Steps:**

1. Add a test near `test_planner_accepts_canonical_maintenance_decisions()`.
2. Build a `make_knowledge_coverage_candidate(...)` with:
   - `evidence_id` like `coverage_patch`
   - representative evidence id like `unmatched_patch`
   - `workflow_boundary: "patch tool workflow"`
3. Include `skill_candidates` with editable `local-patch-workflow`.
4. Let `build_planner_digest()` produce a `coverage_fit` whose `fit_skills` includes `local-patch-workflow`.
5. Inject planner output:
   ```python
   {"skill": "local-patch-workflow", "decision": "mutate_skill", "maintenance_action": "patch", "evidence_ids": [candidate["id"], "unmatched_patch"], "risk": "low", "editor_instructions": "Add bounded retry guidance."}
   ```
6. Assert the normalized row keeps:
   - `decision == "mutate_skill"`
   - `evidence_ids` includes the maintenance candidate id and/or representative id
   - no `reason == "mutate_skill_without_attached_evidence"`

**Expected RED:** Test fails because current `_normalize_decision()` drops those evidence ids unless they are directly attached to the skill candidate row.

---

## Task 2: Add RED test for unrelated evidence still blocked

**Objective:** Prove the safety gate stays strict; only graph-related evidence becomes allowed.

**Files:**
- Modify: `tests/test_knowledge_maintenance_planner.py`

**Steps:**

1. Add a sibling test using the same editable skill.
2. Planner returns `evidence_ids: ["unrelated_evidence"]`.
3. Assert normalized decision is:
   - `decision == "skip"`
   - `reason == "mutate_skill_without_attached_evidence"`
   - `evidence_ids == []`

**Expected RED/GREEN behavior:** This likely already passes today and must continue passing after Task 3.

---

## Task 3: Implement deterministic allowed-evidence expansion

**Objective:** Build the allowed evidence map from both direct candidate evidence and maintenance-candidate graph relationships.

**Files:**
- Modify: `hermes_self_improvement/planner_runtime.py`

**Implementation sketch:**

1. Add a small helper near `_maintenance_candidate_default_decision()`:
   ```python
   def _expanded_evidence_by_candidate(
       *,
       candidate_rows: list[dict[str, Any]],
       maintenance_candidates: list[dict[str, Any]],
   ) -> dict[str, set[str]]:
       ...
   ```
2. Start with the existing direct map:
   - `candidate["evidence_ids"]`
3. For each maintenance candidate:
   - read `evidence_id`
   - read `maintenance_affordance.representative_evidence_ids`
   - read `coverage_fit.fit_skills`
   - optionally read `target_skill`, `skill`, or `target_resolution.target` only when it is an editable candidate name
4. For every editable skill name in those deterministic target sets, union:
   - maintenance candidate `evidence_id`
   - representative evidence ids
   - any candidate-owned `evidence_ids` field if present
5. In `_normalize_planner_payload()`, replace the inline `evidence_by_candidate = {...}` with the helper call after `maintenance_candidates` is available.
6. Keep expansion limited to names present in `candidate_names`. Do not include reference-only skills unless they are also editable candidates.
7. Only attach maintenance-candidate evidence through bounded editable-skill relationships:
   - `coverage_fit.fit_skills` contains the editable skill and `coverage_fit.match_target` is editable / local / partial-overlap with editable fit, or
   - explicit target metadata identifies the editable skill without a block hint.
8. Require the maintenance candidate id to remain in normalized `evidence_ids` when it is the reason a `mutate_skill` becomes allowed. Representative ids may supplement it, but representative-only citation must not be enough unless the representative id is also present in direct candidate evidence.

**Do not:**
- use fuzzy name matching here
- accept all `available_skill_evidence_ids`
- treat arbitrary planner-cited evidence as valid

**Verification:**
- Task 1 turns GREEN.
- Task 2 remains GREEN.

**Additional safety test:** Add a regression where `coverage_fit.fit_skills` contains only a reference/builtin/non-mutable skill (for example `safe-patch-usage`) and the planner tries `mutate_skill` for it. The decision must still be dropped because the target is not in editable `candidate_names`.

---

## Task 3.5: Preserve executable skill editor task in canonical transactions

**Objective:** Make the fixed evidence gate actually reach the editor. A normalized `mutate_skill` with only `editor_instructions` currently risks becoming a canonical skill transaction with `editor_task: None`, which then blocks in `runner_steps._execute_skill_transaction()` when `mutate=True`.

**Files:**
- Modify: `hermes_self_improvement/planner_runtime.py`
- Possibly modify: `hermes_self_improvement/knowledge_transactions.py` only if planner-runtime cannot supply canonical task shape cleanly
- Tests: `tests/test_knowledge_maintenance_planner.py`, `tests/test_report_improve_connection.py`

**Implementation sketch:**

1. When `_normalize_decision()` keeps `decision == "mutate_skill"`, synthesize or preserve a bounded task payload:
   ```python
   "skill_task": {
       "task_kind": "mutate_skill",
       "targets": {"primary_skill": skill, ...},
       "instructions": <editor_instructions or skill_editor_instructions or change_intent>,
       "maintenance_action": maintenance_action,
       "target_skill": target_skill for merge only,
   }
   ```
2. Prefer preserving any valid raw `skill_task` / `editor_task` if already provided, after validating the primary target matches `skill`.
3. Ensure `normalize_knowledge_transaction()` receives `skill_task` / `editor_task`, so canonical output has `editor_task` and `operation == "mutate_skill"`.
4. Add assertions that `execute_knowledge_transaction(transaction, mutate=False)` previews and `execute_knowledge_transaction(transaction, mutate=True)` with a fake successful backend does not block with `knowledge_transaction_missing_required_fields`.

**Do not:** encode natural-language instructions only in top-level `editor_instructions` and assume the executor will recover them.

---

## Task 4: Add test for inventory skip identity preservation

**Objective:** Stop empty canonical skip rows from hiding what target was skipped.

**Files:**
- Modify: `tests/test_knowledge_transactions.py` or `tests/test_knowledge_maintenance_planner.py`
- Modify after GREEN: `hermes_self_improvement/knowledge_transactions.py` and/or `planner_runtime.py`

**Preferred test shape:**

1. Normalize a planner skill skip:
   ```python
   {"skill": "timeout-workflow", "decision": "skip", "reason": "not_selected_by_planner", "evidence_ids": []}
   ```
2. Assert canonical output preserves target identity:
   - `transaction_kind == "skill"`
   - `target_store == "skill"`
   - `target_id == "timeout-workflow"`
   - `decision == "skip"`
   - `reason == "not_selected_by_planner"`

Avoid `transaction_kind == "planner_skill"` in final canonical output. Summary code uses `transaction_kind` first, so `planner_skill` would create a pseudo-kind and obscure canonical skill reporting.

**Expected RED:** Current canonical normalization can erase target identity for non-apply planner-skill rows.

---

## Task 5: Implement inventory skip reporting split

**Objective:** Make `not_selected_by_planner` counts honest: inventory omissions are not the same as evidence-backed maintenance candidates.

**Files:**
- Modify: `hermes_self_improvement/planner_runtime.py`
- Possibly modify: `hermes_self_improvement/knowledge_transactions.py`
- Possibly modify: `hermes_self_improvement/cli.py` if summary counters are produced there
- Tests: `tests/test_report_improve_connection.py`, `tests/test_knowledge_maintenance_planner.py`, or a focused reporting test

**Implementation sketch:**

1. Change auto-added inventory skip rows from:
   ```python
   {"skill": name, "decision": "skip", "reason": "not_selected_by_planner", "evidence_ids": []}
   ```
   to something more precise:
   ```python
   {
       "skill": name,
       "decision": "skip",
       "reason": "inventory_not_selected_by_planner",
       "evidence_ids": [],
       "target_store": "skill",
       "target_id": name,
       "transaction_kind": "skill",
   }
   ```
2. Keep maintenance default decisions using `maintenance_candidate_not_selected_by_planner` with real evidence ids.
3. Update benign/needs-follow-up classification so inventory omissions are visible as inventory omissions, not as `matched_existing_coverage`. They may be benign at top-level, but `_matched_noop_class()` should either exclude `inventory_not_selected_by_planner` from matched existing coverage or assign a dedicated `matched_inventory_not_selected` class.
4. Add summary counters if useful:
   - `inventory_not_selected_count`
   - `maintenance_not_selected_count`
   - `planner_selected_but_evidence_detached_count`

**Verification:**
- Existing skip classifications still make sense.
- Artifact no longer reads as “40 evidence-backed planner rejections.”

---

## Task 6: Add editor-handoff regression at `run_improve` boundary

**Objective:** Prove the fixed planner decision reaches the canonical execution path as an apply/preview skill transaction in dry-run mode.

**Files:**
- Modify: `tests/test_report_improve_connection.py`

**Steps:**

1. Add a fixture-style test similar to `test_run_improve_fixture_proves_all_canonical_transaction_stores_without_split_lanes`.
2. Do **not** monkeypatch `runner_steps.run_planner_runtime` to return already-normalized transactions; that bypasses the evidence gate under test.
3. Instead pass `config["_planner_runtime_func"]` or `config["_planner_func"]` that returns the raw planner payload, so `run_planner_runtime()` executes `_normalize_planner_payload()` / `_normalize_decision()` normally.
4. Run `cli.run_improve(config=config, dry_run=True)`.
5. Assert:
   - `action_summary["apply"] >= 1`
   - one `knowledge_transactions` row has `target_store == "skill"`
   - that row has `transaction_kind == "skill"`, `operation == "mutate_skill"`, and non-empty `editor_task`
   - `transaction_result.outcome == "preview"`
   - `skill_editor_task_count` or equivalent validation summary reflects a skill preview task
   - split lanes remain absent from `step_decisions`

6. Add a narrower executor-level test with a fake successful backend and `mutate=True` to prove the same canonical transaction does not block as `knowledge_transaction_missing_required_fields`.

If a direct `run_planner()` focused test already proves handoff sufficiently, keep this test small and avoid over-mocking editor internals.

---

## Task 7: Focused and full verification

**Objective:** Validate the change without relying on live mutation.

**Commands:**

```bash
python -m pytest tests/test_knowledge_maintenance_planner.py tests/test_knowledge_transactions.py tests/test_report_improve_connection.py -q
python -m py_compile __init__.py hermes_self_improvement/*.py
python -m pytest tests -q
git diff --check
hermes self-improvement status
```

Expected:
- Focused tests pass.
- Full suite passes.
- Status healthy.

---

## Task 8: Dry-run artifact smoke

**Objective:** Confirm runtime artifact shape is clearer and no split lanes return.

**Commands:**

```bash
hermes self-improvement improve --dry-run --json > /tmp/self-improvement-evidence-gate-hardening-dryrun.json
python - <<'PY'
import json, pathlib
p = pathlib.Path('/tmp/self-improvement-evidence-gate-hardening-dryrun.json')
data = json.loads(p.read_text())
print('artifact_path', data.get('artifact_path'))
print('action_summary', data.get('action_summary'))
print('knowledge_quality', data.get('step_decisions', {}).get('knowledge_quality'))
print('knowledge_transactions', data.get('step_decisions', {}).get('knowledge_transactions'))
PY
```

Then inspect the artifact path for:
- `knowledge_transactions` present
- no split `step_decisions.skill` / `memory` / `memory_to_skill`
- inventory skip vs maintenance skip visible enough to explain no-op runs
- `mutate_skill_without_attached_evidence` only when evidence is genuinely detached

Do not require `apply > 0` from live dry-run; natural evidence may still produce a healthy no-op.

---

## Task 9: Update plans and index, then commit/push

**Objective:** Keep roadmap state truthful and leave a clean checkpoint.

**Files:**
- Modify: `.hermes/plans/2026-05-28-planner-evidence-gate-hardening.md`
- Modify: `.hermes/plans/README.md`
- Possibly modify: `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`

**Steps:**

1. Update this plan with implementation status, validation commands, and dry-run artifact path.
2. Update the plan index current-priority section to point at this hardening plan until complete.
3. If the fix changes readiness meaning, update the long-term roadmap current-state note.
4. Commit with an appropriate conventional message, likely:
   ```bash
   git add hermes_self_improvement tests .hermes/plans
   git commit -m "fix(self-improvement): preserve planner maintenance evidence"
   git push
   ```

---

## Review checklist before implementation

- [x] Does the plan preserve the evidence gate instead of weakening it?
- [x] Are the graph relationships deterministic and bounded?
- [x] Are reference/builtin/non-mutable skills still protected?
- [x] Is unrelated evidence still blocked?
- [x] Does reporting separate inventory omissions from real evidence-backed non-selection?
- [x] Are tests small enough to fail for the current bug and pass for the intended fix?
- [x] Is dogfood verification dry-run based rather than forcing mutation?
