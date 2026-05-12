from __future__ import annotations

import copy

from hermes_self_improvement.prompt_cache import apply_caching


def test_apply_caching_returns_cache_key_and_marks_system():
    messages = [
        {"role": "system", "content": "You are a planner."},
        {"role": "user", "content": "digest payload"},
    ]

    cached, extras = apply_caching(messages, site="planner")

    # Original messages must not be mutated.
    assert messages[0]["content"] == "You are a planner."
    assert messages[1]["content"] == "digest payload"

    # System content is converted to a block list with an ephemeral marker.
    sys_content = cached[0]["content"]
    assert isinstance(sys_content, list)
    assert sys_content[-1]["cache_control"] == {"type": "ephemeral"}
    assert sys_content[-1]["type"] == "text"
    assert sys_content[-1]["text"] == "You are a planner."

    # User content is left untouched.
    assert cached[1]["content"] == "digest payload"

    # Cache key embeds site + system signature + 'none' overlay slot.
    assert extras["prompt_cache_key"].startswith("self_improvement:planner:")
    parts = extras["prompt_cache_key"].split(":")
    assert parts[0] == "self_improvement"
    assert parts[1] == "planner"
    assert len(parts[2]) == 12  # system sha trim
    assert parts[3] == "none"


def test_apply_caching_includes_overlay_hash_when_provided():
    messages = [
        {"role": "system", "content": "Editor instructions"},
        {"role": "user", "content": "task brief"},
    ]

    _, extras_a = apply_caching(messages, site="skill_agent", overlay_hash="abc123def456ghi")
    _, extras_b = apply_caching(messages, site="skill_agent", overlay_hash="zzz999zzz999zzz")
    _, extras_none = apply_caching(messages, site="skill_agent")

    # Different overlay hashes produce different keys.
    assert extras_a["prompt_cache_key"] != extras_b["prompt_cache_key"]
    # Overlay-bearing keys differ from the "none" fallback.
    assert extras_a["prompt_cache_key"] != extras_none["prompt_cache_key"]
    # Overlay hash is truncated to 12 chars.
    assert extras_a["prompt_cache_key"].endswith(":abc123def456")


def test_apply_caching_handles_missing_system_message():
    messages = [{"role": "user", "content": "no system"}]

    cached, extras = apply_caching(messages, site="target_resolver")

    # Without system, content is preserved verbatim.
    assert cached == messages
    # Cache key still uses a 'nosys' marker slot.
    assert "self_improvement:target_resolver:nosys" in extras["prompt_cache_key"]


def test_apply_caching_keeps_existing_block_format():
    messages = [
        {"role": "system", "content": [{"type": "text", "text": "first"}, {"type": "text", "text": "second"}]},
        {"role": "user", "content": "u"},
    ]

    cached, _ = apply_caching(messages, site="planner")

    blocks = cached[0]["content"]
    assert [b["text"] for b in blocks] == ["first", "second"]
    # Marker lands on the last text block.
    assert "cache_control" not in blocks[0]
    assert blocks[1]["cache_control"] == {"type": "ephemeral"}


def test_apply_caching_is_pure_with_respect_to_input():
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
    ]
    snapshot = copy.deepcopy(messages)

    apply_caching(messages, site="planner")

    assert messages == snapshot


def test_apply_caching_system_signature_stability():
    msgs1 = [{"role": "system", "content": "abc"}, {"role": "user", "content": "x"}]
    msgs2 = [{"role": "system", "content": "abc"}, {"role": "user", "content": "y"}]
    msgs3 = [{"role": "system", "content": "abd"}, {"role": "user", "content": "x"}]

    _, e1 = apply_caching(msgs1, site="planner")
    _, e2 = apply_caching(msgs2, site="planner")
    _, e3 = apply_caching(msgs3, site="planner")

    # Same system → same key regardless of user content.
    assert e1["prompt_cache_key"] == e2["prompt_cache_key"]
    # Different system → different key.
    assert e1["prompt_cache_key"] != e3["prompt_cache_key"]


def test_apply_caching_extra_key_parts_change_scope():
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]

    _, base = apply_caching(messages, site="planner")
    _, tagged = apply_caching(messages, site="planner", extra_key_parts=["run42"])

    assert base["prompt_cache_key"] != tagged["prompt_cache_key"]
    assert tagged["prompt_cache_key"].endswith(":run42")
