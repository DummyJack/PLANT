"""Thread-scoped logging used by the PLANT runtime."""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


class RunThreadFilter(logging.Filter):
    def __init__(self, owner_thread_id: int):
        super().__init__()
        self.owner_thread_id = owner_thread_id

    def filter(self, record: logging.LogRecord) -> bool:
        return record.thread == self.owner_thread_id


class Logger:
    def __init__(self, log_dir: str = "log", write_file: bool = True):
        timestamp = datetime.now().strftime("%H%M%S%f")
        owner_thread_id = threading.get_ident()
        handlers = [logging.StreamHandler()]
        self.log_dir = Path(log_dir)
        if write_file:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            log_file = self.log_dir / f"system_{os.getpid()}_{owner_thread_id}_{timestamp}.log"
            handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

        self.logger = logging.getLogger("Plant")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        formatter = logging.Formatter(LOG_FORMAT)
        thread_filter = RunThreadFilter(owner_thread_id)
        self._handlers = handlers
        for handler in handlers:
            handler.setLevel(logging.INFO)
            handler.setFormatter(formatter)
            handler.addFilter(thread_filter)
            self.logger.addHandler(handler)

    def close(self) -> None:
        for handler in getattr(self, "_handlers", []):
            self.logger.removeHandler(handler)
            try:
                handler.flush()
            finally:
                handler.close()
        self._handlers = []

    def info(self, msg: object, *args: Any, **kwargs: Any) -> None:
        self.logger.info(msg, *args, **kwargs)

    def debug(self, msg: object, *args: Any, **kwargs: Any) -> None:
        self.logger.debug(msg, *args, **kwargs)

    def warning(self, msg: object, *args: Any, **kwargs: Any) -> None:
        self.logger.warning(msg, *args, **kwargs)

    def error(self, msg: object, *args: Any, **kwargs: Any) -> None:
        self.logger.error(msg, *args, **kwargs)

    def stage_started(
        self, stage_id: str, title: str, *, message: str | None = None
    ) -> None:
        self.info("stage started: %s", message or title)

    def stage_completed(
        self, stage_id: str, title: str, *, message: str | None = None
    ) -> None:
        self.info("stage completed: %s", message or title)

    def step_started(
        self,
        stage_id: str,
        step_id: str,
        title: str,
        *,
        agent: str | None = None,
        message: str | None = None,
    ) -> None:
        if agent:
            self.info("%s: %s", agent, message or title)
        else:
            self.info("%s", message or title)

    def step_delta(
        self,
        stage_id: str,
        step_id: str,
        content: Any,
        *,
        delta_type: str = "text",
        agent: str | None = None,
        title: str | None = None,
    ) -> None:
        return None

    def step_completed(
        self,
        stage_id: str,
        step_id: str,
        title: str,
        *,
        agent: str | None = None,
        message: str | None = None,
        output_path: str | None = None,
        summary: dict | None = None,
    ) -> None:
        if output_path:
            self.info("%s: %s (%s)", agent or "system", message or title, output_path)
        else:
            self.info("%s: %s", agent or "system", message or title)

    def artifact_created(
        self,
        stage_id: str,
        step_id: str,
        title: str,
        output_path: str,
        *,
        message: str | None = None,
    ) -> None:
        self.info("%s: %s (%s)", step_id, message or title, output_path)

    def heartbeat(
        self,
        stage_id: str | None = None,
        step_id: str | None = None,
        *,
        message: str = "仍在處理中",
    ) -> None:
        self.info("%s", message)
