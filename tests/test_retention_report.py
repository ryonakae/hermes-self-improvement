from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
PLUGIN_INIT = PLUGIN_DIR / "__init__.py"
CLI = PLUGIN_DIR / "bin" / "hermes-self-improve"


def load_plugin_module():
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_retention_report_under_test", PLUGIN_INIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def seed_artifacts(tmp_path: Path):
    reports = tmp_path / "reports"
    write_json(reports / "apply-plans" / "2026-03-01" / "old-plan.json", {
        "schema_name": "self_improvement_apply_plan",
        "plan_id": "old-plan",
        "created_at": "2026-03-01T00:00:00+00:00",
    })
    write_json(reports / "apply-plans" / "2026-04-20" / "recent-plan.json", {
        "schema_name": "self_improvement_apply_plan",
        "plan_id": "recent-plan",
        "created_at": "2026-04-20T00:00:00+00:00",
    })
    write_json(reports / "ledgers" / "2026-03-02" / "old-ledger.json", {
        "schema_name": "self_improvement_apply_ledger",
        "ledger_id": "old-ledger",
        "created_at": "2026-03-02T00:00:00+00:00",
        "current_status": "applied",
    })
    write_json(reports / "approvals" / "2026-03-01" / "old-approval.json", {
        "schema_name": "self_improvement_approval",
        "approval_id": "old-approval",
        "created_at": "2026-03-01T00:00:00+00:00",
        "current_status": "approved",
    })
    write_json(reports / "apply-attempts" / "2026-04-27" / "recent-attempt.json", {
        "schema_name": "self_improvement_apply_attempt",
        "attempt_id": "recent-attempt",
        "created_at": "2026-04-27T00:00:00+00:00",
        "current_status": "would_apply_low_risk",
    })
    (reports / "ledgers" / "2026-03-03" / "malformed.json").parent.mkdir(parents=True, exist_ok=True)
    (reports / "ledgers" / "2026-03-03" / "malformed.json").write_text("{not json\n", encoding="utf-8")
    return {"reports_dir": str(reports), "retention_days": 30}


def test_build_retention_report_payload_is_read_only_and_marks_expired_candidates(tmp_path):
    mod = load_plugin_module()
    config = seed_artifacts(tmp_path)

    payload = mod.build_retention_report_payload(
        config=config,
        now=datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc),
        limit=10,
    )

    assert payload["schema_name"] == "self_improvement_retention_report"
    assert payload["target_changed"] is False
    assert payload["retention_days"] == 30
    assert payload["cutoff_at"] == "2026-03-28T12:00:00+00:00"
    assert payload["total_files"] == 6
    assert payload["expired_candidate_count"] == 3
    assert payload["malformed_count"] == 1
    assert payload["category_filter"] == "all"
    assert set(payload["categories"]) >= {"apply-plans", "ledgers", "apply-attempts", "approvals"}
    assert payload["malformed_artifacts"][0]["category"] == "ledgers"
    assert payload["malformed_artifacts"][0]["error"] == "malformed_json"
    assert payload["legacy_artifact_count"] == 2
    assert set(payload["legacy_categories"]) == {"apply-attempts", "approvals"}
    assert payload["cleanup_policy"] == {
        "primary_surface": "read_only_report_only",
        "automatic_prune": False,
        "manual_cleanup_required": True,
        "reason": "retention cleanup is intentionally not exposed as CLI or plugin tool surface",
    }
    expired_ids = {item.get("artifact_id") for item in payload["expired_candidates"]}
    assert {"old-plan", "old-ledger", "old-approval"} <= expired_ids
    assert "recent-plan" not in expired_ids
    assert not any(not Path(item["path"]).exists() for item in payload["expired_candidates"])


def test_retention_report_supports_category_filter_and_malformed_details(tmp_path):
    mod = load_plugin_module()
    config = seed_artifacts(tmp_path)

    payload = mod.build_retention_report_payload(
        config=config,
        now=datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc),
        category="ledgers",
        limit=10,
    )

    assert payload["category_filter"] == "ledgers"
    assert set(payload["categories"]) == {"ledgers"}
    assert payload["total_files"] == 2
    assert payload["expired_candidate_count"] == 1
    assert payload["expired_candidates"][0]["artifact_id"] == "old-ledger"
    assert payload["malformed_count"] == 1
    assert payload["malformed_artifacts"][0]["path"].endswith("malformed.json")


def test_retention_report_rejects_unknown_category_without_scanning(tmp_path):
    mod = load_plugin_module()
    config = seed_artifacts(tmp_path)

    payload = mod.build_retention_report_payload(
        config=config,
        now=datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc),
        category="unknown",
    )

    assert payload["current_status"] == "rejected"
    assert payload["target_changed"] is False
    assert payload["expired_candidate_count"] == 0
    assert payload["malformed_count"] == 0
    assert "unknown_category" in payload["reasons"]


def test_render_retention_report_includes_preview_not_deletion_language(tmp_path):
    mod = load_plugin_module()
    config = seed_artifacts(tmp_path)
    payload = mod.build_retention_report_payload(
        config=config,
        now=datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc),
        limit=3,
    )

    rendered = mod.render_retention_report(payload)

    assert "# Hermes self-improvement retention report" in rendered
    assert "expired candidates: 3" in rendered
    assert "read-only preview" in rendered
    assert "old-ledger" in rendered
    assert "malformed artifacts" in rendered.lower()
    assert "malformed.json" in rendered
    assert "legacy artifacts: 2" in rendered
    assert "Legacy artifacts" in rendered
    assert "apply-attempts" in rendered
    assert "cleanup" in rendered.lower()
    assert "delete" not in rendered.lower()
    assert "automatic prune" not in rendered.lower()


def test_retention_report_cli_is_removed_from_primary_surface(tmp_path):
    config = seed_artifacts(tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    completed = subprocess.run(
        [str(CLI), "retention-report", "--mode", "report_only", "--config", str(config_path), "--json", "--limit", "5", "--category", "ledgers"],
        cwd=str(PLUGIN_DIR),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 2
    assert "invalid choice" in completed.stderr

def test_plugin_does_not_register_retention_report_in_primary_tool_surface():
    mod = load_plugin_module()

    class Ctx:
        def __init__(self):
            self.tools = []
            self.hooks = []
            self.commands = []
            self.skills = []

        def register_tool(self, **kwargs):
            self.tools.append(kwargs)

        def register_hook(self, name, callback):
            self.hooks.append((name, callback))

        def register_cli_command(self, *args, **kwargs):
            self.commands.append((args, kwargs))

        def register_command(self, *args, **kwargs):
            self.commands.append((args, kwargs))

        def register_skill(self, *args, **kwargs):
            self.skills.append((args, kwargs))

    ctx = Ctx()
    mod.register(ctx)

    names = {tool["name"] for tool in ctx.tools}
    assert "self_improvement_retention_report" not in names
    assert len([name for name in names if name.startswith("self_improvement_")]) == 7
