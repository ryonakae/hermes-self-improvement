# Slice B Detailed Plan — Deterministic Cluster Summary + Evidence Index/Detail Artifacts

> **For Hermes:** This plan refines Slice B from `2026-05-26-turn-trace-and-readiness-followup.md` into implementation-ready tasks. Use strict TDD. After each completed task, update the parent follow-up plan, the long-term roadmap, and `.hermes/plans/README.md` if scope/status changed.

**Parent plans:**
- `.hermes/plans/2026-05-26-turn-trace-and-readiness-followup.md`
- `.hermes/plans/2026-05-25-self-improvement-role-redesign.md`
- `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md`

**Goal:** Build deterministic cluster summary, evidence index, and evidence detail artifacts from turn traces so the planner can read index-first detail instead of raw event-derived digests.

**Status — 2026-05-26:** ✅ Complete. All tasks landed: build_cluster_summary, build_evidence_index, build_evidence_detail, persistence (write_cluster_summary / write_evidence_index + atomic JSON), CLI improve flow wiring, status display. 818 tests passing.

**Architecture:** Turn traces (Slice A) → deterministic cluster summary → evidence index → evidence detail (for selected clusters). No LLM summarizer. All grouping, dedup, and representative selection is code-only. The cluster summary is a compact grouped view of recurring tool/error/kind patterns across traces. The evidence index is a `skills_list`-like compact list for the planner. Evidence detail is the `skill_view`-like drilldown for selected cluster ids.

**Tech Stack:** Python, pytest, existing `evidence.py` cluster logic, existing `observer.py` trace artifacts, `hermes_self_improvement/` module structure.

---

## Scope boundaries

### In scope
- Define cluster summary artifact schema and build it from turn traces.
- Define evidence index artifact schema and build it from cluster summary.
- Define evidence detail records for selected clusters.
- Persist cluster/index/detail as runtime artifacts.
- Add deterministic id and ordering rules (byte-stable for same input).
- Add focused TDD tests for each layer.
- Update `status` to show cluster/index counts.

### Out of scope
- Making planner consume the new index/detail directly (Slice C).
- Deleting or replacing `build_evidence_pack` / `events.jsonl` flow (migration later).
- LLM summarizer or semantic grouping.
- Quality retuning (Slice D).
- Changing the existing evidence pack format that planner currently receives.

---

## Artifact contracts

### Cluster summary

```json
{
  "schema_name": "self_improvement_cluster_summary",
  "schema_version": "1.0",
  "generated_at": "...",
  "trace_count": 17,
  "trace_range": {"earliest": "...", "latest": "..."},
  "clusters": [
    {
      "cluster_id": "c_<sha256-prefix>",
      "group_key": {"tool_name": "terminal", "error_kind": "nonzero_exit"},
      "count": 5,
      "traces_affected": ["turn-abc123", "turn-def456", ...],
      "representative_trace_ids": ["turn-abc123"],
      "severity": "medium",
      "rate": 0.3,
      "error_kinds": ["nonzero_exit"],
      "tools": ["terminal"],
      "outcome_summary": {"completed": 2, "failed": 3},
      "target_hints": [
        {"target_skill": "timeout-workflow", "confidence": "medium", "source": "proposal_cluster"}
      ]
    }
  ],
  "unclustered_count": 12,
  "total_step_count": 83,
  "total_error_count": 19
}
```

### Evidence index

```json
{
  "schema_name": "self_improvement_evidence_index",
  "schema_version": "1.0",
  "generated_at": "...",
  "source_summary_id": "cs_<sha256-prefix>",
  "cluster_count": 7,
  "total_evidence_count": 42,
  "entries": [
    {
      "cluster_id": "c_<sha256-prefix>",
      "group_key": {"tool_name": "terminal", "error_kind": "nonzero_exit"},
      "count": 5,
      "severity": "medium",
      "target_skill": "timeout-workflow",
      "target_confidence": "medium",
      "has_detail": true
    }
  ],
  "unclustered_summary": {
    "count": 12,
    "sample_kinds": ["correction_evidence", "llm_api_evidence", ...]
  }
}
```

### Evidence detail

```json
{
  "schema_name": "self_improvement_evidence_detail",
  "schema_version": "1.0",
  "generated_at": "...",
  "cluster_id": "c_<sha256-prefix>",
  "source_summary_id": "cs_<sha256-prefix>",
  "group_key": {"tool_name": "terminal", "error_kind": "nonzero_exit"},
  "count": 5,
  "traces": [
    {
      "turn_id": "turn-abc123",
      "session_id": "...",
      "platform": "...",
      "created_at": "...",
      "steps": [
        {
          "step_index": 0,
          "kind": "tool",
          "tool_name": "terminal",
          "status": "error",
          "error_kind": "nonzero_exit",
          "args_preview": {},
          "result_preview": "..."
        }
      ],
      "summary": {
        "tool_count": 3,
        "tool_error_count": 1,
        "api_call_count": 1,
        "finish_reasons": ["stop"],
        "final_error_kinds": ["nonzero_exit"]
      }
    }
  ],
  "representative_trace_id": "turn-abc123",
  "target_hints": [
    {"target_skill": "timeout-workflow", "confidence": "medium", "source": "proposal_cluster"}
  ]
}
```

---

## Determinism rules

- `cluster_id` is `sha256(group_key_items_sorted_concat)[:12]`. Same group key → same id, regardless of input order.
- `summary_id` is `sha256(sorted_cluster_ids_concat + unclustered_count + total_step_count)[:12]`.
- `index_id` is derived from summary id.
- Cluster ordering is: descending count, then alphabetical group key components.
- Representative trace id selection: first trace id by `(created_at, turn_id)` from the traces contributing to the cluster.
- Same input traces → same cluster ids, same ordering, same representative selection → byte-stable output.

---

## Relationship to current evidence system

The current `build_evidence_pack` and `_cluster_findings_from_events` produce cluster-based evidence items. Slice B does **not** replace these yet. Instead:

- Slice B adds a new pipeline: `turn traces → cluster summary → evidence index → evidence detail`.
- The new pipeline runs alongside the old one. Existing `build_evidence_pack` continues to produce the evidence pack that planner consumes today.
- In Slice C, planner will migrate from the old evidence-pack digest to the new index/detail model.
- During this slice, the new artifacts are written to `~/.hermes/self-improvement/clusters/` and verified for correctness/determinism, but **not yet consumed by the planner**.

---

## Task 1: Add failing tests for cluster summary building from turn traces

**Objective:** Lock the cluster summary contract and determinism rules before implementation.

**Files:**
- Create: `tests/test_cluster_summary.py`
- Modify: `hermes_self_improvement/evidence.py` (add stub if needed)

**Step 1: Write failing tests**

Cover at least:
- `build_cluster_summary(traces, config)` returns a cluster summary with correct schema.
- Two traces with the same `(tool_name, error_kind)` produce one cluster with count=2.
- Two traces with different error kinds produce two separate clusters.
- Clusters are ordered by descending count, then alphabetical key.
- `cluster_id` is deterministic: same group key always produces the same id.
- `representative_trace_ids` is a bounded list (max 3) sorted by `(created_at, turn_id)`.
- `severity` is computed from rate thresholds (low < 0.1, medium < 0.4, high >= 0.4).
- Empty traces list produces empty clusters with zero counts.
- Traces with no tool errors produce empty clusters with `unclustered_count` reflecting all steps.
- `target_hints` come from existing skill mapping when group key matches known workflow skills.

**Step 2: Run targeted tests to verify failure**

```bash
pytest tests/test_cluster_summary.py -q
```

Expected:
- All new tests fail because `build_cluster_summary` does not exist yet.

---

## Task 2: Implement cluster summary builder

**Objective:** Make the cluster summary tests pass.

**Files:**
- Modify: `hermes_self_improvement/evidence.py`

**Step 1: Implement `build_cluster_summary(traces, config)`**

The builder should:
- Accept a list of trace dicts (the turn trace artifacts from Slice A).
- Group steps by `(tool_name, error_kind)` where status is error or warning.
- Compute count, rate, severity, representative trace ids, and target hints per cluster.
- Produce a cluster summary dict matching the artifact contract above.
- Use deterministic id and ordering rules from this plan.

**Step 2: Re-run focused tests**

```bash
pytest tests/test_cluster_summary.py -q
```

Expected: all cluster summary tests pass.

---

## Task 3: Add failing tests for evidence index building from cluster summary

**Objective:** Lock the evidence index contract before implementation.

**Files:**
- Create/modify: `tests/test_cluster_summary.py` (or new `tests/test_evidence_index.py` if cleaner)

**Step 1: Write failing tests**

Cover at least:
- `build_evidence_index(cluster_summary, config)` returns an index with correct schema.
- Index entries correspond 1:1 with cluster summary clusters.
- `has_detail` is `True` for clusters with count >= 1.
- `target_skill` and `target_confidence` come from cluster `target_hints[0]` when available, else `None`.
- `unclustered_summary` correctly reflects traces not in any tool-error cluster.
- Deterministic ordering matches cluster summary ordering.
- Empty cluster summary produces empty entries.

**Step 2: Run targeted tests to verify failure**

```bash
pytest tests/test_evidence_index.py -q
```

---

## Task 4: Implement evidence index builder

**Objective:** Make the evidence index tests pass.

**Files:**
- Modify: `hermes_self_improvement/evidence.py`

**Step 1: Implement `build_evidence_index(cluster_summary, config)`**

The builder should:
- Accept a cluster summary dict.
- Produce one index entry per cluster.
- Populate `has_detail`, `target_skill`, `target_confidence` from cluster metadata.
- Produce an `unclustered_summary` for non-error traces.
- Follow deterministic ordering from the cluster summary.

**Step 2: Re-run focused tests**

```bash
pytest tests/test_evidence_index.py -q
```

---

## Task 5: Add failing tests for evidence detail from selected clusters

**Objective:** Lock the detail contract so planner can request drilldown for specific clusters.

**Files:**
- Create/modify: `tests/test_evidence_index.py` or new `tests/test_evidence_detail.py`

**Step 1: Write failing tests**

Cover at least:
- `build_evidence_detail(cluster_id, cluster_summary, traces, config)` returns a detail dict with correct schema.
- Only traces contributing to the specified cluster are included.
- Step previews are redacted and bounded.
- `representative_trace_id` matches the cluster's representative selection.
- Invalid / missing cluster_id returns empty detail with count=0.
- Detail is bounded: at most 5 traces, each with at most 10 steps.

**Step 2: Run targeted tests to verify failure**

---

## Task 6: Implement evidence detail builder

**Objective:** Make the evidence detail tests pass.

**Files:**
- Modify: `hermes_self_improvement/evidence.py`

**Step 1: Implement `build_evidence_detail(cluster_id, cluster_summary, traces, config)`**

The builder should:
- Accept a specific cluster id, the cluster summary, and the original traces.
- Filter traces to only those in the named cluster.
- Redact step previews (reuse existing redaction helpers).
- Bound the number of traces and steps per trace.
- Produce a detail dict matching the artifact contract.

**Step 2: Re-run focused tests**

---

## Task 7: Persist cluster summary, index, and detail as runtime artifacts

**Objective:** Write cluster summary and evidence index to disk on each `improve` run so later slices can consume them.

**Files:**
- Modify: `hermes_self_improvement/evidence.py` or new `hermes_self_improvement/cluster_artifacts.py`
- Modify: `hermes_self_improvement/cli.py` or `runner_steps.py` to call the new builders
- Modify: tests

**Step 1: Write failing tests**

Cover:
- `write_cluster_summary(summary, config)` writes to `~/.hermes/self-improvement/clusters/cluster-summary-<timestamp>.json`.
- `write_evidence_index(index, config)` writes to `~/.hermes/self-improvement/clusters/evidence-index-<timestamp>.json`.
- Files are valid JSON matching their respective schemas.
- `hermes self-improvement status` shows `cluster summaries: N / evidence indexes: N`.

**Step 2: Implement write helpers**

Add path helpers and atomic write (same pattern as trace persistence and run artifacts).

**Step 3: Wire into improve flow**

On `improve` (both dry-run and mutating), after building evidence pack, also:
1. Read turn traces from the trace directory for the current window.
2. Build cluster summary.
3. Build evidence index.
4. Persist both to disk.
5. Include cluster/index artifact paths in the run artifact.

**Step 4: Re-run focused + full tests**

```bash
pytest tests/test_cluster_summary.py tests/test_evidence_index.py tests/test_evidence_detail.py -q
pytest tests -q
```

---

## Task 8: Update status visibility and full regression

**Objective:** Make the new artifacts visible in `status` output and verify nothing regressed.

**Files:**
- Modify: `hermes_self_improvement/cli.py`
- Modify: tests

**Step 1: Add cluster/index counts to status output**

After existing trace count:
```
  turn traces: 7 / latest trace: traces/2026-05-26/turn-abc123.json
  cluster summaries: 3 / latest: clusters/cluster-summary-20260526T031316Z.json
  evidence indexes: 3 / latest: clusters/evidence-index-20260526T031316Z.json
```

**Step 2: Full regression**

```bash
python -m py_compile __init__.py hermes_self_improvement/*.py
python -m pytest tests -q
hermes self-improvement status
hermes self-improvement improve --dry-run --json
git diff --check
```

**Step 3: Update this plan, parent roadmap, and README index**

After regression passes, update:
- This plan's status field.
- `.hermes/plans/2026-05-26-turn-trace-and-readiness-followup.md` Slice B status.
- `.hermes/plans/2026-05-10-self-improvement-long-term-roadmap.md` progress.
- `.hermes/plans/README.md`.

---

## Exit criteria

- Re-running on the same trace set yields byte-stable cluster/index ids and ordering.
- CLI/report can point to cluster/index/detail artifacts.
- Planner-facing data can be built entirely from the new trace-derived artifacts (but planner does not yet consume them — that is Slice C).
- `build_evidence_pack` and the old event-derived flow continue to work unchanged.
- All existing tests pass, plus new cluster/index/detail tests.