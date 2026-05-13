# llm_scorer の完全削除と "scorer" → "evaluator" リネーム

## Context

`hermes_self_improvement` プラグインの LLM 呼び出しサイトの 1 つ `llm_scorer` は、proposals を採点して `report` と `diagnostic_signals` を生成する補助だが、**意思決定はすべて `planner` が独立して行っている**ため機能的に冗長。git history を見ると 2026-04 中は scorer 中心の設計だったが、2026-05-01 `92a63df feat: add global self-improvement planner` で planner が追加されて以降、scorer の意思決定責務は planner に奪われ、現在は report 描画と diagnostic_signals 用にしか使われていない。`scoring.py` の出力フォーマット (`recommendation: skip|candidate`、`auto_apply: false`、`scorer: 'heuristic-v0.1'`) も planner 時代以前の名残。

加えて、コード上の role 名 `"scorer"` は **proposal scorer (llm_scorer) と evaluator overlay (GEPA 改善対象) の 2 つの意味を共有**しており(`prompt_overlays.py:11 ALLOWED_PROMPT_ROLES = {planner, editor, scorer}` 等)、mental model の混乱の元になっている。実装では `prompt_overlays.py:198` で `filename = "evaluator.md" if role == "scorer"` のように片足だけ evaluator に寄せた状態。

このプランの目的は:

1. `llm_scorer` (proposal を LLM で採点する経路) を完全削除する
2. コード上に残る role 名 `"scorer"` を `"evaluator"` にフルリネームし、mental model とコードを一致させる
3. heuristic 採点 (`_score_proposals_heuristic`) は report 描画用に維持しつつ、出力 vocabulary を planner と整合させる

ユーザー方針は「過去互換不要、綺麗さっぱり消す」。dead code / 古い field / 名残記述すべて削除する。

`hermes self-improvement improve` の dry-run でも `llm_scorer` site の prompt は 28KB 規模で記録されており、削除すれば毎 run この分の LLM 呼び出しがゼロになる(直接的なトークン削減効果も大きい)。

## 進行順序

依存関係: Step 1〜3 はそれぞれ独立、Step 4 は前 3 つの完了を前提、Step 5〜7 は適宜並行。各 Step 後 `pytest tests -q` を回す。

### Step 1: 共通 util を `llm_utils.py` に切り出す

**目的**: `scoring.py` から削除する関数群を簡単にするための前段。

**変更**:
- 新規: `hermes_self_improvement/llm_utils.py`
  - `_ensure_hermes_agent_on_path()` を移動 (`scoring.py:179-189`)
  - `_extract_json_object()` を移動 (`scoring.py:161-176`)
  - `_coerce_int()` を移動 (`scoring.py:154-158`)
- import path の書き換え:
  - `planner.py:10`
  - `target_resolver.py:7`
  - `conversation_memory.py:10`
  - `runner_steps.py:322, 671`
- これらは Step 1 では関数名を変えず、`from .llm_utils import _coerce_int, _ensure_hermes_agent_on_path, _extract_json_object` に切り替えるだけ

**テスト**: 既存 pytest が pass すれば OK。新規テストは不要(動作変更なし)。

### Step 2: `scorer` role を `evaluator` にフルリネーム

**目的**: コード上の role 名を mental model に揃える。

**変更**:
- `prompt_overlays.py:11`: `ALLOWED_PROMPT_ROLES = {"planner", "editor", "evaluator"}`
- `prompt_overlays.py:12`: `DEFAULT_PROMPT_SEED_ROLES = ("planner", "editor", "evaluator")`
- `prompt_overlays.py:198`: `filename = f"{role}.md"`(`if role == "scorer"` 分岐削除、`evaluator.md` のファイル名は変えない、role 名と一致するように)
- `prompts.py:155-161`: `base_prompt_spec("scorer")` → `base_prompt_spec("evaluator")`、`role: "evaluator"` に変更
- `runtime_eval_cases.py:157, 349`: `role="evaluator"` は既にこの値なので変更不要(prompt_overlays 側が受け入れる)
- config:
  - `config.py:89`: `"gepa_scorer"` → `"gepa_evaluator"`
  - `config.py:254-256`: `gepa_defaults` / `gepa_scorer` 変数名と key を `gepa_evaluator` に
  - `config.py:100-`: `scorer_comparison_policy` セクション完全削除
  - `config.example.yaml:40`、`config.yaml:35`: 関連 commented セクション削除
- 参照:
  - `cli.py:1955`: `gepa_scorer_mode` → `gepa_evaluator_mode`
  - `gepa_adapter.py:73, 266, 362, 391, 486`: `config.get("gepa_scorer")` → `config.get("gepa_evaluator")`
  - `gepa_adapter.py:393`: エラーメッセージ `"gepa_scorer.enabled=true"` → `"gepa_evaluator.enabled=true"`
  - `gepa_adapter.py:404`: `gepa_scorer.compiled_program_path` → `gepa_evaluator.compiled_program_path`
  - `prompt_candidate_optimizer.py:283`、`prompt_gepa_adapter.py:277`: 同様
- ファイルシステム上の `defaults/prompt-overlays/scorer.md` があれば `evaluator.md` にリネーム(`ls defaults/prompt-overlays/` で確認)

**テスト**: 既存テストで `"scorer"` role を assert している箇所を修正。`test_prompt_classification.py`、`test_default_prompt_overlay_seeds.py` 等を中心に。

### Step 3: `_call_llm_scorer` 系と関連 dead code を削除

**目的**: LLM 採点経路の完全削除。

**変更**:
- `scoring.py`:
  - `_call_llm_scorer` (line 192-261) 削除
  - `_fallback_with_scorer_error` (line 36-48) 削除
  - `_merge_external_scores` (line 74-120) 削除
  - `_merge_llm_scores` (line 139-151) 削除
  - `_sanitize_score_breakdown` (line 123-136) 削除
  - `score_proposals_impl` (line 14-33) の LLM 分岐削除 → `_score_proposals_heuristic` を直接呼ぶ wrapper に縮める(または wrapper 自体を消して呼び出し側を直接 heuristic に)
  - util 関数群は Step 1 で移動済み
  - `_score_proposals_heuristic` は **残す**
- `__init__.py:147-157`:
  - `_call_llm_scorer`、`_fallback_with_scorer_error` の import / export 削除
  - `_call_llm_scorer` を渡している箇所 (`__init__.py:170`) 削除
- `cli.py:44`: `from .scoring import _call_llm_scorer, score_proposals_impl` → `from .scoring import _score_proposals_heuristic`(または `score_proposals_impl` 維持で内部書き換え、判断は実装時)
- `cli.py:485-489`: `--scorer llm` / `--scorer heuristic` の説明文削除
- `cli.py:506-508`: `llm_scorer_func=_call_llm_scorer` 引数削除
- `cli.py:840`: `scorer: str = "llm"` → `"heuristic"` 固定または引数自体削除
- `cli.py:921-925`: `scorer=scorer` 削除
- `cli.py:1864`: `p_improve.add_argument("--scorer", ...)` 削除
- `cli.py:1887`: `p_report.add_argument("--scorer", ...)` 削除
- `cli.py:1931, 2003, 2021, 2026`: `args.scorer` 参照削除
- `tool_handlers.py:332, 363`: `scorer=str(args.get("scorer") or "llm")` 削除
- `schemas.py:5`: `SCORER_PROPERTY` 定義削除
- `schemas.py:24, 37`: tool schema の `scorer` property 削除

### Step 4: heuristic 出力フォーマット整理

**目的**: vocabulary と label を planner / mental model と整合。

**変更**:
- `scoring.py:_score_proposals_heuristic` の出力:
  - `recommendation`: `risk == "low" → "apply"`、`risk == "medium" → "defer"`、`risk == "high" → "skip"`(現状 `skip`/`candidate`)
  - `scorer` field → `scoring_method`、値は `"heuristic"`(現状 `"heuristic-v0.1"`)
  - `auto_apply: false` は **維持**(evaluator output spec の一部、`gepa_metric.py:87-88` が検証)
- `cli.py:474-475`: `f"- scorer: \`{proposal.get('scorer')}\`"` → `f"- scoring_method: \`{proposal.get('scoring_method')}\`"`
- `cli.py:472`: recommendation 表示はそのまま(vocabulary 変更で見た目が apply/defer/skip になる)

### Step 5: calibration の `scorer_errors` 経路を削除

**目的**: dead code 除去。

**変更**:
- `calibration.py:51-63`: `_count_scorer_errors` 関数削除
- `calibration.py:106`: `summary` 初期化から `"scorer_errors": 0` 削除
- `calibration.py:141-143`: `scorer_errors` 集計削除
- `calibration.py:203`: `strong` 算出から `scorer_errors` 項削除
- `calibration.py:302-303`: `reason = "scorer_errors"` 分岐削除
- `tool_handlers.py:283`: `"scorer_errors": int(evidence.get("scorer_errors") or 0)` 削除
- `cli.py:392`: `("total_events", "disagreements", "bad_outcomes", "scorer_errors")` から `"scorer_errors"` 除去
- `cli.py:399`: `scorer_errors` 表示行削除
- `tests/test_report_integration.py:170, 197`: `"scorer_errors": 0` 削除
- `tests/test_plugin_tools.py:198`: 同上
- `tests/test_calibration.py:80-82, 122-126`: `write_scorer_error` ヘルパーと依存テスト削除

### Step 6: テスト削除 / 修正

**完全削除**:
- `tests/test_llm_scorer.py`
- `tests/test_scorer_compare.py`
- `tests/test_cli_scorer_defaults.py`
- `tests/test_gepa_scorer.py`

**部分修正**:
- `tests/test_cli_surface.py:42-50`: `test_primary_cli_surface_defaults_to_llm_scorer` 削除
- `tests/test_cli_surface.py:53-69`: `test_primary_cli_surface_rejects_gepa_and_compare_scorers` → gepa/compare 行だけ残し、scorer enum チェック削除
- `tests/test_plugin_tools.py:358-370`: `test_report_and_improve_tool_schemas_only_expose_current_scorers` 削除または scorer enum 関連 assert 削除
- `tests/test_prompt_classification.py`: `_call_llm_scorer` モンキーパッチ削除、heuristic 経路のテストに書き換えるか削除
- `tests/test_report_improve_connection.py`: `score_proposals_impl` モンキーパッチ削除
- `tests/test_default_prompt_overlay_seeds.py`: `"scorer"` 期待値を `"evaluator"` に
- `tests/test_calibration.py`: Step 5 で対応済み

### Step 7: ドキュメント更新

**変更**:
- `AGENTS.md` / `CLAUDE.md`:
  - "改善対象は skill, memory, scorer, evaluator" → "改善対象は skill, memory, evaluator"
  - 「重要パス」一覧の更新(`scoring.py` を heuristic 専用に、`llm_utils.py` 追加)
- `README.md`:
  - `--scorer llm` / `--scorer heuristic` の記述削除
  - 「DSPy / GEPA は proposal scorer ではなく…」というコメント (`cli.py:487` も) → "evaluator overlay 改善" に統一
  - "scorer" 文字列の grep & 整理

## 検証

### 各 Step 後
```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
git diff --check
```

### 全 Step 完了後
- 全 pytest が pass(605 件前後を想定、scorer 関連削除で減る)
- `hermes self-improvement status` がエラーなく動く
- `hermes self-improvement improve --dry-run` が動作する(target_resolver の JSON parse エラーは別問題、無視)
- `state/events.jsonl` に `self_improvement_llm_call` の `site` で `llm_scorer` が現れないことを確認:
  ```bash
  jq -r 'select(.event=="self_improvement_llm_call") | .site' ~/.hermes/self-improvement/state/events.jsonl | sort -u
  ```
  期待: `llm_scorer` が出ない、他 7 site のみ

### LLM 呼び出しサイト数の確認

```bash
grep -rn "call_llm\b" hermes_self_improvement/ | grep -v __pycache__ | wc -l
```
削減前 8 site → 削減後 **7 site**(target_resolver / memory_gap_extractor / planner / mutation_agent / memory_capacity_planner / memory_inventory_planner / dspy_gepa_bridge)。

## 関連ファイル

**主要変更対象**:
- `hermes_self_improvement/scoring.py`(大幅縮小)
- `hermes_self_improvement/calibration.py`
- `hermes_self_improvement/prompt_overlays.py`
- `hermes_self_improvement/prompts.py`
- `hermes_self_improvement/config.py`
- `hermes_self_improvement/cli.py`
- `hermes_self_improvement/tool_handlers.py`
- `hermes_self_improvement/schemas.py`
- `hermes_self_improvement/__init__.py`
- `hermes_self_improvement/gepa_adapter.py`
- `hermes_self_improvement/prompt_candidate_optimizer.py`
- `hermes_self_improvement/prompt_gepa_adapter.py`
- 新規: `hermes_self_improvement/llm_utils.py`
- 削除: `tests/test_llm_scorer.py`、`tests/test_scorer_compare.py`、`tests/test_cli_scorer_defaults.py`、`tests/test_gepa_scorer.py`
- 修正: `tests/test_cli_surface.py`、`tests/test_plugin_tools.py`、`tests/test_prompt_classification.py`、`tests/test_report_improve_connection.py`、`tests/test_default_prompt_overlay_seeds.py`、`tests/test_calibration.py`、`tests/test_report_integration.py`
- ドキュメント: `AGENTS.md`、`CLAUDE.md`、`README.md`
- config: `config.yaml`、`config.example.yaml`
- ファイルシステム: `defaults/prompt-overlays/scorer.md` → `evaluator.md`(存在すれば)

## 進捗

- [x] Step 1: 共通 util を `llm_utils.py` に切り出し
- [x] Step 2: `scorer` role → `evaluator` フルリネーム
- [x] Step 3: `_call_llm_scorer` 系と CLI/schema の `scorer` 経路を削除
- [x] Step 4: heuristic 出力フォーマット整理(`recommendation` vocabulary + `scoring_method` ラベル)
- [x] Step 5: calibration の `scorer_errors` 経路削除
- [x] Step 6: テスト削除 / 修正
- [x] Step 7: ドキュメント更新

最終確認:
- pytest: 604 passed, 2 skipped
- LLM call sites: 8 → **7** (`target_resolver` / `memory_gap_extractor` / `planner` / `mutation_agent` / `memory_capacity_planner` / `memory_inventory_planner` / `dspy_gepa_bridge`)
- 削除ファイル: `tests/test_llm_scorer.py`, `tests/test_scorer_compare.py`, `tests/test_cli_scorer_defaults.py`, `tests/test_gepa_scorer.py`
- 新規ファイル: `hermes_self_improvement/llm_utils.py`

## 後回し / 別タスク

- memory 系 3 site 統合(`memory_gap_extractor` + `memory_inventory_planner` → `memory_planner`)は別計画(`.hermes/plans/2026-05-XX-memory-planner-consolidation.md` を別途作成予定)
- `target_resolver` の応答 JSON parse エラー(新 provider 由来)はトークン最適化と独立、別タスク
