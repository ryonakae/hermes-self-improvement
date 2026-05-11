from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from .config import get_hermes_home
from .observer import _redact_text
from .prompts import SKILL_MEMORY_CLASSIFICATION_BLOCK


def score_proposals_impl(
    proposals: list[dict[str, Any]],
    findings: list[dict[str, Any]] | None = None,
    *,
    scorer: str = "heuristic",
    config: dict[str, Any] | None = None,
    llm_scorer_func=None,
) -> list[dict[str, Any]]:
    heuristic = _score_proposals_heuristic(proposals)
    scorer_name = (scorer or "heuristic").lower()
    if scorer_name == "heuristic" or not proposals:
        return heuristic
    if scorer_name == "llm":
        try:
            llm_func = llm_scorer_func or _call_llm_scorer
            llm_payload = llm_func(proposals=proposals, findings=findings or [], config=config or {})
            return _merge_llm_scores(proposals, heuristic, llm_payload)
        except Exception as exc:
            return _fallback_with_scorer_error(heuristic, "llm_scorer_error", exc)
    return heuristic


def _fallback_with_scorer_error(
    heuristic: list[dict[str, Any]],
    error_key: str,
    exc: Exception,
) -> list[dict[str, Any]]:
    message = _redact_text(str(exc), max_chars=240)
    fallback = []
    for item in heuristic:
        p2 = dict(item)
        p2[error_key] = message
        p2["auto_apply"] = False
        fallback.append(p2)
    return fallback


def _score_proposals_heuristic(proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = []
    for p in proposals:
        risk = p.get("risk") or "medium"
        confidence = p.get("confidence") or "low"
        base = 50
        if confidence == "medium":
            base += 15
        if confidence == "high":
            base += 25
        if risk == "low":
            base += 10
        if risk == "high":
            base -= 20
        p2 = dict(p)
        p2["score"] = max(0, min(100, base))
        p2["recommendation"] = "skip" if risk != "low" else "candidate"
        p2["scorer"] = "heuristic-v0.1"
        p2["auto_apply"] = False
        scored.append(p2)
    return sorted(scored, key=lambda item: item.get("score", 0), reverse=True)


def _merge_external_scores(
    proposals: list[dict[str, Any]],
    heuristic: list[dict[str, Any]],
    payload: dict[str, Any],
    *,
    scorer_label: str,
    rationale_key: str,
    error_key: str,
) -> list[dict[str, Any]]:
    scores = payload.get("scores") if isinstance(payload, dict) else None
    if not isinstance(scores, list):
        raise ValueError(f"{scorer_label} response missing `scores` list")
    by_id = {str(item.get("id") or ""): item for item in scores if isinstance(item, dict)}
    heuristic_by_id = {str(item.get("id") or ""): item for item in heuristic}
    merged = []
    for proposal in proposals:
        pid = str(proposal.get("id") or "")
        h = dict(heuristic_by_id.get(pid) or proposal)
        scored_item = by_id.get(pid)
        if not scored_item:
            h[error_key] = "missing score for proposal"
            h["auto_apply"] = False
            merged.append(h)
            continue
        score = _coerce_int(scored_item.get("score"), default=h.get("score", 0))
        p2 = dict(h)
        p2["score"] = max(0, min(100, score))
        if scored_item.get("risk") in {"low", "medium", "high"}:
            p2["risk"] = scored_item["risk"]
        if scored_item.get("confidence") in {"low", "medium", "high"}:
            p2["confidence"] = scored_item["confidence"]
        if scored_item.get("recommendation") in {
            "skip",
            "defer",
            "candidate",
        }:
            p2["recommendation"] = scored_item["recommendation"]
        else:
            p2["recommendation"] = "skip"
        p2[rationale_key] = _redact_text(str(scored_item.get("rationale") or ""), max_chars=600)
        if isinstance(scored_item.get("score_breakdown"), dict):
            p2["score_breakdown"] = _sanitize_score_breakdown(scored_item["score_breakdown"])
        p2["scorer"] = scorer_label
        # Safety gate: external scoring never grants unattended mutation permission.
        p2["auto_apply"] = False
        merged.append(p2)
    return sorted(merged, key=lambda item: item.get("score", 0), reverse=True)


def _sanitize_score_breakdown(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sanitized: dict[str, dict[str, Any]] = {}
    for name, value in raw.items():
        if not isinstance(value, dict):
            continue
        item: dict[str, Any] = {}
        if value.get("level") in {"low", "medium", "high"}:
            item["level"] = value["level"]
        item["points"] = _coerce_int(value.get("points"), default=0)
        item["weight"] = _coerce_int(value.get("weight"), default=0)
        if value.get("reason") is not None:
            item["reason"] = _redact_text(str(value.get("reason") or ""), max_chars=240)
        sanitized[str(name)] = item
    return sanitized


def _merge_llm_scores(
    proposals: list[dict[str, Any]],
    heuristic: list[dict[str, Any]],
    llm_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    return _merge_external_scores(
        proposals,
        heuristic,
        llm_payload,
        scorer_label="llm-v0.1",
        rationale_key="llm_rationale",
        error_key="llm_scorer_error",
    )


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default or 0)


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        parsed = json.loads(raw)
    except Exception:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(raw[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("LLM scorer response is not a JSON object")
    return parsed


def _ensure_hermes_agent_on_path() -> None:
    candidates = [
        get_hermes_home() / "hermes-agent",
        Path(__file__).resolve().parents[2] / "hermes-agent",
    ]
    for candidate in candidates:
        if (candidate / "agent" / "auxiliary_client.py").exists():
            path = str(candidate)
            if path not in sys.path:
                sys.path.insert(0, path)
            return


def _call_llm_scorer(
    *,
    proposals: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    model_config = config.get("model") if isinstance(config.get("model"), dict) else {}
    planner_config = model_config.get("planner") if isinstance(model_config.get("planner"), dict) else {}
    provider = planner_config.get("provider") or "auto"
    model = planner_config.get("model") or None
    timeout = _coerce_int(planner_config.get("timeout"), default=60)
    max_tokens = _coerce_int(planner_config.get("max_tokens"), default=1800)
    prompt_payload = {
        "proposals": proposals,
        "findings": findings,
        "rubric": {
            "score": "0-100。根拠が複数session/複数toolにまたがるほど高い。1回限り・再現性不明なら低い。",
            "risk": ["low", "medium", "high"],
            "recommendation": ["skip", "defer", "candidate"],
            "safety": "無人での skill/memory 自動適用を許可しない。auto_apply は常に false とみなす。",
            "skill_memory_classification": SKILL_MEMORY_CLASSIFICATION_BLOCK,
        },
    }
    messages = [
        {
            "role": "system",
            "content": (
                "あなたは Hermes の skill/memory 自己改善 planner です。"
                "出力は JSON オブジェクトのみ。secret/token/password は推測・復元しない。"
                "観測データから安全に実行できる改善計画を作るための採点を行います。"
            ),
        },
        {
            "role": "user",
            "content": (
                "次の proposal を planning 用に採点してください。返す JSON schema は "
                "{\"scores\":[{\"id\":str,\"score\":int,\"recommendation\":str,"
                "\"risk\":str,\"confidence\":str,\"rationale\":str}]} です。\n\n"
                + json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True, default=str)
            ),
        },
    ]
    _ensure_hermes_agent_on_path()
    from agent.auxiliary_client import call_llm, extract_content_or_reasoning
    from .llm_telemetry import record_llm_call
    from .prompt_cache import apply_caching

    messages, cache_extras = apply_caching(messages, site="llm_scorer")
    response = call_llm(
        task="skills_hub",
        provider=provider,
        model=model,
        messages=messages,
        temperature=None,
        max_tokens=max_tokens,
        timeout=timeout,
        extra_body=cache_extras,
    )
    response_text = extract_content_or_reasoning(response)
    record_llm_call(
        site="llm_scorer",
        messages=messages,
        response_text=response_text,
        config=config,
        model=model,
        provider=provider,
        task="skills_hub",
        max_tokens=max_tokens,
    )
    return _extract_json_object(response_text)
