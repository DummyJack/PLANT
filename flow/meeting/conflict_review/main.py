import json
from typing import Any, Dict, List

from .record import build_pair_review_records
from .support import (
    analyst_signoff_conflict_recheck,
    analyst_changed_label_ids,
    analyst_finalize_conflict_review_reasons,
    collect_discussion_rows_and_pair_reviews,
    consensus_decisions_from_pair_reviews,
    ensure_conflict_review_participant_contributions,
    normalize_conflict_review_statement_for_record,
)
# ---------- 衝突再審查主流程 ----------

def run_conflict_review_round(
    coordinator: Any,
    issue: Dict[str, Any],
    artifact: Dict[str, Any],
    participants: List[str],
    discussion_mode: str,
    conflicts_by_id: Dict[str, Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[str], List[str]]:
    if discussion_mode == "simultaneous":
        contributions = coordinator.flow.mediator_agent.moderate_simultaneous(
            issue, coordinator.flow.registry, artifact=artifact
        )
    else:
        contributions, _ = coordinator.flow.mediator_agent.moderate_sequential(
            issue, coordinator.flow.registry, artifact=artifact
        )
    contributions = ensure_conflict_review_participant_contributions(
        coordinator,
        issue,
        artifact,
        contributions,
        participants,
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
        if isinstance(resp.get("pair_reviews"), list) and resp.get("pair_reviews"):
            statement = json.dumps(
                {
                    "review_summary": statement,
                    "pair_reviews": resp.get("pair_reviews"),
                },
                ensure_ascii=False,
            )
        normalized_statement = normalize_conflict_review_statement_for_record(
            statement,
            known_pair_ids=known_pair_ids,
            current_labels_by_id=current_labels_by_id,
        )
        resp["statement"] = normalized_statement
        c["response"] = resp
        conversation_rows.append(f"{agent_name}: {normalized_statement}")
    return contributions, conversation_rows, contribution_agents

def conflict_review(
    coordinator: Any, artifact: Dict[str, Any], round_num: int
) -> Dict[str, Any]:
    """針對本輪所有 Conflict/Neutral pairs 執行一次衝突再審查與逐筆裁定。"""
    candidates = [
        c
        for c in (artifact.get("conflicts", []) or [])
        if isinstance(c, dict) and str(c.get("label") or "").strip() in {"Conflict", "Neutral"}
    ]
    if not candidates:
        coordinator.flow.logger.info("需求衝突再審查：無需處理項目")
        return artifact

    conflicts_by_id: Dict[str, Dict[str, Any]] = {
        str(c.get("id") or "").strip(): c
        for c in candidates
        if str(c.get("id") or "").strip()
    }

    requirement_by_id: Dict[str, Dict[str, Any]] = {
        str(r.get("id") or "").strip(): r
        for r in (artifact.get("reqt_candidates") or [])
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
        req_rows = [
            {
                "id": rid,
                "text": str((requirement_by_id.get(rid) or {}).get("text") or "").strip(),
            }
            for rid in req_ids
        ]
        pair_cards.append({
            "id": cid,
            "current_label": label,
            "current_description": desc,
            "current_conflict_type": str(conflict.get("conflict_type") or "").strip(),
            "requirement_ids": req_ids,
            "requirements": req_rows,
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
        conflict["requirements"] = req_rows

    plan = coordinator.flow.mediator_agent.plan_conflict_review(
        candidates[0], artifact=artifact, registry=coordinator.flow.registry
    )
    participants = [
        str(p).strip()
        for p in (plan.get("participants") or [])
        if str(p).strip() and str(p).strip() != "user"
    ]
    if len(participants) < 2:
        raise RuntimeError("需求衝突再審查 plan 未產生至少兩位有效 participants")
    discussion_mode = str(plan.get("discussion_mode") or "").strip().lower()
    if discussion_mode not in {"sequential", "simultaneous"}:
        raise RuntimeError(f"需求衝突再審查 plan discussion_mode 不合法: {discussion_mode}")

    issue = {
        "id": "R1-conflict",
        "title": "需求衝突再審查（R1）",
        "description": coordinator.flow.mediator_agent.conflict_review_description(
            conflict_summaries
        ),
        "category": "conflict_discussion",
        "participants": participants,
        "discussion_mode": discussion_mode,
        "source_ids": list(conflicts_by_id.keys()),
        "pair_cards": pair_cards,
    }
    coordinator.flow.logger.info(
        "需求衝突再審查：mode=%s，participants=%s",
        discussion_mode,
        ", ".join(participants),
    )

    contributions, conversation_rows, contribution_agents = run_conflict_review_round(
        coordinator,
        issue,
        artifact,
        participants,
        discussion_mode,
        conflicts_by_id,
    )
    _, first_round_pair_reviews = collect_discussion_rows_and_pair_reviews(
        contributions,
        known_pair_ids=list(conflicts_by_id.keys()),
        current_labels_by_id={
            cid: str(conflict.get("label") or "").strip()
            for cid, conflict in conflicts_by_id.items()
            if isinstance(conflict, dict)
        },
    )
    for review in first_round_pair_reviews:
        if isinstance(review, dict):
            review["review_round"] = 1
    analyst_changed_ids = analyst_changed_label_ids(first_round_pair_reviews, conflicts_by_id)
    second_round_debug: Dict[str, Any] = {
        "triggered": bool(analyst_changed_ids),
        "trigger_ids": analyst_changed_ids,
    }
    if analyst_changed_ids:
        pair_card_by_id = {str(card.get("id") or ""): card for card in pair_cards}
        second_conflicts_by_id = {
            cid: conflicts_by_id[cid]
            for cid in analyst_changed_ids
            if cid in conflicts_by_id
        }
        second_pair_cards = [
            {
                **pair_card_by_id.get(cid, {}),
                "first_round_pair_reviews": [
                    review for review in first_round_pair_reviews
                    if str(review.get("id") or "") == cid
                ],
            }
            for cid in second_conflicts_by_id.keys()
        ]
        second_summaries = [
            f"- [{cid}] 原標籤={conflicts_by_id[cid].get('label')}  Analyst 第一輪改判，需要第二輪 proposed_label 共識"
            for cid in second_conflicts_by_id.keys()
        ]
        second_issue = {
            "id": "R2-conflict",
            "title": "需求衝突再審查（R2）",
            "description": (
                coordinator.flow.mediator_agent.conflict_review_description(second_summaries)
                + "\n\n第二輪目標：只針對 Analyst 第一輪 proposed_label 與原標籤不同的 pair 再審查。"
                + "請各 agent 根據 requirement 原文與第一輪 pair_reviews 重新輸出 proposed_label；"
                + "本輪結束後只看 proposed_label 是否一致。"
            ),
            "category": "conflict_discussion",
            "participants": participants,
            "discussion_mode": discussion_mode,
            "source_ids": list(second_conflicts_by_id.keys()),
            "pair_cards": second_pair_cards,
            "review_round": 2,
        }
        second_contributions, second_conversation_rows, second_agents = run_conflict_review_round(
            coordinator,
            second_issue,
            artifact,
            participants,
            discussion_mode,
            second_conflicts_by_id,
        )
        _, second_round_pair_reviews = collect_discussion_rows_and_pair_reviews(
            second_contributions,
            known_pair_ids=list(second_conflicts_by_id.keys()),
            current_labels_by_id={
                cid: str(conflict.get("label") or "").strip()
                for cid, conflict in second_conflicts_by_id.items()
                if isinstance(conflict, dict)
            },
        )
        for review in second_round_pair_reviews:
            if isinstance(review, dict):
                review["review_round"] = 2
        consensus_decisions, unresolved_second_conflicts, consensus_debug = (
            consensus_decisions_from_pair_reviews(
                second_conflicts_by_id,
                second_round_pair_reviews,
            )
        )
        second_round_debug.update({
            "issue_id": second_issue["id"],
            "contribution_agents": second_agents,
            "consensus": consensus_debug,
        })

        remaining_conflicts_by_id = {
            cid: conflict for cid, conflict in conflicts_by_id.items()
            if cid not in second_conflicts_by_id
        }
        remaining_decisions, remaining_debug = analyst_signoff_conflict_recheck(
            coordinator,
            contributions,
            remaining_conflicts_by_id,
        ) if remaining_conflicts_by_id else ([], {"signoff_status": "skipped_no_remaining_pairs"})
        unresolved_decisions, unresolved_debug = analyst_signoff_conflict_recheck(
            coordinator,
            second_contributions,
            unresolved_second_conflicts,
        ) if unresolved_second_conflicts else ([], {"signoff_status": "skipped_second_round_consensus"})
        decisions = remaining_decisions + consensus_decisions + unresolved_decisions
        extracted_pair_reviews = first_round_pair_reviews + second_round_pair_reviews
        final_reason_contributions = contributions + second_contributions
        signoff_debug = {
            "first_round_pair_reviews": first_round_pair_reviews,
            "second_round_pair_reviews": second_round_pair_reviews,
            "second_round": second_round_debug,
            "remaining_signoff": remaining_debug,
            "unresolved_second_round_signoff": unresolved_debug,
        }
        conversation_rows.extend(second_conversation_rows)
        contribution_agents.extend(second_agents)
    else:
        decisions, signoff_debug = analyst_signoff_conflict_recheck(
            coordinator, contributions, conflicts_by_id
        )
        extracted_pair_reviews = signoff_debug.get("extracted_pair_reviews", [])
        final_reason_contributions = contributions

    final_reason_debug = analyst_finalize_conflict_review_reasons(
        coordinator,
        decisions,
        conflicts_by_id,
        final_reason_contributions,
        extracted_pair_reviews if isinstance(extracted_pair_reviews, list) else [],
    )
    signoff_debug["final_reason"] = final_reason_debug

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
        decided_by = str(dec.get("decided_by") or "").strip()
        review_status = "consensus" if "consensus" in decided_by else "analyst"
        conflict["conflict_review"] = {
            "round": round_num,
            "result": "modify" if modify else "keep",
            "status": review_status,
            "from_label": old_label,
            "to_label": new_label if modify else old_label,
            "reason": str(dec.get("reason") or ""),
        }

    pair_review_records = build_pair_review_records(
        conflicts_by_id,
        decisions,
        extracted_pair_reviews if isinstance(extracted_pair_reviews, list) else [],
        round_num=round_num,
    )
    existing_pair_reviews = [
        row for row in (artifact.get("pair_reviews", []) or [])
        if not (
            isinstance(row, dict)
            and int(row.get("round") or -1) == int(round_num)
        )
    ]
    existing_pair_reviews.extend(pair_review_records)
    artifact["pair_reviews"] = existing_pair_reviews

    recheck_log = artifact.setdefault("conflict_review_log", [])
    recheck_log.append(
        {
            "round": round_num,
            "issue_id": issue.get("id"),
            "discussion_mode": discussion_mode,
            "participants": participants,
            "contribution_agents": contribution_agents,
            "candidates_count": len(decisions),
            "changed_count": changed,
            "conversation": conversation_rows,
            "decisions": decisions,
            "pair_reviews": pair_review_records,
            "signoff_debug": signoff_debug,
        }
    )

    coordinator.flow.logger.info("需求衝突再審查完成：%s 筆，改判 %s 筆", len(conflicts_by_id), changed)
    return artifact
