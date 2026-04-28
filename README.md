# hermes-self-improvement

`hermes-self-improvement` は、Hermes の実行ログから「skill、memory、prompt、tool の使い方をどこで直すべきか」を見つける user plugin です。

hook は観測だけをします。skill や memory を会話中に勝手に書き換えません。通常操作は `improve` / `calibrate` / `plan` / `apply` / `rollback` / `report` / `status` に集約し、実変更は `--execute` を付けた場合だけ行います。

## できること

- Hermes runtime の hook event を JSONL に記録する
- tool error や warning から改善候補を作る
- proposal を heuristic / LLM / DSPy-backed GEPA scorer で採点する
- report、apply plan、apply ledger、calibration ledger を artifact として残す
- policy で許可された低リスクな text replacement を、内部 hash と validation 付きで適用する
- evaluator/scorer の調整を `calibrate` で preview し、regression pass 時だけ `--execute` で active 化する
- retention は `report` 内の read-only inventory として扱う。削除・prune 用 CLI/tool は primary surface に戻さない

保存する event は redacted preview と hash が中心です。secret らしき値や sensitive path は保存前に伏せます。

## しないこと

- hook 内で LLM や GEPA optimizer を呼ばない
- scorer の点数だけで unattended mutation を許可しない
- cron から confirmation 付き mutation を走らせない
- target repo の commit を作らない
- secret や本文全文を復元して保存しない

mutation は preview-first です。primary surface では `--execute` が唯一の user-facing mutation boundary です。item hash / target hash はユーザーに渡させず、内部で検証します。

## 使い方

現行環境では `hermes self-improvement ...` が常に使えるとは限りません。通常は同梱 wrapper を使います。

```bash
cd /path/to/hermes-self-improvement

# 通常はこれを見る
bin/hermes-self-improve status
bin/hermes-self-improve improve
bin/hermes-self-improve improve --execute

# 手動で分けて確認する場合
bin/hermes-self-improve calibrate
bin/hermes-self-improve calibrate --execute
bin/hermes-self-improve plan --since-hours 24
bin/hermes-self-improve apply <plan-id>
bin/hermes-self-improve apply <plan-id> --items step-001,step-002
bin/hermes-self-improve apply <plan-id> --items step-001 --execute
bin/hermes-self-improve rollback <ledger-id>
bin/hermes-self-improve rollback <ledger-id> --execute

# read-only report
bin/hermes-self-improve report --since-hours 24 --json
```

`improve` は `calibrate → plan → apply → summary` をまとめて実行します。`improve` だけなら preview、`improve --execute` で mutation-capable phase を実行します。ただし実際に変更されるのは `apply_policy` と内部 hash / target drift checks を通った item だけです。

`apply` は既定で preview です。実変更は `--execute` を付けた場合だけ行い、item hash / target hash は内部で検証します。policy で許可されない item や review が必要な item は適用されません。

`calibrate` は evaluator/scorer 改善の evidence を集め、既定では preview として `no_op` / `would_update` を返します。`--execute` は regression が pass した場合だけ active evaluator pointer を更新し、active-before snapshot を calibration ledger に残します。regression runner 未設定や regression failure は fail-closed で active evaluator を変更しません。

`report` は観測イベントと proposal 採点に加えて、recent plan summary、recent apply summary、calibration summary、needs-review highlights をまとめます。旧 approval gate summary は表示しません。

## Safety model

Primary surface の安全境界は `--execute` です。

- `improve`, `calibrate`, `apply`, `rollback` は `--execute` なしでは preview-only。
- `apply_policy` が通常の skill/memory 改善の適用範囲を決めます。
- `calibration` が evaluator/scorer 自己調整を決めます。`apply_policy` とは別です。
- `item_hash`, `target_hash`, `ledger_hash` は内部整合性・drift 検知・rollback 用で、user-facing option ではありません。
- `rollback --execute` は実変更前に ledger hash と全 applied item の current target hash / rollback data を検証します。1 item でも drift / tamper があれば、他 item も含めて rollback しません。

```yaml
apply_policy:
  max_risk: low
  allow_destructive: false
  allowed_target_kinds: [skill, memory]
  allowed_change_types: []
  denied_change_types: []

calibration:
  enabled: true
  evidence:
    window_days: 30
    min_evidence_events: 20
    min_disagreements: 5
    min_bad_outcomes: 2
  optimizer:
    max_full_evals: 2
```

Legacy/debug commands such as `generate-apply-plan`, `gepa-eval`, `gepa-optimize`, `ledger-report`, `approval-report`, `retention-report`, and guarded approval/retention pruning are no longer part of the CLI or plugin tool surface. Use `improve`, `calibrate`, `plan`, `apply`, `rollback`, `report`, and `status`. Retention cleanup is intentionally read-only in `report`; legacy `approvals/` and `apply-attempts/` directories may be listed for manual review but are not automatically deleted.

## Plugin tools

`plugin.yaml` は agent-native tools を登録します。tool handler は wrapper CLI に shell out せず、CLI と同じ core function を通します。Primary tool surface は次の 7 個だけです。

- `self_improvement_status`
- `self_improvement_report`
- `self_improvement_improve`
- `self_improvement_calibrate`
- `self_improvement_plan`
- `self_improvement_apply`
- `self_improvement_rollback`

Tool も CLI と同じく、`execute=false` が preview-only、`execute=true` が唯一の mutation intent です。`mode` / `confirm_*` / `expected_*hash` は primary tool schema に出しません。

## Scorers

- `heuristic`: 依存なしの deterministic scorer。軽量な observation / debugging 用。
- `llm`: Hermes auxiliary LLM 経路。失敗時は `llm_scorer_error` を残して heuristic score を併記する。
- `gepa`: DSPy / GEPA evaluator path。`dspy` はこの plugin の evaluator 依存として必須だが、hook / plugin discovery では lazy import する。dependency-free offline baseline には黙って戻さない。
- `compare`: LLM と GEPA の disagreement を report に出す decision scorer。

`improve`、`report`、`plan` は、明示的に `--scorer` を渡さない限り `compare` を使います。`--scorer gepa` は dependency-free offline baseline にフォールバックしません。active runtime に `dspy` が無い場合は `gepa_scorer_error` として明示します。`plan` では、disagreement がなくても non-compare scorer の低リスク item は unattended apply eligible にせず、review 側に倒します。

`compare` の disagreement 判定は `scorer_comparison_policy` で change type ごとに調整します。risk / recommendation mismatch は常に block、memory / lifecycle / destructive / broad change は strict threshold、`typo_fix` / `pitfall_addition_existing_section` / `validation_addition_existing_section` は少し緩い score / confidence threshold を使います。`plan` は `scorer_disagreements` と `scorer_comparison_policy` を item に残し、disagreement がある item は unattended eligible にしません。

```bash
python3 -m pip install -e .
```

GEPA regression / optimizer internals は `calibrate` の内部で扱います。Runtime `gepa` scorer は DSPy program に plugin-local `model.gepa` を渡し、DSPy 側の LM call は Hermes `agent.auxiliary_client.call_llm(...)` を通る `BaseLM` bridge で行います。`model.gepa` の provider / model / base_url / api_key / timeout / max_tokens / extra_body は local `config.yaml` で指定でき、artifact では secret 系 key を redact します。GEPA は scorer の改善・比較・優先順位づけに使いますが、GEPA の点数だけで `auto_apply` は許可しません。

Compiled evaluator の active 化は `calibrate --execute` で扱います。candidate hash、regression result、active-before pointer hash / snapshot を calibration ledger に束縛し、`${HERMES_HOME:-~/.hermes}/self-improvement/gepa/active-evaluator.json` を更新します。regression runner 未設定・regression failure・candidate 不足では fail-closed にして active pointer を変更しません。新しい user-facing surface では expected hash や approval artifact を入力させません。

## ディレクトリ

- `plugin.yaml`: Hermes plugin manifest
- `__init__.py`: root の thin plugin entrypoint
- `hermes_self_improvement/`: 実装 package
- `hermes_self_improvement/cli.py`: CLI parser と pipeline orchestration
- `hermes_self_improvement/calibration.py`: calibration evidence、regression-gated active evaluator promotion、rollback
- `hermes_self_improvement/config.py`: apply_policy、calibration、model config、config precedence
- `hermes_self_improvement/observer.py`: hook observer、redaction、retention
- `hermes_self_improvement/analysis.py`: event aggregation と proposal generation
- `hermes_self_improvement/scoring.py`: scorer 実装
- `hermes_self_improvement/apply_plan.py`: dry-run apply plan と mutation plan
- `hermes_self_improvement/ledger.py`: pending ledger helpers（旧 low-risk apply/rollback は削除済み）
- `hermes_self_improvement/tool_handlers.py`: plugin tools。root 直下の `tools.py` は置かない
- `evals/`: offline scorer の rubric と regression cases
- `skills/operations/`: bundled operational skill
- `tests/`: pytest suite

## Artifact の保存先

既定では `${HERMES_HOME:-~/.hermes}/self-improvement/` 配下に保存します。保存場所の user-facing config override は現時点では提供しません。

- `state/events.jsonl`: observed events
- `daily/latest.md`: daily report
- `apply-plans/YYYY-MM-DD/`: dry-run apply plans
- `ledgers/YYYY-MM-DD/`: apply / calibration ledgers

Legacy directories from the pre-simplification flow, especially `apply-attempts/` and `approvals/`, are treated as read-only historical artifacts. They can appear in retention inventory, but this plugin no longer exposes a cleanup/prune command or tool. If they need to be removed, do it manually after reviewing the report output and backing up anything needed.

`config.json`, plugin-local `config.yaml`, `config.local.json`, `config.local.yaml`, `HERMES_SELF_IMPROVE_CONFIG`, `--config` で保存先や scorer 設定を上書きできます。precedence は defaults < `config.json` < `config.yaml` < `config.local.json` < `config.local.yaml` < env < CLI です。`config.example.yaml` は git-managed な雛形で、local `config.yaml` / `config.local.yaml` は gitignore されています。`model.llm` / `model.gepa` の `api_key` は local YAML で `${ENV}` 参照にできますが、`.env` / `.env.example` は使いません。

## 開発

```bash
cd /path/to/hermes-self-improvement
uv sync --group dev
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
bin/hermes-self-improve status
bin/hermes-self-improve calibrate --json
```

plugin registration、tool schema、bundled skill discovery を触ったら plugin manager loading も確認します。

```bash
$PY - <<'PY'
from hermes_cli.plugins import discover_plugins, get_plugin_manager
import json

discover_plugins(force=True)
info = [p for p in get_plugin_manager().list_plugins() if p['name'] == 'hermes-self-improvement']
print(json.dumps(info, ensure_ascii=False, indent=2))
PY
```

開発時の原則です。

- hook は軽く保つ
- safety gate は code と tests で守る
- 新しい mutation は TDD で fail-closed を先に固定する
- destructive / broad mutation は通常 apply で ready にせず human review / calibration gate に倒す
- target repo の commit は plugin では作らない
