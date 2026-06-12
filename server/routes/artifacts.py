from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from server.services.artifact_service import ArtifactService
from server.services.security import resolve_project_file, resolve_under
from .auth import require_write_access


router = APIRouter()


class FileUpdate(BaseModel):
    content: str


def service(request: Request) -> ArtifactService:
    return ArtifactService(request.app.state.base_dir, run_manager=request.app.state.run_manager)


@router.get("/projects/{project_id}/artifacts")
def artifact_tree(project_id: str, request: Request):
    return {"items": service(request).tree(project_id)}


@router.get("/projects/{project_id}/files")
def read_file(project_id: str, path: str, request: Request):
    return service(request).read_file(project_id, path)


@router.put("/projects/{project_id}/files")
def write_file(project_id: str, path: str, payload: FileUpdate, request: Request):
    require_write_access(request)
    return service(request).write_file(project_id, path, payload.content)


@router.get("/projects/{project_id}/results/{file_path:path}")
def serve_results_file(project_id: str, file_path: str, request: Request):
    svc = service(request)
    root = svc.project_dir(project_id)
    results_root = root / "results"
    if not results_root.exists():
        raise HTTPException(status_code=404, detail="Results not found")
    target = resolve_under(request.app.state.base_dir, results_root, file_path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target)


@router.get("/projects/{project_id}/manual/{file_path:path}")
def serve_manual_file(project_id: str, file_path: str, request: Request):
    svc = service(request)
    root = svc.project_dir(project_id)
    manual_root = root / "manual"
    if not manual_root.exists():
        raise HTTPException(status_code=404, detail="Manual not found")
    target = resolve_under(request.app.state.base_dir, manual_root, file_path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target)


@router.get("/manual/{file_path:path}")
def serve_shared_manual_file(file_path: str, request: Request):
    manual_root = request.app.state.base_dir / "manual"
    if not manual_root.exists():
        raise HTTPException(status_code=404, detail="Manual assets not found")
    target = resolve_under(request.app.state.base_dir, manual_root, file_path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target)


@router.get("/projects/{project_id}/{file_path:path}")
def serve_project_static_file(project_id: str, file_path: str, request: Request):
    svc = service(request)
    root = svc.project_dir(project_id)
    target = resolve_project_file(request.app.state.base_dir, root, file_path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target)
