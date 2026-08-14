# hermes-self-improvement

Hermes Agentの実行時シグナルを観測し、スキル・メモリ・評価プロンプトの改善へつなげます。

<!-- README-I18N:START -->

[English](./README.md) | **日本語**

<!-- README-I18N:END -->

`hermes-self-improvement`は、[Hermes Agent](https://hermes-agent.nousresearch.com/)のユーザープラグインです。軽量な実行時イベントを記録し、証拠パックを作成して、安全性を考慮した知識変更を計画します。変更はHermes公式ツールを介して適用し、planner・editor・evaluatorのプロンプトオーバーレイを[DSPy / GEPA](https://dspy.ai/api/optimizers/GEPA/overview/)で調整します。

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

- **実行時の観測:** ツール失敗、メモリ操作、ユーザーの訂正、セッション結果、サブエージェント結果、LLM／API失敗のメタデータを取得します。
- **証拠を先に集める計画:** 観測結果を証拠パックへまとめてから、plannerが対象と知識トランザクションを選びます。
- **ツールを介した編集:** 制約付きHermesエージェントと公式の`skill_manage`／メモリツールを使い、ファイルやプロバイダーのデータベースを直接編集しません。
- **結果の記録:** 実行アーティファクト、エピソード、台帳、変更後のシグナルを保存し、後から確認できます。
- **プロンプト調整:** DSPy / GEPAを使い、planner・editor・evaluatorの実行時専用プロンプトオーバーレイを最適化します。
- **読み取り専用プレビュー:** 改善と調整の両方で`--dry-run`を利用できます。

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

主な操作は`improve / calibrate / report / status`です。`setup`はCLI専用の初期化コマンドです。

このプラグインはHermesの[Curator](https://hermes-agent.nousresearch.com/docs/user-guide/features/curator)を補完します。Curatorのライフサイクル情報やレビュー結果は将来の証拠になりますが、助言的なフィードバックだけで自動適用を許可することはありません。

<a id="safety-model"></a>
## 安全性

- フックは観測専用です。リクエスト処理中にLLMを呼び出したり、知識を変更したり、重い集計を実行したりしません。
- `improve`と`calibrate`は既定で変更を行います。定期実行の前に`--dry-run`を使ってください。
- スキル変更の対象は、ローカルで変更可能なスキルに限定します。組み込み・ハブから導入したもの・プラグイン同梱・外部・固定・アーカイブ済み・対象が曖昧なスキルは除外します。
- スキル変更には`skill_manage`などのHermes公式ツールを使い、スキルを直接ファイル編集しません。
- メモリ変更にはHermesのメモリツール、または明示されたプロバイダー固有のメモリツールを使います。組み込みメモリファイルやプロバイダーDBを直接編集しません。
- Hermes本体、このプラグイン自身のソース・設定・計画・同梱スキルは自己改善の対象外です。
- ロールバックは主要機能ではありません。失敗した変更や効果の弱い変更は将来の証拠となり、後続の改善実行で修正します。

<a id="requirements"></a>
## 要件

- ユーザープラグインを読み込めるHermes Agent
- Python 3.11以降
- Git
- planner・editor・evaluator・calibratorで使うLLMプロバイダーのHermes設定

パッケージは`dspy>=3.1,<4`を依存関係として宣言しており、プラグインと一緒にインストールされます。

`~/.hermes/plugins`配下にソース一式をチェックアウトする必要があります。Python wheelだけをインストールしても、この単体プラグインの登録やマニフェスト・実行時アセットの配置は行われません。

<a id="installation"></a>
## インストール

Hermesのプラグインディレクトリへクローンし、Hermesが使うPython環境へインストールします。

```bash
mkdir -p ~/.hermes/plugins
git clone https://github.com/ryonakae/hermes-self-improvement.git \
  ~/.hermes/plugins/hermes-self-improvement
cd ~/.hermes/plugins/hermes-self-improvement
python3 -m pip install -e .
```

実行時ディレクトリを初期化し、読み込み状態を確認します。

```bash
hermes self-improvement setup
hermes self-improvement status
```

Hermes CLIやゲートウェイがすでに動いている場合は、インストール後にCLIの新しいセッションを開くか、ゲートウェイを再起動してください。

<a id="quick-start"></a>
## クイックスタート

書き込まずに現在の状態を確認します。

```bash
hermes self-improvement status
hermes self-improvement report --since-hours 24
```

改善処理をプレビューします。

```bash
hermes self-improvement improve --dry-run
```

プレビューの確認後、改善を適用します。

```bash
hermes self-improvement improve
```

プロンプト調整は別にプレビューできます。

```bash
hermes self-improvement calibrate --dry-run
```

<a id="commands"></a>
## コマンド

| コマンド | 役割 | デフォルトで変更するか |
|---|---|---:|
| `setup` | 実行時ディレクトリと初期ファイルを作成 | はい |
| `status` | 観測・実行時状態・評価器の状態を表示 | いいえ |
| `report` | 最近の観測結果と実行結果を要約 | いいえ |
| `improve` | スキル／メモリの改善を計画・適用 | はい |
| `calibrate` | 条件を満たしたプロンプトオーバーレイ候補を最適化・反映 | はい |

すべてのコマンドで`--config PATH`を使えます。機械処理しやすい出力には`--json`を付けます。`improve`と`calibrate`は`--dry-run`に対応し、`setup --check`は書き込まずに初期化状態を確認します。

<a id="configuration"></a>
## 設定

デフォルト値は`hermes_self_improvement/config.py`にあります。上書きが必要な場合だけローカル設定を作成します。

```bash
cp config.example.yaml config.local.yaml
```

設定の優先順位は次のとおりです。

1. 明示的な`--config PATH`
2. `HERMES_SELF_IMPROVE_CONFIG`
3. `config.local.yaml`
4. `config.yaml`
5. 組み込みデフォルト

APIキーやプロバイダーのシークレットをコミットしないでください。ローカル設定では環境変数参照を使います。

4つのモデルロールは分離されています。

| キー | 役割 | ツールアクセス |
|---|---|---|
| `model.planner` | 証拠を読み、知識トランザクションを作成 | 読み取り専用のスキル確認 |
| `model.editor` | plannerが承認したスキル／メモリ変更を適用 | 公式スキル／メモリツールのみ |
| `model.evaluator` | 計画・変更・候補・結果を評価 | ツールなし |
| `model.calibrator` | GEPA最適化中の候補生成と振り返り用フィードバックを担当 | ツールなし |

各ロールは`extra_body.reasoning`を設定できます。プラグインは制約付きエージェントとツールなしエージェントの両方へ、この推論設定を渡します。

内部のメモリ配置レビューには、ツールなしのHermes自動ルーティングを使います。`memory_extractor`は独立したモデル設定キーではありません。

モデルと調整条件の上書き例は[`config.example.yaml`](./config.example.yaml)を参照してください。

<a id="automation"></a>
## 自動実行

`improve`と`calibrate`は別のジョブにしてください。改善処理は比較的軽量ですが、DSPy / GEPAの調整には時間がかかる場合があります。これらのコマンドをLLMエージェントで包まず、エージェントを使わないHermesのスクリプト専用cronジョブとして実行します。

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

最初は`--dry-run`で実行し、生成されたアーティファクトを確認してから変更可能な定期実行を有効にしてください。

<a id="runtime-state"></a>
## 実行時の状態

`setup`は`${HERMES_HOME:-~/.hermes}/self-improvement/`を作成します。

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

完全なプロンプトや詳細な証拠は、実行時アーティファクトと`--json`出力にだけ保存します。エージェント向けのツール結果には、短い要約とアーティファクトのパスを返します。

<a id="development"></a>
## 開発

開発ルールは[`AGENTS.md`](./AGENTS.md)、構成と安全境界は[`skills/operations/SKILL.md`](./skills/operations/SKILL.md)を参照してください。

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
