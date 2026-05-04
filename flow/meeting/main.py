# Meeting round lifecycle: pre-round checks, agenda, post-round updates, and snapshots.
import json
from typing import Any, Dict, List, Optional

from utils import Collect, read_max_iterations
from agents.profile.mediator import AGENDA_CATEGORY_LABEL
from agents.profile.mediator.agenda_runner import AgendaRunner
from agents.profile.mediator.validation import normalize_issue_proposal as normalize_issue_proposal_schema
from flow.requirements import (
    merge_requirement_candidates,
    normalize_requirement_status,
    normalize_requirement_statuses,
    review_requirement_candidates_before_merge,
    verify_requirements_for_final_round,
)


def normalize_requirement_fields(requirements: List[Dict[str, Any]]) -> Dict[str, int]:
    stats = {
        "status_normalized": 0,
        "text_trimmed": 0,
        "source_stakeholders_normalized": 0,
    }
    for req in requirements or []:
        if not isinstance(req, dict):
            continue

        raw_status = str(req.get("status") or "unverified").strip().lower()
        normalized_status = normalize_requirement_status(raw_status)
        if raw_status != normalized_status:
            req["status"] = normalized_status
            stats["status_normalized"] += 1
        elif req.get("status") != raw_status:
            req["status"] = raw_status

        text = str(req.get("text") or "")
        trimmed = text.strip()
        if trimmed != text:
            req["text"] = trimmed
            stats["text_trimmed"] += 1

        stakeholders = req.get("source_stakeholders")
        if stakeholders is None:
            req["source_stakeholders"] = []
        elif not isinstance(stakeholders, list):
            req["source_stakeholders"] = [str(stakeholders).strip()] if str(stakeholders).strip() else []
            stats["source_stakeholders_normalized"] += 1
    return stats


def requirement_status(req: Dict[str, Any]) -> str:
    return normalize_requirement_status(req.get("status"))


def build_round_status_summary(
    artifact: Dict[str, Any],
    *,
    round_num: int,
    normalization_stats: Optional[Dict[str, int]] = None,
    promotion_stats: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    requirements = [r for r in (artifact.get("requirements", []) or []) if isinstance(r, dict)]
    open_questions = [q for q in (artifact.get("open_questions", []) or []) if isinstance(q, dict)]
    conflicts = [c for c in (artifact.get("conflicts", []) or []) if isinstance(c, dict)]
    pending_decisions = [r for r in (artifact.get("pending_decisions", []) or []) if isinstance(r, dict)]
    incomplete_requirements = [
        r for r in requirements
        if not str(r.get("acceptance_criteria") or "").strip()
        or not str(r.get("verification_method") or "").strip()
    ]

    summary = {
        "round": round_num,
        "total_requirements": len(requirements),
        "verified_count": sum(1 for r in requirements if requirement_status(r) == "verified"),
        "unverified_count": sum(1 for r in requirements if requirement_status(r) == "unverified"),
        "unanswered_open_questions_count": sum(
            1 for q in open_questions if str(q.get("status") or "").strip() != "answered"
        ),
        "unresolved_conflict_count": sum(
            1 for c in conflicts if str(c.get("label") or "").strip() == "Conflict"
        ),
        "pending_decision_count": sum(
            1 for row in pending_decisions
            if str(row.get("status") or "").strip() in {"pending", "pending_confirmation"}
        ),
        "incomplete_requirement_count": len(incomplete_requirements),
        "normalization": normalization_stats or {},
        "verification": promotion_stats or {},
    }
    return summary


# ---------- reviews / pre-round ----------

def should_run_round_hidden_elicitation(
    artifact: Dict[str, Any],
    *,
    round_num: int,
) -> bool:
    if not artifact.get("elicitation_log") and not artifact.get("elicitation_candidates"):
        return True
    open_questions = [
        q for q in (artifact.get("open_questions", []) or [])
        if isinstance(q, dict) and str(q.get("status") or "").strip() != "answered"
    ]
    if open_questions:
        return True
    if round_num <= 1:
        return False
    return False


def run_round_hidden_elicitation(
    coordinator: Any,
    artifact: Dict[str, Any],
    *,
    round_num: int,
) -> Dict[str, Any]:
    if not should_run_round_hidden_elicitation(artifact, round_num=round_num):
        coordinator.flow.logger.info("隱性需求挖掘會議：本輪略過")
        return artifact
    coordinator.flow.logger.info("隱性需求挖掘會議：本輪執行")
    before_count = len(artifact.get("elicitation_candidates", []) or [])
    artifact = coordinator.run_hidden_requirement_elicitation_meeting(artifact, round_num)
    new_candidates = (artifact.get("elicitation_candidates", []) or [])[before_count:]
    if new_candidates:
        candidate_review = review_requirement_candidates_before_merge(
            artifact,
            new_candidates,
            stage="round_hidden_elicitation",
            round_num=round_num,
            candidate_source="elicitation",
        )
        stats = merge_requirement_candidates(
            artifact.setdefault("requirements", []),
            candidate_review["candidates"],
            source_round=round_num,
        )
        artifact.setdefault("elicitation_requirement_merges", []).append(
            {
                "round": round_num,
                **stats,
            }
        )
        coordinator.flow.logger.info(
            "隱性需求挖掘會議：併入 %s 筆 unverified requirements",
            stats["added"],
        )
    return artifact


def is_final_meeting_round(artifact: Dict[str, Any], round_num: int) -> bool:
    try:
        return int((artifact.get("meta") or {}).get("session_end_round") or 0) == int(round_num)
    except Exception:
        return False


def append_final_verification_proposal(
    proposals: List[Dict[str, Any]],
    *,
    round_num: int,
    artifact: Dict[str, Any],
) -> List[Dict[str, Any]]:
    if not is_final_meeting_round(artifact, round_num):
        return proposals
    req_ids = [
        str(req.get("id") or "").strip()
        for req in (artifact.get("requirements", []) or [])
        if isinstance(req, dict) and str(req.get("id") or "").strip()
    ]
    proposal = normalize_issue_proposal(
        {
            "issue_id": f"I-R{round_num:02d}-final-verification",
            "title": "最終需求驗證",
            "description": (
                "請逐項確認目前 requirements 的需求文字、verification_method 與 "
                "acceptance_criteria 是否足以作為正式 SRS 的驗證依據；若仍有衝突、"
                "缺漏或不可驗收之處，請明確指出。"
            ),
            "category": "open_question",
            "participants": ["analyst", "expert", "modeler", "user"],
            "discussion_mode": "sequential",
            "speaking_order": ["analyst", "expert", "modeler", "user"],
            "source_ids": req_ids,
            "priority_hint": "high",
            "impact_level": "high",
            "why_now": "這是最後一輪正式會議，必須完成需求驗證後才能產生正式 SRS。",
            "routing_preference": "formal_meeting",
            "requires_multi_party": True,
            "blocks_decision": True,
        },
        proposed_by="system",
        round_num=round_num,
        index=len(proposals) + 1,
    )
    if proposal:
        proposals.append(proposal)
    return proposals

def run_pre_round_review(
    coordinator: Any,
    artifact: Dict[str, Any],
    *,
    recent_discussions: Optional[List[Dict[str, Any]]] = None,
    round_num: Optional[int] = None,
) -> Dict[str, Any]:
    coordinator.flow.logger.info("Pre-Round Review / Conflict Recheck")
    has_conflict_pairs = any(
        isinstance(c, dict) and str(c.get("label") or "").strip() in {"Conflict", "Neutral"}
        for c in (artifact.get("conflicts", []) or [])
    )
    if round_num is not None and has_conflict_pairs:
        artifact = coordinator.run_pre_meeting_conflict_review(artifact, round_num)
    elif round_num is not None:
        coordinator.flow.logger.info("會前衝突再審查略過：沒有 Conflict/Neutral pair")
    return artifact


def save_pre_meeting_updates(
    coordinator: Any,
    artifact: Dict[str, Any],
    round_num: int,
) -> None:
    coordinator.flow.store.save_artifact(artifact)
    if artifact.get("conflicts"):
        conflict_md = coordinator.flow.analyst_agent.generate_conflict_report(
            artifact, round_num=round_num,
            recent_decisions_limit=coordinator.flow.config.get("agenda_items", 5),
        )
        coordinator.flow.store.save_markdown(conflict_md, "conflict_report.md")
    draft_version = round_num
    draft_md = coordinator.flow.analyst_agent.run_requirements_analyst(
        "create_draft", artifact=artifact, draft_version=draft_version,
        round_num=round_num,
        recent_decisions_limit=coordinator.flow.config.get("agenda_items", 5),
    )
    coordinator.flow.store.save_draft(draft_md, version=draft_version)
    coordinator.flow.logger.info(
        "會前審查更新：artifact + conflict_report + draft_v%s", draft_version,
    )


# ---------- issue proposals ----------

def recent_topic_discussions(
    artifact: Dict[str, Any],
    *,
    rounds: int = 1,
) -> List[Dict[str, Any]]:
    discussions = artifact.get("discussions", []) or []
    recent_rounds = discussions[-max(1, rounds):]
    out: List[Dict[str, Any]] = []
    for rd in recent_rounds:
        out.extend(rd.get("topics", []) or [])
    return out


def normalize_issue_proposal(
    item: Dict[str, Any],
    *,
    proposed_by: str,
    round_num: int,
    index: int,
) -> Optional[Dict[str, Any]]:
    return normalize_issue_proposal_schema(
        item,
        allowed_categories=list(AGENDA_CATEGORY_LABEL.keys()),
        default_participants=["analyst", "expert", "modeler", "user"],
        proposed_by=proposed_by,
        round_num=round_num,
        index=index,
    )


def collect_issue_proposals(
    coordinator: Any,
    artifact: Dict[str, Any],
    *,
    round_num: int,
) -> List[Dict[str, Any]]:
    proposals: List[Dict[str, Any]] = []
    invalid_count = 0

    backlog = artifact.get("issue_backlog", [])
    if isinstance(backlog, list):
        for i, row in enumerate(backlog, 1):
            if not isinstance(row, dict):
                invalid_count += 1
                continue
            normalized = normalize_issue_proposal(
                row, proposed_by=(row.get("proposed_by") or "backlog"),
                round_num=round_num, index=i,
            )
            if normalized:
                proposals.append(normalized)
            else:
                invalid_count += 1

    enabled = coordinator.flow.config.get("enable_agents") or {}
    proposal_specs = [
        ("analyst", coordinator.flow.analyst_agent, 4),
        ("expert", coordinator.flow.expert_agent, 3),
        ("modeler", coordinator.flow.modeler_agent, 3),
        ("user", coordinator.flow.user_agent, 2),
    ]
    for role, agent, default_cap in proposal_specs:
        if not enabled.get(role, True):
            continue
        if not hasattr(agent, "propose_topics"):
            continue
        try:
            rows = agent.propose_topics(artifact, round_num=round_num, max_items=default_cap)
            if isinstance(rows, list):
                for i, row in enumerate(rows, 1):
                    normalized = normalize_issue_proposal(
                        row, proposed_by=role, round_num=round_num, index=i,
                    )
                    if normalized:
                        proposals.append(normalized)
                    else:
                        invalid_count += 1
        except Exception as e:
            coordinator.flow.logger.warning("%s 提案階段失敗，略過: %s", role, e)
    coordinator.flow.logger.info("Issue Proposal：%s 筆有效，%s 筆淘汰", len(proposals), invalid_count)
    return proposals

# ---------- round discussion record ----------

def append_round_discussion_record(
    artifact: Dict[str, Any],
    *,
    round_num: int,
    round_discussions: List[Dict[str, Any]],
    agenda_snapshot: List[Dict[str, Any]],
    queue_round_summary: Dict[str, Any],
) -> None:
    artifact.setdefault("discussions", []).append(
        {
            "round": round_num,
            "topics": round_discussions,
            "agenda_snapshot": agenda_snapshot or [],
            "queue_summary": queue_round_summary,
        }
    )


def save_pending_decisions_report(
    coordinator: Any,
    artifact: Dict[str, Any],
) -> None:
    pending_decisions = [
        row for row in (artifact.get("pending_decisions", []) or [])
        if isinstance(row, dict) and str(row.get("status") or "").strip() == "pending_confirmation"
    ]
    if pending_decisions:
        lines = ["# Pending Decisions\n\n"]
        for row in pending_decisions:
            lines.append(f"## {row.get('decision_id', '')} {row.get('title', '')}\n\n")
            if row.get("summary"):
                lines.append(f"{row.get('summary')}\n\n")
            recommendation = row.get("recommendation") or {}
            if isinstance(recommendation, dict) and recommendation:
                lines.append("### Recommendation\n\n")
                lines.append(f"- Option: {recommendation.get('option_id', '')}\n")
                if recommendation.get("confidence"):
                    lines.append(f"- Confidence: {recommendation.get('confidence')}\n")
                if recommendation.get("rationale"):
                    lines.append(f"- Rationale: {recommendation.get('rationale')}\n")
                lines.append("\n")
            options = row.get("options") or []
            if options:
                lines.append("### Options\n\n")
                for option in options:
                    if not isinstance(option, dict):
                        continue
                    lines.append(f"- {option.get('id', '')}: {option.get('summary', '')}\n")
                lines.append("\n")
            unresolved = [str(x).strip() for x in (row.get("unresolved_points") or []) if str(x).strip()]
            if unresolved:
                lines.append("### Needs Confirmation\n\n")
                for item in unresolved:
                    lines.append(f"- {item}\n")
                lines.append("\n")
        artifact["pending_decisions_report"] = "".join(lines).strip() + "\n"


def cap_meeting_trace(
    artifact: Dict[str, Any],
    *,
    max_items: int = 200,
) -> None:
    rows = artifact.get("meeting_opa_trace")
    if not isinstance(rows, list) or len(rows) <= max_items:
        return
    artifact["meeting_opa_trace"] = rows[-max_items:]
    meta = artifact.setdefault("meta", {})
    meta["meeting_opa_trace_capped"] = True
    meta["meeting_opa_trace_retained"] = max_items


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


# ---------- apply mediator updates ----------

def apply_mediator_updates(
    artifact: Dict[str, Any],
    updates: Dict[str, Any],
) -> Dict[str, Any]:
    def dict_rows(value: Any) -> List[Dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [row for row in value if isinstance(row, dict)]

    current_conflicts = dict_rows(artifact.get("conflicts", []))
    new_decisions = dict_rows(updates.get("new_decisions", []))
    prev_conflicts_by_id = {
        c.get("id"): c for c in current_conflicts if c.get("id")
    }
    artifact.setdefault("decisions", []).extend(new_decisions)
    candidate_conflicts = updates.get("conflicts", current_conflicts)
    new_conflicts = dict_rows(candidate_conflicts) or current_conflicts
    extra_new_conflicts = dict_rows(updates.get("new_conflicts", []))
    next_conflict_num = len(
        [c for c in new_conflicts if isinstance(c, dict) and str(c.get("id") or "").startswith("CF-")]
    ) + 1
    for row in extra_new_conflicts:
        if not isinstance(row, dict):
            continue
        candidate = dict(row)
        if not str(candidate.get("id") or "").strip():
            candidate["id"] = f"CF-{next_conflict_num:02d}"
            next_conflict_num += 1
        new_conflicts.append(candidate)
    cf_to_decision = {}
    for d in new_decisions:
        did = d.get("id")
        for cf_id in d.get("resolved_conflict_ids", []):
            if cf_id:
                cf_to_decision[cf_id] = did
    for c in new_conflicts:
        if not isinstance(c, dict):
            continue
        if c.get("label") == "Neutral" and c.get("id"):
            c.setdefault("resolved_by_decision_id", cf_to_decision.get(c["id"]))
        orig = prev_conflicts_by_id.get(c.get("id"))
        if not orig:
            continue
        if orig.get("requirement_ids") is not None:
            c.setdefault("requirement_ids", orig["requirement_ids"])
        if orig.get("conflict_type") and c.get("label") == "Conflict":
            c.setdefault("conflict_type", orig["conflict_type"])
        if orig.get("resolved_by_decision_id") and c.get("label") == "Neutral":
            c.setdefault("resolved_by_decision_id", orig["resolved_by_decision_id"])
    artifact["conflicts"] = new_conflicts
    return {"new_decisions": new_decisions}


# ---------- post round pipeline ----------

def post_round_pipeline(
    coordinator: Any,
    artifact: Dict[str, Any],
    runner: AgendaRunner,
    *,
    round_num: int,
) -> Dict[str, Any]:
    from .subflows import run_routed_queues, build_queue_round_summary
    from .conflict_review import (
        append_requirement_change_candidates,
        apply_requirement_change_candidates,
    )

    if coordinator.is_last_meeting_round(artifact, round_num):
        run_routed_queues(
            coordinator, artifact, runner,
            round_num=round_num, drain_non_formal=True,
        )
    round_discussions = runner.get_round_discussions()
    all_open_questions = runner.get_all_open_questions()
    agenda_snapshot = runner.get_agenda_snapshot()
    queue_round_summary = build_queue_round_summary(artifact, round_num=round_num)
    append_round_discussion_record(
        artifact,
        round_num=round_num,
        round_discussions=round_discussions,
        agenda_snapshot=agenda_snapshot,
        queue_round_summary=queue_round_summary,
    )
    oq_pool = artifact.get("open_questions", [])
    seen = {
        (q.get("topic_id"), q.get("from_agent"), q.get("to_agent"), q.get("question"))
        for q in oq_pool
    }
    for oq in all_open_questions:
        oq["round"] = round_num
        k = (oq.get("topic_id"), oq.get("from_agent"), oq.get("to_agent"), oq.get("question"))
        if k in seen:
            continue
        oq_pool.append(oq)
        seen.add(k)
    artifact["open_questions"] = oq_pool
    coordinator.flow.store.save_artifact(artifact)

    updates = coordinator.flow.mediator_agent.update_decisions(artifact, round_discussions)
    apply_mediator_updates(artifact, updates)

    existing_decisions = artifact.get("decisions", []) or []
    existing_topic_ids = {
        str(d.get("source_topic_id") or "").strip()
        for d in existing_decisions if isinstance(d, dict)
    }
    for disc in round_discussions:
        if not isinstance(disc, dict):
            continue
        _topic = disc.get("topic", {}) if isinstance(disc.get("topic"), dict) else {}
        _resolution = disc.get("resolution", {}) if isinstance(disc.get("resolution"), dict) else {}
        _tid = str(_topic.get("id") or "").strip()
        if not _tid or _tid in existing_topic_ids:
            continue
        _rstatus = str(_resolution.get("resolution_status") or "").strip()
        if _rstatus not in {"agreed", "human_decision"}:
            continue
        _dec_text = str(_resolution.get("decision") or _resolution.get("summary") or "").strip()
        if not _dec_text:
            continue
        dec_record = {
            "id": f"DEC-R{round_num}-{_tid}",
            "summary": _dec_text,
            "decision": _dec_text,
            "source_topic_id": _tid,
            "round": round_num,
            "resolved_conflict_ids": _resolution.get("affected_conflict_ids", []),
            "affected_requirement_ids": _resolution.get("affected_requirement_ids", []),
            "dod_complete": bool(_dec_text and _resolution.get("affected_requirement_ids")),
        }
        if not dec_record["affected_requirement_ids"]:
            coordinator.flow.logger.warning(
                "Traceability 警告：決策 %s 缺少 affected_requirement_ids，追溯鏈不完整", dec_record["id"],
            )
        existing_decisions.append(dec_record)
        existing_topic_ids.add(_tid)
    artifact["decisions"] = existing_decisions

    previous_requirements_snapshot = stable_json(artifact.get("requirements", []) or [])
    draft = coordinator.flow.analyst_agent.run_requirements_analyst("update_draft", artifact=artifact)
    artifact["requirements"] = draft["requirements"]
    change_candidates = draft.get("requirement_change_candidates", [])
    if isinstance(change_candidates, list) and change_candidates:
        append_requirement_change_candidates(artifact, change_candidates)
    artifact = apply_requirement_change_candidates(coordinator, artifact)
    requirements_changed = previous_requirements_snapshot != stable_json(artifact.get("requirements", []) or [])
    normalization_stats = normalize_requirement_fields(artifact.get("requirements", []) or [])
    verification_stats = {}
    if is_final_meeting_round(artifact, round_num):
        verification_stats = verify_requirements_for_final_round(artifact, round_num=round_num)
        coordinator.flow.logger.info(
            "需求驗證：verified=%s unverified=%s",
            verification_stats.get("verified_count", 0),
            verification_stats.get("unverified_count", 0),
        )
    requirements_changed = requirements_changed or previous_requirements_snapshot != stable_json(artifact.get("requirements", []) or [])

    prev_models = artifact.get("system_models", {}).get("models", [])
    if prev_models and not requirements_changed and not change_candidates:
        model_data = artifact.get("system_models", {})
        coordinator.flow.logger.info("System model：需求無變更，本輪沿用既有模型")
    elif prev_models:
        model_data = coordinator.flow.modeler_agent.generate_requirement_models(
            artifact,
            max_iterations=read_max_iterations(coordinator.flow.config, default=3),
        )
    else:
        model_data = coordinator.flow.modeler_agent.generate_requirement_models(
            artifact,
            max_iterations=read_max_iterations(coordinator.flow.config, default=3),
        )
    artifact["system_models"] = model_data
    draft_version = round_num
    draft_md = coordinator.flow.analyst_agent.run_requirements_analyst(
        "create_draft", artifact=artifact, draft_version=draft_version,
        round_num=round_num,
        recent_decisions_limit=coordinator.flow.config.get("agenda_items", 5),
    )
    coordinator.flow.store.save_draft(draft_md, version=draft_version)
    coordinator.flow.touch_artifact_meta(artifact, updated_by="flow.run_meeting_round", round_num=round_num)
    round_status = build_round_status_summary(
        artifact,
        round_num=round_num,
        normalization_stats=normalization_stats,
        promotion_stats=verification_stats,
    )
    save_pending_decisions_report(coordinator, artifact)
    cap_meeting_trace(artifact)
    coordinator.flow.store.save_artifact(artifact)
    coordinator.flow.store.save_plantuml_files(model_data)
    coordinator.flow.logger.info(
        "Round %s status: verified=%s unverified=%s pending_decisions=%s unresolved_conflicts=%s open_questions=%s",
        round_num,
        round_status["verified_count"],
        round_status["unverified_count"],
        round_status["pending_decision_count"],
        round_status["unresolved_conflict_count"],
        round_status["unanswered_open_questions_count"],
    )
    return artifact


# ---------- 主入口 ----------

def run_meeting_round_block(
    coordinator: Any,
    artifact: Dict[str, Any],
    round_num: int,
) -> Dict[str, Any]:
    artifact = coordinator.flow.ensure_artifact_contract(artifact)
    artifact = coordinator.run_round_pipeline_step(
        stage="hidden_elicitation",
        round_num=round_num,
        artifact=artifact,
        action_fn=run_round_hidden_elicitation,
        action_kwargs={
            "coordinator": coordinator,
            "artifact": artifact,
            "round_num": round_num,
        },
    )
    artifact = coordinator.run_round_pipeline_step(
        stage="pre_round_review",
        round_num=round_num,
        artifact=artifact,
        action_fn=run_pre_round_review,
        action_kwargs={
            "coordinator": coordinator,
            "artifact": artifact,
            "recent_discussions": recent_topic_discussions(artifact, rounds=1),
            "round_num": round_num,
        },
    )
    coordinator.run_round_pipeline_step(
        stage="save_pre_meeting_updates",
        round_num=round_num,
        artifact=artifact,
        action_fn=save_pre_meeting_updates,
        action_kwargs={
            "coordinator": coordinator,
            "artifact": artifact,
            "round_num": round_num,
        },
    )
    current_round_proposals = collect_issue_proposals(
        coordinator, artifact, round_num=round_num,
    )
    current_round_proposals = append_final_verification_proposal(
        current_round_proposals,
        round_num=round_num,
        artifact=artifact,
    )
    existing_issue_proposals = artifact.get("issue_proposals", []) or []
    seen_issue_ids = {
        row.get("issue_id")
        for row in existing_issue_proposals
        if isinstance(row, dict) and row.get("issue_id")
    }
    for row in current_round_proposals:
        if not isinstance(row, dict):
            continue
        issue_id = row.get("issue_id")
        if issue_id and issue_id in seen_issue_ids:
            continue
        existing_issue_proposals.append(row)
        if issue_id:
            seen_issue_ids.add(issue_id)
    artifact["issue_proposals"] = existing_issue_proposals
    coordinator.flow.store.save_artifact(artifact)

    runner = AgendaRunner(
        coordinator.flow.mediator_agent,
        coordinator.flow.registry,
        artifact,
        current_round_proposals,
        round_num,
        coordinator.flow.config,
        coordinator.flow.store,
        Collect,
        coordinator.flow.logger,
    )
    coordinator.run_round_pipeline_step(
        stage="agenda_loop",
        round_num=round_num,
        artifact=artifact,
        action_fn=coordinator.run_agenda_loop,
        action_kwargs={"runner": runner},
    )
    return coordinator.run_round_pipeline_step(
        stage="post_round_pipeline",
        round_num=round_num,
        artifact=artifact,
        action_fn=post_round_pipeline,
        action_kwargs={
            "coordinator": coordinator,
            "artifact": artifact,
            "runner": runner,
            "round_num": round_num,
        },
    )
