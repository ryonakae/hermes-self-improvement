# Skill patch intended-change verification

**Status:** implemented.

## Why

The roadmap still had a gap in Milestone 1: skill `patch` / `edit` mutations were readable after mutation, but post-validation did not verify that the intended text actually appeared in the readback content. A tool trace could say `skill_manage(action="patch")` succeeded while the final skill content did not contain the new guidance.

## Scope

Keep the existing native skill-tool editor harness and official `skill_view` readback. Do not add a new lane or direct filesystem checks.

## Implemented behavior

- Preserve compact mutation intent from successful `skill_manage` trace entries:
  - `action`
  - `name`
  - bounded `old_string` / `new_string` / `content` when present
- During skill post-validation for `skill_improve`:
  - For `patch`, require the traced `new_string` to be present in `skill_view` readback content.
  - For `edit`, require the traced full `content` to match the readback content after trimming surrounding whitespace.
  - If expected text is unavailable, keep the check as unknown rather than failing a valid readback.
- If intended-change verification fails, return `mutation_agent_post_validation_failed` with compact diagnostics:
  - `intended_change_verified: false`
  - `intended_change_check: patch_new_string_missing` or `edit_content_mismatch`
  - `intended_change_chars`

## Verification

- Added RED tests first:
  - `test_native_backend_post_validates_patch_intended_new_text`
  - `test_native_backend_rejects_patch_when_new_text_missing_after_readback`
- Focused tests pass after implementation.
- Full suite and syntax checks were run before commit.

## Result

This closes the roadmap’s “post-patch intended-change verification beyond readability” gap for native skill mutations, while keeping direct mutation boundaries unchanged.
