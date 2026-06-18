# Report Accounting and Outcome Credit Hardening Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Fix the observed report/improve accounting mismatch and make outcome credit more useful without weakening positive-credit conservatism.

**Architecture:** Keep the existing `improve / calibrate / report / status` surfaces. Fix reporting by making saved run artifact summaries use the same canonical mutation accounting as immediate `improve` output. Improve outcome credit by strengthening episode/observation signatures and rendering unknown/under-observation buckets more explicitly, not by treating silence as success.

**Tech Stack:** Python, pytest, Hermes self-improvement runtime artifacts under `${HERMES_HOME}/self-improvement`, existing `credit_assignment.py`, `outcome_scoring.py`, `outcome_observer.py`, `episodes.py`, `runtime_eval_cases.py`, and CLI report rendering in `cli.py`.

---

## Subagent review status

Three review subagents checked the first draft against the current repo. All three returned **BLOCKED**. This revision incorporates their blockers:

- `_recent_json_files()` currently drops top-level `skill_changes` / `memory_changes`, so fixing only `_actual_result_summary_lines()` would not affect the real report path.
- Outcome observations are produced in `outcome_observer.py`, not only scored in `outcome_scoring.py`; signature work must cover both episode creation and observation generation/dedupe.
- Dry-run verification must not expect newly written episode artifacts as a side effect.
- Signature/hash logic should live in one shared helper module to avoid episode/observation/runtime-eval drift.
- Recurrence matching must not treat generic `terminal timeout` / broad cluster similarity as proof of recurrence.

Implementation should not start until these revised tasks are followed.

## Implementation status

### Phase 1 — implemented 2026-06-18 JST

Implemented the report/run artifact mutation accounting slice:

- `_recent_json_files()` now preserves bounded top-level `skill_changes`, `memory_changes`, `action_summary`, and canonical `knowledge_transactions` when present.
- `_render_operational_report_sections()` passes saved artifact changes into `_actual_result_summary_lines()`.
- `_actual_result_summary_lines()` falls back to top-level saved `skill_changes` / `memory_changes` only when canonical transaction or legacy decision accounting did not already recover mutations.
- Canonical transaction accounting keeps precedence over fallback lists.

Verification:

- RED confirmed first: 3 new focused tests failed for missing `skill_changes` row preservation, missing report fallback, and missing helper keyword support.
- Focused new tests: `3 passed, 54 deselected`.
- Related suite: `tests/test_cli_surface.py tests/test_report_integration.py` → `63 passed`.
- `py_compile`: passed.
- `hermes self-improvement report --since-hours 24` smoke against latest runtime artifact `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260616T190532Z.json`: rendered `skill patched 3` and `memory 3`.
- `git diff --check`: passed.
- `hermes self-improvement status`: passed; runtime initialized and recent telemetry visible.
- Full suite: `1031 passed, 2 skipped`.

Implementation complete through Phase 5. Next work is scheduled observation/dogfood only; do not claim outcome quality is proven until later comparable usage moves conservative `unknown` outcomes into stronger evidence buckets.

### Phase 2 — implemented 2026-06-18 JST

Implemented the conservative unknown-outcome visibility slice:

- `credit_assignment.py` now assigns machine-readable `unknown_reasons` for unknown outcomes without converting them into positive credit.
- Current reason buckets include `no_later_comparable_observation`, `weak_usage_only`, `missing_evidence_link`, `quality_signal_without_outcome`, `scored_but_not_decisive`, and `unclassified`.
- `compact_credit_assignment_summary()` carries `outcomes.unknown_reasons` into run/report payloads.
- CLI outcome rendering now prints a bounded `unknown breakdown` line when saved or freshly built credit assignment data contains reason counts.
- The output keeps the existing conservative language: unknown/insufficient outcomes remain “under observation”; no “silence means success” credit was added.

Verification:

- RED confirmed first: new focused tests failed for missing aggregate `unknown_reasons` and missing CLI `unknown breakdown` rendering.
- Focused new tests: `3 passed, 63 deselected`.
- Related suite: `tests/test_credit_assignment.py tests/test_cli_surface.py tests/test_report_integration.py` → `72 passed`.
- `py_compile`: passed.
- `git diff --check`: passed.
- Full suite: `1033 passed, 2 skipped`.
- `hermes self-improvement report --since-hours 24` read-only smoke passed against the latest saved runtime artifact and still rendered the conservative outcome headline. The latest artifact predates this field, so no `unknown breakdown` line is expected until a new run writes credit assignment with `unknown_reasons`.

### Phase 3 — implemented 2026-06-18 JST

Implemented bounded episode/outcome matching signatures and stricter recurrence observation handling:

- Added shared `outcome_matching.build_matching_signature()` with normalized bounded fields and evidence-id hashing.
- New skill, memory, knowledge-transaction, and calibration episodes now carry `matching_signature_version`, `matching_signature`, `matching_signature_hash`, and `matching_signature_matchable`.
- Outcome observation producers now propagate episode matching fields and include signature hashes in dedupe keys.
- Generic broad recurrence clusters (`tool_error:terminal:timeout`, `tool_error:patch:unknown_error`, `tool_error:skill_manage:unknown_error`) are diagnostic-only and no longer produce recurrence observations without a stronger target/signature basis.
- Task 9 audit covered `episodes.py`, `outcome_observer.py`, `runner_steps.py`, and CLI/report episode read paths; episode writing remains centralized through `episodes.py`, while observations are produced through `outcome_observer.py` collectors.

Verification:

- Focused RED/GREEN signature tests: `tests/test_outcome_matching.py tests/test_episode_ledger.py` → `14 passed`.
- Phase 3 focused suite: `tests/test_outcome_matching.py tests/test_episode_ledger.py tests/test_outcome_observer.py tests/test_outcome_scoring.py tests/test_runtime_eval_cases.py` → `63 passed`.
- `py_compile`: passed.
- `git diff --check`: passed.
- Full suite: `1037 passed, 2 skipped`.
- `hermes self-improvement report --since-hours 24` read-only smoke passed and kept the conservative outcome headline; the latest saved artifact predates signature fields.

### Phase 4 — implemented 2026-06-18 JST

Implemented higher-signal runtime eval case metadata and selection behavior:

- Runtime eval cases now include `source_episode_id` and, when available, `source_matching_signature_hash` in top-level/source/input fields.
- Outcome-status eval cases now include `outcome_status`, bounded `outcome_components`, and `credit_window` metadata derived from scored outcome observations.
- Case identity now includes signature metadata, and role-case dedupe prefers `case_type + source_matching_signature_hash` when available.
- Runtime role eval case output now orders user-correction/recurring/regressed outcome cases ahead of weak-usage cases, keeping weak-only cases last rather than treating them as high-signal proof.

Verification:

- RED confirmed first: runtime eval test failed for missing source/outcome metadata, then for low-signal ordering.
- Focused runtime eval suite: `tests/test_runtime_eval_cases.py` → `16 passed`.
- Related suite: `tests/test_runtime_eval_cases.py tests/test_credit_assignment.py tests/test_outcome_scoring.py tests/test_outcome_matching.py` → `34 passed`.
- `py_compile`: passed.
- `git diff --check`: passed.
- Full suite: `1037 passed, 2 skipped`.
- `hermes self-improvement status`: passed; runtime initialized, latest run visible at `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260617T190248Z.json`.
- `hermes self-improvement report --since-hours 24` read-only smoke passed and rendered the new `unknown breakdown` line from the latest artifact.
- Source-directed runtime eval smoke ran against the current runtime config and returned `case_count 0`, which is expected when no eligible recent runtime eval cases are present.

### Phase 5 — implemented 2026-06-18 JST

Completed end-to-end verification and dry-run dogfood for the report/outcome-credit hardening plan:

- Focused suite from Task 15 passed: `tests/test_cli_surface.py tests/test_report_integration.py tests/test_episode_ledger.py tests/test_runtime_eval_cases.py` → `91 passed`.
- Full static/runtime verification passed: `py_compile`, `git diff --check`, `hermes self-improvement status`, and full suite `1037 passed, 2 skipped`.
- Read-only report smoke wrote `/tmp/self-improvement-report-after.md` and confirmed `Actual results:`, `unknown breakdown:`, and `unproven changes remain under observation` are present.
- Dry-run improve smoke wrote `/tmp/self-improvement-dry-run-after.json` and runtime artifact `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260618T043401Z.json` with `dry_run=True` and `target_changed=False`.
- Existing/new episode signature inspection found bounded signature artifact `/Users/ryo.nakae/.hermes/self-improvement/episodes/2026-06-18/20260618T043401684385Z-episode-a29e98ee0274f34f.json`; the serialized signature was bounded and did not contain raw `stdout` / `stderr`.

Remaining follow-up:

- Outcome quality is not proven yet; scheduled observation still needs later comparable usage to move many `unknown` outcomes out of `no_later_comparable_observation`.
- Current latest report still shows conservative status: `proven improved: 0`, `recurring: 13`, `unknown: 923`, `insufficient window: 64`, with `unknown breakdown: no later comparable observation 918, weak usage only 5`.

---

## Context from 2026-06-17 investigation

Live artifacts showed a real mismatch:

- `self-improvement-autonomous-maintenance` cron output for 2026-06-17 reported actual mutations correctly:
  - skill patched 3: `llm-context-optimization-integration`, `hermes-gateway-and-sessions`, `hermes-plugin-test-debugging`
  - memory 3
  - post-validated 6
- `daily/2026-06-17.md` later rendered `Recent runner artifacts` with:
  - skill patched 0
  - memory 3

The cron script is not the source of the bug. `~/.hermes/scripts/self-improvement-maintenance.sh` only runs:

```bash
hermes self-improvement status
hermes self-improvement improve
hermes self-improvement report --since-hours 24
```

The likely source is plugin report rendering: `hermes_self_improvement/cli.py::_render_operational_report_sections()` loads saved run JSON, then `_actual_result_summary_lines()` reconstructs mutation counts from `knowledge_transactions` or legacy `step_decisions`. If a run artifact has top-level `skill_changes` but lacks enough transaction detail, skill patched falls through to zero; memory already has a `summary.memory_changes` fallback.

Outcome credit status is conservative but opaque:

- recent run tracked 1000 episodes
- `proven improved: 0`
- `recurring: 14`
- `unknown: 925`
- `insufficient window: 61`

This should not be fixed by rewarding silence. It should be fixed by stronger episode/observation matching and clearer unknown breakdown.

---

## Non-goals

- Do not change cron job scheduling or script structure unless plugin report output proves impossible to fix there.
- Do not loosen mutation safety, skill target boundaries, memory provider boundaries, or GEPA promotion gates.
- Do not count “no observed failure” as positive improvement unless the relevant skill/workflow/memory was actually reused or an explicit outcome observation exists.
- Do not add a new role, lane, approval queue, or policy mode.
- Do not edit repo-managed base prompts for GEPA learning; runtime-private overlays remain the calibration target.

---

## Acceptance criteria

1. `hermes self-improvement report --since-hours 24` renders saved run artifact skill counts consistently with immediate `improve` output when `skill_changes` exists.
2. Report output distinguishes actual run mutations from heuristic proposal counts and diagnostic report proposals.
3. `Actual results` can recover skill patched/created counts from canonical transactions, legacy decisions, and top-level artifact fallback in that order.
4. Outcome credit summary breaks `unknown` into operationally useful sub-buckets such as no later comparable usage, weak usage only, scored but not decisive, and insufficient evidence detail.
5. Episode records include a compact matching signature that can link later observations to the same tool/error/target/evidence pattern without storing raw tool outputs.
6. Outcome scoring uses the matching signature to reduce false recurrence and false unrelated positives.
7. Runtime eval case generation gets better case metadata from real episodes/outcomes, while remaining bounded and deduped.
8. `_recent_json_files()` preserves the bounded run fields required by report rendering, especially `skill_changes` / `memory_changes`.
9. Dry-run verification checks returned payloads and read-only report output, not newly created episode files.
10. Full test suite, `py_compile`, `git diff --check`, `hermes self-improvement status`, and at least one read-only/dry-run report smoke pass.

---

## Phase 1 — Fix report/run artifact mutation accounting

### Task 1: Add a failing regression for top-level `skill_changes` fallback in operational reports

**Objective:** Prove that `Recent runner artifacts` reports skill mutations from a saved run artifact even when canonical transaction details are absent.

**Files:**
- Modify: `tests/test_cli_surface.py`
- Read: `hermes_self_improvement/cli.py`

**Test shape:** Add a test near existing `Recent runner artifacts` tests around lines that assert `skill patched ...`.

Construct an operational report payload with one recent run like:

```python
payloads = {
    "recent_runs": [{
        "path": "/tmp/run.json",
        "summary": {"skill_changes": 3, "memory_changes": 3, "scorer_evaluator_changed": False},
        "skill_changes": [
            "llm-context-optimization-integration",
            "hermes-gateway-and-sessions",
            "hermes-plugin-test-debugging",
        ],
        "memory_changes": ["memory_a", "memory_b", "memory_c"],
        "credit_assignment": {},
    }],
    "recent_evidence": [],
    "runtime_eval_cases": {},
    "calibration": {},
}
```

Assert rendered text contains:

```text
- actual mutations: skill created 0, skill patched 3, skill archived 0, references rewritten 0, memory 3
- patched skills: llm-context-optimization-integration, hermes-gateway-and-sessions, hermes-plugin-test-debugging
```

**Run:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_cli_surface.py -q -k 'Recent or actual or operational'
```

**Expected before implementation:** fail with `skill patched 0` or missing patched names.

---

### Task 2: Extend `_actual_result_summary_lines()` with explicit fallback inputs

**Objective:** Let report rendering pass top-level artifact `skill_changes` / `memory_changes` into the same summary helper without fabricating transaction details.

**Files:**
- Modify: `hermes_self_improvement/cli.py:1821-1973`
- Modify: call site in `hermes_self_improvement/cli.py:447-453`
- Modify: `hermes_self_improvement/cli.py:_recent_json_files()`

**Important data-path fix:** `_render_operational_report_sections()` does not read the full run JSON directly. It consumes rows produced by `_recent_json_files()`. Therefore Task 2 must first preserve the top-level artifact fields there; otherwise `artifact_skill_changes=latest_run.get("skill_changes")` will always be empty in the real report path.

In `_recent_json_files()`, keep the fields needed for bounded report rendering:

```python
for key in (
    "summary",
    "step_decisions",
    "credit_assignment",
    "skill_lifecycle",
    "knowledge_transactions",
    "skill_changes",
    "memory_changes",
    "action_summary",
):
    if key in payload:
        row[key] = payload.get(key)
```

If `knowledge_transactions` is too large for the existing compact row contract, keep the existing behavior and instead add a smaller `knowledge_transaction_summary` helper. Do not drop `skill_changes` / `memory_changes`; those are bounded lists of changed target ids and are required for this bugfix.

**Implementation:** Extend signature:

```python
def _actual_result_summary_lines(
    *,
    summary: dict[str, Any],
    skill_decisions: list[dict[str, Any]],
    memory_decisions: list[dict[str, Any]],
    planner_decisions: list[dict[str, Any]],
    knowledge_transactions: list[dict[str, Any]] | None = None,
    artifact_skill_changes: list[Any] | None = None,
    artifact_memory_changes: list[Any] | None = None,
) -> list[str]:
```

After canonical/legacy reconstruction, add fallback only when the reconstructed skill count is zero:

```python
if not created and not patched and not archived and artifact_skill_changes:
    patched = len([name for name in artifact_skill_changes if str(name or "").strip()])
    note_names(patched_names, artifact_skill_changes)
```

For memory, prefer explicit `artifact_memory_changes` before `summary.memory_changes`:

```python
if not memory_changed and artifact_memory_changes:
    memory_changed = len([name for name in artifact_memory_changes if str(name or "").strip()])
    note_names(memory_names, artifact_memory_changes)
if not memory_changed:
    memory_changed = int(summary.get("memory_changes") or 0)
```

At `_render_operational_report_sections()`, pass:

```python
artifact_skill_changes=latest_run.get("skill_changes") if isinstance(latest_run.get("skill_changes"), list) else None,
artifact_memory_changes=latest_run.get("memory_changes") if isinstance(latest_run.get("memory_changes"), list) else None,
```

**Run:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_cli_surface.py -q -k 'Recent or actual or operational'
```

**Expected:** new test passes; existing actual-result tests still pass.

---

### Task 3: Protect canonical transaction precedence

**Objective:** Ensure fallback does not double-count or override richer canonical transaction accounting.

**Files:**
- Modify: `tests/test_cli_surface.py`

**Test shape:** Create a payload with both:

- `knowledge_transactions` showing one patched skill `canonical-skill`
- top-level `skill_changes` showing `fallback-skill-a`, `fallback-skill-b`

Assert report says `skill patched 1` and `patched skills: canonical-skill`, not 2/3.

**Run:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_cli_surface.py -q -k 'canonical and fallback'
```

**Expected before implementation if Task 2 is too broad:** fail due to double-counting. Fix until canonical wins.

---

### Task 4: Add a live-artifact regression fixture for the 2026-06-17 shape

**Objective:** Lock the exact observed artifact shape into a compact fixture without copying the full 260KB run JSON.

**Files:**
- Modify: `tests/test_report_integration.py` or `tests/test_cli_surface.py`

**Fixture content:** Use only the fields involved:

```python
latest_run = {
    "path": "/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260616T190532Z.json",
    "summary": {"dry_run": False, "skill_changes": 3, "memory_changes": 3, "scorer_evaluator_changed": False},
    "skill_changes": ["hermes-gateway-and-sessions", "hermes-plugin-test-debugging", "llm-context-optimization-integration"],
    "memory_changes": ["memory_place_8d9362c1b6fc", "memory_place_eec8ee6e93ed", "memory_place_f2b1a0c2c0e2"],
    "action_summary": {"apply": 7, "defer": 21, "skip": 95, "block": 0},
}
```

Assert actual-result lines match the cron output semantics.

**Run:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_report_integration.py tests/test_cli_surface.py -q
```

---

### Task 5: Smoke the real report output against current runtime artifacts

**Objective:** Verify the fix against real saved artifacts, not only unit tests.

**Files:** none

**Commands:**

```bash
hermes self-improvement report --since-hours 24 | tee /tmp/self-improvement-report-smoke.md
python - <<'PY'
from pathlib import Path
text = Path('/tmp/self-improvement-report-smoke.md').read_text()
needle = 'skill created 0, skill patched 3, skill archived 0, references rewritten 0, memory 3'
print('has_expected_actual_results=', needle in text)
raise SystemExit(0 if needle in text else 1)
PY
```

**Expected:** `has_expected_actual_results= True` while the latest artifact remains the same 2026-06-17 run. If a newer run exists by implementation time, adjust the smoke to compare latest run JSON `skill_changes` length with rendered text.

---

## Phase 2 — Make outcome unknowns explainable in reports

### Task 6: Add unknown reason buckets to credit assignment summary

**Objective:** Split the large `unknown` bucket into useful operator-facing reasons without changing the underlying scoring policy.

**Files:**
- Modify: `hermes_self_improvement/credit_assignment.py`
- Modify: `tests/test_credit_assignment.py`

**Current-code note:** `credit_assignment.py` already has `quality_under_observation`, `duplicate_noop_credited`, `skill_usage_under_observation`, and `missing_evidence_under_observation`. Do not duplicate those. Add one explicit `unknown_reason_counts` / `unknown_reasons` surface that explains the unknown bucket more precisely.

**Implementation shape:** Add a helper:

```python
def _unknown_reason(row: dict[str, Any]) -> str | None:
    status = _outcome_status(row)
    if status != "unknown":
        return None
    observation_count = int(row.get("observation_count") or 0)
    components = row.get("components") if isinstance(row.get("components"), dict) else {}
    if observation_count <= 0:
        return "no_later_comparable_observation"
    if _has_only_weak_usage_positive(components):
        return "weak_usage_only"
    if row.get("score") is not None:
        return "scored_but_not_decisive"
    if not row.get("evidence_ids"):
        return "missing_evidence_link"
    return "unclassified_unknown"
```

Extend `_outcome_status_summary()` to return `unknown_reasons` counts, or add them to the `quality` dict under a clearer key:

```python
quality["unknown_reasons"] = {...}
quality["unknown_match_basis"] = {
    "no_observation": ...,
    "weak_usage_only": ...,
    "scored_not_decisive": ...,
    "missing_evidence_link": ...,
}
```

Do not add positive credit here. This phase is reporting/accounting only.

**Test cases:**

- executed/changed episode with no observations -> `insufficient_window`, not unknown
- non-executed/no observation -> `unknown_reasons.no_later_comparable_observation`
- positive component only `skill_used_without_correction` -> `weak_usage_only`
- numeric score 0 or positive with only quality penalties -> `scored_but_not_decisive`
- missing evidence ids -> `missing_evidence_link`

**Run:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests -q -k 'credit_assignment or outcome_status or unknown'
```

---

### Task 7: Render unknown reason buckets in CLI/report output

**Objective:** Make reports say why `unknown` is large.

**Files:**
- Modify: `hermes_self_improvement/cli.py:_outcome_summary_lines()` around line 1986
- Modify: `tests/test_cli_surface.py`

**Expected report lines:** Keep the existing compact summary, then add one bounded line when unknown reasons exist:

```text
- unknown breakdown: no later comparable observation 812, weak usage only 74, scored but not decisive 21, missing evidence link 18
```

Use human labels but keep stable keys in JSON artifacts.

**Test shape:** Feed a credit assignment payload with `quality.unknown_reasons` and assert line rendering.

**Run:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_cli_surface.py -q -k 'unknown breakdown or outcome'
```

---

### Task 8: Keep report wording conservative

**Objective:** Avoid implying unknown items are successes.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Modify: `tests/test_cli_surface.py`

**Rules:**

- Keep `proven improved` reserved for stronger positive evidence.
- Render weak-only usage as “under observation,” not “improved.”
- Render no later comparable observation as “not enough reuse yet,” not “good.”

**Test assertions:** Ensure rendered text contains:

```text
- unproven changes remain under observation
```

and does not contain phrases like:

```text
assumed improved
successful by silence
```

No source guard is needed for English phrases unless they already exist. This task can be folded into Task 7 if implementation stays small; keep it separate only if the wording needs a regression fixture.

---

## Phase 3 — Strengthen episode signatures for future credit assignment

### Task 9: Audit episode and outcome-observation creation surfaces

**Objective:** Identify all places that create `self_improvement_episode` records and all places that create outcome observations before changing schema.

**Files to inspect:**
- `hermes_self_improvement/episodes.py`
- `hermes_self_improvement/outcome_observer.py`
- `hermes_self_improvement/runner_steps.py`
- `hermes_self_improvement/cli.py`
- any files found by a repo search for `record.*episode|self_improvement_episode|episode_payload|outcome_observation|collect_.*observations`

**Deliverable:** Add a short implementation comment in the plan execution notes or commit message listing episode producers. Do not add code in this task unless tests reveal a single obvious helper location.

**Verification command:** Use an executable shell/Python command, not Hermes-only `search_files` syntax:

```bash
python - <<'PY'
from pathlib import Path
import re
root = Path('hermes_self_improvement')
pat = re.compile(r'self_improvement_episode|record.*episode|write.*episode|outcome_observation|collect_.*observations')
for path in sorted(root.glob('*.py')):
    text = path.read_text()
    if pat.search(text):
        print(path)
PY
```

---

### Task 10: Add a shared compact `matching_signature` helper

**Objective:** Give future outcome observations a stable, privacy-bounded key to match against, with one shared implementation used by episodes, observations, scoring, and runtime eval cases.

**Files:**
- Create: `hermes_self_improvement/outcome_matching.py`
- Test: new or existing episode tests, likely `tests/test_episode_ledger.py`

**Schema contract:**

```python
matching_signature_version = "1"
required_fields = {"target_kind", "action"}
optional_fields = {
    "target_id",
    "tool_name",
    "error_kind",
    "cluster_id",
    "evidence_ids_hash",
}
```

Normalization rules:

- Trim strings; normalize empty string / `None` to absent.
- Sort and dedupe evidence ids before hashing.
- Hash a stable JSON object with sorted keys and the version included.
- If `target_kind` or `action` is missing, set `matchable=false`; still emit bounded debug fields if useful, but do not use it as positive/recurrence proof.
- Never include raw stdout/stderr, raw memory text, raw `old_text`, full tool args, full tool results, or full prompt/context.
- Prefer exact `episode_id` match over signature match; prefer exact signature hash over derived fallback matching.

**Signature fields:** Build from already-bounded metadata only:

```python
{
    "target_kind": "skill" | "memory" | "evaluator" | "unknown",
    "target_id": "safe-patch-usage",
    "action": "skill_patch" | "memory_replace" | "placement_move" | ...,
    "tool_name": "patch" | "terminal" | "skill_manage" | None,
    "error_kind": "timeout" | "unknown_error" | None,
    "cluster_id": "c_..." | None,
    "evidence_ids_hash": "sha256:...",
}
```

Store both:

```python
"matching_signature_version": "1",
"matching_signature": {...bounded fields...},
"matching_signature_hash": "sha256:...",
"matching_signature_matchable": True,
```

Do not store raw stdout, raw old_text, full memory text, or full tool results.

**Test cases:**

- same logical fields in different dict order produce same hash
- evidence id order is normalized
- missing optional fields still produce a hash, but missing required fields set `matchable=false`
- raw long text is not included

**Run:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_episode_ledger.py -q -k 'signature or episode'
```

---

### Task 11: Populate episode signatures from existing planner/evidence data

**Objective:** Add signatures to newly recorded episodes without requiring a full observation pipeline rewrite.

**Files:**
- Modify episode creation call sites found in Task 9
- Modify tests covering episode recording, likely `tests/test_episode_ledger.py` and `tests/test_cli_surface.py`

**Mapping rules:**

- Skill transaction:
  - `target_kind=skill`
  - `target_id`: target skill name
  - `action`: canonical action/decision/transaction kind
  - `evidence_ids_hash`: from `evidence_ids`
- Memory transaction:
  - `target_kind=memory`
  - `target_id`: memory candidate id or store + candidate id, not raw text
  - `action`: `memory_add`, `memory_replace`, `placement_move`, `placement_split`, etc.
- Cluster-derived skill improvement:
  - include `tool_name`, `error_kind`, `cluster_id` when present in evidence/cluster data
- Evaluator/prompt overlay episode:
  - `target_kind=evaluator`
  - `target_id`: overlay generation id / role when available

**Fail-safe:** If required fields are missing, keep mutation execution unblocked but mark `matching_signature_matchable=false`. Do not let unknown/missing signatures create positive or recurrence credit later.

**Run:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_episode_ledger.py tests/test_runtime_eval_cases.py -q
```

---

### Task 12: Add observation-side signature extraction and stricter recurrence matching

**Objective:** Let later observations match the same target/tool/error/evidence pattern when possible, and avoid broad “similar failure” matches.

**Files:**
- Modify: `hermes_self_improvement/outcome_observer.py`
- Modify: `hermes_self_improvement/outcome_scoring.py`
- Modify: tests for outcome scoring; create `tests/test_outcome_scoring.py` if none exists

**Implementation shape:**

Use the shared helper from `outcome_matching.py`:

```python
def observation_matching_signature(observation: dict[str, Any]) -> dict[str, Any]:
    ...
```

When `outcome_observer.py` creates observations, include bounded fields when available:

```python
"matching_signature": {...},
"matching_signature_hash": "sha256:...",
"match_basis": "episode_id" | "signature_hash" | "target_cluster" | "diagnostic_only",
```

Update observation source/dedupe helpers, including `_source_key()`, so explicit `episode_id` and exact signature hashes dedupe stably before broader diagnostic keys.

Use available bounded observation fields:

- `episode_id` if explicitly present: exact match wins
- `matching_signature_hash` if present: exact match
- else derive from `target_id`, `target_kind`, `tool_name`, `error_kind`, `cluster_id`

Update scoring so recurrence penalties require one of:

1. explicit `episode_id` match
2. exact `matching_signature_hash` match
3. same `target_kind + target_id + non-generic cluster_id`

Do not treat unrelated same-tool failures as recurrence. Do not use `tool_name/error_kind` alone, and do not use generic clusters such as `terminal timeout`, `patch unknown_error`, or `skill_manage unknown_error` as recurrence proof. Those may remain diagnostic-only.

**Tests:**

- same `terminal/timeout` but different target does not penalize the episode
- same target + generic terminal timeout does not penalize without exact signature or non-generic cluster
- same target + non-generic cluster penalizes recurrence
- explicit user correction with episode id remains strong negative
- explicit outcome score still works

---

## Phase 4 — Improve runtime eval case quality from real outcomes

### Task 13: Include signature and outcome status metadata in runtime eval cases

**Objective:** Make GEPA/evaluator cases more useful by attaching why a case exists and what status it teaches.

**Files:**
- Modify: `hermes_self_improvement/runtime_eval_cases.py`
- Modify: `tests/test_runtime_eval_cases.py`

**Fields to add to each generated case when available:**

```python
"source_episode_id": "...",
"source_matching_signature_hash": "sha256:...",
"outcome_status": "recurring" | "regressed" | "unknown" | "improved",
"outcome_components": ["cluster_reappeared_penalty", "user_correction_penalty"],
"credit_window": "immediate" | "short" | "medium" | "long",
```

Keep cases bounded. Do not include raw memory content or full traces.

Case hash/dedupe must account for signature metadata. Prefer dedupe by `source_matching_signature_hash + case_type` when a matchable signature exists; otherwise fall back to the existing `case_hash` behavior.

**Tests:** Existing tests around recurring/regressed episodes should assert new metadata exists.

---

### Task 14: Prefer high-signal cases when building overlay runtime eval cases

**Objective:** Reduce low-value weak/noisy cases in GEPA input without changing promotion gates.

**Files:**
- Modify: `hermes_self_improvement/runtime_eval_cases.py`
- Modify: `tests/test_runtime_eval_cases.py`

**Selection priority:**

1. user correction / explicit negative outcome
2. recurrence after mutation
3. regression after mutation
4. strong no-op correctness cases only when there is explicit evidence, e.g. duplicate prevented with a recorded no-op episode or existing skill sufficient with later explicit successful reuse
5. weak usage-only cases last, capped tightly and never treated as proven improvement

Caps:

- cap cases per source episode to avoid one noisy episode dominating
- cap cases per family (`user_correction`, `recurrence`, `regression`, `noop_correctness`, `weak_usage`)
- do not emit generic recurrence cases from broad tool/error clusters unless an exact signature or explicit episode id exists

**Tests:** Build fixture episodes/outcomes and assert selected cases follow priority and dedupe by signature hash.

---

## Phase 5 — End-to-end verification and dogfood

### Task 15: Run focused suites

**Objective:** Validate changed surfaces quickly before full suite.

**Command:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest \
  tests/test_cli_surface.py \
  tests/test_report_integration.py \
  tests/test_episode_ledger.py \
  tests/test_runtime_eval_cases.py \
  -q
```

**Expected:** all pass.

---

### Task 16: Run full static and test verification

**Objective:** Meet repo verification standard.

**Commands:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
git diff --check
hermes self-improvement status
```

**Expected:**

- py_compile passes
- full pytest passes
- diff check clean
- status shows plugin enabled, runtime initialized, evaluator ready, prompt overlays ready

---

### Task 17: Read-only runtime report smoke

**Objective:** Verify reporting improvement against real artifacts without mutating skill/memory.

**Commands:**

```bash
hermes self-improvement report --since-hours 24 | tee /tmp/self-improvement-report-after.md
python - <<'PY'
from pathlib import Path
text = Path('/tmp/self-improvement-report-after.md').read_text()
required = [
    'Actual results:',
    'unknown breakdown:',
    'unproven changes remain under observation',
]
for item in required:
    print(item, item in text)
raise SystemExit(0 if all(item in text for item in required) else 1)
PY
```

If the latest saved run at implementation time has no skill changes, compare the rendered count against the latest JSON artifact rather than hard-coding 3.

---

### Task 18: Dry-run improvement smoke

**Objective:** Ensure new episode/signature fields do not break normal dry-run planning.

**Command:**

```bash
hermes self-improvement improve --dry-run --json > /tmp/self-improvement-dry-run-after.json
python - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path('/tmp/self-improvement-dry-run-after.json').read_text())
print('dry_run=', payload.get('summary', {}).get('dry_run'))
print('artifact=', payload.get('artifact_path'))
raise SystemExit(0 if payload.get('summary', {}).get('dry_run') is True else 1)
PY
```

**Expected:** dry-run succeeds, no target changes.

---

### Task 19: Inspect dry-run payload and existing artifacts without expecting dry-run side effects

**Objective:** Confirm dry-run still succeeds and, if existing recent artifacts already contain signature fields after a mutating run, they are bounded. Do not require dry-run to create new episode files.

**Commands:**

```bash
python - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path('/tmp/self-improvement-dry-run-after.json').read_text())
print('dry_run=', payload.get('summary', {}).get('dry_run'))
print('target_changed=', payload.get('target_changed'))
if payload.get('summary', {}).get('dry_run') is not True:
    raise SystemExit('dry_run output was not marked dry_run=true')
root = Path.home() / '.hermes/self-improvement/episodes'
for path in sorted(root.glob('**/*.json'))[-20:]:
    data = json.loads(path.read_text())
    sig = data.get('matching_signature')
    if sig:
        serialized = json.dumps(sig, ensure_ascii=False)
        if len(serialized) > 2000 or 'stdout' in serialized or 'stderr' in serialized:
            raise SystemExit(f'unbounded signature in {path}')
        print('bounded_existing_signature=', path)
        break
print('ok')
PY
```

**Expected:** dry-run remains non-mutating. Existing signature artifacts, if present, are bounded. If no existing signature artifacts are present yet because no mutating run has occurred after implementation, this smoke still passes.

---

### Task 20: Update this plan and index after implementation

**Objective:** Keep repo-tracked plan state accurate.

**Files:**
- Modify: `.hermes/plans/2026-06-17-report-accounting-and-outcome-credit-hardening.md`
- Modify: `.hermes/plans/README.md`

**Update with:**

- implemented commit hash/message
- focused and full verification counts
- report smoke result path
- dry-run artifact path
- any remaining follow-up, especially if outcome matching still leaves many unknowns for legitimate “no later usage” reasons

**Do not claim outcome quality is proven** unless later scheduled observation shows actual positive/negative evidence.

---

## Commit sequence

Use small commits:

1. `test: cover report artifact skill fallback accounting`
2. `fix: align report artifact mutation accounting`
3. `feat: explain unknown outcome credit buckets`
4. `feat: add outcome matching signatures to episodes`
5. `feat: prioritize high-signal runtime eval cases`
6. `docs: update self-improvement hardening plan status`

If implementation reveals that Phases 3–4 are larger than expected, stop after commits 1–3 once Phase 1/2 is fully green and create a follow-up plan for signature/eval-case work. Do not mix risky scoring changes into the accounting bugfix commit. Phase 1 should be independently mergeable.

---

## Risks and guardrails

- **Risk:** Fallback accounting double-counts canonical transactions.  
  **Guard:** canonical transaction precedence test in Task 3.

- **Risk:** Outcome credit becomes too optimistic.  
  **Guard:** no-silence-positive rule and tests for weak usage only remaining unknown/under-observation.

- **Risk:** Matching signatures leak raw memory/tool content.  
  **Guard:** signature tests assert bounded ids/hashes only.

- **Risk:** Recurrence matching becomes too narrow and misses real regressions.  
  **Guard:** explicit episode id and exact signature matches always win; fallback recurrence requires same target and non-generic cluster. Broad tool/error recurrence stays diagnostic-only.

- **Risk:** Runtime eval cases become noisy.  
  **Guard:** high-signal priority and dedupe by signature hash.

---

## Recommended first implementation slice

Start with Phase 1 only. It is a clear bug, low-risk, and immediately improves trust in daily reports. Then do Phase 2 as a reporting-only clarity improvement. Phases 3–4 are the real outcome-credit quality work and should be implemented after the report accounting fix is merged and dogfooded.
