from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
INTERNAL_BACKEND_HOST = "127.0.0.1"
INTERNAL_BACKEND_PORT = 8000


def main() -> None:
    load_dotenv(BASE_DIR / ".env")

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
