# LLM Target Resolve and Conversation Memory Gaps Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task. Keep the implementation inside the existing `improve` flow. Do not add a new user-facing command, approval queue, review lane, or apply-mode taxonomy.

**Status:** Implemented through Task 8 in commits `6522a3d` and this follow-up: context-window builders, unmatched evidence candidates, LLM target resolver, conversation memory gap candidates, memory add/replace path integration, compact tool `action_summary` / `actionable` buckets, and runtime eval cases from improve run artifacts. Remaining follow-up is broader CLI/report text polish and dogfood prompt tuning.

**Goal:** Make `improve` planner high-value unmatched evidence, resolve skill targets with LLM + context windows, and detect missing user/memory facts from conversation context so safe skill and memory improvements are applied automatically.

**Architecture:** Program code builds compact context windows and candidate groups; LLMs perform fuzzy extraction, target resolution, and apply/defer/skip/block judgment. Program code enforces only hard invariants and executes through existing bounded skill/memory mutation paths. `apply` remains a single mutation outcome with ledgers/artifacts always written; no `auto_apply_with_ledger`, `dry_run_only`, approval queue, or separate inventory lane.

**Tech Stack:** Python, pytest, Hermes plugin runtime, existing `improve` / `report` / `calibrate` commands, runtime artifacts under `${HERMES_HOME:-~/.hermes}/self-improvement/`, official Hermes skill/memory tools.

---

## Current context

This plan follows and partially supersedes the active plan:

- `.hermes/plans/2026-05-07_095543-llm-inventory-candidates.md`

That plan already added or planned compact inventory evidence in `hermes_self_improvement/evidence.py`. Current code includes:

- `make_skill_inventory_candidate()`
- `make_memory_inventory_candidate()`
- `collect_skill_inventory_candidates()`
- `collect_memory_inventory_candidates()`
- inventory evidence wiring in `build_evidence_pack()`
- planner support for attached `skill_inventory_candidate`

The remaining gap is not “more deterministic filters”. The gap is that `improve` still over-relies on evidence already attached to Curator skill candidates, while the useful material often appears as unmatched cross-cutting tool failures or conversation corrections/preferences.

Recent dry-run evidence showed:

- `unmatched_evidence_count` was high.
- The only mutation-ready skill was `herm-tui-development`.
- The higher-value themes were unmatched: patch usage, terminal cwd/repo/path/auth preflight, Safehouse permission handling, timeout/background handling.
- Memory changes were `0`, even though conversation-level user preferences can be more important than memory file inventory alone.

## Design decisions from Ryo

- Use an LLM for target resolution. Heuristic-only target selection is not good enough.
- Do not make apply mode complicated. Use simple decisions: `apply`, `defer`, `skip`, `block`.
- `apply` always records ledger/artifact evidence; do not create a separate `auto_apply_with_ledger` mode.
- Auto-apply should be less conservative than before. Low-to-medium-risk existing skill updates, stale path/command fixes, obvious workflow improvements, and missing memory additions/replacements should happen automatically when hard checks pass.
- Memory improvement must use conversation interactions, not only memory inventory. Repeated user preferences/corrections that are not remembered are first-class memory candidates.
- Conversation extraction must not depend on keyword filters as hard gates. Programmatic filters can rank windows, but should not decide semantic value.
- A hit message alone is not enough. Extract the previous/following messages around the hit so the LLM sees context.

## Scope

In scope:

- Build compact event/conversation windows from existing observer telemetry.
- Add LLM target resolver for unmatched skill evidence and cross-cutting proposal clusters.
- Add conversation-derived memory gap candidates with context windows.
- Feed report proposal clusters into `improve` evidence/digest rather than leaving them report-only.
- Simplify planner decisions toward `apply | defer | skip | block` while preserving existing backend names where necessary.
- Keep mutation execution through existing bounded skill and memory tools.
- Improve dry-run/run summaries to show mutation-ready, high-value unresolved, memory-gap, and skipped/noise groups.
- Add runtime eval cases so `calibrate` can learn this judgment pattern.

Out of scope:

- No Hermes core changes.
- No new top-level `hermes self-improvement ...` wiring.
- No new primary CLI/tool command.
- No separate review lane, inventory lane, approval artifacts, or multi-stage apply policy.
- No direct filesystem edits to skill or memory stores.
- No memory delete auto-apply in this plan.
- No skill merge/rename/delete auto-apply in this plan.
- No heavy hook-time LLM calls. LLM extraction/resolution runs in `improve`, not runtime hooks.

## Desired final behavior

For a run like the current dry-run, the compact result should be closer to:

```text
Mutation-ready:
- hermes-skill-management: patch tool argument pitfall, apply
- hermes-environment-sandboxing: Safehouse permission denied workflow, apply
- USER memory: replace/add self-improvement auto-apply preference, apply

Deferred:
- terminal preflight guidance: target candidates found, examples mix git/auth/path; needs narrower instructions
- timeout handling: useful but target not resolved confidently enough

Skipped:
- browser_navigate timeout: one-off
```

The exact target names may differ; the important point is that high-value unmatched evidence is summarized, target-resolved, and either applied or explicitly deferred with rationale.

---

## Safety model

### Planner decisions

Use only these semantic decisions in new planner/extractor outputs:

```text
apply
defer
skip
block
```

Mapping to existing internals is allowed, but keep user-facing summaries simple.

Suggested internal compatibility mapping:

- Skill `apply` + patch intent → existing `run_editor`
- Skill `apply` + archive intent → existing `archive_skill` only when Curator archive hard checks pass
- Memory `apply` → existing memory mutation operation path
- `defer` / `skip` / `block` → no mutation

### Hard program stops

Program code should stop only hard boundaries:

- non-mutable, pinned, bundled, hub, external-dir, built-in, plugin-bundled, or ambiguous-provenance skill
- arbitrary repo docs/config/Hermes core/cron mutation
- direct filesystem mutation fallback
- memory delete
- skill merge/rename/delete
- secrets/credentials/PII-like content
- target missing or target hash/provenance drift
- unsupported memory provider operation
- editor attempts a different target than planner resolved

### Apply posture

`apply` is allowed for:

- small-to-medium existing skill additions/replacements
- stale path/command correction
- old workflow step correction
- small reusable pitfall/verification update
- user preference memory add/replace
- environment fact memory add/replace
- conversation-derived missing memory when the LLM sees enough context and related existing memories

All `apply` outcomes write compact ledger/episode/artifact records.

---

## Task 1: Add context-window builder for runtime events

**Objective:** Build compact windows around evidence events so LLM target resolution sees surrounding context rather than isolated tool failures.

**Files:**

- Modify: `hermes_self_improvement/evidence.py`
- Test: `tests/test_evidence_context_windows.py` (create)

**Step 1: Write failing tests**

Create tests for a pure helper:

```python
def test_build_context_window_includes_previous_and_next_events():
    events = [
        {"event": "post_llm_call", "session_id": "s1", "assistant_response_preview": "Use skill A"},
        {"event": "post_tool_call", "session_id": "s1", "tool_name": "patch", "status": "error", "error_kind": "unknown_error", "result_preview": "path required"},
        {"event": "post_llm_call", "session_id": "s1", "assistant_response_preview": "I will retry with path"},
    ]

    window = build_context_window(events, center_index=1, radius=1)

    assert window["center_index"] == 1
    assert [item["event"] for item in window["events"]] == ["post_llm_call", "post_tool_call", "post_llm_call"]
    assert window["session_id"] == "s1"


def test_build_context_window_does_not_cross_sessions():
    events = [
        {"event": "post_llm_call", "session_id": "s0", "assistant_response_preview": "other"},
        {"event": "post_tool_call", "session_id": "s1", "tool_name": "patch", "status": "error"},
        {"event": "post_llm_call", "session_id": "s2", "assistant_response_preview": "other"},
    ]

    window = build_context_window(events, center_index=1, radius=2)

    assert len(window["events"]) == 1
    assert window["events"][0]["session_id"] == "s1"
```

**Step 2: Run tests and verify failure**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_evidence_context_windows.py -q
```

Expected: fail because helper does not exist.

**Step 3: Implement `build_context_window()`**

Add to `evidence.py`:

```python
def build_context_window(events: list[dict[str, Any]], *, center_index: int, radius: int = 3) -> dict[str, Any]:
    ...
```

Requirements:

- Include at most `radius` events before and after the center.
- Do not cross `session_id` boundaries unless the center lacks a session id.
- Compact each event with existing redaction helpers.
- Include available previews:
  - `user_message_preview`
  - `assistant_response_preview`
  - `args_preview`
  - `result_preview`
  - `tool_name`
  - `status`
  - `error_kind`
  - `model` / `provider`
- Keep full payloads out of the window.

**Step 4: Run tests**

```bash
$PY -m pytest tests/test_evidence_context_windows.py -q
```

Expected: pass.

**Step 5: Commit**

```bash
git add hermes_self_improvement/evidence.py tests/test_evidence_context_windows.py
git commit -m "feat: add self-improvement evidence context windows"
```

---

## Task 2: Build high-value unmatched evidence candidates

**Objective:** Convert unmatched evidence clusters into compact candidates instead of treating them as discarded planner leftovers.

**Files:**

- Modify: `hermes_self_improvement/evidence.py`
- Modify: `hermes_self_improvement/planner.py`
- Test: `tests/test_unmatched_evidence_candidates.py` (create)

**Step 1: Write failing tests**

```python
def test_build_unmatched_candidate_groups_patch_failures_with_context():
    events = [
        {"event": "post_tool_call", "session_id": "s1", "tool_name": "patch", "status": "error", "error_kind": "unknown_error", "result_preview": "path required"},
        {"event": "post_tool_call", "session_id": "s1", "tool_name": "patch", "status": "error", "error_kind": "not_found", "result_preview": "old_string and new_string are identical"},
    ]

    candidates = build_unmatched_improvement_candidates(events, existing_candidate_names=[])

    assert candidates
    item = candidates[0]
    assert item["kind"] == "unmatched_improvement_candidate"
    assert item["theme"] == "patch_tool_workflow"
    assert item["likely_targets"][0]["target"] == "skill"
    assert item["context_windows"]
```

**Step 2: Run tests and verify failure**

```bash
$PY -m pytest tests/test_unmatched_evidence_candidates.py -q
```

Expected: fail.

**Step 3: Implement candidate builder**

Add `build_unmatched_improvement_candidates(events, existing_candidate_names, *, limit=10)`.

Initial themes:

- `patch_tool_workflow`
  - `patch` errors: `path required`, `old_string and new_string are identical`, match not found, multiple matches
- `terminal_preflight_workflow`
  - terminal non-zero involving git repo, missing executable, cwd/path, auth/token
- `sandbox_permission_workflow`
  - `permission_denied`, `Operation not permitted`, Safehouse-like failures
- `timeout_workflow`
  - repeated terminal/browser/report timeout

Each candidate should include:

```json
{
  "kind": "unmatched_improvement_candidate",
  "theme": "patch_tool_workflow",
  "count": 12,
  "likely_targets": [{"target": "skill", "weight": 0.8}],
  "representative_failures": [...],
  "context_windows": [...],
  "resolver_required": true,
  "rationale": "..."
}
```

Do not attach a target skill in code.

**Step 4: Wire into evidence pack**

In `build_evidence_pack()`, append these candidates after raw evidence / cluster evidence / inventory evidence.

Summary should expose:

- `unmatched_candidate_count`
- `unmatched_candidate_themes`

**Step 5: Run targeted tests**

```bash
$PY -m pytest tests/test_evidence_context_windows.py tests/test_unmatched_evidence_candidates.py -q
```

Expected: pass.

**Step 6: Commit**

```bash
git add hermes_self_improvement/evidence.py hermes_self_improvement/planner.py tests/test_unmatched_evidence_candidates.py tests/test_evidence_context_windows.py
git commit -m "feat: promote unmatched evidence into improvement candidates"
```

---

## Task 3: Add LLM target resolver

**Objective:** Resolve candidate skill/memory targets with an LLM using evidence windows, skill inventory, and existing memory summaries.

**Files:**

- Create: `hermes_self_improvement/target_resolver.py`
- Modify: `hermes_self_improvement/planner.py`
- Modify: `hermes_self_improvement/prompts.py`
- Test: `tests/test_target_resolver.py` (create)

**Step 1: Write pure normalization tests**

```python
def test_normalize_target_resolver_payload_keeps_known_mutable_targets():
    payload = {
        "resolutions": [{
            "candidate_id": "u1",
            "target_kind": "skill",
            "target": "hermes-skill-management",
            "confidence": "high",
            "reason": "patch failures while editing skills",
            "suggested_action": "apply",
        }]
    }
    known = {"hermes-skill-management": {"mutable": True, "pinned": False, "state": "active", "provenance": "curator_agent_created"}}

    out = normalize_target_resolver_payload(payload, known_skill_targets=known)

    assert out["resolutions"][0]["target"] == "hermes-skill-management"
    assert out["resolutions"][0]["decision_hint"] == "apply"


def test_normalize_target_resolver_payload_blocks_unknown_skill_target():
    payload = {"resolutions": [{"candidate_id": "u1", "target_kind": "skill", "target": "missing", "confidence": "high"}]}

    out = normalize_target_resolver_payload(payload, known_skill_targets={})

    assert out["resolutions"][0]["decision_hint"] == "block"
    assert out["resolutions"][0]["block_reason"] == "unknown_target"
```

**Step 2: Run tests and verify failure**

```bash
$PY -m pytest tests/test_target_resolver.py -q
```

Expected: fail.

**Step 3: Implement `target_resolver.py`**

Functions:

- `build_target_resolution_digest(evidence_pack, *, skill_candidates, memory_context)`
- `normalize_target_resolver_payload(payload, *, known_skill_targets)`
- `run_target_resolver(digest, *, config)`

LLM prompt rules:

- Resolve targets for `unmatched_improvement_candidate`, `tool_error_cluster_evidence` without target hints, and conversation memory gaps.
- Return only JSON.
- Do not invent non-existing skill targets.
- Prefer existing mutable local skills.
- If no good target exists, return `defer`, not a speculative target.
- Suggested decisions are only `apply`, `defer`, `skip`, `block`.

**Step 4: Integrate with planner digest**

In `build_skill_planner_digest()`:

- Accept target resolver output from the evidence pack or caller.
- Attach resolved skill evidence to candidate rows with `evidence_match="llm_target_resolver"` and medium/high strength based on resolver confidence.
- Preserve unresolved candidates under `unresolved_improvement_candidates` instead of burying them under raw unmatched examples.

Avoid adding a new command or separate planning stage visible to users.

**Step 5: Add fake LLM tests**

Inject a resolver function in config, similar to `_skill_planner_func`, so tests do not call real LLMs.

```python
def fake_resolver(digest, config):
    return {"resolutions": [{"candidate_id": "u1", "target_kind": "skill", "target": "hermes-skill-management", "confidence": "high", "suggested_action": "apply"}]}
```

Verify the resolved evidence becomes attached to the candidate row.

**Step 6: Run tests**

```bash
$PY -m pytest tests/test_target_resolver.py tests/test_skill_planner.py -q
```

Expected: pass.

**Step 7: Commit**

```bash
git add hermes_self_improvement/target_resolver.py hermes_self_improvement/planner.py hermes_self_improvement/prompts.py tests/test_target_resolver.py tests/test_skill_planner.py
git commit -m "feat: resolve self-improvement targets with llm context"
```

---

## Task 4: Add conversation-derived memory gap candidates

**Objective:** Detect user preferences/corrections that are missing or outdated in memory using context windows and LLM judgment, not keyword hard filters.

**Files:**

- Create: `hermes_self_improvement/conversation_memory.py`
- Modify: `hermes_self_improvement/evidence.py`
- Modify: `hermes_self_improvement/runner_steps.py` or current memory step file
- Test: `tests/test_conversation_memory_candidates.py` (create)

**Step 1: Write tests for window ranking without hard filtering**

```python
def test_rank_conversation_windows_prefers_user_correction_but_keeps_other_windows():
    events = [
        {"event": "post_llm_call", "session_id": "s1", "user_message_preview": "それは違う。plugin側だけで進めて"},
        {"event": "post_llm_call", "session_id": "s2", "user_message_preview": "普通の相談"},
    ]

    windows = build_conversation_memory_windows(events, limit=10)

    assert len(windows) == 2
    assert windows[0]["rank_reason"] in {"correction_like", "preference_like"}
```

This test protects the design: filters rank windows, they do not discard all non-keyword windows.

**Step 2: Write tests for LLM extractor normalization**

```python
def test_normalize_memory_gap_payload_allows_add_and_replace():
    payload = {
        "candidates": [{
            "candidate_id": "m1",
            "target": "user",
            "action": "replace",
            "candidate_fact": "Ryo prefers plugin-side self-improvement work unless Hermes core changes are explicit.",
            "old_text": "Ryo prefers core changes for self-improvement.",
            "confidence": "high",
            "reason": "User corrected this repeatedly",
        }]
    }

    out = normalize_memory_gap_payload(payload)

    assert out["candidates"][0]["action"] == "replace"
    assert out["candidates"][0]["target"] == "user"
```

**Step 3: Run tests and verify failure**

```bash
$PY -m pytest tests/test_conversation_memory_candidates.py -q
```

Expected: fail.

**Step 4: Implement conversation window builder**

`conversation_memory.py` functions:

- `build_conversation_memory_windows(events, *, radius=3, limit=40)`
- `build_memory_gap_digest(windows, *, existing_memories, recent_candidates)`
- `normalize_memory_gap_payload(payload)`
- `run_memory_gap_extractor(digest, *, config)`

Window ranking inputs:

- user correction-like text
- preference-like text
- assistant failure followed by user response
- repeated topic/session themes
- light sampling of non-keyword windows

Important: do not make keyword hits a hard gate. Keep a small quota of general user-message windows.

Each window includes:

- previous/following messages/events from same session
- redacted previews only
- center event id/index
- rank reason
- session/source/platform if available

**Step 5: Existing memory lookup**

Use existing memory context helpers if available (`memory_context.py`) or add a small read-only helper that returns compact related entries from:

- built-in `USER.md` / `MEMORY.md` summaries when paths are available
- external provider lookup summary when current code already supports it
- recent memory candidate ledger if present

Do not direct-edit memory files.

**Step 6: Evidence candidate shape**

Emit `conversation_memory_gap_candidate` items:

```json
{
  "kind": "conversation_memory_gap_candidate",
  "likely_targets": [{"target": "memory", "weight": 0.9}],
  "memory": {
    "target": "user",
    "action": "add|replace",
    "candidate_fact": "...",
    "old_text": "... optional for replace",
    "relation_to_existing": "missing|supersedes|duplicates|already_covered",
    "confidence": "high|medium|low"
  },
  "context_windows": [...],
  "rationale": "..."
}
```

**Step 7: Wire into `build_evidence_pack()`**

Add optional `memory_context` / `conversation_memory_enabled` parameters if needed. Keep defaults safe and cheap.

**Step 8: Commit**

```bash
git add hermes_self_improvement/conversation_memory.py hermes_self_improvement/evidence.py hermes_self_improvement/runner_steps.py tests/test_conversation_memory_candidates.py
git commit -m "feat: detect conversation-derived memory gaps"
```

---

## Task 5: Make memory apply less conservative for add/replace

**Objective:** Allow high-confidence conversation-derived memory add/replace operations to apply automatically when mutation is enabled and hard checks pass.

**Files:**

- Modify: `hermes_self_improvement/runner_steps.py`
- Modify: `hermes_self_improvement/mutation_policy.py`
- Modify: `hermes_self_improvement/mutation_worker.py` if needed
- Test: `tests/test_memory_inventory_planner.py`
- Test: `tests/test_conversation_memory_candidates.py`

**Step 1: Write failing test for apply add**

```python
def test_memory_gap_add_applies_when_high_confidence_and_not_secret(fake_memory_backend):
    evidence = {
        "id": "m1",
        "kind": "conversation_memory_gap_candidate",
        "memory": {
            "target": "user",
            "action": "add",
            "candidate_fact": "Ryo prefers simple apply/defer/skip/block decisions for self-improvement.",
            "confidence": "high",
            "relation_to_existing": "missing",
        },
    }

    result = run_memory_improvement_step({"evidence": [evidence]}, execute=True, config={"_memory_backend": fake_memory_backend})

    assert result["changed"] == 1
```

Adapt the exact call signature to current `run_memory_improvement_step()`.

**Step 2: Write failing test for block delete/secret**

```python
def test_memory_gap_blocks_delete_and_secret():
    ...
```

Expected blocked cases:

- `action="remove"`
- `candidate_fact` or `old_text` looks secret/credential-like
- missing target
- replace without specific `old_text`

**Step 3: Implement apply logic**

For `conversation_memory_gap_candidate`:

- `add` with high/medium confidence can apply.
- `replace` can apply if `old_text` is specific and target store is known.
- `remove` blocks in this plan.
- `duplicates` / `already_covered` skip.
- Low confidence defer.

Do not add a separate human approval path.

**Step 4: Run targeted tests**

```bash
$PY -m pytest tests/test_memory_inventory_planner.py tests/test_conversation_memory_candidates.py -q
```

Expected: pass.

**Step 5: Commit**

```bash
git add hermes_self_improvement/runner_steps.py hermes_self_improvement/mutation_policy.py hermes_self_improvement/mutation_worker.py tests/test_memory_inventory_planner.py tests/test_conversation_memory_candidates.py
git commit -m "feat: auto-apply high-confidence memory gap updates"
```

---

## Task 6: Simplify planner semantics to apply/defer/skip/block in prompts and summaries

**Objective:** Keep user-facing and artifact summaries simple without breaking existing internal backend names.

**Files:**

- Modify: `hermes_self_improvement/prompts.py`
- Modify: `hermes_self_improvement/planner.py`
- Modify: `hermes_self_improvement/tool_handlers.py`
- Modify: `hermes_self_improvement/episodes.py`
- Test: `tests/test_skill_planner.py`
- Test: `tests/test_cli_surface.py`

**Step 1: Update planner prompt schema**

In `prompts.py`, change new planner wording to ask for semantic decisions:

```json
{"decisions":[{"target_kind":"skill|memory","target":str,"decision":"apply|defer|skip|block", ...}]}
```

Keep compatibility parser support for old `run_editor`, `archive_skill`, `memory_candidate` while new prompts prefer `apply`.

**Step 2: Normalize semantic decisions**

In planner normalization:

- `apply` + skill patch intent → internal `run_editor`
- `apply` + archive intent → internal `archive_skill` only if archive markers pass
- `apply` + memory op → route to memory step
- `block` → no mutation, `reason` required
- `defer` / `skip` unchanged

Do not expose `auto_apply_with_ledger` or `dry_run_only`.

**Step 3: Update summaries**

Tool/CLI summary should show:

- `apply_ready`
- `applied` when executed
- `deferred`
- `skipped`
- `blocked`
- `high_value_unresolved`
- `memory_gap_candidates`

The full artifact may keep internal names for backward compatibility.

**Step 4: Run tests**

```bash
$PY -m pytest tests/test_skill_planner.py tests/test_cli_surface.py -q
```

Expected: pass.

**Step 5: Commit**

```bash
git add hermes_self_improvement/prompts.py hermes_self_improvement/planner.py hermes_self_improvement/tool_handlers.py hermes_self_improvement/episodes.py tests/test_skill_planner.py tests/test_cli_surface.py
git commit -m "refactor: simplify self-improvement planner decisions"
```

---

## Task 7: Improve dry-run and report summaries

**Objective:** Make dry-run answers match the useful human diagnosis: what is ready to apply, what is high-value but unresolved, what memory gaps were found, and what was skipped as noise.

**Files:**

- Modify: `hermes_self_improvement/tool_handlers.py`
- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/runner_steps.py`
- Test: `tests/test_cli_surface.py`

**Step 1: Write summary tests**

Use a synthetic run result containing:

- one skill apply-ready decision
- one high-value unresolved unmatched candidate
- one conversation memory gap apply-ready decision
- one skipped one-off browser timeout

Assert compact summary contains separate buckets and artifact path.

**Step 2: Implement compact buckets**

Add summary sections:

```json
{
  "mutation_ready": [...],
  "high_value_unresolved": [...],
  "memory_gap_candidates": {...},
  "skipped_noise": {...},
  "blocked": [...]
}
```

Keep each entry compact: target, theme, decision, reason, evidence count, artifact ids. No full prompt/window dumps in tool result.

**Step 3: CLI text output**

For local CLI, include a short human-readable section:

```text
Mutation-ready: N
High-value unresolved: N
Memory gaps: N
Skipped/noise: N
Artifacts: ...
```

**Step 4: Run tests**

```bash
$PY -m pytest tests/test_cli_surface.py -q
```

Expected: pass.

**Step 5: Commit**

```bash
git add hermes_self_improvement/tool_handlers.py hermes_self_improvement/cli.py hermes_self_improvement/runner_steps.py tests/test_cli_surface.py
git commit -m "feat: summarize actionable self-improvement candidates"
```

---

## Task 8: Feed this judgment pattern into calibration eval cases

**Objective:** Teach `calibrate` that high-value unmatched evidence and conversation memory gaps should not be ignored just because immediate skill changes are zero.

**Files:**

- Modify: `hermes_self_improvement/runtime_eval_cases.py`
- Modify: `hermes_self_improvement/calibration.py`
- Test: `tests/test_runtime_eval_cases.py` or create if absent

**Step 1: Add eval case fixture**

Create a test case where:

- Curator candidate count is 1.
- Attached skill evidence is low-value/small.
- Unmatched evidence includes repeated patch/terminal/Safehouse failures.
- Conversation windows include a repeated user preference not in memory.

Expected evaluator behavior:

- Do not report “nothing to improve”.
- Identify mutation-ready or high-value unresolved candidates.
- Do not invent memory deletion.
- Do not force apply when target confidence is low.

**Step 2: Implement runtime eval case builder**

When improve runs produce high unmatched counts or memory gap candidates, add compact runtime-private eval cases for planner/editor/evaluator overlays.

Include:

- active overlay hashes
- run id
- evidence ids
- expected behavior labels
- no full private conversation text beyond redacted snippets/windows already in artifacts

**Step 3: Run tests**

```bash
$PY -m pytest tests/test_runtime_eval_cases.py -q
```

Expected: pass.

**Step 4: Commit**

```bash
git add hermes_self_improvement/runtime_eval_cases.py hermes_self_improvement/calibration.py tests/test_runtime_eval_cases.py
git commit -m "feat: add eval cases for unmatched evidence and memory gaps"
```

---

## Task 9: Docs and operational alignment

**Objective:** Update repo docs so future agents do not reintroduce complex apply modes or keyword-gated memory extraction.

**Files:**

- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `skills/operations/SKILL.md`
- Modify: `.hermes/plans/README.md`

**Step 1: Read files immediately before editing**

Do not resurrect removed user edits. Re-read each file before patching.

**Step 2: Update docs**

Document:

- `improve` now uses context-windowed candidates.
- LLM target resolver handles fuzzy target choice.
- Conversation-derived memory gaps are in scope.
- Programmatic filters rank windows, not gate them.
- Semantic decisions are `apply / defer / skip / block`.
- `apply` always records artifact/ledger evidence.
- Human confirmation is not the normal path; hard stops block unsafe changes.
- No new command, approval queue, apply mode taxonomy, or lane.

**Step 3: Run docs sanity checks**

```bash
git diff --check
```

**Step 4: Commit**

```bash
git add README.md AGENTS.md skills/operations/SKILL.md .hermes/plans/README.md
git commit -m "docs: document llm-resolved self-improvement flow"
```

---

## Task 10: End-to-end verification

**Objective:** Prove the feature works without mutating real skills/memory first, then run a controlled mutation if dry-run looks correct.

**Files:**

- No planned code changes.

**Step 1: Static checks**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
git diff --check
```

Expected: all pass.

**Step 2: Dry-run dogfood**

```bash
hermes self-improvement improve --dry-run --json
```

Expected:

- Evidence summary includes context-window and unmatched candidate counts.
- Planner summary includes mutation-ready / high-value unresolved / memory-gap buckets.
- No direct file edits happen.
- Full private details stay in artifact paths, not tool summary.

**Step 3: Mutating dogfood only after dry-run looks sane**

```bash
hermes self-improvement improve --json
```

Expected:

- Low-to-medium risk apply candidates mutate through official tools only.
- Memory add/replace uses memory/provider tools only.
- Ledger/episode artifacts are written.
- Blocked/deferred items are visible but not applied.

**Step 4: Calibration dry-run**

```bash
hermes self-improvement calibrate --dry-run --json
```

Expected:

- Runtime eval cases include the new judgment pattern when evidence exists.
- GEPA/candidate generation remains signal-gated.

**Step 5: Final commit/push if requested or repo convention requires**

```bash
git status --short
git log --oneline -5
```

If all checks pass and the task was implementation, commit/push in logical milestones.

---

## Risks and tradeoffs

- **LLM resolver can overfit to plausible but wrong targets.** Mitigation: require existing mutable target, include context windows, and block unknown/non-mutable targets in program code.
- **Conversation memory extraction can over-store transient opinions.** Mitigation: LLM must state why the fact is durable and why it is not temporary; program blocks delete/secrets and summaries expose additions/replacements.
- **Window volume can bloat prompts.** Mitigation: compact/redacted windows, per-theme limits, full data only in artifacts.
- **Unmatched evidence may still be noisy.** Mitigation: use LLM judgment and `defer/skip`, not deterministic auto-attachment.
- **Simplifying decisions can conflict with current internal names.** Mitigation: keep compatibility mapping internally while showing simple semantic buckets externally.

## Open questions for implementation

- Whether to store context windows directly in evidence artifacts or as separate referenced artifacts when large.
- Whether existing `memory_context.py` is enough for related memory lookup or needs a small helper.
- How much non-keyword conversation sampling is affordable per `improve` run. Start small and configurable.
- Whether target resolver should run before or inside `build_skill_planner_digest()`. Prefer before digest finalization if it keeps artifacts clearer.

## Non-goals to preserve

- Do not revive `plan / apply / rollback / outcome` as primary surfaces.
- Do not add approval queues.
- Do not add separate inventory/review lanes.
- Do not make keyword filters determine memory truth.
- Do not run LLMs in observer hooks.
- Do not mutate Hermes core or plugin runtime config from self-improvement.
