# GEPA calibration signal window implementation plan

> **For Hermes:** 実装は TDD で進める。Hermes core は触らず、`hermes-self-improvement` plugin 内だけを変更する。

**Status:** implemented through rolling evidence window, material classification, GEPA trigger summary, recurring unmatched eval cases, and compact CLI visibility.

**Goal:** `calibrate` が毎日走っても材料を細切れにせず、直近30日の観測から弱・中・強の材料を分類し、材料が十分ある日は GEPA/overlay 候補生成へ進むようにする。

**Architecture:** `outcome_observer` の観測窓を rolling window + dedupe に変更する。`calibration` に材料分類サマリと GEPA 起動判定を追加し、`runtime_eval_cases` が recurring/unmatched 観測から bootstrap ケースを作れるようにする。候補生成の入口だけ広げ、promotion gate は既存のまま厳格に保つ。

**Tech Stack:** Python 3, pytest, JSON artifacts under `${HERMES_HOME:-~/.hermes}/self-improvement/`, CLI `bin/hermes-self-improve calibrate`.

---

## 決定事項

- 日次 `calibrate → improve → report` は継続する。
- GEPA は「毎日必ず」ではなく、材料がある日は動くようにする。
- 材料がない日、弱い単発が少数だけの日は GEPA を動かさない。
- 基本の観測期間は直近30日。
- 短期再発・直し直し判定は7日程度の短い窓を使う。
- 単発の弱い材料も捨てずに記録する。
- 弱い材料が一定数たまる、または同じ失敗が繰り返される場合は GEPA 起動材料にする。
- 自動採用・overlay 昇格の条件は緩めない。

## 起動条件

GEPA/overlay 候補生成へ進む条件:

- 強い材料が1件以上。
- 中くらいの材料が1まとまり以上。
- 弱い材料が直近30日で10件以上。
- 同じ tool の弱い材料が直近30日で5件以上。
- 評価用ケースが3件以上。

動かさない条件:

- 材料なし。
- 弱い単発が少数だけ。

## Task 1: 観測窓を rolling 30 days にする

**Objective:** `calibrate` のたびに観測窓が前回 `calibrate` で切られないようにする。

**Files:**
- Modify: `hermes_self_improvement/outcome_observer.py`
- Modify tests: `tests/test_outcome_observer.py`

**Steps:**
1. `determine_collection_window()` のテストを、既定では `last_30_days` を返す内容へ変更する。
2. 短期判定用の7日窓は既存の再発判定内に残す。
3. 実装を変更し、`previous_calibrate` を primary window boundary にしない。
4. `pytest tests/test_outcome_observer.py -q` を実行する。

## Task 2: 材料の弱・中・強分類を追加する

**Objective:** calibration evidence に材料分類サマリを出す。

**Files:**
- Modify: `hermes_self_improvement/calibration.py`
- Test: `tests/test_calibration.py`

**Steps:**
1. 単発 tool failure / unmatched observation を弱い材料として数える failing test を書く。
2. 同じ tool+error_kind 3件以上、同じ cron/script 対象2件以上を中くらいの材料として数える failing test を書く。
3. user correction / bad outcome / scorer error / disagreement を強い材料として数える failing test を書く。
4. 実装で `evidence_summary["signal_strength"]` を追加する。
5. `pytest tests/test_calibration.py -q` を実行する。

## Task 3: GEPA 起動判定を材料分類に接続する

**Objective:** `should_build_overlay_set` が材料分類と評価用ケース数で判定されるようにする。

**Files:**
- Modify: `hermes_self_improvement/calibration.py`
- Test: `tests/test_calibration.py`

**Steps:**
1. 弱い材料少数では candidate set を作らないテストを書く。
2. 弱い材料10件で candidate set 生成に進むテストを書く。
3. 中くらいの材料1まとまりで candidate set 生成に進むテストを書く。
4. 評価用ケース3件で candidate set 生成に進むテストを書く。
5. 実装する。
6. `pytest tests/test_calibration.py -q` を実行する。

## Task 4: recurring/unmatched 観測から bootstrap 評価用ケースを作る

**Objective:** episode が0件でも、繰り返し失敗や一定量の弱い材料から GEPA 用の小さい評価ケースを作れるようにする。

**Files:**
- Modify: `hermes_self_improvement/runtime_eval_cases.py`
- Test: `tests/test_runtime_eval_cases.py`

**Steps:**
1. recurring tool failure cluster から planner 向け case が作られる failing test を書く。
2. 弱い単発だけ少数では case を作らない failing test を書く。
3. 実装する。
4. `pytest tests/test_runtime_eval_cases.py -q` を実行する。

## Task 5: レポート/CLI summary に GEPA 未実行理由を出す

**Objective:** 毎朝のレポートで「GEPA が動いたか」「動かなかった理由」「材料の内訳」が分かるようにする。

**Files:**
- Modify: `hermes_self_improvement/cli.py` or report rendering path
- Modify tests: `tests/test_report_integration.py`

**Steps:**
1. calibrate/report JSON に `gepa_trigger` と `signal_strength` が出ることをテストする。
2. human-readable report が未実行理由を短く出すことをテストする。
3. 実装する。
4. `pytest tests/test_report_integration.py -q` を実行する。

## Verification

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests/test_outcome_observer.py tests/test_calibration.py tests/test_runtime_eval_cases.py tests/test_report_integration.py -q
$PY -m pytest tests -q
$PY -m py_compile __init__.py hermes_self_improvement/*.py
bin/hermes-self-improve calibrate --dry-run --json
bin/hermes-self-improve status

git diff --check
git status --short
```

## Notes

- `calibrate` は材料を集める評価者であって、観測窓のリセット地点ではない。
- 入口は広げるが、promotion は既存の hard invariant / score / decision gate を維持する。
- LLM-facing output は compact summary と artifact path に留める。
