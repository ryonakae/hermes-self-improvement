# hermes-self-improvement

`hermes-self-improvement` は、Hermes の利用中に起きた tool call・hook・セッション終了などのイベントを観測し、skill / memory / prompt / tool-use workflow をどう改善できるかを後から分析するための Hermes user plugin です。

重要なのは、この plugin は会話中に勝手に skill や memory を書き換えないことです。runtime hook は観測だけを行い、分析・proposal 生成・採点・レポート作成は CLI から明示的に実行します。

## 何をする plugin か

この plugin は、次の流れで Hermes の自己改善候補を扱います。

1. Hermes runtime の hook からイベントを収集する。
2. tool error / warning などを集計し、繰り返し起きている問題候補を見つける。
3. skill 追記、運用ルール見直し、memory 方針確認などの proposal を作る。
4. heuristic / LLM / GEPA 系 scorer で proposal を採点する。
5. Markdown report や JSON artifact として、人間が確認できる形に出す。

観測データは、全文ではなく redacted preview と hash を保存します。credential らしき値や sensitive path は保存前に伏せる設計です。

## しないこと

- hook 内で LLM を呼ばない。
- hook 内で GEPA optimizer を回さない。
- 会話中や cron から skill / memory を無条件に変更しない。
- LLM / GEPA の点数だけを根拠に unattended apply を許可しない。
- secret や本文全文を復元・保存しない。

現時点の apply 系処理はかなり保守的です。`generate-apply-plan` は dry-run artifact を作るだけです。`apply-low-risk` は既定では preview / attempt / ledger artifact だけを記録し、`--confirm-apply --expected-item-hash <item_hash>` が明示された場合に限って、低リスク eligible item を guarded mutation と validation 後に適用します。

## DSPy / GEPA とは

DSPy は、LLM を使う処理を「プロンプト文字列の寄せ集め」ではなく、入出力 schema と評価指標を持つ program として組み立てるための Python framework です。

GEPA は DSPy 周辺で使われる optimizer / evaluation approach で、LLM program の候補を評価しながら改善するための仕組みです。この plugin では、将来 proposal scorer を GEPA で最適化できるように `dspy_program.py` と `gepa_adapter.py` に契約を置いています。

ただし、現在の `--scorer gepa` は本物の optimizer run ではありません。既定では dependency-free の offline scorer を使い、`evals/rubric.json` と `evals/proposal_eval_cases.jsonl` に基づいて proposal を advisory に採点します。`max_iterations > 0` の optimizer 実行は、project-specific metric / invocation が未実装なので fail closed します。

## 主要コマンド

通常は同梱 wrapper を使います。現行 Hermes の top-level plugin CLI discovery では `hermes self-improvement ...` として安定して呼べるとは限らないためです。

```bash
cd /path/to/hermes-self-improvement

bin/hermes-self-improve status
bin/hermes-self-improve analyze --since-hours 24
bin/hermes-self-improve report --since-hours 24 --scorer llm
bin/hermes-self-improve run --since-hours 24 --json --scorer compare
bin/hermes-self-improve gepa-eval --json
bin/hermes-self-improve generate-apply-plan --mode dry_run_plan --since-hours 24 --json --scorer compare
bin/hermes-self-improve ledger-report --status applied --json
bin/hermes-self-improve rollback-low-risk <ledger-id> --mode apply_low_risk --json
```

開発時の基本検証:

```bash
cd /path/to/hermes-self-improvement
PY=${PYTHON:-python3}
$PY -m py_compile __init__.py *.py
$PY -m pytest tests -q
bin/hermes-self-improve status
bin/hermes-self-improve gepa-eval --json
```

## Scorer の種類

- `heuristic`: 既定。依存なしの deterministic scorer。
- `llm`: Hermes auxiliary LLM 経路で proposal を採点する。失敗時は heuristic にフォールバックする。
- `gepa`: `gepa_adapter.py` 経由。既定では offline DSPy-compatible scorer を実行する。
- `compare`: LLM と GEPA の採点を比較し、disagreement を report に出す。

どの scorer でも `auto_apply` は常に `false` として扱います。採点は優先順位付けであり、変更許可ではありません。

## ディレクトリ構成

- `plugin.yaml`: Hermes plugin manifest。
- `__init__.py`: plugin registration、hook / CLI / slash command 登録、互換 export。
- `config.py`: default config、execution mode、policy gate。
- `observer.py`: hook observer、redaction、JSONL telemetry、retention。
- `analysis.py`: telemetry aggregation、finding 抽出、proposal 生成。
- `scoring.py`: heuristic / LLM / GEPA / compare scorer。
- `dspy_program.py`: DSPy-compatible な proposal scoring contract と offline baseline。
- `gepa_adapter.py`: GEPA scorer payload、offline eval、optimizer fail-closed 境界。
- `apply_plan.py`: dry-run apply plan と低リスク mutation plan の生成。
- `ledger.py`: pending ledger / apply attempt artifact。
- `cli.py`: CLI parser、report rendering、pipeline orchestration。
- `bin/hermes-self-improve`: standalone wrapper CLI。
- `evals/`: GEPA offline scorer の rubric と regression cases。
- `skills/operations/SKILL.md`: plugin に同梱する運用 skill。
- `skills/operations/references/`: bundled skill から必要時だけ読む詳細メモ。
- `tests/`: pytest test suite。

## データの保存先

既定では Hermes home 配下に保存します。`HERMES_HOME` が未設定なら通常は `~/.hermes` です。

- events: `${HERMES_HOME:-~/.hermes}/reports/self-improvement/state/events.jsonl`
- daily reports: `${HERMES_HOME:-~/.hermes}/reports/self-improvement/daily/latest.md`
- apply plans: `${HERMES_HOME:-~/.hermes}/reports/self-improvement/apply-plans/YYYY-MM-DD/`
- ledgers: `${HERMES_HOME:-~/.hermes}/reports/self-improvement/ledgers/YYYY-MM-DD/`
- apply attempts: `${HERMES_HOME:-~/.hermes}/reports/self-improvement/apply-attempts/YYYY-MM-DD/`

`config.json` で `data_dir`, `report_dir`, `gepa_scorer`, `llm_scorer`, `observe_hooks` などを上書きできます。

## Execution mode

`execution_mode` は cron prompt ではなく plugin CLI / config / policy で検証します。未知の mode、許可されていない command、足りない capability は deny-by-default です。

- `report_only`: `status`, `analyze`, `report`, `run`, `gepa-eval`, `ledger-report` を許可する既定 mode。
- `dry_run_plan`: `generate-apply-plan` と read-only の `ledger-report` を許可するが、target file は変更しない。
- `apply_low_risk`: 低リスク item の preview / attempt / rollback 記録と read-only の `ledger-report` を許可する。実適用は `--confirm-apply --expected-item-hash <item_hash>`、rollback は `--confirm-rollback --expected-ledger-hash <ledger_hash>` があり、hash・rollback preview・validation が通る場合だけ。
- `apply_approved`: 承認済み変更用の予約的 mode。まだ通常運用では使わない。

## 開発方針

- Hermes 本体や upstream-managed code は触らず、この plugin 内で完結させる。
- hook は軽く保つ。重い処理は CLI / cron / offline evaluator に逃がす。
- safety gate は prompt ではなく code と tests で守る。
- 新しい mutation / apply 挙動は TDD で fail-closed を先に固定する。
- plugin discovery や `__init__.py` を触ったら、unit test だけでなく plugin manager loading も確認する。
