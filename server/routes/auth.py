import hashlib
import hmac
import os
from pathlib import Path
from typing import List
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import HTTPException, Request, Response

from server.services.security import validate_project_id

ACTIVATION_COOKIE = "plant_activation"
WRITE_FORBIDDEN_MESSAGE = "需要啟動碼才能執行此操作"
READ_FORBIDDEN_MESSAGE = "需要啟動碼才能查看執行中或尚未產生成果的專案"
ACTIVE_RUN_STATUSES = {"queued", "running", "waiting_for_human", "cancelling"}
PUBLIC_READABLE_RESULT_STATUSES = {"completed", "idle"}


def _valid_codes(base_dir: Path) -> List[str]:
    load_dotenv(base_dir / ".env")
    env_codes = os.getenv("activation_code", "").strip()
    return [code.strip() for code in env_codes.split(",") if code.strip()]


def _token(base_dir: Path, code: str) -> str:
    key = str(base_dir.resolve()).encode("utf-8")
    return hmac.new(key, code.encode("utf-8"), hashlib.sha256).hexdigest()


def is_activated(request: Request) -> bool:
    value = request.cookies.get(ACTIVATION_COOKIE, "").strip()
    if not value:
        return False
    base_dir = request.app.state.base_dir
    return any(hmac.compare_digest(value, _token(base_dir, code)) for code in _valid_codes(base_dir))


def require_write_access(request: Request) -> None:
    if not is_activated(request):
        raise HTTPException(status_code=403, detail=WRITE_FORBIDDEN_MESSAGE)


def project_exists(request: Request, project_id: str) -> bool:
    project_id = validate_project_id(project_id)
    project_dir = request.app.state.base_dir / "projects" / project_id
    project_file = project_dir / "artifact" / "project.json"
    return project_dir.exists() and project_dir.is_dir() and project_file.exists()


def project_has_results(request: Request, project_id: str) -> bool:
    project_id = validate_project_id(project_id)
    results_dir = request.app.state.base_dir / "projects" / project_id / "results"
    return results_dir.exists() and any(path.is_file() for path in results_dir.rglob("*"))


def project_has_active_run(request: Request, project_id: str) -> bool:
    project_id = validate_project_id(project_id)
    run_manager = getattr(request.app.state, "run_manager", None)
    if not run_manager:
        return False
    if run_manager.get_active_run(project_id):
        return True
    runs = run_manager.list_runs(project_id=project_id)
    latest = runs[0] if runs else {}
    return str(latest.get("status") or "").strip() in ACTIVE_RUN_STATUSES


def project_latest_status(request: Request, project_id: str) -> str:
    project_id = validate_project_id(project_id)
    run_manager = getattr(request.app.state, "run_manager", None)
    if not run_manager:
        return "idle"
    runs = run_manager.list_runs(project_id=project_id)
    if not runs:
        return "idle"
    return str(runs[0].get("status") or "idle").strip() or "idle"


def can_read_project(request: Request, project_id: str) -> bool:
    try:
        if not project_exists(request, project_id):
            return False
        if is_activated(request):
            return True
        return (
            project_has_results(request, project_id)
            and not project_has_active_run(request, project_id)
            and project_latest_status(request, project_id) in PUBLIC_READABLE_RESULT_STATUSES
        )
    except HTTPException:
        return False


def require_project_read_access(request: Request, project_id: str) -> None:
    if not project_exists(request, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    if not can_read_project(request, project_id):
        raise HTTPException(status_code=403, detail=READ_FORBIDDEN_MESSAGE)


def _cross_site_cookie(request: Request) -> bool:
    origin = request.headers.get("origin", "").strip()
    if not origin:
        return False
    origin_host = urlparse(origin).hostname
    request_host = request.url.hostname
    return bool(origin_host and request_host and origin_host != request_host)


def _cookie_options(request: Request) -> dict[str, object]:
    if _cross_site_cookie(request):
        return {"samesite": "none", "secure": True}
    return {"samesite": "lax", "secure": False}


def set_activation_cookie(response: Response, request: Request, code: str) -> None:
    response.set_cookie(
        ACTIVATION_COOKIE,
        _token(request.app.state.base_dir, code),
        max_age=60 * 60 * 24 * 30,
        httponly=True,
        **_cookie_options(request),
    )


def clear_activation_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(ACTIVATION_COOKIE, httponly=True, **_cookie_options(request))
