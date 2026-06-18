from pathlib import Path
import shutil
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from storage import Store
from utils import format_loaded_models_summary
from utils.language import sync_output_language

from server.services.project_service import ProjectService
from server.services.run_config import general_formal_meeting_enabled
from .auth import require_write_access


router = APIRouter()


class ProjectCreate(BaseModel):
    rough_idea: str


class ProjectUpdate(BaseModel):
    rough_idea: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None


class ProjectExport(BaseModel):
    html: bool = True
    cost: bool = True
    manual: bool = True


def base_dir(request: Request) -> Path:
    return request.app.state.base_dir


def project_service(request: Request) -> ProjectService:
    return ProjectService(base_dir(request), run_manager=request.app.state.run_manager)


@router.get("/bootstrap")
def bootstrap(request: Request):
    service = project_service(request)
    run_manager = request.app.state.run_manager
    store = Store(base_dir(request))
    config_status: Dict[str, Any] = {"loaded": False, "error": None}
    model_summary = ""
    key_status = {"valid": True, "error": None}
    config: Optional[Dict[str, Any]] = None
    try:
        config = store.load_config()
        config_status["loaded"] = True
        model_summary = format_loaded_models_summary(config)
    except Exception as exc:
        config_status["error"] = str(exc)
    return {
        "config": config_status,
        "model_summary": model_summary,
        "api_keys": key_status,
        "projects": service.list_projects_enriched(),
        "active_runs": service.active_runs_map(),
        "interrupted_run_count": run_manager.count_interrupted_runs(),
        "formal_meeting_enabled": bool(
            config
            and (
                ((config.get("stage") or {}).get("default_formal_meeting", True))
                or ((config.get("stage") or {}).get("general_formal_meeting", True))
            )
        ),
        "requires_rounds_input": bool(config and general_formal_meeting_enabled(config)),
    }


@router.get("/projects")
def list_projects(request: Request, enriched: bool = True):
    service = project_service(request)
    if enriched:
        return {"projects": service.list_projects_enriched()}
    return {"projects": Store(base_dir(request)).list_projects()}


@router.post("/projects")
def create_project(payload: ProjectCreate, request: Request):
    require_write_access(request)
    rough_idea = payload.rough_idea.strip()
    if not rough_idea:
        raise HTTPException(status_code=400, detail="rough_idea is required")
    store = Store(base_dir(request))
    project_id = store.create_project()
    project_root = base_dir(request) / "projects" / project_id
    try:
        project_store = Store(base_dir(request), project_id)
        artifact = {
            "rough_idea": rough_idea,
            "stakeholders": [],
            "scope": {"in_scope": [], "out_of_scope": []},
            "URL": [],
            "feedback": {},
            "system_models": [],
            "meta": {"last_round": 0},
        }
        sync_output_language(rough_idea, artifact)
        project_store.save_artifact(artifact)
    except Exception:
        shutil.rmtree(project_root, ignore_errors=True)
        raise
    return {"project_id": project_id, "rough_idea": rough_idea}


@router.get("/projects/{project_id}/summary")
def get_project_summary(project_id: str, request: Request):
    return project_service(request).get_summary(project_id)


@router.get("/projects/{project_id}/active-run")
def get_active_run(project_id: str, request: Request):
    project_service(request).ensure_project(project_id)
    active_run = request.app.state.run_manager.get_active_run(project_id)
    return {"project_id": project_id, "active_run": active_run}


@router.get("/projects/{project_id}/cost-summary")
def get_cost_summary(project_id: str, request: Request):
    return project_service(request).get_cost_summary(project_id)


@router.post("/projects/{project_id}/export")
def export_project(project_id: str, payload: ProjectExport, request: Request):
    require_write_access(request)
    return project_service(request).export_project(
        project_id,
        html=payload.html,
        cost=payload.cost,
        manual=payload.manual,
    )


@router.get("/projects/{project_id}/references")
def list_references(project_id: str, request: Request):
    return project_service(request).list_references(project_id)


@router.get("/projects/{project_id}/references/{name}")
def download_reference(project_id: str, name: str, request: Request, inline: bool = False):
    target = project_service(request).reference_path(project_id, name)
    return FileResponse(
        target,
        filename=target.name,
        content_disposition_type="inline" if inline else "attachment",
    )


@router.post("/projects/{project_id}/references")
async def upload_reference(
    project_id: str,
    request: Request,
    file: UploadFile = File(...),
):
    require_write_access(request)
    return await project_service(request).upload_reference(project_id, file)


@router.delete("/projects/{project_id}/references/{name}")
def delete_reference(project_id: str, name: str, request: Request):
    require_write_access(request)
    return project_service(request).delete_reference(project_id, name)


@router.patch("/projects/{project_id}")
def update_project(project_id: str, payload: ProjectUpdate, request: Request):
    require_write_access(request)
    if payload.rough_idea is None and payload.meta is None:
        raise HTTPException(status_code=400, detail="No fields to update")
    return project_service(request).update_project(
        project_id,
        rough_idea=payload.rough_idea,
        meta=payload.meta,
    )


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, request: Request):
    require_write_access(request)
    return project_service(request).delete_project(project_id)


@router.get("/projects/{project_id}")
def get_project(project_id: str, request: Request):
    project_dir = base_dir(request) / "projects" / project_id
    if not project_dir.exists() or not project_dir.is_dir():
        raise HTTPException(status_code=404, detail="Project not found")
    store = Store(base_dir(request), project_id)
    return {
        "project_id": project_id,
        "project": store.load_artifact(),
    }
