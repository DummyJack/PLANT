import re
from typing import Any, Dict, List

from .render import render_trace_links_fallback, render_trace_topology


def render_trace_topology_assets() -> str:
    return """
<style>
.dr-trace-topology {
  margin: 18px 0 22px;
  padding: 0;
}
.dr-trace-topology__graph {
  position: relative;
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
<script data-cfasync="false">
(() => {
  const modal = document.querySelector('.dr-trace-modal');
  if (!modal || modal.dataset.ready === 'true') return;
  modal.dataset.ready = 'true';
  const svgStyle = `
    .dr-trace-edge { fill: none; stroke: #c8d2e2; stroke-width: 1.5; }
    .dr-trace-edge--dashed { stroke-dasharray: 5 5; }
    .dr-trace-edge-label { fill: #66758f; font-size: 12px; font-weight: 650; dominant-baseline: middle; pointer-events: none; }
    .dr-trace-edge-label-bg { fill: #fbfcfe; stroke: #dfe5ef; stroke-width: 1; pointer-events: none; }
    .dr-trace-section-label { fill: #66758f; font-size: 13px; font-weight: 700; pointer-events: none; }
    .dr-trace-support-box { fill: #fbfcfe; stroke: #dfe5ef; stroke-width: 1.4; }
    .dr-trace-node rect { fill: #fff; stroke: #cfd7e4; stroke-width: 1.4; }
    .dr-trace-node text { fill: #243044; font-size: 14px; font-weight: 650; pointer-events: none; }
    .dr-trace-node--target rect { fill: #243044; stroke: #243044; }
    .dr-trace-node--target text { fill: #fff; font-size: 14px; font-weight: 750; }
  `;
  const title = modal.querySelector('.dr-trace-modal__title');
  const body = modal.querySelector('.dr-trace-modal__body');
  const sanitizeHtml = (source) => {
    const allowedTags = new Set([
      'A', 'BLOCKQUOTE', 'BR', 'CODE', 'DIV', 'EM', 'H2', 'H3', 'H4', 'H5',
      'IMG', 'LI', 'OL', 'P', 'PRE', 'SPAN', 'STRONG', 'TABLE', 'TBODY', 'TD',
      'TH', 'THEAD', 'TR', 'UL'
    ]);
    const blockedTags = new Set(['IFRAME', 'OBJECT', 'SCRIPT', 'STYLE', 'TEMPLATE']);
    const parsed = new DOMParser().parseFromString(source || '', 'text/html');
    const clean = (parent) => {
      Array.from(parent.children).forEach((element) => {
        if (blockedTags.has(element.tagName)) {
          element.remove();
          return;
        }
        if (!allowedTags.has(element.tagName)) {
          clean(element);
          element.replaceWith(...Array.from(element.childNodes));
          return;
        }
        Array.from(element.attributes).forEach((attribute) => {
          const name = attribute.name.toLowerCase();
          const allowed = name === 'class'
            || (element.tagName === 'A' && ['href', 'title'].includes(name))
            || (element.tagName === 'IMG' && ['src', 'alt', 'title'].includes(name))
            || (['TD', 'TH'].includes(element.tagName) && ['colspan', 'rowspan'].includes(name));
          if (!allowed) element.removeAttribute(attribute.name);
        });
        if (element.tagName === 'A' && element.hasAttribute('href')) {
          try {
            const url = new URL(element.getAttribute('href'), document.baseURI);
            if (!['http:', 'https:', 'mailto:'].includes(url.protocol)) throw new Error('unsafe link');
            element.href = url.href;
            element.target = '_blank';
            element.rel = 'noopener noreferrer';
          } catch (error) {
            element.removeAttribute('href');
          }
        }
        if (element.tagName === 'IMG' && element.hasAttribute('src')) {
          try {
            const raw = element.getAttribute('src') || '';
            const url = new URL(raw, document.baseURI);
            const safeData = url.protocol === 'data:' && /^data:image\//i.test(raw);
            const safeLocal = ['http:', 'https:'].includes(url.protocol) && url.origin === location.origin;
            const safeOfflineModel = location.protocol === 'file:'
              && url.protocol === 'file:'
              && /^\.\/models\/[^/\\?#]+\.(?:png|jpe?g|gif|webp|svg)(?:[?#].*)?$/i.test(raw);
            if (!safeData && !safeLocal && !safeOfflineModel) throw new Error('unsafe image');
            element.src = url.href;
          } catch (error) {
            element.remove();
            return;
          }
        }
        clean(element);
      });
    };
    clean(parsed.body);
    return parsed.body.innerHTML;
  };
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
      body.innerHTML = sanitizeHtml(content);
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
    topology_section = "\n\n#### Requirements Traceability Map\n\n" + topology + "\n\n"
    trace_heading = re.search(r"(?m)^####\s+Trace Explanation\s*$", block)
    if trace_heading:
        return (
            block[: trace_heading.start()].rstrip()
            + topology_section
            + block[trace_heading.start() :].lstrip()
        )
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
        if topology and "dr-trace-topology" in block:
            block = re.sub(
                r'(?m)^<div class="dr-trace-topology">.*?</svg></div></div>\s*$',
                "",
                block,
            ).strip()
            block = re.sub(
                r"(?m)^#{1,6}\s+Requirements Traceability Map\s*$\n*",
                "",
                block,
            ).strip()
        if topology:
            block = insert_dr_trace_topology(block, topology)
        block = re.sub(r"(?m)^#{1,6}\s+Topology\s*$\n*", "", block)
        out.append(block)
    return "\n\n".join(out).strip()

