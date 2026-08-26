# Episode Eligibility Contract Migration Implementation Plan

> **Status (2026-08-26): Implemented and verified.** New writes use episode schema `1.1` with canonical eligibility fields only; schema `1.0` remains read-only compatible. Production cron/config and active pointers were not changed. The gateway-loaded plugin tool requires a gateway restart to expose the new compact status fields; the fresh-process CLI already does.

**Goal:** 新規episodeとstatus表示から曖昧な`learnable`契約をなくし、`learning_eligible`と`outcome_eligible`を唯一の現行契約にする。

**Architecture:** 新規episodeはschema `1.1`としてcanonical eligibility fieldsだけを書き、過去のschema `1.0`と`learnable`はread-only互換として受け付ける。consumerは共有eligibility predicateへ統一し、defer/skip/previewを保存しつつoutcome・credit・runtime eval・GEPA入力から除外する。新しいagent、lane、設定、migration jobは追加しない。

**Tech Stack:** Python 3.11+、pytest、Hermes plugin CLI、append-only JSON runtime artifacts

**Parent plan:** `.hermes/plans/2026-08-26-execution-promotion-credit-hardening.md`

**Parent roadmap:** `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`

---

## 1. Current observed state

基準commitは`b2580281a4a7429a5ad354f3b655eda7bc9b7ed3`、branchは`main`、`origin/main`と同期済み、worktreeはclean。

修正後のproduction maintenance artifact:

- `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260826T031322Z.json`
  - `apply 0 / defer 5 / skip 69 / block 0`
  - 新規episode 61件
- `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260826T061248Z.json`
  - `apply 0 / defer 4 / skip 69 / block 0`
  - 新規episode 61件
- `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260826T091242Z.json`
  - `apply 0 / defer 5 / skip 69 / block 0`
  - 新規episode 62件

184件はいずれも`episode_kind=preview_decision`、`executed=false`、`changed=false`、`learning_eligible=false`、`outcome_eligible=false`で、credit/outcome/runtime-eval対象から正しく除外されている。ただし全件に`learnable=true`が併記される。最新runには`application_status=deferred`が1件、`skipped`が61件ある。

現行コードには次の不一致が残る。

1. `hermes_self_improvement/autonomous_policy.py`はdeferについて`records_episode=true`と`used_as_learning_signal=true`を返すが、実consumerはdeferを学習対象にしない。
2. `hermes_self_improvement/episodes.py`の全producerは`learnable=True`を固定で渡し、canonical eligibility fieldsと矛盾するepisodeを作る。
3. `hermes_self_improvement/autonomous_loop.py`のschema validatorとcompact summaryは旧`learnable`を必須・表示対象にしている。
4. `hermes_self_improvement/outcome_observer.py`、`runtime_eval_cases.py`、`credit_assignment.py`に旧`learnable`の直接参照が残る。

## 2. Contract decision

### New writes

新規episodeはschema `1.1`で次を必須にする。

```json
{
  "schema_name": "self_improvement_episode",
  "schema_version": "1.1",
  "executed": false,
  "changed": false,
  "application_status": "skipped",
  "learning_eligible": false,
  "outcome_eligible": false
}
```

新規writerは`learnable`を書かない。

### Historical reads

schema `1.0`は引き続き読み込む。

- completeなcanonical field pairが存在する場合は、`learnable`の有無にかかわらず`learning_eligible/outcome_eligible`を優先する。
- canonical fieldsがない古いepisodeだけ、`learnable=true`をlegacy eligibility候補として扱う。
- schema `1.0` validatorは、completeなcanonical pairまたはboolean `learnable`の少なくとも一方を要求する。片方だけのcanonical fieldや型不正は拒否する。
- legacy fallbackでも`executed=true`、`changed=true`、既知のmutation action、非preview decision/kind、`application_status=applied`の既存fail-closed条件をすべて要求する。
- canonical fieldとlegacy fieldが矛盾する場合はcanonical fieldを採用し、eligibleへ昇格させない。
- historical JSONは書き換えない。

### Policy/status

`defer`は次の意味で表示する。

```json
{
  "executes_mutation": false,
  "records_episode": true,
  "learning_eligible": false,
  "outcome_eligible": false
}
```

human-readable statusにも「episodeは記録するが、learning/outcome対象外」と表示する。

## 3. Completion criteria

- 新規schema `1.1` episodeに`learnable`が存在しない。
- 新規episodeは`learning_eligible`と`outcome_eligible`をbooleanで必ず持つ。
- schema `1.0`のhistorical fixtureを引き続き読み込める。
- schema `1.0`でcanonical pairだけを持つfixtureも読み込める。
- schema `1.0`でcanonical fieldsと`learnable`が矛盾するとき、canonical falseが優先される。
- defer/skip/preview/no-op/blocked/partial/unknownはappend-only ledgerへ残るが、learning/outcome/credit/runtime eval/episode-derived GEPAへ入らない。
- appliedかつchanged/executedの既知mutationだけeligibleになる。
- policy JSON、compact tool payload、human statusが同じdefer契約を示す。
- production cron設定、active evaluator/prompt pointer、historical artifactsを変更しない。
- focused tests、全pytest、`py_compile`、status smoke、dry-run artifact inspection、`git diff --check`が通る。

## 4. Non-goals

- outcome score、観測window、promotion thresholdの変更
- Planner/Editorのsemantic decision変更
- mutation gateの緩和
- historical artifact migrationや削除
- 新しいconfig flag、compatibility mode、migration command
- production cronの更新や手動mutating dogfood

---

### Task 1: Eligibility schema migrationのREDテストを追加する

**Objective:** schema `1.1`のcanonical contractとschema `1.0`のread-only互換を、実装前に固定する。

**Files:**
- Modify: `tests/test_autonomous_loop_contracts.py`
- Modify: `tests/test_episode_ledger.py`

**Step 1: schema `1.1` validatorのREDを書く**

`tests/test_autonomous_loop_contracts.py`へ次のケースを追加する。

```python
def test_episode_schema_1_1_requires_canonical_eligibility_without_learnable():
    payload = episode_payload(
        schema_version="1.1",
        learning_eligible=True,
        outcome_eligible=True,
    )
    payload.pop("learnable", None)

    validated = validate_episode(payload)

    assert validated["learning_eligible"] is True
    assert validated["outcome_eligible"] is True
    assert "learnable" not in validated
```

追加ケース:

- schema `1.1`で`learning_eligible`欠落 → validation error
- schema `1.1`で`outcome_eligible`欠落 → validation error
- schema `1.1`でcanonical fieldが文字列`"true"` → validation error
- schema `1.1`に`learnable`を混在 → validation error。新規writerの契約漏れを早期検出する

**Step 2: schema `1.0` compatibilityのREDを書く**

次を固定する。

- `learnable=true`だけを持つhistorical applied mutationはvalidationとeligibilityを通る
- completeなcanonical pairだけを持つschema `1.0` applied mutationもvalidationとeligibilityを通る
- `learnable=false`のhistorical episodeは対象外
- `learnable=true`でも`learning_eligible=false`が併記されたhistorical episodeは対象外
- `outcome_eligible=false`が併記されたhistorical episodeはlearning対象になれてもoutcome対象外
- canonical fieldが片方だけのschema `1.0` episodeはvalidation error
- malformed canonical fieldはlegacy `learnable=true`へfallbackせず対象外

**Step 3: producer contractのREDを書く**

`tests/test_episode_ledger.py`のskill、memory、canonical knowledge transaction、calibration promotion fixtureで次をassertする。

```python
assert episode["schema_version"] == "1.1"
assert "learnable" not in episode
assert episode["learning_eligible"] is expected_learning
assert episode["outcome_eligible"] is expected_outcome
```

preview/defer/skipは両方false、applied changed mutationは両方trueとする。

**Step 4: REDを確認する**

Run:

```bash
python -m pytest \
  tests/test_autonomous_loop_contracts.py \
  tests/test_episode_ledger.py \
  -k "schema_1_1 or canonical_eligibility or legacy" -q
```

Expected: 現行validatorがschema `1.1`を拒否するか`learnable`を要求し、producerが`learnable`を書き続けるためFAIL。

**Step 5: Commit**

```bash
git add tests/test_autonomous_loop_contracts.py tests/test_episode_ledger.py
git commit -m "test(self-improvement): define canonical episode eligibility contract"
```

---

### Task 2: Episode validatorと全writerをschema `1.1`へ移行する

**Objective:** 新規episodeから`learnable`を除去し、canonical eligibility fieldsだけを書く。

**Files:**
- Modify: `hermes_self_improvement/autonomous_loop.py:125-159`
- Modify: `hermes_self_improvement/autonomous_loop.py:208-226`
- Modify: `hermes_self_improvement/episodes.py:140-250`
- Modify: `hermes_self_improvement/episodes.py:253-670`
- Test: `tests/test_autonomous_loop_contracts.py`
- Test: `tests/test_episode_ledger.py`

**Step 1: episode専用schema versionを分離する**

`autonomous_loop.py`へepisode専用versionを追加する。他schemaのversionは変えない。

```python
LEGACY_EPISODE_SCHEMA_VERSION = "1.0"
EPISODE_SCHEMA_VERSION = "1.1"
```

`validate_episode()`はversionごとに次を検証する。

- `1.1`: canonical eligibility fieldsをboolとして必須化し、`learnable`混在を拒否
- `1.0`: completeなcanonical pairまたはboolean `learnable`の少なくとも一方を要求する。canonical pairがあれば両方をboolとして検証し、片方だけなら拒否する。legacy fieldも存在する場合はboolとして検証する
- その他: `episode_schema_version_invalid`

validatorはsemantic eligibilityを再計算しない。型・version契約だけを検証し、fail-closed semantic判定は`episodes.py`のpredicateへ集約する。

**Step 2: canonical-first predicateをwriter変更前に実装する**

`episodes.is_learning_eligible_episode()`と`is_outcome_eligible_episode()`を先にcanonical-firstへ変更する。

- `learning_eligible`が存在すれば、厳密なboolean `True`だけを候補にする
- canonical fieldがなければschema `1.0`のboolean `learnable=True`へfallbackする
- `outcome_eligible`が存在すれば、learning eligibilityに加えて厳密なboolean `True`を要求する
- canonical fieldの型不正、片方だけのcanonical pair、legacy/canonical矛盾はfail closed
- 既存のexecuted/changed/action/decision/kind/application-status条件を維持する

この順序により、後続で`learnable`を持たないschema `1.1` writerとcompact summaryを追加しても、Task 2内でGREENにできる。

**Step 3: canonical application fieldsからlegacy引数を除く**

`episodes.py`の`_application_fields()`から`learnable`引数を削除する。

```python
def _application_fields(
    *,
    executed: bool,
    changed: bool,
    action: str,
    application_status: str | None = None,
) -> dict[str, Any]:
    structurally_eligible = bool(
        executed and changed and action in ELIGIBLE_MUTATION_ACTIONS
    )
    status = str(
        application_status
        or ("applied" if structurally_eligible else "no_change" if executed else "preview")
    )
    eligible = structurally_eligible and status == "applied"
    return {
        "application_status": status,
        "learning_eligible": eligible,
        "outcome_eligible": eligible,
    }
```

decision/kindの矛盾は既存predicateがfail closedで止める。producerは既知のdecision/actionのみ作るため、新しいsemantic ruleは追加しない。

**Step 4: `_base_episode()`をschema `1.1` writerにする**

- `learnable`引数を削除
- `"schema_version": "1.1"`
- payloadから`"learnable"`を削除
- `_application_fields()`がcanonical fieldsを必ず追加

skill、memory、knowledge transactionの全call siteから`learnable=True`を削除する。

**Step 5: calibration episode writerを移行する**

`calibration_episodes_from_result()`内のoverlay/evaluator episodeもschema `1.1`へ揃える。

- `learnable`を削除
- `_application_fields()`を必ず使う
- promote + active changedだけeligible true
- candidate保持、reject、no-opはeligible false

**Step 6: compact episode summaryをcanonical化する**

`compact_episode_summary()`は次を返し、`learnable`を返さない。

```python
{
    "executed": bool(data.get("executed")),
    "changed": bool(data.get("changed")),
    "application_status": data.get("application_status"),
    "learning_eligible": is_learning_eligible_episode(data),
    "outcome_eligible": is_outcome_eligible_episode(data),
}
```

`autonomous_loop.py`から`episodes.py`をimportすると循環するため、compact summaryを`episodes.py`へ移すか、eligibility値をcallerから渡す小さな構成にする。predicateを複製しない。既存call siteがないことを確認済みだが、public import互換が必要なら`autonomous_loop.compact_episode_summary`はthin wrapperとして残す。

**Step 7: focused testsをGREENにする**

Run:

```bash
python -m pytest \
  tests/test_autonomous_loop_contracts.py \
  tests/test_episode_ledger.py -q
```

Expected: PASS。

**Step 8: Commit**

```bash
git add \
  hermes_self_improvement/autonomous_loop.py \
  hermes_self_improvement/episodes.py \
  tests/test_autonomous_loop_contracts.py \
  tests/test_episode_ledger.py
git commit -m "refactor(self-improvement): canonicalize episode eligibility fields"
```

---

### Task 3: 全consumerを共有predicateへ統一する

**Objective:** Task 2で実装したcanonical-first predicateへ全active consumerを統一し、旧`learnable`の直接参照をcompatibility boundary外からなくす。

**Files:**
- Modify: `hermes_self_improvement/episodes.py:177-208`
- Modify: `hermes_self_improvement/outcome_observer.py:529-547`
- Modify: `hermes_self_improvement/runtime_eval_cases.py:7-45`
- Modify: `hermes_self_improvement/credit_assignment.py:14-44`
- Modify: `tests/test_outcome_observer.py`
- Modify: `tests/test_runtime_eval_cases.py`
- Modify: `tests/test_credit_assignment.py`
- Modify: `tests/test_outcome_scoring.py`

**Step 1: outcome observerの直接参照を置換する**

`_coverage_episode_for_cluster()`の次を削除する。

```python
if not bool(episode.get("learnable", True)):
    continue
```

代わりに`is_outcome_eligible_episode(episode)`を使う。preview/skipをrecurrence attributionへ戻さない回帰を`tests/test_outcome_observer.py`へ追加する。

**Step 2: runtime eval helperをcanonical化する**

`runtime_eval_cases.py`の`_is_learnable_episode()`と`_is_overlay_episode()`は`bool(episode.get("learnable"))`を読まない。

- `is_learning_eligible_episode()`を共有利用する
- target kind条件だけlocal helperに残す
- `load_learning_eligible_episodes()`による入口filterも維持する

schema `1.1` applied fixtureからcaseが生成され、preview fixtureから生成されないテストを追加する。

**Step 3: credit rowからlegacy表示を除く**

`credit_assignment._score_rows()`のrowから`"learnable"`を削除し、必要な場合はcanonical fieldだけを入れる。

```python
"learning_eligible": True,
"outcome_eligible": True,
```

この関数へ到達するepisodeは`is_outcome_eligible_episode()`を通過済みなので、値をraw fieldから推測しない。compact aggregateのcount契約は変更しない。

**Step 4: source-search regressionを追加する**

active sourceで`learnable`を許すのは次のcompatibility boundaryだけとする。

- `autonomous_loop.validate_episode()`のschema `1.0` branch
- `episodes.is_learning_eligible_episode()`のschema `1.0` fallback

writer、policy、consumer、compact summaryでの`learnable`使用を禁止する。テストfixture内のschema `1.0`は許可する。

Run:

```bash
python - <<'PY'
from pathlib import Path
allowed = {
    "hermes_self_improvement/autonomous_loop.py",
    "hermes_self_improvement/episodes.py",
}
for path in Path("hermes_self_improvement").glob("*.py"):
    if "learnable" in path.read_text(encoding="utf-8"):
        assert str(path) in allowed, path
PY
```

さらにallowed 2ファイル内の参照がcompatibility branchだけに限定されていることをreviewで確認する。

**Step 5: focused testsをGREENにする**

Run:

```bash
python -m pytest \
  tests/test_episode_ledger.py \
  tests/test_outcome_scoring.py \
  tests/test_credit_assignment.py \
  tests/test_runtime_eval_cases.py \
  tests/test_outcome_observer.py -q
```

Expected: PASS。

**Step 6: Commit**

```bash
git add \
  hermes_self_improvement/episodes.py \
  hermes_self_improvement/outcome_observer.py \
  hermes_self_improvement/runtime_eval_cases.py \
  hermes_self_improvement/credit_assignment.py \
  tests/test_episode_ledger.py \
  tests/test_outcome_observer.py \
  tests/test_runtime_eval_cases.py \
  tests/test_credit_assignment.py \
  tests/test_outcome_scoring.py
git commit -m "fix(self-improvement): isolate legacy episode eligibility reads"
```

---

### Task 4: Defer policyとstatus表示を実契約へ揃える

**Objective:** operatorが「記録された」と「学習対象になった」を混同しないpolicy/statusを返す。

**Files:**
- Modify: `hermes_self_improvement/autonomous_policy.py:45-73`
- Modify: `hermes_self_improvement/cli.py:1481-1498`
- Modify: `tests/test_autonomous_policy.py`
- Modify: `tests/test_cli_surface.py`
- Modify: `tests/test_plugin_tools.py`

**Step 1: policy REDを書く**

`tests/test_autonomous_policy.py`で次を要求する。

```python
assert policy["defer"] == {
    "executes_mutation": False,
    "records_episode": True,
    "learning_eligible": False,
    "outcome_eligible": False,
}
assert "used_as_learning_signal" not in policy["defer"]
```

compact summaryは次を含む。

```python
{
    "defer_executes_mutation": False,
    "defer_records_episode": True,
    "defer_learning_eligible": False,
    "defer_outcome_eligible": False,
}
```

**Step 2: human status REDを書く**

`tests/test_cli_surface.py`で`_render_status_summary()`の出力に次の一行を要求する。

```text
- defer: records episode, learning ineligible, outcome ineligible, no mutation
```

旧`defer executes mutation: False`だけの行は削除する。booleanの羅列ではなく、意味が一読できる文にする。

**Step 3: policyとrendererを最小修正する**

- `used_as_learning_signal`を削除
- canonical fieldsを追加
- `summarize_autonomous_operation_policy()`へ4項目を明示
- status JSON、tool payload、calibration/improve artifactは同じcompact summaryを再利用
- cron/reportのaction countsやmutation behaviorは変更しない

**Step 4: focused testsをGREENにする**

Run:

```bash
python -m pytest \
  tests/test_autonomous_policy.py \
  tests/test_cli_surface.py \
  tests/test_plugin_tools.py -q
```

Expected: PASS。

**Step 5: Commit**

```bash
git add \
  hermes_self_improvement/autonomous_policy.py \
  hermes_self_improvement/cli.py \
  tests/test_autonomous_policy.py \
  tests/test_cli_surface.py \
  tests/test_plugin_tools.py
git commit -m "fix(self-improvement): clarify deferred episode policy"
```

---

### Task 5: Full verificationとartifact-backed dogfoodを行う

**Objective:** historical compatibility、新規writer、全consumer、operator表示が同じ契約で動くことを実行結果で証明する。

**Files:**
- Modify: `.hermes/plans/2026-08-26_180558-episode-eligibility-contract-migration.md`
- Modify: `.hermes/plans/README.md`

**Step 1: focused regressionを実行する**

```bash
python -m pytest \
  tests/test_autonomous_loop_contracts.py \
  tests/test_autonomous_policy.py \
  tests/test_episode_ledger.py \
  tests/test_outcome_scoring.py \
  tests/test_credit_assignment.py \
  tests/test_runtime_eval_cases.py \
  tests/test_outcome_observer.py \
  tests/test_cli_surface.py \
  tests/test_plugin_tools.py -q
```

Expected: PASS。

**Step 2: full verificationを実行する**

```bash
python -m py_compile __init__.py hermes_self_improvement/*.py
python -m pytest tests -q
hermes self-improvement status --json
git diff --check
```

`hermes self-improvement status --json`はHermes本体のterminalから実行する。OpenCodeなどnested sandbox内で`Operation not permitted`になる場合は回避せず、その環境では実行不能と記録し、Hermes terminalで取得した同一commitのexit codeと出力をreviewerへ渡す。status smokeを未実行のまま完了扱いにはしない。

Expected:

- compile/test/diff checkがexit 0
- status full policyに`used_as_learning_signal`がない
- compact statusに`defer_records_episode=true`、`defer_learning_eligible=false`、`defer_outcome_eligible=false`

**Step 3: historical artifact compatibilityを確認する**

production run JSONの`episodes.files`配列を読み、配列が指すepisode JSON本体をread-onlyでloadする。

- `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260826T031322Z.json`
- `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260826T061248Z.json`
- `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260826T091242Z.json`

run JSON自体にepisode本体は埋め込まれていないため、検証対象は必ず`episodes.files`の184ファイルとする。

Expected:

- 184件のschema `1.0` episodeを読める
- legacy `learnable=true`があってもcanonical `learning_eligible=false`を優先
- eligible/outcome/scored countが修正前より増えない
- malformed/contradictory rowをeligibleへ昇格しない

**Step 4: non-mutating dry-runを実行する**

```bash
hermes self-improvement improve --dry-run --json
```

生成artifactとepisode filesを確認する。

Expected:

- `dry_run=true`
- `target_changed=false`
- 新規episodeはschema `1.1`
- 新規episodeに`learnable`なし
- 全episodeにcanonical eligibility fieldsあり
- preview/defer/skipは両方false
- dry-run episodeがcredit/outcome/runtime evalへ入らない

production cron/config、active evaluator/prompt pointerは変更しない。

**Step 5: read-only independent reviewを行う**

OpenCode reviewerへ次を確認させる。

- schema `1.0` compatibilityがfail openになっていない
- canonical falseがlegacy trueより優先される
- writerに`learnable`が残っていない
- outcome/credit/runtime eval/GEPA consumerが共有predicateを通る
- policy/statusがruntime behaviorと一致する
- historical artifact rewriteやmutation gate変更がない

BLOCKEDがあれば修正後に再reviewする。

**Step 6: planとindexを完了状態へ更新する**

このplanへ実測値を追記し、`.hermes/plans/README.md`を`implemented / verified`へ更新する。`proven improved`が0なら0のまま記録し、改善済みとは書かない。

**Step 7: final commit**

```bash
git add .hermes/plans/2026-08-26_180558-episode-eligibility-contract-migration.md .hermes/plans/README.md
git commit -m "docs(self-improvement): record eligibility contract verification"
```

pushはユーザーの明示依頼がある場合だけ行う。

### Verification record — 2026-08-26

- Full suite: `1100 passed, 2 skipped in 25.29s`.
- `py_compile` and `git diff --check`: exit 0.
- Historical compatibility: the three production runs named above referenced 184 schema `1.0` episodes; all 184 validated, all retained canonical `learning_eligible=false / outcome_eligible=false`, and none became eligible. SHA-256 hashes for the 3 run files plus 184 episode files remained unchanged.
- Fresh-process JSON/human status exposes `defer_executes_mutation=false`, `defer_records_episode=true`, `defer_learning_eligible=false`, and `defer_outcome_eligible=false`; production source contains no `used_as_learning_signal`.
- Non-mutating dry-run artifact: `/Users/ryo.nakae/.hermes/self-improvement/runs/run-20260826T114258Z.json`, with `dry_run=true`, `execute=false`, `target_changed=false`, `apply 0 / defer 6 / skip 69 / block 0`.
- The dry-run wrote 61 schema `1.1` episodes. All 61 had canonical boolean eligibility fields, none contained `learnable`, and all had `executed=false / changed=false / learning_eligible=false / outcome_eligible=false`.
- Active evaluator/prompt pointer hashes and historical artifact hashes were unchanged after the dry-run. No mutating dogfood or cron/config change was performed.
- Report accounting remained conservative: latest 1,000-row views showed `eligible 5 / excluded 995 / scored 0` or older run snapshots `eligible 8 / excluded 992 / scored 0`; no preview episode was promoted into outcome credit and strict `proven improved` was not claimed.
- Independent per-task read-only reviews passed Tasks 2–4. The delayed Task 1 subagents were interrupted and superseded by the final Green implementation and full-suite verification.

---

## 5. Risks and controls

### Historical eligibilityを広げる危険

schema `1.0` fallbackを`learnable=true`だけで判定するとpreviewが復活する。既存のexecuted/changed/action/decision/kind/application-status条件を必ず再評価し、canonical fieldがある場合はそちらを優先する。

### Schema versionの波及

global `SCHEMA_VERSION`を変更するとoutcome/evaluator schemaまで変わる。episode専用version定数だけを追加し、他artifact schemaは変更しない。

### Circular import

`autonomous_loop.py`と`episodes.py`間でpredicateを相互importしない。semantic predicateは`episodes.py`を正本にし、validatorはversion/型だけを検証する。compact summaryの配置またはwrapperで依存方向を一方向に保つ。

### Report count regression

field renameとeligible count変更を混ぜない。`total / eligible / excluded / scored / proven improved`の意味と集計値は維持し、表示契約だけをcanonical化する。

## 6. Expected commit sequence

1. `test(self-improvement): define canonical episode eligibility contract`
2. `refactor(self-improvement): canonicalize episode eligibility fields`
3. `fix(self-improvement): isolate legacy episode eligibility reads`
4. `fix(self-improvement): clarify deferred episode policy`
5. `docs(self-improvement): record eligibility contract verification`

This plan is the completed implementation record for the episode eligibility contract migration.
