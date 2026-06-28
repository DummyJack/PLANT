# Handles project export helpers for html results and per-project manual output.
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict

from scripts.build_file import write_manifest
from utils import export_enabled
from .atomic import atomic_write_text


MANUAL_TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "manual"


def should_export_html(config: Dict[str, Any]) -> bool:
    return export_enabled(config, "html", True)


def should_export_manual(config: Dict[str, Any]) -> bool:
    return export_enabled(config, "manual", False)


def normalize_manual_project_path(path: str) -> str:
    normalized = path.strip()
    while normalized.startswith("../") or normalized.startswith("./"):
        if normalized.startswith("../"):
            normalized = normalized[3:]
        else:
            normalized = normalized[2:]
    normalized = normalized.strip("/")
    if normalized.startswith("projects/"):
        normalized = normalized[len("projects/"):]
    return normalized


def is_manual_project_path(path: str) -> bool:
    return re.match(r"^(?:results|artifact|output)/", normalize_manual_project_path(path)) is not None


def manual_href(project_id: str, path: str) -> str:
    normalized = normalize_manual_project_path(path)
    if normalized.lower() == "results/srs.html":
        return f"/{project_id}/manual/srs"
    if normalized.lower() == "results/design_rationale.html":
        return f"/{project_id}/manual/dr"
    return f"/{project_id}/manual/{normalized}"


def rewrite_manual_html_hrefs(html: str, project_id: str) -> str:
    def replace_href(match: re.Match[str]) -> str:
        quote = match.group("quote")
        href = match.group("href")
        if not is_manual_project_path(href):
            return match.group(0)
        return f"href={quote}{manual_href(project_id, href)}{quote}"

    return re.sub(r"href=(?P<quote>['\"])(?P<href>[^'\"]+)(?P=quote)", replace_href, html)


def remove_missing_manual_file_links(html: str, project_dir: Path, project_id: str) -> str:
    manual_prefix = f"/{project_id}/manual/"

    def replace_anchor(match: re.Match[str]) -> str:
        href = match.group("href")
        if not href.startswith(manual_prefix):
            return match.group(0)
        relative = href[len(manual_prefix):]
        if not re.match(r"^(?:artifact|results|output)/", relative):
            return match.group(0)
        if (project_dir / relative).is_file():
            return match.group(0)
        return ""

    return re.sub(
        r"""<a(?P<attrs>[^>]*)\shref=(?P<quote>['"])(?P<href>[^'"]+)(?P=quote)(?P<tail>[^>]*)>.*?</a>""",
        replace_anchor,
        html,
        flags=re.DOTALL,
    )


def rewrite_manual_manifest_hrefs(manifest_path: Path, project_id: str) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    def rewrite_item(item: Any) -> None:
        if not isinstance(item, dict):
            return
        href = item.get("href")
        if not isinstance(href, str):
            return
        if not is_manual_project_path(href):
            return
        item["href"] = manual_href(project_id, href)

    for value in manifest.values():
        if isinstance(value, list):
            for item in value:
                rewrite_item(item)

    atomic_write_text(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def export_project_manual(
    project_dir: Path,
    *,
    template_dir: Path = MANUAL_TEMPLATE_DIR,
) -> Path:
    project_dir = Path(project_dir)
    template_dir = Path(template_dir)
    manual_dir = project_dir / "manual"
    manual_dir.mkdir(parents=True, exist_ok=True)
    project_id = project_dir.name

    html = (template_dir / "index.html").read_text(encoding="utf-8")
    html = html.replace("<head>\n", f'<head>\n  <base href="/{project_id}/manual/" />\n', 1)
    html = rewrite_manual_html_hrefs(html, project_id)
    html = remove_missing_manual_file_links(html, project_dir, project_id)
    html = html.replace('href="styles.css"', 'href="../../../manual/styles.css"')
    html = html.replace('src="main.js"', 'src="../../../manual/main.js"')
    html = html.replace('  <link rel="icon" type="image/png" href="img/logo.png" />\n', "")
    atomic_write_text(manual_dir / "index.html", html, encoding="utf-8")

    for stale_asset in ("main.js", "styles.css"):
        path = manual_dir / stale_asset
        if path.exists():
            path.unlink()

    manifest_path = write_manifest(project_dir=project_dir, output_file=manual_dir / "file.json")
    rewrite_manual_manifest_hrefs(manifest_path, project_id)
    return manual_dir
