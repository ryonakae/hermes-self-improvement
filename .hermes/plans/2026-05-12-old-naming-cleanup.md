# 旧命名 (editor / conversation_memory / run_editor) の最終クリーンアップ

## 背景

PR1 (`refactor/llm-site-role-naming-pr1`) と PR2 (`refactor/memory-agent-pr2`) で
LLM site と主要ファイル / 関数 / クラス名は新命名 (memory_extractor /
target_resolver / improvement_planner / skill_agent / memory_agent /
prompt_optimizer) に揃った。ただし内部の decision 値、event kind、
artifact key、コメント、prompt、docs などに旧名称 (`editor`, `run_editor`,
`conversation_memory`, `planner-editor` 等) が広範に残っている。

pre-release で artifact 互換は不要なため、これらを一気に新命名へ揃える。

`/dig` セッションでの決定事項に従って実施する。

## ゴール

- 旧命名 (`editor`, `run_editor`, `conversation_memory`, `planner_editor`,
  `editor_instructions`, `selected_for_editor`, `native_skill_tool_editor` 等)
  が plugin 内 (.py / .md / .yaml / .json) に残らない状態にする
- decision enum を `mutate_skill / archive_skill / create_skill /
  mutate_memory / calibrate_evaluator / skip / defer` の 7 値に整理する
- README / AGENTS narrative も新命名で書き直し、`run_editor などは残してよい`
  といった互換注記を削除する
- pytest tests -q が 623 passed (pre-existing yaml 9 件除く) を維持する

## 非ゴール

- 機能変更、振る舞い変更は含めない (純粋なリネーム + narrative 書き直し)
- target repo の commit は作らない (plugin 内のみ)
- prompt overlay artifact の再生成は不要 (pre-release で seed のみが正本)

## スコープ (決定事項)

### 1. decision enum 全面刷新

| 旧 | 新 |
|---|---|
| `run_editor` | `mutate_skill` |
| `memory_candidate` | `mutate_memory` |
| `evaluator_candidate` | `calibrate_evaluator` |
| `patch_skill` (decision 値) | 廃止 → `decision: "mutate_skill", maintenance_action: "patch"` |
| `merge_skills` (decision 値) | 廃止 → `decision: "mutate_skill", maintenance_action: "merge"` |

最終 DECISIONS set: `mutate_skill / archive_skill / create_skill /
mutate_memory / calibrate_evaluator / skip / defer` (7 値)。

影響箇所:
- `autonomous_loop.py` DECISIONS, ACTIONS
- `episodes.py` decision normalization (`run_editor_preview` 系)
- `improvement_planner.py` 正規化ロジック (L550-562 の折りたたみは
  `maintenance_action` への代入に集約)
- `prompts.py` PLANNER_SYSTEM_PROMPT / PLANNER_BASE_SECTIONS の許容 vocab
- `runtime_eval_cases.py` case_type, expected.decision
- `outcome_scoring.py`, `credit_assignment.py` の decision 参照
- `tool_handlers.py` summary 表示

### 2. event kind / source 改名

| 旧 | 新 |
|---|---|
| kind `conversation_memory_gap_candidate` | `memory_gap_candidate` |
| source `conversation_memory` | `memory_extractor` |

影響箇所:
- `memory_extractor.py` candidate 生成
- `runner_steps.py` MEMORY_AGENT_DISPATCH_KINDS
- `target_resolver.py` フィルタ
- `runtime_eval_cases.py` case_type / summary フィールド

### 3. case_family / dir 改名

| 旧 | 新 |
|---|---|
| `case_family: "planner_editor"` | `"skill_agent"` |
| dir `runtime_eval_cases/planner-editor/` | `runtime_eval_cases/skill-agent/` |

影響箇所:
- `runtime_eval_cases.py` L57
- `calibration.py` L299 dir path

### 4. backend label

| 旧 | 新 |
|---|---|
| `native_skill_tool_editor` | `native_skill_tool` (memory 側 `native_memory_tool` と対称) |

影響箇所:
- `config.py` default
- `skill_agent_backend.py` 判定箇所 3 件

### 5. 関数 / 変数 / 定数の機械的 rename

| 旧 | 新 |
|---|---|
| `render_editor_instructions` | `render_skill_agent_instructions` |
| `EDITOR_BASE_SECTIONS` | `SKILL_AGENT_BASE_SECTIONS` |
| `selected_for_editor` | `selected_for_skill_agent` |
| `editor_no_op_despite_strong_evidence` | `skill_agent_no_op_despite_strong_evidence` |
| `editor_instructions` (planner → skill_agent 指示 key) | `skill_agent_instructions` |
| `editor_task_count` | `skill_agent_task_count` |
| `editor_target_mismatch_skip` | `skill_agent_target_mismatch_skip` |
| `editor_instructions_full` (forbidden field) | `skill_agent_instructions_full` |
| `build_conversation_memory_windows` | `build_memory_extractor_windows` |
| `make_conversation_memory_candidate` | `make_memory_extractor_candidate` |
| `tests/test_conversation_memory_candidates.py` | `tests/test_memory_extractor.py` |

### 6. prompt / docstring / コメント / narrative

- `prompts.py` PLANNER_SYSTEM_PROMPT (L19, L26) の許容 decision vocab を新 enum に
- `prompts.py` EDITOR_BASE_SECTIONS の説明文 ("You are the Hermes
  self-improvement skill editor.") を SKILL_AGENT_BASE_SECTIONS の本文として書き直し
- `llm_utils.py:5` docstring の旧 site 列挙を新 site 名に
- `target_hints.py:136` コメント (`planner/editor still decide`) を新表現に
- `markdown_artifacts.py:243` セクション `"## Planner/editor failures"` を新表現に
- `README.md` L17/28/32 narrative を新命名で書き直し
- `README.md` L51 の `run_editor などの既存名がアーティファクトに残る` 互換注記を削除
- `AGENTS.md` L68 の `run_editor などは残してよい` 互換注記を削除

### 7. テスト fixture

- `tests/` 内で `run_editor` / `editor_instructions` / `selected_for_editor` /
  `editor_no_op_*` / `editor_task_count` / `conversation_memory_gap_candidate`
  などを assert している全箇所を新命名に置換
- ファイル名 `tests/test_conversation_memory_candidates.py` を
  `tests/test_memory_extractor.py` にリネーム
- 旧命名 transition テストは追加しない

## 進め方

AGENTS.md の TDD 方針に従う。

1. **テスト先行**: decision enum と event kind の最小ケースを新命名で
   失敗するように書き換える (1 PR の最初のコミット)。pytest 落ちを確認。
2. **enum / kind 改名本体**: autonomous_loop / episodes / planner /
   prompts / runner_steps / runtime_eval_cases / outcome_scoring /
   credit_assignment / tool_handlers / target_resolver / calibration /
   config / skill_agent_backend を更新。テスト緑復活を確認。
3. **関数 / 定数 / 変数 rename**: 機械的に置換。tests も同時更新。
4. **prompt / docstring / コメント**: 残った旧名称を一掃。
5. **README / AGENTS narrative 書き直し**: 互換注記削除を含む。
6. **検証**:
   - `python3 -m py_compile __init__.py hermes_self_improvement/*.py`
   - `python3 -m pytest tests -q` (623 passed 維持、yaml 9 件 pre-existing)
   - `hermes self-improvement status` (起動できる)
   - `grep -rn '\beditor\b\|run_editor\|conversation_memory\|planner_editor\|planner-editor' hermes_self_improvement *.md` で
     旧命名残骸 0 件を確認 (テストフィクスチャは除外)
7. **commit 分割**: 上記 1-5 をそれぞれ別 commit、検証は最後の commit に
   含める。1 PR で main 向けに作る。

## ブランチ

`refactor/cleanup-old-naming` (このブランチ)。main から切る。
PR1 / PR2 は既に main にマージ済み。

## 検証コマンド (再掲)

```bash
python3 -m py_compile __init__.py hermes_self_improvement/*.py
python3 -m pytest tests -q
hermes self-improvement status
grep -rn '\beditor\b\|run_editor\|conversation_memory\|planner_editor\|planner-editor\|native_skill_tool_editor\|editor_instructions\|editor_no_op\|selected_for_editor\|editor_task_count' hermes_self_improvement *.md
git diff --check
```

## 想定リスク

- decision enum 改名は LLM プロンプト含め広範囲だが、機械的置換のみで
  振る舞いは変えない。テストで全箇所が同時に検知できる
- `maintenance_action` への集約で planner 内部の正規化フロー
  (`improvement_planner.py:550-562`) が単純化する。`patch_skill` /
  `merge_skills` を LLM が直接返した場合のハンドリングは
  `decision: "mutate_skill", maintenance_action: <name>` に変換するだけで
  済む。LLM プロンプトも新 enum + maintenance_action サブフィールドの
  説明に書き直す
- 既存 runtime artifact (events.jsonl, runs/, episodes) に旧命名が
  残っているが、pre-release で再生成可能。互換層は入れない
- prompt overlay seed (`defaults/prompt-overlays/*.md`) 内の旧概念言及は
  併せて書き直す (本文中で「editor」「run_editor」が出ていれば置換)
