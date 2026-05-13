# native skill-tool editor harness plan

## Goal

`hermes self-improvement improve` の本実行で、planner が editor 対象を選んだあとに `mutation_agent_step_not_json` で止まる問題を解消する。

方針はシンプルにする。

```text
旧: editor LLM に手書き JSON 文字列 protocol を喋らせ、backend が json.loads して tool を代理実行する
新: editor LLM が native tool calling で skill tools を直接呼び、plugin は constrained harness と guardrail だけを担当する
```

この plugin はまだ配布前なので、旧 backend 互換は捨ててよい。`hermes_auxiliary_tool_loop` は廃止し、`native_skill_tool_editor` 相当を唯一の mutation backend にする。

## Current observations

直近の本実行結果:

```text
hermes self-improvement improve

selected for editor: 2
changed 0 skills
reason: mutation_agent_step_not_json
```

artifact:

```text
/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260504T094557Z.json
```

対象候補:

```text
hermes-cron-operations          -> rejected / mutation_agent_step_not_json
hermes-development-maintenance  -> rejected / mutation_agent_step_not_json
```

ファイル変更はなかった。fail-closed は正しいが、実行経路としては弱い。

## Diagnosis

現状の `HermesAuxiliaryMutationBackend` は editor LLM にこういう JSON 文字列を返させている。

```json
{"type":"tool_call","tool":"skill_view","args":{"name":"hermes-development-maintenance"}}
```

plugin はこれを `json.loads(...)` して `skill_view` / `skill_manage` を代理実行する。

これは Hermes の tool calling から見ると不自然。editor LLM にやってほしいのは JSON protocol 生成ではなく、skill を読んで判断し、必要なら skill tool を呼ぶこと。

## Target model

```text
planner LLM
  -> fuzzy / semantic handoff を作る

editor LLM
  -> native tool calling で skill_view / skill_manage を使う
  -> current skill を読んで、重複なら skip、不明なら stop、価値があれば最小変更

harness
  -> editor に渡す tool を skill tools に限定
  -> tool call / action / target / provenance を検査
  -> trace / episode / credit assignment 用に記録
```

### Fuzzy handoff is allowed

planner から editor に渡す内容は、exact patch recipe ではなく semantic intent にする。

```json
{
  "skill": "hermes-development-maintenance",
  "observed_problem": "Repeated patch/read_file failures around ambiguous replacements and missing paths.",
  "desired_outcome": "If current guidance is missing, add or refine reusable troubleshooting guidance.",
  "suggested_focus": [
    "unique patch context",
    "safe replace_all usage",
    "path existence checks before read/patch"
  ],
  "non_goals": [
    "do not rewrite the whole skill",
    "do not duplicate existing guidance",
    "do not edit unrelated skills or files"
  ],
  "evidence_ids": ["..."]
}
```

editor はこれを「証拠付きの意図」として扱う。最終判断は current skill を読んでから行う。

### Hard boundaries remain strict

- editor に渡す tool は以下だけ:
  - `skills_list`
  - `skill_view`
  - `skill_manage`
  - harness-local `submit_mutation_result`
- `skill_manage` action は allowlist のみ。
- target は planner が選んだ mutable local skill のみ。
- pinned / archived / bundled / hub-installed / plugin-bundled / external-dir は mutation 対象外。
- target escape は reject。
- changed があるなら verification notes 必須。
- max tool calls / max iterations / timeout は維持。
- terminal / file / git / browser / delegation / web は渡さない。

## Simplified architecture

### Remove old backend

Remove or replace:

```text
hermes_self_improvement/mutation_backend.py::HermesAuxiliaryMutationBackend
parse_backend_json(...)
hand-written {"type":"tool_call"...} protocol
mutation.backend = hermes_auxiliary_tool_loop
```

Do not keep a fallback unless implementation spike proves native tool calling is impossible.

### Single backend

Use one backend:

```text
NativeSkillToolEditorBackend
```

Config should not expose multiple backend choices for now. If a config key remains, it should only validate the current backend instead of supporting legacy values.

### Final result should be a tool call, not text JSON

Add harness-local finalizer tool:

```text
submit_mutation_result
```

This tool does not mutate anything. It only finalizes the editor run.

Schema:

```json
{
  "success": true,
  "outcome": "applied | skipped_superseded | stopped_stale_target | stopped_conflict | stopped_uncertain_needs_review",
  "reason": "short reason",
  "changed_skills": [],
  "created_skills": [],
  "deleted_skills": [],
  "verification_notes": [],
  "rollback_hints": []
}
```

This avoids final text JSON parsing too.

## Implementation plan

### Step 1: Spike native tool-call shape

Read-only spike first. No skill mutation.

Questions:

- Does `agent.auxiliary_client.call_llm(..., tools=...)` return native tool calls on the current `model.editor` route?
- What is the response shape?
- How should tool result messages be appended for the next call?
- Is direct `call_llm(..., tools=...)` enough, or is a small AIAgent harness simpler?

Preferred outcome: direct auxiliary tool loop is enough.

If `call_llm(..., tools=...)` is not reliable, use a constrained AIAgent only if it can be created without memory/context files and without broad tools.

### Step 2: Implement `NativeSkillToolEditorBackend`

File:

```text
hermes_self_improvement/mutation_backend.py
```

Responsibilities:

1. Build editor messages from semantic task.
2. Pass only tool schemas for:
   - `skills_list`
   - `skill_view`
   - `skill_manage`
   - `submit_mutation_result`
3. Execute `skills_*` tool calls through `SkillToolExecutor.call(...)`.
4. Execute `submit_mutation_result` locally by validating and returning final result.
5. Enforce limits.
6. Return compact structured result with `used_tools` / `tool_trace`.

### Step 3: Delete JSON protocol code

Remove the old parser path instead of hardening it.

Likely deletions / simplifications:

```text
parse_backend_json(...)
HermesAuxiliaryMutationBackend.run() JSON step parser
old tests that assert mutation_agent_step_not_json for non-JSON LLM text
backend config choices for hermes_auxiliary_tool_loop
```

Keep reusable guardrails:

```text
SkillToolExecutor
_validate_tool_call_args
validate_backend_success_result
_task_allowed_targets
MutationBackendLimits
```

Rename errors away from JSON protocol where appropriate:

```text
mutation_agent_step_not_json      -> obsolete
submit_result_missing             -> no finalizer call
native_tool_call_unsupported      -> model/provider cannot tool-call
mutation_agent_limits_exceeded    -> keep
mutation_agent_result_target_escape -> keep
```

### Step 4: Convert planner/editor handoff to semantic task fields

Files:

```text
hermes_self_improvement/planner.py
hermes_self_improvement/runner_steps.py
hermes_self_improvement/mutation_agent.py
```

Change planner prompt/schema to prefer:

```text
observed_problem
desired_outcome
suggested_focus
non_goals
confidence
evidence_ids
```

Keep `change_intent` as a derived compact summary if useful for reports, but stop treating `editor_instructions` as an exact mutation recipe.

### Step 5: Update editor prompt

File:

```text
hermes_self_improvement/mutation_agent.py
```

Prompt should say:

```text
- Use the provided skill tools to inspect the current target.
- Treat planner handoff as evidence-backed intent, not an exact patch command.
- If the skill already covers the point, call submit_mutation_result with a non-mutating outcome.
- If uncertain or stale, stop without mutation.
- If useful, apply the smallest local skill_manage change.
- Finish by calling submit_mutation_result.
```

Do not ask the editor to return JSON text.

### Step 6: Update CLI/report visibility

File:

```text
hermes_self_improvement/cli.py
```

Show rejected/stopped editor outcomes compactly.

Example:

```text
Skill improvements:
- changed 0 skills
- editor stopped: stopped_uncertain_needs_review 1, submit_result_missing 1
```

This is still useful even after native tool calling because changed 0 must explain why.

### Step 7: Tests

#### Backend tests

File:

```text
tests/test_mutation_backend.py
```

Use fake native tool-call responses.

Test cases:

1. `skill_view` -> `submit_mutation_result` no change.
2. `skill_view` -> `skill_manage patch` -> `submit_mutation_result` changed.
3. disallowed tool call is rejected.
4. disallowed `skill_manage` action is rejected.
5. target escape is rejected.
6. missing finalizer returns `submit_result_missing`.
7. max tool calls / iterations enforced.
8. `used_tools` comes from actual tool trace, not self-report.

#### Planner / semantic handoff tests

Files:

```text
tests/test_planner*.py
tests/test_mutation_agent.py
```

Assertions:

- planner prompt asks for semantic fields, not exact patch recipe.
- editor prompt says planner handoff is intent, not command.
- editor prompt requires reading current skill before mutation.
- editor prompt requires finalizer tool call.

#### CLI summary tests

File:

```text
tests/test_cli_surface.py
```

Assertions:

- stopped/rejected reason counts appear in non-JSON summary.
- output remains compact.
- `--json` still returns artifact payload.

### Step 8: Validation

Focused:

```bash
python3 -m py_compile __init__.py hermes_self_improvement/*.py
python3 -m pytest tests/test_mutation_backend.py tests/test_mutation_agent.py tests/test_cli_surface.py -q
python3 -m pytest tests/test_planner*.py -q
```

Full:

```bash
python3 -m pytest tests -q
```

Read-only smoke:

```bash
hermes self-improvement improve --dry-run --since-hours 1 --scorer heuristic
```

Mutating smoke only after confirmation:

```bash
hermes self-improvement improve --since-hours 1 --scorer heuristic
```

## Risks

### Native tool calling may not work on every provider

Because this is pre-distribution, do not keep legacy JSON protocol just for compatibility. Instead:

- fail clearly with `native_tool_call_unsupported`
- document that `model.editor` must support tool calling
- optionally choose a default editor model known to support tool calls

### Full AIAgent harness may bring too much context/tool surface

Prefer direct `call_llm(..., tools=...)` loop. If AIAgent is needed:

- disable memory/context files
- restrict tool schemas to skill tools + finalizer
- verify no terminal/file/git/web/delegation tools are present

### Editor may over-edit

Mitigations:

- target validation
- skill action validation
- final result target escape validation
- prompt says smallest local change only
- editor can stop non-mutatingly

## Non-goals

- No prose+JSON parser.
- No legacy `hermes_auxiliary_tool_loop` compatibility.
- No terminal/file/git/browser/delegation tools for editor.
- No arbitrary docs/config/runtime mutation.
- No Hermes core changes unless direct auxiliary tool calling is impossible and constrained AIAgent cannot be built plugin-side.
- No `skill_manage(action="archive")`.
- No archive lifecycle change.

## Expected outcome

The editor LLM no longer has to speak a bespoke JSON string protocol. It uses native tool calling like a normal constrained tool-using agent.

```text
planner gives fuzzy evidence-backed intent;
editor reads the current skill and decides;
harness allows only safe skill tools and records what happened.
```

The implementation becomes simpler conceptually:

```text
one mutation backend
native tool calls only
local finalizer tool for structured result
no parser hardening rabbit hole
```
