import html
import re
from typing import Any, Dict, List

from .ordering import trace_topology_edge_key


def clean_repeated_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    for sep in ("，", "；", ";", "。"):
        parts = [part.strip() for part in text.split(sep) if part.strip()]
        if len(parts) < 2:
            continue
        cleaned: List[str] = []
        for part in parts:
            if part not in cleaned:
                cleaned.append(part)
        if len(cleaned) != len(parts):
            text = sep.join(cleaned)
            if value and str(value).strip().endswith(sep):
                text += sep
    half = len(text) // 2
    if half > 12 and len(text) % 2 == 0 and text[:half].strip("，；;。 ") == text[half:].strip("，；;。 "):
        text = text[:half].strip("，；;。 ")
    return text.strip()


def html_attr(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def strip_trace_html(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = html.unescape(text)
    return clean_repeated_text(text)


def compact_stakeholder_statement_nodes(
    graph_nodes: List[Dict[str, Any]],
    graph_edges: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for node in graph_nodes:
        if str(node.get("type") or "").strip() != "Stakeholder Statement":
            continue
        label = str(node.get("label") or node.get("title") or "").strip()
        node_id = str(node.get("id") or "").strip()
        if label and node_id:
            groups.setdefault(label, []).append(node)

    duplicate_groups = {
        label: rows
        for label, rows in groups.items()
        if len(rows) > 1
    }
    if not duplicate_groups:
        return graph_nodes, graph_edges

    alias: Dict[str, str] = {}
    compact_nodes: List[Dict[str, Any]] = []
    grouped_ids: set[str] = set()
    for label, rows in duplicate_groups.items():
        primary = dict(rows[0])
        primary_id = str(primary.get("id") or "").strip()
        rows_markup = []
        for row in rows:
            row_id = str(row.get("id") or "").strip()
            if not row_id:
                continue
            alias[row_id] = primary_id
            grouped_ids.add(row_id)
            content = strip_trace_html(row.get("content"))
            rows_markup.append(
                "<tr>"
                f"<td>{html_attr(row_id)}</td>"
                f"<td>{html_attr(content)}</td>"
                "</tr>"
            )
        primary["label"] = label
        primary["title"] = label
        primary["content"] = (
            '<table class="dr-trace-feedback-table dr-trace-user-requirement-table"><thead><tr>'
            "<th>ID</th><th>Statement</th>"
            "</tr></thead><tbody>"
            + "".join(rows_markup)
            + "</tbody></table>"
        )
        primary["content_format"] = "html"
        compact_nodes.append(primary)

    for node in graph_nodes:
        node_id = str(node.get("id") or "").strip()
        if node_id in grouped_ids:
            continue
        compact_nodes.append(node)

    compact_edges: List[Dict[str, Any]] = []
    for edge in graph_edges:
        from_id = alias.get(str(edge.get("from") or "").strip(), str(edge.get("from") or "").strip())
        to_id = alias.get(str(edge.get("to") or "").strip(), str(edge.get("to") or "").strip())
        if not from_id or not to_id or from_id == to_id:
            continue
        next_edge = {**edge, "from": from_id, "to": to_id}
        if next_edge not in compact_edges:
            compact_edges.append(next_edge)
    return compact_nodes, compact_edges


def collect_valid_trace_edges(
    graph_edges: List[Dict[str, Any]],
    node_positions: Dict[str, tuple[int, int, int]],
) -> List[Dict[str, str]]:
    valid_edges: List[Dict[str, str]] = []
    for edge in graph_edges:
        from_id = str(edge.get("from") or "").strip()
        to_id = str(edge.get("to") or "").strip()
        if from_id in node_positions and to_id in node_positions:
            valid_edges.append({
                "from": from_id,
                "to": to_id,
                "relation": str(edge.get("relation") or ""),
                "style": str(edge.get("style") or ""),
            })
    return valid_edges


def validate_rendered_trace_edges(
    valid_edges: List[Dict[str, Any]],
    rendered_edge_keys: set[str],
) -> None:
    required_edge_keys = {trace_topology_edge_key(edge) for edge in valid_edges}
    missing_render_edges = sorted(required_edge_keys - rendered_edge_keys)
    if missing_render_edges:
        raise ValueError(f"trace topology render missing edges: {', '.join(missing_render_edges)}")
