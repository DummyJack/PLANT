# Handles support logic for project flow orchestration and stage execution.
import re
from typing import Any, Dict, List, Optional

from storage.requirements import (
    requirement_candidate,
    requirement_dedupe_key,
    requirement_discussion_pool,
)
from agents.profile.analyst.validation import requirement_record as url_requirement_record

ELICITATION_PHASES = [
    "initial_requirement",
    "requirement_discussion",
    "conclusion",
]
QUESTION_AGENT_ACTIONS = {"ask_user", "supplement_question"}
FINISH_AGENT_ACTION = "propose_finish"


# ========
# Defines split text by speaking as function for this module workflow.
# ========
def split_text_by_speaking_as(text: str, names: List[str], *, require_labels: bool = False) -> Dict[str, str]:
    source = str(text or "").strip()
    clean_names = [str(name or "").strip() for name in names or [] if str(name or "").strip()]
    if not source or not clean_names:
        return {}
    escaped = "|".join(re.escape(name) for name in clean_names)
    pattern = re.compile(rf"(?:^|\n)\s*【({escaped})】\s*")
    matches = list(pattern.finditer(source))
    if not matches:
        if require_labels and len(clean_names) > 1:
            return {}
        return {name: source for name in clean_names}

    parts: Dict[str, str] = {}
    for index, match in enumerate(matches):
        name = str(match.group(1) or "").strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        body = source[start:end].strip()
        body = re.sub(r"^\s*[-—]+\s*", "", body).strip()
        if name and body:
            parts[name] = body
    if require_labels:
        return {name: parts[name] for name in clean_names if name in parts}
    return {name: parts.get(name, source) for name in clean_names}


# ========
# Defines run closure vote loop function for this module workflow.
# ========
def run_closure_vote_loop(
    agent: Any,
    *,
    role: str,
    prompt: str,
) -> Dict[str, Any]:
    def build_observation(**kwargs: Any) -> Dict[str, Any]:
        return {
            "action": "elicitation_closure_vote",
            "role": role,
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs["max_iterations"],
        }

    def decide_action(
        *,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if isinstance(last_result, dict) and not last_result.get("error"):
            return {
                "action": "done",
                "params": {},
                "reasoning": "上一輪 elicitation closure vote 已完成，結束本次投票。",
            }
        return {
            "action": "elicitation_closure_vote",
            "params": {},
            "reasoning": "判斷需求擷取會議是否可以收束。",
        }

    def execute_action(*, decision: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        try:
            data = agent.chat_json(
                agent.build_direct_messages(prompt),
                action="elicitation_closure_vote",
            )
            if not isinstance(data, dict):
                raise ValueError("closure vote must return a JSON object")
            vote = str(data.get("vote") or "").strip().lower()
            if vote not in {"close", "continue"}:
                raise ValueError("closure vote must be close or continue")
            return {
                "action": decision.get("action", ""),
                "status": "success",
                "vote": vote,
                "reason": str(data.get("reason") or "").strip(),
                "missing_question": str(data.get("missing_question") or "").strip(),
                "summary": f"{role} closure vote: {vote}",
            }
        except Exception as e:
            return {
                "action": decision.get("action", ""),
                "status": "failed",
                "error": "closure_vote_invalid",
                "format_error": str(e),
                "summary": f"{role} closure vote failed",
            }

    opa = agent.run_action_loop(
        name="elicitation_closure_vote",
        context={},
        build_observation=build_observation,
        decide_action=decide_action,
        execute_action=execute_action,
    )
    trace = opa.get("opa_trace") or []
    result = dict((trace[-1].get("result") if trace else {}) or {})
    if result.get("error"):
        raise RuntimeError(result.get("format_error") or result.get("error"))
    return result


# ========
# Defines compact text function for this module workflow.
# ========
def compact_text(text: str) -> str:
    value = " ".join(str(text or "").split())
    return value

# ========
# Defines build sequential order function for this module workflow.
# ========
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

# ========
# Defines without finish proposals function for this module workflow.
# ========
def without_finish_proposals(
    conversation: List[Dict[str, Any]],
    stop_phrase: str,
) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    for c in conversation or []:
        if not isinstance(c, dict):
            continue
        if c.get("agent") != "user" and stop_phrase in get_conversation_text(c):
            continue
        resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
        if c.get("agent") != "user" and str(resp.get("action") or "").strip().lower() == FINISH_AGENT_ACTION:
            continue
        filtered.append(c)
    return filtered

# ========
# Defines get elicitation mode function for this module workflow.
# ========
def get_elicitation_mode(artifact: Dict[str, Any]) -> str:
    meta = artifact.get("meta") if isinstance(artifact, dict) else {}
    mode = str((meta or {}).get("elicitation_mode") or "").strip().lower()
    return mode if mode in {"oracle", "main_flow"} else "main_flow"

# ========
# Defines elicitation phase for turn function for this module workflow.
# ========
def elicitation_phase_for_turn(turn: int, max_turns: int) -> str:
    if turn <= 1:
        return "initial_requirement"
    return "requirement_discussion"

# ========
# Defines collect user summary function for this module workflow.
# ========
def collect_user_summary(conversation: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for c in conversation or []:
        if not isinstance(c, dict) or c.get("agent") != "user":
            continue
        text = get_conversation_text(c)
        if text:
            parts.append(text)
    return "\n".join(parts).strip()

# ========
# Defines build phase guidance function for this module workflow.
# ========
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

# ========
# Defines build recent ask history function for this module workflow.
# ========
def build_recent_ask_history(
    elicitation_trace: List[Dict[str, Any]],
    *,
    max_items: Optional[int] = None,
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
        for row in (log.get("conversation") or []):
            if not isinstance(row, dict):
                continue
            agent = str(row.get("agent") or "").strip()
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            if agent != "user" and not question_text:
                question_from = agent
                question_text = extract_first_question(text) or compact_text(text)
            elif agent == "user" and not user_response:
                user_response = compact_text(text)
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
        if max_items is not None and len(rows) >= max_items:
            break
    rows.reverse()
    return rows

# ========
# Defines extract first question function for this module workflow.
# ========
def extract_first_question(text: str) -> str:
    parts = [p.strip() for p in str(text or "").replace("\n", " ").split("。") if p.strip()]
    for p in parts:
        if "？" in p or "?" in p:
            return p
    return parts[0] if parts else ""

# ========
# Defines clean elicited reqts function for this module workflow.
# ========
def clean_elicited_reqts(
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    seen_texts: set = set()
    deduped: List[Dict[str, Any]] = []
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        text = str(cand.get("text") or "").strip()
        marker = requirement_dedupe_key(text)
        if not text or marker in seen_texts:
            continue
        seen_texts.add(marker)
        cand.update(requirement_candidate(cand))
        deduped.append(cand)
    return deduped

# ========
# Defines turn participants function for this module workflow.
# ========
def turn_participants(values: List[str]) -> List[str]:
    participants: List[str] = []
    for value in values or []:
        name = str(value or "").strip()
        if name and name not in participants:
            participants.append(name)
    return participants

# ========
# Defines user questions function for this module workflow.
# ========
def user_questions(conversation: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    questions: List[Dict[str, Any]] = []
    for c in conversation or []:
        if not isinstance(c, dict) or c.get("agent") == "user":
            continue
        resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
        action_values = []
        if isinstance(resp.get("actions"), list):
            action_values.extend(resp.get("actions") or [])
        action_values.append(resp.get("action"))
        actions = {
            str(value or "").strip().lower()
            for value in action_values
            if str(value or "").strip()
        }
        if actions & QUESTION_AGENT_ACTIONS:
            questions.append(c)
    return questions

# ========
# Defines append unique function for this module workflow.
# ========
def append_unique(target: List[str], value: str) -> None:
    item = str(value or "").strip()
    if item and item not in target:
        target.append(item)

# ========
# Defines derive turn summary function for this module workflow.
# ========
def derive_turn_summary(interviewer_question: str, user_response: str) -> Dict[str, List[str]]:
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

    if has_any("exception", "error", "manual", "edge case", "例外", "錯誤", "失敗", "人工", "特殊情況"):
        if confirmed_signal:
            append_unique(confirmed, "exception handling expectation")
        if user_not_care:
            append_unique(closed, "exception handling detail")
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

    if user_not_care and not closed:
        append_unique(closed, "rejected or low-priority discussion direction")
        append_unique(do_not_repeat, "do not repeat the rejected discussion direction")

    return {
        "confirmed_issues": confirmed,
        "closed_issues": closed,
        "do_not_repeat": do_not_repeat,
    }

# ========
# Defines get conversation text function for this module workflow.
# ========
def get_conversation_text(conversation: Dict[str, Any]) -> str:
    if not isinstance(conversation, dict):
        return ""
    resp = conversation.get("response", {}) if isinstance(conversation.get("response"), dict) else {}
    return str(resp.get("text") or "").strip()

# ========
# Defines select question function for this module workflow.
# ========
def select_question(conversation: List[Dict[str, Any]]) -> tuple[str, str]:
    for c in conversation or []:
        if not isinstance(c, dict):
            continue
        agent = str(c.get("agent") or "").strip()
        if not agent or agent == "user":
            continue
        text = get_conversation_text(c)
        if not text:
            continue
        if "?" in text or "？" in text:
            return agent, text
    return "", ""

# ========
# Defines merge turn summary function for this module workflow.
# ========
def merge_turn_summary(
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

# ========
# Defines collect closure votes function for this module workflow.
# ========
def collect_closure_votes(
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
            raise RuntimeError(f"elicitation closure vote agent 未註冊: {role}")
        prompt = coordinator.flow.mediator_agent.closure_vote_prompt(
            role=role,
            proposer_role=proposer_role,
            role_focus=role_focus.get(role, "需求理解是否足夠清楚"),
            scenario=artifact.get("scenario", ""),
            requirements=requirements,
            candidate_texts=candidate_texts,
            recent_ask_history=recent_ask_history or [],
        )
        try:
            data = run_closure_vote_loop(agent, role=role, prompt=prompt)
        except Exception as e:
            data = {
                "vote": "continue",
                "reason": f"closure vote 格式修復失敗，保守起見繼續需求擷取: {e}",
                "missing_question": "",
            }
        vote = str(data.get("vote") or "").strip().lower()
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

# ========
# Defines extract candidates function for this module workflow.
# ========
def extract_candidates(
    coordinator: Any,
    conversation: List[Dict[str, Any]],
    artifact: Dict[str, Any],
    *,
    round_num: int,
    turn: int,
) -> List[Dict[str, Any]]:
    mode = get_elicitation_mode(artifact)
    allowed_stakeholders = {
        str(row.get("name") or "").strip()
        for row in artifact.get("stakeholders", []) or []
        if isinstance(row, dict) and str(row.get("name") or "").strip()
    }
    stakeholder_types = {
        str(row.get("name") or "").strip(): str(row.get("type") or "").strip()
        for row in artifact.get("stakeholders", []) or []
        if isinstance(row, dict) and str(row.get("name") or "").strip()
    }
    stakeholder_rows: List[Dict[str, str]] = []
    row_index = 1
    pending_question = False
    pending_targets: List[str] = []
    for c in conversation:
        if not isinstance(c, dict):
            continue
        agent = c.get("agent", "?")
        resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
        text = (resp.get("text") or "").strip()
        if not text:
            continue
        if agent != "user":
            pending_question = True
            raw_targets = resp.get("target_stakeholders")
            if isinstance(raw_targets, str):
                raw_targets = [raw_targets]
            pending_targets = [
                str(name).strip()
                for name in (raw_targets or [])
                if str(name).strip() in allowed_stakeholders
            ]
            continue
        if agent == "user":
            speaking_as = resp.get("speaking_as")
            if isinstance(speaking_as, str):
                speaking_as = [speaking_as]
            names = [
                str(name).strip()
                for name in (speaking_as or [])
                if str(name).strip() in allowed_stakeholders
            ]
            if not names and len(pending_targets) == 1:
                names = list(pending_targets)
            if not names and len(allowed_stakeholders) == 1:
                names = list(allowed_stakeholders)
            if pending_question:
                start_row_index = row_index
                row_index += max(1, len(names))
            else:
                start_row_index = row_index
            text_parts = split_text_by_speaking_as(
                text,
                names,
                require_labels=len(names) > 1,
            )
            if len(names) > 1 and len(text_parts) < len(names):
                primary_name = names[0] if names else ""
                text_parts = {primary_name: text} if primary_name else {}
                names = [primary_name] if primary_name else []
            for offset, name in enumerate(names):
                source_id = f"elicit-{max(1, int(turn))}-{start_row_index + offset}"
                stakeholder_rows.append({
                    "name": name,
                    "type": stakeholder_types.get(name, ""),
                    "text": text_parts.get(name, text),
                    "source_id": source_id,
                })
            pending_question = False
            pending_targets = []
    if not stakeholder_rows:
        return []

    existing_texts = {
        str(r.get("text") or "").strip().lower()
        for r in requirement_discussion_pool(artifact)
        if isinstance(r, dict) and r.get("text")
    }
    existing_requirements = [
        {
            "id": str(r.get("id") or "").strip(),
            "text": str(r.get("text") or "").strip(),
            "stakeholder": r.get("stakeholder"),
            "source": str(r.get("source") or "").strip(),
        }
        for r in requirement_discussion_pool(artifact)
        if isinstance(r, dict) and str(r.get("text") or "").strip()
    ]
    raw = coordinator.flow.analyst_agent.extract_elicited_reqts(
        stakeholders=stakeholder_rows,
        existing_requirements=existing_requirements,
        mode=mode,
        scenario=str(artifact.get("scenario", "") or "").strip(),
        source=f"elicitation_r{max(1, int(round_num))}",
    )
    if not isinstance(raw, list):
        raise RuntimeError("elicited requirement extraction did not return a list")

    results: List[Dict[str, Any]] = []
    for cand in raw:
        if not isinstance(cand, dict):
            continue
        text = str(cand.get("text") or "").strip()
        if not text or text.lower() in existing_texts:
            continue
        normalized = url_requirement_record(cand)
        normalized = requirement_candidate(normalized)
        results.append(normalized)
    return results
