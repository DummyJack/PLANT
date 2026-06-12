from pathlib import Path
from typing import Any, Dict, List, Optional

from utils import stage_enabled


KNOWN_AGENTS = frozenset(
    {"user", "analyst", "expert", "mediator", "modeler", "documentor"}
)
ALWAYS_ENABLED_AGENTS = frozenset({"user", "mediator"})


def formal_meeting_enabled(config: Dict[str, Any]) -> bool:
    return stage_enabled(config, "default_formal_meeting", True) or stage_enabled(
        config, "general_formal_meeting", True
    )


def general_formal_meeting_enabled(config: Dict[str, Any]) -> bool:
    return stage_enabled(config, "general_formal_meeting", True)


def resolve_run_rounds(
    config: Dict[str, Any],
    rounds_override: Optional[int] = None,
) -> int:
    if rounds_override is not None:
        rounds = int(rounds_override)
        if rounds < 1:
            raise ValueError("rounds must be greater than 0")
        return rounds

    if general_formal_meeting_enabled(config):
        configured = config.get("rounds")
        if configured is None:
            raise ValueError(
                "rounds is required when general_formal_meeting is enabled"
            )
        rounds = int(configured)
        if rounds < 1:
            raise ValueError("config rounds must be greater than 0")
        return rounds

    if formal_meeting_enabled(config):
        return 1

    return 0


def apply_run_rounds(config: Dict[str, Any], rounds_override: Optional[int] = None) -> Dict[str, Any]:
    updated = dict(config)
    updated["rounds"] = resolve_run_rounds(config, rounds_override)
    return updated


def validate_stage_overrides(stage_overrides: Dict[str, Any]) -> None:
    if not isinstance(stage_overrides, dict):
        raise ValueError("stage_overrides must be an object")
    for key, value in stage_overrides.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("stage_overrides keys must be non-empty strings")
        if not isinstance(value, bool):
            raise ValueError(f"stage_overrides[{key!r}] must be a boolean")


def apply_run_stage_overrides(
    config: Dict[str, Any],
    stage_overrides: Optional[Dict[str, bool]] = None,
) -> Dict[str, Any]:
    updated = dict(config)
    if stage_overrides is None:
        return updated
    validate_stage_overrides(stage_overrides)
    stage = dict(updated.get("stage") or {})
    stage.update(stage_overrides)
    updated["stage"] = stage
    return updated


def validate_enable_agents(enable_agents: Dict[str, Any]) -> None:
    if not isinstance(enable_agents, dict):
        raise ValueError("enable_agents must be an object")
    unknown = set(enable_agents.keys()) - KNOWN_AGENTS
    if unknown:
        raise ValueError(f"Unknown agent(s): {', '.join(sorted(unknown))}")
    for key, value in enable_agents.items():
        if not isinstance(value, bool):
            raise ValueError(f"enable_agents[{key!r}] must be a boolean")


def normalize_attached_reference_paths(
    project_id: str,
    paths: Optional[List[str]],
) -> List[str]:
    if not paths:
        return []
    cleaned: List[str] = []
    seen: set[str] = set()
    for raw in paths:
        name = Path(str(raw or "").strip()).name
        if not name or name in seen:
            continue
        seen.add(name)
        cleaned.append(f"{project_id}/{name}")
    return cleaned


def apply_run_enable_agents(
    config: Dict[str, Any],
    enable_agents_override: Optional[Dict[str, bool]] = None,
) -> Dict[str, Any]:
    updated = dict(config)
    merged = dict(updated.get("enable_agents") or {})
    if enable_agents_override is not None:
        validate_enable_agents(enable_agents_override)
        merged.update(enable_agents_override)
    for agent in ALWAYS_ENABLED_AGENTS:
        merged[agent] = True
    updated["enable_agents"] = merged
    return updated
