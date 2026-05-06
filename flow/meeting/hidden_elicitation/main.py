# Hidden elicitation meeting: ask follow-up questions and extract hidden requirements.
import json
from typing import Any, Dict, List, Optional

from utils import human_setting
from utils.language import current_output_language

from .record import summarize_elicitation_meeting_conclusion
from .support import (
    ELICITATION_PHASES,
    FINISH_AGENT_ACTION,
    build_phase_guidance,
    build_recent_ask_history,
    build_sequential_order,
    collect_elicitation_closure_votes,
    collect_user_response_summary,
    derive_turn_memory,
    elicitation_phase_for_turn,
    extract_elicitation_candidates,
    find_finish_proposal,
    get_elicitation_mode,
    initialize_elicitation_meeting_state,
    merge_elicitation_memory,
    normalize_elicitation_candidates,
    normalize_turn_participants,
    question_contributions_for_user,
    select_judged_action,
    without_finish_proposals,
)

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
