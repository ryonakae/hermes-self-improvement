# Outcome Scoring Calibrate Prepass Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** `calibrate` の前処理で、前回 `calibrate` 以降に増えた観測を読み、関係する `improve` episode にだけ outcome observation を紐づけて採点できるようにする。

**Architecture:** `improve` は既存どおり episode を append-only で記録する。`calibrate` は実行前に lightweight producer を呼び、未処理観測から `self_improvement_outcome_observation` を生成して `${HERMES_HOME}/self-improvement/outcomes/` に保存する。既存の `outcome_scoring.py` / `credit_assignment.py` / `calibration.py` は、その observation を読んで GEPA / overlay calibration evidence に反映する。

**Tech Stack:** Python 3, pytest, JSON artifact ledgers under `${HERMES_HOME:-~/.hermes}/self-improvement/`, existing plugin CLI `bin/hermes-self-improve`.

---

## Decisions captured from the design discussion

- Outcome scoring policy: automatic observation is primary; explicit feedback is a strong label.
- Initial automatic signals:
  - `user_correction_recurrence`
  - `same_failure_cluster_recurrence`
  - `target_reedit_shortly_after_mutation`
- Execution location: `calibrate` prepass.
- Collection window:
  - Normal: since previous `calibrate` run.
  - First run fallback: since latest `improve` run; if unavailable, last 7 days.
- Attribution:
  - Score only observations that can be tied to a specific episode.
  - Unmatched observations are recorded in the prepass artifact but not scored.
- Positive handling:
  - Explicit positive / regression pass can be strong.
  - Automatic positive should stay weak; silence is not success.
- Scope exclusions:
  - Do not add `outcome` / `record_outcome` as a primary CLI/tool surface.
  - Do not run this from runtime hooks.
  - Do not mutate Hermes core.
  - Do not add a broad LLM classifier/normalizer before the attribution logic.

---

## Current code context

Relevant existing files:

- `hermes_self_improvement/episodes.py`
  - `record_run_episodes()` already writes append-only `self_improvement_episode` files under `episodes/YYYY-MM-DD/`.
  - `record_calibration_episodes()` already records calibration/prompt candidate episodes.
  - `load_recent_episodes()` loads recent episode JSON files.
- `hermes_self_improvement/outcome_scoring.py`
  - Already defines `load_outcome_observations()`, `score_episode_outcomes()`, and `build_outcome_score_aggregate()`.
  - Existing schema: `self_improvement_outcome_observation` with `episode_id`, `observed_at`, `window`, `signals`, `outcome_score`, `confidence`.
- `hermes_self_improvement/credit_assignment.py`
  - Already aggregates outcome scores by prompt hash, target kind, target id, decision, action, evidence strength, and window.
- `hermes_self_improvement/calibration.py`
  - `collect_calibration_evidence()` already calls `build_outcome_score_aggregate()` and `build_credit_assignment_aggregate()`.
  - It currently reads existing outcome observations but does not produce new observations before evidence collection.
- Existing tests:
  - `tests/test_episode_ledger.py`
  - `tests/test_outcome_scoring.py`
  - `tests/test_credit_assignment.py`
  - `tests/test_calibration.py`

Likely new file:

- `hermes_self_improvement/outcome_observer.py`

Likely new tests:

- `tests/test_outcome_observer.py`
- Small additions to `tests/test_calibration.py`

---

## Data model

### New prepass artifact

Write one compact artifact per `calibrate` run attempt:

```text
${self_improvement_root}/outcome-prepass/YYYY-MM-DD/<timestamp>-<hash>.json
```

Suggested schema:

```json
{
  "schema_name": "self_improvement_outcome_prepass",
  "schema_version": "1.0",
  "created_at": "2026-05-05T13:08:17+00:00",
  "collection_window": {
    "mode": "since_previous_calibrate",
    "start": "2026-05-04T08:00:00+00:00",
    "end": "2026-05-05T13:08:17+00:00",
    "fallback_used": false
  },
  "episode_count": 4,
  "candidate_observation_count": 6,
  "written_observation_count": 3,
  "unmatched_observation_count": 3,
  "deduped_observation_count": 1,
  "signals": {
    "user_correction_recurrence": 1,
    "same_failure_cluster_recurrence": 1,
    "target_reedit_shortly_after_mutation": 1
  },
  "observation_paths": [".../outcomes/2026-05-05/....json"],
  "unmatched": [
    {
      "reason": "target_not_resolved",
      "signal": "user_correction_recurrence",
      "source_path": "..."
    }
  ]
}
```

Keep this artifact compact. Do not include full session transcripts, full evidence bodies, full prompt text, or editor instructions.

### Observation schema additions

Continue using `self_improvement_outcome_observation`. Add small optional fields only:

```json
{
  "schema_name": "self_improvement_outcome_observation",
  "schema_version": "1.0",
  "episode_id": "episode-...",
  "observed_at": "2026-05-05T13:00:00+00:00",
  "window": "short",
  "signals": {
    "user_correction": true,
    "user_correction_recurrence": true
  },
  "outcome_score": -0.8,
  "confidence": 0.9,
  "source": {
    "kind": "automatic_observation",
    "signal": "user_correction_recurrence",
    "source_path": "...",
    "match_kind": "target_id"
  }
}
```

Do not store raw user messages or large snippets. If a snippet is useful, cap it to a short redacted summary.

---

## Task 1: Add read-only window state helpers

**Objective:** Determine the collection window for a calibrate prepass without relying on `improve` and `calibrate` being 1:1.

**Files:**
- Create: `hermes_self_improvement/outcome_observer.py`
- Test: `tests/test_outcome_observer.py`

**Step 1: Write failing tests**

Add tests for:

1. Previous calibrate exists → start at most recent calibration episode or calibration ledger timestamp.
2. No previous calibrate but improve episode exists → start at latest run episode timestamp.
3. Neither exists → start at `now - 7 days`.
4. End is always `now`.

Suggested helper names:

```python
from datetime import datetime, timezone

from hermes_self_improvement.outcome_observer import determine_collection_window


def test_collection_window_prefers_previous_calibrate(tmp_path):
    config = {"_self_improvement_root": str(tmp_path / "self-improvement")}
    now = datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc)
    # write calibration episode and older improve episode
    window = determine_collection_window(config=config, now=now)
    assert window["mode"] == "since_previous_calibrate"
    assert window["start"] == "2026-05-05T09:00:00+00:00"
```

**Step 2: Run test to verify failure**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_outcome_observer.py -q
```

Expected: FAIL because `outcome_observer.py` does not exist.

**Step 3: Implement minimal helpers**

Implement:

```python
def determine_collection_window(*, config: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    ...
```

Rules:

- Load recent episodes with existing `load_recent_episodes(config=config, limit=1000)`.
- Previous calibrate marker can be any episode with `target_kind in {"planner_prompt", "editor_prompt", "evaluator"}` or `episode_kind in {"prompt_candidate", "prompt_promotion", "calibration_update"}`.
- Latest improve marker can be an episode with `target_kind in {"skill", "memory"}`.
- Parse `created_at` as UTC-aware datetime.
- Return ISO timestamps and `fallback_used` boolean.

Do not write any files in this task.

**Step 4: Run tests**

```bash
$PY -m pytest tests/test_outcome_observer.py -q
```

Expected: PASS for new window tests.

**Step 5: Commit**

```bash
git add hermes_self_improvement/outcome_observer.py tests/test_outcome_observer.py
git commit -m "feat: add outcome prepass window helpers"
```

---

## Task 2: Add outcome observation writer with dedupe

**Objective:** Write append-only outcome observations, but avoid recording the same episode/signal/source more than once.

**Files:**
- Modify: `hermes_self_improvement/outcome_observer.py`
- Test: `tests/test_outcome_observer.py`

**Step 1: Write failing tests**

Add tests for:

1. A valid candidate observation writes one JSON file under `outcomes/YYYY-MM-DD/`.
2. Re-running the same candidate does not create a duplicate.
3. Invalid observations fail closed and appear in prepass `unmatched` / `skipped`, not as written outcomes.

Candidate shape for tests:

```python
candidate = {
    "episode_id": "episode-1",
    "observed_at": "2026-05-05T10:00:00+00:00",
    "window": "short",
    "signals": {"user_correction_recurrence": True, "user_correction": True},
    "outcome_score": -0.8,
    "confidence": 0.9,
    "source": {"kind": "automatic_observation", "signal": "user_correction_recurrence", "source_path": "/tmp/source.json"},
}
```

**Step 2: Run test to verify failure**

```bash
$PY -m pytest tests/test_outcome_observer.py -q
```

Expected: FAIL because writer helpers are missing.

**Step 3: Implement minimal writer**

Implement:

```python
def outcome_observation_root(config: dict[str, Any]) -> Path:
    return _reports_dir(config) / "outcomes"


def write_outcome_observations(
    *,
    config: dict[str, Any],
    candidates: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    ...
```

Implementation notes:

- Use existing `validate_outcome_observation()` from `autonomous_loop.py`.
- Dedupe key should include:
  - `episode_id`
  - primary source signal
  - source path or source id
  - observed date/time bucket if needed
- Deduping can read existing files with `load_outcome_observations(config=config, limit=5000)`.
- Filename can be `<timestamp>-<sha12>.json`.
- Return compact summary only.

**Step 4: Run tests**

```bash
$PY -m pytest tests/test_outcome_observer.py tests/test_outcome_scoring.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add hermes_self_improvement/outcome_observer.py tests/test_outcome_observer.py
git commit -m "feat: write deduped outcome observations"
```

---

## Task 3: Implement target re-edit attribution

**Objective:** Generate weak negative observations when the same mutable target is edited again shortly after a prior executed mutation.

**Files:**
- Modify: `hermes_self_improvement/outcome_observer.py`
- Test: `tests/test_outcome_observer.py`

**Step 1: Write failing tests**

Cases:

1. Episode A edits `skill:demo-skill` at 09:00; Episode B edits the same target at 12:00 before calibrate → produce observation for Episode A.
2. Different target → no observation.
3. Preview/no-op episode → no observation.
4. Re-edit outside the collection window or beyond 7 days → no observation.

Expected observation:

```json
{
  "signals": {
    "target_reedit_shortly_after_mutation": true,
    "repeat_fix_needed": true
  },
  "outcome_score": -0.3,
  "confidence": 0.4
}
```

**Step 2: Run test to verify failure**

```bash
$PY -m pytest tests/test_outcome_observer.py -q
```

Expected: FAIL.

**Step 3: Implement generator**

Implement:

```python
def collect_target_reedit_observations(
    *,
    episodes: list[dict[str, Any]],
    window: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ...
```

Rules:

- Only consider prior episodes where:
  - `episode_kind == "executed_mutation"`
  - `executed is True`
  - `changed is True`
  - `target_kind in {"skill", "memory"}`
- A later episode on the same `(target_kind, target_id)` within 7 days is a weak negative.
- Attribute the observation to the earlier episode.
- If the later episode is only preview/no-op, do not count it.

**Step 4: Run tests**

```bash
$PY -m pytest tests/test_outcome_observer.py tests/test_outcome_scoring.py tests/test_credit_assignment.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add hermes_self_improvement/outcome_observer.py tests/test_outcome_observer.py
git commit -m "feat: observe target re-edits after mutations"
```

---

## Task 4: Implement same failure cluster recurrence attribution

**Objective:** Generate medium-confidence negative observations when an episode’s evidence ids or failure cluster identifiers reappear after the mutation.

**Files:**
- Modify: `hermes_self_improvement/outcome_observer.py`
- Possibly inspect/modify: `hermes_self_improvement/analysis.py`, `hermes_self_improvement/evidence.py`
- Test: `tests/test_outcome_observer.py`

**Step 1: Inspect existing evidence event shapes**

Read only:

```bash
# Use search/read tools, not shell grep/cat.
```

Look for fields such as:

- `evidence_id`
- `evidence_ids`
- `failure_cluster`
- `cluster_id`
- `tool_error_cluster`
- `error_signature`
- `source_path`

**Step 2: Write failing tests using the actual existing shape**

Do not invent a broad new event schema. Use the smallest field set already present in run/evidence artifacts.

Minimum test intent:

1. Episode has `evidence_ids: ["cluster:gws-auth"]` or equivalent cluster hint.
2. Later observation/event in collection window contains the same cluster id.
3. Candidate observation is attributed to that episode.
4. Unmatched cluster event is recorded as unmatched, not scored.

Expected observation:

```json
{
  "signals": {
    "same_failure_cluster_recurrence": true,
    "tool_error_cluster_reappeared": true
  },
  "outcome_score": -0.6,
  "confidence": 0.6
}
```

**Step 3: Implement small collector**

Implement:

```python
def collect_failure_cluster_recurrence_observations(
    *,
    config: dict[str, Any],
    episodes: list[dict[str, Any]],
    window: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ...
```

Rules:

- Use existing runtime artifacts under `_reports_dir(config)`.
- Do not parse full transcripts.
- Match only explicit stable identifiers. Avoid fuzzy LLM matching.
- If there is no stable cluster id, leave unmatched with reason `cluster_identifier_missing`.
- Attribute only to episodes created before the recurring event.

**Step 4: Run tests**

```bash
$PY -m pytest tests/test_outcome_observer.py tests/test_outcome_scoring.py tests/test_calibration.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add hermes_self_improvement/outcome_observer.py tests/test_outcome_observer.py
git commit -m "feat: observe recurring failure clusters"
```

---

## Task 5: Implement user correction recurrence attribution

**Objective:** Generate high-confidence negative observations when a later user correction can be attributed to the same target or evidence as an executed episode.

**Files:**
- Modify: `hermes_self_improvement/outcome_observer.py`
- Possibly inspect/modify: `hermes_self_improvement/observer.py`, `hermes_self_improvement/analysis.py`
- Test: `tests/test_outcome_observer.py`

**Step 1: Inspect existing correction signal shape**

Use read/search tools to identify existing telemetry fields for user corrections/session outcomes. Candidate fields may include:

- `user_correction`
- `correction`
- `session_outcome`
- `negative_feedback`
- `target_hint`
- `target_kind`
- `target_id`
- `evidence_id`

**Step 2: Write failing tests using existing shape**

Cases:

1. Later correction event explicitly references same `target_kind` and `target_id` → attribute to episode.
2. Later correction references an `evidence_id` from the episode → attribute to episode.
3. Correction has no target/evidence match → unmatched only.
4. Correction predates the episode → no attribution.

Expected observation:

```json
{
  "signals": {
    "user_correction_recurrence": true,
    "user_correction": true
  },
  "outcome_score": -0.8,
  "confidence": 0.9
}
```

**Step 3: Implement collector**

Implement:

```python
def collect_user_correction_recurrence_observations(
    *,
    config: dict[str, Any],
    episodes: list[dict[str, Any]],
    window: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ...
```

Rules:

- Match explicit target/evidence only.
- Do not use broad natural-language similarity in this slice.
- Cap any stored reason/snippet to a short redacted string.
- Use confidence `0.9` for explicit target/evidence matches.

**Step 4: Run tests**

```bash
$PY -m pytest tests/test_outcome_observer.py tests/test_outcome_scoring.py tests/test_credit_assignment.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add hermes_self_improvement/outcome_observer.py tests/test_outcome_observer.py
git commit -m "feat: observe recurring user corrections"
```

---

## Task 6: Add calibrate prepass orchestration

**Objective:** Make `calibrate` run the outcome observation producer before collecting calibration evidence.

**Files:**
- Modify: `hermes_self_improvement/calibration.py`
- Modify: `hermes_self_improvement/outcome_observer.py`
- Test: `tests/test_calibration.py`

**Step 1: Write failing test**

Add a test that:

1. Creates an executed skill mutation episode.
2. Creates a later same-target executed mutation or correction/failure fixture in the collection window.
3. Calls the calibrate entry path that invokes `collect_calibration_evidence()` or `run_calibration()`.
4. Asserts outcome prepass wrote an observation before `build_outcome_score_aggregate()` is summarized.

Expected assertion examples:

```python
result = run_calibration(config=config, dry_run=True)
assert result["evidence"]["outcome_scores"]["observation_count"] == 1
assert result["evidence"]["outcome_prepass"]["written_observation_count"] == 1
```

Adjust field path to the actual result shape.

**Step 2: Run test to verify failure**

```bash
$PY -m pytest tests/test_calibration.py::test_calibrate_runs_outcome_prepass_before_evidence -q
```

Expected: FAIL because calibrate does not invoke the prepass yet.

**Step 3: Implement orchestrator**

Implement in `outcome_observer.py`:

```python
def run_outcome_prepass(*, config: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    window = determine_collection_window(config=config, now=now)
    episodes = load_recent_episodes(config=config, limit=1000)
    candidates = []
    unmatched = []
    for collector in (...):
        new_candidates, new_unmatched = collector(...)
        candidates.extend(new_candidates)
        unmatched.extend(new_unmatched)
    write_summary = write_outcome_observations(config=config, candidates=candidates, now=now)
    return write_prepass_artifact(...)
```

Then in `calibration.py`, call this before existing `build_outcome_score_aggregate()` / `build_credit_assignment_aggregate()` logic.

Suggested integration point:

```python
def collect_calibration_evidence(...):
    ...
    outcome_prepass = run_outcome_prepass(config=config, now=now)
    summary["outcome_prepass"] = compact_prepass_summary(outcome_prepass)
    outcome_scores = build_outcome_score_aggregate(config=config, limit=1000)
```

Avoid recursion: if prepass scans `_reports_dir(config)`, it must ignore `outcome-prepass` artifacts and existing `self_improvement_outcome_observation` when looking for source events.

**Step 4: Run focused tests**

```bash
$PY -m pytest tests/test_outcome_observer.py tests/test_outcome_scoring.py tests/test_credit_assignment.py tests/test_calibration.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add hermes_self_improvement/outcome_observer.py hermes_self_improvement/calibration.py tests/test_outcome_observer.py tests/test_calibration.py
git commit -m "feat: collect outcome observations before calibration"
```

---

## Task 7: Keep agent-facing output compact

**Objective:** Surface outcome prepass counts without dumping full unmatched observations or source event bodies into LLM-facing tool results.

**Files:**
- Modify: `hermes_self_improvement/tool_handlers.py`
- Modify if needed: `hermes_self_improvement/cli.py`
- Test: `tests/test_plugin_tools.py`, `tests/test_cli_surface.py`

**Step 1: Write failing tests**

Add/extend tests to assert `self_improvement_calibrate(dry_run=True)` returns only compact fields:

- `evidence.outcome_prepass.written_observation_count`
- `evidence.outcome_prepass.unmatched_observation_count`
- `evidence.outcome_prepass.artifact_path`
- no full `unmatched` list
- no raw source events

**Step 2: Run tests to verify failure**

```bash
$PY -m pytest tests/test_plugin_tools.py tests/test_cli_surface.py -q
```

Expected: FAIL if full prepass leaks or fields are absent.

**Step 3: Implement compact summary**

If needed, add:

```python
def compact_outcome_prepass_summary(prepass: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": prepass["collection_window"]["mode"],
        "written_observation_count": prepass["written_observation_count"],
        "unmatched_observation_count": prepass["unmatched_observation_count"],
        "deduped_observation_count": prepass["deduped_observation_count"],
        "signals": prepass.get("signals", {}),
        "artifact_path": prepass.get("artifact_path"),
    }
```

Keep full details only in the artifact.

**Step 4: Run tests**

```bash
$PY -m pytest tests/test_plugin_tools.py tests/test_cli_surface.py tests/test_calibration.py -q
```

Expected: PASS.

**Step 5: Commit**

```bash
git add hermes_self_improvement/tool_handlers.py hermes_self_improvement/cli.py hermes_self_improvement/calibration.py tests/test_plugin_tools.py tests/test_cli_surface.py tests/test_calibration.py
git commit -m "fix: keep outcome prepass summaries compact"
```

---

## Task 8: Add docs and operational notes

**Objective:** Document the outcome scoring prepass so future sessions do not re-open the same design questions.

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md` if command/verification guidance changes
- Modify: `skills/operations/SKILL.md`
- Modify: `skills/operations/references/architecture.md` if present and relevant
- Modify: `skills/operations/references/operations.md` if present and relevant

**Step 1: Update docs**

Document briefly:

- `improve` records episodes.
- `calibrate` collects outcome observations since previous calibrate.
- Observations are attributed to episodes only on explicit matches.
- Unmatched observations stay in artifacts and are not scored.
- Agent-facing outputs remain compact.

Do not over-explain. README should stay user-facing and short.

**Step 2: Validate docs/code formatting**

```bash
$PY -m py_compile __init__.py hermes_self_improvement/*.py
git diff --check
```

Expected: PASS.

**Step 3: Commit**

```bash
git add README.md AGENTS.md skills/operations/SKILL.md skills/operations/references/architecture.md skills/operations/references/operations.md
git commit -m "docs: document calibration outcome prepass"
```

If some listed files were not changed, omit them from `git add`.

---

## Task 9: Full validation and dogfood smoke

**Objective:** Prove the implementation is correct, compact, and does not mutate outside intended surfaces.

**Files:**
- No source files unless tests reveal bugs.

**Step 1: Run focused test suite**

```bash
$PY -m pytest tests/test_outcome_observer.py tests/test_outcome_scoring.py tests/test_credit_assignment.py tests/test_calibration.py tests/test_plugin_tools.py tests/test_cli_surface.py -q
```

Expected: all pass.

**Step 2: Run full test suite**

```bash
$PY -m pytest tests -q
```

Expected: all pass. Existing skips are acceptable.

**Step 3: Compile**

```bash
$PY -m py_compile __init__.py hermes_self_improvement/*.py
```

Expected: no output / exit 0.

**Step 4: CLI smoke**

```bash
bin/hermes-self-improve status
bin/hermes-self-improve calibrate --dry-run
```

Expected:

- `status` succeeds.
- `calibrate --dry-run` succeeds.
- Output remains short.
- Full prepass details are in an artifact path, not printed inline.

**Step 5: Check diff and push**

```bash
git diff --check
git status --short --branch
git push
```

Expected:

- `git diff --check` passes.
- Branch is clean after commits.
- Push succeeds.

---

## Risks and tradeoffs

### Risk: automatic attribution becomes too fuzzy

Mitigation:

- Match only explicit target/evidence/failure-cluster identifiers in this slice.
- Put unmatched observations in artifact, not scoring.
- Do not add LLM fuzzy matching.

### Risk: duplicate scoring across repeated calibrate runs

Mitigation:

- Dedupe observation writes by episode + signal + source id/path.
- Collection window starts at previous calibrate, but dedupe is still required because failed/interrupted runs may repeat.

### Risk: self-congratulatory positive scoring

Mitigation:

- Do not score silence as strong success.
- Keep automatic positive weak or absent in initial implementation.
- Strong positive should come from explicit feedback or regression pass.

### Risk: prepass bloats tool result

Mitigation:

- Tool/CLI summary returns only counts and artifact path.
- Full unmatched list and source details stay in `outcome-prepass` artifact.

### Risk: old medium/long outcome window assumptions remain in code

Mitigation:

- Do not remove existing window buckets yet; keep compatibility.
- Initial producer can use `immediate` / `short` only.
- Existing scoring aggregation can continue reporting all buckets.

---

## Open questions to resolve during implementation

1. What is the current stable runtime artifact shape for user correction events?
   - Resolve by inspecting `observer.py`, `analysis.py`, and existing fixture/tests.
2. What is the current stable field for failure clusters?
   - Prefer existing `evidence_ids` or explicit cluster ids; do not invent fuzzy matching.
3. Should calibration episodes themselves be eligible for outcome attribution?
   - Initial answer: no, this slice attributes only skill/memory `improve` mutations. Prompt/evaluator outcome can be a later follow-up.
4. Should `target_reedit_shortly_after_mutation` apply to memory targets?
   - Initial answer: yes if the same `target_id` is explicit, but treat it as weak negative.

---

## Follow-up plan candidates, not part of this slice

- Outcome attribution for prompt overlay / evaluator calibration episodes.
- Explicit feedback ingestion if a clean existing source does not already exist.
- A real evaluator regression runner, once outcome observations are producing useful cases.
- More nuanced positive outcomes beyond explicit feedback and regression pass.
