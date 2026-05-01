from __future__ import annotations

from hermes_self_improvement.memory_context import build_related_memory_lookup_context


def test_hindsight_related_memory_lookup_uses_injected_recall_tool():
    calls = []

    def recall(query):
        calls.append(query)
        return {"memories": [{"content": "User prefers concise summaries."}]}

    result = build_related_memory_lookup_context(
        provider="hindsight",
        evidence=[{"kind": "correction_evidence", "event": {"message": "Actually, keep summaries short."}}],
        lookup_fn=recall,
    )

    assert result["status"] == "completed"
    assert result["provider"] == "hindsight"
    assert calls == [result["query"]]
    assert result["result_count"] == 1


def test_related_memory_lookup_unavailable_for_provider_without_search():
    result = build_related_memory_lookup_context(
        provider="built-in",
        evidence=[{"kind": "correction_evidence", "event": {"message": "wrong memory"}}],
    )

    assert result["status"] == "unavailable"
    assert result["reason"] == "memory_lookup_unavailable"


def test_related_memory_lookup_redacts_secret_like_query_text():
    calls = []

    def recall(query):
        calls.append(query)
        return []

    result = build_related_memory_lookup_context(
        provider="hindsight",
        evidence=[{"kind": "correction_evidence", "event": {"message": "token sk-1234567890abcdef should not persist"}}],
        lookup_fn=recall,
    )

    assert result["status"] == "completed"
    assert "sk-1234567890abcdef" not in result["query"]
    assert "[REDACTED]" in result["query"]
