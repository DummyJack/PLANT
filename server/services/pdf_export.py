from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from fastapi import HTTPException
from weasyprint import CSS, HTML
from weasyprint.urls import URLFetcher

from server.services.security import resolve_project_file
from storage.markdown import save_markdown_as_html


PDF_EXPORT_PATHS = (
    re.compile(r"^output/[^/]+\.md$", re.IGNORECASE),
    re.compile(r"^artifact/drafts/[^/]+\.md$", re.IGNORECASE),
)
SRS_MARKDOWN_PATH = "output/srs.md"
SRS_PDF_FILENAME = "srs-with-design-rationale.pdf"


@dataclass(frozen=True)
class PdfExport:
    content: bytes
    filename: str


PRINT_CSS = """
@page {
  size: A4;
  margin: 14mm 12mm 17mm;
  @bottom-center {
    content: counter(page) " / " counter(pages);
    color: #64748b;
    font-size: 8pt;
  }
}
html, body {
  background: white !important;
}
body, body.has-floating-toc {
  margin: 0 !important;
  padding: 0 !important;
  font-family: "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", sans-serif;
  color: #0f172a;
  font-size: 9.5pt;
  line-height: 1.55;
}
.md-body {
  width: auto !important;
  max-width: none !important;
  margin: 0 !important;
}
.pdf-design-rationale {
  break-before: page;
  page-break-before: always;
}
.plant-floating-toc,
script,
.dr-trace-modal {
  display: none !important;
}
h1, h2, h3, h4, h5, h6 {
  break-after: avoid-page;
  page-break-after: avoid;
  color: #0f172a;
}
h1 { font-size: 20pt; }
h2 { font-size: 16pt; margin-top: 1.1em; }
h3 { font-size: 13pt; }
h4 { font-size: 11pt; }
p, li { orphans: 3; widows: 3; }
.table-wrap {
  overflow: visible !important;
  width: 100% !important;
}
table {
  width: 100% !important;
  table-layout: fixed !important;
  border-collapse: collapse;
  font-size: 7.5pt;
}
thead { display: table-header-group; }
tr, img, pre, blockquote { break-inside: avoid; page-break-inside: avoid; }
th, td {
  overflow-wrap: anywhere !important;
  word-break: break-word !important;
  white-space: normal !important;
  padding: 4px !important;
}
img, svg {
  max-width: 100% !important;
  height: auto !important;
}
img {
  max-height: 235mm !important;
  width: auto !important;
  object-fit: contain;
}
a { color: #2563eb; text-decoration: underline; }
.srs-dr-ref,
h4 a[href*="dr#"],
li a[href*="dr#con-"] {
  display: inline !important;
  margin-left: 0.25em !important;
  transform: none !important;
  font-size: 0.72em !important;
}
"""


def _allowed_export_path(path: str) -> str:
    normalized = str(path or "").strip().replace("\\", "/")
    if not any(pattern.fullmatch(normalized) for pattern in PDF_EXPORT_PATHS):
        raise HTTPException(
            status_code=400,
            detail="PDF export only supports Output and Draft Markdown files",
        )
    return normalized


def _existing_html_path(project_dir: Path, markdown_path: str) -> Path | None:
    output = re.fullmatch(r"output/(.+)\.md", markdown_path, re.IGNORECASE)
    if output:
        candidate = project_dir / "results" / f"{output.group(1)}.html"
        return candidate if candidate.is_file() else None
    draft = re.fullmatch(r"artifact/drafts/(.+)\.md", markdown_path, re.IGNORECASE)
    if draft:
        candidate = project_dir / "results" / "drafts" / f"{draft.group(1)}.html"
        return candidate if candidate.is_file() else None
    return None


def _find_model(project_dir: Path, encoded_name: str) -> Path | None:
    name = Path(unquote(encoded_name.split("?", 1)[0])).name
    if not name:
        return None
    for folder in ("results", "output", "artifact"):
        candidate = project_dir / folder / "models" / name
        if candidate.is_file():
            return candidate.resolve()
    return None


def _localize_model_urls(html: str, project_dir: Path, project_id: str) -> str:
    public_prefix = f"/{project_id}/manual/models/"
    relative_model = re.compile(r"^(?:(?:\.\.?/)+)?models/(?P<name>.+)$")

    def replace(match: re.Match[str]) -> str:
        value = match.group("value")
        if value.startswith(public_prefix):
            name = value[len(public_prefix):]
        else:
            relative = relative_model.fullmatch(value)
            if not relative:
                return match.group(0)
            name = relative.group("name")
        model = _find_model(project_dir, name)
        if not model:
            return match.group(0)
        return f'{match.group("prefix")}{model.as_uri()}{match.group("quote")}'

    return re.sub(
        r'(?P<prefix>\b(?:src|href)=(?P<quote>["\']))(?P<value>[^"\']+)(?P=quote)',
        replace,
        html,
    )


def _absolute_document_links(html: str, project_id: str, public_base_url: str) -> str:
    base = public_base_url.rstrip("/")
    manual = f"{base}/{project_id}/manual"
    html = html.replace(f'/{project_id}/manual/srs', f"{manual}/srs")
    html = html.replace(f'/{project_id}/manual/dr', f"{manual}/dr")
    return html


def _document_body(html: str) -> tuple[str, str, str]:
    marker = '<div class="md-body">'
    before, found, remainder = html.partition(marker)
    if not found:
        raise HTTPException(status_code=500, detail="Document body is unavailable")
    body, closing, after = remainder.rpartition("</div>")
    if not closing:
        raise HTTPException(status_code=500, detail="Document body is incomplete")
    return before + found, body, closing + after


def _prefix_fragment_ids(html: str, prefix: str) -> str:
    html = re.sub(
        r'\bid=(?P<quote>["\'])(?P<id>[^"\']+)(?P=quote)',
        lambda match: (
            f'id={match.group("quote")}{prefix}{match.group("id")}{match.group("quote")}'
        ),
        html,
    )
    html = re.sub(
        r'\bhref=(?P<quote>["\'])#(?P<id>[^"\']+)(?P=quote)',
        lambda match: (
            f'href={match.group("quote")}#{prefix}{match.group("id")}{match.group("quote")}'
        ),
        html,
    )
    return re.sub(r"url\(#([^)]+)\)", rf"url(#{prefix}\1)", html)


def _combined_srs_design_rationale_html(
    srs_html: str,
    design_rationale_html: str,
    project_id: str,
) -> str:
    document_start, srs_body, document_end = _document_body(srs_html)
    _, dr_body, _ = _document_body(design_rationale_html)
    dr_body = _prefix_fragment_ids(dr_body, "dr-")
    srs_body = re.sub(
        rf'href=(["\'])/{re.escape(project_id)}/manual/dr#([^"\']+)\1',
        lambda match: f'href={match.group(1)}#dr-{match.group(2)}{match.group(1)}',
        srs_body,
    )
    combined_body = (
        srs_body
        + '\n<section class="pdf-design-rationale">\n'
        + dr_body
        + "\n</section>\n"
    )
    return document_start + combined_body + document_end


def _inline_trace_svg_styles(html: str) -> str:
    """Use SVG presentation attributes for PDF engines that ignore HTML CSS in SVG."""

    def style_node(match: re.Match[str]) -> str:
        attrs = match.group("attrs")
        body = match.group("body")
        target = "dr-trace-node--target" in attrs
        rect_fill = "#243044" if target else "#ffffff"
        rect_stroke = "#243044" if target else "#cfd7e4"
        text_fill = "#ffffff" if target else "#243044"
        body = re.sub(
            r"<rect\b",
            f'<rect fill="{rect_fill}" stroke="{rect_stroke}" stroke-width="1.4"',
            body,
            count=1,
        )
        body = re.sub(
            r"<text\b",
            f'<text fill="{text_fill}" font-family="sans-serif" font-size="14" font-weight="700"',
            body,
            count=1,
        )
        return f'<g{attrs}>{body}</g>'

    html = re.sub(
        r'<g(?P<attrs>[^>]*class="[^"]*dr-trace-node[^"]*"[^>]*)>(?P<body>.*?)</g>',
        style_node,
        html,
        flags=re.DOTALL,
    )
    html = re.sub(
        r'<path class="dr-trace-edge([^"]*)"',
        r'<path class="dr-trace-edge\1" fill="none" stroke="#c8d2e2" stroke-width="1.5"',
        html,
    )
    html = re.sub(
        r'<rect class="dr-trace-edge-label-bg"',
        '<rect class="dr-trace-edge-label-bg" fill="#fbfcfe" stroke="#dfe5ef" stroke-width="1"',
        html,
    )
    html = re.sub(
        r'<text class="dr-trace-edge-label"',
        '<text class="dr-trace-edge-label" fill="#66758f" font-family="sans-serif" font-size="12"',
        html,
    )
    return html


class ProjectUrlFetcher(URLFetcher):
    def __init__(self, project_dir: Path):
        super().__init__(allowed_protocols={"data", "file"}, allow_redirects=False)
        self.project_root = project_dir.resolve()

    def fetch(self, url: str, headers=None):
        parsed = urlparse(url)
        if parsed.scheme == "file":
            path = Path(unquote(parsed.path)).resolve()
            try:
                path.relative_to(self.project_root)
            except ValueError as exc:
                raise ValueError("PDF resource is outside the project") from exc
        return super().fetch(url, headers)


def _render_pdf(
    *,
    html_path: Path,
    source: Path,
    project_dir: Path,
    project_id: str,
    markdown_path: str,
    public_base_url: str,
) -> PdfExport:
    html = html_path.read_text(encoding="utf-8")
    filename = f"{source.stem}.pdf"
    if markdown_path.lower() == SRS_MARKDOWN_PATH:
        dr_html_path = project_dir / "results" / "design_rationale.html"
        if not dr_html_path.is_file():
            raise HTTPException(
                status_code=409,
                detail="Design Rationale HTML is required for the combined SRS PDF",
            )
        html = _combined_srs_design_rationale_html(
            html,
            dr_html_path.read_text(encoding="utf-8"),
            project_id,
        )
        filename = SRS_PDF_FILENAME

    html = _localize_model_urls(html, project_dir, project_id)
    html = _absolute_document_links(html, project_id, public_base_url)
    html = _inline_trace_svg_styles(html)
    try:
        content = HTML(
            string=html,
            base_url=html_path.parent.as_uri() + "/",
            url_fetcher=ProjectUrlFetcher(project_dir),
        ).write_pdf(stylesheets=[CSS(string=PRINT_CSS)])
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Unable to generate PDF") from exc
    return PdfExport(content=content, filename=filename)


def render_markdown_pdf(
    *,
    base_dir: Path,
    project_dir: Path,
    project_id: str,
    markdown_path: str,
    public_base_url: str,
) -> PdfExport:
    normalized_path = _allowed_export_path(markdown_path)
    source = resolve_project_file(base_dir, project_dir, normalized_path)
    if not source.is_file():
        raise HTTPException(status_code=404, detail="Markdown file not found")

    def render(html_path: Path) -> PdfExport:
        return _render_pdf(
            html_path=html_path,
            source=source,
            project_dir=project_dir,
            project_id=project_id,
            markdown_path=normalized_path,
            public_base_url=public_base_url,
        )

    existing_html = _existing_html_path(project_dir, normalized_path)
    if existing_html:
        return render(existing_html)

    with tempfile.TemporaryDirectory(prefix="plant-pdf-") as temp_dir:
        html_path = Path(temp_dir) / f"{source.stem}.html"
        save_markdown_as_html(
            source,
            html_path,
            html_root=html_path.parent,
            project_id=project_id,
        )
        return render(html_path)
