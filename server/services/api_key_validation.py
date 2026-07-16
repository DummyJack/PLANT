from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from dotenv import dotenv_values

from storage import Store
from storage.coordinator import FileRunCoordinator


MODEL_API_KEY_ENV: Dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
}

PROVIDER_DISPLAY_NAMES = {
    "openai": "OpenAI",
    "claude": "Claude",
    "gemini": "Gemini",
}


@dataclass(frozen=True)
class ApiKeyValidationResult:
    provider: str
    valid: bool
    error: Optional[str] = None


def configured_api_keys(base_dir: Path) -> Dict[str, str]:
    values = dotenv_values(Path(base_dir) / ".env")
    configured: Dict[str, str] = {}
    for provider, env_key in MODEL_API_KEY_ENV.items():
        file_value = values.get(env_key)
        api_key = str(os.getenv(env_key) or file_value or "").strip()
        if api_key:
            configured[provider] = api_key
    return configured


def test_provider_api_key(provider: str, api_key: str) -> Optional[str]:
    try:
        if provider == "openai":
            from openai import OpenAI

            client = OpenAI(api_key=api_key, timeout=10.0, max_retries=0)
            page = client.models.list()
            next(iter(getattr(page, "data", []) or []), None)
        elif provider == "claude":
            import anthropic

            client = anthropic.Anthropic(api_key=api_key, timeout=10.0, max_retries=0)
            page = client.models.list(limit=1)
            next(iter(getattr(page, "data", []) or []), None)
        elif provider == "gemini":
            from google import genai
            from google.genai import types

            client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=10_000),
            )
            iterator = client.models.list()
            next(iter(iterator), None)
        else:
            raise ValueError("Unsupported provider")
    except Exception as exc:
        message = str(getattr(exc, "message", "") or exc).strip()
        return message or exc.__class__.__name__
    return None


def validate_configured_api_keys(base_dir: Path) -> list[ApiKeyValidationResult]:
    results = []
    for provider, api_key in configured_api_keys(base_dir).items():
        error = test_provider_api_key(provider, api_key)
        results.append(
            ApiKeyValidationResult(
                provider=provider,
                valid=error is None,
                error=error,
            )
        )
    return results


def persist_api_key_validation_results(
    base_dir: Path,
    results: list[ApiKeyValidationResult],
) -> None:
    if not results:
        return
    coordinator = FileRunCoordinator(base_dir)
    with coordinator.exclusive_lock("config"):
        store = Store(base_dir)
        config = store.load_config()
        state = (
            dict(config.get("api_state") or {})
            if isinstance(config.get("api_state"), dict)
            else {}
        )
        for result in results:
            state[result.provider] = "valid" if result.valid else "invalid"
        config["api_state"] = state
        store.save_config(config)
