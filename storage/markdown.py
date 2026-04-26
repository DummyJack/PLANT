from pathlib import Path


def markdown_target_dir(artifact_dir: Path, output_dir: Path, filename: str) -> Path:
    """指定輸出檔案放置目錄。"""
    if filename in {"srs.md", "design_rationale.md"}:
        return output_dir
    return artifact_dir


def save_markdown(
    artifact_dir: Path,
    output_dir: Path,
    content: str,
    filename: str,
) -> None:
    target_dir = markdown_target_dir(artifact_dir, output_dir, filename)
    filepath = target_dir / filename
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
