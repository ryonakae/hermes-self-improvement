# AGENTS.md

`hermes-self-improvement` は、Hermes runtime の観測イベントから skill / memory / prompt / tool-use workflow の改善候補を作る user plugin です。hook は観測専用です。mutation は CLI または plugin tool の明示操作で扱います。

## 着手前チェック

```bash
git status --short
bin/hermes-self-improve status
```

- 無関係な変更を戻さないでください。
- まず `README.md` で全体像を確認してください。
- 安全境界を触る場合は `skills/operations/references/safety-and-apply.md` を先に読んでください。
- repo-tracked plan に沿う作業では `.hermes/plans/` の該当 plan を確認してください。

## よく使うコマンド

現行環境では top-level の `hermes self-improvement ...` が安定して露出しているとは限りません。通常は wrapper を使います。

```bash
cd /path/to/hermes-self-improvement

bin/hermes-self-improve status
bin/hermes-self-improve improve
bin/hermes-self-improve improve --execute
bin/hermes-self-improve report --since-hours 24 --json

bin/hermes-self-improve calibrate
bin/hermes-self-improve calibrate --execute
bin/hermes-self-improve plan --since-hours 24
bin/hermes-self-improve apply <plan-id>
bin/hermes-self-improve apply <plan-id> --items step-001 --execute
bin/hermes-self-improve rollback <ledger-id>
bin/hermes-self-improve rollback <ledger-id> --execute
```

Primary surface は `improve / calibrate / plan / apply / rollback / report / status` です。Legacy/debug command は primary surface に戻しません。`generate-apply-plan`, `apply-low-risk`, `apply-approved`, `approval-report`, `retention-*`, `gepa-*` は使わず、上の 7 command に寄せます。

## 検証

通常の変更後に実行します。

```bash
uv sync --group dev
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
bin/hermes-self-improve status
```

GEPA / scorer / eval assets を触った場合です。

```bash
bin/hermes-self-improve calibrate --json
$PY -m pytest tests/test_gepa_eval_assets.py tests/test_gepa_optimizer.py tests/test_gepa_offline_scorer.py -q
```

`__init__.py`, plugin registration, tool schema, bundled skill discovery を触った場合は plugin manager loading も確認します。

```bash
$PY - <<'PY'
from hermes_cli.plugins import discover_plugins, get_plugin_manager
import json

discover_plugins(force=True)
info = [p for p in get_plugin_manager().list_plugins() if p['name'] == 'hermes-self-improvement']
print(json.dumps(info, ensure_ascii=False, indent=2))
PY
```

期待値は plugin が enabled、error が null です。

## 安全境界

- hook 内で LLM call、GEPA optimizer、skill patch、memory edit、重い集計を動かさないでください。
- `--execute` なしの `improve`, `calibrate`, `apply`, `rollback` は preview-only です。
- `--execute` は mutation intent ですが、実変更は policy と内部検証を通った item だけです。
- `apply --execute` は `apply_policy`、internal item hash、target drift check を通った ready item だけ変更します。
- skill mutation は `skill_manage` の許可 action のみを呼び、直接ファイル編集 fallback は使いません。
- built-in memory mutation は `memory` tool のみを呼びます。外部 memory mutation は provider-native tool 経由だけを許可し、現時点では Hindsight の stale/incorrect/duplicate `memory_delete` → `hindsight_retain` correction のみ実行可能です。sensitive delete と provider tool 不在 runtime は fail-closed にします。
- `rollback --execute` は ledger hash と current target hash を検証します。1 item でも drift / tamper があれば rollback しません。
- `calibrate --execute` は evidence threshold と regression pass を通った場合だけ active evaluator pointer を更新します。
- GEPA / LLM の点数だけで auto-apply を許可しないでください。
- telemetry には全文や secret を保存しません。redacted preview と hash を使います。
- plugin は target repo の commit を作りません。commit は target repo の workflow に委譲します。

## 重要パス

- `README.md`: 人間向けの全体説明
- `plugin.yaml`: plugin manifest
- `__init__.py`: root の thin plugin entrypoint
- `hermes_self_improvement/cli.py`: CLI parser と pipeline orchestration
- `hermes_self_improvement/config.py`: config precedence、apply_policy、calibration、model config
- `hermes_self_improvement/observer.py`: hook observer、redaction、JSONL telemetry、retention
- `hermes_self_improvement/analysis.py`: event aggregation と proposal generation
- `hermes_self_improvement/scoring.py`: heuristic / LLM / GEPA / compare scorer
- `hermes_self_improvement/apply_plan.py`: dry-run apply plan と mutation plan
- `hermes_self_improvement/apply_engine.py`: mutation と rollback ledger
- `hermes_self_improvement/mutation_policy.py`: memory provider capability policy、strategy resolver、skill/memory mutation context builder
- `hermes_self_improvement/mutation_worker.py`: tool-mediated executor。skill mutation は `skill_manage` の許可 action のみ
- `hermes_self_improvement/calibration.py`: calibration evidence、regression-gated active evaluator promotion、calibration rollback
- `hermes_self_improvement/tool_handlers.py`: plugin tools
- `evals/proposal/`: offline scorer の repo-tracked public proposal eval assets。`rubric.json` は scorer contract、`cases.jsonl` は bundled golden regression seed。runtime/private eval cases は将来 `${HERMES_HOME:-~/.hermes}/self-improvement/evals/proposal/` に分ける。
- `skills/operations/`: bundled operational skill
- `tests/`: pytest suite

Runtime artifact は `${HERMES_HOME:-~/.hermes}/self-improvement/` 配下に保存します。保存場所の user-facing config override は提供しません。主な subdir は `state/`, `daily/`, `apply-plans/`, `ledgers/`, `gepa/`, `cache/` です。

Repo 側の `evals/` は共通 seed / regression assets です。user-specific な evidence、report、ledger、active evaluator は runtime root に置きます。

## Plugin tools

Primary tool surface は 7 個だけです。`plugin.yaml`, `hermes_self_improvement/schemas.py`, `hermes_self_improvement/tool_handlers.py` を同時に確認してください。handler は wrapper CLI に shell out せず、CLI と同じ core function を使います。

- `self_improvement_status`
- `self_improvement_report`
- `self_improvement_improve`
- `self_improvement_calibrate`
- `self_improvement_plan`
- `self_improvement_apply`
- `self_improvement_rollback`

`mode` / `confirm_*` / `expected_*hash` は primary schema に出しません。

## コーディング / テスト規約

- Python 3.11 前提。runtime hook 側に重い依存を増やさない。
- package import と direct file execution の両方に耐える import を保つ。
- 新しい policy / apply / scorer 挙動は、先に test で fail-closed を固定してから実装する。
- protected context、曖昧な target、複数一致、scorer disagreement、未検証 canonical replacement は mutation plan で拒否する。
- root 直下に `tools.py` や `tools/` package を置かない。Hermes core の `tools.registry` を shadow します。
- `__pycache__/`, `.pytest_cache/`, runtime log は commit しない。

## Cron / scheduled execution

Cron は plugin 内の scheduler ではなく Hermes runtime / scheduler 側の責務です。safe cron は `report` または preview-only `improve` に限定します。

```bash
bin/hermes-self-improve report --since-hours 24 --json
bin/hermes-self-improve improve --since-hours 24 --json
```

Cron から `improve --execute` を使う場合も、許可範囲は `apply_policy` と internal validation に従います。候補を見つけたら plan path、risk、evidence、validation status を人間に渡してください。

## 追加資料

- `README.md`: plugin の目的、仕組み、DSPy / GEPA、自己改善の流れ
- `skills/operations/SKILL.md`: 運用 skill
- `skills/operations/references/safety-and-apply.md`: safety / apply 境界
- `.hermes/plans/2026-04-26_185111-self-improvement-auto-apply-policy.md`: auto-apply 方針
- `.hermes/plans/2026-04-29_003219-self-improvement-runtime-home.md`: runtime storage migration 方針
