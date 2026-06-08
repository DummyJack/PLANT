# Handles markdown logic for project artifact storage and file export behavior.
from html import escape
from pathlib import Path
from typing import Optional
from markdown_it import MarkdownIt
import re


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


# ========
# Defines markdown heading text cleanup for generated document TOC.
# ========
def clean_heading_text(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", "", str(text or "")).strip()
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"[*_`]+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


# ========
# Defines markdown heading slug function for generated document TOC.
# ========
def markdown_heading_slug(text: str) -> str:
    slug = clean_heading_text(text).lower()
    slug = re.sub(r"[^\w\u4e00-\u9fff]+", "-", slug, flags=re.UNICODE)
    slug = re.sub(r"-+", "-", slug).strip("-_")
    return slug or "section"


# ========
# Defines extract markdown headings function for generated document TOC.
# ========
def extract_markdown_headings(
    markdown_text: str,
    *,
    min_level: int = 2,
    max_level: int = 3,
) -> list[tuple[int, str, str]]:
    headings: list[tuple[int, str, str]] = []
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
        headings.append((level, title, slug))
    return headings


# ========
# Defines insert generated table of contents function for markdown documents.
# ========
def insert_markdown_toc(
    markdown_text: str,
    *,
    title: str = "目錄",
    min_level: int = 2,
    max_level: int = 3,
) -> str:
    source = re.sub(
        r"(?s)\n?<!-- plant-toc:start -->.*?<!-- plant-toc:end -->\n?",
        "\n",
        markdown_text or "",
    ).strip()
    headings = extract_markdown_headings(source, min_level=min_level, max_level=max_level)
    if not headings:
        return source + "\n"

    toc_lines = [
        "<!-- plant-toc:start -->",
        "",
        "---",
        "",
        f"## {title}",
        "",
    ]
    has_level_two_parent = False
    for level, heading, slug in headings:
        if level <= 2:
            has_level_two_parent = True
            indent = ""
        else:
            indent = "  " * (level - 2) if has_level_two_parent else ""
        toc_lines.append(f"{indent}- [{heading}](#{slug})")
    toc_lines.extend(["", "---", "", "<!-- plant-toc:end -->"])
    toc = "\n".join(toc_lines).strip()

    match = re.match(r"(?s)^(#\s+.+?\n)(.*)$", source)
    if match:
        return match.group(1).rstrip() + "\n\n" + toc + "\n\n" + match.group(2).lstrip() + "\n"
    return toc + "\n\n" + source + "\n"


# ========
# Defines markdown target dir function for this module workflow.
# ========
def markdown_target_dir(artifact_dir: Path, output_dir: Path, filename: str) -> Path:
    if filename == "conflict_report.md":
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
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


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


# ========
# Defines normalize model image paths function for this module workflow.
# ========
def normalize_model_image_paths(
    html_body: str,
    html_path: Path,
    html_root: Optional[Path] = None,
) -> str:
    prefix = compute_models_prefix(html_path, html_root) + "models/"

    return re.sub(
        r"""(?P<attr>src|href)=(['\"])(?:\.\./|\./)?(?:artifact/|output/)?(?:models/)(?P<target>[^\"'>\s]+)(?:\?[^\"']*)?(['\"])""",
        lambda m: f'{m.group("attr")}={m.group(2)}{prefix}{m.group("target")}{m.group(4)}',
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
) -> str:
    safe_title = escape(title)
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{safe_title}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, "Noto Sans TC", sans-serif; margin: 24px; }}
    .md-body {{ max-width: 1200px; margin: 0 auto; }}
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
    .table-user-requirements th:first-child, .table-user-requirements td:first-child {{ width: 96px; white-space: nowrap; }}
    .table-user-requirements th:nth-child(2), .table-user-requirements td:nth-child(2),
    .table-user-requirements th:nth-child(4), .table-user-requirements td:nth-child(4) {{ width: 180px; }}
    .table-open-questions th:first-child, .table-open-questions td:first-child {{ width: 96px; white-space: nowrap; }}
    .table-open-questions th:nth-child(3), .table-open-questions td:nth-child(3) {{ width: 220px; white-space: normal; overflow-wrap: anywhere; word-break: break-word; }}
    h2[id="目錄"] {{ font-size: 1.15rem; color: #777; margin-top: 20px; margin-bottom: 10px; }}
    h2[id="目錄"] + ul {{ list-style: none; padding-left: 0; margin: 0 0 24px 0; color: #777; }}
    h2[id="目錄"] + ul ul {{ list-style: none; margin-top: 8px; padding-left: 28px; }}
    h2[id="目錄"] + ul li {{ margin: 8px 0; }}
    h2[id="目錄"] + ul a {{ color: #777; text-decoration: underline; text-underline-offset: 2px; }}
    td > p:first-child {{ margin-top: 0; }}
    td > p:last-child {{ margin-bottom: 0; }}
    img {{ max-width: 100%; height: auto; display: block; margin: 12px auto; }}
    code, pre {{ white-space: pre-wrap; }}
  </style>
</head>
<body>
<div class="md-body">
{wrap_tables(body_html)}
</div>
</body>
</html>"""


# ========
# Defines save markdown as html function for this module workflow.
# ========
def save_markdown_as_html(
    md_path: Path,
    html_path: Path,
    html_root: Optional[Path] = None,
) -> None:
    markdown_text = md_path.read_text(encoding="utf-8")
    html_body = markdown_to_html(markdown_text)
    html_body = normalize_model_image_paths(html_body, html_path, html_root=html_root)
    html_body = normalize_markdown_document_links(html_body)
    html_body = normalize_html_document_links(html_body)
    html_body = normalize_heading_ids(html_body)
    html_body = normalize_system_model_heading_ids(html_body)
    html = wrap_html_document(html_body, title=md_path.stem)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")


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
