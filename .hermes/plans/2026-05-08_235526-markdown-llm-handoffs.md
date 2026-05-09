# LLM-Centered Self-Improvement Handoffs and Placement Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Rework the self-improvement loop so observation collection is deterministic, planner/editor/evaluator assessment is LLM-centered through Markdown context, skill/memory placement decisions are handled in the existing `improve` loop, and mutations are validated by constrained tools plus post-validation rather than fragile enum-like natural-language outcomes.

**Architecture:** Observation collection stays deterministic and writes manifests, evidence, ids, hashes, target metadata, capacity diagnostics, and safety flags as program-owned state. Planner, editor, and evaluator consume Markdown reports/briefs and write Markdown notes; the plugin must not parse LLM-authored Markdown as control state. Skill creation, skill patching, memory add/replace/remove/move, and memory-capacity recovery all stay inside existing `improve` / `calibrate` responsibilities and official tool boundaries. Mutations are validated from tool traces, target guards, and post-validation, not from outcome text alone.

**Tech Stack:** Python, pytest, Hermes auxiliary LLM client, Hermes skill/memory tools, runtime-private artifacts under `${HERMES_HOME:-~/.hermes}/self-improvement/`.

---

## Current context

Recent dogfood exposed several related problems, not only a Markdown/JSON boundary issue:

- Planner/editor LLMs are asked to produce strict JSON-like decisions/results in places where the value is mainly assessment and rationale.
- Skill creation failed with `mutation_agent_result_invalid_outcome` because a worker returned natural-language success text such as `created safe-patch-usage skill ...`, while the parser expected a narrow outcome contract.
- Memory placement is now useful enough to mutate, but built-in memory capacity can block USER→MEMORY moves unless the loop can compact, remove, swap, or route procedural content to skill candidates.
- The improvement loop should learn from tool failures, but not be dominated by them. Skill/memory inventory, repeated user-Hermes preferences, stale memory placement, missing durable procedures, and conversation-derived memory gaps should remain first-class evidence.
- Ryo's intended architecture is:
  - observation/data collection: program
  - planner assessment: LLM
  - editor tool execution: LLM
  - evaluator prompt improvement: LLM
- Therefore, LLM-to-LLM inputs and notes should be Markdown. JSON should be reserved for program-owned manifests, ledgers, tool results, eval case rows, capacity diagnostics, and final summaries that code actually consumes.

Important boundary:

```text
LLM-facing artifacts: Markdown
Program-owned control state: dict/JSON manifest, ids, paths, hashes, guards, capacity diagnostics, ledgers
LLM-authored Markdown: never parsed as authoritative control state
Side effects: official constrained tools only, followed by deterministic validation
```

## Scope decisions carried from the design conversation

- Keep the existing `improve` / `calibrate` split:
  - `improve` is action-oriented self-improvement for skill and memory changes.
  - `calibrate` is assessment/prompt improvement for planner/editor/evaluator overlays.
- Keep semantic decisions simple: `apply / defer / skip / block` at the user-facing level. Do not add a multi-stage apply taxonomy.
- Do not create a separate shelf/inventory lane. Skill/memory inventory, placement review, and coverage gaps are evidence inside the existing `improve` loop.
- Skill mutation targets stay limited to Hermes-created local mutable skills. Built-in, hub-installed, plugin-bundled, external-dir, Hermes core, arbitrary docs/config remain out of scope.
- New skill creation is allowed only when observations show a durable reusable workflow gap and no existing Hermes-created mutable skill fits.
- Target resolver must not decide that a new skill should be created. Its job is to link observations to existing skills/memory when possible, or mark them as unresolved/no-existing-skill-fit for the planner. The planner owns the decision to update an existing skill, create a new skill, route to memory, defer, skip, or block.
- `report` and `improve` should connect through diagnostic signals, not through report-authored mutation decisions. `improve --from-report <artifact>` may use report diagnostics as reference/focus context, but resolver/planner must still make fresh target/action decisions and must not execute report proposals directly.
- Memory mutation should be less conservative for add/replace/move when evidence is clear, but secrets, private content, temporary progress, and weakly evidenced one-off facts remain blocked/deferred.
- If built-in memory is full, try compaction/replace first; if still full, consider removal/swap of lower-value old memory; if the content is procedural, route it to skill patch/create evidence; only then use active external provider fallback when appropriate.
- USER→MEMORY and MEMORY→USER moves should remain add-before-remove unless a newer proof establishes a safer atomic path.

## Non-goals

- Do not add a separate approval queue, new command, new lane, or new apply mode.
- Do not make the plugin accept both JSON and Markdown for the same boundary.
- Do not parse headings like `Decision: apply` from Markdown to drive mutation.
- Do not loosen skill/memory target safety boundaries.
- Do not move GEPA/DSPy into `improve`; `calibrate` remains the evaluator/prompt improvement command.
- Do not remove program-owned JSON artifacts that are used for manifests, ledgers, eval cases, reports, capacity diagnostics, or deterministic validation.
- Do not treat capacity recovery as a blind cleanup job. It is a placement decision: compress, remove/swap, move to skill, or fallback based on value and evidence.
- Do not accept natural-language `outcome` text as proof of mutation success. It is audit text only.
- Do not treat `improve --from-report` as replay or approval. Report diagnostics can focus planning, but they are not executable decisions and must not bypass resolver/planner/target guards.

## Desired end state

The flow should look like this:

```text
program observation collector
  -> run manifest / evidence objects / candidates / diagnostic signals / safety metadata
  -> evidence.md / candidate briefs rendered for LLMs

report command
  -> reads the same observations and diagnostic signals
  -> writes human-facing diagnosis and compact report artifacts
  -> does not author executable mutation decisions

improve --from-report <report-artifact>
  -> reads report diagnostic signals as reference/focus context only
  -> merges them into evidence pack as diagnostic_signal evidence
  -> still runs resolver/planner normally for target/action decisions

target resolver LLM
  -> reads observation evidence plus existing mutable skill inventory
  -> attaches evidence to existing skills when there is a positive fit
  -> marks unmatched observations as unresolved/no-existing-skill-fit with rationale and fit signals
  -> does not decide create-skill, patch, archive, or execute actions

planner LLM
  -> reads Markdown evidence + candidate briefs + resolver attachments/unresolved observations
  -> decides whether to update an existing skill, create a new skill, route to memory, defer, skip, or block
  -> writes planner_notes.md or planner_decisions.md for humans/editor context
  -> may still be normalized to program decisions through a constrained decision tool/object path, not by parsing Markdown

editor LLM
  -> reads Markdown planner notes + candidate briefs + current skill/memory context
  -> calls constrained built-in tools directly: skill_manage / memory / submit_mutation_result
  -> writes editor_notes.md for audit

program validator
  -> validates tool trace, allowed target, expected target name, actual changed/created/deleted skill or memory result
  -> writes ledger/result JSON

evaluator/calibrate LLM
  -> reads Markdown-rendered run report + ledger summaries + eval cases
  -> writes overlay improvement notes / prompt patch rationale
  -> program stores candidate-set metadata and active pointers as JSON
```

Skill/memory placement and capacity recovery should look like this:

```text
new durable fact / workflow gap / stale placement evidence
  -> program renders Markdown placement brief for planner/editor
  -> LLM decides whether it belongs in USER, MEMORY, existing Skill, new Skill, or nowhere
  -> if built-in memory is full:
       1. compact/replace related entries
       2. remove or swap lower-value stale entries only if the new fact is worth it
       3. route procedural content to skill patch/create evidence
       4. fallback to active external provider only when still appropriate
  -> official memory/skill tools execute exact bounded operations
  -> program validates post-state and writes ledger/evaluation evidence
```

`create_skill` should be treated as a normal `improve` capability, not an exception path. It is valid when a repeated procedural gap exists and no mutable local skill is a good fit. It must still be executed only through `skill_manage(action="create")`, and success must be proven by `created_skills` / tool trace / post-validation, not by a natural-language outcome string.

## Implementation slices

### Slice 0A: Re-scope target resolver as attachment only

**Objective:** Prevent the resolver from over-proposing new skills. It should connect observations to existing mutable skills or memory when there is a clear fit, otherwise pass unresolved/no-existing-skill-fit evidence to the planner. The planner remains responsible for deciding whether to update an existing skill or create a new skill.

**Files:**
- Modify: `hermes_self_improvement/target_resolver.py`
- Modify: `hermes_self_improvement/planner.py`
- Modify: `hermes_self_improvement/prompts.py`
- Test: `tests/test_target_resolver.py`
- Test: `tests/test_skill_planner.py`
- Optional: `tests/test_cli_surface.py` if summary wording changes

**Step 1: Add resolver role-boundary tests**

Cover:

- resolver normalization no longer emits authoritative `create_new_skill` decisions.
- existing resolver payloads with legacy `resolution_kind="create_new_skill"` are downgraded to unresolved/no-existing-skill-fit compatibility records, not planner actions.
- resolver may include compact fields such as `unresolved_reason="no_existing_skill_fit"`, `suggested_boundary`, `target_fit_signals`, `confidence`, and `reason`.
- resolver may attach to an existing listed skill only when that skill is mutable and has positive fit.
- resolver may mark `memory_candidate` only for durable fact/preference/environment-like evidence; it still must not perform memory mutation decisions.

**Step 2: Update resolver prompt and schema**

Replace the resolver choices with attachment-oriented choices. Prefer a compact set such as:

```text
attach_existing_skill
memory_candidate
unresolved
skip_noise
```

Use a reason field for unresolved cases:

```text
no_existing_skill_fit
unclear_target
insufficient_context
out_of_scope
```

Do not ask the resolver to choose `create_new_skill`, `run_editor`, `archive_skill`, or any mutation action.

**Step 3: Pass unresolved observations to planner as first-class evidence**

`build_skill_planner_digest(...)` should include resolver output in a form the planner can reason about:

```json
{
  "unresolved_observations": [
    {
      "evidence_id": "...",
      "theme": "patch_tool_workflow",
      "unresolved_reason": "no_existing_skill_fit",
      "suggested_boundary": "patch tool workflow",
      "count": 36,
      "representative_failures": [...],
      "context_windows": [...]
    }
  ]
}
```

Planner prompt wording should say:

```text
The resolver only attaches observations to existing targets or marks them unresolved. You own the mutation decision. If unresolved evidence shows a repeated reusable workflow with no existing mutable skill fit, you may decide create_skill; otherwise update an existing skill, route to memory, defer, skip, or block.
```

**Step 3b: Add planner create-skill decision tests**

Cover:

- high-confidence unresolved/no-existing-skill-fit evidence with repeated procedural failures can become a planner `create_skill` decision.
- the same unresolved evidence does **not** become `create_skill` when recurrence is weak, evidence is one-off, the content is a durable fact better suited to memory, or an existing mutable skill has a positive fit.
- planner decisions include enough editor context for skill creation: proposed skill name, evidence ids, change intent, why existing skills do not fit, and why the content is procedural.
- resolver output alone is not treated as an executable decision; the planner decision is the first place where `create_skill` appears.

**Step 4: Verify**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_target_resolver.py tests/test_skill_planner.py -q
```

Expected: PASS after implementation. Run full suite before dogfood.

---

### Slice 0B: Replay a dry-run artifact for mutating execution

**Objective:** Make dry-run a real preview of the exact candidate set that can later be executed, not a separate run that rebuilds evidence and may make different LLM decisions.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/runner_steps.py` if orchestration needs a helper
- Modify: run artifact schema helpers if present
- Test: `tests/test_cli_surface.py`
- Test: `tests/test_runner_steps.py` or a focused replay test file

**Step 1: Add replay regression tests**

Cover:

- `improve --dry-run` artifact contains the program-owned inputs needed for replay: evidence pack path/hash, resolver output, planner digest/decisions, memory decisions, prompt source metadata, dry-run flag, and safety metadata.
- a mutating replay command such as `improve --from-run <run-json>` or `improve --replay-run <run-json>` executes the stored eligible decisions instead of rebuilding evidence/resolver/planner decisions from fresh observations.
- replay fails closed if the source run was not dry-run, if hashes/paths are missing, if target provenance has drifted, or if the artifact is from an incompatible schema version.
- replay re-runs hard safety validation and post-validation; it does not blindly trust the dry-run artifact.
- replay does not introduce a new approval queue, lane, or apply mode. It is just an execution mode for the existing `improve` artifact.

**Step 2: Add CLI surface**

Preferred simple interface:

```bash
bin/hermes-self-improve improve --dry-run
bin/hermes-self-improve improve --from-run /path/to/run.json
```

`--from-run` should be valid only for `improve`, not `report` or `calibrate`.

**Step 3: Implement replay loading**

Keep this minimal:

- load run JSON
- verify `dry_run: true`
- verify schema/version fields
- verify the artifact has stored decisions and evidence references
- re-run deterministic target guards before mutation
- execute only decisions that were mutation-ready in the artifact
- write a new mutating run artifact that references `source_dry_run_artifact`

Do not re-call resolver/planner during replay unless a hard validation failure requires `defer` with a clear reason.

**Step 4: Verify**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_cli_surface.py tests/test_runner_steps.py -q
```

Expected: PASS. Full suite before dogfood.

---

### Slice 0C: Improve dry-run summary readability

**Objective:** Make Slack/CLI dry-run output explain what would happen without opening the run JSON for every check.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/tool_handlers.py` if agent-facing tool summaries share formatting
- Test: `tests/test_cli_surface.py`
- Test: plugin tool summary tests if present

**Step 1: Add summary tests**

Cover compact sections like:

```text
Would apply:
- memory_replace: <short target/reason>
- skill_create: <proposed name> from unresolved/no_existing_skill_fit

Deferred:
- no_existing_skill_fit: patch_tool_workflow; planner needs create/update decision
- unclear_target: ...

Blocked:
- memory_operation_missing: 31
- unsafe_target: ...
```

Requirements:

- cap list lengths and show omitted counts.
- do not dump raw evidence windows or large Markdown.
- group by user-facing `Would apply / Deferred / Skipped / Blocked` buckets.
- include reason codes and short human labels for the top few items.
- preserve compact output for Slack/tool responses.

**Step 2: Implement compact formatting helpers**

Add a helper that reads existing `step_decisions` / `action_summary` and formats only the top items. Keep full details in artifacts.

**Step 3: Verify**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_cli_surface.py tests/test_plugin_tools.py -q
```

Expected: PASS. Full suite before dogfood.

---

### Slice 0D: Use report artifacts as diagnostic context for improve

**Objective:** Add `improve --from-report <report-artifact>` so report diagnostics can focus a new improve planning run, while keeping report as reference-only input rather than an executable proposal source.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Modify: `hermes_self_improvement/evidence.py` or a new small diagnostic-signal helper if report signal construction is currently embedded in report code
- Modify: report artifact writer/parser if needed
- Modify: `hermes_self_improvement/runner_steps.py` only if improve orchestration needs explicit report context plumbing
- Test: `tests/test_cli_surface.py`
- Test: report/evidence tests if present, or add a focused `tests/test_report_improve_connection.py`

**Step 1: Add report artifact / diagnostic signal tests**

Cover:

- report JSON artifacts expose compact `diagnostic_signals` with `kind`, `theme`, `severity`, `count`, `trend` if available, `evidence_refs`, `summary`, and `suggested_attention`.
- report Markdown remains human/LLM-facing context only and is not parsed for control state.
- diagnostic signals do not contain mutation decisions such as `create_skill`, `run_editor`, `memory_replace`, or `archive_skill`.

Example signal:

```json
{
  "kind": "diagnostic_signal",
  "theme": "patch_tool_workflow",
  "severity": "medium",
  "count": 36,
  "evidence_refs": ["..."],
  "summary": "patch argument and old_string failures are recurring",
  "suggested_attention": "planner_should_consider_workflow_gap"
}
```

**Step 2: Add `improve --from-report` CLI tests**

Cover:

- `improve --dry-run --from-report <report.json>` loads report diagnostics and adds them to the evidence pack as `kind="diagnostic_signal"` or a clearly named report-signal evidence kind.
- resolver and planner still run normally; report diagnostics only affect context/focus.
- if report contains legacy proposal-like fields, they are normalized to diagnostic signals or ignored; they are never executed directly.
- stale, incompatible, missing, or malformed report artifacts fail closed with a clear reason.
- `--from-report` can be combined with `--dry-run`, and the resulting run artifact records `source_report_artifact`, `source_report_hash`, and signal counts.
- `--from-report` is distinct from `--from-run`: it replans; it does not replay decisions.

**Step 3: Implement shared diagnostic signal builder**

Prefer a shared builder over `improve` reading the latest report by convention:

```text
observations -> build_diagnostic_signals(...) -> diagnostic_signals
report       -> displays/writes diagnostic_signals
improve      -> includes diagnostic_signals in evidence pack, optionally seeded from --from-report
```

`--from-report` may read a report artifact when explicitly provided, but normal `improve` should not depend on a report having been generated.

**Step 4: Wire planner/resolver context**

Diagnostic signals should flow like other evidence:

```text
diagnostic_signal
  -> resolver attaches to existing skill/memory or marks unresolved/no_existing_skill_fit
  -> planner decides update/create/memory/defer/skip/block
```

The planner prompt should explicitly say report diagnostics are attention signals, not instructions.

**Step 5: Verify**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_cli_surface.py tests/test_report_improve_connection.py tests/test_target_resolver.py tests/test_skill_planner.py -q
```

Adjust test filenames to the actual suite. Full suite before dogfood.

---

### Slice 0: Lock the non-Markdown requirements as regression tests

**Objective:** Before changing prompt format, capture the two concrete dogfood failures and the placement policy so the implementation cannot become “Markdown-only cleanup.”

**Files:**
- Modify: existing mutation backend / runner tests
- Modify: `tests/test_memory_inventory_planner.py`
- Modify: `tests/test_runner_steps.py`

**Step 1: Add create-skill contract regression tests**

Cover:

- natural-language `outcome` like `created safe-patch-usage skill ...` is accepted only when `created_skills` contains the expected skill, tool trace shows `skill_manage(action="create")`, and post-validation confirms the skill.
- the same natural-language outcome is rejected when `created_skills` is empty, target mismatches, or tool trace is missing.

**Step 2: Add memory capacity placement regression tests**

Cover:

- built-in memory full triggers compaction/replace attempt before abandoning add/move.
- if compaction is insufficient, the planner can consider lower-value remove/swap with explicit reason.
- procedural content is routed to skill patch/create evidence rather than forcing MEMORY.
- external provider fallback happens only after built-in compaction/replacement is exhausted and an active provider supports the operation.

**Step 3: Add boundary tests**

Cover:

- no new lane/queue/apply mode is introduced.
- skill mutation remains limited to Hermes-created local mutable skills, with create-skill only for missing reusable workflows.
- `improve` does not run GEPA/DSPy calibration; `calibrate` owns prompt/evaluator improvement.

Expected command:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_runner_steps.py tests/test_memory_inventory_planner.py -q
```

Expected initial result: some tests fail until later slices implement the behavior.

---

### Slice 1: Add Markdown rendering helpers for LLM context

**Objective:** Introduce a single renderer layer that turns existing program-owned evidence/candidate/planner state into Markdown without changing the mutation behavior yet.

**Files:**
- Create: `hermes_self_improvement/markdown_artifacts.py`
- Test: `tests/test_markdown_artifacts.py`

**Step 1: Write failing tests**

Add tests for:

- `render_evidence_markdown(evidence_pack)` includes stable sections:
  - `# Self-improvement evidence`
  - `## Window summary`
  - `## Knowledge inventory`
  - `## Coverage gaps`
  - `## Unmatched evidence`
  - `## Safety boundaries`
- redaction is applied to previews containing token/password-like material.
- output is bounded: large evidence lists are summarized and capped.
- renderer returns a plain string and does not require parsing back.

Expected command:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_markdown_artifacts.py -q
```

Expected initial result: FAIL because `markdown_artifacts.py` does not exist.

**Step 2: Implement minimal renderer**

Create `hermes_self_improvement/markdown_artifacts.py` with small pure functions:

```python
def render_evidence_markdown(evidence_pack: dict[str, Any], *, max_items: int = 20) -> str: ...
def render_candidate_markdown(candidate: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]], *, max_evidence: int = 8) -> str: ...
def render_planner_markdown(planner: dict[str, Any], *, max_decisions: int = 30) -> str: ...
def render_tool_result_markdown(result: dict[str, Any]) -> str: ...
```

Keep the implementation simple:

- deterministic Markdown only
- no frontmatter
- no Markdown parser
- use existing redaction helper if accessible; otherwise add a local minimal redaction helper and consolidate later if needed
- include artifact caveat: `This Markdown is LLM-facing context, not machine-control state.`

**Step 3: Verify**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_markdown_artifacts.py -q
```

Expected: PASS.

---

### Slice 2: Feed planner with Markdown context while keeping program-owned digest

**Objective:** Change the planner prompt input from raw JSON-heavy digest presentation to Markdown-rendered evidence/candidate context, without changing planner normalization or decisions yet.

**Files:**
- Modify: `hermes_self_improvement/prompts.py`
- Modify: `hermes_self_improvement/planner.py`
- Test: `tests/test_skill_planner.py`
- Test: `tests/test_markdown_artifacts.py`

**Step 1: Write failing test**

Add a planner prompt rendering test that asserts:

- `render_planner_messages(...)` includes Markdown headings from `render_evidence_markdown` / candidate summaries.
- the prompt explicitly says Markdown is context, not a control protocol.
- the prompt still tells the planner the allowed semantic decisions are the existing ones.
- no new user-facing command/lane/mode appears.

**Step 2: Implement**

Update `render_planner_messages` so it can receive the current `digest` but render the user-facing content as Markdown.

Do **not** remove the digest object from program flow. `run_skill_planner()` may still normalize structured planner output in this slice. The purpose is to make the LLM's input richer and less schema-shaped first.

Recommended prompt wording:

```text
Read the Markdown context below. It is evidence and rationale context, not a machine protocol.
Use your assessment to decide apply/defer/skip/block-equivalent actions within the existing planner decision vocabulary.
The program will enforce target provenance, mutable-skill scope, memory safety, and post-validation.
```

**Step 3: Verify planner tests**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_skill_planner.py tests/test_markdown_artifacts.py -q
```

Expected: PASS.

---

### Slice 3: Build editor tasks around Markdown briefs, not JSON task dumps

**Objective:** Make editor LLMs read Markdown briefs generated by the program while keeping target ids, allowed tools, and expected target names in program-owned task fields.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Modify: `hermes_self_improvement/mutation_backend.py`
- Modify: `hermes_self_improvement/prompts.py`
- Test: `tests/test_runner_steps.py`
- Test: `tests/test_mutation_backend.py` or existing mutation backend test file

**Step 1: Write failing tests**

Add tests that assert:

- `build_skill_agent_task(...)` includes an `llm_brief_markdown` field or embeds a Markdown brief in `instructions`.
- the task still includes program-owned fields:
  - `task_kind`
  - `targets`
  - `candidate`
  - `evidence_ids`
  - `constraints`
  - `expected_outcome`
- mutation backend prompt no longer appends a large `Task JSON:` blob as the primary editor context.
- the editor prompt says: use Markdown for assessment, use tools for side effects, finish with `submit_mutation_result` for audit.

**Step 2: Implement task rendering**

Use the new renderer from Slice 1:

```python
brief = render_candidate_markdown(candidate_or_create_candidate, evidence_by_id)
```

For create-skill tasks, include sections like:

```markdown
# Skill creation brief: safe-patch-usage

## Evidence
...

## Why this may be a skill
...

## Why this may not be a skill
...

## Safety boundaries
...
```

Keep exact target name and allowed tools in task object fields; do not rely on parsing the Markdown.

**Step 3: Change mutation backend prompt composition**

In `mutation_backend.py`, replace `Task JSON:` as primary context with:

```text
Task manifest summary:
- task_kind: ...
- target: ...
- allowed tools: ...

Markdown brief:
...
```

It is okay to include a compact machine-owned manifest excerpt for the LLM's convenience, but the prompt must not imply that the LLM is writing/parsing a JSON protocol.

**Step 4: Verify**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_runner_steps.py tests/test_mutation_backend.py -q
```

If `tests/test_mutation_backend.py` does not exist, add the backend prompt composition tests to the existing closest mutation backend test file.

Expected: PASS.

---

### Slice 4: Validate editor success by tool trace and post-validation, not enum-like outcome text

**Objective:** Fix the specific `mutation_agent_result_invalid_outcome` class without making natural-language outcomes authoritative.

**Files:**
- Modify: `hermes_self_improvement/mutation_backend.py`
- Modify: `hermes_self_improvement/runner_steps.py` if result normalization happens there
- Test: existing mutation backend/runner tests

**Step 1: Write failing tests**

Cover at least these cases:

1. Skill create success with natural-language outcome passes only when grounded:
   - `success: true`
   - `created_skills: ["safe-patch-usage"]`
   - tool trace includes `skill_manage` with `action=create`
   - post-validation confirms the expected skill name

2. Natural-language `created ... skill` outcome is still rejected when `created_skills` is empty or target mismatches.

3. Skill patch success with natural-language outcome passes only when `changed_skills` contains the expected target and tool trace/action is allowed.

4. `outcome` enum aliases like `changed` may continue to normalize, but they are secondary to actual tool/post-validation evidence.

**Step 2: Implement result validation helper**

Add or refine a helper like:

```python
def validate_mutation_result_against_task(result: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]: ...
```

Rules:

- Treat `outcome` as audit text, not proof.
- For `skill_create`, require expected `targets.new_skill` in `created_skills`.
- For `skill_improve`, require expected `targets.primary_skill` in `changed_skills` or an explicit skip/stopped outcome.
- For archive/delete, keep existing stricter boundaries.
- Preserve failure details in `reason` / `error` for calibration evidence.

**Step 3: Verify**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_runner_steps.py tests/test_mutation_backend.py -q
```

Expected: PASS.

---

### Slice 5: Render memory placement/capacity review as Markdown for LLMs

**Objective:** Support Ryo's memory-full policy with Markdown assessment context: compact first, then remove/swap if worthwhile, and move procedural content to skill when appropriate.

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py`
- Modify: `hermes_self_improvement/mutation_policy.py` if capacity policy helpers live there
- Modify: `hermes_self_improvement/markdown_artifacts.py`
- Test: `tests/test_memory_inventory_planner.py`
- Test: `tests/test_runner_steps.py`

**Step 1: Write failing tests**

Add tests for memory capacity planner input rendering:

- includes the new memory fact/candidate
- includes related current USER/MEMORY entries
- includes sections:
  - `## Placement options`
  - `## Compact first`
  - `## Remove or replace only if lower value`
  - `## Move procedural knowledge to skill`
  - `## External provider fallback`
- does not ask LLM to return raw memory content copied from tool output
- does not parse Markdown for operations

**Step 2: Implement Markdown context**

Render memory capacity context as Markdown for the LLM planner/editor.

Keep actual operations constrained to existing normalized operation objects:

```text
memory_add
memory_replace
memory_remove
move_user_to_memory
move_memory_to_user
skill_create_candidate / skill_patch_candidate as evidence, not immediate direct file edits
```

This slice may still use a structured operation object at the program boundary. The Markdown is the reasoning input, not the operation source of truth.

**Step 3: Verify**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_memory_inventory_planner.py tests/test_runner_steps.py tests/test_markdown_artifacts.py -q
```

Expected: PASS.

---

### Slice 6: Update evaluator/calibration input to prefer Markdown-rendered run reports

**Objective:** Keep `calibrate` LLM-facing context in Markdown while preserving runtime eval cases and candidate-set metadata as program-owned JSON.

**Files:**
- Modify: `hermes_self_improvement/calibration.py`
- Modify: `hermes_self_improvement/prompt_gepa_adapter.py`
- Modify: `hermes_self_improvement/runtime_eval_cases.py` only if cases need a Markdown summary field
- Test: calibration / prompt GEPA tests

**Step 1: Write failing tests**

Assert that GEPA/prompt overlay candidate construction receives or can produce Markdown context containing:

- recent run outcome summary
- planner/editor failures
- memory capacity failures
- successful/failed mutations
- lessons for planner/editor/evaluator

Keep existing JSONL eval cases intact.

**Step 2: Implement Markdown report rendering**

Use `render_tool_result_markdown` / `render_planner_markdown` or add a small `render_calibration_context_markdown(...)` helper.

Do not remove:

- `runtime-eval-cases/*.jsonl`
- candidate-set JSON artifacts
- active overlay pointer JSON
- base/overlay hashes

**Step 3: Verify**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_calibration*.py tests/test_prompt_gepa*.py tests/test_runtime_eval_cases.py -q
```

Adjust exact test globs to existing files.

Expected: PASS.

---

### Slice 7: CLI summary and artifacts

**Objective:** Make dry-run/mutating output explain that Markdown is the LLM context, while compact summaries remain machine-readable and user-readable.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Possibly modify: `hermes_self_improvement/runner_steps.py`
- Test: CLI summary tests if present, otherwise add focused tests around summary builders

**Step 1: Write failing tests**

Assert summary includes artifact paths or labels for:

- evidence Markdown
- planner notes Markdown
- editor notes Markdown when mutation runs
- ledger/result JSON

Do not dump large Markdown bodies in Slack/tool summary.

**Step 2: Implement compact summary fields**

Add paths/counts only:

```text
LLM context artifacts:
- evidence: .../evidence.md
- planner notes: .../planner.md
- editor notes: .../editor.md
Program artifacts:
- run json: .../run-....json
- ledger: ...
```

If artifact writing is not yet implemented for every Markdown file, surface generated context in the run JSON first and leave path writing to the smallest useful follow-up. Do not overbuild storage.

**Step 3: Verify**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests -q
```

Expected: PASS.

---

### Slice 8: Dogfood with dry-run, then one mutating run if dry-run is sane

**Objective:** Prove the new boundary fixes the previous failure mode and keeps safety boundaries intact.

**Files:**
- No planned source edits except fixes from dogfood findings.
- Runtime artifacts under `${HERMES_HOME:-~/.hermes}/self-improvement/`.

**Step 1: Full static/test validation**

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
git diff --check
```

Expected:

```text
all tests pass
git diff --check produces no output
```

**Step 2: Dry-run dogfood**

```bash
bin/hermes-self-improve improve --dry-run
```

Check:

- planner/editor context is Markdown-rendered
- no parse failure from Markdown handoff
- action buckets remain `apply / defer / skip / block` equivalent in summary
- skill/memory target guards still work
- large Markdown is not dumped into Slack/tool summaries

**Step 3: Mutating dogfood only if dry-run is sane**

```bash
bin/hermes-self-improve improve
```

Check:

- skill create candidates no longer fail due to natural-language `outcome` alone
- success is accepted only when tool trace/post-validation proves it
- memory capacity failures produce useful placement/capacity notes
- episodes/runtime eval cases capture the new boundary correctly

**Step 4: Calibrate dry-run after dogfood**

```bash
bin/hermes-self-improve calibrate --dry-run
```

Check:

- evaluator reads Markdown-rendered run context
- candidate-set metadata remains JSON
- no forced promote in this implementation slice unless explicitly requested

---

## Risks and mitigations

### Risk: Markdown becomes an implicit schema

Mitigation: tests should fail if code starts extracting authoritative decisions from Markdown headings. Markdown is context only.

### Risk: Losing machine-readable summaries

Mitigation: keep manifests, ledgers, tool results, run summaries, active pointers, hashes, and eval cases as JSON. Only LLM-facing reasoning handoffs move to Markdown.

### Risk: Editor has too much freedom

Mitigation: editor still gets constrained tools only. Program validates target name, provenance, allowed action, mutation result, and post-state.

### Risk: Prompt/context grows too large

Mitigation: render Markdown with caps and summaries. Include artifact paths and omitted counts. Keep full evidence in run JSON/artifacts.

### Risk: GEPA/DSPy expects JSON fields

Mitigation: keep JSON eval cases and candidate-set metadata. Add Markdown context as an input field or rendered report, not as replacement for eval case storage.

## Files likely to change

- `hermes_self_improvement/markdown_artifacts.py` — new Markdown renderer layer.
- `hermes_self_improvement/target_resolver.py` — resolver prompt/normalization for attaching observations to existing skills/memory or marking unresolved; it must not decide new skill creation.
- `hermes_self_improvement/planner.py` — planner call plumbing if Markdown context is passed through prompt rendering, plus unresolved/no-existing-skill-fit evidence in planner digest so planner owns create-skill decisions.
- `hermes_self_improvement/prompts.py` — planner/editor prompt wording and rendered context.
- `hermes_self_improvement/runner_steps.py` — editor task construction, memory capacity context, summaries.
- `hermes_self_improvement/mutation_backend.py` — editor prompt composition and result validation against task/tool trace.
- `hermes_self_improvement/mutation_policy.py` — only if memory placement/capacity policy helpers need small refactor.
- `hermes_self_improvement/calibration.py` — calibration context rendering.
- `hermes_self_improvement/prompt_gepa_adapter.py` — GEPA input descriptions/context fields.
- `hermes_self_improvement/cli.py` — compact summary paths/labels, dry-run artifact replay CLI option, and explicit `improve --from-report` report-context input.
- `hermes_self_improvement/tool_handlers.py` — shared compact dry-run summary formatting if agent-facing tool output uses the same buckets.
- `hermes_self_improvement/evidence.py` or a small diagnostic-signal helper — shared report/improve diagnostic signal construction.
- Report artifact writer/parser modules if diagnostics are not currently saved as structured JSON.
- `tests/test_markdown_artifacts.py` — new renderer tests.
- Existing tests under `tests/test_skill_planner.py`, `tests/test_target_resolver.py`, `tests/test_cli_surface.py`, `tests/test_plugin_tools.py`, `tests/test_runner_steps.py`, `tests/test_memory_inventory_planner.py`, report/evidence connection tests, calibration/GEPA tests, mutation backend tests.

## Validation checklist

Run before commit:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
git diff --check
bin/hermes-self-improve status
```

Dogfood after tests pass:

```bash
bin/hermes-self-improve report --since-hours 24 --json
bin/hermes-self-improve improve --dry-run --from-report /path/to/report.json
bin/hermes-self-improve improve --from-run /path/to/dry-run.json
bin/hermes-self-improve calibrate --dry-run
```

Do not promote calibrate candidate sets in this plan unless Ryo explicitly asks or the scheduled daily cron handles it.

## Commit strategy

Use small commits by slice:

1. `test: capture resolver role-boundary regressions`
2. `feat: replay dry-run improvement artifacts`
3. `feat: summarize dry-run actions by bucket`
4. `feat: use report diagnostics as improve context`
5. `test: capture self-improvement placement regressions`
6. `feat: add markdown self-improvement renderers`
7. `feat: render planner context as markdown`
8. `feat: use markdown briefs for editor tasks`
9. `fix: validate mutation results by tool evidence`
10. `feat: render memory placement context as markdown`
11. `feat: render calibration context as markdown`
12. `docs: record llm-centered self-improvement handoff plan` or combine docs with the last code slice if small

If a slice produces a meaningful passing state, commit and push before continuing.
