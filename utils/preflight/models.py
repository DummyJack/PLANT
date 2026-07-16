from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


PREFLIGHT_STATUSES = {"ok", "info", "warning", "error"}


@dataclass(frozen=True)
class PreflightCheck:
    check_id: str
    status: str
    message: str
    detail: Optional[str] = None

    def __post_init__(self) -> None:
        if self.status not in PREFLIGHT_STATUSES:
            raise ValueError(f"Unsupported preflight status: {self.status}")


@dataclass
class PreflightReport:
    checks: List[PreflightCheck] = field(default_factory=list)
    config: Optional[Dict[str, Any]] = field(default=None, repr=False)

    @property
    def can_start(self) -> bool:
        return not any(check.status == "error" for check in self.checks)

    def add(
        self,
        check_id: str,
        status: str,
        message: str,
        detail: Optional[str] = None,
    ) -> None:
        self.checks.append(PreflightCheck(check_id, status, message, detail))


def preflight_display_checks(report: PreflightReport) -> List[PreflightCheck]:
    """Return concise startup rows while retaining the full report internally."""
    by_id = {check.check_id: check for check in report.checks}
    rows: List[PreflightCheck] = []

    python_check = by_id.get("python_version")
    if python_check:
        rows.append(python_check)

    setting_ids = {"config", "stage_config", "config_limits"}
    setting_checks = [check for check in report.checks if check.check_id in setting_ids]
    setting_problems = [check for check in setting_checks if check.status == "error"]
    if setting_problems:
        rows.extend(setting_problems)
    elif {"config", "stage_config"}.issubset(by_id):
        rows.append(PreflightCheck("system_config", "ok", "系統設定正確"))

    storage_check = by_id.get("storage_directories")
    if storage_check:
        if storage_check.status == "ok":
            rows.append(PreflightCheck("storage_directories", "ok", "資料儲存環境正常"))
        else:
            rows.append(storage_check)

    plantuml_check = by_id.get("plantuml_runtime")
    if plantuml_check:
        rows.append(plantuml_check)

    for check_id in ("temp_storage", "disk_space"):
        check = by_id.get(check_id)
        if check and check.status != "ok":
            rows.append(check)

    displayed_ids = {check.check_id for check in rows} | setting_ids
    rows.extend(
        check
        for check in report.checks
        if check.check_id not in displayed_ids
        and check.check_id not in {"plantuml_runtime", "temp_storage", "disk_space"}
        and check.status in {"info", "warning", "error"}
    )
    return rows
