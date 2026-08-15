# hermes-self-improvement

Hermes Agent の実行時シグナルを観測し、根拠に基づいてスキル・メモリ・評価プロンプトを改善します。

<!-- README-I18N:START -->

[English](./README.md) | **日本語**

<!-- README-I18N:END -->

エージェントは同じ失敗を繰り返しがちです。同じツールがセッションをまたいで同じように失敗し、先週伝えた訂正もいつの間にか忘れています。`hermes-self-improvement` は、この繰り返される失敗を修正に変えるための [Hermes Agent](https://hermes-agent.nousresearch.com/) ユーザープラグインです。Hermes の実行中は、軽量なフックがツールの失敗、メモリ操作、ユーザーによる訂正、セッションの結果といった実際の出来事を記録します。プラグインはあとから別のタイミングでこの記録を証拠としてまとめ、スキルとメモリへの変更を計画し、承認されたものだけを Hermes 公式ツール経由で適用します。さらに、プラグイン内部のロールが使うプロンプトを [DSPy / GEPA](https://dspy.ai/api/optimizers/GEPA/overview/) で調整します。

## 目次

- [機能](#features)
- [動作の流れ](#how-it-works)
- [安全性](#safety-model)
- [要件](#requirements)
- [インストール](#installation)
- [クイックスタート](#quick-start)
- [コマンド](#commands)
- [設定](#configuration)
- [自動実行](#automation)
- [実行時の状態](#runtime-state)
- [開発](#development)
- [ライセンス](#license)

<a id="features"></a>
## 機能

- **実行時の観測:** フックが、ツールの失敗、メモリ操作、ユーザーによる訂正、セッションとサブエージェントの結果、LLM / API 失敗のメタデータを記録します。
- **証拠に基づく計画:** 観測結果をまず証拠パック(関連イベントを重複排除してまとめた束)に整理します。planner はその証拠をもとに対象を選び、知識トランザクション(変更対象・編集指示・根拠をひとまとめにした変更計画)を提案します。
- **ツール経由の編集:** 変更はすべて、制約付き Hermes エージェントと公式の `skill_manage`・メモリツールを通して行います。ファイルやプロバイダーのデータベースを直接書き換えることはありません。
- **結果の記録:** 実行ごとにアーティファクト、エピソード、台帳、変更後のシグナルが残り、あとから見返せます。
- **プロンプト調整:** 各ロールは、固定のベースプロンプトに調整可能なオーバーレイを重ねて動きます。planner・editor・evaluator のオーバーレイを DSPy / GEPA で最適化します。
- **読み取り専用プレビュー:** `improve` と `calibrate` のどちらでも `--dry-run` を使えます。

<a id="how-it-works"></a>
## 動作の流れ

```text
[1] Hermes runtime
      ↓
[2] Observation hooks append events to state/events.jsonl
      ↓
[3] Evidence builder creates indexes, detail packs, and diagnostics
      ↓
[4] Planner resolves targets and proposes knowledge transactions
      ↓
[5] Editor applies skill, memory, or user-profile changes through Hermes tools
      ↓
[6] Evaluator records episodes, outcomes, and credit-assignment signals
      ↓
[7] Calibrator optimizes planner/editor/evaluator prompt overlays with DSPy / GEPA
      │
      └─→ Future Hermes runs provide new evidence
```

このループを回すのは 4 つの内部ロールです。**planner** が証拠を読んで何を変えるかを決め、**editor** が Hermes ツール経由で変更を適用し、**evaluator** が計画と結果を採点し、**calibrator** が他のロールが使うプロンプトを調整します。planner は提案ごとに `apply`・`defer`・`skip`・`block` の 4 つの判断のいずれかを下します。

たとえば、長時間かかるコマンドを、元のプロセスが生きているのに再実行してしまう失敗が複数のセッションで続いたとします。フックはその失敗を毎回記録します。次の `improve` 実行で、evidence builder がそれらのイベントを証拠パックにまとめ、planner は「ポーリングの失敗と本当のタイムアウトを見分ける手順」をローカルの `timeout-workflow` スキルへ追記する変更を提案し、editor が `skill_manage` 経由でパッチを適用します。実行アーティファクトには、この `apply` の判断が、`defer` や `skip` にした他の候補と並んで記録されます。

ふだん使うコマンドは `improve`・`calibrate`・`report`・`status` の 4 つです。もうひとつの `setup` は実行時状態を初期化するコマンドで、CLI からだけ使えます。

このプラグインは Hermes の [Curator](https://hermes-agent.nousresearch.com/docs/user-guide/features/curator) を補完します。Curator のライフサイクル情報やレビュー結果は将来の証拠として使えますが、助言的なフィードバックだけを根拠に自動適用することはありません。

<a id="safety-model"></a>
## 安全性

- フックは観測しかしません。LLM 呼び出し、知識の変更、重い集計はすべて、リクエスト処理の外にある `improve` / `calibrate` の実行側で行います。
- `improve` と `calibrate` は既定で変更を適用します。出力に納得できるまでは `--dry-run` を使い、定期実行を組む前には必ずプレビューしてください。
- スキル編集の対象は、ローカルの変更可能なスキルだけです。組み込み、ハブから導入したもの、プラグイン同梱、外部ディレクトリ、固定済み、アーカイブ済み、判別が曖昧なスキルは対象から外します。
- スキル編集は `skill_manage` などの Hermes 公式ツール経由で行い、スキルファイルを直接書き換えません。
- メモリ編集は Hermes のメモリツール、または明示的に設定したプロバイダー固有のメモリツール経由で行い、組み込みメモリファイルやプロバイダーのデータベースには直接触れません。Hermes 側で `memory.user_profile_enabled` が有効な場合の組み込みユーザープロファイルの編集も、同じ経路を通ります。
- Hermes 本体と、このプラグイン自身のソース・設定・計画・同梱スキルは改善の対象外です。
- ロールバックの仕組みは持ちません。失敗した変更や効果の薄い変更は証拠として残り、後続の改善実行で修正します。

<a id="requirements"></a>
## 要件

- ユーザープラグインを読み込める Hermes Agent
- Python 3.11 以降
- Git
- planner・editor・evaluator・calibrator の各ロールで使う LLM プロバイダーの Hermes 設定

パッケージは `dspy>=3.1,<4` に依存しており、プラグインと一緒にインストールされます。

プラグインは `~/.hermes/plugins` 配下にソースをチェックアウトした状態で使います。Hermes はチェックアウト内のマニフェストと実行時アセットからプラグインを認識するため、Python wheel だけをインストールしても動きません。

<a id="installation"></a>
## インストール

Hermes のプラグインディレクトリへクローンし、Hermes が使う Python 環境にインストールします。

```bash
mkdir -p ~/.hermes/plugins
git clone https://github.com/ryonakae/hermes-self-improvement.git \
  ~/.hermes/plugins/hermes-self-improvement
cd ~/.hermes/plugins/hermes-self-improvement
python3 -m pip install -e .
```

続けて実行時状態を初期化し、プラグインが認識されているか確認します。

```bash
hermes self-improvement setup
hermes self-improvement status
```

Hermes CLI やゲートウェイがすでに動いている場合は、インストール後に新しい CLI セッションを開くか、ゲートウェイを再起動してください。

観測のための追加設定は不要です。Hermes がプラグインのフックを自動で登録し、以降のセッションのイベントがログに記録されていきます。

<a id="quick-start"></a>
## クイックスタート

インストール直後はイベントログが空なので、改善候補が出てくるまでしばらく Hermes をふだんどおり使ってください。まずは読み取り専用のコマンドで、観測がどこまで溜まっているかを確認します。

```bash
hermes self-improvement status
hermes self-improvement report --since-hours 24
```

改善実行が何を変えようとするかをプレビューします。

```bash
hermes self-improvement improve --dry-run
```

プレビューの内容に問題がなければ、そのまま適用します。

```bash
hermes self-improvement improve
```

プロンプト調整のプレビューは別コマンドです。

```bash
hermes self-improvement calibrate --dry-run
```

<a id="commands"></a>
## コマンド

| コマンド | 役割 | 既定で変更するか |
|---|---|---:|
| `setup` | 実行時ディレクトリと初期ファイルを作成 | はい(実行時ディレクトリのみ) |
| `status` | 観測・実行時状態・評価器の状態を表示 | いいえ |
| `report` | 最近の観測結果と実行結果を要約 | いいえ |
| `improve` | スキル／メモリの改善を計画・適用 | はい |
| `calibrate` | プロンプトオーバーレイ候補を最適化し、リグレッション検査を通過したものを反映 | はい |

どのコマンドも `--config PATH` を受け付け、`--json` を付けると機械処理向けの出力になります。`improve` と `calibrate` は `--dry-run` に対応し、`setup --check` は何も書き込まずに初期化状態を確認します。`calibrate` が候補オーバーレイを反映するのは、保存済みの実行時評価ケースに対するリグレッション評価を通過した場合だけです。通過しなかった候補はアーティファクトとしてディスクに残ります。

<a id="configuration"></a>
## 設定

デフォルト値は `hermes_self_improvement/config.py` にあります。変えたい項目があるときだけローカル設定を作ります。

```bash
cp config.example.yaml config.local.yaml
```

設定は次の順に探し、最初に見つかったものを使います。

1. 明示的な `--config PATH`
2. `HERMES_SELF_IMPROVE_CONFIG`
3. `config.local.yaml`
4. `config.yaml`
5. 組み込みデフォルト

API キーやプロバイダーのシークレットはコミットせず、ローカル設定から環境変数を参照してください。

プラグインは LLM を 4 つのロールに分けて使います。それぞれにモデル設定キーとツールアクセス範囲があります。

| キー | 役割 | ツールアクセス |
|---|---|---|
| `model.planner` | 証拠を読み、知識トランザクションを作成 | 読み取り専用のスキル確認 |
| `model.editor` | planner が承認したスキル／メモリ変更を適用 | 公式スキル／メモリツールのみ |
| `model.evaluator` | 計画・変更・候補・結果を評価 | ツールなし |
| `model.calibrator` | GEPA 最適化中の候補生成と振り返り用フィードバックを担当 | ツールなし |

各ロールには `extra_body.reasoning` を設定でき、プラグインはこの推論設定を制約付きエージェントとツールなしエージェントの両方へ渡します。

内部のメモリ配置レビューはツールなしの Hermes 自動ルーティングで動くため、`memory_extractor` という独立したモデル設定キーはありません。

モデルや調整条件の上書き例は [`config.example.yaml`](./config.example.yaml) を参照してください。

<a id="automation"></a>
## 自動実行

`improve` と `calibrate` は別々のジョブとして動かしてください。`improve` の LLM 呼び出しは planner・editor・evaluator による限られた回数で、たいてい数分で終わります。一方 `calibrate` は DSPy / GEPA の最適化ループを回すため LLM 呼び出しがずっと多く、タイムアウトには余裕を持たせる必要があります。どちらもスクリプト専用の Hermes cron ジョブとして実行すれば十分で、LLM エージェントで包む必要はありません。

メンテナンススクリプトの例:

```bash
#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/.hermes/plugins/hermes-self-improvement"
hermes self-improvement improve
hermes self-improvement report --since-hours 24
```

調整スクリプトの例:

```bash
#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/.hermes/plugins/hermes-self-improvement"
hermes self-improvement calibrate
```

最初は `--dry-run` で動かし、実行ごとに生成されるアーティファクトを確認してから、変更を伴う定期実行を有効にしてください。

<a id="runtime-state"></a>
## 実行時の状態

`setup` は `${HERMES_HOME:-~/.hermes}/self-improvement/` を作成します。

```text
${HERMES_HOME}/self-improvement/
  state/events.jsonl
  state/install.json
  daily/
  runs/
  evidence/
  outcomes/
  ledgers/
  evaluator/
    active.json
    active-prompts.json
    prompt-candidates/
    prompt-candidate-sets/
    runtime-eval-cases/
  cache/dspy/
```

完全なプロンプトや詳細な証拠は、実行時アーティファクトと `--json` 出力にだけ残ります。エージェントに返るツール結果には、短い要約とアーティファクトのパスだけが含まれます。

<a id="development"></a>
## 開発

開発ルールは [`AGENTS.md`](./AGENTS.md)、アーキテクチャと安全境界は [`skills/operations/SKILL.md`](./skills/operations/SKILL.md) を参照してください。

```bash
git status --short
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e . 'pytest>=9,<10'
python -m py_compile __init__.py hermes_self_improvement/*.py
python -m pytest tests -q
hermes self-improvement status
git diff --check
```

<a id="license"></a>
## ライセンス

[MIT License](./LICENSE) © 2026 Ryo Nakae.
