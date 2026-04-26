import re
from typing import Any, Dict, List, Optional

from utils import Collect, read_max_iterations
from agents.agenda.schema import normalize_topic_proposal
from agents.profile.mediator import AGENDA_CATEGORY_LABEL
from .agenda_runner import AgendaRunner


_MEASURABLE_PATTERN = re.compile(
    r"(<=|>=|<|>|=|≦|≧|\d+\s*(ms|s|sec|seconds|分鐘|小時|%|percent|筆|次|items|users|人))",
    re.IGNORECASE,
)
_HIGH_RISK_FORMALIZATION_PATTERNS = [
    r"\btls\b",
    r"\baes\b",
    r"\boauth\b",
    r"\bpci\b",
    r"\bgdpr\b",
    r"\biso\b",
    r"\bwcag\b",
    r"\bapi\b",
    r"\bexternal\b",
    r"\bdashboard\b",
    r"\banalytics\b",
    r"\bpayment\s*gateway\b",
    r"第三方",
    r"多分店",
    r"跨店",
    r"法規",
    r"合規",
    r"compliance",
    r"加密",
    r"稽核",
    r"權限控管",
    r"解析度",
    r"螢幕尺寸",
    r"android\s*\d",
    r"iphone\s*\d",
    r"ipad",
]


def _has_source_backing(req: Dict[str, Any]) -> bool:
    return bool(str(req.get("source") or "").strip()) or bool(req.get("source_stakeholders"))


def _is_high_risk_requirement(req: Dict[str, Any]) -> bool:
    haystacks = [
        str(req.get("text") or ""),
        str(req.get("acceptance_criteria") or ""),
        str(req.get("rationale") or ""),
    ]
    joined = " \n ".join(haystacks)
    lower = joined.lower()
    if _MEASURABLE_PATTERN.search(joined):
        return True
    return any(re.search(pattern, lower, re.IGNORECASE) for pattern in _HIGH_RISK_FORMALIZATION_PATTERNS)


def _can_auto_formalize_requirement(req: Dict[str, Any]) -> bool:
    if not _is_high_risk_requirement(req):
        return True
    return _has_source_backing(req)


def _guess_verification_method(req: Dict[str, Any]) -> str:
    text = str(req.get("text") or "").strip().lower()
    rtype = str(req.get("type") or req.get("requirement_type") or "").strip().upper()
    if rtype.startswith("NFR"):
        if any(token in text for token in ("延遲", "latency", "回應時間", "throughput", "availability", "uptime", "%")):
            return "test"
        return "review"
    if any(token in text for token in ("顯示", "建立", "送出", "新增", "刪除", "更新", "登入", "付款", "呼叫", "accept", "reject")):
        return "test"
    if any(token in text for token in ("應支援", "應提供", "應允許", "shall")):
        return "test"
    return "inspection"


def _guess_acceptance_criteria(req: Dict[str, Any], verification_method: str) -> str:
    text = str(req.get("text") or "").strip()
    if not text:
        return ""
    compact = " ".join(text.split())
    lower = compact.lower()
    if _MEASURABLE_PATTERN.search(compact):
        return f"Given the specified condition, when the requirement is exercised, then the system satisfies: {compact}"
    if any(token in lower for token in ("應能", "可以", "可", "allow", "able to", "shall")):
        return (
            "Given the relevant precondition is met, "
            f"when the user or system attempts the behavior described in '{compact}', "
            "then the expected result is completed successfully without error."
        )
    if verification_method == "review":
        return f"The requirement is satisfied when project evidence shows that '{compact}' is explicitly addressed."
    if verification_method == "inspection":
        return f"The requirement is satisfied when inspection confirms that '{compact}' is present and correctly specified."
    return (
        "Given the relevant precondition is met, "
        f"when the behavior described in '{compact}' is tested, "
        "then the expected result is observed."
    )


def _normalize_requirement_fields(requirements: List[Dict[str, Any]]) -> Dict[str, int]:
    valid_statuses = {"draft", "approved", "baselined", "rejected"}
    stats = {
        "status_normalized": 0,
        "verification_method_filled": 0,
        "acceptance_criteria_filled": 0,
        "text_trimmed": 0,
        "source_stakeholders_normalized": 0,
    }
    for req in requirements or []:
        if not isinstance(req, dict):
            continue

        raw_status = str(req.get("status") or "draft").strip().lower()
        if raw_status not in valid_statuses:
            req["status"] = "draft"
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

        if not str(req.get("verification_method") or "").strip():
            req["verification_method"] = _guess_verification_method(req)
            stats["verification_method_filled"] += 1

        if not str(req.get("acceptance_criteria") or "").strip():
            verification_method = str(req.get("verification_method") or "inspection").strip() or "inspection"
            req["acceptance_criteria"] = _guess_acceptance_criteria(req, verification_method)
            stats["acceptance_criteria_filled"] += 1
    return stats


def _requirement_status(req: Dict[str, Any]) -> str:
    status = str(req.get("status") or "draft").strip().lower()
    return status if status in {"draft", "approved", "baselined", "rejected"} else "draft"


def _promote_mature_requirements(
    artifact: Dict[str, Any],
    *,
    round_num: int,
) -> Dict[str, int]:
    requirements = [
        r for r in (artifact.get("requirements", []) or [])
        if isinstance(r, dict)
    ]
    unresolved_conflict_req_ids = set()
    for conflict in (artifact.get("conflicts", []) or []):
        if not isinstance(conflict, dict):
            continue
        if str(conflict.get("label") or "").strip() != "Conflict":
            continue
        for rid in (conflict.get("requirement_ids") or []):
            rid_s = str(rid).strip()
            if rid_s:
                unresolved_conflict_req_ids.add(rid_s)

    pending_approval_req_ids = set()
    for row in (artifact.get("approval_queue", []) or []):
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "").strip() != "pending":
            continue
        for rid in (row.get("affected_requirement_ids") or []):
            rid_s = str(rid).strip()
            if rid_s:
                pending_approval_req_ids.add(rid_s)

    pending_candidate_req_ids = set()
    for row in (artifact.get("requirement_change_candidates", []) or []):
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "").strip() != "pending_review":
            continue
        rid_s = str(row.get("requirement_id") or "").strip()
        if rid_s:
            pending_candidate_req_ids.add(rid_s)

    promoted = 0
    skipped_conflict = 0
    skipped_pending = 0
    skipped_high_risk = 0
    for req in requirements:
        rid = str(req.get("id") or "").strip()
        if not rid or _requirement_status(req) != "draft":
            continue
        if rid in unresolved_conflict_req_ids:
            skipped_conflict += 1
            continue
        if rid in pending_approval_req_ids or rid in pending_candidate_req_ids:
            skipped_pending += 1
            continue
        text = str(req.get("text") or "").strip()
        verification_method = str(req.get("verification_method") or "").strip()
        acceptance_criteria = str(req.get("acceptance_criteria") or "").strip()
        stakeholders = req.get("source_stakeholders")
        if not text or not verification_method or not acceptance_criteria:
            continue
        if stakeholders is not None and not isinstance(stakeholders, list):
            continue
        if not _can_auto_formalize_requirement(req):
            skipped_high_risk += 1
            req.setdefault("status_reason", "requires_explicit_source_or_approval_for_high_risk_formalization")
            continue
        req["status"] = "approved"
        req["status_updated_round"] = round_num
        req["status_reason"] = "auto_promoted_mature_requirement"
        promoted += 1

    return {
        "promoted": promoted,
        "skipped_conflict": skipped_conflict,
        "skipped_pending": skipped_pending,
        "skipped_high_risk": skipped_high_risk,
    }


def build_init_candidate_absorption_report(artifact: Dict[str, Any]) -> Dict[str, Any]:
    candidates = [
        row for row in (artifact.get("requirement_change_candidates", []) or [])
        if isinstance(row, dict)
        and (
            str(row.get("source_topic_id") or "").strip() == "ELICIT-INIT"
            or "ELICIT-INIT" in {str(s).strip() for s in (row.get("source_ids") or []) if str(s).strip()}
        )
    ]
    status_counts: Dict[str, int] = {}
    requirement_ids: List[str] = []
    for row in candidates:
        status = str(row.get("status") or "unknown").strip() or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
        rid = str(row.get("requirement_id") or "").strip()
        if rid:
            requirement_ids.append(rid)

    requirement_ids = sorted(set(requirement_ids))
    requirement_statuses: Dict[str, str] = {}
    req_by_id = {
        str(req.get("id") or "").strip(): req
        for req in (artifact.get("requirements", []) or [])
        if isinstance(req, dict) and str(req.get("id") or "").strip()
    }
    for rid in requirement_ids:
        if rid in req_by_id:
            requirement_statuses[rid] = _requirement_status(req_by_id[rid])

    return {
        "candidate_count": len(candidates),
        "status_counts": status_counts,
        "requirement_ids": requirement_ids,
        "requirement_statuses": requirement_statuses,
        "absorbed_count": sum(1 for s in requirement_statuses.values() if s in {"approved", "baselined"}),
    }


def _build_round_convergence_summary(
    artifact: Dict[str, Any],
    *,
    round_num: int,
    normalization_stats: Optional[Dict[str, int]] = None,
    promotion_stats: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    requirements = [r for r in (artifact.get("requirements", []) or []) if isinstance(r, dict)]
    open_questions = [q for q in (artifact.get("open_questions", []) or []) if isinstance(q, dict)]
    conflicts = [c for c in (artifact.get("conflicts", []) or []) if isinstance(c, dict)]
    approval_queue = [r for r in (artifact.get("approval_queue", []) or []) if isinstance(r, dict)]

    def _status(req: Dict[str, Any]) -> str:
        status = str(req.get("status") or "draft").strip().lower()
        return status if status in {"draft", "approved", "baselined", "rejected"} else "draft"

    summary = {
        "round": round_num,
        "total_requirements": len(requirements),
        "approved_or_baselined_count": sum(1 for r in requirements if _status(r) in {"approved", "baselined"}),
        "draft_count": sum(1 for r in requirements if _status(r) == "draft"),
        "rejected_count": sum(1 for r in requirements if _status(r) == "rejected"),
        "unanswered_open_questions_count": sum(
            1 for q in open_questions if str(q.get("status") or "").strip() != "answered"
        ),
        "unresolved_conflict_count": sum(
            1 for c in conflicts if str(c.get("label") or "").strip() == "Conflict"
        ),
        "pending_approval_count": sum(
            1 for row in approval_queue if str(row.get("status") or "").strip() == "pending"
        ),
        "missing_verification_method_count": sum(
            1 for r in requirements if not str(r.get("verification_method") or "").strip()
        ),
        "missing_acceptance_criteria_count": sum(
            1 for r in requirements if not str(r.get("acceptance_criteria") or "").strip()
        ),
        "normalization": normalization_stats or {},
        "promotion": promotion_stats or {},
        "init_candidate_absorption": build_init_candidate_absorption_report(artifact),
    }
    artifact.setdefault("round_convergence", []).append(summary)
    return summary


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
    coordinator.flow.logger.info("Pre-Round Review / Conflict Recheck")
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


def _save_round_snapshots(
    coordinator: Any,
    artifact: Dict[str, Any],
    *,
    round_num: int,
) -> None:
    store = coordinator.flow.store
    artifact_dir = store.artifact_dir
    latest_convergence = {}
    if isinstance(artifact.get("round_convergence"), list) and artifact["round_convergence"]:
        latest_convergence = artifact["round_convergence"][-1] or {}

    snapshots = {
        f"round_convergence_r{round_num}.json": latest_convergence if isinstance(latest_convergence, dict) else {},
        f"approval_queue_r{round_num}.json": {
            "round": round_num,
            "items": [row for row in (artifact.get("approval_queue", []) or []) if isinstance(row, dict)],
        },
        f"requirement_change_candidates_r{round_num}.json": {
            "round": round_num,
            "items": [row for row in (artifact.get("requirement_change_candidates", []) or []) if isinstance(row, dict)],
        },
        f"init_candidate_absorption_r{round_num}.json": {
            "round": round_num,
            "report": build_init_candidate_absorption_report(artifact),
        },
        f"open_questions_r{round_num}.json": {
            "round": round_num,
            "items": [row for row in (artifact.get("open_questions", []) or []) if isinstance(row, dict)],
        },
    }
    for filename, payload in snapshots.items():
        store.save_json(payload, artifact_dir / filename)


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
    normalization_stats = _normalize_requirement_fields(artifact.get("requirements", []) or [])
    promotion_stats = _promote_mature_requirements(artifact, round_num=round_num)

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
    convergence = _build_round_convergence_summary(
        artifact,
        round_num=round_num,
        normalization_stats=normalization_stats,
        promotion_stats=promotion_stats,
    )
    coordinator.flow.store.save_artifact(artifact)
    _save_round_snapshots(coordinator, artifact, round_num=round_num)
    coordinator.flow.store.save_plantuml_files(model_data)
    coordinator.flow.logger.info(
        "Round %s convergence: approved/baselined=%s pending_approval=%s unresolved_conflicts=%s missing_vm=%s missing_ac=%s promoted=%s",
        round_num,
        convergence["approved_or_baselined_count"],
        convergence["pending_approval_count"],
        convergence["unresolved_conflict_count"],
        convergence["missing_verification_method_count"],
        convergence["missing_acceptance_criteria_count"],
        promotion_stats["promoted"],
    )
    return artifact


# ---------- 主入口 ----------

def run_meeting_round_block(
    coordinator: Any,
    artifact: Dict[str, Any],
    round_num: int,
) -> Dict[str, Any]:
    artifact = coordinator.flow._ensure_artifact_contract(artifact)
    artifact = coordinator.run_round_pipeline_step(
        stage="pre_round_review",
        round_num=round_num,
        artifact=artifact,
        action_fn=_run_pre_round_review,
        action_kwargs={
            "coordinator": coordinator,
            "artifact": artifact,
            "recent_discussions": _recent_topic_discussions(artifact, rounds=1),
            "round_num": round_num,
        },
    )
    coordinator.run_round_pipeline_step(
        stage="save_pre_meeting_updates",
        round_num=round_num,
        artifact=artifact,
        action_fn=_save_pre_meeting_updates,
        action_kwargs={
            "coordinator": coordinator,
            "artifact": artifact,
            "round_num": round_num,
        },
    )
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
    coordinator.run_round_pipeline_step(
        stage="agenda_loop",
        round_num=round_num,
        artifact=artifact,
        action_fn=coordinator._run_agenda_loop,
        action_kwargs={"runner": runner},
    )
    return coordinator.run_round_pipeline_step(
        stage="post_round_pipeline",
        round_num=round_num,
        artifact=artifact,
        action_fn=_post_round_pipeline,
        action_kwargs={
            "coordinator": coordinator,
            "artifact": artifact,
            "runner": runner,
            "round_num": round_num,
        },
    )
