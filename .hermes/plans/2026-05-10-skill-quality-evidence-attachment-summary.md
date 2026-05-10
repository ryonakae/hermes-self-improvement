# Skill quality evidence attachment summary

## Status

Implemented.

## Why

The roadmap still lists evidence alignment as a weak part of the skill quality evaluator. Current summaries can explain whether a skill has frontmatter, pitfalls, verification, triggers, and concrete steps, but they do not show whether the accepted mutation was tied to concrete attached evidence.

## Goal

Carry compact attached-evidence counts from planner/runner decisions into skill-quality summaries and mark accepted skill mutations with zero attached evidence as follow-up candidates.

## Scope

- Preserve `attached_evidence_count` on skill runner decisions for create and patch/edit paths.
- Preserve a bounded `missing_evidence_id_count` for diagnostics.
- In skill-quality summaries, treat `attached_evidence_count == 0` as `needs_patch` / `missing_attached_evidence` when the field is present.
- Keep old artifacts compatible by not penalizing decisions that lack this new field.
- Update CLI and report integration tests.
- Update roadmap and plan index after verification.

## Verification

- `python -m pytest tests/test_cli_surface.py tests/test_runner_steps.py tests/test_report_integration.py -q` → 72 passed.
- `python -m py_compile __init__.py hermes_self_improvement/*.py` → passed.
- Full `python -m pytest -q` → 584 passed, 2 skipped.
- `git diff --check` → passed.
