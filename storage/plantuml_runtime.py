from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .atomic import atomic_write_text
from .coordinator import FileRunCoordinator


DEFAULT_PLANTUML_SERVER = "https://www.plantuml.com/plantuml"
ADOPTIUM_API_BASE = "https://api.adoptium.net"
PLANTUML_JAR_VERSION = "1.2026.6"
PLANTUML_JAR_SHA256 = "c65ad3c10dccc928f54a12ee6fab43c44e94eabbcbaf1bd0196f90bd6ace054d"
PLANTUML_JAR_URL = (
    "https://github.com/plantuml/plantuml/releases/download/"
    f"v{PLANTUML_JAR_VERSION}/plantuml-lgpl-{PLANTUML_JAR_VERSION}.jar"
)
JAVA_FEATURE_VERSION = 21
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLANTUML_TOOL_DIR = PROJECT_ROOT / "tools" / "plantuml"
MANAGED_JAVA_DIR = PLANTUML_TOOL_DIR / "runtime" / "java"
MANAGED_JAR_PATH = PLANTUML_TOOL_DIR / "plantuml.jar"
PlantUMLStatusCallback = Callable[[str, str], None]


@dataclass(frozen=True)
class PlantUMLRuntime:
    mode: str
    available: bool
    message: str
    command_path: Optional[Path] = None
    java_path: Optional[Path] = None
    jar_path: Optional[Path] = None


def plantuml_online_enabled(_config: Optional[Dict[str, Any]] = None) -> bool:
    return True


def plantuml_server_url() -> str:
    return DEFAULT_PLANTUML_SERVER


def _report(
    callback: Optional[PlantUMLStatusCallback],
    status: str,
    message: str,
) -> None:
    if callback is not None:
        callback(status, message)


def _platform_target() -> Optional[tuple[str, str]]:
    os_name = platform.system().lower()
    target_os = {"windows": "windows", "darwin": "mac", "linux": "linux"}.get(os_name)
    machine = platform.machine().lower()
    architecture = {
        "amd64": "x64",
        "x86_64": "x64",
        "arm64": "aarch64",
        "aarch64": "aarch64",
    }.get(machine)
    if not target_os or not architecture:
        return None
    return target_os, architecture


def _managed_java_path() -> Optional[Path]:
    executable = "java.exe" if os.name == "nt" else "java"
    if not MANAGED_JAVA_DIR.exists():
        return None
    candidates = sorted(MANAGED_JAVA_DIR.rglob(executable))
    for candidate in candidates:
        if candidate.parent.name == "bin" and candidate.is_file():
            return candidate
    return None


def _system_java_path() -> Optional[Path]:
    system_java = shutil.which("java")
    return Path(system_java) if system_java else None


def _valid_managed_jar() -> bool:
    if not MANAGED_JAR_PATH.exists() or not MANAGED_JAR_PATH.is_file():
        return False
    digest = hashlib.sha256(MANAGED_JAR_PATH.read_bytes()).hexdigest()
    return digest == PLANTUML_JAR_SHA256


def inspect_plantuml_runtime(config: Optional[Dict[str, Any]] = None) -> PlantUMLRuntime:
    command = shutil.which("plantuml")
    if command:
        return PlantUMLRuntime(
            mode="local_command",
            available=True,
            message="PlantUML 可使用本機指令產生圖片",
            command_path=Path(command),
        )

    java_path = _managed_java_path() or _system_java_path()
    jar_path = MANAGED_JAR_PATH if _valid_managed_jar() else None
    if java_path and jar_path:
        mode = "managed_local" if _managed_java_path() == java_path else "system_local"
        return PlantUMLRuntime(
            mode=mode,
            available=True,
            message="Java 與 PlantUML 本機執行環境可用",
            java_path=java_path,
            jar_path=jar_path,
        )

    if _platform_target() is not None:
        return PlantUMLRuntime(
            mode="download_required",
            available=True,
            message="Java 與 PlantUML 將在首次建立模型時自動準備",
            java_path=java_path,
            jar_path=jar_path,
        )

    if plantuml_online_enabled(config):
        return PlantUMLRuntime(
            mode="online",
            available=True,
            message="本機執行環境不可用，模型圖片將使用線上 PlantUML",
        )
    return PlantUMLRuntime(
        mode="source_only",
        available=False,
        message="無法產生模型圖片，僅會保存 PlantUML 原始檔",
    )


def _download_file(url: str, target: Path, expected_sha256: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "PLANT/1.0"})
    digest = hashlib.sha256()
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".download", dir=target.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as output, urllib.request.urlopen(request, timeout=120) as response:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        actual = digest.hexdigest()
        if actual.lower() != expected_sha256.lower():
            raise ValueError(f"SHA-256 不符，預期 {expected_sha256}，實際 {actual}")
        os.replace(temp_path, target)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _temurin_package() -> Dict[str, str]:
    target = _platform_target()
    if target is None:
        raise RuntimeError("目前作業系統或 CPU 架構不支援 Java Runtime 自動下載")
    operating_system, architecture = target
    query = urllib.parse.urlencode(
        {
            "architecture": architecture,
            "heap_size": "normal",
            "image_type": "jre",
            "jvm_impl": "hotspot",
            "os": operating_system,
            "page_size": 1,
            "project": "jdk",
            "sort_method": "DEFAULT",
            "sort_order": "DESC",
            "vendor": "eclipse",
        }
    )
    url = f"{ADOPTIUM_API_BASE}/v3/assets/latest/{JAVA_FEATURE_VERSION}/hotspot?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "PLANT/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    try:
        binary = payload[0]["binary"]
        package = binary["package"]
        return {
            "name": str(package["name"]),
            "url": str(package["link"]),
            "sha256": str(package["checksum"]),
            "version": str(payload[0]["version"]["semver"]),
            "os": operating_system,
            "architecture": architecture,
        }
    except (IndexError, KeyError, TypeError) as exc:
        raise RuntimeError("Eclipse Temurin API 未回傳可用的 Java Runtime") from exc


def _safe_destination(root: Path, member_name: str) -> Path:
    destination = (root / member_name).resolve()
    try:
        destination.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Runtime 壓縮檔包含不安全路徑：{member_name}") from exc
    return destination


def _extract_runtime(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                _safe_destination(destination, member.filename)
            bundle.extractall(destination)
        return
    if tarfile.is_tarfile(archive):
        with tarfile.open(archive, "r:*") as bundle:
            for member in bundle.getmembers():
                _safe_destination(destination, member.name)
                if member.issym():
                    _safe_destination(destination, str(Path(member.name).parent / member.linkname))
                elif member.islnk():
                    _safe_destination(destination, member.linkname)
            bundle.extractall(destination)
        return
    raise ValueError("不支援的 Java Runtime 壓縮格式")


def _replace_directory_with_retry(source: Path, target: Path) -> None:
    delay = 0.05
    for attempt in range(8):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if os.name != "nt" or attempt == 7:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.5)


def _install_managed_java(callback: Optional[PlantUMLStatusCallback]) -> tuple[Path, Dict[str, str]]:
    package = _temurin_package()
    PLANTUML_TOOL_DIR.mkdir(parents=True, exist_ok=True)
    archive = PLANTUML_TOOL_DIR / "java-runtime.download"
    staging = PLANTUML_TOOL_DIR / f".java-{os.getpid()}.staging"
    archive.unlink(missing_ok=True)
    if staging.exists():
        shutil.rmtree(staging)
    try:
        _report(callback, "downloading", "正在下載 Java 執行環境…")
        _download_file(package["url"], archive, package["sha256"])
        _report(callback, "installing", "正在準備 Java 執行環境…")
        _extract_runtime(archive, staging)
        executable = "java.exe" if os.name == "nt" else "java"
        java_candidates = [
            path for path in staging.rglob(executable) if path.parent.name == "bin" and path.is_file()
        ]
        if not java_candidates:
            raise RuntimeError("下載內容中找不到 Java 執行檔")
        if MANAGED_JAVA_DIR.exists():
            shutil.rmtree(MANAGED_JAVA_DIR)
        MANAGED_JAVA_DIR.parent.mkdir(parents=True, exist_ok=True)
        _replace_directory_with_retry(staging, MANAGED_JAVA_DIR)
        java_path = _managed_java_path()
        if java_path is None:
            raise RuntimeError("Java Runtime 安裝後仍找不到執行檔")
        return java_path, package
    finally:
        archive.unlink(missing_ok=True)
        if staging.exists():
            shutil.rmtree(staging)


def _install_managed_jar(callback: Optional[PlantUMLStatusCallback]) -> Path:
    _report(callback, "downloading", "正在下載 PlantUML…")
    _download_file(PLANTUML_JAR_URL, MANAGED_JAR_PATH, PLANTUML_JAR_SHA256)
    return MANAGED_JAR_PATH


def ensure_plantuml_runtime(
    config: Optional[Dict[str, Any]] = None,
    status_callback: Optional[PlantUMLStatusCallback] = None,
) -> PlantUMLRuntime:
    inspected = inspect_plantuml_runtime(config)
    if inspected.mode != "download_required":
        return inspected

    coordinator = FileRunCoordinator(PROJECT_ROOT)
    try:
        with coordinator.exclusive_lock("plantuml-runtime", timeout=300.0):
            java_path = _managed_java_path() or _system_java_path()
            jar_path = MANAGED_JAR_PATH if _valid_managed_jar() else None
            java_package: Optional[Dict[str, str]] = None
            if java_path is None:
                java_path, java_package = _install_managed_java(status_callback)
            if jar_path is None:
                jar_path = _install_managed_jar(status_callback)
            manifest = {
                "java": java_package or {"source": "managed-existing-or-system", "path": str(java_path)},
                "plantuml": {
                    "version": PLANTUML_JAR_VERSION,
                    "license": "LGPL",
                    "source": PLANTUML_JAR_URL,
                    "sha256": PLANTUML_JAR_SHA256,
                },
            }
            atomic_write_text(
                PLANTUML_TOOL_DIR / "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            _report(status_callback, "ready", "Java 與 PlantUML 執行環境準備完成")
            return PlantUMLRuntime(
                mode="managed_local" if _managed_java_path() == java_path else "system_local",
                available=True,
                message="Java 與 PlantUML 本機執行環境可用",
                java_path=java_path,
                jar_path=jar_path,
            )
    except Exception as exc:
        message = f"Java 與 PlantUML 執行環境準備失敗：{exc}"
        _report(status_callback, "failed", message)
        print(message)
        if plantuml_online_enabled(config):
            _report(status_callback, "online_fallback", "正在改用線上 PlantUML 產生圖片…")
            return PlantUMLRuntime("online", True, "模型圖片將使用線上 PlantUML")
        return PlantUMLRuntime("source_only", False, "僅會保存 PlantUML 原始檔")
