# Self-Improvement Roadmap Refresh Plan

> **For Hermes:** Use this as the current source-of-truth follow-up plan after the GEPA overlay-set implementation. Do not continue older active-looking plans directly unless this file explicitly reopens them.

**Goal:** Bring `hermes-self-improvement` plans back in sync with the current implementation and define the remaining work from the latest code state.

**Architecture:** The core loop is now implemented around bounded `improve`, runtime-private overlay prompt sets, GEPA/DSPy calibration, compact LLM-facing outputs, and append-only episode/outcome artifacts. The remaining work is not another redesign; it is cleanup of duplicate prompt-overlay paths, proof that the loop runs across real generations, and integration polish.

**Tech Stack:** Python, pytest, DSPy/GEPA, Hermes plugin tools, runtime-private artifacts under `${HERMES_HOME:-~/.hermes}/self-improvement/`, repo-tracked plans under `.hermes/plans/`.

---

## Current observed state

Repo: `/Users/ryo.nakae/.hermes/plugins/hermes-self-improvement`

Observed on 2026-05-05 JST:

```text
## main...origin/main
clean
```

Recent implementation commits:

```text
bb3f045 feat: connect GEPA overlay optimizer
0aef4fe feat: summarize overlay candidate sets
69298f2 feat: promote overlay sets during calibration
8a0eb04 feat: promote overlay candidate sets
407e9d6 feat: include overlay candidate sets in calibration
346ae00 feat: evaluate overlay candidate sets
afb39fe feat: generate overlay candidate sets
28f2320 feat: build overlay set eval cases
90e11e0 feat: record overlay hashes in episodes
9778e55 fix: report calibration partial updates
c66459c docs: plan GEPA overlay prompt self-improvement loop
5dc365d feat: use native skill tool mutation backend
```

Latest verified implementation baseline:

```text
focused:
- tests/test_prompt_gepa_adapter.py
- tests/test_prompt_candidate_optimizer.py
- tests/test_config_precedence.py
- tests/test_calibration.py
- tests/test_autonomous_evaluator.py
- tests/test_prompt_overlays.py
- tests/test_plugin_tools.py
- tests/test_cli_surface.py
- tests/test_gepa_optimizer.py
→ 93 passed

full:
→ 387 passed, 2 skipped

smoke:
- python3 -m py_compile __init__.py hermes_self_improvement/*.py
- bin/hermes-self-improve status
- bin/hermes-self-improve calibrate --dry-run
- bin/hermes-self-improve improve --dry-run --since-hours 1 --scorer heuristic
- git diff --check
→ OK
```

The current core loop pieces are implemented:

- `improve` uses the global planner and native skill-tool editor harness for bounded skill mutation.
- Skill archive lifecycle uses Curator-style `tools.skill_usage.archive_skill`, not direct deletion.
- Memory mutation is target-routed through built-in or external provider tools, not direct store edits.
- Episodes record active overlay generation/hash fields.
- Runtime eval cases can be built from improvement episodes for the overlay set.
- `calibrate` can build a single runtime-private overlay candidate set for `planner_overlay`, `editor_overlay`, and `evaluator_overlay`.
- DSPy/GEPA is connected for overlay candidate set generation when configured and evidence/cases exist.
- Overlay candidate set acceptance checks enforce artifact validity, no full replacement, consistent generation metadata, and GEPA result mapping.
- `calibrate` execute promotes accepted overlay candidate sets to active runtime-private overlays.
- CLI/tool summaries are compact; full payloads remain in artifacts or explicit `--json` output.

## Canonical boundaries

Keep these fixed unless a newer plan explicitly changes them:

- Mutation scope is only skill improvements, memory improvements, and scorer/evaluator/prompt-overlay self-improvement.
- No runtime config, prompt/tool policy, arbitrary docs, repo structure, gateway settings, or cron mutation targets.
- `improve` and `calibrate` are mutation-capable by default; `--dry-run` is the preview boundary.
- `improve` does not run GEPA. GEPA/DSPy belongs to `calibrate`.
- GEPA improves runtime-private overlay addenda, not repo-managed base prompts.
- Planner/editor/evaluator overlays are one candidate set and one generation unit, with per-target `changed|unchanged`.
- Plugin acceptance checks only verify artifact/overlay safety and consistency; they do not rejudge GEPA's quality decision with a parallel heavy evaluator.
- Agent-facing tool results return compact summaries and artifact paths, not full nested payloads.
- Full JSON/debug output remains available through CLI `--json` and runtime artifacts.
- Do not reintroduce classifier/normalizer layers, legacy fallback surfaces, approval/apply/rollback primary surfaces, or direct filesystem mutation fallbacks.

## What is complete

### Completed implementation records

- `2026-05-04_215735-gepa-prompt-self-improvement-loop.md`
  - Implemented episode overlay hash recording, overlay-set eval cases, candidate-set contract, GEPA adapter connection, acceptance decision, promotion primitive, `calibrate` execute promotion, and compact CLI/tool summaries.
- `2026-05-04_194014-mutation-agent-json-contract.md`
  - Implemented the native skill-tool editor harness and removed dependence on a handwritten JSON tool-call protocol.
- `archive/2026-05-04_213623-calibration-partial-success-status.md`
  - Implemented partial update reporting so prompt overlay promotion and evaluator regression availability are not conflated.
- `archive/2026-05-04_093127-skill-archive-lifecycle.md`
  - Implemented Curator-style archive lifecycle integration.
- `2026-05-02_235356-autonomous-improvement-loop.md`
  - Implemented the scoped autonomous loop contracts for skill/memory/scorer-evaluator targets.
- `2026-05-02_211229-runtime-private-prompt-overlays.md`
  - Implemented repo-managed base prompts plus runtime-private overlay candidates and active pointers, then extended by the GEPA overlay-set plan.
- Earlier 2026-05-01/2026-05-02 plans for planner, evidence hints, compact tool results, role names, and scorer cleanup are completed or absorbed by this baseline.

## Remaining work, in priority order

### Slice 1: Make overlay-set the only prompt-overlay promotion path

**Status:** completed in this follow-up slice. `calibration.py` no longer exposes or calls the old `build_prompt_overlay_candidates()` / `_run_prompt_overlay_regression()` single-role active flow. Prompt overlay promotion now flows through `generate_overlay_candidate_set()` + `evaluate_overlay_candidate_set()` + `promote_overlay_candidate_set()` only. Low-level `promote_prompt_candidate()` remains as the internal primitive used by overlay-set promotion and active-overlay loading tests.

**Objective:** Remove the remaining ambiguity where `calibrate` still has both the new overlay-set path and an older planner/editor single-role prompt candidate path.

**Files:**

- Modify: `hermes_self_improvement/calibration.py`
- Modify: `hermes_self_improvement/prompt_candidate_optimizer.py`
- Modify: `tests/test_calibration.py`
- Modify: `tests/test_prompt_candidate_optimizer.py`
- Modify if needed: `tests/test_cli_surface.py`, `tests/test_plugin_tools.py`

**Current issue:**

`run_calibration()` now builds and evaluates `overlay_candidate_set`, but it also still builds `prompt_candidates` via `build_prompt_overlay_candidates()` and may promote planner/editor individually through `_run_prompt_overlay_regression()` and `promote_prompt_candidate()`.

That leaves two prompt-overlay promotion concepts alive:

```text
new: overlay candidate set, GEPA-backed, planner/editor/evaluator together
old: planner/editor single-role candidate, rule_fallback-backed
```

**Target behavior:**

- Prompt overlay promotion flows only through `generate_overlay_candidate_set()` + `evaluate_overlay_candidate_set()` + `promote_overlay_candidate_set()`.
- The old planner/editor single-role promotion path is removed from `run_calibration()`.
- Evaluator calibration remains a separate sub-result and may still update the active evaluator pointer.
- `prompt_overlays` summary is derived from overlay-set state, not from single-role prompt candidates.
- If there is insufficient evidence for an evaluator candidate but overlay cases exist, `calibrate` may still build/evaluate an overlay candidate set.

**TDD tasks:**

1. Add/adjust a failing test proving `run_calibration()` does not call `generate_prompt_overlay_candidate()` or `promote_prompt_candidate()` when overlay-set candidate generation is available.
2. Add a failing test proving `calibrate` can report overlay-set candidate status without planner/editor single-role candidate fields.
3. Remove or deprecate `build_prompt_overlay_candidates()` from the active calibration flow.
4. Keep single-role helper functions only if tests still need them as low-level utilities; otherwise remove them and their fallback tests.
5. Update CLI/tool summary tests so the displayed prompt overlay state comes from `overlay_candidate_set`.
6. Run focused tests, then full suite.

**Verification:**

```bash
python3 -m pytest tests/test_calibration.py tests/test_prompt_candidate_optimizer.py tests/test_cli_surface.py tests/test_plugin_tools.py -q
python3 -m pytest -q
bin/hermes-self-improve calibrate --dry-run
bin/hermes-self-improve improve --dry-run --since-hours 1 --scorer heuristic
git diff --check
```

**Commit:**

```bash
git commit -m "refactor: make overlay sets the prompt calibration path"
```

### Slice 2: Dogfood one real overlay generation loop

**Status:** attempted on 2026-05-05 JST, not fully completed. The first dogfood run proved the candidate-set path and selected-case artifact shape, but did not produce an active overlay generation promotion.

Observed result:

```text
Before:
- active overlay_generation_id: null
- active roles: planner only

calibrate --dry-run after Slice 3 case selection:
- decision: promote
- GEPA: selected
- changed targets: 3
- available_case_count: 2883
- optimizer_case_count: 3
- selected_case_targets: planner_overlay, editor_overlay, evaluator_overlay

calibrate execute immediately after:
- decision: keep_candidate
- GEPA: no_improvement
- changed targets: 0
- active overlay_generation_id: still null
- active generation count: still 0

improve --dry-run after execute:
- planner still used the pre-existing runtime overlay
- editor still used base prompt
- no new overlay generation/hash proof was available
```

Interpretation:

- Do not weaken GEPA/acceptance to force a promotion.
- The no-promotion outcome is valid evidence.
- A new issue is now visible: dry-run and execute each rerun GEPA, so a promotable dry-run candidate is not the exact candidate promoted by execute. If exact dry-run-to-execute continuity becomes important, add a separate follow-up design for candidate artifact execution/promotion rather than smuggling it into this slice.

**Objective:** Prove the closed loop with runtime artifacts, not only unit tests.

**Files:**

- Modify only if bugs are found.
- Runtime artifacts under `${HERMES_HOME}/self-improvement/` are evidence, not repo commits.
- Optional doc update: `.hermes/plans/README.md` if the proof changes the roadmap.

**Proof sequence:**

1. Capture current active overlay generation pointers.
2. Run a bounded `calibrate --dry-run` and inspect compact output plus candidate-set artifact.
3. If the candidate is promotable under current evidence, run `calibrate` without `--dry-run`.
4. Run `improve --dry-run --since-hours 1 --scorer heuristic` or a similarly bounded safe preview.
5. Confirm the new episode records `overlay_generation_id`, `planner_overlay_hash`, `editor_overlay_hash`, and `evaluator_overlay_hash`.
6. Confirm a later `calibrate --dry-run` includes eval cases derived from that episode.

**Important:** Do not fabricate promotion by weakening GEPA/acceptance logic. If GEPA returns `no_improvement`, record that as a valid dogfood result and keep candidate.

**Verification commands:**

```bash
bin/hermes-self-improve status
bin/hermes-self-improve calibrate --dry-run
bin/hermes-self-improve improve --dry-run --since-hours 1 --scorer heuristic
```

Use `read_file` on the artifact paths reported by compact summaries. Do not dump huge JSON into the chat.

**Commit:**

Only commit if repo docs/tests change.

### Slice 3: Improve overlay case selection budget

**Status:** completed in this follow-up slice. `select_overlay_eval_cases()` now applies a deterministic bounded selection policy before DSPy/GEPA: target-balanced round-robin across `planner_overlay`, `editor_overlay`, and `evaluator_overlay`, high-signal cases first within each target, preserving recent/source order after selection. Candidate-set artifacts now record `selected_case_ids` and `selected_case_targets` alongside available/optimizer case counts.

**Objective:** Keep GEPA input small while selecting better cases than simple list order.

**Files:**

- Modify: `hermes_self_improvement/prompt_gepa_adapter.py`
- Modify: `hermes_self_improvement/prompt_candidate_optimizer.py`
- Modify: `tests/test_prompt_gepa_adapter.py`
- Modify: `tests/test_prompt_candidate_optimizer.py`

**Current issue:**

`gepa_scorer.overlay_max_cases` caps cases, defaulting to a small number to avoid context/time blowups. This is good, but the selected cases should be high-signal and balanced.

**Target behavior:**

- Keep the default cap small.
- Select cases using a simple deterministic budget, not a classifier:
  - include recent cases first,
  - prefer cases with concrete outcomes/failures/repeats,
  - balance `planner_overlay`, `editor_overlay`, and `evaluator_overlay` when possible.
- Record both `available_case_count` and selected case metadata in the artifact.
- Keep CLI/tool output compact.

**TDD tasks:**

1. Add tests for deterministic balanced selection under a small cap.
2. Add tests that high-signal cases beat low-signal filler cases.
3. Implement a tiny selection function with no LLM, no parser complexity, and no mutation decision logic.
4. Confirm artifact records selected counts without embedding prompt bodies in tool output.

**Verification:**

```bash
python3 -m pytest tests/test_prompt_gepa_adapter.py tests/test_prompt_candidate_optimizer.py -q
bin/hermes-self-improve calibrate --dry-run
```

**Commit:**

```bash
git commit -m "feat: select high-signal overlay eval cases"
```

### Slice 4: Add optional dry-run candidate-set reuse

**Status:** completed in this follow-up slice. `run_calibration()` now accepts `candidate_set_artifact_path` only in execute mode, loads the explicit overlay candidate-set artifact, evaluates it through the existing candidate-set acceptance checks, and promotes it without calling `generate_overlay_candidate_set()` / DSPy / GEPA. CLI support is exposed as `bin/hermes-self-improve calibrate --from-candidate-set <path>`. Agent-facing `self_improvement_calibrate` also accepts `candidate_set_artifact_path`, returns compact metadata, and rejects dry-run reuse.

**Positioning:** This is an opt-in cost/control feature, not the default path. Most normal runs should continue to call `bin/hermes-self-improve calibrate` directly and generate/evaluate the current candidate set from current evidence. Reuse is only for the workflow where an operator already ran `calibrate --dry-run`, inspected the compact summary/artifact, and wants to promote exactly that candidate without paying for another GEPA run or accepting stochastic drift.

**Files:**

- Modify: `hermes_self_improvement/calibration.py`
- Modify: `hermes_self_improvement/cli.py`
- Modify if agent tool support is desired: `hermes_self_improvement/tool_handlers.py` and plugin schema/registration file
- Modify: `tests/test_calibration.py`
- Modify: `tests/test_cli_surface.py`
- Modify if tool support is added: `tests/test_plugin_tools.py`
- Modify if helper coverage is cleaner there: `tests/test_feedback_loop.py`, `tests/test_prompt_overlays.py`

**Current issue:**

Dogfood showed this sequence:

```text
calibrate --dry-run:
- decision: promote
- GEPA: selected
- changed targets: 3

calibrate execute immediately after:
- GEPA reran
- decision: keep_candidate
- GEPA: no_improvement
- changed targets: 0
```

That is acceptable as the default behavior, but it wastes LLM/GEPA cost when the operator intentionally wants to apply the reviewed dry-run candidate. It also makes the dry-run artifact less useful as an exact preview.

**Target behavior:**

- Default remains unchanged:
  - `bin/hermes-self-improve calibrate` builds/evaluates a fresh candidate set.
  - No implicit reuse of the latest dry-run artifact.
- Add an explicit option, recommended spelling:
  - `bin/hermes-self-improve calibrate --from-candidate-set /path/to/candidate-set.json`
- The option is valid only for execute mode. Combining it with `--dry-run` should fail fast with a clear message, because dry-run is how the artifact was produced.
- When `--from-candidate-set` is present:
  - load the candidate-set artifact from the provided path,
  - validate the candidate-set schema and target/base-hash consistency using the existing overlay candidate-set acceptance checks,
  - evaluate it with `evaluate_overlay_candidate_set()` if the artifact does not already include a trusted evaluation payload, or re-evaluate cheaply without rerunning GEPA,
  - if the decision is `promote`, call `promote_overlay_candidate_set()` directly,
  - do not call `generate_overlay_candidate_set()` / DSPy / GEPA.
- The result summary must say it reused an artifact, e.g. `source: candidate_set_artifact`, and include the artifact path.
- Keep LLM-facing tool output compact. Do not inline the candidate-set JSON.

**Non-goals:**

- Do not make dry-run artifacts auto-apply later.
- Do not add a general approval/apply/rollback surface.
- Do not weaken GEPA acceptance or hard invariant checks.
- Do not use "latest artifact" discovery as a default; require an explicit path to avoid accidental stale promotion.

**TDD tasks:**

1. Add a failing calibration test where `execute=True` and `candidate_set_artifact_path` is passed; assert `generate_overlay_candidate_set()` is not called.
2. Add a failing test proving the loaded candidate set is passed through `evaluate_overlay_candidate_set()` / `promote_overlay_candidate_set()` and promotes changed targets when the decision is `promote`.
3. Add a failing test for invalid combinations: `execute=False` / `--dry-run` with `--from-candidate-set` fails clearly.
4. Add a failing CLI test proving `--from-candidate-set` is parsed and forwarded to `run_calibration()`.
5. Add a failing CLI summary test proving reused artifacts are visible as compact metadata.
6. Implement a small loader/helper for candidate-set artifacts. Keep it schema-focused and avoid a broad artifact registry abstraction.
7. Wire `run_calibration(config, execute=True, candidate_set_artifact_path=...)` to use the loaded artifact path instead of generating a fresh GEPA candidate.
8. If exposing this to the agent-facing tool, add an optional `candidate_set_artifact_path` parameter and the same compact summary behavior. If not, document it as CLI-only for now.
9. Run focused tests, then full suite and smoke.

**Verification:**

```bash
python3 -m pytest tests/test_calibration.py tests/test_cli_surface.py tests/test_feedback_loop.py tests/test_prompt_overlays.py -q
python3 -m pytest tests/test_plugin_tools.py -q
python3 -m pytest -q
python3 -m py_compile __init__.py hermes_self_improvement/*.py
bin/hermes-self-improve calibrate --dry-run
# If the dry-run reports a promotable candidate, manually test:
# bin/hermes-self-improve calibrate --from-candidate-set /path/from/dry-run.json
git diff --check
```

**Commit:**

```bash
git commit -m "feat: reuse overlay candidate artifacts on request"
```

### Slice 5: Tighten status and report surfaces around partial success

**Status:** completed in this follow-up slice. CLI calibration summaries now include a `Component status` block that separately reports the prompt overlay set and evaluator status, and no longer emits a standalone legacy `Regression:` line that made evaluator failure look like the whole overlay path failed. Agent-facing compact calibrate results now include a `components` object with `prompt_overlay_set` and `evaluator` sub-results while keeping the existing compact `overlay_candidate_set` payload.

**Objective:** Make operator-facing output clearly separate prompt overlay set status from evaluator calibration status.

**Files:**

- Modify: CLI rendering module / `cli.py` equivalent
- Modify: `hermes_self_improvement/plugin_tools.py` or tool handler module
- Modify: `tests/test_cli_surface.py`
- Modify: `tests/test_plugin_tools.py`

**Target display model:**

```text
Prompt overlay set:
- status: evaluated|promoted|kept|rejected|not_built
- GEPA result: selected|no_improvement|failed|...
- changed targets: N
- artifact: ...

Evaluator:
- status: updated|failed|no_candidate|unavailable
- reason: ...
- active changed: true|false
```

**TDD tasks:**

1. Add CLI tests for `promoted overlay / failed evaluator => partial_update`.
2. Add tool-result tests that compact summaries include both sub-results.
3. Remove duplicate or misleading legacy `prompt_overlay_updates` wording if Slice 1 made it obsolete.
4. Keep full diagnostic data in artifacts only.

**Verification:**

```bash
python3 -m pytest tests/test_cli_surface.py tests/test_plugin_tools.py tests/test_calibration.py -q
bin/hermes-self-improve calibrate --dry-run
```

**Commit:**

```bash
git commit -m "fix: clarify calibration sub-results"
```

### Slice 6: Top-level Hermes CLI integration, separate from plugin quality

**Objective:** Decide whether to fix Hermes core plugin CLI wiring or continue using `bin/hermes-self-improve` as the supported top-level entrypoint.

**Files:**

- Likely Hermes core repo, not this plugin repo.
- Plugin repo docs only if documenting the decision.

**Known state:**

- Plugin tools are registered.
- Slash command works.
- `PluginManager._cli_commands` contains `self-improvement`.
- `hermes self-improvement ...` still fails at top-level argparse in the inspected Hermes core path.
- `bin/hermes-self-improve ...` remains the reliable CLI.

**Recommendation:**

Do not block self-improvement quality work on this. Treat it as a separate Hermes core integration task.

## Completion criteria for this roadmap

- `calibrate` has one prompt-overlay promotion path: overlay-set.
- `generate_prompt_overlay_candidate()` is removed from active calibration flow or clearly demoted to test/legacy-free utility status.
- A real dogfood run proves overlay generation/hash data flows from promotion to later improvement episodes and back into eval cases, or records a clear no-promotion reason without weakening gates.
- GEPA overlay case selection is bounded, deterministic, high-signal, and compact-output-safe.
- Optional dry-run candidate-set reuse is available only when an explicit artifact path is provided; default `calibrate` still generates/evaluates fresh candidates.
- CLI/tool summaries separate prompt overlay set state from evaluator state.
- `.hermes/plans/README.md` names this roadmap and the GEPA overlay plan as the latest source of truth.

## Do not do

- Do not revive `plan/apply/rollback/outcome` primary surfaces.
- Do not add report-only mode as the main answer.
- Do not add classifier/normalizer layers that decide edit/archive/skip before the planner.
- Do not make GEPA mutate repo base prompts.
- Do not loosen acceptance checks to force promotion.
- Do not dump full GEPA/candidate/evidence payloads into agent-facing tool results.
- Do not implicitly promote the latest dry-run candidate artifact without an explicit path.
- Do not handle top-level `hermes self-improvement` by adding another plugin-local wrapper hack.
