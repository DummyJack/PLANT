from typing import Any, Dict, List, Optional

from utils import Collect, read_max_iterations
from utils import normalize_topic_proposal
from agents.profile.mediator import AGENDA_CATEGORY_LABEL
from .agenda_runner import AgendaRunner


# ---------- reviews / pre-round ----------

def _run_enabled_reviews(
    coordinator: Any,
    artifact: Dict[str, Any],
    *,
    recent_discussions: Optional[List[Dict[str, Any]]],
    roles: List[str],
) -> None:
    enabled = coordinator.flow.config.get("enable_agents") or {}
    role_to_agent = {
        "analyst": coordinator.flow.analyst_agent,
        "expert": coordinator.flow.expert_agent,
        "modeler": coordinator.flow.modeler_agent,
    }
    max_iter = read_max_iterations(coordinator.flow.config, default=3)
    for role in roles:
        if not enabled.get(role, True):
            continue
        agent = role_to_agent.get(role)
        if not agent:
            continue
        agent.run_review_loop(
            artifact, recent_discussions=recent_discussions, max_iterations=max_iter,
        )


def _run_pre_round_review(
    coordinator: Any,
    artifact: Dict[str, Any],
    *,
    recent_discussions: Optional[List[Dict[str, Any]]] = None,
    round_num: Optional[int] = None,
) -> Dict[str, Any]:
    coordinator.flow.logger.info("Pre-Round Review")
    if round_num is not None:
        artifact = coordinator.run_pre_meeting_conflict_review(artifact, round_num)
    from .meeting_subflows import _count_unanswered_open_questions
    should_run_role_review = bool(
        _recent_topic_discussions(artifact, rounds=1)
        or any(
            isinstance(c, dict) and (c.get("label") or "").strip() in {"Conflict", "Neutral"}
            for c in (artifact.get("conflicts", []) or [])
        )
        or _count_unanswered_open_questions(artifact) > 0
    )
    if should_run_role_review:
        _run_enabled_reviews(
            coordinator, artifact,
            recent_discussions=recent_discussions,
            roles=["analyst", "expert", "modeler"],
        )
    return artifact


def _save_pre_meeting_updates(
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


# ---------- topic proposals ----------

def _recent_topic_discussions(
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


def _normalize_topic_proposal(
    item: Dict[str, Any],
    *,
    proposed_by: str,
    round_num: int,
    index: int,
) -> Optional[Dict[str, Any]]:
    return normalize_topic_proposal(
        item,
        allowed_categories=list(AGENDA_CATEGORY_LABEL.keys()),
        default_participants=["analyst", "expert", "modeler", "user"],
        proposed_by=proposed_by,
        round_num=round_num,
        index=index,
    )


def _collect_topic_proposals(
    coordinator: Any,
    artifact: Dict[str, Any],
    *,
    round_num: int,
) -> List[Dict[str, Any]]:
    proposals: List[Dict[str, Any]] = []
    invalid_count = 0

    backlog = artifact.get("proposal_backlog", [])
    if isinstance(backlog, list):
        for i, row in enumerate(backlog, 1):
            normalized = _normalize_topic_proposal(
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
                    normalized = _normalize_topic_proposal(
                        row, proposed_by=role, round_num=round_num, index=i,
                    )
                    if normalized:
                        proposals.append(normalized)
                    else:
                        invalid_count += 1
        except Exception as e:
            coordinator.flow.logger.warning("%s 提案階段失敗，略過: %s", role, e)
    coordinator.flow.logger.info("Topic Proposal：%s 筆有效，%s 筆淘汰", len(proposals), invalid_count)
    return proposals


# ---------- round discussion record ----------

def _append_round_discussion_record(
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


# ---------- apply mediator updates ----------

def _apply_mediator_updates(
    artifact: Dict[str, Any],
    updates: Dict[str, Any],
) -> Dict[str, Any]:
    prev_conflicts_by_id = {
        c.get("id"): c for c in artifact.get("conflicts", []) if c.get("id")
    }
    new_decisions = updates.get("new_decisions", [])
    artifact.setdefault("decisions", []).extend(new_decisions)
    new_conflicts = list(updates.get("conflicts", artifact.get("conflicts", [])))
    extra_new_conflicts = updates.get("new_conflicts", []) or []
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

def _post_round_pipeline(
    coordinator: Any,
    artifact: Dict[str, Any],
    runner: AgendaRunner,
    *,
    round_num: int,
) -> Dict[str, Any]:
    from .meeting_subflows import _run_routed_queues, _build_queue_round_summary
    from .meeting_conflict_review import (
        _append_requirement_change_candidates,
        _process_approval_queue,
        apply_requirement_change_candidates,
    )

    if coordinator._is_last_meeting_round(artifact, round_num):
        _run_routed_queues(
            coordinator, artifact, runner,
            round_num=round_num, drain_non_formal=True,
        )
    round_discussions = runner.get_round_discussions()
    all_open_questions = runner.get_all_open_questions()
    agenda_snapshot = runner.get_agenda_snapshot()
    queue_round_summary = _build_queue_round_summary(artifact, round_num=round_num)
    _append_round_discussion_record(
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
    _apply_mediator_updates(artifact, updates)

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
                "RTM 警告：決策 %s 缺少 affected_requirement_ids，追溯鏈不完整", dec_record["id"],
            )
        existing_decisions.append(dec_record)
        existing_topic_ids.add(_tid)
    artifact["decisions"] = existing_decisions

    approval_summary = _process_approval_queue(coordinator, artifact, round_num=round_num)
    coordinator.flow.logger.info(
        "Approval Queue：approved=%s rejected=%s pending=%s",
        approval_summary["approved"], approval_summary["rejected"], approval_summary["pending"],
    )

    draft = coordinator.flow.analyst_agent.run_requirements_analyst("update_draft", artifact=artifact)
    artifact["requirements"] = draft["requirements"]
    change_candidates = draft.get("requirement_change_candidates", [])
    if isinstance(change_candidates, list) and change_candidates:
        _append_requirement_change_candidates(artifact, change_candidates)
    artifact = apply_requirement_change_candidates(coordinator, artifact)

    prev_models = artifact.get("system_models", {}).get("models", [])
    if prev_models:
        model_data = coordinator.flow.modeler_agent.refine_model(
            artifact["requirements"], prev_models,
            stakeholders=artifact.get("stakeholders", []),
        )
    else:
        model_data = coordinator.flow.modeler_agent.generate_system_model(
            artifact["requirements"], artifact["stakeholders"],
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
    coordinator.flow._touch_artifact_meta(artifact, updated_by="flow.run_meeting_round", round_num=round_num)
    coordinator.flow.store.save_artifact(artifact)
    coordinator.flow.store.save_plantuml_files(model_data)
    return artifact


# ---------- 主入口 ----------

def run_meeting_round_block(
    coordinator: Any,
    artifact: Dict[str, Any],
    round_num: int,
) -> Dict[str, Any]:
    artifact = coordinator.flow._ensure_artifact_contract(artifact)
    artifact = _run_pre_round_review(
        coordinator, artifact,
        recent_discussions=_recent_topic_discussions(artifact, rounds=1),
        round_num=round_num,
    )
    _save_pre_meeting_updates(coordinator, artifact, round_num)
    current_round_proposals = _collect_topic_proposals(
        coordinator, artifact, round_num=round_num,
    )
    existing_topic_proposals = artifact.get("topic_proposals", []) or []
    seen_proposal_ids = {
        row.get("proposal_id")
        for row in existing_topic_proposals
        if isinstance(row, dict) and row.get("proposal_id")
    }
    for row in current_round_proposals:
        if not isinstance(row, dict):
            continue
        proposal_id = row.get("proposal_id")
        if proposal_id and proposal_id in seen_proposal_ids:
            continue
        existing_topic_proposals.append(row)
        if proposal_id:
            seen_proposal_ids.add(proposal_id)
    artifact["topic_proposals"] = existing_topic_proposals
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
    coordinator._run_agenda_loop(runner)
    return _post_round_pipeline(
        coordinator, artifact, runner, round_num=round_num,
    )
