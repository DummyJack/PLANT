# Record helpers for pair-level conflict review.
from typing import Any, Dict, List


def build_pair_review_records(
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

    records: List[Dict[str, Any]] = []
    for pair_id, conflict in conflicts_by_id.items():
        req_ids = [str(r) for r in (conflict.get("requirement_ids") or []) if str(r).strip()]
        decision = decision_by_id.get(pair_id, {})
        final_label = str(decision.get("new_label") or conflict.get("label") or "").strip()
        if final_label not in {"Conflict", "Neutral"}:
            final_label = str(conflict.get("label") or "Neutral").strip() or "Neutral"
        flat_reviews = reviews_by_id.get(pair_id, [])
        meeting_conflict_review: Dict[str, List[Dict[str, Any]]] = {}
        for row in flat_reviews:
            try:
                review_round = int(row.get("review_round") or 1)
            except (TypeError, ValueError):
                review_round = 1
            key = f"r{review_round}"
            review_row = dict(row)
            review_row.pop("review_round", None)
            meeting_conflict_review.setdefault(key, []).append(review_row)
        record = {
            "id": pair_id,
            "round": round_num,
            "initial_label": str(
                (conflict.get("conflict_review") or {}).get("from_label")
                or conflict.get("label")
                or ""
            ).strip(),
            "final_label": final_label,
            "description": str(decision.get("reason") or "").strip(),
            "decided_by": str(decision.get("decided_by") or "").strip(),
            "meeting_conflict_review": meeting_conflict_review,
        }
        for idx, req_id in enumerate(req_ids, 1):
            record[f"req_{idx}"] = req_id
        records.append(record)
    return records
