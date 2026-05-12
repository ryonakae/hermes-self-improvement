# LLM 呼び出し点の役割境界・命名一貫性リファクタ

## Context

`hermes-self-improvement` plugin には現在 7 個の LLM 呼び出し点 (`site`) が存在し、責務粒度・命名・対象別の対称性に一貫性がない：

- 段階1 (抽出): `memory_gap_extractor` (memory のみ、action 決定まで踏み込んでいる)
- 段階2 (解決): `target_resolver`
- 段階3 (計画): `planner`, `memory_inventory_planner`, `memory_capacity_planner` の3個が併存
- 段階4 (実行): `mutation_agent` (skill 専用、agent loop)
- 段階5 (最適化): `dspy_gepa_bridge` (実装詳細が露出)

skill 側は LLM agent が tool-use loop で実行まで担うのに対し、memory 側は LLM が3段階に分散して計画するだけで、実行は決定論的コード (`mutation_worker.execute_memory_tool_operation`) が担っている。「LLM で賢く自己改善」という思想に対して memory 側だけ薄っぺらく、命名も `*_extractor` / `*_planner` / `*_agent` / `*_bridge` と suffix が混在している。

この非対称性と命名不揃いを解消し、6 個の site にスリム化したうえで、`skill_agent` / `memory_agent` を対称な agent loop として並列化する。memory も skill と同等に「LLM が賢く判断して連続操作する」ループに乗せ、prompt overlay 自己改善対象も 4 role (planner / skill_agent / memory_agent / evaluator) に統一する。

リリース前なので既存 prompt overlay の歴史互換は持たず、リネームと同時に破棄する。

## 整理後の最終形

### LLM site 一覧 (6 個)

| 段階 | site 名 | 対象 | 種別 | 旧名 |
|---|---|---|---|---|
| 1. 抽出 | `memory_extractor` | memory | LLM (会話 window 必須) | `memory_gap_extractor` |
| 1. 抽出 | (なし) | skill | deterministic (`evidence.py`) | — |
| 2. 解決 | `target_resolver` | 汎用 | LLM | (維持) |
| 3. 計画 | `improvement_planner` | 汎用 (skill candidate 入力) | LLM | `planner` |
| 4. 実行 | `skill_agent` | skill | LLM agent loop | `mutation_agent` |
| 4. 実行 | `memory_agent` | memory | LLM agent loop | (新規) |
| 5. 最適化 | `prompt_optimizer` | 4 role overlay | LLM (GEPA 内部) | `dspy_gepa_bridge` |

廃止: `memory_inventory_planner` / `memory_capacity_planner` → `memory_agent` 内 loop に吸収。

### 命名規則

- 段階別 suffix で統一: `*_extractor` / `*_resolver` / `*_planner` / `*_agent` / `*_optimizer`
- 実装詳細 (dspy / gepa / mutation / editor) は site 名・関数名・ファイル名から外す
- prompt role 名 = 実装名で完全一致 (`editor` → `skill_agent`, `planner` → `improvement_planner`, `memory_agent` 新規追加, `evaluator` 維持)
- 「mutation」は下位実装層 (`mutation_worker.py`, `mutation_policy.py`) の名前として保持

### 責務境界

- **段階1 `memory_extractor`**: candidate 生成のみ。`action` 決定 (add/replace/skip/defer/block) は剥がし、下流 (resolver/planner/agent) に委ねる。出力スキーマは `{candidate_id, target, candidate_fact, old_text, confidence, relation_to_existing, reason}` (action 削除)。
- **段階2 `target_resolver`**: 維持。unmatched evidence の enrichment 担当。
- **段階3 `improvement_planner`**: ranking + skill/memory routing decision のみ。memory operation 詳細は出さない。
- **段階4 `skill_agent` / `memory_agent`**: 公式 Hermes tool surface を使った agent loop。
- **段階5 `prompt_optimizer`**: 4 role (planner / skill_agent / memory_agent / evaluator) の overlay 最適化。

### memory_agent の tool セット

- `memory_tool` (Hermes 公式, action: `add`/`replace`/`remove`, target: `memory`/`user`) — `/Users/ryo.nakae/.hermes/hermes-agent/tools/memory_tool.py:465`
- `submit_mutation_result` (plugin)
- list/view 代替は initial prompt 注入 (現状の `current_entries` digest を流用)
- capacity error は agent loop 内で `memory_tool` の戻り値を観測し、`remove` で空けてから再 `add` を実行
- `move_user_to_memory` 等は agent が `remove` + `add` の 2-shot で実現 (公式 API に move なし)
- cross-domain routing は `submit_mutation_result` に `decision: "convert_to_skill_proposal"` を含めて報告のみ。skill 化は次サイクルで `improvement_planner` が判断

## 実装計画

### PR 1: リネームのみ (機能不変)

site 名・role 名・ファイル名・関数名・class 名を一括リネーム。`grep -rn` + sed 中心。テスト調整。

**LLM site リテラル**
- `hermes_self_improvement/mutation_backend.py:648, 655, 670, 684`: `"mutation_agent"` → `"skill_agent"`
- `hermes_self_improvement/planner.py:710, 723`: `"planner"` → `"improvement_planner"`
- `hermes_self_improvement/conversation_memory.py:302, 315`: `"memory_gap_extractor"` → `"memory_extractor"`
- `hermes_self_improvement/dspy_program.py:97, 117`: `"dspy_gepa_bridge"` → `"prompt_optimizer"`
- `hermes_self_improvement/target_resolver.py:277, 290`: 維持
- (`memory_inventory_planner` / `memory_capacity_planner` は PR2 で廃止するため PR1 では触らない)

**prompt role 文字列**
- `hermes_self_improvement/prompts.py:140-159`: `"editor"` 分岐 → `"skill_agent"`、`"planner"` 分岐 → `"improvement_planner"`、`"memory_agent"` 分岐を新設 (PR1 では `skill_agent` と同じ base_prompt_spec を流用して plumbing だけ通し、本格的な prompt は PR2 で書く)
- `hermes_self_improvement/prompt_overlays.py:11-12`: `ALLOWED_PROMPT_ROLES` を `{"improvement_planner", "skill_agent", "memory_agent", "evaluator"}` に
- `hermes_self_improvement/prompt_candidate_optimizer.py:32-34`: overlay mapping を新 role 名に
- `hermes_self_improvement/calibration.py:153, 156, 293, 325`: overlay targets を新 role 名 + `memory_agent` 追加
- `hermes_self_improvement/episodes.py:69, 109-113, 372-382`: role iteration を新 role 名に
- `hermes_self_improvement/runtime_eval_cases.py:155-157, 173-197, 263, 347-349`: overlay case を新 role 名に
- `hermes_self_improvement/setup_runtime.py:179`: role loop を新 role 名に
- `hermes_self_improvement/autonomous_evaluator.py:13`: `OVERLAY_TARGETS` を新 role 名に
- `hermes_self_improvement/prompt_gepa_adapter.py:157-159, 305-307`: `planner_overlay`/`editor_overlay`/`evaluator_overlay` → `improvement_planner_overlay`/`skill_agent_overlay`/`memory_agent_overlay`/`evaluator_overlay`
- `hermes_self_improvement/planner.py:454, 462, 701`: `model_role="planner"` → `"improvement_planner"`、`role="planner"` → `"improvement_planner"`
- `hermes_self_improvement/runner_steps.py:773`: `role="editor"` → `"skill_agent"`

**ファイル / 関数 / class 名**
- `hermes_self_improvement/conversation_memory.py` → `hermes_self_improvement/memory_extractor.py`
- `hermes_self_improvement/planner.py` → `hermes_self_improvement/improvement_planner.py`
- `hermes_self_improvement/mutation_backend.py` → `hermes_self_improvement/skill_agent_backend.py`
- `hermes_self_improvement/mutation_agent.py` → `hermes_self_improvement/skill_agent.py`
- 関数: `run_memory_gap_extractor` → `run_memory_extractor`、`build_memory_gap_digest` → `build_memory_extractor_digest`、`build_memory_gap_messages` → `build_memory_extractor_messages`、`normalize_memory_gap_payload` → `normalize_memory_extractor_payload`
- 関数: `run_skill_planner` → `run_improvement_planner`、`build_skill_planner_digest` → `build_improvement_planner_digest`、`build_planner_quality_report` → `build_improvement_planner_quality_report`
- 関数: `run_skill_agent_task` (mutation_agent.py:234) — 既に `skill_agent` 名で適切、内部移動のみ
- class: `MutationAgentRunner` (mutation_agent.py:35) → `SkillAgentRunner`、`MutationAgentError` → `SkillAgentError`
- class: `NativeSkillToolEditorBackend` (mutation_backend.py:645) → `NativeSkillAgentBackend`

**`mutation_worker.py` / `mutation_policy.py` は据え置き** (下位実装層の語彙として残す)

**`defaults/prompt-overlays/`**
- `editor.md` → `skill_agent.md`
- `planner.md` → `improvement_planner.md`
- `evaluator.md` 維持
- `memory_agent.md` 新規追加 (PR1 では `skill_agent.md` のテンプレートをコピーし、PR2 で memory 向けに書き直す)

**変更が波及する箇所 (import / 呼び出し / monkeypatch)**
- `hermes_self_improvement/cli.py:20, 32, 105, 106, 107`
- `hermes_self_improvement/runner_steps.py:9, 15, 19, 791, 799, 807, 846` (および memory planner 周辺は PR2 まで保持)
- `tests/test_mutation_agent.py`, `tests/test_mutation_backend.py`, `tests/test_skill_planner.py`, `tests/test_conversation_memory_candidates.py`, `tests/test_cli_surface.py`, `tests/test_llm_telemetry.py`, `tests/test_prompt_cache.py`, `tests/test_report_improve_connection.py` の import / fixture 名
- `__init__.py` の re-export

**既存 overlay の破棄 (Q13 B)**
- リネーム完了後、`${HERMES_HOME}/self-improvement/evaluator/active-prompts.json` と `evaluator/prompt-candidates/`, `evaluator/prompt-candidate-sets/` 配下の既存ファイルは新 role 名と hash が一致しないので、リセット手順をドキュメント化:
  - `bin/hermes-self-improve setup --check` 後に `evaluator/active-prompts.json` を削除し再生成
  - PR1 の README/CLAUDE.md に「リネーム後は既存 overlay リセット必須」を追記

### PR 2: memory_agent 化一式

#### (a) `memory_extractor` の責務縮小 (Q7)

- `hermes_self_improvement/memory_extractor.py` の `MEMORY_GAP_SYSTEM` (旧 conversation_memory.py:274) を書き換え:
  - 出力スキーマから `action` を削除
  - 出力 = `{candidates: [{candidate_id, target, candidate_fact, old_text, confidence, relation_to_existing, reason}]}`
- `normalize_memory_extractor_payload` (旧 `normalize_memory_gap_payload`, conversation_memory.py:54) の `action` 検証を削除
- 下流 (`target_resolver`, `improvement_planner`) で `action` フィールドを参照している箇所を洗い出して撤去
- `make_conversation_memory_gap_candidate` (conversation_memory.py:207) の signature から `action` を外す

#### (b) `memory_agent` 新設 (Q4, Q14)

新規ファイル: `hermes_self_improvement/memory_agent.py`

- `mutation_backend.py` の `NativeSkillAgentBackend` (旧 `NativeSkillToolEditorBackend`) を雛形に `NativeMemoryAgentBackend` を作成
- tool schemas: `memory_tool` (Hermes 公式 API, action: `add`/`replace`/`remove`, target: `memory`/`user`) と `submit_mutation_result` のみ
- agent loop:
  1. initial prompt に `current_entries` (memory/user 両 store) を注入
  2. agent が `memory_tool` を呼ぶ → 戻り値を観測
  3. capacity error (`memory_capacity_exceeded`) 検出時は continue (agent が自分で `remove` してから再 `add`)
  4. `submit_mutation_result` で終了
- `submit_mutation_result` の payload に `decision: "convert_to_skill_proposal"` フィールドを追加 (cross-domain routing 報告)
- `MemoryAgentRunner` class、`run_memory_agent_task` 関数を `hermes_self_improvement/memory_agent.py` に
- `mutation_worker.execute_memory_tool_operation` (mutation_worker.py:207) は依然として agent backend の最下層で呼ばれる (post-validation, safety, store 注入を担保)

#### (c) `memory_inventory_planner` / `memory_capacity_planner` の廃止 (Q6)

- `hermes_self_improvement/runner_steps.py:287-342` (`_call_memory_capacity_planner_llm`) と `runner_steps.py:345-377` (`_capacity_compaction_operations`) を削除
- `hermes_self_improvement/runner_steps.py:646-720` (`_call_memory_inventory_planner_llm`, `_memory_inventory_operations`) を削除
- `_execute_built_in_memory_context` (runner_steps.py:380) を簡素化:
  - capacity error 検出後の compaction 計画 → 廃止
  - 代わりに memory candidate を `run_memory_agent_task` 経由で実行する route に変更
- memory candidate の dispatch ロジックを `runner_steps.py` 内に新設:
  - `improvement_planner` の output で `decision: "memory_candidate"` のものを memory_agent に投げる
  - skill candidate と並列に memory_agent task を実行
- `_memory_non_operation_route` (runner_steps.py:574) の routing で `kind == "memory_inventory_candidate"` の `suggested_route: "memory_planner"` を `"memory_agent"` に書き換え

#### (d) `prompt_optimizer` の 4 role 拡張 (Q11)

- `hermes_self_improvement/prompt_gepa_adapter.py:157-159, 305-307` の 3 role 設定を 4 role に拡張:
  - `improvement_planner_overlay`, `skill_agent_overlay`, `memory_agent_overlay`, `evaluator_overlay`
- `hermes_self_improvement/prompts.py` で `memory_agent` role の `base_prompt_spec` を新規実装 (PR1 では skill_agent 流用のままなので、ここで memory 向けに書き直す)
- `defaults/prompt-overlays/memory_agent.md` を memory 向けに書き直す (PR1 で skill_agent.md コピーから差し替え)
- `hermes_self_improvement/calibration.py:153` の `("planner", "editor")` (PR1 後は `("improvement_planner", "skill_agent")`) を `("improvement_planner", "skill_agent", "memory_agent")` に拡張
- `hermes_self_improvement/autonomous_evaluator.py:13` の `OVERLAY_TARGETS` に `"memory_agent"` を追加

## 重要パス

- `hermes_self_improvement/cli.py` — CLI parser、runner orchestration
- `hermes_self_improvement/runner_steps.py` — skill_agent / memory_agent dispatch ロジック (PR2 で大幅変更)
- `hermes_self_improvement/prompts.py` — base_prompt_spec の role 分岐
- `hermes_self_improvement/prompt_overlays.py` — `ALLOWED_PROMPT_ROLES`
- `hermes_self_improvement/calibration.py` — overlay calibration の role 集計
- `hermes_self_improvement/prompt_gepa_adapter.py` — GEPA 最適化対象の role 一覧
- `hermes_self_improvement/mutation_worker.py` — `execute_memory_tool_operation` (下位層、維持)
- `/Users/ryo.nakae/.hermes/hermes-agent/tools/memory_tool.py` — 公式 memory_tool API (memory_agent が呼ぶ)
- `defaults/prompt-overlays/*.md` — bootstrap seed
- `CLAUDE.md`, `README.md` — リネーム後の安全境界記述・runner surface

## 検証

### PR 1 (リネーム)

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m py_compile __init__.py hermes_self_improvement/*.py
$PY -m pytest tests -q
bin/hermes-self-improve setup --check
bin/hermes-self-improve status
bin/hermes-self-improve improve --dry-run
bin/hermes-self-improve calibrate --dry-run
git diff --check
```

Tool schema 確認:
```bash
$PY - <<'PY'
from hermes_cli.plugins import discover_plugins, get_plugin_manager
import json
discover_plugins(force=True)
info = [p for p in get_plugin_manager().list_plugins() if p['name'] == 'hermes-self-improvement']
print(json.dumps(info, ensure_ascii=False, indent=2))
PY
```

期待: plugin enabled / error null / tools 4。

旧 overlay リセット:
```bash
rm -f ${HERMES_HOME:-~/.hermes}/self-improvement/evaluator/active-prompts.json
rm -rf ${HERMES_HOME:-~/.hermes}/self-improvement/evaluator/prompt-candidates/*
rm -rf ${HERMES_HOME:-~/.hermes}/self-improvement/evaluator/prompt-candidate-sets/*
bin/hermes-self-improve setup --check
```

### PR 2 (memory_agent 化)

```bash
$PY -m pytest tests -q
bin/hermes-self-improve improve --dry-run
bin/hermes-self-improve improve   # memory_agent が実際に走ることを確認
bin/hermes-self-improve report --since-hours 24
```

確認項目:
- `state/events.jsonl` で `site=memory_agent` の `self_improvement_llm_call` event が記録されているか
- `site=memory_inventory_planner` / `site=memory_capacity_planner` の event が出ていないか (廃止確認)
- memory candidate に対して `memory_agent` 経由で `add`/`replace`/`remove` が実行されているか (`mutation_worker.execute_memory_tool_operation` 経由のログで確認)
- capacity error が発生した場合、agent loop 内で `remove` → 再 `add` のシーケンスが記録されているか
- `prompt_optimizer` (`site=prompt_optimizer`) が `improvement_planner` / `skill_agent` / `memory_agent` / `evaluator` の 4 role 全部に対して候補生成しているか (`evaluator/prompt-candidates/` 配下)

新規テスト追加対象:
- `tests/test_memory_agent.py` — memory_agent loop の単体テスト (mock memory_tool で add/replace/remove/capacity recovery を検証)
- `tests/test_runner_steps.py` — memory candidate dispatch の orchestration
- 既存の `tests/test_memory_inventory_planner.py`, `tests/test_memory_capacity_fallback.py` は削除 (廃止される機能のテスト)

## 注意事項

- PR 1 と PR 2 は別 commit / 別 PR に分ける。PR1 が機能不変であることを diff レビューで担保する。
- PR 1 完了時点で旧 overlay は破棄され、4 role 分の overlay 候補生成が空からスタートする (リリース前なので問題なし)。
- PR 2 で memory_agent が安定運用に乗るまで数サイクルの dogfooding が必要。`bin/hermes-self-improve report --since-hours 24` で site 別の挙動を観測。
- `mutation_worker.py` / `mutation_policy.py` は据え置き。下位実装層の「mutation」概念語として保持する (Q16 A)。
- 「mutation」という語は worker / policy / エラーコード (`mutation_agent_unavailable` 等) に残るが、これは下位レイヤーの語彙として正当。skill_agent / memory_agent という中位の対象別命名と階層的に共存する。
- CLAUDE.md の安全境界記述 (memory mutation は memory tool 経由のみ等) は変更なし。memory_agent も `mutation_worker.execute_memory_tool_operation` 経由で公式 tool を呼ぶ。
