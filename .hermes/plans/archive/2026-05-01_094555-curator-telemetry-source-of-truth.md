# Curator Telemetry Source-of-Truth Implementation Plan

> **Status:** completed 2026-05-01. Archived after implementation; `.hermes/plans/README.md` is the current index.

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Make `hermes-self-improvement` actually use Curator/Hermes skill telemetry and lifecycle state as the skill candidate source-of-truth, while using plugin hook evidence only for high-resolution context Curator cannot collect; also strengthen memory runner input with provider recall/search related-memory context.

**Architecture:** Keep the four-surface runner (`improve`, `calibrate`, `report`, `status`) and existing bounded mutation backends. Add a read-only Curator telemetry adapter that produces normalized skill candidate records, merge those records into evidence packs, and update runner steps to use normalized candidates instead of filesystem-derived target guesses. Memory changes are an input-context enhancement only: no memory lifecycle, no full memory sweep, no direct memory file/database edits.

**Tech Stack:** Python, pytest, Hermes plugin APIs, Curator usage/lifecycle files or Hermes registry helpers where available, existing `skill_manage`/memory/provider tool-mediated mutation paths.

---

## Current context

Repo: `/Users/ryo.nakae/.hermes/plugins/hermes-self-improvement`

Current state checked before writing this plan:

```text
## main...origin/main
hermes self-improvement status: OK
plugin enabled: True
mutation backend: available
DSPy available: True
Curator compatibility:
- skill telemetry source: Hermes Curator
- hook mode: observation_only
```

Current implemented baseline from `.hermes/plans/README.md`:

- Primary CLI surface: `improve / calibrate / report / status`.
- Primary tool surface: `self_improvement_improve / self_improvement_calibrate / self_improvement_report / self_improvement_status`.
- `improve` and `calibrate` mutate by default; `--dry-run` is preview.
- Legacy `plan / apply / rollback / outcome`, `--execute`, item/hash flags, and `self_improvement_record_outcome` are removed.
- Skill mutation is bounded to official skill tools.
- Memory mutation is bounded to memory/provider tools.

Relevant current files:

- `hermes_self_improvement/evidence.py`
  - Has `build_evidence_pack(..., curator_telemetry=None)` but currently only stores `curator_telemetry_summary` and does not use real telemetry as the candidate source-of-truth.
  - Ignores successful `skill_view` / `skills_list` as `curator_redundant`, which is correct.
- `hermes_self_improvement/runner_steps.py`
  - `run_skill_improvement_step()` currently extracts `skill_name` from individual evidence items.
  - `run_memory_improvement_step()` already executes provider-compatible memory operations, but does not enrich memory decisions by fetching related existing memories via recall/search.
- `hermes_self_improvement/skill_snapshot.py`
  - Enforces mutable local skill root safety, but this is still a filesystem/root safety gate, not a Curator/Hermes registry candidate source-of-truth.
- `tests/test_evidence_pack.py`, `tests/test_runner_steps.py`, `tests/test_skill_snapshot.py`, `tests/test_report_integration.py`, `tests/test_plugin_tools.py`, `tests/test_cli_surface.py`
  - Existing likely test homes for this work.

## Decided design

### Skill candidate source-of-truth

Use Curator/Hermes registry + Curator usage/lifecycle state as the source-of-truth for skill candidates.

Candidate set:

```text
include:
- active agent-created local mutable skills
- stale agent-created local mutable skills

exclude:
- pinned
- archived
- built-in
- bundled
- hub-installed
- plugin-bundled
- external_dirs
- missing / ambiguous provenance
```

Execution must still revalidate provenance and mutability immediately before any mutation.

### Hook evidence role

Hook data supplements Curator, it does not duplicate Curator.

Curator/Hermes owns:

```text
- skill usage/view/patch counts
- last used/viewed timestamps
- active/stale/archived lifecycle state
- pinned state
- agent-created/local/hub/bundled/external provenance where available
```

Plugin hooks own high-resolution context Curator does not collect:

```text
- tool failure context
- memory operation / memory unavailable signals
- user corrections and review/session outcomes
- subagent outcomes
- LLM/API failure metadata
- user reactions to report/dry-run/run results
```

### Memory runner related-memory context

The memory runner should keep the current evidence-driven/provider-compatible execution path, but enrich decisions with provider recall/search context when there is a relevant trigger.

Triggers:

```text
- correction evidence
- contradiction evidence
- repeated explanation/preference evidence
- memory tool failure evidence
- memory unavailable evidence
```

Non-goals:

```text
- no full memory lifecycle
- no full memory sweep
- no direct built-in memory file edit
- no provider DB/internal edit
- no rollback feature reintroduction
```

### Additional recovered decisions from the 02:51+ dig

These decisions were made before this plan was written and must not be lost during implementation:

```text
Curator runtime assumption:
- When this plugin runs, built-in Curator is disabled or paused.
- Therefore `improve` must cover the Curator lifecycle work it depends on, rather than assuming Curator will run beside it.

Skill lifecycle:
- active skills are candidates.
- stale skills are candidates.
- pinned skills are excluded.
- archived skills are excluded from normal candidates, restore candidates, and duplicate-prevention context; match Curator behavior rather than inventing a separate archive search path.
- `improve` should run the same automatic lifecycle transitions Curator would run, preferably via Hermes/Curator helpers instead of reimplementing them.

Skill provenance:
- Follow Curator/Hermes provenance boundaries.
- Agent-created local mutable skills are in scope.
- built-in, bundled, hub-installed, plugin-bundled, external-dir, pinned, archived, and ambiguous-provenance skills are out of scope.

DSPy/GEPA responsibility:
- DSPy/GEPA is not an immediate mutation gate for every edit.
- It is the mechanism for improving the judgment loop over time.
- The judgment loop has three layers: classifier, editor, evaluator.
- `improve` performs action and records evidence/outcome material.
- `calibrate` improves the judgment machinery from accumulated evidence/outcome cases.

Outcome signals:
- Strong signals: explicit user corrections and review outcomes.
- Weak signals: recurrence reduction, repeated failures/corrections, later skill use, memory contradiction/no-op evidence, and operation results.
```

---

## Task 1: Add normalized Curator telemetry models and loader

**Objective:** Provide a small read-only module that normalizes Curator/Hermes skill telemetry into explicit candidate records without invoking mutation tools.

**Files:**

- Create: `hermes_self_improvement/curator_telemetry.py`
- Test: `tests/test_curator_telemetry.py`

**Step 1: Write failing tests for normalization**

Add tests for a pure function such as `normalize_skill_candidate(raw, *, mutable_roots=None)` or `build_skill_candidates(raw_telemetry, registry=None)`.

Test cases:

- active agent-created local mutable skill is included.
- stale agent-created local mutable skill is included.
- pinned skill is excluded with reason `pinned`.
- archived skill is excluded with reason `archived`.
- bundled / hub / plugin-bundled / external skills are excluded with reasons.
- missing or ambiguous provenance is excluded fail-closed.

Expected candidate shape:

```python
{
    "name": "example-skill",
    "state": "active",  # active|stale
    "provenance": "curator_agent_created",  # Curator-eligible local skill; do not broaden to arbitrary external/user dirs
    "mutable": True,
    "source": "curator",
    "usage": {
        "view_count": 3,
        "use_count": 1,
        "patch_count": 0,
        "last_viewed_at": "...",
        "last_used_at": "...",
    },
    "reasons": ["active", "local_mutable", "agent_created"],
}
```

Expected rejected shape:

```python
{
    "name": "example-skill",
    "decision": "rejected",
    "reason": "pinned",
    "source": "curator",
}
```

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_curator_telemetry.py -q
```

Expected: FAIL because module/functions do not exist.

**Step 2: Implement minimal pure normalization**

Create `hermes_self_improvement/curator_telemetry.py` with pure helpers first. Do not read files yet.

Suggested public API:

```python
def normalize_curator_skill_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Return included candidates plus rejected records with reasons."""
```

Return shape:

```python
{
    "available": True,
    "source": "curator",
    "candidates": [...],
    "rejected": [...],
    "summary": {
        "candidate_count": 2,
        "rejected_count": 5,
        "rejected_by_reason": {"pinned": 1, "archived": 1},
    },
}
```

**Step 3: Run normalization tests**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_curator_telemetry.py -q
```

Expected: PASS.

**Step 4: Commit slice**

```bash
git add hermes_self_improvement/curator_telemetry.py tests/test_curator_telemetry.py
git commit -m "feat(self-improvement): normalize curator skill telemetry"
```

---

## Task 2: Read real Curator/Hermes telemetry safely

**Objective:** Add a read-only collector that discovers Curator/Hermes skill usage/lifecycle data from supported runtime files/helpers, returning `available: false` rather than guessing when data is missing.

**Files:**

- Modify: `hermes_self_improvement/curator_telemetry.py`
- Test: `tests/test_curator_telemetry.py`
- Possibly inspect only, do not modify: Hermes core Curator files such as `agent/curator.py`, `tools/skill_usage.py`, and skill registry helpers in the active Hermes runtime checkout.

**Step 1: Write tests for safe missing-data behavior**

Test with temporary `HERMES_HOME` containing no Curator files.

Expected:

```python
{
    "available": False,
    "source": "curator",
    "candidates": [],
    "rejected": [],
    "summary": {"candidate_count": 0, "rejected_count": 0},
    "reasons": ["curator_telemetry_missing"],
}
```

**Step 2: Write tests for fixture telemetry files**

Use temp files representing current Curator usage/lifecycle shape. Keep fixture format narrow and documented in the test. The loader should tolerate absent optional fields.

Test:

- usage/lifecycle data is parsed.
- records are passed through the normalization from Task 1.
- corrupt JSON returns `available: false` with reason `curator_telemetry_unreadable`, not an exception.

**Step 3: Implement read-only collector**

Add a function such as:

```python
def load_curator_telemetry(config: dict[str, Any] | None = None) -> dict[str, Any]:
    ...
```

Rules:

- Read only.
- No mutation, no lifecycle transitions in this task.
- Prefer Hermes/Curator official helper APIs if importable and stable.
- If falling back to files, keep paths behind small helpers and tests.
- Fail closed on missing/unrecognized/corrupt data.
- Do not infer bundled/hub/external status from path alone when registry/provenance is missing; mark rejected as `ambiguous_provenance`.

**Step 4: Run focused tests**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_curator_telemetry.py -q
```

Expected: PASS.

**Step 5: Commit slice**

```bash
git add hermes_self_improvement/curator_telemetry.py tests/test_curator_telemetry.py
git commit -m "feat(self-improvement): load curator telemetry read-only"
```

---

## Task 3: Merge Curator telemetry into evidence packs as candidate source-of-truth

**Objective:** Ensure `build_evidence_pack()` carries normalized Curator candidate data, while hook events remain high-resolution supplemental evidence.

**Files:**

- Modify: `hermes_self_improvement/evidence.py`
- Modify or add tests: `tests/test_evidence_pack.py`

**Step 1: Write failing evidence-pack tests**

Add tests that pass a normalized `curator_telemetry` payload to `build_evidence_pack()` and assert:

- `pack["curator_telemetry_summary"]` includes candidate/rejected counts.
- `pack["skill_candidates"]` or equivalent explicit field contains included Curator candidates.
- rejected candidates and reasons are preserved in an audit field, e.g. `pack["rejected_skill_candidates"]` or inside `curator_telemetry_summary`.
- successful `skill_view` and `skills_list` events remain ignored as `curator_redundant`.
- hook-only failures still become evidence.

Expected pack-level shape:

```python
{
    "skill_candidates": [...],
    "curator_telemetry_summary": {
        "available": True,
        "candidate_count": 2,
        "rejected_count": 3,
        "rejected_by_reason": {"pinned": 1, "archived": 1, "external": 1},
    },
}
```

**Step 2: Implement evidence-pack merge**

Update `build_evidence_pack()` so Curator telemetry is not just a raw summary blob. It should be a structured source for skill candidates.

Rules:

- Do not create fake evidence items for ordinary Curator usage stats.
- Do not duplicate Curator usage as hook evidence.
- Keep hook evidence in `evidence[]`.
- Keep Curator candidate data in a separate candidate field.
- Use `ignored_reason: curator_redundant` for successful skill usage tool calls as today.

**Step 3: Run focused tests**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_evidence_pack.py tests/test_analysis_reclassification.py -q
```

Expected: PASS.

**Step 4: Commit slice**

```bash
git add hermes_self_improvement/evidence.py tests/test_evidence_pack.py tests/test_analysis_reclassification.py
git commit -m "feat(self-improvement): add curator skill candidates to evidence packs"
```

---

## Task 4: Use Curator candidates in the skill improvement runner

**Objective:** Stop relying on individual hook evidence to name target skills. The skill runner should iterate Curator-selected candidates and attach relevant hook evidence to each candidate.

**Files:**

- Modify: `hermes_self_improvement/runner_steps.py`
- Possibly modify: `hermes_self_improvement/mutation_agent.py`
- Test: `tests/test_runner_steps.py`

**Step 1: Write failing runner tests**

Cases:

1. When evidence pack has a Curator candidate and no hook evidence, dry-run creates a skill agent task for the candidate.
2. When evidence pack has hook evidence referencing a candidate skill, that evidence is attached to the candidate task.
3. Hook evidence referencing a non-candidate skill is rejected/skipped with reason `skill_not_in_curator_candidates`.
4. Pinned/archived/external rejected candidates do not produce tasks.
5. Mutating path revalidates target provenance before calling backend.

Expected dry-run decision shape:

```python
{
    "skill": "example-skill",
    "decision": "accepted",
    "reason": "dry_run_would_run_skill_agent",
    "candidate_source": "curator",
    "candidate_state": "active",
    "evidence_ids": [...],
    "task": {...},
}
```

**Step 2: Implement candidate-driven skill task construction**

Update `run_skill_improvement_step()`:

- Read `evidence_pack["skill_candidates"]`.
- Group hook evidence by target skill only when it matches a candidate.
- For each candidate, build a task containing:
  - candidate metadata
  - usage/lifecycle summary
  - attached hook evidence
  - explicit constraints from current task builder
- If no candidates exist, return `no_skill_candidates` or similar, not `no_skill_evidence`.

**Step 3: Revalidation boundary**

Before mutation, ensure the backend/mutation agent receives candidate metadata and still performs existing snapshot/provenance checks. Do not remove `skill_snapshot.py` safety.

Expected fail-closed reasons:

```text
skill_not_in_curator_candidates
skill_candidate_rejected
skill_provenance_changed
skill_no_longer_mutable
```

Only implement reasons that the code can genuinely detect in this slice; do not invent unreachable branches.

**Step 4: Run focused tests**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_runner_steps.py tests/test_mutation_agent.py tests/test_skill_snapshot.py -q
```

Expected: PASS.

**Step 5: Commit slice**

```bash
git add hermes_self_improvement/runner_steps.py hermes_self_improvement/mutation_agent.py tests/test_runner_steps.py tests/test_mutation_agent.py
git commit -m "feat(self-improvement): drive skill runner from curator candidates"
```

---

## Task 5: Add related-memory recall/search context to the memory runner

**Objective:** Enrich memory improvement decisions with related existing memory context when triggered by hook evidence, without creating a memory lifecycle or sweeping all memory.

**Files:**

- Modify: `hermes_self_improvement/mutation_policy.py`
- Modify: `hermes_self_improvement/runner_steps.py`
- Possibly create: `hermes_self_improvement/memory_context.py`
- Test: `tests/test_runner_steps.py`
- Test: `tests/test_mutation_policy.py`

**Step 1: Write provider capability tests**

Add tests for a helper such as `build_related_memory_lookup_context(provider, evidence)`.

Cases:

- Hindsight provider exposes recall/search context through `hindsight_recall` or `hindsight_reflect` where appropriate.
- Built-in memory either receives full available context only if supplied by config/test fixture, or marks lookup unavailable without direct file reads.
- Providers without recall/search return `lookup_available: false` with a clear reason.
- Sensitive/secret-looking evidence does not get echoed into unsafe query strings if current redaction helpers can be reused.

**Step 2: Write runner tests with injected fake lookup function**

Do not call live memory tools in tests. Inject a fake lookup function through config, e.g. `_memory_lookup_fn` or `_memory_provider_tool_fn` wrapper.

Cases:

- correction evidence triggers lookup and includes related memories in dry-run decision context.
- plain successful memory add evidence without correction/contradiction does not trigger lookup unnecessarily.
- lookup failure does not block all memory operation execution; it records `related_memory_lookup.status = failed` and continues only if the operation is otherwise safe.
- provider without lookup records `related_memory_lookup.status = unavailable`.

Expected decision context:

```python
{
    "related_memory_lookup": {
        "status": "completed",
        "provider": "hindsight",
        "query": "...",
        "result_count": 2,
        "results": [...],
    },
    "context": {... existing mutation context ...},
}
```

**Step 3: Implement lookup helper**

Keep it bounded:

- Only call provider recall/search tools through injected/provider tool functions.
- Never read built-in memory files directly.
- Never call provider DB internals.
- If no supported lookup exists, return unavailable.
- Keep query construction short and based on evidence preview/correction reason.

**Step 4: Attach lookup context to memory operation context**

Update `run_memory_improvement_step()` so related-memory context is passed into the decision artifact and, where the existing mutation worker supports it, into the LLM/backend context. Do not change low-level provider operation semantics unless needed.

**Step 5: Run focused tests**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_runner_steps.py tests/test_mutation_policy.py -q
```

Expected: PASS.

**Step 6: Commit slice**

```bash
git add hermes_self_improvement/runner_steps.py hermes_self_improvement/mutation_policy.py hermes_self_improvement/memory_context.py tests/test_runner_steps.py tests/test_mutation_policy.py
git commit -m "feat(self-improvement): enrich memory runner with related context"
```

---

## Task 6: Wire telemetry loading and Curator lifecycle transitions into `improve` runner

**Objective:** Ensure real `improve` and `improve --dry-run` runs apply/read Curator lifecycle state, load Curator telemetry, build candidate-aware evidence packs, run candidate-driven skill/memory steps, and write artifacts that distinguish Curator-derived data from hook-derived evidence.

**Files:**

- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/evidence.py` if additional helpers are needed
- Modify: `hermes_self_improvement/runner_steps.py` if orchestration lives there
- Modify: `hermes_self_improvement/curator_telemetry.py` if lifecycle helpers belong there
- Test: `tests/test_cli_surface.py`
- Test: `tests/test_report_integration.py`

**Step 1: Write failing CLI/orchestration tests**

Use temp runtime state and injected telemetry/lifecycle loader.

Assert `improve --dry-run --json` or the direct runner function includes:

```json
{
  "curator_lifecycle": {
    "status": "dry_run",
    "transitions_checked": true
  },
  "curator_telemetry": {
    "available": true,
    "candidate_count": 1,
    "rejected_count": 2
  },
  "evidence_pack": {
    "skill_candidates": [...]
  },
  "steps": {
    "skill": {"status": "completed"},
    "memory": {"status": "..."}
  }
}
```

Also test missing telemetry:

- status/report should not crash.
- skill step should not mutate arbitrary filesystem-derived skills when telemetry is unavailable.
- output should say `curator_telemetry_missing` or equivalent.

**Step 2: Implement lifecycle + telemetry orchestration**

In the improve runner:

1. Run or preview Curator automatic lifecycle transitions first.
   - Mutating `improve`: run the same lifecycle transition path Curator would run.
   - `improve --dry-run`: preview/report what would be checked or transitioned without mutation.
   - Prefer Hermes/Curator helper APIs over reimplementation.
2. Load Curator telemetry read-only after lifecycle state is current.
3. Pass normalized telemetry into `build_evidence_pack()`.
4. Run skill step from `skill_candidates`.
5. Run memory step with related-memory lookup context.
6. Write run artifact.

Do not run calibration/GEPA optimization inside `improve`; that remains `calibrate` responsibility per design. `improve` may record outcome/eval-case material for later `calibrate`.

**Step 3: Run focused tests**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_cli_surface.py tests/test_report_integration.py tests/test_runner_steps.py tests/test_evidence_pack.py -q
```

Expected: PASS.

**Step 4: Commit slice**

```bash
git add hermes_self_improvement/cli.py hermes_self_improvement/evidence.py hermes_self_improvement/runner_steps.py hermes_self_improvement/curator_telemetry.py tests/test_cli_surface.py tests/test_report_integration.py tests/test_runner_steps.py tests/test_evidence_pack.py
git commit -m "feat(self-improvement): use curator telemetry during improve"
```

---

## Task 7: Verify `calibrate` consumes accumulated outcome signals for the three-layer judgment loop

**Objective:** Ensure the plan explicitly preserves the dig decision that `calibrate`, not `improve`, owns DSPy/GEPA judgment-loop improvement for classifier, editor, and evaluator using accumulated outcome signals.

**Files:**

- Modify if needed: `hermes_self_improvement/calibration.py`
- Modify if needed: `hermes_self_improvement/dspy_program.py`
- Modify if needed: `hermes_self_improvement/gepa_adapter.py`
- Test: `tests/test_calibration.py`
- Test: `tests/test_dspy_program.py`
- Test: `tests/test_gepa_eval_assets.py`

**Step 1: Audit current calibration coverage**

Before coding, inspect existing calibration tests and implementation to determine whether classifier/editor/evaluator and outcome-signal handling are already implemented.

If already implemented, add only regression tests or documentation assertions needed to lock the decision.

**Step 2: Add/adjust tests for the decided responsibility split**

Assert:

- `improve` does not run GEPA/DSPy optimization.
- `improve` records outcome/evidence material usable by calibration.
- `calibrate` reads accumulated correction/outcome/disagreement/regression evidence.
- classifier, editor, and evaluator are represented in calibration artifacts or schema.
- regression gate failure does not promote active evaluator/prompt changes.

**Step 3: Implement only missing gaps**

Do not broaden target scope beyond skill, memory, scorer/evaluator judgment. Keep runtime-private eval cases under runtime state, not repo-tracked eval assets.

**Step 4: Run focused tests**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_calibration.py tests/test_dspy_program.py tests/test_gepa_eval_assets.py -q
```

Expected: PASS.

**Step 5: Commit slice**

```bash
git add hermes_self_improvement/calibration.py hermes_self_improvement/dspy_program.py hermes_self_improvement/gepa_adapter.py tests/test_calibration.py tests/test_dspy_program.py tests/test_gepa_eval_assets.py
git commit -m "feat(self-improvement): lock calibrate judgment-loop responsibilities"
```

---

## Task 8: Update report/status visibility

**Objective:** Make user-facing output show what came from Curator versus hooks, without dumping noisy raw telemetry.

**Files:**

- Modify: `hermes_self_improvement/cli.py`
- Modify: report helper module if separate
- Test: `tests/test_report_integration.py`
- Test: `tests/test_plugin_tools.py`

**Step 1: Write report/status tests**

Assert human-readable report/status includes concise sections:

```text
Curator telemetry:
- available: yes/no
- skill candidates: N active, M stale
- rejected: pinned X, archived Y, external Z

Hook evidence:
- tool failures: N
- memory evidence: N
- correction evidence: N

Memory related context:
- lookups attempted: N
- completed/unavailable/failed counts
```

For JSON output, assert machine-readable fields exist and raw sensitive content is not overexposed.

**Step 2: Implement concise output**

Rules:

- Human report: counts + short reasons, not full raw telemetry.
- JSON report: structured counts and artifact paths.
- Status: readiness and last-run summary only.
- Keep `status` lightweight.

**Step 3: Run focused tests**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_report_integration.py tests/test_plugin_tools.py -q
```

Expected: PASS.

**Step 4: Commit slice**

```bash
git add hermes_self_improvement/cli.py tests/test_report_integration.py tests/test_plugin_tools.py
git commit -m "feat(self-improvement): report curator and hook evidence sources"
```

---

## Task 9: Documentation and operational skill sync

**Objective:** Keep repo docs and bundled operations guidance aligned with the new source-of-truth behavior.

**Files:**

- Modify: `README.md`
- Modify: `skills/operations/SKILL.md`
- Modify: `skills/operations/references/architecture.md` if present/relevant
- Modify: `.hermes/plans/README.md`
- Test: docs-related tests if any relevant, commonly `tests/test_scheduled_execution_docs.py`

**Step 1: Update docs**

Document:

- Curator/Hermes telemetry is the skill candidate source-of-truth.
- Hook evidence only supplements Curator with high-resolution context.
- Built-in Curator is assumed disabled or paused when this plugin runs.
- `improve` runs/previews the same Curator automatic lifecycle transitions before reading telemetry.
- Skill candidates are active/stale agent-created local mutable only.
- Pinned/archived/bundled/hub/plugin/external are excluded at planning and revalidated before mutation.
- Archived skills are not used as duplicate-prevention or restore candidates; match Curator behavior.
- Memory runner uses related-memory recall/search only when triggered by evidence.
- No memory lifecycle or full memory sweep.
- `calibrate` owns classifier/editor/evaluator judgment-loop improvement from accumulated strong/weak outcome signals.

**Step 2: Update plan index**

When implementation completes, update `.hermes/plans/README.md`:

- Move this plan to archive or mark completed depending on the repo convention used at completion time.
- Add it as the latest completed implementation record.
- Keep completed baseline up to date.

Do not leave this plan marked active after completion.

**Step 3: Run docs tests**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_scheduled_execution_docs.py -q
```

Expected: PASS.

**Step 4: Commit slice**

```bash
git add README.md skills/operations/SKILL.md skills/operations/references/architecture.md .hermes/plans/README.md tests/test_scheduled_execution_docs.py
git commit -m "docs(self-improvement): document curator telemetry source of truth"
```

---

## Task 10: Final verification and push

**Objective:** Verify the full implementation and publish the completed plan slices.

**Step 1: Static and test verification**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py tests/*.py
$PY -m pytest tests -q
hermes self-improvement status
hermes self-improvement improve --dry-run --json | $PY -m json.tool >/tmp/self_improve_dry_run.json
hermes self-improvement report --since-hours 24 --json | $PY -m json.tool >/tmp/self_improve_report.json
hermes self-improvement calibrate --dry-run --json | $PY -m json.tool >/tmp/self_improve_calibrate.json
```

Expected:

- compile passes
- full pytest passes
- status exits 0
- dry-run/report/calibrate JSON parse successfully
- dry-run artifact shows Curator candidate source and hook evidence source separately

**Step 2: Plugin discovery verification if tool schema/registration changed**

Only required if plugin manifest, tool schemas, or tool handlers changed. If not touched, note not required.

```bash
PY=${PYTHON:-python3}
$PY - <<'PY'
from hermes_cli.plugins import discover_plugins, get_plugin_manager
import json

discover_plugins(force=True)
info = [p for p in get_plugin_manager().list_plugins() if p['name'] == 'hermes-self-improvement']
print(json.dumps(info, ensure_ascii=False, indent=2))
PY
```

Expected:

```text
plugin enabled
error null
tools 4
```

**Step 3: Check working tree**

```bash
git status --short
git log --oneline -5
```

Remove accidental artifacts such as untracked `uv.lock` if not intentionally tracked.

**Step 4: Push**

```bash
git push
```

---

## Risks and tradeoffs

### Curator data shape drift

Curator internals may change. Keep the adapter small, covered by tests, and fail closed on unrecognized data instead of guessing.

### Registry/provenance ambiguity

If provenance cannot prove a skill is agent-created/user-created local mutable, reject it. Do not fall back to broad filesystem scans for mutation eligibility.

### Hook/Curator duplication

Do not turn hooks into a second usage telemetry system. Successful ordinary skill views/uses stay Curator-owned and hook-ignored where redundant.

### Memory provider variance

Providers have different recall/search and mutation capabilities. Related-memory context must be optional and provider-compatible. Unsupported lookup should not become a reason to direct-edit memory stores.

### Over-noisy reports

Curator telemetry can be large. Human output should show counts and reasons; raw details belong in artifacts/JSON.

## Open questions for implementation-time discovery

These should be answered by inspecting current Hermes Curator code during Task 2, not by redesigning the product behavior:

1. Exact current path/API for Curator usage/lifecycle state.
2. Whether Hermes registry exposes Curator-eligible agent-created/local provenance directly or whether a plugin-owned normalized field is needed. Do not broaden this to arbitrary external/user dirs.
3. Exact archived/pinned sidecar format used by current Curator.
4. Which memory providers expose callable recall/search tool names in the active Hermes runtime.

If any of these are unavailable, fail closed and document the unavailable state in report/status.

## Acceptance criteria

- `improve --dry-run` shows Curator-derived skill candidates and rejected skill counts.
- `improve` / `improve --dry-run` runs or previews Curator automatic lifecycle transitions before telemetry is consumed.
- Successful skill usage hook events remain ignored as Curator redundant.
- Skill runner only acts on active/stale agent-created local mutable candidates from Curator/Hermes telemetry.
- Pinned/archived/bundled/hub/plugin/external skills are rejected before mutation and revalidated before execution.
- Archived skills are not used as duplicate-prevention or restore candidates.
- Memory runner attaches related-memory lookup context when triggered and available.
- No full memory sweep or memory lifecycle is introduced.
- `calibrate` consumes accumulated correction/outcome/disagreement evidence for the classifier/editor/evaluator judgment loop without running GEPA/DSPy inside `improve`.
- Report/status separate Curator-derived candidate data from hook-derived evidence.
- Full pytest and CLI smoke checks pass.
