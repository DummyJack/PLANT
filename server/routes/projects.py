from pathlib import Path
import shutil
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from storage import Store
from utils import format_loaded_models_summary
from utils.language import sync_output_language

from server.services.project_service import ProjectService
from storage.coordinator import FileRunCoordinator
from server.services.run_config import general_formal_meeting_enabled
from .auth import can_read_project, is_activated, require_project_read_access, require_write_access


router = APIRouter()
public_router = APIRouter()


class ProjectCreate(BaseModel):
    rough_idea: str
    creation_id: Optional[str] = None


def base_dir(request: Request) -> Path:
    return request.app.state.base_dir


def project_service(request: Request) -> ProjectService:
    return ProjectService(base_dir(request), run_manager=request.app.state.run_manager)


@router.get("/bootstrap")
def bootstrap(request: Request):
    service = project_service(request)
    run_manager = request.app.state.run_manager
    activated = is_activated(request)
    store = Store(base_dir(request))
    config_status: Dict[str, Any] = {"loaded": False, "error": None}
    model_summary = ""
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
        "activated": activated,
        "projects": readable_projects(request, service.list_projects_enriched()),
        "active_runs": service.active_runs_map() if activated else {},
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


def readable_projects(request: Request, rows: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    if is_activated(request):
        return rows
    return [
        row
        for row in rows
        if can_read_project(request, str(row.get("project_id") or ""))
    ]


@router.post("/projects")
def create_project(payload: ProjectCreate, request: Request):
    require_write_access(request)
    rough_idea = payload.rough_idea.strip()
    if not rough_idea:
        raise HTTPException(status_code=400, detail="rough_idea is required")
    creation_id = str(payload.creation_id or "").strip()
    if creation_id and not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", creation_id):
        raise HTTPException(status_code=400, detail="creation_id is invalid")
    coordinator = FileRunCoordinator(base_dir(request))
    lock_name = f"project-create-{creation_id}" if creation_id else "project-create"
    with coordinator.exclusive_lock(lock_name):
        existing = coordinator.project_creation(creation_id) if creation_id else None
        if existing:
            existing_project_id = str(existing.get("project_id") or "")
            if (base_dir(request) / "projects" / existing_project_id).is_dir():
                return {"project_id": existing_project_id, "rough_idea": existing.get("rough_idea") or rough_idea}
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
            if creation_id:
                coordinator.record_project_creation(creation_id, project_id, rough_idea)
        except Exception:
            shutil.rmtree(project_root, ignore_errors=True)
            raise
    return {"project_id": project_id, "rough_idea": rough_idea}


@router.get("/projects/{project_id}/cost-summary")
def get_cost_summary(project_id: str, request: Request):
    require_project_read_access(request, project_id)
    return project_service(request).get_cost_summary(project_id)


@router.get("/projects/{project_id}/references")
def list_references(project_id: str, request: Request):
    require_project_read_access(request, project_id)
    return project_service(request).list_references(project_id)


@router.get("/projects/{project_id}/references/{name}")
def download_reference(project_id: str, name: str, request: Request, inline: bool = False):
    return reference_response(project_id, name, request, inline=inline)


@public_router.get("/{project_id}/references/{name}")
def public_download_reference(project_id: str, name: str, request: Request, inline: bool = False):
    return reference_response(project_id, name, request, inline=inline)


def reference_response(project_id: str, name: str, request: Request, *, inline: bool = False):
    require_project_read_access(request, project_id)
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
    active_statuses = {"queued", "running", "waiting_for_human", "cancelling"}
    active_run = next(
        (
            run
            for run in request.app.state.run_manager.list_runs(project_id=project_id)
            if run.get("status") in active_statuses
        ),
        None,
    )
    waiting_for_human = active_run is not None and active_run.get("status") == "waiting_for_human"
    return await project_service(request).upload_reference(
        project_id,
        file,
        allow_during_active_run=active_run is not None,
        pending=active_run is not None and not waiting_for_human,
    )


@router.delete("/projects/{project_id}/references/{name}")
def delete_reference(project_id: str, name: str, request: Request):
    require_write_access(request)
    return project_service(request).delete_reference(project_id, name)


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, request: Request):
    require_write_access(request)
    return project_service(request).delete_project(project_id)


@router.get("/projects/{project_id}")
def get_project(project_id: str, request: Request):
    require_project_read_access(request, project_id)
    store = project_service(request).ensure_project(project_id)
    return {
        "project_id": project_id,
        "project": store.load_artifact(),
    }
