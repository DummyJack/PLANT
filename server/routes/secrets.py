from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from storage import Store
from storage.atomic import atomic_write_text
from storage.coordinator import FileRunCoordinator
from ..services.activation_rate_limit import verify_activation_attempt
from ..services.api_key_validation import MODEL_API_KEY_ENV, test_provider_api_key
from .auth import (
    _valid_codes,
    clear_activation_cookie,
    is_activated,
    require_write_access,
    set_activation_cookie,
)


router = APIRouter()

class ModelApiKeyUpdate(BaseModel):
    provider: str
    api_key: str


class ModelApiKeyTest(BaseModel):
    provider: str


class ActivationCodePayload(BaseModel):
    code: str


def env_path(request: Request) -> Path:
    return request.app.state.base_dir / ".env"


def read_env(path: Path) -> Dict[str, str]:
    rows: Dict[str, str] = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        rows[key.strip()] = value.strip().strip('"').strip("'")
    return rows


def write_env_value(path: Path, key: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    updated = False
    out = []
    for line in lines:
        if line.strip().startswith(f"{key}="):
            out.append(f"{key}={value}")
            updated = True
        else:
            out.append(line)
    if not updated:
        out.append(f"{key}={value}")
    atomic_write_text(path, "\n".join(out).rstrip() + "\n", encoding="utf-8")


def remove_env_value(path: Path, key: str) -> bool:
    if not path.exists():
        return False
    lines = path.read_text(encoding="utf-8").splitlines()
    removed = False
    out = []
    for line in lines:
        if line.strip().startswith(f"{key}="):
            removed = True
            continue
        out.append(line)
    atomic_write_text(
        path,
        "\n".join(out).rstrip() + ("\n" if out else ""),
        encoding="utf-8",
    )
    return removed


API_KEY_TEST_STATUSES = {"valid", "invalid", "untested"}


def read_api_key_test_state(request: Request) -> Dict[str, str]:
    config = Store(request.app.state.base_dir).load_config()
    state = config.get("api_state") if isinstance(config, dict) else None
    if not isinstance(state, dict):
        return {}
    rows: Dict[str, str] = {}
    for provider, value in state.items():
        if isinstance(value, str) and value in API_KEY_TEST_STATUSES:
            rows[provider] = value
    return rows


def set_api_key_test_state(
    request: Request,
    provider: str,
    *,
    status: str,
    error: Optional[str] = None,
) -> Dict[str, Optional[str] | bool]:
    coordinator = FileRunCoordinator(request.app.state.base_dir)
    with coordinator.exclusive_lock("config"):
        store = Store(request.app.state.base_dir)
        config = store.load_config()
        state = dict(config.get("api_state") or {}) if isinstance(config.get("api_state"), dict) else {}
        normalized_status = status if status in API_KEY_TEST_STATUSES else "untested"
        state[provider] = normalized_status
        config["api_state"] = state
        store.save_config(config)
    return {
        "status": normalized_status,
        "valid": normalized_status == "valid",
        "error": error,
    }


def normalized_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized not in MODEL_API_KEY_ENV:
        raise HTTPException(status_code=400, detail="Unsupported provider")
    return normalized


def api_key_for_provider(request: Request, provider: str) -> tuple[str, str]:
    env_key = MODEL_API_KEY_ENV[provider]
    file_values = read_env(env_path(request))
    api_key = (os.getenv(env_key) or file_values.get(env_key) or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="API Key is not configured")
    return env_key, api_key


@router.get("/model-api-keys")
def get_model_api_keys(request: Request):
    file_values = read_env(env_path(request))
    test_state = read_api_key_test_state(request)
    providers = []
    for provider, env_key in MODEL_API_KEY_ENV.items():
        file_value = (file_values.get(env_key) or "").strip()
        environment_value = (os.getenv(env_key) or "").strip()
        value = environment_value or file_value
        configured = bool(value)
        status = test_state.get(provider, "untested") if configured else "untested"
        valid = status == "valid"
        providers.append(
            {
                "provider": provider,
                "env_key": env_key,
                "configured": configured,
                "status": status,
                "valid": valid,
                "error": None,
                "tested_at": None,
            }
        )
    return {"providers": providers}


@router.put("/model-api-keys")
def put_model_api_key(payload: ModelApiKeyUpdate, request: Request):
    require_write_access(request)
    provider = normalized_provider(payload.provider)
    env_key = MODEL_API_KEY_ENV[provider]
    api_key = payload.api_key.strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="api_key cannot be empty")
    if any(character in api_key for character in ("\r", "\n", "\x00")):
        raise HTTPException(status_code=400, detail="api_key must be a single line")
    path = env_path(request)
    coordinator = FileRunCoordinator(request.app.state.base_dir)
    with coordinator.exclusive_lock("secrets", timeout=30.0):
        write_env_value(path, env_key, api_key)
        os.environ[env_key] = api_key
        load_dotenv(path, override=True)
        set_api_key_test_state(request, provider, status="untested")
    return {
        "saved": True,
        "provider": provider,
        "env_key": env_key,
        "configured": True,
        "status": "untested",
        "valid": False,
        "error": None,
        "tested_at": None,
    }


@router.post("/model-api-keys/test")
def test_model_api_key(payload: ModelApiKeyTest, request: Request):
    require_write_access(request)
    provider = normalized_provider(payload.provider)
    coordinator = FileRunCoordinator(request.app.state.base_dir)
    with coordinator.exclusive_lock("secrets", timeout=30.0):
        env_key, api_key = api_key_for_provider(request, provider)
        error = test_provider_api_key(provider, api_key)
        status = "valid" if error is None else "invalid"
        state = set_api_key_test_state(request, provider, status=status, error=error)
    valid = bool(state["valid"])
    return {
        "provider": provider,
        "env_key": env_key,
        "configured": True,
        "valid": valid,
        "error": error,
        "status": state["status"],
        "tested_at": None,
    }


@router.delete("/model-api-keys/{provider}")
def delete_model_api_key(provider: str, request: Request):
    require_write_access(request)
    normalized = normalized_provider(provider)
    env_key = MODEL_API_KEY_ENV[normalized]
    path = env_path(request)
    coordinator = FileRunCoordinator(request.app.state.base_dir)
    with coordinator.exclusive_lock("secrets", timeout=30.0):
        removed = remove_env_value(path, env_key)
        os.environ.pop(env_key, None)
        load_dotenv(path, override=True)
        set_api_key_test_state(request, normalized, status="untested")
    return {
        "deleted": True,
        "provider": normalized,
        "env_key": env_key,
        "configured": False,
        "removed": removed,
        "status": "untested",
        "valid": False,
        "error": None,
        "tested_at": None,
    }


@router.get("/activation-code")
def activation_status(request: Request):
    return {"activated": is_activated(request)}


@router.post("/activation-code")
def activate_code(payload: ActivationCodePayload, request: Request, response: Response):
    code = payload.code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="啟動碼不能為空")
    valid_codes = _valid_codes(request.app.state.base_dir)
    client_id = request.client.host if request.client else "unknown"
    valid, retry_after = verify_activation_attempt(
        request.app.state.base_dir,
        client_id,
        code,
        valid_codes,
    )
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="啟動碼嘗試次數過多，請稍後再試",
            headers={"Retry-After": str(retry_after)},
        )
    if not valid:
        raise HTTPException(status_code=400, detail="無效的啟動碼")
    set_activation_cookie(response, request, code)
    return {"activated": True}


@router.delete("/activation-code")
def deactivate_code(request: Request, response: Response):
    clear_activation_cookie(response, request)
    return {"activated": False}
