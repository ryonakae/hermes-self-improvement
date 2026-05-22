# Architecture notes

Use this reference when changing observation, analysis, scorer, or module layout code.

## Plugin shape

- `plugin.yaml` declares the standalone user plugin.
- root `__init__.py` is the Hermes plugin discovery shim. It imports the package implementation and exposes `register` / `main`.
- `hermes self-improvement` imports `hermes_self_improvement.main` through the package, so normal CLI smoke tests do not rely on direct file execution.
- Keep implementation imports package-relative; do not add direct-file import fallbacks for unreleased compatibility.

## Observed hooks

The plugin observes these hooks when enabled:

- `pre_tool_call`
- `post_tool_call`
- `pre_llm_call`
- `post_llm_call`
- `pre_api_request`
- `post_api_request`
- `on_session_start`
- `on_session_end`
- `on_session_finalize`
- `on_session_reset`
- `subagent_stop`

Hook callbacks should stay lightweight and observation-only. Expensive analysis belongs in CLI/report paths.

## Telemetry and redaction

`hermes_self_improvement/observer.py` writes JSONL telemetry under `${HERMES_HOME:-~/.hermes}/self-improvement/state/events.jsonl` by default.

- Store redacted previews and stable hashes, not full sensitive payloads.
- Redact credential-looking values and sensitive paths before writing JSONL.
- Enforce `retention_days` before the first event write in a process.
- Prune old timestamped rows, drop malformed JSON rows, and keep rows with missing/unparseable timestamps for manual inspection.
- Drop incomplete early `pre_tool_call` rows when they lack `session_id` / `tool_call_id`; also defensively filter historical partial rows during analysis.

## Analysis and proposal generation

`hermes_self_improvement/analysis.py` should:

- Reclassify historical `post_tool_call` rows from `result_preview` without rewriting the JSONL source.
- Prefer structured success/error fields over raw text keyword matching.
- Treat truncated success previews such as `{"success": true`, `{"total_count":`, or `{"content":` as likely success payloads.
- Cluster findings by `(tool_name, error_kind)` rather than by tool alone.
- Generate remediation-oriented proposals and merge equivalent fixes.

## Proposal scoring and diagnostic signals

`hermes_self_improvement/scoring.py` now provides only deterministic heuristic proposal scoring for report ordering and diagnostic signals. It does not make mutation decisions and does not call an LLM. The historical LLM-driven proposal scorer was retired after `improvement_planner` became the decision owner.

LLM judgment is split by role and permission boundary, not by one generic auxiliary path:

| Role/site | Model config key | Tool access | Execution shape |
|---|---|---|---|
| `target_resolver` | `model.target_resolver` | `skills_list`, `skill_view` only | Hermes constrained agent |
| `improvement_planner` | `model.improvement_planner` | `skills_list`, `skill_view` only | Hermes constrained agent |
| `skill_agent` | `model.skill_agent` | official skill tools | Hermes constrained agent |
| `memory_agent` | `model.memory_agent` | official memory tool/provider | Hermes constrained agent |
| `memory_extractor` | `model.memory_extractor` | tool-free | Hermes auxiliary LLM call with host-prepared conversation/memory context |
| DSPy evaluator scoring / GEPA prompt optimization | `model.evaluator` | tool-free | DSPy/GEPA through the Hermes auxiliary LM bridge |

`provider: auto` with an empty `model` means the plugin does not pin a concrete model and lets Hermes use its normal auto/main routing. `memory_extractor` only proposes normalized memory-gap candidates; it does not mutate memory. Memory changes remain owned by `memory_agent` through the official memory tool.

GEPA / DSPy are not live proposal scorers. They belong to `calibrate`, where they improve runtime-private evaluator, prompt, and rubric artifacts for later planner and agent runs. Scoring remains advisory and never grants mutation permission.

## Improvement planner and mutation agents

`improve` runs skill and memory changes as `evidence builder -> target_resolver / memory_extractor -> improvement_planner -> skill_agent / memory_agent`. The planner receives a compact redacted digest of mutable skill candidates, memory candidates, target-resolution metadata, evidence ids/previews, and unmatched evidence counts. Planner decisions are `mutate_skill`, `archive_skill`, `create_skill`, `mutate_memory`, `calibrate_evaluator`, `skip`, or `defer`. Skill patch/merge semantics are represented by `decision: "mutate_skill"` plus `maintenance_action: "patch" | "merge"`.

Dry-run executes planning and writes the planner payload plus digest into the run artifact, but does not execute mutation agents. Mutating runs send `mutate_skill` decisions to `skill_agent` with `skill_agent_instructions` and selected `evidence_ids`, and send `mutate_memory` decisions to `memory_agent`. Planner fallback remains deterministic and evidence-attached; weak-only evidence does not grant mutation permission.

Planner / skill-agent / memory-agent / evaluator prompts are rendered from thin repo-managed base specs in `hermes_self_improvement/prompts.py`. The base specs carry only role identity, schema, allowed actions/tools, hard safety boundaries, secret handling, and overlay-loading semantics. Rich operating guidance lives in runtime-private overlays under `${HERMES_HOME:-~/.hermes}/self-improvement/evaluator/active-prompts.json`; `setup` materializes initial guidance from repo seed Markdown files in `defaults/prompt-overlays/`, but runtime overlays are the active source of truth after setup. Invalid or mismatched overlays fail closed to the repo base prompt. Overlays are capped at 150 lines and 12000 chars per role. Artifacts and compact tool results record prompt source/hash/path metadata only; they must not include full prompt text or candidate content.

Planner normalization is deliberately strict: `mutate_skill` without attached evidence becomes `skip` with an insufficient-evidence reason; `skip` decisions do not retain action fields such as `change_intent` or `skill_agent_instructions`. Planner quality proof counts are stored in the artifact and compact tool result: attached candidate count, unmatched evidence count/reasons, selected-with-evidence count, action-like skips, target-hint attachment counts/match kinds, evidence-strength counts, weak-only selected count, cluster evidence counts, and skill-agent prompt length. The skill-agent prompt is structured into role, target skill, candidate metadata, planner decision, selected evidence, allowed tools, hard stops, and expected output.

Evidence target attachment uses deterministic hints before planner reasoning: explicit skill names remain strongest, plugin-bundled aliases can map to an existing mutable local operational skill, path hints can map automation/plugin paths to existing mutable candidates, recurring tool-error clusters are medium-strength pattern evidence, and generic tool classes map to one best matching workflow skill as weak evidence. Hints never grant mutation permission; they only attach evidence to planner and agent context.

## GEPA / DSPy assets

- `evals/proposal/cases.jsonl`: repo-tracked public golden regression cases for proposal scoring (for example repeated tool failure, one-off low evidence, dangerous auto-apply denial, and stale memory review). Plugin users do not mutate this file; runtime/private cases belong under `~/.hermes/self-improvement/evals/proposal/` in later phases.
- `evals/proposal/rubric.json`: `proposal-eval-v0.1` rubric. Hard constraint: `auto_apply: false`.
- `hermes_self_improvement/dspy_program.py`: real DSPy scoring contract / module boundary. Deterministic baseline is retained only for regression fixtures/tests.
- `hermes_self_improvement/gepa_adapter.py`: payload builder, offline fixture evaluation, real DSPy/GEPA evaluator/optimizer boundary, compiled evaluator artifact resolution, and fail-closed error reporting.

Calibration internals call DSPy/GEPA through this adapter. Active evaluator promotion is exposed through `calibrate` and requires regression pass; `calibrate --dry-run` previews without promotion.

Planner/editor/evaluator prompt overlay calibration is a separate runtime-private lane. `calibrate` treats the three roles as one overlay candidate set/generation; each target can still be `changed` or `unchanged`, so promotion does not imply rewriting every role. Dry-run reports compact candidate-set status and writes the full candidate-set artifact under `evaluator/prompt-candidate-sets/` without changing active pointers. Role-level candidates, including materialized default seeds, live under `evaluator/prompt-candidates/`. Mutating `calibrate` can either run fresh GEPA/DSPy optimization or explicitly promote an existing dry-run artifact via `--from-candidate-set /path/to/candidate-set.json`; the explicit artifact path avoids rerunning GEPA and avoids implicitly promoting a stale latest artifact. Promotion writes `active-prompts.json` only after candidate-set acceptance checks pass.

After promotion, `overlay_generation_id` must flow from `active-prompts.json` into prompt source metadata, improve run artifacts, episode records, and later runtime eval cases. Dogfood proof should inspect compact fields and artifact paths rather than pasting full JSON into the conversation. If GEPA returns `no_improvement` / `keep_candidate` with changed targets `0`, preserve behavior; do not weaken acceptance gates to force a promotion.

## Outcome scoring prepass

`improve` writes append-only skill/memory mutation episodes. `calibrate` runs `hermes_self_improvement/outcome_observer.py` before evidence scoring: it reads observations since the previous calibration episode, falls back to the latest improve episode or seven days, and writes attributable `self_improvement_outcome_observation` artifacts under `outcomes/`.

Initial automatic signals are explicit-only: same target re-edit after mutation, recurring `(tool_name, error_kind)` failure clusters tied to episode evidence ids, and user correction events tied to the same target/evidence id. Unmatched observations stay in `outcome-prepass/` artifacts and are not scored. Agent-facing summaries expose only counts, signal totals, and artifact paths.
