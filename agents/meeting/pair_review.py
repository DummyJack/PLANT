from typing import Any, Dict, Optional


VALID_PAIR_LABELS = {"Conflict", "Neutral"}


def normalize_pair_review_record(
    review: Dict[str, Any],
    *,
    pair_id_set: set[str],
    current_labels_by_id: Optional[Dict[str, str]] = None,
    require_valid_label: bool = False,
) -> Optional[Dict[str, Any]]:
    if not isinstance(review, dict):
        return None
    pair_id = str(review.get("id") or "").strip()
    if not pair_id or pair_id not in pair_id_set:
        return None
    proposed_label = str(review.get("proposed_label") or "").strip()
    if proposed_label not in VALID_PAIR_LABELS:
        if require_valid_label:
            return None
        proposed_label = ""
    current_label = ""
    if current_labels_by_id:
        current_label = str(current_labels_by_id.get(pair_id) or "").strip()
    decision = ""
    if proposed_label and current_label in VALID_PAIR_LABELS:
        decision = "keep" if proposed_label == current_label else "modify"
    return {
        "id": pair_id,
        "decision": decision,
        "proposed_label": proposed_label,
        "reason": str(review.get("reason") or "").strip(),
    }
