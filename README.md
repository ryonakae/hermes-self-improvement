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

- `improve`: 統合 runner。Curator 自動 lifecycle transition の実行/preview、Curator telemetry 読み取り、hook evidence pack、skill / memory runner step、run artifact 作成を行う。default は mutation-capable。
- `improve --dry-run`: mutation せず preview / artifact だけ作る。
- `calibrate`: scorer/evaluator calibration。regression gate を通った場合だけ active state を更新する。default は mutation-capable。
- `calibrate --dry-run`: calibration の preview。
- `report`: 直近 event / artifact の読み取りレポート。mutation しない。
- `status`: plugin readiness と runtime path の読み取り表示。

削除済みの primary surface: `plan`, `apply`, `rollback`, `outcome` / `record_outcome`。`--execute`, item 指定、hash 確認 flag は primary CLI/tool schema に出しません。

## Configuration

デフォルト値は `hermes_self_improvement/config.py` の code defaults が持ちます。repo-tracked な JSON default config file は使いません。

Operator override が必要な場合だけ、plugin root に local YAML を置きます。

```bash
cp config.example.yaml config.yaml
# or local-only override
$EDITOR config.local.yaml
```

読み込み順は低い順に以下です。

```text
code defaults
-> config.yaml
-> config.local.yaml
-> HERMES_SELF_IMPROVE_CONFIG
-> --config
-> Hermes runtime memory overlay
```

`config.yaml` / `config.local.yaml` は local runtime 用で gitignore 済みです。

## Curator operating mode

この plugin は Hermes Curator を置き換えるというより、Curator の telemetry / lifecycle 情報を source of truth として使う上位 runner です。運用時は Hermes Curator を `disabled` にせず、必要なら `paused` にしてください。

```bash
hermes curator pause
hermes curator status
```

`paused` では Curator の background review agent は自動起動しませんが、skill usage / lifecycle / pinned / archive state は引き続き読めます。`improve` は Curator/Hermes telemetry を使い、mutating run では Curator と同じ automatic lifecycle transition を実行してから候補を読むことがあります。これはこの plugin の想定動作です。

`curator.enabled: false` は通常使いません。telemetry source や lifecycle semantics を失い、plugin が Curator-compatible runner として判断する前提を弱めます。

## Runner model

現在の設計方向です。

```text
Curator/Hermes skill telemetry + lifecycle
  -> active/stale agent-created local mutable skill candidates
Hermes runtime hooks
  -> redacted high-resolution event JSONL
  -> candidate-aware evidence pack
  -> improve runner steps
     - skill step (Curator candidates + attached hook context)
     - memory step (provider-compatible related-memory lookup when triggered)
  -> run artifact

calibrate
  -> accumulated correction/outcome/disagreement/regression evidence
  -> classifier / editor / evaluator judgment-loop improvement
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

Skill mutation は公式 Hermes skill tools（特に `skill_manage`）だけを使います。候補は Curator/Hermes telemetry を source of truth とし、active / stale の agent-created local mutable skills だけを扱います。Pinned / archived / bundled / hub-installed / plugin-bundled / external / ambiguous provenance は planning 時点で除外し、mutation 直前にも revalidate します。Archived skills は duplicate-prevention や restore candidate としても通常候補に戻しません。

Memory mutation は memory tool / provider-native memory tool だけを使います。correction / contradiction / memory failure など evidence があるときだけ provider recall/search context を添えます。full memory lifecycle、full sweep、直接ファイル編集、provider DB 直書きには fallback しません。

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
