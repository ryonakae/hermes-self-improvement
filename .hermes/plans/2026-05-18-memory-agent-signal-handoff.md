# Memory Agent Signal Handoff Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Improve `hermes-self-improvement` memory mutation recall without dumping raw events into the LLM: pass compact inventory and structurally detected durable-fact signals to `memory_agent`, and normalize successful memory-agent outcome variants.

**Architecture:** Keep `improve` as the single flow. Program code creates compact, language-agnostic evidence signals from structure (event sequence, typed tool failures, value/path tokens, existing-memory relation, retry outcome), not from Japanese/English keyword lists as the primary gate. `memory_agent` receives bounded candidates and decides add/replace/remove/skip through existing memory tools; executor hard stops remain fail-closed.

**Tech Stack:** Python, pytest, existing `hermes_self_improvement` modules (`evidence.py`, `memory_extractor.py`, `runner_steps.py`, `memory_agent.py`, `memory_agent_backend.py`, `cli.py`).

---

## Current problem

Observed 2026-05-18 behavior:

- `memory_gap_candidate` reaches `memory_agent`.
- `memory_inventory_candidate` is generated but usually becomes `defer / memory_inventory_needs_planner` because `MEMORY_AGENT_DISPATCH_KINDS = {"memory_gap_candidate"}`.
- Tool failures are grouped for skill/workflow maintenance, but there is no compact bridge from `tool_failure_evidence` to durable memory fact candidates such as environment paths, sockets, repo locations, model/provider routing, or repeated correction facts.
- Memory-agent success can be rejected when the LLM reports a successful but non-canonical outcome like `applied_after_capacity_recovery`.
- `memory_extractor._rank_reason()` uses language-specific markers (`違う`, `前にも`, `wrong`, etc.). That may help Ryo's environment, but it is not acceptable as a primary mechanism for a generally distributed plugin.

## Design principles

1. **Do not broaden raw input blindly.** Keep raw events and full tool output out of the memory-agent prompt. Artifacts may contain detail; LLM handoff stays compact.
2. **Use language-agnostic structure first.** Prefer typed event fields and sequence patterns: failure followed by user/assistant corrective turn, changed path/env token, retry success, repeated same error cluster, candidate contradicts existing memory specifics.
3. **Use lexical markers only as weak ranking hints.** If retained, markers must be configurable/secondary and never the sole gate for candidate generation.
4. **Let LLM decide fuzzy placement.** Once compact material is selected, `memory_agent` decides memory vs user vs skill-route vs skip. GEPA can improve that decision prompt over time.
5. **Keep executor safety hard.** Secrets, raw tool output, workflow-shaped text, unsupported provider operations, ambiguous replace/delete, topic mismatch, and direct-store writes remain blocked.
6. **No new lane or approval queue.** Extend existing evidence -> memory step -> episode/report flow.

## Acceptance criteria

- `memory_inventory_candidate` with compact entries is eligible for memory-agent preview/execution.
- Clear `stale_fact_pair` inventory can become an operation hint or memory-agent candidate without defaulting to `memory_inventory_needs_planner`.
- Tool-failure-derived durable signals are generated only from structural evidence and compacted before LLM handoff.
- Language-specific correction words are not the primary filter for memory candidate creation.
- Memory-agent successful unknown outcome variants with actual changes normalize to `applied` while preserving `reported_outcome`.
- `improve --dry-run --json` shows memory-agent preview candidates beyond plain `memory_gap_candidate` when such evidence exists, without large prompt bloat.
- Full test suite and py_compile pass.

---

## Task 1: Add regression tests for successful memory-agent outcome normalization

**Objective:** Capture the current bug where successful outcome variants such as `applied_after_capacity_recovery` are rejected.

**Files:**
- Modify: `tests/test_memory_agent_backend.py` or create focused test file if no suitable file exists.
- Modify: `tests/test_memory_agent.py` if the non-backend parser has parallel normalization.
- Implementation later: `hermes_self_improvement/memory_agent_backend.py`, `hermes_self_improvement/memory_agent.py`.

**Step 1: Find existing tests**

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests -q --collect-only | grep -E 'memory_agent|memory.*backend' || true
```

Expected: identify the current test file names.

**Step 2: Write failing tests**

Add tests for both normalization paths if both validators exist:

```python
def test_memory_agent_normalizes_successful_reported_outcome_with_changes():
    result = normalize_memory_agent_result({
        "success": True,
        "outcome": "applied_after_capacity_recovery",
        "used_tools": ["memory"],
        "changed_memories": ["cand_123"],
        "removed_memories": [],
        "verification_notes": ["memory add succeeded after capacity recovery"],
        "rollback_hints": [],
    })

    assert result["success"] is True
    assert result["outcome"] == "applied"
    assert result["reported_outcome"] == "applied_after_capacity_recovery"
    assert result["changed_memories"] == ["cand_123"]
```

If the actual helper is private, use the existing public test style in the file rather than exporting a new API.

**Step 3: Run focused test and verify RED**

Run:

```bash
$PY -m pytest tests/test_memory_agent_backend.py tests/test_memory_agent.py -q
```

Expected: FAIL with `memory_agent_result_invalid_outcome` or equivalent.

---

## Task 2: Normalize successful non-canonical memory-agent outcomes

**Objective:** Preserve strict failure semantics while accepting successful outcome strings when tool trace lists actual changes.

**Files:**
- Modify: `hermes_self_improvement/memory_agent_backend.py`
- Modify: `hermes_self_improvement/memory_agent.py`
- Test: files from Task 1

**Implementation shape:**

Add a small helper in both modules or a shared helper if a suitable shared module already exists:

```python
def _normalize_successful_outcome(result: dict[str, Any]) -> dict[str, Any] | None:
    outcome = str(result.get("outcome") or "applied")
    changed = bool(result.get("changed_memories") or result.get("removed_memories"))
    if outcome == "changed":
        result["outcome"] = "applied"
        return None
    if outcome == "applied" or outcome in NON_MUTATING_AGENT_OUTCOMES:
        result["outcome"] = outcome
        return None
    if changed:
        result["reported_outcome"] = outcome
        result["outcome"] = "applied"
        return None
    return {"success": False, "error": "memory_agent_result_invalid_outcome", "outcome": outcome}
```

Do **not** accept arbitrary outcome strings when there are no changed/removed memories; those remain invalid unless they are existing non-mutating outcomes.

**Verification:**

```bash
$PY -m pytest tests/test_memory_agent_backend.py tests/test_memory_agent.py -q
```

Expected: PASS.

---

## Task 3: Add compact memory-agent candidate schema for inventory evidence

**Objective:** Convert `memory_inventory_candidate` into bounded memory-agent handoff items without raw memory dump.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Test: `tests/test_runner_steps.py` or focused memory runner tests.

**Step 1: Write failing tests**

Add tests around `_memory_agent_candidate_from_evidence()` or the public `run_memory_improvement_step()` behavior:

```python
def test_memory_inventory_candidate_is_compacted_for_memory_agent():
    item = {
        "id": "memory_inv_1",
        "kind": "memory_inventory_candidate",
        "inventory": {
            "group_kind": "stale_fact_pair",
            "entries": [
                {"target": "memory", "old_text": "Old Hermes path is /opt/data", "hash": "old"},
                {"target": "memory", "old_text": "Hermes runtime root is ~/.hermes", "hash": "new"},
            ],
            "hints": ["planner should consider replace/remove for stale fact pairs"],
        },
        "risk": "medium",
    }

    candidate = _memory_agent_candidate_from_evidence(item)

    assert candidate["candidate_id"] == "memory_inv_1"
    assert candidate["candidate_kind"] == "memory_inventory_candidate"
    assert candidate["inventory_kind"] == "stale_fact_pair"
    assert len(candidate["entries"]) == 2
    assert all(len(entry["old_text"]) <= 260 for entry in candidate["entries"])
```

**Step 2: Implement compact conversion**

- Keep `MEMORY_AGENT_DISPATCH_KINDS` expanded to include `memory_inventory_candidate`.
- For inventory items, return a compact candidate:

```python
{
    "candidate_id": item["id"],
    "candidate_kind": "memory_inventory_candidate",
    "inventory_kind": inventory["group_kind"],
    "entries": [{"target", "old_text", "hash", "summary"}][:4],
    "hints": inventory["hints"][:4],
    "target_resolution_hint": item.get("target_resolution_hint"),
    "risk": item.get("risk"),
}
```

- Do not include full context windows or raw event previews here.
- If no entries survive redaction, return `None`.

**Step 3: Verify**

```bash
$PY -m pytest tests/test_runner_steps.py -q
```

Expected: PASS.

---

## Task 4: Route only suspicious placement candidates to memory-agent

**Objective:** Avoid sending all 25+ placement-review entries to the LLM while still allowing ambiguous USER/MEMORY/Skill placement to be decided.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Test: `tests/test_runner_steps.py`

**Suspicious placement criteria:**

Implement a small helper such as `_memory_placement_needs_agent(item)` using structural/content-shape signals, not language-specific words:

Send to memory-agent only when at least one is true:

- candidate is also in an inventory duplicate/stale group (if evidence has a linkage field now; otherwise skip this criterion in first slice)
- text contains strong procedural shape: command snippets, numbered steps, code fences, shell prompts, `run`, `execute`, `pytest`, `curl`, `hermes`, tool names with imperative syntax
- text contains path/env/model/provider/socket tokens and current store appears questionable only when paired with a placement affordance/hint
- inventory allowed recommendations include move/skill conversion and the candidate carries an explicit hint/reason from upstream

Default placement candidates with only `current_store` and no suspicious signal should continue to become `skip / keep_current_memory|user` without LLM handoff.

**Test examples:**

```python
def test_plain_memory_placement_candidate_is_not_sent_to_memory_agent():
    item = {"id": "place_1", "kind": "memory_placement_candidate", "inventory": {"current_store": "memory", "old_text": "User likes concise replies"}}
    assert _memory_agent_candidate_from_evidence(item) is None


def test_workflow_shaped_placement_candidate_is_compacted_for_memory_agent():
    item = {"id": "place_2", "kind": "memory_placement_candidate", "inventory": {"current_store": "memory", "old_text": "Run `pytest tests -q` after editing."}}
    candidate = _memory_agent_candidate_from_evidence(item)
    assert candidate["candidate_kind"] == "memory_placement_candidate"
    assert candidate["suggested_route"] == "placement_review"
```

**Verification:**

```bash
$PY -m pytest tests/test_runner_steps.py -q
```

Expected: PASS.

---

## Task 5: Replace language-specific correction ranking with structural ranking metadata

**Objective:** Keep language-specific words as optional weak hints, but make memory-extractor window selection useful for multilingual users.

**Files:**
- Modify: `hermes_self_improvement/memory_extractor.py`
- Test: `tests/test_memory_extractor.py` or create it.

**Structural rank signals to implement:**

Create `_rank_window_signals(events, index)` returning a dict:

```python
{
    "has_user_turn": bool,
    "has_prior_failure": bool,
    "has_retry_after_failure": bool,
    "has_value_token_delta": bool,
    "has_existing_memory_overlap": bool,  # if available later; can be false in this task
    "lexical_correction_hint": bool,
    "lexical_preference_hint": bool,
}
```

Use event fields and previews:

- prior nearby `post_tool_call` status in error/warning/failed/failure => `has_prior_failure`
- later nearby successful `post_tool_call` for same tool/session => `has_retry_after_failure`
- path/env/value tokens differ across nearby tool args/results/user/assistant previews => `has_value_token_delta`
- lexical hints remain only a tie-breaker

Window ranking priority should become:

1. structural correction-like: prior failure + value token delta or retry
2. explicit memory/correction event kind if present
3. lexical hint
4. sampled context

**Do not remove all lexical markers in this task.** Make them secondary and document that they are weak hints only.

**Tests:**

- A Spanish/French/Japanese-free user message with wrong path corrected by retry ranks above sampled context because of structural signals.
- A pure keyword-only message can still get a lexical hint but does not outrank structural failure/retry.

**Verification:**

```bash
$PY -m pytest tests/test_memory_extractor.py -q
```

Expected: PASS.

---

## Task 6: Generate compact environment/correction fact signals from tool-failure sequences

**Objective:** Bridge tool failures to memory-worthy material without sending raw failures to memory-agent.

**Files:**
- Modify: `hermes_self_improvement/evidence.py`
- Possibly modify: `hermes_self_improvement/cli.py` only if evidence pack wiring needs a new summary count.
- Test: `tests/test_evidence.py`

**New evidence kind:**

Use one kind, not two, to keep the surface simple:

```text
environment_fact_signal
```

This can represent both environment facts and correction-derived memory facts.

**Candidate shape:**

```json
{
  "id": "env_fact_<hash>",
  "kind": "environment_fact_signal",
  "source": "structural_evidence",
  "likely_targets": [{"target":"memory","weight":0.8},{"target":"skill","weight":0.2}],
  "signal": {
    "reason": "failure_retry_value_delta|repeated_failure_with_stable_value|correction_after_failure",
    "tool_name": "terminal",
    "error_kind": "not_found",
    "session_id": "...",
    "failure_count": 2,
    "success_after_correction": true,
    "value_tokens": ["/Users/...", "~/.docker/run/docker.sock"],
    "candidate_fact_hint": "...",
    "support_preview": "..."
  },
  "risk": "medium"
}
```

**Structural generation rules:**

Generate only when at least two structural supports exist:

- failure or warning event present
- retry success in same session/tool, or same error appears repeatedly
- path/env/socket/model/provider token appears in failure and differs from later success/correction
- user/assistant correction/final message mentions a stable value token

Do not require natural-language keywords.

**Token extraction helper:**

Add a small helper for stable value tokens:

- paths: `/...`, `~/...`, repo-looking paths
- env names: `DOCKER_HOST`, `HERMES_HOME`, uppercase snake case
- sockets/files: `.sock`, `.json`, `.yaml`, `.md`, `.py`
- provider/model-ish tokens only when adjacent to provider/model fields or API errors

Redact with existing `_redact_text`; cap tokens to maybe 8.

**Tests:**

- wrong repo path failure followed by success in different repo path produces one `environment_fact_signal`.
- repeated timeout with no stable value token does **not** produce memory signal; it remains skill/workflow material.
- secret-like token is not emitted.
- multilingual user text with no known correction keyword still produces signal if structure supports it.

**Verification:**

```bash
$PY -m pytest tests/test_evidence.py -q
```

Expected: PASS.

---

## Task 7: Pass environment fact signals to memory-agent as compact candidates

**Objective:** Let `memory_agent` decide whether environment/correction signals become memory add/replace, skill route, or skip.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Test: `tests/test_runner_steps.py`

**Implementation shape:**

Expand dispatch kinds:

```python
MEMORY_AGENT_DISPATCH_KINDS = {
    "memory_gap_candidate",
    "memory_inventory_candidate",
    "memory_placement_candidate",
    "environment_fact_signal",
}
```

For `environment_fact_signal`, produce:

```python
{
    "candidate_id": item["id"],
    "candidate_kind": "environment_fact_signal",
    "candidate_fact_hint": signal.get("candidate_fact_hint", ""),
    "signal_reason": signal.get("reason", ""),
    "value_tokens": signal.get("value_tokens", [])[:8],
    "support": {
        "tool_name": signal.get("tool_name"),
        "error_kind": signal.get("error_kind"),
        "failure_count": signal.get("failure_count"),
        "success_after_correction": signal.get("success_after_correction"),
        "support_preview": signal.get("support_preview"),
    },
    "target": "memory",
    "confidence": "medium",
}
```

**Prompt contract:**

Update `memory_agent.py` / `memory_agent_backend.py` prompt text only if needed to tell the LLM:

- environment signals are hints, not commands
- add only durable facts/preferences/environment details
- convert procedural guidance to skill route
- skip if transient or insufficiently supported

**Verification:**

```bash
$PY -m pytest tests/test_runner_steps.py tests/test_memory_agent_backend.py -q
```

Expected: PASS.

---

## Task 8: Add compact prompt-size accounting for memory-agent handoff

**Objective:** Prevent recall improvements from accidentally bloating LLM prompts.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Test: `tests/test_runner_steps.py`

**Implementation shape:**

In `_dispatch_memory_agent()`:

- cap candidates per kind, e.g.:
  - memory_gap: 6
  - inventory: 6
  - placement: 4
  - environment_fact_signal: 6
- include `omitted_candidate_counts_by_kind`
- include `candidate_counts_by_kind`
- preserve all evidence in artifact, but not prompt

Example return/preview block:

```json
{
  "status": "preview",
  "candidate_count": 8,
  "candidate_counts_by_kind": {"memory_gap_candidate":2,"memory_inventory_candidate":3,"environment_fact_signal":3},
  "omitted_candidate_counts_by_kind": {"memory_placement_candidate":21},
  "candidates": [...]
}
```

**Tests:**

- More than cap candidates are omitted deterministically.
- Omitted counts are reported.
- Preview does not include raw event windows.

**Verification:**

```bash
$PY -m pytest tests/test_runner_steps.py -q
```

Expected: PASS.

---

## Task 9: Report memory handoff source counts and no-op reasons

**Objective:** Make daily/debug reports explain why memory changes are zero despite candidates.

**Files:**
- Modify: report rendering module where current `Knowledge maintenance:` / `Actual results:` lines are generated. Locate with:
  ```bash
  grep -R "Knowledge maintenance" -n hermes_self_improvement tests
  ```
  Use `search_files` instead of grep when working through Hermes tools.
- Test: corresponding report tests.

**Report shape:**

Add compact line, not full payload:

```text
Memory handoff: candidates 8 (gap 2, inventory 3, env 3; placement omitted 21), changed 0, top no-op: keep_current_user 13, keep_current_memory 12, memory_inventory_needs_planner 3
```

After Tasks 3-8, `memory_inventory_needs_planner` should drop for candidates sent to memory-agent; if still present, report it explicitly.

**Verification:**

```bash
$PY -m pytest tests -q -k 'report or memory'
```

Expected: PASS.

---

## Task 10: Dogfood dry-run and full verification

**Objective:** Prove the new handoff improves recall without unsafe mutation.

**Files:**
- No source changes unless verification finds defects.

**Commands:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
hermes self-improvement status
hermes self-improvement improve --dry-run --json
 git diff --check
```

Expected:

- pytest passes.
- status ready.
- dry-run includes memory-agent preview candidates from at least inventory and/or environment signal when evidence exists.
- no raw tool output is present in memory-agent candidates.
- `action_summary` remains conservative; this plan is not trying to force actual changes when evidence is weak.

---

## Non-goals

- Do not add a new approval queue, lane, command, or user-facing surface.
- Do not run GEPA inside runtime hooks or `improve` mutation execution.
- Do not edit Hermes core.
- Do not mutate built-in memory files or provider stores directly.
- Do not make natural-language keyword lists the primary correction detector.
- Do not send raw tool outputs, complete event windows, or full memory stores to `memory_agent`.

## Subagent review amendments

The first review found several implementation hazards. Treat these amendments as part of the plan, not optional notes.

### Amendment A: Unify memory-agent outcome normalization

`memory_agent.py` and `memory_agent_backend.py` both validate outcome strings. Do not patch two divergent copies by hand. Implement or reuse a single helper, for example `_normalize_memory_agent_outcome(result)`, and call it from both parser/validator paths.

Rules:

- `changed` -> `applied`.
- `applied` and existing non-mutating outcomes stay valid.
- Unknown successful outcome with same-run `changed_memories` or `removed_memories` becomes `reported_outcome=<original>`, `outcome="applied"`.
- Unknown successful outcome with no changed/removed trace remains invalid.

### Amendment B: Separate agent-routed candidates from deterministic no-op routes

`run_memory_improvement_step()` already routes `memory_inventory_candidate` and `memory_placement_candidate` through `_memory_non_operation_route()` before `_dispatch_memory_agent()`. When adding inventory/placement to the memory-agent handoff, explicitly refactor the flow so each evidence item is classified once:

- `agent_candidate`: compacted and sent to memory-agent.
- `deterministic_noop`: kept as `skip/keep_current_memory|keep_current_user` or diagnostic/skill route.
- `hinted_operation`: executed through existing operation path when a safe deterministic `target_resolution_hint.memory_operation_hint` exists.

Do not let the same inventory/placement evidence both produce a defer/skip decision and enter `memory_agent` as an active candidate unless the report intentionally records an `agent_candidate` plus an omitted deterministic summary.

### Amendment C: Make candidate-kind prompt support explicit

If `memory_agent` prompt assumes every candidate has `candidate_fact`, update the prompt/task schema before expanding dispatch kinds. The prompt must explain candidate kinds generically:

- `memory_gap_candidate`: proposed fact with optional `old_text`.
- `memory_inventory_candidate`: compact existing entries requiring add/replace/remove/skip decision.
- `memory_placement_candidate`: suspicious placement only; decide keep/move/skill-route/skip.
- `environment_fact_signal`: structural hint from failures/retries/value deltas; not a command.

The LLM must be told that all candidates are hints, not tool instructions.

### Amendment D: Generate `environment_fact_signal` in a defined evidence-pack slot

Add a collector such as `collect_environment_fact_signals(events, existing_memory_entries=...)` in `evidence.py` and call it inside `build_evidence_pack()` after tool failure / unmatched / coverage evidence is available, before `views` and `inventory_health` are finalized.

Deduplicate by stable hash over session/tool/error/value token/support reason. Do not create separate duplicate signals for every retry in the same local sequence.

### Amendment E: Redact and normalize value tokens for general distribution

Stable value tokens are useful, but plugin artifacts may be shared. Add tests and implementation for:

- home path normalization: `/Users/<name>/...` and platform home equivalents -> `~/...` when possible.
- secret marker filtering before token emission.
- max token count and max token length.
- no full raw stdout/stderr or complete command transcript in `support_preview`.

### Amendment F: Cap current memory entries passed to memory-agent

The existing `current_entries` handoff can itself bloat prompts. Task 8 must also cap or filter `current_entries`:

- Prefer entries related to selected candidates by token overlap / exact `old_text` / target store.
- Keep a small fallback cap, e.g. first 20 compact entries, if no relation can be found.
- Report `current_entries_omitted_count` in preview/result metadata.

### Amendment G: Treat lexical markers as compatibility hints only

Task 5 should not leave `_rank_reason()` as the effective primary sorter. The new structural signal output must be used in `build_memory_extractor_windows()` sorting. Lexical markers may remain as a tie-breaker and should be described as optional compatibility hints. Future work may make them configurable or remove them.

### Amendment H: Add a cleanup task after routing expansion

After Tasks 3, 4, 7, and 8, add a small cleanup pass to simplify `_memory_non_operation_route()`, `_memory_agent_candidate_from_evidence()`, and `_dispatch_memory_agent()` so the new routing contract is legible and kind-specific behavior is test-covered.

## Open design notes for implementation review

- The new structural signal generator should probably live in `evidence.py` first. If it grows, extract a small `memory_signals.py` later, but avoid a new abstraction in the first slice.
- `environment_fact_signal` should be allowed to route to skill if the LLM sees procedure rather than fact. This should be a normal memory-agent skip/convert outcome, not a separate pipeline.
- If `memory_agent` prompt currently assumes all candidates have `candidate_fact`, update it to describe candidate kinds generically.
- GEPA will optimize the decision prompt later; this plan focuses on making the right compact materials available to that prompt.
