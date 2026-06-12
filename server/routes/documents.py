from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from server.services.security import sanitize_filename
from .auth import require_write_access


router = APIRouter()

ALLOWED_DOC_EXTS = {
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",
    ".txt",
    ".md",
    ".json",
    ".csv",
}
DOC_EXTS_LABEL = ", ".join(sorted(ALLOWED_DOC_EXTS))
MAX_DOC_BYTES = 20 * 1024 * 1024


def doc_dir(request: Request) -> Path:
    path = request.app.state.base_dir / "doc"
    path.mkdir(parents=True, exist_ok=True)
    return path


@router.get("/documents")
def list_documents(request: Request):
    rows = []
    for path in sorted(doc_dir(request).iterdir()):
        if path.is_file() and path.name != ".DS_Store":
            rows.append({"name": path.name, "size": path.stat().st_size})
    return {"documents": rows}


@router.post("/documents")
async def upload_document(request: Request, file: UploadFile = File(...)):
    require_write_access(request)
    name = sanitize_filename(file.filename or "")
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_DOC_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported document type. Allowed: {DOC_EXTS_LABEL}",
        )
    data = await file.read()
    if len(data) > MAX_DOC_BYTES:
        raise HTTPException(status_code=400, detail="File is too large")
    target = doc_dir(request) / name
    target.write_bytes(data)
    return {"saved": True, "name": name, "size": len(data)}


@router.delete("/documents/{name}")
def delete_document(name: str, request: Request):
    require_write_access(request)
    safe = sanitize_filename(name)
    target = doc_dir(request) / safe
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Document not found")
    target.unlink()
    return {"deleted": True, "name": safe}
