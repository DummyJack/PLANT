# Handles log logic for shared utility behavior for the Plant runtime.
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
        timestamp = datetime.now().strftime("%H%M%S")
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
