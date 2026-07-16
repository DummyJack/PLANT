from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from storage import Store

from server.services.config_service import validate_config
from storage.coordinator import FileRunCoordinator
from .auth import require_write_access


router = APIRouter()


class ConfigPatch(BaseModel):
    patch: Dict[str, Any]


def deep_merge(current: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(current)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def base_dir(request: Request) -> Path:
    return request.app.state.base_dir


@router.get("/config")
def get_config(request: Request):
    return {"config": Store(base_dir(request)).load_config()}


@router.patch("/config")
def patch_config(payload: ConfigPatch, request: Request):
    require_write_access(request)
    coordinator = FileRunCoordinator(base_dir(request))
    with coordinator.exclusive_lock("config"):
        store = Store(base_dir(request))
        updated = deep_merge(store.load_config(), payload.patch)
        result = validate_config(updated)
        if not result["valid"]:
            raise HTTPException(status_code=400, detail={"errors": result["errors"]})
        store.save_config(updated)
    return {"saved": True, "config": updated}
