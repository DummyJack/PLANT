import json
from typing import Any, Dict, List, Optional

from utils import current_output_language


# ---------- elicitation helpers ----------

def _extract_first_question(text: str) -> str:
    parts = [p.strip() for p in str(text or "").replace("\n", " ").split("。") if p.strip()]
    for p in parts:
        if "？" in p or "?" in p:
            return p
    return parts[0] if parts else ""


def _compact_text(text: str, max_len: int = 160) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= max_len:
        return value
    return value[:max_len].rstrip() + "..."


def _extract_focus_area(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    for sep in ("：", ":"):
        if sep in value:
            head = value.split(sep, 1)[0].strip()
            if 2 <= len(head) <= 20:
                return head
    keywords = [
        "流程", "輸入", "輸出", "內容", "資料", "欄位", "狀態", "事件",
        "偏好", "介面", "風格", "配色", "版面", "限制", "權限", "安全",
        "品質", "速度", "穩定性", "可用性",
    ]
    for kw in keywords:
        if kw in value:
            return kw
    return _compact_text(value, 24)


def _extract_reason_excerpt(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    parts = [p.strip() for p in value.replace("\n", " ").split("。") if p.strip()]
    if not parts:
        return _compact_text(value, 140)
    for part in parts:
        if any(token in part for token in ("因為", "避免", "需要", "重要", "影響", "不清楚", "未知", "缺")):
            return _compact_text(part, 140)
    return _compact_text(parts[0], 140)


def _curate_collector_inputs(
    contributions: List[Dict[str, Any]],
    *,
    collectors: List[str],
    include_user_signal: bool = False,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    collector_set = set(collectors or [])
    for c in contributions or []:
        if not isinstance(c, dict):
            continue
        role = str(c.get("agent") or "").strip()
        if role not in collector_set and not (include_user_signal and role == "user"):
            continue
        resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
        statement = str(resp.get("statement") or resp.get("content") or "").strip()
        if not statement:
            continue
        if role == "user":
            structured_payload = {
                "type": "UserSignal",
                "role": role,
                "focus_area": _extract_focus_area(statement),
                "stakeholder_cue": _extract_reason_excerpt(statement),
                "why_it_matters": _extract_reason_excerpt(statement),
            }
        else:
            question = _extract_first_question(statement)
            structured_payload = {
                "type": "SupportSuggestion",
                "role": role,
                "focus_area": _extract_focus_area(statement),
                "suggested_question": question or "（未明確給出，請從內容抽取一題）",
                "why_it_matters": _extract_reason_excerpt(statement),
            }
        rows.append(
            {
                "agent": role,
                "response": {
                    "statement": json.dumps(structured_payload, ensure_ascii=False),
                    "open_questions": [],
                },
            }
        )
    return rows


def _extract_elicitation_candidates(
    coordinator: Any,
    contributions: List[Dict[str, Any]],
    artifact: Dict[str, Any],
    *,
    round_num: int,
    turn: int,
) -> List[Dict[str, Any]]:
    discussion_text = ""
    for c in contributions:
        if not isinstance(c, dict):
            continue
        agent = c.get("agent", "?")
        resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
        statement = (resp.get("statement") or resp.get("content") or "").strip()
        if statement:
            discussion_text += f"\n【{agent}】\n{statement}\n"
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
            normalized = AnalystAgent._normalize_requirement_record(cand)
            normalized["source"] = "elicitation"
            normalized["elicitation_round"] = round_num
            normalized["elicitation_turn"] = turn
            results.append(normalized)
        return results
    except Exception as e:
        coordinator.flow.logger.warning("挖掘需求提取失敗: %s", e)
        return []


def _normalize_elicitation_candidates(
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
        deduped.append(cand)
    return deduped


def _build_recent_ask_history(
    elicitation_log: List[Dict[str, Any]],
    *,
    max_items: int = 3,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for log in reversed(elicitation_log or []):
        if not isinstance(log, dict):
            continue
        turn = int(log.get("turn", 0) or 0)
        asker = str(log.get("asker_agent") or "").strip()
        asker_question = ""
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
            if agent == asker and not asker_question:
                asker_question = _extract_first_question(statement) or _compact_text(statement, 160)
            elif agent == "user" and not user_response:
                user_response = _compact_text(statement, 160)
        if not log.get("new_candidates_count"):
            missing_signal = "上一輪未形成新 candidate，應避開重複追問並換一個需求缺口。"
        elif log.get("new_candidate_texts"):
            first_new = str((log.get("new_candidate_texts") or [""])[0]).strip()
            if first_new:
                missing_signal = f"上一輪已挖到新方向：{_compact_text(first_new, 80)}；本輪避免重複。"
        if not asker_question:
            continue
        rows.append(
            {
                "turn": turn,
                "asker": asker,
                "question": asker_question,
                "user_signal": user_response,
                "user_action_type": user_action_type,
                "what_is_still_missing": missing_signal,
            }
        )
        if len(rows) >= max_items:
            break
    rows.reverse()
    return rows


def _asker_should_use_support(
    coordinator: Any,
    *,
    asker_role: str,
    topic: Dict[str, Any],
    support_inputs: List[Dict[str, Any]],
    previous_turn_summary: Optional[Dict[str, Any]],
) -> bool:
    """由 asker 自行判斷本輪要用 support 建議，或直接提問。"""
    if not support_inputs:
        return False
    # 先用 asker's role 決定策略（可被 config 覆蓋）：
    # always: 一律使用 support
    # never: 一律直接提問
    # decide: 交由該 asker 的模型判斷
    role_policy_cfg = coordinator.flow.config.get("elicitation_support_by_asker") or {}
    policy = str(role_policy_cfg.get(asker_role, "")).strip().lower()
    if not policy:
        default_policy = {
            "analyst": "always",
            "expert": "decide",
            "modeler": "decide",
        }
        policy = default_policy.get(asker_role, "decide")
    if policy == "always":
        return True
    if policy == "never":
        return False
    asker_agent = coordinator.flow.registry.get(asker_role)
    if not asker_agent or not hasattr(asker_agent, "build_direct_messages"):
        return True
    support_preview: List[Dict[str, str]] = []
    for row in support_inputs[:5]:
        if not isinstance(row, dict):
            continue
        agent = str(row.get("agent") or "").strip()
        resp = row.get("response", {}) if isinstance(row.get("response"), dict) else {}
        text = str(resp.get("statement") or resp.get("content") or "").strip()
        if text:
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    parsed["agent"] = agent
                    support_preview.append(parsed)
                    continue
            except Exception:
                pass
            support_preview.append({"agent": agent, "summary": _compact_text(text, 180)})
    prompt = (
        "你即將擔任本輪需求挖掘的 asker。請判斷你是否需要使用 support 建議再提問。\n\n"
        f"# 議題\n{str(topic.get('title') or '').strip()}\n"
        f"{str(topic.get('description') or '').strip()[:600]}\n\n"
        f"# 上一輪摘要\n{json.dumps(previous_turn_summary or {}, ensure_ascii=False)}\n\n"
        f"# 本輪 support 建議摘要\n{json.dumps(support_preview, ensure_ascii=False)}\n\n"
        "# 判斷規則\n"
        "- 若 support 建議能幫你補齊明確追問方向，use_support=true\n"
        "- 若你已可直接提出高品質問題，use_support=false\n"
        "- 僅輸出 JSON\n"
        '{"use_support": true/false, "reason": "一句話"}'
    )
    try:
        messages = asker_agent.build_direct_messages(prompt)
        data = asker_agent.model.chat_json(messages)
        if isinstance(data, dict):
            return bool(data.get("use_support", True))
    except Exception as e:
        coordinator.flow.logger.warning("asker support 決策失敗（%s）：%s", asker_role, e)
    return True


# ---------- 主流程 ----------

def run_hidden_requirement_elicitation_meeting_block(
    coordinator: Any,
    artifact: Dict[str, Any],
    round_num: int,
) -> Dict[str, Any]:
    """隱性需求挖掘會議：Mediator 規劃 -> 多輪對話 -> Analyst 結構化收尾。"""
    if not coordinator.flow.config.get("enable_elicitation", True):
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
    previous_turn_summary: Optional[Dict[str, Any]] = None

    all_candidates: List[Dict[str, Any]] = []
    elicitation_log: List[Dict[str, Any]] = []
    termination_reason = "max_turns_reached"
    stop_phrase = (
        "I have gathered enough information"
        if current_output_language() == "en"
        else "我已蒐集足夠資訊"
    )

    def _append_finish_turn(final_turn: int, final_asker: str) -> None:
        final_recent_ask_history = _build_recent_ask_history(elicitation_log, max_items=3)
        final_statement = stop_phrase
        final_contributions = [
            {
                "agent": final_asker,
                "response": {"statement": final_statement},
            }
        ]
        final_new_candidates = _extract_elicitation_candidates(
            coordinator, final_contributions, artifact, round_num=round_num, turn=final_turn
        )
        if final_new_candidates:
            all_candidates.extend(final_new_candidates)
        final_turn_log = {
            "round": round_num,
            "turn": final_turn,
            "topic_id": f"ELICIT-R{round_num}-T{final_turn}",
            "contributions_count": len(final_contributions),
            "contributions": [{"agent": final_asker, "statement": final_statement}],
            "speaking_order": [final_asker, "user"],
            "mode_strategy": "forced_finish",
            "collectors": [],
            "asker_agent": final_asker,
            "asker_use_support": False,
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
        turn_strategy = coordinator.flow.mediator_agent.decide_elicitation_turn_strategy(
            artifact=artifact,
            turn=turn,
            max_turns=max_turns,
            default_participants=participants,
            default_speaking_order=interviewers + ["user"],
            default_mode="sequential",
            previous_turn_summary=previous_turn_summary,
        )
        turn_participants = turn_strategy.get("participants") or participants
        turn_asker = str(turn_strategy.get("asker") or "").strip()
        turn_collectors = [
            str(x).strip() for x in (turn_strategy.get("collectors") or []) if str(x).strip()
        ]

        req_summary = json.dumps(
            [
                {"id": r.get("id"), "text": (r.get("text") or "")[:80]}
                for r in artifact.get("requirements", [])
                if isinstance(r, dict)
            ],
            ensure_ascii=False,
        )
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
                "你的目標是從 User 的回答中挖掘出尚未被明確記錄的隱性需求。\n"
                "請根據目前需求、前面對話與提問建議，優先追問最可能補齊需求缺口的一個方向。\n"
                "請避免重複既有需求，並優先釐清仍會影響核心功能、內容範圍、操作方式、使用者偏好、介面呈現偏好或重要限制的問題。\n"
                "\n"
                f"目前已有需求：\n{req_summary}\n"
                f"{prev_text}\n\n"
                "請不要重複已有需求，專注挖掘新的隱性需求。"
            ),
            "category": "open_question",
            "participants": turn_participants,
            "discussion_mode": "sequential",
            "speaking_order": interviewers + ["user"],
            "source_ids": [],
        }
        contributions: List[Dict[str, Any]] = []
        if "user" not in turn_participants:
            turn_participants = list(turn_participants) + ["user"]
        interviewers = [p for p in turn_participants if p != "user"]
        if not turn_asker or turn_asker not in interviewers:
            if interviewers:
                turn_asker = interviewers[(turn - 1) % len(interviewers)]
            else:
                turn_asker = "analyst"
        valid_collectors = [r for r in turn_collectors if r in interviewers and r != turn_asker]
        if not valid_collectors:
            valid_collectors = [r for r in interviewers if r != turn_asker][:2]
        turn_collectors = valid_collectors
        turn_speaking_order = turn_collectors + [turn_asker, "user"]

        collector_topic = {
            **topic,
            "id": f"{topic['id']}-COLLECT",
            "title": f"{topic['title']}｜提問資訊蒐集",
            "participants": turn_collectors,
            "speaking_order": turn_collectors,
            "discussion_mode": "sequential",
            "collector_mode": True,
        }
        snapshot = coordinator.flow.mediator_agent.build_artifact_snapshot(artifact)
        for role in turn_collectors:
            agent = coordinator.flow.registry.get(role)
            if not agent:
                coordinator.flow.logger.warning("Support role '%s' 未註冊，跳過", role)
                continue
            try:
                response = agent.respond_to_topic(
                    collector_topic, previous_responses=contributions, artifact_snapshot=snapshot
                )
                contributions.append(
                    {
                        "agent": role,
                        "response": response if isinstance(response, dict) else {"content": str(response)},
                    }
                )
            except Exception as e:
                coordinator.flow.logger.warning("Support role '%s' 蒐集失敗: %s", role, e)
                contributions.append({"agent": role, "response": {"content": f"（蒐集失敗: {e}）"}})

        user_agent = coordinator.flow.registry.get("user")
        if user_agent:
            try:
                user_signal = user_agent.respond_to_topic(
                    collector_topic, previous_responses=contributions, artifact_snapshot=snapshot
                )
                contributions.append(
                    {
                        "agent": "user",
                        "response": user_signal if isinstance(user_signal, dict) else {"content": str(user_signal)},
                    }
                )
            except Exception as e:
                coordinator.flow.logger.warning("Collector 階段 user 回覆失敗: %s", e)

        curated_collector_inputs = _curate_collector_inputs(
            contributions,
            collectors=turn_collectors,
            include_user_signal=True,
        )
        use_support = _asker_should_use_support(
            coordinator,
            asker_role=turn_asker,
            topic=topic,
            support_inputs=curated_collector_inputs,
            previous_turn_summary=previous_turn_summary,
        )
        ask_seed_responses = list(curated_collector_inputs) if use_support else []
        recent_ask_history = _build_recent_ask_history(elicitation_log, max_items=3)
        ask_topic = {
            **topic,
            "id": f"{topic['id']}-ASK",
            "title": f"{topic['title']}｜主問題提問",
            "participants": [turn_asker, "user"],
            "speaking_order": [turn_asker, "user"],
            "discussion_mode": "sequential",
            "asker_agent": turn_asker,
            "collectors": turn_collectors,
            "use_support": use_support,
            "recent_ask_history": recent_ask_history,
            "seed_previous_responses": ask_seed_responses,
        }
        ask_contribs, _ = coordinator.flow.mediator_agent.moderate_sequential(
            ask_topic, coordinator.flow.registry, artifact=artifact
        )
        contributions.extend(ask_contribs)

        asker_finish = False
        asker_statement = ""
        judge_action_type = ""
        for c in ask_contribs:
            if not isinstance(c, dict) or c.get("agent") != turn_asker:
                continue
            resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
            asker_statement = str(resp.get("statement") or resp.get("content") or "").strip()
            if asker_statement:
                break
        if asker_statement and user_agent and hasattr(user_agent, "judge_interviewer_action_type"):
            try:
                judge_action_type = str(
                    user_agent.judge_interviewer_action_type(asker_statement)
                ).strip().lower()
                asker_finish = judge_action_type == "finish"
            except Exception as e:
                coordinator.flow.logger.warning("  finish 判定失敗（asker）: %s", e)

        new_candidates = _extract_elicitation_candidates(
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
        for c in contributions:
            if not isinstance(c, dict):
                continue
            agent_name = str(c.get("agent") or "").strip()
            resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
            statement = str(resp.get("statement") or resp.get("content") or "").strip()
            if not agent_name or not statement:
                continue
            contribution_rows.append({"agent": agent_name, "statement": statement})

        should_stop_after_this_turn = bool(asker_finish)
        stop_reason_after_this_turn = "judge_finish" if asker_finish else "judge_continue"

        turn_log = {
            "round": round_num,
            "turn": turn,
            "topic_id": topic["id"],
            "contributions_count": len(contributions),
            "contributions": contribution_rows,
            "speaking_order": turn_speaking_order,
            "mode_strategy": "mediator",
            "collectors": turn_collectors,
            "asker_agent": turn_asker,
            "asker_use_support": use_support,
            "judge_action_type": judge_action_type,
            "judge_finish": asker_finish,
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

        if new_candidates:
            all_candidates.extend(new_candidates)

        previous_turn_summary = {
            "turn": turn,
            "asker_agent": turn_asker,
            "new_candidates_count": len(new_candidates),
            "revealed_ids_count": len(revealed_ids),
            "speaking_order": turn_speaking_order,
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
        collectors_label = ",".join(turn_collectors) if turn_collectors else "-"
        asker_line = asker_statement[:120] + ("..." if len(asker_statement) > 120 else "")
        coordinator.flow.logger.info("  動作類型：%s", user_action_type or "unknown")
        coordinator.flow.logger.info("  與隱式需求相關：%s", user_is_relevant)
        coordinator.flow.logger.info("  已取得的需求：%s", user_revealed_ids)
        coordinator.flow.logger.info(
            "Plant: collector:[%s], asker: %s | %s",
            collectors_label,
            turn_asker,
            asker_line or "(no statement)",
        )
        if user_statement:
            coordinator.flow.logger.info(
                "  User: %s", user_statement[:80] + ("..." if len(user_statement) > 80 else "")
            )
        coordinator.flow.logger.info(
            "  觀察：總需求=%s，剩餘=%s，取得比例=%.2f%%",
            total_requirements,
            remaining_total,
            ratio * 100.0,
        )
        if should_stop_after_this_turn:
            termination_reason = stop_reason_after_this_turn
            if stop_reason_after_this_turn == "forced_finish_at_max_turn":
                coordinator.flow.logger.info("  停止：本輪完成後已達最後一輪，以 finish action 收斂")
            else:
                # judge / mediator gate 決定停止時，補一輪收尾，讓 record 可穩定呈現最後一輪 finish。
                _append_finish_turn(min(max_turns, turn + 1), turn_asker)
                coordinator.flow.logger.info(
                    "  停止：本輪完成後，judge 判定為 finish（reason=%s）",
                    stop_reason_after_this_turn,
                )
            break

    if termination_reason == "max_turns_reached":
        # 達上限時，最後一輪直接進入 finish 收尾，不再執行 asker/user 對話。
        final_turn = max_turns
        final_asker = str((previous_turn_summary or {}).get("asker_agent") or "analyst").strip() or "analyst"
        _append_finish_turn(final_turn, final_asker)
        coordinator.flow.logger.info("[輪次 %s]", final_turn)
        coordinator.flow.logger.info("  動作類型：finish")
        coordinator.flow.logger.info("  停止：達到最後一輪，直接進入 finish 收尾（不再執行 asker/user）")
        termination_reason = "forced_finish_at_max_turn"

    all_candidates = _normalize_elicitation_candidates(all_candidates)

    artifact.setdefault("elicitation_log", []).extend(elicitation_log)
    artifact.setdefault("elicitation_candidates", []).extend(all_candidates)
    artifact["elicitation_termination_reason"] = termination_reason

    change_candidates: List[Dict[str, Any]] = []
    base_idx = len(artifact.get("requirement_change_candidates", []) or []) + 1
    for i, cand in enumerate(all_candidates):
        change_candidates.append(
            {
                "id": f"RC-ELICIT-R{round_num}-{base_idx + i:02d}",
                "requirement_id": cand.get("id") or f"ELICIT-{base_idx + i}",
                "change_type": "add",
                "field": "requirement",
                "before": None,
                "after": cand,
                "reason": cand.get("reason", "隱性需求挖掘會議中發現"),
                "source_ids": [f"ELICIT-R{round_num}"],
                "source_topic_id": f"ELICIT-R{round_num}",
                "status": "pending_review",
                "auto_apply": False,
            }
        )
    from .meeting_conflict_review import _append_requirement_change_candidates
    _append_requirement_change_candidates(artifact, change_candidates)

    coordinator.flow.store.save_artifact(artifact)
    return artifact
