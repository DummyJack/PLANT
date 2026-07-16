# 掃描 Manual 專案檔案並產生前端 file manifest。
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT = REPO_ROOT / "manual"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.clean import apply_entrypoint_bootstrap

apply_entrypoint_bootstrap()

from storage.atomic import atomic_write_text

PROJECT_DIR = ROOT / "projects"
OUTPUT_FILE = ROOT / "file.json"


GROUPS = {
    "conflict_reports": [
        "artifact/report/conflict_report_v*.json",
        "results/report/conflict_report.html",
    ],
    "conflict_report_htmls": [
        "results/report/conflict_report_v*.html",
    ],
    "models": [
        "artifact/models/*.png",
    ],
    "model_sources": [
        "artifact/models/*.plantuml",
    ],
    "formal_meetings": [
        "artifact/meeting/formal_meeting_r*.json",
    ],
    "mom": [
        "results/MoM/R*-M*.html",
    ],
    "drafts": [
        "results/drafts/draft_v*.html",
    ],
}


def natural_key(path: Path) -> list[object]:
    parts: list[object] = []
    text = path.name
    chunk = ""
    is_digit = False
    for char in text:
        char_is_digit = char.isdigit()
        if chunk and char_is_digit != is_digit:
            parts.append(int(chunk) if is_digit else chunk)
            chunk = ""
        chunk += char
        is_digit = char_is_digit
    if chunk:
        parts.append(int(chunk) if is_digit else chunk)
    return parts


def href_for(path: Path, href_root: Path) -> str:
    return os.path.relpath(path, href_root).replace(os.sep, "/")


def collect_files(
    patterns: list[str],
    *,
    project_dir: Path = PROJECT_DIR,
    href_root: Path = ROOT,
) -> list[dict[str, str]]:
    items: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        matched = sorted(project_dir.glob(pattern), key=natural_key)
        for path in matched:
            if path.is_file() and not path.name.startswith(".") and path not in seen:
                items.append(path)
                seen.add(path)
    return [
        {
            "label": path.stem,
            "href": href_for(path, href_root),
        }
        for path in items
    ]


def is_artifact_html_browser_file(href: str) -> bool:
    if "/results/" not in href and "/output/" not in href:
        return False
    if not href.endswith(".html"):
        return False
    name = href.rsplit("/", 1)[-1]
    if "/drafts/" in href and name.startswith("draft_v"):
        return True
    if "/MoM/" in href:
        return True
    if "/report/" in href and name.startswith("conflict_report"):
        return True
    return False


def is_output_browser_file(href: str) -> bool:
    if "/results/" not in href and "/output/" not in href:
        return False
    name = href.rsplit("/", 1)[-1]
    if name in {"srs.html", "design_rationale.html"}:
        return True
    return "/models/" in href and name.lower().endswith(".png")


def split_browser_files(
    all_files: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    artifact_files: list[dict[str, str]] = []
    output_files: list[dict[str, str]] = []
    for file in all_files:
        href = file["href"]
        if "/artifact/" in href:
            artifact_files.append(file)
        elif is_artifact_html_browser_file(href):
            artifact_files.append(file)
        elif is_output_browser_file(href):
            output_files.append(file)
    return artifact_files, output_files


def build_manifest(
    project_dir: Path = PROJECT_DIR,
    href_root: Path = ROOT,
) -> dict[str, list[dict[str, str]]]:
    project_dir = Path(project_dir)
    href_root = Path(href_root)
    if not project_dir.exists():
        raise SystemExit(f"Missing project directory: {project_dir}")
    manifest = {
        name: collect_files(patterns, project_dir=project_dir, href_root=href_root)
        for name, patterns in GROUPS.items()
    }
    all_files = collect_all_files(project_dir=project_dir, href_root=href_root)
    artifact_files, output_files = split_browser_files(all_files)
    manifest["all_files"] = all_files
    manifest["artifact_files"] = artifact_files
    manifest["output_files"] = output_files
    return manifest


def write_manifest(
    project_dir: Path = PROJECT_DIR,
    output_file: Path = OUTPUT_FILE,
    *,
    href_root: Path | None = None,
) -> Path:
    output_file = Path(output_file)
    href_root = Path(href_root) if href_root is not None else output_file.parent
    manifest = build_manifest(project_dir=Path(project_dir), href_root=href_root)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        output_file,
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_file


def collect_all_files(
    *,
    project_dir: Path = PROJECT_DIR,
    href_root: Path = ROOT,
) -> list[dict[str, str]]:
    scan_roots: list[Path] = []
    for name in ("artifact", "results", "output"):
        root = project_dir / name
        if root.exists():
            scan_roots.append(root)
    if not scan_roots:
        return []

    files = dedupe_model_images(
        (
            path
            for root in scan_roots
            for path in root.rglob("*")
            if should_show_file(path)
        ),
        project_dir=project_dir,
    )
    return [
        {
            "label": display_label(path, project_dir=project_dir),
            "href": href_for(path, href_root),
        }
        for path in files
    ]


def display_label(path: Path, *, project_dir: Path = PROJECT_DIR) -> str:
    relative = path.relative_to(project_dir)
    if relative.parts and relative.parts[0] in {"artifact", "results", "output"}:
        return Path(*relative.parts[1:]).as_posix()
    return relative.as_posix()


def should_show_file(path: Path) -> bool:
    if not path.is_file() or path.name.startswith("."):
        return False
    if path.parent.name == "report" and path.name.startswith("conflict_report_v") and path.suffix.lower() == ".md":
        return True
    if path.suffix.lower() == ".md":
        return False
    return True


def dedupe_model_images(paths, *, project_dir: Path = PROJECT_DIR) -> list[Path]:
    selected: dict[tuple[str, str], Path] = {}
    ordered: list[Path] = []
    for path in paths:
        key = model_image_key(path, project_dir=project_dir)
        if key is None:
            ordered.append(path)
            continue

        current = selected.get(key)
        if current is None or model_image_priority(
            path, project_dir=project_dir
        ) < model_image_priority(current, project_dir=project_dir):
            selected[key] = path

    selected_model_paths = set(selected.values())
    ordered.extend(selected_model_paths)
    return sorted(ordered, key=lambda path: natural_key(path.relative_to(project_dir)))


def model_image_key(path: Path, *, project_dir: Path = PROJECT_DIR) -> tuple[str, str] | None:
    relative = path.relative_to(project_dir)
    if path.suffix.lower() != ".png":
        return None
    if len(relative.parts) < 3 or relative.parts[1] != "models":
        return None
    if relative.parts[0] not in {"artifact", "output", "results"}:
        return None
    return ("models", path.name)


def model_image_priority(path: Path, *, project_dir: Path = PROJECT_DIR) -> int:
    source = path.relative_to(project_dir).parts[0]
    return {"results": 0, "artifact": 1, "output": 2}.get(source, 9)


def main() -> None:
    project_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT_DIR
    output_file = Path(sys.argv[2]) if len(sys.argv) > 2 else OUTPUT_FILE
    written = write_manifest(project_dir=project_dir, output_file=output_file)
    try:
        label = written.relative_to(ROOT)
    except ValueError:
        label = written
    print(f"generated: {label}")


if __name__ == "__main__":
    main()
