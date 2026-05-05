# hermes-self-improvement

`hermes-self-improvement` は、Hermes の実行履歴から改善材料を集め、skill / memory / scorer / evaluator を更新する user plugin です。

Hermes は会話中に多くの手がかりを残します。tool の失敗、ユーザーの訂正、subagent のズレ、うまくいった回避策、判断器が外したケース。この plugin はそれらを runtime evidence として保存し、あとで `improve` と `calibrate` が読みます。

この plugin は Hermes core を書き換えません。hook は観測だけを行い、変更は runner が担当します。変更対象も `skill`, `memory`, `scorer`, `evaluator` に絞ります。runtime config、tool policy、任意の docs、Hermes core は自己改善対象にしません。

## どういうプラグインか

主な入口は5つです。

```bash
bin/hermes-self-improve setup
bin/hermes-self-improve status
bin/hermes-self-improve report --since-hours 24
bin/hermes-self-improve improve --dry-run
bin/hermes-self-improve calibrate --dry-run
```

`setup` は runtime directory を作ります。LLM、GEPA、skill mutation、memory mutation は動かしません。

`status` と `report` は read-only です。まずここで plugin、runtime、Curator telemetry、直近 event を確認します。

`improve` は skill / memory を改善します。既定では変更可能です。確認だけしたいときは `--dry-run` を付けます。

```bash
bin/hermes-self-improve improve --dry-run
bin/hermes-self-improve improve
```

`calibrate` は scorer / evaluator / runtime-private prompt overlay を改善します。こちらも既定では変更可能です。

```bash
bin/hermes-self-improve calibrate --dry-run
bin/hermes-self-improve calibrate
```

Dry-run で出た overlay candidate set をそのまま適用したいときだけ、artifact path を明示します。

```bash
bin/hermes-self-improve calibrate --from-candidate-set /path/to/candidate-set.json
```

通常 CLI 出力と agent tool result は短い summary だけを返します。full payload は `${HERMES_HOME:-~/.hermes}/self-improvement/` 配下の artifact に保存します。`--json` は operator/debug 用です。

Agent から使える tool は4つです。

```text
self_improvement_status
self_improvement_report
self_improvement_improve
self_improvement_calibrate
```

`self_improvement_improve` と `self_improvement_calibrate` は full evidence、planner decision 本文、editor instructions、prompt candidate 本文を返しません。LLM-facing result には counts、status、hash、artifact path だけを入れます。

## 導入方法

### 1. Plugin を配置する

Hermes が読む plugin directory に repo を置きます。

```bash
mkdir -p ~/.hermes/plugins
git clone git@github.com:ryonakae/hermes-self-improvement.git \
  ~/.hermes/plugins/hermes-self-improvement
cd ~/.hermes/plugins/hermes-self-improvement
```

依存関係は Python package として入れます。DSPy/GEPA を使うので `dspy` が必要です。

```bash
python3 -m pip install -e .
```

Hermes gateway や CLI が既に起動している場合は、plugin discovery のために新しい session / gateway restart が必要です。

### 2. Runtime directory を初期化する

```bash
bin/hermes-self-improve setup
bin/hermes-self-improve status
```

まず read-only で見るなら次を使います。

```bash
bin/hermes-self-improve setup --check
bin/hermes-self-improve report --since-hours 24
```

### 3. Curator を pause する

この plugin は Curator の skill usage / lifecycle / pinned / archive state を source of truth として読みます。Curator を `disabled` にすると、その telemetry も lifecycle state も弱くなります。

運用では Curator を止めきらず、background review だけを止めるために pause します。

```bash
hermes curator pause
hermes curator status
```

`paused` でも telemetry は読めます。Curator の自律 maintenance は走りません。

### 4. Cron job を入れる

おすすめは、self-improvement job を Slack に直接出さず、local producer として走らせる形です。日次 digest が別にある環境では、その digest が必要な要点だけを拾います。

まず read-only の health/report を入れます。

```bash
hermes cron create '20 7 * * *' \
  --name self-improvement-status \
  --deliver local \
  --workdir ~/.hermes/plugins/hermes-self-improvement \
  'Run `bin/hermes-self-improve status` and `bin/hermes-self-improve report --since-hours 24`. Keep the output short and include artifact paths.'
```

実運用では `improve` と `calibrate` を時間差で走らせます。どちらも mutation-capable なので、最初は自分の環境で dry-run を確認してから切り替えてください。

```bash
hermes cron create '10 3 * * *' \
  --name self-improvement-improve \
  --deliver local \
  --workdir ~/.hermes/plugins/hermes-self-improvement \
  'Run `bin/hermes-self-improve improve --since-hours 24`. Return a compact summary and artifact path.'

hermes cron create '40 3 * * *' \
  --name self-improvement-calibrate \
  --deliver local \
  --workdir ~/.hermes/plugins/hermes-self-improvement \
  'Run `bin/hermes-self-improve calibrate`. Return component status, overlay candidate-set status, and artifact path.'
```

Gateway 停止や laptop sleep が多い環境では、cron の catch-up 方針も確認してください。重い optimizer を大量にまとめて走らせると、翌朝に無駄な負荷が出ます。

## プラグインの強み

### Curator より詳細な観測データを使う

Curator は skill の usage、lifecycle、pinned、archived state をよく知っています。ただ、会話中の細かい失敗までは持ちません。

この plugin は runtime hook で次の情報を拾います。

- tool failure context
- memory operation / failure
- user correction
- session outcome
- subagent outcome
- LLM / API failure metadata

Hook は軽く保ちます。hook 内で LLM、GEPA、skill patch、memory edit、重い集計は走らせません。

### スキルに加えてメモリも自動改善する

Curator の主戦場は skill maintenance です。この plugin は skill と memory を同じ evidence pack から扱います。

Skill 変更は `skill_manage` などの Hermes skill tools で行います。archive が必要なときは Curator-style lifecycle を使います。filesystem delete や自前 `mv` は使いません。

Memory 変更は memory tool / provider-native memory tool で行います。built-in memory file、provider DB、provider internals は直接編集しません。

### DSPy/GEPA で自己改善の判断器も育てる

`improve` は skill / memory を直します。`calibrate` は、その判断に使う scorer / evaluator / prompt overlay を直します。

Planner / editor / evaluator の prompt は repo-tracked base prompt を直接書き換えません。`calibrate` は `${HERMES_HOME:-~/.hermes}/self-improvement/evaluator/active-prompts.json` に runtime-private overlay set を持ちます。

Overlay は planner / editor / evaluator を1つの candidate set として扱います。各 target は `changed` / `unchanged` を持つので、promotion しても3つ全部を書き換えるとは限りません。

Promotion 後は `overlay_generation_id` が improve run、episode、runtime eval case に流れます。これで「新しい overlay が次の改善判断を良くしたか」を後から追えます。

## DSPy/GEPAとはなにか

DSPy は、LLM への指示や評価を Python program として扱うための framework です。手書き prompt を文字列として置くだけではなく、入力、出力、評価関数、最適化対象を分けて扱えます。

GEPA は DSPy の optimizer の一つです。評価ケースを使って prompt や instruction を改善します。この plugin では、GEPA を「skill や memory を直接書き換える機械」として使いません。GEPA は scorer / evaluator / prompt overlay の改善に使います。

この plugin での流れはこうです。

```text
runtime evidence
-> runtime eval cases
-> DSPy/GEPA optimization
-> overlay candidate set
-> acceptance checks
-> active-prompts.json
-> later improve episodes
-> next runtime eval cases
```

GEPA が `no_improvement` と判断したら、それは正常な結果です。失敗ではありません。変更する根拠がないときに preserve behavior を選べることも、自己改善には必要です。

## その他開発向け情報

### 設定

既定値は `hermes_self_improvement/config.py` にあります。local override が必要なときだけ YAML を置きます。

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

`config.yaml` と `config.local.yaml` は local runtime 用です。API key や provider secret は commit しないでください。

Model routing は3つです。

| key | 用途 |
|---|---|
| `model.planner` | proposal scoring と global skill planning |
| `model.editor` | 選ばれた skill / memory の mutation agent |
| `model.evaluator` | DSPy / GEPA による evaluator / prompt / rubric calibration |

### Runtime files

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
  evaluator/active-prompts.json
  evaluator/defaults/
  evaluator/programs/
  evaluator/candidates/
  evaluator/prompt-candidate-sets/
  evaluator/runtime-eval-cases/
  cache/dspy/
```

主なファイルは次の通りです。`state/events.jsonl` は hook event、`runs/` は run artifact、`evidence/` は evidence pack、`evaluator/active.json` は active evaluator pointer、`evaluator/active-prompts.json` は active overlay pointer です。`evaluator/prompt-candidate-sets/` には DSPy/GEPA の overlay candidate set、`evaluator/runtime-eval-cases/` には user-specific eval cases、`cache/dspy/` には DSPy/GEPA cache を置きます。

Repo-tracked default evaluator assets は `defaults/evaluator/`、public regression seed は `evals/proposal/` に置きます。

### 開発時の確認

まず作業前に状態を見ます。

```bash
git status --short
bin/hermes-self-improve status
```

通常変更後はこれを通します。

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
bin/hermes-self-improve status
git diff --check
```

Plugin registration / tool surface を触ったら、Hermes plugin manager からも確認します。

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

### 主要ファイル

入口は `plugin.yaml`、root `__init__.py`、`hermes_self_improvement/cli.py`、`hermes_self_improvement/schemas.py`、`hermes_self_improvement/tool_handlers.py` です。観測は `observer.py`、集計は `analysis.py`、calibration は `calibration.py`、memory/skill mutation は `mutation_policy.py` と `mutation_worker.py` を見ます。

初めて触るなら、`AGENTS.md`、`skills/operations/SKILL.md`、関係する `.hermes/plans/` を読んでから実装に入ってください。tests は `tests/` にあります。
