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
- Runtime scorer の `--scorer gepa` は real DSPy / GEPA path を使い、dependency-free offline baseline に黙って fallback しない。deterministic scaffold は必要なら tests / fixtures / private helper に閉じる。
- LLM / GEPA scoring は advisory only。`auto_apply` は常に false 扱いにし、無人変更の許可として使わない。GEPA/LLM comparison を self-improvement decision の default input とし、score / recommendation / risk / confidence / target / rationale の material disagreement は human review / approval-required に倒して unattended apply を block する。material 判定は change type ごとの policy config で扱い、risk / recommendation disagreement は常に block、memory / lifecycle / destructive / broad change は厳しめ、typo / pitfall / validation addition は score / confidence threshold だけ少し緩めてもよい。`report` / `run` / `generate-apply-plan` は compare default、軽量 `analyze` は heuristic default でよい。
- Evaluator 自体も自己改善対象にする。GEPA/LLM disagreement、human approval/rejection、rollback/failure ledger、regression eval cases から candidate evaluator を生成・評価してよいが、active evaluator への昇格は既存 approval artifact model に乗せた approval-gated `evaluator_promote` とし、candidate hash / active-before pointer/hash / regression result hash / rollback pointer を束縛して silent replacement を禁止する。
- `execution_mode` と capability gate は prompt ではなく plugin CLI / config / policy code で検証する。
- 変更前に `git status --short` と対象 diff を確認し、無関係な変更を巻き戻さない。

## 主要パス

実装 package は `hermes_self_improvement/`。root `__init__.py` は Hermes plugin discovery の thin entrypoint として残し、root 直下に `tools.py` は置かない。


- `plugin.yaml`: plugin manifest。
- `__init__.py`: thin plugin entrypoint。Hermes discovery 用に root に残し、実装 package を re-export。
- `hermes_self_improvement/schemas.py`: plugin tool schema。
- `hermes_self_improvement/tool_handlers.py`: CLI parity tool handler。root 直下の `tools.py` は Hermes core `tools.registry` を shadow するため使わない。
- `hermes_self_improvement/config.py`: default config、config precedence、execution mode、policy gate。
- `hermes_self_improvement/observer.py`: hook observer、redaction、JSONL telemetry、retention。
- `hermes_self_improvement/analysis.py`: event aggregation、finding 抽出、proposal 生成。explicit `memory_compression_candidate` / `skill_lifecycle_candidate` finding と `self_improvement_candidate` event は approval-required proposal に変換するが、auto-apply 許可にはしない。`scan_memory_compression_candidates()` / `scan_skill_lifecycle_candidates()` は dry-run candidate event だけを作る。
- `hermes_self_improvement/scoring.py`: heuristic / LLM / GEPA / compare scorer。
- `hermes_self_improvement/dspy_program.py`: DSPy-compatible scoring contract と offline baseline。
- `hermes_self_improvement/gepa_adapter.py`: GEPA payload、offline eval、optimizer fail-closed 境界。
- `hermes_self_improvement/apply_plan.py`: dry-run apply plan と low-risk mutation planning。
- `hermes_self_improvement/ledger.py`: pending ledger と apply attempt artifact。
- `hermes_self_improvement/approvals.py`: approval artifact generation / validation / report / `apply-approved` preview and guarded apply helpers。plan / item hash / expiry に束縛された承認メタデータを作り、後続 apply のために fail-closed 検証する。実 mutation は explicit confirmation と expected approval/target hashes が揃う場合だけ。
- `hermes_self_improvement/cli.py`: CLI parser、report rendering、ledger/approval/retention report integration、pipeline orchestration。
- `bin/hermes-self-improve`: standalone wrapper CLI。
- `evals/`: GEPA offline scorer の rubric / regression cases。
- `skills/operations/SKILL.md`: この bundled operational skill。

Runtime artifact は既定で `${HERMES_HOME:-~/.hermes}/reports/self-improvement/` 配下に保存する。主な subdirectory は `apply-plans/`, `ledgers/`, `apply-attempts/`, `approvals/`。

## 日常コマンド

Repository root から実行する。

```bash
bin/hermes-self-improve status
bin/hermes-self-improve analyze --since-hours 24
bin/hermes-self-improve report --since-hours 24 --scorer llm
bin/hermes-self-improve run --since-hours 24 --json --scorer compare
bin/hermes-self-improve gepa-eval --json
bin/hermes-self-improve generate-apply-plan --mode dry_run_plan --since-hours 24 --json --scorer compare
bin/hermes-self-improve ledger-report --status applied --json
bin/hermes-self-improve approval-report --status all --json
bin/hermes-self-improve retention-report --mode report_only --json
bin/hermes-self-improve retention-prune --mode apply_approved --json
bin/hermes-self-improve approve <plan-id> <item-id> --mode apply_approved --json
bin/hermes-self-improve apply-approved <approval-id> --mode apply_approved --json
bin/hermes-self-improve rollback-low-risk <ledger-id> --mode apply_low_risk --json
```

Top-level `hermes self-improvement ...` は Hermes version / plugin discovery 状態により露出しないことがある。運用では wrapper CLI を優先し、CLI discovery の挙動を変える作業では plugin manager と user-facing CLI の両方を確認する。

## 変更時の進め方

1. `README.md`, `AGENTS.md`, 関連 reference を読む。auto-apply / apply-policy / roadmap を続ける作業では、必ず repo-tracked plan（例: `.hermes/plans/*self-improvement-auto-apply-policy.md`）も読んでから、今回の変更が docs / runtime / scorer / apply-policy のどこに属するか切り分ける。
2. 新しい policy / apply / scorer 挙動は TDD で fail-closed を先に固定してから実装する。
3. Hook path を触る場合は、redaction・retention・partial event filtering が壊れないか確認する。
4. Scorer path を触る場合は、advisory-only と `auto_apply: false` を崩さない。
5. Apply-plan / ledger path を触る場合は、target hash、rollback preview、explicit target resolution、scorer disagreement gate を確認する。stale path / command は canonical replacement が README/config/実ファイル/active memory/observed success などで独立確認できる場合だけ mutation plan を許可する。
6. 実 mutation slice を追加するときは preview-first を崩さない。low-risk apply は explicit confirmation と expected item hash、approved apply は approval hash + target hash + rollback preview/post-write validation、retention prune は expected artifact list hash、whole-file replacement は full before snapshot rollback を必須にする。`skill_create` / `skill_delete` / `skill_rename` / `skill_merge` / `memory_delete` のような lifecycle / destructive mutation は approval-gated path だけで扱う。create は missing target + rollback delete、delete は existing target + before snapshot restore、rename は source exists + destination missing + rollback rename back、merge は destination replacement + source delete + multi-target rollback data、memory delete は configured `memory_roots` 内 target + before snapshot restore を必須にする。新しい destructive / broad mutation は low-risk に混ぜず、approval-gated path から始める。
7. `__init__.py` / registration / bundled skill discovery を触ったら、unit test だけでなく plugin manager loading も確認する。
8. Tool handler を触る場合は、wrapper CLI に shell out せず、CLI と同じ core function と `validate_mode_action(...)` / `_required_capability_for_command(...)` を通す。
9. Config / policy を触る場合は、defaults < `config.json` < `config.local.json` < `HERMES_SELF_IMPROVE_CONFIG` < `--config` の precedence と、`allow_policy_expansion` なしでは権限拡張できないことを確認する。

## 検証 checklist

通常変更後:

```bash
PY=${PYTHON:-python3}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
bin/hermes-self-improve status
```

Scorer / GEPA / eval asset 変更後:

```bash
bin/hermes-self-improve gepa-eval --json
$PY -m pytest tests/test_gepa_eval_assets.py tests/test_gepa_eval_cli.py tests/test_gepa_offline_scorer.py -q
```

Registration / discovery 変更後:

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

Expected: enabled true, error null, hooks > 0。

## 詳細 reference

必要になった部分だけ読む。

- `references/architecture.md`: hook、telemetry、module layout、scorer / GEPA の仕組み。
- `references/safety-and-apply.md`: execution mode、apply-plan、ledger、auto-apply 境界。
- `references/operations.md`: scheduled maintenance、memory/custom-skill review、plugin discovery、pitfalls。

## Pitfalls

- Tool result classification は structured success/error field を優先する。raw text に `timeout`, `not found`, `permission denied` が含まれるだけで failure cluster にしない。
- Findings は `(tool_name, error_kind)` で cluster 化し、同じ remediation は proposal 側で集約する。
- `target_path` / `path` / `file_path` / `skill_path` がある場合は直接 hint を優先し、自然言語 title から target を推測しない。
- `target_skill` / `skill_name` / `skill` は configured `custom_skill_roots` 配下だけに解決し、absolute path・`..`・root escape を拒否する。
- Plugin-bundled skills は read-only として扱われ、現在実行中の agent session にはすぐ現れない場合がある。discovery reload / new session / gateway restart の必要性を疑う。
- `importlib.util.module_from_spec` で unit test する場合は、`exec_module` 前に `sys.modules[spec.name] = module` を入れる。`@dataclass` 処理が失敗するのを避けるため。
