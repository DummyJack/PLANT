from html import escape
from pathlib import Path
from typing import Optional
from markdown_it import MarkdownIt
import re


def clean_llm_output(text: str) -> str:
    """Remove a single outer Markdown code fence often added by LLMs."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1 :]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


def markdown_target_dir(artifact_dir: Path, output_dir: Path, filename: str) -> Path:
    """指定輸出檔案放置目錄。"""
    if filename == "conflict_report.md":
        return artifact_dir / "report"
    if filename in {"srs.md", "design_rationale.md"}:
        return output_dir
    if filename.startswith("R") and filename.endswith(".md"):
        return artifact_dir / "MoM"
    return artifact_dir


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


def load_markdown(artifact_dir: Path, output_dir: Path, filename: str) -> str:
    target_dir = markdown_target_dir(artifact_dir, output_dir, filename)
    filepath = target_dir / filename
    if not filepath.exists():
        return ""
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


def markdown_to_html(markdown_text: str) -> str:
    """將 markdown 轉為簡單 HTML 字串。"""
    # 先清理 LLM 常見輸出格式（外層 code fence）。
    cleaned = clean_llm_output(markdown_text or "")
    # 啟用表格與常用格式規則，避免 pipe table、刪除線、超連結被錯誤解析。
    return _MD_ENGINE.render(cleaned).strip()


def _compute_models_prefix(html_path: Path, html_root: Optional[Path]) -> str:
    """根據 HTML 輸出位置，回傳 models 的相對路徑前綴."""
    if html_root:
        try:
            rel = html_path.parent.relative_to(html_root)
            depth = len(rel.parts)
        except ValueError:
            depth = 0
    else:
        depth = 0
    return "./" if depth == 0 else "../" * depth + ""


def normalize_model_image_paths(
    html_body: str,
    html_path: Path,
    html_root: Optional[Path] = None,
) -> str:
    """Normalize any model-image paths in HTML so it can be loaded from results/models."""
    prefix = _compute_models_prefix(html_path, html_root) + "models/"

    return re.sub(
        r"""(?P<attr>src|href)=(['\"])(?:\.\./|\./)?(?:artifact/|output/)?(?:models/)(?P<target>[^\"'>\s]+)(?:\?[^\"']*)?(['\"])""",
        lambda m: f'{m.group("attr")}={m.group(2)}{prefix}{m.group("target")}{m.group(4)}',
        html_body,
    )


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
    table {{ border-collapse: collapse; width: max-content; min-width: 100%; margin: 12px 0; }}
    th, td {{ border: 1px solid #d0d0d0; padding: 8px; text-align: left; vertical-align: top; white-space: nowrap; }}
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


def save_markdown_as_html(
    md_path: Path,
    html_path: Path,
    html_root: Optional[Path] = None,
) -> None:
    """讀取 markdown 檔案並輸出 HTML 檔。"""
    markdown_text = md_path.read_text(encoding="utf-8")
    html_body = markdown_to_html(markdown_text)
    html_body = normalize_model_image_paths(html_body, html_path, html_root=html_root)
    html = wrap_html_document(html_body, title=md_path.stem)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")


def wrap_tables(html_body: str) -> str:
    """將 HTML 內的 <table> 包進可水平捲動容器，避免寬表格破版。"""
    if "<table" not in html_body:
        return html_body

    def repl(match: re.Match) -> str:
        table_html = match.group(0)
        return f'<div class="table-wrap">{table_html}</div>'

    # 同時處理含有屬性的 <table ...>，避免 table 被直接吃掉造成樣式失效。
    return re.sub(
        r"<table(?:\s[^>]*)?>[\s\S]*?</table>",
        lambda m: repl(m),
        html_body,
    )


def _build_markdown_engine() -> MarkdownIt:
    engine = MarkdownIt("commonmark")
    candidate_rules = [
        "table",
        "strikethrough",
        "autolink",
        "linkify",
        "breaks",
    ]
    for rule in candidate_rules:
        try:
            engine.enable(rule)
        except ValueError:
            # 某些版本不支援特定 rule，保持向下相容，不因單一路徑失敗
            pass
    return engine


_MD_ENGINE = _build_markdown_engine()
