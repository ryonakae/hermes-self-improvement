# Skill quality weak-positive outcome status

**Status:** implemented.

## Why

After weighting validation outcomes, a thin but readable skill gets a small positive score (`0.05`). The current outcome status classifier treats any positive score as `improved`, which overstates weak post-validation evidence. A skill that needs patch should remain under observation until stronger later evidence appears.

## Scope

Small credit-assignment slice:

- keep deterministic score components unchanged;
- adjust outcome status classification so weak quality-positive validation is not called `improved`;
- leave stronger positive signals and negative/regressed signals intact.

## Desired behavior

- `score > 0` with `skill_quality_needs_patch_penalty` and no stronger later positive evidence -> `unknown`.
- normal positive score without quality penalty -> `improved`.
- `score < 0` with too-generic/memory-shaped penalty -> `regressed`.

## Verification

- Added focused tests in `test_credit_assignment.py` for thin skill status remaining unknown.
- Full suite, py_compile, and diff check were run before commit.
