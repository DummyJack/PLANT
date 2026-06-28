# Handles conversation logic for project flow orchestration and stage execution.
from typing import Any, Dict, List


# ========
# Defines build pair review conversation function for this module workflow.
# ========
def build_pair_review_conversation(
    conflicts_by_id: Dict[str, Dict[str, Any]],
    decisions: List[Dict[str, Any]],
    extracted_pair_reviews: List[Dict[str, Any]],
    *,
    round_num: int,
) -> List[Dict[str, Any]]:
    reviews_by_id: Dict[str, List[Dict[str, Any]]] = {}
    for review in extracted_pair_reviews or []:
        if not isinstance(review, dict):
            continue
        rid = str(review.get("id") or "").strip()
        if rid:
            reviews_by_id.setdefault(rid, []).append(review)

    decision_by_id = {
        str(dec.get("id") or "").strip(): dec
        for dec in decisions or []
        if isinstance(dec, dict) and str(dec.get("id") or "").strip()
    }

    conversations: List[Dict[str, Any]] = []
    for pair_id, conflict in conflicts_by_id.items():
        req_ids = [str(r) for r in (conflict.get("requirement_ids") or []) if str(r).strip()]
        decision = decision_by_id.get(pair_id)
        if not isinstance(decision, dict):
            raise RuntimeError(f"缺少衝突再審查 decision: {pair_id}")
        final_label = str(decision.get("final_label") or "").strip()
        if final_label not in {"Conflict", "Neutral"}:
            raise RuntimeError(f"衝突再審查 final_label 不合法: {pair_id}")
        initial_label = str(conflict.get("initial_label") or conflict.get("final_label") or "").strip()
        if initial_label not in {"Conflict", "Neutral"}:
            raise RuntimeError(f"衝突再審查 initial_label 不合法: {pair_id}")
        description = str(decision.get("reason") or "").strip()
        if not description:
            raise RuntimeError(f"缺少衝突再審查 description: {pair_id}")
        status = str(decision.get("decided_by") or "").strip()
        if status not in {"consensus", "analyst"}:
            raise RuntimeError(f"衝突再審查 status 不合法: {pair_id}")
        flat_reviews = reviews_by_id.get(pair_id, [])
        meeting: Dict[str, List[Dict[str, Any]]] = {}
        for row in flat_reviews:
            try:
                review_round = int(row.get("review_round") or 1)
            except (TypeError, ValueError):
                review_round = 1
            key = f"r{review_round}"
            review_row = dict(row)
            review_row.pop("review_round", None)
            meeting.setdefault(key, []).append(review_row)
        if not meeting:
            meeting["r1"] = [
                {
                    "agent": status,
                    "decision": "modify" if final_label != initial_label else "keep",
                    "proposed_label": final_label,
                    "reason": description,
                }
            ]
        conversation = {
            "id": pair_id,
            "round": round_num,
            "initial_label": initial_label,
            "final_label": final_label,
            "description": description,
            "status": status,
            "meeting": meeting,
        }
        final_type = str(decision.get("final_type") or conflict.get("final_type") or "").strip()
        if final_label == "Conflict" and final_type:
            conversation["final_type"] = final_type
        if req_ids:
            conversation["requirements"] = [{"id": req_id} for req_id in req_ids]
        conversations.append(conversation)
    return conversations


# ========
# Defines attach review conversation to conflicts function for this module workflow.
# ========
def attach_review_conversation_to_conflicts(
    conflicts_by_id: Dict[str, Dict[str, Any]],
    conversations: List[Dict[str, Any]],
) -> None:
    conversation_by_id = {
        str(row.get("id") or "").strip(): row
        for row in conversations or []
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }
    for conflict_id, conflict in conflicts_by_id.items():
        conversation = conversation_by_id.get(str(conflict_id).strip())
        if not conversation:
            continue
        conflict["initial_label"] = str(conversation.get("initial_label") or "").strip()
        conflict["final_label"] = str(conversation.get("final_label") or "").strip()
        conflict["description"] = str(conversation.get("description") or "").strip()
        status = str(conversation.get("status") or "").strip()
        if status:
            conflict["status"] = status
        if conversation.get("final_type"):
            conflict["final_type"] = conversation["final_type"]

        meeting_details = conversation.get("meeting")
        if isinstance(meeting_details, dict) and any(meeting_details.values()):
            conflict["meeting"] = meeting_details
        else:
            conflict.pop("meeting", None)
