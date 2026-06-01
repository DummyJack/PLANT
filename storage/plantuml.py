# PlantUML storage helpers: write generated diagram files safely.
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Optional
import socket
import urllib.error
import urllib.request


PLANTUML_SERVER = "https://www.plantuml.com/plantuml"


def plantuml_safe_name(model: Dict[str, Any]) -> str:
    safe_name = "".join(
        c
        for c in model.get("name", "unnamed")
        if c.isalnum() or c in (" ", "-", "_")
    ).strip()
    return safe_name or "unnamed"


def encode_plantuml_hex(code: str) -> str:
    return "~h" + code.encode("utf-8").hex()


def write_plantuml_file(artifact_dir: Path, model: Dict[str, Any]) -> Optional[str]:
    plantuml_code = model.get("plantuml", "")
    if not plantuml_code:
        return None
    safe_name = plantuml_safe_name(model)
    filename = f"{safe_name}.plantuml"
    models_dir = artifact_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    filepath = models_dir / filename
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(plantuml_code)
    return filename


def render_plantuml_png(artifact_dir: Path, model: Dict[str, Any]) -> Optional[str]:
    plantuml_code = model.get("plantuml", "")
    if not plantuml_code:
        return None
    safe_name = plantuml_safe_name(model)
    filename = f"{safe_name}.png"
    models_dir = artifact_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    filepath = models_dir / filename
    url = f"{PLANTUML_SERVER}/png/{encode_plantuml_hex(plantuml_code)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Plant-Modeler/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
        if data:
            filepath.write_bytes(data)
            return filename
    except (urllib.error.URLError, urllib.error.HTTPError, socket.timeout, TimeoutError, OSError) as e:
        print(f"PlantUML PNG 輸出失敗 {filename}: {e}")
    return None


def save_plantuml_files(artifact_dir: Path, model_data: Any) -> None:
    models = [m for m in (model_data or []) if isinstance(m, dict) and m.get("plantuml")]
    if not models:
        return
    models_dir = artifact_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    for old in models_dir.glob("*.plantuml"):
        old.unlink(missing_ok=True)
    for old in models_dir.glob("*.png"):
        old.unlink(missing_ok=True)
    max_workers = min(len(models), 8)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for model in models:
            futures.append(executor.submit(write_plantuml_file, artifact_dir, model))
            futures.append(executor.submit(render_plantuml_png, artifact_dir, model))
        for future in as_completed(futures):
            try:
                name = future.result()
                if name:
                    print(f"✓ 儲存 PlantUML 輸出: {name}")
            except Exception as e:
                print(f"儲存 PlantUML 失敗: {e}")
    for model in models:
        filename = f"{plantuml_safe_name(model)}.png"
        if (models_dir / filename).exists():
            model["image_path"] = f"../models/{filename}"
