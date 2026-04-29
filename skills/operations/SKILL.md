---
name: operations
description: Hermes self-improvement plugin（`hermes-self-improvement`）の設計・実装・検証・運用に使う bundled operational skill。runtime hook、telemetry、proposal/scorer/report、GEPA/LLM scorer、execution mode、apply-plan/ledger、安全な skill/memory 改善を扱うときは `skill_view("hermes-self-improvement:operations")` で明示的に読む。一般配布向けに、環境固有パスやローカル cron 前提を混ぜず、この skill を短い operational index として使う。
---

# hermes-self-improvement operations

Hermes の skill / memory / prompt / tool-use workflow を改善するための user plugin を扱う operational index。
詳細な設計・長い policy・roadmap はこの skill に積み増さず、repo-tracked docs / plan に置く。ここには、作業時に毎回必要な判断と参照先だけを残す。

## まず守ること

- Hermes 本体や upstream-managed code を直接編集しない。plugin 内で解決する。
- Runtime hook は観測専用にする。hook 内で LLM、GEPA optimizer、skill patch、memory edit、重い集計を実行しない。
- 問題抽出、proposal 生成、採点、report、apply-plan は CLI / cron / explicit evaluator command から明示的に実行する。
- DSPy/GEPA は `hermes-self-improvement` plugin の evaluator path では必須依存として扱う。ただし hook / plugin discovery path では lazy import を維持し、Hermes runtime 全体の必須依存にはしない。
- DSPy/GEPA evaluator の LLM call は Hermes で認証済みの provider routing を使う。default は Hermes auxiliary model。`reflection_model` / `task_model` は model name override のみで、`null` は Hermes auxiliary default を意味する。plugin 独自に OpenAI / Anthropic / LiteLLM API key や provider selector を持たせない。
- `model.llm` / `model.gepa` / `model.mutation` は Hermes auxiliary task config と同じ ergonomics（`provider`, `model`, `base_url`, `api_key`, `timeout`, `max_tokens`, `extra_body`）にし、呼び出し自体は `agent.auxiliary_client.call_llm(...)` 経由にする。local `config.yaml` は gitignore、`config.example.yaml` は placeholder のみ。`.env` / `.env.example` はこの用途では作らず、custom endpoint secret が必要なら local YAML の `${ENV}` 参照を使う。
- Runtime scorer の `--scorer gepa` は real DSPy / GEPA path を使い、dependency-free offline baseline に黙って fallback しない。deterministic scaffold は必要なら tests / fixtures / private helper に閉じる。
- LLM / GEPA scoring は advisory only。`auto_apply` は常に false 扱いにし、無人変更の許可として使わない。GEPA/LLM comparison を self-improvement decision の default input とし、score / recommendation / risk / confidence / target / rationale の material disagreement は human review に倒して unattended apply を block する。material 判定は change type ごとの policy config で扱い、risk / recommendation disagreement は常に block、memory / lifecycle / destructive / broad change は厳しめ、typo / pitfall / validation addition は score / confidence threshold だけ少し緩めてもよい。`report` / `plan` / `improve` は compare default。
- Evaluator 自体も自己改善対象にする。GEPA/LLM disagreement、human review outcome、rollback/failure ledger、regression eval cases から candidate evaluator を生成・評価してよいが、active evaluator への昇格は `calibrate --execute` の regression gate を通った場合だけにする。candidate hash / active-before pointer/hash / regression result / rollback data を calibration ledger に束縛して silent replacement を禁止する。
- Primary surface では `--execute` を唯一の user-facing mutation boundary にする。旧 `execution_mode` / capability gate / approval artifact / expected-hash command は削除済みで、通常 apply は `apply_policy` と内部 hash / target drift checks で fail-closed にする。
- この plugin の mutation 対象は、ユーザーが plugin を入れた Hermes 環境の mutable local skills と memory。skill は `skill_manage` が編集できる `$HERMES_HOME/skills` 配下、かつ hub-installed / built-in ではないものだけ。plugin-bundled skill、hub-installed skill、built-in skill、external skill dirs、plugin 自身の README / AGENTS.md / config、任意 docs/config file は自己改善対象にしない。skill に同梱された README / reference などの supporting file は、skill の一部として必要な場合だけ `skill_manage` 経由で扱う。
- 変更前に `git status --short` と対象 diff を確認し、無関係な変更を巻き戻さない。

## 主要パス

実装 package は `hermes_self_improvement/`。root `__init__.py` は Hermes plugin discovery の thin entrypoint として残し、root 直下に `tools.py` は置かない。


- `plugin.yaml`: plugin manifest。
- `__init__.py`: thin plugin entrypoint。Hermes discovery 用に root に残し、実装 package を re-export。
- `hermes_self_improvement/schemas.py`: plugin tool schema。
- `hermes_self_improvement/tool_handlers.py`: CLI parity tool handler。root 直下の `tools.py` は Hermes core `tools.registry` を shadow するため使わない。
- `hermes_self_improvement/config.py`: default config、config precedence、apply_policy、calibration config。
- `hermes_self_improvement/observer.py`: hook observer、redaction、JSONL telemetry、retention。
- `hermes_self_improvement/analysis.py`: event aggregation、finding 抽出、proposal 生成。explicit `memory_compression_candidate` / `skill_lifecycle_candidate` finding と `self_improvement_candidate` event は review-required proposal として扱い、auto-apply 許可にはしない。`scan_memory_compression_candidates()` / `scan_skill_lifecycle_candidates()` は dry-run candidate event だけを作る。
- `hermes_self_improvement/scoring.py`: heuristic / LLM / GEPA / compare scorer。
- `hermes_self_improvement/dspy_program.py`: real DSPy scoring contract / module boundary。deterministic baseline は runtime scorer ではなく regression fixture に閉じる。
- `hermes_self_improvement/gepa_adapter.py`: GEPA payload、offline fixture eval、real DSPy/GEPA path の fail-closed 境界。
- `hermes_self_improvement/apply_plan.py`: dry-run apply plan と low-risk mutation planning。
- `hermes_self_improvement/mutation_policy.py`: provider-aware memory mutation policy、strategy resolver、skill/memory context builder。
- `hermes_self_improvement/mutation_worker.py`: tool-mediated mutation executor。skill mutation は `skill_manage` の許可 action のみ実行可。built-in memory は `memory` tool、外部 memory は provider-native correction/delete tool のみ。直接 fallback はしない。generic direct file mutation は apply / rollback 実行 path では無効で、skill supporting file は `skill_manage` 経由でのみ扱う。
- `hermes_self_improvement/calibration.py`: calibration evidence collection、regression-gated active evaluator promotion、calibration rollback。
- `hermes_self_improvement/ledger.py`: pending ledger helpers。旧 low-risk apply / rollback skeleton は削除済み。
- `hermes_self_improvement/cli.py`: CLI parser、report rendering、recent plan/apply/calibration summary integration、pipeline orchestration。
- `bin/hermes-self-improve`: standalone wrapper CLI。
- `evals/proposal/`: GEPA offline scorer の repo-tracked public proposal eval assets。`rubric.json` は scorer contract、`cases.jsonl` は bundled golden regression seed。plugin 利用ユーザーが環境ごとに変更するものではない。
- `skills/operations/SKILL.md`: この bundled operational skill。

Runtime artifact は既定で `${HERMES_HOME:-~/.hermes}/self-improvement/` 配下に保存する。保存場所の user-facing config override は現時点では提供しない。主な subdirectory は `apply-plans/`, `ledgers/`, `state/`, `daily/`, `gepa/`, `cache/`。

## 日常コマンド

Repository root から実行する。

```bash
bin/hermes-self-improve status
bin/hermes-self-improve improve
bin/hermes-self-improve improve --execute
bin/hermes-self-improve calibrate
bin/hermes-self-improve calibrate --execute
bin/hermes-self-improve plan --since-hours 24 --scorer compare
bin/hermes-self-improve apply <plan-id>
bin/hermes-self-improve apply <plan-id> --items step-001,step-002
bin/hermes-self-improve apply <plan-id> --items step-001 --execute
bin/hermes-self-improve rollback <ledger-id>
bin/hermes-self-improve rollback <ledger-id> --execute
bin/hermes-self-improve report --since-hours 24 --scorer compare
```

Primary CLI / tool surface は `improve / calibrate / plan / apply / rollback / report / status`。`--execute` なしは preview-only。item hash / target hash / ledger hash は internal validation / drift detection / rollback 用で、user-facing option にしない。`rollback --execute` は事前に ledger hash と全 applied item の current target hash / rollback data を検証し、drift / tamper が 1 件でもあれば partial rollback しない。`report` は recent plan、recent apply、calibration、retention inventory、needs-review highlights を統合し、旧 approval gate summary は出さない。retention cleanup は read-only inventory に留め、削除・prune 用 command/tool は戻さない。

Legacy/debug commands (`generate-apply-plan`, `gepa-eval`, `gepa-optimize`, `ledger-report`, `approval-report`, `retention-report`, `retention-prune`, approval/low-risk commands) は CLI / tool surface から外す。内部 helper や古い module が残る場合も primary path から呼ばない。

Primary plugin tools:

```text
self_improvement_status
self_improvement_report
self_improvement_improve
self_improvement_calibrate
self_improvement_plan
self_improvement_apply
self_improvement_rollback
```

## 変更時の進め方

1. `README.md`, `AGENTS.md`, 関連 reference を読む。auto-apply / apply-policy / roadmap を続ける作業では、必ず repo-tracked plan（例: `.hermes/plans/*self-improvement-auto-apply-policy.md`）も読んでから、今回の変更が docs / runtime / scorer / apply-policy のどこに属するか切り分ける。
2. 新しい policy / apply / scorer 挙動は TDD で fail-closed を先に固定してから実装する。
3. Hook path を触る場合は、redaction・retention・partial event filtering が壊れないか確認する。
4. Scorer path を触る場合は、advisory-only と `auto_apply: false` を崩さない。
5. Apply-plan / ledger path を触る場合は、target hash、rollback preview、explicit target resolution、scorer disagreement gate、non-compare scorer が unattended eligible にならないことを確認する。stale path / command は canonical replacement が README/config/実ファイル/active memory/observed success などで独立確認できる場合だけ skill mutation plan を許可する。plugin 自身の docs/config や任意 docs/config file を mutation target にしない。
6. 実 mutation slice を追加するときは preview-first を崩さない。新しい簡素 surface では `apply <plan-id>` が preview、`apply <plan-id> --execute` が実行で、item hash / target baseline は内部検証する。`skill_create` / `skill_delete` / `skill_rename` / `skill_merge` / `memory_delete` / `evaluator_promote` のような lifecycle / destructive / active-evaluator mutation は通常 apply では ready にせず、まず `calibrate` や human-review plan に倒す。新しい destructive / broad mutation は低リスク apply に混ぜない。
7. `__init__.py` / registration / bundled skill discovery を触ったら、unit test だけでなく plugin manager loading も確認する。
8. Tool handler を触る場合は、wrapper CLI に shell out せず、CLI と同じ core function を使う。
9. Config / policy を触る場合は、defaults < `config.json` < plugin-local `config.yaml` < `config.local.json` < `config.local.yaml` < `HERMES_SELF_IMPROVE_CONFIG` < `--config` の precedence を確認する。explicit env / CLI config は JSON/YAML どちらも fail-closed に扱う。

## 検証 checklist

通常変更後:

```bash
uv sync --group dev
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
bin/hermes-self-improve status
```

Scorer / GEPA / eval asset 変更後:

```bash
bin/hermes-self-improve calibrate --json
$PY -m pytest tests/test_gepa_eval_assets.py tests/test_gepa_optimizer.py tests/test_gepa_offline_scorer.py -q
```

Registration / discovery / plugin tool surface 変更後:

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

Expected: enabled true, error null, hooks > 0。Tool を追加・削除した場合は `plugin.yaml`、`hermes_self_improvement/schemas.py`、`hermes_self_improvement/tool_handlers.py`、root/package `__init__.py` の handler map、`tests/test_plugin_tools.py` を同時に更新し、既存 tests に hard-coded tool count assertion がないか検索して期待値も合わせる。Discovery output の `tools` count も確認する。

## 詳細 reference

必要になった部分だけ読む。

- `references/architecture.md`: hook、telemetry、module layout、scorer / GEPA の仕組み。
- `references/safety-and-apply.md`: execution mode、apply-plan、ledger、auto-apply 境界。
- `references/operations.md`: scheduled maintenance、memory/custom-skill review、plugin discovery、pitfalls。

## Pitfalls

- Tool result classification は structured success/error field を優先する。raw text に `timeout`, `not found`, `permission denied` が含まれるだけで failure cluster にしない。
- Findings は `(tool_name, error_kind)` で cluster 化し、同じ remediation は proposal 側で集約する。
- `target_path` / `path` / `file_path` / `skill_path` がある場合は直接 hint を優先し、自然言語 title から target を推測しない。
- `target_skill` / `skill_name` / `skill` は Hermes の mutable local skills（`skill_manage` が編集できる `$HERMES_HOME/skills` 配下、かつ hub-installed / built-in ではない skill）だけに解決する。absolute path・`..`・root escape、plugin-bundled skill、external skill dirs は拒否する。
- Plugin-bundled skills は read-only として扱われ、現在実行中の agent session にはすぐ現れない場合がある。discovery reload / new session / gateway restart の必要性を疑う。
- `importlib.util.module_from_spec` で unit test する場合は、`exec_module` 前に `sys.modules[spec.name] = module` を入れる。`@dataclass` 処理が失敗するのを避けるため。
- `cli.py` の parser / handler を unit test するとき、direct file spec import だと相対 import が失敗し、fallback の bare import（例: `from analysis import ...`）も `sys.path` 次第で失敗しやすい。CLI 全体の parser を見るテストは repo root を一時的に `sys.path` に入れて `importlib.import_module("hermes_self_improvement.cli")` で package import する。個別 adapter/module の fake dependency test は file spec import でよい。
- DSPy/GEPA dependency を `python3 -m pip install -e .` で入れる作業は、Safehouse の書き込み制限で dependency install が途中失敗することがある。特に `litellm/proxy/auth/public_key.pem` への `Operation not permitted` を見たら、まず `python3 -m ensurepip --upgrade` で壊れた pip/certifi を復旧し、次に active runtime の `dspy_available` / `bin/hermes-self-improve status` で実際に DSPy が見えているか確認する。plugin 側は missing DSPy を fail-closed にし、offline fixture を runtime scorer の代替にしない。
- DSPy/GEPA scorer tests は基本 fake dependency で書く。runtime hook / normal import が `dspy` を eager import しないことを守るため、unit tests では `require_dspy()` や program module boundary を monkeypatch し、実 installed DSPy に依存する test は opt-in smoke に寄せる。`score_with_gepa()` では mode/config validation をできるだけ `require_dspy()` より前に置き、missing dependency が config error を不必要に覆い隠さないようにする。
- DSPy を Hermes 認証済み provider routing へ接続するときは、plugin-local `model.gepa` を `dspy.BaseLM` bridge に渡し、`agent.auxiliary_client.call_llm(...)` の戻りを OpenAI chat completion 互換 object（`choices[].message.content`, `model`, `usage`, `_hidden_params`）に整形してから DSPy に返す。real DSPy program は `dspy.context(lm=bridge)` 内で `dspy.Predict` を呼び、`gepa-optimize` は同じ bridge を student program と `dspy.GEPA(reflection_lm=...)` に渡す。fake-DSPy tests では `BaseLM` / `context` の有無で分岐し、live LLM/network に依存しない。
- GEPA optimizer / trainset 変換では malformed eval case を `rejected` として記録するだけで終わらせず、optimizer training / compile path では non-empty rejected set を fail-closed にする。report / non-optimizer path では rejected を表示して継続してよいが、partial train silently は避ける。
