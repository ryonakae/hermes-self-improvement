from __future__ import annotations

from hermes_self_improvement.autonomous_policy import build_autonomous_operation_policy, summarize_autonomous_operation_policy
from hermes_self_improvement.config import load_config


def test_default_autonomous_policy_matches_closed_loop_boundaries():
    policy = build_autonomous_operation_policy({})

    assert policy["enabled"] is True
    assert policy["calibrate"]["mutation_capable"] is True
    assert policy["calibrate"]["allowed_mutations"] == ["prompt_pointer_update", "evaluator_pointer_update"]
    assert policy["calibrate"]["requires_autonomous_evaluator_decision"] == "promote"
    assert policy["improve"]["mutation_capable"] is True
    assert policy["improve"]["allowed_skill_targets"] == ["local_mutable_active", "local_mutable_stale"]
    assert policy["improve"]["allowed_skill_lifecycle_actions"] == ["archive"]
    assert policy["improve"]["skill_archive_requires"] == [
        "local_mutable_active_or_stale",
        "not_pinned",
        "not_archived",
        "not_bundled_hub_external_builtin",
        "archive_evidence_attached",
        "no_blocking_active_references",
        "tool_mediated_lifecycle_transition",
    ]
    assert policy["improve"]["allowed_memory_operations"] == ["builtin_user", "builtin_memory", "external_memory"]
    assert policy["defer"]["records_episode"] is True


def test_legacy_automation_policy_is_ignored_by_config_normalization(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
automation_policy:
  enabled: false
  allowed_target_kinds: [runtime_config, arbitrary_docs]
  allow_destructive: true
self_improvement:
  autonomous:
    enabled: false
""".strip()
        + "\n",
        encoding="utf-8",
    )

    config = load_config(default_path=config_path)
    policy = build_autonomous_operation_policy(config)

    assert "automation_policy" not in config
    assert "self_improvement" not in config
    assert policy["enabled"] is True
    assert "runtime_config" not in policy["improve"]["allowed_target_kinds"]
    assert policy["improve"]["destructive_changes_allowed"] is False


def test_policy_summary_is_compact_and_contains_no_prompt_text():
    policy = build_autonomous_operation_policy({})
    summary = summarize_autonomous_operation_policy(policy)

    assert summary == {
        "enabled": True,
        "calibrate_mutation_capable": True,
        "calibrate_requires": "autonomous_evaluator_promote",
        "improve_mutation_capable": True,
        "improve_skill_targets": ["local_mutable_active", "local_mutable_stale"],
        "improve_skill_lifecycle_actions": ["archive"],
        "defer_executes_mutation": False,
    }
