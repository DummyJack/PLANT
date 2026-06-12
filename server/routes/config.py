from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from storage import Store

from server.services.config_service import validate_config
from .auth import require_write_access


router = APIRouter()


class ConfigUpdate(BaseModel):
    config: Dict[str, Any]


def base_dir(request: Request) -> Path:
    return request.app.state.base_dir


@router.get("/config")
def get_config(request: Request):
    return {"config": Store(base_dir(request)).load_config()}


@router.post("/config/validate")
def validate_config_endpoint(payload: ConfigUpdate, request: Request):
    return validate_config(payload.config)


@router.put("/config")
def put_config(payload: ConfigUpdate, request: Request):
    require_write_access(request)
    result = validate_config(payload.config)
    if not result["valid"]:
        raise HTTPException(status_code=400, detail={"errors": result["errors"]})
    Store(base_dir(request)).save_config(payload.config)
    return {"saved": True, "config": payload.config}
