# hermes-self-improvement

Hermes の skill / memory / prompt / tool-use workflow を継続改善するための plugin。

## 方針

- hook は観測専用。会話中に LLM / GEPA / skill patch / memory edit は実行しない。
- 問題抽出・候補生成・採点・レポート作成は CLI command から明示的に実行する。
- 無人 cron で自動適用できる変更は、将来的にも low-risk に限定する。
- 採点は既定では heuristic。`--scorer llm` を指定すると Hermes の auxiliary LLM 経路で proposal を採点する。失敗時は heuristic にフォールバックする。
- `--scorer gepa` は GEPA/DSPy 評価経路を通す。既定では dependency-free の offline program eval として実行し、score は `gepa-v0.1` になる。GEPA optimizer 本体はまだ手動実験用で、project-specific metric / invocation が無い場合は閉じておく。
- `--scorer compare` は LLM と GEPA の両方で proposal を採点し、score delta / recommendation / risk / confidence の disagreement を report に出す。
- LLM / GEPA / compare scorer は advisory only。`auto_apply` は常に `false` として扱い、無人 cron の自動適用許可には使わない。
- `execution_mode` は cron prompt ではなく plugin CLI/config/policy で解決・検証する。初期 default は `report_only`。有効 mode は `report_only`, `dry_run_plan`, `apply_low_risk`, `apply_approved` で、未定義 command/capability は deny-by-default。
- `generate-apply-plan` は versioned JSON artifact を生成するだけで、まだ実ファイルを変更しない。item には `change_type`, `target_path`, `target_exists`, `before_hash`, `proposal_hash`, `item_hash`, `eligibility`, `ledger_preview`, `rollback_preview`, `scorer_disagreements` を入れ、target が存在しない候補や mutation plan が無い候補は fail closed にする。
- v1 mutation planner は `pitfall_addition_existing_section` だけを扱う。target に既存 `## Pitfalls` / `## 注意` / `## 注意点` / `## よくある失敗` / `## 落とし穴` セクションがある場合のみ `append_to_existing_section` mutation を作り、既存セクションが無い場合は `existing_section_missing` で拒否する。eligible item には before/after hash と snippet を含む rollback preview を付け、将来の pending ledger が復元材料を持てるようにする。
- `build_pending_ledger` / `write_pending_ledger` は eligible apply-plan item から proposal-level の pending ledger JSON を作り、`reports/self-improvement/ledgers/YYYY-MM-DD/` に保存できる。現時点では ledger を書ける内部部品までで、skill/memory 本体の mutation CLI はまだ開けない。
- `apply-low-risk <plan-id> <item-id>` は現時点では skeleton。plan/item を読み込み、eligibility と target hash を検証し、`would_apply_low_risk` / `stale_plan` / `rejected` の apply-attempt JSON を `reports/self-improvement/apply-attempts/YYYY-MM-DD/` に保存するが、target file は変更しない。`would_apply_low_risk` の場合だけ pending ledger を `reports/self-improvement/ledgers/YYYY-MM-DD/` に作成し、attempt に `pending_ledger_path` / `pending_ledger_hash`、`planned_diff`、`validation_plan` を記録する。
- target resolver は explicit hints のみ使う。`target_path` / `path` / `file_path` / `skill_path` があればそれを優先し、無い場合は `target_skill` / `skill_name` / `skill` を `custom_skill_roots` 配下の `<skill>/SKILL.md` にだけ解決する。絶対パス・`..`・root 外への解決は拒否し、曖昧な自然言語 title からは推測しない。

## Layout

- `__init__.py`: plugin registration and compatibility exports during the refactor.
- `config.py`: defaults, local config loading, execution mode resolution, mode policy validation, and command capability mapping.
- `observer.py`: runtime observer, telemetry JSONL helpers, redaction, retention pruning, partial hook filtering, and tool-result classification.
- `analysis.py`: `AnalysisResult`, telemetry aggregation, finding extraction, and proposal generation/deduplication.
- `scoring.py`: heuristic, LLM, GEPA, and compare scorer logic; `__init__.py` keeps a thin compatibility wrapper so existing monkeypatch-based tests and callers can still override scorer functions through the entrypoint.
- `apply_plan.py`: dry-run apply plan generation, low-risk mutation planning, target metadata resolution, rollback previews, and apply-plan artifact writing.
- `ledger.py`: pending ledger artifacts, apply-attempt artifact writing, apply-plan lookup helpers, file hash checks, and the current non-mutating `apply-low-risk` skeleton.
- `cli.py`: report rendering, GEPA eval CLI support, pipeline orchestration, standalone CLI parser/handler, and slash-command handler.
- `skills/hermes-self-improvement-plugin/SKILL.md`: bundled operational skill, loadable as `skill_view("hermes-self-improvement:hermes-self-improvement-plugin")` when the plugin is discovered.

## CLI

現行 Hermes の top-level plugin CLI discovery は memory plugin 側に寄っているため、cron からは同梱 wrapper を使う。

```bash
~/.hermes/plugins/hermes-plugins/hermes-self-improvement/bin/hermes-self-improve status
~/.hermes/plugins/hermes-plugins/hermes-self-improvement/bin/hermes-self-improve status --mode dry_run_plan
~/.hermes/plugins/hermes-plugins/hermes-self-improvement/bin/hermes-self-improve analyze --since-hours 24
~/.hermes/plugins/hermes-plugins/hermes-self-improvement/bin/hermes-self-improve analyze --since-hours 24 --scorer llm --json
~/.hermes/plugins/hermes-plugins/hermes-self-improvement/bin/hermes-self-improve analyze --since-hours 24 --scorer gepa --json
~/.hermes/plugins/hermes-plugins/hermes-self-improvement/bin/hermes-self-improve analyze --since-hours 24 --scorer compare --json
~/.hermes/plugins/hermes-plugins/hermes-self-improvement/bin/hermes-self-improve gepa-eval --json
~/.hermes/plugins/hermes-plugins/hermes-self-improvement/bin/hermes-self-improve report --since-hours 24 --scorer llm
~/.hermes/plugins/hermes-plugins/hermes-self-improvement/bin/hermes-self-improve run --since-hours 24 --json --scorer llm
~/.hermes/plugins/hermes-plugins/hermes-self-improvement/bin/hermes-self-improve run --mode dry_run_plan --since-hours 24 --json --scorer compare
~/.hermes/plugins/hermes-plugins/hermes-self-improvement/bin/hermes-self-improve generate-apply-plan --mode dry_run_plan --since-hours 24 --json --scorer compare
```

開発中は direct module 実行でも確認できる。

```bash
python3 ~/.hermes/plugins/hermes-plugins/hermes-self-improvement/__init__.py status
python3 ~/.hermes/plugins/hermes-plugins/hermes-self-improvement/__init__.py run --since-hours 24
```

plugin runtime では `/self-improvement status|analyze|report` の slash command も登録する。`/self-improvement report llm` または `/self-improvement report --scorer llm` で LLM scorer、`/self-improvement report gepa` で GEPA scorer path、`/self-improvement report compare` で LLM/GEPA disagreement review を使う。

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

## LLM / GEPA compare scorer

- `score_proposals(..., scorer="compare")` は LLM scorer と GEPA scorer を両方実行し、proposal ごとに `llm_score`, `gepa_score`, `score_delta`, `scorer_disagreements` を付ける。
- disagreement は `score_gap`（20点以上）, `recommendation_mismatch`, `risk_mismatch`, `confidence_mismatch` を記録する。
- disagreement がある proposal は `human_review` に倒し、score は安全側として LLM/GEPA の低い方を採用する。
- GEPA offline scorer は `unknown_error`、低証拠の `not_found`、`review_existing_skill_or_add_pitfall` のような generic recurring failure を過大評価しないよう calibration している。proposal の `tool_name` / `error_kind` に一致する finding だけで evidence を数え、具体的な remediation、examples、verification plan が弱い場合は score / reuse_value / specificity を抑える。
- `report --scorer compare` は compact な `scorer_compare` 行を出す。custom skill maintenance cron ではこの compare report を優先して、人間レビュー候補を見つける。

## Data

- events: `~/.hermes/reports/self-improvement/state/events.jsonl`
- reports: `~/.hermes/reports/self-improvement/daily/latest.md`

イベント本文や引数は全文保存せず、redacted preview と hash を保存する。
`pre_tool_call` は `session_id` / `tool_call_id` が揃った行だけ保存する。古い partial 行は分析時に除外し、レポートのメタ情報に除外件数を出す。
`retention_days`（既定30日）より古いイベントは runtime observer の初回記録前に prune する。JSON として壊れた行は削除し、timestamp が無い/読めない古い行は手動確認の余地を残すため保持する。
分析時には historical `post_tool_call` の `result_preview` を再分類する。古い classifier で error 扱いされた成功 payload や、truncated JSON preview の `success: true` / `total_count` / `content` などは report 上で成功扱いに戻し、元の JSONL は書き換えない。
問題候補は `tool_name` だけでなく `error_kind` ごとに cluster 化し、同じ remediation（例: Safehouse permission-denied）は proposal 側で1件に集約する。
