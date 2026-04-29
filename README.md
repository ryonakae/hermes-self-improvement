# hermes-self-improvement

`hermes-self-improvement` は、Hermes の実行ログから「次に直すと Hermes が少し賢くなる場所」を見つける user plugin です。

たとえば、同じ tool error が何度も出る、古い skill の手順が失敗している、memory に圧縮できそうな繰り返し説明がある。そういう兆候を hook で観測し、改善候補としてまとめます。

この plugin は勝手に skill や memory を書き換えません。hook は観測だけをします。実変更は `apply` / `rollback` / `calibrate` などの明示コマンドで扱い、変更できる phase でも `--execute` が必要です。

## 何をする plugin か

この plugin は、Hermes の自己改善を「ログを見る」「候補を作る」「採点する」「人間が確認できる形にする」「安全に適用する」に分けます。

できること:

- Hermes runtime の hook event を JSONL に記録する
- tool error、warning、失敗した手順、繰り返し説明から改善候補を作る
- 候補を heuristic / LLM / DSPy-backed GEPA scorer で採点する
- report、apply plan、apply ledger、calibration ledger を artifact として残す
- policy で許可された低リスクな text replacement を、内部 hash と drift check 付きで適用する
- skill mutation は、直接ファイル編集ではなく `skill_manage` の create / patch / edit / delete / write_file / remove_file だけを使って適用する
- built-in memory mutation は `memory` tool の add / replace / remove だけを使って適用する。外部 memory provider は capability policy に解決し、stale/incorrect/duplicate `memory_delete` は各 provider の correction tool（例: `hindsight_retain`, `honcho_conclude`, `mem0_conclude`, `brv_curate`, `viking_remember`, `fact_store`, `retaindb_remember`, `supermemory_store`）で実行可能。native delete は provider-native ID がある場合だけ実行し、sensitive delete や provider tool 不在時は fail-closed
- evaluator/scorer の調整を `calibrate` で preview し、regression を通った場合だけ active 化する

しないこと:

- hook 内で LLM や GEPA optimizer を呼ぶ
- scorer の点数だけで unattended mutation を許可する
- cron から confirmation 付き mutation を走らせる
- target repo の commit を作る
- secret、本文全文、sensitive path をそのまま保存する

保存する event は redacted preview と hash が中心です。secret らしき値は保存前に伏せます。

## 大まかな仕組み

```text
Hermes runtime
  ↓ hooks
observer.py
  ↓ redacted events
~/.hermes/self-improvement/state/events.jsonl
  ↓ aggregate
analysis.py
  ↓ proposals
scoring.py  (heuristic / LLM / GEPA / compare)
  ↓
plan / report / improve
  ↓
apply_engine.py  (--execute のときだけ mutation)
  ↓
ledgers / rollback data
```

主要な部品です。

- `observer.py`: Hermes の hook event を受け取り、redact して保存する
- `analysis.py`: event を集計し、改善候補を作る
- `scoring.py`: 候補に score、risk、recommendation、confidence を付ける
- `apply_plan.py`: 変更案を plan artifact にする
- `apply_engine.py`: `--execute` 時にだけ検証済み item を適用する
- `calibration.py`: scorer/evaluator の更新候補を作り、regression 後に active 化する
- `tool_handlers.py`: agent-native tool surface を提供する

hook は軽く保ちます。重い判断、LLM call、optimizer は CLI / tool command 側で動かします。

## DSPy / GEPA とは

### DSPy

DSPy は、LLM を使う処理を「prompt の文字列」ではなく「入出力を持つ program」として書くための framework です。

この plugin では、GEPA scorer の evaluator を DSPy program として扱います。DSPy 自体が勝手に Hermes を改善するわけではありません。候補をどう採点するか、どの evidence を見るか、どう regression するかを構造化するために使います。

### GEPA

GEPA は、DSPy program を改善する optimizer です。ここでは「改善候補を採点する evaluator」を育てるために使います。

この plugin での GEPA の役割は、skill や memory を直接書き換えることではありません。GEPA は scorer/evaluator の改善候補を作ります。`calibrate --execute` は、十分な evidence と regression pass がある場合だけ active evaluator pointer を更新します。

つまり流れはこうです。

```text
session logs / outcomes
  ↓
calibration evidence
  ↓
GEPA candidate evaluator
  ↓ regression
active evaluator
  ↓
future proposal scoring
```

GEPA の score が高くても、そのまま自動適用はしません。mutation は `apply_policy`、internal hash、target drift check を通った item だけです。

## 自己改善の流れ

普段は `improve` を使います。

```bash
bin/hermes-self-improve improve
```

`improve` は次をまとめて実行します。

1. `calibrate`: scorer/evaluator を更新できるだけの evidence があるか見る
2. `plan`: 直近 event から改善候補と apply plan を作る
3. `apply`: plan を preview する
4. `summary`: 何が見つかり、何を人間が見るべきか返す

`--execute` を付けると mutation-capable phase まで進みます。

```bash
bin/hermes-self-improve improve --execute
```

ただし、`--execute` は「何でも変えてよい」という意味ではありません。実際に変更されるのは、policy と検証を通った item だけです。review が必要な item、drift した target、scorer disagreement がある item は止まります。

手動で分けて確認したい場合:

```bash
bin/hermes-self-improve status
bin/hermes-self-improve report --since-hours 24 --json
bin/hermes-self-improve calibrate
bin/hermes-self-improve calibrate --execute
bin/hermes-self-improve plan --since-hours 24
bin/hermes-self-improve apply <plan-id>
bin/hermes-self-improve apply <plan-id> --items step-001 --execute
bin/hermes-self-improve rollback <ledger-id>
bin/hermes-self-improve rollback <ledger-id> --execute
```

## Safety model

Primary surface の安全境界は `--execute` です。

- `improve`, `calibrate`, `apply`, `rollback` は `--execute` なしでは preview-only
- `apply_policy` が通常の skill/memory 改善の適用範囲を決める
- `calibration` が evaluator/scorer 自己調整を決める。`apply_policy` とは別
- `item_hash`, `target_hash`, `ledger_hash` は内部整合性、drift 検知、rollback 用
- `rollback --execute` は ledger hash と current target hash を検証する。1 item でも drift / tamper があれば rollback しない
- skill / memory mutation の直接ファイル・DB fallback は使わない。skill mutation は `skill_manage` 経由、built-in memory は `memory` tool 経由。外部 memory provider は provider-native tool 経由に限定し、stale/incorrect/duplicate delete は provider の correction tool、native delete は provider-native ID がある場合だけ使う。sensitive delete と tool 不在 runtime は fail-closed

既定 policy の例です。

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

## CLI surface

Primary command は 7 個だけです。

```bash
bin/hermes-self-improve improve
bin/hermes-self-improve calibrate
bin/hermes-self-improve plan
bin/hermes-self-improve apply
bin/hermes-self-improve rollback
bin/hermes-self-improve report
bin/hermes-self-improve status
```

現行環境では top-level の `hermes self-improvement ...` が安定して露出しているとは限りません。通常は repo 同梱 wrapper を使います。

Legacy/debug command は primary surface に戻しません。`generate-apply-plan`, `gepa-eval`, `gepa-optimize`, `ledger-report`, `approval-report`, `retention-report`, guarded approval/retention pruning は使わず、上の 7 command に寄せます。

## Plugin tools

`plugin.yaml` は agent-native tools を登録します。tool handler は wrapper CLI に shell out せず、CLI と同じ core function を呼びます。

Primary tool surface も 7 個だけです。

- `self_improvement_status`
- `self_improvement_report`
- `self_improvement_improve`
- `self_improvement_calibrate`
- `self_improvement_plan`
- `self_improvement_apply`
- `self_improvement_rollback`

Tool でも `execute=false` が preview-only、`execute=true` が mutation intent です。`mode` / `confirm_*` / `expected_*hash` は primary schema に出しません。

## Scorers

- `heuristic`: 依存なしの deterministic scorer。軽量な observation / debugging 用
- `llm`: Hermes auxiliary LLM 経路。失敗時は `llm_scorer_error` を残し、heuristic score も併記する
- `gepa`: DSPy / GEPA evaluator path。`dspy` が使えない場合は error として明示し、dependency-free baseline に黙って戻さない
- `compare`: LLM と GEPA の disagreement を report に出す decision scorer

`improve`、`report`、`plan` は、明示的に `--scorer` を渡さない限り `compare` を使います。

`compare` は disagreement を保守的に扱います。risk / recommendation mismatch は block、memory / lifecycle / destructive / broad change は strict threshold、typo や既存 section への validation 追加は少し緩い threshold を使います。disagreement がある item は unattended apply eligible にしません。

GEPA regression / optimizer internals は `calibrate` の内部で扱います。Runtime `gepa` scorer は DSPy program に plugin-local `model.gepa` を渡し、DSPy 側の LM call は Hermes `agent.auxiliary_client.call_llm(...)` を通る `BaseLM` bridge で行います。`model.gepa` の provider / model / base_url / api_key / timeout / max_tokens / extra_body は local `config.yaml` で指定できます。artifact では secret 系 key を redact します。

## Artifact の保存先

Runtime artifact は固定で `${HERMES_HOME:-~/.hermes}/self-improvement/` 配下に保存します。保存場所の user-facing config override は提供しません。

主な subdir:

- `state/events.jsonl`: observed events
- `daily/latest.md`: latest report
- `daily/YYYY-MM-DD.md`: dated reports
- `apply-plans/YYYY-MM-DD/`: dry-run apply plans
- `ledgers/YYYY-MM-DD/`: apply / calibration ledgers
- `gepa/active-evaluator.json`: active evaluator pointer
- `gepa/programs/`: compiled evaluator artifacts
- `cache/dspy/`: DSPy cache

Repo 側の `evals/` は共通 seed / regression assets です。user-specific な evidence、report、ledger、active evaluator は runtime root に置きます。

## 設定

設定は plugin-local `config.yaml` / `config.local.yaml` などで扱います。保存場所は変えません。

Precedence:

```text
defaults
  < config.json
  < config.yaml
  < config.local.json
  < config.local.yaml
  < HERMES_SELF_IMPROVE_CONFIG
  < --config
```

`config.example.yaml` は git-managed な雛形です。local `config.yaml` / `config.local.yaml` は gitignore されています。`model.llm` / `model.gepa` / `model.mutation` の `api_key` は local YAML で `${ENV}` 参照にできます。`.env` / `.env.example` は使いません。`model.mutation` は isolated mutation worker 用の model selection で、実行 policy や fallback 設定ではありません。

## ディレクトリ

- `plugin.yaml`: Hermes plugin manifest
- `__init__.py`: root の thin plugin entrypoint
- `hermes_self_improvement/`: 実装 package
- `hermes_self_improvement/cli.py`: CLI parser と pipeline orchestration
- `hermes_self_improvement/config.py`: apply_policy、calibration、model config、config precedence
- `hermes_self_improvement/observer.py`: hook observer、redaction、retention
- `hermes_self_improvement/analysis.py`: event aggregation と proposal generation
- `hermes_self_improvement/scoring.py`: scorer 実装
- `hermes_self_improvement/apply_plan.py`: dry-run apply plan と mutation plan
- `hermes_self_improvement/apply_engine.py`: mutation と rollback ledger
- `hermes_self_improvement/mutation_policy.py`: provider-aware memory mutation policy と skill/memory context builder
- `hermes_self_improvement/mutation_worker.py`: tool-mediated mutation executor。skill mutation は `skill_manage`、built-in memory は `memory`、外部 memory は provider-native correction/delete tool だけ実行可
- `hermes_self_improvement/calibration.py`: calibration evidence、regression-gated active evaluator promotion、rollback
- `hermes_self_improvement/ledger.py`: ledger helpers
- `hermes_self_improvement/tool_handlers.py`: plugin tools。root 直下の `tools.py` は置かない
- `evals/`: offline scorer の rubric と regression cases
- `skills/operations/`: bundled operational skill
- `tests/`: pytest suite

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
- destructive / broad mutation は通常 apply で ready にせず、human review / calibration gate に倒す
- target repo の commit は plugin では作らない
