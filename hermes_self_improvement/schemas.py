from __future__ import annotations

MODE_PROPERTY = {
    "type": "string",
    "enum": ["report_only", "dry_run_plan", "apply_low_risk", "apply_approved"],
    "description": "Execution mode checked by the plugin policy gate before the tool does any work.",
}

STRING = {"type": "string"}
CONFIG_PATH_PROPERTY = {"type": "string", "description": "Explicit config JSON path; same precedence as CLI --config."}
BOOLEAN = {"type": "boolean"}
INTEGER = {"type": "integer"}

SELF_IMPROVEMENT_STATUS_SCHEMA = {
    "name": "self_improvement_status",
    "description": "Show hermes-self-improvement plugin status. Read-only.",
    "parameters": {
        "type": "object",
        "properties": {"mode": MODE_PROPERTY, "config_path": CONFIG_PATH_PROPERTY},
    },
}

SELF_IMPROVEMENT_GENERATE_APPLY_PLAN_SCHEMA = {
    "name": "self_improvement_generate_apply_plan",
    "description": "Generate a dry-run apply plan artifact. Does not mutate target files; requires dry_run_plan mode.",
    "parameters": {
        "type": "object",
        "properties": {
            "mode": MODE_PROPERTY,
            "config_path": CONFIG_PATH_PROPERTY,
            "since_hours": {"type": "integer", "default": 24},
            "scorer": {"type": "string", "enum": ["heuristic", "llm", "gepa", "compare"], "default": "heuristic"},
        },
    },
}

SELF_IMPROVEMENT_LEDGER_REPORT_SCHEMA = {
    "name": "self_improvement_ledger_report",
    "description": "Summarize low-risk apply ledgers for human review. Read-only.",
    "parameters": {
        "type": "object",
        "properties": {
            "mode": MODE_PROPERTY,
            "config_path": CONFIG_PATH_PROPERTY,
            "status": {"type": "string", "enum": ["all", "pending", "applied", "rolled_back", "failed", "rejected"], "default": "applied"},
            "limit": {"type": "integer", "default": 20},
        },
    },
}

SELF_IMPROVEMENT_APPROVAL_REPORT_SCHEMA = {
    "name": "self_improvement_approval_report",
    "description": "Summarize approval artifacts and validation status. Read-only.",
    "parameters": {
        "type": "object",
        "properties": {
            "mode": MODE_PROPERTY,
            "config_path": CONFIG_PATH_PROPERTY,
            "status": {"type": "string", "enum": ["all", "approved", "rejected", "valid"], "default": "all"},
            "limit": {"type": "integer", "default": 20},
            "include_previews": {"type": "boolean", "default": False, "description": "Include non-mutating apply-approved preview status for each approval."},
        },
    },
}

SELF_IMPROVEMENT_RETENTION_REPORT_SCHEMA = {
    "name": "self_improvement_retention_report",
    "description": "Preview old self-improvement artifacts that are past retention. Read-only; does not delete or prune files.",
    "parameters": {
        "type": "object",
        "properties": {
            "mode": MODE_PROPERTY,
            "config_path": CONFIG_PATH_PROPERTY,
            "limit": {"type": "integer", "default": 20},
            "retention_days": {"type": "integer"},
            "category": {"type": "string", "enum": ["all", "apply-plans", "ledgers", "apply-attempts", "approvals"], "default": "all"},
        },
    },
}

SELF_IMPROVEMENT_RETENTION_PRUNE_SCHEMA = {
    "name": "self_improvement_retention_prune",
    "description": "Preview or explicitly prune expired self-improvement artifacts. Actual deletion requires apply_approved mode, confirm_prune=true, and matching expected_artifact_list_hash.",
    "parameters": {
        "type": "object",
        "properties": {
            "mode": MODE_PROPERTY,
            "config_path": CONFIG_PATH_PROPERTY,
            "limit": {"type": "integer", "default": 20},
            "retention_days": {"type": "integer"},
            "category": {"type": "string", "enum": ["all", "apply-plans", "ledgers", "apply-attempts", "approvals"], "default": "all"},
            "confirm_prune": BOOLEAN,
            "expected_artifact_list_hash": STRING,
        },
    },
}

SELF_IMPROVEMENT_VALIDATE_APPROVAL_SCHEMA = {
    "name": "self_improvement_validate_approval",
    "description": "Validate one approval artifact against its hash, expiry, current plan, current item, change type, and target path. Read-only.",
    "parameters": {
        "type": "object",
        "properties": {
            "mode": MODE_PROPERTY,
            "config_path": CONFIG_PATH_PROPERTY,
            "approval_id": STRING,
        },
        "required": ["approval_id"],
    },
}

SELF_IMPROVEMENT_APPROVE_SCHEMA = {
    "name": "self_improvement_approve",
    "description": "Create a non-mutating approval artifact for one apply-plan item. Requires apply_approved mode.",
    "parameters": {
        "type": "object",
        "properties": {
            "mode": MODE_PROPERTY,
            "config_path": CONFIG_PATH_PROPERTY,
            "plan_id": STRING,
            "item_id": STRING,
            "approver_source": {"type": "string", "default": "manual_tool"},
            "ttl_hours": {"type": "integer", "default": 24},
        },
        "required": ["plan_id", "item_id"],
    },
}


SELF_IMPROVEMENT_APPLY_APPROVED_SCHEMA = {
    "name": "self_improvement_apply_approved",
    "description": "Validate and preview one approved apply artifact. Actual mutation requires apply_approved mode, confirm_approved_apply=true, expected_approval_hash, and expected_target_hash.",
    "parameters": {
        "type": "object",
        "properties": {
            "mode": MODE_PROPERTY,
            "config_path": CONFIG_PATH_PROPERTY,
            "approval_id": STRING,
            "confirm_approved_apply": BOOLEAN,
            "expected_approval_hash": STRING,
            "expected_target_hash": STRING,
        },
        "required": ["approval_id"],
    },
}

SELF_IMPROVEMENT_APPLY_LOW_RISK_SCHEMA = {
    "name": "self_improvement_apply_low_risk",
    "description": "Preview or explicitly apply one low-risk apply-plan item. Actual mutation requires apply_low_risk mode, confirm_apply=true, and matching expected_item_hash.",
    "parameters": {
        "type": "object",
        "properties": {
            "mode": MODE_PROPERTY,
            "config_path": CONFIG_PATH_PROPERTY,
            "plan_id": STRING,
            "item_id": STRING,
            "confirm_apply": BOOLEAN,
            "expected_item_hash": STRING,
        },
        "required": ["plan_id", "item_id"],
    },
}

SELF_IMPROVEMENT_ROLLBACK_LOW_RISK_SCHEMA = {
    "name": "self_improvement_rollback_low_risk",
    "description": "Preview or explicitly rollback one applied low-risk ledger. Actual rollback requires apply_low_risk mode, confirm_rollback=true, and matching expected_ledger_hash.",
    "parameters": {
        "type": "object",
        "properties": {
            "mode": MODE_PROPERTY,
            "config_path": CONFIG_PATH_PROPERTY,
            "ledger_id": STRING,
            "confirm_rollback": BOOLEAN,
            "expected_ledger_hash": STRING,
        },
        "required": ["ledger_id"],
    },
}

SELF_IMPROVEMENT_TOOL_SPECS = (
    ("self_improvement_status", SELF_IMPROVEMENT_STATUS_SCHEMA),
    ("self_improvement_generate_apply_plan", SELF_IMPROVEMENT_GENERATE_APPLY_PLAN_SCHEMA),
    ("self_improvement_ledger_report", SELF_IMPROVEMENT_LEDGER_REPORT_SCHEMA),
    ("self_improvement_approval_report", SELF_IMPROVEMENT_APPROVAL_REPORT_SCHEMA),
    ("self_improvement_validate_approval", SELF_IMPROVEMENT_VALIDATE_APPROVAL_SCHEMA),
    ("self_improvement_retention_report", SELF_IMPROVEMENT_RETENTION_REPORT_SCHEMA),
    ("self_improvement_retention_prune", SELF_IMPROVEMENT_RETENTION_PRUNE_SCHEMA),
    ("self_improvement_approve", SELF_IMPROVEMENT_APPROVE_SCHEMA),
    ("self_improvement_apply_approved", SELF_IMPROVEMENT_APPLY_APPROVED_SCHEMA),
    ("self_improvement_apply_low_risk", SELF_IMPROVEMENT_APPLY_LOW_RISK_SCHEMA),
    ("self_improvement_rollback_low_risk", SELF_IMPROVEMENT_ROLLBACK_LOW_RISK_SCHEMA),
)
