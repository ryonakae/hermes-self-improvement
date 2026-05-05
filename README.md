# hermes-self-improvement

`hermes-self-improvement` は、Hermes の実行履歴からスキル、メモリ、scorer、evaluator の改善材料を集めるユーザープラグインです。

Curator より細かい実行時の観測データを使い、スキルだけでなくメモリも改善します。さらに DSPy/GEPA で判断器そのものを改善し、次の `improve` / `calibrate` に戻します。

フックは観測だけを行います。Hermes 本体、実行時設定、ツール方針、任意のドキュメントは自己改善対象にしません。

## 導入方法

### 1. プラグインを配置する

Hermes が読むプラグインディレクトリにリポジトリを置きます。

```bash
mkdir -p ~/.hermes/plugins
git clone git@github.com:ryonakae/hermes-self-improvement.git \
  ~/.hermes/plugins/hermes-self-improvement
cd ~/.hermes/plugins/hermes-self-improvement
```

依存関係は Python パッケージとして入れます。DSPy/GEPA を使うので `dspy` が必要です。

```bash
python3 -m pip install -e .
```

Hermes gateway や CLI がすでに起動している場合は、プラグイン検出のために新しいセッションか gateway の再起動が必要です。

### 2. 実行時ディレクトリを初期化する

```bash
bin/hermes-self-improve setup
bin/hermes-self-improve status
```

読み取り専用で確認するなら次を使います。

```bash
bin/hermes-self-improve setup --check
bin/hermes-self-improve report --since-hours 24
```

### 3. Curator を pause する

このプラグインは Curator のスキル利用状況、ライフサイクル、pinned / archive 状態を判断元として読みます。Curator を `disabled` にすると、そのテレメトリもライフサイクル状態も弱くなります。

運用では Curator を止めきらず、バックグラウンドレビューだけを止めるために pause します。

```bash
hermes curator pause
hermes curator status
```

`paused` でもテレメトリは読めます。Curator の自律メンテナンスは走りません。

### 4. cron ジョブを入れる

おすすめは、self-improvement ジョブを Slack に直接出さず、ローカル出力のジョブとして走らせる形です。日次レポートが別にある環境では、そのレポートが必要な要点だけを拾います。

まず読み取り専用の health/report を入れます。

```bash
hermes cron create '20 7 * * *' \
  --name self-improvement-status \
  --deliver local \
  --workdir ~/.hermes/plugins/hermes-self-improvement \
  '`bin/hermes-self-improve status` と `bin/hermes-self-improve report --since-hours 24` を実行する。出力は短くし、アーティファクトのパスを含める。'
```

実運用では `improve` と `calibrate` を時間差で走らせます。どちらも変更可能なので、最初は自分の環境で dry-run を確認してから切り替えてください。

```bash
hermes cron create '10 3 * * *' \
  --name self-improvement-improve \
  --deliver local \
  --workdir ~/.hermes/plugins/hermes-self-improvement \
  '`bin/hermes-self-improve improve --since-hours 24` を実行する。短い要約とアーティファクトのパスだけを返す。'

hermes cron create '40 3 * * *' \
  --name self-improvement-calibrate \
  --deliver local \
  --workdir ~/.hermes/plugins/hermes-self-improvement \
  '`bin/hermes-self-improve calibrate` を実行する。component status、overlay 候補セットの状態、アーティファクトのパスだけを返す。'
```

Gateway 停止や PC スリープが多い環境では、cron の catch-up 方針も確認してください。重い最適化をまとめて走らせると、翌朝に無駄な負荷が出ます。

## プラグインの強み

### Curator より詳細な観測データを使う

Curator はスキルの利用状況、ライフサイクル、pinned / archived 状態をよく知っています。ただ、会話中の細かい失敗までは持ちません。

このプラグインは実行時フックで次の情報を拾います。

- ツール失敗時の文脈
- メモリ操作と失敗
- ユーザーの訂正
- セッション結果
- subagent の結果
- LLM / API 失敗のメタデータ

フックは軽く保ちます。フック内で LLM、GEPA、スキル修正、メモリ編集、重い集計は走らせません。

### スキルに加えてメモリも自動改善する

Curator の主戦場はスキル保守です。このプラグインはスキルとメモリを同じ証拠パックから扱います。

スキル変更は `skill_manage` などの Hermes のスキルツールで行います。archive が必要なときは Curator 方式のライフサイクルを使います。ファイル削除や自前 `mv` は使いません。

メモリ変更は memory tool / provider-native memory tool で行います。built-in memory file、provider DB、provider internals は直接編集しません。

### DSPy/GEPA で自己改善の判断器も育てる

`improve` はスキルとメモリを直します。`calibrate` は、その判断に使う scorer、evaluator、プロンプト overlay を直します。

Planner / editor / evaluator のプロンプトは、リポジトリ管理の base prompt を直接書き換えません。`calibrate` は `${HERMES_HOME:-~/.hermes}/self-improvement/evaluator/active-prompts.json` に実行時専用の overlay set を持ちます。

Overlay は planner / editor / evaluator を1つの候補セットとして扱います。各対象は `changed` / `unchanged` を持つので、promotion しても3つ全部を書き換えるとは限りません。

Promotion 後は `overlay_generation_id` が improve 実行、episode、runtime eval case に流れます。これで「新しい overlay が次の改善判断を良くしたか」を後から追えます。

`improve` は変更内容を episode として記録します。`calibrate` は前回 `calibrate` 以降の観測から outcome observation を作り、明示的に紐づく episode だけを採点します。紐づかない観測はアーティファクトに残しますが、scoring には使いません。

## DSPy/GEPAとはなにか

DSPy は、LLM への指示や評価を Python プログラムとして扱うためのフレームワークです。手書きプロンプトを文字列として置くだけではなく、入力、出力、評価関数、最適化対象を分けて扱えます。

GEPA は DSPy の最適化器の一つです。評価ケースを使ってプロンプトや指示を改善します。このプラグインでは、GEPA を「スキルやメモリを直接書き換える機械」として使いません。GEPA は scorer、evaluator、プロンプト overlay の改善に使います。

このプラグインでの流れはこうです。

```text
実行時の証拠
-> 実行時評価ケース
-> DSPy/GEPA による最適化
-> overlay 候補セット
-> 受け入れチェック
-> active-prompts.json
-> 後続の improve episode
-> 次の実行時評価ケース
```

GEPA が `no_improvement` と判断したら、それは正常な結果です。失敗ではありません。変更する根拠がないときに挙動維持を選べることも、自己改善には必要です。

## その他開発向け情報

### 設定

既定値は `hermes_self_improvement/config.py` にあります。ローカル上書きが必要なときだけ YAML を置きます。

```bash
cp config.example.yaml config.yaml
# またはローカル上書き
$EDITOR config.local.yaml
```

読み込み順は下へ行くほど強くなります。

```text
コード既定値
-> config.yaml
-> config.local.yaml
-> HERMES_SELF_IMPROVE_CONFIG
-> --config
-> Hermes 実行時メモリ overlay
```

`config.yaml` と `config.local.yaml` はローカル実行用です。API key や provider secret は commit しないでください。

モデル振り分けは3つです。

| key | 用途 |
|---|---|
| `model.planner` | 改善案の採点と全体スキル計画 |
| `model.editor` | 選ばれたスキル / メモリの変更エージェント |
| `model.evaluator` | DSPy / GEPA による evaluator / プロンプト / rubric 調整 |

### 実行時ファイル

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

主なファイルは次の通りです。`state/events.jsonl` はフックイベント、`runs/` は実行アーティファクト、`evidence/` は証拠パック、`evaluator/active.json` は active evaluator pointer、`evaluator/active-prompts.json` は active overlay pointer です。`evaluator/prompt-candidate-sets/` には DSPy/GEPA の overlay 候補セット、`evaluator/runtime-eval-cases/` にはユーザー固有の評価ケース、`cache/dspy/` には DSPy/GEPA キャッシュを置きます。

リポジトリ管理の既定 evaluator assets は `defaults/evaluator/`、公開 regression seed は `evals/proposal/` に置きます。

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

プラグイン登録 / tool surface を触ったら、Hermes プラグインマネージャーからも確認します。

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

初めて触るなら、`AGENTS.md`、`skills/operations/SKILL.md`、関係する `.hermes/plans/` を読んでから実装に入ってください。テストは `tests/` にあります。
