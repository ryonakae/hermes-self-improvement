# hermes-self-improvement

Observe Hermes Agent runtime signals and turn them into evidence-backed improvements for skills, memory, and evaluator prompts.

<!-- README-I18N:START -->

**English** | [日本語](./README.ja.md)

<!-- README-I18N:END -->

`hermes-self-improvement` is a user plugin for [Hermes Agent](https://hermes-agent.nousresearch.com/). It records lightweight runtime events, builds evidence packs, plans guarded knowledge changes, applies approved mutations through Hermes tools, and tunes its planner, editor, and evaluator prompt overlays with [DSPy / GEPA](https://dspy.ai/api/optimizers/GEPA/overview/).

## Contents

- [Features](#features)
- [How it works](#how-it-works)
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

- **Runtime observation:** Captures tool failures, memory operations, user corrections, session outcomes, subagent outcomes, and LLM/API failure metadata.
- **Evidence-first planning:** Groups observations into evidence packs before a planner selects a target and knowledge transaction.
- **Tool-mediated editing:** Uses constrained Hermes agents and official `skill_manage` and memory tools instead of direct file or provider-database edits.
- **Outcome accounting:** Stores run artifacts, episodes, ledgers, and post-change signals for later review.
- **Prompt calibration:** Uses DSPy / GEPA to optimize runtime-private prompt overlays for planner, editor, and evaluator roles.
- **Read-only previews:** Supports `--dry-run` for both improvement and calibration workflows.

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

The primary surface is `improve / calibrate / report / status`. `setup` is a CLI-only bootstrap command.

The plugin complements Hermes [Curator](https://hermes-agent.nousresearch.com/docs/user-guide/features/curator). Curator lifecycle and review outcome data can become future evidence, but advisory feedback does not grant auto-apply permission.

<a id="safety-model"></a>
## Safety model

- Hooks are observation-only. They do not call an LLM, mutate knowledge, or run heavy aggregation inside the request path.
- `improve` and `calibrate` are default mutation-capable commands. Use `--dry-run` before enabling scheduled execution.
- Skill changes are limited to local mutable skills. Built-in, hub-installed, plugin-bundled, external, pinned, archived, or ambiguous skills are excluded from mutation targets.
- Skill mutation goes through official Hermes tools such as `skill_manage`; the plugin does not use direct filesystem writes for skill changes.
- Memory mutation goes through the Hermes memory tool or an explicit provider-native memory tool. The plugin does not directly edit built-in memory files or provider databases.
- Hermes core, this plugin's source tree, configuration, plans, and bundled skills are not self-improvement targets.
- Rollback is not a primary feature. Failed or weak changes become future evidence for a later corrective improvement run.

<a id="requirements"></a>
## Requirements

- Hermes Agent with user-plugin loading enabled
- Python 3.11 or later
- Git
- A configured Hermes LLM provider for planner, editor, evaluator, and calibrator calls

The package declares `dspy>=3.1,<4` and installs it with the plugin.

A source checkout under `~/.hermes/plugins` is required. Installing the Python wheel alone does not register this standalone plugin or install its manifest and runtime assets.

<a id="installation"></a>
## Installation

Clone the plugin into the Hermes plugin directory and install it in the Python environment used by Hermes:

```bash
mkdir -p ~/.hermes/plugins
git clone https://github.com/ryonakae/hermes-self-improvement.git \
  ~/.hermes/plugins/hermes-self-improvement
cd ~/.hermes/plugins/hermes-self-improvement
python3 -m pip install -e .
```

Initialize runtime state and verify discovery:

```bash
hermes self-improvement setup
hermes self-improvement status
```

If a Hermes CLI or gateway process was already running, start a new CLI session or restart the gateway after installation.

<a id="quick-start"></a>
## Quick start

Inspect the current state without writing:

```bash
hermes self-improvement status
hermes self-improvement report --since-hours 24
```

Preview an improvement run:

```bash
hermes self-improvement improve --dry-run
```

Apply an improvement run after reviewing the preview:

```bash
hermes self-improvement improve
```

Preview prompt calibration separately:

```bash
hermes self-improvement calibrate --dry-run
```

<a id="commands"></a>
## Commands

| Command | Purpose | Mutates by default |
|---|---|---:|
| `setup` | Initialize runtime directories and seed files | Yes |
| `status` | Show observer, runtime, and evaluator state | No |
| `report` | Summarize recent observations and run outcomes | No |
| `improve` | Plan and apply skill or memory improvements | Yes |
| `calibrate` | Optimize and promote prompt-overlay candidates when gates pass | Yes |

All commands accept `--config PATH`. Add `--json` for machine-readable output. `improve` and `calibrate` accept `--dry-run`; `setup --check` verifies runtime setup without writing.

<a id="configuration"></a>
## Configuration

Defaults live in `hermes_self_improvement/config.py`. Create a local override only when needed:

```bash
cp config.example.yaml config.local.yaml
```

Configuration precedence is:

1. An explicit `--config PATH`
2. `HERMES_SELF_IMPROVE_CONFIG`
3. `config.local.yaml`
4. `config.yaml`
5. Built-in defaults

Do not commit API keys or provider secrets. Use environment-variable references in local configuration.

The four model roles are intentionally separate:

| Key | Responsibility | Tool access |
|---|---|---|
| `model.planner` | Read evidence and produce knowledge transactions | Read-only skill inspection |
| `model.editor` | Apply planner-approved skill and memory changes | Official skill and memory tools only |
| `model.evaluator` | Evaluate plans, mutations, candidates, and outcomes | Tool-free |
| `model.calibrator` | Generate candidates and reflection feedback during GEPA optimization | Tool-free |

Role configs support `extra_body.reasoning`. The plugin forwards that reasoning configuration to both constrained and tool-free Hermes agents.

Internal memory-placement reviews use tool-free Hermes auto routing; `memory_extractor` is not a separate model configuration key.

See [`config.example.yaml`](./config.example.yaml) for model and calibration overrides.

<a id="automation"></a>
## Automation

Run `improve` and `calibrate` as separate jobs: improvement is relatively lightweight, while DSPy / GEPA calibration can take longer. Use script-only Hermes cron jobs rather than placing an LLM agent around these commands.

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

Start with `--dry-run`, inspect the generated artifacts, and only then schedule mutation-capable runs.

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

Full prompts and detailed evidence remain in runtime artifacts and `--json` output. Agent-facing tool responses return compact summaries and artifact paths.

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
