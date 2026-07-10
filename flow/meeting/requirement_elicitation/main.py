# Handles main logic for project flow orchestration and stage execution.
import json
import re
from typing import Any, Dict, List, Optional

from storage.requirements import requirement_discussion_pool
from utils import meeting_setting
from utils.language import current_output_language

from .support import (
    ELICITATION_PHASES,
    FINISH_AGENT_ACTION,
    build_phase_guidance,
    build_recent_ask_history,
    build_sequential_order,
    collect_closure_votes,
    collect_user_summary,
    derive_turn_summary,
    elicitation_phase_for_turn,
    extract_candidates,
    merge_turn_summary,
    clean_elicited_reqts,
    split_text_by_speaking_as,
    turn_participants as normalized_turn_participants,
    user_questions,
    select_question,
    without_finish_proposals,
)


def feedback_has_rows(artifact: Dict[str, Any]) -> bool:
    feedback = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
    for section in ("findings", "constraints", "risks", "recommendations"):
        if any(isinstance(row, dict) for row in (feedback.get(section) or [])):
            return True
    return False


# ========
# Defines meeting rows function for this module workflow.
# ========
def meeting_rows(
    elicitation_trace: List[Dict[str, Any]],
    *,
    round_num: int,
) -> Dict[str, List[Dict[str, str]]]:
    try:
        round_key = f"r{max(1, int(round_num))}"
    except (TypeError, ValueError):
        round_key = "r1"
    rows: List[Dict[str, str]] = []

    def turn_number(turn: Dict[str, Any], default_turn: int) -> int:
        try:
            value = int(turn.get("turn") or default_turn)
        except (TypeError, ValueError):
            value = default_turn
        return max(1, value)

    def row_id(turn_no: int, row_no: int = 1) -> str:
        return f"elicit-{turn_no}-{row_no}"

    def row_text(row: Dict[str, Any]) -> str:
        text = str(row.get("text") or "").strip()
        if text:
            return text
        response = row.get("response") if isinstance(row.get("response"), dict) else {}
        return str(response.get("text") or "").strip()

    def answer_rows(row: Dict[str, Any]) -> List[Dict[str, str]]:
        text = row_text(row)
        if not text:
            return []
        speaking_as = row.get("speaking_as") or []
        if isinstance(speaking_as, str):
            speaking_as = [speaking_as]
        keys = [str(name).strip() for name in speaking_as if str(name).strip()]
        if not keys:
            return []
        parts = split_text_by_speaking_as(text, keys, require_labels=len(keys) > 1)
        if len(keys) > 1 and len(parts) < len(keys):
            return []
        return [{key: parts.get(key, text)} for key in keys]

    for index, turn in enumerate(elicitation_trace or [], 1):
        if not isinstance(turn, dict):
            continue
        turn_no = turn_number(turn, index)
        if bool(turn.get("forced_finish")):
            continue
        if str(turn.get("discussion_mode") or "").strip() == "simultaneous":
            turn_row_index = 1

            def next_turn_row_id() -> str:
                nonlocal turn_row_index
                value = row_id(turn_no, turn_row_index)
                turn_row_index += 1
                return value

            pending_questions: List[Dict[str, str]] = []
            for conversation in turn.get("conversation", []) or []:
                if not isinstance(conversation, dict):
                    continue
                agent = str(conversation.get("agent") or "").strip()
                text = row_text(conversation)
                if not agent or not text:
                    continue
                if agent != "user":
                    pending_question = {agent: text}
                    if pending_question not in pending_questions:
                        pending_questions.append(pending_question)
                    continue
                if pending_questions:
                    pending_question = pending_questions.pop(0)
                    answers = answer_rows(conversation)
                    if answers:
                        for answer in answers:
                            rows.append(
                                {
                                    "id": next_turn_row_id(),
                                    **pending_question,
                                    **answer,
                                }
                            )
            continue
        question = str(turn.get("judged_action") or "").strip()
        question_agent = str(turn.get("judged_action_agent") or "").strip()
        answer = ""
        answer_row_maps: List[Dict[str, str]] = []
        for row in turn.get("conversation", []) or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("agent") or "").strip() != "user":
                continue
            answer = row_text(row)
            answer_row_maps = answer_rows(row)
            break
        if bool(turn.get("judge_finish")) and not answer:
            continue
        if not question and not answer:
            continue
        if answer_row_maps and answer:
            for row_no, answer_map in enumerate(answer_row_maps, 1):
                row = {"id": row_id(turn_no, row_no)}
                if question_agent and question:
                    row[question_agent] = question
                row.update(answer_map)
                rows.append(row)
    return {round_key: rows}

# ========
# Defines valid stakeholder names function for this module workflow.
# ========
def valid_stakeholder_names(artifact: Dict[str, Any]) -> set[str]:
    return {
        str(row.get("name") or "").strip()
        for row in artifact.get("stakeholders", []) or []
        if isinstance(row, dict) and str(row.get("name") or "").strip()
    }

# ========
# Defines valid targets function for this module workflow.
# ========
def valid_targets(
    values: Any,
    *,
    allowed_names: set[str],
) -> List[str]:
    if isinstance(values, str):
        raw_values = [values]
    elif isinstance(values, list):
        raw_values = values
    else:
        raw_values = []
    out: List[str] = []
    for value in raw_values:
        name = str(value or "").strip()
        if name and name in allowed_names and name not in out:
            out.append(name)
    return out


# ========
# Defines validated elicitation answer function for this module workflow.
# ========
def validated_elicitation_answer(
    response: Any,
    *,
    question_targets: List[str],
) -> Dict[str, Any]:
    if not isinstance(response, dict):
        raise RuntimeError("Requirement elicitation user answer 必須是 JSON object")
    text = str(response.get("text") or response.get("content") or "").strip()
    if not text:
        raise RuntimeError("Requirement elicitation user answer 缺少回答內容")
    speaking_as = response.get("speaking_as")
    if isinstance(speaking_as, str):
        speaking_as = [speaking_as]
    if not isinstance(speaking_as, list):
        speaking_as = []
    valid_speakers = [
        str(name).strip()
        for name in speaking_as
        if str(name).strip() and str(name).strip() in set(question_targets)
    ]
    if not valid_speakers and question_targets:
        valid_speakers = list(question_targets)
    if not valid_speakers:
        raise RuntimeError(
            "Requirement elicitation user answer 缺少有效 speaking_as，"
            f"必須對應 target_stakeholders: {question_targets}"
        )
    return {
        **response,
        "text": text,
        "speaking_as": list(dict.fromkeys(valid_speakers)),
    }


# ========
# Defines log elicitation turn function for this module workflow.
# ========
def log_elicitation_turn(
    logger: Any,
    *,
    round_num: int,
    turn: int,
    meeting_phase: str,
    conversation_rows: List[Dict[str, Any]],
    new_candidates: List[Dict[str, Any]],
    cumulative_candidates: int,
) -> None:
    pending_question: Optional[Dict[str, Any]] = None
    for row in conversation_rows:
        agent = str(row.get("agent") or "").strip()
        text = str(row.get("text") or "").strip()
        if not agent or not text:
            continue
        if agent != "user":
            targets = [
                str(name).strip()
                for name in (row.get("target_stakeholders") or [])
                if str(name).strip()
            ]
            target_label = "、".join(targets) if targets else "stakeholder"
            logger.info("  %s → %s：%s", agent.capitalize(), target_label, text)
            pending_question = {"agent": agent, "targets": targets}
            continue
        speaking_as = [
            str(name).strip()
            for name in (row.get("speaking_as") or [])
            if str(name).strip()
        ]
        if not speaking_as and pending_question:
            pending_question = None
            continue
        if not speaking_as:
            continue
        logger.info("  %s：%s", "、".join(speaking_as), text)
        pending_question = None
    logger.step_completed(
        "elicitation",
        "elicitation.extract_requirements",
        "候選需求",
        agent="analyst",
        message=f"本輪 {len(new_candidates)} 筆，累計 {cumulative_candidates} 筆",
        output_path="artifact/requirements.json",
    )
    preview = [
        str(c.get("text") or "").strip()
        for c in new_candidates
        if isinstance(c, dict) and str(c.get("text") or "").strip()
    ]
    if preview:
        logger.info("  候選需求：%s", preview)


def emit_elicitation_speech(
    logger: Any,
    row: Dict[str, Any],
) -> None:
    if not isinstance(row, dict):
        return
    agent = str(row.get("agent") or "").strip()
    response = row.get("response") if isinstance(row.get("response"), dict) else {}
    text = str(response.get("text") or "").strip()
    if not agent or not text:
        return
    if agent == "user":
        speaking_as = response.get("speaking_as")
        if isinstance(speaking_as, str):
            speaking_as = [speaking_as]
        title = "、".join(
            str(name).strip()
            for name in (speaking_as or [])
            if str(name).strip()
        ) or "User"
        logger.step_delta(
            "elicitation",
            "elicitation.run_meeting",
            {
                "title": title,
                "text": text,
            },
            delta_type="speech",
            agent="user",
        )
        return
    targets = response.get("target_stakeholders")
    if isinstance(targets, str):
        targets = [targets]
    target_label = "、".join(
        str(name).strip()
        for name in (targets or [])
        if str(name).strip()
    ) or "stakeholder"
    if target_label and target_label != "stakeholder":
        text = re.sub(rf"^\s*{re.escape(target_label)}\s*[：:]\s*", "", text).strip()
    logger.step_delta(
        "elicitation",
        "elicitation.run_meeting",
        {
            "title": target_label,
            "text": text,
        },
        delta_type="speech",
        agent=agent,
    )


# ========
# Defines log turn plan function for this module workflow.
# ========
def log_turn_plan(
    logger: Any,
    *,
    turn: int,
    turn_strategy: Dict[str, Any],
) -> None:
    participants = [
        str(name).strip()
        for name in (turn_strategy.get("participants") or [])
        if str(name).strip()
    ]
    actions = turn_strategy.get("actions") or {}
    logger.info("[輪次 %s]", turn)
    goal = str(turn_strategy.get("goal") or "").strip() or "釐清本輪最重要且尚未充分探索的方向"
    participants_order_parts = []
    if isinstance(actions, dict) and actions:
        for agent, action_info in actions.items():
            if isinstance(action_info, dict):
                action = str(action_info.get("action") or "").strip()
            else:
                action = str(action_info or "").strip()
            if action in {"ask_user", "supplement_question"}:
                participants_order_parts.append(f"{agent} → user")
    logger.step_completed(
        "elicitation",
        "elicitation.prepare_meeting",
        "Plan",
        agent="mediator",
        message=(
            f"elicit plan：participants: {', '.join(participants) if participants else '無'} | "
            f"participants_order: {'; '.join(participants_order_parts) if participants_order_parts else '無'} | "
            f"goal: {goal}"
        ),
    )


# ========
# Defines planned targets for agent function for this module workflow.
# ========
def planned_targets_for_agent(
    turn_strategy: Dict[str, Any],
    agent: str,
    *,
    allowed_names: set[str],
) -> List[str]:
    action_info = (turn_strategy.get("actions") or {}).get(agent)
    if not isinstance(action_info, dict):
        return []
    return valid_targets(action_info.get("target_stakeholders"), allowed_names=allowed_names)


# ========
# Defines finish agents from conversation function for this module workflow.
# ========
def finish_agents_from_conversation(
    conversation: List[Dict[str, Any]],
    stop_phrase: str,
) -> List[str]:
    agents: List[str] = []
    for row in conversation or []:
        if not isinstance(row, dict):
            continue
        agent = str(row.get("agent") or "").strip()
        if not agent or agent == "user":
            continue
        response = row.get("response") if isinstance(row.get("response"), dict) else {}
        action = str(response.get("action") or "").strip().lower()
        text = str(response.get("text") or response.get("content") or "").strip()
        if action == FINISH_AGENT_ACTION or (text and stop_phrase in text):
            if agent not in agents:
                agents.append(agent)
    return agents


# ========
# Defines default plan function for this module workflow.
# ========
def default_plan(coordinator: Any) -> Dict[str, Any]:
    registry = getattr(coordinator.flow, "registry", None)
    exclude = {"mediator", "documentor", "user"}
    if registry:
        interviewers = [name for name in registry.get_names() if name not in exclude]
    else:
        interviewers = ["analyst", "expert", "modeler"]
    participants = interviewers + ["user"]
    return {
        "participants": participants,
        "interviewers": interviewers,
    }


# ========
# Defines run elicitation function for this module workflow.
# ========
def run_elicitation(
    coordinator: Any,
    artifact: Dict[str, Any],
    round_num: int,
) -> Dict[str, Any]:
    if not meeting_setting(coordinator.flow.config, "elicitation", True):
        return artifact

    cfg_max = coordinator.flow.config.get("elicitation_max_turns")
    if cfg_max is None:
        cfg_max = 10
    max_turns = max(1, int(cfg_max))
    plan = default_plan(coordinator)
    artifact.setdefault("elicitation", {})["plan"] = {
        "round_limit": max_turns,
        "participants": plan.get("participants", []) or [],
        "mode": "simultaneous",
    }
    participants = plan.get("participants") or []
    if not participants or "user" not in participants:
        raise RuntimeError("Requirement elicitation plan 未產生有效 participants，或未包含 user")
    interviewers = plan.get("interviewers") or []
    if not interviewers:
        raise RuntimeError("Requirement elicitation plan 未產生有效 interviewers")
    allowed_stakeholders = valid_stakeholder_names(artifact)
    previous_turn_summary: Optional[Dict[str, Any]] = None

    all_candidates: List[Dict[str, Any]] = []
    elicitation_trace: List[Dict[str, Any]] = []
    termination_reason = "max_turns_reached"
    stop_phrase = (
        "I have gathered enough information"
        if current_output_language() == "en"
        else "我已蒐集足夠資訊"
    )
    forced_finish_phrase = (
        "This meeting is over."
        if current_output_language() == "en"
        else "本次會議結束。"
    )
    display_round_num = max(1, int(round_num))

    def append_finish_turn(
        final_turn: int,
        final_agent: Any,
        final_text: str,
        *,
        forced_finish: bool = True,
    ) -> None:
        final_recent_ask_history = build_recent_ask_history(elicitation_trace)
        final_agents = (
            [
                str(agent or "").strip()
                for agent in final_agent
                if str(agent or "").strip()
            ]
            if isinstance(final_agent, list)
            else [str(final_agent or "").strip()]
        )
        final_agents = list(dict.fromkeys(agent for agent in final_agents if agent))
        if not final_agents:
            final_agents = ["mediator"]
        final_conversation = [
            {"agent": agent, "text": final_text, "action": FINISH_AGENT_ACTION}
            for agent in final_agents
        ]
        final_turn_log = {
            "round": round_num,
            "turn": final_turn,
            "meeting_phase": "conclusion",
            "issue_id": f"ELICIT-R{display_round_num}-T{final_turn}",
            "conversation": final_conversation,
            "discussion_mode": "sequential",
            "participants": final_agents,
            "judged_action_agent": final_agents[0],
            "judged_action": final_text,
            "recent_ask_history": final_recent_ask_history,
            "new_candidates_count": 0,
            "new_candidate_texts": [],
            "judge_finish": not forced_finish,
            "forced_finish": forced_finish,
        }
        elicitation_trace.append(final_turn_log)

    def finalize_elicitation(reason: str) -> Dict[str, Any]:
        cleaned_candidates = clean_elicited_reqts(all_candidates)
        rows_by_round = meeting_rows(
            elicitation_trace,
            round_num=round_num,
        )
        coordinator.flow.logger.info(
            "  reason=%s | 提取的需求：%s 筆",
            reason,
            len(cleaned_candidates),
        )
        elicitation = artifact.setdefault("elicitation", {})
        elicitation["plan"] = {
            "round_limit": max_turns,
            "participants": plan.get("participants", []) or [],
            "mode": "simultaneous",
        }
        elicitation["meeting"] = rows_by_round
        elicitation["elicited_reqts"] = list(elicitation.get("elicited_reqts", []) or []) + list(cleaned_candidates)
        elicitation["elicitation_stop_reason"] = reason
        closure_votes = artifact.get("elicitation_closure_votes")
        if isinstance(closure_votes, list) and closure_votes:
            elicitation["closure_summary"] = closure_votes[-1]
        artifact.setdefault("elicitation_trace", []).extend(elicitation_trace)

        coordinator.flow.store.save_artifact(artifact)
        if feedback_has_rows(artifact):
            coordinator.flow.logger.step_completed(
                "elicitation",
                "elicitation.update_feedback",
                "領域研究",
                agent="expert",
                output_path="artifact/feedback.json",
            )
        return artifact

    for turn in range(1, max_turns):
        meeting_phase = elicitation_phase_for_turn(turn, max_turns)
        phase_guidance = build_phase_guidance(meeting_phase)
        recent_ask_history = build_recent_ask_history(elicitation_trace)
        turn_strategy = coordinator.flow.mediator_agent.plan_elicitation(
            artifact=artifact,
            turn=turn,
            max_turns=max_turns,
            default_participants=participants,
            previous_turn_summary=previous_turn_summary,
            recent_ask_history=recent_ask_history,
        )
        turn_participants = normalized_turn_participants(
            turn_strategy.get("participants") or [],
        )
        if not turn_participants or "user" not in turn_participants:
            raise RuntimeError("Requirement elicitation turn strategy 未產生有效 participants，或未包含 user")
        turn_mode = "simultaneous"
        meeting_phase = str(turn_strategy.get("meeting_phase") or meeting_phase).strip() or meeting_phase
        if meeting_phase not in set(ELICITATION_PHASES):
            meeting_phase = elicitation_phase_for_turn(turn, max_turns)
        phase_guidance = build_phase_guidance(meeting_phase)
        turn_goal = str(turn_strategy.get("goal") or "").strip()
        log_turn_plan(
            coordinator.flow.logger,
            turn=turn,
            turn_strategy=turn_strategy,
        )

        req_summary = json.dumps(
            [
                {"id": r.get("id"), "text": (r.get("text") or "")}
                for r in requirement_discussion_pool(artifact)
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

        issue = {
            "id": f"ELICIT-R{display_round_num}-T{turn}",
            "title": "待命名需求擷取會議",
            "description": (
                f"產品情境：{json.dumps(str(artifact.get('scenario') or '').strip(), ensure_ascii=False)}\n\n"
                f"本輪會議階段：{meeting_phase}\n"
                f"階段指引：{phase_guidance}\n\n"
                f"本輪發言模式：{turn_mode}\n"
                f"本輪訪談目標：{turn_goal or '依目前缺口提出最值得確認的問題'}\n"
                f"本輪提問安排：{json.dumps(turn_strategy.get('actions') or {}, ensure_ascii=False)}\n"
                f"可選回答身份：{json.dumps(sorted(allowed_stakeholders), ensure_ascii=False)}\n\n"
                "這是一場實務需求訪談，不是單純訪談或自由閒聊。\n"
                "請依本輪缺口類型找出最值得確認的一個問題。\n"
                "你的目標是從 User 的回答中驗證、修正或補充尚未被明確記錄的需求。\n"
                "所有追問與候選需求都必須直接服務於產品情境；不得泛化成無關的企業資料管理、內部審批或需求工程流程。\n"
                "每輪問題都應先基於目前理解定位缺口，再向 User 確認一個最重要的不確定點。\n"
                "不要把會議變成閒聊或泛問；每個問題都必須能支援產生或修正一條 requirement。\n"
                "\n"
                f"目前初步 scope（可被 User 修正，不代表最終範圍）：\n{scope_summary}\n"
                "\n"
                f"目前已有需求：\n{req_summary}\n"
                f"{prev_text}\n\n"
                "請不要重複已有需求，專注驗證目前需求理解並擷取新的需求候選。\n"
                "若本輪是逐一發言，User 必須最後回答；若本輪是同時發言，User 會逐題回答各 agent 的問題。"
            ),
            "participants": turn_participants,
            "discussion_mode": turn_mode,
            "trace": {"artifact_ids": [], "proposal_ids": []},
            "scenario": str(artifact.get("scenario", "") or "").strip(),
            "meeting_phase": meeting_phase,
            "phase_guidance": phase_guidance,
            "meeting_goal": turn_goal,
            "allowed_stakeholders": sorted(allowed_stakeholders),
            "actions": turn_strategy.get("actions") or {},
            "recent_ask_history": recent_ask_history,
        }
        issue["title"] = str(turn_goal or "需求擷取會議").strip() or "需求擷取會議"
        conversation: List[Dict[str, Any]] = []
        coordinator.flow.store.save_artifact(artifact)
        user_agent = coordinator.flow.registry.get("user")
        if turn_mode == "simultaneous":
            interviewer_participants = [p for p in turn_participants if p != "user"]
            interviewer_issue = {
                **issue,
                "participants": interviewer_participants,
                "answer_all": False,
                "actions": turn_strategy.get("actions") or {},
            }
            if interviewer_participants:
                conversation.extend(
                    coordinator.flow.mediator_agent.moderate_simultaneous(
                        interviewer_issue, coordinator.flow.registry, artifact=artifact
                    )
                )
            conversation_participants_order = interviewer_participants + ["user"]
            user_answer_all_questions = True
        else:
            conversation_participants_order = build_sequential_order(
                turn_participants,
                turn_participants,
            )
            interviewer_order = [p for p in conversation_participants_order if p != "user"]
            issue["participants"] = interviewer_order
            conversation, _ = coordinator.flow.mediator_agent.moderate_sequential(
                issue, coordinator.flow.registry, artifact=artifact
            )
            user_answer_all_questions = True

        interviewer_conversation = list(conversation)
        interviewer_finish = False
        closure_vote: Dict[str, Any] = {}
        finish_agents = finish_agents_from_conversation(
            interviewer_conversation,
            stop_phrase,
        )
        finish_proposer = finish_agents[0] if finish_agents else ""
        finish_text = stop_phrase if finish_agents else ""
        effective_conversation = list(interviewer_conversation)
        if finish_text:
            if not finish_proposer:
                raise RuntimeError("需求擷取收束缺少提出收束的 agent")
            closure_vote = collect_closure_votes(
                coordinator,
                artifact,
                round_num=round_num,
                turn=turn,
                proposer_role=finish_proposer,
                proposer_roles=finish_agents,
                recent_ask_history=recent_ask_history,
                candidate_texts=[
                    str(c.get("text") or "").strip()
                    for c in all_candidates
                    if isinstance(c, dict) and str(c.get("text") or "").strip()
                ],
            )
            if closure_vote.get("approved"):
                coordinator.flow.logger.info(
                    "  收束投票通過：propose_finish=%s close=%s continue=%s",
                    len(finish_agents),
                    closure_vote.get("close_count"),
                    closure_vote.get("continue_count"),
                )
                interviewer_finish = True
                effective_conversation = [
                    {
                        "agent": agent,
                        "response": {
                            "text": stop_phrase,
                            "content": stop_phrase,
                            "action": FINISH_AGENT_ACTION,
                        },
                    }
                    for agent in finish_agents
                ]
            else:
                coordinator.flow.logger.info(
                    "  收束投票未通過：propose_finish=%s close=%s continue=%s，本輪後繼續追問",
                    len(finish_agents),
                    closure_vote.get("close_count"),
                    closure_vote.get("continue_count"),
                )
                effective_conversation = without_finish_proposals(
                    interviewer_conversation,
                    stop_phrase,
                )

        question_conversations = user_questions(effective_conversation)
        normalized_question_conversations: List[Dict[str, Any]] = []
        for question_conversation in question_conversations:
            agent_name = str(question_conversation.get("agent") or "").strip()
            question_response = (
                question_conversation.get("response")
                if isinstance(question_conversation.get("response"), dict)
                else {}
            )
            question_targets = valid_targets(
                question_response.get("target_stakeholders"),
                allowed_names=allowed_stakeholders,
            )
            if not question_targets:
                question_targets = planned_targets_for_agent(
                    turn_strategy,
                    agent_name,
                    allowed_names=allowed_stakeholders,
                )
            if not question_targets:
                raise RuntimeError(
                    f"Requirement elicitation question 缺少有效 target_stakeholders: agent={agent_name}"
                )
            question_response = dict(question_response)
            question_response["target_stakeholders"] = question_targets
            normalized_question_conversations.append(
                {**question_conversation, "response": question_response}
            )
        question_conversations = normalized_question_conversations
        judged_action_agent, judged_text = select_question(question_conversations)
        judge_action_type = ""
        if interviewer_finish:
            if not finish_proposer:
                raise RuntimeError("Requirement elicitation finish 缺少提議收束的 agent")
            judged_action_agent = finish_proposer
            judged_text = stop_phrase
        elif not judged_text:
            if finish_text and closure_vote and not closure_vote.get("approved"):
                coordinator.flow.logger.info(
                    "  收束投票未通過且本輪無可追問問題，進入下一輪"
                )
                previous_turn_summary = {
                    **(previous_turn_summary or {}),
                    "turn": turn,
                    "meeting_phase": meeting_phase,
                    "goal": turn_goal,
                    "finish_rejected": True,
                    "closure_vote": closure_vote,
                    "gaps": closure_vote.get("gaps") or [],
                    "questions": closure_vote.get("questions") or [],
                    "open_questions": closure_vote.get("open_questions") or [],
                }
                continue
            planned_finish_agents = [
                agent
                for agent, row in (turn_strategy.get("actions") or {}).items()
                if isinstance(row, dict)
                and str(row.get("action") or "").strip().lower()
                == FINISH_AGENT_ACTION
            ]
            if planned_finish_agents:
                finish_agent = str(planned_finish_agents[0] or "mediator").strip() or "mediator"
                closure_vote = collect_closure_votes(
                    coordinator,
                    artifact,
                    round_num=round_num,
                    turn=turn,
                    proposer_role=finish_agent,
                    proposer_roles=planned_finish_agents,
                    recent_ask_history=recent_ask_history,
                    candidate_texts=[
                        str(c.get("text") or "").strip()
                        for c in all_candidates
                        if isinstance(c, dict) and str(c.get("text") or "").strip()
                    ],
                )
                if closure_vote.get("approved"):
                    append_finish_turn(
                        turn,
                        planned_finish_agents,
                        stop_phrase,
                        forced_finish=False,
                    )
                    coordinator.flow.logger.info(
                        "  收束投票通過：propose_finish=%s close=%s continue=%s",
                        len(planned_finish_agents),
                        closure_vote.get("close_count"),
                        closure_vote.get("continue_count"),
                    )
                    return finalize_elicitation("propose_finish")
                coordinator.flow.logger.info(
                    "  propose_finish 收束投票未通過：propose_finish=%s close=%s continue=%s，進入下一輪",
                    len(planned_finish_agents),
                    closure_vote.get("close_count"),
                    closure_vote.get("continue_count"),
                )
                previous_turn_summary = {
                    **(previous_turn_summary or {}),
                    "turn": turn,
                    "meeting_phase": meeting_phase,
                    "goal": turn_goal,
                    "finish_rejected": True,
                    "closure_vote": closure_vote,
                    "gaps": closure_vote.get("gaps") or [],
                    "questions": closure_vote.get("questions") or [],
                    "open_questions": closure_vote.get("open_questions") or [],
                }
                continue
            conversation_preview = []
            for row in effective_conversation:
                if not isinstance(row, dict):
                    continue
                response = row.get("response") if isinstance(row.get("response"), dict) else {}
                conversation_preview.append({
                    "agent": row.get("agent"),
                    "actions": response.get("actions") or response.get("action"),
                    "target_stakeholders": response.get("target_stakeholders"),
                    "text": str(response.get("text") or "")[:160],
                })
            raise RuntimeError(
                "Requirement elicitation agent loop 未產生可詢問利害關係人的問題: "
                + json.dumps(
                    {
                        "actions": turn_strategy.get("actions") or {},
                        "question_count": len(question_conversations),
                        "conversation": conversation_preview,
                    },
                    ensure_ascii=False,
                )
            )
        if judged_text and user_agent and hasattr(user_agent, "judge_interviewer_action_type"):
            try:
                judge_action_type = str(
                    user_agent.judge_interviewer_action_type(judged_text)
                ).strip().lower()
            except Exception as e:
                raise RuntimeError("Requirement elicitation action type 判定失敗") from e
        if interviewer_finish and stop_phrase in judged_text:
            judge_action_type = "finish"
        oracle_judge_finish = judge_action_type == "finish"

        conversation = list(effective_conversation)
        if interviewer_finish or oracle_judge_finish:
            for row in conversation:
                emit_elicitation_speech(coordinator.flow.logger, row)
        if (
            user_agent
            and not interviewer_finish
            and not oracle_judge_finish
            and judged_text
            and question_conversations
        ):
            if user_answer_all_questions:
                paired_conversation: List[Dict[str, Any]] = []
                question_ids = {id(c) for c in question_conversations}
                paired_conversation.extend(
                    c for c in effective_conversation if id(c) not in question_ids
                )
                for q_index, question_conversation in enumerate(question_conversations, 1):
                    question_response = (
                        question_conversation.get("response")
                        if isinstance(question_conversation.get("response"), dict)
                        else {}
                    )
                    question_targets = valid_targets(
                        question_response.get("target_stakeholders"),
                        allowed_names=allowed_stakeholders,
                    )
                    if not question_targets:
                        question_targets = planned_targets_for_agent(
                            turn_strategy,
                            str(question_conversation.get("agent") or "").strip(),
                            allowed_names=allowed_stakeholders,
                        )
                    question_response = dict(question_response)
                    question_response["target_stakeholders"] = question_targets
                    question_conversation = {
                        **question_conversation,
                        "response": question_response,
                    }
                    paired_conversation.append(question_conversation)
                    emit_elicitation_speech(coordinator.flow.logger, question_conversation)
                    user_issue = {
                        **issue,
                        "id": f"{issue['id']}-USER-{q_index}",
                        "title": "利害關係人回答",
                        "participants": ["user"],
                                                "discussion_mode": "sequential",
                        "answer_all": False,
                        "target_stakeholders": question_targets,
                    }
                    user_response = coordinator.flow.mediator_agent.collect_issue_response(
                        user_agent,
                        user_issue,
                        previous_responses=[question_conversation],
                    )
                    user_response = validated_elicitation_answer(
                        user_response,
                        question_targets=question_targets,
                    )
                    paired_conversation.append(
                        {
                            "agent": "user",
                            "response": user_response,
                        }
                    )
                    emit_elicitation_speech(
                        coordinator.flow.logger,
                        {
                            "agent": "user",
                            "response": user_response,
                        },
                    )
                conversation = paired_conversation
            else:
                for question_conversation in question_conversations:
                    emit_elicitation_speech(coordinator.flow.logger, question_conversation)
                question_response = (
                    question_conversations[-1].get("response")
                    if question_conversations
                    and isinstance(question_conversations[-1].get("response"), dict)
                    else {}
                )
                question_targets = valid_targets(
                    question_response.get("target_stakeholders"),
                    allowed_names=allowed_stakeholders,
                )
                user_issue = {
                    **issue,
                    "id": f"{issue['id']}-USER",
                    "title": "利害關係人回答",
                    "participants": ["user"],
                                        "discussion_mode": "sequential",
                    "answer_all": False,
                    "target_stakeholders": question_targets,
                }
                user_response = coordinator.flow.mediator_agent.collect_issue_response(
                    user_agent,
                    user_issue,
                    previous_responses=question_conversations,
                )
                user_response = validated_elicitation_answer(
                    user_response,
                    question_targets=question_targets,
                )
                conversation.append(
                    {
                        "agent": "user",
                        "response": user_response,
                    }
                )
                emit_elicitation_speech(
                    coordinator.flow.logger,
                    {
                        "agent": "user",
                        "response": user_response,
                    },
                )
        elif finish_text and not interviewer_finish and not judged_text:
            judge_action_type = "finish_rejected_by_vote"

        raw_conversation = list(conversation)
        new_candidates = extract_candidates(
            coordinator, conversation, artifact, round_num=round_num, turn=turn
        )
        conversation_rows: List[Dict[str, Any]] = []
        for c in raw_conversation:
            if not isinstance(c, dict):
                continue
            agent_name = str(c.get("agent") or "").strip()
            resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
            text = str(resp.get("text") or "").strip()
            if not agent_name or not text:
                continue
            row = {"agent": agent_name, "text": text}
            agent_action = str(resp.get("action") or "").strip()
            action_focus = str(resp.get("action_focus") or "").strip()
            if agent_action:
                row["action"] = agent_action
            if action_focus:
                row["action_focus"] = action_focus
            targets = resp.get("target_stakeholders")
            if isinstance(targets, str):
                targets = [targets]
            if isinstance(targets, list):
                row["target_stakeholders"] = [
                    str(name).strip()
                    for name in targets
                    if str(name).strip()
                ]
            speaking_as = resp.get("speaking_as")
            if isinstance(speaking_as, str):
                speaking_as = [speaking_as]
            if isinstance(speaking_as, list):
                row["speaking_as"] = [
                    str(name).strip()
                    for name in speaking_as
                    if str(name).strip()
                ]
            conversation_rows.append(row)

        should_stop_after_this_turn = bool(interviewer_finish or oracle_judge_finish)
        stop_reason_after_this_turn = (
            "judge_finish"
            if interviewer_finish
            else ("oracle_judge_finish" if oracle_judge_finish else "judge_continue")
        )

        turn_log = {
            "round": round_num,
            "turn": turn,
            "meeting_phase": meeting_phase,
            "phase_guidance": phase_guidance,
            "issue_id": issue["id"],
            "conversation": conversation_rows,
            "discussion_mode": turn_mode,
            "participants": turn_participants,
            "participants_order": conversation_participants_order,
            "actions": turn_strategy.get("actions") or {},
            "goal": turn_goal,
            "judged_action_agent": judged_action_agent,
            "judged_action": judged_text,
            "judge_action_type": judge_action_type,
            "judge_finish": should_stop_after_this_turn,
            "closure_finish": interviewer_finish,
            "oracle_judge_finish": oracle_judge_finish,
            "closure_vote": closure_vote,
            "recent_ask_history": recent_ask_history,
            "new_candidates_count": len(new_candidates),
            "new_candidate_texts": [
                str(c.get("text") or "").strip()
                for c in new_candidates
                if isinstance(c, dict) and str(c.get("text") or "").strip()
            ],
        }
        elicitation_trace.append(turn_log)
        if new_candidates:
            all_candidates.extend(new_candidates)

        user_response_for_memory = collect_user_summary(conversation)
        current_memory = derive_turn_summary(judged_text, user_response_for_memory)
        merged_memory = merge_turn_summary(previous_turn_summary, current_memory)

        previous_turn_summary = {
            "turn": turn,
            "meeting_phase": meeting_phase,
            "discussion_mode": turn_mode,
            "participants": list(turn_participants),
            "actions": dict(turn_strategy.get("actions") or {}),
            "judged_action_agent": judged_action_agent,
            "judged_action": judged_text,
            "new_candidates_count": len(new_candidates),
            "participants_order": list(conversation_participants_order),
            "closure_vote": closure_vote,
            **merged_memory,
        }

        log_elicitation_turn(
            coordinator.flow.logger,
            round_num=round_num,
            turn=turn,
            meeting_phase=meeting_phase,
            conversation_rows=conversation_rows,
            new_candidates=new_candidates,
            cumulative_candidates=len(all_candidates),
        )
        if should_stop_after_this_turn:
            termination_reason = stop_reason_after_this_turn
            if stop_reason_after_this_turn == "max_turn":
                coordinator.flow.logger.info("  停止：本輪完成後已達最後一輪，以 finish action 收斂")
            else:
                coordinator.flow.logger.info(
                    "  停止：本輪完成後，judge 判定為 finish（reason=%s）",
                    stop_reason_after_this_turn,
                )
            break

    if termination_reason == "max_turns_reached":
        final_turn = len(elicitation_trace) + 1
        final_agent = "mediator"
        append_finish_turn(final_turn, final_agent, forced_finish_phrase)
        coordinator.flow.logger.info("[輪次 %s]", final_turn)
        coordinator.flow.logger.step_completed(
            "elicitation",
            "elicitation.run_meeting",
            "需求擷取會議結束",
            agent="mediator",
            message=forced_finish_phrase,
            output_path="artifact/meeting/elicitation_meeting.json",
        )
        termination_reason = "max_turn"

    return finalize_elicitation(termination_reason)
