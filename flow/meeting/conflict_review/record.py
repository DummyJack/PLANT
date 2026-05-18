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
        decision = decision_by_id.get(pair_id)
        if not isinstance(decision, dict):
            raise RuntimeError(f"缺少衝突再審查 decision: {pair_id}")
        final_label = str(decision.get("new_label") or conflict.get("label") or "").strip()
        if final_label not in {"Conflict", "Neutral"}:
            raise RuntimeError(f"衝突再審查 final_label 不合法: {pair_id}")
        initial_label = str(
            (conflict.get("conflict_review") or {}).get("from_label")
            or conflict.get("label")
            or ""
        ).strip()
        if initial_label not in {"Conflict", "Neutral"}:
            raise RuntimeError(f"衝突再審查 initial_label 不合法: {pair_id}")
        description = str(decision.get("reason") or "").strip()
        if not description:
            raise RuntimeError(f"缺少衝突再審查 description: {pair_id}")
        status = str(decision.get("decided_by") or "").strip()
        if status not in {"consensus", "analyst"}:
            raise RuntimeError(f"衝突再審查 status 不合法: {pair_id}")
        flat_reviews = reviews_by_id.get(pair_id, [])
        details: Dict[str, List[Dict[str, Any]]] = {}
        for row in flat_reviews:
            try:
                review_round = int(row.get("review_round") or 1)
            except (TypeError, ValueError):
                review_round = 1
            key = f"r{review_round}"
            review_row = dict(row)
            review_row.pop("review_round", None)
            details.setdefault(key, []).append(review_row)
        record = {
            "id": pair_id,
            "round": round_num,
            "initial_label": initial_label,
            "final_label": final_label,
            "description": description,
            "status": status,
            "details": details,
        }
        initial_type = str(conflict.get("initial_type") or "").strip()
        if initial_label == "Conflict" and initial_type:
            record["initial_type"] = initial_type
        final_type = str(decision.get("final_type") or conflict.get("final_type") or "").strip()
        if final_label == "Conflict" and final_type:
            record["final_type"] = final_type
        for idx, req_id in enumerate(req_ids, 1):
            record[f"req_{idx}"] = req_id
        records.append(record)
    return records


def attach_review_records_to_conflicts(
    conflicts_by_id: Dict[str, Dict[str, Any]],
    records: List[Dict[str, Any]],
) -> None:
    record_by_id = {
        str(row.get("id") or "").strip(): row
        for row in records or []
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }
    for conflict_id, conflict in conflicts_by_id.items():
        record = record_by_id.get(str(conflict_id).strip())
        if not record:
            continue
        meeting_row = {
            "initial_label": str(record.get("initial_label") or "").strip(),
            "final_label": str(record.get("final_label") or "").strip(),
            "description": str(record.get("description") or "").strip(),
            "status": str(record.get("status") or "").strip(),
            "details": record.get("details") or {},
        }
        if record.get("initial_type"):
            meeting_row["initial_type"] = record["initial_type"]
        if record.get("final_type"):
            meeting_row["final_type"] = record["final_type"]
        conflict["meeting"] = [meeting_row]
