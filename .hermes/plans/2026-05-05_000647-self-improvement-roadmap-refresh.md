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
c40b03a fix: clarify calibration sub-results
557c8d7 feat: reuse overlay candidate artifacts on request
d866f7e docs: plan optional candidate artifact reuse
d67b25b feat: select high-signal overlay eval cases
a654155 refactor: make overlay sets the prompt calibration path
b3859d7 docs: refresh self-improvement roadmap
bb3f045 feat: connect GEPA overlay optimizer
0aef4fe feat: summarize overlay candidate sets
69298f2 feat: promote overlay sets during calibration
```

Latest verified implementation baseline:

```text
focused:
- tests/test_calibration.py
- tests/test_cli_surface.py
- tests/test_plugin_tools.py
- tests/test_feedback_loop.py
- tests/test_prompt_overlays.py
→ 65 passed

full:
→ 395 passed, 2 skipped

smoke:
- python3 -m py_compile __init__.py hermes_self_improvement/*.py
- bin/hermes-self-improve calibrate --dry-run
- git diff --check
→ OK
```

Current working boundary:

```text
Hermes core repository is out of scope for this roadmap.
Do not implement top-level `hermes self-improvement ...` wiring here.
Use `bin/hermes-self-improve ...` as the reliable CLI surface.
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

### Slice 6: Dogfood one real overlay generation loop after artifact reuse

**Status:** active next slice. Earlier dogfood was attempted before optional candidate-set reuse and clearer component summaries existed. Re-run the proof using the current `--from-candidate-set` path when a promotable dry-run artifact appears.

**Objective:** Prove the closed loop with runtime artifacts: prompt overlay candidate-set promotion updates active overlay generation, later `improve` episodes record that generation/hash data, and later `calibrate` can use those episodes as runtime eval cases.

**Files:**

- Modify only if bugs are found.
- Runtime artifacts under `${HERMES_HOME}/self-improvement/` are evidence, not repo commits.
- Update this roadmap with the observed proof/no-promotion result.

**Proof sequence:**

1. Capture current active overlay pointer:
   ```bash
   python3 - <<'PY'
   import json
   from pathlib import Path
   p = Path.home() / '.hermes/self-improvement/evaluator/active-prompts.json'
   print(p)
   print(p.read_text() if p.exists() else 'missing')
   PY
   ```
2. Run a bounded preview:
   ```bash
   bin/hermes-self-improve calibrate --dry-run
   ```
3. Read the reported candidate-set artifact with `read_file`/small JSON inspection. Do not paste full JSON into chat.
4. If the artifact reports `decision promote`, `GEPA selected|improved`, and changed targets, execute exactly that artifact:
   ```bash
   bin/hermes-self-improve calibrate --from-candidate-set <artifact-path>
   ```
5. Confirm active overlay pointer changed and includes the promoted `overlay_generation_id`.
6. Run:
   ```bash
   bin/hermes-self-improve improve --dry-run --since-hours 1 --scorer heuristic
   ```
7. Inspect the new run/episode artifacts and confirm overlay generation/hash fields are recorded.
8. Run a later `calibrate --dry-run` and confirm candidate-set eval cases can include the newly recorded episode.

**If no promotion appears:**

- Record it as valid no-promotion evidence.
- Do not loosen acceptance checks.
- Inspect only compact artifact metadata first: `gepa_result`, `baseline_score`, `candidate_score`, `selected_case_ids`, `selected_case_targets`, and changed-target count.
- If repeated no-promotion occurs, open the next slice below instead of forcing promotion.

**Verification:**

```bash
bin/hermes-self-improve status
bin/hermes-self-improve calibrate --dry-run
bin/hermes-self-improve improve --dry-run --since-hours 1 --scorer heuristic
```

**Commit:**

Only commit if repo docs/tests/code change. Runtime artifact proof alone is not committed.

### Slice 7: Inspect no-promotion scoring/case quality if dogfood still cannot promote

**Status:** pending; only start if Slice 6 repeatedly produces `keep_candidate` / `no_improvement` and no active overlay generation proof.

**Objective:** Determine whether GEPA has no real improvement to make, or whether the eval-case/scoring budget is too weak to recognize improvement.

**Files:**

- Modify likely: `hermes_self_improvement/prompt_gepa_adapter.py`
- Modify likely: `hermes_self_improvement/prompt_candidate_optimizer.py`
- Modify likely: `tests/test_prompt_gepa_adapter.py`, `tests/test_prompt_candidate_optimizer.py`
- Modify this roadmap with findings.

**Inspection checklist:**

1. For several candidate-set artifacts, inspect compact fields only:
   - `gepa_result`
   - `available_case_count`
   - `optimizer_case_count`
   - `selected_case_ids`
   - `selected_case_targets`
   - baseline/candidate scores if present
   - changed target count
2. Check whether selected cases are all low-signal/pending or if scoring always yields ties.
3. If needed, adjust deterministic selection/scoring narrowly. Keep the default cap bounded and do not add classifier/normalizer layers.
4. Re-run focused tests and dogfood preview.

**Verification:**

```bash
python3 -m pytest tests/test_prompt_gepa_adapter.py tests/test_prompt_candidate_optimizer.py tests/test_calibration.py -q
bin/hermes-self-improve calibrate --dry-run
```

**Commit:**

```bash
git commit -m "fix: improve overlay calibration case signal"
```

### Slice 8: Remove remaining legacy prompt-overlay summary duplication

**Status:** pending cleanup; do after dogfood proof or scoring inspection.

**Objective:** Reduce duplicated calibration summary fields now that `components.prompt_overlay_set` and `overlay_candidate_set` are the primary compact result surfaces.

**Files:**

- Modify: `hermes_self_improvement/calibration.py`
- Modify: `hermes_self_improvement/tool_handlers.py`
- Modify: `hermes_self_improvement/cli.py` if display wording changes
- Modify: `tests/test_calibration.py`, `tests/test_plugin_tools.py`, `tests/test_cli_surface.py`

**Target behavior:**

- Keep `overlay_candidate_set` as the detailed compact candidate-set summary.
- Keep `components.prompt_overlay_set` and `components.evaluator` as the operator-friendly component summary.
- Deprecate or remove stale `prompt_overlay_updates` wording if it no longer carries unique information.
- Keep `prompt_overlays` only if role-level candidate/promoted paths are still useful for debugging active overlays.
- Do not remove runtime artifact fields needed for episode recording or active pointer validation.

**Verification:**

```bash
python3 -m pytest tests/test_calibration.py tests/test_cli_surface.py tests/test_plugin_tools.py tests/test_feedback_loop.py tests/test_prompt_overlays.py -q
python3 -m pytest -q
bin/hermes-self-improve calibrate --dry-run
git diff --check
```

**Commit:**

```bash
git commit -m "refactor: simplify calibration summary fields"
```

### Out of scope: Top-level Hermes CLI integration

**Status:** explicitly out of scope for this plugin roadmap.

`hermes self-improvement ...` requires Hermes core argparse/plugin CLI wiring. Do not modify Hermes core from this roadmap, and do not add another plugin-local wrapper hack. Continue to use:

```bash
bin/hermes-self-improve ...
```

Supported plugin surfaces remain:

- `bin/hermes-self-improve ...`
- agent tools: `self_improvement_status`, `self_improvement_report`, `self_improvement_improve`, `self_improvement_calibrate`
- slash command: `/self-improvement ...`

## Completion criteria for this roadmap

- `calibrate` has one prompt-overlay promotion path: overlay-set. **Done.**
- `generate_prompt_overlay_candidate()` is removed from active calibration flow or clearly demoted to test/legacy-free utility status. **Done.**
- GEPA overlay case selection is bounded, deterministic, high-signal, and compact-output-safe. **Done.**
- Optional dry-run candidate-set reuse is available only when an explicit artifact path is provided; default `calibrate` still generates/evaluates fresh candidates. **Done.**
- CLI/tool summaries separate prompt overlay set state from evaluator state. **Done.**
- `.hermes/plans/README.md` names this roadmap as the latest source of truth and marks Hermes core top-level CLI integration out of scope. **Done.**
- A real dogfood run proves overlay generation/hash data flows from promotion to later improvement episodes and back into eval cases, or records repeated no-promotion reasons without weakening gates. **Remaining.**
- If dogfood repeatedly cannot promote, compact artifact inspection identifies whether the issue is no real improvement, weak scoring, or weak case selection. **Conditional remaining.**


## Do not do

- Do not revive `plan/apply/rollback/outcome` primary surfaces.
- Do not add report-only mode as the main answer.
- Do not add classifier/normalizer layers that decide edit/archive/skip before the planner.
- Do not make GEPA mutate repo base prompts.
- Do not loosen acceptance checks to force promotion.
- Do not dump full GEPA/candidate/evidence payloads into agent-facing tool results.
- Do not implicitly promote the latest dry-run candidate artifact without an explicit path.
- Do not handle top-level `hermes self-improvement` by adding another plugin-local wrapper hack.
