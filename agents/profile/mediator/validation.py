# Agenda schema helpers: normalize issue proposals and decision topics.
import json
from pathlib import Path
from typing import Any, Dict, Optional, Sequence


with open(Path(__file__).resolve().parent / "agenda_types.json", "r", encoding="utf-8") as f:
    AGENDA_TYPES = tuple(json.load(f))
AGENDA_TYPE_IDS = [t["id"] for t in AGENDA_TYPES]
AGENDA_CATEGORY_LABEL = {t["id"]: t["label"] for t in AGENDA_TYPES}

AGENDA_ACTIONS = [
    "generate_decision_topics",
    "expand_decision_topics",
    "start_discussion",
    "resolve_topic",
    "escalate_to_human",
    "save_topic",
    "finish_round",
]

VALID_DISCUSSION_MODES = {"sequential", "simultaneous"}
VALID_PRIORITY_HINTS = {"high", "medium", "low"}
VALID_ROUTING_ACTIONS = {
    "direct_apply",
    "direct_clarification",
    "formal_meeting",
    "human_decision",
}
VALID_IMPACT_LEVELS = {"high", "medium", "low"}


def normalize_issue_proposal(
    item: Dict[str, Any],
    *,
    allowed_categories: Sequence[str],
    default_participants: Sequence[str],
    proposed_by: str,
    round_num: int,
    index: int,
) -> Optional[Dict[str, Any]]:
    """驗證並正規化 agent issue proposal（固定 schema）。"""
    if not isinstance(item, dict):
        return None

    title = (item.get("title") or "").strip()
    description = (item.get("description") or "").strip()
    category = (item.get("category") or "").strip()
    why_now = (item.get("why_now") or "").strip()
    if not title or not description or not category or not why_now:
        return None
    if category not in set(allowed_categories):
        return None

    participants = [
        str(p).strip()
        for p in (item.get("participants") or [])
        if str(p).strip()
    ]
    participants = list(dict.fromkeys(participants))
    if not participants:
        participants = list(default_participants)
    if not participants:
        return None

    discussion_mode = (item.get("discussion_mode") or "sequential").strip()
    if discussion_mode not in VALID_DISCUSSION_MODES:
        discussion_mode = "sequential"

    speaking_order = [
        str(p).strip()
        for p in (item.get("speaking_order") or participants)
        if str(p).strip() in participants
    ]
    speaking_order = list(dict.fromkeys(speaking_order))
    if set(speaking_order) != set(participants):
        speaking_order = list(participants)

    source_ids = [
        str(s).strip() for s in (item.get("source_ids") or [])
        if str(s).strip()
    ]
    source_ids = list(dict.fromkeys(source_ids))

    priority_hint = (item.get("priority_hint") or "medium").strip().lower()
    if priority_hint not in VALID_PRIORITY_HINTS:
        priority_hint = "medium"
    impact_level = (item.get("impact_level") or priority_hint or "medium").strip().lower()
    if impact_level not in VALID_IMPACT_LEVELS:
        impact_level = priority_hint

    issue_id = (item.get("issue_id") or "").strip()
    if not issue_id:
        issue_id = f"I-R{round_num:02d}-{proposed_by}-{index:03d}"
    routing_preference = (item.get("routing_preference") or "formal_meeting").strip()
    if routing_preference not in VALID_ROUTING_ACTIONS:
        routing_preference = "formal_meeting"

    return {
        "schema_version": "issue_proposal.v1",
        "issue_id": issue_id,
        "title": title,
        "description": description,
        "category": category,
        "participants": participants,
        "discussion_mode": discussion_mode,
        "speaking_order": speaking_order,
        "source_ids": source_ids,
        "priority_hint": priority_hint,
        "impact_level": impact_level,
        "why_now": why_now,
        "proposed_by": proposed_by,
        "round": round_num,
        "deferred_rounds": int(item.get("deferred_rounds") or 0),
        "routing_preference": routing_preference,
        "requires_multi_party": bool(item.get("requires_multi_party")),
        "blocks_decision": bool(item.get("blocks_decision")),
        "needs_human": bool(item.get("needs_human")),
        "status": (item.get("status") or "proposed").strip() or "proposed",
    }


def normalize_decision_topic(
    item: Dict[str, Any],
    *,
    allowed_categories: Sequence[str],
    registered_agents: Sequence[str],
    index: int,
) -> Optional[Dict[str, Any]]:
    """驗證並正規化正式 decision topic（固定 schema）。"""
    if not isinstance(item, dict):
        return None
    title = (item.get("title") or "").strip()
    description = (item.get("description") or "").strip()
    category = (item.get("category") or "").strip()
    if not title or not category:
        return None
    if category not in set(allowed_categories):
        return None

    participants = [
        str(p).strip()
        for p in (item.get("participants") or [])
        if str(p).strip() in set(registered_agents)
    ]
    participants = list(dict.fromkeys(participants))
    if not participants:
        participants = list(registered_agents)
    if not participants:
        return None

    discussion_mode = (item.get("discussion_mode") or "sequential").strip()
    if discussion_mode not in VALID_DISCUSSION_MODES:
        discussion_mode = "sequential"

    speaking_order = [
        str(p).strip()
        for p in (item.get("speaking_order") or participants)
        if str(p).strip() in participants
    ]
    speaking_order = list(dict.fromkeys(speaking_order))
    if set(speaking_order) != set(participants):
        speaking_order = list(participants)

    source_ids = [
        str(s).strip()
        for s in (item.get("source_ids") or [])
        if str(s).strip()
    ]
    source_ids = list(dict.fromkeys(source_ids))
    source_issue_ids = [
        str(s).strip()
        for s in (item.get("source_issue_ids") or [])
        if str(s).strip()
    ]
    source_issue_ids = list(dict.fromkeys(source_issue_ids))
    routing_action = (item.get("triage_action") or "formal_meeting").strip()
    if routing_action not in VALID_ROUTING_ACTIONS:
        routing_action = "formal_meeting"

    topic_id = (item.get("id") or "").strip() or f"T-{index:02d}"
    return {
        "schema_version": "decision_topic.v1",
        "id": topic_id,
        "title": title,
        "description": description,
        "category": category,
        "participants": participants,
        "discussion_mode": discussion_mode,
        "speaking_order": speaking_order,
        "source_ids": source_ids,
        "source_issue_ids": source_issue_ids,
        "status": (item.get("status") or "scheduled").strip() or "scheduled",
        "triage_action": routing_action,
    }
