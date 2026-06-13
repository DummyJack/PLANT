import copy
import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from flow.setup import Flow
from model import normalize_authentication_error, validate_provider_api_keys
from storage import Store
from utils import export_enabled
from utils.cancel import clear_cancel_checker, register_cancel_checker
from utils.human import Collect
from utils.language import sync_output_language

from .event_logger import EventLogger
from .human_decisions import (
    normalize_decision_options_payload,
    parse_human_decision_response,
    parse_stakeholder_response,
)
from .run_config import (
    apply_run_enable_agents,
    apply_run_max_issues,
    apply_run_rounds,
    apply_run_stage_overrides,
    general_formal_meeting_enabled,
    normalize_attached_reference_paths,
)
from .run_persistence import ACTIVE_STATUSES, RunPersistence
from .run_checkpoint import clear_run_checkpoint, clear_run_checkpoint_for_continue, load_run_checkpoint, mark_run_checkpoint


UI_ERROR_MAX_LENGTH = 500
MAX_STEP_DELTA_EVENTS_PER_RUN = 1000


def _ui_error_message(exc: Exception) -> str:
    normalized = normalize_authentication_error(exc)
    text = str(normalized).strip() or "執行失敗"
    if "\n" in text:
        text = next((line.strip() for line in text.splitlines() if line.strip()), text)
    if len(text) > UI_ERROR_MAX_LENGTH:
        text = text[:UI_ERROR_MAX_LENGTH].rstrip() + "..."
    return text


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
        for row in rows:
            self._attach_run_checkpoint(row)
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
        max_issues: Optional[int] = None,
        rough_idea: Optional[str] = None,
        attached_reference_paths: Optional[List[str]] = None,
        enable_agents: Optional[Dict[str, bool]] = None,
        stage_overrides: Optional[Dict[str, bool]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        store = Store(self.base_dir, project_id)
        if not store.project_dir.exists():
            raise ValueError("Project not found")

        base_config = copy.deepcopy(config) if config else Store(self.base_dir).load_config()
        resolved_config = apply_run_stage_overrides(base_config, stage_overrides)
        resolved_config = apply_run_rounds(resolved_config, rounds)
        resolved_config = apply_run_max_issues(resolved_config, max_issues)
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
                "skip_all_human_interventions": False,
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
            if payload.get("skip_all_human_interventions") is True:
                run["skip_all_human_interventions"] = True
                payload = {
                    **payload,
                    "skipped": True,
                }
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
            if payload.get("skip_all_human_interventions") is True:
                self._append_event_locked(
                    run,
                    {
                        "type": "human_intervention_skip_all_enabled",
                        "decision_id": decision_id,
                        "message": "後續人類介入將自動跳過",
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
            flow.run_id = run_id
            with self._lock:
                self._runs[run_id]["_flow"] = flow
            register_cancel_checker(project_id, lambda: self._cancelled(run_id))

            if self._cancelled(run_id):
                self._finish(run_id, "cancelled")
                return

            original_user_selection = Collect.user_selection
            original_human_decision = Collect.human_decision_on_issue
            original_stakeholder_statement_review = Collect.stakeholder_statement_review
            original_requirements_review = Collect.requirements_review
            original_domain_research_review = Collect.domain_research_review
            original_meeting_issue_proposal_review = Collect.meeting_issue_proposal_review
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
            Collect.stakeholder_statement_review = staticmethod(
                lambda stakeholders: self._request_stakeholder_statement_review(run_id, stakeholders)
            )
            Collect.requirements_review = staticmethod(
                lambda requirements: self._request_requirements_review(run_id, requirements)
            )
            Collect.domain_research_review = staticmethod(
                lambda references: self._request_domain_research_review(run_id, references)
            )
            Collect.meeting_issue_proposal_review = staticmethod(
                lambda proposals, round_num, max_issues=5: self._request_meeting_issue_proposal_review(
                    run_id,
                    proposals,
                    round_num,
                    max_issues=max_issues,
                )
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
                    run_id=run_id,
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
                Collect.stakeholder_statement_review = original_stakeholder_statement_review
                Collect.requirements_review = original_requirements_review
                Collect.domain_research_review = original_domain_research_review
                Collect.meeting_issue_proposal_review = original_meeting_issue_proposal_review
                clear_cancel_checker(project_id)

            self._finish(
                run_id,
                "cancelled" if self._cancelled(run_id) else "completed",
                flow=flow,
                output_exported_via_flow=output_exported_via_flow,
            )
        except Exception as exc:
            error_text = _ui_error_message(exc)
            with self._lock:
                run = self._runs[run_id]
                project_id = str(run.get("project_id") or "")
                stage_id = str(run.get("current_stage") or "")
                run["status"] = "failed"
                run["error"] = error_text
                run["finished_at"] = datetime.now().isoformat()
                self._append_event_locked(
                    run,
                    {"type": "run_failed", "message": error_text, "error": error_text},
                )
                self._persist_locked(run)
                self._release_active_locked(run)
                run.pop("_flow", None)
            if project_id:
                self._record_checkpoint(
                    project_id,
                    run_id=run_id,
                    status="failed",
                    stage_id=stage_id,
                    error=error_text,
                )
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
            stage_id = str(run.get("current_stage") or "")
            self._append_event_locked(run, {"type": f"run_{status}", "message": f"Run {status}"})
            self._persist_locked(run)
            self._release_active_locked(run)
        if project_id:
            if status == "cancelled":
                self._record_checkpoint(
                    project_id,
                    run_id=run_id,
                    status="cancelled",
                    stage_id=stage_id,
                    error="Run cancelled",
                )
            elif status == "completed":
                try:
                    clear_run_checkpoint(Store(self.base_dir, project_id))
                except Exception:
                    pass
            clear_cancel_checker(project_id)
        if status == "completed" and flow is not None:
            self._auto_export_after_finish(
                run_id,
                project_id,
                flow,
                output_exported_via_flow=output_exported_via_flow,
            )
            self._clear_consumed_force_regenerate_flags(flow)

    def _clear_consumed_force_regenerate_flags(self, flow: Flow) -> None:
        flags = (getattr(flow, "config", {}) or {}).get("force_regenerate_outputs")
        if not isinstance(flags, dict) or not flags:
            return
        try:
            store = Store(self.base_dir)
            config = store.load_config()
            current = config.get("force_regenerate_outputs")
            if not isinstance(current, dict):
                return
            for key in ("DR", "SRS"):
                if flags.get(key) is True:
                    current.pop(key, None)
            if current:
                config["force_regenerate_outputs"] = current
            else:
                config.pop("force_regenerate_outputs", None)
            store.save_config(config)
        except Exception:
            pass

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
            error_text = _ui_error_message(exc)
            self._append_event(
                run_id,
                {
                    "type": "auto_export_failed",
                    "message": error_text,
                    "error": error_text,
                },
            )

    def _record_checkpoint(
        self,
        project_id: str,
        *,
        run_id: str,
        status: str,
        stage_id: str,
        error: str = "",
    ) -> None:
        if not project_id or not stage_id:
            return
        try:
            store = Store(self.base_dir, project_id)
            checkpoint = mark_run_checkpoint(
                store,
                run_id=run_id,
                status=status,
                stage_id=stage_id,
                error=error,
            )
            self._append_event(
                run_id,
                {
                    "type": "run_checkpoint_recorded",
                    "stage_id": stage_id,
                    "message": "已記錄繼續時可重跑的步驟",
                    "checkpoint": checkpoint,
                },
            )
        except Exception as exc:
            self._append_event(
                run_id,
                {
                    "type": "run_checkpoint_record_failed",
                    "stage_id": stage_id,
                    "message": _ui_error_message(exc),
                    "error": _ui_error_message(exc),
                },
            )

    def _prepare_artifact_for_run(
        self,
        store: Store,
        *,
        run_id: str,
        mode: str,
        rough_idea: str,
        attached_reference_paths: List[str],
    ) -> Dict[str, Any]:
        artifact = store.load_artifact() or {}
        changed = False

        if mode == "continue":
            artifact = clear_run_checkpoint_for_continue(store, artifact)
            changed = True
            if rough_idea:
                meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
                history = meta.get("continue_instructions")
                if not isinstance(history, list):
                    history = []
                instruction = {
                    "run_id": run_id,
                    "text": rough_idea,
                    "created_at": datetime.now().isoformat(),
                }
                history.append(instruction)
                meta["continue_instruction"] = rough_idea
                meta["continue_instructions"] = history
                artifact["meta"] = meta
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
        if item.get("type") == "step_delta":
            delta_count = sum(1 for existing in run.get("events", []) if existing.get("type") == "step_delta")
            if delta_count >= MAX_STEP_DELTA_EVENTS_PER_RUN:
                return
        item.setdefault("timestamp", datetime.now().isoformat())
        item["id"] = len(run["events"])
        run["events"].append(item)
        stage_id = item.get("stage_id")
        if isinstance(stage_id, str) and stage_id:
            run["current_stage"] = stage_id
        agent = item.get("agent")
        if isinstance(agent, str) and agent:
            run["current_agent"] = agent
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
        state = self._persistence.public_state(run)
        self._attach_run_checkpoint(state)
        return state

    def _attach_run_checkpoint(self, state: Dict[str, Any]) -> None:
        project_id = str(state.get("project_id") or "").strip()
        if not project_id:
            return
        if str(state.get("status") or "") == "completed":
            state.pop("run_checkpoint", None)
            return
        try:
            checkpoint = load_run_checkpoint(Store(self.base_dir, project_id))
        except Exception:
            checkpoint = None
        if not checkpoint:
            state.pop("run_checkpoint", None)
            return
        checkpoint_run_id = str(checkpoint.get("run_id") or "")
        run_id = str(state.get("run_id") or "")
        if checkpoint_run_id and run_id and checkpoint_run_id != run_id:
            return
        state["run_checkpoint"] = checkpoint

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
            "description": f"最多 {max_select} 位。",
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
        normalized_options = normalize_decision_options_payload(options)
        payload = {
            "id": f"decision_{uuid.uuid4().hex[:8]}",
            "kind": "human_decision",
            "title": str((issue or {}).get("title") or "需要人類裁決"),
            "description": str((issue or {}).get("description") or ""),
            "issue": issue,
            "options": normalized_options,
            "response_schema": {
                "skipped": True,
                "choices": ["A", "B"],
                "custom_decision": "string",
                "chosen_options": [{"id": "A", "option_id": "A", "index": 1, "title": "string", "description": "string", "rationale": "string"}],
                "decision": "string",
            },
        }
        response = self._wait_for_decision(run_id, payload)
        return parse_human_decision_response(response, normalized_options)

    def _request_stakeholder_statement_review(
        self,
        run_id: str,
        stakeholders: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        payload = {
            "id": f"stakeholder_statement_{uuid.uuid4().hex[:8]}",
            "kind": "stakeholder_statement_review",
            "title": "利害關係人發言",
            "description": "請確認、直接編輯，或留下 Human Decision。",
            "options": {
                "stage_id": "stakeholder_statement",
                "status": "waiting_for_human_decision",
                "stakeholders": stakeholders,
            },
            "response_schema": {
                "action": "approve|direct_edit|human_decision|selection_comment|agent_refinement",
                "stakeholders": [{"name": "string", "text": [{"id": "string", "text": "string"}]}],
                "human_decision": "string",
                "selection_comment": {"selected_text": "string", "comment": "string"},
            },
        }
        response = self._wait_for_decision(run_id, payload)
        return response if isinstance(response, dict) else {"action": "approve"}

    def _request_requirements_review(
        self,
        run_id: str,
        requirements: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        payload = {
            "id": f"requirements_review_{uuid.uuid4().hex[:8]}",
            "kind": "requirements_review",
            "title": "初始需求分析",
            "description": "請在對話匡加入建議，按確定送出。",
            "options": {
                "stage_id": "requirements_review",
                "status": "waiting_for_human_decision",
                "requirements": requirements,
            },
            "response_schema": {
                "action": "approve|human_decision|selection_comment|agent_refinement",
                "human_decision": "string",
                "selection_comment": {"selected_text": "string", "comment": "string"},
            },
        }
        response = self._wait_for_decision(run_id, payload)
        return response if isinstance(response, dict) else {"action": "approve"}

    def _request_domain_research_review(
        self,
        run_id: str,
        references: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        payload = {
            "id": f"domain_research_review_{uuid.uuid4().hex[:8]}",
            "kind": "domain_research_review",
            "title": "領域研究",
            "description": "請在對話匡加入建議，按確定送出。",
            "options": {
                "stage_id": "domain_research_review",
                "status": "waiting_for_human_decision",
                "references": references,
            },
            "response_schema": {
                "action": "approve|human_decision",
                "human_decision": "string",
                "referenced_files": [{"name": "string", "path": "string", "type": "string"}],
            },
        }
        response = self._wait_for_decision(run_id, payload)
        return response if isinstance(response, dict) else {"action": "approve"}

    def _request_meeting_issue_proposal_review(
        self,
        run_id: str,
        proposals: List[Dict[str, Any]],
        round_num: int,
        max_issues: int = 5,
    ) -> Dict[str, Any]:
        payload = {
            "id": f"meeting_issue_proposal_review_{uuid.uuid4().hex[:8]}",
            "kind": "meeting_issue_proposal_review",
            "title": "候選議題",
            "description": "可輸入自訂議題，按確定送出。",
            "options": {
                "stage_id": "meeting_issue_proposal_review",
                "status": "waiting_for_human_decision",
                "round_num": round_num,
                "max_issues": max_issues,
                "proposals": proposals,
            },
            "response_schema": {
                "action": "approve|human_issues",
                "custom_issues": [{"title": "string"}],
            },
        }
        response = self._wait_for_decision(run_id, payload)
        return response if isinstance(response, dict) else {"action": "approve"}

    def _wait_for_decision(self, run_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        event = threading.Event()
        with self._lock:
            run = self._runs[run_id]
            if (
                run.get("skip_all_human_interventions") is True
                and payload.get("kind") != "stakeholder_selection"
            ):
                response = self._auto_skip_decision_response(payload)
                self._append_event_locked(
                    run,
                    {
                        "type": "human_decision_auto_skipped",
                        "decision_id": payload["id"],
                        "decision": payload,
                        "payload": response,
                        "message": "已自動跳過人類介入",
                    },
                )
                self._persist_locked(run)
                return response
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

    @staticmethod
    def _auto_skip_decision_response(payload: Dict[str, Any]) -> Dict[str, Any]:
        kind = str(payload.get("kind") or "").strip()
        if kind == "human_decision":
            return {"skipped": True, "auto_skipped": True}
        return {"action": "approve", "skipped": True, "auto_skipped": True}


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
