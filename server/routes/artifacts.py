import io
import zipfile

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from server.services.artifact_service import ArtifactService
from server.services.security import resolve_project_file, resolve_under
from .auth import require_project_read_access, require_write_access


router = APIRouter()
public_router = APIRouter()

NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


class FileUpdate(BaseModel):
    content: str


def service(request: Request) -> ArtifactService:
    return ArtifactService(request.app.state.base_dir, run_manager=request.app.state.run_manager)


def dynamic_file_response(path) -> FileResponse:
    return FileResponse(path, headers=NO_CACHE_HEADERS)


def project_manual_response(project_id: str, file_path: str, request: Request) -> FileResponse:
    require_project_read_access(request, project_id)
    svc = service(request)
    root = svc.project_dir(project_id)
    manual_root = root / "manual"
    if not manual_root.exists():
        raise HTTPException(status_code=404, detail="Manual not found")
    target = resolve_under(request.app.state.base_dir, manual_root, file_path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return dynamic_file_response(target)


def project_manual_zip_response(project_id: str, request: Request) -> StreamingResponse:
    require_project_read_access(request, project_id)
    svc = service(request)
    root = svc.project_dir(project_id)
    manual_root = root / "manual"
    if not manual_root.exists() or not manual_root.is_dir():
        raise HTTPException(status_code=404, detail="Manual not found")

    shared_manual_root = request.app.state.base_dir / "manual"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(manual_root.rglob("*")):
            if not path.is_file() or path.name == ".DS_Store":
                continue
            arcname = f"manual/{path.relative_to(manual_root).as_posix()}"
            if path.name == "index.html":
                html = path.read_text(encoding="utf-8")
                html = html.replace('href="../../../manual/styles.css"', 'href="styles.css"')
                html = html.replace('src="../../../manual/main.js"', 'src="main.js"')
                archive.writestr(arcname, html)
            else:
                archive.write(path, arcname)

        if shared_manual_root.exists():
            for path in sorted(shared_manual_root.rglob("*")):
                if not path.is_file() or path.name == ".DS_Store":
                    continue
                arcname = f"manual/{path.relative_to(shared_manual_root).as_posix()}"
                if arcname not in archive.namelist():
                    archive.write(path, arcname)

    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={
            **NO_CACHE_HEADERS,
            "Content-Disposition": 'attachment; filename="manual.zip"',
        },
    )


def shared_manual_zip_response(request: Request) -> StreamingResponse:
    shared_manual_root = request.app.state.base_dir / "manual"
    if not shared_manual_root.exists() or not shared_manual_root.is_dir():
        raise HTTPException(status_code=404, detail="Manual assets not found")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(shared_manual_root.rglob("*")):
            if not path.is_file() or path.name == ".DS_Store":
                continue
            archive.write(path, f"manual/{path.relative_to(shared_manual_root).as_posix()}")

    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={
            **NO_CACHE_HEADERS,
            "Content-Disposition": 'attachment; filename="manual.zip"',
        },
    )


def shared_manual_response(file_path: str, request: Request) -> FileResponse:
    manual_root = request.app.state.base_dir / "manual"
    if not manual_root.exists():
        raise HTTPException(status_code=404, detail="Manual assets not found")
    target = resolve_under(request.app.state.base_dir, manual_root, file_path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return dynamic_file_response(target)


def project_static_response(project_id: str, file_path: str, request: Request) -> FileResponse:
    require_project_read_access(request, project_id)
    svc = service(request)
    root = svc.project_dir(project_id)
    target = resolve_project_file(request.app.state.base_dir, root, file_path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return dynamic_file_response(target)


def project_result_response(project_id: str, file_name: str, request: Request) -> FileResponse:
    return project_static_response(project_id, f"results/{file_name}", request)


@router.get("/projects/{project_id}/artifacts")
def artifact_tree(project_id: str, request: Request):
    require_project_read_access(request, project_id)
    return {"items": service(request).tree(project_id)}


@router.get("/projects/{project_id}/files")
def read_file(project_id: str, path: str, request: Request):
    require_project_read_access(request, project_id)
    return service(request).read_file(project_id, path)


@router.put("/projects/{project_id}/files")
def write_file(project_id: str, path: str, payload: FileUpdate, request: Request):
    require_write_access(request)
    return service(request).write_file(project_id, path, payload.content)


@router.get("/projects/{project_id}/results/{file_path:path}")
def serve_results_file(project_id: str, file_path: str, request: Request):
    require_project_read_access(request, project_id)
    svc = service(request)
    root = svc.project_dir(project_id)
    results_root = root / "results"
    if not results_root.exists():
        raise HTTPException(status_code=404, detail="Results not found")
    target = resolve_under(request.app.state.base_dir, results_root, file_path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return dynamic_file_response(target)


@router.get("/projects/{project_id}/manual/{file_path:path}")
def serve_manual_file(project_id: str, file_path: str, request: Request):
    return project_manual_response(project_id, file_path, request)


@router.get("/projects/{project_id}/manual.zip")
def download_manual_zip(project_id: str, request: Request):
    return project_manual_zip_response(project_id, request)


@router.get("/manual/{file_path:path}")
def serve_shared_manual_file(file_path: str, request: Request):
    return shared_manual_response(file_path, request)


@router.get("/manual.zip")
def download_shared_manual_zip(request: Request):
    return shared_manual_zip_response(request)


@router.get("/projects/{project_id}/{file_path:path}")
def serve_project_static_file(project_id: str, file_path: str, request: Request):
    return project_static_response(project_id, file_path, request)


@public_router.get("/{project_id}/manual")
@public_router.get("/{project_id}/manual/")
def serve_public_manual_index(project_id: str, request: Request):
    return project_manual_response(project_id, "index.html", request)


@public_router.get("/{project_id}/manual.zip")
def serve_public_manual_zip(project_id: str, request: Request):
    return project_manual_zip_response(project_id, request)


@public_router.get("/manual.zip")
def serve_public_shared_manual_zip(request: Request):
    return shared_manual_zip_response(request)


@public_router.get("/{project_id}/manual/srs")
def serve_public_srs(project_id: str, request: Request):
    return project_result_response(project_id, "srs.html", request)


@public_router.get("/{project_id}/manual/dr")
def serve_public_design_rationale(project_id: str, request: Request):
    return project_result_response(project_id, "design_rationale.html", request)


@public_router.get("/{project_id}/manual/models/{file_path:path}")
def serve_public_manual_model_file(project_id: str, file_path: str, request: Request):
    return project_static_response(project_id, f"results/models/{file_path}", request)


@public_router.get("/{project_id}/manual/results/{file_path:path}")
def serve_public_manual_result_file(project_id: str, file_path: str, request: Request):
    return project_static_response(project_id, f"results/{file_path}", request)


@public_router.get("/{project_id}/manual/artifact/{file_path:path}")
def serve_public_manual_artifact_file(project_id: str, file_path: str, request: Request):
    return project_static_response(project_id, f"artifact/{file_path}", request)


@public_router.get("/{project_id}/manual/output/{file_path:path}")
def serve_public_manual_output_file(project_id: str, file_path: str, request: Request):
    return project_static_response(project_id, f"output/{file_path}", request)


@public_router.get("/{project_id}/manual/agent/{file_path:path}")
def serve_public_manual_agent_file(project_id: str, file_path: str, request: Request):
    return shared_manual_response(f"agent/{file_path}", request)


@public_router.get("/{project_id}/manual/{file_path:path}")
def serve_public_manual_file(project_id: str, file_path: str, request: Request):
    return project_manual_response(project_id, file_path, request)


@public_router.get("/manual/{file_path:path}")
def serve_public_shared_manual_file(file_path: str, request: Request):
    return shared_manual_response(file_path, request)


@public_router.get("/{project_id}/{file_path:path}")
def serve_public_project_static_file(project_id: str, file_path: str, request: Request):
    if file_path.lower().endswith(".html"):
        raise HTTPException(status_code=404, detail="File not found")
    return project_static_response(project_id, file_path, request)
