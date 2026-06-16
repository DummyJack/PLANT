# Handles log logic for shared utility behavior for the Plant runtime.
from __future__ import annotations

import logging

from datetime import datetime
from pathlib import Path


# ========
# Defines Logger class for this module workflow.
# ========
class Logger:
    # ========
    # Defines __init__ function for this module workflow.
    # ========
    def __init__(self, log_dir: str = "log", write_file: bool = True):
        timestamp = datetime.now().strftime("%H%M%S%f")
        handlers = [logging.StreamHandler()]
        if write_file:
            self.log_dir = Path(log_dir)
            self.log_dir.mkdir(parents=True, exist_ok=True)
            log_file = self.log_dir / f"system_{timestamp}.log"
            handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
        else:
            self.log_dir = Path(log_dir)

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=handlers,
        )
        self.logger = logging.getLogger("Plant")

    # ========
    # Defines info function for this module workflow.
    # ========
    def info(self, msg, *args, **kwargs):
        self.logger.info(msg, *args, **kwargs)

    # ========
    # Defines debug function for this module workflow.
    # ========
    def debug(self, msg, *args, **kwargs):
        self.logger.debug(msg, *args, **kwargs)

    # ========
    # Defines warning function for this module workflow.
    # ========
    def warning(self, msg, *args, **kwargs):
        self.logger.warning(msg, *args, **kwargs)

    # ========
    # Defines error function for this module workflow.
    # ========
    def error(self, msg, *args, **kwargs):
        self.logger.error(msg, *args, **kwargs)

    def stage_started(self, stage_id: str, title: str, *, message: str | None = None):
        self.info("stage started: %s", message or title)

    def stage_completed(self, stage_id: str, title: str, *, message: str | None = None):
        self.info("stage completed: %s", message or title)

    def step_started(
        self,
        stage_id: str,
        step_id: str,
        title: str,
        *,
        agent: str | None = None,
        message: str | None = None,
    ):
        if agent:
            self.info("%s: %s", agent, message or title)
        else:
            self.info("%s", message or title)

    def step_delta(
        self,
        stage_id: str,
        step_id: str,
        content,
        *,
        delta_type: str = "text",
        agent: str | None = None,
        title: str | None = None,
    ):
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
    ):
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
    ):
        self.info("%s: %s (%s)", step_id, message or title, output_path)

    def heartbeat(
        self,
        stage_id: str | None = None,
        step_id: str | None = None,
        *,
        message: str = "仍在處理中",
    ):
        self.info("%s", message)
