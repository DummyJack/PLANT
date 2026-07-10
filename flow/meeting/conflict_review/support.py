# Handles support logic for project flow orchestration and stage execution.
import json
import re
from typing import Any, Dict, List, Optional

from agents.meeting.pair_review import normalize_pair_review_record
from agents.profile.analyst.conflicts import all_conflict_rows, normalize_conflict_state


def conflict_current_label(conflict: Dict[str, Any]) -> str:
    return str(conflict.get("final_label") or "").strip()


# ========
# Defines mark conflicts resolved by ids function for this module workflow.
# ========
def mark_conflicts_resolved_by_ids(
    artifact: Dict[str, Any],
    conflict_ids: List[str],
) -> None:
    if not conflict_ids:
        return
    target = {str(cid).strip() for cid in conflict_ids if str(cid).strip()}
    for c in all_conflict_rows(artifact):
        cid = str(c.get("id") or "").strip()
        if cid not in target:
            continue
        c["final_label"] = "Neutral"
    normalize_conflict_state(artifact)

def normalize_expert_non_intervention_review(
    review: Dict[str, Any],
    *,
    current_label: str,
) -> Dict[str, Any]:
    if current_label not in {"Conflict", "Neutral"}:
        return review
    proposed_label = str(review.get("proposed_label") or "").strip()
    if proposed_label == current_label:
        return review
    reason = str(review.get("reason") or "").strip().lower()
    non_intervention_markers = (
        "no external",
        "no evidence of external",
        "no known external",
        "no regulatory",
        "not a regulatory conflict",
        "not a compliance conflict",
        "absence of such external",
        "in the absence of such evidence",
        "unless a specific",
        "無外部",
        "沒有外部",
        "沒有外部證據",
        "不屬於外部證據衝突",
    )
    if not any(marker in reason for marker in non_intervention_markers):
        return review
    normalized = dict(review)
    normalized["proposed_label"] = current_label
    normalized["decision"] = "keep"
    return normalized


def normalize_requirement_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def description_contradicts_label(description: str, final_label: str) -> bool:
    text = normalize_requirement_text(description)
    if not text:
        return False
    if final_label == "Conflict":
        neutral_markers = (
            "no conflict",
            "not conflict",
            "not in conflict",
            "there is no conflict",
            "can coexist",
            "can co-exist",
            "do not conflict",
            "does not conflict",
            "不構成衝突",
            "可以共存",
            "可共存",
        )
        return any(marker in text for marker in neutral_markers)
    if final_label == "Neutral":
        conflict_markers = (
            "mutually exclusive",
            "cannot coexist",
            "cannot co-exist",
            "direct conflict",
            "in conflict",
            "互斥",
            "不可共存",
            "無法共存",
            "構成衝突",
        )
        return any(marker in text for marker in conflict_markers)
    return False


# ========
# Defines extract reviews from json function for this module workflow.
# ========
def extract_reviews_from_json(
    text: str,
    *,
    known_pair_ids: List[str],
    current_labels_by_id: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    text = str(text or "").strip()
    if not text:
        return []

    pair_id_set = {str(x).strip() for x in (known_pair_ids or []) if str(x).strip()}
    reviews: List[Dict[str, Any]] = []

    try:
        parsed = json.loads(text)
    except Exception:
        parsed = None

    if isinstance(parsed, dict):
        raw_reviews = parsed.get("pair_reviews")
        if isinstance(raw_reviews, list):
            for raw_review in raw_reviews:
                normalized = normalize_pair_review_record(
                    raw_review,
                    pair_id_set=pair_id_set,
                    current_labels_by_id=current_labels_by_id,
                )
                if normalized:
                    reviews.append(normalized)
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for review in reviews:
        key = (review.get("id"), review.get("decision"), review.get("proposed_label"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(review)
    return deduped


# ========
# Defines normalize review text function for this module workflow.
# ========
def normalize_review_text(
    text: str,
    *,
    known_pair_ids: List[str],
    current_labels_by_id: Optional[Dict[str, str]] = None,
) -> str:
    text = str(text or "").strip()
    if not text:
        return ""

    reviews = extract_reviews_from_json(
        text,
        known_pair_ids=known_pair_ids,
        current_labels_by_id=current_labels_by_id,
    )
    if not reviews:
        return text

    review_summary = ""
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        review_summary = str(parsed.get("review_summary") or "").strip()

    return json.dumps(
        {
            "review_summary": review_summary,
            "pair_reviews": reviews,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )

# ========
# Defines collect discussion rows function for this module workflow.
# ========
def collect_discussion_rows(conversation: List[Dict[str, Any]]) -> list[dict]:
    discussion_rows: List[Dict[str, Any]] = []
    for c in conversation or []:
        if not isinstance(c, dict):
            continue
        resp = c.get("response") or {}
        text = ""
        if isinstance(resp, dict):
            text = (resp.get("text") or resp.get("content") or "").strip()
        else:
            text = str(resp).strip()
        agent_name = str(c.get("agent") or "").strip()
        if text:
            discussion_rows.append({"agent": agent_name, "text": text})
    return discussion_rows

# ========
# Defines collect reviews function for this module workflow.
# ========
def collect_reviews(
    conversation: List[Dict[str, Any]],
    *,
    known_pair_ids: List[str],
    current_labels_by_id: Optional[Dict[str, str]] = None,
) -> tuple[list[dict], list[dict]]:
    discussion_rows = collect_discussion_rows(conversation)
    extracted_pair_reviews: List[Dict[str, Any]] = []
    seen_reviews: set[tuple[str, str, str, str]] = set()
    for c in conversation or []:
        if not isinstance(c, dict):
            continue
        agent_name = str(c.get("agent") or "").strip()
        resp = c.get("response") or {}
        raw_reviews = resp.get("pair_reviews") if isinstance(resp, dict) else None
        if not isinstance(raw_reviews, list):
            text = ""
            if isinstance(resp, dict):
                text = str(resp.get("text") or resp.get("content") or "").strip()
            parsed_reviews = extract_reviews_from_json(
                text,
                known_pair_ids=known_pair_ids,
                current_labels_by_id=current_labels_by_id,
            )
            if parsed_reviews:
                raw_reviews = parsed_reviews
        if isinstance(raw_reviews, list) and raw_reviews:
            pair_id_set = {str(x).strip() for x in known_pair_ids if str(x).strip()}
            for raw_review in raw_reviews:
                normalized = normalize_pair_review_record(
                    raw_review,
                    pair_id_set=pair_id_set,
                    current_labels_by_id=current_labels_by_id,
                )
                if normalized:
                    if agent_name == "expert":
                        current_label = ""
                        if current_labels_by_id:
                            current_label = str(
                                current_labels_by_id.get(str(normalized.get("id") or "").strip()) or ""
                            ).strip()
                        normalized = normalize_expert_non_intervention_review(
                            normalized,
                            current_label=current_label,
                        )
                    key = (
                        agent_name,
                        str(normalized.get("id") or "").strip(),
                        str(normalized.get("proposed_label") or "").strip(),
                        str(normalized.get("reason") or "").strip(),
                    )
                    if key in seen_reviews:
                        continue
                    seen_reviews.add(key)
                    extracted_pair_reviews.append({"agent": agent_name, **normalized})
            continue
    return discussion_rows, extracted_pair_reviews

# ========
# Defines get conversation text function for this module workflow.
# ========
def get_conversation_text(conversation: Dict[str, Any]) -> str:
    if not isinstance(conversation, dict):
        return ""
    resp = conversation.get("response", {}) if isinstance(conversation.get("response"), dict) else {}
    return str(resp.get("text") or resp.get("content") or "").strip()


# ========
# Defines merge review decisions function for this module workflow.
# ========
def merge_review_decisions(
    conflicts_by_id: Dict[str, Dict[str, Any]],
    extracted_pair_reviews: List[Dict[str, Any]],
    *,
    expected_agents: Optional[set[str]] = None,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    expected_agents = expected_agents or {"analyst", "expert", "modeler"}
    reviews_by_id: Dict[str, List[Dict[str, Any]]] = {}
    for review in extracted_pair_reviews or []:
        if not isinstance(review, dict):
            continue
        rid = str(review.get("id") or "").strip()
        if not rid or rid not in conflicts_by_id:
            continue
        reviews_by_id.setdefault(rid, []).append(review)

    auto_decisions: List[Dict[str, Any]] = []
    signoff_targets: List[Dict[str, Any]] = []
    info: Dict[str, Any] = {
        "auto_keep_count": 0,
        "auto_modify_count": 0,
        "signoff_target_count": 0,
        "signoff_target_ids_preview": [],
    }

    for cid, conflict in conflicts_by_id.items():
        current_label = conflict_current_label(conflict)
        reviews = reviews_by_id.get(cid, [])
        review_agents = {
            str(r.get("agent") or "").strip()
            for r in reviews
            if str(r.get("agent") or "").strip()
        }
        missing_expected_agents = sorted(expected_agents - review_agents)
        valid_labels = [
            str(r.get("proposed_label") or "").strip()
            for r in reviews
            if str(r.get("proposed_label") or "").strip() in {"Conflict", "Neutral"}
        ]
        valid_decisions = [
            str(r.get("decision") or "").strip().lower()
            for r in reviews
            if str(r.get("decision") or "").strip().lower() in {"keep", "modify"}
        ]
        reasons = [
            str(r.get("reason") or "").strip()
            for r in reviews
            if str(r.get("reason") or "").strip()
        ]
        any_modify = "modify" in valid_decisions
        unique_labels = sorted(set(valid_labels))
        unresolved = (
            (not reviews)
            or bool(missing_expected_agents)
            or (not valid_labels)
            or any_modify
            or len(unique_labels) > 1
        )

        if unresolved:
            signoff_targets.append(
                {
                    "id": cid,
                    "current_label": current_label,
                    "requirements": list(conflict.get("requirements") or []),
                    "requirement_a": dict((conflict.get("requirement_a") or {})),
                    "requirement_b": dict((conflict.get("requirement_b") or {})),
                    "signoff_reason": (
                        "missing_expected_agent_review"
                        if missing_expected_agents
                        else "missing_or_disputed_pair_review"
                    ),
                    "missing_expected_agents": missing_expected_agents,
                }
            )
            continue

        decided_label = unique_labels[0] if unique_labels else current_label
        auto_decisions.append(
            {
                "id": cid,
                "final_label": decided_label,
                "reason": reasons[0] if reasons else "consensus_keep_current_label",
                "decided_by": "consensus",
            }
        )
        if decided_label == current_label:
            info["auto_keep_count"] += 1
        else:
            info["auto_modify_count"] += 1

    info["signoff_target_count"] = len(signoff_targets)
    info["signoff_target_ids_preview"] = [row.get("id") for row in signoff_targets[:5]]
    return auto_decisions, signoff_targets, info


# ========
# Defines analyst changed label ids function for this module workflow.
# ========
def analyst_changed_label_ids(
    extracted_pair_reviews: List[Dict[str, Any]],
    conflicts_by_id: Dict[str, Dict[str, Any]],
) -> List[str]:
    changed: List[str] = []
    for review in extracted_pair_reviews or []:
        if not isinstance(review, dict):
            continue
        if str(review.get("agent") or "").strip() != "analyst":
            continue
        cid = str(review.get("id") or "").strip()
        proposed_label = str(review.get("proposed_label") or "").strip()
        current_label = conflict_current_label(conflicts_by_id.get(cid) or {})
        if cid and proposed_label in {"Conflict", "Neutral"} and current_label in {"Conflict", "Neutral"}:
            if proposed_label != current_label and cid not in changed:
                changed.append(cid)
    return changed


# ========
# Defines consensus decisions function for this module workflow.
# ========
def consensus_decisions(
    conflicts_by_id: Dict[str, Dict[str, Any]],
    extracted_pair_reviews: List[Dict[str, Any]],
    *,
    min_valid_labels: int = 2,
    expected_agents: Optional[set[str]] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Any]]:
    expected_agents = expected_agents or {"analyst", "expert", "modeler"}
    reviews_by_id: Dict[str, List[Dict[str, Any]]] = {}
    for review in extracted_pair_reviews or []:
        if not isinstance(review, dict):
            continue
        cid = str(review.get("id") or "").strip()
        if cid in conflicts_by_id:
            reviews_by_id.setdefault(cid, []).append(review)

    decisions: List[Dict[str, Any]] = []
    unresolved: Dict[str, Dict[str, Any]] = {}
    info = {
        "consensus_count": 0,
        "unresolved_count": 0,
        "unresolved_ids_preview": [],
    }
    for cid, conflict in conflicts_by_id.items():
        reviews = reviews_by_id.get(cid, [])
        review_agents = {
            str(r.get("agent") or "").strip()
            for r in reviews
            if str(r.get("agent") or "").strip()
        }
        has_expected_reviews = expected_agents.issubset(review_agents)
        labels = [
            str(r.get("proposed_label") or "").strip()
            for r in reviews
            if str(r.get("proposed_label") or "").strip() in {"Conflict", "Neutral"}
        ]
        unique_labels = sorted(set(labels))
        if (
            has_expected_reviews
            and len(labels) >= min_valid_labels
            and len(unique_labels) == 1
        ):
            reasons = [
                str(r.get("reason") or "").strip()
                for r in reviews
                if str(r.get("reason") or "").strip()
            ]
            decisions.append(
                {
                    "id": cid,
                    "final_label": unique_labels[0],
                    "reason": reasons[0] if reasons else "consensus_keep_current_label",
                    "decided_by": "consensus",
                }
            )
            info["consensus_count"] += 1
        else:
            unresolved[cid] = conflict
    info["unresolved_count"] = len(unresolved)
    info["unresolved_ids_preview"] = list(unresolved.keys())[:5]
    return decisions, unresolved, info

# ========
# Defines finalize review reasons function for this module workflow.
# ========
def finalize_review_reasons(
    coordinator: Any,
    decisions: List[Dict[str, Any]],
    conflicts_by_id: Dict[str, Dict[str, Any]],
    conversation: List[Dict[str, Any]],
    extracted_pair_reviews: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if not decisions:
        return {"final_reason_status": "skipped_no_decisions"}
    discussion_rows, extracted_from_conversation = collect_reviews(
        conversation,
        known_pair_ids=list(conflicts_by_id.keys()),
        current_labels_by_id={
            cid: conflict_current_label(conflict)
            for cid, conflict in conflicts_by_id.items()
            if isinstance(conflict, dict)
        },
    )
    reviews_for_prompt = (
        extracted_pair_reviews
        if isinstance(extracted_pair_reviews, list) and extracted_pair_reviews
        else extracted_from_conversation
    )
    decision_items: List[Dict[str, Any]] = []
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        cid = str(decision.get("id") or "").strip()
        if not cid or cid not in conflicts_by_id:
            continue
        conflict = conflicts_by_id[cid]
        req_rows = [
            {
                "id": str(req.get("id") or "").strip(),
                "text": str(req.get("text") or "").strip(),
            }
            for req in (conflict.get("requirements") or [])
            if isinstance(req, dict)
            and str(req.get("id") or "").strip()
            and str(req.get("text") or "").strip()
        ]
        decision_items.append(
            {
                "id": cid,
                "final_label": str(decision.get("final_label") or "").strip(),
                "requirements": req_rows,
            }
        )
    def reviews_for_ids(pair_ids: set[str]) -> List[Dict[str, Any]]:
        return [
            row for row in reviews_for_prompt
            if isinstance(row, dict) and str(row.get("id") or "").strip() in pair_ids
        ]

    def fetch_reason_batch(batch: List[Dict[str, Any]]) -> tuple[List[Dict[str, str]], str]:
        batch_ids = {
            str(item.get("id") or "").strip()
            for item in batch
            if str(item.get("id") or "").strip()
        }
        return coordinator.flow.analyst_agent.finalize_review(
            batch,
            discussion_rows,
            extracted_pair_reviews=reviews_for_ids(batch_ids),
        )

    reason_by_id: Dict[str, str] = {}
    final_type_by_id: Dict[str, str] = {}
    batch_size = 8
    for start in range(0, len(decision_items), batch_size):
        batch = decision_items[start : start + batch_size]
        reason_rows, _ = fetch_reason_batch(batch)
        for row in reason_rows:
            if not isinstance(row, dict):
                continue
            pair_id = str(row.get("id") or "").strip()
            reason = str(row.get("reason") or "").strip()
            if pair_id and reason:
                reason_by_id[pair_id] = reason
                final_type = str(row.get("final_type") or "").strip()
                if final_type:
                    final_type_by_id[pair_id] = final_type

    missing = [
        str(item.get("id") or "").strip()
        for item in decision_items
        if str(item.get("id") or "").strip() not in reason_by_id
    ]
    if missing:
        retry_items = [
            item for item in decision_items
            if str(item.get("id") or "").strip() in set(missing)
        ]
        for start in range(0, len(retry_items), batch_size):
            batch = retry_items[start : start + batch_size]
            reason_rows, _ = fetch_reason_batch(batch)
            for row in reason_rows:
                if not isinstance(row, dict):
                    continue
                pair_id = str(row.get("id") or "").strip()
                reason = str(row.get("reason") or "").strip()
                if pair_id and reason:
                    reason_by_id[pair_id] = reason
                    final_type = str(row.get("final_type") or "").strip()
                    if final_type:
                        final_type_by_id[pair_id] = final_type

    missing = [
        str(item.get("id") or "").strip()
        for item in decision_items
        if str(item.get("id") or "").strip() not in reason_by_id
    ]
    if missing:
        raise RuntimeError(f"Analyst final reason 缺少 pair: {missing}")
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        cid = str(decision.get("id") or "").strip()
        final_label = str(decision.get("final_label") or "").strip()
        if cid in reason_by_id and description_contradicts_label(reason_by_id[cid], final_label):
            fallback_reason = str(decision.get("reason") or "").strip()
            reason_by_id[cid] = fallback_reason or f"依最終裁定結果整理為 {final_label}。"
        if cid in reason_by_id:
            decision["reason"] = reason_by_id[cid]
            decision["reason_by"] = "analyst"
        if cid in final_type_by_id:
            decision["final_type"] = final_type_by_id[cid]
        elif final_label == "Conflict":
            conflict = conflicts_by_id.get(cid) if isinstance(conflicts_by_id, dict) else {}
            fallback_type = str(
                (conflict or {}).get("final_type")
                or "other"
            ).strip().lower()
            decision["final_type"] = fallback_type or "other"
    return {
        "final_reason_status": "ok",
        "reason_count": len(reason_by_id),
    }

# ========
# Defines complete missing review decisions function for this module workflow.
# ========
def complete_missing_review_decisions(
    coordinator: Any,
    decisions: List[Dict[str, Any]],
    conflicts_by_id: Dict[str, Dict[str, Any]],
    extracted_pair_reviews: List[Dict[str, Any]],
    conversation: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    existing_ids = {
        str(dec.get("id") or "").strip()
        for dec in decisions or []
        if isinstance(dec, dict) and str(dec.get("id") or "").strip()
    }
    missing_ids = [
        cid for cid in conflicts_by_id.keys()
        if cid not in existing_ids
    ]
    info: Dict[str, Any] = {
        "missing_decision_ids": missing_ids,
        "missing_decision_count": len(missing_ids),
    }
    if not missing_ids:
        info["status"] = "skipped_no_missing_decisions"
        return decisions, info

    discussion_rows, extracted_from_conversation = collect_reviews(
        conversation,
        known_pair_ids=list(conflicts_by_id.keys()),
        current_labels_by_id={
            cid: conflict_current_label(conflict)
            for cid, conflict in conflicts_by_id.items()
            if isinstance(conflict, dict)
        },
    )
    reviews_for_prompt = (
        extracted_pair_reviews
        if isinstance(extracted_pair_reviews, list) and extracted_pair_reviews
        else extracted_from_conversation
    )
    missing_set = set(missing_ids)
    proposal_list = []
    for cid in missing_ids:
        conflict = conflicts_by_id.get(cid) or {}
        proposal_list.append(
            {
                "id": cid,
                "current_label": conflict_current_label(conflict),
                "requirements": list(conflict.get("requirements") or []),
                "requirement_a": dict((conflict.get("requirement_a") or {})),
                "requirement_b": dict((conflict.get("requirement_b") or {})),
                "signoff_reason": "missing_review_decision",
            }
        )
    reviews_for_missing = [
        row for row in reviews_for_prompt or []
        if isinstance(row, dict) and str(row.get("id") or "").strip() in missing_set
    ]

    coordinator.flow.logger.warning(
        "衝突再審查缺少 decisions，啟動 Analyst 補裁定：%s",
        ", ".join(missing_ids[:10]),
    )
    results, _ = coordinator.flow.analyst_agent.review_conflicts(
        proposal_list,
        discussion_rows,
        extracted_pair_reviews=reviews_for_missing,
    )
    completed = []
    for row in results or []:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("id") or "").strip()
        if cid not in missing_set:
            continue
        row["decided_by"] = "analyst"
        completed.append(row)
    completed_ids = {
        str(row.get("id") or "").strip()
        for row in completed
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }
    still_missing = [cid for cid in missing_ids if cid not in completed_ids]
    info["completed_missing_decision_count"] = len(completed)
    info["completed_missing_decision_ids"] = sorted(completed_ids)
    if still_missing:
        info["status"] = "failed_missing_after_loop"
        info["still_missing_decision_ids"] = still_missing
        raise RuntimeError(f"Analyst missing decision 補裁定後仍缺少 pair: {still_missing}")
    info["status"] = "ok"
    return list(decisions or []) + completed, info

# ========
# Defines collect missing reviews function for this module workflow.
# ========
def collect_missing_reviews(
    coordinator: Any,
    issue: Dict[str, Any],
    artifact: Dict[str, Any],
    conversation: List[Dict[str, Any]],
    participants: List[str],
) -> List[Dict[str, Any]]:
    def has_review_response(row: Dict[str, Any]) -> bool:
        resp = row.get("response") if isinstance(row.get("response"), dict) else {}
        if get_conversation_text(row):
            return True
        return isinstance(resp.get("pair_reviews"), list) and bool(resp.get("pair_reviews"))

    existing_with_response = {
        str(c.get("agent") or "").strip()
        for c in conversation or []
        if isinstance(c, dict)
        and str(c.get("agent") or "").strip()
        and has_review_response(c)
    }
    missing = [
        str(p).strip()
        for p in participants or []
        if str(p).strip() and str(p).strip() not in existing_with_response
    ]
    if not missing:
        return conversation

    coordinator.flow.store.save_artifact(artifact)
    out = list(conversation or [])
    retry_issue = {
        **issue,
        "discussion_mode": "simultaneous",
        "participants": missing,
        "title": "衝突缺席角色補審",
    }
    for agent_name in missing:
        agent = coordinator.flow.registry.get(agent_name)
        if not agent:
            raise RuntimeError(f"Conflict review 補審 Agent 未註冊: {agent_name}")
        try:
            response = coordinator.flow.mediator_agent.collect_issue_response(
                agent,
                retry_issue,
                previous_responses=None,
            )
            out.append(
                {
                    "agent": agent_name,
                    "response": response if isinstance(response, dict) else {"content": str(response)},
                }
            )
        except Exception as e:
            raise RuntimeError(f"Conflict review 補審：{agent_name} 發言失敗") from e
    return out

# ========
# Defines analyst signoff function for this module workflow.
# ========
def analyst_signoff(
    coordinator: Any,
    conversation: List[Dict[str, Any]],
    conflicts_by_id: Dict[str, Dict[str, Any]],
    *,
    expected_agents: Optional[set[str]] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    discussion_rows, extracted_pair_reviews = collect_reviews(
        conversation,
        known_pair_ids=list(conflicts_by_id.keys()),
        current_labels_by_id={
            cid: conflict_current_label(conflict)
            for cid, conflict in conflicts_by_id.items()
            if isinstance(conflict, dict)
        },
    )
    signoff_info: Dict[str, Any] = {
        "conversation_count": len(conversation or []),
        "discussion_rows_count": len(discussion_rows),
        "extracted_pair_reviews_count": len(extracted_pair_reviews),
        "extracted_pair_reviews_preview": extracted_pair_reviews[:3],
        "extracted_pair_reviews": extracted_pair_reviews,
    }
    if extracted_pair_reviews:
        coordinator.flow.logger.info(
            "需求衝突再審查裁定：pair_reviews 預覽=%s",
            json.dumps(extracted_pair_reviews[:3], ensure_ascii=False),
        )
    else:
        coordinator.flow.logger.warning(
            "需求衝突再審查裁定：未解析出 pair_reviews"
        )

    auto_decisions, proposal_list, merge_info = merge_review_decisions(
        conflicts_by_id,
        extracted_pair_reviews,
        expected_agents=expected_agents,
    )
    signoff_info.update(merge_info)
    signoff_info["auto_decisions_preview"] = auto_decisions[:3]

    if not proposal_list:
        coordinator.flow.logger.info("需求衝突再審查裁定：無爭議 pair，略過 Analyst 最終裁定")
        signoff_info["proposal_list_count"] = 0
        signoff_info["proposal_pair_ids_preview"] = []
        signoff_info["signoff_status"] = "skipped_no_disputed_pairs"
        signoff_info["decisions_count"] = len(auto_decisions)
        signoff_info["decisions_preview"] = auto_decisions[:3]
        return auto_decisions, signoff_info
    coordinator.flow.logger.info(
        "需求衝突再審查裁定：待 Analyst 裁定 pairs=%s，預覽=%s",
        len(proposal_list),
        ", ".join([str(row.get("id") or "") for row in proposal_list[:5]]),
    )
    signoff_info["proposal_list_count"] = len(proposal_list)
    signoff_info["proposal_pair_ids_preview"] = [row.get("id") for row in proposal_list[:5]]

    try:
        results, _ = coordinator.flow.analyst_agent.review_conflicts(
            proposal_list,
            discussion_rows,
            extracted_pair_reviews=extracted_pair_reviews,
        )
        if not results:
            signoff_info["signoff_status"] = "empty_or_invalid_decisions"
            raise RuntimeError("Analyst 衝突裁定在 agent loop 後仍未產生有效 decisions")

        for r in results:
            if isinstance(r, dict):
                r["decided_by"] = "analyst"
        merged_results = auto_decisions + results
        coordinator.flow.logger.info("Analyst 衝突裁定完成：%s 筆", len(results))
        coordinator.flow.logger.info(
            "需求衝突再審查裁定：Analyst 裁定結果預覽=%s",
            json.dumps(merged_results[:3], ensure_ascii=False),
        )
        signoff_info["signoff_status"] = "ok"
        signoff_info["decisions_count"] = len(merged_results)
        signoff_info["decisions_preview"] = merged_results[:3]
        return merged_results, signoff_info
    except Exception as e:
        signoff_info["signoff_status"] = "exception"
        signoff_info["exception"] = str(e)
        raise RuntimeError(f"Analyst 衝突裁定失敗: {e}") from e
