from __future__ import annotations

import io
import base64
import binascii
import hashlib
import json
import posixpath
import re
import zipfile

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from server.services.artifact_service import ArtifactService
from server.services.security import resolve_project_file, resolve_under
from .auth import require_project_read_access


router = APIRouter()
public_router = APIRouter()

NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}

def trusted_inline_script_sources() -> str:
    from storage.markdown import floating_toc_script
    from utils.topology import render_trace_topology_assets

    sources = []
    for html in (floating_toc_script(), render_trace_topology_assets()):
        for script in re.findall(r"<script(?:\s[^>]*)?>([\s\S]*?)</script>", html):
            digest = hashlib.sha256(script.encode("utf-8")).digest()
            sources.append("'sha256-" + base64.b64encode(digest).decode("ascii") + "'")
    return " ".join(dict.fromkeys(sources))


TRUSTED_INLINE_SCRIPT_SOURCES = trusted_inline_script_sources()


UNTRUSTED_HTML_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self' data:; "
        f"script-src {TRUSTED_INLINE_SCRIPT_SOURCES}; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "form-action 'none'; "
        "frame-ancestors 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}

OFFLINE_TEXT_SUFFIXES = {".json", ".txt", ".md", ".plantuml"}


def service(request: Request) -> ArtifactService:
    return ArtifactService(request.app.state.base_dir)


def dynamic_file_response(path, *, untrusted_html: bool = False) -> FileResponse:
    headers = dict(NO_CACHE_HEADERS)
    if untrusted_html and path.suffix.lower() in {".html", ".htm"}:
        headers.update(UNTRUSTED_HTML_HEADERS)
    return FileResponse(path, headers=headers)


def zip_download_response(data: bytes, filename: str = "manual.zip") -> Response:
    return Response(
        data,
        media_type="application/zip",
        headers={
            **NO_CACHE_HEADERS,
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(data)),
            "X-Content-Type-Options": "nosniff",
        },
    )


def manual_archive_name(arcname: str) -> str:
    prefix = "manual/"
    return arcname[len(prefix):] if arcname.startswith(prefix) else arcname


def offline_manual_href(project_id: str, href: str) -> str:
    prefix = f"/{project_id}/manual/"
    if href == f"/{project_id}/manual/srs":
        return "projects/results/srs.html"
    if href == f"/{project_id}/manual/dr":
        return "projects/results/design_rationale.html"
    model_prefix = f"/{project_id}/manual/models/"
    if href.startswith(model_prefix):
        return f"models/{href[len(model_prefix):]}"
    if href.startswith(prefix):
        relative = href[len(prefix):]
        if relative.startswith(("artifact/", "results/", "output/")):
            return f"projects/{relative}"
        return relative
    return href


def offline_manual_html(html: str, project_id: str, files: dict[str, str] | None = None) -> str:
    html = html.replace(f'<base href="/{project_id}/manual/" />\n', "")
    html = html.replace('href="../../../manual/styles.css"', 'href="styles.css"')
    html = html.replace('src="../../../manual/main.js"', 'src="main.js"')
    html = html.replace(f'/{project_id}/manual/srs', "projects/results/srs.html")
    html = html.replace(f'/{project_id}/manual/dr', "projects/results/design_rationale.html")
    html = html.replace(f'/{project_id}/manual/models/', "models/")
    html = html.replace(f'/{project_id}/manual/artifact/', "projects/artifact/")
    html = html.replace(f'/{project_id}/manual/results/', "projects/results/")
    html = html.replace(f'/{project_id}/manual/output/', "projects/output/")
    html = html.replace(f'/{project_id}/manual/', "")
    if files:
        payload = json.dumps(files, ensure_ascii=False).replace("</script", "<\\/script")
        script = f"<script>window.PLANT_MANUAL_FILES = {payload};</script>\n"
        main_script = '<script src="main.js"></script>'
        if main_script in html:
            html = html.replace(main_script, f"{script}{main_script}", 1)
        elif "</body>" in html:
            html = html.replace("</body>", f"{script}</body>", 1)
        else:
            html += script
    return html


def offline_project_html(
    html: str,
    project_id: str,
    model_prefix: str = "models/",
) -> str:
    route_prefix = rf"(?:https?://[^\"'<>]+)?/{re.escape(project_id)}/manual"

    def rewrite(source: str) -> str:
        source = re.sub(rf"{route_prefix}/srs(?=#[^\"'<>]*|[\"'<>])", "srs.html", source)
        source = re.sub(rf"{route_prefix}/dr(?=#[^\"'<>]*|[\"'<>])", "design_rationale.html", source)
        source = re.sub(
            r"(?<![A-Za-z0-9_/\\])(?:\.\.[\\/]|\.[\\/])?(?:artifact[\\/]|results[\\/]|output[\\/])?models[\\/]",
            model_prefix,
            source,
        )
        source = re.sub(rf"{route_prefix}/models/", model_prefix, source)
        return re.sub(
            r"(\.(?:png|jpe?g|gif|webp|svg))\?v=\d+(?=[\"'<>\s)]|$)",
            r"\1",
            source,
            flags=re.IGNORECASE,
        )

    html = rewrite(html)

    def rewrite_trace_content(match: re.Match) -> str:
        encoded = match.group(1)
        try:
            decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError):
            return match.group(0)
        rewritten = rewrite(decoded)
        if rewritten == decoded:
            return match.group(0)
        replacement = base64.b64encode(rewritten.encode("utf-8")).decode("ascii")
        return f'data-trace-content-b64="{replacement}"'

    return re.sub(r'data-trace-content-b64="([^"]*)"', rewrite_trace_content, html)


def offline_manual_manifest(text: str, project_id: str) -> str:
    manifest = json.loads(text)

    def rewrite_item(item):
        if not isinstance(item, dict):
            return
        href = item.get("href")
        if isinstance(href, str):
            item["href"] = offline_manual_href(project_id, href)

    for value in manifest.values():
        if isinstance(value, list):
            for item in value:
                rewrite_item(item)
    return json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"


def maybe_read_offline_text(path, arcname: str) -> tuple[str, str] | None:
    if not str(arcname).startswith("manual/"):
        return None
    if path.suffix.lower() not in OFFLINE_TEXT_SUFFIXES:
        return None
    try:
        return arcname[len("manual/"):], path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def refresh_project_manual_manifest(project_dir) -> None:
    from scripts.build_file import write_manifest
    from storage.coordinator import FileRunCoordinator
    from storage.export import rewrite_manual_manifest_hrefs

    manual_dir = project_dir / "manual"
    coordinator = FileRunCoordinator(project_dir.parents[1])
    with coordinator.exclusive_lock(f"manual-manifest-{project_dir.name}"):
        manifest_path = write_manifest(
            project_dir=project_dir,
            output_file=manual_dir / "file.json",
        )
        rewrite_manual_manifest_hrefs(manifest_path, project_dir.name)


def project_manual_response(project_id: str, file_path: str, request: Request) -> FileResponse:
    require_project_read_access(request, project_id)
    svc = service(request)
    root = svc.project_dir(project_id)
    manual_root = root / "manual"
    if not manual_root.exists():
        raise HTTPException(status_code=404, detail="Manual not found")
    if str(file_path).replace("\\", "/").strip("/") == "file.json":
        refresh_project_manual_manifest(root)
    target = resolve_under(request.app.state.base_dir, manual_root, file_path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return dynamic_file_response(target)


def project_manual_zip_response(project_id: str, request: Request) -> Response:
    require_project_read_access(request, project_id)
    svc = service(request)
    root = svc.project_dir(project_id)
    manual_root = root / "manual"
    if not manual_root.exists() or not manual_root.is_dir():
        raise HTTPException(status_code=404, detail="Manual not found")
    refresh_project_manual_manifest(root)

    shared_manual_root = request.app.state.base_dir / "manual"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        written = set()
        offline_files: dict[str, str] = {}

        def write_file(path, arcname: str) -> None:
            archive_name = manual_archive_name(arcname)
            if archive_name in written:
                return
            archive.write(path, archive_name)
            written.add(archive_name)
            text_item = maybe_read_offline_text(path, arcname)
            if text_item:
                key, text = text_item
                offline_files.setdefault(key, text)

        def write_text(arcname: str, text: str) -> None:
            archive_name = manual_archive_name(arcname)
            if archive_name in written:
                return
            archive.writestr(archive_name, text)
            written.add(archive_name)
            if arcname.startswith("manual/"):
                offline_files.setdefault(arcname[len("manual/"):], text)

        def write_project_file(path, arcname: str) -> None:
            if arcname in written:
                return
            if path.suffix.lower() == ".html":
                source = path.read_text(encoding="utf-8")
                html_parent = posixpath.dirname(arcname)
                if arcname in {
                    "manual/projects/results/design_rationale.html",
                    "manual/projects/results/srs.html",
                }:
                    model_prefix = "./models/"
                else:
                    model_prefix = posixpath.relpath("manual/models", html_parent) + "/"
                source = offline_project_html(source, project_id, model_prefix=model_prefix)
                write_text(arcname, source)
            else:
                write_file(path, arcname)

        manual_paths = [
            path for path in sorted(manual_root.rglob("*"))
            if path.is_file() and path.name != ".DS_Store"
        ]
        project_paths = []
        for folder in ("artifact", "results", "output"):
            project_root = root / folder
            if not project_root.exists():
                continue
            project_paths.extend(
                (folder, path, f"manual/projects/{folder}/{path.relative_to(project_root).as_posix()}")
                for path in sorted(project_root.rglob("*"))
                if path.is_file() and path.name != ".DS_Store"
            )
        shared_paths = [
            path for path in sorted(shared_manual_root.rglob("*"))
            if path.is_file() and path.name != ".DS_Store"
        ] if shared_manual_root.exists() else []

        for path in manual_paths:
            if not path.is_file() or path.name == ".DS_Store":
                continue
            arcname = f"manual/{path.relative_to(manual_root).as_posix()}"
            if path.name == "file.json":
                write_text(arcname, offline_manual_manifest(path.read_text(encoding="utf-8"), project_id))
            elif path.name != "index.html":
                write_file(path, arcname)

        for _, path, arcname in project_paths:
            write_project_file(path, arcname)
            for model_prefix in (
                "manual/projects/artifact/models/",
                "manual/projects/results/models/",
                "manual/projects/output/models/",
            ):
                if arcname.startswith(model_prefix):
                    model_name = arcname[len(model_prefix):]
                    write_file(path, f"manual/models/{model_name}")
                    write_file(path, f"manual/projects/results/models/{model_name}")
                    break

        for path in shared_paths:
            arcname = f"manual/{path.relative_to(shared_manual_root).as_posix()}"
            if arcname in {"manual/index.html", "manual/file.json"}:
                continue
            if manual_archive_name(arcname) in written:
                continue
            write_file(path, arcname)

        for path in manual_paths:
            if path.name == "index.html":
                arcname = f"manual/{path.relative_to(manual_root).as_posix()}"
                write_text(arcname, offline_manual_html(path.read_text(encoding="utf-8"), project_id, offline_files))
                break

    return zip_download_response(buffer.getvalue())


def shared_manual_zip_response(request: Request) -> Response:
    shared_manual_root = request.app.state.base_dir / "manual"
    if not shared_manual_root.exists() or not shared_manual_root.is_dir():
        raise HTTPException(status_code=404, detail="Manual assets not found")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(shared_manual_root.rglob("*")):
            if not path.is_file() or path.name == ".DS_Store":
                continue
            archive.write(path, path.relative_to(shared_manual_root).as_posix())

    return zip_download_response(buffer.getvalue())


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
    return dynamic_file_response(target, untrusted_html=True)


def project_result_response(project_id: str, file_name: str, request: Request) -> FileResponse:
    return project_static_response(project_id, f"results/{file_name}", request)


@router.get("/projects/{project_id}/artifacts")
def artifact_tree(project_id: str, request: Request):
    require_project_read_access(request, project_id)
    return {"items": service(request).tree(project_id)}


@router.get("/projects/{project_id}/manual.zip")
def download_project_manual_zip(project_id: str, request: Request):
    return project_manual_zip_response(project_id, request)


@router.get("/manual.zip")
def download_shared_manual_zip(request: Request):
    return shared_manual_zip_response(request)


@router.get("/projects/{project_id}/files")
def read_file(project_id: str, path: str, request: Request):
    require_project_read_access(request, project_id)
    return service(request).read_file(project_id, path)


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
    require_project_read_access(request, project_id)
    root = service(request).project_dir(project_id)
    for folder in ("results", "output", "artifact"):
        target = resolve_project_file(
            request.app.state.base_dir,
            root,
            f"{folder}/models/{file_path}",
        )
        if target.exists() and target.is_file():
            return dynamic_file_response(target)
    raise HTTPException(status_code=404, detail="Model file not found")


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
