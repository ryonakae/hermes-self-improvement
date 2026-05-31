# Memory Placement LLM Judgment Unblocking Implementation Plan

Status: **implemented and verified** (2026-05-31).

Verification:

- Removed program-owned `likely_targets` weights from all `memory_placement_candidate` evidence.
- Added bounded `candidate_target_skills` context hints for `likely_memory_to_skill` placement rows; hints are prompt context, not commands.
- Added bounded raw planner / normalization diagnostics to planner results and run artifacts via `step_decisions.planner_diagnostics`.
- Added `step_decisions.memory_placement_target_hints` so artifacts expose derived target-skill context without dumping full planner digest.
- Full validation passed: `py_compile`, `932 passed, 2 skipped`, `git diff --check` clean.
- Dogfood dry-run artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260531T075000Z.json`; `dry_run=true`, `target_changed=false`, placement candidates `25`, candidates with `likely_targets=0`, target-hint rows `3`, planner diagnostics present, `planner_decision_count=25`, `default_defer_count=0`.
- Non-goals preserved: no new gates, approval queues, confidence thresholds, canaries, deterministic forced routing, or execution-safety loosening.

**Goal:** Let the planner LLM make USER/MEMORY/Skill placement judgments from coherent evidence instead of being biased by contradictory program-owned target weights or opaque normalization.

**Architecture:** Keep existing one Planner / one Knowledge Editor flow and official tool-mediated execution. Remove misleading placement `likely_targets` weights, surface candidate skill matches as judgment material, and persist raw planner output/normalization diagnostics so we can distinguish LLM judgment from program-side filtering. This is not a new safety layer and does not add approval queues, confidence gates, canaries, or deterministic forced routing.

**Tech Stack:** Python, pytest, existing `hermes-self-improvement` evidence/planner runtime/artifact pipeline.

---

## Current diagnosis

Latest dry-run artifact reviewed:

- `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260531T001824Z.json`

Observed issue:

- `likely_memory_to_skill` placement candidates were visible and classified as `procedural_or_operational_workflow`.
- The same evidence carried contradictory `likely_targets`:
  - `memory: 0.7`
  - `skill: 0.3`
- The priority prompt says to choose `memory_to_skill` when an exact editable target skill is known, but priority candidate rows do not include candidate target skills.
- The final artifact shows `planner_omitted_candidate_default_defer`, but raw planner output and normalization/drop diagnostics are not easy to inspect from the run artifact.

Ryo's direction:

1. Remove target weights for memory placement candidates. Do not use program-owned weights to constrain LLM judgment.
2. Add target skill candidate material so the LLM has enough context to decide memory-to-skill naturally.
3. Persist raw planner output / normalization diagnostics to tell whether the LLM omitted a candidate or the program dropped it.

## Non-goals

- Do not add new hard gates, queues, approval modes, confidence thresholds, or canary flows.
- Do not force deterministic `memory_to_skill` based only on program hints.
- Do not loosen execution safety: exact `old_text`, official tools, add-before-remove, and skill-success-before-source-remove remain unchanged.
- Do not route built-in USER/MEMORY placement candidates to external memory in this slice.

## Completion criteria

This plan is complete when:

- `memory_placement_candidate` evidence no longer carries misleading `likely_targets` weights.
- Planner digest/prompt includes candidate target skill material for `likely_memory_to_skill` rows when such material can be derived from existing skill inventory/names.
- Run artifacts expose enough raw planner/normalization diagnostics to classify:
  - LLM omitted candidate;
  - LLM produced candidate but normalization rejected it;
  - LLM produced candidate and it survived as canonical transaction.
- Dry-run remains non-mutating (`target_changed=False`).
- No execution safety behavior is weakened.

---

## Task 1: Remove placement `likely_targets` weights

**Objective:** Stop presenting memory placement candidates as `memory 0.7 / skill 0.3` when their own route hint may say `likely_memory_to_skill`.

**Files:**
- Modify: `hermes_self_improvement/evidence.py`
- Test: existing evidence/planner tests, likely `tests/test_evidence_inventory_candidates.py` or nearest memory placement evidence test.

**Step 1: Write failing test**

Add or update a test that builds memory placement candidates from a MEMORY entry containing procedural/operational markers such as `restart`, `workflow`, `確認`, or `運用`.

Expected assertions:

```python
candidate = collect_memory_placement_candidates(memory_paths)[0]
assert candidate["kind"] == "memory_placement_candidate"
assert candidate["inventory"]["suggested_route"] == "likely_memory_to_skill"
assert "likely_targets" not in candidate or candidate["likely_targets"] == []
```

Also cover a USER→MEMORY candidate and a likely_keep candidate, so the removal is consistent for all placement candidates, not only skill-shaped ones.

**Step 2: Run focused test and verify failure**

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_evidence_inventory_candidates.py -q
```

Expected before implementation: failure showing `likely_targets` still present with memory/skill weights.

**Step 3: Implement minimal change**

In `collect_memory_placement_candidates(...)`, remove this field from placement evidence:

```python
"likely_targets": _targets(("memory", 0.7), ("skill", 0.3)),
```

Do not replace it with new weights. The authoritative placement material should be:

- `inventory.current_store`
- `inventory.suggested_route`
- `inventory.route_reasons`
- `inventory.official_boundary`
- `inventory.old_text`
- candidate target skills from later tasks

**Step 4: Run focused tests**

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_evidence_inventory_candidates.py tests/test_skill_planner.py -q
```

Expected: pass.

---

## Task 2: Add target skill candidate material to placement digest

**Objective:** Give the planner LLM natural judgment material for `memory_to_skill` without forcing the decision.

**Files:**
- Modify: `hermes_self_improvement/planner_runtime.py`
- Modify if needed: `hermes_self_improvement/prompts.py`
- Test: `tests/test_skill_planner.py`

**Design:**

For each `memory_placement_candidate` with `suggested_route=likely_memory_to_skill`, derive bounded `candidate_target_skills` from existing local/editable skill inventory already present in the planner digest. This should be a context hint, not a routing command.

Candidate matching can be simple and transparent:

- compare old_text/summary tokens to editable skill names and descriptions;
- use existing editable skill list already exposed in the planner digest;
- prefer exact name/domain token overlap such as:
  - Gateway text → `hermes-gateway-and-sessions`
  - Hindsight text → `hindsight-operations`
  - hermes-lcm text → `hermes-lcm`
  - live context text → `hermes-live-context-design`
- cap at 3 candidates per placement item;
- include `match_reason` such as `name_token_overlap` or `description_token_overlap`.

Do not make this a safety gate. If no match exists, keep `candidate_target_skills=[]` and let the LLM defer.

**Step 1: Write failing test**

In `tests/test_skill_planner.py`, build a planner digest fixture containing:

- one placement candidate with old_text mentioning `Gateway`;
- editable skills including `hermes-gateway-and-sessions` and an unrelated skill.

Assert the rendered planner prompt includes:

```text
candidate_target_skills=[hermes-gateway-and-sessions]
```

or equivalent structured material in the priority candidate row.

Also assert the prompt still says candidate target skills are hints, not commands.

**Step 2: Implement digest helper**

Add a small helper in `planner_runtime.py`, for example:

```python
def _candidate_target_skills_for_memory_text(text: str, editable_skills: list[dict[str, Any]]) -> list[dict[str, str]]:
    ...
```

Keep it deterministic, bounded, and explainable. No LLM call here.

**Step 3: Wire into `_memory_placement_candidates_digest(...)`**

`_memory_placement_candidates_digest(...)` currently only receives `evidence_pack`. If editable skills are not available there, either:

- pass the editable skill inventory into the helper after the main digest is assembled; or
- enrich the prompt renderer from `digest.knowledge_maintenance.editable_skills`.

Prefer the smaller code path that avoids broad refactor. The result should be present in the prompt and artifact-facing digest.

**Step 4: Render in prompt**

In `prompts.py`, include candidate target skills in both:

- the priority `likely_memory_to_skill` section;
- the full memory placement list if compact enough.

Example wording:

```text
candidate_target_skills=[hermes-gateway-and-sessions(name_token_overlap)]
These are context hints for the LLM, not commands. If none is a good semantic fit, defer with reason=memory_to_skill_target_unclear.
```

**Step 5: Run focused tests**

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_skill_planner.py -q
```

Expected: pass.

---

## Task 3: Persist raw planner output and normalization diagnostics

**Objective:** Make it observable whether a candidate was omitted by the LLM, rejected during normalization, or accepted as a canonical transaction.

**Files:**
- Modify: `hermes_self_improvement/planner_runtime.py`
- Modify: `hermes_self_improvement/runner_steps.py` if artifact assembly happens there
- Test: `tests/test_skill_planner.py` or `tests/test_runner_steps.py`

**Step 1: Locate current raw planner lifecycle**

Inspect where `run_planner_runtime(...)` receives and parses the model output. Identify:

- raw text before JSON extraction;
- parsed planner payload before normalization;
- normalized `knowledge_transactions`;
- rejected or altered transactions.

Do not dump full prompts or huge raw responses into compact Slack/tool output. This belongs in run artifacts only.

**Step 2: Add diagnostics object**

Add a bounded artifact field, for example:

```json
"planner_output_diagnostics": {
  "raw_response_preview": "... bounded ...",
  "raw_response_sha256": "...",
  "parsed_transaction_count": 12,
  "normalized_transaction_count": 10,
  "normalization_drops": [
    {
      "source_evidence_id": "memory_place_...",
      "transaction_kind": "memory_to_skill",
      "reason": "transaction_missing_target_id"
    }
  ]
}
```

If raw response is already unavailable by this layer, preserve parsed-pre-normalization transactions and add a follow-up note in the plan; do not over-refactor.

**Step 3: Add candidate-level classification**

For memory placement actionability, distinguish:

- `planner_omitted_candidate_default_defer`
- `planner_emitted_but_normalization_rejected`
- `planner_emitted_and_selected`

This is diagnostics only. Do not use it to force apply.

**Step 4: Write tests**

Add fixtures where the raw planner payload contains a `memory_to_skill` transaction missing `target_skill`.

Expected:

- final transaction may be blocked/deferred as today;
- diagnostics say normalization rejected it, not omitted;
- a truly absent candidate still says omitted.

**Step 5: Run focused tests**

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_skill_planner.py tests/test_runner_steps.py -q
```

Expected: pass.

---

## Task 4: Dry-run dogfood and compare against known artifacts

**Objective:** Verify the changes improve judgment inputs and observability without adding mutation or extra safety gates.

**Files:**
- No code changes expected unless diagnostics reveal a bug.
- Update: this plan, `.hermes/plans/README.md`, and parent roadmap after results.

**Step 1: Run full validation**

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
git diff --check
```

Expected: all pass.

**Step 2: Run source dry-run**

Run:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -c 'import sys; from hermes_self_improvement.cli import main; sys.argv=["hermes-self-improvement","improve","--dry-run","--since-hours","24","--json"]; main()'
```

Expected:

- `dry_run=true`
- `target_changed=false`
- placement candidates still visible
- `likely_memory_to_skill` candidates no longer carry contradictory memory-heavy weights
- priority candidate rows include candidate target skills when derivable
- artifact contains raw/normalization diagnostics

**Step 3: Compare with baseline artifacts**

Compare against:

- success-shaped baseline: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260530T222529Z.json`
- problematic latest baseline: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260531T001824Z.json`

Report:

- memory_to_skill count
- placement_move count
- `planner_decision_count`
- `default_defer_count`
- whether any remaining default defer is true LLM omission or normalization drop

Do not claim success from one good dry-run alone. Record whether this improved inputs/diagnostics and whether planner behavior still varies.

---

## Task 5: Documentation and commit boundary

**Objective:** Make future sessions understand the corrected boundary: LLM judgment is primary; program hints must not contradict it.

**Files:**
- Modify: `.hermes/plans/README.md`
- Modify: `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`
- Possibly create/update skill reference after implementation if the workflow is proven useful.

**Step 1: Update plan status**

At the end of implementation, add a status note to this file with:

- tests run;
- dry-run artifact path;
- whether target weights were removed;
- whether target skill hints appeared;
- whether raw/normalization diagnostics appeared;
- remaining variance if any.

**Step 2: Update plan index and roadmap**

Update `.hermes/plans/README.md` current source of truth and the long-term roadmap current follow-up list.

**Step 3: Commit and push only after implementation is requested and verified**

Commit message suggestion:

```bash
git add hermes_self_improvement tests .hermes/plans
 git commit -m "fix: unblock llm memory placement judgment"
 git push
```

Do not commit this planning-only document unless Ryo asks for docs commit or approves implementation.

---

## Risk notes

- Removing `likely_targets` may affect aggregate evidence summary counts if any code assumes all evidence has target weights. Tests should catch this. If a summary helper requires the key, represent missing target weights as `target_unweighted` in summary code rather than reintroducing weights.
- Candidate target skill matching must remain a hint. It should not silently create executable `memory_to_skill` transactions without LLM selection.
- Raw planner diagnostics must be bounded/redacted and artifact-only, not dumped into Slack/tool compact summaries.
