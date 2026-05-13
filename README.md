# hermes-self-improvement

[Hermes Agent](https://hermes-agent.nousresearch.com/) の実行時イベントを観測し、スキルとメモリを自己改善する user plugin です。
改善判断のプロンプト自体も [DSPy / GEPA](https://dspy.ai/api/optimizers/GEPA/overview/) でチューニングします。

## 何を解決するか

Hermes Agent の [Curator](https://hermes-agent.nousresearch.com/docs/user-guide/features/curator) はスキル利用状況とライフサイクルを追跡します。
ただし、会話中のツール失敗、ユーザーの訂正、メモリ操作の不整合といった細かい信号は拾いません。

このプラグインは runtime hook で次の信号を記録します。

- ツール失敗時の文脈
- メモリ操作と失敗
- ユーザーからの訂正
- セッションと subagent の結果
- LLM / API 失敗のメタデータ

hook は記録だけを行います。実際の変更は `improve` と `calibrate` の 2 つの runner が担当します。

## 動作の流れ

```text
[1] Hermes 実行
      ↓
[2] hook がイベントを state/events.jsonl に記録
      ↓
[3] 観測を証拠パックにまとめる
      ↓
[4] improvement_planner が改善方針を選ぶ
      ↓
[5] skill_agent / memory_agent が変更を実行
      ↓
[6] evaluator が結果を episode / outcome に保存
      ↓
[7] prompt_optimizer が overlay prompt を調整
      │
      └─→ 次回の Hermes 実行へ
```

`improve` が [3] から [6]、`calibrate` が [7] を回します。

### 改善対象

| 対象 | 範囲 |
|---|---|
| skill | Hermes が作成した local mutable skill。built-in / hub / plugin-bundled / external は対象外 |
| memory | 公式 memory tool または provider-native memory tool 経由 |
| evaluator | runtime-private な prompt overlay と eval case |

skill の新規作成は、durable な手順不足が観測から見えて、既存 skill に受け皿がないときだけ `skill_manage(action="create")` で行います。
memory の配置は Hermes の境界に従います。`USER` は好み・会話スタイル・期待値、`MEMORY` は環境事実・規約・学んだこと、`Skill` は手順・workflow です。

## 導入

### 1. プラグインを配置する

Hermes が読むディレクトリにリポジトリを置き、Python パッケージとして install します。

```bash
mkdir -p ~/.hermes/plugins
git clone git@github.com:ryonakae/hermes-self-improvement.git \
  ~/.hermes/plugins/hermes-self-improvement
cd ~/.hermes/plugins/hermes-self-improvement
python3 -m pip install -e .
```

Hermes gateway や CLI を起動中なら、新しいセッションを開くか gateway を再起動してください。

### 2. 実行時ディレクトリを初期化する

```bash
hermes self-improvement setup
hermes self-improvement status
```

書き込まずに状態を見るときは `setup --check` と `report --since-hours 24` を使います。

### 3. Curator を pause する

`improve` は Curator のスキル利用状況とライフサイクル状態を判断材料に使います。
`disabled` にするとこの情報が弱くなります。バックグラウンドレビューだけ止めたい場合は `pause` を使ってください。

```bash
hermes curator pause
hermes curator status
```

### 4. cron で自動化する (任意)

最初は `--dry-run` で動作を確認してから cron に入れます。
日次 maintenance は LLM agent を挟まず、`--no-agent` の script-only job として `hermes self-improvement ...` を直接実行するのが安定です。

`~/.hermes/scripts/self-improvement-maintenance.sh` に薄い wrapper を置きます。

```bash
#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/.hermes/plugins/hermes-self-improvement"
hermes self-improvement status >/dev/null
hermes self-improvement calibrate
hermes self-improvement improve --scorer llm
hermes self-improvement report --since-hours 24
```

cron job はこの script を `--no-agent` で登録します。stdout がそのまま local output に保存されるため、script 側の出力は短い要約とアーティファクトのパスだけにしてください。

```bash
hermes cron create '0 4 * * *' \
  --name self-improvement-maintenance \
  --deliver local \
  --script self-improvement-maintenance.sh \
  --no-agent
```

監視だけ欲しいなら `status` と `report --since-hours 24` だけを実行する別 script / job にしてかまいません。

## コマンド

| コマンド | 役割 | 変更するか |
|---|---|---|
| `status` | 実行時ディレクトリ、観測、評価器の状態を表示 | しない |
| `report` | 直近の観測を要約 | しない |
| `improve` | 観測から skill / memory の改善案を選び実行 | する |
| `calibrate` | 改善判断に使う evaluator / overlay を調整 | する |

`improve` と `calibrate` は既定で変更可能です。プレビューしたいときは `--dry-run` を付けます。
`improve` の判断は `apply / defer / skip / block` の 4 つに集約します。`apply` した変更は ledger と artifact に常に残します。

## 設定

既定値は `hermes_self_improvement/config.py` にあります。ローカル上書きが必要なときだけ YAML を置きます。

```bash
cp config.example.yaml config.yaml
# またはローカル上書き
$EDITOR config.local.yaml
```

API key や provider secret は commit しないでください。

モデルは 4 つの role に振り分けます。

| key | 用途 |
|---|---|
| `model.improvement_planner` | 改善案の採点とスキル計画 |
| `model.skill_agent` | スキル変更エージェント |
| `model.memory_agent` | メモリ変更エージェント (memory tool 経由の add / replace / remove) |
| `model.evaluator` | DSPy / GEPA による evaluator / プロンプト / rubric 調整 |

calibration の evidence しきい値 (window 日数、最少イベント数など) も YAML から調整できます。
具体的なキーは `config.example.yaml` を参照してください。

## 実行時ファイル

`setup` は `${HERMES_HOME:-~/.hermes}/self-improvement/` 配下を作ります。

```text
${HERMES_HOME}/self-improvement/
  state/events.jsonl              # hook イベント + 自身の LLM 呼び出し計測
  state/install.json
  daily/
  runs/                           # 実行アーティファクト
  evidence/                       # 証拠パック
  outcomes/
  ledgers/
  evaluator/
    active.json                   # active evaluator pointer
    active-prompts.json           # active prompt overlay pointer
    prompt-candidates/            # role 別の overlay candidate
    prompt-candidate-sets/        # GEPA が生成した候補セット
    runtime-eval-cases/           # ユーザー固有の評価ケース
  cache/dspy/                     # DSPy / GEPA キャッシュ
```

full prompt の本文は runtime artifact と `--json` 出力だけに残します。
compact なツール結果には source / hash / path だけを返します。

## 開発

着手手順、安全境界、検証コマンドは [`AGENTS.md`](AGENTS.md) にまとめてあります。
設計と運用上の制約は [`skills/operations/SKILL.md`](skills/operations/SKILL.md) を参照してください。

最低限の確認手順:

```bash
git status --short
hermes self-improvement status

PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests -q
```

## ライセンス

MIT License.
