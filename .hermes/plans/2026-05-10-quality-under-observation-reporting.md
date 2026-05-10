# Quality under-observation reporting

**Status:** implemented.

## Why

Thin skills with weak-positive validation now classify as `unknown` instead of `improved`, but summaries still only say “unknown”. That hides the important distinction between ordinary unknown outcomes and skills intentionally held under observation because they need patch/quality improvement.

## Scope

Small reporting/credit slice:

- count quality-related under-observation episodes in credit assignment compact summary;
- show the count in `Outcomes:` summary when present;
- do not change scoring or mutation policy.

## Desired behavior

- `compact_credit_assignment_summary()` exposes `quality_under_observation`.
- CLI `Outcomes:` includes a line such as `quality under observation: 1`.
- This count is driven by quality penalty components, not by generic unknown status alone.

## Verification

- Added focused tests in `test_credit_assignment.py` and `test_cli_surface.py`.
- Full suite, py_compile, and diff check were run before commit.
