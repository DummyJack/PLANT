# Validates and normalizes agent output data formats.
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


with open(Path(__file__).resolve().parent / "issue_types.json", "r", encoding="utf-8") as f:
    issue_types = tuple(json.load(f))
issue_type_ids = [t["id"] for t in issue_types]
category_labels = {t["id"]: t["label"] for t in issue_types}

meeting_actions = [
    "plan_issues",
    "add_issues",
    "update_default_draft",
    "run_general_conflict_gate",
    "update_general_draft",
    "start_issue",
    "resolve_issue",
    "judge_issue",
    "save_issue",
    "finish_round",
]

discussion_modes = {"sequential", "simultaneous"}
priority_hints = {"high", "medium", "low"}
impact_levels = {"high", "medium", "low"}
elicitation_phases = {
    "initial_requirement",
    "requirement_discussion",
    "conclusion",
}
elicitation_actions = {
    "ask_user",
    "supplement_question",
    "propose_finish",
}
related_artifacts = {
    "URL",
    "REQ",
    "conflict_report",
    "conversation",
    "system_models",
    "open_questions",
    "scope",
    "feedback",
}


# ========
# Defines normalize sources function for this module workflow.
# ========
def normalize_sources(value: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen = set()
    for item in value or []:
        if not isinstance(item, dict):
            continue
        artifact = str(item.get("artifact") or "").strip()
        if artifact not in related_artifacts:
            continue
        ids = [
            str(x).strip()
            for x in (item.get("ids") or [])
            if str(x).strip()
        ]
        evidence = str(item.get("evidence") or "").strip()
        key = (artifact, tuple(dict.fromkeys(ids)), evidence)
        if key in seen:
            continue
        seen.add(key)
        row = {"artifact": artifact, "ids": list(dict.fromkeys(ids))}
        if evidence:
            row["evidence"] = evidence
        rows.append(row)
    return rows


# ========
# Defines normalize trace function for this module workflow.
# ========
def normalize_trace(value: Any) -> Dict[str, List[str]]:
    if not isinstance(value, dict):
        value = {}
    artifact_ids = [
        str(x).strip()
        for x in (value.get("artifact_ids") or [])
        if str(x).strip()
    ]
    proposal_ids = [
        str(x).strip()
        for x in (value.get("proposal_ids") or [])
        if str(x).strip()
    ]
    return {
        "artifact_ids": list(dict.fromkeys(artifact_ids)),
        "proposal_ids": list(dict.fromkeys(proposal_ids)),
    }


# ========
# Defines trace artifact ids function for this module workflow.
# ========
def trace_artifact_ids(issue: Optional[Dict[str, Any]]) -> List[str]:
    return normalize_trace((issue or {}).get("trace")).get("artifact_ids", [])


# ========
# Defines trace proposal ids function for this module workflow.
# ========
def trace_proposal_ids(issue: Optional[Dict[str, Any]]) -> List[str]:
    return normalize_trace((issue or {}).get("trace")).get("proposal_ids", [])


# ========
# Defines issue proposal function for this module workflow.
# ========
def issue_proposal(
    item: Dict[str, Any],
    *,
    allowed_categories: Sequence[str],
    default_participants: Sequence[str],
    proposed_by: str,
    round_num: int,
    index: int,
) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None

    title = (item.get("title") or "").strip()
    if not title:
        return None

    importance = str(item.get("importance") or "").strip().lower()
    if importance not in priority_hints:
        return None
    issue_level = str(item.get("issue_level") or "").strip().lower()
    if issue_level not in {"blocking", "improvement"}:
        issue_level = "blocking" if importance == "high" else "improvement"

    issue_id = (item.get("issue_id") or "").strip()
    if not issue_id:
        issue_id = f"R{round_num}-I{index}"
    sources = normalize_sources(item.get("sources"))
    expected_actions = normalize_expected_actions(item.get("expected_actions"))
    suggested_participants = [
        str(value).strip()
        for value in (item.get("suggested_participants") or [])
        if str(value).strip()
    ]
    participant_reasoning = item.get("participant_reasoning")
    if isinstance(participant_reasoning, dict):
        participant_reasoning = {
            str(agent).strip(): str(reason or "").strip()
            for agent, reason in participant_reasoning.items()
            if str(agent).strip() and str(reason or "").strip()
        }
    else:
        participant_reasoning = {}

    proposal = {
        "issue_id": issue_id,
        "title": title,
        "category": str(item.get("category") or "").strip(),
        "issue_focus": str(item.get("issue_focus") or "").strip(),
        "expect_outcome": str(item.get("expect_outcome") or "").strip(),
        "sources": sources,
        "expected_actions": expected_actions,
        "issue_level": issue_level,
        "importance": importance,
        "reason": str(item.get("reason") or "").strip(),
        "proposed_by": proposed_by,
        "round": round_num,
    }
    if suggested_participants:
        proposal["suggested_participants"] = list(dict.fromkeys(suggested_participants))
    if participant_reasoning:
        proposal["participant_reasoning"] = participant_reasoning
    return proposal


# ========
# Defines normalize expected actions function for this module workflow.
# ========
def normalize_expected_actions(value: Any) -> Dict[str, List[str]]:
    if not isinstance(value, dict):
        return {}
    out: Dict[str, List[str]] = {}
    for agent_name, actions in value.items():
        agent = str(agent_name or "").strip()
        if not agent:
            continue
        if isinstance(actions, str):
            actions = [actions]
        if not isinstance(actions, list):
            continue
        clean = [
            str(action).strip()
            for action in actions
            if str(action).strip()
        ]
        if clean:
            out[agent] = list(dict.fromkeys(clean))
    return out


# ========
# Defines meeting issue function for this module workflow.
# ========
def meeting_issue(
    item: Dict[str, Any],
    *,
    allowed_categories: Sequence[str],
    registered_agents: Sequence[str],
    allowed_stakeholders: Optional[Sequence[str]] = None,
    index: int,
) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    title = (item.get("title") or "").strip()
    description = str(item.get("description") or "").strip()
    category = (item.get("category") or "").strip()
    if not title or not category:
        return None
    if category not in set(allowed_categories):
        return None

    registered_agent_set = set(registered_agents)
    participants = [
        str(p).strip()
        for p in (item.get("participants") or [])
        if str(p).strip() in registered_agent_set
    ]
    participants = list(dict.fromkeys(participants))
    proposed_by = str(item.get("proposed_by") or "").strip()
    if proposed_by and proposed_by != "mediator" and proposed_by in registered_agent_set and proposed_by not in participants:
        participants.append(proposed_by)
    if not participants:
        return None

    discussion_mode = (item.get("discussion_mode") or "").strip()
    if discussion_mode not in discussion_modes:
        return None
    if item.get("discussion_rounds") in (None, ""):
        return None
    try:
        discussion_rounds = int(item.get("discussion_rounds"))
    except (TypeError, ValueError):
        return None
    if discussion_rounds < 1 or discussion_rounds > 3:
        return None

    allowed_stakeholder_set = {
        str(name).strip()
        for name in (allowed_stakeholders or [])
        if str(name).strip()
    }
    target_stakeholders = [
        str(name).strip()
        for name in (item.get("target_stakeholders") or [])
        if str(name).strip()
        and (not allowed_stakeholder_set or str(name).strip() in allowed_stakeholder_set)
    ]
    target_stakeholders = list(dict.fromkeys(target_stakeholders))
    if "user" in participants and allowed_stakeholder_set and not target_stakeholders:
        return None
    if "user" not in participants:
        target_stakeholders = []

    trace = normalize_trace(item.get("trace"))
    issue_id = (item.get("id") or "").strip() or f"M-{index}"
    issue_level = str(item.get("issue_level") or "").strip().lower()
    if issue_level not in {"blocking", "improvement"}:
        issue_level = "blocking"
    expected_actions = {
        agent: actions
        for agent, actions in normalize_expected_actions(item.get("expected_actions")).items()
        if agent in set(participants)
    }
    participant_reasoning = item.get("participant_reasoning")
    if isinstance(participant_reasoning, dict):
        participant_reasoning = {
            str(agent).strip(): str(reason or "").strip()
            for agent, reason in participant_reasoning.items()
            if str(agent).strip() in set(participants) and str(reason or "").strip()
        }
    else:
        participant_reasoning = {}
    if set(participants) - set(participant_reasoning):
        return None
    return {
        "schema_version": "meeting_issue.v1",
        "id": issue_id,
        "title": title,
        "description": description,
        "category": category,
        "participants": participants,
        "discussion_mode": discussion_mode,
        "discussion_rounds": discussion_rounds,
        "target_stakeholders": target_stakeholders,
        "trace": trace,
        "proposed_by": proposed_by,
        "issue_level": issue_level,
        "expected_actions": expected_actions,
        "participant_reasoning": participant_reasoning,
    }


# ========
# Defines meeting action decision function for this module workflow.
# ========
def meeting_action_decision(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("meeting action 必須輸出 JSON object")
    action = str(data.get("action") or "").strip()
    if action not in meeting_actions:
        raise ValueError(f"meeting action 不合法: {action or '<empty>'}")
    params = data.get("params") or {}
    if not isinstance(params, dict):
        raise ValueError("meeting action params 必須是 object")
    return {
        "action": action,
        "params": params,
        "reasoning": str(data.get("reasoning") or "").strip(),
    }


# ========
# Defines elicitation plan function for this module workflow.
# ========
def elicitation_plan(
    data: Dict[str, Any],
    *,
    default_participants: Sequence[str],
    stakeholder_names: Sequence[str],
) -> Dict[str, Any]:
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
    if phase not in elicitation_phases:
        raise ValueError(f"逐輪策略 meeting_phase 不合法: {phase or '<empty>'}")

    raw_actions = data.get("actions") if isinstance(data.get("actions"), dict) else {}
    if not isinstance(raw_actions, dict):
        raise ValueError("逐輪策略 actions 必須是 object")
    actions: Dict[str, Dict[str, Any]] = {}
    stakeholder_list = [str(x).strip() for x in stakeholder_names if str(x).strip()]
    stakeholder_set = set(stakeholder_list)
    for role in [p for p in participants if p != "user"]:
        raw_action = raw_actions.get(role) if isinstance(raw_actions, dict) else {}
        if not isinstance(raw_action, dict):
            raise ValueError(f"逐輪策略 actions.{role} 必須是 object")
        action = str(raw_action.get("action") or "").strip().lower()
        if action not in elicitation_actions:
            raise ValueError(f"逐輪策略 actions.{role}.action 不合法: {action or '<empty>'}")
        targets = [
            str(name).strip()
            for name in (raw_action.get("target_stakeholders") or [])
            if str(name).strip() in stakeholder_set
        ]
        normalized_action: Dict[str, Any] = {"action": action}
        if action in {"ask_user", "supplement_question"}:
            if not targets:
                raise ValueError(f"逐輪策略 actions.{role}.target_stakeholders 必須指定有效利害關係人")
            normalized_action["target_stakeholders"] = list(dict.fromkeys(targets))
        actions[role] = normalized_action

    has_finish_proposal = any(
        row.get("action") == "propose_finish" for row in actions.values()
    )
    has_user_question = any(
        row.get("action") in {"ask_user", "supplement_question"}
        for row in actions.values()
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
        "actions": actions,
    }


# ========
# Defines conflict review plan function for this module workflow.
# ========
def conflict_review_plan(
    data: Dict[str, Any],
    *,
    allowed_participants: Sequence[str],
) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("plan_conflict_review 必須輸出 JSON object")
    mode = str(data.get("discussion_mode") or "").strip().lower()
    if mode not in discussion_modes:
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


# ========
# Defines judgment data function for this module workflow.
# ========
def judgment_data(
    data: Dict[str, Any],
    *,
    source_requirement_ids: Sequence[str],
) -> Dict[str, Any]:
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
        risk = str(option.get("risk") or "").strip().lower()
        if risk not in impact_levels:
            raise ValueError(f"decision option risk 不合法: {risk or '<empty>'}")
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
    compromise = data.get("compromise", {})
    if not isinstance(compromise, dict):
        compromise = {}
    if compromise:
        compromise = {
            "title": str(compromise.get("title") or "").strip(),
            "description": str(compromise.get("description") or "").strip(),
            "rationale": str(compromise.get("rationale") or "").strip(),
        }
        if not any(compromise.values()):
            compromise = {}

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
        "compromise": compromise,
        "affected_requirement_ids": [
            str(x).strip() for x in affected_requirement_ids if str(x).strip()
        ],
        "unresolved_points": [
            str(x).strip() for x in unresolved_points if str(x).strip()
        ] or ["需要人類裁決採用哪個方案。"],
    }


# ========
# Defines close issue data function for this module workflow.
# ========
def close_issue_data(
    data: Dict[str, Any],
    *,
    source_requirement_ids: Sequence[str],
    source_conflict_ids: Sequence[str],
) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("closed resolution 必須輸出 JSON object")
    summary = str(data.get("summary") or "").strip()
    decision = str(data.get("decision") or "").strip()
    if not summary:
        raise ValueError("closed resolution summary 不可為空")
    if not decision:
        raise ValueError("closed resolution decision 不可為空")
    agreed_points = data.get("agreed_points", [])
    if not isinstance(agreed_points, list):
        agreed_points = []
    affected_requirement_ids = data.get("affected_requirement_ids", [])
    if not isinstance(affected_requirement_ids, list) or not affected_requirement_ids:
        affected_requirement_ids = list(source_requirement_ids)
    affected_conflict_ids = data.get("affected_conflict_ids", [])
    if not isinstance(affected_conflict_ids, list) or not affected_conflict_ids:
        affected_conflict_ids = list(source_conflict_ids)
    elif source_conflict_ids:
        affected_conflict_ids = list(affected_conflict_ids) + list(source_conflict_ids)
    requirement_changes = data.get("requirement_changes", [])
    if not isinstance(requirement_changes, list):
        requirement_changes = []
    model_changes = data.get("model_changes", [])
    if not isinstance(model_changes, list):
        model_changes = []
    open_questions = data.get("open_questions", [])
    if not isinstance(open_questions, list):
        open_questions = []
    return {
        "summary": summary,
        "decision": decision,
        "agreed_points": [
            str(x).strip() for x in agreed_points if str(x).strip()
        ] or [decision],
        "affected_requirement_ids": [
            str(x).strip() for x in affected_requirement_ids if str(x).strip()
        ],
        "affected_conflict_ids": list(dict.fromkeys(
            str(x).strip() for x in affected_conflict_ids if str(x).strip()
        )),
        "requirement_changes": [row for row in requirement_changes if isinstance(row, dict)],
        "model_changes": [row for row in model_changes if isinstance(row, dict)],
        "open_questions": [row for row in open_questions if isinstance(row, dict)],
    }
