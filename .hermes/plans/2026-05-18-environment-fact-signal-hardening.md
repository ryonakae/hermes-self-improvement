# Environment Fact Signal Hardening Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Reduce noisy `environment_fact_signal` candidates while preserving durable environment-memory signals such as repeated ambiguous skill-name resolution.

**Architecture:** Keep the existing evidence -> compact signal -> memory_agent handoff flow. Add a small structural token classifier and signal-quality gate in `evidence.py`, then keep runner-side handoff simple and bounded. Do not narrow candidate ingress so much that useful weak/medium signals disappear; filter generic tokens and diagnostic-only transitions before the memory-agent prompt.

**Tech Stack:** Python, pytest, existing `hermes_self_improvement.evidence`, `runner_steps`, and dry-run artifact verification.

---

## Current state

After gateway reload, the new memory handoff code is active:

- `MEMORY_AGENT_DISPATCH_KINDS`: `memory_gap_candidate`, `memory_inventory_candidate`, `memory_placement_candidate`, `environment_fact_signal`.
- Latest dry-run artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260518T062506Z.json`.
- Evidence counts in that run:
  - `environment_fact_signal`: 10
  - `memory_inventory_candidate`: 3
  - `memory_placement_candidate`: 25
  - `memory_gap_candidate`: 4
- Memory-agent preview candidates:
  - total: 17
  - `environment_fact_signal`: 6 kept, 4 omitted by cap
  - `memory_inventory_candidate`: 3
  - `memory_placement_candidate`: 4 kept, 18 omitted by cap
  - `memory_gap_candidate`: 4

The ingress widening worked. The remaining problem is signal quality: generic tokens such as `HEAD`, `PATH`, `/main`, `/dev/null`, and fragment-like path artifacts are entering `value_tokens`. Executor safety currently skips many as `not_memory_diagnostic_only`, but they still consume candidate budget and prompt attention.

## Non-goals

- Do not send raw `tool_failure_evidence` to `memory_agent`.
- Do not remove `environment_fact_signal` entirely.
- Do not introduce a new lane, approval queue, or separate user-facing command.
- Do not make Japanese/English lexical correction markers the primary detector.
- Do not mutate memory in this plan; this is a candidate-quality hardening slice plus dry-run verification.

## Acceptance criteria

- Generic value tokens such as `HEAD`, `PATH`, `/main`, `/dev/null`, `/HEAD`, `/main...upstream/main`, and newline/escape-contaminated fragments are removed before signal creation.
- If filtering leaves fewer than two meaningful value tokens, no `environment_fact_signal` is emitted for that failure/retry pair.
- Repeated ambiguous skill-name resolution remains eligible as a durable environment signal, with useful tokens such as:
  - `~/.hermes/skills/hermes-custom/hermes-self-evolution-repo-review/SKILL.md`
  - `~/.hermes/skills/hermes-custom/hermes-development-maintenance/references/hermes-self-evolution-repo-review.md`
  - the ambiguous skill name, if available as a stable identifier.
- `environment_fact_signal` carries a compact quality reason or signal subtype, e.g. `signal_quality: durable_value_delta` / `ambiguous_skill_resolution`.
- Memory-agent preview shows fewer diagnostic-only environment signals while preserving durable candidates.
- Full verification passes: `py_compile`, focused tests, full `pytest tests -q`, `git diff --check`.

---

## Task 1: Add regression tests for generic-token filtering

**Objective:** Prove that generic git/shell/path fragments are not emitted as memory value tokens.

**Files:**

- Modify: `tests/test_evidence_pack.py`
- Implementation later: `hermes_self_improvement/evidence.py`

**Step 1: Write failing test**

Add a test near the existing environment-signal tests:

```python
def test_environment_fact_signal_filters_generic_value_tokens():
    since = datetime(2026, 4, 30, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 4, 30, 1, 0, tzinfo=timezone.utc)
    events = [
        {
            "ts": since.isoformat(),
            "event": "post_tool_call",
            "session_id": "s1",
            "tool_name": "terminal",
            "status": "error",
            "error_kind": "terminal_nonzero_exit",
            "args_preview": '{"command":"git fetch origin main","workdir":"/Users/alice/.hermes/hermes-agent"}',
            "result_preview": "HEAD PATH /main /main...upstream/main /dev/null /HEAD FETCH_HEAD",
        },
        {
            "ts": since.isoformat(),
            "event": "post_tool_call",
            "session_id": "s1",
            "tool_name": "terminal",
            "status": "ok",
            "args_preview": '{"command":"git status","workdir":"/Users/alice/.hermes/hermes-agent"}',
            "result_preview": "On branch main HEAD PATH /dev/null",
        },
    ]

    pack = build_evidence_pack(events, since, until)

    assert not any(item["kind"] == "environment_fact_signal" for item in pack["evidence"])
```

**Step 2: Run test to verify RED**

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_evidence_pack.py::test_environment_fact_signal_filters_generic_value_tokens -q
```

Expected before implementation: FAIL because a signal is emitted.

---

## Task 2: Add regression test that ambiguous skill resolution is preserved

**Objective:** Ensure the filter does not throw away the useful repeated ambiguous skill-name case.

**Files:**

- Modify: `tests/test_evidence_pack.py`
- Implementation later: `hermes_self_improvement/evidence.py`

**Step 1: Write failing or characterization test**

```python
def test_environment_fact_signal_preserves_ambiguous_skill_resolution():
    since = datetime(2026, 4, 30, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 4, 30, 1, 0, tzinfo=timezone.utc)
    events = [
        {
            "ts": since.isoformat(),
            "event": "post_tool_call",
            "session_id": "s1",
            "tool_name": "skill_view",
            "status": "error",
            "error_kind": "unknown_error",
            "args_preview": '{"name":"hermes-self-evolution-repo-review"}',
            "result_preview": "Ambiguous skill name 'hermes-self-evolution-repo-review': /Users/alice/.hermes/skills/hermes-custom/hermes-self-evolution-repo-review/SKILL.md and /Users/alice/.hermes/skills/hermes-custom/hermes-development-maintenance/references/hermes-self-evolution-repo-review.md",
        },
        {
            "ts": since.isoformat(),
            "event": "post_tool_call",
            "session_id": "s1",
            "tool_name": "skill_view",
            "status": "success",
            "args_preview": '{"name":"hermes-custom/hermes-self-evolution-repo-review"}',
            "result_preview": "loaded /Users/alice/.hermes/skills/hermes-custom/hermes-self-evolution-repo-review/SKILL.md",
        },
    ]

    pack = build_evidence_pack(events, since, until)
    signal = next(item for item in pack["evidence"] if item["kind"] == "environment_fact_signal")

    assert signal["signal"]["signal_quality"] == "ambiguous_skill_resolution"
    # Guards against the current regex producing a bare "~" token plus a separate path fragment.
    assert "~" not in signal["signal"]["value_tokens"]
    assert "~/.hermes/skills/hermes-custom/hermes-self-evolution-repo-review/SKILL.md" in signal["signal"]["value_tokens"]
    assert "~/.hermes/skills/hermes-custom/hermes-development-maintenance/references/hermes-self-evolution-repo-review.md" in signal["signal"]["value_tokens"]
    assert "hermes-self-evolution-repo-review" in signal["signal"].get("stable_identifiers", [])
```

Adjust the exact assertion names only if there is a compelling reason to rename the field before implementation; the preferred field name is `signal_quality`.

**Step 2: Run focused test**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_evidence_pack.py::test_environment_fact_signal_preserves_ambiguous_skill_resolution -q
```

Expected: FAIL until `signal_quality` / stable identifier extraction exists.

---

## Task 3: Implement token quality filtering in `evidence.py`

**Objective:** Filter generic / fragment / diagnostic-only tokens before building `environment_fact_signal`.

**Files:**

- Modify: `hermes_self_improvement/evidence.py`

**Step 1: Add explicit generic token constants**

Near `_VALUE_TOKEN_PATTERN`, add small allow/deny helpers:

```python
_GENERIC_VALUE_TOKENS = {
    "~",  # artifact from the current regex alternative; never useful alone
    "HEAD",
    "FETCH_HEAD",
    "PATH",
    "PIPE",  # observed as a standalone env-like artifact in tool output; drop unless a future test proves it meaningful
    "USER",
    "HOME",
    "PWD",
    "OLDPWD",
    "SHELL",
    "/dev/null",
    "/main",
    "/HEAD",
}

_GENERIC_PATH_SUFFIXES = (
    "...upstream/main",
    "...origin/main",
)
```

**Step 2: Add classifier helpers**

```python
def _looks_generic_value_token(token: str) -> bool:
    text = str(token or "").strip()
    if not text:
        return True
    if text in _GENERIC_VALUE_TOKENS:
        return True
    if text.endswith("\\n") or "\\n" in text:
        return True
    if "…[truncated" in text or "...[truncated" in text:
        return True
    if any(text.endswith(suffix) for suffix in _GENERIC_PATH_SUFFIXES):
        return True
    if re.fullmatch(r"/[A-Za-z0-9_.-]{1,8}", text):
        return True
    return False
```

Keep this conservative, but document the trade-off: short container paths such as `/app`, `/src`, or `/build` may be meaningful in some environments. This plan intentionally drops them as weak fragments for now; if dogfood later shows a real durable `/app`-style environment fact, add a narrow allowlist with regression coverage instead of broadly allowing short root paths.

Do not drop full paths under `~/.hermes/...`, `.sock`, `.json`, `.yaml`, `.md`, or `.py`.

**Step 3: Use helper in extraction**

Update `_extract_value_tokens_from_text`:

```python
if not token or _looks_secret(token) or _looks_generic_value_token(token) or token in seen:
    continue
```

**Step 4: Re-run focused tests**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_evidence_pack.py::test_environment_fact_signal_filters_generic_value_tokens -q
```

Expected: PASS.

---

## Task 4: Add signal subtype / quality detection

**Objective:** Keep durable ambiguous skill-name cases while still dropping generic command-noise transitions.

**Files:**

- Modify: `hermes_self_improvement/evidence.py`
- Test: `tests/test_evidence_pack.py`

**Step 1: Add classifier**

```python
def _environment_signal_quality(failure: dict[str, Any], success: dict[str, Any], value_tokens: list[str]) -> str | None:
    tool_name = str(failure.get("tool_name") or "")
    failure_text = _event_text_for_value_tokens(failure)
    success_text = _event_text_for_value_tokens(success)
    combined = f"{failure_text}\n{success_text}".lower()

    if tool_name in {"skill_view", "skill_manage"} and "ambiguous skill name" in combined:
        return "ambiguous_skill_resolution"

    durable_tokens = [token for token in value_tokens if _is_durable_value_token(token)]
    if len(durable_tokens) >= 2:
        return "durable_value_delta"

    return None
```

**Step 2: Add durable token helper**

```python
def _is_durable_value_token(token: str) -> bool:
    text = str(token or "")
    if _looks_generic_value_token(text):
        return False
    if text.startswith("~/.hermes/"):
        return True
    if text.startswith("~/") and text.count("/") >= 2:
        return True
    if text.endswith((".sock", ".json", ".yaml", ".yml", ".md", ".py")):
        return True
    if "/" in text and len(text) >= 12:
        return True
    return False
```

This intentionally keeps real paths and config/socket/model-provider file references, but drops short fragments. `~/` is not automatically durable; require either `~/.hermes/...`, a useful file/config suffix, or enough path depth to avoid preserving `~/tmp`-style noise.

**Step 3: Wire quality into `collect_environment_fact_signals`**

After `unique_tokens` is built:

```python
quality = _environment_signal_quality(ev, later, unique_tokens)
if quality is None:
    continue
```

Add to `stable`:

```python
"signal_quality": quality,
```

**Step 4: Preserve stable identifiers for ambiguous skill names**

Add helper:

```python
def _extract_stable_identifiers(text: str) -> list[str]:
    identifiers = []
    for match in re.finditer(r"'([a-z0-9][a-z0-9_-]{2,})'", text, re.IGNORECASE):
        value = match.group(1)
        if value not in identifiers:
            identifiers.append(value)
    return identifiers[:4]
```

When `quality == "ambiguous_skill_resolution"`, include:

```python
"stable_identifiers": _extract_stable_identifiers(f"{failure_text}\n{success_text}"),
```

**Step 5: Re-run focused tests**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_evidence_pack.py::test_environment_fact_signal_preserves_ambiguous_skill_resolution -q
```

Expected: PASS.

---

## Task 5: Apply the same generic-token filtering to memory-extractor ranking

**Objective:** Keep `memory_extractor` structural window ranking from being promoted by the same generic tokens filtered out of `environment_fact_signal`.

**Files:**

- Modify: `hermes_self_improvement/memory_extractor.py`
- Test: `tests/test_memory_extractor.py`

**Step 1: Add regression test**

Add a test near `test_rank_conversation_windows_prefers_structural_failure_retry_over_lexical_hint`:

```python
def test_memory_extractor_structural_ranking_ignores_generic_value_tokens():
    events = [
        {
            "event": "post_tool_call",
            "session_id": "s1",
            "tool_name": "terminal",
            "status": "error",
            "result_preview": "HEAD PATH /main /dev/null",
        },
        {
            "event": "post_llm_call",
            "session_id": "s1",
            "user_message_preview": "普通の相談です",
        },
        {
            "event": "post_tool_call",
            "session_id": "s1",
            "tool_name": "terminal",
            "status": "success",
            "result_preview": "HEAD PATH /dev/null",
        },
    ]

    windows = build_memory_extractor_windows(events, limit=10)

    assert windows[0]["rank_reason"] == "sampled_context"
    assert windows[0]["rank_signals"]["has_value_token_delta"] is False
```

**Step 2: Implement without creating a large abstraction layer**

Either:

- import narrow helpers from `evidence.py` if doing so does not create an import cycle, or
- mirror the small `_looks_generic_value_token` behavior in `memory_extractor.py` with a comment pointing to `evidence.py`.

Prefer a shared helper only if it stays simple. Do not move broad evidence code into a new module just for this hardening slice.

**Step 3: Run focused test**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_memory_extractor.py::test_memory_extractor_structural_ranking_ignores_generic_value_tokens -q
```

Expected: PASS.

---

## Task 6: Keep runner handoff compact but include quality metadata

**Objective:** Give `memory_agent` enough signal context to decide durable-vs-diagnostic without expanding raw payloads.

**Files:**

- Modify: `hermes_self_improvement/runner_steps.py`
- Test: `tests/test_memory_agent_dispatch.py`

**Step 1: Add regression test**

Extend `_environment_signal_candidate()` fixture or add a new fixture with:

```python
"signal_quality": "ambiguous_skill_resolution",
"stable_identifiers": ["hermes-self-evolution-repo-review"],
```

Add assertion in `test_run_memory_improvement_step_previews_environment_fact_signals_for_memory_agent`:

```python
assert handed["signal_quality"] == "ambiguous_skill_resolution"
assert handed["stable_identifiers"] == ["hermes-self-evolution-repo-review"]
```

**Step 2: Update `_environment_fact_agent_candidate_from_evidence`**

Add compact fields:

```python
"signal_quality": str(signal.get("signal_quality") or ""),
"stable_identifiers": [
    _redact_text(str(value), max_chars=120)
    for value in (signal.get("stable_identifiers") if isinstance(signal.get("stable_identifiers"), list) else [])[:4]
    if str(value).strip()
],
```

Do not include full failure/success text.

**Step 3: Run focused dispatch test**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_memory_agent_dispatch.py::test_run_memory_improvement_step_previews_environment_fact_signals_for_memory_agent -q
```

Expected: PASS.

---

## Task 7: Dogfood the artifact counts after hardening

**Objective:** Verify that noise drops but durable candidates remain.

**Files:**

- No code files unless dogfood reveals a bug.
- Runtime artifacts under `~/.hermes/self-improvement/`.

**Step 1: Run focused tests**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_evidence_pack.py tests/test_memory_agent_dispatch.py -q
```

Expected: PASS.

**Step 2: Run full verification**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
git diff --check
```

Expected: full suite passes.

**Step 3: Run dry-run**

```bash
hermes self-improvement improve --dry-run --json > /tmp/self-improvement-env-signal-hardening.json
```

Extract the important fields:

```bash
python3 - <<'PY'
import json
from pathlib import Path
payload=json.loads(Path('/tmp/self-improvement-env-signal-hardening.json').read_text())
run=Path(payload['artifact_path'])
data=json.loads(run.read_text())
ev=data['evidence_pack']['summary']
ma=data['step_decisions']['memory']['memory_agent']
print('artifact', run)
print('evidence_by_kind', ev['evidence_by_kind'])
print('candidate_counts_by_kind', ma.get('candidate_counts_by_kind'))
print('omitted_candidate_counts_by_kind', ma.get('omitted_candidate_counts_by_kind'))
PY
```

Expected:

- `environment_fact_signal` count should usually be lower than the noisy baseline of 10 when running over the same event window. If new real events entered the 24h window, compare candidate samples instead of treating the raw count as a hard failure.
- `candidate_counts_by_kind.environment_fact_signal` should still be non-zero if ambiguous skill resolution or real durable path/env deltas exist.
- Generic tokens should not appear in memory-agent candidate `value_tokens`.

---

## Task 8: Update docs/status and commit

**Objective:** Keep the repo-tracked plan index accurate.

**Files:**

- Modify: `.hermes/plans/README.md`
- Optionally modify: `.hermes/plans/2026-05-18-memory-agent-signal-handoff.md` with a pointer to this hardening plan.

**Step 1: Update plan index**

Set current active hardening plan to this file:

```markdown
- `2026-05-18-environment-fact-signal-hardening.md`
  - **Status:** planned / awaiting implementation.
  - Filters noisy generic value tokens from `environment_fact_signal` while preserving durable ambiguous skill-name resolution and real path/env deltas.
```

Move `2026-05-18-memory-agent-signal-handoff.md` to implemented status with its commits.

**Step 2: Commit plan**

```bash
git add .hermes/plans/README.md .hermes/plans/2026-05-18-environment-fact-signal-hardening.md .hermes/plans/2026-05-18-memory-agent-signal-handoff.md
git commit -m "docs: plan environment fact signal hardening"
git push
```

---

## Implementation notes

### Keep filtering conservative

The goal is not perfect semantic judgment in regex. Program code should only remove obvious noise and attach useful compact metadata. The LLM memory agent still decides whether the remaining signal is memory-worthy.

### Examples to drop

- `HEAD`
- `FETCH_HEAD`
- `PATH`
- `PIPE`
- `/main`
- `/HEAD`
- `/dev/null`
- `/main...upstream/main`
- tokens containing literal `\n`
- tokens containing truncated markers such as `…[truncated]`

### Examples to preserve

- `~/.hermes/skills/hermes-custom/hermes-self-evolution-repo-review/SKILL.md`
- `~/.hermes/skills/hermes-custom/hermes-development-maintenance/references/hermes-self-evolution-repo-review.md`
- `~/.docker/run/docker.sock`
- `~/.hermes/google_token.json`
- `~/.hermes/plugins/hermes-self-improvement`
- stable skill identifiers such as `hermes-self-evolution-repo-review`

### If dry-run still shows many diagnostic-only signals

Do not add broad hard stops immediately. First inspect top candidate `value_tokens` and add narrow deny rules only for clearly generic tokens. If a token is ambiguous but stable, preserve it and let memory_agent skip it.
