# Handles markdown logic for project artifact storage and file export behavior.
from html import escape
from pathlib import Path
from typing import Optional
from markdown_it import MarkdownIt
import re
from urllib.parse import unquote

from .atomic import atomic_write_text


# ========
# Defines clean llm output function for this module workflow.
# ========
def clean_llm_output(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1 :]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


def clean_markdown_for_storage(text: str) -> str:
    return re.sub(
        r"(?im)^\s*<span\b[^>]*\bid=(['\"])[^'\"]+\1[^>]*>\s*</span>\s*\n?",
        "",
        str(text or ""),
    )


def clean_heading_text(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", "", str(text or "")).strip()
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"[*_`]+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def markdown_heading_slug(text: str) -> str:
    slug = clean_heading_text(text).lower()
    srs_match = re.match(r"^(fr|nfr|con)-(\d+)\b", slug)
    if srs_match:
        return f"{srs_match.group(1)}-{srs_match.group(2)}"
    slug = re.sub(r"[^\w\u4e00-\u9fff]+", "-", slug, flags=re.UNICODE)
    slug = re.sub(r"-+", "-", slug).strip("-_")
    return slug or "section"


def remove_generated_markdown_toc(markdown_text: str) -> str:
    source = re.sub(
        r"(?s)\n?<!-- plant-toc:start -->.*?<!-- plant-toc:end -->\n?",
        "\n",
        markdown_text or "",
    )
    source = re.sub(
        r"(?s)\n?<!-- plant-floating-toc:start -->.*?<!-- plant-floating-toc:end -->\n?",
        "\n",
        source,
    )
    return source.strip() + "\n"


def markdown_toc_entries(
    markdown_text: str,
    *,
    min_level: int = 2,
    max_level: int = 3,
) -> list[tuple[int, str, str]]:
    entries: list[tuple[int, str, str]] = []
    in_fence = False
    seen: dict[str, int] = {}
    for line in (markdown_text or "").splitlines():
        if re.match(r"^\s*```", line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if not match:
            continue
        level = len(match.group(1))
        if level < min_level or level > max_level:
            continue
        title = clean_heading_text(re.sub(r"\s+#+\s*$", "", match.group(2)))
        if not title or title.lower() in {"目錄", "table of contents"}:
            continue
        base_slug = markdown_heading_slug(title)
        count = seen.get(base_slug, 0)
        seen[base_slug] = count + 1
        slug = base_slug if count == 0 else f"{base_slug}-{count + 1}"
        entries.append((level, title, slug))
    return entries


def insert_static_markdown_toc(markdown_text: str, *, title: str = "目錄") -> str:
    source = remove_generated_markdown_toc(markdown_text)
    entries = markdown_toc_entries(source)
    if not entries:
        return source
    toc_lines = [
        "<!-- plant-toc:start -->",
        "",
        f"## {title}",
        "",
    ]
    for level, heading, slug in entries:
        indent = "  " * max(0, level - 2)
        toc_lines.append(f"{indent}- [{heading}](#{slug})")
    toc_lines.extend(["", "<!-- plant-toc:end -->"])
    toc = "\n".join(toc_lines).strip()
    match = re.match(r"(?s)^(#\s+.+?\n)(.*)$", source)
    if match:
        return match.group(1).rstrip() + "\n\n" + toc + "\n\n" + match.group(2).lstrip()
    return toc + "\n\n" + source


def floating_toc_html(entries: list[tuple[int, str, str]]) -> str:
    if not entries:
        return ""
    links = []
    for level, heading, slug in entries:
        level_class = f"plant-floating-toc__link--level-{level}"
        links.append(
            f'<a class="plant-floating-toc__link {level_class}" href="#{escape(slug, quote=True)}">'
            f"{escape(heading)}</a>"
        )
    return (
        '<details class="plant-floating-toc" aria-label="目錄">'
        '<summary class="plant-floating-toc__title" aria-label="切換目錄"></summary>'
        '<div class="plant-floating-toc__items">'
        + "\n".join(links)
        + "</div></details>"
    )


def html_toc_entries(
    html_body: str,
    *,
    min_level: int = 2,
    max_level: int = 3,
) -> list[tuple[int, str, str]]:
    entries: list[tuple[int, str, str]] = []
    for match in re.finditer(
        r"""<h(?P<level>[1-6])(?P<attrs>[^>]*)>(?P<body>[\s\S]*?)</h(?P=level)>""",
        html_body or "",
    ):
        level = int(match.group("level"))
        if level < min_level or level > max_level:
            continue
        attrs = match.group("attrs") or ""
        id_match = re.search(r"""\sid=(['"])(?P<id>.*?)\1""", attrs)
        if not id_match:
            continue
        title = clean_heading_text(match.group("body"))
        if not title or title.lower() in {"目錄", "table of contents"}:
            continue
        entries.append((level, title, id_match.group("id")))
    return entries


def floating_toc_script() -> str:
    return """<script>
(function () {
  var links = Array.prototype.slice.call(document.querySelectorAll(".plant-floating-toc__link"));
  if (!links.length) return;
  var byId = new Map();
  links.forEach(function (link) {
    var id = decodeURIComponent((link.getAttribute("href") || "").replace(/^#/, ""));
    if (id) byId.set(id, link);
  });
  var headings = Array.prototype.slice.call(document.querySelectorAll("h2[id], h3[id]"))
    .filter(function (heading) { return byId.has(heading.id); });
  if (!headings.length) return;

  var activeId = "";
  function setActive(id) {
    if (!id || id === activeId) return;
    activeId = id;
    links.forEach(function (link) { link.classList.remove("is-active"); });
    var active = byId.get(id);
    if (active) {
      active.classList.add("is-active");
      active.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  }

  function updateActive() {
    var threshold = Math.max(80, window.innerHeight * 0.18);
    var current = headings[0];
    for (var i = 0; i < headings.length; i += 1) {
      if (headings[i].getBoundingClientRect().top <= threshold) {
        current = headings[i];
      } else {
        break;
      }
    }
    setActive(current.id);
  }

  var ticking = false;
  function requestUpdate() {
    if (ticking) return;
    ticking = true;
    window.requestAnimationFrame(function () {
      ticking = false;
      updateActive();
    });
  }

  window.addEventListener("scroll", requestUpdate, { passive: true });
  window.addEventListener("resize", requestUpdate);
  updateActive();
})();
</script>"""


# ========
# Defines markdown target dir function for this module workflow.
# ========
def markdown_target_dir(artifact_dir: Path, output_dir: Path, filename: str) -> Path:
    if re.fullmatch(r"conflict_report_v\d+\.md", filename):
        return artifact_dir / "report"
    if filename in {"srs.md", "design_rationale.md"}:
        return output_dir
    if filename.startswith("R") and filename.endswith(".md"):
        return artifact_dir / "MoM"
    return artifact_dir


# ========
# Defines save markdown function for this module workflow.
# ========
def save_markdown(
    artifact_dir: Path,
    output_dir: Path,
    content: str,
    filename: str,
) -> None:
    target_dir = markdown_target_dir(artifact_dir, output_dir, filename)
    target_dir.mkdir(parents=True, exist_ok=True)
    filepath = target_dir / filename
    atomic_write_text(filepath, clean_markdown_for_storage(content), encoding="utf-8")


# ========
# Defines load markdown function for this module workflow.
# ========
def load_markdown(artifact_dir: Path, output_dir: Path, filename: str) -> str:
    target_dir = markdown_target_dir(artifact_dir, output_dir, filename)
    filepath = target_dir / filename
    if not filepath.exists():
        return ""
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


# ========
# Defines markdown to html function for this module workflow.
# ========
def markdown_to_html(markdown_text: str) -> str:
    cleaned = clean_llm_output(markdown_text or "")
    return _MD_ENGINE.render(cleaned).strip()


# ========
# Defines compute models prefix function for this module workflow.
# ========
def compute_models_prefix(html_path: Path, html_root: Optional[Path]) -> str:
    if html_root:
        try:
            rel = html_path.parent.relative_to(html_root)
            depth = len(rel.parts)
        except ValueError:
            depth = 0
    else:
        depth = 0
    return "./" if depth == 0 else "../" * depth + ""


def model_image_version(target: str, html_path: Path) -> Optional[int]:
    image_name = unquote(str(target or "").split("?", 1)[0])
    if not image_name:
        return None
    image_path = html_path.parent / "models" / image_name
    if not image_path.exists() or not image_path.is_file():
        return None
    return int(image_path.stat().st_mtime_ns)


# ========
# Defines normalize model image paths function for this module workflow.
# ========
def normalize_model_image_paths(
    html_body: str,
    html_path: Path,
    html_root: Optional[Path] = None,
    project_id: Optional[str] = None,
) -> str:
    if project_id and html_path.name in {"srs.html", "design_rationale.html"}:
        prefix = f"/{project_id}/manual/models/"
    else:
        prefix = compute_models_prefix(html_path, html_root) + "models/"

    def repl(match: re.Match) -> str:
        target = match.group("target")
        suffix = ""
        version = model_image_version(target, html_path)
        if version is not None:
            suffix = f"?v={version}"
        return f'{match.group("attr")}={match.group(2)}{prefix}{target}{suffix}{match.group(4)}'

    return re.sub(
        r"""(?P<attr>src|href)=(['\"])(?:\.\./|\./)?(?:artifact/|output/)?(?:models/)(?P<target>[^\"'>\s]+)(?:\?[^\"']*)?(['\"])""",
        repl,
        html_body,
    )


# ========
# Defines model image markdown normalization function for this module workflow.
# ========
def normalize_model_image_markdown(markdown_text: str) -> str:
    image_ext = r"(?:png|jpg|jpeg|svg|webp|gif|bmp)"

    def repl(match: re.Match) -> str:
        path = match.group("path").strip()
        alt = Path(path).stem
        return f"![{alt}]({path})"

    return re.sub(
        rf"""(?m)^\s*(?:-\s*)?(?:圖片|Image)\s*[:：]\s*(?P<path>(?:\.\.?/)?models/[^\n\r]+\.(?:{image_ext}))\s*$""",
        repl,
        markdown_text or "",
    )


# ========
# Defines normalize markdown document links function for this module workflow.
# ========
def normalize_markdown_document_links(html_body: str) -> str:

    def repl(match: re.Match) -> str:
        quote = match.group("quote")
        target = match.group("target")
        if re.match(r"^(?:https?://|mailto:|#|/)", target):
            return match.group(0)
        path_part, sep, anchor = target.partition("#")
        if not path_part.lower().endswith(".md"):
            return match.group(0)
        html_target = path_part[:-3] + ".html"
        if sep:
            html_target += "#" + anchor
        return (
            f'href={quote}{html_target}{quote} '
            'target="_blank" rel="noopener noreferrer"'
        )

    return re.sub(
        r"""href=(?P<quote>['"])(?P<target>[^'"]+\.md(?:#[^'"]*)?)(?P=quote)""",
        repl,
        html_body,
    )


# ========
# Defines local HTML link target function for this module workflow.
# ========
def normalize_html_document_links(html_body: str) -> str:

    def repl(match: re.Match) -> str:
        attrs = match.group("attrs")
        quote = match.group("quote")
        target = match.group("target")
        if re.match(r"^(?:https?://|mailto:|#|/)", target):
            return match.group(0)
        if not target.partition("#")[0].lower().endswith(".html"):
            return match.group(0)
        if re.search(r"""\starget=(['"]).*?\1""", attrs):
            return match.group(0)
        return (
            f'<a{attrs} href={quote}{target}{quote} '
            'target="_blank" rel="noopener noreferrer">'
        )

    return re.sub(
        r"""<a(?P<attrs>[^>]*)\shref=(?P<quote>['"])(?P<target>[^'"]+\.html(?:#[^'"]*)?)(?P=quote)>""",
        repl,
        html_body,
    )


# ========
# Defines external link target function for this module workflow.
# ========
def normalize_external_links(html_body: str) -> str:

    def repl(match: re.Match) -> str:
        attrs = match.group("attrs")
        quote = match.group("quote")
        target = match.group("target")
        if not re.match(r"^https?://", target):
            return match.group(0)
        if re.search(r"""\starget=(['"]).*?\1""", attrs):
            return match.group(0)
        return (
            f'<a{attrs} href={quote}{target}{quote} '
            'target="_blank" rel="noopener noreferrer">'
        )

    return re.sub(
        r"""<a(?P<attrs>[^>]*)\shref=(?P<quote>['"])(?P<target>[^'"]+)(?P=quote)>""",
        repl,
        html_body,
    )


# ========
# Defines stable generated heading ids function for this module workflow.
# ========
def normalize_heading_ids(html_body: str) -> str:
    seen: dict[str, int] = {}

    def repl(match: re.Match) -> str:
        level = match.group("level")
        attrs = match.group("attrs") or ""
        body = match.group("body")
        if re.search(r"""\sid=(['"]).*?\1""", attrs):
            heading_text = re.sub(r"<[^>]+>", "", body)
            slug = markdown_heading_slug(heading_text)
            seen[slug] = seen.get(slug, 0) + 1
            return match.group(0)
        heading_text = re.sub(r"<[^>]+>", "", body)
        base_slug = markdown_heading_slug(heading_text)
        count = seen.get(base_slug, 0)
        seen[base_slug] = count + 1
        slug = base_slug if count == 0 else f"{base_slug}-{count + 1}"
        return f'<h{level}{attrs} id="{slug}">{body}</h{level}>'

    return re.sub(
        r"""<h(?P<level>[1-6])(?P<attrs>[^>]*)>(?P<body>[\s\S]*?)</h(?P=level)>""",
        repl,
        html_body,
    )


# ========
# Defines stable SM heading ids function for this module workflow.
# ========
def normalize_system_model_heading_ids(html_body: str) -> str:
    def repl(match: re.Match) -> str:
        level = match.group("level")
        attrs = match.group("attrs") or ""
        body = match.group("body")
        model_id = match.group("model_id").lower()
        if re.search(r"""\sid=(['"]).*?\1""", attrs):
            return match.group(0)
        return f'<h{level}{attrs} id="{model_id}">{body}</h{level}>'

    return re.sub(
        r"""<h(?P<level>[2-6])(?P<attrs>[^>]*)>(?P<body>\s*(?P<model_id>SM-\d+)\b[^<]*)</h(?P=level)>""",
        repl,
        html_body,
    )


# ========
# Defines wrap html document function for this module workflow.
# ========
def wrap_html_document(
    body_html: str,
    title: str = "Document",
    toc_entries: Optional[list[tuple[int, str, str]]] = None,
) -> str:
    safe_title = escape(title)
    toc_html = floating_toc_html(toc_entries or [])
    body_class = " has-floating-toc" if toc_html else ""
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{safe_title}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, "Noto Sans TC", sans-serif; margin: 24px; }}
    body.has-floating-toc {{ margin-right: 292px; }}
    .md-body {{ max-width: 1200px; margin: 0 auto; }}
    .plant-floating-toc {{
      position: fixed;
      top: 24px;
      right: 24px;
      z-index: 20;
      width: 236px;
      max-height: calc(100vh - 48px);
      overflow-y: auto;
      scrollbar-width: none;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      background: rgba(255, 255, 255, 0.96);
      box-shadow: 0 14px 35px rgba(15, 23, 42, 0.12);
      padding: 10px;
    }}
    .plant-floating-toc::-webkit-scrollbar {{ display: none; }}
    .plant-floating-toc__title {{ margin: 0 0 6px; min-height: 20px; font-size: 13px; font-weight: 700; color: #1e293b; }}
    .plant-floating-toc__title {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      cursor: pointer;
      list-style: none;
      user-select: none;
    }}
    .plant-floating-toc__title::-webkit-details-marker {{ display: none; }}
    .plant-floating-toc__title::after {{
      content: "收起";
      padding: 2px 0;
      color: #64748b;
      font-size: 11px;
      font-weight: 650;
    }}
    .plant-floating-toc:not([open]) {{
      width: auto;
      overflow: visible;
      padding: 8px 10px;
    }}
    .plant-floating-toc:not([open]) .plant-floating-toc__title {{ margin: 0; }}
    .plant-floating-toc:not([open]) .plant-floating-toc__title::after {{ content: "目錄"; }}
    .plant-floating-toc__items {{ display: flex; flex-direction: column; gap: 2px; }}
    .plant-floating-toc__link {{
      display: block;
      border-radius: 7px;
      padding: 6px 8px;
      color: #475569;
      font-size: 12px;
      line-height: 1.35;
      text-decoration: none;
    }}
    .plant-floating-toc__link:hover {{ background: #f1f5f9; color: #0f172a; }}
    .plant-floating-toc__link.is-active {{
      background: #e5e7eb;
      color: #1f2937;
      font-weight: 700;
    }}
    .plant-floating-toc__link--level-3 {{ padding-left: 18px; color: #64748b; }}
    .plant-floating-toc__link--level-4,
    .plant-floating-toc__link--level-5,
    .plant-floating-toc__link--level-6 {{ padding-left: 28px; color: #64748b; }}
    .table-wrap {{ width: 100%; overflow-x: auto; }}
    table {{ border-collapse: collapse; width: 100%; table-layout: fixed; margin: 12px 0; }}
    th, td {{ border: 1px solid #d0d0d0; padding: 8px; text-align: left; vertical-align: top; }}
    .table-compact th, .table-compact td {{ white-space: normal; overflow-wrap: anywhere; word-break: break-word; }}
    .table-readable th, .table-readable td {{ white-space: normal; overflow-wrap: anywhere; word-break: break-word; }}
    .table-traceability {{ table-layout: fixed; }}
    .table-traceability th:first-child, .table-traceability td:first-child {{ width: 128px; white-space: nowrap; }}
    .table-traceability th:nth-child(2), .table-traceability td:nth-child(2) {{ width: auto; }}
    .table-traceability th:nth-child(3), .table-traceability td:nth-child(3) {{ width: 260px; white-space: normal; overflow-wrap: anywhere; word-break: normal; }}
    .table-traceability td:nth-child(3) a {{ display: inline-block; margin: 0 4px 4px 0; white-space: nowrap; }}
    .dr-trace-feedback-table {{ table-layout: fixed; width: 100%; }}
    .dr-trace-feedback-table th,
    .dr-trace-feedback-table td {{ white-space: normal; overflow-wrap: anywhere; word-break: break-word; }}
    .dr-trace-feedback-table th:nth-child(1), .dr-trace-feedback-table td:nth-child(1) {{ width: 72px; }}
    .dr-trace-feedback-table th:nth-child(2), .dr-trace-feedback-table td:nth-child(2) {{ width: 120px; }}
    .dr-trace-feedback-table th:nth-child(3), .dr-trace-feedback-table td:nth-child(3) {{ width: 190px; }}
    .dr-trace-source-chip {{
      display: inline-block;
      margin: 0 4px 4px 0;
      padding: 2px 6px;
      border-radius: 999px;
      background: #eef2f7;
      color: #475569;
      font-size: 0.86em;
      line-height: 1.45;
      white-space: nowrap;
    }}
    .table-user-requirements th:first-child, .table-user-requirements td:first-child {{ width: 96px; white-space: nowrap; }}
    .table-user-requirements th:nth-child(2), .table-user-requirements td:nth-child(2),
    .table-user-requirements th:nth-child(4), .table-user-requirements td:nth-child(4) {{ width: 180px; }}
    .table-open-questions th:first-child, .table-open-questions td:first-child {{ width: 96px; white-space: nowrap; }}
    .table-open-questions th:nth-child(3), .table-open-questions td:nth-child(3) {{ width: 220px; white-space: normal; overflow-wrap: anywhere; word-break: break-word; }}
    td > p:first-child {{ margin-top: 0; }}
    td > p:last-child {{ margin-bottom: 0; }}
    img {{ max-width: 100%; height: auto; display: block; margin: 12px auto; }}
    code, pre {{ white-space: pre-wrap; }}
    .srs-dr-ref,
    h4 a[href*="dr#"],
    li a[href*="dr#con-"] {{
      display: inline-flex;
      align-items: center;
      margin-left: 0.35rem;
      transform: translateY(-0.35em);
      font-size: 0.62em;
      font-weight: 700;
      line-height: 1;
      color: #64748b;
      text-decoration: none;
    }}
    .srs-dr-ref:hover,
    h4 a[href*="dr#"]:hover,
    li a[href*="dr#con-"]:hover {{ color: #0f172a; text-decoration: underline; }}
    @media (max-width: 1024px) {{
      body.has-floating-toc {{ margin: 16px; padding-bottom: 72px; }}
      .plant-floating-toc {{
        top: auto;
        left: 12px;
        right: 12px;
        bottom: 12px;
        width: auto;
        max-height: 38vh;
      }}
    }}
  </style>
</head>
<body class="{body_class.strip()}">
{toc_html}
<div class="md-body">
{wrap_tables(body_html)}
</div>
{floating_toc_script() if toc_html else ""}
</body>
</html>"""


# ========
# Defines save markdown as html function for this module workflow.
# ========
def save_markdown_as_html(
    md_path: Path,
    html_path: Path,
    html_root: Optional[Path] = None,
    project_id: Optional[str] = None,
) -> None:
    markdown_text = md_path.read_text(encoding="utf-8")
    needs_floating_toc = md_path.name in {"srs.md", "design_rationale.md"}
    if md_path.name in {"srs.md", "design_rationale.md"}:
        markdown_text = remove_generated_markdown_toc(markdown_text)
    html_body = markdown_to_html(markdown_text)
    html_body = normalize_model_image_paths(
        html_body,
        html_path,
        html_root=html_root,
        project_id=project_id,
    )
    html_body = normalize_markdown_document_links(html_body)
    html_body = normalize_html_document_links(html_body)
    html_body = normalize_external_links(html_body)
    html_body = normalize_heading_ids(html_body)
    html_body = normalize_system_model_heading_ids(html_body)
    toc_entries = html_toc_entries(html_body) if needs_floating_toc else []
    html = wrap_html_document(html_body, title=md_path.stem, toc_entries=toc_entries)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(html_path, html, encoding="utf-8")


# ========
# Defines table class function for this module workflow.
# ========
def table_class(table_html: str) -> str:
    header_text = re.sub(r"<[^>]+>", " ", table_html).lower()
    normalized = re.sub(r"\s+", " ", header_text)
    if all(text in normalized for text in ("requirement id", "source", "system model")):
        return "table-readable table-traceability"
    if all(text in normalized for text in ("id", "stakeholder", "user requirement", "source")):
        return "table-readable table-user-requirements"
    if all(text in normalized for text in ("id", "question", "related source")):
        return "table-readable table-open-questions"
    return "table-compact"


# ========
# Defines apply table class function for this module workflow.
# ========
def apply_table_class(table_html: str) -> str:
    cls = table_class(table_html)
    match = re.match(r"<table(?P<attrs>[^>]*)>", table_html)
    if not match:
        return table_html
    attrs = match.group("attrs") or ""
    class_match = re.search(r"""class=(['"])(?P<class>.*?)\1""", attrs)
    if class_match:
        old_class = class_match.group("class")
        new_attrs = re.sub(
            r"""class=(['"])(?P<class>.*?)\1""",
            lambda m: f'class="{old_class} {cls}"',
            attrs,
            count=1,
        )
    else:
        new_attrs = attrs + f' class="{cls}"'
    return "<table" + new_attrs + ">" + table_html[match.end():]


# ========
# Defines wrap tables function for this module workflow.
# ========
def wrap_tables(html_body: str) -> str:
    if "<table" not in html_body:
        return html_body

    def repl(match: re.Match) -> str:
        table_html = apply_table_class(match.group(0))
        return f'<div class="table-wrap">{table_html}</div>'

    return re.sub(
        r"<table(?:\s[^>]*)?>[\s\S]*?</table>",
        lambda m: repl(m),
        html_body,
    )


# ========
# Defines build markdown engine function for this module workflow.
# ========
def build_markdown_engine() -> MarkdownIt:
    engine = MarkdownIt("commonmark")
    engine.enable("table")
    return engine


_MD_ENGINE = build_markdown_engine()
