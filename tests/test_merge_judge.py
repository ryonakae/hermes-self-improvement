from __future__ import annotations

import json

from hermes_self_improvement.verification import auxiliary_merge_judge, build_merge_judge, merge_judge_status


def _snap(name: str, content: str):
    return {"exists": True, "name": name, "file_set_hash": str(hash(content)), "skill_md": {"content": content}, "supporting_files": {}}


def test_merge_judge_parses_auxiliary_json_pass():
    result = auxiliary_merge_judge(
        source_before=_snap("source", "---\nname: source\n---\nsource guidance"),
        destination_before=_snap("dest", "---\nname: dest\n---\ndest guidance"),
        destination_after=_snap("dest", "---\nname: dest\n---\ndest guidance\nsource guidance"),
        agent_result={"merged_points": ["source guidance"]},
        llm_call=lambda messages, **kwargs: json.dumps({
            "passed": True,
            "source_information_preserved": True,
            "no_obvious_contradictions": True,
            "no_major_duplicate_guidance": True,
            "safe_to_delete_source": True,
            "reasons": [],
        }),
    )
    assert result["passed"] is True
    assert result["source"] == "hermes_auxiliary"


def test_merge_judge_rejects_malformed_json():
    result = auxiliary_merge_judge(source_before={}, destination_before={}, destination_after={}, agent_result={}, llm_call=lambda messages, **kwargs: "nope")
    assert result["passed"] is False
    assert "merge_judge_malformed_json" in result["reasons"]


def test_merge_judge_requires_safe_to_delete_source():
    result = auxiliary_merge_judge(
        source_before={}, destination_before={}, destination_after={}, agent_result={},
        llm_call=lambda messages, **kwargs: json.dumps({
            "passed": True,
            "source_information_preserved": True,
            "no_obvious_contradictions": True,
            "no_major_duplicate_guidance": True,
            "safe_to_delete_source": False,
            "reasons": [],
        }),
    )
    assert result["passed"] is False
    assert "merge_judge_not_safe_to_delete_source" in result["reasons"]


def test_merge_judge_fails_closed_on_llm_exception():
    def boom(messages, **kwargs):
        raise RuntimeError("boom")
    result = auxiliary_merge_judge(source_before={}, destination_before={}, destination_after={}, agent_result={}, llm_call=boom)
    assert result["passed"] is False
    assert "merge_judge_llm_failed" in result["reasons"]


def test_merge_judge_uses_configured_mutation_model():
    seen = {}
    def fake(messages, **kwargs):
        seen.update(kwargs)
        return json.dumps({
            "passed": True,
            "source_information_preserved": True,
            "no_obvious_contradictions": True,
            "no_major_duplicate_guidance": True,
            "safe_to_delete_source": True,
            "reasons": [],
        })
    config = {"model": {"mutation": {"timeout": 12, "max_tokens": 345}}}
    result = build_merge_judge(config=config, llm_call=fake)(source_before={}, destination_before={}, destination_after={}, agent_result={})
    assert result["passed"] is True
    assert seen["timeout"] == 12
    assert seen["max_tokens"] == 345


def test_merge_judge_status_reports_injected():
    assert merge_judge_status({"_merge_judge": lambda **kwargs: {"passed": True}}) == {"available": True, "source": "injected"}
