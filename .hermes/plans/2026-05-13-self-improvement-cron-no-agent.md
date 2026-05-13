# Self-improvement cron no-agent conversion

**Date:** 2026-05-13

**Goal:** Convert the daily `self-improvement-autonomous-maintenance` cron job from an agent-prompt job into a deterministic script-only `no_agent` job, using the canonical `hermes self-improvement ...` CLI surface.

## Why

The current cron job still runs an outer Hermes agent that reads a long prompt and then calls terminal tools. This is unnecessarily heavy and has previously hit the cron agent inactivity timeout (`idle for 601s`, default 600s). The plugin already owns the decision logic inside `hermes self-improvement calibrate/improve/report`, so the cron job should only invoke those commands directly.

## Scope

In scope:

1. Add a thin script under `~/.hermes/scripts/` that runs:
   - `hermes self-improvement status`
   - `hermes self-improvement calibrate`
   - `hermes self-improvement improve`
   - `hermes self-improvement report --since-hours 24`
2. Set script-only cron timeout high enough for this heavy job.
3. Update cron job `self-improvement-autonomous-maintenance` (`1d8bff2395e2`) to `script=<script>` and `no_agent=true`.
4. Keep delivery local; daily Slack digest remains the user-facing integration.
5. Verify with a read-only smoke (`status`, `report`) and cron definition inspection.

Out of scope:

- Adding new cron jobs.
- Changing the self-improvement planner/editor/evaluator logic.
- Reintroducing `bin/hermes-self-improve`.
- Changing provider/model routing for the plugin internals.
- Running a full mutating self-improvement cycle manually unless explicitly requested.

## Implementation steps

1. Write `~/.hermes/scripts/self-improvement-maintenance.sh`.
   - Use `set -euo pipefail`.
   - `cd ~/.hermes/plugins/hermes-self-improvement`.
   - Print compact section headers and run the four canonical commands.
   - Do not print secrets or full JSON payloads.
2. Make it executable.
3. Configure `cron.script_timeout_seconds` to `3600` unless an equal-or-larger value already exists.
   - This matters because no-agent script jobs use the script timeout, not `HERMES_CRON_TIMEOUT`.
4. Update existing cron job `1d8bff2395e2` with:
   - `script: self-improvement-maintenance.sh`
   - `no_agent: true`
   - `enabled_toolsets: ["terminal", "file"]` can remain harmless but is ignored by no-agent execution.
   - Prompt should be empty/minimal because no-agent ignores it.
5. Verify:
   - `hermes self-improvement status`
   - `bash ~/.hermes/scripts/self-improvement-maintenance.sh` only if we accept that it will run mutating calibrate/improve; otherwise smoke individual read-only commands.
   - `cronjob list` shows `no_agent: true` and the script.
   - `~/.hermes/cron/jobs.json` remains valid JSON.

## Rollback

If the script-only job fails tomorrow:

1. Inspect `~/.hermes/cron/output/` and `~/.hermes/logs/errors.log`.
2. Either fix the script command/path or restore the previous agent-backed job from `~/.hermes/cron/jobs.json` backup if needed.
3. Do not restore `bin/hermes-self-improve`; the canonical surface is `hermes self-improvement`.

## Implementation result

Completed on 2026-05-13.

- Created `~/.hermes/scripts/self-improvement-maintenance.sh`.
- Set executable bit and verified shell syntax with `bash -n`.
- Set `cron.script_timeout_seconds: 3600` in `~/.hermes/config.yaml`.
- Updated cron job `1d8bff2395e2`:
  - `script: self-improvement-maintenance.sh`
  - `no_agent: true`
  - `prompt: ""`
  - schedule remains `0 4 * * *`
  - delivery remains `local`
- Verified:
  - `hermes self-improvement status` passed.
  - `hermes self-improvement report --since-hours 1` passed.
  - `~/.hermes/cron/jobs.json` is valid JSON.
  - `cronjob list` shows the target job as script-only / no-agent.

The mutating full script was not run manually; the next scheduled 04:00 run is the first full script-only execution.

## Success criteria

- [x] The 04:00 job is script-only / no-agent.
- [x] The job no longer depends on an outer LLM agent prompt.
- [x] The script timeout is long enough for the heavy self-improvement cycle.
- [ ] The next daily run output is compact and consumable by `daily-ops-digest`.
