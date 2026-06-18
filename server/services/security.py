import re
from pathlib import Path
from typing import Any, Iterable

from fastapi import HTTPException


SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-\u4e00-\u9fff]")
MAX_EVENT_STRING_LENGTH = 8 * 1024
MAX_EVENT_JSON_LENGTH = 32 * 1024
ALLOWED_OUTPUT_ROOTS = {"artifact", "results", "output", "manual"}
SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization|bearer)\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
]
ABSOLUTE_PATH_PATTERN = re.compile(r"(?<![\w/])/(?:Users|home|var|tmp|private|etc)/[^\s\"'<>]+")
BLOCKED_EVENT_KEYS = {
    "system_prompt",
    "full_context",
    "raw_context",
    "raw_messages",
    "tool_args",
    "config_snapshot",
    "api_key",
    "secret",
    "password",
}


def sanitize_filename(name: str) -> str:
    cleaned = SAFE_NAME.sub("_", Path(name).name).strip("._")
    if not cleaned:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return cleaned


def validate_project_id(project_id: str) -> str:
    cleaned = str(project_id or "").strip()
    if (
        not cleaned
        or cleaned in {".", ".."}
        or "/" in cleaned
        or "\\" in cleaned
        or "\x00" in cleaned
    ):
        raise HTTPException(status_code=400, detail="Invalid project_id")
    return cleaned


def resolve_under(base_dir: Path, root: Path, relative_path: str) -> Path:
    if not relative_path or ".." in Path(relative_path).parts:
        raise HTTPException(status_code=400, detail="Invalid path")
    root_resolved = root.resolve()
    target = (root / relative_path).resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Path is not allowed") from exc
    try:
        target.relative_to(base_dir.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Path is outside workspace") from exc
    return target


def validate_project_relative_path(relative_path: str, *, allowed_roots: Iterable[str] = ALLOWED_OUTPUT_ROOTS) -> str:
    value = str(relative_path or "").strip().replace("\\", "/")
    if not value or value.startswith("/") or "\x00" in value:
        raise ValueError("Invalid path")
    path = Path(value)
    if ".." in path.parts:
        raise ValueError("Invalid path")
    allowed = set(allowed_roots)
    if path.parts and path.parts[0] not in allowed:
        raise ValueError("Path root is not allowed")
    return path.as_posix()


def resolve_project_file(base_dir: Path, project_root: Path, relative_path: str) -> Path:
    safe_path = validate_project_relative_path(relative_path)
    return resolve_under(base_dir, project_root, safe_path)


def redact_sensitive_text(value: str) -> str:
    text = ABSOLUTE_PATH_PATTERN.sub("[redacted-path]", value)
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(lambda m: f"{m.group(1)}=[redacted]" if m.groups() else "[redacted]", text)
    if len(text) > MAX_EVENT_STRING_LENGTH:
        text = text[:MAX_EVENT_STRING_LENGTH].rstrip() + "...[truncated]"
    return text


def sanitize_event_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, list):
        return [sanitize_event_value(item) for item in value[:100]]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in BLOCKED_EVENT_KEYS:
                out[key_text] = "[redacted]"
                continue
            out[key_text] = sanitize_event_value(item)
        return out
    return value


def sanitize_workspace_event(event: dict[str, Any]) -> dict[str, Any]:
    sanitized = sanitize_event_value(event)
    if not isinstance(sanitized, dict):
        return {}
    output_path = sanitized.get("output_path")
    if output_path:
        try:
            sanitized["output_path"] = validate_project_relative_path(str(output_path))
        except ValueError:
            sanitized.pop("output_path", None)
    try:
        import json

        encoded = json.dumps(sanitized, ensure_ascii=False)
        if len(encoded) > MAX_EVENT_JSON_LENGTH:
            content = sanitized.get("content")
            if isinstance(content, dict):
                sanitized["content"] = {
                    key: sanitize_event_value(str(value)[:1024])
                    for key, value in content.items()
                    if key in {"title", "heading", "id", "text", "body", "markdown", "content"}
                }
            elif isinstance(content, str):
                sanitized["content"] = content[:2048] + "...[truncated]"
    except Exception:
        pass
    return sanitized


def ensure_extension(path: Path, allowed: Iterable[str]) -> None:
    suffix = path.suffix.lower()
    if suffix not in set(allowed):
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")
