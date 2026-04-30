# hermes-self-improvement

`hermes-self-improvement` は、Hermes runtime の観測イベントから skill / memory / scorer / evaluator の改善材料を集め、Curator 互換の runner として扱う user plugin です。

hook は観測専用です。hook 内で LLM call、GEPA optimizer、skill patch、memory edit、重い集計は行いません。

## Primary surface

CLI / plugin tool surface は4つです。

```bash
bin/hermes-self-improve status
bin/hermes-self-improve report --since-hours 24 --json
bin/hermes-self-improve improve
bin/hermes-self-improve improve --dry-run
bin/hermes-self-improve calibrate
bin/hermes-self-improve calibrate --dry-run
```

- `improve`: 統合 runner。calibration、分析、runner step、run artifact 作成を行う。default は mutation-capable。
- `improve --dry-run`: mutation せず preview / artifact だけ作る。
- `calibrate`: scorer/evaluator calibration。regression gate を通った場合だけ active state を更新する。default は mutation-capable。
- `calibrate --dry-run`: calibration の preview。
- `report`: 直近 event / artifact の読み取りレポート。mutation しない。
- `status`: plugin readiness と runtime path の読み取り表示。

削除済みの primary surface: `plan`, `apply`, `rollback`, `outcome` / `record_outcome`。`--execute`, item 指定、hash 確認 flag は primary CLI/tool schema に出しません。

## Runner model

現在の設計方向です。

```text
Hermes runtime hooks
  -> redacted event JSONL
  -> analysis / evidence pack
  -> improve runner steps
     - skill step
     - memory step
     - scorer/evaluator calibration
  -> run artifact
```

Run artifact は `${HERMES_HOME:-~/.hermes}/self-improvement/runs/` に保存します。詳細な evidence、step decisions、summary は artifact に残し、通常出力は Curator 風に短くします。

## Scope and safety

改善対象はこの4カテゴリだけです。

- `skill`
- `memory`
- `scorer`
- `evaluator`

対象外です。

- Hermes core / upstream-managed code
- plugin 自身の `README.md`, `AGENTS.md`, `config*`, `.hermes/plans/**`, bundled `skills/operations/**`
- hub-installed / built-in / plugin-bundled / external read-only skills
- arbitrary docs/config targets
- direct filesystem / provider DB / provider internal mutation fallback

Skill mutation は公式 Hermes skill tools（特に `skill_manage`）だけを使います。Memory mutation は memory tool / provider-native memory tool だけを使います。直接ファイル編集や provider DB 直書きに fallback しません。

Rollback は primary feature ではありません。失敗や誤変更は後続 evidence として扱い、次の改善 run で correction します。skill archive restore のような Curator-style lifecycle restore は別扱いです。

## Scorer / evaluator

DSPy / GEPA は scorer/evaluator の改善に使います。skill や memory を直接変更するものではありません。

- scorer/evaluator の自己改善は prompt / rubric / runtime-private eval cases が対象です。
- Python implementation code は自己変更しません。
- Runtime-private eval cases は `${HERMES_HOME:-~/.hermes}/self-improvement/` 配下に置き、repo-tracked `evals/` に勝手に混ぜません。
- calibration の active promotion は regression gate を通った場合だけです。

## 主要パス

- `plugin.yaml`: plugin manifest / exposed tools
- `hermes_self_improvement/schemas.py`: plugin tool schemas
- `hermes_self_improvement/tool_handlers.py`: plugin tool handlers。wrapper CLI に shell out せず core function を呼ぶ
- `hermes_self_improvement/cli.py`: CLI parser と runner orchestration
- `hermes_self_improvement/observer.py`: hook observer、redaction、JSONL telemetry
- `hermes_self_improvement/analysis.py`: event aggregation / evidence extraction
- `hermes_self_improvement/calibration.py`: scorer/evaluator calibration
- `hermes_self_improvement/mutation_policy.py`: memory provider capability / strategy helpers
- `hermes_self_improvement/mutation_worker.py`: tool-mediated mutation executor
- `skills/operations/`: bundled operational skill
- `.hermes/plans/`: repo-tracked implementation plans

## Verification

通常変更後:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
bin/hermes-self-improve status
```

Plugin registration / tool surface 変更後:

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

期待値: plugin enabled、error null、tools は4つ。
