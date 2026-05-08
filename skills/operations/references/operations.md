# Operations

Use the repository-local wrapper CLI. The mutation-capable runner surface is intentionally small; `setup` is a safe CLI-only runtime bootstrap:

```bash
bin/hermes-self-improve setup
bin/hermes-self-improve setup --check
bin/hermes-self-improve setup --reset
bin/hermes-self-improve setup --reset --yes
bin/hermes-self-improve status
bin/hermes-self-improve report --since-hours 24
bin/hermes-self-improve improve
bin/hermes-self-improve improve --dry-run
bin/hermes-self-improve calibrate
bin/hermes-self-improve calibrate --dry-run
```

Semantics:

- `setup` creates `${HERMES_HOME:-~/.hermes}/self-improvement` runtime directories, default evaluator assets, `evaluator/active.json`, and prompt-overlay runtime state paths such as `evaluator/active-prompts.json`. If no valid active prompt overlay exists for the current base prompt hashes, it materializes repo seed Markdown from `defaults/prompt-overlays/` into runtime-private overlay candidates. It does not call LLMs, GEPA, skill mutation, or memory mutation.
- `setup --check` is read-only.
- `setup --reset` is destructive for the runtime directory only. It asks for y/N confirmation on an interactive terminal and fails non-interactively unless `--yes` is passed.
- `improve` is mutation-capable by default, but internal runner gates still decide whether anything changes.
- `improve --dry-run` builds evidence and run artifacts without mutation. Normal CLI output and agent tool result are compact; full details belong in the run artifact or CLI `--json`.
- `calibrate` may promote scorer/evaluator state or runtime-private prompt overlay sets only when evidence and required gates pass. Before scoring, it also runs an outcome prepass over observations since the previous `calibrate`.
- `calibrate --dry-run` previews calibration and writes candidate-set artifacts without writing active evaluator/overlay state. The outcome prepass still writes compact outcome/prepass artifacts so the evidence summary reflects newly attributable observations.
- `calibrate --from-candidate-set /path/to/candidate-set.json` explicitly evaluates and promotes/rejects that artifact without rerunning GEPA/DSPy. Do not auto-discover the latest dry-run artifact.
- `report` and `status` are read-only.

Do not schedule or reintroduce legacy approval / low-risk / hash-confirmation commands. `plan`, `apply`, `rollback`, `outcome`, `record_outcome`, item selection flags, hash confirmation flags, and old GEPA-specific primary commands are not part of the surface.

User and runtime feedback are evidence for future runs. Reports summarize review/outcome signals, but feedback never grants unattended mutation permission.

Validation after code or docs changes:

```bash
python -m py_compile __init__.py hermes_self_improvement/*.py
python -m pytest tests -q
bin/hermes-self-improve status
bin/hermes-self-improve improve --dry-run
bin/hermes-self-improve calibrate --dry-run
bin/hermes-self-improve calibrate --from-candidate-set /path/to/candidate-set.json
```
