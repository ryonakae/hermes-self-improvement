# Global Planner Before Editor Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** `judge` terminologyを外部・内部ともに `planner` に寄せ、`improve --dry-run` が「どのskillがなぜ選ばれ、どう修正予定か」を表示できるようにする。実行構造は `analyzer/evidence builder -> global planner -> per-skill editor` にする。

**Architecture:** Analyzer は既存の evidence pack builder を維持する。新しい global planner は Curator candidate list、attached evidence、target resolution summary、ignored/rejected evidence summary を compact digest として受け取り、`run_editor / skip / human_review / memory_candidate / evaluator_candidate` の plan を返す。Dry-run は planner まで実行し editor は実行しない。Mutating run は planner が `run_editor` とした対象だけ editor に渡す。GEPA/DSPy は planner/editor prompt・rubric改善の `calibrate` 側に残す。

**Tech Stack:** Python, argparse, pytest, Hermes auxiliary LLM, Hermes plugin tool schemas, bounded skill mutation backend.

---

## Current context

- Repo: `/Users/ryo.nakae/.hermes/plugins/hermes-self-improvement`
- Branch/status at planning time: `main`, clean working tree.
- Latest completed commit: `db292f1 fix: remove gepa compare proposal scorers`.
- Current baseline:
  - `improve` / `report` proposal scoring defaults to `llm`.
  - `gepa` / `compare` are no longer primary proposal scorers.
  - `run_skill_improvement_step()` still loops through every mutable Curator candidate and creates a per-skill editor task.
  - Dry-run currently creates task previews but does not run an LLM that globally chooses targets or produces planned edits.
- User decision:
  - Rename `judge` thesaurus to `planner` externally and internally where it describes this self-improvement decision layer.
  - Use the simpler two-stage model: **global planner + individual editor**.

## Non-goals

- Do not add a separate per-skill planner stage yet. Keep the simpler model.
- Do not make GEPA a live `improve` judge/planner. GEPA remains `calibrate` / evaluator optimization.
- Do not broaden mutation scope beyond local mutable skills and supported memory tools.
- Do not reintroduce `plan/apply/rollback/outcome`, `--execute`, item selection, or approval surfaces.
- Do not direct-edit skills/memory files; editor remains tool-mediated.

---

## Desired behavior

### `improve --dry-run`

Dry-run should execute:

```text
analyzer/evidence builder -> global planner -> summary/artifact
```

It should not execute editor mutation.

Human-facing summary should include concise planner output, for example:

```text
Planner:
- selected for editor: 1
- skipped: 32
- human review: 0

Planned skill edits:
- hermes-development-maintenance
  decision: run_editor
  intent: add pitfall about qualified skill names resolving to bare mutable candidates
  evidence: 3 events
  reason: repeated skill_view not_found for qualified name while bare candidate exists
```

Artifact should include full planner payload and compact planner input digest.

### `improve` mutating run

Mutating run should execute:

```text
analyzer/evidence builder -> global planner -> editor only for run_editor targets
```

Editor receives planner-produced `editor_instructions` and selected `evidence_ids`, not a generic per-candidate task.

---

## Naming / terminology target

Use `planner` for the new global decision layer.

Rename current user-facing or internal self-improvement decision terminology where it refers to this layer:

```text
model.judge       -> model.planner
merge_judge       -> merge_planner or merge/adjudication planner, if still applicable
llm_scorer/judge  -> planner, where the function decides improvement tasks rather than scores report proposals
```

Important nuance:

- Do not blindly replace all English word `judge` in historical archived plans.
- Do rename active docs, config examples, CLI/status fields, tool outputs, tests, current code identifiers, and bundled operations skill wording.
- For compatibility: the plugin is unreleased/local. Prefer current-only schema over aliases. Do not keep `model.judge` as a fallback unless implementation discovers live runtime config requires one; if required, make it a one-time local config update plan rather than a long-term alias.

---

## Planner schema

Add a current-schema planner result like:

```json
{
  "schema_name": "self_improvement_skill_planner_result",
  "schema_version": "1.0",
  "model_role": "planner",
  "summary": {
    "candidate_count": 33,
    "selected_for_editor": 1,
    "skipped": 32,
    "human_review": 0,
    "memory_candidates": 0,
    "evaluator_candidates": 0
  },
  "decisions": [
    {
      "skill": "hermes-development-maintenance",
      "decision": "run_editor",
      "priority": "high",
      "risk": "low",
      "change_intent": "add pitfall about qualified skill names resolving to bare mutable candidates",
      "editor_instructions": "Patch the skill to document exact qualified match first, then bare fallback, with verification guidance.",
      "evidence_ids": ["ev_..."],
      "rationale": "Repeated evidence shows qualified skill_view not_found while the bare mutable candidate exists."
    },
    {
      "skill": "some-skill",
      "decision": "skip",
      "reason": "no_attached_evidence",
      "evidence_ids": []
    }
  ]
}
```

Allowed decisions:

```text
run_editor
skip
human_review
memory_candidate
evaluator_candidate
```

Planner prompt rule of thumb:

```text
目的は人間レビュー待ちを増やすことではなく、安全に tool-mediated editor に任せられる改善を選ぶこと。
低リスクな local mutable skill の小さな追記・修正は run_editor にする。
曖昧、破壊的、sensitive、target不明、削除/merge/archive は human_review にする。
```

---

## Planner digest input

Build a compact digest rather than passing full artifact JSON.

Include:

- Window summary: event count, evidence count, ignored count.
- Curator candidate summary: name, state, source/provenance, usage/lifecycle fields available from telemetry.
- Evidence attachment summary per candidate:
  - attached evidence count
  - evidence kinds
  - representative redacted previews
  - raw skill name / normalized skill / match kind
- Unmatched/rejected evidence summary:
  - target missing count
  - not mutable candidate count
  - out-of-scope count
  - representative examples
- Mutable scope constraints.
- Planner output schema.

Do not include secrets or raw full outputs. Use existing redaction helpers and cap representative examples.

---

## Task 1: Add failing terminology tests for `planner`

**Objective:** Lock the external/internal terminology pivot before implementation.

**Files:**
- Modify: `tests/test_config_precedence.py`
- Modify: `tests/test_cli_surface.py` or `tests/test_plugin_tools.py`
- Possibly modify: `tests/test_prompt_classification.py`

**Steps:**

1. Add/modify config tests to expect:

```python
assert list(config["model"].keys()) == ["planner", "editor", "evaluator"]
assert "judge" not in config["model"]
```

2. Add status/tool output tests that active runtime/status fields expose planner wording, not judge wording, where applicable.
3. Add strict source-search regression if current test style supports it:
   - active source/docs should not contain `model.judge`.
   - active user-facing docs should not say `judge LLM` for the improvement planning layer.
4. Run focused tests and confirm RED:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_config_precedence.py tests/test_plugin_tools.py tests/test_cli_surface.py tests/test_prompt_classification.py -q
```

Expected failure: current code/docs still use `model.judge`, `merge_judge`, and judge wording.

---

## Task 2: Rename current model role from `judge` to `planner`

**Objective:** Make planner the canonical model role.

**Files likely to change:**
- `hermes_self_improvement/config.py`
- `hermes_self_improvement/scoring.py`
- `hermes_self_improvement/cli.py`
- `hermes_self_improvement/tool_handlers.py`
- `hermes_self_improvement/verification.py` if `merge_judge_status` is current, not historical
- `README.md`
- `config.example.yaml`
- `skills/operations/SKILL.md`
- `skills/operations/references/architecture.md`
- tests

**Implementation details:**

1. Change default model roles:

```yaml
model:
  planner: ...
  editor: ...
  evaluator: ...
```

2. Update LLM routing in proposal scoring / future planner calls to read `model.planner`.
3. Rename functions/fields where practical:
   - `_call_llm_scorer()` may become `_call_planner_scorer()` only if it remains a proposal report scorer.
   - `merge_judge_status` should be renamed only if this is still an active current helper. If it is a legacy merge adjudicator name, inspect before changing.
4. Remove `model.judge` fallback and tests unless a live local config migration is explicitly required.
5. Update config/docs/examples to current-only names.

**Verification:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_config_precedence.py tests/test_prompt_classification.py tests/test_cli_surface.py tests/test_plugin_tools.py -q
```

---

## Task 3: Add planner digest builder tests

**Objective:** Define the compact input passed to global planner.

**Files:**
- Create or modify: `hermes_self_improvement/planner.py`
- Create: `tests/test_skill_planner.py`

**Test cases:**

1. Candidate with attached evidence appears with:
   - `name`
   - candidate state/source fields
   - `attached_evidence_count`
   - `evidence_ids`
   - representative redacted previews
   - match metadata (`raw_evidence_skill`, `normalized_skill`, `evidence_match`) when available

2. Candidate with no evidence appears as candidate-only summary, not as selected.
3. Unmatched evidence summary includes grouped reasons:
   - `skill_target_missing`
   - `skill_not_in_curator_candidates`
   - `out_of_scope`
4. Digest caps examples and does not include full raw event payloads or secrets.

**Expected RED:** `planner.py` does not exist.

---

## Task 4: Implement `build_skill_planner_digest()`

**Objective:** Produce token-bounded planner input from evidence pack and current candidate/evidence matching.

**Implementation details:**

1. Reuse existing target resolution logic from `runner_steps.py` or extract shared helpers.
2. Return structure:

```python
{
  "window": {...},
  "skill_candidates": [...],
  "unmatched_evidence": {...},
  "constraints": {...},
}
```

3. Keep representative previews short and redacted.
4. Include enough information to let the planner choose targets without reading full skill bodies.
5. Do not call LLM here.

**Verification:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_skill_planner.py -q
```

---

## Task 5: Add planner LLM tests with injected fake planner

**Objective:** Define planner call contract and parsing before using real LLM.

**Files:**
- Modify: `hermes_self_improvement/planner.py`
- Modify: `tests/test_skill_planner.py`

**Test cases:**

1. `run_skill_planner()` calls injected `planner_func` with digest and config.
2. Valid planner JSON returns normalized decisions.
3. Invalid JSON fails closed with planner error and no `run_editor` decisions.
4. Planner cannot select non-candidate skills.
5. Planner cannot return `run_editor` without evidence unless candidate lifecycle metadata alone clearly allows it. For initial implementation, prefer fail-closed: require evidence for `run_editor`.
6. Planner output strips unknown fields and redacts/caps rationale/instructions.

**Expected RED:** planner runner missing.

---

## Task 6: Implement `run_skill_planner()`

**Objective:** Add one global LLM call that chooses editor targets and produces editor instructions.

**Implementation details:**

1. Read model config from `model.planner`.
2. Build system/user messages with explicit role:

```text
You are the Hermes self-improvement planner.
Your job is to choose which mutable local skills should be sent to the tool-mediated editor.
Do not maximize human review. Prefer run_editor for low-risk small local skill improvements with attached evidence.
Use human_review only for ambiguous, destructive, sensitive, delete/merge/archive, or target-uncertain cases.
```

3. Output JSON only, with allowed decisions.
4. On LLM/provider/JSON failure, return fail-closed planner result:

```json
{"status":"planner_error", "decisions": []}
```

5. Do not run editor in this function.

**Verification:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_skill_planner.py -q
```

---

## Task 7: Wire planner into `run_skill_improvement_step()`

**Objective:** Replace candidate-all task creation with planner-selected editor tasks.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Modify: `tests/test_runner_steps.py`
- Modify: tool result compaction tests if step shape changes

**Implementation details:**

1. `run_skill_improvement_step()` should:
   - build digest
   - run global planner
   - record planner result
   - for dry-run, return planner decisions and `editor_task_previews` only for `run_editor`
   - for mutating run, execute editor only for `run_editor`
2. Remove dry-run decision reason:

```text
dry_run_would_run_skill_agent
```

3. Replace with:

```text
planner_run_editor_preview
planner_skip_no_evidence
planner_human_review
planner_memory_candidate
planner_evaluator_candidate
```

4. Build editor task from planner decision:

```python
build_skill_agent_task(
    skill_name=decision["skill"],
    evidence=selected_evidence,
    candidate=candidate,
    planner_decision=decision,
)
```

5. Update `build_skill_agent_task()` instructions to include planner intent and editor instructions:

```text
The global planner selected this skill for editor execution.
Planner intent: ...
Planner editor instructions: ...
```

6. Keep editor fail-closed behavior: editor must read the current skill and stop on stale/conflict/unsafe.

**Verification:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_runner_steps.py tests/test_skill_planner.py tests/test_plugin_tools.py -q
```

---

## Task 8: Update dry-run summaries and tool compact results

**Objective:** Make dry-run useful without dumping full planner payload into LLM-facing tool results.

**Files:**
- `hermes_self_improvement/cli.py`
- `hermes_self_improvement/tool_handlers.py`
- tests covering summaries and compact tool results

**Implementation details:**

1. Human CLI summary should show:
   - selected for editor count
   - skipped count
   - human review count
   - top planned skill edits with intent and evidence count
   - artifact path
2. Tool result should remain compact:

```json
{
  "planner": {
    "status": "completed",
    "selected_for_editor": 1,
    "skipped": 32,
    "human_review": 0,
    "planned_edit_previews": [... capped ...]
  },
  "artifact_path": "..."
}
```

3. Full planner digest and decisions stay in run artifact.
4. CLI `--json` keeps full payload for operator/debug.

**Verification:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_cli_surface.py tests/test_plugin_tools.py -q
```

---

## Task 9: Update docs, operations skill, runtime defaults, and eval assets

**Objective:** Align user-facing docs and calibration assets with planner/editor architecture.

**Files likely to change:**
- `README.md`
- `config.example.yaml`
- `skills/operations/SKILL.md`
- `skills/operations/references/architecture.md`
- `defaults/evaluator/proposal-rubric.json`
- `defaults/evaluator/proposal-evaluator.json`
- `defaults/evaluator/proposal-cases.jsonl`
- `evals/proposal/rubric.json`
- `evals/proposal/cases.jsonl`
- `.hermes/plans/README.md`

**Updates:**

1. Replace active `judge` wording with `planner`.
2. Rename proposal/evaluator assets only if they are current runtime active assets for the planner. If renaming files is too broad, update content first and create a follow-up plan for file/path rename.
3. Update calibration language:

```text
GEPA/DSPy improves planner/editor prompts, rubrics, examples, and evaluator artifacts.
```

4. Update dry-run docs:

```text
dry-run executes analyzer + planner, not editor.
```

---

## Task 10: Runtime validation

**Objective:** Verify behavior end-to-end.

**Commands:**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py tests/*.py
$PY -m pytest tests -q
bin/hermes-self-improve status
bin/hermes-self-improve improve --dry-run
bin/hermes-self-improve improve --dry-run --json > /tmp/self_improvement_planner_dry_run.json
$PY - <<'PY'
import json
payload = json.load(open('/tmp/self_improvement_planner_dry_run.json'))
step = payload.get('step_decisions', {}).get('skill', {})
planner = step.get('planner') or {}
print(json.dumps({
    'artifact_path': payload.get('artifact_path'),
    'planner_status': planner.get('status'),
    'selected_for_editor': planner.get('summary', {}).get('selected_for_editor'),
    'dry_run': payload.get('dry_run'),
}, ensure_ascii=False, indent=2))
if payload.get('dry_run') is not True:
    raise SystemExit(1)
if not planner:
    raise SystemExit('missing planner result')
PY
bin/hermes-self-improve report --since-hours 24 --json > /tmp/self_improvement_report.json
git diff --check
```

Also verify `self_improvement_improve(dry_run=True)` tool result stays compact by using the existing plugin tool smoke pattern.

---

## Task 11: Commit and push

**Objective:** Commit a coherent architecture slice.

**Commands:**

```bash
git status --short
git diff --stat
git add hermes_self_improvement tests README.md config.example.yaml skills/operations .hermes/plans
git commit -m "feat: add global planner before skill editor"
git push
```

If this slice becomes too large, split into two commits:

1. `refactor: rename judge role to planner`
2. `feat: add global planner before skill editor`

Prefer split commits if terminology rename touches many files before functional planner wiring.

---

## Risks and mitigations

### Risk: planner LLM increases dry-run cost/latency

Mitigation: one global planner call only. Keep digest compact and capped.

### Risk: planner skips valid improvements

Mitigation: artifact records skipped reasons; future calibration can learn from user corrections. Prompt should prefer `run_editor` for low-risk local skill patches with attached evidence.

### Risk: planner over-selects and editor mutates too much

Mitigation: editor remains bounded by official skill tools and must stop on stale/conflict/unsafe. Planner `run_editor` is not direct mutation permission; it is permission to ask editor to inspect and patch if still valid.

### Risk: terminology rename breaks config unexpectedly

Mitigation: plugin is local/unreleased; prefer current-only schema. Before implementation, inspect live `config.yaml` and update docs. If a live config still has `model.judge`, decide whether to migrate the local file explicitly in the implementation session rather than adding permanent aliases.

### Risk: active evaluator assets still use proposal/judge terms

Mitigation: update active docs/assets in the same slice where practical. If file/path rename is too large, keep file paths but update content and create a follow-up rename plan.

---

## Acceptance criteria

- Active external/internal terminology uses `planner` for the global improvement decision layer.
- Config default roles are `model.planner`, `model.editor`, `model.evaluator`.
- `improve --dry-run` runs analyzer + global planner and does not run editor.
- Dry-run output shows selected skills, rationale, intended change, and evidence count.
- Mutating `improve` runs editor only for planner decisions with `decision=run_editor`.
- Evidence-less candidates are not marked `accepted`; they are `skip_no_evidence` or equivalent planner skips.
- LLM-facing tool result remains compact and full planner payload stays in artifact / CLI `--json`.
- GEPA/DSPy remain under `calibrate` as planner/editor prompt/rubric/evaluator optimization.
- Full tests and runtime smoke pass.
---

## Implementation result

**Status:** completed.

Implemented in this pass:

- `model.planner` is the canonical decision role for proposal scoring and global skill planning.
- Added `hermes_self_improvement/planner.py` with compact planner digest construction, JSON schema normalization, deterministic fallback, and Hermes auxiliary LLM routing.
- Changed `run_skill_improvement_step()` to run `analyzer/evidence builder -> global planner -> per-skill editor`.
- Dry-run now runs the planner and records `run_editor_preview` decisions without executing editor mutation.
- Mutating runs execute editor tasks only for planner `run_editor` decisions, passing `change_intent`, `editor_instructions`, and selected `evidence_ids` into the editor task.
- CLI summary and agent-facing tool result now expose compact planner counts while preserving full planner payload in the run artifact.
- GEPA/DSPy remain scoped to `calibrate` / evaluator-prompt-rubric optimization.

Verification:

```text
PY=${PYTHON:-.venv/bin/python}; $PY -m pytest tests -q
280 passed, 2 skipped
```
