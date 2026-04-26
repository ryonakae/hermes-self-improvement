# hermes-self-improvement

Hermes の skill / memory / prompt / tool-use workflow を継続改善するための plugin。

## 方針

- hook は観測専用。会話中に LLM / GEPA / skill patch / memory edit は実行しない。
- 問題抽出・候補生成・採点・レポート作成は CLI command から明示的に実行する。
- 無人 cron で自動適用できる変更は、将来的にも low-risk に限定する。
- 採点は既定では heuristic。`--scorer llm` を指定すると Hermes の auxiliary LLM 経路で proposal を採点する。失敗時は heuristic にフォールバックする。
- `--scorer gepa` は GEPA/DSPy 評価経路を通す。既定では dependency-free の offline program eval として実行し、score は `gepa-v0.1` になる。GEPA optimizer 本体はまだ手動実験用で、project-specific metric / invocation が無い場合は閉じておく。
- LLM / GEPA scorer はどちらも advisory only。`auto_apply` は常に `false` として扱い、無人 cron の自動適用許可には使わない。

## CLI

現行 Hermes の top-level plugin CLI discovery は memory plugin 側に寄っているため、cron からは同梱 wrapper を使う。

```bash
~/.hermes/plugins/hermes-plugins/hermes-self-improvement/bin/hermes-self-improve status
~/.hermes/plugins/hermes-plugins/hermes-self-improvement/bin/hermes-self-improve analyze --since-hours 24
~/.hermes/plugins/hermes-plugins/hermes-self-improvement/bin/hermes-self-improve analyze --since-hours 24 --scorer llm --json
~/.hermes/plugins/hermes-plugins/hermes-self-improvement/bin/hermes-self-improve analyze --since-hours 24 --scorer gepa --json
~/.hermes/plugins/hermes-plugins/hermes-self-improvement/bin/hermes-self-improve gepa-eval --json
~/.hermes/plugins/hermes-plugins/hermes-self-improvement/bin/hermes-self-improve report --since-hours 24 --scorer llm
~/.hermes/plugins/hermes-plugins/hermes-self-improvement/bin/hermes-self-improve run --since-hours 24 --json --scorer llm
```

開発中は direct module 実行でも確認できる。

```bash
python3 ~/.hermes/plugins/hermes-plugins/hermes-self-improvement/__init__.py status
python3 ~/.hermes/plugins/hermes-plugins/hermes-self-improvement/__init__.py run --since-hours 24
```

plugin runtime では `/self-improvement status|analyze|report` の slash command も登録する。`/self-improvement report llm` または `/self-improvement report --scorer llm` で LLM scorer、`/self-improvement report gepa` で GEPA scorer path を使う。

## GEPA scorer

- `score_proposals(..., scorer="gepa")` は `gepa_adapter.py` を通す。`gepa_scorer.enabled=true` かつ `max_iterations=0` の既定構成では、`dspy_program.py` の dependency-free `ProposalBatchScoringProgram` を使って offline advisory score を返す。
- `bin/hermes-self-improve gepa-eval --json` runs bundled eval cases against the offline scorer and reports pass/fail regression checks for score range, recommendation, risk, confidence, and `auto_apply`.
- Offline GEPA scores include `score_breakdown` for rubric dimensions: `evidence_strength`, `reuse_value`, `operational_safety`, `specificity`, and `verification_plan`. Markdown reports show a compact `level points/weight` summary for each available dimension.
- 初期版の目的は本番 skill を変異させることではなく、candidate comparison / rubric 評価 / regression check の入口を CLI に用意すること。
- GEPA optimizer 本体はまだ未設定。`max_iterations > 0` の optimizer run は、DSPy/GEPA の存在確認後も project-specific metric / invocation が実装されるまで fail closed する。
- safety gate として、GEPA scorer も `auto_apply` を常に `false` にする。cron の既定 scorer は当面 `llm` のままにする。

GEPA 手動検証用の評価資産:

- eval cases: `evals/proposal_eval_cases.jsonl`
  - `repeated-tool-failure-human-review`
  - `one-off-low-evidence-report-only`
  - `dangerous-auto-apply-denied`
  - `stale-memory-human-review`
- rubric: `evals/rubric.json`
  - version: `proposal-eval-v0.1`
  - dimensions: `evidence_strength`, `reuse_value`, `operational_safety`, `specificity`, `verification_plan`
  - hard constraint: `auto_apply: false`
- DSPy program scaffold: `dspy_program.py`
  - `ProposalScoringProgram`
  - `ProposalBatchScoringProgram`
  - DSPy 未インストールでも import / test できる dependency-free baseline。`--scorer gepa` の既定構成では、この offline program eval を使って `gepa-v0.1` score を返す。将来 GEPA optimizer をつなぐときも同じ input/output schema を使う。

評価資産だけを確認する例:

```bash
cd ~/.hermes/plugins/hermes-plugins/hermes-self-improvement
python3 -m pytest tests/test_gepa_eval_assets.py -q
python3 -m py_compile gepa_adapter.py dspy_program.py
bin/hermes-self-improve analyze --since-hours 24 --json --scorer gepa
```

## LLM scorer

- `score_proposals(..., scorer="llm")` はまず heuristic score を作り、その後 LLM の JSON 出力で score / risk / confidence / recommendation / rationale を上書きする。
- LLM 出力が壊れている、provider が使えない、timeout した場合は `llm_scorer_error` を付けて heuristic score を返す。
- safety gate として、LLM scorer は `auto_apply` を常に `false` にする。cron 側も LLM score だけを根拠に skill / memory を自動変更しない。
- provider 設定は `config.json` の `llm_scorer` で管理する。既定は Hermes auxiliary client の `auto` 経路。

## Data

- events: `~/.hermes/reports/self-improvement/state/events.jsonl`
- reports: `~/.hermes/reports/self-improvement/daily/latest.md`

イベント本文や引数は全文保存せず、redacted preview と hash を保存する。
`pre_tool_call` は `session_id` / `tool_call_id` が揃った行だけ保存する。古い partial 行は分析時に除外し、レポートのメタ情報に除外件数を出す。
`retention_days`（既定30日）より古いイベントは runtime observer の初回記録前に prune する。JSON として壊れた行は削除し、timestamp が無い/読めない古い行は手動確認の余地を残すため保持する。
分析時には historical `post_tool_call` の `result_preview` を再分類する。古い classifier で error 扱いされた成功 payload や、truncated JSON preview の `success: true` / `total_count` / `content` などは report 上で成功扱いに戻し、元の JSONL は書き換えない。
問題候補は `tool_name` だけでなく `error_kind` ごとに cluster 化し、同じ remediation（例: Safehouse permission-denied）は proposal 側で1件に集約する。
