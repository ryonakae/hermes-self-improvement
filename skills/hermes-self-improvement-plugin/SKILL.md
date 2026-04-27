---
name: hermes-self-improvement-plugin
description: Hermes の自己改善 plugin（`hermes-self-improvement`）を設計・実装・拡張・検証するときに使う。runtime hook で観測だけを収集し、分析・proposal・score・report は wrapper CLI / cron から実行する構成、telemetry、GEPA/LLM scorer の安全な接続を扱う依頼では必ず参照する。
---

# hermes-self-improvement plugin

Hermes の skill / memory / prompt / tool-use workflow を継続改善するための user plugin を扱う手順。

## 基本方針

- Hermes 本体や upstream-managed code は直接編集しない。
- plugin runtime の hook は観測専用にする。
- hook 内で LLM 呼び出し、GEPA 実行、skill patch、memory edit、重い集計をしない。
- 問題抽出・候補生成・採点・report 作成は wrapper CLI / cron / offline evaluator から実行する。
- 無人 cron で自動適用できる変更は low-risk のみに限定する。
- skill / memory の意味を変える変更、rename / merge / delete / 大幅 rewrite / trigger description の大幅変更は proposal に留める。
- 方針・設計判断・段階的ロードマップ・未決事項は skill に積み増しすぎない。repo-tracked plan / docs に計画を書き、安定した内容は repo docs に昇格する。skill は実行時に必要な短い運用手順と参照先に留める。

## 主要パス

- plugin repo: this repository root.
- manifest: `plugin.yaml`
- registration / compatibility entrypoint: `__init__.py`
- config module: `config.py`
- observer module: `observer.py`
- analysis module: `analysis.py`
- scoring module: `scoring.py`
- apply plan module: `apply_plan.py`
- ledger module: `ledger.py`
- CLI/report module: `cli.py`
- local config JSON: `config.json`
- wrapper CLI: `bin/hermes-self-improve`
- telemetry: `${HERMES_HOME:-~/.hermes}/reports/self-improvement/state/events.jsonl`
- reports: `${HERMES_HOME:-~/.hermes}/reports/self-improvement/daily/latest.md`

## Current implementation notes

The initial plugin observes these hooks:

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

It stores redacted previews and hashes, not full sensitive payloads. Sensitive paths and credential-looking values should be redacted before writing JSONL.

Retention / classifier notes:

- `retention_days` is enforced by `RuntimeObserver` before the first event write in a process. Old timestamped rows are pruned, malformed JSON rows are dropped, and rows with missing/unparseable timestamps are kept for manual inspection.
- Tool result classification must prefer structured success/error fields over searching raw content text. Successful `read_file`, `search_files`, `skill_view`, `skills_list`, and `patch` payloads may legitimately contain words like "timeout", "not found", or "permission denied" in documentation/code snippets; those should not become failure clusters. Analysis also reclassifies historical `post_tool_call` rows from `result_preview` without rewriting JSONL, including truncated success previews such as `{"success": true`, `{"total_count":`, or `{"content":`.
- Findings should cluster by `(tool_name, error_kind)` rather than tool alone. Proposals should be remediation-oriented and deduplicate equivalent fixes, e.g. merge `permission_denied` clusters from terminal/process/execute_code into one sandbox/access-policy proposal.

The wrapper CLI supports:

```bash
bin/hermes-self-improve status
bin/hermes-self-improve analyze --since-hours 24
bin/hermes-self-improve analyze --since-hours 24 --scorer llm --json
bin/hermes-self-improve analyze --since-hours 24 --scorer gepa --json
bin/hermes-self-improve analyze --since-hours 24 --scorer compare --json
bin/hermes-self-improve gepa-eval --json
bin/hermes-self-improve report --since-hours 24 --scorer llm
bin/hermes-self-improve run --since-hours 24 --json --scorer llm
```

Scorer behavior:

- default: `--scorer heuristic` (`heuristic-v0.1`).
- LLM: `--scorer llm` uses Hermes `agent.auxiliary_client.call_llm()` through the `skills_hub` auxiliary task and returns `llm-v0.1` scores when successful.
- LLM failures fall back to heuristic scores with `llm_scorer_error` on each proposal.
- GEPA: `--scorer gepa` routes through `gepa_adapter.py`. With the default safe config (`gepa_scorer.enabled=true`, `max_iterations=0`), it runs the dependency-free offline `ProposalBatchScoringProgram` and returns `gepa-v0.1` advisory scores. Disabled config still fails closed and falls back to heuristic via `gepa_scorer_error`.
- `gepa-eval --json` runs the bundled offline scorer regression cases and reports pass/fail checks for score range, recommendation, risk, confidence floor, and `auto_apply`.
- Offline GEPA scores include `score_breakdown` for rubric dimensions (`evidence_strength`, `reuse_value`, `operational_safety`, `specificity`, `verification_plan`); Markdown reports show compact `level points/weight` summaries.
- GEPA optimizer runs (`max_iterations > 0`) are still not production-wired; they require a concrete DSPy/GEPA metric/invocation and should fail closed until implemented and validated.
- `--scorer compare` runs both LLM and GEPA scoring, then records `llm_score`, `gepa_score`, `score_delta`, and `scorer_disagreements` (`score_gap`, `recommendation_mismatch`, `risk_mismatch`, `confidence_mismatch`). Disagreements force `human_review`, keep `auto_apply: false`, and should be treated as maintenance review signals rather than automatic apply permission.
- GEPA offline scorer calibration intentionally downranks `unknown_error`, low-evidence `not_found`, and generic `review_existing_skill_or_add_pitfall` proposals unless they include concrete remediation, examples, and a verification plan. It counts evidence from findings matching the proposal's `tool_name` / `error_kind` rather than letting unrelated high-volume clusters inflate the score. This prevents repeated but vague telemetry clusters from all scoring as high-value skill changes.
- GEPA evaluation assets live in the plugin directory: `evals/proposal_eval_cases.jsonl` contains regression cases, `evals/rubric.json` contains rubric `proposal-eval-v0.1`, and `dspy_program.py` contains dependency-free `ProposalScoringProgram` / `ProposalBatchScoringProgram` scaffolds used by the offline scorer and future DSPy/GEPA wiring.
- LLM and GEPA scoring are advisory only; they always force `auto_apply: false` and must not be treated as permission for unattended skill/memory edits.
- Auto-apply roadmap: the current operating scope is B/C — allow only low-risk existing-skill additions/fixes such as small pitfall/validation additions, typo fixes, and obvious stale path or stale command corrections after checking telemetry evidence and the target skill. Stale path / stale command is auto-applicable only when the old path/command check fails and the current canonical replacement is confirmed by another source such as active memory, README, config, or an existing file. Memory cleanup remains review-only for now. Future target is broader C/D, meaning memory compression/deduplication and eventually skill creation/merge/rename/delete, but those require stronger dry-run plans, rollback ledgers, and human-approval gates before unattended execution.
- Change history policy: most custom skills under configured `custom_skill_roots` are not git-managed. For non-git-managed skills, auto-apply must write a timestamped local change ledger with before/after snippets and rollback data instead of pretending a git commit exists. If a target skill is inside a git repository, make a local commit after successful low-risk auto-apply and do not push.

Current Hermes top-level plugin CLI discovery does not expose this as `hermes self-improvement`; cron should use the wrapper CLI instead.

Execution mode / policy gate implementation notes:

- Use TDD for mode-policy work. Add tests under `hermes-self-improvement/tests/` before changing `__init__.py`; confirm failures are missing behavior, then implement minimally.
- Keep `execution_mode` enforcement inside plugin CLI/config/policy, not cron prompts. Cron prompts may describe mode, but plugin code must reject disallowed commands/capabilities.
- Default mode is `report_only`; active modes are `report_only`, `dry_run_plan`, `apply_low_risk`, and `apply_approved`. Keep `full_auto_with_policy` reserved until policy/ledger/approval enforcement is mature.
- Model mode policy as command allowlists plus capability flags, and deny by default. Unknown mode, unknown command, or missing capability should fail closed with a structured reason such as `unknown_execution_mode`, `command_not_allowed`, or `capability_not_allowed`.
- Existing read/report commands (`status`, `analyze`, `report`, `run`, `gepa-eval`) should remain usable in `report_only`; do not break current cron/report workflows while adding future mutation gates.
- Add dry-run planning as a separate safe slice before any mutation work. Implement `generate-apply-plan` in `dry_run_plan` mode, require a `write_apply_plan` capability, and write versioned JSON artifacts under `${HERMES_HOME:-~/.hermes}/reports/self-improvement/apply-plans/YYYY-MM-DD/`. Apply-plan artifacts should start conservative: schema metadata, `created_by`, `execution_mode`, summary/items, and all mutation/apply fields disabled or approval-required until ledger/approval/rollback enforcement exists. Eligible dry-run items should include rollback preview metadata (before/after hash and snippets) so later pending ledgers can be written from verified preview data instead of re-inferring rollback state. `build_pending_ledger` / `write_pending_ledger` can now create and save proposal-level pending ledger JSON. `apply-low-risk <plan-id> <item-id>` currently runs a non-mutating skeleton: it loads the explicit plan item, checks eligibility and target hash, writes an apply-attempt artifact, records `planned_diff` and `validation_plan` for `would_apply_low_risk`, and leaves target files unchanged. When the result is `would_apply_low_risk`, it also writes a pending ledger and records `pending_ledger_path` / `pending_ledger_hash` on the attempt; `stale_plan` and `rejected` attempts do not create ledgers or planned diffs.
- When strengthening apply-plan item schema, use TDD to lock down fail-closed behavior. Items should carry stable metadata such as `change_type`, `target_kind`, `target_path`, `target_exists`, `before_hash`, `proposal_hash`, `item_hash`, `eligibility`, `evidence`, `ledger_preview`, and `scorer_disagreements`. Resolve `before_hash` from the target file when `target_path` points at an existing file. Classification may identify low-risk types like pitfall/validation/typo, but missing target path, missing target file, missing mutation plan, unknown change type, or scorer disagreement must keep `eligible_for_unattended=false`. The first mutation planner slice only creates `append_to_existing_section` mutations for `pitfall_addition_existing_section` when the target already has a Pitfalls/注意系 section; otherwise fail closed with `existing_section_missing`. Target resolution should stay explicit: direct path hints win, otherwise resolve only `target_skill` / `skill_name` / `skill` under configured `custom_skill_roots`; reject absolute names, `..`, and root escapes, and do not infer targets from prose titles.
- After implementing mode-policy or apply-plan changes, verify with full plugin tests, `py_compile`, `bin/hermes-self-improve status --mode dry_run_plan`, a read-only `run --mode dry_run_plan --json` smoke test, and when apply-plan code changes, `bin/hermes-self-improve generate-apply-plan --mode dry_run_plan --since-hours 1 --json --scorer heuristic` plus a JSON check that the artifact path exists and schema metadata is correct.

## Repository / discovery notes

- The `hermes-self-improvement` plugin repo is this repository root.
- When installed as a user plugin, place it under `${HERMES_HOME:-~/.hermes}/plugins/hermes-self-improvement/` or another path supported by Hermes plugin discovery.
- `plugins.enabled` should use the bare plugin name (`hermes-self-improvement`).
- Keep cache/runtime noise in `.gitignore` and avoid committing `__pycache__/` or `.pytest_cache/`.
- After layout changes, verify discovery with `PluginManager().discover_and_load(force=True)` before editing `config.yaml`; a config change may be unnecessary.
- When comparing a plugin against the official docs, check both plugin-manager registration and user-facing CLI exposure. Depending on the Hermes version, `ctx.register_cli_command()` can appear in `get_plugin_manager()._cli_commands` / `list_plugins()` while `hermes <plugin> ...` is still not accepted by the top-level CLI, and `hermes plugins list` may omit nested user plugins even when `discover_plugins(force=True)` loads them. Treat that as a Hermes CLI/discovery integration gap to investigate, not immediately as a plugin manifest/register bug. Keep using the wrapper CLI for operational commands until top-level CLI exposure is verified.
- The operational skill is also bundled in the plugin at `skills/hermes-self-improvement-plugin/SKILL.md` and registered from `register(ctx)` with `ctx.register_skill(child.name, skill_md)`. Verify with the Python environment used to run Hermes: `get_plugin_manager().list_plugin_skills("hermes-self-improvement")` and `find_plugin_skill("hermes-self-improvement:hermes-self-improvement-plugin")`. Plugin-bundled skills are read-only and may not appear in the current already-running agent session's `<available_skills>` / `skill_view` until plugin discovery is reloaded, so keep the custom skill as a discoverability/compatibility copy until that behavior is intentionally changed.

## Validation checklist

After changing the plugin:

1. Compile all plugin modules touched by the refactor. Use the Python environment that has Hermes and test dependencies installed.

```bash
PY=${PYTHON:-python3}
$PY -m py_compile __init__.py *.py
```

2. Run the full plugin test suite before any commit.

```bash
cd /path/to/hermes-self-improvement
PY=${PYTHON:-python3}
$PY -m pytest tests -q
```

3. Check standalone CLI.

```bash
bin/hermes-self-improve status
bin/hermes-self-improve report --since-hours 24
```

4. Check plugin manager loading. This is mandatory after any `__init__.py` / module-layout refactor, because unit tests and the wrapper CLI can pass even when plugin discovery fails. In particular, verify that `register(ctx)` still exists in `__init__.py`; an over-broad extraction can accidentally remove it and discovery will report `no register() function`.

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

Expected: enabled true, error null, hooks > 0.

5. If testing hook writes with synthetic events, clean up synthetic events from `events.jsonl` afterward.

## Cron integration pattern

Official Hermes cron docs matter for this plugin. Cron jobs run in fresh agent sessions, must have self-contained prompts, cannot ask clarifying questions, and have the `cronjob` toolset disabled as a recursion guard. Job config covers scheduling/delivery/runtime fields such as prompt, schedule, skills, deliver, script, workdir, enabled_toolsets, model, and provider; do not treat natural-language cron prompts or undocumented arbitrary job metadata as a policy enforcement channel.

Responsibility split:

- Cron job prompt/config: when to run, which wrapper CLI command to call, delivery target, report framing, attached skills, script/workdir/toolsets, and a short human-readable policy summary/reference.
- Plugin CLI/config/policy: execution mode, allowlists, thresholds, approval gates, apply-plan generation, ledgers, apply-attempts, approvals, and safe apply enforcement.

For scheduled skill maintenance, prefer this sequence:

1. Read the automation prompt/template for the deployment, if one exists.
2. Read `README.md` and the active repo-tracked plan/docs if the task touches auto-apply policy.
3. From the repository root, run:

```bash
bin/hermes-self-improve report --since-hours 24 --scorer llm
```

Confirm proposal rows show `scorer: llm-v0.1`; if they show `heuristic-v0.1` with `llm_scorer_error`, record the fallback reason in the maintenance report.

4. Read `${HERMES_HOME:-~/.hermes}/reports/self-improvement/daily/latest.md`.
5. Inspect configured custom skill roots such as `${HERMES_HOME:-~/.hermes}/skills/**/SKILL.md` only as needed to ground high-value proposals.
6. Use `session_search` for recent sessions. If `session_search` fails (for example `database disk image is malformed`), do not block the cron job; record the failure and use plugin telemetry (`${HERMES_HOME:-~/.hermes}/reports/self-improvement/state/events.jsonl`) to extract recent `session_id`, platform, `user_message_preview`, and tool summaries as a fallback.
7. If the Markdown report does not show proposal `scorer` fields, run `analyze --since-hours 24 --scorer llm --json` and confirm each proposal uses `scorer: "llm-v0.1"`, or `scorer: "heuristic-v0.1"` with `llm_scorer_error` when LLM scoring failed.
8. Until the plugin has explicit apply-plan/ledger/approval enforcement, apply only low-risk fixes with `skill_manage`; do not directly edit `SKILL.md`.
9. Include evidence, risk, score/confidence, auto-apply reason, and deferral reason in the final maintenance report.

## GEPA / LLM scorer direction

Use GEPA or LLM scoring as candidate comparison / evaluation only. Do not let GEPA output directly patch production skills or memory. A safe flow is:

```text
telemetry -> analyze -> proposals -> score/rubric -> optional GEPA candidate comparison -> report -> human review or low-risk apply
```

GEPA manual-eval assets:

- `evals/proposal_eval_cases.jsonl`: regression cases for repeated tool failure, one-off low evidence, dangerous auto-apply denial, and stale memory review.
- `evals/rubric.json`: rubric `proposal-eval-v0.1` with dimensions `evidence_strength`, `reuse_value`, `operational_safety`, `specificity`, and `verification_plan`; hard constraint `auto_apply: false`.
- `dspy_program.py`: dependency-free `ProposalScoringProgram` / `ProposalBatchScoringProgram` scaffold. It is intentionally importable without DSPy so tests and cron fallback stay stable.

Good first eval targets:

- scheduled skill maintenance prompt and policy quality.
- Whether a proposed skill change has enough evidence.
- Whether a new skill candidate is actually reusable or should be merged into an existing skill.

## Ad-hoc memory / custom-skill review pattern

When the user asks whether current memory or custom skills look healthy, run the plugin in review-only mode and then ground the proposals in the actual files before recommending edits.

1. Run compare scoring and save JSON for inspection:

```bash
bin/hermes-self-improve analyze --since-hours 24 --scorer compare --json > /tmp/hermes-review-compare.json
```

2. Summarize proposal count, tool error kinds, and each proposal's `llm_score`, `gepa_score`, `score_delta`, and `scorer_disagreements`. Treat large LLM/GEPA gaps as review signals, not as permission to patch.
3. Read active built-in memory files and measure size / entry count:
   - `${HERMES_HOME:-~/.hermes}/memories/USER.md`
   - `${HERMES_HOME:-~/.hermes}/memories/MEMORY.md`
   Compare them against the official approximate limits (`USER.md` 1375 chars, `MEMORY.md` 2200 chars). If near full, recommend compression before adding new entries.
4. List custom skills under configured custom skill roots, for example `${HERMES_HOME:-~/.hermes}/skills/*/SKILL.md`, then inspect only the skills related to high-value proposals. Avoid reading every large skill unless the evidence points there.
5. Cross-check proposal claims against actual skill content. For example:
   - sandbox / permission-denied proposals should be checked against the relevant access-policy and auth guidance for the deployment.
   - skill lookup namespace misses should be checked against skill preload / self-improvement guidance.
   - terminal timeout and patch validation proposals should be treated as small pitfall additions unless repeated evidence is strong.
6. Report separately:
   - proposals where LLM and GEPA agree and actual files confirm the gap;
   - proposals where GEPA appears to overrate low-evidence `not_found` / one-off failures;
   - memory compression opportunities;
   - concrete next edits, if any.
7. Do not edit memory or skills during this review unless the user explicitly asks. The safest default is "review only, then recommend prioritized changes".

## Pitfalls

- When invoking `skill_view` / `skill_manage`, use the actual skill name from `available_skills`, not display/category prefixes such as `category:skill-name` or `category/skill-name`. If a category-qualified lookup returns `not_found`, immediately retry the bare skill name before treating it as a missing skill.
- Do not let this skill become the primary policy/design document. For auto-apply policy, rollout phases, ledger schema, approval gates, and open design questions, create or update a repo-tracked `/plan` / docs file under the active plugin repository, then keep this skill as a concise operational index that points to those docs.
- Do not use `dojo` as a directory or feature name here; prior investigation treated hermes-dojo as a reference only.
- Do not copy hermes-dojo `fixer.py --apply` behavior; direct appending to `SKILL.md` is unsafe.
- Do not rely on `state.db.messages.tool_name`; older Hermes logs may have `tool_name` empty. Prefer plugin telemetry from `post_tool_call` when available.
- Hermes can emit an early/partial `pre_tool_call` without `session_id` / `tool_call_id`, followed by the complete event. Drop those partial `pre_tool_call` rows at write time and defensively filter historical partial rows in `analyze_events`; otherwise report counts get inflated and empty-session noise appears.
- Remember that enabling or changing plugin hook code may require gateway restart before live messaging sessions use the new observer. CLI `analyze` / `report` reads current files immediately, but the running gateway may still hold the old plugin instance.
- When unit-testing this plugin with `importlib.util.module_from_spec`, insert the module into `sys.modules[spec.name]` before `exec_module`; otherwise the `@dataclass` processing can fail with `AttributeError: 'NoneType' object has no attribute '__dict__'`.
