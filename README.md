# hermes-self-improvement

`hermes-self-improvement` は、Hermes の実行ログから「skill、memory、prompt、tool の使い方をどこで直すべきか」を見つける user plugin です。

hook は観測だけをします。skill や memory を会話中に勝手に書き換えません。分析、採点、apply plan、承認、実適用は CLI または plugin tool から明示して実行します。

## できること

- Hermes runtime の hook event を JSONL に記録する
- tool error や warning から改善候補を作る
- proposal を heuristic / LLM / DSPy-backed GEPA scorer で採点する
- report、apply plan、ledger、approval、retention preview を artifact として残す
- 低リスクな text replacement を、hash と validation 付きで適用する
- approval 済み item を、approval hash と target hash 付きで適用する
- approval-gated に skill file の作成・削除・全置換を扱う
- 古い self-improvement artifact を preview し、確認済み list hash が一致した場合だけ prune する

保存する event は redacted preview と hash が中心です。secret らしき値や sensitive path は保存前に伏せます。

## しないこと

- hook 内で LLM や GEPA optimizer を呼ばない
- scorer の点数だけで unattended mutation を許可しない
- cron から confirmation 付き mutation を走らせない
- target repo の commit を作らない
- secret や本文全文を復元して保存しない

mutation は preview-first です。実ファイル変更には mode、confirmation flag、expected hash が必要です。

## 使い方

現行環境では `hermes self-improvement ...` が常に使えるとは限りません。通常は同梱 wrapper を使います。

```bash
cd /path/to/hermes-self-improvement

bin/hermes-self-improve status
bin/hermes-self-improve analyze --since-hours 24 --json
bin/hermes-self-improve report --since-hours 24 --json
bin/hermes-self-improve run --since-hours 24 --json
```

apply plan と review 系です。

```bash
bin/hermes-self-improve plan --since-hours 24
bin/hermes-self-improve apply <plan-id>
bin/hermes-self-improve apply <plan-id> --items step-001,step-002
bin/hermes-self-improve apply <plan-id> --items step-001 --execute
bin/hermes-self-improve generate-apply-plan --mode dry_run_plan --since-hours 24 --json
bin/hermes-self-improve ledger-report --mode report_only --status all --json
bin/hermes-self-improve approval-report --mode report_only --status all --include-previews --json
bin/hermes-self-improve retention-report --mode report_only --json
```

`apply` は既定で preview です。実変更は `--execute` を付けた場合だけ行い、item hash / target hash は内部で検証します。policy で許可されない item や review が必要な item は適用されません。

旧 guarded command は互換用に残っています。直接使う場合は、preview を見てから hash を渡します。

```bash
# low-risk item の preview または pending ledger 作成
bin/hermes-self-improve apply-low-risk <plan-id> <item-id> --mode apply_low_risk --json

# low-risk item の実適用
bin/hermes-self-improve apply-low-risk <plan-id> <item-id> \
  --mode apply_low_risk \
  --confirm-apply \
  --expected-item-hash <item_hash> \
  --json

# low-risk rollback の preview
bin/hermes-self-improve rollback-low-risk <ledger-id> --mode apply_low_risk --json

# low-risk rollback の実行
bin/hermes-self-improve rollback-low-risk <ledger-id> \
  --mode apply_low_risk \
  --confirm-rollback \
  --expected-ledger-hash <ledger_hash> \
  --json

# approval artifact 作成
bin/hermes-self-improve approve <plan-id> <item-id> --mode apply_approved --json

# approved item の preview
bin/hermes-self-improve apply-approved <approval-id> --mode apply_approved --json

# approved item の実適用
bin/hermes-self-improve apply-approved <approval-id> \
  --mode apply_approved \
  --confirm-approved-apply \
  --expected-approval-hash <approval_hash> \
  --expected-target-hash <current_hash> \
  --json

# retention prune preview
bin/hermes-self-improve retention-prune --mode apply_approved --json

# retention prune 実行
bin/hermes-self-improve retention-prune \
  --mode apply_approved \
  --confirm-prune \
  --expected-artifact-list-hash <artifact_list_hash> \
  --json
```

## Execution modes

Policy は `hermes_self_improvement/config.py` で検証します。prompt だけでは解除できません。

| mode | 主な用途 | mutation |
| --- | --- | --- |
| `report_only` | status、analyze、report、ledger/approval/retention report | なし |
| `dry_run_plan` | apply plan artifact の生成 | target file は変更しない |
| `apply_low_risk` | low-risk item の preview、apply、rollback | confirmation と expected hash が必要 |
| `apply_approved` | approval、approved apply、retention prune | confirmation と expected hash が必要 |

未知 mode、未許可 command、足りない capability は deny-by-default です。`allow_policy_expansion: true` を入れない限り、local config は default policy より権限を広げられません。

## Apply の安全境界

### Low-risk apply

`apply-low-risk` は、既定では preview / attempt / pending ledger を作るだけです。実適用には次が必要です。

- `--mode apply_low_risk`
- `--confirm-apply`
- `--expected-item-hash <item_hash>`
- target hash、rollback preview、post-write validation の成功

対象は狭い `replace_text_once` 系です。protected context、曖昧な target、複数一致、scorer disagreement、未検証 canonical replacement は拒否します。

### Approved apply

`apply-approved` は、既定では approval と target の検証、planned diff、rollback preview を返します。実適用には次が必要です。

- `--mode apply_approved`
- `--confirm-approved-apply`
- `--expected-approval-hash <approval_hash>`
- `--expected-target-hash <current_hash>`
- approval expiry、plan/item drift、rollback preview hash、rollback data、post-write validation の成功

`replace_entire_file` は approval-gated path だけで使います。`skill_large_rewrite` と `memory_compress` の土台ですが、low-risk unattended apply には入れません。

`skill_create` は存在しない target にだけ `create_file` mutation を作ります。rollback は作成ファイルの削除です。`skill_delete` は既存 target にだけ `delete_file` mutation を作ります。rollback は before snapshot の復元です。

`skill_rename` は source が存在し、destination が存在しない場合だけ `rename_file` mutation を作ります。rollback は destination を source へ戻します。`skill_merge` は source と destination の両方が存在し、replacement content がある場合だけ `merge_files` mutation を作ります。実適用では destination を置換して source を削除し、rollback は両方の before snapshot を復元します。これらは multi-target rollback data を ledger に残し、low-risk unattended apply には入れません。

`memory_delete` は configured `memory_roots` 配下の既存 file だけに `delete_file` mutation を作ります。rollback は before snapshot の復元です。root 外の target は `memory_target_outside_allowed_roots` で拒否します。

Proposal generation は、明示的な `memory_compression_candidate` finding を `memory_compress` proposal に、明示的な `skill_lifecycle_candidate` finding を `skill_create` / `skill_delete` / `skill_rename` / `skill_merge` proposal に変換できます。`self_improvement_candidate` event も同じ finding として passthrough します。`scan_memory_compression_candidates()` は memory file の単純な重複行を、`scan_skill_lifecycle_candidates()` は明示的に deprecated / obsolete と印がある skill file を dry-run candidate event として出せます。どれも `recommendation=approval_required` / `auto_apply=false` のままです。実際の変更は apply-plan と approval gate を通します。

### Retention prune

`retention-report` は read-only preview です。`retention-prune` も既定では削除候補と `artifact_list_hash` を返すだけです。実削除には次が必要です。

- `--mode apply_approved`
- `--confirm-prune`
- `--expected-artifact-list-hash <artifact_list_hash>`

削除対象は `apply-plans/`, `ledgers/`, `apply-attempts/`, `approvals/` の expired candidates だけです。malformed artifact は報告しますが削除しません。

## Plugin tools

`plugin.yaml` は agent-native tools を登録します。tool handler は wrapper CLI に shell out せず、CLI と同じ core function と policy gate を通します。

- `self_improvement_status`
- `self_improvement_gepa_eval`
- `self_improvement_gepa_optimize`（`report_only` + positive `max_full_evals` 必須。active evaluator pointer は更新しない）
- `self_improvement_generate_apply_plan`
- `self_improvement_ledger_report`
- `self_improvement_approval_report`
- `self_improvement_validate_approval`
- `self_improvement_retention_report`
- `self_improvement_retention_prune`
- `self_improvement_approve`
- `self_improvement_apply_approved`
- `self_improvement_apply_low_risk`
- `self_improvement_rollback_low_risk`

Mutation-capable tools も CLI と同じ confirmation と expected hash を要求します。

## Scorers

- `heuristic`: 依存なしの deterministic scorer。軽量な observation / debugging 用。
- `llm`: Hermes auxiliary LLM 経路。失敗時は `llm_scorer_error` を残して heuristic score を併記する。
- `gepa`: DSPy / GEPA evaluator path。`dspy` はこの plugin の evaluator 依存として必須だが、hook / plugin discovery では lazy import する。dependency-free offline baseline には黙って戻さない。
- `compare`: LLM と GEPA の disagreement を report に出す decision scorer。

`report`、`run`、`plan`、`generate-apply-plan` は、明示的に `--scorer` を渡さない限り `compare` を使います。`analyze` は観測・分類なので軽量な `heuristic` のままです。`--scorer gepa` は dependency-free offline baseline にフォールバックしません。active runtime に `dspy` が無い場合は `gepa_scorer_error` として明示します。`plan` / `generate-apply-plan` では、disagreement がなくても non-compare scorer の低リスク item は unattended apply eligible にせず、review / approval 側に倒します。

`compare` の disagreement 判定は `scorer_comparison_policy` で change type ごとに調整します。risk / recommendation mismatch は常に block、memory / lifecycle / destructive / broad change は strict threshold、`typo_fix` / `pitfall_addition_existing_section` / `validation_addition_existing_section` は少し緩い score / confidence threshold を使います。`generate-apply-plan` は `scorer_disagreements` と `scorer_comparison_policy` を item に残し、disagreement がある item は unattended eligible にしません。

```bash
python3 -m pip install -e .
```

`gepa-eval` は repo-tracked eval case の dependency-free regression fixture として残します。本物の optimizer run ではありません。Runtime `gepa` scorer / `gepa-optimize` は DSPy program に plugin-local `model.gepa` を渡し、DSPy 側の LM call は Hermes `agent.auxiliary_client.call_llm(...)` を通る `BaseLM` bridge で行います。`model.gepa` の provider / model / base_url / api_key / timeout / max_tokens / extra_body は local `config.yaml` で指定でき、artifact では secret 系 key を redact します。GEPA は scorer の改善・比較・優先順位づけに使いますが、GEPA の点数だけで `auto_apply` は許可しません。

Compiled evaluator の active 化は `evaluator_promote` change type の approval-gated apply-plan item として扱います。candidate path/hash と regression result hash を pointer payload に束縛し、`${reports_dir}/gepa/active-evaluator.json` または configured `active_evaluator_pointer_path` を `create_file` / `replace_entire_file` mutation で更新します。approval artifact は candidate id/path/hash、regression result hash、active-before pointer hash、rollback strategy も保持し、validation は candidate drift と active pointer drift を fail-closed にします。昇格は approval artifact、expected hash、rollback preview を通るまで実行されません。成功時は apply result / attempt / ledger に `evaluator_promotion` metadata を残します。

## ディレクトリ

- `plugin.yaml`: Hermes plugin manifest
- `__init__.py`: root の thin plugin entrypoint
- `hermes_self_improvement/`: 実装 package
- `hermes_self_improvement/cli.py`: CLI parser と pipeline orchestration
- `hermes_self_improvement/config.py`: execution mode と policy gate
- `hermes_self_improvement/observer.py`: hook observer、redaction、retention
- `hermes_self_improvement/analysis.py`: event aggregation と proposal generation
- `hermes_self_improvement/scoring.py`: scorer 実装
- `hermes_self_improvement/apply_plan.py`: dry-run apply plan と mutation plan
- `hermes_self_improvement/ledger.py`: apply attempt、ledger、rollback
- `hermes_self_improvement/approvals.py`: approval artifact、validation、approved apply
- `hermes_self_improvement/tool_handlers.py`: plugin tools。root 直下の `tools.py` は置かない
- `evals/`: offline scorer の rubric と regression cases
- `skills/operations/`: bundled operational skill
- `tests/`: pytest suite

## Artifact の保存先

既定では `${HERMES_HOME:-~/.hermes}/reports/self-improvement/` 配下に保存します。

- `state/events.jsonl`: observed events
- `daily/latest.md`: daily report
- `apply-plans/YYYY-MM-DD/`: dry-run apply plans
- `ledgers/YYYY-MM-DD/`: apply ledgers
- `apply-attempts/YYYY-MM-DD/`: apply attempt artifacts
- `approvals/YYYY-MM-DD/`: approval artifacts

`config.json`, plugin-local `config.yaml`, `config.local.json`, `config.local.yaml`, `HERMES_SELF_IMPROVE_CONFIG`, `--config` で保存先や scorer 設定を上書きできます。precedence は defaults < `config.json` < `config.yaml` < `config.local.json` < `config.local.yaml` < env < CLI です。`config.example.yaml` は git-managed な雛形で、local `config.yaml` / `config.local.yaml` は gitignore されています。`model.llm` / `model.gepa` の `api_key` は local YAML で `${ENV}` 参照にできますが、`.env` / `.env.example` は使いません。

## 開発

```bash
cd /path/to/hermes-self-improvement
uv sync --group dev
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
bin/hermes-self-improve status
bin/hermes-self-improve gepa-eval --json
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
- destructive / broad mutation は approval-gated path から始める
- target repo の commit は plugin では作らない
