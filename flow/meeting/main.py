# Meeting round lifecycle: pre-round checks, issue planning, post-round updates, and snapshots.
import json
from typing import Any, Dict, List, Optional

from utils import Collect
from agents.profile.mediator import ISSUE_CATEGORY_LABEL
from agents.profile.mediator.meeting_runner import MeetingRunner
from agents.profile.mediator.validation import issue_proposal as issue_proposal_schema
from agents.profile.analyst.requirements import (
    requirement_discussion_pool,
)
from agents.profile.analyst.conflict_store import (
    all_conflict_rows,
    set_conflict_entries,
)


def requirement_fields(requirements: List[Dict[str, Any]]) -> Dict[str, int]:
    stats = {
        "text_trimmed": 0,
        "source_stakeholders_normalized": 0,
    }
    for req in requirements or []:
        if not isinstance(req, dict):
            continue

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


def build_round_status_summary(
    artifact: Dict[str, Any],
    *,
    round_num: int,
    normalization_stats: Optional[Dict[str, int]] = None,
    final_meeting_stats: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    requirements = [r for r in requirement_discussion_pool(artifact) if isinstance(r, dict)]
    open_questions = [q for q in (artifact.get("open_questions", []) or []) if isinstance(q, dict)]
    conflicts = [c for c in all_conflict_rows(artifact) if isinstance(c, dict)]
    pending_decisions = [r for r in (artifact.get("pending_decisions", []) or []) if isinstance(r, dict)]
    incomplete_requirements = [
        r for r in requirements
        if not str(r.get("acceptance_criteria") or "").strip()
    ]

    summary = {
        "round": round_num,
        "total_requirements": len(requirements),
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
        "final_meeting": final_meeting_stats or {},
    }
    return summary


def save_meeting_preparation_outputs(
    coordinator: Any,
    artifact: Dict[str, Any],
    round_num: int,
) -> None:
    coordinator.flow.store.save_artifact(artifact)
    draft_version = round_num
    previous_draft = (
        coordinator.flow.store.load_draft(draft_version - 1)
        if draft_version > 0
        else None
    )
    draft_md = coordinator.flow.analyst_agent.run_requirements_analyst(
        "create_draft", artifact=artifact, draft_version=draft_version,
        round_num=round_num,
        previous_draft=previous_draft,
    )
    coordinator.flow.store.save_draft(draft_md, version=draft_version)
    coordinator.flow.logger.info(
        "會議準備輸出：artifact + draft_v%s", draft_version,
    )


# ---------- issue proposals ----------

def recent_issue_discussions(
    artifact: Dict[str, Any],
    *,
    rounds: int = 1,
) -> List[Dict[str, Any]]:
    discussions = artifact.get("discussions", []) or []
    recent_rounds = discussions[-max(1, rounds):]
    out: List[Dict[str, Any]] = []
    for rd in recent_rounds:
        out.extend(rd.get("issues", []) or [])
    return out


def issue_proposal(
    item: Dict[str, Any],
    *,
    proposed_by: str,
    round_num: int,
    index: int,
) -> Optional[Dict[str, Any]]:
    return issue_proposal_schema(
        item,
        allowed_categories=list(ISSUE_CATEGORY_LABEL.keys()),
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
            normalized = issue_proposal(
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
        if not hasattr(agent, "propose_issues"):
            continue
        try:
            rows = agent.propose_issues(artifact, round_num=round_num, max_items=default_cap)
            if isinstance(rows, list):
                for i, row in enumerate(rows, 1):
                    normalized = issue_proposal(
                        row, proposed_by=role, round_num=round_num, index=i,
                    )
                    if normalized:
                        proposals.append(normalized)
                    else:
                        invalid_count += 1
        except Exception as e:
            raise RuntimeError(f"{role} 提案階段失敗") from e
    coordinator.flow.logger.info("Issue Proposal：%s 筆有效，%s 筆淘汰", len(proposals), invalid_count)
    return proposals

# ---------- round discussion record ----------

def append_round_discussion_record(
    artifact: Dict[str, Any],
    *,
    round_num: int,
    round_discussions: List[Dict[str, Any]],
    issue_snapshot: List[Dict[str, Any]],
    queue_round_summary: Dict[str, Any],
) -> None:
    artifact.setdefault("discussions", []).append(
        {
            "round": round_num,
            "issues": round_discussions,
            "issue_snapshot": issue_snapshot or [],
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


def build_model_revision_context(
    artifact: Dict[str, Any],
    *,
    round_num: int,
    previous_models: List[Dict[str, Any]],
    change_candidates: List[Dict[str, Any]],
    round_discussions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    changed_requirement_ids = []
    change_candidate_ids = []
    for row in change_candidates or []:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("id") or "").strip()
        rid = str(row.get("requirement_id") or "").strip()
        if cid:
            change_candidate_ids.append(cid)
        if rid:
            changed_requirement_ids.append(rid)

    decision_ids = []
    for row in artifact.get("decisions", []) or []:
        if not isinstance(row, dict):
            continue
        try:
            decision_round = int(row.get("round") or -1)
        except (TypeError, ValueError):
            continue
        decision_id = str(row.get("id") or "").strip()
        if decision_round == int(round_num) and decision_id:
            decision_ids.append(decision_id)
    discussion_issue_ids = []
    for row in round_discussions or []:
        if not isinstance(row, dict):
            continue
        issue = row.get("issue") if isinstance(row.get("issue"), dict) else {}
        issue_id = str(issue.get("id") or "").strip()
        if issue_id:
            discussion_issue_ids.append(issue_id)

    previous_model_summary = [
        {
            "name": model.get("name"),
            "type": model.get("type"),
            "to_confirm": model.get("to_confirm", []),
            "maturity": model.get("maturity", ""),
        }
        for model in previous_models or []
        if isinstance(model, dict)
    ]
    return {
        "round_num": round_num,
        "mode": "revise_existing_models",
        "changed_requirement_ids": list(dict.fromkeys(changed_requirement_ids)),
        "change_candidate_ids": list(dict.fromkeys(change_candidate_ids)),
        "decision_ids": list(dict.fromkeys(decision_ids)),
        "discussion_issue_ids": list(dict.fromkeys(discussion_issue_ids)),
        "previous_model_summary": previous_model_summary,
    }


# ---------- apply mediator updates ----------

def apply_mediator_updates(
    artifact: Dict[str, Any],
    updates: Dict[str, Any],
) -> Dict[str, Any]:
    def dict_rows(value: Any) -> List[Dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [row for row in value if isinstance(row, dict)]

    current_conflicts = dict_rows(all_conflict_rows(artifact))
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
            candidate["id"] = f"CF-{next_conflict_num}"
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
        if orig.get("resolved_by_decision_id") and c.get("label") == "Neutral":
            c.setdefault("resolved_by_decision_id", orig["resolved_by_decision_id"])
    set_conflict_entries(artifact, new_conflicts)
    return {"new_decisions": new_decisions}


# ---------- post round pipeline ----------

def post_round_pipeline(
    coordinator: Any,
    artifact: Dict[str, Any],
    runner: MeetingRunner,
    *,
    round_num: int,
    finalize_requirements: bool = False,
) -> Dict[str, Any]:
    from .subflows import build_queue_round_summary
    from .conflict_review import (
        append_change_record,
        apply_change_record,
    )

    round_discussions = runner.get_round_discussions()
    all_open_questions = runner.get_all_open_questions()
    issue_snapshot = runner.get_issue_snapshot()
    queue_round_summary = build_queue_round_summary(artifact, round_num=round_num)
    append_round_discussion_record(
        artifact,
        round_num=round_num,
        round_discussions=round_discussions,
        issue_snapshot=issue_snapshot,
        queue_round_summary=queue_round_summary,
    )
    oq_pool = artifact.get("open_questions", [])
    seen = {
        (q.get("issue_id"), q.get("from_agent"), q.get("to_agent"), q.get("question"))
        for q in oq_pool
    }
    for oq in all_open_questions:
        oq["round"] = round_num
        k = (oq.get("issue_id"), oq.get("from_agent"), oq.get("to_agent"), oq.get("question"))
        if k in seen:
            continue
        oq_pool.append(oq)
        seen.add(k)
    artifact["open_questions"] = oq_pool
    coordinator.flow.store.save_artifact(artifact)

    updates = coordinator.flow.mediator_agent.update_decisions(artifact, round_discussions)
    apply_mediator_updates(artifact, updates)

    existing_decisions = artifact.get("decisions", []) or []
    existing_issue_ids = {
        str(d.get("source_issue_id") or "").strip()
        for d in existing_decisions if isinstance(d, dict)
    }
    for disc in round_discussions:
        if not isinstance(disc, dict):
            continue
        issue = disc.get("issue", {}) if isinstance(disc.get("issue"), dict) else {}
        resolution = disc.get("resolution", {}) if isinstance(disc.get("resolution"), dict) else {}
        tid = str(issue.get("id") or "").strip()
        if not tid or tid in existing_issue_ids:
            continue
        rstatus = str(resolution.get("resolution_status") or "").strip()
        if rstatus not in {"agreed", "human_decision"}:
            continue
        dec_text = str(resolution.get("decision") or resolution.get("summary") or "").strip()
        if not dec_text:
            continue
        dec_record = {
            "id": f"DEC-R{round_num}-{tid}",
            "summary": dec_text,
            "decision": dec_text,
            "source_issue_id": tid,
            "round": round_num,
            "resolved_conflict_ids": resolution.get("affected_conflict_ids", []),
            "affected_requirement_ids": resolution.get("affected_requirement_ids", []),
            "dod_complete": bool(dec_text and resolution.get("affected_requirement_ids")),
        }
        if not dec_record["affected_requirement_ids"]:
            coordinator.flow.logger.warning(
                "Traceability 警告：決策 %s 缺少 affected_requirement_ids，追溯鏈不完整", dec_record["id"],
            )
        existing_decisions.append(dec_record)
        existing_issue_ids.add(tid)
    artifact["decisions"] = existing_decisions

    previous_requirements_snapshot = stable_json(artifact.get("requirements", []) or [])
    previous_requirement_pool_snapshot = stable_json(requirement_discussion_pool(artifact))
    change_candidates = []
    if finalize_requirements:
        draft = coordinator.flow.analyst_agent.run_requirements_analyst(
            "finalize_requirements",
            artifact=artifact,
        )
        artifact["requirements"] = draft["requirements"]
        change_candidates = draft.get("change_record", [])
        if isinstance(change_candidates, list) and change_candidates:
            append_change_record(artifact, change_candidates)
        artifact = apply_change_record(coordinator, artifact)
    elif artifact.get("requirements"):
        draft = coordinator.flow.analyst_agent.run_requirements_analyst("update_draft", artifact=artifact)
        artifact["requirements"] = draft["requirements"]
        change_candidates = draft.get("change_record", [])
        if isinstance(change_candidates, list) and change_candidates:
            append_change_record(artifact, change_candidates)
        artifact = apply_change_record(coordinator, artifact)
    candidate_pool_changed = bool(artifact.pop("_candidate_pool_changed", False))
    requirements_changed = (
        previous_requirements_snapshot != stable_json(artifact.get("requirements", []) or [])
        or previous_requirement_pool_snapshot != stable_json(requirement_discussion_pool(artifact))
        or candidate_pool_changed
    )
    normalization_stats = requirement_fields(artifact.get("requirements", []) or [])
    final_meeting_stats = {}
    requirements_changed = (
        requirements_changed
        or previous_requirements_snapshot != stable_json(artifact.get("requirements", []) or [])
        or previous_requirement_pool_snapshot != stable_json(requirement_discussion_pool(artifact))
        or candidate_pool_changed
    )

    prev_models = artifact.get("system_models", {}).get("models", [])
    if prev_models and not requirements_changed and not change_candidates:
        model_data = artifact.get("system_models", {})
        coordinator.flow.logger.info("System model：需求無變更，本輪沿用既有模型")
    elif prev_models:
        revision_context = build_model_revision_context(
            artifact,
            round_num=round_num,
            previous_models=prev_models,
            change_candidates=change_candidates,
            round_discussions=round_discussions,
        )
        model_data = coordinator.flow.modeler_agent.generate_requirement_models(
            artifact,
            revision_context=revision_context,
        )
    else:
        model_data = coordinator.flow.modeler_agent.generate_requirement_models(
            artifact,
        )
    artifact["system_models"] = model_data
    draft_version = round_num
    previous_draft = (
        coordinator.flow.store.load_draft(draft_version - 1)
        if draft_version > 0
        else None
    )
    draft_md = coordinator.flow.analyst_agent.run_requirements_analyst(
        "create_draft", artifact=artifact, draft_version=draft_version,
        round_num=round_num,
        previous_draft=previous_draft,
    )
    coordinator.flow.store.save_draft(draft_md, version=draft_version)
    coordinator.flow.touch_artifact_meta(artifact, updated_by="flow.run_meeting_round", round_num=round_num)
    round_status = build_round_status_summary(
        artifact,
        round_num=round_num,
        normalization_stats=normalization_stats,
        final_meeting_stats=final_meeting_stats,
    )
    save_pending_decisions_report(coordinator, artifact)
    cap_meeting_trace(artifact)
    coordinator.flow.store.save_artifact(artifact)
    coordinator.flow.store.save_plantuml_files(model_data)
    coordinator.flow.logger.info(
        "Round %s status: requirements=%s incomplete_requirements=%s pending_decisions=%s unresolved_conflicts=%s open_questions=%s",
        round_num,
        round_status["total_requirements"],
        round_status["incomplete_requirement_count"],
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
    coordinator.run_round_pipeline_step(
        stage="save_meeting_preparation_outputs",
        round_num=round_num,
        artifact=artifact,
        action_fn=save_meeting_preparation_outputs,
        action_kwargs={
            "coordinator": coordinator,
            "artifact": artifact,
            "round_num": round_num,
        },
    )
    current_round_proposals = collect_issue_proposals(
        coordinator, artifact, round_num=round_num,
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

    runner = MeetingRunner(
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
        stage="meeting_loop",
        round_num=round_num,
        artifact=artifact,
        action_fn=coordinator.run_meeting_loop,
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
