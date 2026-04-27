# AGENTS.md

`hermes-self-improvement` は、Hermes runtime の観測イベントから skill / memory / prompt / tool-use workflow の改善候補を抽出・採点・レポート化する user plugin です。まず `README.md` で全体像を確認してから作業してください。

## よく使うコマンド

```bash
cd /path/to/hermes-self-improvement

# 状態確認
bin/hermes-self-improve status

# 直近イベントの分析 / レポート
bin/hermes-self-improve analyze --since-hours 24
bin/hermes-self-improve report --since-hours 24 --scorer llm
bin/hermes-self-improve run --since-hours 24 --json --scorer compare

# GEPA offline scorer の regression 確認
bin/hermes-self-improve gepa-eval --json

# dry-run apply plan（target file は変更しない）
bin/hermes-self-improve generate-apply-plan --mode dry_run_plan --since-hours 24 --json --scorer compare
```

現行環境では top-level の `hermes self-improvement ...` が安定して露出しているとは限らないため、運用コマンドは `bin/hermes-self-improve` wrapper を優先します。

## 検証手順

変更後は、少なくとも次を実行します。

```bash
cd /path/to/hermes-self-improvement
PY=${PYTHON:-python3}
$PY -m py_compile __init__.py *.py
$PY -m pytest tests -q
bin/hermes-self-improve status
```

GEPA / scorer / eval assets を触った場合は追加で実行します。

```bash
bin/hermes-self-improve gepa-eval --json
$PY -m pytest tests/test_gepa_eval_assets.py tests/test_gepa_eval_cli.py tests/test_gepa_offline_scorer.py -q
```

`__init__.py`, plugin registration, bundled skill discovery を触った場合は plugin manager loading も確認します。

```bash
PY=${PYTHON:-python3}
$PY - <<'PY'
from hermes_cli.plugins import discover_plugins, get_plugin_manager
import json

discover_plugins(force=True)
info = [p for p in get_plugin_manager().list_plugins() if p['name'] == 'hermes-self-improvement']
print(json.dumps(info, ensure_ascii=False, indent=2))
PY
```

期待値は plugin が enabled、error が null、hooks が登録されていることです。

## 重要パス

- `plugin.yaml`: plugin manifest。
- `__init__.py`: registration、hook / CLI / slash command 登録、互換 export。
- `config.py`: default config、execution mode、deny-by-default policy。
- `observer.py`: hook observer、redaction、JSONL telemetry、retention。
- `analysis.py`: event aggregation、finding 抽出、proposal 生成。
- `scoring.py`: heuristic / LLM / GEPA / compare scorer。
- `dspy_program.py`: DSPy-compatible scoring contract と dependency-free baseline。
- `gepa_adapter.py`: GEPA payload、offline eval、optimizer fail-closed 境界。
- `apply_plan.py`: dry-run apply plan と low-risk mutation planning。
- `ledger.py`: pending ledger と apply attempt artifact。
- `cli.py`: CLI parser、report rendering、pipeline orchestration。
- `evals/`: offline scorer の rubric / regression cases。
- `skills/operations/SKILL.md`: plugin-bundled operational skill。
- `skills/operations/references/`: skill 用の詳細 reference。
- `tests/`: pytest suite。

Runtime artifact の既定保存先:

- events: `${HERMES_HOME:-~/.hermes}/reports/self-improvement/state/events.jsonl`
- reports: `${HERMES_HOME:-~/.hermes}/reports/self-improvement/daily/latest.md`
- apply plans: `${HERMES_HOME:-~/.hermes}/reports/self-improvement/apply-plans/YYYY-MM-DD/`
- ledgers: `${HERMES_HOME:-~/.hermes}/reports/self-improvement/ledgers/YYYY-MM-DD/`
- apply attempts: `${HERMES_HOME:-~/.hermes}/reports/self-improvement/apply-attempts/YYYY-MM-DD/`

## コーディング / テスト規約

- Python 3.11 前提。標準ライブラリ中心で、runtime hook 側に重い依存を増やさない。
- import は package import と direct file execution の両方に耐える形を保つ。wrapper CLI は `__init__.py` を `runpy` で実行します。
- 新しい policy / apply / scorer 挙動は先に tests を追加し、fail-closed を固定してから実装する。
- `auto_apply` は scorer の結果に関係なく false 扱い。LLM / GEPA score は優先順位付けであり、変更許可ではありません。
- telemetry には全文や secret を保存しない。redacted preview と hash を使う。
- `__pycache__/`, `.pytest_cache/`, runtime log は commit しない。

## ワークフロー上の注意

- hook は観測専用です。hook 内で LLM、GEPA optimizer、skill patch、memory edit、重い集計を実行しないでください。
- `execution_mode` は prompt ではなく `config.py` / CLI policy で検証します。未知 mode / 未許可 command / 足りない capability は拒否します。
- `generate-apply-plan` は artifact 生成のみで、target file を変更しません。
- `apply-low-risk` は既定では preview / apply-attempt / pending ledger だけを書きます。target file の実変更は `--confirm-apply --expected-item-hash <item_hash>` があり、eligibility・before hash・rollback preview・post-write validation が通る場合だけです。
- 作業前に `git status --short` と該当 diff を確認し、無関係な変更を巻き戻さないでください。
- README は人間向けの入口、AGENTS.md はエージェント向けの最短作業入口として分けます。長い設計経緯は README か repo-tracked plan/docs に寄せてください。

## 追加ドキュメント

- `README.md`: plugin の目的、DSPy / GEPA の位置づけ、主要コマンド、保存先。
- `docs/` または repo-tracked plan: 方針整理やロードマップを置く場所。
- `skills/operations/SKILL.md`: 運用時に使う短い operational index。
- `skills/operations/references/`: architecture / safety / operations の詳細。
