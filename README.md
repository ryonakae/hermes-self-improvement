# hermes-self-improvement

Hermes の実行履歴から改善材料を集め、skill / memory / scorer / evaluator を育てるための plugin です。

普通の会話や開発作業では、あとから効いてくる情報がたくさん残ります。ユーザーの訂正、tool の失敗、subagent の結果、うまくいった回避策、判断器が外したケース。`hermes-self-improvement` はそれらを runtime evidence として集め、`improve` と `calibrate` で次の改善に変えます。

## この plugin の強み

### 1. 実際の失敗から改善できる

静的なルールや手書きメモだけでは、Hermes がどこで迷ったか、どの tool が失敗したか、どの判断があとから否定されたかを拾いきれません。

この plugin は実行中の event と run artifact を使います。改善対象を「なんとなく古そうな skill」ではなく、実際の失敗や訂正に紐づく候補へ寄せられます。

### 2. Curator の telemetry と runtime hook を組み合わせる

Curator は skill の usage、lifecycle、pinned / archived state を知っています。一方で、会話中の tool failure や memory failure、ユーザーからの訂正、subagent の結果までは細かく持ちません。

この plugin は両方を使います。

- Curator: skill 候補の source of truth
- runtime hook: その候補を直す理由になる具体的な evidence

この分担があるので、skill を雑に総当たりで直すのではなく、「使われていて、直す理由があるもの」に絞れます。

### 3. `improve` と `calibrate` を分けている

`improve` は行動する自己改善です。skill と memory の改善案を作り、必要なら公式 tool 経由で反映します。

`calibrate` は判断器を育てる自己改善です。scorer / evaluator の prompt、rubric、runtime-private eval cases を調整します。

この2つを分けると、日常の小さな改善と、判断器そのものの調整を別々に確認できます。失敗したときの切り分けも簡単になります。

### 4. dry-run と artifact を前提にしている

`improve --dry-run` は、変更せずに planner まで実行します。どの候補を選んだか、なぜ選んだか、どう直す予定かを summary と artifact に残します。

通常出力は短くし、詳細は `${HERMES_HOME:-~/.hermes}/self-improvement/runs/` に保存します。agent tool result に巨大な payload を返さないので、会話 context も壊しにくくなります。

## hook はなぜ必要か

Hermes の自己改善に必要な情報は、セッション終了後の要約だけでは足りません。

たとえば、tool が失敗した直後には、失敗した tool 名、引数、エラーの種類、どの作業の途中だったかが分かります。ユーザーが訂正した瞬間には、どの memory や skill が古かったのかを推測しやすい文脈があります。subagent が期待と違う結果を返したときも、親タスクとのズレをその場で記録できます。

hook はこの「その瞬間の文脈」を軽く記録するためにあります。

ただし hook は観測だけを担当します。hook 内で LLM call、GEPA optimizer、skill patch、memory edit、重い集計は動かしません。実行中の Hermes を重くしないためです。集めた event は、あとで `report`、`improve`、`calibrate` が読みます。

## まず使うコマンド

初回または runtime directory を確認したいとき:

```bash
bin/hermes-self-improve setup --check
bin/hermes-self-improve status
```

直近の状況を読むだけ:

```bash
bin/hermes-self-improve report --since-hours 24
```

変更せずに改善案を見る:

```bash
bin/hermes-self-improve improve --dry-run
bin/hermes-self-improve calibrate --dry-run
```

実際に変更を許す:

```bash
bin/hermes-self-improve improve
bin/hermes-self-improve calibrate
```

`improve` と `calibrate` は、既定では変更可能な runner です。確認だけしたいときは必ず `--dry-run` を付けてください。

## この plugin が扱うもの

| 対象 | 何をするか |
|---|---|
| `skill` | Hermes が再利用する手順書を、実際の失敗や訂正に合わせて直す |
| `memory` | ユーザー設定や環境情報など、長く使う記憶を追加・修正・削除する |
| `scorer` | 改善案の良し悪しを判定する採点基準を調整する |
| `evaluator` | scorer / planner の評価プロンプトや rubric を改善する |

変更経路は公式 tool に寄せます。skill は `skill_manage` などの Hermes skill tools、memory は memory tool / provider-native memory tool を使います。filesystem や provider DB を直接触る設計にはしません。

開発や運用で迷ったら、まず `AGENTS.md` を読んでください。実装判断に踏み込むときだけ、`AGENTS.md` から参照されている plan や reference を確認します。

## コマンドの役割

### `status`

plugin と runtime の状態を確認します。変更はしません。

見るもの:

- plugin が有効か
- mutation backend が使えるか
- DSPy / GEPA が使えるか
- runtime directory が初期化済みか
- Curator telemetry が読めるか
- 直近の event / run artifact があるか

```bash
bin/hermes-self-improve status
bin/hermes-self-improve status --json
```

### `report`

直近の event や artifact を読み、今の状態を短くまとめます。変更はしません。

```bash
bin/hermes-self-improve report --since-hours 24
bin/hermes-self-improve report --since-hours 24 --json
```

`--json` は operator/debug 用です。通常は Markdown 表示で十分です。

### `improve`

skill / memory の改善 runner です。

主な流れ:

1. Curator / Hermes telemetry から skill candidate を読む
2. runtime hook の event から evidence を集める
3. planner が直す候補を選ぶ
4. mutation worker が公式 tool 経由で変更する
5. run artifact を保存する

```bash
bin/hermes-self-improve improve --dry-run
bin/hermes-self-improve improve
```

`--dry-run` では変更しません。planner まで実行し、どの候補を選んだか、なぜ選んだか、どう直す予定かを summary と artifact に残します。

### `calibrate`

scorer / evaluator の調整 runner です。

DSPy / GEPA はここで使います。skill や memory を直接書き換えるためには使いません。

```bash
bin/hermes-self-improve calibrate --dry-run
bin/hermes-self-improve calibrate
```

`calibrate` が active evaluator state を更新するのは、regression gate を通った場合だけです。runtime-private eval cases は `${HERMES_HOME:-~/.hermes}/self-improvement/evaluator/runtime-eval-cases/` に置きます。

### `setup`

runtime directory を初期化します。LLM / GEPA / mutation は実行しません。

```bash
bin/hermes-self-improve setup
bin/hermes-self-improve setup --check
bin/hermes-self-improve setup --reset
```

`setup --reset` は `${HERMES_HOME:-~/.hermes}/self-improvement` を削除して作り直します。対話環境では確認を挟みます。非対話実行では `--yes` が必要です。

## Agent から使える tools

Hermes の agent tool surface は4つです。

```text
self_improvement_status
self_improvement_report
self_improvement_improve
self_improvement_calibrate
```

`setup` は CLI-only です。

通常操作は `status`, `report`, `improve`, `calibrate` に絞ります。入口を増やすと、人間も agent もどれを実行すべきか判断しにくくなります。

## Curator との関係

この plugin は Curator が持つ skill telemetry / lifecycle / pinned / archive state を source of truth として使います。

運用時は Curator を `disabled` にせず、必要なら `paused` にします。

```bash
hermes curator pause
hermes curator status
```

`paused` でも skill usage / lifecycle / pinned / archive state は読めます。background review agent は自動起動しません。

## 設定

既定値は `hermes_self_improvement/config.py` の code defaults が持ちます。local override が必要なときだけ、plugin root に YAML を置きます。

```bash
cp config.example.yaml config.yaml
# または local-only override
$EDITOR config.local.yaml
```

読み込み順は下へ行くほど強くなります。

```text
code defaults
-> config.yaml
-> config.local.yaml
-> HERMES_SELF_IMPROVE_CONFIG
-> --config
-> Hermes runtime memory overlay
```

`config.yaml` と `config.local.yaml` は local runtime 用で gitignore 済みです。API key や provider secret は commit しないでください。custom endpoint を使う場合も、local file では `${ENV_VAR}` 参照を優先します。

Model routing は責務ごとに分けます。

| key | 用途 |
|---|---|
| `model.planner` | proposal scoring と global skill planning |
| `model.editor` | 選ばれた skill / memory の mutation agent |
| `model.evaluator` | DSPy / GEPA による evaluator / prompt / rubric calibration |

## Runtime files

`setup` は `${HERMES_HOME:-~/.hermes}/self-improvement/` 配下を作ります。

```text
${HERMES_HOME}/self-improvement/
  state/events.jsonl
  state/install.json
  daily/
  runs/
  evidence/
  outcomes/
  ledgers/
  evaluator/active.json
  evaluator/defaults/
  evaluator/programs/
  evaluator/candidates/
  evaluator/runtime-eval-cases/
  cache/dspy/
```

主な置き場所:

- `state/events.jsonl`: hook が記録した redacted event
- `runs/`: `improve` / `calibrate` の run artifact
- `evaluator/active.json`: active evaluator pointer
- `evaluator/runtime-eval-cases/`: user-specific な runtime eval cases
- `cache/dspy/`: DSPy / GEPA 周辺の cache

Repo-tracked default evaluator assets は `defaults/evaluator/`、public regression seed は `evals/proposal/` に置きます。

## 開発するとき

まず現状を確認します。

```bash
git status --short
bin/hermes-self-improve status
```

通常変更後:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
bin/hermes-self-improve status
```

Plugin registration / tool surface を触った場合:

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

期待値は plugin enabled、error null、tools 4 です。

## 主要ファイル

| path | 役割 |
|---|---|
| `plugin.yaml` | plugin manifest / exposed tools |
| `__init__.py` | root の thin plugin entrypoint |
| `hermes_self_improvement/cli.py` | CLI parser と runner orchestration |
| `hermes_self_improvement/schemas.py` | plugin tool schema |
| `hermes_self_improvement/tool_handlers.py` | plugin tool handlers |
| `hermes_self_improvement/observer.py` | hook observer、redaction、JSONL telemetry |
| `hermes_self_improvement/analysis.py` | event aggregation / evidence extraction |
| `hermes_self_improvement/calibration.py` | scorer / evaluator calibration |
| `hermes_self_improvement/mutation_policy.py` | memory provider capability / strategy helpers |
| `hermes_self_improvement/mutation_worker.py` | tool-mediated mutation executor |
| `AGENTS.md` | 開発時の約束事 |
| `.hermes/plans/` | repo-tracked implementation plans |
| `tests/` | pytest suite |

## 読む順番

初めて触るなら、この順で十分です。

1. この README
2. `AGENTS.md`
3. 変更対象に関係する `.hermes/plans/` または reference
4. 実装ファイルと tests

README は入口です。開発時の約束事は `AGENTS.md`、設計の履歴は repo-tracked plan に置きます。
