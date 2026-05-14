# Support helpers for requirement elicitation meetings.
from typing import Any, Dict, List, Optional

from agents.profile.analyst.requirements import requirement_candidate, requirement_discussion_pool

ELICITATION_PHASES = [
    "initial_requirement",
    "requirement_discussion",
    "conclusion",
]
QUESTION_AGENT_ACTIONS = {"ask_user", "supplement_question"}
FINISH_AGENT_ACTION = "propose_finish"
def compact_text(text: str) -> str:
    value = " ".join(str(text or "").split())
    return value

def build_sequential_order(
    proposed_order: List[str],
    participants: List[str],
) -> List[str]:
    order: List[str] = []
    participant_set = set(participants or [])
    for value in proposed_order or []:
        name = str(value or "").strip()
        if name and name in participant_set and name != "user" and name not in order:
            order.append(name)
    for name in participants or []:
        if name != "user" and name not in order:
            order.append(name)
    order.append("user")
    return order

def without_finish_proposals(
    contributions: List[Dict[str, Any]],
    stop_phrase: str,
) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    for c in contributions or []:
        if not isinstance(c, dict):
            continue
        if c.get("agent") != "user" and stop_phrase in get_contribution_statement(c):
            continue
        resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
        if c.get("agent") != "user" and str(resp.get("action") or "").strip().lower() == FINISH_AGENT_ACTION:
            continue
        filtered.append(c)
    return filtered

def get_elicitation_mode(artifact: Dict[str, Any]) -> str:
    meta = artifact.get("meta") if isinstance(artifact, dict) else {}
    mode = str((meta or {}).get("elicitation_mode") or "").strip().lower()
    return mode if mode in {"oracle", "main_flow"} else "main_flow"

def elicitation_phase_for_turn(turn: int, max_turns: int) -> str:
    if turn <= 1:
        return "initial_requirement"
    return "requirement_discussion"

def collect_user_response_summary(contributions: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for c in contributions or []:
        if not isinstance(c, dict) or c.get("agent") != "user":
            continue
        statement = get_contribution_statement(c)
        if statement:
            parts.append(statement)
    return "\n".join(parts).strip()

def build_phase_guidance(phase: str) -> str:
    if phase == "initial_requirement":
        return (
            "本階段是需求訪談開場：先找出最能形成候選需求的核心缺口，"
            "不要停留在泛泛的背景、動機或痛點追問。"
        )
    if phase == "conclusion":
        return (
            "本階段是收斂確認：只有在目前需求理解已足以形成下一版 requirement set 時才輸出停止句；"
            "否則只能問一個會阻礙收斂的待補問題。"
        )
    return (
        "本階段是深入需求訪談與即時更新：參與 agent 應依自身角色檢查目前需求理解中仍缺少的目標、內容、流程、限制、例外或可接受標準，"
        "並向指定利害關係人提出可直接支援 requirement candidate 更新的問題。"
    )

def build_recent_ask_history(
    elicitation_trace: List[Dict[str, Any]],
    *,
    max_items: int = 3,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for log in reversed(elicitation_trace or []):
        if not isinstance(log, dict):
            continue
        turn = int(log.get("turn", 0) or 0)
        question_from = str(log.get("judged_action_agent") or "").strip()
        question_text = str(log.get("judged_action") or "").strip()
        user_response = ""
        user_action_type = str(log.get("user_action_type") or "").strip()
        missing_signal = ""
        for row in (log.get("contributions") or []):
            if not isinstance(row, dict):
                continue
            agent = str(row.get("agent") or "").strip()
            statement = str(row.get("statement") or "").strip()
            if not statement:
                continue
            if agent != "user" and not question_text:
                question_from = agent
                question_text = extract_first_question(statement) or compact_text(statement)
            elif agent == "user" and not user_response:
                user_response = compact_text(statement)
        if not log.get("new_candidates_count"):
            missing_signal = "上一輪未形成新 candidate，請避免原樣重複；若同一缺口仍重要，可換一種更具體但不誘導的問法。"
        elif log.get("new_candidate_texts"):
            first_new = str((log.get("new_candidate_texts") or [""])[0]).strip()
            if first_new:
                missing_signal = f"上一輪已挖到新方向：{compact_text(first_new)}；本輪避免重複。"
        if not question_text:
            continue
        rows.append(
            {
                "turn": turn,
                "question_from": question_from,
                "question": extract_first_question(question_text) or compact_text(question_text),
                "user_signal": user_response,
                "user_action_type": user_action_type,
                "what_is_still_missing": missing_signal,
            }
        )
        if len(rows) >= max_items:
            break
    rows.reverse()
    return rows

def initialize_requirement_elicitation_session(
    artifact: Dict[str, Any],
    *,
    round_num: int,
    max_turns: int,
    participants: List[str],
) -> Dict[str, Any]:
    state = {
        "round": round_num,
        "standard": "practical_requirement_elicitation_meeting",
        "goal": (
            "Align the current requirement understanding, validate gaps with the user, "
            "and turn validated answers into concrete requirement updates."
        ),
        "phase_order": list(ELICITATION_PHASES),
        "phases": [
            {
                "id": "initial_requirement",
                "purpose": "Align product goal, scope, current requirement understanding, and the most important gaps.",
            },
            {
                "id": "requirement_discussion",
                "purpose": "Let the selected agents ask stakeholder-focused validation questions and convert answers into requirement updates.",
            },
            {
                "id": "conclusion",
                "purpose": "Stop only when the current requirement understanding is clear enough, or record remaining open items.",
            },
        ],
        "participants": list(participants or []),
        "max_turns": max_turns,
        "turns": [],
        "conclusion": {},
    }
    return state

def find_finish_proposal(
    contributions: List[Dict[str, Any]],
    stop_phrase: str,
) -> tuple[str, str]:
    for c in contributions or []:
        if not isinstance(c, dict):
            continue
        agent = str(c.get("agent") or "").strip()
        if not agent or agent == "user":
            continue
        resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
        agent_action = str(resp.get("action") or "").strip().lower()
        if agent_action == FINISH_AGENT_ACTION:
            return agent, stop_phrase
        statement = get_contribution_statement(c)
        if statement and stop_phrase in statement:
            return agent, stop_phrase
    return "", ""

def extract_first_question(text: str) -> str:
    parts = [p.strip() for p in str(text or "").replace("\n", " ").split("。") if p.strip()]
    for p in parts:
        if "？" in p or "?" in p:
            return p
    return parts[0] if parts else ""

def elicited_requirement_candidates(
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    seen_texts: set = set()
    deduped: List[Dict[str, Any]] = []
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        text = str(cand.get("text") or "").strip().lower()
        if not text or text in seen_texts:
            continue
        seen_texts.add(text)
        cand.update(requirement_candidate(cand))
        deduped.append(cand)
    return deduped

def turn_participants(values: List[str]) -> List[str]:
    participants: List[str] = []
    for value in values or []:
        name = str(value or "").strip()
        if name and name not in participants:
            participants.append(name)
    return participants

def question_contributions_for_user(contributions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    questions: List[Dict[str, Any]] = []
    for c in contributions or []:
        if not isinstance(c, dict) or c.get("agent") == "user":
            continue
        resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
        agent_action = str(resp.get("action") or "").strip().lower()
        if agent_action in QUESTION_AGENT_ACTIONS:
            questions.append(c)
    return questions

def append_unique(target: List[str], value: str) -> None:
    item = str(value or "").strip()
    if item and item not in target:
        target.append(item)

def derive_turn_memory(interviewer_question: str, user_response: str) -> Dict[str, List[str]]:
    text = f"{interviewer_question}\n{user_response}".lower()
    user = str(user_response or "").lower()
    confirmed: List[str] = []
    closed: List[str] = []
    do_not_repeat: List[str] = []

    def has_any(*tokens: str) -> bool:
        return any(token.lower() in text for token in tokens)

    def user_has_any(*tokens: str) -> bool:
        return any(token.lower() in user for token in tokens)

    user_not_care = user_has_any(
        "i don't really care",
        "i don’t really care",
        "doesn't matter",
        "does not matter",
        "not a priority",
        "not required",
        "that's fine",
        "that’s fine",
        "already listed",
        "covered",
        "no need",
        "not needed",
        "not necessary",
        "not important",
        "not relevant",
        "skip",
        "ignore",
        "不用",
        "不在意",
        "不重要",
        "不需要",
        "沒必要",
        "沒關係",
        "已經",
        "已涵蓋",
        "跳過",
    )

    confirmed_signal = user_has_any(
        "yes",
        "correct",
        "that's right",
        "that’s right",
        "exactly",
        "must",
        "need",
        "want",
        "should",
        "require",
        "expect",
        "可以",
        "正確",
        "沒錯",
        "需要",
        "希望",
        "必須",
        "要能",
        "應該",
    )

    if has_any("goal", "objective", "purpose", "why", "motivation", "目標", "目的", "動機", "原因"):
        if confirmed_signal:
            append_unique(confirmed, "user goal or requirement intent")
        if user_not_care:
            append_unique(closed, "general motivation discussion")
            append_unique(do_not_repeat, "do not re-ask general motivation unless it changes scope or priority")

    if has_any("content", "information", "field", "data", "output", "result", "report", "內容", "資訊", "欄位", "資料", "輸出", "結果"):
        if confirmed_signal:
            append_unique(confirmed, "required content, data, or output expectation")
        if user_not_care:
            append_unique(closed, "additional content or data details")
            append_unique(do_not_repeat, "do not re-ask optional content or data details unless a requirement depends on them")

    if has_any("workflow", "flow", "step", "process", "task", "scenario", "interaction", "流程", "步驟", "情境", "操作", "互動", "任務"):
        if confirmed_signal:
            append_unique(confirmed, "main workflow or interaction expectation")
        if user_not_care:
            append_unique(closed, "workflow detail discussion")
            append_unique(do_not_repeat, "do not re-ask workflow details already rejected or covered")

    if has_any("exception", "error", "fallback", "manual", "edge case", "例外", "錯誤", "失敗", "人工", "特殊情況"):
        if confirmed_signal:
            append_unique(confirmed, "exception handling or fallback expectation")
        if user_not_care:
            append_unique(closed, "exception or fallback detail")
            append_unique(do_not_repeat, "do not re-ask exception handling unless it blocks a requirement")

    if has_any("constraint", "limit", "policy", "rule", "risk", "compliance", "quality", "限制", "規則", "風險", "合規", "品質", "條件"):
        if confirmed_signal:
            append_unique(confirmed, "constraint, risk, or quality boundary")
        if user_not_care:
            append_unique(closed, "constraint or risk detail")
            append_unique(do_not_repeat, "do not re-ask constraints or risks the user has dismissed")

    if has_any("priority", "must-have", "nice-to-have", "important", "重要", "優先", "必要", "可延後"):
        if confirmed_signal:
            append_unique(confirmed, "priority or must-have boundary")
        if user_not_care:
            append_unique(closed, "priority detail")
            append_unique(do_not_repeat, "do not re-ask priority for already covered items")

    if has_any("acceptance", "criteria", "success", "measure", "metric", "standard", "驗收", "標準", "成功", "量測", "指標"):
        if confirmed_signal:
            append_unique(confirmed, "acceptance criteria or success standard")
        if user_not_care:
            append_unique(closed, "acceptance detail")
            append_unique(do_not_repeat, "do not re-ask acceptance details unless needed to make a requirement testable")

    if user_not_care and not closed:
        append_unique(closed, "rejected or low-priority discussion direction")
        append_unique(do_not_repeat, "do not repeat the rejected discussion direction")

    return {
        "confirmed_issues": confirmed,
        "closed_issues": closed,
        "do_not_repeat": do_not_repeat,
    }

def get_contribution_statement(contribution: Dict[str, Any]) -> str:
    if not isinstance(contribution, dict):
        return ""
    resp = contribution.get("response", {}) if isinstance(contribution.get("response"), dict) else {}
    return str(resp.get("statement") or "").strip()

def select_judged_action(contributions: List[Dict[str, Any]]) -> tuple[str, str]:
    for c in contributions or []:
        if not isinstance(c, dict):
            continue
        agent = str(c.get("agent") or "").strip()
        if not agent or agent == "user":
            continue
        statement = get_contribution_statement(c)
        if not statement:
            continue
        if "?" in statement or "？" in statement:
            return agent, statement
    return "", ""

def merge_elicitation_memory(
    previous: Optional[Dict[str, Any]],
    current: Dict[str, List[str]],
) -> Dict[str, List[str]]:
    merged = {
        "confirmed_issues": [],
        "closed_issues": [],
        "do_not_repeat": [],
    }
    source = previous or {}
    for key in merged:
        for value in (source.get(key) or []):
            append_unique(merged[key], str(value))
        for value in (current.get(key) or []):
            append_unique(merged[key], str(value))
    return merged

def collect_elicitation_closure_votes(
    coordinator: Any,
    artifact: Dict[str, Any],
    *,
    round_num: int,
    turn: int,
    proposer_role: str,
    recent_ask_history: List[Dict[str, Any]],
    candidate_texts: List[str],
) -> Dict[str, Any]:
    roles = ["analyst", "expert", "modeler"]
    role_focus = {
        "analyst": "需求意圖、scope、功能需求、成功標準與整體收斂是否足夠清楚",
        "expert": "領域合理性、使用者可接受性，以及是否仍有會阻礙系統成立的限制未釐清",
        "modeler": "使用流程、步驟、輸入輸出、判斷點、例外情況與人工介入是否足夠清楚",
    }
    requirements = [
        {"id": r.get("id"), "text": str(r.get("text") or "").strip()}
        for r in requirement_discussion_pool(artifact)
        if isinstance(r, dict) and str(r.get("text") or "").strip()
    ]
    votes: List[Dict[str, Any]] = []
    for role in roles:
        agent = coordinator.flow.registry.get(role)
        if not agent:
            votes.append(
                {
                    "role": role,
                    "vote": "continue",
                    "reason": "agent 未註冊，保守判定不收束。",
                    "missing_question": "",
                }
            )
            continue
        prompt = coordinator.flow.mediator_agent.closure_vote_prompt(
            role=role,
            proposer_role=proposer_role,
            role_focus=role_focus.get(role, "需求理解是否足夠清楚"),
            rough_idea=str(artifact.get("rough_idea") or "").strip(),
            requirements=requirements,
            candidate_texts=candidate_texts,
            recent_ask_history=recent_ask_history or [],
        )
        try:
            data = agent.chat_json(agent.build_direct_messages(prompt), action="elicitation_closure_vote")
        except Exception as e:
            coordinator.flow.logger.warning("elicitation 收束投票失敗（%s）: %s", role, e)
            data = {}
        vote = str((data or {}).get("vote") or "").strip().lower()
        if vote not in {"close", "continue"}:
            vote = "continue"
        votes.append(
            {
                "role": role,
                "vote": vote,
                "reason": str((data or {}).get("reason") or "").strip(),
                "missing_question": str((data or {}).get("missing_question") or "").strip(),
            }
        )

    close_count = sum(1 for row in votes if row.get("vote") == "close")
    continue_count = sum(1 for row in votes if row.get("vote") == "continue")
    approved = close_count >= 2
    summary = {
        "round": round_num,
        "turn": turn,
        "proposer_role": proposer_role,
        "approved": approved,
        "rule": "majority_2_of_3",
        "close_count": close_count,
        "continue_count": continue_count,
        "votes": votes,
    }
    artifact.setdefault("elicitation_closure_votes", []).append(summary)
    return summary

def extract_elicited_requirement_candidates(
    coordinator: Any,
    contributions: List[Dict[str, Any]],
    artifact: Dict[str, Any],
    *,
    round_num: int,
    turn: int,
) -> List[Dict[str, Any]]:
    mode = get_elicitation_mode(artifact)
    discussion_parts: List[str] = []
    interviewer_context_parts: List[str] = []
    for c in contributions:
        if not isinstance(c, dict):
            continue
        agent = c.get("agent", "?")
        resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
        statement = (resp.get("statement") or "").strip()
        if not statement:
            continue
        if mode == "oracle":
            discussion_parts.append(f"\n【{agent}】\n{statement}\n")
            continue
        if agent == "user":
            discussion_parts.append(f"\n【user】\n{statement}\n")
        elif str(agent).strip() in {"analyst", "expert", "modeler"}:
            interviewer_context_parts.append(f"\n【{agent}_question】\n{statement}\n")
    discussion_text = ""
    if mode == "main_flow" and interviewer_context_parts:
        discussion_text += "".join(interviewer_context_parts)
    discussion_text += "".join(discussion_parts)
    if not discussion_text.strip():
        return []

    existing_texts = {
        str(r.get("text") or "").strip().lower()
        for r in requirement_discussion_pool(artifact)
        if isinstance(r, dict) and r.get("text")
    }
    existing_ids = {
        str(r.get("id") or "").strip()
        for r in requirement_discussion_pool(artifact)
        if isinstance(r, dict) and r.get("id")
    }
    valid_source_stakeholders = [
        str(row.get("name") or "").strip()
        for row in artifact.get("stakeholders", []) or []
        if isinstance(row, dict) and str(row.get("name") or "").strip()
    ]

    try:
        raw = coordinator.flow.analyst_agent.extract_elicited_requirement_candidates(
            discussion_text=discussion_text,
            existing_ids=sorted(existing_ids),
            mode=mode,
            rough_idea=str(artifact.get("rough_idea") or ""),
            valid_source_stakeholders=valid_source_stakeholders,
        )
        if not isinstance(raw, list):
            return []

        results: List[Dict[str, Any]] = []
        for cand in raw:
            if not isinstance(cand, dict):
                continue
            text = str(cand.get("text") or "").strip()
            if not text or text.lower() in existing_texts:
                continue
            from agents.profile.analyst import AnalystAgent
            normalized = AnalystAgent.requirement_record(cand)
            normalized = requirement_candidate(normalized)
            results.append(normalized)
        return results
    except Exception as e:
        coordinator.flow.logger.warning("挖掘需求提取失敗: %s", e)
        return []
