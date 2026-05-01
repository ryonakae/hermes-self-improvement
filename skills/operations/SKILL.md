---
name: operations
description: Hermes self-improvement plugin（`hermes-self-improvement`）の設計・実装・検証・運用に使う bundled operational skill。runtime hook、telemetry、evidence、runner、scorer/evaluator calibration、安全な skill/memory 改善を扱うときに読む。
---

# hermes-self-improvement operations

Hermes の skill / memory / scorer / evaluator を改善するための user plugin を扱う operational index。詳細な設計や roadmap は repo-tracked docs / `.hermes/plans/` に置き、この skill は毎回必要な判断だけを短く保持する。

## まず守ること

- Hermes 本体や upstream-managed code を直接編集しない。plugin 内で解決する。
- Runtime hook は観測専用。hook 内で LLM、GEPA optimizer、skill patch、memory edit、重い集計を実行しない。
- Primary CLI / tool surface は `improve`, `calibrate`, `report`, `status` の4つ。
- `improve` と `calibrate` は default mutation-capable。preview-only は `--dry-run`。
- `plan`, `apply`, `rollback`, `outcome` / `record_outcome`, `--execute`, item/hash 指定 flag は primary surface に戻さない。
- 改善対象は `skill`, `memory`, `scorer`, `evaluator` だけ。runtime config、prompt policy、tool policy、任意 docs/config、Hermes core へ広げない。
- Curator telemetry（skill usage / lifecycle / pinned / archive state）は Curator を source of truth にし、plugin hooks で重複収集しない。
- Plugin hooks は Curator が持たない情報だけを集める: tool failure context、memory operation/failure、user correction/session outcome、subagent outcome、LLM/API failure metadata。
- `improve` は Curator/Hermes telemetry を skill candidate source-of-truth として使う。built-in Curator が disabled/paused の前提で、Curator と同じ automatic lifecycle transition を最初に実行/preview してから telemetry を読む。
- Skill mutation は local mutable active/stale agent-created skills のみを対象にし、`skill_manage` など公式 skill tools だけで実行する。pinned / archived / bundled / hub-installed / plugin-bundled / external / ambiguous provenance は除外し、direct filesystem fallback は使わない。
- Archived skills は通常の candidate / duplicate-prevention / restore candidate として使わない。Curator behavior に合わせる。
- Memory mutation は memory tool / provider-native memory tool だけで実行する。evidence-triggered related-memory recall/search context は使うが、built-in memory files、provider DB、provider internals を直接編集しない。full memory lifecycle / sweep はしない。
- Rollback は primary feature ではない。失敗や誤変更は future evidence として次の improvement run で correction する。Curator-style archive restore は別扱い。
- Scorer/evaluator self-improvement は prompt / rubric / runtime-private eval cases が対象。Python implementation code は自己変更しない。
- DSPy/GEPA は hook / plugin discovery path では lazy import を維持し、Hermes runtime 全体の必須依存にしない。
- LLM / GEPA scoring は advisory。無人変更の許可として扱わない。
- 変更前に `git status --short` と対象 diff を確認し、無関係な変更を巻き戻さない。

## 主要パス

- `plugin.yaml`: plugin manifest / exposed tools
- `__init__.py`: root thin plugin entrypoint
- `hermes_self_improvement/schemas.py`: plugin tool schemas
- `hermes_self_improvement/tool_handlers.py`: CLI parity tool handlers。wrapper CLI に shell out せず core function を使う
- `hermes_self_improvement/cli.py`: CLI parser、report rendering、runner orchestration
- `hermes_self_improvement/observer.py`: hook observer、redaction、JSONL telemetry
- `hermes_self_improvement/analysis.py`: event aggregation / evidence extraction
- `hermes_self_improvement/calibration.py`: calibration evidence、regression-gated active evaluator/scorer promotion
- `hermes_self_improvement/mutation_policy.py`: provider-aware memory mutation policy / context builders
- `hermes_self_improvement/mutation_worker.py`: tool-mediated mutation executor
- `evals/proposal/`: repo-tracked public scorer regression seed。user-specific runtime eval cases はここに混ぜない
- `skills/operations/SKILL.md`: この bundled operational skill

Runtime artifact は `${HERMES_HOME:-~/.hermes}/self-improvement/` 配下。主な subdir は `state/`, `daily/`, `runs/`, `gepa/`, `cache/`。

## 日常コマンド

```bash
bin/hermes-self-improve status
bin/hermes-self-improve report --since-hours 24 --json
bin/hermes-self-improve improve
bin/hermes-self-improve improve --dry-run
bin/hermes-self-improve calibrate
bin/hermes-self-improve calibrate --dry-run
```

Primary plugin tools:

```text
self_improvement_status
self_improvement_report
self_improvement_improve
self_improvement_calibrate
```

## 変更時の進め方

1. `README.md`, `AGENTS.md`, 関連 reference、該当 repo-tracked plan を読む。
2. 新しい runner / scorer / mutation 挙動は TDD で fail-closed を先に固定してから実装する。
3. Hook path を触る場合は、redaction・retention・partial event filtering が壊れないか確認する。
4. Scorer/evaluator path を触る場合は、advisory-only と runtime-private eval cases を崩さない。
5. Tool handler / schema を触る場合は、`plugin.yaml`, `schemas.py`, `tool_handlers.py`, registration、`tests/test_plugin_tools.py` を同時に更新する。
6. `__init__.py` / registration / bundled skill discovery を触ったら、unit test だけでなく plugin manager loading も確認する。
7. 実 mutation step を追加するときは、skill は official skill tools、memory は memory/provider tools だけに閉じる。

## 検証 checklist

通常変更後:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
bin/hermes-self-improve status
```

Registration / tool surface 変更後:

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

Expected: enabled true, error null, tools 4。

## Pitfalls

- root 直下に `tools.py` や `tools/` package を置かない。Hermes core `tools.registry` を shadow する。
- Plugin-bundled skills は repo file として編集する。`skill_manage` で plugin-bundled skill を編集しない。
- `importlib.util.module_from_spec` で unit test する場合は、`exec_module` 前に `sys.modules[spec.name] = module` を入れる。
- DSPy/GEPA scorer tests は基本 fake dependency で書く。runtime hook / normal import が `dspy` を eager import しないことを守る。
