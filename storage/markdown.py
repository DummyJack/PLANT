# Markdown storage helpers: clean LLM fences and route output files.
from pathlib import Path


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
    if filename.startswith("conflict_report"):
        for legacy_path in (artifact_dir / filename, artifact_dir / "MoM" / filename, output_dir / filename):
            if legacy_path.exists():
                legacy_path.unlink()


def load_markdown(artifact_dir: Path, output_dir: Path, filename: str) -> str:
    target_dir = markdown_target_dir(artifact_dir, output_dir, filename)
    filepath = target_dir / filename
    if not filepath.exists():
        return ""
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()
