import os
from pathlib import Path
from typing import Dict

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel


router = APIRouter()

MODEL_API_KEY_ENV: Dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


class ModelApiKeyUpdate(BaseModel):
    provider: str
    api_key: str


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


@router.get("/model-api-keys")
def get_model_api_keys(request: Request):
    file_values = read_env(env_path(request))
    providers = []
    for provider, env_key in MODEL_API_KEY_ENV.items():
        value = os.getenv(env_key) or file_values.get(env_key) or ""
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
