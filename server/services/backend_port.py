from __future__ import annotations

import os
import socket
import sys


DEFAULT_BACKEND_PORT = 8000


def configured_backend_port() -> int:
    raw_value = os.getenv("backend_port", str(DEFAULT_BACKEND_PORT)).strip()
    try:
        port = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"backend_port 必須是整數，目前值：{raw_value!r}") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError(f"backend_port 必須介於 1 到 65535，目前值：{port}")
    return port


def ensure_backend_port_available(host: str, port: int) -> None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind((host, port))
    except OSError as exc:
        command = (
            f"netstat -ano | findstr :{port}"
            if sys.platform == "win32"
            else f"lsof -nP -iTCP:{port} -sTCP:LISTEN"
        )
        raise RuntimeError(
            f"後端 Port {port} 已被其他程式占用；"
            f"請關閉占用程序或修改 .env 的 backend_port 後重試（可用 {command} 查詢）"
        ) from exc
