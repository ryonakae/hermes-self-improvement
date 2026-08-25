# Self-Improvement Execution, Promotion, and Credit Hardening Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** memory replaceを実際に適用できる状態へ戻し、改善していないoverlayの昇格を止め、outcome集計を効果測定に値するepisodeへ限定する。

**Architecture:** 既存のPlanner → canonical knowledge transaction → Knowledge Editor、GEPA candidate set → evaluator → active overlay、episode → outcome observer → credit assignmentの各経路は維持する。新しいagent、approval lane、設定項目、スコアリング基盤は追加せず、既存フィールドと`learnable`契約を正しく消費する。

**Tech Stack:** Python 3.11+、pytest、DSPy / GEPA、Hermes plugin CLI、JSON runtime artifacts

**Parent roadmap:** `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`

---

## 1. 調査結果

2026-08-26時点のrecent artifactと現行コードから、次の3件を根因として確認した。

1. **Memory replacement payload contract mismatch**
   - `run-20260821T181250Z.json`、`run-20260822T061328Z.json`、`run-20260823T061308Z.json`のapply transactionには、`source_old_text`と`replacement_content`が存在する。
   - transactionは`transaction_kind=memory`、`operation=memory_replace`としてexecutorへ渡る。
   - `runner_steps._knowledge_transaction_content()`は`content`、`editor_task.content`、`current_claim`しか読まないため、`replacement_content`を捨てる。
   - その結果、公式memory mutation contextは`memory_replace_args_missing:content`で停止する。

2. **Overlay promotion gate ignores score delta**
   - candidate set artifactには既にtop-level `baseline_score`と`candidate_score`がある。
   - `autonomous_evaluator._overlay_candidate_decision()`は`gepa_result=selected`、changed targetあり、hard violationなしだけで`promote`する。
   - `candidate_score == baseline_score`でもactive overlayへ昇格できる。

3. **Credit assignment consumes non-learning boilerplate**
   - `episodes._knowledge_transaction_episode()`は全transactionを`learnable=True`にする。
   - programが補完した`inventory_not_selected_by_planner`のskipも毎run記録される。
   - `credit_assignment._score_rows()`、`outcome_scoring.build_outcome_score_aggregate()`、`outcome_observer.run_outcome_prepass()`、runtime eval case buildersは`learnable`を選別せず、直近1000件をそのまま使う。
   - audit ledgerは有用だが、同じboilerplate skipがoutcome追跡とGEPAの入力を埋めるべきではない。

## 2. 完了条件

このplanは次の条件をすべて満たすまで完了扱いにしない。

- `memory_replace`がtop-levelまたは`editor_task`内の`replacement_content`を公式memory toolの`content`へ正しく渡す。
- replacement本文欠落、exact old text不一致、post-validation失敗は従来どおりfail closedになる。
- overlayは`candidate_score > baseline_score`が数値として確認できる場合だけ`promote`できる。
- 同点、悪化、score欠落・非数値はactiveを変えず、candidate artifactを保持して理由を返す。
- append-only episode ledgerは維持する。
- program補完のinventory skipは監査用episodeとして残せるが、outcome prepass、credit assignment、outcome score、runtime eval caseの対象外になる。
- historical episodeも、既存の`reason=inventory_not_selected_by_planner`からmigrationなしで除外できる。
- changed/executed mutation、blocked/partial execution、Plannerが根拠付きで選んだapply/defer/skip、calibration promotionは学習対象のまま残る。
- deterministic integration testで、changed episode → later comparable observation → strict `improved` creditを証明する。
- 実artifactで後続比較がまだない場合、reportは`proven improved`を0のまま保ち、改善済みと表現しない。
- focused tests、全pytest、`py_compile`、`git diff --check`が通る。

## 3. 非対象

- Planner / Knowledge Editor / Evaluator / Calibrator以外の新しいactor
- `candidate_score - baseline_score`の閾値をconfig化すること
- outcome scoreの重み変更や新しい報酬関数
- historical runtime artifactの書き換え
- USER/MEMORY placement policyの変更
- skill/memory mutation gateを緩めること
- テストのためだけの強制的なreal memory mutation

---

### Task 1: Memory replacement contractのREDテストを追加する

**Objective:** recent artifactと同じtransaction shapeが現行executorで失敗することを、本文を固定fixtureへ閉じ込めて再現する。

**Files:**
- Modify: `tests/test_memory_to_skill_migration.py`
- Modify: `tests/test_knowledge_transactions.py`

**Step 1: failing executor regressionを書く**

`tests/test_memory_to_skill_migration.py`へ、次の2ケースを追加する。

```python
def test_execute_canonical_memory_replace_uses_top_level_replacement_content():
    calls = []
    result = execute_knowledge_transaction(
        {
            "transaction_kind": "memory",
            "decision": "apply",
            "operation": "memory_replace",
            "source_store": "builtin_memory",
            "target_store": "builtin_memory",
            "source_old_text": "Old durable fact.",
            "replacement_content": "Current durable fact.",
        },
        config={"_memory_tool_func": recording_memory_tool(calls)},
        mutate=True,
    )

    assert result["success"] is True
    assert calls == [{
        "action": "replace",
        "target": "memory",
        "old_text": "Old durable fact.",
        "content": "Current durable fact.",
    }]
```

同じ期待値で、`editor_task.replacement_content`だけを持つケースも追加する。既存fixture/helper名が異なる場合は、同ファイルのofficial memory tool spyを再利用し、新helperを増やさない。

**Step 2: REDを確認する**

Run:

```bash
python -m pytest tests/test_memory_to_skill_migration.py -k "replacement_content" -q
```

Expected: FAIL。`memory_replace_args_missing:content`またはmemory tool callの`content`欠落を確認する。

**Step 3: normalizerのfail-closed回帰を追加する**

`tests/test_knowledge_transactions.py`の既存`test_normalize_memory_rewrite_apply_requires_exact_replacement_content`の隣に、次を追加する。

- `transaction_kind=memory / operation=memory_replace`で`replacement_content`なし → `decision=block`
- `replacement_content`あり → `decision=apply`を維持
- `content`ありのlegacy/canonical shape → 既存互換を維持

**Step 4: REDを確認する**

Run:

```bash
python -m pytest tests/test_knowledge_transactions.py -k "memory_replace" -q
```

Expected: 少なくともreplacement欠落のapplyが現状通過することを示すFAIL。

**Step 5: Commit**

```bash
git add tests/test_memory_to_skill_migration.py tests/test_knowledge_transactions.py
git commit -m "test(self-improvement): reproduce memory replace payload loss"
```

---

### Task 2: `replacement_content`をcanonical contentへ橋渡しする

**Objective:** Plannerが生成済みのexact replacementを、意味を変えずKnowledge Editorへ渡す。

**Files:**
- Modify: `hermes_self_improvement/runner_steps.py:2134-2153`
- Modify: `hermes_self_improvement/knowledge_transactions.py:198-280`
- Test: `tests/test_memory_to_skill_migration.py`
- Test: `tests/test_knowledge_transactions.py`

**Step 1: content resolutionを最小修正する**

`_knowledge_transaction_content()`の優先順を次にする。

```python
def _knowledge_transaction_content(transaction: dict[str, Any]) -> str:
    task = transaction.get("editor_task") if isinstance(transaction.get("editor_task"), dict) else {}
    return str(
        transaction.get("content")
        or transaction.get("replacement_content")
        or task.get("content")
        or task.get("replacement_content")
        or transaction.get("current_claim")
        or ""
    ).strip()
```

優先順の理由は、明示的なcanonical `content`を最優先し、その後にrecent Planner shapeの`replacement_content`を読むため。replacement文をprogram側で生成・短縮・書き換えない。

**Step 2: apply validationをcanonical operation全体へ揃える**

`knowledge_transactions._validate_apply_transaction()`で、次の両shapeが同じrequired-field contractを通るようにする。

- `transaction_kind=memory_rewrite / operation=replace`
- `transaction_kind=memory / operation=memory_replace`

`memory_replace` applyは`source_old_text`と、`content`または`replacement_content`のどちらかが必須。欠落時は既存reason `planner_task_missing_replacement_content`で`block / operation=none`へ落とす。

**Step 3: focused testsをGREENにする**

Run:

```bash
python -m pytest \
  tests/test_memory_to_skill_migration.py \
  tests/test_knowledge_transactions.py \
  -k "memory_replace or memory_rewrite" -q
```

Expected: PASS。

**Step 4: memory execution regressionsを確認する**

Run:

```bash
python -m pytest \
  tests/test_memory_to_skill_migration.py \
  tests/test_mutation_policy.py \
  tests/test_knowledge_transactions.py -q
```

Expected: PASS。stale source、missing old text、post-validation failure、dry-run previewが従来どおり停止または非mutationになる。

**Step 5: Commit**

```bash
git add hermes_self_improvement/runner_steps.py hermes_self_improvement/knowledge_transactions.py tests/test_memory_to_skill_migration.py tests/test_knowledge_transactions.py
git commit -m "fix(self-improvement): preserve memory replacement content"
```

---

### Task 3: Overlay promotionをstrict score improvementに限定する

**Objective:** GEPAの`selected`を候補選択として扱い、active昇格は既存baselineより数値的に良い場合だけ許可する。

**Files:**
- Modify: `hermes_self_improvement/autonomous_evaluator.py:297-326`
- Modify: `hermes_self_improvement/calibration.py`
- Modify: `tests/test_autonomous_evaluator.py:155-229`
- Modify: `tests/test_feedback_loop.py`

**Step 1: equal/worse/missing scoreのREDテストを書く**

`tests/test_autonomous_evaluator.py`の`overlay_candidate_set()` fixtureへtop-level `baseline_score`と`candidate_score`を追加する。テストは次の表を固定する。

| baseline | candidate | GEPA | Expected |
|---:|---:|---|---|
| 0.25 | 0.50 | selected | promote |
| 1.00 | 1.00 | selected | keep_candidate |
| 1.00 | 0.75 | selected | keep_candidate |
| missing | 1.00 | selected | keep_candidate |
| 1.00 | non-numeric | selected | keep_candidate |
| 0.25 | 0.50 | failed | reject |

各resultで`promotion_reason`、`baseline_score`、`candidate_score`もassertする。

**Step 2: REDを確認する**

Run:

```bash
python -m pytest tests/test_autonomous_evaluator.py -k "overlay_candidate_set" -q
```

Expected: equal/worse/missing scoreケースが現状`promote`となりFAIL。

**Step 3: strict comparison helperを実装する**

`autonomous_evaluator.py`へ、boolを数値扱いしない小さなhelperを追加する。

```python
def _score_improvement(candidate_set: dict[str, Any]) -> tuple[bool, float | None, float | None, str]:
    baseline = candidate_set.get("baseline_score")
    candidate = candidate_set.get("candidate_score")
    if not isinstance(baseline, (int, float)) or isinstance(baseline, bool):
        return False, None, None, "baseline_score_unavailable"
    if not isinstance(candidate, (int, float)) or isinstance(candidate, bool):
        return False, float(baseline), None, "candidate_score_unavailable"
    baseline_value = float(baseline)
    candidate_value = float(candidate)
    if candidate_value <= baseline_value:
        return False, baseline_value, candidate_value, "candidate_not_strictly_better"
    return True, baseline_value, candidate_value, "candidate_strictly_better"
```

`evaluate_overlay_candidate_set()`はartifactをloadした後、このhelperを使う。`_overlay_candidate_decision()`のpromote条件は次のすべてを要求する。

- hard violationなし
- `gepa_result`がpromote対象
- changed targetあり
- scoreが比較可能
- `candidate_score > baseline_score`

同点、悪化、score欠落は`keep_candidate`。GEPA failureやhard violationは従来どおり`reject`。

**Step 4: evaluation resultとcompact reportに理由を残す**

full evaluation resultへ次を追加する。

```python
{
    "baseline_score": baseline_score,
    "candidate_score": candidate_score,
    "score_improved": score_improved,
    "promotion_reason": promotion_reason,
}
```

`calibration.py`のcompact resultはprompt本文を出さず、score 2値と`promotion_reason`だけを出す。active pointer更新は`decision == "promote"`の既存条件を維持する。

**Step 5: focused testsをGREENにする**

Run:

```bash
python -m pytest \
  tests/test_autonomous_evaluator.py \
  tests/test_feedback_loop.py -q
```

Expected: PASS。

**Step 6: candidate artifact互換を確認する**

既存artifact fixtureで次を確認する。

- `baseline_score=-0.25 / candidate_score=0.1`はpromote可能
- `baseline_score=1.0 / candidate_score=1.0`はkeep_candidate
- artifact自体は削除されず、active pointerだけが変わらない

**Step 7: Commit**

```bash
git add hermes_self_improvement/autonomous_evaluator.py hermes_self_improvement/calibration.py tests/test_autonomous_evaluator.py tests/test_feedback_loop.py
git commit -m "fix(self-improvement): require strict overlay score improvement"
```

---

### Task 4: Learning-eligible episodeだけをoutcomeとGEPAへ渡す

**Objective:** audit ledgerを保ちながら、program補完のboilerplate skipが直近1000件とruntime eval casesを埋めるのを止める。

**Files:**
- Modify: `hermes_self_improvement/episodes.py` (`_knowledge_transaction_episode`, `load_recent_episodes`)
- Modify: `hermes_self_improvement/credit_assignment.py:14-40`
- Modify: `hermes_self_improvement/outcome_scoring.py:206-210`
- Modify: `hermes_self_improvement/outcome_observer.py:850-859`
- Modify: `hermes_self_improvement/runtime_eval_cases.py:403-575`
- Modify: `tests/test_episode_ledger.py`
- Modify: `tests/test_credit_assignment.py`
- Modify: `tests/test_outcome_scoring.py`
- Modify: `tests/test_outcome_observer.py`
- Modify: `tests/test_runtime_eval_cases.py`

**Step 1: eligibilityのREDテストを書く**

`tests/test_episode_ledger.py`へ次を追加する。

- `reason=inventory_not_selected_by_planner`、`decision=skip`、`executed=False`、`changed=False`はledgerへ記録されるが`learnable=False`
- apply / blocked / partial / changed transactionは`learnable=True`
- Plannerがevidence付きで返したdefer/skipは`learnable=True`
- `load_recent_episodes(learnable_only=True, limit=N)`はnon-learning rowを飛ばし、さらに古いeligible rowをN件集める
- historical fixtureで`learnable=True`でも`reason=inventory_not_selected_by_planner`なら互換ルールにより除外する

**Step 2: REDを確認する**

Run:

```bash
python -m pytest tests/test_episode_ledger.py -k "learnable or learning_eligible" -q
```

Expected: current implementationがinventory skipを`learnable=True`にする、または`learnable_only`引数がなくFAIL。

**Step 3: one canonical eligibility helperを追加する**

`episodes.py`へ`episode_is_learning_eligible(episode)`を追加し、判定を一箇所へ集約する。

```python
def episode_is_learning_eligible(episode: dict[str, Any]) -> bool:
    if (
        str(episode.get("reason") or "") == "inventory_not_selected_by_planner"
        and not episode.get("executed")
        and not episode.get("changed")
        and str(episode.get("action") or "") == "no_op"
    ):
        return False
    return bool(episode.get("learnable"))
```

`_knowledge_transaction_episode()`は同じ条件で新規episodeの`learnable=False`を保存する。historical artifactはhelperで同じ意味になるためmigrationしない。

このsliceでreason文字列の一般化、skip taxonomyの再設計、重み付けはしない。

**Step 4: eligible-only loaderを実装する**

`load_recent_episodes()`へkeyword-only `learnable_only: bool = False`を追加する。`False`は監査互換、`True`はnon-learning rowをappend前に除外し、**eligible rowがlimit件集まるまで**古いfileを読む。最初のraw 1000件を読んでからfilterする実装にはしない。

**Step 5: learning consumersを一括で切り替える**

次のcall siteだけ`learnable_only=True`へ変更する。

- `credit_assignment._score_rows()`
- `outcome_scoring.build_outcome_score_aggregate()`
- `outcome_observer.run_outcome_prepass()`
- `runtime_eval_cases.build_role_runtime_eval_cases()`
- `runtime_eval_cases.build_overlay_set_runtime_eval_cases()`

status/reportの監査件数やraw ledger readerがあればdefault `False`を維持する。

**Step 6: consumer回帰テストを書く**

各testで、eligible mutation 1件とboilerplate skip 20件をfixtureへ置き、次をassertする。

- credit assignment `episode_count == 1`
- outcome score aggregateの対象が1件
- outcome prepass collectorへ渡るepisodeが1件
- role/overlay runtime eval casesにinventory skip由来caseがない
- raw `load_recent_episodes()`では21件を読める

**Step 7: focused testsをGREENにする**

Run:

```bash
python -m pytest \
  tests/test_episode_ledger.py \
  tests/test_credit_assignment.py \
  tests/test_outcome_scoring.py \
  tests/test_outcome_observer.py \
  tests/test_runtime_eval_cases.py -q
```

Expected: PASS。

**Step 8: Commit**

```bash
git add hermes_self_improvement/episodes.py hermes_self_improvement/credit_assignment.py hermes_self_improvement/outcome_scoring.py hermes_self_improvement/outcome_observer.py hermes_self_improvement/runtime_eval_cases.py tests/test_episode_ledger.py tests/test_credit_assignment.py tests/test_outcome_scoring.py tests/test_outcome_observer.py tests/test_runtime_eval_cases.py
git commit -m "fix(self-improvement): exclude audit-only episodes from learning"
```

---

### Task 5: Changed episodeからstrict outcomeまでの統合テストを追加する

**Objective:** 実変更を記録しても比較不能のままになる経路を、matching signature込みでend-to-end検証する。

**Files:**
- Modify: `tests/test_outcome_matching.py`
- Modify: `tests/test_credit_assignment.py`
- Modify: `tests/test_feedback_loop.py`

**Step 1: deterministic end-to-end RED testを書く**

fixtureで次を構築する。

1. `executed=True / changed=True / action=memory_replace`のepisodeを記録
2. episodeと同じbounded matching signatureを持つlater comparable outcome observationを記録
3. observationへstrict positive component（既存contractの`failure_reduction`または`user_correction_absent`）を持たせる
4. `build_credit_assignment_aggregate()`を実行

assert:

```python
assert aggregate["outcome_status_counts"]["improved"] == 1
assert aggregate["quality_outcomes"]["unknown_reasons"].get(
    "no_later_comparable_observation", 0
) == 0
```

raw memory本文、tool args、prompt本文がepisode/outcome/aggregateへ漏れないことも既存redaction assertionで確認する。

**Step 2: negative controlを追加する**

- matching signatureが異なるlater observation → `improved=0`
- weak usageだけ → strict `improved=0`、report-only early positiveのまま
- boilerplate inventory skip → aggregate対象外

**Step 3: focused testsをGREENにする**

Run:

```bash
python -m pytest \
  tests/test_outcome_matching.py \
  tests/test_credit_assignment.py \
  tests/test_feedback_loop.py -q
```

Expected: PASS。

**Step 4: Commit**

```bash
git add tests/test_outcome_matching.py tests/test_credit_assignment.py tests/test_feedback_loop.py
git commit -m "test(self-improvement): prove comparable outcome credit path"
```

---

### Task 6: Full validationとdry-run dogfoodを行う

**Objective:** 3つの修正が既存の安全境界とreport contractを壊していないことを実行結果で確認する。

**Files:**
- Modify after verification: `.hermes/plans/2026-08-26-execution-promotion-credit-hardening.md`
- Modify after verification: `.hermes/plans/README.md`
- Modify after verification: `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`

**Step 1: syntaxとfocused regressionを実行する**

Run:

```bash
python -m py_compile hermes_self_improvement/*.py
python -m pytest \
  tests/test_memory_to_skill_migration.py \
  tests/test_knowledge_transactions.py \
  tests/test_autonomous_evaluator.py \
  tests/test_feedback_loop.py \
  tests/test_episode_ledger.py \
  tests/test_credit_assignment.py \
  tests/test_outcome_matching.py \
  tests/test_outcome_scoring.py \
  tests/test_outcome_observer.py \
  tests/test_runtime_eval_cases.py -q
```

Expected: PASS。

**Step 2: full suiteを実行する**

Run:

```bash
python -m pytest tests -q
git diff --check
```

Expected: 全test PASS、2 skipped以内の既知skipのみ、diff check clean。

**Step 3: source contractを検索する**

Run:

```bash
python - <<'PY'
from pathlib import Path
text = Path('hermes_self_improvement/runner_steps.py').read_text()
assert 'transaction.get("replacement_content")' in text
assert 'task.get("replacement_content")' in text
print('replacement content bridge: ok')
PY
```

Expected: `replacement content bridge: ok`。

**Step 4: dry-run dogfoodを実行する**

Run:

```bash
bin/hermes-self-improve improve --dry-run --json
bin/hermes-self-improve calibrate --dry-run --json
bin/hermes-self-improve report --since-hours 24
```

Expected:

- improve artifactは`dry_run=true`、`target_changed=false`
- memory replacement applyがあれば、previewは`memory_replace_args_missing:content`にならない
- calibrateで同点またはscore不明なら`keep_candidate`かつactive unchanged
- reportのstrict proofはeligible episodeだけをtrackedとして扱う
- report-only weak positiveはstrict `proven improved`へ昇格しない

**Step 5: mutating dogfoodの境界を守る**

このplanの実装完了確認では、テスト用のmemory/skill変更を捏造しない。自然に低リスクapplyが出た場合だけ、Ryoの明示承認後に`improve --execute`または通常cron結果を観測する。

実mutation後は次の2段階で確認する。

1. 同run: `changed=True`、official tool success、post-validation passed、episodeがlearning eligible
2. 後続run/session: comparable outcomeがmatching signatureで結び付き、strict positive evidenceがある場合だけ`proven improved`へ入る

後続比較がない場合は`insufficient_window`または`unknown / no_later_comparable_observation`を正解とする。

**Step 6: plan indexとroadmapを更新する**

検証結果、artifact path、test count、real mutationの有無、outcome証明の有無をこのplanへ記録する。`.hermes/plans/README.md`のcurrent priorityをcompletedへ変え、parent roadmapのcurrent-stateへ結果を反映する。

**Step 7: Final commit**

```bash
git add .hermes/plans/2026-08-26-execution-promotion-credit-hardening.md .hermes/plans/README.md .hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md
git commit -m "docs(self-improvement): record hardening verification"
```

---

## 4. 実装時の判断ルール

- memory replacement本文はPlanner出力をそのまま公式toolへ渡す。programで補完生成しない。
- exact sourceが現在値と一致しなければblockする。自動再探索・別entry置換はしない。
- GEPAの`selected`は「候補として選ばれた」であり、「baselineより改善した」と同義にしない。
- strict promotionに新しいconfig thresholdは設けない。まず既存scoreの`>`だけを正しく適用する。
- episode ledgerは監査記録として削らない。学習対象の選別は既存`learnable` contractで行う。
- `inventory_not_selected_by_planner`以外のskip/deferを一括除外しない。Plannerのsemantic judgmentや安全停止は学習材料になり得る。
- reportの`proven improved`定義は緩めない。弱い肯定材料は既存`Outcome signals`に残す。

## 5. Rollback

- Task 2: content bridge commitをrevertすれば、memory replaceは再び安全停止する。partial writeを許す変更は含まない。
- Task 3: promotion gate commitをrevertしてもcandidate artifactは残る。active pointerの変更履歴は既存rollback identityで追跡する。
- Task 4: eligible-only consumer変更をrevertしてもappend-only ledgerに欠損はない。historical artifact migrationは不要。
- いずれもruntime artifactを削除・書換えしない。
