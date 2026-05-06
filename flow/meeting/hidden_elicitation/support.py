# Support helpers for hidden requirement elicitation meetings.
import json
from typing import Any, Dict, List, Optional

from agents.profile.analyst.requirements import normalize_requirement_candidate

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
            "本階段是需求訪談開場：先依訪談階段了解背景或痛點脈絡，"
            "不要直接跳到功能清單。"
        )
    if phase == "conclusion":
        return (
            "本階段是收斂確認：只有在目前需求理解已足以形成下一版 requirement set 時才輸出停止句；"
            "否則只能問一個會阻礙收斂的待補問題。"
        )
    return (
        "本階段是深入需求訪談與即時更新：參與 agent 應依自身角色檢查目前需求理解中仍缺少的背景、痛點、流程、需求、限制或確認問題，"
        "並向指定利害關係人提出可直接支援 requirement 更新的問題。"
    )

def build_recent_ask_history(
    elicitation_log: List[Dict[str, Any]],
    *,
    max_items: int = 3,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for log in reversed(elicitation_log or []):
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

def initialize_elicitation_meeting_state(
    artifact: Dict[str, Any],
    *,
    round_num: int,
    max_turns: int,
    participants: List[str],
) -> Dict[str, Any]:
    state = {
        "round": round_num,
        "standard": "practical_requirements_elicitation_meeting",
        "goal": (
            "Align the current requirement understanding, validate gaps with the user, "
            "and turn validated answers into concrete requirement updates."
        ),
        "phase_order": list(ELICITATION_PHASES),
        "phases": [
            {
                "id": "initial_requirement",
                "purpose": "Align product goal, scope, current requirement understanding, and the most important unknowns.",
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
    artifact.setdefault("elicitation_meeting", []).append(state)
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

def normalize_elicitation_candidates(
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
        if str(cand.get("type") or "").strip() == "NFR":
            ac = str(cand.get("acceptance_criteria") or "").strip()
            if ac and not any(ch.isdigit() for ch in ac):
                cand["acceptance_criteria"] = ac + "（待補可量測指標）"
            if not cand.get("metric"):
                cand["metric"] = ""
            if not cand.get("target"):
                cand["target"] = ""
        cand.update(
            normalize_requirement_candidate(
                cand,
                candidate_source=str(cand.get("candidate_source") or "elicitation"),
            )
        )
        deduped.append(cand)
    return deduped

def normalize_turn_participants(values: List[str], fallback: List[str]) -> List[str]:
    participants: List[str] = []
    for value in values or fallback or []:
        name = str(value or "").strip()
        if name and name not in participants:
            participants.append(name)
    if "user" not in participants:
        participants.append("user")
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

def _append_unique(target: List[str], value: str) -> None:
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
        "not a priority",
        "not required",
        "that's fine",
        "that’s fine",
        "already listed",
        "covered",
        "no need",
        "不用",
        "不在意",
        "沒關係",
        "已經",
    )

    if has_any("metric", "data point", "financial", "ratio", "p/e", "revenue", "earnings", "debt"):
        if user_has_any("overview", "price", "chart", "revenue", "earnings", "p/e", "debt", "volatility", "risk"):
            _append_unique(confirmed, "basic report content and key metrics")
        if user_not_care or user_has_any("don't add", "don’t add", "no additional", "nothing else", "already listed"):
            _append_unique(closed, "additional report metrics")
            _append_unique(do_not_repeat, "do not ask again whether more metrics/data points are needed")

    if has_any("side-by-side", "compare", "comparison"):
        _append_unique(confirmed, "side-by-side report comparison")

    if has_any("timestamp", "data as of", "source", "provider"):
        if has_any("timestamp", "data as of") or user_has_any("data as of", "timestamp"):
            _append_unique(confirmed, "data timestamp and source attribution")
        if has_any("provider", "api", "data source") and user_not_care:
            _append_unique(closed, "specific data provider/API preference")
            _append_unique(do_not_repeat, "do not ask for specific data provider/API preference")

    if has_any("real-time", "realtime", "delayed", "end-of-day", "update frequency"):
        if user_has_any("delayed", "end-of-day", "not real-time", "not realtime"):
            _append_unique(confirmed, "delayed or end-of-day data is acceptable")
            _append_unique(closed, "real-time data requirement")
            _append_unique(do_not_repeat, "do not re-ask real-time versus delayed data unless a contradiction appears")

    if has_any("geographic", "country", "region", "global", "localization", "language", "exchange", "us stocks"):
        if user_has_any("us stocks", "us markets", "english-only", "global", "not care", "don’t really care", "don't really care"):
            _append_unique(confirmed, "initial stock coverage and localization preference")
        if user_not_care:
            _append_unique(closed, "geography/localization details")
            _append_unique(do_not_repeat, "do not re-ask geography, localization, or country-specific features")

    if has_any("tabs", "panels", "layout", "ui pattern", "exact ui", "exact layout"):
        if user_not_care:
            _append_unique(closed, "exact UI layout pattern")
            _append_unique(do_not_repeat, "do not ask tabs/panels/exact UI pattern again")

    if has_any("workflow", "step", "search", "generate", "view", "previous", "session", "save", "history"):
        if user_has_any("search", "generate", "view", "current session", "regenerate", "run another search"):
            _append_unique(confirmed, "search-generate-view workflow")
        if user_not_care and has_any("session", "save", "history", "previously generated"):
            _append_unique(closed, "saved report history across sessions")
            _append_unique(do_not_repeat, "do not re-ask saved report history unless persistence becomes a requirement")

    return {
        "confirmed_topics": confirmed,
        "closed_topics": closed,
        "do_not_repeat": do_not_repeat,
    }

def get_contribution_statement(contribution: Dict[str, Any]) -> str:
    if not isinstance(contribution, dict):
        return ""
    resp = contribution.get("response", {}) if isinstance(contribution.get("response"), dict) else {}
    return str(resp.get("statement") or resp.get("content") or "").strip()

def select_judged_action(contributions: List[Dict[str, Any]]) -> tuple[str, str]:
    fallback_agent = ""
    fallback_statement = ""
    for c in contributions or []:
        if not isinstance(c, dict):
            continue
        agent = str(c.get("agent") or "").strip()
        if not agent or agent == "user":
            continue
        statement = get_contribution_statement(c)
        if not statement:
            continue
        if not fallback_statement:
            fallback_agent = agent
            fallback_statement = statement
        if "?" in statement or "？" in statement:
            return agent, statement
    return fallback_agent, fallback_statement

def merge_elicitation_memory(
    previous: Optional[Dict[str, Any]],
    current: Dict[str, List[str]],
) -> Dict[str, List[str]]:
    merged = {
        "confirmed_topics": [],
        "closed_topics": [],
        "do_not_repeat": [],
    }
    source = previous or {}
    for key in merged:
        for value in (source.get(key) or []):
            _append_unique(merged[key], str(value))
        for value in (current.get(key) or []):
            _append_unique(merged[key], str(value))
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
        for r in artifact.get("requirements", []) or []
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
        prompt = f"""你正在參與需求擷取會議的收束投票。本輪 {proposer_role} 已提議結束需求擷取，但必須由 Analyst / Expert / Modeler 三方投票決定是否真的收束。

# 你的角色
{role}

# 你的判斷重點
{role_focus.get(role, "需求理解是否足夠清楚")}

# 原始產品概念
{str(artifact.get("rough_idea") or "").strip()}

# 目前正式需求
{json.dumps(requirements, ensure_ascii=False, indent=2)}

# 本次需求擷取已整理出的候選需求
{json.dumps(candidate_texts, ensure_ascii=False, indent=2)}

# 最近幾輪正式提問與 user 回答
{json.dumps(recent_ask_history or [], ensure_ascii=False, indent=2)}

# 投票規則
- 如果依你的角色判斷，目前資訊已足夠讓 Analyst 整理下一版 requirement set，vote 填 close。
- 如果仍有一個會明顯影響需求正確性的關鍵問題沒問，vote 填 continue。
- 不要因為還可以問更多細節就反對收束；只有缺口會影響需求正確性或可用性時才 vote continue。
- 若 vote continue，missing_question 必須是一個可直接問 user 的單一主問題。
- 僅輸出 JSON，不要輸出 Markdown。

# 輸出 JSON
{{"vote":"close|continue","reason":"一句話理由","missing_question":"若 vote=continue，填一個建議追問；否則空字串"}}"""
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

def extract_elicitation_candidates(
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
    user_signal_count = 0
    for c in contributions:
        if not isinstance(c, dict):
            continue
        agent = c.get("agent", "?")
        resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
        statement = (resp.get("statement") or resp.get("content") or "").strip()
        if not statement:
            continue
        if mode == "oracle":
            discussion_parts.append(f"\n【{agent}】\n{statement}\n")
            continue
        if agent == "user":
            user_signal_count += 1
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
        for r in artifact.get("requirements", [])
        if isinstance(r, dict) and r.get("text")
    }
    existing_ids = {
        str(r.get("id") or "").strip()
        for r in artifact.get("requirements", [])
        if isinstance(r, dict) and r.get("id")
    }

    try:
        raw = coordinator.flow.analyst_agent.extract_elicitation_candidates(
            discussion_text=discussion_text,
            existing_ids=sorted(existing_ids),
            mode=mode,
            rough_idea=str(artifact.get("rough_idea") or ""),
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
            normalized = AnalystAgent.normalize_requirement_record(cand)
            normalized["source"] = "elicitation"
            normalized["elicitation_round"] = round_num
            normalized["elicitation_turn"] = turn
            normalized["elicitation_mode"] = mode
            normalized["elicitation_user_signal_count"] = user_signal_count
            normalized = normalize_requirement_candidate(
                normalized,
                candidate_source="elicitation",
            )
            results.append(normalized)
        return results
    except Exception as e:
        coordinator.flow.logger.warning("挖掘需求提取失敗: %s", e)
        return []
