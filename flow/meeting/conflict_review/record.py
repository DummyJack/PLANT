# Record helpers for conflict review logs.
from typing import Any, Dict, List
def build_pair_review_records(
    conflicts_by_id: Dict[str, Dict[str, Any]],
    decisions: List[Dict[str, Any]],
    extracted_pair_reviews: List[Dict[str, Any]],
    *,
    round_num: int,
    topic_id: str,
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

    records: List[Dict[str, Any]] = []
    for pair_id, conflict in conflicts_by_id.items():
        req_ids = [str(r) for r in (conflict.get("requirement_ids") or []) if str(r).strip()]
        decision = decision_by_id.get(pair_id, {})
        final_label = str(decision.get("new_label") or conflict.get("label") or "").strip()
        if final_label not in {"Conflict", "Neutral"}:
            final_label = str(conflict.get("label") or "Neutral").strip() or "Neutral"
        meeting_conflict_review = reviews_by_id.get(pair_id, [])
        confidences = [
            str(row.get("confidence") or "").strip().lower()
            for row in meeting_conflict_review
            if str(row.get("confidence") or "").strip().lower() in {"high", "medium", "low"}
        ]
        confidence = "medium"
        if confidences and all(c == "high" for c in confidences):
            confidence = "high"
        elif "low" in confidences:
            confidence = "low"
        records.append(
            {
                "pair_id": pair_id,
                "round": round_num,
                "topic_id": topic_id,
                "req_a": req_ids[0] if len(req_ids) >= 1 else "",
                "req_b": req_ids[1] if len(req_ids) >= 2 else "",
                "requirement_ids": req_ids,
                "initial_label": str(
                    (conflict.get("pre_meeting_review") or {}).get("from_label")
                    or conflict.get("label")
                    or ""
                ).strip(),
                "final_label": final_label,
                "confidence": confidence,
                "rationale": str(decision.get("reason") or "").strip(),
                "decided_by": str(decision.get("decided_by") or "").strip(),
                "meeting_conflict_review": meeting_conflict_review,
            }
        )
    return records
