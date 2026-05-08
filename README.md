# hermes-self-improvement

`hermes-self-improvement` は、[Hermes Agent](https://hermes-agent.nousresearch.com/) の実行時の観測データから、スキル、メモリを自己改善するプラグインです。
さらに [DSPy/GEPA](https://dspy.ai/api/optimizers/GEPA/overview/) で、改善の判断そのものを自己改善します。

## どう動き、どう自己改善するか

このプラグインは、Hermes の会話を実行時フックで観測します。Hermes Agent の [Curator](https://hermes-agent.nousresearch.com/docs/user-guide/features/curator) はスキルの利用状況、ライフサイクルなどの状態をよく知っていますが、会話中の細かい失敗などの情報までは取得していません。このプラグインはそこを補い、以下のような情報を記録します。

- ツール失敗時の文脈
- メモリ操作と失敗
- ユーザーの訂正
- セッション結果
- subagent の結果
- LLM / API 失敗のメタデータ

フックは観測だけを行います。観測後の処理は、コマンド名ではなく内部の役割で見ると分かりやすくなります。planner は証拠から改善方針を選び、editor は選ばれたスキルやメモリを直し、evaluator は結果や候補を評価します。判断に使う実行時専用の overlay prompt は、あとから調整され、次の実行に反映されます。

```text
[1] Hermes の実行
      ↓
[2] フックでイベントを記録
      ↓
[3] 観測を証拠パックにまとめる
      ↓
[4] planner が改善方針を選ぶ
      ↓
[5] editor が必要な変更だけを実行
      ↓
[6] evaluator が結果や候補を評価し、episode / outcome に保存
      ↓
[7] planner / editor / evaluator の overlay を調整する
      │
      └──── 次の [1] Hermes の実行へ戻る
```

`improve` は、この流れのうち証拠パック作成、改善方針の選択、スキル / メモリの改善、episode 記録を担います。Curator の主な役割はスキル保守ですが、このプラグインはスキルとメモリの両方を扱います。Curator に直接結びつかない失敗も、前後のイベント文脈を含む unmatched evidence candidate として扱います。証拠パックには knowledge inventory health snapshot、memory の重複 / stale pair、Hermes-created skill の stale singleton、coverage gap candidate も入り、dry-run summary では `Knowledge inventory`、`Coverage gaps`、`Target resolution` として短く表示します。`Target resolution` は recommendation だけでなく、defer / create-skill / memory / skip-noise leaning の代表テーマも最大3件ずつ表示します。LLM target resolver は `attach_existing_skill / create_new_skill / memory_candidate / defer_unresolved / skip_noise` の5分類で判断し、generic な tool failure は「唯一見えている skill」に無理に attach しないよう target-fit / negative-fit signals を受け取ります。スキルの patch / archive 対象は Hermes が作成した local mutable skill だけです。built-in、hub-installed、plugin-bundled、external-dir など対象外の skill は LLM-facing candidate list にも載せず、必要なら除外件数と理由だけ artifact に残します。観測から durable な手順不足が見え、既存 Hermes-created skill に適切な受け皿がない場合は、`skill_manage(action="create")` 経由で新規 skill を作成できます。会話由来の memory gap も対象で、キーワードは候補 window の ranking にだけ使い、意味判断は前後文脈を見た LLM に寄せます。抽出前には既存 built-in memory の compact entry を digest に渡し、抽出後にも既存 memory との類似を見て、重複 add は `skip`、関連する古い内容は `replace` に寄せます。メモリ変更は公式 `memory` tool / active external provider tool 経由だけで実行します。`USER.md` / `MEMORY.md` / Skill の置き場所も inventory evidence として LLM に渡し、Hermes 公式の「USER は好み・会話スタイル・期待値、MEMORY は環境事実・規約・学んだこと、Skill は手順・workflow」という境界に沿って判断させます。clear な USER↔MEMORY move は add-before-remove で実行し、曖昧なら `defer` します。明白な stale memory pair は既存の memory mutation planning に `memory_replace` hint として渡せますが、曖昧な pair は `defer` に留めます。raw terminal/search output は memory にせず、skill/workflow evidence 側に残します。built-in memory が満杯のときは、まず `memory` tool のエラーに含まれる `current_entries` をもとに統合・削除候補を作って `replace/remove` → `add` を再試行し、それでも入らない場合だけ active external provider があれば provider tool に回します。直近30日（設定値 `calibration.evidence.window_days`）の観測は、重複排除したうえで outcome scoring や GEPA 用の実行時評価ケースに使います。

`calibrate` は、`improve` の判断そのものを見直します。[DSPy](https://dspy.ai/) は LLM への指示や評価を Python プログラムとして扱うためのフレームワークで、[GEPA](https://dspy.ai/api/optimizers/GEPA/overview/) は評価ケースを使って指示を改善する optimizer です。採用された overlay は `${HERMES_HOME:-~/.hermes}/self-improvement/evaluator/active-prompts.json` に保存され、次の `improve` で使われます。

## よく使うコマンド
主なコマンドは以下の4つです。

| コマンド | 役割 | 変更するか |
|---|---|---|
| `status` | 実行時ディレクトリ、観測、評価器の状態を見る | しない |
| `report` | 直近の観測を読み取り、改善材料を要約する | しない |
| `improve` | 観測からスキル / メモリの改善案を選び、実行する | する |
| `calibrate` | 改善判断に使う scorer / evaluator / プロンプト overlay を調整する | する |

`improve` と `calibrate` は既定で変更可能です。確認だけしたいときは `--dry-run` を付けます。`improve` の判断は、利用者向けには `apply / defer / skip / block` の4つの意味に寄せます。内部互換のため `run_editor` などの既存名がアーティファクトに残ることはありますが、新しい apply mode や承認キューは増やしません。`apply` した変更は常に ledger / artifact に残します。

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

このプラグインは、Hermes Agent の [Curator](https://hermes-agent.nousresearch.com/docs/user-guide/features/curator) のスキル利用状況、ライフサイクル、pinned / archive 状態を判断元として読み取ります。Curator を `disabled` にすると、そのテレメトリもライフサイクル状態も弱くなります。
Curator による観測を止めず、バックグラウンドレビューだけを止めるために pause します。

```bash
hermes curator pause
hermes curator status
```

### 4. cron ジョブを設定する

cron では、まず `--dry-run` 付きで動きを確認してください。実運用では、1本の producer job にして `status`、`calibrate`、`improve`、`report` を順に走らせる構成が扱いやすいです。通知先は環境に合わせて変えてください。以下は `local` に保存する薄い例です。

```bash
hermes cron create '0 4 * * *' \
  --name self-improvement-maintenance \
  --deliver local \
  --workdir ~/.hermes/plugins/hermes-self-improvement \
  '`bin/hermes-self-improve status` で状態を確認し、`bin/hermes-self-improve calibrate`、`bin/hermes-self-improve improve --scorer llm`、`bin/hermes-self-improve report --since-hours 24` を順に実行する。出力は短い要約とアーティファクトのパスだけにする。'
```

`improve` と `calibrate` は既定で変更可能です。最初は手元で `calibrate --dry-run` と `improve --dry-run` を確認してから cron に入れてください。読み取り専用の監視だけが欲しい場合は、`status` と `report --since-hours 24` だけを別 job にしてもかまいません。

## その他

### 設定

既定値は `hermes_self_improvement/config.py` にあります。ローカル上書きが必要なときだけ YAML を置きます。

```bash
cp config.example.yaml config.yaml
# またはローカル上書き
$EDITOR config.local.yaml
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

入口は `plugin.yaml`、root `__init__.py`、`hermes_self_improvement/cli.py`、`hermes_self_improvement/schemas.py`、`hermes_self_improvement/tool_handlers.py` です。観測は `observer.py`、集計と context-windowed evidence は `evidence.py`、LLM target resolve は `target_resolver.py`、会話由来 memory gap は `conversation_memory.py`、calibration は `calibration.py` と `runtime_eval_cases.py`、memory/skill mutation は `mutation_policy.py` と `mutation_worker.py` を見ます。

初めて触るなら、`AGENTS.md`、`skills/operations/SKILL.md`、関係する `.hermes/plans/` を読んでから実装に入ってください。テストは `tests/` にあります。

## ライセンス

MIT License.
