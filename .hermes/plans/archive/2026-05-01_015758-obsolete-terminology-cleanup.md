# Obsolete terminology cleanup

## Status

Completed and archived. This follow-up canonicalized unattended mutation/scorer/restore/historical-reader terminology without reviving the removed `plan / apply / rollback / outcome` primary surface.

## Goal

Make current self-improvement internals and docs use Curator-aligned vocabulary after the legacy apply/rollback cleanup:

- Canonicalize `apply_policy` to a current unattended mutation policy name with no legacy input fallback.
- Rename scorer recommendation value `review_for_possible_low_risk_apply` away from apply-era wording.
- Rename calibration rollback internals to previous-evaluator restore terminology without writing or reading obsolete rollback metadata keys.
- Rename historical apply-preview next-action reader helpers so their purpose is audit/report compatibility, not an active apply flow.

## Non-goals

- Do not add any primary commands, tools, flags, or schemas.
- Do not change the four-tool surface.
- Do not direct-edit runtime memory/skill stores.
- Do not delete archived historical plans only because they contain old terms.

## Proposed slices

### Slice 1: Plan index hygiene

- Mark `2026-05-01_011409-obsolete-internal-legacy-cleanup.md` as completed/archived.
- Update `.hermes/plans/README.md` so this plan is the only active follow-up.

### Slice 2: Canonical unattended mutation policy vocabulary

- Rename defaults/helpers from apply policy to automation/mutation-safe vocabulary.
- Prefer a new config key such as `automation_policy` as canonical.
- Use only `automation_policy`; do not support the obsolete `apply_policy` input key.
- Update example config and tests.

### Slice 3: Scorer recommendation vocabulary

- Replace `review_for_possible_low_risk_apply` with a current value such as `review_low_risk_candidate`.
- Update eval rubric, scorer, DSPy, calibration expected cases, and tests.
- Historical archived plans may keep old strings.

### Slice 4: Calibration restore vocabulary

- Rename `rollback_calibration()` to `restore_previous_calibration()`.
- Rename calibration ledger metadata from obsolete rollback wording to `restore_data`.
- Do not read or write old `rollback_data` keys; this is unreleased, so current schema wins.
- Keep this internal; do not add a primary rollback command.

### Slice 5: Historical reader helper naming

- Rename `build_next_actions_for_apply_preview()` to a historical-artifact oriented name.
- Keep report/CLI behavior pointing users back to `improve`, `calibrate`, `report`, and `status` only.
- Update tests.

## Verification

Run after each focused slice where useful, then final:

```bash
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest tests -q
$PY -m py_compile __init__.py hermes_self_improvement/*.py tests/*.py
bin/hermes-self-improve status
bin/hermes-self-improve improve --dry-run
bin/hermes-self-improve calibrate --dry-run
bin/hermes-self-improve report --since-hours 24
```

Also verify plugin discovery still exposes exactly four tools.
