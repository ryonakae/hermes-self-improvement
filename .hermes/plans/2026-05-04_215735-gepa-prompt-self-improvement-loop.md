# GEPA による overlay prompt 自己改善ループ計画

作成: 2026-05-04 21:57 JST
更新: 2026-05-04 22:00 JST
対象: `/Users/ryo.nakae/.hermes/plugins/hermes-self-improvement`

## ゴール

`hermes-self-improvement` plugin で、Ryo さんの環境固有の観測データを使い、**runtime-private overlay prompt** を DSPy/GEPA で改善する。

閉ループはこれだけ。

```text
1. observe
   skill / memory 改善の実行結果を記録する

2. improve
   現在の overlay prompt で skill / memory を改善する

3. score outcomes
   改善が良かったか悪かったかを prompt hash 付きで記録する

4. calibrate prompt
   観測 outcome から eval cases を作り、DSPy/GEPA で overlay prompt candidate を作る

5. promote if better
   baseline より良い candidate だけ active overlay に昇格する

6. repeat
```

GEPA が改善する対象は **repo-managed base prompt ではない**。

```text
base prompt: plugin 同梱。汎用。基本的に変更しない。
overlay prompt: Ryo さん環境固有。runtime-private。GEPA が改善する対象。
```

## 非ゴール

- Hermes 本体 prompt の変更
- plugin 同梱 base prompt の自動書き換え
- tool policy / safety boundary の変更
- built-in / hub / plugin-bundled / external skill の編集
- archived skill の復元・削除・merge
- classifier / normalizer / legacy fallback 層の追加
- GEPA candidate の無条件 auto-promote

## 最小設計

必要な部品は 4 つだけ。

### 1. Episode 記録

skill / memory 改善を実行したとき、どの prompt で判断したかを記録する。

最低限のフィールド:

```json
{
  "episode_id": "...",
  "created_at": "...",
  "planner_overlay_hash": "...",
  "editor_overlay_hash": "...",
  "evaluator_overlay_hash": "...",
  "target_kind": "skill|memory",
  "decision": "run_editor|skip|defer",
  "mutation": "changed|no_change|failed",
  "outcome": "success|failed|rejected|unknown",
  "evidence_ids": ["..."]
}
```

既存 ledger / outcome store を拡張する。新しい巨大 DB や別 pipeline は作らない。

### 2. Eval case 生成

episode から GEPA 用 eval case を作る。

対象は最初から 3 つを同時に扱う。

```text
planner_overlay:   run_editor / skip / defer の判断
editor_overlay:    実際の skill / memory mutation の狭さ・正確さ
evaluator_overlay: proposal / outcome / risk / confidence の採点
```

同時にやる理由:

- skill / memory 改善の品質は planner / editor / evaluator の組み合わせで決まる
- planner だけ良くしても editor / evaluator が古いままだと実改善の評価が歪む
- GEPA 後の改善効果は 3 overlay のセットで検証しないと分からない

ただし、pipeline は 1 本だけにする。target ごとに別システムを作らない。

case は最小でよい。

```json
{
  "target": "planner_overlay|editor_overlay|evaluator_overlay",
  "input": {
    "proposal": {},
    "findings": [],
    "evidence_ids": [],
    "mutation_task": {},
    "outcome": {}
  },
  "expected": {
    "decision": "run_editor|skip|defer",
    "mutation": "changed|no_change|skip",
    "recommendation": "report_only|human_review|review_low_risk_candidate"
  },
  "source_episode_id": "...",
  "case_hash": "..."
}
```

各 target は必要な expected だけ使う。複雑な分類器は作らない。episode の結果から素直に case 化する。

### 3. GEPA optimizer

`calibrate` が eval cases を渡して、overlay prompt candidate を作る。

1 回の calibration run で、3 target を同じ candidate set として扱う。

```text
candidate_set
  ├─ planner_overlay candidate   changed | unchanged
  ├─ editor_overlay candidate    changed | unchanged
  └─ evaluator_overlay candidate changed | unchanged
```

重要: **3 target を同時に検証するが、3 target すべてを必ず変更するわけではない**。

例えば、planner/editor だけ改善余地があり evaluator は十分なら、candidate set はこうなる。

```text
planner_overlay:   changed
editor_overlay:    changed
evaluator_overlay: unchanged
```

この場合も promote は set 単位で行い、`overlay_generation_id` は更新する。ただし evaluator overlay の content/hash は active と同じまま保持する。

出力は overlay addendum だけ。

```json
{
  "candidate_set_id": "...",
  "target": "planner_overlay|editor_overlay|evaluator_overlay",
  "change_status": "changed|unchanged",
  "source": "gepa",
  "optimizer": "dspy.GEPA",
  "base_prompt_hash": "...",
  "active_overlay_hash": "...",
  "candidate_prompt": {
    "system_addendum": "...",
    "user_addendum": null,
    "replacement": null
  },
  "trainset_hash": "...",
  "valset_hash": "...",
  "candidate_hash": "...",
  "runtime_private": true,
  "promoted": false
}
```

hard rule:

- `replacement` は常に禁止
- addendum は短くする
- safety / tool authority / mutation scope を変える文言は禁止
- `source=rule_fallback` と `source=gepa` を混ぜない

### 4. GEPA eval result + promotion gate

candidate をすぐ使わない。

候補探索と score 比較は、原則として GEPA に任せる。

```text
GEPA input:
  active overlay set
  train cases
  val cases
  metric

GEPA output:
  candidate overlay set
  per-target change_status
  baseline score
  candidate score
  eval stats
```

plugin 側で GEPA と同じ重い shadow eval を再実装しない。
plugin の役割は、GEPA の eval result を受けて **薄い promotion gate** を通すこと。

promote は原則 **set 単位**。

理由:

- planner / editor / evaluator は相互依存する
- 1つだけ promote すると、組み合わせが崩れて outcome の解釈が難しくなる
- GEPA の改善効果を「prompt set の世代」として追跡できる

plugin 側は、GEPA の判断をもう一度審査しない。

#### Acceptance checks

candidate を active にする前に、最低限の受け入れチェックだけ行う。

これは「良し悪しの判定」ではなく、artifact と overlay として壊れていないことの確認。

```text
GEPA result がある
candidate artifact が読める
3 target が同じ candidate_set_id に入っている
各 target の change_status が changed または unchanged
replacement が null
addendum が max chars 以下
active-before hash が記録されていて戻せる
```

`unchanged` target は、active overlay hash を参照して「変更なし」と表現できればよい。serialization 差分だけで落とさない。

#### Promotion decision

promotion decision は GEPA result をそのまま尊重する。

plugin 側の決定はほぼ機械的にする。

```text
promote:
  acceptance checks が通る
  かつ、GEPA result が candidate set を selected / improved としている
  かつ、少なくとも 1 target が changed

keep_candidate:
  acceptance checks は通るが、GEPA result が no_improvement / tie / insufficient_data
  または、changed target がない

reject:
  acceptance checks が落ちる
  または、GEPA result が invalid / worse / failed
```

固定 threshold を plugin 側で二重管理しない。`min_delta` や metric は GEPA の metric/config 側に寄せる。plugin は GEPA の selected result と壊れていない artifact だけを見る。

通ったら changed/unchanged を含む 3 overlay を同じ `overlay_generation_id` で active generation として記録する。promote しない場合も candidate artifact は残す。

## CLI / tool surface

既存のシンプル surface を維持する。

```bash
bin/hermes-self-improve improve --dry-run
bin/hermes-self-improve improve
bin/hermes-self-improve calibrate --dry-run
bin/hermes-self-improve calibrate
bin/hermes-self-improve report
bin/hermes-self-improve status
```

追加 flag は最小限。

```bash
bin/hermes-self-improve calibrate --target overlay-set --optimizer gepa --dry-run
```

`calibrate` のデフォルトは安全側:

- candidate 作成
- GEPA eval result の保存
- acceptance checks
- GEPA result に基づく promotion decision
- 条件を満たしたら promote
- dry-run では promote しない

## 実装順

### Step 1: episode に overlay hash を残す

Status: 実装済み（`90e11e0 feat: record overlay hashes in episodes`）。

変更候補:

- `outcome_store.py`
- `runner_steps.py`
- `calibration.py`

検証:

```bash
python3 -m pytest tests/test_runner_steps.py tests/test_cli_surface.py -q
bin/hermes-self-improve improve --dry-run
```

### Step 2: episode から overlay-set eval cases を作る

Status: 実装済み（`28f2320 feat: build overlay set eval cases`）。

変更候補:

- `runtime_eval_cases.py` を拡張
- 必要なら `prompt_eval_cases.py` を小さく追加

検証:

```bash
python3 -m pytest tests/test_runtime_eval_cases.py -q
bin/hermes-self-improve calibrate --target overlay-set --dry-run
```

### Step 3: GEPA で overlay candidate set を作る

Status: 実装中。candidate-set artifact の最小 contract は追加済み。

変更候補:

- `gepa_adapter.py` または小さな `prompt_gepa_adapter.py`
- `prompt_candidate_optimizer.py`

判断:

- planner/editor/evaluator を別 pipeline にしない
- 1つの candidate set に 3 target の overlay candidate を入れる
- ただし各 target は `changed|unchanged` を持ち、改善不要な overlay は active と同じ内容で持ち越す
- 既存 `gepa_adapter.py` が肥大化するなら `prompt_gepa_adapter.py` に分ける

検証:

```bash
python3 -m pytest tests/test_gepa_adapter.py tests/test_prompt_candidate_optimizer.py -q
bin/hermes-self-improve calibrate --target overlay-set --optimizer gepa --max-full-evals 2 --dry-run
```

### Step 4: GEPA eval result と acceptance checks をつなぐ

Status: 実装中。candidate-set acceptance checks と GEPA result に基づく `promote|keep_candidate|reject` 判定は追加済み。`calibrate` は candidate-set 生成と acceptance summary まで接続済み。active overlay set promotion は未接続。

変更候補:

- `autonomous_evaluator.py`
- `prompt_overlays.py`
- `calibration.py`

方針:

- GEPA 内部の val score / stats を採用判断の主材料にする
- plugin 側では重い shadow eval を再実装しない
- plugin 側は artifact が読める / overlay として壊れていない / rollback できる、だけを acceptance check する
- promote / keep_candidate / reject は GEPA result の selected/improved/no_improvement/worse をほぼそのまま反映する

検証:

```bash
python3 -m pytest tests/test_autonomous_evaluator.py tests/test_cli_surface.py -q
bin/hermes-self-improve calibrate --target overlay-set --optimizer gepa --dry-run
```

### Step 5: 出力を compact に保つ

変更候補:

- `tool_handlers.py`
- `cli.py`

検証:

```bash
bin/hermes-self-improve improve --dry-run
bin/hermes-self-improve calibrate --dry-run
```

agent-facing tool result は counts / status / artifact path だけ返す。full payload は artifact に逃がす。

## 完了条件

- GEPA が `overlay-set` candidate を生成し、baseline/candidate score と val stats を artifact に残す
- candidate artifact に planner/editor/evaluator の 3 overlay candidate と `source=gepa` が残る
- 各 overlay candidate に `change_status=changed|unchanged` が残る
- 改善不要な target は `unchanged` として active overlay と同じ hash/content を持ち越せる
- plugin 側は GEPA と同じ重い shadow eval を再実装しない
- acceptance checks が artifact readability / overlay validity / generation consistency / rollback metadata を確認できる
- promote / keep_candidate / reject は GEPA result をほぼそのまま反映する
- no_improvement / tie / insufficient_data は reject ではなく keep_candidate にできる
- candidate set が良い場合だけ 3 overlay が同じ `overlay_generation_id` で promote される
- 次の `improve` episode に新しい overlay generation / 3 overlay hash が記録される
- その episode が次回 `calibrate` の eval case に戻る
- CLI/tool 出力が長大 JSON を LLM に返さない

## 判断

この設計では、新しい概念は実質 2 つだけ。

```text
episode: どの overlay で skill/memory 改善したか
overlay candidate: GEPA が作った runtime-private prompt 差分
```

それ以外は既存の outcome / runtime eval / prompt overlay / calibration を使う。

planner/editor/evaluator は最初から同時に扱う。ただし、3 本の別 pipeline にはしない。**overlay-set という 1 つの世代単位**で candidate 作成・GEPA eval result 保存・promotion gate・promote する。
