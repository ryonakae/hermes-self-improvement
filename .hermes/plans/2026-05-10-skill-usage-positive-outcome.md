# Skill usage positive outcome

## Status

implemented

## Parent roadmap

`2026-05-10-self-improvement-long-term-roadmap.md` — Milestone 5 / 7.

## Goal

Skill mutations should receive cautious positive outcome evidence when the same skill is later intentionally viewed/loaded successfully without an adjacent correction. This adds a real later-use signal distinct from immediate post-validation and quiet-window silence.

## Non-goals

- Do not treat every successful `skill_view` as strong proof of improvement.
- Do not use `skills_list` as positive usage; listing is too broad.
- Do not change evidence-pack filtering that ignores successful skill usage as redundant low-signal evidence.

## Implementation plan

1. Add a small parser for successful `skill_view` events that extracts `name` from `args_preview` when it is a dict/JSON-like payload.
2. Add an outcome collector that links later successful `skill_view(name=<target_id>)` events to prior executed skill mutation episodes.
3. Emit a weak positive observation, e.g. `skill_used_after_mutation`, only when event time is after episode time and inside the collection window.
4. Include the new collector in `run_outcome_prepass` and signal counts.
5. Add focused tests proving:
   - matching skill usage creates a weak positive observation;
   - pre-mutation usage and unrelated skill usage do not count.
6. Update roadmap and index after validation.

## Verification

- `python -m pytest tests/test_outcome_observer.py::test_collect_skill_usage_observations_attributes_weak_positive_to_prior_skill_mutation tests/test_outcome_observer.py::test_collect_skill_usage_observations_ignores_unrelated_and_pre_mutation_usage -q` — 2 passed.
- `python -m pytest tests/test_outcome_observer.py -q` — 22 passed.
- Full-suite / py_compile / diff-check results are recorded in the session summary after commit.

