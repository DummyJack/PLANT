from __future__ import annotations

import shutil
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from storage import Store
from storage.atomic import atomic_write_text


CHECKPOINT_META_KEY = "run_checkpoint"


def checkpoint_path(store: Store) -> Path:
    return store.project_dir / "runs" / "run_checkpoint.json"


def _normalize_checkpoint(checkpoint: Dict[str, Any]) -> Dict[str, Any]:
    stage_id = str(checkpoint.get("stage_id") or "").strip()
    step_id = str(checkpoint.get("step_id") or "").strip() or stage_id
    dirty_outputs = checkpoint.get("dirty_outputs")
    checkpoint = {
        "version": 1,
        "status": checkpoint.get("status", ""),
        "stage_id": stage_id,
        "step_id": step_id,
        "run_id": checkpoint.get("run_id", ""),
        "error": checkpoint.get("error", ""),
        "resume_policy": checkpoint.get("resume_policy", "rerun_step"),
        "dirty_outputs": list(dirty_outputs if isinstance(dirty_outputs, list) else []),
        "last_round": checkpoint.get("last_round", 0),
        "round": checkpoint.get("round", checkpoint.get("last_round", 0)),
        "issue_id": checkpoint.get("issue_id", ""),
        "agent": checkpoint.get("agent", ""),
        "action": checkpoint.get("action", ""),
        "created_at": checkpoint.get("created_at") or datetime.now().isoformat(),
    }
    completed = checkpoint.get("completed_steps")
    if isinstance(completed, list):
        checkpoint["completed_steps"] = completed
    return checkpoint


def _load_checkpoint(store: Store, artifact: Dict[str, Any]) -> Dict[str, Any] | None:
    meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
    checkpoint = meta.get(CHECKPOINT_META_KEY) if isinstance(meta.get(CHECKPOINT_META_KEY), dict) else None
    if checkpoint:
        return _normalize_checkpoint(checkpoint)
    checkpoint_file = checkpoint_path(store)
    if checkpoint_file.exists():
        try:
            data = json.loads(checkpoint_file.read_text(encoding="utf-8"))
        except Exception:
            data = None
        if isinstance(data, dict):
            return _normalize_checkpoint(data)
    return None


def load_run_checkpoint(store: Store) -> Dict[str, Any] | None:
    artifact = store.load_artifact() or {}
    return _load_checkpoint(store, artifact)


def clear_run_checkpoint(store: Store, artifact: Dict[str, Any] | None = None) -> None:
    current_artifact = artifact if isinstance(artifact, dict) else (store.load_artifact() or {})
    meta = current_artifact.get("meta") if isinstance(current_artifact.get("meta"), dict) else {}
    if CHECKPOINT_META_KEY in meta:
        meta.pop(CHECKPOINT_META_KEY, None)
        current_artifact["meta"] = meta
        store.save_artifact(current_artifact)
    try:
        checkpoint_path(store).unlink()
    except FileNotFoundError:
        pass


def _save_checkpoint(store: Store, checkpoint: Dict[str, Any]) -> None:
    path = checkpoint_path(store)
    checkpoint = _normalize_checkpoint(checkpoint)
    atomic_write_text(
        path,
        json.dumps(checkpoint, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _project_relative(store: Store, path: Path) -> str:
    try:
        return path.relative_to(store.project_dir).as_posix()
    except ValueError:
        return path.as_posix()


def _safe_unlink(store: Store, path: Path) -> bool:
    try:
        resolved = path.resolve()
        resolved.relative_to(store.project_dir.resolve())
    except Exception:
        return False
    if not resolved.exists():
        return False
    if resolved.is_file():
        resolved.unlink()
        return True
    return False


def _safe_rmtree(store: Store, path: Path) -> bool:
    try:
        resolved = path.resolve()
        resolved.relative_to(store.project_dir.resolve())
    except Exception:
        return False
    if not resolved.exists() or not resolved.is_dir():
        return False
    shutil.rmtree(resolved)
    return True


def _latest_mom_paths(store: Store) -> List[Path]:
    mom_dir = store.artifact_dir / "MoM"
    if not mom_dir.exists():
        return []
    rows = sorted(
        [path for path in mom_dir.glob("R*-M*.md") if path.is_file()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not rows:
        return []
    latest = rows[0]
    result = [latest]
    result_html = store.project_dir / "results" / "MoM" / latest.with_suffix(".html").name
    result.append(result_html)
    return result


def stage_dirty_outputs(store: Store, stage_id: str) -> List[Path]:
    stage = str(stage_id or "").strip()
    if stage in {"formal_meeting", "meeting_issue_proposal_review"}:
        return _latest_mom_paths(store)
    if stage in {"draft"}:
        latest = store.get_draft_version()
        if latest < 0:
            return []
        return [
            store.artifact_dir / "drafts" / f"draft_v{latest}.md",
            store.project_dir / "results" / "drafts" / f"draft_v{latest}.html",
        ]
    if stage in {"document_generation"}:
        return [
            store.output_dir / "srs.md",
            store.output_dir / "design_rationale.md",
            store.project_dir / "results" / "srs.html",
            store.project_dir / "results" / "design_rationale.html",
        ]
    if stage in {"research_domain"}:
        latest = store.get_draft_version()
        paths = [
            store.artifact_dir / "feedback.json",
            store.artifact_dir / "system_models.json",
            store.artifact_dir / "models",
        ]
        if latest >= 0:
            paths.extend([
                store.artifact_dir / "drafts" / f"draft_v{latest}.md",
                store.project_dir / "results" / "drafts" / f"draft_v{latest}.html",
            ])
        return paths
    if stage in {"system_model"}:
        return [
            store.artifact_dir / "system_models.json",
            store.artifact_dir / "models",
        ]
    if stage in {"export"}:
        return [store.project_dir / "results"]
    return []


def record_run_checkpoint(
    store: Store,
    *,
    run_id: str,
    status: str,
    stage_id: str,
    step_id: str = "",
    round_num: int | None = None,
    issue_id: str = "",
    agent: str = "",
    action: str = "",
    error: str = "",
) -> Dict[str, Any]:
    artifact = store.load_artifact() or {}
    meta = artifact.setdefault("meta", {})
    try:
        last_round = int(meta.get("last_round") or artifact.get("last_round") or 0)
    except (TypeError, ValueError):
        last_round = 0
    paths = stage_dirty_outputs(store, stage_id)
    step_id = str(step_id or stage_id or "").strip()
    resolved_round = round_num if round_num is not None else last_round
    checkpoint = {
        "status": status,
        "stage_id": stage_id,
        "step_id": step_id,
        "run_id": run_id,
        "error": error,
        "resume_policy": "rerun_step",
        "dirty_outputs": [_project_relative(store, path) for path in paths],
        "last_round": last_round,
        "round": resolved_round,
        "issue_id": issue_id,
        "agent": agent,
        "action": action,
        "created_at": datetime.now().isoformat(),
    }
    checkpoint = _normalize_checkpoint(checkpoint)
    _save_checkpoint(store, checkpoint)
    meta[CHECKPOINT_META_KEY] = checkpoint
    artifact["meta"] = meta
    store.save_artifact(artifact)
    return checkpoint


def mark_run_checkpoint(
    store: Store,
    *,
    run_id: str,
    status: str,
    stage_id: str,
    error: str = "",
) -> Dict[str, Any]:
    artifact = store.load_artifact() or {}
    checkpoint = _load_checkpoint(store, artifact)
    if checkpoint:
        checkpoint["status"] = status
        checkpoint["run_id"] = run_id
        if error:
            checkpoint["error"] = error
        checkpoint = _normalize_checkpoint(checkpoint)
        _save_checkpoint(store, checkpoint)
        meta = artifact.setdefault("meta", {})
        meta[CHECKPOINT_META_KEY] = checkpoint
        artifact["meta"] = meta
        store.save_artifact(artifact)
        return checkpoint
    return record_run_checkpoint(
        store,
        run_id=run_id,
        status=status,
        stage_id=stage_id,
        error=error,
    )


def clear_run_checkpoint_for_continue(store: Store, artifact: Dict[str, Any]) -> Dict[str, Any]:
    meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
    checkpoint = _load_checkpoint(store, artifact)
    if not checkpoint:
        return artifact
    stage_id = str(checkpoint.get("stage_id") or "").strip()
    cleaned: List[str] = []
    for path in stage_dirty_outputs(store, stage_id):
        removed = _safe_rmtree(store, path) if path.is_dir() else _safe_unlink(store, path)
        if removed:
            cleaned.append(_project_relative(store, path))
    meta["last_checkpoint_cleanup"] = {
        "stage_id": stage_id,
        "step_id": checkpoint.get("step_id", ""),
        "run_id": checkpoint.get("run_id", ""),
        "cleaned_outputs": cleaned,
        "cleaned_at": datetime.now().isoformat(),
    }
    meta["last_resume_checkpoint"] = dict(checkpoint)
    meta.pop(CHECKPOINT_META_KEY, None)
    try:
        checkpoint_path(store).unlink()
    except FileNotFoundError:
        pass
    if stage_id in {"formal_meeting", "meeting_issue_proposal_review"}:
        try:
            last_round = int(checkpoint.get("last_round") or meta.get("last_round") or 0)
        except (TypeError, ValueError):
            last_round = 0
        meta["last_round"] = max(0, last_round - 1)
    if stage_id == "research_domain":
        artifact.pop("feedback", None)
        artifact.pop("domain_research_review", None)
        artifact.pop("system_models", None)
        meta.pop("research_domain_completed", None)
        meta.pop("research_domain_coverage", None)
        meta.pop("domain_research_user_guidance", None)
        meta.pop("domain_research_referenced_files", None)
        meta.pop("draft_version", None)
        meta.pop("draft_without_meeting", None)
    if stage_id == "system_model":
        artifact.pop("system_models", None)
    artifact["meta"] = meta
    store.save_artifact(artifact)
    return artifact
