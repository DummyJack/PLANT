# Conflict state helpers: normalize conflict.pairs/multiple for runtime use.
from typing import Any, Dict, List


def requirement_ids(row: Dict[str, Any]) -> List[str]:
    ids = [
        str(item).strip()
        for item in (row.get("requirement_ids") or row.get("reqs") or [])
        if str(item).strip()
    ]
    idx = 1
    while True:
        value = str(row.get(f"req_{idx}") or "").strip()
        if not value:
            break
        if value not in ids:
            ids.append(value)
        idx += 1
    for key in ("req_a", "req_b"):
        value = str(row.get(key) or "").strip()
        if value and value not in ids:
            ids.append(value)
    return ids


def is_multiple_conflict(row: Dict[str, Any]) -> bool:
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
    artifact.pop("conflicts", None)
    return artifact


def set_pair_conflicts(artifact: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    state = conflict_state(artifact)
    state["pairs"] = [dict(row) for row in rows if isinstance(row, dict)]
    artifact["conflict"] = state
    artifact.pop("conflicts", None)
    return artifact


def set_multiple_conflicts(artifact: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    state = conflict_state(artifact)
    state["multiple"] = [dict(row) for row in rows if isinstance(row, dict)]
    artifact["conflict"] = state
    artifact.pop("conflicts", None)
    return artifact


def set_conflict_entries(artifact: Dict[str, Any], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    state = split_conflict_rows([dict(row) for row in rows if isinstance(row, dict)])
    artifact["conflict"] = state
    artifact.pop("conflicts", None)
    return artifact


def conflict_entries_count(artifact: Dict[str, Any]) -> int:
    return len(all_conflict_rows(artifact))
