# Environment Signal Dedup Implementation Plan

> **For Hermes:** Use test-driven-development skill to implement this plan task-by-task.

**Goal:** Prevent repeated `environment_fact_signal` candidates from wasting memory-agent candidate caps, especially duplicate `ambiguous_skill_resolution` signals.

**Architecture:** Keep the existing evidence -> compact signal -> memory_agent handoff flow. Add deterministic aggregation inside `collect_environment_fact_signals()` after signal construction but before limit/cap pressure. Use a stable dedup key derived from compact semantic fields (`signal_quality`, `tool_name`, `error_kind`, `stable_identifiers`, normalized `value_tokens`) rather than session id. Preserve auditability with `occurrence_count`, bounded `session_ids`, and support previews; do not send raw events to `memory_agent`.

**Tech Stack:** Python, pytest, existing `hermes_self_improvement.evidence`, `runner_steps`, and dry-run artifact verification.

---

## Current state

Implemented before this plan:

- `memory_inventory_candidate`, suspicious `memory_placement_candidate`, `memory_gap_candidate`, and `environment_fact_signal` can reach `memory_agent`.
- Generic value-token noise is filtered before environment signal creation.
- Runtime paths are normalized to `$HERMES_HOME/...` where possible.
- `environment_fact_signal` handoff includes `signal_quality` and `stable_identifiers`.

Observed remaining issue in dry-run artifact `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260518T072820Z.json`:

- `environment_fact_signal` still reaches the per-kind cap: `6 kept, 4 omitted`.
- Multiple candidates represent the same ambiguous skill-name resolution, for example `hermes-self-evolution-repo-review` resolving to the same two `$HERMES_HOME/skills/...` paths.
- These duplicates consume candidate slots before `memory_agent` sees more diverse material.

## Scope

### In scope

- Deterministically aggregate duplicate `environment_fact_signal` items in `hermes_self_improvement/evidence.py`.
- Preserve compact audit metadata:
  - `occurrence_count`
  - bounded `session_ids`
  - bounded `support_previews`
  - optionally `first_seen_index` / `last_seen_index` if useful for deterministic ordering
- Keep `memory_agent` handoff compact by passing `occurrence_count` and not raw events.
- Verify with focused tests, full tests, and dry-run artifact inspection.

### Non-goals

- Do not send raw `tool_failure_evidence` or full event windows to `memory_agent`.
- Do not add a new lane, approval queue, or planner step.
- Do not deduplicate unrelated durable value deltas just because they share one path token.
- Do not require semantic/LLM comparison for deduplication.
- Do not mutate memory in this slice; mutating `improve` dogfood is the next step after this plan lands.

## Dedup key

Use a stable key such as:

```python
(
    signal.get("signal_quality"),
    signal.get("tool_name"),
    signal.get("error_kind"),
    tuple(signal.get("stable_identifiers") or []),
    tuple(signal.get("value_tokens") or []),
)
```

Important details:

- Do **not** include `session_id`; otherwise the same repeated issue across sessions will not aggregate.
- Do **not** include `support_preview`; previews vary and would defeat aggregation.
- Preserve ordering by first occurrence so output remains deterministic.
- If `stable_identifiers` is empty, `value_tokens` must still be part of the key to avoid merging unrelated path deltas.
- If `signal_quality == "ambiguous_skill_resolution"`, prefer exact `stable_identifiers + value_tokens` matching.

## Acceptance criteria

- Two identical ambiguous skill resolution sequences produce one `environment_fact_signal` evidence item.
- The aggregated signal has `occurrence_count == 2`.
- The aggregated signal preserves bounded `session_ids` without including raw event payloads.
- Distinct ambiguous skill identifiers remain separate candidates.
- Runner handoff includes `occurrence_count` for `environment_fact_signal` candidates.
- Dry-run memory-agent preview shows fewer duplicate `ambiguous_skill_resolution` candidates and frees candidate cap for other evidence.
- Verification passes:
  - focused tests
  - `py_compile`
  - full `pytest tests -q`
  - `git diff --check`
  - `hermes self-improvement improve --dry-run --json` artifact inspection

---

## Task 1: Add RED tests for duplicate ambiguous skill resolution aggregation

**Objective:** Capture the current bug where identical ambiguous skill-name resolution signals appear as separate evidence items.

**Files:**

- Modify: `tests/test_evidence_pack.py`
- Later implementation: `hermes_self_improvement/evidence.py`

**Step 1: Add a focused test**

Add near existing environment-signal tests:

```python
def test_environment_fact_signal_aggregates_duplicate_ambiguous_skill_resolution(monkeypatch):
    monkeypatch.setenv("HERMES_HOME", "/opt/hermes-data")
    since = datetime(2026, 4, 30, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 4, 30, 1, 0, tzinfo=timezone.utc)

    def ambiguous_pair(session_id: str):
        return [
            {
                "ts": since.isoformat(),
                "event": "post_tool_call",
                "session_id": session_id,
                "tool_name": "skill_view",
                "status": "error",
                "error_kind": "unknown_error",
                "args_preview": '{"name":"hermes-self-evolution-repo-review"}',
                "result_preview": "Ambiguous skill name 'hermes-self-evolution-repo-review': /opt/hermes-data/skills/hermes-custom/hermes-self-evolution-repo-review/SKILL.md and /opt/hermes-data/skills/hermes-custom/hermes-development-maintenance/references/hermes-self-evolution-repo-review.md",
            },
            {
                "ts": since.isoformat(),
                "event": "post_tool_call",
                "session_id": session_id,
                "tool_name": "skill_view",
                "status": "success",
                "args_preview": '{"name":"hermes-custom/hermes-self-evolution-repo-review"}',
                "result_preview": "loaded /opt/hermes-data/skills/hermes-custom/hermes-self-evolution-repo-review/SKILL.md",
            },
        ]

    pack = build_evidence_pack([*ambiguous_pair("s1"), *ambiguous_pair("s2")], since, until)
    signals = [item for item in pack["evidence"] if item["kind"] == "environment_fact_signal"]

    assert len(signals) == 1
    signal = signals[0]["signal"]
    assert signal["signal_quality"] == "ambiguous_skill_resolution"
    assert signal["occurrence_count"] == 2
    assert signal["session_ids"] == ["s1", "s2"]
    assert signal["stable_identifiers"] == ["hermes-self-evolution-repo-review"]
```

**Step 2: Verify RED**

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_evidence_pack.py::test_environment_fact_signal_aggregates_duplicate_ambiguous_skill_resolution -q
```

Expected before implementation: FAIL because two signals are emitted, or `occurrence_count` is absent.

---

## Task 2: Add RED test that distinct ambiguous identifiers stay separate

**Objective:** Prevent over-aggressive aggregation.

**Files:**

- Modify: `tests/test_evidence_pack.py`
- Later implementation: `hermes_self_improvement/evidence.py`

**Step 1: Add test**

Use two ambiguous pairs with different quoted skill identifiers and different `$HERMES_HOME/skills/...` paths.

Expected assertions:

```python
signals = [item for item in pack["evidence"] if item["kind"] == "environment_fact_signal"]
assert len(signals) == 2
assert {tuple(item["signal"].get("stable_identifiers") or []) for item in signals} == {
    ("hermes-self-evolution-repo-review",),
    ("hermes-standalone-plugin-development",),
}
```

**Step 2: Verify RED/GREEN status**

Run the new test with Task 1. If it passes before implementation, keep it as a guard; Task 1 is the RED test.

---

## Task 3: Implement deterministic environment-signal aggregation

**Objective:** Aggregate duplicate compact signals without broad semantic merging.

**Files:**

- Modify: `hermes_self_improvement/evidence.py`

**Implementation shape:**

Add helper near `collect_environment_fact_signals()`:

```python
def _environment_signal_dedup_key(signal: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(signal.get("signal_quality") or ""),
        str(signal.get("tool_name") or ""),
        str(signal.get("error_kind") or ""),
        tuple(str(value) for value in (signal.get("stable_identifiers") if isinstance(signal.get("stable_identifiers"), list) else [])),
        tuple(str(value) for value in (signal.get("value_tokens") if isinstance(signal.get("value_tokens"), list) else [])),
    )
```

Add merge helper:

```python
def _merge_environment_signal(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    signal = existing["signal"]
    incoming_signal = incoming["signal"]
    signal["occurrence_count"] = int(signal.get("occurrence_count") or 1) + int(incoming_signal.get("occurrence_count") or 1)
    session_ids = list(signal.get("session_ids") or [])
    incoming_session = str(incoming_signal.get("session_id") or "")
    if incoming_session and incoming_session not in session_ids and len(session_ids) < 6:
        session_ids.append(incoming_session)
    signal["session_ids"] = session_ids
    previews = list(signal.get("support_previews") or [])
    incoming_preview = str(incoming_signal.get("support_preview") or "")
    if incoming_preview and incoming_preview not in previews and len(previews) < 3:
        previews.append(incoming_preview)
    if previews:
        signal["support_previews"] = previews
```

Then change `collect_environment_fact_signals()`:

- Build incoming item as today.
- Compute key from `stable`.
- If key already exists, merge into first item and continue.
- Only append new items for new keys.
- Keep `limit` applied to unique aggregated signals, not raw occurrences.

Implementation can be simpler than the sketch if names differ, but preserve the fields and behavior.

---

## Task 4: Include occurrence count in memory-agent handoff

**Objective:** Let `memory_agent` see that a signal is recurring without receiving raw events.

**Files:**

- Modify: `hermes_self_improvement/runner_steps.py`
- Test: `tests/test_memory_agent_dispatch.py`

**Step 1: Add/extend test**

Extend `_environment_signal_candidate()` fixture with:

```python
"occurrence_count": 3,
"session_ids": ["s1", "s2", "s3"],
```

Add assertions in `test_run_memory_improvement_step_previews_environment_fact_signals_for_memory_agent`:

```python
assert handed["occurrence_count"] == 3
assert handed["session_ids"] == ["s1", "s2", "s3"]
```

**Step 2: Implement compact handoff**

In `_environment_fact_agent_candidate_from_evidence()`, include:

```python
"occurrence_count": int(signal.get("occurrence_count") or 1),
"session_ids": [
    _redact_text(str(value), max_chars=80)
    for value in (signal.get("session_ids") if isinstance(signal.get("session_ids"), list) else [])[:6]
    if str(value).strip()
],
```

Do not add raw support previews unless a later dry-run proves `memory_agent` needs them; they remain artifact-only for audit.

---

## Task 5: Verify and dogfood dry-run artifact

**Objective:** Prove aggregation reduces duplicate cap pressure without hiding distinct signals.

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_evidence_pack.py tests/test_memory_agent_dispatch.py -q
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
git diff --check
hermes self-improvement improve --dry-run --json > /tmp/self-improvement-env-signal-dedup.json
python3 - <<'PY'
import json
from pathlib import Path
payload=json.loads(Path('/tmp/self-improvement-env-signal-dedup.json').read_text())
run=Path(payload['artifact_path'])
data=json.loads(run.read_text())
ma=data.get('step_decisions',{}).get('memory',{}).get('memory_agent',{})
print('artifact', run)
print('candidate_counts_by_kind', ma.get('candidate_counts_by_kind'))
print('omitted_candidate_counts_by_kind', ma.get('omitted_candidate_counts_by_kind'))
for cand in ma.get('candidates',[]):
    if cand.get('candidate_kind') == 'environment_fact_signal':
        print(json.dumps({
            'signal_quality': cand.get('signal_quality'),
            'stable_identifiers': cand.get('stable_identifiers'),
            'occurrence_count': cand.get('occurrence_count'),
            'value_tokens': cand.get('value_tokens'),
        }, ensure_ascii=False))
PY
```

Expected:

- Duplicate `ambiguous_skill_resolution` candidates collapse into one candidate with `occurrence_count > 1`.
- `omitted_candidate_counts_by_kind.environment_fact_signal` should decrease when duplicates were previously consuming the cap.
- Distinct identifiers still appear separately.
- No raw event payloads appear in memory-agent candidates.

---

## Task 6: Update plan index and commit

**Objective:** Keep plan state clear before moving to mutating dogfood.

Files:

- Modify: `.hermes/plans/README.md`
- Modify: `.hermes/plans/2026-05-18-environment-signal-dedup.md`

After implementation and verification, update this plan's `Current state` with final artifact path and counts, then commit:

```bash
git add .hermes/plans/2026-05-18-environment-signal-dedup.md .hermes/plans/README.md hermes_self_improvement/evidence.py hermes_self_improvement/runner_steps.py tests/test_evidence_pack.py tests/test_memory_agent_dispatch.py
git commit -m "feat: deduplicate environment memory signals"
git push
```

## Follow-up after this plan

After this plan lands, run a mutating dogfood pass:

```bash
hermes self-improvement improve
```

Then inspect the run artifact to answer the original product question:

- Did memory-agent execute any add/replace/remove?
- If still 0 changes, are skips due to duplicate, diagnostic-only, provider capacity, unsupported operation, or placement mismatch?
- If all candidates are skipped for good reasons, the next plan should target memory-agent decision/report clarity rather than candidate ingress.
