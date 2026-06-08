# Handles plantuml logic for project artifact storage and file export behavior.
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Optional
import socket
import urllib.error
import urllib.request
import zlib


PLANTUML_SERVER = "https://www.plantuml.com/plantuml"


# ========
# Defines plantuml safe name function for this module workflow.
# ========
def plantuml_safe_name(model: Dict[str, Any]) -> str:
    safe_name = "".join(
        c
        for c in model.get("name", "unnamed")
        if c.isalnum() or c in (" ", "-", "_")
    ).strip()
    return safe_name or "unnamed"


# ========
# Defines encode plantuml function for this module workflow.
# ========
def encode_plantuml(code: str) -> str:
    compressed = zlib.compress(code.encode("utf-8"), 9)[2:-4]
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"

    def encode3(b1: int, b2: int, b3: int) -> str:
        c1 = b1 >> 2
        c2 = ((b1 & 0x3) << 4) | (b2 >> 4)
        c3 = ((b2 & 0xF) << 2) | (b3 >> 6)
        c4 = b3 & 0x3F
        return alphabet[c1 & 0x3F] + alphabet[c2 & 0x3F] + alphabet[c3 & 0x3F] + alphabet[c4 & 0x3F]

    out = []
    for idx in range(0, len(compressed), 3):
        chunk = compressed[idx:idx + 3]
        b1 = chunk[0]
        b2 = chunk[1] if len(chunk) > 1 else 0
        b3 = chunk[2] if len(chunk) > 2 else 0
        out.append(encode3(b1, b2, b3))
    return "".join(out)


# ========
# Defines write plantuml file function for this module workflow.
# ========
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


# ========
# Defines render plantuml png function for this module workflow.
# ========
def render_plantuml_png(artifact_dir: Path, model: Dict[str, Any]) -> Optional[str]:
    plantuml_code = model.get("plantuml", "")
    if not plantuml_code:
        return None
    safe_name = plantuml_safe_name(model)
    filename = f"{safe_name}.png"
    models_dir = artifact_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    filepath = models_dir / filename
    url = f"{PLANTUML_SERVER}/png/{encode_plantuml(plantuml_code)}"
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


# ========
# Defines save plantuml files function for this module workflow.
# ========
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
