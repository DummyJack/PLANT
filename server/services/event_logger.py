from datetime import datetime
from pathlib import Path

from utils.log import Logger


class EventLogger(Logger):
    def __init__(self, log_dir: Path, emit, write_file: bool = False):
        super().__init__(log_dir, write_file=write_file)
        self.emit = emit

    def _event(self, level: str, msg, *args):
        text = str(msg)
        if args:
            try:
                text = text % args
            except TypeError:
                text = " ".join([text, *[str(arg) for arg in args]])
        self.emit(
            {
                "type": "log",
                "level": level,
                "message": text,
                "timestamp": datetime.now().isoformat(),
            }
        )

    def info(self, msg, *args, **kwargs):
        self._event("info", msg, *args)
        super().info(msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self._event("warning", msg, *args)
        super().warning(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self._event("error", msg, *args)
        super().error(msg, *args, **kwargs)
