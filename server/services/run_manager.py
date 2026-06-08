import copy
import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from flow.setup import Flow
from model import validate_provider_api_keys
from storage import Store
from utils import export_enabled
from utils.cancel import clear_cancel_checker, register_cancel_checker
from utils.human import Collect
from utils.language import sync_output_language

from .event_logger import EventLogger
from .human_decisions import parse_human_decision_response, parse_stakeholder_response
from .run_config import (
    apply_run_enable_agents,
    apply_run_rounds,
    general_formal_meeting_enabled,
    normalize_attached_reference_paths,
)
from .run_persistence import ACTIVE_STATUSES, RunPersistence


class RunManager:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self._lock = threading.Lock()
        self._runs: Dict[str, Dict[str, Any]] = {}
        self._project_active: Dict[str, str] = {}
        self._persistence = RunPersistence(base_dir)

    def recover_on_startup(self) -> int:
        return self._persistence.recover_interrupted_runs()

    def count_interrupted_runs(self) -> int:
        return self._persistence.count_runs_by_status("interrupted")

    def list_runs(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            memory_runs = {
                run["run_id"]: self._public_state(run)
                for run in self._runs.values()
                if not project_id or run.get("project_id") == project_id
            }
        disk_runs = {
            run["run_id"]: run
            for run in self._persistence.list_runs(project_id)
            if run.get("run_id")
        }
        merged = dict(disk_runs)
        merged.update(memory_runs)
        rows = list(merged.values())
        rows.sort(key=lambda item: (item.get("started_at", ""), item.get("run_id", "")), reverse=True)
        return rows

    def get_active_run(self, project_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            active_id = self._project_active.get(project_id)
            if active_id and active_id in self._runs:
                run = self._public_state(self._runs[active_id])
                if run.get("status") in ACTIVE_STATUSES:
                    return run
        for run in self.list_runs(project_id):
            if run.get("status") in ACTIVE_STATUSES:
                return run
        return None

    def get(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            run = self._runs.get(run_id)
            if run:
                return self._public_state(run)
        for row in self._persistence.list_runs():
            if row.get("run_id") == run_id:
                return row
        return None

    def events_since(self, run_id: str, index: int = 0) -> List[Dict[str, Any]]:
        since = max(0, int(index))
        with self._lock:
            run = self._runs.get(run_id)
            if run:
                return list(run["events"][since:])
        project_id = self._project_id_for_run(run_id)
        if project_id:
            return self._persistence.load_events(project_id, run_id, since=since)
        return []

    def final_event_index(self, run_id: str) -> int:
        events = self.events_since(run_id, 0)
        if not events:
            run = self.get(run_id) or {}
            return int(run.get("event_count") or 0)
        return int(events[-1].get("id", 0)) + 1

    def start_run(
        self,
        *,
        project_id: str,
        mode: str,
        rounds: Optional[int],
        rough_idea: Optional[str] = None,
        attached_reference_paths: Optional[List[str]] = None,
        enable_agents: Optional[Dict[str, bool]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        store = Store(self.base_dir, project_id)
        if not store.project_dir.exists():
            raise ValueError("Project not found")

        base_config = copy.deepcopy(config) if config else Store(self.base_dir).load_config()
        resolved_config = apply_run_rounds(base_config, rounds)
        resolved_config = apply_run_enable_agents(resolved_config, enable_agents)
        attached_paths = normalize_attached_reference_paths(
            project_id,
            attached_reference_paths,
        )

        with self._lock:
            active_id = self._project_active.get(project_id)
            if active_id:
                active = self._runs.get(active_id)
                if active and active.get("status") in ACTIVE_STATUSES:
                    raise ValueError("Project already has an active run")

            run_id = f"run_{uuid.uuid4().hex[:10]}"
            state = {
                "run_id": run_id,
                "project_id": project_id,
                "mode": mode,
                "status": "queued",
                "current_stage": "",
                "current_agent": "",
                "round": resolved_config.get("rounds"),
                "rough_idea": rough_idea or "",
                "attached_reference_paths": attached_paths,
                "requires_rounds_input": general_formal_meeting_enabled(base_config) and rounds is None,
                "config_snapshot": resolved_config,
                "pending_decision": None,
                "cancel_requested": False,
                "started_at": datetime.now().isoformat(),
                "finished_at": None,
                "error": None,
                "events": [],
            }
            self._runs[run_id] = state
            self._project_active[project_id] = run_id
            self._persist_locked(state)

        thread = threading.Thread(target=self._execute, args=(run_id,), daemon=True)
        thread.start()
        return self.get(run_id) or {}

    def cancel(self, run_id: str) -> Dict[str, Any]:
        with self._lock:
            run = self._runs.get(run_id)
            if not run:
                raise KeyError(run_id)
            run["cancel_requested"] = True
            if run["status"] in {"queued", "running", "waiting_for_human"}:
                run["status"] = "cancelling"
            self._append_event_locked(run, {"type": "cancel_requested", "message": "Cancel requested"})
            self._persist_locked(run)
            return self._public_state(run)

    def submit_decision(self, run_id: str, decision_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            run = self._runs.get(run_id)
            if not run:
                raise KeyError(run_id)
            pending = run.get("pending_decision") or {}
            if pending and pending.get("id") != decision_id:
                raise ValueError("decision_id does not match pending decision")
            run["pending_decision"] = None
            run["_decision_response"] = payload
            decision_event = run.get("_decision_event")
            if decision_event:
                decision_event.set()
            self._append_event_locked(
                run,
                {
                    "type": "human_decision_submitted",
                    "decision_id": decision_id,
                    "payload": payload,
                    "message": "Human decision submitted",
                },
            )
            if run["status"] == "waiting_for_human":
                run["status"] = "running"
            self._persist_locked(run)
            return self._public_state(run)

    def _execute(self, run_id: str) -> None:
        load_dotenv(self.base_dir / ".env")
        with self._lock:
            run = self._runs[run_id]
            run["status"] = "running"
            self._append_event_locked(run, {"type": "run_started", "message": "Run started"})
            attached_paths = list(run.get("attached_reference_paths") or [])
            if attached_paths:
                self._append_event_locked(
                    run,
                    {
                        "type": "references_attached",
                        "message": "Attached reference files",
                        "attached_reference_paths": attached_paths,
                    },
                )
            self._persist_locked(run)

        project_id = ""
        try:
            base_store = Store(self.base_dir)
            with self._lock:
                config = copy.deepcopy(self._runs[run_id].get("config_snapshot") or base_store.load_config())
            validate_provider_api_keys(config)

            project_id = str(self._runs[run_id]["project_id"])
            store = Store(self.base_dir, project_id)
            write_file_log = bool(export_enabled(config, "log", False))
            logger = EventLogger(
                store.log_dir,
                emit=lambda event: self._append_event(run_id, event),
                write_file=write_file_log,
            )
            flow = Flow(config, store, logger)
            with self._lock:
                self._runs[run_id]["_flow"] = flow
            register_cancel_checker(project_id, lambda: self._cancelled(run_id))

            if self._cancelled(run_id):
                self._finish(run_id, "cancelled")
                return

            original_user_selection = Collect.user_selection
            original_human_decision = Collect.human_decision_on_issue
            Collect.user_selection = staticmethod(
                lambda proposed, max_select=5: self._request_stakeholder_selection(
                    run_id,
                    proposed,
                    max_select=max_select,
                )
            )
            Collect.human_decision_on_issue = staticmethod(
                lambda issue, options: self._request_human_decision(run_id, issue, options)
            )
            output_exported_via_flow = False
            try:
                mode = self._runs[run_id]["mode"]
                rough_idea = str(self._runs[run_id].get("rough_idea") or "").strip()
                attached_paths = list(
                    self._runs[run_id].get("attached_reference_paths") or []
                )
                artifact = self._prepare_artifact_for_run(
                    store,
                    mode=mode,
                    rough_idea=rough_idea,
                    attached_reference_paths=attached_paths,
                )
                if mode == "continue":
                    if not artifact:
                        raise RuntimeError("Cannot continue project without artifact")
                    flow.run_continue(artifact)
                else:
                    if not rough_idea:
                        rough_idea = str(artifact.get("rough_idea") or "").strip()
                    if not rough_idea:
                        raise RuntimeError("rough_idea is required for new project")
                    sync_output_language(rough_idea, artifact)
                    flow.run(rough_idea)
                output_exported_via_flow = True
            finally:
                Collect.user_selection = original_user_selection
                Collect.human_decision_on_issue = original_human_decision
                clear_cancel_checker(project_id)

            self._finish(
                run_id,
                "cancelled" if self._cancelled(run_id) else "completed",
                flow=flow,
                output_exported_via_flow=output_exported_via_flow,
            )
        except Exception as exc:
            with self._lock:
                run = self._runs[run_id]
                project_id = str(run.get("project_id") or "")
                run["status"] = "failed"
                run["error"] = str(exc)
                run["finished_at"] = datetime.now().isoformat()
                self._append_event_locked(
                    run,
                    {"type": "run_failed", "message": str(exc), "error": str(exc)},
                )
                self._persist_locked(run)
                self._release_active_locked(run)
                run.pop("_flow", None)
            if project_id:
                clear_cancel_checker(project_id)

    def _finish(
        self,
        run_id: str,
        status: str,
        *,
        flow: Optional[Flow] = None,
        output_exported_via_flow: bool = False,
    ) -> None:
        project_id = ""
        with self._lock:
            run = self._runs[run_id]
            project_id = str(run.get("project_id") or "")
            if flow is None:
                flow = run.pop("_flow", None)
            else:
                run.pop("_flow", None)
            run["status"] = status
            run["finished_at"] = datetime.now().isoformat()
            self._append_event_locked(run, {"type": f"run_{status}", "message": f"Run {status}"})
            self._persist_locked(run)
            self._release_active_locked(run)
        if project_id:
            clear_cancel_checker(project_id)
        if status == "completed" and flow is not None:
            self._auto_export_after_finish(
                run_id,
                project_id,
                flow,
                output_exported_via_flow=output_exported_via_flow,
            )

    def _auto_export_after_finish(
        self,
        run_id: str,
        project_id: str,
        flow: Flow,
        *,
        output_exported_via_flow: bool,
    ) -> None:
        from .project_service import ProjectService

        service = ProjectService(self.base_dir, run_manager=self)
        export_flags = service.describe_export_flags(flow.config)
        if output_exported_via_flow:
            self._append_event(
                run_id,
                {
                    "type": "auto_export_completed",
                    "message": "Run output already exported by flow",
                    "exported": export_flags,
                    "skipped": True,
                },
            )
            return
        try:
            result = service.export_from_flow(
                flow,
                html=export_flags["html"],
                cost=export_flags["cost"],
            )
            self._append_event(
                run_id,
                {
                    "type": "auto_export_completed",
                    "message": "Auto export completed",
                    "exported": result.get("exported"),
                    "skipped": False,
                },
            )
        except Exception as exc:
            self._append_event(
                run_id,
                {
                    "type": "auto_export_failed",
                    "message": str(exc),
                    "error": str(exc),
                },
            )

    def _prepare_artifact_for_run(
        self,
        store: Store,
        *,
        mode: str,
        rough_idea: str,
        attached_reference_paths: List[str],
    ) -> Dict[str, Any]:
        artifact = store.load_artifact() or {}
        changed = False

        if mode == "continue":
            if rough_idea:
                existing = str(artifact.get("rough_idea") or "").strip()
                if rough_idea != existing:
                    artifact["rough_idea"] = rough_idea
                    sync_output_language(rough_idea, artifact)
                    changed = True
            elif artifact.get("rough_idea"):
                sync_output_language(str(artifact.get("rough_idea") or ""), artifact)
                changed = True
        elif rough_idea:
            artifact["rough_idea"] = rough_idea
            sync_output_language(rough_idea, artifact)
            changed = True

        if attached_reference_paths:
            meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
            meta["attached_references"] = attached_reference_paths
            artifact["meta"] = meta
            changed = True

        if changed:
            store.save_artifact(artifact)
        return artifact

    def _cancelled(self, run_id: str) -> bool:
        with self._lock:
            return bool(self._runs.get(run_id, {}).get("cancel_requested"))

    def _append_event(self, run_id: str, event: Dict[str, Any]) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if not run:
                return
            self._append_event_locked(run, event)
            self._persist_locked(run)

    def _append_event_locked(self, run: Dict[str, Any], event: Dict[str, Any]) -> None:
        item = dict(event)
        item.setdefault("timestamp", datetime.now().isoformat())
        item["id"] = len(run["events"])
        run["events"].append(item)
        project_id = str(run.get("project_id") or "")
        run_id = str(run.get("run_id") or "")
        if project_id and run_id:
            self._persistence.append_event(project_id, run_id, item)

    def _persist_locked(self, run: Dict[str, Any]) -> None:
        self._persistence.save_state(run)

    def _release_active_locked(self, run: Dict[str, Any]) -> None:
        project_id = run.get("project_id")
        if project_id and self._project_active.get(project_id) == run.get("run_id"):
            self._project_active.pop(project_id, None)

    def _public_state(self, run: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not run:
            return {}
        return self._persistence.public_state(run)

    def _project_id_for_run(self, run_id: str) -> Optional[str]:
        with self._lock:
            run = self._runs.get(run_id)
            if run:
                return str(run.get("project_id") or "") or None
        for row in self._persistence.list_runs():
            if row.get("run_id") == run_id:
                return str(row.get("project_id") or "") or None
        return None

    def _request_stakeholder_selection(
        self,
        run_id: str,
        proposed: List[Dict[str, Any]],
        *,
        max_select: int,
    ) -> List[Dict[str, Any]]:
        payload = {
            "id": f"stakeholders_{uuid.uuid4().hex[:8]}",
            "kind": "stakeholder_selection",
            "title": "請選擇利害關係人",
            "description": (
                f"最多 {max_select} 位。可輸入編號或自訂名稱，例如 1,3,系統管理員；"
                "也可傳 stakeholders 或 selections 結構化資料。"
            ),
            "proposed": proposed,
            "max_select": max_select,
            "response_schema": {
                "stakeholders": [{"name": "string", "type": "primary_user|system_owner|external_party", "reason": "string"}],
                "selections": [{"index": 1}, {"name": "string", "type": "primary_user|system_owner|external_party"}],
                "selection": "1,3,系統管理員",
                "custom_types": {"系統管理員": "system_owner"},
            },
        }
        response = self._wait_for_decision(run_id, payload)
        return parse_stakeholder_response(response, proposed, max_select=max_select)

    def _request_human_decision(self, run_id: str, issue: Dict[str, Any], options: Any) -> Dict[str, Any]:
        payload = {
            "id": f"decision_{uuid.uuid4().hex[:8]}",
            "kind": "human_decision",
            "title": str((issue or {}).get("title") or "需要人類裁決"),
            "description": str((issue or {}).get("description") or ""),
            "issue": issue,
            "options": options,
            "response_schema": {
                "skipped": True,
                "choices": [1, 2],
                "custom_decision": "string",
                "chosen_options": [{"id": 1, "title": "string", "description": "string", "rationale": "string"}],
                "decision": "string",
            },
        }
        response = self._wait_for_decision(run_id, payload)
        return parse_human_decision_response(response, options)

    def _wait_for_decision(self, run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        event = threading.Event()
        with self._lock:
            run = self._runs[run_id]
            run["status"] = "waiting_for_human"
            run["pending_decision"] = payload
            run["_decision_event"] = event
            run["_decision_response"] = None
            self._append_event_locked(
                run,
                {
                    "type": "waiting_for_human",
                    "decision_id": payload["id"],
                    "decision": payload,
                    "message": payload.get("title", "Waiting for human input"),
                },
            )
            self._persist_locked(run)
        while True:
            if self._cancelled(run_id):
                raise RuntimeError("Run cancelled while waiting for human input")
            if event.wait(timeout=0.5):
                break
        with self._lock:
            run = self._runs[run_id]
            response = run.get("_decision_response") or {}
            run["_decision_event"] = None
            run["_decision_response"] = None
            if run["status"] == "waiting_for_human":
                run["status"] = "running"
            self._persist_locked(run)
            return response


def sse_format(event: Dict[str, Any]) -> str:
    return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"


def sse_heartbeat() -> str:
    return ": ping\n\n"


def sse_done(run_id: str, status: str, *, next_event_id: int) -> str:
    payload = {
        "type": "stream_done",
        "run_id": run_id,
        "status": status,
        "next_event_id": next_event_id,
    }
    return "event: done\ndata: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
