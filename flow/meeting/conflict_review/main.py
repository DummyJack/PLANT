# Conflict and requirement-change helpers for meeting rounds.

from typing import Any, Dict, List

from agents.base import build_pre_meeting_conflict_review_description

from .record import build_pair_review_records
from .support import (
    analyst_signoff_conflict_recheck,
    ensure_conflict_review_participant_contributions,
    normalize_conflict_review_statement_for_record,
)
# ---------- 會前衝突再審查主流程 ----------

def conflict_review(
    coordinator: Any, artifact: Dict[str, Any], round_num: int
) -> Dict[str, Any]:
    """針對本輪所有 Conflict/Neutral pairs 執行一次會前再審查與逐筆裁定。"""
    candidates = [
        c
        for c in (artifact.get("conflicts", []) or [])
        if isinstance(c, dict) and str(c.get("label") or "").strip() in {"Conflict", "Neutral"}
    ]
    if not candidates:
        coordinator.flow.logger.info("會前衝突再審查：無需處理項目")
        return artifact

    conflicts_by_id: Dict[str, Dict[str, Any]] = {
        str(c.get("id") or "").strip(): c
        for c in candidates
        if str(c.get("id") or "").strip()
    }

    requirement_by_id: Dict[str, Dict[str, Any]] = {
        str(r.get("id") or "").strip(): r
        for r in (artifact.get("requirements", []) or [])
        if isinstance(r, dict) and str(r.get("id") or "").strip()
    }

    conflict_summaries = []
    pair_cards = []
    for cid, conflict in conflicts_by_id.items():
        label = str(conflict.get("label") or "").strip()
        desc = (conflict.get("description") or "").strip()
        req_ids = [str(r) for r in (conflict.get("requirement_ids") or []) if str(r).strip()]
        conflict_summaries.append(f"- [{cid}] 標籤={label}  需求={req_ids}  描述: {desc}")
        req_a_id = req_ids[0] if len(req_ids) >= 1 else ""
        req_b_id = req_ids[1] if len(req_ids) >= 2 else ""
        req_a = requirement_by_id.get(req_a_id, {})
        req_b = requirement_by_id.get(req_b_id, {})
        pair_cards.append({
            "id": cid,
            "current_label": label,
            "current_description": desc,
            "current_conflict_type": str(conflict.get("conflict_type") or "").strip(),
            "requirement_ids": req_ids,
            "requirement_a": {
                "id": req_a_id,
                "text": str(req_a.get("text") or "").strip(),
            },
            "requirement_b": {
                "id": req_b_id,
                "text": str(req_b.get("text") or "").strip(),
            },
        })
        conflict["requirement_a"] = {
            "id": req_a_id,
            "text": str(req_a.get("text") or "").strip(),
        }
        conflict["requirement_b"] = {
            "id": req_b_id,
            "text": str(req_b.get("text") or "").strip(),
        }

    plan = coordinator.flow.mediator_agent.plan_pre_meeting_conflict_review(
        candidates[0], artifact=artifact, registry=coordinator.flow.registry
    )
    participants = [
        str(p).strip()
        for p in (plan.get("participants") or ["analyst", "expert", "modeler"])
        if str(p).strip() and str(p).strip() != "user"
    ]
    if len(participants) < 2:
        participants = ["analyst", "expert", "modeler"]
    discussion_mode = str(plan.get("discussion_mode") or "sequential").strip().lower()
    if discussion_mode not in {"sequential", "simultaneous"}:
        discussion_mode = "sequential"

    topic = {
        "id": f"PM-R{round_num}",
        "title": f"會前衝突批次再審查（Round {round_num}）",
        "description": build_pre_meeting_conflict_review_description(conflict_summaries),
        "category": "conflict_discussion",
        "participants": participants,
        "discussion_mode": discussion_mode,
        "source_ids": list(conflicts_by_id.keys()),
        "pair_cards": pair_cards,
    }

    if discussion_mode == "simultaneous":
        contributions = coordinator.flow.mediator_agent.moderate_simultaneous(
            topic, coordinator.flow.registry, artifact=artifact
        )
        oq_records = []
    else:
        contributions, oq_records = coordinator.flow.mediator_agent.moderate_sequential(
            topic, coordinator.flow.registry, artifact=artifact
        )
        oq_records = []
    contributions = ensure_conflict_review_participant_contributions(
        coordinator,
        topic,
        artifact,
        contributions,
        participants,
    )
    coordinator.flow.logger.info(
        "Conflict judgment meeting: topic=%s mode=%s participants=%s contributions=%s open_questions=%s",
        topic["id"],
        discussion_mode,
        participants,
        len(contributions or []),
        len(oq_records or []),
    )
    if contributions:
        coordinator.flow.logger.info(
            "Conflict judgment meeting: contribution_agents=%s",
            [
                str(c.get("agent") or "").strip()
                for c in contributions
                if isinstance(c, dict)
            ],
        )
    contribution_agents = [
        str(c.get("agent") or "").strip()
        for c in contributions
        if isinstance(c, dict)
    ]

    conversation_rows: List[str] = []
    known_pair_ids = list(conflicts_by_id.keys())
    current_labels_by_id = {
        cid: str(conflict.get("label") or "").strip()
        for cid, conflict in conflicts_by_id.items()
        if isinstance(conflict, dict)
    }
    for c in contributions:
        if not isinstance(c, dict):
            continue
        agent_name = str(c.get("agent") or "").strip()
        resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
        statement = str(resp.get("statement") or resp.get("content") or "").strip()
        if not agent_name or not statement:
            continue
        normalized_statement = normalize_conflict_review_statement_for_record(
            statement,
            known_pair_ids=known_pair_ids,
            current_labels_by_id=current_labels_by_id,
        )
        resp["statement"] = normalized_statement
        c["response"] = resp
        statement = normalized_statement
        conversation_rows.append(f"{agent_name}: {statement}")

    decisions, signoff_debug = analyst_signoff_conflict_recheck(
        coordinator, contributions, conflicts_by_id
    )
    extracted_pair_reviews = signoff_debug.get("extracted_pair_reviews", [])

    changed = 0
    for dec in decisions:
        cid = str(dec.get("id") or "").strip()
        conflict = conflicts_by_id.get(cid)
        if not conflict:
            continue
        new_label = str(dec.get("new_label") or "").strip()
        old_label = str(conflict.get("label") or "").strip()
        modify = new_label in {"Conflict", "Neutral"} and new_label != old_label
        if modify:
            conflict["label"] = new_label
            changed += 1
        conflict["pre_meeting_review"] = {
            "round": round_num,
            "result": "modify" if modify else "keep",
            "from_label": old_label,
            "to_label": new_label if modify else old_label,
            "reason": str(dec.get("reason") or ""),
        }

    pair_review_records = build_pair_review_records(
        conflicts_by_id,
        decisions,
        extracted_pair_reviews if isinstance(extracted_pair_reviews, list) else [],
        round_num=round_num,
        topic_id=topic["id"],
    )
    existing_pair_reviews = [
        row for row in (artifact.get("pair_reviews", []) or [])
        if not (
            isinstance(row, dict)
            and int(row.get("round") or -1) == int(round_num)
            and str(row.get("topic_id") or "") == topic["id"]
        )
    ]
    existing_pair_reviews.extend(pair_review_records)
    artifact["pair_reviews"] = existing_pair_reviews

    recheck_log = artifact.setdefault("conflict_recheck_log", [])
    recheck_log.append(
        {
            "round": round_num,
            "topic_id": topic.get("id"),
            "discussion_mode": discussion_mode,
            "participants": participants,
            "contribution_agents": contribution_agents,
            "candidates_count": len(decisions),
            "changed_count": changed,
            "conversation": conversation_rows,
            "decisions": decisions,
            "pair_reviews": pair_review_records,
        }
    )

    coordinator.flow.logger.info("會前衝突再審查：%s 筆，改 %s", len(conflicts_by_id), changed)
    return artifact
