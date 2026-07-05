import re
from typing import Any, Dict


def trace_topology_edge_key(edge: Dict[str, Any]) -> str:
    return f"{str(edge.get('from') or '').strip()}->{str(edge.get('to') or '').strip()}"


def trace_topology_natural_id_key(value: Any) -> tuple[int, int, int, str]:
    text = str(value or "").strip()
    meeting_match = re.fullmatch(r"R(\d+)-M(\d+)", text, flags=re.IGNORECASE)
    if meeting_match:
        return (5, int(meeting_match.group(1)), int(meeting_match.group(2)), text)
    match = re.fullmatch(r"([A-Za-z]+)-(\d+)(?:-(\d+))?", text)
    if not match:
        return (99, 10**9, 10**9, text)
    group_order = {
        "ST": 0,
        "URL": 1,
        "CR": 2,
        "FB": 3,
        "SM": 4,
        "REQ": 5,
        "FR": 6,
        "NFR": 6,
        "CON": 6,
    }.get(match.group(1).upper(), 98)
    return (
        group_order,
        int(match.group(2) or 0),
        int(match.group(3) or 0),
        text,
    )
