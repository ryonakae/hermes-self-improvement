from __future__ import annotations

STRING = {"type": "string"}
CONFIG_PATH_PROPERTY = {"type": "string", "description": "Explicit config YAML path; same precedence as CLI --config."}
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
    "description": "Run self-improvement. Mutates by default; dry_run=true previews without mutation.",
    "parameters": {
        "type": "object",
        "properties": {
            "config_path": CONFIG_PATH_PROPERTY,
            "since_hours": {"type": "integer", "default": 24},
            "scorer": SCORER_PROPERTY,
            "dry_run": {"type": "boolean", "default": False},
        },
    },
}

SELF_IMPROVEMENT_CALIBRATE_SCHEMA = {
    "name": "self_improvement_calibrate",
    "description": "Calibrate evaluator/scorer. Mutates active evaluator state by default when gates pass; dry_run=true previews.",
    "parameters": {
        "type": "object",
        "properties": {
            "config_path": CONFIG_PATH_PROPERTY,
            "dry_run": {"type": "boolean", "default": False},
        },
    },
}

SELF_IMPROVEMENT_TOOL_SPECS = (
    ("self_improvement_status", SELF_IMPROVEMENT_STATUS_SCHEMA),
    ("self_improvement_report", SELF_IMPROVEMENT_REPORT_SCHEMA),
    ("self_improvement_improve", SELF_IMPROVEMENT_IMPROVE_SCHEMA),
    ("self_improvement_calibrate", SELF_IMPROVEMENT_CALIBRATE_SCHEMA),
)
