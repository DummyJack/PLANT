import os
import uuid
from pathlib import Path

from utils.preflight import abort_startup, preflight_enabled, prepare_python_environment


BASE_DIR = Path(__file__).resolve().parents[1]
PREFLIGHT_ENABLED = preflight_enabled(BASE_DIR, "server")
STARTUP_CHECK_REQUIRED = (
    PREFLIGHT_ENABLED and os.getenv("PLANT_BACKEND_STARTUP_CHECKED") != "1"
)
prepare_python_environment(BASE_DIR, enabled=STARTUP_CHECK_REQUIRED)

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from model import validate_provider_api_keys
from storage import Store
from .routes import artifacts, config, projects, runs, secrets
from .services.run_config import normalize_agent_models_to_valid_provider
from .services.run_manager import RunManager
from .services.startup import run_backend_startup_checks


load_dotenv(BASE_DIR / ".env")

if STARTUP_CHECK_REQUIRED:
    try:
        run_backend_startup_checks(BASE_DIR)
    except RuntimeError as exc:
        abort_startup(exc)
run_manager = RunManager(BASE_DIR)
run_manager.recover_on_startup()

app = FastAPI(
    title="System API",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.state.base_dir = BASE_DIR
app.state.run_manager = run_manager

BLOCKED_BROWSER_PATHS = {"/", "/api", "/docs", "/redoc", "/openapi.json"}


def is_browser_navigation(request: Request) -> bool:
    fetch_mode = request.headers.get("sec-fetch-mode", "").strip().lower()
    if fetch_mode == "navigate":
        return True
    accept = request.headers.get("accept", "").lower()
    return "text/html" in accept and "application/json" not in accept


def is_api_navigation_allowed(path: str) -> bool:
    parts = path.strip("/").split("/")
    if len(parts) < 5 or parts[0] != "api" or parts[1] != "projects":
        return False
    route = parts[3]
    if route == "references" and len(parts) >= 5:
        return True
    return False


def forbidden_page() -> HTMLResponse:
    return HTMLResponse(
        """
        <!doctype html>
        <html lang="en">
          <head>
            <meta charset="utf-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1" />
            <title>Forbidden (403)</title>
            <style>
              html, body { height: 100%; margin: 0; }
              body {
                display: grid;
                place-items: center;
                background: #fff;
                color: #020617;
                font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
              }
              main { transform: translateY(-2rem); text-align: center; }
              .logo {
                display: grid;
                place-items: center;
                width: 8rem;
                height: 8rem;
                margin: 0 auto;
                border-radius: 999px;
                background: #f1f5f9;
                box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
              }
              .mark {
                font-size: 2rem;
                font-weight: 800;
                letter-spacing: 0.02em;
              }
              h1 {
                margin: 3.5rem 0 0;
                font-size: 3rem;
                line-height: 1;
              }
              p {
                margin: 1.5rem 0 0;
                font-size: 1.25rem;
                line-height: 1.6;
                color: #1e293b;
              }
            </style>
          </head>
          <body>
            <main>
              <div class="logo" aria-hidden="true"><span class="mark">PLANT</span></div>
              <h1>Forbidden (403)</h1>
              <p>Sorry, you cannot access this page</p>
            </main>
          </body>
        </html>
        """,
        status_code=403,
    )


def frontend_origins() -> list[str]:
    frontend_host = os.getenv("frontend_host", "localhost").strip() or "localhost"
    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        f"https://{frontend_host}",
        f"http://{frontend_host}",
    ]


@app.middleware("http")
async def block_direct_backend_pages(request: Request, call_next):
    path = request.url.path
    if path in BLOCKED_BROWSER_PATHS or (
        path.startswith("/api/") and is_browser_navigation(request)
        and not is_api_navigation_allowed(path)
    ):
        return forbidden_page()
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router, prefix="/api")
app.include_router(projects.public_router)
app.include_router(config.router, prefix="/api")
app.include_router(artifacts.router, prefix="/api")
app.include_router(runs.router, prefix="/api")
app.include_router(secrets.router, prefix="/api/secrets")


@app.get("/api/health")
def health(request: Request):
    base_dir = request.app.state.base_dir
    projects_dir = base_dir / "projects"
    checks = {
        "status": "ok",
        "config": {"loaded": False, "error": None},
        "api_keys": {"valid": False, "error": None},
        "projects_dir": {"exists": projects_dir.exists(), "writable": False},
    }
    try:
        config = Store(base_dir).load_config()
        checks["config"]["loaded"] = True
        try:
            validate_provider_api_keys(normalize_agent_models_to_valid_provider(config))
            checks["api_keys"]["valid"] = True
        except Exception as exc:
            checks["api_keys"]["error"] = str(exc)
            checks["status"] = "degraded"
    except Exception as exc:
        checks["config"]["error"] = str(exc)
        checks["status"] = "degraded"

    projects_dir.mkdir(parents=True, exist_ok=True)
    probe = projects_dir / f".health_probe_{uuid.uuid4().hex}"
    try:
        probe.write_text("ok", encoding="utf-8")
        checks["projects_dir"]["writable"] = True
    except OSError as exc:
        checks["projects_dir"]["writable"] = False
        checks["status"] = "degraded"
        checks["projects_dir"]["error"] = str(exc)
    finally:
        probe.unlink(missing_ok=True)

    return checks


app.include_router(artifacts.public_router)
