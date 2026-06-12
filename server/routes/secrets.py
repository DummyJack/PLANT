import os
from pathlib import Path
from typing import Dict

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from storage import Store
from .auth import (
    _valid_codes,
    clear_activation_cookie,
    is_activated,
    require_write_access,
    set_activation_cookie,
)


router = APIRouter()

MODEL_API_KEY_ENV: Dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


class ModelApiKeyUpdate(BaseModel):
    provider: str
    api_key: str


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
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


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
    path.write_text("\n".join(out).rstrip() + ("\n" if out else ""), encoding="utf-8")
    return removed


@router.get("/model-api-keys")
def get_model_api_keys(request: Request):
    file_values = read_env(env_path(request))
    providers = []
    for provider, env_key in MODEL_API_KEY_ENV.items():
        value = file_values.get(env_key) or ""
        providers.append(
            {
                "provider": provider,
                "env_key": env_key,
                "configured": bool(value),
            }
        )
    return {"providers": providers}


@router.put("/model-api-keys")
def put_model_api_key(payload: ModelApiKeyUpdate, request: Request):
    require_write_access(request)
    provider = payload.provider.strip().lower()
    env_key = MODEL_API_KEY_ENV.get(provider)
    if not env_key:
        raise HTTPException(status_code=400, detail="Unsupported provider")
    api_key = payload.api_key.strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="api_key cannot be empty")
    path = env_path(request)
    write_env_value(path, env_key, api_key)
    os.environ[env_key] = api_key
    load_dotenv(path, override=True)
    return {"saved": True, "provider": provider, "env_key": env_key, "configured": True}


@router.delete("/model-api-keys/{provider}")
def delete_model_api_key(provider: str, request: Request):
    require_write_access(request)
    normalized = provider.strip().lower()
    env_key = MODEL_API_KEY_ENV.get(normalized)
    if not env_key:
        raise HTTPException(status_code=400, detail="Unsupported provider")
    path = env_path(request)
    removed = remove_env_value(path, env_key)
    os.environ.pop(env_key, None)
    load_dotenv(path, override=True)
    return {
        "deleted": True,
        "provider": normalized,
        "env_key": env_key,
        "configured": False,
        "removed": removed,
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
    if code not in valid_codes:
        raise HTTPException(status_code=400, detail="無效的啟動碼")
    set_activation_cookie(response, request, code)
    return {"activated": True}


@router.delete("/activation-code")
def deactivate_code(response: Response):
    clear_activation_cookie(response)
    return {"activated": False}
