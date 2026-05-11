from __future__ import annotations

STRING = {"type": "string"}
CONFIG_PATH_PROPERTY = {"type": "string", "description": "Explicit config YAML path; same precedence as CLI --config."}

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
            "dry_run": {"type": "boolean", "default": False},
        },
    },
}

SELF_IMPROVEMENT_CALIBRATE_SCHEMA = {
    "name": "self_improvement_calibrate",
    "description": "Calibrate evaluator prompts/rubrics. Mutates active evaluator state by default when gates pass; dry_run=true previews.",
    "parameters": {
        "type": "object",
        "properties": {
            "config_path": CONFIG_PATH_PROPERTY,
            "dry_run": {"type": "boolean", "default": False},
            "candidate_set_artifact_path": {"type": "string", "description": "Optional explicit dry-run overlay candidate-set artifact path to reuse during execute mode."},
        },
    },
}

SELF_IMPROVEMENT_TOOL_SPECS = (
    ("self_improvement_status", SELF_IMPROVEMENT_STATUS_SCHEMA),
    ("self_improvement_report", SELF_IMPROVEMENT_REPORT_SCHEMA),
    ("self_improvement_improve", SELF_IMPROVEMENT_IMPROVE_SCHEMA),
    ("self_improvement_calibrate", SELF_IMPROVEMENT_CALIBRATE_SCHEMA),
)
