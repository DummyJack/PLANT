# Requirement elicitation meeting: ask stakeholder-focused questions and extract requirement candidates.
import json
from typing import Any, Dict, List, Optional

from agents.profile.analyst.requirements import requirement_discussion_pool
from agents.profile.scenario import scenario_prompt_value
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
    find_finish_proposal,
    merge_turn_summary,
    clean_elicited_reqts,
    turn_participants as normalized_turn_participants,
    user_questions,
    select_question,
    without_finish_proposals,
)

# ---------- 主流程 ----------

def meeting_rows(
    elicitation_trace: List[Dict[str, Any]],
    *,
    round_num: int,
) -> Dict[str, List[Dict[str, str]]]:
    """Convert internal elicitation turn logs into compact meeting records."""
    try:
        round_key = f"r{max(1, int(round_num))}"
    except (TypeError, ValueError):
        round_key = "r1"
    rows: List[Dict[str, str]] = []

    def turn_number(turn: Dict[str, Any], fallback: int) -> int:
        try:
            value = int(turn.get("turn") or fallback)
        except (TypeError, ValueError):
            value = fallback
        return max(1, value)

    def row_id(turn_no: int, row_no: int = 1) -> str:
        return f"elicit-{turn_no}-{row_no}"

    def row_text(row: Dict[str, Any]) -> str:
        return str(row.get("text") or "").strip()

    def answer_fields(row: Dict[str, Any]) -> Dict[str, str]:
        text = row_text(row)
        if not text:
            return {}
        speaking_as = row.get("speaking_as") or []
        if isinstance(speaking_as, str):
            speaking_as = [speaking_as]
        keys = [str(name).strip() for name in speaking_as if str(name).strip()]
        if not keys:
            return {}
        return {key: text for key in keys}

    for index, turn in enumerate(elicitation_trace or [], 1):
        if not isinstance(turn, dict):
            continue
        turn_no = turn_number(turn, index)
        if bool(turn.get("forced_finish")):
            text = str(turn.get("judged_action") or "").strip()
            agent = str(turn.get("judged_action_agent") or "mediator").strip() or "mediator"
            if text:
                rows.append({"id": row_id(turn_no), agent: text})
            continue
        if str(turn.get("discussion_mode") or "").strip() == "simultaneous":
            turn_row_index = 1

            def next_turn_row_id() -> str:
                nonlocal turn_row_index
                value = row_id(turn_no, turn_row_index)
                turn_row_index += 1
                return value

            pending_question: Optional[Dict[str, str]] = None
            for contribution in turn.get("contributions", []) or []:
                if not isinstance(contribution, dict):
                    continue
                agent = str(contribution.get("agent") or "").strip()
                text = row_text(contribution)
                if not agent or not text:
                    continue
                if agent != "user":
                    if pending_question:
                        rows.append({"id": next_turn_row_id(), **pending_question})
                    pending_question = {agent: text}
                    continue
                if pending_question:
                    rows.append(
                        {
                            "id": next_turn_row_id(),
                            **pending_question,
                            **answer_fields(contribution),
                        }
                    )
                    pending_question = None
            if pending_question:
                rows.append({"id": next_turn_row_id(), **pending_question})
            continue
        question = str(turn.get("judged_action") or "").strip()
        question_agent = str(turn.get("judged_action_agent") or "").strip()
        answer = ""
        answer_fields_map: Dict[str, str] = {}
        for row in turn.get("contributions", []) or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("agent") or "").strip() != "user":
                continue
            answer = row_text(row)
            answer_fields_map = answer_fields(row)
            break
        if bool(turn.get("judge_finish")) and not answer:
            agent = question_agent or "mediator"
            rows.append({"id": row_id(turn_no), agent: question})
            continue
        if not question and not answer:
            continue
        row = {"id": row_id(turn_no)}
        if question_agent and question:
            row[question_agent] = question
        if answer_fields_map and answer:
            row.update(answer_fields_map)
        rows.append(row)
    return {round_key: rows}

def valid_stakeholder_names(artifact: Dict[str, Any]) -> set[str]:
    return {
        str(row.get("name") or "").strip()
        for row in artifact.get("stakeholders", []) or []
        if isinstance(row, dict) and str(row.get("name") or "").strip()
    }

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


def log_elicitation_turn(
    logger: Any,
    *,
    round_num: int,
    turn: int,
    meeting_phase: str,
    contribution_rows: List[Dict[str, Any]],
    new_candidates: List[Dict[str, Any]],
    cumulative_candidates: int,
) -> None:
    pending_question: Optional[Dict[str, Any]] = None
    for row in contribution_rows:
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
            speaking_as = list(pending_question.get("targets") or [])
        if not speaking_as:
            pending_question = None
            continue
        logger.info("  %s：%s", "、".join(speaking_as), text)
        pending_question = None
    logger.info("  候選需求：本輪 %s 筆，累計 %s 筆", len(new_candidates), cumulative_candidates)
    preview = [
        str(c.get("text") or "").strip()
        for c in new_candidates
        if isinstance(c, dict) and str(c.get("text") or "").strip()
    ]
    logger.info("  候選需求：%s", preview)


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
    agent_actions = turn_strategy.get("agent_actions") or {}
    logger.info("[輪次 %s]", turn)
    goal = str(turn_strategy.get("goal") or "").strip() or "釐清本輪最重要且尚未充分探索的方向"
    speaking_order_parts = []
    if isinstance(agent_actions, dict) and agent_actions:
        for agent, action_info in agent_actions.items():
            if isinstance(action_info, dict):
                action = str(action_info.get("action") or "").strip()
            else:
                action = str(action_info or "").strip()
            if action in {"ask_user", "supplement_question"}:
                speaking_order_parts.append(f"{agent} → user")
    logger.info(
        "  elicit plan：participants: %s | speaking_order: %s | goal: %s",
        ", ".join(participants) if participants else "無",
        "; ".join(speaking_order_parts) if speaking_order_parts else "無",
        goal,
    )


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


def run_elicitation_meeting(
    coordinator: Any,
    artifact: Dict[str, Any],
    round_num: int,
) -> Dict[str, Any]:
    """需求擷取會議：Mediator 規劃 -> 多輪對話 -> Analyst 結構化收尾。"""
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

    def append_finish_turn(final_turn: int, final_agent: str, final_text: str) -> None:
        final_recent_ask_history = build_recent_ask_history(elicitation_trace, max_items=3)
        final_contributions = [
            {
                "agent": final_agent,
                "response": {"text": final_text, "action": FINISH_AGENT_ACTION},
            }
        ]
        final_turn_log = {
            "round": round_num,
            "turn": final_turn,
            "meeting_phase": "conclusion",
            "issue_id": f"ELICIT-R{round_num}-T{final_turn}",
            "contributions": [{"agent": final_agent, "text": final_text, "action": FINISH_AGENT_ACTION}],
            "discussion_mode": "sequential",
            "participants": [final_agent],
            "speaking_order": [final_agent],
            "judged_action_agent": final_agent,
            "judged_action": final_text,
            "recent_ask_history": final_recent_ask_history,
            "new_candidates_count": 0,
            "new_candidate_texts": [],
            "forced_finish": True,
        }
        elicitation_trace.append(final_turn_log)

    for turn in range(1, max_turns):
        meeting_phase = elicitation_phase_for_turn(turn, max_turns)
        phase_guidance = build_phase_guidance(meeting_phase)
        recent_ask_history = build_recent_ask_history(elicitation_trace, max_items=3)
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
            "id": f"ELICIT-R{round_num}-T{turn}",
            "title": "待命名需求擷取會議",
            "description": (
                f"產品情境：{json.dumps(scenario_prompt_value(artifact.get('scenario')), ensure_ascii=False)}\n\n"
                f"本輪會議階段：{meeting_phase}\n"
                f"階段指引：{phase_guidance}\n\n"
                f"本輪發言模式：{turn_mode}\n"
                f"本輪訪談目標：{turn_goal or '依目前缺口提出最值得確認的問題'}\n"
                f"本輪提問安排：{json.dumps(turn_strategy.get('agent_actions') or {}, ensure_ascii=False)}\n"
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
            "category": "open_question",
            "participants": turn_participants,
            "discussion_mode": turn_mode,
            "source_ids": [],
            "scenario": scenario_prompt_value(artifact.get("scenario", {})),
            "meeting_phase": meeting_phase,
            "phase_guidance": phase_guidance,
            "meeting_goal": turn_goal,
            "allowed_stakeholders": sorted(allowed_stakeholders),
            "agent_actions": turn_strategy.get("agent_actions") or {},
            "recent_ask_history": recent_ask_history,
        }
        mediator_title = coordinator.flow.mediator_agent.name_meeting_issue(
            issue,
            context_label="需求擷取會議",
        )
        issue["title"] = mediator_title
        contributions: List[Dict[str, Any]] = []
        coordinator.flow.store.save_artifact(artifact)
        user_agent = coordinator.flow.registry.get("user")
        if turn_mode == "simultaneous":
            interviewer_participants = [p for p in turn_participants if p != "user"]
            interviewer_issue = {
                **issue,
                "participants": interviewer_participants,
                "answer_all_interviewer_questions": False,
                "agent_actions": turn_strategy.get("agent_actions") or {},
            }
            if interviewer_participants:
                contributions.extend(
                    coordinator.flow.mediator_agent.moderate_simultaneous(
                        interviewer_issue, coordinator.flow.registry, artifact=artifact
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
            issue["speaking_order"] = interviewer_order
            contributions, _ = coordinator.flow.mediator_agent.moderate_sequential(
                issue, coordinator.flow.registry, artifact=artifact
            )
            user_answer_all_questions = False

        interviewer_contributions = list(contributions)
        interviewer_finish = False
        closure_vote: Dict[str, Any] = {}
        finish_proposer, finish_text = find_finish_proposal(
            interviewer_contributions,
            stop_phrase,
        )
        effective_contributions = list(interviewer_contributions)
        if finish_text:
            closure_vote = collect_closure_votes(
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
                            "text": stop_phrase,
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

        user_question_contributions = user_questions(effective_contributions)
        judged_action_agent, judged_text = select_question(user_question_contributions)
        judge_action_type = ""
        if interviewer_finish:
            if not finish_proposer:
                raise RuntimeError("Requirement elicitation finish 缺少提議收束的 agent")
            judged_action_agent = finish_proposer
            judged_text = stop_phrase
        elif not judged_text:
            raise RuntimeError("Requirement elicitation agent loop 未產生可詢問利害關係人的問題")
        if judged_text and user_agent and hasattr(user_agent, "judge_interviewer_action_type"):
            try:
                judge_action_type = str(
                    user_agent.judge_interviewer_action_type(judged_text)
                ).strip().lower()
            except Exception as e:
                raise RuntimeError("Requirement elicitation action type 判定失敗") from e
        if stop_phrase in judged_text:
            interviewer_finish = True
            judge_action_type = "finish"

        contributions = list(effective_contributions)
        if user_agent and not interviewer_finish and judged_text and user_question_contributions:
            if user_answer_all_questions:
                paired_contributions: List[Dict[str, Any]] = []
                question_ids = {id(c) for c in user_question_contributions}
                paired_contributions.extend(
                    c for c in effective_contributions if id(c) not in question_ids
                )
                for q_index, question_contribution in enumerate(user_question_contributions, 1):
                    question_response = (
                        question_contribution.get("response")
                        if isinstance(question_contribution.get("response"), dict)
                        else {}
                    )
                    question_targets = valid_targets(
                        question_response.get("target_stakeholders"),
                        allowed_names=allowed_stakeholders,
                    )
                    if not question_targets:
                        raise RuntimeError("Requirement elicitation question 缺少合法 target_stakeholders")
                    if question_targets:
                        question_response = dict(question_response)
                        question_response["target_stakeholders"] = question_targets
                        question_contribution = {
                            **question_contribution,
                            "response": question_response,
                        }
                    paired_contributions.append(question_contribution)
                    user_issue = {
                        **issue,
                        "id": f"{issue['id']}-USER-{q_index}",
                        "title": "待命名會議",
                        "participants": ["user"],
                        "speaking_order": ["user"],
                        "discussion_mode": "sequential",
                        "answer_all_interviewer_questions": False,
                        "target_stakeholders": question_targets,
                    }
                    user_issue_title = coordinator.flow.mediator_agent.name_meeting_issue(
                        user_issue,
                        context_label="需求擷取 User 回答回合",
                    )
                    user_issue["title"] = user_issue_title
                    user_response = coordinator.flow.mediator_agent.collect_issue_response(
                        user_agent,
                        user_issue,
                        previous_responses=[question_contribution],
                    )
                    paired_contributions.append(
                        {
                            "agent": "user",
                            "response": user_response if isinstance(user_response, dict) else {"content": str(user_response)},
                        }
                    )
                contributions = paired_contributions
            else:
                question_response = (
                    user_question_contributions[-1].get("response")
                    if user_question_contributions
                    and isinstance(user_question_contributions[-1].get("response"), dict)
                    else {}
                )
                question_targets = valid_targets(
                    question_response.get("target_stakeholders"),
                    allowed_names=allowed_stakeholders,
                )
                if not question_targets:
                    raise RuntimeError("Requirement elicitation question 缺少合法 target_stakeholders")
                user_issue = {
                    **issue,
                    "id": f"{issue['id']}-USER",
                    "title": "待命名會議",
                    "participants": ["user"],
                    "speaking_order": ["user"],
                    "discussion_mode": "sequential",
                    "answer_all_interviewer_questions": False,
                    "target_stakeholders": question_targets,
                }
                user_issue_title = coordinator.flow.mediator_agent.name_meeting_issue(
                    user_issue,
                    context_label="需求擷取 User 回答回合",
                )
                user_issue["title"] = user_issue_title
                user_response = coordinator.flow.mediator_agent.collect_issue_response(
                    user_agent,
                    user_issue,
                    previous_responses=user_question_contributions,
                )
                contributions.append(
                    {
                        "agent": "user",
                        "response": user_response if isinstance(user_response, dict) else {"content": str(user_response)},
                    }
                )
        elif finish_text and not interviewer_finish and not judged_text:
            judge_action_type = "finish_rejected_by_vote"

        record_contributions = list(contributions)
        new_candidates = extract_candidates(
            coordinator, contributions, artifact, round_num=round_num, turn=turn
        )
        contribution_rows: List[Dict[str, Any]] = []
        for c in record_contributions:
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
            contribution_rows.append(row)

        should_stop_after_this_turn = bool(interviewer_finish)
        stop_reason_after_this_turn = "judge_finish" if interviewer_finish else "judge_continue"

        turn_log = {
            "round": round_num,
            "turn": turn,
            "meeting_phase": meeting_phase,
            "phase_guidance": phase_guidance,
            "issue_id": issue["id"],
            "contributions": contribution_rows,
            "discussion_mode": turn_mode,
            "participants": turn_participants,
            "speaking_order": record_speaking_order,
            "agent_actions": turn_strategy.get("agent_actions") or {},
            "goal": turn_goal,
            "judged_action_agent": judged_action_agent,
            "judged_action": judged_text,
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
        }
        elicitation_trace.append(turn_log)
        if new_candidates:
            all_candidates.extend(new_candidates)

        user_response_for_memory = collect_user_summary(contributions)
        current_memory = derive_turn_summary(judged_text, user_response_for_memory)
        merged_memory = merge_turn_summary(previous_turn_summary, current_memory)

        previous_turn_summary = {
            "turn": turn,
            "meeting_phase": meeting_phase,
            "discussion_mode": turn_mode,
            "participants": list(turn_participants),
            "agent_actions": dict(turn_strategy.get("agent_actions") or {}),
            "judged_action_agent": judged_action_agent,
            "judged_action": judged_text,
            "new_candidates_count": len(new_candidates),
            "speaking_order": list(record_speaking_order),
            "closure_vote": closure_vote,
            **merged_memory,
        }

        log_elicitation_turn(
            coordinator.flow.logger,
            round_num=round_num,
            turn=turn,
            meeting_phase=meeting_phase,
            contribution_rows=contribution_rows,
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
        # 達上限時，最後一輪直接進入 finish 收尾，不再執行 user 對話。
        final_turn = max_turns
        final_agent = "mediator"
        append_finish_turn(final_turn, final_agent, forced_finish_phrase)
        coordinator.flow.logger.info("[輪次 %s]", final_turn)
        coordinator.flow.logger.info("  Mediator：%s", forced_finish_phrase)
        termination_reason = "max_turn"

    all_candidates = clean_elicited_reqts(all_candidates)
    rows_by_round = meeting_rows(
        elicitation_trace,
        round_num=round_num,
    )
    coordinator.flow.logger.info(
        "  reason=%s | 提取的需求：%s 筆",
        termination_reason,
        len(all_candidates),
    )
    elicitation = artifact.setdefault("elicitation", {})
    elicitation["plan"] = {
        "round_limit": max_turns,
        "participants": plan.get("participants", []) or [],
        "mode": "simultaneous",
    }
    elicitation["meeting"] = rows_by_round
    elicitation["elicited_reqts"] = list(elicitation.get("elicited_reqts", []) or []) + list(all_candidates)
    elicitation["elicitation_stop_reason"] = termination_reason
    artifact.setdefault("elicitation_trace", []).extend(elicitation_trace)

    coordinator.flow.store.save_artifact(artifact)
    return artifact
