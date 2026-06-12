from datetime import datetime
from pathlib import Path
from typing import Any

from utils.log import Logger
from .security import sanitize_workspace_event


class EventLogger(Logger):
    def __init__(self, log_dir: Path, emit, write_file: bool = False):
        super().__init__(log_dir, write_file=write_file)
        self.emit = emit

    def workspace_event(self, event_type: str, **payload: Any):
        payload.setdefault("timestamp", datetime.now().isoformat())
        self.emit(sanitize_workspace_event({"type": event_type, **payload}))

    def info(self, msg, *args, **kwargs):
        super().info(msg, *args, **kwargs)
        try:
            message = str(msg % args if args else msg).strip()
        except Exception:
            message = str(msg).strip()
        if message:
            self.workspace_event("log", level="info", message=message)

    def warning(self, msg, *args, **kwargs):
        super().warning(msg, *args, **kwargs)
        try:
            message = str(msg % args if args else msg).strip()
        except Exception:
            message = str(msg).strip()
        if message:
            self.workspace_event("log", level="warning", message=message)

    def error(self, msg, *args, **kwargs):
        super().error(msg, *args, **kwargs)
        try:
            message = str(msg % args if args else msg).strip()
        except Exception:
            message = str(msg).strip()
        if message:
            self.workspace_event("log", level="error", message=message)

    def stage_started(self, stage_id: str, title: str, *, message: str | None = None):
        self.workspace_event(
            "stage_started",
            stage_id=stage_id,
            title=title,
            message=message or title,
            status="running",
        )
        super().info("stage started: %s", title)

    def stage_completed(self, stage_id: str, title: str, *, message: str | None = None):
        self.workspace_event(
            "stage_completed",
            stage_id=stage_id,
            title=title,
            message=message or f"{title}完成",
            status="done",
        )
        super().info("stage completed: %s", title)

    def step_started(
        self,
        stage_id: str,
        step_id: str,
        title: str,
        *,
        agent: str | None = None,
        message: str | None = None,
    ):
        self.workspace_event(
            "step_started",
            stage_id=stage_id,
            step_id=step_id,
            title=title,
            agent=agent,
            message=message or title,
            status="running",
        )
        super().info("step started: %s", title)

    def step_delta(
        self,
        stage_id: str,
        step_id: str,
        content: Any,
        *,
        delta_type: str = "text",
        agent: str | None = None,
        title: str | None = None,
    ):
        self.workspace_event(
            "step_delta",
            stage_id=stage_id,
            step_id=step_id,
            title=title,
            agent=agent,
            delta_type=delta_type,
            content=content,
            status="running",
        )

    def step_completed(
        self,
        stage_id: str,
        step_id: str,
        title: str,
        *,
        agent: str | None = None,
        message: str | None = None,
        output_path: str | None = None,
        summary: dict[str, Any] | None = None,
    ):
        self.workspace_event(
            "step_completed",
            stage_id=stage_id,
            step_id=step_id,
            title=title,
            agent=agent,
            message=message or f"{title}完成",
            output_path=output_path,
            summary=summary,
            status="done",
        )
        super().info("step completed: %s", title)

    def artifact_created(
        self,
        stage_id: str,
        step_id: str,
        title: str,
        output_path: str,
        *,
        message: str | None = None,
    ):
        self.workspace_event(
            "artifact_created",
            stage_id=stage_id,
            step_id=step_id,
            title=title,
            message=message or title,
            output_path=output_path,
            status="done",
        )
        super().info("artifact created: %s", output_path)

    def heartbeat(
        self,
        stage_id: str | None = None,
        step_id: str | None = None,
        *,
        message: str = "仍在處理中",
    ):
        self.workspace_event(
            "heartbeat",
            stage_id=stage_id,
            step_id=step_id,
            message=message,
            status="running",
        )
