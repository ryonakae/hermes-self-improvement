# AGENTS.md

`hermes-self-improvement` は、Hermes runtime の観測イベントから skill / memory / prompt / tool-use workflow の改善候補を作る user plugin です。hook は観測だけを行い、mutation は CLI または plugin tool の明示操作で扱います。

## 最初に見るもの

- 全体像: `README.md`
- 安全境界: `skills/operations/references/safety-and-apply.md`
- 長期方針: `.hermes/plans/2026-04-26_185111-self-improvement-auto-apply-policy.md`
- 運用 index: `skills/operations/SKILL.md`

作業前に `git status --short` と対象 diff を確認してください。無関係な変更を戻さないでください。

## よく使うコマンド

現行環境では top-level の `hermes self-improvement ...` が安定して露出しているとは限りません。通常は wrapper を使います。

```bash
cd /path/to/hermes-self-improvement

bin/hermes-self-improve status
bin/hermes-self-improve analyze --since-hours 24 --json
bin/hermes-self-improve report --since-hours 24 --scorer compare
bin/hermes-self-improve run --since-hours 24 --json --scorer compare
bin/hermes-self-improve gepa-eval --json
```

Apply / approval / retention の確認です。

```bash
bin/hermes-self-improve generate-apply-plan --mode dry_run_plan --since-hours 24 --json --scorer compare
bin/hermes-self-improve ledger-report --mode report_only --status all --json
bin/hermes-self-improve approval-report --mode report_only --status all --include-previews --json
bin/hermes-self-improve retention-report --mode report_only --json
bin/hermes-self-improve retention-prune --mode apply_approved --json
```

実 mutation は preview を見てから hash を渡します。

```bash
bin/hermes-self-improve apply-low-risk <plan-id> <item-id> --mode apply_low_risk --confirm-apply --expected-item-hash <item_hash> --json
bin/hermes-self-improve rollback-low-risk <ledger-id> --mode apply_low_risk --confirm-rollback --expected-ledger-hash <ledger_hash> --json
bin/hermes-self-improve approve <plan-id> <item-id> --mode apply_approved --json
bin/hermes-self-improve apply-approved <approval-id> --mode apply_approved --confirm-approved-apply --expected-approval-hash <approval_hash> --expected-target-hash <current_hash> --json
bin/hermes-self-improve retention-prune --mode apply_approved --confirm-prune --expected-artifact-list-hash <artifact_list_hash> --json
```

## 検証

通常の変更後に実行します。

```bash
PY=${PYTHON:-python3}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
bin/hermes-self-improve status
```

GEPA / scorer / eval assets を触った場合です。

```bash
bin/hermes-self-improve gepa-eval --json
$PY -m pytest tests/test_gepa_eval_assets.py tests/test_gepa_eval_cli.py tests/test_gepa_offline_scorer.py -q
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

- hook は観測専用です。hook 内で LLM、GEPA optimizer、skill patch、memory edit、重い集計を実行しないでください。
- `execution_mode` は `hermes_self_improvement/config.py` と CLI / tool policy gate で検証します。未知 mode、未許可 command、足りない capability は拒否します。
- scorer は優先順位付けだけに使います。`auto_apply` は scorer に関係なく false 扱いです。
- telemetry には全文や secret を保存しません。redacted preview と hash を使います。
- plugin は target repo の commit を作りません。commit は target repo の workflow に委譲します。

Mutation の条件です。

- `generate-apply-plan`: dry-run artifact を作る。target file は変更しない。
- `apply-low-risk`: 実変更には `--confirm-apply --expected-item-hash` と validation が必要。
- `rollback-low-risk`: 実 rollback には `--confirm-rollback --expected-ledger-hash` と current target hash 検証が必要。
- `apply-approved`: 実変更には `--confirm-approved-apply --expected-approval-hash --expected-target-hash` と approval / target / rollback / post-write validation が必要。
- `retention-prune`: 実削除には `--confirm-prune --expected-artifact-list-hash` が必要。
- `replace_entire_file`: `skill_large_rewrite` / `memory_compress` 用の approval-gated mutation。low-risk unattended apply には入れない。
- `create_file` / `delete_file`: `skill_create` / `skill_delete` 用の approval-gated mutation。create は rollback で作成ファイルを削除し、delete は before snapshot から復元する。
- `rename_file` / `merge_files`: `skill_rename` / `skill_merge` 用の approval-gated mutation。rename は source exists + destination missing を必須にし、merge は destination 置換 + source 削除を multi-target rollback data で復元する。

## Plugin tools

`plugin.yaml`, `hermes_self_improvement/schemas.py`, `hermes_self_improvement/tool_handlers.py` で CLI parity の tools を登録しています。handler は wrapper CLI に shell out せず、CLI と同じ core function と policy gate を使います。

`self_improvement_status`, `self_improvement_generate_apply_plan`, `self_improvement_ledger_report`, `self_improvement_approval_report`, `self_improvement_validate_approval`, `self_improvement_retention_report`, `self_improvement_retention_prune`, `self_improvement_approve`, `self_improvement_apply_approved`, `self_improvement_apply_low_risk`, `self_improvement_rollback_low_risk`

root 直下に `tools.py` は置きません。Hermes core の `tools.registry` を shadow して plugin discovery を壊します。

## 重要パス

- `plugin.yaml`: plugin manifest
- `__init__.py`: root の thin plugin entrypoint
- `hermes_self_improvement/cli.py`: CLI parser と pipeline orchestration
- `hermes_self_improvement/config.py`: execution mode と deny-by-default policy
- `hermes_self_improvement/observer.py`: hook observer、redaction、JSONL telemetry、retention
- `hermes_self_improvement/analysis.py`: event aggregation と proposal generation
- `hermes_self_improvement/scoring.py`: heuristic / LLM / GEPA / compare scorer
- `hermes_self_improvement/apply_plan.py`: dry-run apply plan と mutation plan
- `hermes_self_improvement/ledger.py`: apply attempt、ledger、rollback
- `hermes_self_improvement/approvals.py`: approval artifact、validation、approved apply
- `hermes_self_improvement/tool_handlers.py`: plugin tools
- `evals/`: offline scorer の rubric / regression cases
- `skills/operations/`: bundled operational skill
- `tests/`: pytest suite

Runtime artifact は `${HERMES_HOME:-~/.hermes}/reports/self-improvement/` 配下に保存します。主な subdir は `state/`, `daily/`, `apply-plans/`, `ledgers/`, `apply-attempts/`, `approvals/` です。

## コーディング / テスト規約

- Python 3.11 前提。runtime hook 側に重い依存を増やさない。
- package import と direct file execution の両方に耐える import を保つ。
- 新しい policy / apply / scorer 挙動は、先に test で fail-closed を固定してから実装する。
- protected context、曖昧な target、複数一致、scorer disagreement、未検証 canonical replacement は mutation plan で拒否する。
- `__pycache__/`, `.pytest_cache/`, runtime log は commit しない。

## Cron / scheduled execution

Cron は plugin 内の scheduler ではなく Hermes runtime / scheduler 側の責務です。safe cron は report / dry-run に限定します。

```bash
bin/hermes-self-improve generate-apply-plan --mode dry_run_plan --since-hours 24 --json --scorer compare
bin/hermes-self-improve ledger-report --mode report_only --status applied --json
bin/hermes-self-improve approval-report --mode report_only --status all --json
bin/hermes-self-improve retention-report --mode report_only --json
```

cron では confirmation flag や expected hash を渡さないでください。候補を見つけたら plan path、item hash、ledger hash、risk、evidence、validation status を人間に渡します。
