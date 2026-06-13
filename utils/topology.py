# Renders trace topology diagrams for Design Rationale documents.
import base64
import html
import re
from typing import Any, Dict, List, Tuple


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
  overflow-x: auto;
}
.dr-trace-topology__svg {
  display: block;
  min-width: 1120px;
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
  .dr-trace-topology__svg {
    min-width: 1040px;
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


def render_trace_links_fallback(requirement: Dict[str, Any], error: Exception | None = None) -> str:
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
    marker_id = f"dr-trace-arrow-{re.sub(r'[^A-Za-z0-9_-]+', '-', target_id).strip('-').lower() or 'target'}"
    column_order = ["Source", "User Requirement", "Analysis", "Meeting", "Requirement"]
    groups: Dict[str, List[Dict[str, str]]] = {column: [] for column in column_order}
    for node in graph_nodes:
        column = str(node.get("column") or "").strip()
        if column not in groups:
            column = "Analysis"
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
        if str(node.get("column") or "").strip() == "Analysis":
            node_type = str(node.get("type") or "").strip()
            type_rank = {"Conflict": 0, "Feedback": 1, "System Model": 2}.get(node_type, 3)
        return (anchor, type_rank, node_index.get(node_id, 10**9))

    order_map: Dict[str, float] = {}
    for column in column_order:
        groups[column].sort(key=lambda node: node_rank(node, order_map))
        for index, node in enumerate(groups[column]):
            node_id = str(node.get("id") or "").strip()
            if node_id:
                order_map[node_id] = float(index)

    layout_attempts = [
        {
            "column_specs": [
                ("Source", 24, 180),
                ("User Requirement", 246, 210),
                ("Analysis", 510, 190),
                ("Meeting", 754, 190),
                ("Requirement", 994, 180),
            ],
            "row_gap": 18,
            "view_width": 1200,
        },
        {
            "column_specs": [
                ("Source", 24, 190),
                ("User Requirement", 274, 220),
                ("Analysis", 580, 205),
                ("Meeting", 870, 205),
                ("Requirement", 1148, 190),
            ],
            "row_gap": 30,
            "view_width": 1368,
        },
        {
            "column_specs": [
                ("Source", 24, 200),
                ("User Requirement", 308, 235),
                ("Analysis", 670, 220),
                ("Meeting", 1010, 220),
                ("Requirement", 1320, 200),
            ],
            "row_gap": 42,
            "view_width": 1550,
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
        column_specs = attempt["column_specs"]
        row_gap = int(attempt["row_gap"])
        max_nodes = max(len(groups[name]) for name, _, _ in column_specs)
        height = top + max_nodes * node_height + max(0, max_nodes - 1) * row_gap + 18
        node_positions: Dict[str, tuple[int, int, int]] = {}
        node_markup: List[str] = []
        for name, x, width in column_specs:
            count = len(groups[name])
            column_height = count * node_height + max(0, count - 1) * row_gap
            y_start = top + max(0, (height - top - 18 - column_height) // 2)
            for index, node in enumerate(groups[name]):
                y = y_start + index * (node_height + row_gap)
                node_id = str(node.get("id") or "").strip()
                node_positions[node_id] = (x, y, width)
                node_markup.append(trace_topology_svg_node(
                    node_id=node_id,
                    label=str(node.get("label") or node_id),
                    node_type=str(node.get("type") or ""),
                    title=str(node.get("title") or node_id),
                    content=str(node.get("content") or ""),
                    content_format=str(node.get("content_format") or "text"),
                    x=x,
                    y=y,
                    width=width,
                    target=name == "Requirement",
                ))
        valid_edges = collect_valid_trace_edges(edges_for_layout, node_positions)
        return {
            "height": height,
            "node_positions": node_positions,
            "node_markup": node_markup,
            "valid_edges": valid_edges,
            "view_width": int(attempt["view_width"]),
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
        main_chain_labels = {"整理", "解決", "正式化", "釐清"}
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
    layout_quality = "needs-review" if selected_layout["issues"] else "ok"

    def edge_path(
        start: tuple[int, int, int],
        end: tuple[int, int, int],
        label: str = "",
        source_edge: str = "",
        style: str = "",
    ) -> str:
        sx, sy = start[0] + start[2], start[1] + node_height // 2
        ex, ey = end[0], end[1] + node_height // 2
        mid = sx + max(24, (ex - sx) // 2)
        source_attr = f' data-source-edge="{html_attr(source_edge)}"' if source_edge else ""
        edge_class = "dr-trace-edge dr-trace-edge--dashed" if str(style or "").strip() == "dashed" else "dr-trace-edge"
        path = f'<path class="{edge_class}"{source_attr} d="M {sx} {sy} C {mid} {sy}, {mid} {ey}, {ex} {ey}" marker-end="url(#{marker_id})"></path>'
        clean_label = str(label or "").strip()
        if not clean_label:
            return path
        lx = (sx + ex) / 2
        ly = (sy + ey) / 2 - 10
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

    def bundled_edge_paths(target: tuple[int, int, int], incoming: List[Dict[str, Any]]) -> str:
        ex, ey = target[0], target[1] + node_height // 2
        junction_x = ex - 28
        junction_y = ey
        paths: List[str] = []
        for edge in incoming:
            key = trace_topology_edge_key(edge)
            start = node_positions[str(edge.get("from") or "").strip()]
            sx, sy = start[0] + start[2], start[1] + node_height // 2
            mid = sx + max(24, (junction_x - sx) // 2)
            edge_class = "dr-trace-edge dr-trace-edge--dashed" if str(edge.get("style") or "").strip() == "dashed" else "dr-trace-edge"
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
            paths.append(edge_label_markup(junction_x - 18, ey - 12, label))
        return "".join(paths)

    edges: List[str] = []
    valid_edges = selected_layout["valid_edges"]
    rendered_edge_keys: set[str] = set()
    incoming_by_target: Dict[str, List[Dict[str, Any]]] = {}
    for edge in valid_edges:
        incoming_by_target.setdefault(str(edge.get("to") or ""), []).append(edge)
    bundled_targets = {
        target
        for target, incoming in incoming_by_target.items()
        if len(incoming) >= 3
    }
    for target in sorted(bundled_targets):
        edges.append(bundled_edge_paths(node_positions[target], incoming_by_target[target]))
        rendered_edge_keys.update(trace_topology_edge_key(edge) for edge in incoming_by_target[target])
    for edge in valid_edges:
        if str(edge.get("to") or "") in bundled_targets:
            continue
        key = trace_topology_edge_key(edge)
        edges.append(edge_path(
            node_positions[str(edge.get("from") or "").strip()],
            node_positions[str(edge.get("to") or "").strip()],
            label=str(edge.get("relation") or ""),
            source_edge=key,
            style=str(edge.get("style") or ""),
        ))
        rendered_edge_keys.add(key)
    validate_rendered_trace_edges(valid_edges, rendered_edge_keys)
    layout_notice = ""
    if layout_quality != "ok" or compact_label_mode:
        notice = "Trace topology layout needs review."
        if compact_label_mode:
            notice = "Trace topology labels were simplified for readability."
        layout_notice = f'<p class="dr-trace-fallback__warning">{html_attr(notice)}</p>'

    return (
        '<div class="dr-trace-topology">'
        '<div class="dr-trace-topology__graph">'
        f'{layout_notice}'
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
            try:
                topology = render_trace_topology(req)
            except Exception as exc:
                topology = render_trace_links_fallback(req, exc)
        if topology and "dr-trace-topology" not in block:
            block = re.sub(
                r"(?m)^(\*\*Description\*\*:[^\n]*(?:\n)?)",
                r"\1\n#### Topology\n\n" + topology + "\n",
                block,
                count=1,
            )
        elif "dr-trace-topology" in block and not re.search(r"(?m)^#{1,6}\s+Topology\s*$", block):
            block = re.sub(
                r"(<div class=\"dr-trace-topology\">)",
                "#### Topology\n\n" + r"\1",
                block,
                count=1,
            )
        out.append(block)
    return "\n\n---\n\n".join(out).strip()
