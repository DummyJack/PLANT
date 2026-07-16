# Handles plantuml logic for project artifact storage and file export behavior.
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, Optional
import socket
import subprocess
import tempfile
import urllib.error
import urllib.request
import zlib

from .atomic import atomic_write_bytes, atomic_write_text
from .plantuml_runtime import (
    PlantUMLRuntime,
    ensure_plantuml_runtime,
    plantuml_online_enabled,
    plantuml_server_url,
)


PlantUMLStatusCallback = Callable[[str, str], None]


def _report_status(
    callback: Optional[PlantUMLStatusCallback],
    status: str,
    message: str,
) -> None:
    if callback is not None:
        callback(status, message)


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
    atomic_write_text(filepath, plantuml_code, encoding="utf-8")
    return filename


def _render_with_local_command(plantuml_code: str, filepath: Path, command_path: Path) -> bool:
    with tempfile.TemporaryDirectory() as tmp_dir:
        source_path = Path(tmp_dir) / "diagram.plantuml"
        output_path = Path(tmp_dir) / "diagram.png"
        source_path.write_text(plantuml_code, encoding="utf-8")
        result = subprocess.run(
            [str(command_path), "-tpng", str(source_path)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode == 0 and output_path.exists():
            atomic_write_bytes(filepath, output_path.read_bytes())
            return True
        print(f"PlantUML 本機指令輸出失敗 {filepath.name}: {result.stderr.strip() or result.stdout.strip()}")
        return False


def _render_with_local_jar(
    plantuml_code: str,
    filepath: Path,
    java_path: Path,
    jar_path: Path,
) -> bool:
    if not java_path.exists() or not jar_path.exists():
        return False
    with tempfile.TemporaryDirectory() as tmp_dir:
        source_path = Path(tmp_dir) / "diagram.plantuml"
        output_path = Path(tmp_dir) / "diagram.png"
        source_path.write_text(plantuml_code, encoding="utf-8")
        result = subprocess.run(
            [str(java_path), "-jar", str(jar_path), "-tpng", str(source_path)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode == 0 and output_path.exists():
            atomic_write_bytes(filepath, output_path.read_bytes())
            return True
        print(f"PlantUML JAR 輸出失敗 {filepath.name}: {result.stderr.strip() or result.stdout.strip()}")
        return False


def _render_with_server(plantuml_code: str, filepath: Path) -> bool:
    if not plantuml_online_enabled():
        return False
    url = f"{plantuml_server_url()}/png/{encode_plantuml(plantuml_code)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Plant-Modeler/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
        if data:
            atomic_write_bytes(filepath, data)
            return True
    except (urllib.error.URLError, urllib.error.HTTPError, socket.timeout, TimeoutError, OSError) as e:
        print(f"PlantUML 遠端 PNG 輸出失敗 {filepath.name}: {e}")
    return False


# ========
# Defines render plantuml png function for this module workflow.
# ========
def render_plantuml_png(
    artifact_dir: Path,
    model: Dict[str, Any],
    status_callback: Optional[PlantUMLStatusCallback] = None,
    runtime: Optional[PlantUMLRuntime] = None,
) -> Optional[str]:
    plantuml_code = model.get("plantuml", "")
    if not plantuml_code:
        return None
    safe_name = plantuml_safe_name(model)
    filename = f"{safe_name}.png"
    models_dir = artifact_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    filepath = models_dir / filename
    runtime = runtime or ensure_plantuml_runtime(status_callback=status_callback)
    if runtime.command_path and _render_with_local_command(
        plantuml_code,
        filepath,
        runtime.command_path,
    ):
        return filename
    if runtime.java_path and runtime.jar_path and _render_with_local_jar(
        plantuml_code,
        filepath,
        runtime.java_path,
        runtime.jar_path,
    ):
        return filename
    if _render_with_server(plantuml_code, filepath):
        return filename
    print(f"PlantUML PNG 輸出失敗 {filename}: 已保留 .plantuml 原始檔，可安裝本機 PlantUML 後重新輸出")
    return None


# ========
# Defines save plantuml files function for this module workflow.
# ========
def save_plantuml_files(
    artifact_dir: Path,
    model_data: Any,
    status_callback: Optional[PlantUMLStatusCallback] = None,
) -> None:
    models = [m for m in (model_data or []) if isinstance(m, dict) and m.get("plantuml")]
    if not models:
        return
    runtime = ensure_plantuml_runtime(status_callback=status_callback)
    online_fallback = runtime.mode == "online"
    if online_fallback:
        _report_status(
            status_callback,
            "online_fallback",
            "本機缺少 Java，正在改用線上 PlantUML 產生圖片…",
        )
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
            futures.append(
                executor.submit(
                    render_plantuml_png,
                    artifact_dir,
                    model,
                    status_callback,
                    runtime,
                )
            )
        for future in as_completed(futures):
            try:
                name = future.result()
                if name:
                    print(f"儲存 PlantUML 輸出: {name}")
            except Exception as e:
                print(f"儲存 PlantUML 失敗: {e}")
    for model in models:
        filename = f"{plantuml_safe_name(model)}.png"
        if (models_dir / filename).exists():
            model["image_path"] = f"../models/{filename}"
    if online_fallback:
        rendered_count = sum(
            1
            for model in models
            if (models_dir / f"{plantuml_safe_name(model)}.png").exists()
        )
        if rendered_count == len(models):
            _report_status(
                status_callback,
                "ready",
                "線上 PlantUML 圖片產生完成",
            )
        else:
            _report_status(
                status_callback,
                "failed",
                f"線上 PlantUML 圖片產生失敗：成功 {rendered_count}/{len(models)} 張",
            )
