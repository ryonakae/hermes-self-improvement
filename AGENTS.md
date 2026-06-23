# AGENTS.md

`hermes-self-improvement` は、Hermes runtime の観測イベントから skill / memory / evaluator の改善材料を作る user plugin です。hook は観測専用で、mutation は `improve` / `calibrate` runner が担当します。

全体像は `README.md`、設計の詳細は `skills/operations/SKILL.md` と `.hermes/plans/` を参照してください。

## 進め方

TDD で進めます。新規機能や振る舞い変更は、`tests/` に失敗するテストを先に置いてから実装します。リファクタや純粋なリネームでも、変更前後に `pytest -q` を緑に保ちます。

## 着手前

```bash
git status --short
hermes self-improvement status
```

無関係な変更を巻き戻さないこと。安全境界に触る変更は `skills/operations/SKILL.md` を先に読みます。

## よく使うコマンド

```bash
hermes self-improvement status                      # 状態確認 (read-only)
hermes self-improvement report --since-hours 24     # 直近観測の要約 (read-only)
hermes self-improvement improve --dry-run           # 改善案のプレビュー
hermes self-improvement calibrate --dry-run         # overlay 調整のプレビュー
hermes self-improvement improve                     # skill / memory を実際に変更
hermes self-improvement calibrate                   # evaluator overlay を実際に変更
```

primary surface は `improve / calibrate / report / status` の 4 つだけ。`setup` は CLI 専用の bootstrap で agent tool には出しません。`plan / apply / rollback / outcome`、`--execute`、item/hash 指定 flag、legacy command を primary surface に戻さないでください。

`improve` と `calibrate` は既定で変更可能です。確認だけなら `--dry-run` を付けます。

cron / no-agent 運用メモ:
- `self-improvement-calibrate` と `self-improvement-autonomous-maintenance` は分離して扱う。重い `calibrate` を maintenance script に戻さない。
- 現在の実運用は `self-improvement-autonomous-maintenance` が `10 */3 * * *`、`self-improvement-calibrate` が `0 3 * * *`。maintenance は `improve + report`、calibrate は DSPy/GEPA 系として扱う。
- 08:00 の `daily-ops-digest` は直近24時間の maintenance 出力を最大8回分まとめる。個別ログを羅列せず、実行回数・実変更・候補・defer/skip/block の傾向だけを書く。
- 現在の Hermes cron global `script_timeout_seconds` は `1200`。manual dogfood では maintenance は収まり、calibrate は旧 600s budget を超えた。
- cron / timeout の判断材料や最新運用判断は `.hermes/plans/` と `README.md` を先に確認する。

## 検証

通常変更後:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
hermes self-improvement status
git diff --check
```

tool schema / registration を触った場合は、追加で plugin manager から確認します。

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

- runtime hook 内で LLM 呼び出し、GEPA optimizer、skill patch、memory edit、重い集計を動かさない
- 改善対象は `skill` / `memory` / `evaluator` の 3 種類だけ。Hermes core、plugin 自身の README / AGENTS / config / plans / bundled skill、任意 docs/config は対象外
- `improve` の semantic decision は `apply / defer / skip / block` の 4 つに寄せる。新しい apply mode、承認キュー、別 lane を増やさない
- skill mutation は `skill_manage` など公式 skill tools 経由のみ。candidate は `$HERMES_HOME/skills/` 配下の local unprotected skill に限る。built-in / hub-installed / plugin-bundled / external-dir / pinned / archived / ambiguous は LLM-facing mutation target に出さず、artifact に除外件数・理由だけ残す。edit には patch / merge・absorb / reference rewrite / Curator-style archive を含める。
- memory mutation は memory tool / provider-native memory tool 経由のみ。built-in memory file や provider DB を直接編集しない。CLI/standalone 実行でも公式 `tools.memory_tool.MemoryStore` を load して `memory_tool(..., store=store)` で呼ぶ
- built-in memory 満杯時は Planner が `current_entries` を見て `replace/remove` / skill 化 / defer / explicit external memory routing を決める。executor は built-in memory 操作から active external provider tool へ暗黙 fallback しない
- conversation-derived memory gap は改善対象。キーワードは window ranking にだけ使い、semantic gate にしない
- rollback は primary feature ではない。失敗は次回の improvement run で correction する
- plugin 自身の改善対象は target repo の commit を作らない。repo 内の手作業変更は作業者の workflow で commit する

## 重要パス

実装の入口は次の順で読みます。

- `plugin.yaml`: plugin manifest と exposed tools
- `__init__.py`: root の thin entrypoint
- `hermes_self_improvement/cli.py`: CLI parser と runner orchestration
- `hermes_self_improvement/schemas.py` / `tool_handlers.py`: plugin tool surface
- `hermes_self_improvement/observer.py`: hook observer と redaction、JSONL telemetry
- `skills/operations/SKILL.md`: 設計・運用上の制約

役割別モジュール (LLM site 名で参照):

- evidence 収集: `evidence.py`、`planner_targets.py`、`planner_memory.py`
- 改善判断: `planner.py` / `planner_runtime.py`
- mutation 実行: `editor.py` / `editor_skill.py` / `editor_memory.py`、`editor_backend.py` / `editor_backend_skill.py` / `editor_backend_memory.py`
- mutation 下位層: `mutation_policy.py`、`mutation_worker.py`
- evaluator: `calibration.py`、`runtime_eval_cases.py`
- 計測: `llm_telemetry.py`、`prompt_cache.py`

## Runtime artifact

`setup` が `${HERMES_HOME:-~/.hermes}/self-improvement/` 配下に `state/`、`daily/`、`runs/`、`evidence/`、`outcomes/`、`ledgers/`、`evaluator/`、`cache/dspy/` を作ります。

- 観測イベントと plugin 自身の LLM 呼び出し計測: `state/events.jsonl`
- run artifact: `runs/`
- active evaluator: `evaluator/active.json`
- active prompt overlay: `evaluator/active-prompts.json`
- runtime-private eval cases: `evaluator/runtime-eval-cases/`

`defaults/prompt-overlays/*.md` は bootstrap seed です。実行時の正本は runtime overlay 側で、role ごとに 150 行 / 12000 文字までに抑えます。
