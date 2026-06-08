import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, UploadFile

from flow.main import run_export_html_stage, save_cost_summary
from flow.setup import Flow
from storage import Store
from utils import Logger, export_enabled
from utils.language import sync_output_language

from .security import sanitize_filename


ALLOWED_REFERENCE_EXTS = {".pdf", ".docx", ".txt", ".md", ".json", ".csv"}
REFERENCE_EXTS_LABEL = ", ".join(sorted(ALLOWED_REFERENCE_EXTS))
MAX_REFERENCE_BYTES = 20 * 1024 * 1024


class ProjectService:
    def __init__(self, base_dir: Path, run_manager=None):
        self.base_dir = base_dir
        self.run_manager = run_manager

    def store(self, project_id: str) -> Store:
        return Store(self.base_dir, project_id)

    def _latest_run_status(self, project_id: str) -> str:
        if not self.run_manager:
            return "idle"
        runs = self.run_manager.list_runs(project_id=project_id)
        if not runs:
            return "idle"
        return str(runs[0].get("status") or "idle")

    def _project_hints(self, project_id: str) -> Dict[str, Any]:
        results_dir = self.base_dir / "projects" / project_id / "results"
        active_run = self.run_manager.get_active_run(project_id) if self.run_manager else None
        active_summary = None
        if active_run:
            active_summary = {
                "run_id": active_run.get("run_id"),
                "status": active_run.get("status"),
                "pending_decision": active_run.get("pending_decision"),
            }
        return {
            "has_results": results_dir.exists() and any(results_dir.rglob("*")),
            "status_hint": active_run.get("status") if active_run else self._latest_run_status(project_id),
            "active_run": active_summary,
        }

    def list_projects_enriched(self) -> List[Dict[str, Any]]:
        rows = Store(self.base_dir).list_projects()
        enriched = []
        for row in rows:
            project_id = str(row.get("project_id") or "")
            if not project_id:
                continue
            item = dict(row)
            item.update(self._project_hints(project_id))
            enriched.append(item)
        return enriched

    def active_runs_map(self) -> Dict[str, Dict[str, Any]]:
        if not self.run_manager:
            return {}
        mapping: Dict[str, Dict[str, Any]] = {}
        for run in self.run_manager.list_runs():
            if run.get("status") not in {"queued", "running", "waiting_for_human", "cancelling"}:
                continue
            project_id = str(run.get("project_id") or "")
            if not project_id:
                continue
            mapping[project_id] = {
                "run_id": run.get("run_id"),
                "status": run.get("status"),
                "pending_decision": run.get("pending_decision"),
            }
        return mapping

    def ensure_project(self, project_id: str) -> Store:
        store = self.store(project_id)
        if not store.project_dir.exists():
            raise HTTPException(status_code=404, detail="Project not found")
        return store

    def assert_no_active_run(self, project_id: str) -> None:
        if self.run_manager and self.run_manager.get_active_run(project_id):
            raise HTTPException(status_code=409, detail="Project has an active run")

    def references_dir(self, project_id: str) -> Path:
        path = self.base_dir / "doc" / project_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_summary(self, project_id: str) -> Dict[str, Any]:
        store = self.ensure_project(project_id)
        artifact = store.load_artifact() or {}
        results_dir = store.project_dir / "results"
        cost_path = store.project_dir / "cost_summary.json"
        active_run = self.run_manager.get_active_run(project_id) if self.run_manager else None
        return {
            "project_id": project_id,
            "rough_idea": str(artifact.get("rough_idea") or ""),
            "meta": artifact.get("meta", {}) if isinstance(artifact.get("meta"), dict) else {},
            "stakeholder_count": len(artifact.get("stakeholders", []) or []),
            "user_requirement_count": len(artifact.get("URL", []) or []),
            "system_requirement_count": len(artifact.get("REQ", []) or []),
            "system_model_count": len(artifact.get("system_models", []) or []),
            "discussion_count": len(artifact.get("discussions", []) or []),
            "has_results": results_dir.exists() and any(results_dir.rglob("*")),
            "has_cost_summary": cost_path.exists(),
            "active_run": active_run,
            "path": str(store.project_dir),
        }

    def update_project(
        self,
        project_id: str,
        *,
        rough_idea: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self.assert_no_active_run(project_id)
        store = self.ensure_project(project_id)
        artifact = store.load_artifact() or {}
        changed = False
        if rough_idea is not None:
            cleaned = rough_idea.strip()
            if not cleaned:
                raise HTTPException(status_code=400, detail="rough_idea cannot be empty")
            artifact["rough_idea"] = cleaned
            sync_output_language(cleaned, artifact)
            changed = True
        if meta is not None:
            if not isinstance(meta, dict):
                raise HTTPException(status_code=400, detail="meta must be an object")
            current_meta = artifact.get("meta")
            if not isinstance(current_meta, dict):
                current_meta = {}
            current_meta.update(meta)
            artifact["meta"] = current_meta
            changed = True
        if changed:
            store.save_artifact(artifact)
        return {"project_id": project_id, "updated": changed, "summary": self.get_summary(project_id)}

    def delete_project(self, project_id: str) -> Dict[str, Any]:
        self.assert_no_active_run(project_id)
        store = self.ensure_project(project_id)
        project_dir = store.project_dir
        references_dir = self.references_dir(project_id)
        shutil.rmtree(project_dir)
        if references_dir.exists():
            shutil.rmtree(references_dir)
        return {"project_id": project_id, "deleted": True}

    def export_from_flow(
        self,
        flow: Flow,
        *,
        html: bool = True,
        cost: bool = True,
    ) -> Dict[str, Any]:
        config = flow.config
        store = flow.store
        exported: Dict[str, Any] = {"html": False, "cost": False}

        if html and export_enabled(config, "html", True):
            run_export_html_stage(flow)
            exported["html"] = True
        if cost and export_enabled(config, "cost", True):
            save_cost_summary(flow)
            exported["cost"] = bool((store.project_dir / "cost_summary.json").exists())

        return {
            "project_id": store.project_id,
            "exported": exported,
            "results_dir": str(store.project_dir / "results"),
        }

    def export_project(
        self,
        project_id: str,
        *,
        html: bool = True,
        cost: bool = True,
    ) -> Dict[str, Any]:
        self.assert_no_active_run(project_id)
        store = self.ensure_project(project_id)
        config = Store(self.base_dir).load_config()
        logger = Logger(store.log_dir, write_file=False)
        flow = Flow(config, store, logger)
        result = self.export_from_flow(flow, html=html, cost=cost)
        result["project_id"] = project_id
        return result

    def describe_export_flags(self, config: Dict[str, Any]) -> Dict[str, bool]:
        return {
            "html": bool(export_enabled(config, "html", True)),
            "cost": bool(export_enabled(config, "cost", True)),
        }

    def get_cost_summary(self, project_id: str) -> Dict[str, Any]:
        store = self.ensure_project(project_id)
        cost_path = store.project_dir / "cost_summary.json"
        if not cost_path.exists():
            raise HTTPException(status_code=404, detail="Cost summary not found")
        return {
            "project_id": project_id,
            "cost_summary": json.loads(cost_path.read_text(encoding="utf-8")),
        }

    def list_references(self, project_id: str) -> Dict[str, Any]:
        self.ensure_project(project_id)
        rows = []
        ref_dir = self.references_dir(project_id)
        for path in sorted(ref_dir.iterdir()):
            if path.is_file() and path.name != ".DS_Store":
                rows.append({"name": path.name, "size": path.stat().st_size})
        return {"project_id": project_id, "references": rows}

    async def upload_reference(self, project_id: str, file: UploadFile) -> Dict[str, Any]:
        self.ensure_project(project_id)
        name = sanitize_filename(file.filename or "")
        suffix = Path(name).suffix.lower()
        if suffix not in ALLOWED_REFERENCE_EXTS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported reference file type. Allowed: {REFERENCE_EXTS_LABEL}",
            )
        data = await file.read()
        if len(data) > MAX_REFERENCE_BYTES:
            raise HTTPException(status_code=400, detail="File is too large")
        target = self.references_dir(project_id) / name
        target.write_bytes(data)
        return {"project_id": project_id, "saved": True, "name": name, "size": len(data)}

    def delete_reference(self, project_id: str, name: str) -> Dict[str, Any]:
        self.ensure_project(project_id)
        safe = sanitize_filename(name)
        target = self.references_dir(project_id) / safe
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="Reference not found")
        target.unlink()
        return {"project_id": project_id, "deleted": True, "name": safe}
