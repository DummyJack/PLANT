from pathlib import Path
from typing import Any, Dict, List, Optional

from utils import stage_enabled


KNOWN_AGENTS = frozenset(
    {"user", "analyst", "expert", "mediator", "modeler", "documentor"}
)

PROVIDER_PRIORITY = ("openai", "gemini", "claude")
DEFAULT_PROVIDER_MODELS = {
    "openai": "gpt-5.5",
    "claude": "claude-opus-4-8",
    "gemini": "gemini-3.5-flash",
}
PROVIDER_MODEL_PREFIXES = {
    "openai": ("gpt-", "o1", "o3", "o4"),
    "claude": ("claude-",),
    "gemini": ("gemini-",),
}


def first_valid_api_provider(config: Dict[str, Any]) -> Optional[str]:
    state = config.get("api_state") if isinstance(config.get("api_state"), dict) else {}
    for provider in PROVIDER_PRIORITY:
        if state.get(provider) == "valid":
            return provider
    return None


def default_model_for_provider(config: Dict[str, Any], provider: str) -> str:
    return DEFAULT_PROVIDER_MODELS.get(provider, DEFAULT_PROVIDER_MODELS["openai"])


def model_matches_provider(provider: str, model: str) -> bool:
    normalized_provider = str(provider or "").strip().lower()
    normalized_model = str(model or "").strip().lower()
    if not normalized_model:
        return False
    own_prefixes = PROVIDER_MODEL_PREFIXES.get(normalized_provider)
    if own_prefixes and normalized_model.startswith(own_prefixes):
        return True
    for other_provider, prefixes in PROVIDER_MODEL_PREFIXES.items():
        if other_provider == normalized_provider:
            continue
        if normalized_model.startswith(prefixes):
            return False
    return True


def normalize_agent_models_to_valid_provider(config: Dict[str, Any]) -> Dict[str, Any]:
    default_provider = first_valid_api_provider(config)
    if not default_provider:
        raise ValueError("請先完成至少一個 API Key 測試")

    state = config.get("api_state") if isinstance(config.get("api_state"), dict) else {}
    updated = dict(config)
    agent_models = dict(updated.get("agent_models") or {})
    targets = set(KNOWN_AGENTS) | set(agent_models.keys()) | {"default"}
    fallback_model = default_model_for_provider(config, default_provider)

    for agent in targets:
        current = agent_models.get(agent)
        row = dict(current) if isinstance(current, dict) else {}
        provider = str(row.get("provider") or "").strip().lower()
        provider_valid = state.get(provider) == "valid"
        if not provider_valid:
            row["provider"] = default_provider
            row["model"] = fallback_model
        elif not model_matches_provider(provider, str(row.get("model") or "")):
            row["model"] = default_model_for_provider(config, provider)
        agent_models[agent] = row

    updated["agent_models"] = agent_models
    return updated


def required_agents_for_enabled_stages(config: Dict[str, Any]) -> set[str]:
    required: set[str] = set()
    if stage_enabled(config, "init", True):
        required.add("user")
    if stage_enabled(config, "elicitation", True):
        required.update({"user", "analyst", "mediator"})
    if stage_enabled(config, "conflict_detection", True):
        required.update({"analyst", "mediator"})
    if stage_enabled(config, "research_domain", True):
        required.add("expert")
    if stage_enabled(config, "system_model", True):
        required.add("modeler")
    if stage_enabled(config, "draft", True):
        required.add("analyst")
    if formal_meeting_enabled(config):
        required.update({"user", "analyst", "expert", "modeler", "mediator"})
    if stage_enabled(config, "DR", True) or stage_enabled(config, "SRS", True):
        required.add("documentor")
    return required


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


def apply_run_max_issues(
    config: Dict[str, Any],
    max_issues_override: Optional[int] = None,
) -> Dict[str, Any]:
    updated = dict(config)
    value = max_issues_override if max_issues_override is not None else updated.get("max_issues", 5)
    max_issues = int(value)
    if max_issues < 1:
        raise ValueError("max_issues must be greater than 0")
    updated["max_issues"] = max_issues
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
    for agent in required_agents_for_enabled_stages(updated):
        merged[agent] = True
    updated["enable_agents"] = merged
    return updated
