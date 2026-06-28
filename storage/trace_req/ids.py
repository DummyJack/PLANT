import re
from typing import Any, Dict, List


def trace_req_ids(value: Any) -> List[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    return [str(item).strip() for item in values if str(item).strip()]


def trace_req_first_id(value: Any) -> str:
    ids = trace_req_ids(value)
    return ids[0] if ids else ""


def trace_req_target_id(value: Any, req_to_srs: Dict[str, str]) -> str:
    for item in trace_req_ids(value):
        if item.startswith(("FR-", "NFR-", "CON-")):
            return item
        if item in req_to_srs:
            return req_to_srs[item]
    return ""


def trace_req_trace_id(target_requirement_id: str) -> str:
    target = str(target_requirement_id or "").strip()
    return f"TR-{target}" if target else ""


def trace_req_next_id(rows: List[Dict[str, Any]]) -> str:
    max_num = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        match = re.fullmatch(r"TE-(\d+)", str(row.get("event_id") or "").strip())
        if match:
            max_num = max(max_num, int(match.group(1)))
    return f"TE-{max_num + 1}"


def meeting_order_key(meeting_id: str) -> tuple[int, int, str]:
    clean_id = str(meeting_id or "").strip()
    match = re.fullmatch(r"R(\d+)-M(\d+)", clean_id, flags=re.IGNORECASE)
    if match:
        return (int(match.group(1)), int(match.group(2)), clean_id)
    numbers = [int(value) for value in re.findall(r"\d+", clean_id)]
    padded = numbers[:2] + [0] * max(0, 2 - len(numbers))
    return (
        padded[0] if padded else 10**9,
        padded[1] if len(padded) > 1 else 10**9,
        clean_id,
    )


def is_meeting_id(value: str) -> bool:
    return bool(re.fullmatch(r"R\d+-M\d+", str(value or "").strip(), flags=re.IGNORECASE))
