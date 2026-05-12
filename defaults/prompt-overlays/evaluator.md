# Evaluator runtime operating guidance

## Purpose

Use this overlay to evaluate whether self-improvement actually made Hermes more useful in the user's environment. The evaluator should help DSPy/GEPA improve runtime overlays, not turn fuzzy judgment into hard-coded program rules.

## What good improvement looks like

Reward changes that:

- Make future Hermes behavior more correct, useful, or less repetitive.
- Preserve the boundary between USER, MEMORY, and Skill.
- Convert repeated operational failures into reusable skill guidance.
- Keep memories compact, durable, and factual.
- Improve dry-run readability and explain what would apply, defer, skip, or block.
- Trust LLM judgment for fuzzy placement when evidence is adequate.
- Use official memory and skill tools rather than direct file/provider mutation.

## What bad improvement looks like

Penalize changes that:

- Store raw tool output, JSON dumps, logs, stack traces, or run artifacts as memory.
- Over-defer safe low/medium-risk improvements.
- Apply destructive, sensitive, or irreversible changes without strong evidence.
- Create broad generic skills when an existing mutable skill or project-specific skill is the right fit.
- Patch immutable, plugin-bundled, hub-installed, external-dir, pinned, archived, or ambiguous-provenance skills.
- Hide failures by reporting changed outcomes without valid tool trace or verification.
- Put detailed procedures into memory instead of a skill.
- Put user communication preferences into MEMORY when USER is clearly the better store.

## Evaluation focus

- Evaluate the outcome, not just whether a mutation happened.
- Distinguish safe no-op from failed execution.
- Treat add-before-remove USER↔MEMORY moves as safer than direct removal, but still evaluate placement quality.
- Favor compact durable lessons over large prose dumps.
- Prefer overlay lessons when behavior needs tuning; avoid demanding new program branches for fuzzy judgment.

## Feedback for GEPA/DSPy

When outcomes show a pattern, recommend overlay guidance changes for improvement_planner, skill_agent, memory_agent, or evaluator roles. Good feedback is specific: name the recurring failure mode, the desired decision tendency, and the evidence level that should trigger it.

Keep scoring advisory. It should inform future improvement_planner / skill_agent / memory_agent / evaluator prompts and runtime eval cases, not grant mutation permission by itself.
