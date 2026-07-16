from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import dotenv_values
from storage import Store
from storage.atomic import atomic_write_text
from storage.coordinator import FileRunCoordinator
from storage.plantuml_runtime import (
    ensure_plantuml_runtime,
    inspect_plantuml_runtime,
    plantuml_server_url,
)
from utils.stage_validation import validate_stage_overrides

from .models import PreflightReport


MINIMUM_PYTHON = (3, 10)
MINIMUM_FREE_BYTES = 1024 * 1024 * 1024
WARNING_FREE_BYTES = 2 * 1024 * 1024 * 1024
HOST_PATTERN = re.compile(
    r"^(?:localhost|(?:\d{1,3}\.){3}\d{1,3}|[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?)$"
)


def _check_python(report: PreflightReport) -> None:
    current = sys.version_info[:3]
    rendered = ".".join(str(part) for part in current)
    if current < MINIMUM_PYTHON:
        report.add(
            "python_version",
            "error",
            f"不支援 Python {rendered}，需要 Python 3.10 以上版本",
        )
        return
    report.add("python_version", "ok", f"Python {rendered}")


def _load_config(report: PreflightReport, base_dir: Path) -> Optional[Dict[str, Any]]:
    path = base_dir / "config.json"
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            config = json.load(handle)
    except FileNotFoundError:
        report.add("config", "error", "找不到 config.json", str(path))
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        report.add("config", "error", "無法讀取 config.json", str(exc))
        return None
    if not isinstance(config, dict):
        report.add("config", "error", "config.json 最外層必須是物件", str(path))
        return None
    preflight = config.get("preflight")
    if preflight is not None and (
        not isinstance(preflight, dict)
        or any(
            name in preflight and not isinstance(preflight[name], bool)
            for name in ("system", "server")
        )
    ):
        report.add(
            "config",
            "error",
            "preflight.system 與 preflight.server 必須是布林值",
            str(path),
        )
        return config
    report.add("config", "ok", "config.json 格式正確")
    return config


def _check_non_negative_integer(
    report: PreflightReport,
    config: Dict[str, Any],
    key: str,
    *,
    maximum: int,
) -> None:
    value = config.get(key)
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        report.add("config", "error", f"{key} 必須是整數", str(value))
        return
    if parsed < 0 or parsed > maximum:
        report.add("config", "error", f"{key} 必須介於 0 與 {maximum} 之間", str(value))


def _check_positive_integer(
    report: PreflightReport,
    config: Dict[str, Any],
    key: str,
    *,
    maximum: int,
) -> None:
    value = config.get(key)
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        report.add("config_limits", "error", f"config 的 {key} 必須是整數")
        return
    if parsed < 1 or parsed > maximum:
        report.add(
            "config_limits",
            "error",
            f"config 的 {key} 必須介於 1 到 {maximum} 之間",
        )


def _check_stage_config(report: PreflightReport, config: Dict[str, Any]) -> None:
    stage = config.get("stage", {})
    try:
        validate_stage_overrides(stage)
    except ValueError as exc:
        report.add("stage_config", "error", "Stage 設定無效", str(exc))
        return

    draft_enabled = stage.get("draft", True)
    default_update = stage.get("default_update_draft", True)
    general_update = stage.get("general_update_draft", True)
    if not draft_enabled and (default_update or general_update):
        report.add(
            "stage_config",
            "error",
            "關閉草稿階段時不能開啟草稿更新階段",
        )
        return

    report.add("stage_config", "ok", "Stage 設定正確")


def _check_environment(
    report: PreflightReport,
    base_dir: Path,
    config: Dict[str, Any],
) -> None:
    try:
        values = dotenv_values(base_dir / ".env")
    except (OSError, UnicodeError) as exc:
        report.add("environment", "error", "無法讀取 .env", str(exc))
        return

    frontend_host = str(
        os.getenv("frontend_host") or values.get("frontend_host") or "127.0.0.1"
    ).strip()
    if (
        not HOST_PATTERN.fullmatch(frontend_host)
        or "://" in frontend_host
        or "/" in frontend_host
    ):
        report.add(
            "frontend_host",
            "error",
            "frontend_host 必須是主機名稱或 IP，不可包含協定、Port 或路徑",
        )
    else:
        report.add("frontend_host", "ok", "frontend_host 設定正確")

    raw_codes = str(
        os.getenv("activation_code") or values.get("activation_code") or ""
    ).strip()
    codes = [code.strip() for code in raw_codes.split(",") if code.strip()]
    if not codes:
        report.add(
            "activation_code",
            "warning",
            "尚未設定啟動碼，網站將維持唯讀模式",
        )
    elif any(len(code) < 8 for code in codes):
        report.add(
            "activation_code",
            "warning",
            "啟動碼長度過短，建議每組至少使用 8 個字元",
        )
    else:
        report.add("activation_code", "ok", "啟動碼設定正確")

    enabled_tools = config.get("enable_tools")
    web_search_enabled = (
        isinstance(enabled_tools, dict) and bool(enabled_tools.get("web_search", False))
    )
    tavily_key = str(
        os.getenv("TAVILY_API_KEY") or values.get("TAVILY_API_KEY") or ""
    ).strip()
    if web_search_enabled and (
        not tavily_key or tavily_key.lower() == "your_tavily_api_key"
    ):
        try:
            coordinator = FileRunCoordinator(base_dir)
            with coordinator.exclusive_lock("config", timeout=30.0):
                store = Store(base_dir)
                latest = store.load_config()
                enabled_tools = latest.get("enable_tools")
                if not isinstance(enabled_tools, dict):
                    enabled_tools = {}
                    latest["enable_tools"] = enabled_tools
                if enabled_tools.get("web_search", False):
                    enabled_tools["web_search"] = False
                    store.save_config(latest)
            current_tools = config.get("enable_tools")
            if not isinstance(current_tools, dict):
                current_tools = {}
                config["enable_tools"] = current_tools
            current_tools["web_search"] = False
        except (OSError, ValueError, TimeoutError) as exc:
            report.add(
                "tavily_api_key",
                "error",
                "缺少 TAVILY_API_KEY，且無法自動關閉網路搜尋",
                str(exc),
            )
        else:
            report.add(
                "tavily_api_key",
                "warning",
                "尚未設定有效的 TAVILY_API_KEY，已自動關閉網路搜尋",
            )


def _probe_directory(path: Path) -> Optional[str]:
    target: Optional[Path] = None
    try:
        path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir():
            raise NotADirectoryError(str(path))
        target = path / f".preflight-{uuid.uuid4().hex}.json"
        atomic_write_text(target, '{"preflight":true}\n')
        if target.read_text(encoding="utf-8") != '{"preflight":true}\n':
            raise OSError("atomic write verification returned unexpected content")
        target.unlink()
    except OSError as exc:
        if target is not None:
            target.unlink(missing_ok=True)
        return str(exc)
    return None


def _check_storage_directories(report: PreflightReport, base_dir: Path) -> None:
    directories = {
        "projects": base_dir / "projects",
        "runtime": base_dir / "projects" / ".runtime",
        "doc": base_dir / "doc",
        "log": base_dir / "log",
    }
    failures = []
    root_error = _probe_directory(base_dir)
    if root_error:
        failures.append(f"config.json 所在目錄（{base_dir}）：{root_error}")

    config_path = base_dir / "config.json"
    if config_path.is_file():
        try:
            with config_path.open("r+", encoding="utf-8-sig"):
                pass
        except OSError as exc:
            failures.append(f"config.json（{config_path}）：{exc}")

    for name, path in directories.items():
        error = _probe_directory(path)
        if error:
            failures.append(f"{name}（{path}）：{error}")

    if failures:
        report.add(
            "storage_directories",
            "error",
            "設定、專案、附件或執行紀錄無法正常儲存資料",
            "；".join(failures),
        )
        return
    report.add(
        "storage_directories",
        "ok",
        "設定、專案、附件與執行紀錄皆可正常儲存",
    )


def _check_temp_directory(report: PreflightReport) -> None:
    try:
        with tempfile.NamedTemporaryFile(prefix="plant-preflight-", delete=True) as handle:
            handle.write(b"ok")
            handle.flush()
    except OSError as exc:
        report.add("temp_storage", "error", "系統暫存目錄無法寫入", str(exc))
        return
    report.add("temp_storage", "ok", "系統暫存目錄可寫入")


def _check_disk_space(report: PreflightReport, base_dir: Path) -> None:
    try:
        free = shutil.disk_usage(base_dir).free
    except OSError as exc:
        report.add("disk_space", "warning", "無法取得磁碟可用空間", str(exc))
        return
    free_mb = free // (1024 * 1024)
    if free < MINIMUM_FREE_BYTES:
        report.add("disk_space", "error", f"磁碟可用空間僅剩 {free_mb} MB")
    elif free < WARNING_FREE_BYTES:
        report.add("disk_space", "warning", f"磁碟可用空間僅剩 {free_mb} MB")
    else:
        report.add("disk_space", "ok", f"磁碟可用空間為 {free_mb} MB")


def _check_plantuml_runtime(report: PreflightReport, config: Dict[str, Any]) -> None:
    runtime = inspect_plantuml_runtime(config)
    preparation_messages: list[str] = []
    if runtime.mode == "download_required":
        runtime = ensure_plantuml_runtime(
            config,
            status_callback=lambda _status, message: preparation_messages.append(message),
        )

    if runtime.mode in {"online", "source_only"}:
        status = "warning"
    else:
        status = "ok"
    detail = "；".join(preparation_messages) or None
    report.add("plantuml_runtime", status, runtime.message, detail)

    if runtime.mode == "online":
        sources = [plantuml_server_url()]
    else:
        return

    def probe(url: str) -> Optional[str]:
        request = urllib.request.Request(
            url,
            method="HEAD",
            headers={"User-Agent": "PLANT/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=5):
                return None
        except urllib.error.HTTPError as exc:
            return None if exc.code < 500 else f"HTTP {exc.code}"
        except (OSError, urllib.error.URLError) as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=len(sources)) as executor:
        results = list(executor.map(probe, sources))
    failures = [f"{url}：{error}" for url, error in zip(sources, results) if error]
    if failures:
        report.add(
            "plantuml_sources",
            "warning",
            "目前無法連線至 Java／PlantUML 下載來源",
            "；".join(failures),
        )


def run_preflight(base_dir: Path) -> PreflightReport:
    """Run startup checks that are shared by CLI and server entrypoints."""
    root = Path(base_dir).resolve()
    report = PreflightReport()
    _check_python(report)
    report.config = _load_config(report, root)
    if report.config is not None:
        _check_stage_config(report, report.config)
        _check_environment(report, root, report.config)
        stage = report.config.get("stage") if isinstance(report.config.get("stage"), dict) else {}
        if stage.get("general_formal_meeting", True):
            _check_non_negative_integer(report, report.config, "rounds", maximum=20)
        _check_positive_integer(report, report.config, "max_issues", maximum=50)
        _check_plantuml_runtime(report, report.config)
    _check_storage_directories(report, root)
    _check_temp_directory(report)
    _check_disk_space(report, root)
    return report
