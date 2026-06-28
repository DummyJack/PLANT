from typing import Any, Dict, List

from .ids import is_meeting_id, meeting_order_key
from .indexes import TraceReqIndexes
from .schema import enrich_trace_req_row


def normalize_trace_req_rows(
    input_rows: List[Dict[str, Any]],
    indexes: TraceReqIndexes,
) -> List[Dict[str, Any]]:
    target_entry_sources: set[tuple[str, str]] = set()
    target_meeting_next: Dict[tuple[str, str], List[str]] = {}
    for row in input_rows:
        target_id = str(row.get("target_requirement_id") or "").strip()
        from_id = str(row.get("from") or "").strip()
        to_id = str(row.get("to") or "").strip()
        if not target_id or not from_id or not to_id:
            continue
        if indexes.entry_meeting_id and to_id == indexes.entry_meeting_id:
            target_entry_sources.add((target_id, from_id))
        if is_meeting_id(from_id) and is_meeting_id(to_id):
            if meeting_order_key(from_id) < meeting_order_key(to_id):
                target_meeting_next.setdefault((target_id, from_id), []).append(to_id)

    cleaned: List[Dict[str, Any]] = []
    dropped_signatures: set[tuple[str, str, str, str, str]] = set()
    for row in input_rows:
        target_id = str(row.get("target_requirement_id") or "").strip()
        from_id = str(row.get("from") or "").strip()
        to_id = str(row.get("to") or "").strip()
        edge_label = str(row.get("edge_label") or "").strip()
        if not target_id or not from_id or not to_id:
            continue
        if from_id == to_id:
            continue
        if is_meeting_id(from_id) and is_meeting_id(to_id):
            if meeting_order_key(from_id) >= meeting_order_key(to_id):
                continue
        if (
            indexes.entry_meeting_id
            and indexes.formalization_meeting_id
            and indexes.entry_meeting_id != indexes.formalization_meeting_id
            and target_id not in indexes.conflict_target_ids
            and to_id == indexes.entry_meeting_id
            and from_id.startswith("URL-")
        ):
            continue
        if (
            indexes.entry_meeting_id
            and indexes.formalization_meeting_id
            and indexes.entry_meeting_id != indexes.formalization_meeting_id
            and target_id not in indexes.conflict_target_ids
            and from_id == indexes.entry_meeting_id
            and to_id == indexes.formalization_meeting_id
        ):
            continue
        if (
            indexes.entry_meeting_id
            and indexes.formalization_meeting_id
            and target_id in indexes.conflict_target_ids
            and to_id == indexes.formalization_meeting_id
            and from_id.startswith("URL-")
            and edge_label == "正式化"
            and (target_id, from_id) in target_entry_sources
        ):
            continue
        if (
            is_meeting_id(from_id)
            and to_id == target_id
            and target_meeting_next.get((target_id, from_id))
        ):
            continue
        signature = (
            target_id,
            from_id,
            to_id,
            edge_label,
            str(row.get("role") or "").strip(),
        )
        if signature in dropped_signatures:
            continue
        dropped_signatures.add(signature)
        cleaned.append(row)

    for index, row in enumerate(cleaned, 1):
        row["event_id"] = f"TE-{index}"
        enrich_trace_req_row(row, indexes.req_to_srs)
    return cleaned
