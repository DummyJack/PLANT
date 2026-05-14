# Meeting subflows: queues, direct clarification/apply, and meeting loop dispatch.
from typing import Any, Dict, List, Optional

from agents.profile.mediator import ISSUE_CATEGORY_LABEL
from agents.profile.mediator.validation import decision_issue
from utils import Collect


# ---------- 純工具 ----------

def partition_queue_skip_formal(
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


def record_queue_item_trace(
    artifact: Dict[str, Any],
    *,
    queue_name: str,
    issue: Optional[Dict[str, Any]],
    substep: str,
    observation: Dict[str, Any],
    decision: Dict[str, Any],
    result: Dict[str, Any],
) -> None:
    artifact.setdefault("meeting_opa_trace", []).append(
        {
            "stage": f"queue.{queue_name}",
            "issue_id": (issue or {}).get("id"),
            "issue_title": (issue or {}).get("title"),
            "issue_category": (issue or {}).get("category"),
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

def build_queue_round_summary(
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

def ingest_round_resolution_effects(
    coordinator: Any,
    artifact: Dict[str, Any],
    round_discussions: List[Dict[str, Any]],
    *,
    round_num: int,
) -> None:
    oq_pool = artifact.get("open_questions", []) or []
    new_candidates: List[Dict[str, Any]] = []
    resolution_effects = artifact.get("issue_resolution_effects", []) or []
    pending_decisions = artifact.get("pending_decisions", []) or []
    seen_pending_decisions = {
        str(row.get("decision_id") or row.get("issue_id") or "").strip()
        for row in pending_decisions
        if isinstance(row, dict)
    }
    for item in round_discussions:
        if not isinstance(item, dict):
            continue
        issue = item.get("issue", {}) if isinstance(item.get("issue"), dict) else {}
        resolution = item.get("resolution", {}) if isinstance(item.get("resolution"), dict) else {}
        source_ids = list(issue.get("source_ids", []) or [])
        for oq in resolution.get("new_open_questions", []) or []:
            if not isinstance(oq, dict):
                continue
            oq_pool.append(
                {
                    **oq,
                    "issue_id": issue.get("id"),
                    "status": oq.get("status") or "pending",
                    "round": round_num,
                }
            )
        if resolution.get("resolution_status") in {"agreed", "human_decision", "direct_clarification"}:
            from .conflict_review import close_related_open_questions
            close_related_open_questions(artifact, source_ids, round_num=round_num)
        affected_conflict_ids = resolution.get("affected_conflict_ids", []) or []
        decision_id = str(resolution.get("decision_id") or "").strip()
        if resolution.get("resolution_status") == "human_decision" and affected_conflict_ids and decision_id:
            from .conflict_review import mark_conflicts_resolved_by_ids
            mark_conflicts_resolved_by_ids(
                artifact, affected_conflict_ids, decision_id=decision_id,
            )
        affected_requirement_ids = [
            str(rid).strip()
            for rid in (resolution.get("affected_requirement_ids", []) or [])
            if str(rid).strip()
        ]
        requirement_impact = resolution.get("requirement_impact", {}) or {}
        if not isinstance(requirement_impact, dict):
            requirement_impact = {}
        needs_human = bool(resolution.get("needs_human"))
        needs_approval = bool(resolution.get("needs_approval"))
        needs_user_confirmation = bool(resolution.get("needs_user_confirmation"))
        dod_ok = bool(
            resolution.get("decision")
            and affected_requirement_ids
        )
        resolution_effects.append(
            {
                "issue_id": issue.get("id"),
                "round": round_num,
                "resolution_status": resolution.get("resolution_status"),
                "affected_requirement_ids": affected_requirement_ids,
                "requirement_impact": {
                    "level": str(requirement_impact.get("level") or "none").strip() or "none",
                    "notes": str(requirement_impact.get("notes") or "").strip(),
                },
                "needs_approval": needs_approval,
                "needs_human": needs_human,
                "needs_user_confirmation": needs_user_confirmation,
                "dod_complete": dod_ok,
            }
        )
        if needs_human:
            existing_human_ids = {
                str(row.get("issue_id") or row.get("issue_id") or "").strip()
                for row in (artifact.get("human_decision_queue", []) or [])
                if isinstance(row, dict)
            }
            issue_id = f"HQ-R{round_num}-{issue.get('id') or len(existing_human_ids) + 1}"
            if issue_id not in existing_human_ids:
                artifact.setdefault("human_decision_queue", []).append(
                    {
                        "schema_version": "issue_proposal.v1",
                        "issue_id": issue_id,
                        "issue_id": issue.get("id"),
                        "round": round_num,
                        "title": issue.get("title"),
                        "description": str(resolution.get("summary") or "").strip(),
                        "category": "tradeoff",
                        "source_ids": source_ids,
                        "status": "pending",
                        "needs_human": True,
                        "routing_preference": "human_decision",
                        "options": resolution.get("options", []) or [],
                        "recommendation": resolution.get("recommendation", {}) or {},
                        "affected_requirement_ids": affected_requirement_ids,
                        "unresolved_points": resolution.get("unresolved_points", []) or [],
                    }
                )
            continue
        if needs_user_confirmation or needs_approval:
            decision_id = f"D-R{round_num}-{issue.get('id') or len(pending_decisions) + 1}"
            if decision_id not in seen_pending_decisions:
                pending_decisions.append(
                    {
                        "schema_version": "decision_analysis.v1",
                        "decision_id": decision_id,
                        "issue_id": issue.get("id"),
                        "round": round_num,
                        "title": issue.get("title"),
                        "source_ids": source_ids,
                        "status": "pending_confirmation",
                        "summary": str(resolution.get("summary") or "").strip(),
                        "options": resolution.get("options", []) or [],
                        "recommendation": resolution.get("recommendation", {}) or {},
                        "affected_requirement_ids": affected_requirement_ids,
                        "unresolved_points": resolution.get("unresolved_points", []) or [],
                        "decision": str(resolution.get("decision") or "").strip(),
                        "requirement_impact": {
                            "level": str(requirement_impact.get("level") or "none").strip() or "none",
                            "notes": str(requirement_impact.get("notes") or "").strip(),
                        },
                        "reason": "needs_user_confirmation" if needs_user_confirmation else "needs_change_confirmation",
                    }
                )
                seen_pending_decisions.add(decision_id)
            continue
        for candidate in resolution.get("change_record", []) or []:
            if not isinstance(candidate, dict):
                continue
            candidate.setdefault("source_issue_id", issue.get("id"))
            new_candidates.append(candidate)
    artifact["open_questions"] = oq_pool
    artifact["issue_resolution_effects"] = resolution_effects
    artifact["pending_decisions"] = pending_decisions
    from .conflict_review import append_change_record
    append_change_record(artifact, new_candidates)


# ---------- queue issue record ----------

def queue_issue_record(
    coordinator: Any,
    row: Dict[str, Any],
    *,
    queue_prefix: str,
    index: int,
    triage_action: str,
) -> Dict[str, Any]:
    normalized = decision_issue(
        {
            "id": f"{queue_prefix}-{index}",
            "title": (row.get("title") or "待處理事項").strip(),
            "description": (row.get("description") or "").strip(),
            "category": row.get("category") or "open_question",
            "participants": row.get("participants", []),
            "discussion_mode": row.get("discussion_mode", "sequential"),
            "speaking_order": row.get("speaking_order", []),
            "source_ids": row.get("source_ids", []),
            "source_issue_ids": [row.get("issue_id")] if row.get("issue_id") else [],
            "triage_action": triage_action,
            "status": "processed",
        },
        allowed_categories=list(ISSUE_CATEGORY_LABEL.keys()),
        registered_agents=list(coordinator.flow.registry.get_names()) if coordinator.flow.registry else ["analyst", "expert", "modeler", "user"],
        index=index,
    )
    return normalized or {
        "schema_version": "decision_issue.v1",
        "id": f"{queue_prefix}-{index}",
        "title": (row.get("title") or "待處理事項").strip(),
        "description": (row.get("description") or "").strip(),
        "category": row.get("category") or "open_question",
        "participants": row.get("participants", []),
        "discussion_mode": row.get("discussion_mode", "sequential"),
        "speaking_order": row.get("speaking_order", []),
        "source_ids": row.get("source_ids", []),
        "source_issue_ids": [row.get("issue_id")] if row.get("issue_id") else [],
        "status": "processed",
        "triage_action": triage_action,
    }


# ---------- 三條 queue 執行 ----------

def execute_clarification_queue(
    coordinator: Any,
    artifact: Dict[str, Any],
    runner: Any,
    *,
    round_num: int,
) -> None:
    queue = artifact.get("clarification_queue", []) or []
    if not queue:
        return
    coordinator.flow.store.save_artifact(artifact)
    oq_pool = artifact.get("open_questions", []) or []
    execution_log = artifact.get("queue_execution_log", []) or []
    for idx, row in enumerate(queue, 1):
        if not isinstance(row, dict):
            continue
        issue = queue_issue_record(
            coordinator, row, queue_prefix="CQ", index=idx, triage_action="direct_clarification",
        )
        record_queue_item_trace(
            artifact,
            queue_name="clarification_queue",
            issue=issue,
            substep="clarification.observe_item",
            observation={"issue_id": row.get("issue_id"), "index": idx},
            decision={"action": "prepare_issue", "params": {"issue_id": issue.get("id")}, "reasoning": "將 queue item 正規化為 decision issue。"},
            result={"target_candidates": issue.get("participants", []), "source_ids": issue.get("source_ids", [])},
        )
        target_candidates = issue.get("speaking_order") or issue.get("participants") or []
        target_name = (target_candidates[0] if target_candidates else "")
        agent = coordinator.flow.registry.get(target_name) if coordinator.flow.registry else None
        if not agent:
            raise RuntimeError(f"clarification_queue 目標 agent 未註冊: {target_name}")
        try:
            response = coordinator.flow.mediator_agent.collect_issue_response(
                agent,
                issue,
                previous_responses=None,
            )
            record_queue_item_trace(
                artifact,
                queue_name="clarification_queue",
                issue=issue,
                substep="clarification.collect_response",
                observation={"target_name": target_name, "artifact_context_source": "artifact_folder"},
                decision={"action": "collect_issue_response", "params": {"target_name": target_name}, "reasoning": "收集定向釐清回答。"},
                result={"statement_present": bool((response.get("statement") or "").strip()), "open_questions_count": len(response.get("open_questions", []) or [])},
            )
            statement = (response.get("statement") or "").strip()
            open_questions = response.get("open_questions", []) or []
            for q in open_questions:
                if not isinstance(q, dict):
                    continue
                oq_pool.append(
                    {
                        "issue_id": issue.get("id"),
                        "from_agent": target_name,
                        "to_agent": q.get("to"),
                        "question": (q.get("question") or "").strip(),
                        "status": "pending",
                        "round": round_num,
                        "type": "clarification_follow_up",
                    }
                )
            resolution = coordinator.flow.mediator_agent.build_issue_result(
                resolution_status="direct_clarification",
                summary=statement or "已執行定向釐清，但未取得明確回答。",
                decision="",
                mediator_compromise={},
                agreed_points=[statement] if statement else [],
                unresolved_points=[] if statement else ["尚未取得可用回答。"],
                new_open_questions=[],
                affected_conflict_ids=[
                    sid for sid in (issue.get("source_ids") or [])
                    if isinstance(sid, str) and sid.startswith("CF-")
                ],
                change_record=(
                    [
                        {
                            "id": f"RC-CQ-{round_num}-{idx}",
                            "requirement_id": next(
                                (sid for sid in (issue.get("source_ids") or []) if isinstance(sid, str) and sid.startswith(("REQ-", "FR-", "NFR-"))),
                                "",
                            ),
                            "change_type": "update",
                            "field": "text",
                            "before": None,
                            "after": statement,
                            "reason": "Derived from direct clarification response.",
                            "source_ids": list(issue.get("source_ids", [])),
                            "status": "pending_review",
                            "auto_apply": False,
                        }
                    ]
                    if statement and any(isinstance(sid, str) and sid.startswith(("REQ-", "FR-", "NFR-")) for sid in (issue.get("source_ids") or []))
                    else []
                ),
                needs_human=False,
            )
            runner.round_discussions.append(
                {"issue": {**issue, "status": "processed"}, "source_ids": issue.get("source_ids", []), "contributions": [{"agent": target_name, "response": response}], "resolution": resolution}
            )
            trace_rows = artifact.setdefault("meeting_opa_trace", [])
            if isinstance(response, dict):
                for row in (response.get("opa_trace") or []):
                    if not isinstance(row, dict):
                        continue
                    trace_rows.append(
                        {
                            "stage": "direct_clarification",
                            "issue_id": issue.get("id"),
                            "issue_title": issue.get("title"),
                            "issue_category": issue.get("category"),
                            "agent": target_name,
                            "trace": row,
                        }
                    )
            if not statement:
                raise RuntimeError("clarification_queue agent 回答缺少 statement")
            row["status"] = "answered"
            row["queue_processed_round"] = round_num
            record_queue_item_trace(
                artifact,
                queue_name="clarification_queue",
                issue=issue,
                substep="clarification.finalize_item",
                observation={"statement_present": bool(statement)},
                decision={"action": "finalize_queue_item", "params": {"issue_id": issue.get("id")}, "reasoning": "根據回答結果更新 queue item 狀態與 round discussion。"},
                result={"status": row["status"]},
            )
            execution_log.append(
                {"round": round_num, "queue": "clarification_queue", "issue_id": row.get("issue_id"), "status": row["status"], "handled_by": target_name}
            )
        except Exception as e:
            raise RuntimeError("clarification_queue 執行失敗") from e
    artifact["open_questions"] = oq_pool
    artifact["queue_execution_log"] = execution_log


def execute_human_decision_queue(
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
        issue = queue_issue_record(
            coordinator, row, queue_prefix="HQ", index=idx, triage_action="human_decision",
        )
        record_queue_item_trace(
            artifact,
            queue_name="human_decision_queue",
            issue=issue,
            substep="human.observe_item",
            observation={"issue_id": row.get("issue_id"), "index": idx},
            decision={"action": "prepare_human_decision", "params": {"issue_id": issue.get("id")}, "reasoning": "將 queue item 整理成人類裁決輸入。"},
            result={"source_ids": issue.get("source_ids", [])},
        )
        options = {
            "best_options": [],
            "compromise": {
                "id": 1,
                "title": issue.get("title", ""),
                "description": issue.get("description", ""),
                "rationale": row.get("why_now", ""),
            },
        }
        if row.get("options"):
            best_options = []
            for idx_opt, opt in enumerate(row.get("options") or [], start=1):
                if not isinstance(opt, dict):
                    continue
                best_options.append(
                    {
                        "id": idx_opt,
                        "title": f"{opt.get('id')}: {opt.get('summary') or opt.get('title') or ''}",
                        "description": opt.get("summary") or opt.get("description") or "",
                        "source": "formal_meeting_options",
                    }
                )
            options = {"best_options": best_options, "compromise": {}}
        record_queue_item_trace(
            artifact,
            queue_name="human_decision_queue",
            issue=issue,
            substep="human.prepare_options",
            observation={"issue_id": issue.get("id")},
            decision={"action": "build_options", "params": {}, "reasoning": "建立人類裁決的最小選項集。"},
            result={"options_count": 1},
        )
        resolution_raw = Collect.human_decision_on_issue(issue, options)
        record_queue_item_trace(
            artifact,
            queue_name="human_decision_queue",
            issue=issue,
            substep="human.collect_decision",
            observation={"issue_id": issue.get("id"), "options_count": 1},
            decision={"action": "collect_human_decision", "params": {"issue_id": issue.get("id")}, "reasoning": "交由人類裁決 queue item。"},
            result={"decision": str(resolution_raw.get("decision", "")).strip()},
        )
        decision_text = str(resolution_raw.get("decision", "")).strip()
        decision_id = f"DEC-HQ-{round_num}-{idx}" if decision_text else ""
        resolution = coordinator.flow.mediator_agent.build_issue_result(
            resolution_status="human_decision",
            summary=decision_text or "此議題已送人工裁決，但暫未定案。",
            decision=decision_text,
            mediator_compromise={},
            agreed_points=[decision_text] if decision_text else [],
            unresolved_points=[] if decision_text else ["人類選擇暫不裁決。"],
            new_open_questions=[],
            affected_conflict_ids=[
                sid for sid in (issue.get("source_ids") or [])
                if isinstance(sid, str) and sid.startswith("CF-")
            ],
            change_record=(
                [
                    {
                        "id": f"RC-HQ-{round_num}-{idx}",
                        "requirement_id": next(
                            (sid for sid in (issue.get("source_ids") or []) if isinstance(sid, str) and sid.startswith(("REQ-", "FR-", "NFR-"))),
                            "",
                        ),
                        "change_type": "update",
                        "field": "text",
                        "before": None,
                        "after": decision_text,
                        "reason": "Derived from human decision queue result.",
                        "source_ids": list(issue.get("source_ids", [])),
                        "status": "pending_review",
                        "auto_apply": False,
                    }
                ]
                if decision_text and any(isinstance(sid, str) and sid.startswith(("REQ-", "FR-", "NFR-")) for sid in (issue.get("source_ids") or []))
                else []
            ),
            needs_human=True,
        )
        if decision_id:
            resolution["decision_id"] = decision_id
        resolution["human_decision_raw"] = resolution_raw
        runner.round_discussions.append(
            {"issue": {**issue, "status": "processed"}, "source_ids": issue.get("source_ids", []), "contributions": [], "resolution": resolution}
        )
        if decision_text:
            decisions = artifact.get("decisions", []) or []
            decisions.append(
                {
                    "id": decision_id,
                    "summary": decision_text,
                    "decision": decision_text,
                    "source_issue_id": issue.get("id"),
                    "resolved_conflict_ids": resolution.get("affected_conflict_ids", []),
                }
            )
            artifact["decisions"] = decisions
            from .conflict_review import mark_conflicts_resolved_by_ids
            mark_conflicts_resolved_by_ids(
                artifact, resolution.get("affected_conflict_ids", []), decision_id=decision_id,
            )
            row["status"] = "decided"
        else:
            row["status"] = "deferred"
        row["queue_processed_round"] = round_num
        record_queue_item_trace(
            artifact,
            queue_name="human_decision_queue",
            issue=issue,
            substep="human.finalize_item",
            observation={"decision_present": bool(decision_text)},
            decision={"action": "finalize_queue_item", "params": {"issue_id": issue.get("id")}, "reasoning": "將人類裁決結果寫回 artifact 與 queue 狀態。"},
            result={"status": row["status"], "decision_id": decision_id},
        )
        execution_log.append(
            {"round": round_num, "queue": "human_decision_queue", "issue_id": row.get("issue_id"), "status": row["status"]}
        )
    artifact["queue_execution_log"] = execution_log


def execute_direct_apply_queue(
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
    next_idx = len(artifact.get("change_record", []) or []) + 1
    for row in queue:
        if not isinstance(row, dict):
            continue
        record_queue_item_trace(
            artifact,
            queue_name="direct_apply_queue",
            issue=None,
            substep="direct_apply.observe_item",
            observation={"issue_id": row.get("issue_id")},
            decision={"action": "inspect_direct_apply_item", "params": {"source_ids": row.get("source_ids", [])}, "reasoning": "檢查 queue item 是否可形成 requirement change candidate。"},
            result={"source_ids": row.get("source_ids", [])},
        )
        req_ids = [
            sid for sid in (row.get("source_ids") or [])
            if isinstance(sid, str) and sid.startswith(("REQ-", "FR-", "NFR-"))
        ]
        if not req_ids:
            record_queue_item_trace(
                artifact,
                queue_name="direct_apply_queue",
                issue=None,
                substep="direct_apply.skip_no_requirement_id",
                observation={"issue_id": row.get("issue_id")},
                decision={"action": "skip", "params": {}, "reasoning": "缺少 requirement id，無法轉成 change candidate。"},
                result={"status": "skipped_no_requirement_id"},
            )
            row["status"] = "skipped_no_requirement_id"
            row["queue_processed_round"] = round_num
            execution_log.append(
                {"round": round_num, "queue": "direct_apply_queue", "issue_id": row.get("issue_id"), "status": row["status"]}
            )
            continue
        candidate_id = f"RC-QA-{next_idx}"
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
        record_queue_item_trace(
            artifact,
            queue_name="direct_apply_queue",
            issue=None,
            substep="direct_apply.queue_change_candidate",
            observation={"issue_id": row.get("issue_id"), "requirement_id": req_ids[0]},
            decision={"action": "queue_change_candidate", "params": {"requirement_id": req_ids[0]}, "reasoning": "將 direct-apply item 轉成待審 requirement change candidate。"},
            result={"candidate_id": candidate_id},
        )
        next_idx += 1
        row["status"] = "queued_change_candidate"
        row["queue_processed_round"] = round_num
        execution_log.append(
            {"round": round_num, "queue": "direct_apply_queue", "issue_id": row.get("issue_id"), "status": row["status"]}
        )
    from .conflict_review import append_change_record
    append_change_record(artifact, candidates)
    artifact["queue_execution_log"] = execution_log


# ---------- routed queues ----------

def run_routed_queues(
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
            nf, fm = partition_queue_skip_formal(q)
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
        execute_clarification_queue(coordinator, artifact, runner, round_num=round_num)
        execute_human_decision_queue(coordinator, artifact, runner, round_num=round_num)
        execute_direct_apply_queue(coordinator, artifact, round_num=round_num)
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


def post_issue_processing(
    coordinator: Any,
    artifact: Dict[str, Any],
    issue_discussion: Dict[str, Any],
    *,
    round_num: int,
) -> None:
    ingest_round_resolution_effects(
        coordinator, artifact, [issue_discussion], round_num=round_num,
    )
    coordinator.flow.store.save_artifact(artifact)
