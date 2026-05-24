# Built-in Memory Read Path Proof Plan

**Goal:** Prove whether `hermes-self-improvement` can replace its read-only built-in memory `§` parser with Hermes' official `MemoryStore`/current-entry source without changing mutation behavior.

## Scope

- Read-only proof first.
- No changes to real `USER.md` / `MEMORY.md`.
- No mutation behavior changes until equivalence tests pass.

## Questions

1. Can the official source expose structured entries equivalent to the current parser?
2. Does it preserve exact multi-line `old_text` for `replace`/`remove`?
3. Does it respect profiles, `get_hermes_home()`, and configured store files?
4. Can replay verify exact current state through the official source without direct file parsing?

## Acceptance criteria

- Fixture equivalence for single-line, multi-line, CJK, and compacted entries.
- Exact `old_text` survives round-trip.
- Profile/HERMES_HOME tests pass.
- Existing memory current-entry handoff, USER↔MEMORY move, and Memory→Skill replay tests still pass.

## Non-goals

- Do not remove the existing parser in this plan.
- Do not add a new memory lifecycle lane.
- Do not edit real memories.
