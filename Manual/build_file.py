# 掃描 Manual 專案檔案並產生前端 file manifest。
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.clean import apply_entrypoint_bootstrap

apply_entrypoint_bootstrap()

PROJECT_DIR = ROOT / "projects"
OUTPUT_FILE = ROOT / "file.json"


GROUPS = {
    "conflict_reports": [
        "artifact/report/conflict_report_v*.json",
        "results/report/conflict_report.html",
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


def collect_files(patterns: list[str]) -> list[dict[str, str]]:
    items: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        matched = sorted(PROJECT_DIR.glob(pattern), key=natural_key)
        for path in matched:
            if path.is_file() and not path.name.startswith(".") and path not in seen:
                items.append(path)
                seen.add(path)
    return [
        {
            "label": path.stem,
            "href": path.relative_to(ROOT).as_posix(),
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


def build_manifest() -> dict[str, list[dict[str, str]]]:
    if not PROJECT_DIR.exists():
        raise SystemExit(f"Missing project directory: {PROJECT_DIR}")
    manifest = {name: collect_files(patterns) for name, patterns in GROUPS.items()}
    all_files = collect_all_files()
    artifact_files, output_files = split_browser_files(all_files)
    manifest["all_files"] = all_files
    manifest["artifact_files"] = artifact_files
    manifest["output_files"] = output_files
    return manifest


def collect_all_files() -> list[dict[str, str]]:
    scan_roots: list[Path] = []
    for name in ("artifact", "results", "output"):
        root = PROJECT_DIR / name
        if root.exists():
            scan_roots.append(root)
    if not scan_roots:
        return []

    files = dedupe_model_images(
        path
        for root in scan_roots
        for path in root.rglob("*")
        if should_show_file(path)
    )
    return [
        {
            "label": display_label(path),
            "href": path.relative_to(ROOT).as_posix(),
        }
        for path in files
    ]


def display_label(path: Path) -> str:
    relative = path.relative_to(PROJECT_DIR)
    if relative.parts and relative.parts[0] in {"artifact", "results", "output"}:
        return Path(*relative.parts[1:]).as_posix()
    return relative.as_posix()


def should_show_file(path: Path) -> bool:
    if not path.is_file() or path.name.startswith("."):
        return False
    if path.suffix.lower() == ".md":
        return False
    return True


def dedupe_model_images(paths) -> list[Path]:
    selected: dict[tuple[str, str], Path] = {}
    ordered: list[Path] = []
    for path in paths:
        key = model_image_key(path)
        if key is None:
            ordered.append(path)
            continue

        current = selected.get(key)
        if current is None or model_image_priority(path) < model_image_priority(current):
            selected[key] = path

    selected_model_paths = set(selected.values())
    ordered.extend(selected_model_paths)
    return sorted(ordered, key=lambda path: natural_key(path.relative_to(PROJECT_DIR)))


def model_image_key(path: Path) -> tuple[str, str] | None:
    relative = path.relative_to(PROJECT_DIR)
    if path.suffix.lower() != ".png":
        return None
    if len(relative.parts) < 3 or relative.parts[1] != "models":
        return None
    if relative.parts[0] not in {"artifact", "output", "results"}:
        return None
    return ("models", path.name)


def model_image_priority(path: Path) -> int:
    source = path.relative_to(PROJECT_DIR).parts[0]
    return {"results": 0, "artifact": 1, "output": 2}.get(source, 9)


def main() -> None:
    manifest = build_manifest()
    OUTPUT_FILE.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"generated: {OUTPUT_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
