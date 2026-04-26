from typing import Any, Dict, List, Optional

from agents.profile.mediator import AGENDA_CATEGORY_LABEL
from agents.agenda.schema import normalize_agenda_topic
from utils import Collect


# ---------- 純工具 ----------

def _partition_queue_skip_formal(
    queue: List[Any],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    non_formal: List[Dict[str, Any]] = []
    formal: List[Dict[str, Any]] = []
    for row in queue or []:
        if not isinstance(row, dict):
            continue
        if (row.get("triage_action") or "").strip() == "formal_meeting":
            formal.append(row)
        else:
            non_formal.append(row)
    return non_formal, formal


def _count_unanswered_open_questions(artifact: Dict[str, Any]) -> int:
    return sum(
        1
        for q in (artifact.get("open_questions", []) or [])
        if isinstance(q, dict) and q.get("status") != "answered"
    )


def _record_queue_item_trace(
    artifact: Dict[str, Any],
    *,
    queue_name: str,
    topic: Optional[Dict[str, Any]],
    substep: str,
    observation: Dict[str, Any],
    decision: Dict[str, Any],
    result: Dict[str, Any],
) -> None:
    artifact.setdefault("meeting_opa_trace", []).append(
        {
            "stage": f"queue.{queue_name}",
            "topic_id": (topic or {}).get("id"),
            "topic_title": (topic or {}).get("title"),
            "topic_category": (topic or {}).get("category"),
            "agent": "meeting_queue",
            "trace": {
                "agent": "meeting_queue",
                "mode": "queue_item_substep",
                "iteration": 1,
                "observation": observation,
                "decision": decision,
                "result": result,
                "substep": substep,
            },
        }
    )


# ---------- queue round summary ----------

def _build_queue_round_summary(
    artifact: Dict[str, Any],
    *,
    round_num: int,
) -> Dict[str, Any]:
    logs = [
        row for row in (artifact.get("queue_execution_log", []) or [])
        if isinstance(row, dict) and int(row.get("round") or -1) == round_num
    ]
    summary = {
        "round": round_num,
        "clarification_queue": {"processed": 0, "answered": 0, "deferred": 0},
        "human_decision_queue": {"processed": 0, "decided": 0, "deferred": 0},
        "direct_apply_queue": {"processed": 0, "queued_change_candidate": 0, "skipped": 0},
    }
    for row in logs:
        queue = row.get("queue")
        status = row.get("status")
        if queue == "clarification_queue":
            summary[queue]["processed"] += 1
            if status == "answered":
                summary[queue]["answered"] += 1
            else:
                summary[queue]["deferred"] += 1
        elif queue == "human_decision_queue":
            summary[queue]["processed"] += 1
            if status == "decided":
                summary[queue]["decided"] += 1
            else:
                summary[queue]["deferred"] += 1
        elif queue == "direct_apply_queue":
            summary[queue]["processed"] += 1
            if status == "queued_change_candidate":
                summary[queue]["queued_change_candidate"] += 1
            else:
                summary[queue]["skipped"] += 1
    return summary


# ---------- ingest effects ----------

def _ingest_round_resolution_effects(
    coordinator: Any,
    artifact: Dict[str, Any],
    round_discussions: List[Dict[str, Any]],
    *,
    round_num: int,
) -> None:
    oq_pool = artifact.get("open_questions", []) or []
    new_candidates: List[Dict[str, Any]] = []
    resolution_effects = artifact.get("topic_resolution_effects", []) or []
    approval_queue = artifact.get("approval_queue", []) or []
    seen_approval = {
        (
            str(row.get("topic_id") or "").strip(),
            tuple(sorted(str(x).strip() for x in (row.get("affected_requirement_ids") or []) if str(x).strip())),
        )
        for row in approval_queue
        if isinstance(row, dict)
    }
    for item in round_discussions:
        if not isinstance(item, dict):
            continue
        topic = item.get("topic", {}) if isinstance(item.get("topic"), dict) else {}
        resolution = item.get("resolution", {}) if isinstance(item.get("resolution"), dict) else {}
        source_ids = list(topic.get("source_ids", []) or [])
        for oq in resolution.get("new_open_questions", []) or []:
            if not isinstance(oq, dict):
                continue
            oq_pool.append(
                {
                    **oq,
                    "topic_id": topic.get("id"),
                    "status": oq.get("status") or "pending",
                    "round": round_num,
                }
            )
        if resolution.get("resolution_status") in {"agreed", "human_decision", "direct_clarification"}:
            from .meeting_conflict_review import _close_related_open_questions
            _close_related_open_questions(artifact, source_ids, round_num=round_num)
        affected_conflict_ids = resolution.get("affected_conflict_ids", []) or []
        decision_id = str(resolution.get("decision_id") or "").strip()
        if resolution.get("resolution_status") == "human_decision" and affected_conflict_ids and decision_id:
            from .meeting_conflict_review import _mark_conflicts_resolved_by_ids
            _mark_conflicts_resolved_by_ids(
                artifact, affected_conflict_ids, decision_id=decision_id,
            )
        affected_requirement_ids = [
            str(rid).strip()
            for rid in (resolution.get("affected_requirement_ids", []) or [])
            if str(rid).strip()
        ]
        verification_impact = resolution.get("verification_impact", {}) or {}
        if not isinstance(verification_impact, dict):
            verification_impact = {}
        needs_approval = bool(resolution.get("needs_approval"))
        _dod_ok = bool(
            resolution.get("decision")
            and affected_requirement_ids
        )
        resolution_effects.append(
            {
                "topic_id": topic.get("id"),
                "round": round_num,
                "resolution_status": resolution.get("resolution_status"),
                "affected_requirement_ids": affected_requirement_ids,
                "verification_impact": {
                    "level": str(verification_impact.get("level") or "none").strip() or "none",
                    "notes": str(verification_impact.get("notes") or "").strip(),
                },
                "needs_approval": needs_approval,
                "dod_complete": _dod_ok,
            }
        )
        if needs_approval:
            key = (str(topic.get("id") or "").strip(), tuple(sorted(affected_requirement_ids)))
            if key not in seen_approval:
                approval_queue.append(
                    {
                        "topic_id": topic.get("id"),
                        "round": round_num,
                        "status": "pending",
                        "summary": str(resolution.get("summary") or "").strip(),
                        "decision": str(resolution.get("decision") or "").strip(),
                        "affected_requirement_ids": affected_requirement_ids,
                        "verification_impact": {
                            "level": str(verification_impact.get("level") or "none").strip() or "none",
                            "notes": str(verification_impact.get("notes") or "").strip(),
                        },
                    }
                )
                seen_approval.add(key)
        for candidate in resolution.get("requirement_change_candidates", []) or []:
            if not isinstance(candidate, dict):
                continue
            candidate.setdefault("source_topic_id", topic.get("id"))
            new_candidates.append(candidate)
    artifact["open_questions"] = oq_pool
    artifact["topic_resolution_effects"] = resolution_effects
    artifact["approval_queue"] = approval_queue
    from .meeting_conflict_review import _append_requirement_change_candidates
    _append_requirement_change_candidates(artifact, new_candidates)


# ---------- queue topic record ----------

def _queue_topic_record(
    coordinator: Any,
    row: Dict[str, Any],
    *,
    queue_prefix: str,
    index: int,
    triage_action: str,
) -> Dict[str, Any]:
    normalized = normalize_agenda_topic(
        {
            "id": f"{queue_prefix}-{index:02d}",
            "title": (row.get("title") or "待處理事項").strip(),
            "description": (row.get("description") or "").strip(),
            "category": row.get("category") or "open_question",
            "participants": row.get("participants", []),
            "discussion_mode": row.get("discussion_mode", "sequential"),
            "speaking_order": row.get("speaking_order", []),
            "source_ids": row.get("source_ids", []),
            "source_proposal_ids": [row.get("proposal_id")] if row.get("proposal_id") else [],
            "triage_action": triage_action,
            "status": "processed",
        },
        allowed_categories=list(AGENDA_CATEGORY_LABEL.keys()),
        registered_agents=list(coordinator.flow.registry.get_names()) if coordinator.flow.registry else ["analyst", "expert", "modeler", "user"],
        index=index,
    )
    return normalized or {
        "schema_version": "agenda_topic.v1",
        "id": f"{queue_prefix}-{index:02d}",
        "title": (row.get("title") or "待處理事項").strip(),
        "description": (row.get("description") or "").strip(),
        "category": row.get("category") or "open_question",
        "participants": row.get("participants", []),
        "discussion_mode": row.get("discussion_mode", "sequential"),
        "speaking_order": row.get("speaking_order", []),
        "source_ids": row.get("source_ids", []),
        "source_proposal_ids": [row.get("proposal_id")] if row.get("proposal_id") else [],
        "status": "processed",
        "triage_action": triage_action,
    }


# ---------- 三條 queue 執行 ----------

def _execute_clarification_queue(
    coordinator: Any,
    artifact: Dict[str, Any],
    runner: Any,
    *,
    round_num: int,
) -> None:
    queue = artifact.get("clarification_queue", []) or []
    if not queue:
        return
    snapshot = coordinator.flow.mediator_agent.build_artifact_snapshot(artifact)
    oq_pool = artifact.get("open_questions", []) or []
    execution_log = artifact.get("queue_execution_log", []) or []
    for idx, row in enumerate(queue, 1):
        if not isinstance(row, dict):
            continue
        topic = _queue_topic_record(
            coordinator, row, queue_prefix="CQ", index=idx, triage_action="direct_clarification",
        )
        _record_queue_item_trace(
            artifact,
            queue_name="clarification_queue",
            topic=topic,
            substep="clarification.observe_item",
            observation={"proposal_id": row.get("proposal_id"), "index": idx},
            decision={"action": "prepare_topic", "params": {"topic_id": topic.get("id")}, "reasoning": "將 queue item 正規化為 agenda topic。"},
            result={"target_candidates": topic.get("participants", []), "source_ids": topic.get("source_ids", [])},
        )
        target_name = ((topic.get("speaking_order") or topic.get("participants") or ["analyst"])[0] or "analyst")
        agent = coordinator.flow.registry.get(target_name) if coordinator.flow.registry else None
        if not agent:
            _record_queue_item_trace(
                artifact,
                queue_name="clarification_queue",
                topic=topic,
                substep="clarification.defer_no_agent",
                observation={"target_name": target_name},
                decision={"action": "defer", "params": {}, "reasoning": "找不到對應 agent，暫時遞延。"},
                result={"status": "deferred_no_agent"},
            )
            row["status"] = "deferred"
            row["queue_processed_round"] = round_num
            execution_log.append(
                {"round": round_num, "queue": "clarification_queue", "proposal_id": row.get("proposal_id"), "status": "deferred_no_agent"}
            )
            continue
        try:
            response = coordinator.flow.mediator_agent.collect_topic_response(
                agent,
                topic,
                previous_responses=None,
                artifact_snapshot=snapshot,
            )
            _record_queue_item_trace(
                artifact,
                queue_name="clarification_queue",
                topic=topic,
                substep="clarification.collect_response",
                observation={"target_name": target_name, "has_snapshot": bool(snapshot)},
                decision={"action": "collect_topic_response", "params": {"target_name": target_name}, "reasoning": "收集定向釐清回答。"},
                result={"statement_present": bool((response.get("statement") or "").strip()), "open_questions_count": len(response.get("open_questions", []) or [])},
            )
            statement = (response.get("statement") or "").strip()
            open_questions = response.get("open_questions", []) or []
            for q in open_questions:
                if not isinstance(q, dict):
                    continue
                oq_pool.append(
                    {
                        "topic_id": topic.get("id"),
                        "from_agent": target_name,
                        "to_agent": q.get("to"),
                        "question": (q.get("question") or "").strip(),
                        "status": "pending",
                        "round": round_num,
                        "type": "clarification_follow_up",
                    }
                )
            resolution = coordinator.flow.mediator_agent.build_topic_result(
                resolution_status="direct_clarification",
                summary=statement or "已執行定向釐清，但未取得明確回答。",
                decision="",
                votes={},
                votes_summary="direct_clarification",
                mediator_compromise={},
                agreed_points=[statement] if statement else [],
                unresolved_points=[] if statement else ["尚未取得可用回答。"],
                new_open_questions=[],
                affected_conflict_ids=[
                    sid for sid in (topic.get("source_ids") or [])
                    if isinstance(sid, str) and sid.startswith("CF-")
                ],
                requirement_change_candidates=(
                    [
                        {
                            "id": f"RC-CQ-{round_num:02d}-{idx:02d}",
                            "requirement_id": next(
                                (sid for sid in (topic.get("source_ids") or []) if isinstance(sid, str) and sid.startswith(("REQ-", "FR-", "NFR-"))),
                                "",
                            ),
                            "change_type": "update",
                            "field": "text",
                            "before": None,
                            "after": statement,
                            "reason": "Derived from direct clarification response.",
                            "source_ids": list(topic.get("source_ids", [])),
                            "status": "pending_review",
                            "auto_apply": False,
                        }
                    ]
                    if statement and any(isinstance(sid, str) and sid.startswith(("REQ-", "FR-", "NFR-")) for sid in (topic.get("source_ids") or []))
                    else []
                ),
                needs_human=False,
            )
            runner.round_discussions.append(
                {"topic": {**topic, "status": "processed"}, "source_ids": topic.get("source_ids", []), "contributions": [{"agent": target_name, "response": response}], "resolution": resolution}
            )
            trace_rows = artifact.setdefault("meeting_opa_trace", [])
            if isinstance(response, dict):
                for row in (response.get("opa_trace") or []):
                    if not isinstance(row, dict):
                        continue
                    trace_rows.append(
                        {
                            "stage": "direct_clarification",
                            "topic_id": topic.get("id"),
                            "topic_title": topic.get("title"),
                            "topic_category": topic.get("category"),
                            "agent": target_name,
                            "trace": row,
                        }
                    )
            row["status"] = "answered" if statement else "deferred"
            row["queue_processed_round"] = round_num
            _record_queue_item_trace(
                artifact,
                queue_name="clarification_queue",
                topic=topic,
                substep="clarification.finalize_item",
                observation={"statement_present": bool(statement)},
                decision={"action": "finalize_queue_item", "params": {"topic_id": topic.get("id")}, "reasoning": "根據回答結果更新 queue item 狀態與 round discussion。"},
                result={"status": row["status"]},
            )
            execution_log.append(
                {"round": round_num, "queue": "clarification_queue", "proposal_id": row.get("proposal_id"), "status": row["status"], "handled_by": target_name}
            )
        except Exception as e:
            coordinator.flow.logger.warning("clarification_queue 執行失敗: %s", e)
            _record_queue_item_trace(
                artifact,
                queue_name="clarification_queue",
                topic=topic,
                substep="clarification.error",
                observation={"target_name": target_name},
                decision={"action": "collect_topic_response", "params": {"target_name": target_name}, "reasoning": "嘗試收集定向釐清回答。"},
                result={"error": str(e)},
            )
            row["status"] = "deferred"
            row["queue_processed_round"] = round_num
    artifact["open_questions"] = oq_pool
    artifact["queue_execution_log"] = execution_log


def _execute_human_decision_queue(
    coordinator: Any,
    artifact: Dict[str, Any],
    runner: Any,
    *,
    round_num: int,
) -> None:
    queue = artifact.get("human_decision_queue", []) or []
    if not queue:
        return
    execution_log = artifact.get("queue_execution_log", []) or []
    for idx, row in enumerate(queue, 1):
        if not isinstance(row, dict):
            continue
        topic = _queue_topic_record(
            coordinator, row, queue_prefix="HQ", index=idx, triage_action="human_decision",
        )
        _record_queue_item_trace(
            artifact,
            queue_name="human_decision_queue",
            topic=topic,
            substep="human.observe_item",
            observation={"proposal_id": row.get("proposal_id"), "index": idx},
            decision={"action": "prepare_human_decision", "params": {"topic_id": topic.get("id")}, "reasoning": "將 queue item 整理成人類裁決輸入。"},
            result={"source_ids": topic.get("source_ids", [])},
        )
        options = {
            "best_options": [],
            "compromise": {
                "id": 1,
                "title": topic.get("title", ""),
                "description": topic.get("description", ""),
                "rationale": row.get("why_now", ""),
            },
        }
        _record_queue_item_trace(
            artifact,
            queue_name="human_decision_queue",
            topic=topic,
            substep="human.prepare_options",
            observation={"topic_id": topic.get("id")},
            decision={"action": "build_options", "params": {}, "reasoning": "建立人類裁決的最小選項集。"},
            result={"options_count": 1},
        )
        resolution_raw = Collect.human_decision_on_topic(topic, options)
        _record_queue_item_trace(
            artifact,
            queue_name="human_decision_queue",
            topic=topic,
            substep="human.collect_decision",
            observation={"topic_id": topic.get("id"), "options_count": 1},
            decision={"action": "collect_human_decision", "params": {"topic_id": topic.get("id")}, "reasoning": "交由人類裁決 queue item。"},
            result={"decision": str(resolution_raw.get("decision", "")).strip()},
        )
        decision_text = str(resolution_raw.get("decision", "")).strip()
        decision_id = f"DEC-HQ-{round_num:02d}-{idx:02d}" if decision_text else ""
        resolution = coordinator.flow.mediator_agent.build_topic_result(
            resolution_status="human_decision",
            summary=decision_text or "此議題已送人工裁決，但暫未定案。",
            decision=decision_text,
            votes={},
            votes_summary="human_decision_queue",
            mediator_compromise={},
            agreed_points=[decision_text] if decision_text else [],
            unresolved_points=[] if decision_text else ["人類選擇暫不裁決。"],
            new_open_questions=[],
            affected_conflict_ids=[
                sid for sid in (topic.get("source_ids") or [])
                if isinstance(sid, str) and sid.startswith("CF-")
            ],
            requirement_change_candidates=(
                [
                    {
                        "id": f"RC-HQ-{round_num:02d}-{idx:02d}",
                        "requirement_id": next(
                            (sid for sid in (topic.get("source_ids") or []) if isinstance(sid, str) and sid.startswith(("REQ-", "FR-", "NFR-"))),
                            "",
                        ),
                        "change_type": "update",
                        "field": "text",
                        "before": None,
                        "after": decision_text,
                        "reason": "Derived from human decision queue result.",
                        "source_ids": list(topic.get("source_ids", [])),
                        "status": "pending_review",
                        "auto_apply": False,
                    }
                ]
                if decision_text and any(isinstance(sid, str) and sid.startswith(("REQ-", "FR-", "NFR-")) for sid in (topic.get("source_ids") or []))
                else []
            ),
            needs_human=True,
        )
        if decision_id:
            resolution["decision_id"] = decision_id
        resolution["human_decision_raw"] = resolution_raw
        runner.round_discussions.append(
            {"topic": {**topic, "status": "processed"}, "source_ids": topic.get("source_ids", []), "contributions": [], "resolution": resolution}
        )
        if decision_text:
            decisions = artifact.get("decisions", []) or []
            decisions.append(
                {
                    "id": decision_id,
                    "summary": decision_text,
                    "decision": decision_text,
                    "source_topic_id": topic.get("id"),
                    "resolved_conflict_ids": resolution.get("affected_conflict_ids", []),
                }
            )
            artifact["decisions"] = decisions
            from .meeting_conflict_review import _mark_conflicts_resolved_by_ids
            _mark_conflicts_resolved_by_ids(
                artifact, resolution.get("affected_conflict_ids", []), decision_id=decision_id,
            )
            row["status"] = "decided"
        else:
            row["status"] = "deferred"
        row["queue_processed_round"] = round_num
        _record_queue_item_trace(
            artifact,
            queue_name="human_decision_queue",
            topic=topic,
            substep="human.finalize_item",
            observation={"decision_present": bool(decision_text)},
            decision={"action": "finalize_queue_item", "params": {"topic_id": topic.get("id")}, "reasoning": "將人類裁決結果寫回 artifact 與 queue 狀態。"},
            result={"status": row["status"], "decision_id": decision_id},
        )
        execution_log.append(
            {"round": round_num, "queue": "human_decision_queue", "proposal_id": row.get("proposal_id"), "status": row["status"]}
        )
    artifact["queue_execution_log"] = execution_log


def _execute_direct_apply_queue(
    coordinator: Any,
    artifact: Dict[str, Any],
    *,
    round_num: int,
) -> None:
    queue = artifact.get("direct_apply_queue", []) or []
    if not queue:
        return
    execution_log = artifact.get("queue_execution_log", []) or []
    candidates: List[Dict[str, Any]] = []
    next_idx = len(artifact.get("requirement_change_candidates", []) or []) + 1
    for row in queue:
        if not isinstance(row, dict):
            continue
        _record_queue_item_trace(
            artifact,
            queue_name="direct_apply_queue",
            topic=None,
            substep="direct_apply.observe_item",
            observation={"proposal_id": row.get("proposal_id")},
            decision={"action": "inspect_direct_apply_item", "params": {"source_ids": row.get("source_ids", [])}, "reasoning": "檢查 queue item 是否可形成 requirement change candidate。"},
            result={"source_ids": row.get("source_ids", [])},
        )
        req_ids = [
            sid for sid in (row.get("source_ids") or [])
            if isinstance(sid, str) and sid.startswith(("REQ-", "FR-", "NFR-"))
        ]
        if not req_ids:
            _record_queue_item_trace(
                artifact,
                queue_name="direct_apply_queue",
                topic=None,
                substep="direct_apply.skip_no_requirement_id",
                observation={"proposal_id": row.get("proposal_id")},
                decision={"action": "skip", "params": {}, "reasoning": "缺少 requirement id，無法轉成 change candidate。"},
                result={"status": "skipped_no_requirement_id"},
            )
            row["status"] = "skipped_no_requirement_id"
            row["queue_processed_round"] = round_num
            execution_log.append(
                {"round": round_num, "queue": "direct_apply_queue", "proposal_id": row.get("proposal_id"), "status": row["status"]}
            )
            continue
        candidate_id = f"RC-QA-{next_idx:03d}"
        candidates.append(
            {
                "id": candidate_id,
                "requirement_id": req_ids[0],
                "change_type": "update",
                "field": "text",
                "before": None,
                "after": row.get("description", ""),
                "reason": row.get("why_now") or "Queued direct-apply proposal pending analyst review.",
                "source_ids": list(row.get("source_ids", [])),
                "status": "pending_review",
                "auto_apply": False,
            }
        )
        _record_queue_item_trace(
            artifact,
            queue_name="direct_apply_queue",
            topic=None,
            substep="direct_apply.queue_change_candidate",
            observation={"proposal_id": row.get("proposal_id"), "requirement_id": req_ids[0]},
            decision={"action": "queue_change_candidate", "params": {"requirement_id": req_ids[0]}, "reasoning": "將 direct-apply item 轉成待審 requirement change candidate。"},
            result={"candidate_id": candidate_id},
        )
        next_idx += 1
        row["status"] = "queued_change_candidate"
        row["queue_processed_round"] = round_num
        execution_log.append(
            {"round": round_num, "queue": "direct_apply_queue", "proposal_id": row.get("proposal_id"), "status": row["status"]}
        )
    from .meeting_conflict_review import _append_requirement_change_candidates
    _append_requirement_change_candidates(artifact, candidates)
    artifact["queue_execution_log"] = execution_log


# ---------- routed queues ----------

def _run_routed_queues(
    coordinator: Any,
    artifact: Dict[str, Any],
    runner: Any,
    *,
    round_num: int,
    drain_non_formal: bool = False,
) -> None:
    keys = ("clarification_queue", "human_decision_queue", "direct_apply_queue")
    held_formal: Dict[str, List[Dict[str, Any]]] = {k: [] for k in keys}
    if drain_non_formal:
        for k in keys:
            q = artifact.get(k) or []
            nf, fm = _partition_queue_skip_formal(q)
            artifact[k] = nf
            held_formal[k] = fm
        n_skip = sum(len(held_formal[k]) for k in keys)
        if n_skip:
            coordinator.flow.logger.info(
                "最後一輪：略過 formal_meeting 佇列項目共 %s 筆（仍保留於 artifact）", n_skip,
            )

    max_passes = 50 if drain_non_formal else 1
    prev_after = -1
    for pass_idx in range(max_passes):
        total_before = sum(len(artifact.get(k) or []) for k in keys)
        if drain_non_formal and total_before == 0:
            break
        _execute_clarification_queue(coordinator, artifact, runner, round_num=round_num)
        _execute_human_decision_queue(coordinator, artifact, runner, round_num=round_num)
        _execute_direct_apply_queue(coordinator, artifact, round_num=round_num)
        artifact["clarification_queue"] = [
            row for row in (artifact.get("clarification_queue", []) or [])
            if isinstance(row, dict) and row.get("status") == "deferred"
        ]
        artifact["human_decision_queue"] = [
            row for row in (artifact.get("human_decision_queue", []) or [])
            if isinstance(row, dict) and row.get("status") == "deferred"
        ]
        artifact["direct_apply_queue"] = [
            row for row in (artifact.get("direct_apply_queue", []) or [])
            if isinstance(row, dict) and row.get("status") not in {"queued_change_candidate"}
        ]
        total_after = sum(len(artifact.get(k) or []) for k in keys)
        if not drain_non_formal:
            break
        if total_after == 0:
            coordinator.flow.logger.info("最後一輪：非 formal 佇列已清空（第 %s 輪執行）", pass_idx + 1)
            break
        if pass_idx > 0 and total_after == prev_after:
            coordinator.flow.logger.warning("最後一輪：佇列無進度，停止重試（剩餘 %s 筆）", total_after)
            break
        prev_after = total_after
    if drain_non_formal:
        for k in keys:
            artifact[k] = held_formal[k] + (artifact.get(k) or [])


# ---------- topic post-processing ----------

def _triggered_roles_for_topic(
    topic_discussion: Dict[str, Any],
    artifact: Dict[str, Any],
) -> List[str]:
    roles: List[str] = []
    resolution = topic_discussion.get("resolution", {})
    if not isinstance(resolution, dict):
        return roles
    status = (resolution.get("resolution_status") or "").strip()
    if status not in {"agreed", "human_decision", "direct_clarification"}:
        roles.extend(["analyst", "expert"])
    if resolution.get("new_open_questions"):
        roles.append("expert")
    if resolution.get("requirement_change_candidates"):
        roles.append("analyst")
    if (
        artifact.get("system_models", {}).get("models")
        and resolution.get("requirement_change_candidates")
    ):
        roles.append("modeler")
    deduped: List[str] = []
    for r in roles:
        if r not in deduped:
            deduped.append(r)
    return deduped


def _post_topic_processing(
    coordinator: Any,
    artifact: Dict[str, Any],
    topic_discussion: Dict[str, Any],
    *,
    round_num: int,
) -> None:
    _ingest_round_resolution_effects(
        coordinator, artifact, [topic_discussion], round_num=round_num,
    )
    coordinator.flow.store.save_artifact(artifact)
    roles = _triggered_roles_for_topic(topic_discussion, artifact)
    if roles:
        coordinator.flow.logger.info("議題後觸發 review：%s", ", ".join(roles))
        from .main_meeting import _run_enabled_reviews
        _run_enabled_reviews(coordinator, artifact, recent_discussions=[topic_discussion], roles=roles)
        coordinator.flow.store.save_artifact(artifact)


# ---------- agenda loop ----------

def run_agenda_loop_block(coordinator: Any, runner: Any) -> None:
    obs = runner.run("generate_agenda", None)
    if obs.get("error"):
        coordinator.flow.logger.warning(f"  議程生成失敗: {obs['error']}")
    drain = coordinator._is_last_meeting_round(runner.artifact, runner.round_num)
    _run_routed_queues(
        coordinator,
        runner.artifact,
        runner,
        round_num=runner.round_num,
        drain_non_formal=drain,
    )
    coordinator.run_round_opa_loop(runner)
