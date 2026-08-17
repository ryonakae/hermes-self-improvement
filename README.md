# hermes-self-improvement

Observe Hermes Agent runtime signals and turn them into evidence-backed improvements for skills, memory, and evaluator prompts.

<!-- README-I18N:START -->

**English** | [日本語](./README.ja.md)

<!-- README-I18N:END -->

An agent tends to repeat its mistakes: the same tool fails the same way across sessions, and the agent forgets a correction you gave last week. `hermes-self-improvement` is a user plugin for [Hermes Agent](https://hermes-agent.nousresearch.com/) that turns those repeated failures into fixes. Lightweight hooks record what actually happened during each session, such as tool failures, memory operations, user corrections, and session outcomes. Later, on its own schedule, the plugin assembles that history into evidence, plans a small set of changes to your skills and memory, and applies the approved ones through official Hermes tools. It also uses [DSPy / GEPA](https://dspy.ai/api/optimizers/GEPA/overview/) to tune the prompts that drive its own internal roles.

## Contents

- [Features](#features)
- [How it works](#how-it-works)
- [Relationship with Curator](#curator-integration)
- [Safety model](#safety-model)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Commands](#commands)
- [Configuration](#configuration)
- [Automation](#automation)
- [Runtime state](#runtime-state)
- [Development](#development)
- [License](#license)

<a id="features"></a>
## Features

- **Runtime observation:** Hooks capture tool failures, memory operations, user corrections, session and subagent outcomes, and LLM/API failure metadata.
- **Evidence-first planning:** Observations are first grouped into evidence packs, deduplicated bundles of related events. The planner then picks a target and proposes a knowledge transaction: a planned change together with its target, edit instructions, and rationale.
- **Tool-mediated editing:** All changes go through constrained Hermes agents and the official `skill_manage` and memory tools, rather than direct file or provider-database writes.
- **Outcome accounting:** Each run leaves behind artifacts, episodes, ledgers, and post-change signals that you can review later.
- **Prompt calibration:** Each role runs on a fixed base prompt plus a tunable overlay. DSPy / GEPA optimizes the planner, editor, and evaluator overlays.
- **Read-only previews:** Both `improve` and `calibrate` accept `--dry-run`.

<a id="how-it-works"></a>
## How it works

```text
[1] Hermes runtime
      ↓
[2] Observation hooks append events to state/events.jsonl
      ↓
[3] Evidence builder creates indexes, detail packs, and diagnostics
      ↓
[4] Planner resolves targets and proposes knowledge transactions
      ↓
[5] Editor applies skill, memory, or user-profile changes through Hermes tools
      ↓
[6] Evaluator records episodes, outcomes, and credit-assignment signals
      ↓
[7] Calibrator optimizes planner/editor/evaluator prompt overlays with DSPy / GEPA
      │
      └─→ Future Hermes runs provide new evidence
```

Four internal roles drive this loop: the **planner** reads evidence and decides what to change, the **editor** applies the change through Hermes tools, the **evaluator** scores plans and outcomes, and the **calibrator** tunes the prompts the other roles run on. For every proposed change, the planner settles on one of four decisions: `apply`, `defer`, `skip`, or `block`.

For example, suppose several sessions show a long-running command being retried while the original process is still alive. The hooks record each failure. On the next `improve` run, the evidence builder groups those events into an evidence pack, the planner proposes patching a local `timeout-workflow` skill with a procedure for telling a polling failure apart from a real timeout, and the editor applies the patch through `skill_manage`. The run artifact records that decision as `apply`, next to everything the planner chose to `defer` or `skip`.

Day to day, you interact with four commands: `improve`, `calibrate`, `report`, and `status`. A fifth command, `setup`, bootstraps the runtime state and is only available from the CLI.

<a id="curator-integration"></a>
## Relationship with Curator

Hermes [Curator](https://hermes-agent.nousresearch.com/docs/user-guide/features/curator) and this plugin have different responsibilities. Curator owns skill usage telemetry, pinning, the `active → stale → archived` lifecycle, and optional consolidation of overlapping skills. `hermes-self-improvement` starts from a wider set of observations, including tool failures, user corrections, memory operations, and run outcomes. Its planner, editor, and evaluator use that evidence to improve skills, memory, the user profile, and evaluator prompts.

The plugin does not replace Curator. It reads Curator and Hermes skill usage, pin, and archive state as the source of truth instead of collecting duplicate telemetry in its hooks. A mutating `improve` run may also apply the same automatic lifecycle transitions as Curator before it loads skill candidates.

When self-improvement runs on a schedule, pause Curator so that two autonomous maintainers do not change the same skill library at different times. Keep Curator enabled.

```bash
hermes curator pause
hermes curator status
```

Pausing stops Curator's scheduled runs while preserving its configuration, telemetry, pin and lifecycle state, and management commands. Setting `curator.enabled: false` loses the operational distinction between a temporary pause and disabling the subsystem, so it is not the recommended integration mode. If you later stop scheduled self-improvement and return to Curator-only automatic maintenance, resume it with:

```bash
hermes curator resume
```

Curator review outcomes may become improvement evidence, but advisory feedback alone never authorizes a change. The plugin still requires its own planner decision and safety checks.

<a id="safety-model"></a>
## Safety model

- Hooks only observe. LLM calls, knowledge mutation, and heavy aggregation all happen later in the `improve` and `calibrate` runners, outside the request path.
- `improve` and `calibrate` mutate state by default. Run them with `--dry-run` until you trust the output, and always preview before scheduling them.
- Skill edits target local mutable skills only. Built-in, hub-installed, plugin-bundled, external, pinned, archived, and ambiguous skills are excluded from mutation.
- Skill edits go through official Hermes tools such as `skill_manage`; the plugin does not write skill files directly.
- Memory edits, including edits to the built-in user profile when Hermes has `memory.user_profile_enabled` on, go through the Hermes memory tool or an explicitly configured provider-native memory tool; the plugin does not touch built-in memory files or provider databases directly.
- Hermes core and the plugin's own source tree, configuration, plans, and bundled skills are not improvement targets.
- There is no rollback pipeline. A failed or weak change becomes evidence for a later improvement run to correct.

<a id="requirements"></a>
## Requirements

- Hermes Agent with user-plugin loading enabled
- Python 3.11 or later
- Git
- A Hermes LLM provider configured for the planner, editor, evaluator, and calibrator roles

The package depends on `dspy>=3.1,<4`, which installs together with the plugin.

The plugin must live as a source checkout under `~/.hermes/plugins`. Installing only the Python wheel is not enough, because Hermes discovers the plugin through the manifest and runtime assets in the checkout.

<a id="installation"></a>
## Installation

Clone the plugin into the Hermes plugin directory and install it into the Python environment that Hermes uses:

```bash
mkdir -p ~/.hermes/plugins
git clone https://github.com/ryonakae/hermes-self-improvement.git \
  ~/.hermes/plugins/hermes-self-improvement
cd ~/.hermes/plugins/hermes-self-improvement
python3 -m pip install -e .
```

Then initialize the runtime state and confirm that Hermes discovers the plugin:

```bash
hermes self-improvement setup
hermes self-improvement status
```

If a Hermes CLI or gateway process was already running, open a new CLI session or restart the gateway after installation.

Observation needs no further wiring: Hermes registers the plugin's hooks automatically, and every session from then on appends events to the log.

<a id="quick-start"></a>
## Quick start

Right after installation the event log is empty, so use Hermes normally for a while before expecting improvement candidates. Start with the read-only commands to see what the observer has collected:

```bash
hermes self-improvement status
hermes self-improvement report --since-hours 24
```

Preview what an improvement run would change:

```bash
hermes self-improvement improve --dry-run
```

Once the preview looks reasonable, apply the changes:

```bash
hermes self-improvement improve
```

Prompt calibration has its own preview:

```bash
hermes self-improvement calibrate --dry-run
```

<a id="commands"></a>
## Commands

| Command | Purpose | Mutates by default |
|---|---|---:|
| `setup` | Initialize runtime directories and seed files | Yes (runtime directories only) |
| `status` | Show observer, runtime, and evaluator state | No |
| `report` | Summarize recent observations and run outcomes | No |
| `improve` | Plan and apply skill or memory improvements | Yes |
| `calibrate` | Optimize prompt-overlay candidates and promote the ones that pass a regression check | Yes |

Every command accepts `--config PATH`, and `--json` switches to machine-readable output. `improve` and `calibrate` support `--dry-run`; `setup --check` verifies the runtime setup without writing anything. `calibrate` promotes a candidate overlay only after it passes a regression evaluation against the stored runtime eval cases; candidates that fail stay on disk as artifacts.

<a id="configuration"></a>
## Configuration

Defaults live in `hermes_self_improvement/config.py`, so you only need a local override when you want to change something:

```bash
cp config.example.yaml config.local.yaml
```

The plugin looks for configuration in this order and uses the first match:

1. An explicit `--config PATH`
2. `HERMES_SELF_IMPROVE_CONFIG`
3. `config.local.yaml`
4. `config.yaml`
5. Built-in defaults

Keep API keys and provider secrets out of the repository; reference environment variables from your local configuration instead.

The plugin splits its LLM usage across four roles, each with its own model key and tool access:

| Key | Responsibility | Tool access |
|---|---|---|
| `model.planner` | Read evidence and produce knowledge transactions | Read-only skill inspection |
| `model.editor` | Apply planner-approved skill and memory changes | Official skill and memory tools only |
| `model.evaluator` | Evaluate plans, mutations, candidates, and outcomes | Tool-free |
| `model.calibrator` | Generate candidates and reflection feedback during GEPA optimization | Tool-free |

Each role accepts `extra_body.reasoning`, and the plugin forwards that reasoning configuration to both constrained and tool-free Hermes agents.

Internal memory-placement reviews run on tool-free Hermes auto routing, so there is no separate `memory_extractor` model key.

See [`config.example.yaml`](./config.example.yaml) for model and calibration overrides.

<a id="automation"></a>
## Automation

Schedule `improve` and `calibrate` as separate jobs. An `improve` run makes a limited number of planner, editor, and evaluator LLM calls and usually finishes within minutes; `calibrate` drives a DSPy / GEPA optimization loop and makes many more LLM calls, so give it a generous timeout. Run both as script-only Hermes cron jobs; these commands do not need an LLM agent wrapped around them.

Example maintenance script:

```bash
#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/.hermes/plugins/hermes-self-improvement"
hermes self-improvement improve
hermes self-improvement report --since-hours 24
```

Example calibration script:

```bash
#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/.hermes/plugins/hermes-self-improvement"
hermes self-improvement calibrate
```

Start with `--dry-run`, read the artifacts each run produces, and only then enable the mutation-capable schedule.

<a id="runtime-state"></a>
## Runtime state

`setup` creates `${HERMES_HOME:-~/.hermes}/self-improvement/`:

```text
${HERMES_HOME}/self-improvement/
  state/events.jsonl
  state/install.json
  daily/
  runs/
  evidence/
  outcomes/
  ledgers/
  evaluator/
    active.json
    active-prompts.json
    prompt-candidates/
    prompt-candidate-sets/
    runtime-eval-cases/
  cache/dspy/
```

Full prompts and detailed evidence stay in the runtime artifacts and `--json` output. Tool responses returned to agents carry only a compact summary and the artifact paths.

<a id="development"></a>
## Development

Read [`AGENTS.md`](./AGENTS.md) for contribution rules and [`skills/operations/SKILL.md`](./skills/operations/SKILL.md) for architecture and safety boundaries.

```bash
git status --short
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e . 'pytest>=9,<10'
python -m py_compile __init__.py hermes_self_improvement/*.py
python -m pytest tests -q
hermes self-improvement status
git diff --check
```

<a id="license"></a>
## License

[MIT License](./LICENSE) © 2026 Ryo Nakae.
