# Hidden elicitation meeting: ask follow-up questions and extract hidden requirements.
import json
from typing import Any, Dict, List, Optional

from utils import human_setting
from flow.requirements import normalize_requirement_candidate
from utils.language import current_output_language


# ---------- elicitation helpers ----------

ELICITATION_PHASES = [
    "initial_requirement",
    "requirement_discussion",
    "conclusion",
]
QUESTION_AGENT_ACTIONS = {"ask_user", "supplement_question"}
FINISH_AGENT_ACTION = "propose_finish"


def get_elicitation_mode(artifact: Dict[str, Any]) -> str:
    meta = artifact.get("meta") if isinstance(artifact, dict) else {}
    mode = str((meta or {}).get("elicitation_mode") or "").strip().lower()
    return mode if mode in {"oracle", "main_flow"} else "main_flow"


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


def elicitation_phase_for_turn(turn: int, max_turns: int) -> str:
    if turn <= 1:
        return "initial_requirement"
    return "requirement_discussion"


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


def summarize_elicitation_meeting_conclusion(
    *,
    elicitation_log: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
    termination_reason: str,
) -> Dict[str, Any]:
    candidate_texts = [
        str(c.get("text") or "").strip()
        for c in candidates or []
        if isinstance(c, dict) and str(c.get("text") or "").strip()
    ]
    phase_counts: Dict[str, int] = {}
    for row in elicitation_log or []:
        if not isinstance(row, dict):
            continue
        phase = str(row.get("meeting_phase") or "unknown").strip() or "unknown"
        phase_counts[phase] = phase_counts.get(phase, 0) + 1
    return {
        "termination_reason": termination_reason,
        "turns": len(elicitation_log or []),
        "phase_counts": phase_counts,
        "candidate_count": len(candidate_texts),
        "candidate_preview": candidate_texts[:5],
        "ready_for_requirement_draft": bool(candidate_texts) or termination_reason in {"judge_finish", "forced_finish_at_max_turn"},
    }

def extract_first_question(text: str) -> str:
    parts = [p.strip() for p in str(text or "").replace("\n", " ").split("。") if p.strip()]
    for p in parts:
        if "？" in p or "?" in p:
            return p
    return parts[0] if parts else ""


def compact_text(text: str) -> str:
    value = " ".join(str(text or "").split())
    return value


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


def collect_user_response_summary(contributions: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for c in contributions or []:
        if not isinstance(c, dict) or c.get("agent") != "user":
            continue
        statement = get_contribution_statement(c)
        if statement:
            parts.append(statement)
    return "\n".join(parts).strip()


def normalize_turn_participants(values: List[str], fallback: List[str]) -> List[str]:
    participants: List[str] = []
    for value in values or fallback or []:
        name = str(value or "").strip()
        if name and name not in participants:
            participants.append(name)
    if "user" not in participants:
        participants.append("user")
    return participants


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


# ---------- 主流程 ----------

def run_hidden_requirement_elicitation_meeting_block(
    coordinator: Any,
    artifact: Dict[str, Any],
    round_num: int,
) -> Dict[str, Any]:
    """隱性需求挖掘會議：Mediator 規劃 -> 多輪對話 -> Analyst 結構化收尾。"""
    if not human_setting(coordinator.flow.config, "enable_elicitation", True):
        return artifact

    plan = coordinator.flow.mediator_agent.plan_elicitation_meeting(
        artifact, registry=coordinator.flow.registry
    )
    cfg_max = coordinator.flow.config.get("elicitation_max_turns")
    if cfg_max is None:
        cfg_max = 10
    max_turns = max(1, int(cfg_max))
    plan["max_turns"] = max_turns
    artifact.setdefault("elicitation_plan", plan)

    participants = plan.get("participants") or ["analyst", "expert", "modeler", "user"]
    interviewers = plan.get("interviewers") or [p for p in participants if p != "user"]
    meeting_state = initialize_elicitation_meeting_state(
        artifact,
        round_num=round_num,
        max_turns=max_turns,
        participants=participants,
    )
    previous_turn_summary: Optional[Dict[str, Any]] = None

    all_candidates: List[Dict[str, Any]] = []
    elicitation_log: List[Dict[str, Any]] = []
    termination_reason = "max_turns_reached"
    stop_phrase = (
        "I have gathered enough information"
        if current_output_language() == "en"
        else "我已蒐集足夠資訊"
    )

    def append_finish_turn(final_turn: int, final_agent: str) -> None:
        final_recent_ask_history = build_recent_ask_history(elicitation_log, max_items=3)
        final_statement = stop_phrase
        final_contributions = [
            {
                "agent": final_agent,
                "response": {"statement": final_statement, "action": FINISH_AGENT_ACTION},
            }
        ]
        final_new_candidates = extract_elicitation_candidates(
            coordinator, final_contributions, artifact, round_num=round_num, turn=final_turn
        )
        if final_new_candidates:
            all_candidates.extend(final_new_candidates)
        final_turn_log = {
            "round": round_num,
            "turn": final_turn,
            "meeting_phase": "conclusion",
            "topic_id": f"ELICIT-R{round_num}-T{final_turn}",
            "contributions_count": len(final_contributions),
            "contributions": [{"agent": final_agent, "statement": final_statement, "action": FINISH_AGENT_ACTION}],
            "discussion_mode": "sequential",
            "participants": [final_agent],
            "speaking_order": [final_agent],
            "mode_strategy": "forced_finish",
            "target_stakeholders": [],
            "judged_action_agent": final_agent,
            "judged_action": final_statement,
            "recent_ask_history": final_recent_ask_history,
            "new_candidates_count": len(final_new_candidates),
            "new_candidate_texts": [
                str(c.get("text") or "").strip()
                for c in final_new_candidates
                if isinstance(c, dict) and str(c.get("text") or "").strip()
            ],
            "post_meeting_analysis": (
                f"Finish turn: extracted {len(final_new_candidates)} candidate(s) after stop decision."
            ),
            "forced_finish": True,
        }
        elicitation_log.append(final_turn_log)

    for turn in range(1, max_turns):
        meeting_phase = elicitation_phase_for_turn(turn, max_turns)
        phase_guidance = build_phase_guidance(meeting_phase)
        recent_ask_history = build_recent_ask_history(elicitation_log, max_items=3)
        elicitation_memory = {
            "confirmed_topics": (previous_turn_summary or {}).get("confirmed_topics", []),
            "closed_topics": (previous_turn_summary or {}).get("closed_topics", []),
            "do_not_repeat": (previous_turn_summary or {}).get("do_not_repeat", []),
        }
        turn_strategy = coordinator.flow.mediator_agent.decide_elicitation_turn_strategy(
            artifact=artifact,
            turn=turn,
            max_turns=max_turns,
            default_participants=participants,
            default_speaking_order=interviewers + ["user"],
            default_mode="sequential",
            previous_turn_summary=previous_turn_summary,
            recent_ask_history=recent_ask_history,
        )
        turn_participants = normalize_turn_participants(
            turn_strategy.get("participants") or [],
            participants,
        )
        forced_turn_mode = str(
            ((artifact.get("meta") or {}).get("force_elicitation_discussion_mode") or "")
        ).strip().lower()
        turn_mode = str(turn_strategy.get("discussion_mode") or "sequential").strip().lower()
        if forced_turn_mode:
            turn_mode = forced_turn_mode
        if turn_mode not in {"sequential", "simultaneous"}:
            turn_mode = "sequential"
        meeting_phase = str(turn_strategy.get("meeting_phase") or meeting_phase).strip() or meeting_phase
        if meeting_phase not in set(ELICITATION_PHASES):
            meeting_phase = elicitation_phase_for_turn(turn, max_turns)
        phase_guidance = build_phase_guidance(meeting_phase)
        turn_goal = str(turn_strategy.get("goal") or "").strip()
        target_stakeholders = [
            str(x).strip()
            for x in (turn_strategy.get("target_stakeholders") or [])
            if str(x).strip()
        ]

        req_summary = json.dumps(
            [
                {"id": r.get("id"), "text": (r.get("text") or "")}
                for r in artifact.get("requirements", [])
                if isinstance(r, dict)
            ],
            ensure_ascii=False,
        )
        scope_summary = json.dumps(artifact.get("scope", {}) or {}, ensure_ascii=False)
        prev_text = ""
        if all_candidates:
            prev_text = "\n已挖掘出的候選需求：\n" + json.dumps(
                [{"text": c.get("text", "")} for c in all_candidates],
                ensure_ascii=False,
            )

        topic = {
            "id": f"ELICIT-R{round_num}-T{turn}",
            "title": f"隱性需求挖掘（Round {round_num} 第 {turn} 輪）",
            "description": (
                f"原始產品概念：{str(artifact.get('rough_idea') or '').strip()}\n\n"
                f"本輪會議階段：{meeting_phase}\n"
                f"階段指引：{phase_guidance}\n\n"
                f"本輪發言模式：{turn_mode}\n"
                f"本輪訪談目標：{turn_goal or '依目前缺口提出最值得確認的問題'}\n"
                f"本輪指定回答身份：{json.dumps(target_stakeholders, ensure_ascii=False)}\n\n"
                "這是一場實務需求訪談，不是單純訪談或自由閒聊。\n"
                "請依本輪缺口類型找出最值得確認的一個問題。\n"
                "你的目標是從 User 的回答中驗證、修正或補充尚未被明確記錄的需求。\n"
                "所有追問與候選需求都必須直接服務於原始產品概念；不得泛化成無關的企業資料管理、內部審批或需求工程流程。\n"
                "每輪問題都應先基於目前理解定位缺口，再向 User 確認一個最重要的不確定點。\n"
                "不要把會議變成閒聊或泛問；每個問題都必須能支援產生或修正一條 requirement。\n"
                "\n"
                f"目前初步 scope（可被 User 修正，不代表最終範圍）：\n{scope_summary}\n"
                "\n"
                f"目前已有需求：\n{req_summary}\n"
                f"{prev_text}\n\n"
                f"本輪避免重複的訪談記憶：\n{json.dumps(elicitation_memory, ensure_ascii=False)}\n\n"
                "請不要重複已有需求，專注驗證目前需求理解並挖掘新的隱性需求。\n"
                "若本輪是逐一發言，User 必須最後回答；若本輪是同時發言，User 會逐題回答各 agent 的問題。"
            ),
            "category": "open_question",
            "participants": turn_participants,
            "discussion_mode": turn_mode,
            "speaking_order": [],
            "source_ids": [],
            "rough_idea": artifact.get("rough_idea", ""),
            "meeting_phase": meeting_phase,
            "phase_guidance": phase_guidance,
            "meeting_goal": turn_goal,
            "target_stakeholders": target_stakeholders,
            "agent_actions": turn_strategy.get("agent_actions") or {},
            "elicitation_memory": elicitation_memory,
            "recent_ask_history": recent_ask_history,
        }
        contributions: List[Dict[str, Any]] = []
        snapshot = coordinator.flow.mediator_agent.build_artifact_snapshot(artifact)
        user_agent = coordinator.flow.registry.get("user")
        if turn_mode == "simultaneous":
            interviewer_participants = [p for p in turn_participants if p != "user"]
            interviewer_topic = {
                **topic,
                "participants": interviewer_participants,
                "speaking_order": [],
                "answer_all_interviewer_questions": False,
                "agent_actions": turn_strategy.get("agent_actions") or {},
            }
            if interviewer_participants:
                contributions.extend(
                    coordinator.flow.mediator_agent.moderate_simultaneous(
                        interviewer_topic, coordinator.flow.registry, artifact=artifact
                    )
                )
            record_speaking_order = interviewer_participants + ["user"]
            user_answer_all_questions = True
        else:
            record_speaking_order = build_sequential_order(
                turn_strategy.get("speaking_order") or [],
                turn_participants,
            )
            interviewer_order = [p for p in record_speaking_order if p != "user"]
            topic["speaking_order"] = interviewer_order
            contributions, _ = coordinator.flow.mediator_agent.moderate_sequential(
                topic, coordinator.flow.registry, artifact=artifact
            )
            user_answer_all_questions = False

        interviewer_contributions = list(contributions)
        interviewer_finish = False
        closure_vote: Dict[str, Any] = {}
        finish_proposer, finish_statement = find_finish_proposal(
            interviewer_contributions,
            stop_phrase,
        )
        effective_contributions = list(interviewer_contributions)
        if finish_statement:
            closure_vote = collect_elicitation_closure_votes(
                coordinator,
                artifact,
                round_num=round_num,
                turn=turn,
                proposer_role=finish_proposer or "analyst",
                recent_ask_history=recent_ask_history,
                candidate_texts=[
                    str(c.get("text") or "").strip()
                    for c in all_candidates
                    if isinstance(c, dict) and str(c.get("text") or "").strip()
                ],
            )
            if closure_vote.get("approved"):
                coordinator.flow.logger.info(
                    "  收束投票通過：close=%s continue=%s",
                    closure_vote.get("close_count"),
                    closure_vote.get("continue_count"),
                )
                interviewer_finish = True
                effective_contributions = [
                    {
                        "agent": finish_proposer or "analyst",
                        "response": {
                            "statement": stop_phrase,
                            "content": stop_phrase,
                            "action": FINISH_AGENT_ACTION,
                        },
                    }
                ]
            else:
                coordinator.flow.logger.info(
                    "  收束投票未通過：close=%s continue=%s，本輪後繼續追問",
                    closure_vote.get("close_count"),
                    closure_vote.get("continue_count"),
                )
                effective_contributions = without_finish_proposals(
                    interviewer_contributions,
                    stop_phrase,
                )

        user_question_contributions = question_contributions_for_user(effective_contributions)
        judged_action_agent, judged_statement = select_judged_action(user_question_contributions)
        judge_action_type = ""
        if interviewer_finish:
            judged_action_agent = finish_proposer or judged_action_agent or "analyst"
            judged_statement = stop_phrase
        if judged_statement and user_agent and hasattr(user_agent, "judge_interviewer_action_type"):
            try:
                judge_action_type = str(
                    user_agent.judge_interviewer_action_type(judged_statement)
                ).strip().lower()
            except Exception as e:
                coordinator.flow.logger.warning("  finish 判定失敗（interviewer）: %s", e)
        if stop_phrase in judged_statement:
            interviewer_finish = True
            judge_action_type = "finish"

        contributions = list(effective_contributions)
        if user_agent and not interviewer_finish and judged_statement and user_question_contributions:
            try:
                user_topic = {
                    **topic,
                    "id": f"{topic['id']}-USER",
                    "title": f"{topic['title']}｜User 回答",
                    "participants": ["user"],
                    "speaking_order": ["user"],
                    "discussion_mode": "sequential",
                    "answer_all_interviewer_questions": bool(user_answer_all_questions),
                }
                user_response = coordinator.flow.mediator_agent.collect_topic_response(
                    user_agent,
                    user_topic,
                    previous_responses=user_question_contributions,
                    artifact_snapshot=snapshot,
                )
                contributions.append(
                    {
                        "agent": "user",
                        "response": user_response if isinstance(user_response, dict) else {"content": str(user_response)},
                    }
                )
            except Exception as e:
                coordinator.flow.logger.warning("User 回答失敗: %s", e)
                contributions.append({"agent": "user", "response": {"content": f"（回答失敗: {e}）"}})
        elif finish_statement and not interviewer_finish and not judged_statement:
            judge_action_type = "finish_rejected_by_vote"

        record_contributions = list(contributions)
        new_candidates = extract_elicitation_candidates(
            coordinator, contributions, artifact, round_num=round_num, turn=turn
        )
        revealed_ids = {
            str(rid)
            for c in contributions
            if isinstance(c, dict)
            and c.get("agent") == "user"
            and isinstance(c.get("response"), dict)
            for rid in (c.get("response", {}).get("oracle_revealed_ids") or [])
            if rid
        }
        contribution_rows: List[Dict[str, Any]] = []
        for c in record_contributions:
            if not isinstance(c, dict):
                continue
            agent_name = str(c.get("agent") or "").strip()
            resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
            statement = str(resp.get("statement") or resp.get("content") or "").strip()
            if not agent_name or not statement:
                continue
            row = {"agent": agent_name, "statement": statement}
            agent_action = str(resp.get("action") or "").strip()
            action_focus = str(resp.get("action_focus") or "").strip()
            if agent_action:
                row["action"] = agent_action
            if action_focus:
                row["action_focus"] = action_focus
            contribution_rows.append(row)

        should_stop_after_this_turn = bool(interviewer_finish)
        stop_reason_after_this_turn = "judge_finish" if interviewer_finish else "judge_continue"

        turn_log = {
            "round": round_num,
            "turn": turn,
            "meeting_phase": meeting_phase,
            "phase_guidance": phase_guidance,
            "topic_id": topic["id"],
            "contributions_count": len(contribution_rows),
            "contributions": contribution_rows,
            "discussion_mode": turn_mode,
            "participants": turn_participants,
            "speaking_order": record_speaking_order,
            "mode_strategy": "mediator",
            "target_stakeholders": target_stakeholders,
            "agent_actions": turn_strategy.get("agent_actions") or {},
            "goal": turn_goal,
            "elicitation_memory_before_turn": elicitation_memory,
            "judged_action_agent": judged_action_agent,
            "judged_action": judged_statement,
            "judge_action_type": judge_action_type,
            "judge_finish": interviewer_finish,
            "closure_vote": closure_vote,
            "recent_ask_history": recent_ask_history,
            "new_candidates_count": len(new_candidates),
            "new_candidate_texts": [
                str(c.get("text") or "").strip()
                for c in new_candidates
                if isinstance(c, dict) and str(c.get("text") or "").strip()
            ],
            "post_meeting_analysis": (
                f"Turn summary: extracted {len(new_candidates)} new candidate(s); "
                f"revealed {len(revealed_ids)} implicit requirement id(s)."
            ),
        }
        elicitation_log.append(turn_log)
        meeting_state.setdefault("turns", []).append(
            {
                "turn": turn,
                "phase": meeting_phase,
                "discussion_mode": turn_mode,
                "participants": list(turn_participants),
                "speaking_order": list(record_speaking_order),
                "target_stakeholders": list(target_stakeholders),
                "agent_actions": dict(turn_strategy.get("agent_actions") or {}),
                "judged_action_agent": judged_action_agent,
                "new_candidates_count": len(new_candidates),
                "revealed_ids_count": len(revealed_ids),
                "judge_finish": interviewer_finish,
                "closure_vote": closure_vote,
            }
        )

        if new_candidates:
            all_candidates.extend(new_candidates)

        user_response_for_memory = collect_user_response_summary(contributions)
        current_memory = derive_turn_memory(judged_statement, user_response_for_memory)
        merged_memory = merge_elicitation_memory(previous_turn_summary, current_memory)
        turn_log["elicitation_memory_after_turn"] = merged_memory

        previous_turn_summary = {
            "turn": turn,
            "meeting_phase": meeting_phase,
            "discussion_mode": turn_mode,
            "participants": list(turn_participants),
            "target_stakeholders": list(target_stakeholders),
            "agent_actions": dict(turn_strategy.get("agent_actions") or {}),
            "judged_action_agent": judged_action_agent,
            "judged_action": judged_statement,
            "new_candidates_count": len(new_candidates),
            "revealed_ids_count": len(revealed_ids),
            "speaking_order": list(record_speaking_order),
            "closure_vote": closure_vote,
            **merged_memory,
        }

        user_statement = ""
        user_action_types: List[str] = []
        user_is_relevant = False
        user_revealed_ids_set: set[str] = set()
        for c in contributions:
            if not isinstance(c, dict) or c.get("agent") != "user":
                continue
            resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
            user_statement = str(resp.get("statement") or resp.get("content") or "").strip()
            action_type = str(resp.get("oracle_action_type") or "").strip()
            if action_type:
                user_action_types.append(action_type)
            user_is_relevant = user_is_relevant or bool(resp.get("oracle_is_relevant", False))
            for rid in (resp.get("oracle_revealed_ids") or []):
                rid_s = str(rid).strip()
                if rid_s:
                    user_revealed_ids_set.add(rid_s)
        user_revealed_ids = sorted(user_revealed_ids_set)
        user_action_type = user_action_types[-1] if user_action_types else "unknown"
        elicitation_mode = get_elicitation_mode(artifact)
        total_requirements = len(
            (getattr(user_agent, "current_task", {}) or {}).get("Implicit Requirements", []) or []
        )
        revealed_total = len(
            {
                str(rid)
                for tr in (getattr(user_agent, "oracle_trace", []) or [])
                if isinstance(tr, dict)
                for rid in (tr.get("revealed_ids") or [])
                if rid
            }
        )
        remaining_total = max(0, total_requirements - revealed_total)
        ratio = (revealed_total / total_requirements) if total_requirements > 0 else 0.0
        coordinator.flow.logger.info("[輪次 %s]", turn)
        action_line = judged_statement[:120] + ("..." if len(judged_statement) > 120 else "")
        coordinator.flow.logger.info("  動作類型：%s", user_action_type or "unknown")
        coordinator.flow.logger.info("  與隱式需求相關：%s", user_is_relevant)
        if elicitation_mode == "oracle":
            coordinator.flow.logger.info("  已取得的需求：%s", user_revealed_ids)
        display_participants = [p for p in turn_participants if p != "user"]
        plant_line_parts = []
        if interviewer_finish:
            display_participants = [judged_action_agent or "analyst"]
        else:
            plant_line_parts.append(f"mode={turn_mode}")
        plant_line_parts.append("participants=%s" % (",".join(display_participants) or "-"))
        if not interviewer_finish and turn_mode != "simultaneous" and record_speaking_order:
            plant_line_parts.append("speaker_order=%s" % ",".join(record_speaking_order))
        coordinator.flow.logger.info(
            "Plant: %s | %s",
            " | ".join(plant_line_parts),
            action_line or "(no statement)",
        )
        if user_statement:
            coordinator.flow.logger.info(
                "  User: %s", user_statement
            )
        if elicitation_mode == "oracle":
            coordinator.flow.logger.info(
                "  觀察：總需求=%s，剩餘=%s，取得比例=%.2f%%",
                total_requirements,
                remaining_total,
                ratio * 100.0,
            )
        else:
            cumulative_candidates = len(all_candidates) + len(new_candidates)
            preview = [
                str(c.get("text") or "").strip()
                for c in new_candidates[:3]
                if isinstance(c, dict) and str(c.get("text") or "").strip()
            ]
            coordinator.flow.logger.info(
                "  觀察：new_candidates=%s，cumulative_candidates=%s",
                len(new_candidates),
                cumulative_candidates,
            )
            if preview:
                coordinator.flow.logger.info("  新候選需求：%s", preview)
        if should_stop_after_this_turn:
            termination_reason = stop_reason_after_this_turn
            if stop_reason_after_this_turn == "forced_finish_at_max_turn":
                coordinator.flow.logger.info("  停止：本輪完成後已達最後一輪，以 finish action 收斂")
            else:
                coordinator.flow.logger.info(
                    "  停止：本輪完成後，judge 判定為 finish（reason=%s）",
                    stop_reason_after_this_turn,
                )
            break

    if termination_reason == "max_turns_reached":
        # 達上限時，最後一輪直接進入 finish 收尾，不再執行 user 對話。
        final_turn = max_turns
        final_agent = str((previous_turn_summary or {}).get("judged_action_agent") or "analyst").strip() or "analyst"
        append_finish_turn(final_turn, final_agent)
        coordinator.flow.logger.info("[輪次 %s]", final_turn)
        coordinator.flow.logger.info("  動作類型：finish")
        coordinator.flow.logger.info(
            "Plant: participants=%s | %s",
            final_agent,
            stop_phrase,
        )
        coordinator.flow.logger.info("  停止：達到最後一輪，直接進入 finish 收尾（不再執行 user 對話）")
        termination_reason = "forced_finish_at_max_turn"

    all_candidates = normalize_elicitation_candidates(all_candidates)
    meeting_state["conclusion"] = summarize_elicitation_meeting_conclusion(
        elicitation_log=elicitation_log,
        candidates=all_candidates,
        termination_reason=termination_reason,
    )

    artifact.setdefault("elicitation_log", []).extend(elicitation_log)
    artifact.setdefault("elicitation_candidates", []).extend(all_candidates)
    artifact["elicitation_termination_reason"] = termination_reason

    coordinator.flow.store.save_artifact(artifact)
    return artifact
