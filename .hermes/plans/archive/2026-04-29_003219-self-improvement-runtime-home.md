# self-improvement runtime home 移行計画

> **Status: completed.** Runtime artifacts use `${HERMES_HOME:-~/.hermes}/self-improvement/`; this is a completed supporting plan, not an active migration checklist.

## Goal

`hermes-self-improvement` の runtime artifact 保存先を、暫定的な `~/.hermes/reports/self-improvement/` から専用 runtime home の `~/.hermes/self-improvement/` へ移す。

実装状況: completed（`refactor(self-improvement): move runtime home out of reports` で実装・検証する想定）。

今回の方針はシンプルにする。

- 新しい既定 root は固定で `${HERMES_HOME:-~/.hermes}/self-improvement/`
- config で任意の保存場所へ変更する機能は入れない
- 旧配置との互換読み取りはしない
- 既存の runtime artifact は実ファイルとして新しい場所へ移動する
- primary CLI/tool surface は増やさない

## Current context

現状、保存先は主に `hermes_self_improvement/config.py` と `observer.py` にある。

```text
config.py:
  data_dir    = ~/.hermes/reports/self-improvement/state
  report_dir  = ~/.hermes/reports/self-improvement/daily
  reports_dir = ~/.hermes/reports/self-improvement

observer.py fallback:
  _event_path -> ~/.hermes/reports/self-improvement/state/events.jsonl
  _report_dir -> ~/.hermes/reports/self-improvement/daily
  _reports_dir -> ~/.hermes/reports/self-improvement
```

GEPA / calibration / apply artifacts も `reports_dir` helper 経由で以下に保存されている。

```text
~/.hermes/reports/self-improvement/apply-plans/
~/.hermes/reports/self-improvement/ledgers/
~/.hermes/reports/self-improvement/gepa/
~/.hermes/reports/self-improvement/daily/
~/.hermes/reports/self-improvement/state/events.jsonl
```

ユーザー方針:

- `reports/` 配下だったのは偶然の暫定配置
- 新 root は `~/.hermes/self-improvement/`
- `~/.hermes/.self-improvement/` ではなく非 hidden directory を採用
- 旧配置互換は不要
- config override も今は不要

## Proposed layout

新しい runtime home:

```text
${HERMES_HOME:-~/.hermes}/self-improvement/
```

初期実装では、既存 code への変更量を抑えるため、subdirectory 名は大きく変えずに移す。

```text
~/.hermes/self-improvement/
  state/
    events.jsonl
  daily/
    latest.md
    YYYY-MM-DD.md
  apply-plans/
    YYYY-MM-DD/*.json
  ledgers/
    YYYY-MM-DD/*.json
  gepa/
    programs/*.json
    YYYY-MM-DD/*.json
    active-evaluator.json
  cache/
    dspy/
```

将来 `feedback/` や `eval-cases/` を追加する場合もこの root の下に置く。

```text
~/.hermes/self-improvement/feedback/
~/.hermes/self-improvement/eval-cases/
~/.hermes/self-improvement/evaluators/  # 将来 gepa/ を整理したくなった場合
```

ただし今回の scope では feedback/eval-cases の実装はしない。

## Implementation approach

### 1. runtime home helper を追加する

`hermes_self_improvement/observer.py` か新規小モジュールに、固定 root helper を置く。

候補:

```python
def _self_improvement_root() -> Path:
    return get_hermes_home() / "self-improvement"
```

既存 helper はこの root を使う。

```python
def _event_path(config):
    return _self_improvement_root() / "state" / "events.jsonl"

def _report_dir(config):
    return _self_improvement_root() / "daily"

def _reports_dir(config):
    return _self_improvement_root()
```

ここでは config の `data_dir` / `report_dir` / `reports_dir` override は使わない。将来戻すなら別 plan で設計する。

注意: helper 名 `_reports_dir` は既存 code に広く使われているため、名前は当面維持して中身だけ `self-improvement root` に変えるのが安全。

### 2. default config を新 root に合わせる

`hermes_self_improvement/config.py` の default を更新する。

```python
"data_dir": str(get_hermes_home() / "self-improvement" / "state")
"report_dir": str(get_hermes_home() / "self-improvement" / "daily")
"reports_dir": str(get_hermes_home() / "self-improvement")
```

ただし runtime helper では config override を見ない方針なので、これらは status/report payload の表示や古い tests の期待値調整用に残すだけにする。

より思い切るなら `data_dir/report_dir/reports_dir` config keys 自体を削る選択もあるが、影響範囲が広いので今回の実装では非推奨。まず default と helper を新 root に寄せる。

### 3. GEPA/DSPy cache も新 root へ寄せる

直近で入れた DSPy cache default は今 `~/.hermes/cache/dspy`。

新 root 方針に合わせるなら以下へ移す。

```text
~/.hermes/self-improvement/cache/dspy
```

対象:

- `hermes_self_improvement/dspy_program.py`
- `hermes_self_improvement/gepa_adapter.py`

`DSPY_CACHEDIR` が明示されている場合は尊重する。明示がなければ新 root 下を使う。

### 4. docs / bundled operations skill を更新する

更新対象:

- `README.md`
- `AGENTS.md`
- `skills/operations/SKILL.md`
- 必要なら `skills/operations/references/architecture.md`
- 必要なら `skills/operations/references/operations.md`

記載方針:

```text
Runtime artifact は `${HERMES_HOME:-~/.hermes}/self-improvement/` 配下に保存する。
旧 `${HERMES_HOME}/reports/self-improvement/` は使用しない。
保存場所の config override は現時点では提供しない。
```

### 5. tests を更新・追加する

既存 tests の `reports_dir` / `report_dir` / `data_dir` 期待値を確認し、新 root に更新する。

追加したい確認:

- default config が `~/.hermes/self-improvement` を指す
- `_event_path({})` が `~/.hermes/self-improvement/state/events.jsonl`
- `_report_dir({})` が `~/.hermes/self-improvement/daily`
- `_reports_dir({})` が `~/.hermes/self-improvement`
- `DSPY_CACHEDIR` default が `~/.hermes/self-improvement/cache/dspy`
- `status` の `event_path` が新 root を表示する
- `report --json` の `report_paths` / operational artifacts が新 root を使う

### 6. runtime artifact を実移動する

実装後、既存 runtime artifact を新場所へ移す。

現状の旧 root:

```text
/Users/ryo.nakae/.hermes/reports/self-improvement/
```

新 root:

```text
/Users/ryo.nakae/.hermes/self-improvement/
```

手順案:

```bash
mkdir -p ~/.hermes/self-improvement
rsync -a ~/.hermes/self-improvement/ ~/.hermes/self-improvement/
```

コピー後に新 CLI で読めることを確認してから旧 root を削除する。

旧配置互換は不要なので、確認後は以下を削除してよい。

```bash
rm -rf ~/.hermes/self-improvement
```

ただし `~/.hermes/reports/` 自体は他用途がある可能性があるので削除しない。

### 7. verification

通常検証:

```bash
python -m py_compile __init__.py hermes_self_improvement/*.py
python -m pytest tests -q
hermes self-improvement status
```

storage smoke:

```bash
hermes self-improvement report --since-hours 1 --scorer heuristic --json
hermes self-improvement improve --since-hours 1 --json
hermes self-improvement calibrate --json
```

確認点:

- `status.event_path` が `~/.hermes/self-improvement/state/events.jsonl`
- `report_paths` が新 root 下に出る
- `operational_reports.retention.reports_dir` が新 root
- `apply-plans` / `ledgers` inventory が新 root の既存 artifact を読む
- `~/.hermes/self-improvement` が存在しない、または空である
- plugin discovery が tools 7 / hooks 11 / error None のまま

plugin discovery:

```bash
python3 - <<'PY'
from hermes_cli.plugins import discover_plugins, get_plugin_manager
import json

discover_plugins(force=True)
info = [p for p in get_plugin_manager().list_plugins() if p['name'] == 'hermes-self-improvement']
print(json.dumps(info, ensure_ascii=False, indent=2))
PY
```

## Files likely to change

実装:

- `hermes_self_improvement/config.py`
- `hermes_self_improvement/observer.py`
- `hermes_self_improvement/gepa_adapter.py`
- `hermes_self_improvement/dspy_program.py`
- 影響が出る場合のみ `hermes_self_improvement/cli.py`
- 影響が出る場合のみ `hermes_self_improvement/calibration.py`

Docs / skills:

- `README.md`
- `AGENTS.md`
- `skills/operations/SKILL.md`
- `skills/operations/references/architecture.md`
- `skills/operations/references/operations.md`

Tests:

- `tests/test_config.py` または config 関連 test
- `tests/test_observer.py` / `tests/test_status.py` 相当
- `tests/test_report_integration.py`
- `tests/test_retention_report.py`
- `tests/test_dspy_program.py`
- `tests/test_gepa_optimizer.py`
- その他 `reports_dir` 文字列に依存する tests

Runtime migration:

- tracked file ではないが、以下を移動する。

```text
~/.hermes/self-improvement/ -> ~/.hermes/self-improvement/
```

## Risks / tradeoffs

### 旧 root 互換を切るリスク

旧 `~/.hermes/self-improvement` に artifact が残ったままだと、新実装からは読まれない。今回の方針では互換不要なので、実移動を必ず同じ作業内で行う。

### config override を無効化するリスク

既存 test や一部 code が `config["reports_dir"]` を前提にしている可能性がある。今回の方針では user-facing override は提供しないが、内部 test fixture で temporary root を使う必要は残る。

そのため実装上は以下のどちらかを選ぶ。

1. 完全固定 rootにして tests は `HERMES_HOME` を monkeypatch する
2. 内部 helper だけは test 用に config override を許すが、docs/user-facing では非公開にする

おすすめは 1。シンプルで方針に合う。

### directory naming

`daily/`, `state/`, `apply-plans/`, `ledgers/`, `gepa/` は既存名を維持する。`reports/` subdir に再編すると今回の scope が大きくなるため、まず root だけ移す。

## Out of scope

今回やらないこと:

- 保存場所を config で任意変更できる機能
- 旧 root からの自動 fallback / compatibility read
- `migrate` command の追加
- `feedback/` / `eval-cases/` の schema 実装
- active evaluator の新規生成や calibration logic 強化
- `gepa/` を `evaluators/` にリネームする再編

## Suggested commit shape

1 commit でまとめてよい。

```text
refactor(self-improvement): move runtime home out of reports
```

含める内容:

- code default root 変更
- tests 更新
- docs/skill 更新
- runtime artifact 実移動は git commit には含まれないが、実施結果を最終報告に書く

## Done criteria

- `~/.hermes/self-improvement/` に既存 artifact が移動済み
- `~/.hermes/self-improvement/` は存在しない
- `hermes self-improvement status` が新 event path を表示
- `report/improve/calibrate` smoke が通る
- tests が通る
- plugin discovery が tools 7 / hooks 11 / error None
- README / AGENTS / operations skill が新 root を案内している
