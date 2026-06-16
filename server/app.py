import os
from pathlib import Path

from setup import apply_runtime_setup

apply_runtime_setup()

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from model import validate_provider_api_keys
from storage import Store

from .routes import artifacts, config, documents, projects, runs, secrets
from .services.run_manager import RunManager


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

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


def use_localhost(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def frontend_origins() -> list[str]:
    if use_localhost("devlop_frontend", True):
        return [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    return [
        "https://plant.dummyjack.com",
        "http://plant.dummyjack.com",
    ]


@app.middleware("http")
async def block_direct_backend_pages(request: Request, call_next):
    if request.url.path in BLOCKED_BROWSER_PATHS:
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
app.include_router(config.router, prefix="/api")
app.include_router(artifacts.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
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
            validate_provider_api_keys(config)
            checks["api_keys"]["valid"] = True
        except Exception as exc:
            checks["api_keys"]["error"] = str(exc)
            checks["status"] = "degraded"
    except Exception as exc:
        checks["config"]["error"] = str(exc)
        checks["status"] = "degraded"

    projects_dir.mkdir(parents=True, exist_ok=True)
    probe = projects_dir / ".health_probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        checks["projects_dir"]["writable"] = True
    except OSError as exc:
        checks["projects_dir"]["writable"] = False
        checks["status"] = "degraded"
        checks["projects_dir"]["error"] = str(exc)

    return checks
