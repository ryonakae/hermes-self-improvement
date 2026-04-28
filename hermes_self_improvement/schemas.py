from __future__ import annotations

STRING = {"type": "string"}
CONFIG_PATH_PROPERTY = {"type": "string", "description": "Explicit config JSON/YAML path; same precedence as CLI --config."}
BOOLEAN = {"type": "boolean"}
SCORER_PROPERTY = {"type": "string", "enum": ["heuristic", "llm", "gepa", "compare"], "default": "compare"}

SELF_IMPROVEMENT_STATUS_SCHEMA = {
    "name": "self_improvement_status",
    "description": "Show hermes-self-improvement plugin status. Read-only.",
    "parameters": {
        "type": "object",
        "properties": {"config_path": CONFIG_PATH_PROPERTY},
    },
}

SELF_IMPROVEMENT_REPORT_SCHEMA = {
    "name": "self_improvement_report",
    "description": "Generate a self-improvement analysis report. Read-only; does not mutate targets.",
    "parameters": {
        "type": "object",
        "properties": {
            "config_path": CONFIG_PATH_PROPERTY,
            "since_hours": {"type": "integer", "default": 24},
            "scorer": SCORER_PROPERTY,
        },
    },
}

SELF_IMPROVEMENT_IMPROVE_SCHEMA = {
    "name": "self_improvement_improve",
    "description": "Run the simplified self-improvement loop: calibrate, plan, apply preview/execute, and summarize.",
    "parameters": {
        "type": "object",
        "properties": {
            "config_path": CONFIG_PATH_PROPERTY,
            "since_hours": {"type": "integer", "default": 24},
            "scorer": SCORER_PROPERTY,
            "items": {"type": "array", "items": STRING, "description": "Optional plan item ids to apply after planning."},
            "execute": {"type": "boolean", "default": False},
        },
    },
}

SELF_IMPROVEMENT_CALIBRATE_SCHEMA = {
    "name": "self_improvement_calibrate",
    "description": "Preview or execute evaluator/scorer calibration. Mutates active evaluator state only when execute=true and regression passes.",
    "parameters": {
        "type": "object",
        "properties": {
            "config_path": CONFIG_PATH_PROPERTY,
            "execute": {"type": "boolean", "default": False},
        },
    },
}

SELF_IMPROVEMENT_PLAN_SCHEMA = {
    "name": "self_improvement_plan",
    "description": "Generate an ordered self-improvement plan artifact. Does not mutate targets.",
    "parameters": {
        "type": "object",
        "properties": {
            "config_path": CONFIG_PATH_PROPERTY,
            "since_hours": {"type": "integer", "default": 24},
            "scorer": SCORER_PROPERTY,
        },
    },
}

SELF_IMPROVEMENT_APPLY_SCHEMA = {
    "name": "self_improvement_apply",
    "description": "Preview or execute an ordered self-improvement plan. Hash and target drift checks are internal; execute=false is preview-only.",
    "parameters": {
        "type": "object",
        "properties": {
            "config_path": CONFIG_PATH_PROPERTY,
            "plan_id": STRING,
            "items": {"type": "array", "items": STRING, "description": "Optional plan item ids."},
            "execute": {"type": "boolean", "default": False},
        },
        "required": ["plan_id"],
    },
}

SELF_IMPROVEMENT_ROLLBACK_SCHEMA = {
    "name": "self_improvement_rollback",
    "description": "Preview or execute rollback for a self-improvement ledger. execute=false is preview-only.",
    "parameters": {
        "type": "object",
        "properties": {
            "config_path": CONFIG_PATH_PROPERTY,
            "ledger_id": STRING,
            "execute": {"type": "boolean", "default": False},
        },
        "required": ["ledger_id"],
    },
}

SELF_IMPROVEMENT_TOOL_SPECS = (
    ("self_improvement_status", SELF_IMPROVEMENT_STATUS_SCHEMA),
    ("self_improvement_report", SELF_IMPROVEMENT_REPORT_SCHEMA),
    ("self_improvement_improve", SELF_IMPROVEMENT_IMPROVE_SCHEMA),
    ("self_improvement_calibrate", SELF_IMPROVEMENT_CALIBRATE_SCHEMA),
    ("self_improvement_plan", SELF_IMPROVEMENT_PLAN_SCHEMA),
    ("self_improvement_apply", SELF_IMPROVEMENT_APPLY_SCHEMA),
    ("self_improvement_rollback", SELF_IMPROVEMENT_ROLLBACK_SCHEMA),
)
