from pathlib import Path

from utils.clean import disable_pycache

disable_pycache()

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from model import validate_provider_api_keys
from storage import Store

from .routes import artifacts, config, documents, projects, runs, secrets
from .services.run_manager import RunManager


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

run_manager = RunManager(BASE_DIR)
run_manager.recover_on_startup()

app = FastAPI(title="System API")
app.state.base_dir = BASE_DIR
app.state.run_manager = run_manager

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://plant.dummyjack.com",
        "http://plant.dummyjack.com",
    ],
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
