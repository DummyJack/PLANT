import atexit
import os
from pathlib import Path

from utils.preflight import abort_startup, preflight_enabled, prepare_python_environment


BASE_DIR = Path(__file__).resolve().parents[1]
PREFLIGHT_ENABLED = preflight_enabled(BASE_DIR, "server")
prepare_python_environment(BASE_DIR, enabled=PREFLIGHT_ENABLED)

from dotenv import load_dotenv
from .services.backend_port import (
    configured_backend_port,
    first_available_backend_port,
    remove_backend_runtime,
    write_backend_runtime,
)
from .services.startup import run_backend_startup_checks


INTERNAL_BACKEND_HOST = "127.0.0.1"


def main() -> None:
    load_dotenv(BASE_DIR / ".env")
    try:
        if PREFLIGHT_ENABLED:
            run_backend_startup_checks(BASE_DIR)
        requested_port = configured_backend_port()
        backend_port = first_available_backend_port(
            INTERNAL_BACKEND_HOST,
            requested_port,
        )
        runtime_path = write_backend_runtime(
            BASE_DIR,
            INTERNAL_BACKEND_HOST,
            backend_port,
        )
    except RuntimeError as exc:
        abort_startup(exc)
    except OSError as exc:
        abort_startup(RuntimeError(f"無法寫入後端 runtime Port 資訊：{exc}"))
    atexit.register(remove_backend_runtime, runtime_path)
    if backend_port != requested_port:
        print(
            f"[WARN] 後端 Port {requested_port} 已被占用，已自動改用 {backend_port}",
            flush=True,
        )
    else:
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
