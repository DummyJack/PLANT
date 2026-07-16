import os
from pathlib import Path

from utils.preflight import abort_startup, preflight_enabled, prepare_python_environment


BASE_DIR = Path(__file__).resolve().parents[1]
PREFLIGHT_ENABLED = preflight_enabled(BASE_DIR, "server")
prepare_python_environment(BASE_DIR, enabled=PREFLIGHT_ENABLED)

from dotenv import load_dotenv
from .services.backend_port import (
    configured_backend_port,
    ensure_backend_port_available,
)
from .services.startup import run_backend_startup_checks


INTERNAL_BACKEND_HOST = "127.0.0.1"


def main() -> None:
    load_dotenv(BASE_DIR / ".env")
    try:
        if PREFLIGHT_ENABLED:
            run_backend_startup_checks(BASE_DIR)
        backend_port = configured_backend_port()
        ensure_backend_port_available(INTERNAL_BACKEND_HOST, backend_port)
    except RuntimeError as exc:
        abort_startup(exc)
    print(f"[OK] 後端 Port 可使用：{backend_port}", flush=True)
    os.environ["PLANT_BACKEND_STARTUP_CHECKED"] = "1"
    os.environ["PLANT_BACKEND_PORT"] = str(backend_port)

    import uvicorn

    uvicorn.run(
        "server.app:app",
        host=INTERNAL_BACKEND_HOST,
        port=backend_port,
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
