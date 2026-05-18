# PlantUML storage helpers: write generated diagram files safely.
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Optional


def write_plantuml_file(artifact_dir: Path, model: Dict[str, Any]) -> Optional[str]:
    plantuml_code = model.get("plantuml", "")
    if not plantuml_code:
        return None
    safe_name = "".join(
        c
        for c in model.get("name", "unnamed")
        if c.isalnum() or c in (" ", "-", "_")
    ).strip()
    if not safe_name:
        safe_name = "unnamed"
    filename = f"{safe_name}.plantuml"
    models_dir = artifact_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    filepath = models_dir / filename
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(plantuml_code)
    return filename


def save_plantuml_files(artifact_dir: Path, model_data: Any) -> None:
    models = [m for m in (model_data or []) if isinstance(m, dict) and m.get("plantuml")]
    if not models:
        return
    models_dir = artifact_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    for old in models_dir.glob("*.plantuml"):
        old.unlink(missing_ok=True)
    max_workers = min(len(models), 8)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(write_plantuml_file, artifact_dir, m) for m in models]
        for future in as_completed(futures):
            try:
                name = future.result()
                if name:
                    print(f"✓ 儲存 PlantUML: {name}")
            except Exception as e:
                print(f"儲存 PlantUML 失敗: {e}")
