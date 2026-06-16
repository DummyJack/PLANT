import hashlib
import hmac
import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from fastapi import HTTPException, Request, Response

ACTIVATION_COOKIE = "plant_activation"
WRITE_FORBIDDEN_MESSAGE = "需要啟動碼才能執行此操作"


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


def require_project_read_access(request: Request, project_id: str) -> None:
    # Current deployment model has shared read access and activation-gated writes.
    # Keep this hook centralized so project ownership checks can be added without
    # touching every route.
    project_dir = request.app.state.base_dir / "projects" / project_id
    if not project_dir.exists() or not project_dir.is_dir():
        raise HTTPException(status_code=404, detail="Project not found")


def set_activation_cookie(response: Response, request: Request, code: str) -> None:
    response.set_cookie(
        ACTIVATION_COOKIE,
        _token(request.app.state.base_dir, code),
        max_age=60 * 60 * 24 * 30,
        httponly=True,
        samesite="lax",
        secure=False,
    )


def clear_activation_cookie(response: Response) -> None:
    response.delete_cookie(ACTIVATION_COOKIE, httponly=True, samesite="lax", secure=False)
