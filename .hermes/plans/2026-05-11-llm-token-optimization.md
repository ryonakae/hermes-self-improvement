# LLM トークン消費の最適化

## 目的

プラグインの各 LLM 呼び出しに観測データが過剰に流れ込んでいる現状を、品質を著しく落とさず削減する。anthropic / OpenAI / Codex / DSPy bridge の各経路で prompt cache を効かせ、データ重複と無駄を構造的に減らす。

## 現状認識

### LLM call サイト一覧(計測対象)

| Site | ファイル | overlay 対応 | 構造 | 1 run 内固定 | run 跨ぎ固定 |
|---|---|---|---|---|---|
| `target_resolver` | `target_resolver.py:_call_resolver_llm` | 非対応 | user 1 message | yes | yes |
| `memory_gap_extractor` | `conversation_memory.py:_call_memory_gap_llm` | 非対応 | user 1 message | yes | yes |
| `llm_scorer` | `scoring.py:_call_llm_scorer` | 非対応 | system + user | yes | yes |
| `planner` | `planner.py:_call_planner_llm` | 対応 (`role=planner`) | system + user | yes | overlay 更新で変動 |
| `mutation_agent` (editor) | `mutation_backend.py:NativeSkillToolEditorBackend.run` | 対応 (`role=editor`) | system + user (loop) | yes | overlay 更新で変動 |
| `memory_capacity_planner` | `runner_steps.py:_call_memory_capacity_planner_llm` | 非対応 | system + user | yes | yes |
| `memory_inventory_planner` | `runner_steps.py:_call_memory_inventory_planner_llm` | 非対応 | system + user | yes | yes |
| `dspy_gepa_bridge` | `dspy_program.py:HermesAuxiliaryLM.forward` | n/a | DSPy 任せ | n/a | n/a |

### 既に完了

- **計測パッチ**: `hermes_self_improvement/llm_telemetry.py` の `record_llm_call` を 8 サイト全てに注入済み。`state/events.jsonl` に `self_improvement_llm_call` を追記する。`prompt_chars_total` / `prompt_chars_by_role` / `prompt_hash` / `response_chars` / `iteration` などを記録。`HERMES_SELF_IMPROVEMENT_DISABLE_LLM_TELEMETRY` で無効化可能。
- AGENTS.md / README.md にこの計測経路を追記済み。
- 単体テスト `tests/test_llm_telemetry.py` 10 件 pass、既存 597 テストも pass。

### LLM weekly limit ギリギリの制約

ユーザーは anthropic はほぼ使わず OpenAI / Codex 系を主に使う。一般配布プラグインなので anthropic ユーザーにも効く最適化は入れる。`hermes self-improvement improve` / `calibrate` の実走行は今回は避ける。

### hermes-agent 側の caching 事情(確認済み)

- `agent/auxiliary_client.py:call_llm` は **prompt caching を一切自動適用しない** (`apply_anthropic_cache_control` は main agent でのみ使用)。
- `agent/anthropic_adapter.py:1344-1809` は `cache_control` を pass-through する → messages に乗せれば届く。
- OpenAI Chat Completions は **prefix 一致で自動 cache hit** する(明示指定不要)。
- OpenAI Responses / Codex backend は `prompt_cache_key` を `extra_body` 経由で渡せば cache scope が安定 (`agent/transports/codex.py:104`)。
- `call_llm` の `extra_body` は task config の `effective_extra_body` を引数側で `.update` するので、引数側が勝つ。安全に渡せる。

## 着手範囲

S 級(品質劣化ほぼゼロ)と A 級(許容範囲の品質劣化、効果大)。B 級(`mutation_agent` loop の tool_result 圧縮など、品質劣化リスクが残るもの)は計測値を見てから判断する。

## 実装プラン

### Step 1: S-1 — prompt 構造を `system + user` に分離

#### 目的
OpenAI 自動 cache の hit 範囲を user 先頭固定文(数百 chars)から system 全体(数 KB)に拡張。anthropic cache_control の置き場を作る。

#### 変更ファイル
- `hermes_self_improvement/target_resolver.py`
- `hermes_self_improvement/conversation_memory.py`

#### 変更内容
- `target_resolver.py` に定数 `TARGET_RESOLVER_SYSTEM` を切り出す(既存 `build_target_resolver_prompt` 内の固定 instruction 部分)。
- `build_target_resolver_messages(digest) -> list[dict]` を追加。
- `_call_resolver_llm` を新関数で呼ぶ。
- 既存 `build_target_resolver_prompt` は **保持**(後方互換、`test_target_resolver.py:273` が直接呼ぶ)。
- `conversation_memory.py` も同様に `MEMORY_GAP_SYSTEM` 定数 + `build_memory_gap_messages` を追加して `_call_memory_gap_llm` を切り替え。

#### テスト
- 既存 `test_target_resolver.py::test_target_resolver_prompt_keeps_attachment_only_guidance` (line 273-286) は維持。
- 新規: `build_target_resolver_messages` / `build_memory_gap_messages` が system に固定文、user に digest JSON を返すこと。

#### 削減効果
直接削減はゼロ(構造変更のみ)。Step 2 と組み合わせて効く。

#### リスク
極小。

---

### Step 2: S-2 — cache 戦略ヘルパー追加 + 全 LLM call 経路に適用

#### 目的
- anthropic: system に `cache_control: ephemeral` 注入(5 分 TTL、cross-run hit)。
- OpenAI / Codex: `prompt_cache_key` を `extra_body` 経由で送り cache scope を安定化。
- 完全固定 site と overlay 群を区別。

#### 変更ファイル
- 新規: `hermes_self_improvement/prompt_cache.py`
- `target_resolver.py` / `conversation_memory.py` / `scoring.py` / `planner.py` / `mutation_backend.py` / `runner_steps.py` (2 箇所) / `dspy_program.py`

#### 新規 helper API
```python
# prompt_cache.py
def apply_caching(
    messages: list[dict],
    *,
    site: str,
    overlay_hash: str | None = None,
    extra_key_parts: list[str] | None = None,
) -> tuple[list[dict], dict[str, str]]:
    """
    Returns (cached_messages, extra_body_additions).

    - cached_messages: anthropic cache_control 注入済み messages の deep copy。
      system message の content を [{"type":"text","text":...,"cache_control":{"type":"ephemeral"}}] 形式に変換。
      system message が無い場合は何もしない(messages の deep copy を返す)。
    - extra_body_additions: {"prompt_cache_key": f"self_improvement:{site}:{key_suffix}"}
      key_suffix は overlay_hash があれば含める。base prompt の sha256[:8] も含める。
    """
```

#### cache key 設計
- 完全固定 site: `self_improvement:{site}:{prompt_sha8}` (prompt 改修時に自動 invalidate)
- overlay site: `self_improvement:{site}:{prompt_sha8}:{overlay_hash[:8] or 'none'}`

#### anthropic cache_control 注入
- system message の content を string → block list 形式に変換。
- breakpoint は 1 つ(system 末尾)で十分。
- 非 anthropic provider は cache_control を無視するだけ。

#### call site への注入(例)
```python
messages = build_target_resolver_messages(digest)
messages, cache_extras = apply_caching(messages, site="target_resolver")
response = call_llm(..., messages=messages, extra_body=cache_extras)
```

overlay 群:
```python
overlay = load_active_prompt_overlay(...)
messages, cache_extras = apply_caching(
    messages, site="planner",
    overlay_hash=overlay.get("candidate_hash") if overlay else None,
)
```

#### テスト
新規 `tests/test_prompt_cache.py`:
- system が string → block list に変換される。
- cache_control: ephemeral が system 末尾に付く。
- prompt_cache_key の生成(固定 / overlay つき)。
- overlay_hash 変化で key が変わる。
- 元 messages を破壊しない (deep copy)。
- system 無し messages は cache_extras だけ返す。

#### 削減効果(課金単価ベース)
- anthropic: cache hit 部分の input token 単価 -90%。
- OpenAI 自動 cache: hit 範囲が user 先頭 → system 全体に拡張、cached tokens 増。
- Codex Responses: prompt_cache_key 設定で session 跨ぎ cache 安定化。

#### リスク
- 非 anthropic provider で content が block list 形式になることに注意。OpenAI Chat Completions はマルチモーダル用に block list を受けるので問題なし。要動作テスト確認。
- `extra_body` merge: `call_llm` 内で引数側 `.update` で勝つので安全。

---

### Step 3: S-3 + A-1 — `context_windows` 構造を union event 形式に変更 + center 重複削除

#### 目的
- S-3: 3 つの window で重複する event を 1 つに集約。
- A-1: `representative_failures[i]` と `context_windows[i].center` の重複を解消。

#### 変更ファイル
- `hermes_self_improvement/evidence.py`(中心)
- `hermes_self_improvement/target_resolver.py` (line 174、`context_windows` 参照)
- `hermes_self_improvement/planner.py` (line 227)
- `hermes_self_improvement/conversation_memory.py` (line 233、`context_windows[:5]` 参照)
- `tests/test_evidence_context_windows.py` / `tests/test_unmatched_evidence_candidates.py` / `tests/test_target_resolver.py`

#### 構造変更
現状:
```python
{
  "representative_failures": [_compact_event(events[i]) for i in indices[:5]],
  "context_windows": [
    {"center_index": i, "session_id": ..., "events": [..5 events..]} for i in indices[:3]
  ],
}
```

新形式:
```python
{
  "representative_failures": [_compact_event(events[i]) for i in indices[:5]],
  "context_window": {
    "session_id": ...,
    "centers": [indices[0], indices[1], indices[2]],
    "events": [
      _compact_event(events[i])
      for i in sorted(set(window_event_indices)) if i not in center_set
    ],
  },
}
```

- events から center event を除外(representative_failures に同じ表現で含まれている)。
- 周辺 event の union dedup。
- `build_context_window` 関数のシグネチャは保つ(単体テストが pass)。union 化と center 除外は呼び出し側(`evidence.py:399` 周辺)で行う。

#### テスト
- `test_evidence_context_windows.py` の 3 テストは pass (function signature 保持)。
- `test_unmatched_evidence_candidates.py:36` `assert item["context_windows"]` → `item["context_window"]` に更新、または old field をエイリアスとして残す方針を選ぶ。
- 新規: union dedup と center 除外のロジックテスト。

#### 削減効果
- 同 cluster で近接 indices なら events 重複が 50-66% 減。
- 1 unmatched_improvement_candidate あたり ~2-3 KB → ~1 KB。

#### リスク
- LLM 側の system prompt 内で `context_windows` のような具体 field 名を参照していないか確認。`target_resolver.py:201-213` の TARGET_RESOLVER_SYSTEM は具体 field を参照しないので影響なし。
- `planner.py:227` などの転送経路は同時に更新する。

---

### Step 4: A-3 — `representative_failures[:5]` → `[:2]`

#### 目的
代表 failure の数を絞る。LLM が見るのは実質 1-2 個、`count` で件数は別途伝わる。

#### 変更ファイル
- `hermes_self_improvement/evidence.py:398` (`representative = [...for index in indices[:5]]`)
- 他に `indices[:5]` 系の slice があれば一括検討。

#### テスト
- `test_unmatched_evidence_candidates.py` で `len(item["representative_failures"])` を見ている箇所があれば調整。
- 新規: count = indices 全長、representative_failures = 上位 2 件、の関係を確認。

#### 削減効果
- 1 evidence あたり ~3 event 分削減(60% カット)。
- representative_failures が登場する全 LLM call で効く。

#### リスク
- 「3 件目以降にしか出ない手がかり」を見逃すケース。影響は小さい想定。
- `count` で件数は維持。

---

### Step 5: A-2 — `target_resolver` の `skill_targets` 2-tier 化

#### 目的
登録 skill 全列挙(name + description 180 chars + state + provenance)を、関連度上位の詳細 + 残りは name のみに分離。

#### 変更ファイル
- `hermes_self_improvement/target_resolver.py:184-195` (`build_target_resolution_digest` 内 `skill_targets`)
- TARGET_RESOLVER_SYSTEM 文言に「skill_targets には詳細、skill_targets_other_names には残り skill 名」と説明追加

#### 変更内容
```python
def _skill_relevance_for_digest(skill, evidence_list):
    # 既存 _target_fit_signals のロジックを再利用。
    # evidence のいずれかで positive signal を立てれば候補入り。
    ...

detailed, names_only = [], []
for skill in skill_candidates:
    if not isinstance(skill, dict) or not skill.get("name"):
        continue
    is_mutable = bool(skill.get("mutable", True))
    if not is_mutable:
        continue  # 非 mutable は names_only にも入れない(attach 対象外)
    if _skill_relevance_for_digest(skill, evidence) > 0:
        detailed.append({...full info...})
    else:
        names_only.append({"name": skill["name"]})

return {
    ...,
    "skill_targets": detailed,
    "skill_targets_other_names": names_only,
}
```

#### テスト
- 既存 `test_target_resolver.py` で skill_targets を参照する箇所を確認。
- 新規: relevance positive → detailed、それ以外 → names_only。non-mutable は除外。

#### 削減効果
- 100 skill 環境で skill_targets 部分が 25 KB → ~6 KB(75% 削減)。

#### リスク
- 「fit signal が漏らした skill を LLM だけが拾える」ケース。names_only 側に skill 名は載るので `target` に書く分には到達可能。description が無くても skill 名が説明的なら問題なし。
- non-mutable を完全に外す件: attach 対象外なので情報量ゼロ。

---

### Step 6: A-4 — memory_gap window radius 段階化

#### 目的
`windows[:40]` の件数は維持しつつ、各 window 内の周辺イベント preview を縮める。

#### 変更ファイル
- `hermes_self_improvement/evidence.py` (`build_context_window` に `full_radius` パラメータ追加、または ultra-compact 用関数を別出し)
- `hermes_self_improvement/conversation_memory.py` (`build_conversation_memory_windows` 呼び出し)

#### 変更内容
```python
def _ultra_compact_event(ev):
    keys = ("ts", "tool_name", "status", "error_kind")
    return {k: ev.get(k) for k in keys if ev.get(k) is not None}

def build_context_window(events, *, center_index, radius=3, full_radius=None):
    # full_radius が None なら現状動作。
    # 数値なら center ± full_radius は _compact_event、それ以外は _ultra_compact_event。
    ...
```

呼び出し側で `full_radius=1, radius=3` を指定(memory_gap)。unmatched_evidence (`evidence.py:399`) は radius=2 のまま、`full_radius=1` を渡す。

#### テスト
- `test_evidence_context_windows.py:38` `test_build_context_window_redacts_and_compacts_large_payloads`: center は full、外側は ultra-compact を確認する形に拡張。
- 新規: `full_radius` 境界(0, radius と一致、None)。

#### 削減効果
- memory_gap で windows 部分が ~70% 削減。
- 1 window: 7 event × 1.2 KB → 3 event full + 4 event ultra → ~5 KB(から ~2 KB)。

#### リスク
- 「±2/±3 の preview に手がかり」を見逃すケース。preview を完全に落とすのではなく `tool_name + status + error_kind` は残す。
- memory_gap 抽出用途では「center + ts + tool 名」で大抵足りる想定。

---

## テスト戦略

### 各 Step 完了後
```bash
.venv/bin/python -m py_compile __init__.py hermes_self_improvement/*.py
.venv/bin/python -m pytest tests -q
git diff --check
```

### 最終確認(Step 6 後)
- 全 Step の新規テスト + 既存 597 テスト pass。
- `llm_telemetry` の `prompt_chars_total` 集計が messages 構造変更後も正しく動くこと(`tests/test_llm_telemetry.py` で system + user + block list 形式を網羅)。

### LLM limit 回復後の実測手順
```bash
jq -r 'select(.event=="self_improvement_llm_call")
       | [.site, .prompt_chars_total, .prompt_chars_by_role, .response_chars] | @json' \
  ~/.hermes/self-improvement/state/events.jsonl
```

最適化前後の比較で `prompt_chars_by_role.system` と `prompt_chars_by_role.user` の分布、`prompt_hash` の重複率(cache hit の代理指標)を確認。

## 推定総削減量(1 run、悲観値)

| 項目 | 現状 | 完了後 |
|---|---|---|
| target_resolver | 30–80K tokens | 8–20K |
| memory_gap | 50–80K | 15–25K |
| planner | 15–25K | 10–18K |
| scorer | 5–20K | 5–18K (cache のみ) |
| mutation_agent | 50–150K × N | 同(B-1 後回し) |
| inventory/capacity | 5–10K | 同 |

合計トークン消費 **40-60% 削減**目標。anthropic / OpenAI 自動 cache で input token 課金は更に -30-50%。

## 後回し(B 級、計測値を見て判断)

- **B-1**: `mutation_agent` loop の古い tool_result 圧縮。直近 1 iter は full、それ以前は `{tool, args summary, status, output_hash}` に。LLM が再 call をスキップするリスクがあるので、計測パッチで現状の loop 内 prompt 肥大を実測してから判断。
- **B-2**: planner ↔ scorer の evidence cross-call dedup。evidence registry + id 参照モデル。実装重い、効果は大きいが LLM cooperation 前提。

## 進捗

- [x] 計測パッチ (`llm_telemetry.py` + 8 サイト + 単体テスト)
- [x] Step 1: S-1 prompt 構造分離 (target_resolver / memory_gap_extractor を system + user に分割)
- [x] Step 2: S-2 cache 戦略ヘルパー (`prompt_cache.apply_caching`、8 サイトに注入、anthropic `cache_control` + prompt_cache_key)
- [x] Step 3: S-3 + A-1 context_windows event dedup + center 重複削除 (`dedup_context_windows`)
- [x] Step 4: A-3 representative_failures slice 5→2 (count は維持)
- [x] Step 5: A-2 skill_targets 2-tier (`skill_targets` 詳細 + `skill_targets_other_names` name のみ、non-mutable は除外)
- [x] Step 6: A-4 memory_gap window radius 段階化 (`full_radius` パラメータで center±1 は full、外側は ultra-compact)

最終テスト: 615 passed, 2 skipped。

## 参考: 関連ファイル

- `hermes_self_improvement/llm_telemetry.py` — 計測パッチ(完了)
- `hermes_self_improvement/target_resolver.py` — Step 1, 2, 5
- `hermes_self_improvement/conversation_memory.py` — Step 1, 2, 6
- `hermes_self_improvement/scoring.py` — Step 2
- `hermes_self_improvement/planner.py` — Step 2, 3
- `hermes_self_improvement/mutation_backend.py` — Step 2
- `hermes_self_improvement/runner_steps.py` — Step 2
- `hermes_self_improvement/dspy_program.py` — Step 2
- `hermes_self_improvement/evidence.py` — Step 3, 4, 6
- 新規: `hermes_self_improvement/prompt_cache.py` — Step 2
- 新規テスト: `tests/test_prompt_cache.py` — Step 2

## 関連調査メモ

### hermes-agent 側
- `agent/auxiliary_client.py:3889` `call_llm` シグネチャ
- `agent/anthropic_adapter.py:1344-1809` cache_control pass-through
- `agent/prompt_caching.py:apply_anthropic_cache_control` (main agent のみ使用、auxiliary では使われない)
- `agent/codex_responses_adapter.py:760` prompt_cache_key passthrough
- `agent/transports/codex.py:104` main agent では session_id を prompt_cache_key として渡している

### overlay 経路
- `hermes_self_improvement/prompt_overlays.py:load_active_prompt_overlay`
- 対象 role: `planner` / `editor` / `evaluator` のみ (`runtime_eval_cases.py:155-157`, `prompts.py:139-162`)
- target_resolver / memory_gap_extractor / scorer / capacity / inventory planner は完全固定 prompt
