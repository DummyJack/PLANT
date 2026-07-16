from __future__ import annotations

import logging
from pathlib import Path

from utils.preflight.checks import run_preflight
from utils.preflight.models import PreflightReport, preflight_display_checks

from .api_key_validation import (
    PROVIDER_DISPLAY_NAMES,
    persist_api_key_validation_results,
    validate_configured_api_keys,
)


logger = logging.getLogger("Plant")
MAX_DISPLAYED_ERROR_LENGTH = 300


class BackendPreflightError(RuntimeError):
    """A user-facing startup failure that should be printed without a traceback."""


def concise_error(error: object) -> str:
    message = " ".join(str(error or "未知錯誤").split())
    if len(message) <= MAX_DISPLAYED_ERROR_LENGTH:
        return message
    return message[: MAX_DISPLAYED_ERROR_LENGTH - 3] + "..."


def format_preflight_failure(report: PreflightReport) -> str:
    failures = []
    for check in report.checks:
        if check.status != "error":
            continue
        failure = f"- {check.message}"
        if check.detail:
            failure += f"\n  詳細：{check.detail}"
        failures.append(failure)
    return "後端前置檢查失敗：\n" + "\n".join(failures)


def require_backend_preflight(base_dir: Path) -> PreflightReport:
    report = run_preflight(base_dir)
    if report.can_start:
        return report

    raise BackendPreflightError(format_preflight_failure(report))


def print_backend_preflight(report: PreflightReport) -> None:
    labels = {"ok": "OK", "info": "INFO", "warning": "WARN", "error": "ERROR"}
    for check in preflight_display_checks(report):
        label = labels[check.status]
        print(f"[{label}] {check.message}", flush=True)
        if check.detail:
            print(f"       {check.detail}", flush=True)
    print(flush=True)


def test_backend_api_keys(base_dir: Path) -> None:
    results = validate_configured_api_keys(base_dir)
    if not results:
        return

    print("API Key 連線測試", flush=True)
    for result in results:
        provider = PROVIDER_DISPLAY_NAMES[result.provider]
        if result.valid:
            print(f"[OK] {provider} API Key 可正常使用", flush=True)
        else:
            print(f"[WARN] {provider} API Key 測試失敗", flush=True)
            print(f"       原因：{concise_error(result.error)}", flush=True)
            logger.info("%s API Key startup test failed: %s", provider, result.error)
    try:
        persist_api_key_validation_results(base_dir, results)
    except (OSError, TimeoutError, ValueError) as exc:
        print("[WARN] API Key 測試狀態無法寫入 config.json", flush=True)
        print(f"       原因：{exc}", flush=True)
        logger.info("Unable to persist API Key startup test state: %s", exc)
    print(flush=True)


def run_backend_startup_checks(base_dir: Path) -> None:
    print("後端環境檢查", flush=True)
    report = require_backend_preflight(base_dir)
    print_backend_preflight(report)
    test_backend_api_keys(base_dir)
