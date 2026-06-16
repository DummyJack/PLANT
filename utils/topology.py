# Renders trace topology diagrams for Design Rationale documents.
import base64
import html
import re
from typing import Any, Dict, List, Optional, Tuple


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


def render_trace_topology_assets() -> str:
    return """
<style>
.dr-trace-topology {
  margin: 18px 0 22px;
  padding: 0;
}
.dr-trace-topology__graph {
  width: 100%;
  overflow-x: hidden;
}
.dr-trace-topology__svg {
  display: block;
  width: 100%;
  max-width: 100%;
  height: auto;
}
.dr-trace-topology--fallback {
  border: 1px solid #dfe5ef;
  background: #fbfcfe;
  padding: 12px 14px;
}
.dr-trace-topology--fallback ul {
  margin: 8px 0 0;
  padding-left: 1.25rem;
}
.dr-trace-fallback__warning {
  margin: 6px 0 0;
  color: #8a4b00;
}
.dr-trace-edge {
  fill: none;
  stroke: #c8d2e2;
  stroke-width: 1.5;
}
.dr-trace-edge--dashed {
  stroke-dasharray: 5 5;
}
.dr-trace-edge-label {
  fill: #66758f;
  font-size: 12px;
  font-weight: 650;
  dominant-baseline: middle;
  pointer-events: none;
}
.dr-trace-edge-label-bg {
  fill: #fbfcfe;
  stroke: #dfe5ef;
  stroke-width: 1;
  pointer-events: none;
}
.dr-trace-section-label {
  fill: #66758f;
  font-size: 13px;
  font-weight: 700;
  pointer-events: none;
}
.dr-trace-support-box {
  fill: #fbfcfe;
  stroke: #dfe5ef;
  stroke-width: 1.4;
}
.dr-trace-node rect {
  fill: #fff;
  stroke: #cfd7e4;
  stroke-width: 1.4;
  filter: drop-shadow(0 1px 2px rgba(15, 23, 42, 0.08));
}
.dr-trace-node text {
  fill: #243044;
  font-size: 14px;
  font-weight: 650;
  pointer-events: none;
}
.dr-trace-node:not(.dr-trace-node--target):hover rect,
.dr-trace-node:not(.dr-trace-node--target):focus rect {
  fill: #f1f4ff;
  stroke: #526dff;
}
.dr-trace-node:focus {
  outline: none;
}
.dr-trace-node {
  cursor: pointer;
}
.dr-trace-node--target rect {
  fill: #243044;
  stroke: #243044;
}
.dr-trace-node--target text {
  fill: #fff;
}
.dr-trace-node--target {
  cursor: default;
  pointer-events: none;
}
.dr-trace-modal[hidden] {
  display: none;
}
.dr-trace-modal {
  position: fixed;
  inset: 0;
  z-index: 200;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(15, 23, 42, 0.36);
}
.dr-trace-modal__panel {
  width: min(760px, 100%);
  max-height: min(720px, calc(100vh - 48px));
  overflow: auto;
  border-radius: 12px;
  border: 1px solid #d8dee8;
  background: #fff;
  box-shadow: 0 20px 60px rgba(15, 23, 42, 0.24);
}
.dr-trace-modal__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 20px 10px;
  border-bottom: 1px solid #e5e9f0;
}
.dr-trace-modal--content-only .dr-trace-modal__header {
  justify-content: flex-end;
  padding: 10px 12px 0;
  border-bottom: 0;
}
.dr-trace-modal--content-only .dr-trace-modal__title {
  display: none;
}
.dr-trace-modal__title {
  margin: 0;
  font-size: 1.1rem;
}
.dr-trace-modal__close {
  border: 0;
  background: transparent;
  color: #66758f;
  cursor: pointer;
  font-size: 1.6rem;
  line-height: 1;
}
.dr-trace-modal__body {
  padding: 16px 20px 20px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.dr-trace-modal__body--html {
  white-space: normal;
}
.dr-trace-modal__body h1,
.dr-trace-modal__body h2,
.dr-trace-modal__body h3,
.dr-trace-modal__body h4 {
  margin: 0.75rem 0 0.4rem;
  color: #172033;
  line-height: 1.3;
}
.dr-trace-modal__body h1 {
  font-size: 1.25rem;
}
.dr-trace-modal__body h2 {
  font-size: 1.12rem;
}
.dr-trace-modal__body h3 {
  font-size: 1rem;
}
.dr-trace-modal__body p {
  margin: 0.45rem 0;
  line-height: 1.65;
}
.dr-trace-modal__body ul,
.dr-trace-modal__body ol {
  margin: 0.45rem 0;
  padding-left: 1.4rem;
}
.dr-trace-modal__body li {
  margin: 0.25rem 0;
  line-height: 1.6;
}
.dr-trace-modal__body strong {
  font-weight: 700;
}
.dr-trace-modal__body table {
  width: 100%;
  border-collapse: collapse;
  white-space: normal;
  table-layout: fixed;
}
.dr-trace-modal__body img {
  display: block;
  max-width: 100%;
  height: auto;
  margin: 4px auto 0;
  border: 1px solid #d8dee8;
  border-radius: 8px;
  background: #fff;
}
.dr-trace-modal__body th,
.dr-trace-modal__body td {
  padding: 8px 10px;
  border: 1px solid #d8dee8;
  text-align: left;
  vertical-align: top;
}
.dr-trace-modal__body th {
  background: #f5f7fb;
  color: #243044;
  font-weight: 700;
}
.dr-trace-feedback-table th:nth-child(1),
.dr-trace-feedback-table td:nth-child(1) {
  width: 76px;
  white-space: nowrap;
}
.dr-trace-feedback-table th:nth-child(2),
.dr-trace-feedback-table td:nth-child(2) {
  width: 132px;
  min-width: 132px;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.dr-trace-feedback-table th:nth-child(3),
.dr-trace-feedback-table td:nth-child(3) {
  width: 120px;
  min-width: 120px;
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.dr-trace-feedback-table th:nth-child(4),
.dr-trace-feedback-table td:nth-child(4) {
  overflow-wrap: anywhere;
  word-break: break-word;
}
.dr-trace-user-requirement-table th:nth-child(2),
.dr-trace-user-requirement-table td:nth-child(2),
.dr-trace-feedback-group-table th:nth-child(3),
.dr-trace-feedback-group-table td:nth-child(3) {
  width: auto;
}
.dr-trace-user-requirement-table th:nth-child(3),
.dr-trace-user-requirement-table td:nth-child(3),
.dr-trace-feedback-group-table th:nth-child(4),
.dr-trace-feedback-group-table td:nth-child(4) {
  width: 160px;
  min-width: 160px;
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.dr-trace-source-chip {
  display: inline-block;
  max-width: 100%;
  margin: 0 4px 4px 0;
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.dr-trace-card {
  padding: 12px 14px;
  border: 1px solid #d8dee8;
  border-radius: 8px;
  background: #fbfcfe;
}
.dr-trace-card__main {
  color: #243044;
  font-size: 0.98rem;
  line-height: 1.55;
}
.dr-trace-card__meta {
  margin-top: 8px;
  color: #66758f;
  font-size: 0.9rem;
  font-weight: 650;
}
.dr-trace-card--stack {
  display: grid;
  gap: 10px;
}
.dr-trace-card__item + .dr-trace-card__item {
  padding-top: 10px;
  border-top: 1px solid #e5e9f0;
}
.dr-trace-card__label {
  margin-bottom: 4px;
  color: #66758f;
  font-size: 0.84rem;
  font-weight: 700;
}
.dr-trace-card__value {
  color: #243044;
  font-size: 0.96rem;
  line-height: 1.5;
}
.dr-trace-model-description {
  margin: 8px 0 0;
  color: #243044;
  font-size: 0.98rem;
  line-height: 1.65;
}
.dr-trace-model-description__item {
  margin: 0 0 8px;
}
.dr-trace-model-description__item:last-child {
  margin-bottom: 0;
}
.dr-trace-report {
  margin: 0;
  padding: 12px 14px;
  overflow-x: auto;
  border: 1px solid #d8dee8;
  border-radius: 8px;
  background: #fbfcfe;
  color: #243044;
  font: 0.92rem/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  white-space: pre-wrap;
}
@media (max-width: 760px) {
  .dr-trace-topology {
    padding: 12px;
  }
}
</style>
<div class="dr-trace-modal" hidden aria-hidden="true">
  <div class="dr-trace-modal__panel" role="dialog" aria-modal="true" aria-labelledby="dr-trace-modal-title">
    <div class="dr-trace-modal__header">
      <div>
        <h3 class="dr-trace-modal__title" id="dr-trace-modal-title"></h3>
      </div>
      <button class="dr-trace-modal__close" type="button" aria-label="關閉">×</button>
    </div>
    <div class="dr-trace-modal__body"></div>
  </div>
</div>
<script>
(() => {
  const modal = document.querySelector('.dr-trace-modal');
  if (!modal || modal.dataset.ready === 'true') return;
  modal.dataset.ready = 'true';
  const title = modal.querySelector('.dr-trace-modal__title');
  const body = modal.querySelector('.dr-trace-modal__body');
  const close = () => {
    modal.hidden = true;
    modal.setAttribute('aria-hidden', 'true');
    modal.classList.remove('dr-trace-modal--content-only');
  };
  const open = (button) => {
    const contentOnly = ['User Requirement', 'Stakeholder Statement'].includes(button.dataset.traceType || '');
    modal.classList.toggle('dr-trace-modal--content-only', contentOnly);
    title.textContent = contentOnly ? '' : (button.dataset.traceTitle || button.dataset.traceId || '');
    let content = button.dataset.traceContent || '';
    if (button.dataset.traceContentB64) {
      try {
        const bytes = Uint8Array.from(atob(button.dataset.traceContentB64), (char) => char.charCodeAt(0));
        content = new TextDecoder().decode(bytes);
      } catch (error) {
        content = button.dataset.traceContent || '';
      }
    }
    if ((button.dataset.traceFormat || '') === 'html') {
      body.classList.add('dr-trace-modal__body--html');
      body.innerHTML = content;
    } else {
      body.classList.remove('dr-trace-modal__body--html');
      body.textContent = content;
    }
    modal.hidden = false;
    modal.setAttribute('aria-hidden', 'false');
  };
  document.addEventListener('click', (event) => {
    const button = event.target.closest('.dr-trace-node');
    if (button) {
      event.preventDefault();
      if ((button.dataset.traceType || '') === 'Requirement') return;
      open(button);
      return;
    }
    if (event.target === modal || event.target.closest('.dr-trace-modal__close')) {
      close();
    }
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !modal.hidden) close();
  });
})();
</script>
""".strip()


def trace_topology_label_lines(label: str, max_chars: int = 10) -> List[str]:
    text = re.sub(r"\s+", " ", str(label or "")).strip()
    id_match = re.match(r"^((?:ST|URL|CR|FB|SM|REQ|FR|NFR|CON)-\d+(?:-\d+)?|R\d+-M\d+)[:：]?\s+(.+)$", text)
    if id_match:
        head = id_match.group(1)
        tail = id_match.group(2).strip()
        if len(tail) > max_chars:
            tail = tail[: max_chars - 1].rstrip() + "…"
        return [head, tail] if tail else [head]
    if len(text) <= max_chars:
        return [text]
    first = text[:max_chars].rstrip()
    boundary = max(first.rfind(" "), first.rfind("、"), first.rfind("，"))
    if boundary >= 4:
        first = first[:boundary].rstrip()
    second = text[len(first):].strip()
    if len(second) > max_chars:
        second = second[: max_chars - 1].rstrip() + "…"
    return [first, second] if second else [first]


def trace_topology_svg_node(
    *,
    node_id: str,
    label: str,
    node_type: str,
    title: str,
    content: str,
    x: int,
    y: int,
    width: int,
    content_format: str = "text",
    target: bool = False,
) -> str:
    classes = "dr-trace-node dr-trace-node--target" if target else "dr-trace-node"
    raw_label = clean_repeated_text(label or node_id)
    label_lines = trace_topology_label_lines(raw_label)
    if target:
        text_markup = (
            f'<text x="{width / 2:.1f}" y="22" text-anchor="middle" '
            f'dominant-baseline="middle">{html_attr(label_lines[0])}</text>'
        )
    elif len(label_lines) == 1:
        text_markup = f'<text x="{width / 2:.1f}" y="23" text-anchor="middle">{html_attr(label_lines[0])}</text>'
    else:
        text_markup = (
            f'<text x="{width / 2:.1f}" y="16" text-anchor="middle">'
            f'<tspan x="{width / 2:.1f}" dy="0">{html_attr(label_lines[0])}</tspan>'
            f'<tspan x="{width / 2:.1f}" dy="15">{html_attr(label_lines[1])}</tspan>'
            '</text>'
        )
    content_b64 = base64.b64encode(str(content or "").encode("utf-8")).decode("ascii")
    interaction_attrs = "" if target else (
        'tabindex="0" role="button" '
        f'data-trace-id="{html_attr(node_id)}" '
        f'data-trace-type="{html_attr(node_type)}" '
        f'data-trace-title="{html_attr(title or node_id)}" '
        f'data-trace-content-b64="{html_attr(content_b64)}" '
        f'data-trace-format="{html_attr(content_format)}"'
    )
    return (
        f'<g class="{classes}" transform="translate({x},{y})" {interaction_attrs}>'
        f'<rect width="{width}" height="44" rx="8"></rect>'
        f'{text_markup}'
        '</g>'
    )


def trace_topology_edge_key(edge: Dict[str, Any]) -> str:
    return f"{str(edge.get('from') or '').strip()}->{str(edge.get('to') or '').strip()}"


def strip_trace_html(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = html.unescape(text)
    return clean_repeated_text(text)


def trace_source_text(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return "、".join(
            strip_trace_html(item)
            for item in value
            if strip_trace_html(item)
        )
    return strip_trace_html(value)


def user_requirement_content_text(node: Dict[str, Any]) -> str:
    node_id = str(node.get("id") or "").strip()
    text = strip_trace_html(node.get("content")) or strip_trace_html(node.get("label"))
    if not text:
        return ""
    if node_id:
        text = re.sub(
            rf"^\s*{re.escape(node_id)}\s*[:：]\s*",
            "",
            text,
            count=1,
        )
    text = re.sub(r"\s*利害關係人\s*[:：]\s*.+?\s+來源\s*[:：]\s*.+$", "", text)
    text = re.sub(r"\s*來源\s*[:：]\s*.+$", "", text)
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


def compact_user_requirement_nodes(
    graph_nodes: List[Dict[str, Any]],
    graph_edges: List[Dict[str, Any]],
    *,
    target_id: str,
    threshold: int = 3,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    conflict_ids = {
        str(node.get("id") or "").strip()
        for node in graph_nodes
        if str(node.get("type") or "").strip() == "Conflict"
        and str(node.get("id") or "").strip()
    }
    conflict_url_ids = {
        str(edge.get("from") or "").strip()
        for edge in graph_edges
        if str(edge.get("to") or "").strip() in conflict_ids
        and str(edge.get("from") or "").strip().startswith("URL-")
    }
    conflict_url_ids.update(
        str(edge.get("to") or "").strip()
        for edge in graph_edges
        if str(edge.get("from") or "").strip() in conflict_ids
        and str(edge.get("to") or "").strip().startswith("URL-")
    )
    url_nodes = [
        node for node in graph_nodes
        if str(node.get("type") or "").strip() == "User Requirement"
        and str(node.get("id") or "").strip()
        and str(node.get("id") or "").strip() not in conflict_url_ids
    ]
    if len(url_nodes) <= threshold:
        return graph_nodes, graph_edges

    url_ids = {str(node.get("id") or "").strip() for node in url_nodes}
    group_id = f"URL-GROUP-{re.sub(r'[^A-Za-z0-9_-]+', '-', target_id).strip('-') or 'REQ'}"
    rows = []
    for node in url_nodes:
        node_id = str(node.get("id") or "").strip()
        content = user_requirement_content_text(node)
        source = trace_source_text(
            node.get("source")
            or node.get("source_id")
            or node.get("related_sources")
            or node.get("related_statement_ids")
        )
        rows.append(
            "<tr>"
            f"<td>{html_attr(node_id)}</td>"
            f"<td>{html_attr(content)}</td>"
            f"<td>{html_attr(source)}</td>"
            "</tr>"
        )
    group_content = (
        '<table class="dr-trace-feedback-table dr-trace-user-requirement-table"><thead><tr>'
        "<th>ID</th><th>Requirement</th><th>Source</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )
    group_node = {
        "id": group_id,
        "type": "User Requirement Group",
        "label": f"URL({len(url_nodes)} 筆)",
        "title": f"User Requirement（{len(url_nodes)} 筆）",
        "content": group_content,
        "content_format": "html",
        "column": "User Requirement",
    }
    compact_nodes = [
        node for node in graph_nodes
        if str(node.get("id") or "").strip() not in url_ids
    ] + [group_node]

    compact_edges: List[Dict[str, Any]] = []
    for edge in graph_edges:
        from_id = str(edge.get("from") or "").strip()
        to_id = str(edge.get("to") or "").strip()
        if not from_id or not to_id:
            continue
        next_edge = dict(edge)
        if from_id in url_ids:
            next_edge["from"] = group_id
        if to_id in url_ids:
            next_edge["to"] = group_id
        if next_edge["from"] == next_edge["to"]:
            continue
        if next_edge not in compact_edges:
            compact_edges.append(next_edge)
    return compact_nodes, compact_edges


def order_trace_topology_groups(
    groups: Dict[str, List[Dict[str, Any]]],
    graph_nodes: List[Dict[str, Any]],
    graph_edges: List[Dict[str, Any]],
    column_order: List[str],
) -> None:
    order_trace_topology_groups(groups, graph_nodes, graph_edges, column_order)


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


def render_trace_links_fallback(requirement: Dict[str, Any], error: Optional[Exception] = None) -> str:
    graph = requirement.get("trace_graph") if isinstance(requirement.get("trace_graph"), dict) else {}
    nodes = {
        str(node.get("id") or "").strip(): str(node.get("label") or node.get("id") or "").strip()
        for node in (graph.get("all_nodes") or graph.get("nodes") or [])
        if isinstance(node, dict) and str(node.get("id") or "").strip()
    }
    rows: List[str] = []
    for edge in graph.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        from_id = str(edge.get("from") or "").strip()
        to_id = str(edge.get("to") or "").strip()
        if not from_id or not to_id:
            continue
        label = str(edge.get("relation") or "").strip()
        label_text = f" ({label})" if label else ""
        rows.append(
            "<li>"
            f"<code>{html_attr(from_id)}</code> → <code>{html_attr(to_id)}</code>{html_attr(label_text)}"
            "</li>"
        )
        nodes.setdefault(from_id, from_id)
        nodes.setdefault(to_id, to_id)
    error_markup = ""
    if error:
        error_markup = f'<p class="dr-trace-fallback__warning">Topology render fallback: {html_attr(error)}</p>'
    if not rows:
        target_id = str(requirement.get("srs_id") or requirement.get("id") or "").strip()
        rows.append(f"<li><code>{html_attr(target_id)}</code></li>")
    return (
        '<div class="dr-trace-topology dr-trace-topology--fallback" data-layout-quality="fallback">'
        "<p><strong>Trace Links</strong></p>"
        f"{error_markup}"
        "<ul>"
        + "".join(rows)
        + "</ul></div>"
    )


def trace_topology_rects_overlap(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float], padding: float = 0) -> bool:
    return not (
        a[2] + padding <= b[0]
        or b[2] + padding <= a[0]
        or a[3] + padding <= b[1]
        or b[3] + padding <= a[1]
    )


def render_trace_topology(requirement: Dict[str, Any]) -> str:
    graph = requirement.get("trace_graph") if isinstance(requirement.get("trace_graph"), dict) else {}
    graph_nodes = [node for node in (graph.get("nodes") or []) if isinstance(node, dict) and str(node.get("id") or "").strip()]
    graph_edges = [edge for edge in (graph.get("edges") or []) if isinstance(edge, dict)]
    if not graph_nodes:
        return ""

    target_id = str(requirement.get("srs_id") or requirement.get("id") or "").strip()
    graph_nodes, graph_edges = compact_stakeholder_statement_nodes(
        graph_nodes,
        graph_edges,
    )
    marker_id = f"dr-trace-arrow-{re.sub(r'[^A-Za-z0-9_-]+', '-', target_id).strip('-').lower() or 'target'}"
    column_order = ["Source", "User Requirement", "Evidence", "Analysis", "Meeting", "Requirement", "Background"]
    groups: Dict[str, List[Dict[str, str]]] = {column: [] for column in column_order}
    main_conflict_ids = {
        str(edge.get("to") or "").strip()
        for edge in graph_edges
        if str(edge.get("relation") or "").strip() == "衝突"
        and str(edge.get("style") or "").strip() != "dashed"
    }
    main_conflict_ids.update({
        str(edge.get("from") or "").strip()
        for edge in graph_edges
        if str(edge.get("relation") or "").strip() == "解決"
        and str(edge.get("style") or "").strip() != "dashed"
    })

    def visual_trace_column(node: Dict[str, Any]) -> str:
        node_type = str(node.get("type") or "").strip()
        column = str(node.get("column") or "").strip()
        if column == "Background":
            return "Background"
        node_id = str(node.get("id") or "").strip()
        if node_type == "Conflict" and node_id in main_conflict_ids:
            return "Analysis"
        if node_type in {"Conflict", "Feedback", "Feedback Group", "System Model"}:
            return "Evidence"
        return column if column in groups else "Analysis"

    for node in graph_nodes:
        column = visual_trace_column(node)
        groups[column].append(node)

    node_index = {
        str(node.get("id") or "").strip(): index
        for index, node in enumerate(graph_nodes)
        if str(node.get("id") or "").strip()
    }
    incoming_by_id: Dict[str, List[str]] = {}
    for edge in graph_edges:
        from_id = str(edge.get("from") or "").strip() if isinstance(edge, dict) else ""
        to_id = str(edge.get("to") or "").strip() if isinstance(edge, dict) else ""
        if from_id and to_id:
            incoming_by_id.setdefault(to_id, []).append(from_id)

    def node_rank(node: Dict[str, Any], order_map: Dict[str, float]) -> tuple[float, int, int]:
        node_id = str(node.get("id") or "").strip()
        incoming = incoming_by_id.get(node_id) or []
        anchors = [order_map[source_id] for source_id in incoming if source_id in order_map]
        anchor = sum(anchors) / len(anchors) if anchors else float(node_index.get(node_id, 10**9))
        type_rank = 0
        visual_column = visual_trace_column(node)
        node_type = str(node.get("type") or "").strip()
        if visual_column == "Evidence":
            type_rank = {
                "System Model": 0,
                "Feedback": 1,
                "Feedback Group": 1,
                "Conflict": 2,
            }.get(node_type, 2)
        elif visual_column == "User Requirement":
            type_rank = {
                "User Requirement": 0,
                "User Requirement Group": 0,
            }.get(node_type, 3)
        elif visual_column == "Analysis":
            type_rank = {"Conflict": 0, "Feedback": 1, "System Model": 2}.get(node_type, 3)
        elif visual_column == "Background":
            type_rank = {"System Model": 0, "Feedback": 1, "Feedback Group": 1, "Conflict": 2}.get(node_type, 3)
        return (type_rank, anchor, node_index.get(node_id, 10**9))

    order_map: Dict[str, float] = {}
    for column in column_order:
        groups[column].sort(key=lambda node: node_rank(node, order_map))
        for index, node in enumerate(groups[column]):
            node_id = str(node.get("id") or "").strip()
            if node_id:
                order_map[node_id] = float(index)

    graph_node_by_id = {
        str(node.get("id") or "").strip(): node
        for node in graph_nodes
        if str(node.get("id") or "").strip()
    }
    raw_url_model_edges_by_target: Dict[str, List[Dict[str, Any]]] = {}
    raw_url_feedback_edges_by_target: Dict[str, List[Dict[str, Any]]] = {}
    for edge in graph_edges:
        source_id = str(edge.get("from") or "").strip()
        target_node_id = str(edge.get("to") or "").strip()
        source_node = graph_node_by_id.get(source_id, {})
        target_node = graph_node_by_id.get(target_node_id, {})
        source_is_url = str(source_node.get("type") or "").strip() in {"User Requirement", "User Requirement Group"}
        target_type = str(target_node.get("type") or "").strip()
        if (
            source_is_url
            and target_type == "System Model"
            and str(edge.get("style") or "").strip() == "dashed"
        ):
            raw_url_model_edges_by_target.setdefault(target_node_id, []).append(edge)
        if (
            source_is_url
            and target_type in {"Feedback", "Feedback Group"}
            and str(edge.get("style") or "").strip() == "dashed"
        ):
            raw_url_feedback_edges_by_target.setdefault(target_node_id, []).append(edge)
    single_url_mode = len(groups["User Requirement"]) == 1
    direct_url_model_node_ids = {
        target_node_id
        for target_node_id, model_edges in raw_url_model_edges_by_target.items()
        if len(model_edges) == 1
        and len([
            value for value in (
                graph_node_by_id.get(target_node_id, {}).get("related_sources") or []
            )
            if str(value).strip().startswith("URL-")
        ]) <= 1
    }
    direct_url_feedback_node_ids = {
        target_node_id
        for target_node_id, feedback_edges in raw_url_feedback_edges_by_target.items()
        if single_url_mode and len(feedback_edges) == 1
    }

    layout_attempts = [
        {
            "layout": "vertical",
            "main_x": 440,
            "main_width": 220,
            "url_width": 220,
            "url_gap": 36,
            "evidence_right_x": 840,
            "evidence_width": 230,
            "analysis_x": 60,
            "analysis_width": 220,
            "row_gap": 50,
            "stack_gap": 28,
            "view_width": 1110,
        },
        {
            "layout": "vertical",
            "main_x": 490,
            "main_width": 240,
            "url_width": 240,
            "url_gap": 40,
            "evidence_right_x": 930,
            "evidence_width": 250,
            "analysis_x": 60,
            "analysis_width": 240,
            "row_gap": 58,
            "stack_gap": 34,
            "view_width": 1220,
        },
        {
            "layout": "vertical",
            "main_x": 540,
            "main_width": 260,
            "url_width": 260,
            "url_gap": 44,
            "evidence_right_x": 1020,
            "evidence_width": 270,
            "analysis_x": 60,
            "analysis_width": 250,
            "row_gap": 66,
            "stack_gap": 42,
            "view_width": 1330,
        },
    ]
    node_height = 44
    top = 0

    def edge_label_width(label: str) -> int:
        width = 10
        for char in str(label or ""):
            width += 14 if ord(char) > 127 else 7
        return max(30, width)

    def edge_label_rect(x: float, y: float, label: str) -> Tuple[float, float, float, float]:
        width = edge_label_width(label)
        height = 18
        return (x - width / 2, y - height / 2, x + width / 2, y + height / 2)

    def assess_trace_topology_layout(
        positions: Dict[str, tuple[int, int, int]],
        valid_edges_for_layout: List[Dict[str, Any]],
    ) -> List[str]:
        issues: List[str] = []
        node_rects = {
            node_id: (x, y, x + width, y + node_height)
            for node_id, (x, y, width) in positions.items()
        }
        for edge in valid_edges_for_layout:
            label = str(edge.get("relation") or "").strip()
            if not label:
                continue
            start = positions.get(str(edge.get("from") or ""))
            end = positions.get(str(edge.get("to") or ""))
            if not start or not end:
                continue
            sx, sy = start[0] + start[2], start[1] + node_height // 2
            ex, ey = end[0], end[1] + node_height // 2
            if end[1] > start[1] + node_height:
                sx, sy = start[0] + start[2] / 2, start[1] + node_height
                ex, ey = end[0] + end[2] / 2, end[1]
                label_box = edge_label_rect((sx + ex) / 2, sy + max(24, (ey - sy) / 2) - 8, label)
            elif start[1] > end[1] + node_height:
                sx, sy = start[0] + start[2] / 2, start[1]
                ex, ey = end[0] + end[2] / 2, end[1] + node_height
                label_box = edge_label_rect((sx + ex) / 2, ey + max(24, (sy - ey) / 2) - 8, label)
            else:
                label_box = edge_label_rect((sx + ex) / 2, (sy + ey) / 2 - 10, label)
            for node_id, node_box in node_rects.items():
                if node_id in {str(edge.get("from") or ""), str(edge.get("to") or "")}:
                    continue
                if trace_topology_rects_overlap(label_box, node_box, padding=6):
                    issues.append(f"edge label {trace_topology_edge_key(edge)} overlaps {node_id}")
                    break
        columns: Dict[int, List[Tuple[float, float, float, float]]] = {}
        for x, y, width in positions.values():
            columns.setdefault(x, []).append((x, y, x + width, y + node_height))
        for rects in columns.values():
            rects.sort(key=lambda rect: rect[1])
            for index in range(1, len(rects)):
                if rects[index][1] - rects[index - 1][3] < 16:
                    issues.append("nodes too dense")
                    break
        return issues

    def build_layout(attempt: Dict[str, Any], edges_for_layout: List[Dict[str, Any]]) -> Dict[str, Any]:
        row_gap = int(attempt["row_gap"])
        stack_gap = int(attempt.get("stack_gap") or row_gap)
        meeting_stack_gap = max(stack_gap, 78)
        node_positions: Dict[str, tuple[int, int, int]] = {}
        node_markup: List[str] = []
        main_x = int(attempt["main_x"])
        main_width = int(attempt["main_width"])
        url_width = int(attempt["url_width"])
        url_gap = int(attempt["url_gap"])
        evidence_right_x = int(attempt["evidence_right_x"])
        evidence_width = int(attempt["evidence_width"])
        analysis_x = int(attempt["analysis_x"])
        analysis_width = int(attempt["analysis_width"])
        view_width = int(attempt["view_width"])
        evidence_left_nodes = [
            node for node in groups["Evidence"]
            if str(node.get("type") or "").strip() in {"Feedback", "Feedback Group", "Conflict"}
        ]
        direct_feedback_nodes = [
            node for node in evidence_left_nodes
            if str(node.get("id") or "").strip() in direct_url_feedback_node_ids
        ]
        evidence_left_nodes = [
            node for node in evidence_left_nodes
            if str(node.get("id") or "").strip() not in direct_url_feedback_node_ids
        ]
        evidence_right_nodes = [
            node for node in groups["Evidence"]
            if str(node.get("type") or "").strip() not in {"Feedback", "Feedback Group", "Conflict"}
        ]
        direct_model_nodes = [
            node for node in evidence_right_nodes
            if str(node.get("id") or "").strip() in direct_url_model_node_ids
        ]
        evidence_right_nodes = [
            node for node in evidence_right_nodes
            if str(node.get("id") or "").strip() not in direct_url_model_node_ids
        ]

        def stack_count_height(count: int, gap: int = stack_gap) -> int:
            return count * node_height + max(0, count - 1) * gap

        def stack_height(name: str, gap: int = stack_gap) -> int:
            if name == "Meeting":
                gap = meeting_stack_gap
            return stack_count_height(len(groups[name]), gap)

        url_count = len(groups["User Requirement"])
        total_url_width = url_count * url_width + max(0, url_count - 1) * url_gap if url_count else 0
        if total_url_width and total_url_width + 48 > view_width:
            view_width = int(total_url_width + 48)
            main_center_x = 24 + total_url_width / 2
            main_x = int(main_center_x - main_width / 2)
        else:
            main_center_x = main_x + main_width / 2
        url_start_x = int(main_center_x - total_url_width / 2) if url_count else main_x
        url_order = {
            str(node.get("id") or "").strip(): index
            for index, node in enumerate(groups["User Requirement"])
            if str(node.get("id") or "").strip()
        }

        def url_center_for_id(node_id: str) -> Optional[float]:
            if node_id not in url_order:
                return None
            return url_start_x + url_order[node_id] * (url_width + url_gap) + url_width / 2

        def conflict_anchor_x(node: Dict[str, Any], width: int) -> int:
            node_id = str(node.get("id") or "").strip()
            source_centers = [
                center
                for edge in edges_for_layout
                if str(edge.get("to") or "").strip() == node_id
                and str(edge.get("relation") or "").strip() == "衝突"
                for center in [url_center_for_id(str(edge.get("from") or "").strip())]
                if center is not None
            ]
            if not source_centers:
                return analysis_x
            center_x = sum(source_centers) / len(source_centers)
            return int(center_x - width / 2)

        source_target_indices: Dict[str, List[int]] = {}
        for edge in edges_for_layout:
            source_id = str(edge.get("from") or "").strip()
            target_id = str(edge.get("to") or "").strip()
            if target_id in url_order:
                source_target_indices.setdefault(source_id, []).append(url_order[target_id])
        source_groups: Dict[Tuple[int, ...], List[Dict[str, Any]]] = {}
        for node in groups["Source"]:
            node_id = str(node.get("id") or "").strip()
            target_indices = tuple(sorted(set(source_target_indices.get(node_id) or [])))
            source_groups.setdefault(target_indices, []).append(node)

        source_y = top
        source_height = node_height if groups["Source"] else 0
        url_y = source_y + source_height + row_gap
        url_height = node_height if groups["User Requirement"] else 0
        support_nodes = evidence_left_nodes + evidence_right_nodes + groups["Background"]
        support_count = len(support_nodes)
        support_columns = 1 if support_count else 0
        support_rows = (support_count + support_columns - 1) // support_columns if support_columns else 0
        support_gap_x = 16
        support_gap_y = 18
        support_width = evidence_width
        support_padding = 18
        support_title_height = 0
        direct_model_ids = {
            str(node.get("id") or "").strip()
            for node in direct_model_nodes
            if str(node.get("id") or "").strip()
        }
        direct_model_counts_by_source: Dict[str, int] = {}
        for edge in edges_for_layout:
            source_id = str(edge.get("from") or "").strip()
            target_id = str(edge.get("to") or "").strip()
            if target_id in direct_model_ids and source_id:
                direct_model_counts_by_source[source_id] = direct_model_counts_by_source.get(source_id, 0) + 1
        direct_model_rows = max(direct_model_counts_by_source.values(), default=0)
        direct_feedback_ids = {
            str(node.get("id") or "").strip()
            for node in direct_feedback_nodes
            if str(node.get("id") or "").strip()
        }
        direct_feedback_counts_by_source: Dict[str, int] = {}
        for edge in edges_for_layout:
            source_id = str(edge.get("from") or "").strip()
            target_id = str(edge.get("to") or "").strip()
            if target_id in direct_feedback_ids and source_id:
                direct_feedback_counts_by_source[source_id] = direct_feedback_counts_by_source.get(source_id, 0) + 1
        direct_feedback_rows = max(direct_feedback_counts_by_source.values(), default=0)
        direct_model_gap_y = 20
        direct_side_rows = max(direct_model_rows, direct_feedback_rows)
        direct_model_band_height = (
            direct_model_gap_y + max(0, direct_side_rows - 1) * (node_height + support_gap_y)
            if direct_side_rows > 1
            else 0
        )
        support_content_height = (
            support_rows * node_height + max(0, support_rows - 1) * support_gap_y
            if support_rows
            else 0
        )
        url_band_height = url_height + direct_model_band_height
        analysis_conflict_inline = (
            len(groups["Analysis"]) > 1
            and all(str(node.get("type") or "").strip() == "Conflict" for node in groups["Analysis"])
        )
        analysis_height = node_height if analysis_conflict_inline else stack_height("Analysis")
        analysis_gap = row_gap + (28 if analysis_conflict_inline else 0)
        analysis_y = url_y + url_band_height + (analysis_gap if groups["Analysis"] else 0)
        meeting_y = analysis_y + analysis_height + row_gap
        meeting_height = stack_height("Meeting")
        requirement_y = meeting_y + meeting_height + row_gap
        requirement_height = stack_height("Requirement")
        support_panel_width = (
            support_columns * support_width
            + max(0, support_columns - 1) * support_gap_x
            + support_padding * 2
            if support_count
            else 0
        )
        support_height = (
            support_title_height + support_content_height + support_padding * 2
            if support_count
            else 0
        )
        support_main_gap = 96
        support_x = max(evidence_right_x, main_x + main_width + support_main_gap) if support_count else 0
        support_y = max(top, meeting_y - support_padding) if support_count else 0
        if support_count:
            view_width = max(view_width, int(support_x + support_panel_width + 24))
        height = max(
            requirement_y + requirement_height + 18,
            support_y + support_height + 18 if support_count else 0,
        )
        support_panel = (
            {
                "x": support_x,
                "y": support_y,
                "width": support_panel_width,
                "height": support_height,
                "side": "right",
            }
            if support_count
            else None
        )

        row_specs = [
            ("Analysis", analysis_x, analysis_width, analysis_y, analysis_height),
            ("Meeting", main_x, main_width, meeting_y, meeting_height),
            ("Requirement", main_x, main_width, requirement_y, requirement_height),
        ]
        source_gap = 16
        source_group_specs: List[Tuple[float, List[Dict[str, Any]]]] = []
        for target_indices, nodes in source_groups.items():
            if target_indices and url_count:
                centers = [
                    url_start_x + index * (url_width + url_gap) + url_width / 2
                    for index in target_indices
                ]
                center_x = sum(centers) / len(centers)
            else:
                center_x = main_center_x
            source_group_specs.append((center_x, nodes))
        source_group_specs.sort(key=lambda item: item[0])
        previous_right = 24
        for center_x, bucket_nodes in source_group_specs:
            group_width = len(bucket_nodes) * url_width + max(0, len(bucket_nodes) - 1) * source_gap
            x_start = int(center_x - group_width / 2)
            x_start = max(24, x_start, previous_right)
            previous_right = x_start + group_width + source_gap
            view_width = max(view_width, int(previous_right + 24))
            for index, node in enumerate(bucket_nodes):
                x = int(x_start + index * (url_width + source_gap))
                y = source_y
                node_id = str(node.get("id") or "").strip()
                node_positions[node_id] = (x, y, url_width)
                node_markup.append(trace_topology_svg_node(
                    node_id=node_id,
                    label=str(node.get("label") or node_id),
                    node_type=str(node.get("type") or ""),
                    title=str(node.get("title") or node_id),
                    content=str(node.get("content") or ""),
                    content_format=str(node.get("content_format") or "text"),
                    x=x,
                    y=y,
                    width=url_width,
                    target=False,
                ))
        for name, x, width, band_y, band_height in row_specs:
            count = len(groups[name])
            if not count:
                continue
            row_stack_gap = meeting_stack_gap if name == "Meeting" else stack_gap
            content_height = (
                node_height
                if name == "Analysis" and analysis_conflict_inline
                else count * node_height + max(0, count - 1) * row_stack_gap
            )
            y_start = band_y + max(0, (band_height - content_height) // 2)
            inline_conflict_x: Dict[str, int] = {}
            if name == "Analysis" and analysis_conflict_inline:
                desired_positions = sorted(
                    [
                        (
                            conflict_anchor_x(node, width),
                            str(node.get("id") or "").strip(),
                        )
                        for node in groups[name]
                        if str(node.get("id") or "").strip()
                    ],
                    key=lambda item: item[0],
                )
                min_gap = 28
                previous_right = 24
                for desired_x, node_id in desired_positions:
                    node_x = max(24, desired_x, previous_right)
                    inline_conflict_x[node_id] = node_x
                    previous_right = node_x + width + min_gap
                    view_width = max(view_width, int(previous_right + 24))
            for index, node in enumerate(groups[name]):
                node_id = str(node.get("id") or "").strip()
                node_type = str(node.get("type") or "").strip()
                if name == "Analysis" and analysis_conflict_inline and node_type == "Conflict":
                    y = y_start
                    node_x = inline_conflict_x.get(node_id, conflict_anchor_x(node, width))
                else:
                    y = y_start + index * (node_height + row_stack_gap)
                    node_x = conflict_anchor_x(node, width) if name == "Analysis" and node_type == "Conflict" else x
                view_width = max(view_width, int(node_x + width + 24))
                node_positions[node_id] = (node_x, y, width)
                node_markup.append(trace_topology_svg_node(
                    node_id=node_id,
                    label=str(node.get("label") or node_id),
                    node_type=str(node.get("type") or ""),
                    title=str(node.get("title") or node_id),
                    content=str(node.get("content") or ""),
                    content_format=str(node.get("content_format") or "text"),
                    x=node_x,
                    y=y,
                    width=width,
                    target=name == "Requirement",
                ))
        if url_count:
            y = url_y + max(0, (url_band_height - node_height) // 2)
            for index, node in enumerate(groups["User Requirement"]):
                x = url_start_x + index * (url_width + url_gap)
                node_id = str(node.get("id") or "").strip()
                node_positions[node_id] = (x, y, url_width)
                node_markup.append(trace_topology_svg_node(
                    node_id=node_id,
                    label=str(node.get("label") or node_id),
                    node_type=str(node.get("type") or ""),
                    title=str(node.get("title") or node_id),
                    content=str(node.get("content") or ""),
                    content_format=str(node.get("content_format") or "text"),
                    x=x,
                    y=y,
                    width=url_width,
                    target=False,
                ))
        direct_model_slot_by_source: Dict[str, int] = {}
        def render_direct_side_nodes(
            nodes: List[Dict[str, Any]],
            *,
            side: str,
            slot_by_source: Dict[str, int],
        ) -> None:
            nonlocal view_width
            side_gap = 80
            for node in nodes:
                node_id = str(node.get("id") or "").strip()
                source_id = next(
                    (
                        str(edge.get("from") or "").strip()
                        for edge in edges_for_layout
                        if str(edge.get("to") or "").strip() == node_id
                        and str(edge.get("from") or "").strip() in node_positions
                    ),
                    "",
                )
                source_position = node_positions.get(source_id)
                if source_position:
                    slot = slot_by_source.get(source_id, 0)
                    slot_by_source[source_id] = slot + 1
                    if side == "left":
                        x = max(24, source_position[0] - support_width - side_gap)
                    else:
                        right_x = source_position[0] + source_position[2] + side_gap
                        if right_x + support_width + 24 <= view_width:
                            x = int(right_x)
                        else:
                            x = int(right_x)
                    y = source_position[1] + slot * (node_height + support_gap_y)
                else:
                    x = max(24, url_start_x - support_width - 64) if side == "left" else url_start_x + url_width + 36
                    y = url_y
                view_width = max(view_width, int(x + support_width + 24))
                node_positions[node_id] = (x, y, support_width)
                node_markup.append(trace_topology_svg_node(
                    node_id=node_id,
                    label=str(node.get("label") or node_id),
                    node_type=str(node.get("type") or ""),
                    title=str(node.get("title") or node_id),
                    content=str(node.get("content") or ""),
                    content_format=str(node.get("content_format") or "text"),
                    x=x,
                    y=y,
                    width=support_width,
                    target=False,
                ))

        render_direct_side_nodes(direct_feedback_nodes, side="left", slot_by_source={})
        render_direct_side_nodes(direct_model_nodes, side="right", slot_by_source=direct_model_slot_by_source)
        if support_count:
            total_support_width = support_columns * support_width + max(0, support_columns - 1) * support_gap_x
            support_start_x = support_x + support_padding
            node_markup.append(
                f'<rect class="dr-trace-support-box" x="{support_x}" y="{support_y}" '
                f'width="{support_panel_width}" height="{support_height}" rx="8"></rect>'
            )
            y_start = support_y + support_padding + support_title_height
            for index, node in enumerate(support_nodes):
                column_index = index % support_columns
                row_index = index // support_columns
                x = support_start_x + column_index * (support_width + support_gap_x)
                y = y_start + row_index * (node_height + support_gap_y)
                node_id = str(node.get("id") or "").strip()
                node_positions[node_id] = (x, y, support_width)
                node_markup.append(trace_topology_svg_node(
                    node_id=node_id,
                    label=str(node.get("label") or node_id),
                    node_type=str(node.get("type") or ""),
                    title=str(node.get("title") or node_id),
                    content=str(node.get("content") or ""),
                    content_format=str(node.get("content_format") or "text"),
                    x=x,
                    y=y,
                    width=support_width,
                    target=False,
                ))
        valid_edges = collect_valid_trace_edges(edges_for_layout, node_positions)
        return {
            "height": height,
            "node_positions": node_positions,
            "node_markup": node_markup,
            "valid_edges": valid_edges,
            "view_width": view_width,
            "orientation": str(attempt.get("layout") or "horizontal"),
            "support_panel": support_panel,
            "issues": assess_trace_topology_layout(node_positions, valid_edges),
        }

    selected_graph_edges = graph_edges
    compact_label_mode = False
    selected_layout = build_layout(layout_attempts[-1], selected_graph_edges)
    selected_attempt_index = len(layout_attempts) - 1
    for attempt_index, attempt in enumerate(layout_attempts):
        candidate = build_layout(attempt, selected_graph_edges)
        selected_layout = candidate
        selected_attempt_index = attempt_index
        if not candidate["issues"]:
            break
    if selected_layout["issues"]:
        main_chain_labels = {"分析", "整理", "衝突", "解決", "正式化", "精練"}
        selected_graph_edges = [
            {
                **edge,
                "relation": str(edge.get("relation") or "").strip()
                if str(edge.get("relation") or "").strip() in main_chain_labels
                else "",
            }
            for edge in graph_edges
        ]
        compact_label_mode = True
        selected_layout = build_layout(layout_attempts[-1], selected_graph_edges)
        selected_attempt_index = len(layout_attempts)

    height = selected_layout["height"]
    view_width = selected_layout["view_width"]
    node_positions = selected_layout["node_positions"]
    node_markup = selected_layout["node_markup"]
    layout_orientation = str(selected_layout.get("orientation") or "horizontal")
    layout_quality = "needs-review" if selected_layout["issues"] else "ok"
    node_by_id = {
        str(node.get("id") or "").strip(): node
        for node in graph_nodes
        if str(node.get("id") or "").strip()
    }
    has_evidence_nodes = bool(groups.get("Evidence"))

    def is_url_to_meeting_edge(edge: Dict[str, Any]) -> bool:
        source_node = node_by_id.get(str(edge.get("from") or "").strip(), {})
        target_node = node_by_id.get(str(edge.get("to") or "").strip(), {})
        return (
            has_evidence_nodes
            and str(source_node.get("type") or "").strip() in {"User Requirement", "User Requirement Group"}
            and str(source_node.get("column") or "").strip() == "User Requirement"
            and str(target_node.get("type") or "").strip() == "Meeting Discussion"
            and str(edge.get("style") or "").strip() != "dashed"
        )

    def outside_url_to_meeting_path(
        start: tuple[int, int, int],
        end: tuple[int, int, int],
        *,
        label: str = "",
        source_edge: str = "",
    ) -> str:
        sx, sy = start[0] + start[2] / 2, start[1] + node_height
        ex, ey = end[0] + end[2] / 2, end[1] + node_height
        outside_y = height - 8
        source_attr = f' data-source-edge="{html_attr(source_edge)}"' if source_edge else ""
        path = (
            f'<path class="dr-trace-edge"{source_attr} '
            f'd="M {sx:.1f} {sy} C {sx:.1f} {outside_y}, {sx:.1f} {outside_y}, {sx + 72:.1f} {outside_y} '
            f'L {ex:.1f} {outside_y} C {ex:.1f} {outside_y}, {ex:.1f} {outside_y}, {ex:.1f} {ey}" '
            f'marker-end="url(#{marker_id})"></path>'
        )
        clean_label = str(label or "").strip()
        if not clean_label:
            return path
        return path + edge_label_markup((sx + ex) / 2, outside_y - 12, clean_label)

    def edge_path(
        start: tuple[int, int, int],
        end: tuple[int, int, int],
        label: str = "",
        source_edge: str = "",
        style: str = "",
    ) -> str:
        source_attr = f' data-source-edge="{html_attr(source_edge)}"' if source_edge else ""
        edge_class = "dr-trace-edge dr-trace-edge--dashed" if str(style or "").strip() == "dashed" else "dr-trace-edge"
        if end[1] > start[1] + node_height:
            sx, sy = start[0] + start[2] / 2, start[1] + node_height
            ex, ey = end[0] + end[2] / 2, end[1]
            mid_y = sy + max(24, (ey - sy) / 2)
            d = f"M {sx:.1f} {sy} C {sx:.1f} {mid_y:.1f}, {ex:.1f} {mid_y:.1f}, {ex:.1f} {ey}"
            lx, ly = (sx + ex) / 2, mid_y - 8
        elif start[1] > end[1] + node_height:
            sx, sy = start[0] + start[2] / 2, start[1]
            ex, ey = end[0] + end[2] / 2, end[1] + node_height
            mid_y = ey + max(24, (sy - ey) / 2)
            d = f"M {sx:.1f} {sy} C {sx:.1f} {mid_y:.1f}, {ex:.1f} {mid_y:.1f}, {ex:.1f} {ey}"
            lx, ly = (sx + ex) / 2, mid_y - 8
        elif end[0] >= start[0]:
            sx, sy = start[0] + start[2], start[1] + node_height // 2
            ex, ey = end[0], end[1] + node_height // 2
            mid = sx + max(24, (ex - sx) / 2)
            d = f"M {sx} {sy} C {mid:.1f} {sy}, {mid:.1f} {ey}, {ex} {ey}"
            lx, ly = (sx + ex) / 2, (sy + ey) / 2 - 10
        else:
            sx, sy = start[0], start[1] + node_height // 2
            ex, ey = end[0] + end[2], end[1] + node_height // 2
            mid = ex + max(24, (sx - ex) / 2)
            d = f"M {sx} {sy} C {mid:.1f} {sy}, {mid:.1f} {ey}, {ex} {ey}"
            lx, ly = (sx + ex) / 2, (sy + ey) / 2 - 10
        path = f'<path class="{edge_class}"{source_attr} d="{d}" marker-end="url(#{marker_id})"></path>'
        clean_label = str(label or "").strip()
        if not clean_label:
            return path
        return path + edge_label_markup(lx, ly, clean_label)

    def edge_label_markup(x: float, y: float, label: str) -> str:
        clean_label = str(label or "").strip()
        if not clean_label:
            return ""
        rect_x, rect_y, rect_right, rect_bottom = edge_label_rect(x, y, clean_label)
        width = rect_right - rect_x
        height = rect_bottom - rect_y
        return (
            f'<g class="dr-trace-edge-label-wrap">'
            f'<rect class="dr-trace-edge-label-bg" x="{rect_x:.1f}" y="{rect_y:.1f}" '
            f'width="{width:.1f}" height="{height}" rx="9"></rect>'
            f'<text class="dr-trace-edge-label" x="{x:.1f}" y="{y:.1f}" '
            f'text-anchor="middle">{html_attr(clean_label)}</text>'
            '</g>'
        )

    def is_url_to_evidence_edge(edge: Dict[str, Any]) -> bool:
        source_node = node_by_id.get(str(edge.get("from") or "").strip(), {})
        target_node = node_by_id.get(str(edge.get("to") or "").strip(), {})
        return (
            str(source_node.get("type") or "").strip() in {"User Requirement", "User Requirement Group"}
            and str(target_node.get("type") or "").strip() in {"Feedback", "Feedback Group", "System Model"}
            and str(edge.get("style") or "").strip() == "dashed"
        )

    def is_source_to_url_edge(edge: Dict[str, Any]) -> bool:
        source_node = node_by_id.get(str(edge.get("from") or "").strip(), {})
        target_node = node_by_id.get(str(edge.get("to") or "").strip(), {})
        return (
            str(source_node.get("type") or "").strip() in {"Source", "Stakeholder Statement"}
            and str(target_node.get("type") or "").strip() in {"User Requirement", "User Requirement Group"}
            and str(edge.get("style") or "").strip() != "dashed"
        )

    def bundled_source_to_url_paths(target: tuple[int, int, int], incoming: List[Dict[str, Any]]) -> str:
        if not incoming:
            return ""
        target_top_x = target[0] + target[2] / 2
        target_top_y = target[1]
        source_points = []
        for edge in incoming:
            source_id = str(edge.get("from") or "").strip()
            if source_id not in node_positions:
                continue
            source = node_positions[source_id]
            source_points.append((source[0] + source[2] / 2, source[1] + node_height, trace_topology_edge_key(edge)))
        if not source_points:
            return ""
        source_bottom_y = max(point[1] for point in source_points)
        junction_y = source_bottom_y + max(20, (target_top_y - source_bottom_y) / 2)
        min_x = min([point[0] for point in source_points] + [target_top_x])
        max_x = max([point[0] for point in source_points] + [target_top_x])
        parts = [
            f'<path class="dr-trace-edge" d="M {min_x:.1f} {junction_y:.1f} '
            f'L {max_x:.1f} {junction_y:.1f}"></path>'
        ]
        for sx, sy, key in source_points:
            parts.append(
                f'<path class="dr-trace-edge" data-source-edge="{html_attr(key)}" '
                f'd="M {sx:.1f} {sy:.1f} L {sx:.1f} {junction_y:.1f}"></path>'
            )
        parts.append(
            f'<path class="dr-trace-edge" d="M {target_top_x:.1f} {junction_y:.1f} '
            f'L {target_top_x:.1f} {target_top_y:.1f}" marker-end="url(#{marker_id})"></path>'
        )
        parts.append(edge_label_markup(target_top_x, junction_y - 14, "分析"))
        return "".join(parts)

    def bundled_source_to_urls_paths(source: tuple[int, int, int], outgoing: List[Dict[str, Any]]) -> str:
        if not outgoing:
            return ""
        source_bottom_x = source[0] + source[2] / 2
        source_bottom_y = source[1] + node_height
        target_points = []
        for edge in outgoing:
            target_id = str(edge.get("to") or "").strip()
            if target_id not in node_positions:
                continue
            target = node_positions[target_id]
            target_points.append((target[0] + target[2] / 2, target[1], trace_topology_edge_key(edge)))
        if not target_points:
            return ""
        target_top_y = min(point[1] for point in target_points)
        junction_y = source_bottom_y + max(20, (target_top_y - source_bottom_y) / 2)
        min_x = min([point[0] for point in target_points] + [source_bottom_x])
        max_x = max([point[0] for point in target_points] + [source_bottom_x])
        parts = [
            f'<path class="dr-trace-edge" d="M {source_bottom_x:.1f} {source_bottom_y:.1f} '
            f'L {source_bottom_x:.1f} {junction_y:.1f}"></path>',
            f'<path class="dr-trace-edge" d="M {min_x:.1f} {junction_y:.1f} '
            f'L {max_x:.1f} {junction_y:.1f}"></path>',
        ]
        for tx, ty, key in target_points:
            parts.append(
                f'<path class="dr-trace-edge" data-source-edge="{html_attr(key)}" '
                f'd="M {tx:.1f} {junction_y:.1f} L {tx:.1f} {ty:.1f}" '
                f'marker-end="url(#{marker_id})"></path>'
            )
        parts.append(edge_label_markup(source_bottom_x, junction_y - 14, "分析"))
        return "".join(parts)

    def bundled_vertical_paths(
        edges_for_bundle: List[Dict[str, Any]],
        *,
        label: str,
        label_each_target: bool = False,
    ) -> str:
        if not edges_for_bundle:
            return ""
        source_ids = sorted({
            str(edge.get("from") or "").strip()
            for edge in edges_for_bundle
            if str(edge.get("from") or "").strip() in node_positions
        })
        target_ids = sorted({
            str(edge.get("to") or "").strip()
            for edge in edges_for_bundle
            if str(edge.get("to") or "").strip() in node_positions
        })
        if not source_ids or not target_ids:
            return ""
        source_points = [
            (
                node_positions[source_id][0] + node_positions[source_id][2] / 2,
                node_positions[source_id][1] + node_height,
            )
            for source_id in source_ids
        ]
        target_points = [
            (
                node_positions[target_id][0] + node_positions[target_id][2] / 2,
                node_positions[target_id][1],
            )
            for target_id in target_ids
        ]
        source_y = max(point[1] for point in source_points)
        target_y = min(point[1] for point in target_points)
        junction_y = source_y + max(20, (target_y - source_y) / 2)
        min_x = min(point[0] for point in source_points + target_points)
        max_x = max(point[0] for point in source_points + target_points)
        parts = [
            f'<path class="dr-trace-edge" d="M {min_x:.1f} {junction_y:.1f} '
            f'L {max_x:.1f} {junction_y:.1f}"></path>'
        ]
        for sx, sy in source_points:
            parts.append(
                f'<path class="dr-trace-edge" d="M {sx:.1f} {sy:.1f} '
                f'L {sx:.1f} {junction_y:.1f}"></path>'
            )
        for tx, ty in target_points:
            parts.append(
                f'<path class="dr-trace-edge" d="M {tx:.1f} {junction_y:.1f} '
                f'L {tx:.1f} {ty:.1f}" marker-end="url(#{marker_id})"></path>'
            )
            if label_each_target:
                parts.append(edge_label_markup(tx, junction_y + max(14, (ty - junction_y) / 2), label))
        if not label_each_target:
            parts.append(edge_label_markup((min_x + max_x) / 2, junction_y - 14, label))
        return "".join(parts)

    def bundled_side_evidence_paths(edges_for_bundle: List[Dict[str, Any]], *, label: str) -> str:
        visible_edges = [
            edge for edge in edges_for_bundle
            if str(edge.get("from") or "").strip() in node_positions
            and str(edge.get("to") or "").strip() in node_positions
        ]
        if not visible_edges:
            return ""
        source_id = str(visible_edges[0].get("from") or "").strip()
        source = node_positions[source_id]
        source_center_y = source[1] + node_height / 2
        targets = [
            (
                str(edge.get("to") or "").strip(),
                node_positions[str(edge.get("to") or "").strip()],
                trace_topology_edge_key(edge),
            )
            for edge in visible_edges
        ]
        target_is_left = sum(target[1][0] + target[1][2] / 2 for target in targets) / len(targets) < source[0] + source[2] / 2
        if target_is_left:
            source_x = source[0]
            target_x = max(target[1][0] + target[1][2] for target in targets)
            junction_x = source_x - max(22, (source_x - target_x) / 2)
        else:
            source_x = source[0] + source[2]
            target_x = min(target[1][0] for target in targets)
            junction_x = source_x + max(22, (target_x - source_x) / 2)
        paths = [
            f'<path class="dr-trace-edge dr-trace-edge--dashed" '
            f'd="M {source_x:.1f} {source_center_y:.1f} L {junction_x:.1f} {source_center_y:.1f}"></path>'
        ]
        target_ys = [target[1][1] + node_height / 2 for target in targets]
        if len(target_ys) > 1:
            paths.append(
                f'<path class="dr-trace-edge dr-trace-edge--dashed" '
                f'd="M {junction_x:.1f} {min(target_ys):.1f} L {junction_x:.1f} {max(target_ys):.1f}"></path>'
            )
        for _, target, key in targets:
            target_y = target[1] + node_height / 2
            end_x = target[0] + target[2] if target_is_left else target[0]
            paths.append(
                f'<path class="dr-trace-edge dr-trace-edge--dashed" data-source-edge="{html_attr(key)}" '
                f'd="M {junction_x:.1f} {target_y:.1f} L {end_x:.1f} {target_y:.1f}" '
                f'marker-end="url(#{marker_id})"></path>'
            )
        label_y = min(target_ys) - 12 if len(target_ys) > 1 else source_center_y - 12
        paths.append(edge_label_markup(junction_x, label_y, label))
        return "".join(paths)

    def support_summary_to_meeting_path() -> str:
        support_panel = selected_layout.get("support_panel") if isinstance(selected_layout, dict) else None
        if not isinstance(support_panel, dict):
            return ""
        panel_x = float(support_panel.get("x") or 0)
        panel_y = float(support_panel.get("y") or 0)
        panel_height = float(support_panel.get("height") or 0)
        source_x = panel_x

        def single_url_formalization_point() -> Optional[Tuple[float, float]]:
            url_ids = [
                str(node.get("id") or "").strip()
                for node in groups["User Requirement"]
                if str(node.get("id") or "").strip() in node_positions
            ]
            if len(url_ids) != 1:
                return None
            url_id = url_ids[0]
            url_position = node_positions[url_id]
            url_center_x = url_position[0] + url_position[2] / 2
            url_bottom_y = url_position[1] + node_height
            meeting_edges = [
                edge for edge in valid_edges
                if str(edge.get("from") or "").strip() == url_id
                and str(edge.get("to") or "").strip() in node_positions
                and str(node_by_id.get(str(edge.get("to") or "").strip(), {}).get("type") or "").strip() == "Meeting Discussion"
                and str(edge.get("style") or "").strip() != "dashed"
            ]
            if not meeting_edges:
                return (url_position[0] + url_position[2], url_position[1] + node_height / 2)
            latest_edge = max(
                meeting_edges,
                key=lambda edge: node_positions[str(edge.get("to") or "").strip()][1],
            )
            meeting_position = node_positions[str(latest_edge.get("to") or "").strip()]
            meeting_top_y = meeting_position[1]
            target_y = url_bottom_y + max(18, min(42, (meeting_top_y - url_bottom_y) / 3))
            return (url_center_x, target_y)

        def meeting_bundle_junction(relation: str) -> Optional[Tuple[float, float]]:
            bundle_edges = [
                edge for edge in valid_edges
                if str(edge.get("relation") or "").strip() == relation
                and str(edge.get("from") or "").strip() in node_positions
                and str(edge.get("to") or "").strip() in node_positions
                and str(node_by_id.get(str(edge.get("to") or "").strip(), {}).get("type") or "").strip() == "Meeting Discussion"
            ]
            if not bundle_edges:
                return None
            source_points = [
                (
                    node_positions[str(edge.get("from") or "").strip()][0]
                    + node_positions[str(edge.get("from") or "").strip()][2] / 2,
                    node_positions[str(edge.get("from") or "").strip()][1] + node_height,
                )
                for edge in bundle_edges
            ]
            target_points = [
                (
                    node_positions[str(edge.get("to") or "").strip()][0]
                    + node_positions[str(edge.get("to") or "").strip()][2] / 2,
                    node_positions[str(edge.get("to") or "").strip()][1],
                )
                for edge in bundle_edges
            ]
            source_y = max(point[1] for point in source_points)
            target_y = min(point[1] for point in target_points)
            junction_y = source_y + max(20, (target_y - source_y) / 2)
            target_x = sum(point[0] for point in target_points) / len(target_points)
            return (target_x, junction_y)

        target_point = single_url_formalization_point() or meeting_bundle_junction("正式化") or meeting_bundle_junction("精練")
        if target_point:
            target_x, target_y = target_point
        else:
            target_ids = [
                str(node.get("id") or "").strip()
                for node in groups["Meeting"]
                if str(node.get("id") or "").strip() in node_positions
            ]
            if not target_ids:
                target_ids = [
                    str(node.get("id") or "").strip()
                    for node in groups["Requirement"]
                    if str(node.get("id") or "").strip() in node_positions
                ]
            if not target_ids:
                return ""
            target_id = max(target_ids, key=lambda node_id: node_positions[node_id][1])
            target = node_positions[target_id]
            target_x = target[0] + target[2]
            target_y = target[1] + node_height / 2
        source_y = min(max(target_y, panel_y + 26), panel_y + panel_height - 26)
        mid_x = target_x + max(30, (source_x - target_x) / 2)
        return (
            f'<path class="dr-trace-edge dr-trace-edge--dashed" data-support-summary="true" '
            f'd="M {source_x:.1f} {source_y:.1f} C {mid_x:.1f} {source_y:.1f}, '
            f'{mid_x:.1f} {target_y:.1f}, {target_x:.1f} {target_y:.1f}"></path>'
        )

    def bundled_conflict_paths(target: tuple[int, int, int], incoming: List[Dict[str, Any]]) -> str:
        visible_incoming = [
            edge for edge in incoming
            if str(edge.get("from") or "").strip() in node_positions
            and str(edge.get("to") or "").strip() in node_positions
        ]
        if not visible_incoming:
            return ""
        ex = target[0] + target[2] / 2
        target_top_y = target[1]
        source_points = []
        for edge in visible_incoming:
            source_id = str(edge.get("from") or "").strip()
            source = node_positions[source_id]
            source_points.append((
                source[0] + source[2] / 2,
                source[1] + node_height,
                trace_topology_edge_key(edge),
            ))
        if not source_points:
            return ""
        source_y = max(point[1] for point in source_points)
        if source_y >= target_top_y:
            target_left_x = target[0]
            target_center_y = target[1] + node_height / 2
            source_points_side = []
            for edge in visible_incoming:
                source_id = str(edge.get("from") or "").strip()
                source = node_positions[source_id]
                source_points_side.append((
                    source[0] + source[2],
                    source[1] + node_height / 2,
                    trace_topology_edge_key(edge),
                ))
            if not source_points_side:
                return ""
            junction_x = target_left_x - 30
            min_y = min([point[1] for point in source_points_side] + [target_center_y])
            max_y = max([point[1] for point in source_points_side] + [target_center_y])
            parts = [
                f'<path class="dr-trace-edge" d="M {junction_x:.1f} {min_y:.1f} '
                f'L {junction_x:.1f} {max_y:.1f}"></path>'
            ]
            for sx, sy, key in source_points_side:
                mid_x = sx + max(24, (junction_x - sx) / 2)
                parts.append(
                    f'<path class="dr-trace-edge" data-source-edge="{html_attr(key)}" '
                    f'd="M {sx:.1f} {sy:.1f} C {mid_x:.1f} {sy:.1f}, '
                    f'{mid_x:.1f} {sy:.1f}, {junction_x:.1f} {sy:.1f}"></path>'
                )
            parts.append(
                f'<path class="dr-trace-edge" d="M {junction_x:.1f} {target_center_y:.1f} '
                f'L {target_left_x:.1f} {target_center_y:.1f}" marker-end="url(#{marker_id})"></path>'
            )
            parts.append(edge_label_markup(junction_x, target_center_y - 14, "衝突"))
            return "".join(parts)
        junction_y = source_y + max(20, (target_top_y - source_y) / 2)
        conflict_targets = [
            target_id
            for target_id, target_incoming in incoming_by_target.items()
            if (
                str(node_by_id.get(target_id, {}).get("type") or "").strip() == "Conflict"
                and len(target_incoming) >= 2
                and {
                    str(edge.get("relation") or "").strip()
                    for edge in target_incoming
                    if str(edge.get("relation") or "").strip()
                } == {"衝突"}
                and target_id in node_positions
            )
        ]
        conflict_targets.sort(key=lambda node_id: node_positions[node_id][0] + node_positions[node_id][2] / 2)
        target_id = str(visible_incoming[0].get("to") or "").strip()
        if len(conflict_targets) > 1 and target_id in conflict_targets:
            available = max(0.0, target_top_y - source_y - 34)
            spacing = min(30.0, max(16.0, available / max(1, len(conflict_targets) - 1)))
            offset = (conflict_targets.index(target_id) - (len(conflict_targets) - 1) / 2) * spacing
            junction_y = min(target_top_y - 18, max(source_y + 18, junction_y + offset))
        min_x = min([point[0] for point in source_points] + [ex])
        max_x = max([point[0] for point in source_points] + [ex])
        parts = [
            f'<path class="dr-trace-edge" d="M {min_x:.1f} {junction_y:.1f} '
            f'L {max_x:.1f} {junction_y:.1f}"></path>'
        ]
        for sx, sy, key in source_points:
            parts.append(
                f'<path class="dr-trace-edge" data-source-edge="{html_attr(key)}" '
                f'd="M {sx:.1f} {sy:.1f} C {sx:.1f} {junction_y:.1f}, '
                f'{sx:.1f} {junction_y:.1f}, {sx:.1f} {junction_y:.1f}"></path>'
            )
        parts.append(
            f'<path class="dr-trace-edge" d="M {ex:.1f} {junction_y:.1f} '
            f'L {ex:.1f} {target_top_y:.1f}" marker-end="url(#{marker_id})"></path>'
        )
        parts.append(edge_label_markup(ex, junction_y - 14, "衝突"))
        return "".join(parts)

    def bundled_resolution_paths(target: tuple[int, int, int], incoming: List[Dict[str, Any]]) -> str:
        visible_incoming = [
            edge for edge in incoming
            if str(edge.get("from") or "").strip() in node_positions
            and str(edge.get("to") or "").strip() in node_positions
        ]
        if not visible_incoming:
            return ""
        ex = target[0] + target[2] / 2
        target_top_y = target[1]
        source_points = []
        for edge in visible_incoming:
            source_id = str(edge.get("from") or "").strip()
            source = node_positions[source_id]
            source_points.append((
                source[0] + source[2] / 2,
                source[1] + node_height,
                trace_topology_edge_key(edge),
            ))
        if not source_points:
            return ""
        source_y = max(point[1] for point in source_points)
        if source_y >= target_top_y:
            return bundled_edge_paths(target, incoming)
        junction_y = source_y + max(22, (target_top_y - source_y) / 2)
        min_x = min([point[0] for point in source_points] + [ex])
        max_x = max([point[0] for point in source_points] + [ex])
        parts = [
            f'<path class="dr-trace-edge" d="M {min_x:.1f} {junction_y:.1f} '
            f'L {max_x:.1f} {junction_y:.1f}"></path>'
        ]
        for sx, sy, key in source_points:
            parts.append(
                f'<path class="dr-trace-edge" data-source-edge="{html_attr(key)}" '
                f'd="M {sx:.1f} {sy:.1f} L {sx:.1f} {junction_y:.1f}"></path>'
            )
        parts.append(
            f'<path class="dr-trace-edge" d="M {ex:.1f} {junction_y:.1f} '
            f'L {ex:.1f} {target_top_y:.1f}" marker-end="url(#{marker_id})"></path>'
        )
        parts.append(edge_label_markup(ex, junction_y - 14, "解決"))
        return "".join(parts)

    def bundled_edge_paths(target: tuple[int, int, int], incoming: List[Dict[str, Any]]) -> str:
        target_id = str(incoming[0].get("to") or "").strip() if incoming else ""
        target_node = next(
            (
                node
                for node in graph_nodes
                if str(node.get("id") or "").strip() == target_id
            ),
            {},
        )
        ex, ey = target[0], target[1] + node_height // 2
        junction_x = ex - 28
        junction_y = ey
        paths: List[str] = []
        solid_incoming: List[Dict[str, Any]] = []
        dashed_incoming: List[Dict[str, Any]] = []
        for edge in incoming:
            key = trace_topology_edge_key(edge)
            source_id = str(edge.get("from") or "").strip()
            start = node_positions[str(edge.get("from") or "").strip()]
            sx, sy = start[0] + start[2], start[1] + node_height // 2
            edge_class = "dr-trace-edge dr-trace-edge--dashed" if str(edge.get("style") or "").strip() == "dashed" else "dr-trace-edge"
            if str(edge.get("style") or "").strip() == "dashed":
                dashed_incoming.append(edge)
            else:
                solid_incoming.append(edge)
            if layout_orientation == "horizontal" and is_url_to_meeting_edge(edge):
                start_bottom_x = start[0] + start[2] / 2
                start_bottom_y = start[1] + node_height
                target_bottom_x = target[0] + target[2] / 2
                target_bottom_y = target[1] + node_height
                outside_y = height - 8
                paths.append(
                    f'<path class="{edge_class}" data-source-edge="{html_attr(key)}" '
                    f'd="M {start_bottom_x:.1f} {start_bottom_y} '
                    f'C {start_bottom_x:.1f} {outside_y}, {start_bottom_x:.1f} {outside_y}, {start_bottom_x + 72:.1f} {outside_y} '
                    f'L {target_bottom_x:.1f} {outside_y} '
                    f'C {target_bottom_x:.1f} {outside_y}, {target_bottom_x:.1f} {outside_y}, {target_bottom_x:.1f} {target_bottom_y}"></path>'
                )
            else:
                mid = sx + max(24, (junction_x - sx) // 2)
                paths.append(
                    f'<path class="{edge_class}" data-source-edge="{html_attr(key)}" d="M {sx} {sy} C {mid} {sy}, {mid} {junction_y}, {junction_x} {junction_y}"></path>'
                )
        paths.append(
            f'<path class="dr-trace-edge" d="M {junction_x} {junction_y} L {ex} {ey}" marker-end="url(#{marker_id})"></path>'
        )
        labels = {
            str(edge.get("relation") or "").strip()
            for edge in incoming
            if str(edge.get("relation") or "").strip()
        }
        if len(labels) == 1:
            label = next(iter(labels))
            paths.append(edge_label_markup(junction_x - 18, ey - (16 if dashed_incoming else 12), label))
            if dashed_incoming:
                paths.append(edge_label_markup(junction_x - 18, ey + 16, "佐證"))
        elif dashed_incoming:
            solid_labels = {
                str(edge.get("relation") or "").strip()
                for edge in solid_incoming
                if str(edge.get("relation") or "").strip()
            }
            if len(solid_labels) == 1:
                paths.append(edge_label_markup(junction_x - 18, ey - 16, next(iter(solid_labels))))
            paths.append(edge_label_markup(junction_x - 18, ey + 16, "佐證"))
        return "".join(paths)

    edges: List[str] = []
    valid_edges = selected_layout["valid_edges"]
    rendered_edge_keys: set[str] = set()
    source_url_edges = [edge for edge in valid_edges if is_source_to_url_edge(edge)]
    source_url_edges_by_source: Dict[str, List[Dict[str, Any]]] = {}
    for edge in source_url_edges:
        source_url_edges_by_source.setdefault(str(edge.get("from") or "").strip(), []).append(edge)
    for source_id, outgoing in sorted(source_url_edges_by_source.items()):
        target_ids = {
            str(edge.get("to") or "").strip()
            for edge in outgoing
            if str(edge.get("to") or "").strip() in node_positions
        }
        if len(target_ids) <= 1 or source_id not in node_positions:
            continue
        edges.append(bundled_source_to_urls_paths(node_positions[source_id], outgoing))
        rendered_edge_keys.update(trace_topology_edge_key(edge) for edge in outgoing)
    source_url_edges_by_target: Dict[str, List[Dict[str, Any]]] = {}
    for edge in source_url_edges:
        if trace_topology_edge_key(edge) in rendered_edge_keys:
            continue
        source_url_edges_by_target.setdefault(str(edge.get("to") or "").strip(), []).append(edge)
    for target_id, incoming in sorted(source_url_edges_by_target.items()):
        if len(incoming) <= 1 or target_id not in node_positions:
            continue
        edges.append(bundled_source_to_url_paths(node_positions[target_id], incoming))
        rendered_edge_keys.update(trace_topology_edge_key(edge) for edge in incoming)
    url_meeting_edges = [edge for edge in valid_edges if is_url_to_meeting_edge(edge)]
    if len(url_meeting_edges) > 1:
        edges.append(bundled_vertical_paths(url_meeting_edges, label="正式化"))
        rendered_edge_keys.update(trace_topology_edge_key(edge) for edge in url_meeting_edges)
    url_evidence_edges = [edge for edge in valid_edges if is_url_to_evidence_edge(edge)]
    evidence_edges_by_target: Dict[str, List[Dict[str, Any]]] = {}
    for edge in url_evidence_edges:
        evidence_edges_by_target.setdefault(str(edge.get("to") or "").strip(), []).append(edge)
    direct_feedback_edges = [
        edge for edge in url_evidence_edges
        if str(edge.get("to") or "").strip() in direct_url_feedback_node_ids
    ]
    single_url_model_edges = [
        edge for edge in url_evidence_edges
        if len(evidence_edges_by_target.get(str(edge.get("to") or "").strip()) or []) == 1
        and str(node_by_id.get(str(edge.get("to") or "").strip(), {}).get("type") or "").strip() == "System Model"
        and len([
            value for value in (
                node_by_id.get(str(edge.get("to") or "").strip(), {}).get("related_sources") or []
            )
            if str(value).strip().startswith("URL-")
        ]) <= 1
    ]
    direct_side_evidence_edges = direct_feedback_edges + single_url_model_edges
    rendered_edge_keys.update(
        trace_topology_edge_key(edge)
        for edge in url_evidence_edges
        if edge not in direct_side_evidence_edges
    )
    if direct_feedback_edges:
        edges.append(bundled_side_evidence_paths(direct_feedback_edges, label="領域研究"))
        rendered_edge_keys.update(trace_topology_edge_key(edge) for edge in direct_feedback_edges)
    if single_url_model_edges:
        edges.append(bundled_side_evidence_paths(single_url_model_edges, label="建模"))
        rendered_edge_keys.update(trace_topology_edge_key(edge) for edge in single_url_model_edges)
    if not single_url_mode:
        edges.append(support_summary_to_meeting_path())
    incoming_by_target: Dict[str, List[Dict[str, Any]]] = {}
    for edge in valid_edges:
        if trace_topology_edge_key(edge) in rendered_edge_keys:
            continue
        incoming_by_target.setdefault(str(edge.get("to") or ""), []).append(edge)
    visible_conflict_ids = {
        str(node_id)
        for node_id in node_positions
        if str(node_by_id.get(str(node_id), {}).get("type") or "").strip() == "Conflict"
    }
    bundled_targets = {
        target
        for target, incoming in incoming_by_target.items()
        if (
            len(incoming) >= 3
        )
        or (
            len(incoming) >= 2
            and str(node_by_id.get(target, {}).get("type") or "").strip() == "Conflict"
            and {
                str(edge.get("relation") or "").strip()
                for edge in incoming
                if str(edge.get("relation") or "").strip()
            } == {"衝突"}
        )
        or (
            len(incoming) >= 2
            and str(node_by_id.get(target, {}).get("type") or "").strip() == "Meeting Discussion"
            and {
                str(edge.get("relation") or "").strip()
                for edge in incoming
                if str(edge.get("relation") or "").strip()
            } == {"正式化"}
        )
        or (
            len(incoming) >= 2
            and str(node_by_id.get(target, {}).get("type") or "").strip() == "Meeting Discussion"
            and {
                str(node_by_id.get(str(edge.get("from") or "").strip(), {}).get("type") or "").strip()
                for edge in incoming
                if str(edge.get("from") or "").strip()
            } == {"Conflict"}
            and {
                str(edge.get("relation") or "").strip()
                for edge in incoming
                if str(edge.get("relation") or "").strip()
            } == {"解決"}
        )
    }
    for target in sorted(bundled_targets):
        incoming = incoming_by_target[target]
        target_type = str(node_by_id.get(target, {}).get("type") or "").strip()
        incoming_labels = {
            str(edge.get("relation") or "").strip()
            for edge in incoming
            if str(edge.get("relation") or "").strip()
        }
        if target_type == "Conflict" and incoming_labels == {"衝突"}:
            edges.append(bundled_conflict_paths(node_positions[target], incoming))
        elif target_type == "Meeting Discussion" and incoming_labels == {"解決"}:
            edges.append(bundled_resolution_paths(node_positions[target], incoming))
        elif target_type == "Meeting Discussion" and incoming_labels == {"正式化"}:
            edges.append(bundled_vertical_paths(incoming, label="正式化"))
        else:
            edges.append(bundled_edge_paths(node_positions[target], incoming))
        rendered_edge_keys.update(trace_topology_edge_key(edge) for edge in incoming_by_target[target])
    direct_conflict_label_targets: set[str] = set()
    for edge in valid_edges:
        if trace_topology_edge_key(edge) in rendered_edge_keys:
            continue
        if str(edge.get("to") or "") in bundled_targets:
            continue
        key = trace_topology_edge_key(edge)
        start = node_positions[str(edge.get("from") or "").strip()]
        end = node_positions[str(edge.get("to") or "").strip()]
        if layout_orientation == "horizontal" and is_url_to_meeting_edge(edge):
            edges.append(outside_url_to_meeting_path(
                start,
                end,
                label=str(edge.get("relation") or ""),
                source_edge=key,
            ))
        elif edge in single_url_model_edges:
            edges.append(edge_path(
                start,
                end,
                label="建模",
                source_edge=key,
                style=str(edge.get("style") or ""),
            ))
        else:
            target_id = str(edge.get("to") or "").strip()
            source_id = str(edge.get("from") or "").strip()
            is_multi_conflict_edge = (
                len(visible_conflict_ids) > 1
                and str(edge.get("relation") or "").strip() == "衝突"
                and source_id.startswith("URL-")
                and target_id in visible_conflict_ids
            )
            if is_multi_conflict_edge:
                direct_conflict_label_targets.add(target_id)
            edges.append(edge_path(
                start,
                end,
                label="" if is_multi_conflict_edge else str(edge.get("relation") or ""),
                source_edge=key,
                style=str(edge.get("style") or ""),
            ))
        rendered_edge_keys.add(key)
    for target_id in sorted(direct_conflict_label_targets):
        target = node_positions.get(target_id)
        if not target:
            continue
        edges.append(edge_label_markup(target[0] + target[2] / 2, target[1] - 14, "衝突"))
    validate_rendered_trace_edges(valid_edges, rendered_edge_keys)

    return (
        '<div class="dr-trace-topology">'
        '<div class="dr-trace-topology__graph">'
        f'<svg class="dr-trace-topology__svg" viewBox="0 0 {view_width} {height}" height="{height}" '
        f'data-layout-quality="{layout_quality}" data-layout-attempt="{selected_attempt_index + 1}" '
        f'data-compact-labels="{"true" if compact_label_mode else "false"}" '
        'role="img" aria-label="Trace topology">'
        f'<defs><marker id="{marker_id}" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">'
        '<path d="M0,0 L0,6 L9,3 z" fill="#c8d2e2"></path>'
        '</marker></defs>'
        + "".join(edges)
        + "".join(node_markup)
        + '</svg>'
        + "</div></div>"
    )


def normalize_dr_model_path(value: Any) -> str:
    image_path = str(value or "").strip()
    if not image_path:
        return ""
    image_path = re.sub(r"^\./", "", image_path)
    image_path = re.sub(r"^(?:\.\./)+", "", image_path)
    image_path = re.sub(r"^(?:artifact/|output/)?models/", "", image_path)
    return f"./models/{image_path}" if image_path else ""


def dr_description_field_text(req: Dict[str, Any], srs_id: str, block: str) -> str:
    if srs_id.startswith("FR-"):
        existing = re.search(
            r"(?ms)^\*\*Acceptance Criteria\*\*:\s*\n(?P<body>.*?)(?=^\*\*[A-Za-z ]+\*\*:|^#{3,6}\s+|\Z)",
            block,
        )
        if existing:
            body = existing.group("body").strip()
            return f"**Acceptance Criteria**:\n{body}" if body else ""
        criteria = [
            str(item or "").strip()
            for item in (req.get("acceptance_criteria") or [])
            if str(item or "").strip()
        ]
        if criteria:
            return (
                "**Acceptance Criteria**:\n"
                + "\n".join(f"{index}. {item}" for index, item in enumerate(criteria, start=1))
            )
    if srs_id.startswith("NFR-"):
        existing = re.search(r"(?m)^\*\*Metric\*\*:\s*(?P<body>.+?)\s*$", block)
        if existing:
            return f"**Metric**: {existing.group('body').strip()}"
        metric = str(req.get("metric") or "").strip()
        if metric:
            return f"**Metric**: {metric}"
    return ""


def place_dr_description_field(block: str, field_text: str) -> str:
    if not field_text:
        return block
    block = re.sub(
        r"(?ms)^\*\*Acceptance Criteria\*\*:\s*\n.*?(?=^\*\*[A-Za-z ]+\*\*:|^#{3,6}\s+|\Z)",
        "",
        block,
    )
    block = re.sub(r"(?m)^\*\*Metric\*\*:\s*.+?\s*$\n?", "", block)
    block = re.sub(
        r"(?m)^(\*\*Description\*\*:[^\n]*)(?:\n+)?",
        lambda match_obj: match_obj.group(1).rstrip() + "\n\n" + field_text.strip() + "\n\n",
        block,
        count=1,
    )
    return re.sub(r"\n{4,}", "\n\n\n", block)


TRACE_STEP_HEADING_RE = (
    r"(?m)^(?:Stakeholder|User Requirement|Conflict|Feedback|System Model|"
    r"Meeting Discussion|Requirement Formation)\s*$"
)


def insert_dr_trace_topology(block: str, topology: str) -> str:
    topology = str(topology or "").strip()
    if not topology:
        return block
    block = re.sub(r"(?m)^####\s+Trace Explanation\s*$\n*", "", block)
    topology_section = "\n\n" + topology + "\n\n"
    trace_match = re.search(TRACE_STEP_HEADING_RE, block)
    if trace_match:
        return (
            block[: trace_match.start()].rstrip()
            + topology_section
            + "#### Trace Explanation\n\n"
            + block[trace_match.start() :].lstrip()
        )
    return block.rstrip() + topology_section.rstrip()


def inject_trace_topologies(body: str, requirements: List[Dict[str, Any]]) -> str:
    text = str(body or "").strip()
    req_by_srs_id = {
        str(req.get("srs_id") or "").strip(): req
        for req in requirements or []
        if isinstance(req, dict) and str(req.get("srs_id") or "").strip()
    }
    blocks = [
        block.strip()
        for block in re.split(
            r"(?m)(?=^###\s*(?:FR|NFR|CON)-\d+\s*[:：])",
            text,
        )
        if block.strip()
    ]
    out: List[str] = []
    for block in blocks:
        match = re.search(r"(?m)^###\s*((?:FR|NFR|CON)-\d+)\s*[:：]", block)
        req = req_by_srs_id.get(match.group(1)) if match else None
        topology = ""
        if req:
            srs_id = str(req.get("srs_id") or "").strip()
            block = place_dr_description_field(block, dr_description_field_text(req, srs_id, block))
            try:
                topology = render_trace_topology(req)
            except Exception as exc:
                topology = render_trace_links_fallback(req, exc)
        if topology and "dr-trace-topology" not in block:
            block = insert_dr_trace_topology(block, topology)
        block = re.sub(r"(?m)^#{1,6}\s+Topology\s*$\n*", "", block)
        out.append(block)
    return "\n\n".join(out).strip()
