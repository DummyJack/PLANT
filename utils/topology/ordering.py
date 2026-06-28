import re
from typing import Any, Dict, List


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




def order_trace_topology_groups(
    groups: Dict[str, List[Dict[str, Any]]],
    graph_nodes: List[Dict[str, Any]],
    graph_edges: List[Dict[str, Any]],
    column_order: List[str],
) -> None:
    node_index = {
        str(node.get("id") or "").strip(): index
        for index, node in enumerate(graph_nodes or [])
        if isinstance(node, dict) and str(node.get("id") or "").strip()
    }

    def node_order(node: Dict[str, Any]) -> tuple[int, int, int, str, int]:
        node_id = str(node.get("id") or "").strip()
        natural = trace_topology_natural_id_key(node_id)
        return (*natural, node_index.get(node_id, 10**9))

    for column in column_order or list(groups.keys()):
        rows = groups.get(column)
        if isinstance(rows, list):
            rows.sort(key=node_order)
