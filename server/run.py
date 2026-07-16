import os
import socket
import sys
from pathlib import Path

from utils.preflight import ensure_python_dependencies, preflight_enabled


BASE_DIR = Path(__file__).resolve().parents[1]
PREFLIGHT_ENABLED = preflight_enabled(BASE_DIR, "server")
if PREFLIGHT_ENABLED and sys.version_info < (3, 10):
    current = ".".join(str(part) for part in sys.version_info[:3])
    raise RuntimeError(
        f"PLANT requires Python 3.10 or newer; current version is Python {current}"
    )
if PREFLIGHT_ENABLED:
    ensure_python_dependencies(BASE_DIR)

from dotenv import load_dotenv
from .services.startup import run_backend_startup_checks


INTERNAL_BACKEND_HOST = "127.0.0.1"
INTERNAL_BACKEND_PORT = 8000


def require_backend_port_available() -> None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind((INTERNAL_BACKEND_HOST, INTERNAL_BACKEND_PORT))
    except OSError as exc:
        raise RuntimeError(
            f"後端 Port {INTERNAL_BACKEND_PORT} 已被其他程式占用"
        ) from exc


def main() -> None:
    load_dotenv(BASE_DIR / ".env")
    if PREFLIGHT_ENABLED:
        run_backend_startup_checks(BASE_DIR)
    os.environ["PLANT_BACKEND_STARTUP_CHECKED"] = "1"
    require_backend_port_available()

    import uvicorn

    uvicorn.run(
        "server.app:app",
        host=INTERNAL_BACKEND_HOST,
        port=INTERNAL_BACKEND_PORT,
        reload=True,
        reload_dirs=[str(BASE_DIR)],
        reload_excludes=[
            ".env",
            "config.json",
            "doc/*",
            "log/*",
            "manual/*",
            "projects/*",
            "system/*",
        ],
    )


if __name__ == "__main__":
    main()
