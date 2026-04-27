from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

try:  # pragma: no cover - package import path
    from .config import get_hermes_home
    from .observer import _redact_text
except Exception:  # pragma: no cover - direct file import used by tests/wrapper CLI
    from config import get_hermes_home
    from observer import _redact_text

def score_proposals_impl(
    proposals: list[dict[str, Any]],
    findings: list[dict[str, Any]] | None = None,
    *,
    scorer: str = "heuristic",
    config: dict[str, Any] | None = None,
    llm_scorer_func=None,
    gepa_scorer_func=None,
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
    if scorer_name == "gepa":
        try:
            gepa_func = gepa_scorer_func or _call_gepa_scorer
            gepa_payload = gepa_func(proposals=proposals, findings=findings or [], config=config or {})
            return _merge_gepa_scores(proposals, heuristic, gepa_payload)
        except Exception as exc:
            return _fallback_with_scorer_error(heuristic, "gepa_scorer_error", exc)
    if scorer_name == "compare":
        llm_scored = score_proposals_impl(
            proposals, findings, scorer="llm", config=config, llm_scorer_func=llm_scorer_func, gepa_scorer_func=gepa_scorer_func
        )
        gepa_scored = score_proposals_impl(
            proposals, findings, scorer="gepa", config=config, llm_scorer_func=llm_scorer_func, gepa_scorer_func=gepa_scorer_func
        )
        return _compare_scorer_results(proposals, heuristic, llm_scored, gepa_scored, config=config or {})
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
        p2["recommendation"] = "report_only" if risk != "low" else "review_for_possible_low_risk_apply"
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
            "report_only",
            "human_review",
            "review_for_possible_low_risk_apply",
        }:
            p2["recommendation"] = scored_item["recommendation"]
        else:
            p2["recommendation"] = "report_only"
        p2[rationale_key] = _redact_text(str(scored_item.get("rationale") or ""), max_chars=600)
        if isinstance(scored_item.get("score_breakdown"), dict):
            p2["score_breakdown"] = _sanitize_score_breakdown(scored_item["score_breakdown"])
        p2["scorer"] = scorer_label
        # Safety gate: external scoring never grants unattended apply permission.
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


def _merge_gepa_scores(
    proposals: list[dict[str, Any]],
    heuristic: list[dict[str, Any]],
    gepa_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    return _merge_external_scores(
        proposals,
        heuristic,
        gepa_payload,
        scorer_label="gepa-v0.1",
        rationale_key="gepa_rationale",
        error_key="gepa_scorer_error",
    )


def _compare_scorer_results(
    proposals: list[dict[str, Any]],
    heuristic: list[dict[str, Any]],
    llm_scored: list[dict[str, Any]],
    gepa_scored: list[dict[str, Any]],
    *,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    heuristic_by_id = {str(item.get("id") or ""): item for item in heuristic}
    llm_by_id = {str(item.get("id") or ""): item for item in llm_scored}
    gepa_by_id = {str(item.get("id") or ""): item for item in gepa_scored}
    merged: list[dict[str, Any]] = []
    for proposal in proposals:
        pid = str(proposal.get("id") or "")
        h = dict(heuristic_by_id.get(pid) or proposal)
        llm = llm_by_id.get(pid) or {}
        gepa = gepa_by_id.get(pid) or {}
        llm_score = _coerce_int(llm.get("score"), default=h.get("score", 0))
        gepa_score = _coerce_int(gepa.get("score"), default=h.get("score", 0))
        delta = abs(llm_score - gepa_score)
        comparison_policy = _comparison_policy_for_proposal(proposal, config or {})
        disagreements = _scorer_disagreements_for_policy(
            llm=llm,
            gepa=gepa,
            score_delta=delta,
            policy=comparison_policy,
        )

        p2 = dict(h)
        p2["scorer"] = "compare-v0.1"
        p2["llm_score"] = llm_score
        p2["gepa_score"] = gepa_score
        p2["score_delta"] = delta
        p2["scorer_disagreements"] = disagreements
        p2["scorer_comparison_policy"] = comparison_policy
        p2["llm_recommendation"] = llm.get("recommendation")
        p2["gepa_recommendation"] = gepa.get("recommendation")
        p2["llm_risk"] = llm.get("risk")
        p2["gepa_risk"] = gepa.get("risk")
        p2["score"] = min(llm_score, gepa_score)
        p2["recommendation"] = "human_review" if disagreements else (gepa.get("recommendation") or llm.get("recommendation") or h.get("recommendation"))
        p2["risk"] = _max_risk(llm.get("risk"), gepa.get("risk"), h.get("risk"))
        p2["confidence"] = _min_confidence(llm.get("confidence"), gepa.get("confidence"), h.get("confidence"))
        if llm.get("llm_scorer_error"):
            p2["llm_scorer_error"] = llm.get("llm_scorer_error")
        if gepa.get("gepa_scorer_error"):
            p2["gepa_scorer_error"] = gepa.get("gepa_scorer_error")
        if isinstance(gepa.get("score_breakdown"), dict):
            p2["score_breakdown"] = gepa["score_breakdown"]
        p2["auto_apply"] = False
        merged.append(p2)
    return sorted(
        merged,
        key=lambda item: (
            len(item.get("scorer_disagreements") or []),
            item.get("score_delta", 0),
            item.get("score", 0),
        ),
        reverse=True,
    )


def _proposal_change_type(proposal: dict[str, Any]) -> str:
    explicit = str(proposal.get("change_type") or "").strip()
    if explicit:
        return explicit
    action = str(proposal.get("action") or "").lower()
    title = str(proposal.get("title") or "").lower()
    haystack = f"{action} {title}"
    if "pitfall" in haystack:
        return "pitfall_addition_existing_section"
    if "validation" in haystack or "verification" in haystack or "checklist" in haystack:
        return "validation_addition_existing_section"
    if "typo" in haystack:
        return "typo_fix"
    if "memory_compress" in haystack or "memory compression" in haystack or "compress_memory" in haystack:
        return "memory_compress"
    if "memory_delete" in haystack or "memory delete" in haystack or "delete memory" in haystack:
        return "memory_delete"
    for change_type in ("skill_create", "skill_delete", "skill_rename", "skill_merge", "skill_trigger_change", "skill_large_rewrite"):
        if change_type in haystack or change_type.replace("_", " ") in haystack:
            return change_type
    return "unknown_or_unclassified"


def _comparison_policy_for_proposal(proposal: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    raw_policy = config.get("scorer_comparison_policy") if isinstance(config.get("scorer_comparison_policy"), dict) else {}
    default = {
        "block_on_risk_disagreement": True,
        "block_on_recommendation_disagreement": True,
        "score_delta_block_threshold": 15,
        "confidence_rank_delta_block_threshold": 1,
    }
    if isinstance(raw_policy.get("default"), dict):
        default.update(raw_policy["default"])
    change_type = _proposal_change_type(proposal)
    selected = dict(default)
    selected["policy_name"] = "default"
    strict_types = {str(item) for item in raw_policy.get("strict_change_types", [])} if isinstance(raw_policy.get("strict_change_types"), list) else {"unknown_or_unclassified"}
    low_risk_prose = raw_policy.get("low_risk_prose") if isinstance(raw_policy.get("low_risk_prose"), dict) else {}
    low_risk_types = {str(item) for item in low_risk_prose.get("change_types", [])} if isinstance(low_risk_prose.get("change_types"), list) else set()
    if change_type in low_risk_types:
        selected.update({k: v for k, v in low_risk_prose.items() if k != "change_types"})
        selected["policy_name"] = "low_risk_prose"
    elif change_type in strict_types or change_type == "unknown_or_unclassified":
        strict = raw_policy.get("strict") if isinstance(raw_policy.get("strict"), dict) else {}
        selected.update(strict)
        selected["policy_name"] = "strict"
    selected["change_type"] = change_type
    selected["block_on_risk_disagreement"] = bool(selected.get("block_on_risk_disagreement", True))
    selected["block_on_recommendation_disagreement"] = bool(selected.get("block_on_recommendation_disagreement", True))
    selected["score_delta_block_threshold"] = _coerce_int(selected.get("score_delta_block_threshold"), default=15)
    selected["confidence_rank_delta_block_threshold"] = _coerce_int(selected.get("confidence_rank_delta_block_threshold"), default=1)
    return selected


def _scorer_disagreements_for_policy(*, llm: dict[str, Any], gepa: dict[str, Any], score_delta: int, policy: dict[str, Any]) -> list[str]:
    disagreements: list[str] = []
    if score_delta >= _coerce_int(policy.get("score_delta_block_threshold"), default=15):
        disagreements.append("score_gap")
    if policy.get("block_on_recommendation_disagreement", True) and llm.get("recommendation") != gepa.get("recommendation"):
        disagreements.append("recommendation_mismatch")
    if policy.get("block_on_risk_disagreement", True) and llm.get("risk") != gepa.get("risk"):
        disagreements.append("risk_mismatch")
    confidence_delta = abs(_confidence_rank(llm.get("confidence")) - _confidence_rank(gepa.get("confidence")))
    if confidence_delta >= _coerce_int(policy.get("confidence_rank_delta_block_threshold"), default=1):
        disagreements.append("confidence_gap")
    return disagreements


def _confidence_rank(value: Any) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(str(value or "").lower(), -1)


def _max_risk(*values: Any) -> str:
    order = {"low": 1, "medium": 2, "high": 3}
    valid = [str(v) for v in values if v in order]
    if not valid:
        return "medium"
    return max(valid, key=lambda v: order[v])


def _min_confidence(*values: Any) -> str:
    order = {"low": 1, "medium": 2, "high": 3}
    valid = [str(v) for v in values if v in order]
    if not valid:
        return "low"
    return min(valid, key=lambda v: order[v])


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
    llm_config = config.get("llm_scorer") if isinstance(config.get("llm_scorer"), dict) else {}
    provider = llm_config.get("provider") or "auto"
    model = llm_config.get("model") or None
    timeout = _coerce_int(llm_config.get("timeout"), default=60)
    max_tokens = _coerce_int(llm_config.get("max_tokens"), default=1800)
    prompt_payload = {
        "proposals": proposals,
        "findings": findings,
        "rubric": {
            "score": "0-100。根拠が複数session/複数toolにまたがるほど高い。1回限り・再現性不明なら低い。",
            "risk": ["low", "medium", "high"],
            "recommendation": ["report_only", "human_review", "review_for_possible_low_risk_apply"],
            "safety": "無人での skill/memory 自動適用を許可しない。auto_apply は常に false とみなす。",
        },
    }
    messages = [
        {
            "role": "system",
            "content": (
                "あなたは Hermes の skill/memory 自己改善 proposal を採点するレビュアーです。"
                "出力は JSON オブジェクトのみ。secret/token/password は推測・復元しない。"
                "自動適用ではなく、人間レビュー向けの採点を行います。"
            ),
        },
        {
            "role": "user",
            "content": (
                "次の proposal を採点してください。返す JSON schema は "
                "{\"scores\":[{\"id\":str,\"score\":int,\"recommendation\":str,"
                "\"risk\":str,\"confidence\":str,\"rationale\":str}]} です。\n\n"
                + json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True, default=str)
            ),
        },
    ]
    _ensure_hermes_agent_on_path()
    from agent.auxiliary_client import call_llm, extract_content_or_reasoning

    response = call_llm(
        task="skills_hub",
        provider=provider,
        model=model,
        messages=messages,
        temperature=None,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    return _extract_json_object(extract_content_or_reasoning(response))


def _call_gepa_scorer(
    *,
    proposals: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    adapter_path = Path(__file__).with_name("gepa_adapter.py")
    spec = importlib.util.spec_from_file_location("hermes_self_improvement_gepa_adapter", adapter_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load GEPA adapter: {adapter_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.score_with_gepa(proposals=proposals, findings=findings, config=config)

