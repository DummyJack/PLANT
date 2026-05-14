# Mediator validation helpers: normalize issue proposals and decision issues.
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


with open(Path(__file__).resolve().parent / "issue_types.json", "r", encoding="utf-8") as f:
    ISSUE_TYPES = tuple(json.load(f))
ISSUE_TYPE_IDS = [t["id"] for t in ISSUE_TYPES]
ISSUE_CATEGORY_LABEL = {t["id"]: t["label"] for t in ISSUE_TYPES}

MEETING_ACTIONS = [
    "generate_decision_issues",
    "expand_decision_issues",
    "start_discussion",
    "resolve_issue",
    "escalate_to_human",
    "save_issue",
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
VALID_ELICITATION_PHASES = {
    "initial_requirement",
    "requirement_discussion",
    "conclusion",
}
VALID_ELICITATION_ACTIONS = {
    "ask_user",
    "supplement_question",
    "propose_finish",
}


def issue_proposal(
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
        return None

    discussion_mode = (item.get("discussion_mode") or "").strip()
    if discussion_mode not in VALID_DISCUSSION_MODES:
        return None

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
        issue_id = f"I-R{round_num}-{proposed_by}-{index}"
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


def decision_issue(
    item: Dict[str, Any],
    *,
    allowed_categories: Sequence[str],
    registered_agents: Sequence[str],
    index: int,
) -> Optional[Dict[str, Any]]:
    """驗證並正規化正式 decision issue（固定 schema）。"""
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
        return None

    discussion_mode = (item.get("discussion_mode") or "").strip()
    if discussion_mode not in VALID_DISCUSSION_MODES:
        return None

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

    issue_id = (item.get("id") or "").strip() or f"T-{index}"
    return {
        "schema_version": "decision_issue.v1",
        "id": issue_id,
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


def meeting_action_decision(data: Dict[str, Any]) -> Dict[str, Any]:
    """驗證並正規化 meeting loop 的下一步 action。"""
    if not isinstance(data, dict):
        raise ValueError("meeting action 必須輸出 JSON object")
    action = str(data.get("action") or "").strip()
    if action not in MEETING_ACTIONS:
        raise ValueError(f"meeting action 不合法: {action or '<empty>'}")
    params = data.get("params") or {}
    if not isinstance(params, dict):
        raise ValueError("meeting action params 必須是 object")
    return {
        "action": action,
        "params": params,
        "reasoning": str(data.get("reasoning") or "").strip(),
    }


def elicitation_plan(
    data: Dict[str, Any],
    *,
    default_participants: Sequence[str],
    stakeholder_names: Sequence[str],
) -> Dict[str, Any]:
    """驗證並正規化 requirement elicitation 每輪會議策略。"""
    if not isinstance(data, dict):
        raise ValueError("逐輪策略決策必須輸出 JSON object")

    allowed = [str(x).strip() for x in default_participants if str(x).strip()]
    allowed_set = set(allowed)
    participants_raw = data.get("participants")
    if not isinstance(participants_raw, list):
        raise ValueError("逐輪策略 participants 必須是 list")
    participants = [
        str(x).strip()
        for x in participants_raw
        if isinstance(x, str) and str(x).strip() in allowed_set
    ]
    participants = list(dict.fromkeys(participants))
    if not participants:
        raise ValueError("逐輪策略 participants 未包含有效參與者")
    if "user" not in participants:
        raise ValueError("逐輪策略 participants 必須包含 user")

    phase = str(data.get("meeting_phase") or "").strip()
    if phase not in VALID_ELICITATION_PHASES:
        raise ValueError(f"逐輪策略 meeting_phase 不合法: {phase or '<empty>'}")

    raw_agent_actions = data.get("agent_actions") if isinstance(data.get("agent_actions"), dict) else {}
    if not isinstance(raw_agent_actions, dict):
        raise ValueError("逐輪策略 agent_actions 必須是 object")
    agent_actions: Dict[str, Dict[str, str]] = {}
    for role in [p for p in participants if p != "user"]:
        raw_action = raw_agent_actions.get(role) if isinstance(raw_agent_actions, dict) else {}
        if not isinstance(raw_action, dict):
            raise ValueError(f"逐輪策略 agent_actions.{role} 必須是 object")
        action = str(raw_action.get("action") or "").strip().lower()
        if action not in VALID_ELICITATION_ACTIONS:
            raise ValueError(f"逐輪策略 agent_actions.{role}.action 不合法: {action or '<empty>'}")
        agent_actions[role] = {"action": action}

    has_finish_proposal = any(
        row.get("action") == "propose_finish" for row in agent_actions.values()
    )
    has_user_question = any(
        row.get("action") in {"ask_user", "supplement_question"}
        for row in agent_actions.values()
    )
    if not has_finish_proposal and not has_user_question:
        raise ValueError("逐輪策略必須至少包含一個 ask_user 或 supplement_question，除非 propose_finish")
    goal = str(data.get("goal") or "").strip()
    if not goal:
        raise ValueError("逐輪策略 goal 不可為空")

    return {
        "participants": participants,
        "meeting_phase": phase,
        "goal": goal,
        "agent_actions": agent_actions,
    }


def conflict_review_plan(
    data: Dict[str, Any],
    *,
    allowed_participants: Sequence[str],
) -> Dict[str, Any]:
    """驗證並正規化衝突再審查的模式與參與者。"""
    if not isinstance(data, dict):
        raise ValueError("plan_conflict_review 必須輸出 JSON object")
    mode = str(data.get("discussion_mode") or "").strip().lower()
    if mode not in VALID_DISCUSSION_MODES:
        raise ValueError(f"plan_conflict_review discussion_mode 不合法: {mode or '<empty>'}")

    allowed_set = {str(x).strip() for x in allowed_participants if str(x).strip()}
    participants = [
        str(x).strip()
        for x in (data.get("participants") or [])
        if str(x).strip() in allowed_set and str(x).strip() != "user"
    ]
    participants = list(dict.fromkeys(participants))
    if len(participants) < 2:
        raise ValueError("plan_conflict_review participants 至少需要兩位有效 agent")
    return {"discussion_mode": mode, "participants": participants}


def meeting_title_batch(data: Any, *, expected_count: int) -> Dict[int, str]:
    """驗證批次會議標題輸出，回傳 index -> title。"""
    if not isinstance(data, list):
        if isinstance(data, dict):
            if "index" in data and "title" in data:
                data = [data]
            else:
                data = data.get("items") or data.get("titles") or []
        else:
            data = []
    title_map: Dict[int, str] = {}
    for row in data:
        if not isinstance(row, dict):
            continue
        if "index" not in row:
            continue
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        try:
            idx = int(row["index"])
        except (TypeError, ValueError):
            continue
        if 0 <= idx < expected_count:
            title_map[idx] = title
    missing = [i for i in range(expected_count) if i not in title_map]
    if missing:
        raise ValueError(f"Mediator meeting title missing for item indexes: {missing}")
    return title_map


def meeting_title(data: Any) -> str:
    """驗證單一會後標題輸出。"""
    if not isinstance(data, dict):
        raise ValueError("Mediator meeting title 必須輸出 JSON object")
    title = str(data.get("title") or "").strip()
    if not title:
        raise ValueError("Mediator meeting title 不可為空")
    return title


def convergence_result(data: Dict[str, Any]) -> Dict[str, Any]:
    """驗證並正規化討論收斂判斷。"""
    if not isinstance(data, dict):
        raise ValueError("收斂判斷必須輸出 JSON object")
    return {
        "converged": bool(data.get("converged")),
        "reason": str(data.get("reason") or "").strip(),
        "summary": str(data.get("summary") or "").strip(),
        "decision": str(data.get("decision") or "").strip(),
    }


def decision_option_analysis(
    data: Dict[str, Any],
    *,
    source_requirement_ids: Sequence[str],
) -> Dict[str, Any]:
    """驗證並正規化未收斂議題的人類裁決選項。"""
    if not isinstance(data, dict):
        raise ValueError("decision option analysis 必須輸出 JSON object")
    options = data.get("options", [])
    if not isinstance(options, list):
        raise ValueError("decision option analysis options 必須是 list")
    clean_options = []
    for idx, option in enumerate(options, 1):
        if not isinstance(option, dict):
            continue
        oid = str(option.get("id") or chr(64 + idx)).strip() or chr(64 + idx)
        summary = str(option.get("summary") or "").strip()
        if not summary:
            continue
        risk = str(option.get("risk") or "medium").strip().lower() or "medium"
        if risk not in VALID_IMPACT_LEVELS:
            risk = "medium"
        clean_options.append(
            {
                "id": oid,
                "summary": summary,
                "pros": [str(x).strip() for x in (option.get("pros") or []) if str(x).strip()],
                "cons": [str(x).strip() for x in (option.get("cons") or []) if str(x).strip()],
                "impact": [str(x).strip() for x in (option.get("impact") or []) if str(x).strip()],
                "risk": risk,
            }
        )
    if not clean_options:
        raise ValueError("decision option analysis 必須至少輸出一個有效 option")

    recommendation = data.get("recommendation", {})
    if not isinstance(recommendation, dict):
        raise ValueError("decision option analysis recommendation 必須是 object")
    option_ids = {row["id"] for row in clean_options}
    rec_option = str(recommendation.get("option_id") or "").strip()
    if rec_option not in option_ids:
        raise ValueError("decision option analysis recommendation.option_id 不合法")
    affected_requirement_ids = data.get("affected_requirement_ids", [])
    if not isinstance(affected_requirement_ids, list) or not affected_requirement_ids:
        affected_requirement_ids = list(source_requirement_ids)
    unresolved_points = data.get("unresolved_points", [])
    if not isinstance(unresolved_points, list):
        unresolved_points = []

    summary = str(data.get("summary") or "").strip()
    if not summary:
        raise ValueError("decision option analysis summary 不可為空")
    return {
        "summary": summary,
        "options": clean_options,
        "recommendation": {
            "option_id": rec_option,
            "rationale": str(recommendation.get("rationale") or "").strip(),
            "needs_human": True,
        },
        "affected_requirement_ids": [
            str(x).strip() for x in affected_requirement_ids if str(x).strip()
        ],
        "unresolved_points": [
            str(x).strip() for x in unresolved_points if str(x).strip()
        ] or ["需要人類裁決採用哪個方案。"],
    }


def human_option_slates(data: Dict[str, Any]) -> Dict[str, Any]:
    """驗證並正規化提供給人類裁決的方案 slate。"""
    if not isinstance(data, dict):
        raise ValueError("human option slates 必須輸出 JSON object")
    best_options = data.get("best_options", [])
    if not isinstance(best_options, list):
        best_options = []
    clean_best: List[Dict[str, Any]] = []
    for idx, option in enumerate(best_options, 1):
        if not isinstance(option, dict):
            continue
        title = str(option.get("title") or "").strip()
        description = str(option.get("description") or "").strip()
        if not title or not description:
            continue
        clean_best.append(
            {
                "id": option.get("id") or idx,
                "title": title,
                "description": description,
                "source": str(option.get("source") or "").strip(),
            }
        )
    compromise = data.get("compromise", {})
    if not isinstance(compromise, dict):
        compromise = {}
    if compromise:
        compromise = {
            "id": compromise.get("id") or 4,
            "title": str(compromise.get("title") or "").strip(),
            "description": str(compromise.get("description") or "").strip(),
            "rationale": str(compromise.get("rationale") or "").strip(),
        }
    return {"best_options": clean_best, "compromise": compromise}
