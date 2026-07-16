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


def require_backend_preflight(base_dir: Path) -> PreflightReport:
    report = run_preflight(base_dir)
    if report.can_start:
        return report

    failures = [
        f"[{check.check_id}] {check.message}"
        + (f": {check.detail}" if check.detail else "")
        for check in report.checks
        if check.status == "error"
    ]
    raise RuntimeError("Backend preflight failed:\n" + "\n".join(failures))


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
            logger.warning("%s API Key startup test failed: %s", provider, result.error)
    try:
        persist_api_key_validation_results(base_dir, results)
    except OSError as exc:
        print("[WARN] API Key 測試狀態無法寫入 config.json", flush=True)
        logger.warning("Unable to persist API Key startup test state: %s", exc)
    print(flush=True)


def run_backend_startup_checks(base_dir: Path) -> None:
    print("後端環境檢查", flush=True)
    report = require_backend_preflight(base_dir)
    print_backend_preflight(report)
    test_backend_api_keys(base_dir)
