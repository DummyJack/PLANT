# Handles project export helpers for html results and per-project manual output.
from __future__ import annotations

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


def export_project_manual(
    project_dir: Path,
    *,
    template_dir: Path = MANUAL_TEMPLATE_DIR,
) -> Path:
    project_dir = Path(project_dir)
    template_dir = Path(template_dir)
    manual_dir = project_dir / "manual"
    manual_dir.mkdir(parents=True, exist_ok=True)

    html = (template_dir / "index.html").read_text(encoding="utf-8")
    html = html.replace('href="projects/', 'href="../')
    html = html.replace('href="styles.css"', 'href="../../../manual/styles.css"')
    html = html.replace('src="main.js"', 'src="../../../manual/main.js"')
    html = html.replace('  <link rel="icon" type="image/png" href="img/logo.png" />\n', "")
    atomic_write_text(manual_dir / "index.html", html, encoding="utf-8")

    for stale_asset in ("main.js", "styles.css"):
        path = manual_dir / stale_asset
        if path.exists():
            path.unlink()

    write_manifest(project_dir=project_dir, output_file=manual_dir / "file.json")
    return manual_dir
