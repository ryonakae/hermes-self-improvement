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
bin/hermes-self-improve ledger-report --status applied --json
bin/hermes-self-improve approval-report --status all --json
bin/hermes-self-improve retention-report --mode report_only --json
bin/hermes-self-improve approve <plan-id> <item-id> --mode apply_approved --json
bin/hermes-self-improve apply-approved <approval-id> --mode apply_approved --json
bin/hermes-self-improve apply-approved <approval-id> --mode apply_approved --confirm-approved-apply --expected-approval-hash <approval_hash> --expected-target-hash <current_hash> --json
bin/hermes-self-improve rollback-low-risk <ledger-id> --mode apply_low_risk --json
```

現行環境では top-level の `hermes self-improvement ...` が安定して露出しているとは限らないため、運用コマンドは `bin/hermes-self-improve` wrapper を優先します。

## 検証手順

変更後は、少なくとも次を実行します。

```bash
cd /path/to/hermes-self-improvement
PY=${PYTHON:-python3}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
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

## Stale path / command fixes

`stale_path_fix` / `stale_command_fix` は `replace_text_once` の dry-run mutation plan だけを生成します。対象にできるのは、古い参照と canonical replacement が明示され、target 内の古い参照が1回だけで、replacement が小さな1行文字列、かつ README / config / 実ファイル / active memory / observed success など信頼できる別ソースで確認済みの場合だけです。古い path / command が失敗しただけ、または LLM guess だけでは `canonical_replacement_unverified` として拒否します。

## Config / policy precedence

Config precedence is defaults < `config.json` < `config.local.json` < `HERMES_SELF_IMPROVE_CONFIG` < explicit `--config`. Explicit env / CLI config paths must exist and be valid JSON. `mode_policy` is restrictive by default: without `allow_policy_expansion: true`, custom policy may narrow permissions but cannot add commands or enable capabilities that defaults deny.

## Cron / scheduled execution

Cron / scheduled execution は plugin 内の scheduler 実装ではなく、Hermes runtime / scheduler 側の責務です。cron-run session は fresh session として self-contained prompt で実行し、recursive cron job を作らないでください。

安全な cron は report / dry-run に限定します。例:

```bash
bin/hermes-self-improve generate-apply-plan --mode dry_run_plan --since-hours 24 --json --scorer compare
bin/hermes-self-improve ledger-report --mode report_only --status applied --json
bin/hermes-self-improve approval-report --mode report_only --status all --json
```

cron では `apply-low-risk --confirm-apply` や `rollback-low-risk --confirm-rollback` を実行してはいけません。hash 付きの実 mutation は、人間の明示操作か別の explicit workflow に分離します。

## Report integration

`run` / `report` now include concise operational summaries when artifacts exist:

- `Apply ledger summary` lists recent low-risk ledgers across statuses for review;
- `Approval gate summary` lists recent approval artifacts and whether current validation is still valid;
- `Retention summary` lists expired artifact candidates and malformed files from the read-only retention preview.

The integration is read-only. It does not create, approve, apply, rollback, remove, or prune artifacts. Empty artifact sets stay quiet so routine reports do not gain noisy empty sections.

## Retention report

`retention-report` / `self_improvement_retention_report` は read-only preview です。`apply-plans/`, `ledgers/`, `apply-attempts/`, `approvals/` の artifact を集計し、`retention_days` より古い候補、malformed JSON、カテゴリ別件数を報告します。`--category` / tool `category` でカテゴリを絞り込めます。ファイルの削除・移動・圧縮・prune は行いません。実 cleanup を追加する場合も、まず preview と expected artifact list / hash による明示 confirmation を別 slice で設計します。

## Plugin tools

`plugin.yaml` / `hermes_self_improvement/schemas.py` / `hermes_self_improvement/tool_handlers.py` で CLI parity の tools を登録しています。`tools.py` という名前は Hermes core `tools.registry` を shadow するため使いません。tool handler は wrapper CLI に shell out せず、CLI と同じ core function と policy gate を使います。

登録 tools:

- `self_improvement_status`
- `self_improvement_generate_apply_plan`
- `self_improvement_ledger_report`
- `self_improvement_approval_report`
- `self_improvement_validate_approval`
- `self_improvement_retention_report`
- `self_improvement_approve`
- `self_improvement_apply_approved`
- `self_improvement_apply_low_risk`
- `self_improvement_rollback_low_risk`

`self_improvement_apply_approved` は approval artifact を検証して planned diff / rollback preview を返す preview-only tool です。`expected_approval_hash` / `expected_target_hash` を渡すと、operator が確認した approval hash と current target hash の一致も検証し、不一致なら `expected_approval_hash_mismatch` / `expected_target_hash_mismatch` で拒否します。valid preview には attempt / ledger の非永続 preview metadata（required confirmation、expected hashes、rollback preview hash、validation plan）も含めます。実 mutation は `--confirm-approved-apply` / tool `confirm_approved_apply=true` と `expected_approval_hash` / `expected_target_hash` が揃い、approval・target・rollback・post-write validation が通る場合だけです。`approval-report --include-previews` / tool `include_previews` は各 approval の preview status だけを集約し、target を変更しません。Mutation-capable tools は explicit confirmation/hash が揃わない限り target を変更しません。

## 重要パス

実装は `hermes_self_improvement/` package 配下に集約しています。root `__init__.py` は Hermes plugin discovery 用の thin entrypoint です。root 直下に `tools.py` は置きません。


- `plugin.yaml`: plugin manifest。
- `__init__.py`: thin plugin entrypoint。Hermes discovery 用に root に残し、実装 package を re-export。
- `hermes_self_improvement/schemas.py`: plugin tool schema。
- `hermes_self_improvement/tool_handlers.py`: CLI parity tool handler。
- `hermes_self_improvement/config.py`: default config、execution mode、deny-by-default policy。
- `hermes_self_improvement/observer.py`: hook observer、redaction、JSONL telemetry、retention。
- `hermes_self_improvement/analysis.py`: event aggregation、finding 抽出、proposal 生成。
- `hermes_self_improvement/scoring.py`: heuristic / LLM / GEPA / compare scorer。
- `hermes_self_improvement/dspy_program.py`: DSPy-compatible scoring contract と dependency-free baseline。
- `hermes_self_improvement/gepa_adapter.py`: GEPA payload、offline eval、optimizer fail-closed 境界。
- `hermes_self_improvement/apply_plan.py`: dry-run apply plan と low-risk mutation planning。
- `hermes_self_improvement/ledger.py`: pending ledger と apply attempt artifact。
- `hermes_self_improvement/approvals.py`: approval artifact generation / validation / report helpers。
- `hermes_self_improvement/cli.py`: CLI parser、report rendering、pipeline orchestration。
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
- `execution_mode` は prompt ではなく `hermes_self_improvement/config.py` / CLI policy で検証します。未知 mode / 未許可 command / 足りない capability は拒否します。
- `generate-apply-plan` は artifact 生成のみで、target file を変更しません。
- `apply-low-risk` は既定では preview / apply-attempt / pending ledger だけを書きます。target file の実変更は `--confirm-apply --expected-item-hash <item_hash>` があり、eligibility・before hash・rollback preview・post-write validation が通る場合だけです。`rollback-low-risk` も既定では非破壊で、実 rollback は `--confirm-rollback --expected-ledger-hash <ledger_hash>` と current target hash 検証が必要です。`apply-approved` と `approval-report --include-previews` は既定では validation-only / preview-only です。`apply-approved` の実変更は `--confirm-approved-apply --expected-approval-hash --expected-target-hash` があり、approval・target・rollback・post-write validation が通る場合だけです。
- 作業前に `git status --short` と該当 diff を確認し、無関係な変更を巻き戻さないでください。
- README は人間向けの入口、AGENTS.md はエージェント向けの最短作業入口として分けます。長い設計経緯は README か repo-tracked plan/docs に寄せてください。

## 追加ドキュメント

- `README.md`: plugin の目的、DSPy / GEPA の位置づけ、主要コマンド、保存先。
- `docs/` または repo-tracked plan: 方針整理やロードマップを置く場所。
- `skills/operations/SKILL.md`: 運用時に使う短い operational index。
- `skills/operations/references/`: architecture / safety / operations の詳細。
