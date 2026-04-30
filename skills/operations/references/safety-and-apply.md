# Safety and mutation boundaries

This plugin improves only four target classes:

- local mutable skills
- memory facts/preferences/environment notes
- scorer rubric/prompt behavior
- evaluator/runtime-private eval cases

Primary commands:

```bash
bin/hermes-self-improve improve
bin/hermes-self-improve improve --dry-run
bin/hermes-self-improve calibrate
bin/hermes-self-improve calibrate --dry-run
bin/hermes-self-improve report --since-hours 24
bin/hermes-self-improve status
```

## Mutation intent

`improve` and `calibrate` are mutation-capable by default. `--dry-run` is the explicit preview mode. Internal gates remain fail-closed: evidence, target scope, provider capability, regression, and tool availability can still produce no-op results.

## Skill safety

Skill changes must go through official skill tools only. The runner may use `skills_list`, `skill_view`, and `skill_manage`; it must not use terminal, file tools, git, browser, direct filesystem access, provider internals, or arbitrary repo docs/config mutation.

Allowed skill targets are mutable local user/Hermes-created skills. Built-in, hub-installed, plugin-bundled, external-dir, pinned, ambiguous, or stale targets are rejected or skipped.

## Memory safety

Memory changes must go through memory/provider tools only. Do not edit built-in memory files, provider databases, provider internals, USER.md, or MEMORY.md directly from the runner.

Provider capability decides the executable operation. Unsupported delete/replace requests become provider-compatible correction/add operations only when safe and non-sensitive; otherwise they fail closed. Sensitive/secret/PII deletes require provider-native delete identity and must not be represented by correction text that repeats the secret.

## Scorer/evaluator safety

Scorer/evaluator self-improvement is advisory and regression-gated. Runtime-derived eval cases are stored under `${HERMES_HOME:-~/.hermes}/self-improvement/gepa/runtime-eval-cases/` and are not written into repo-tracked `evals/proposal/`.

DSPy/GEPA dependencies stay lazy. Hook and plugin discovery paths must not import heavy optional dependencies.

## Removed primary surface

Do not reintroduce primary `plan`, `apply`, `rollback`, `outcome`, `record_outcome`, `--execute`, item selection, or hash-confirmation commands/tools. Historical modules may remain temporarily as internal compatibility or evidence readers until a cleanup slice deletes them, but normal user-facing docs and output should describe only the four-command surface above.
