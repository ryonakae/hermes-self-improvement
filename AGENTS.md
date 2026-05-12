# AGENTS.md

`hermes-self-improvement` は、Hermes runtime の観測イベントから skill / memory / evaluator の改善材料を作る user plugin です。hook は観測専用です。mutation は `improve` / `calibrate` runner で扱います。初めて触るときは、まず `README.md` で全体像を確認してください。

## 進め方

TDD で進めてください。新規機能 / 振る舞い変更は、先に失敗するテストを `tests/` に追加してから実装に着手します。リファクタや純粋なリネームのときも、既存テストが緑のまま意図を担保できることを変更前後に `pytest -q` で確認してください。

## 着手前チェック

```bash
git status --short
bin/hermes-self-improve status
```

- 無関係な変更を戻さないでください。
- まず `README.md` と該当 `.hermes/plans/` を確認してください。
- 安全境界を触る場合は `skills/operations/SKILL.md` と関連 reference を先に読んでください。

## よく使うコマンド

```bash
bin/hermes-self-improve setup --check
bin/hermes-self-improve status
bin/hermes-self-improve report --since-hours 24
bin/hermes-self-improve improve --dry-run
bin/hermes-self-improve calibrate --dry-run
bin/hermes-self-improve improve
bin/hermes-self-improve calibrate
```

上から read-only、dry-run、mutation-capable の順です。`improve` と `calibrate` は既定で変更可能なので、確認だけなら `--dry-run` を付けてください。

CLI の primary runner/tool surface は `improve / calibrate / report / status` の4つです。`setup` は CLI-only の安全な runtime bootstrap で、agent tool には出しません。`plan / apply / rollback / outcome`、`--execute`、item/hash 指定 flag、legacy/debug command は primary surface に戻しません。

## 検証

通常変更後:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
bin/hermes-self-improve status
git diff --check
```

Tool schema / registration を触った場合:

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

期待値は plugin enabled、error null、tools 4。

## 安全境界

- Runtime hook 内で LLM call、GEPA optimizer、skill patch、memory edit、重い集計を動かさない。
- 改善対象は `skill`, `memory`, `evaluator` だけ。
- `improve` の semantic decision は `apply / defer / skip / block` に寄せる。内部互換の `run_editor` などは残してよいが、新しい apply mode、承認キュー、別 lane は増やさない。
- Conversation-derived memory gap は改善対象。キーワードは window ranking にだけ使い、semantic gate にしない。
- plugin 自身の README / AGENTS / config / plans / bundled skill、Hermes core、任意 docs/config は自己改善対象にしない。
- skill mutation は `skill_manage` など公式 skill tools 経由だけ。direct filesystem fallback は使わない。既存 skill の patch/archive は Hermes-created local mutable skill だけを候補にし、built-in / hub-installed / plugin-bundled / external-dir / ambiguous provenance は LLM-facing candidate list に載せない。観測から durable な手順不足が明確で、既存 Hermes-created skill に受け皿がない場合だけ `skill_manage(action="create")` 経由の新規 skill 作成を許可する。
- memory mutation は memory tool / provider-native memory tool 経由だけ。built-in memory file や provider DB を直接編集しない。CLI/standalone 実行でも Hermes 公式 `tools.memory_tool.MemoryStore` を読み込んで `memory_tool(..., store=store)` として実行する。built-in memory が満杯なら `current_entries` を使って統合・削除を検討し、`replace/remove` 後に `add` を再試行する。それでも満杯なら active external provider がある場合だけ provider tool に fallback する。Hindsight 固定にしない。
- `improve` / `calibrate` は default mutation-capable。preview-only は `--dry-run`。
- rollback は primary feature ではない。失敗は future evidence として correction する。
- plugin の自己改善対象は target repo の commit を作らない。repo 内の実装・docs を手作業で変更した場合は、作業者の workflow で commit する。

## 重要パス

- `README.md`: plugin の目的、surface、runner、安全境界
- `plugin.yaml`: plugin manifest
- `__init__.py`: root の thin plugin entrypoint
- `hermes_self_improvement/cli.py`: CLI parser と runner orchestration
- `hermes_self_improvement/schemas.py`: plugin tool schema
- `hermes_self_improvement/tool_handlers.py`: plugin tool handlers
- `hermes_self_improvement/observer.py`: hook observer、redaction、JSONL telemetry
- `hermes_self_improvement/llm_telemetry.py`: plugin 自身の LLM 呼び出し計測 (`self_improvement_llm_call` を `state/events.jsonl` に追記)
- `hermes_self_improvement/prompt_cache.py`: 各 LLM 呼び出しに anthropic `cache_control` 注入と OpenAI/Codex 用 `prompt_cache_key` を付与する `apply_caching` ヘルパー
- `hermes_self_improvement/evidence.py`: event aggregation / evidence extraction / context windows / unmatched improvement candidates
- `hermes_self_improvement/target_resolver.py`: LLM target resolution for unmatched evidence
- `hermes_self_improvement/memory_extractor.py`: conversation window ranking and memory gap candidates (LLM site `memory_extractor`)
- `hermes_self_improvement/improvement_planner.py`: planner that ranks skill candidates and routes memory/evaluator decisions (LLM site `improvement_planner`)
- `hermes_self_improvement/skill_agent.py`: skill mutation agent runner / prompt builder / result parser (LLM site `skill_agent`)
- `hermes_self_improvement/skill_agent_backend.py`: native skill agent backend, tool executor, limits (LLM site `skill_agent`)
- `hermes_self_improvement/calibration.py`: evaluator overlay calibration
- `hermes_self_improvement/runtime_eval_cases.py`: runtime-private eval cases for episodes, unmatched observations, and improve run artifacts
- `hermes_self_improvement/mutation_policy.py`: memory provider capability / strategy helpers
- `hermes_self_improvement/mutation_worker.py`: tool-mediated mutation executor
- `skills/operations/`: bundled operational skill
- `tests/`: pytest suite

Runtime artifact は `${HERMES_HOME:-~/.hermes}/self-improvement/` 配下に保存します。`setup` が `state/`, `daily/`, `runs/`, `evidence/`, `outcomes/`, `ledgers/`, `evaluator/`, `cache/dspy/` を作ります。run artifact は `runs/`、event は `state/events.jsonl`、active evaluator pointer は `evaluator/active.json`、active prompt overlay pointer は `evaluator/active-prompts.json`、role-level prompt candidates は `evaluator/prompt-candidates/`、prompt candidate set artifact は `evaluator/prompt-candidate-sets/`、runtime-private eval cases は `evaluator/runtime-eval-cases/`。repo の `defaults/prompt-overlays/*.md` は bootstrap seed で、実行時の正本は runtime-private overlay です。overlay は role ごとに 150 行 / 12000 文字まで。
