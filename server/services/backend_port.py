from __future__ import annotations

import errno
import json
import os
import socket
import sys
from pathlib import Path


DEFAULT_BACKEND_PORT = 8000
BACKEND_PORT_SEARCH_LIMIT = 100
BACKEND_RUNTIME_FILE = Path("log/backend-runtime.json")


def configured_backend_port() -> int:
    raw_value = os.getenv("backend_port", str(DEFAULT_BACKEND_PORT)).strip()
    try:
        port = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"backend_port 必須是整數，目前值：{raw_value!r}") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError(f"backend_port 必須介於 1 到 65535，目前值：{port}")
    return port


def first_available_backend_port(
    host: str,
    start_port: int,
    *,
    search_limit: int = BACKEND_PORT_SEARCH_LIMIT,
) -> int:
    end_port = min(65535, start_port + max(1, search_limit) - 1)
    last_error: OSError | None = None
    for port in range(start_port, end_port + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                probe.bind((host, port))
            return port
        except OSError as exc:
            last_error = exc
            if exc.errno in {errno.EADDRINUSE, errno.EACCES}:
                continue
            raise RuntimeError(f"無法檢查後端 Port {port}：{exc}") from exc

    command = (
        f"netstat -ano | findstr :{start_port}"
        if sys.platform == "win32"
        else f"lsof -nP -iTCP:{start_port}-{end_port} -sTCP:LISTEN"
    )
    detail = f"；最後錯誤：{last_error}" if last_error else ""
    raise RuntimeError(
        f"後端 Port {start_port} 到 {end_port} 都無法使用{detail}；可用 {command} 查詢"
    )


def write_backend_runtime(base_dir: Path, host: str, port: int) -> Path:
    runtime_path = base_dir / BACKEND_RUNTIME_FILE
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"host": host, "port": port, "pid": os.getpid()}
    runtime_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return runtime_path


def remove_backend_runtime(runtime_path: Path) -> None:
    try:
        payload = json.loads(runtime_path.read_text(encoding="utf-8"))
        if int(payload.get("pid") or 0) != os.getpid():
            return
        runtime_path.unlink(missing_ok=True)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return
