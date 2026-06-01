# Conflict state helpers: normalize conflict.pairs/multiple for runtime use.
from typing import Any, Dict, List


def requirement_ids(row: Dict[str, Any]) -> List[str]:
    ids = [
        str(item).strip()
        for item in (row.get("requirement_ids") or [])
        if str(item).strip()
    ]
    if ids:
        return ids
    for req in row.get("requirements") or []:
        if not isinstance(req, dict):
            continue
        req_id = str(req.get("id") or "").strip()
        if req_id:
            ids.append(req_id)
    idx = 1
    while True:
        key = f"req_{idx}"
        if key not in row:
            break
        req_id = str(row.get(key) or "").strip()
        if req_id:
            ids.append(req_id)
        idx += 1
    return list(dict.fromkeys(ids))


def is_multiple_conflict(row: Dict[str, Any]) -> bool:
    row_id = str(row.get("id") or "").strip()
    if row_id.startswith("MULTIPLE-"):
        return True
    conflict_scope = str(
        row.get("scope")
        or row.get("kind")
        or row.get("conflict_scope")
        or ""
    ).strip().lower()
    if conflict_scope in {"group", "multiple", "set", "group_conflict"}:
        return True
    if row.get("related_pairs"):
        return True
    return len(requirement_ids(row)) >= 3


def conflict_state(artifact: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    state = artifact.get("conflict")
    if isinstance(state, dict):
        return {
            "pairs": [row for row in (state.get("pairs") or []) if isinstance(row, dict)],
            "multiple": [row for row in (state.get("multiple") or []) if isinstance(row, dict)],
        }
    return {"pairs": [], "multiple": []}


def split_conflict_rows(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    pairs: List[Dict[str, Any]] = []
    multiple: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if is_multiple_conflict(item):
            multiple.append(item)
        else:
            pairs.append(item)
    return {"pairs": pairs, "multiple": multiple}


def all_conflict_rows(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    state = conflict_state(artifact)
    return list(state.get("pairs") or []) + list(state.get("multiple") or [])


def normalize_conflict_state(artifact: Dict[str, Any]) -> Dict[str, Any]:
    artifact["conflict"] = conflict_state(artifact)
    return artifact


def set_pair_conflicts(artifact: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    state = conflict_state(artifact)
    existing_by_signature = {
        tuple(sorted(requirement_ids(row))): row
        for row in state.get("pairs", [])
        if isinstance(row, dict) and requirement_ids(row)
    }
    preserved_keys = (
        "meeting",
        "initial_label",
        "initial_type",
        "initial_reason",
        "final_label",
        "final_type",
        "description",
        "status",
    )
    next_rows: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        current_label = str(item.get("label") or item.get("initial_label") or "").strip()
        existing = existing_by_signature.get(tuple(sorted(requirement_ids(item)))) or {}
        for key in preserved_keys:
            if current_label in {"Conflict", "Neutral"} and key in {"final_label", "final_type", "description", "status"}:
                continue
            if key not in item and existing.get(key) not in (None, "", [], {}):
                item[key] = existing[key]
        next_rows.append(item)
    state["pairs"] = next_rows
    artifact["conflict"] = state
    return artifact


def set_multiple_conflicts(artifact: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    state = conflict_state(artifact)
    existing_by_signature = {
        tuple(sorted(requirement_ids(row))): row
        for row in state.get("multiple", [])
        if isinstance(row, dict) and requirement_ids(row)
    }
    preserved_keys = (
        "meeting",
        "initial_label",
        "initial_type",
        "initial_reason",
        "final_label",
        "final_type",
        "description",
        "status",
    )
    next_rows: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        current_label = str(item.get("label") or item.get("initial_label") or "").strip()
        existing = existing_by_signature.get(tuple(sorted(requirement_ids(item)))) or {}
        for key in preserved_keys:
            if current_label in {"Conflict", "Neutral"} and key in {"final_label", "final_type", "description", "status"}:
                continue
            if key not in item and existing.get(key) not in (None, "", [], {}):
                item[key] = existing[key]
        next_rows.append(item)
    state["multiple"] = next_rows
    artifact["conflict"] = state
    return artifact


def set_conflict_entries(artifact: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    state = split_conflict_rows([dict(row) for row in rows if isinstance(row, dict)])
    artifact["conflict"] = state
    return artifact


def conflict_entries_count(artifact: Dict[str, Any]) -> int:
    return len(all_conflict_rows(artifact))
