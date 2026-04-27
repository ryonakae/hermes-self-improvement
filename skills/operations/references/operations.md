# Operations notes

Use this reference for scheduled maintenance, plugin discovery checks, memory/custom-skill review, and recurring pitfalls.

## Repository and discovery

- The plugin repo is this repository root.
- When installed as a user plugin, place it under `${HERMES_HOME:-~/.hermes}/plugins/hermes-self-improvement/` or another path supported by Hermes plugin discovery.
- `plugins.enabled` should use the bare plugin name: `hermes-self-improvement`.
- Keep cache/runtime noise out of commits: `__pycache__/`, `.pytest_cache/`, local logs, and synthetic test events.
- After layout changes, verify discovery before editing `config.yaml`; a config change may be unnecessary.

Check plugin manager loading:

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

Depending on Hermes version, plugin-manager registration and top-level CLI exposure can diverge. `ctx.register_cli_command()` may appear in plugin manager internals while `hermes <plugin> ...` is still not accepted by the top-level CLI. Treat that as a CLI/discovery integration gap to investigate, not immediately as a plugin manifest bug. Keep the wrapper CLI operational while investigating.

## Bundled skill discovery

The operational skill is bundled at `skills/operations/SKILL.md` and registered from `register(ctx)` with `ctx.register_skill(child.name, skill_md)`.

Verify with the Python environment used to run Hermes:

```python
get_plugin_manager().list_plugin_skills("hermes-self-improvement")
find_plugin_skill("hermes-self-improvement:operations")
```

Plugin-bundled skills are read-only and may not appear in the active agent session until plugin discovery is reloaded. If a running gateway or long-lived session still behaves as if the old skill is loaded, suspect a reload / restart boundary before suspecting file content.

## Cron / scheduled execution

Cron / scheduled execution belongs to the Hermes runtime / scheduler, not this plugin. The plugin does not implement a scheduler; it provides safe CLI commands and tools that scheduled jobs can call. Scheduled runs should use a fresh session, a self-contained prompt, and must not create recursive cron jobs.

Safe scheduled command set:

```bash
cd /path/to/hermes-self-improvement
bin/hermes-self-improve generate-apply-plan --mode dry_run_plan --since-hours 24 --json --scorer compare
bin/hermes-self-improve ledger-report --mode report_only --status applied --json
bin/hermes-self-improve approval-report --mode report_only --status all --json
```

Do not run `apply-low-risk --confirm-apply` from cron. Do not run `rollback-low-risk --confirm-rollback` from cron. Do not pass `expected_item_hash` or `expected_ledger_hash` in scheduled jobs. Scheduled jobs may mention `hermes cron create` in operator-facing docs, but the job body should only call safe CLI/tools and report artifacts.

Recommended cron prompt:

```text
Target repository: /path/to/hermes-self-improvement

Run the hermes-self-improvement scheduled review in a fresh session.
Do not create, update, or remove cron jobs. Do not schedule recursive cron jobs.
Do not run apply-low-risk. Do not run rollback-low-risk. Do not pass confirmation flags or expected hashes.

From the target repository, run the safe non-mutating commands:
- bin/hermes-self-improve generate-apply-plan --mode dry_run_plan --since-hours 24 --json --scorer compare
- bin/hermes-self-improve ledger-report --mode report_only --status applied --json
- bin/hermes-self-improve approval-report --mode report_only --status all --json

Summarize generated artifact paths, proposal counts, high-confidence low-risk candidates, applied/rolled-back ledger summaries, approval drift/expiry summaries, and any command failures.
```

## Scheduled skill maintenance pattern

For scheduled maintenance jobs that use this plugin:

1. Read the deployment's automation prompt/template if one exists.
2. Read `README.md` and any active repo-tracked plan/docs if the task touches auto-apply policy.
3. From the repository root, run:

```bash
bin/hermes-self-improve report --since-hours 24 --scorer llm
```

4. Confirm proposal rows show `scorer: llm-v0.1`; if they show `heuristic-v0.1` with `llm_scorer_error`, record the fallback reason.
5. Read `${HERMES_HOME:-~/.hermes}/reports/self-improvement/daily/latest.md`.
6. Inspect configured custom skill roots only as needed to ground high-value proposals. Avoid reading every large skill unless evidence points there.
7. Use session recall for recent sessions when available. If recall fails, do not block the job; record the failure and use plugin telemetry from `events.jsonl` as a fallback.
8. Until explicit apply-plan / ledger / approval enforcement is implemented, apply only low-risk fixes and avoid direct untracked `SKILL.md` edits.
9. Report evidence, risk, score/confidence, auto-apply reason, and deferral reason.

## Memory / custom-skill review pattern

When asked whether current memory or custom skills look healthy:

1. Run compare scoring and save JSON for inspection:

```bash
bin/hermes-self-improve analyze --since-hours 24 --scorer compare --json > /tmp/hermes-review-compare.json
```

2. Summarize proposal count, tool error kinds, `llm_score`, `gepa_score`, `score_delta`, and `scorer_disagreements`.
3. Read active built-in memory files when available:
   - `${HERMES_HOME:-~/.hermes}/memories/USER.md`
   - `${HERMES_HOME:-~/.hermes}/memories/MEMORY.md`
4. Compare memory size against the runtime's approximate limits. If near full, recommend compression before adding entries.
5. List configured custom skill roots and inspect only the skills related to high-value proposals.
6. Cross-check proposal claims against actual skill content.
7. Separate recommendations into:
   - LLM/GEPA agreement confirmed by actual files
   - low-evidence or one-off failures
   - memory compression opportunities
   - concrete next edits
8. Do not edit memory or skills during review unless the user explicitly asks.

## Pitfalls

- When invoking `skill_view` / `skill_manage`, use the actual skill name from `available_skills`, not display/category prefixes such as `category:skill-name` or `category/skill-name`. If a category-qualified lookup returns `not_found`, retry the bare skill name before treating it as missing.
- Do not let this skill become the primary policy/design document. Keep auto-apply policy, rollout phases, ledger schema, approval gates, and open design questions in repo-tracked docs / plans.
- Do not copy direct `fixer.py --apply`-style behavior from other projects; direct append-to-skill workflows are unsafe without policy, target hashing, and rollback data.
- Do not rely on `state.db.messages.tool_name`; older Hermes logs may have `tool_name` empty. Prefer plugin telemetry from `post_tool_call` when available.
- If testing hook writes with synthetic events, remove synthetic events from `events.jsonl` afterward.
