from typing import Any, Dict, List

from model import validate_provider_api_keys
from server.services.run_config import MAX_RUN_ISSUES, MAX_RUN_ROUNDS, normalize_agent_models_to_valid_provider


def validate_config(config: Any) -> Dict[str, Any]:
    errors: List[str] = []
    if not isinstance(config, dict):
        return {"valid": False, "errors": ["config must be an object"]}

    agent_models = config.get("agent_models")
    if agent_models is not None and not isinstance(agent_models, dict):
        errors.append("agent_models must be an object")

    preflight = config.get("preflight")
    if preflight is not None:
        if not isinstance(preflight, dict):
            errors.append("preflight must be an object")
        else:
            unknown = set(preflight) - {"system", "server"}
            if unknown:
                errors.append(f"unknown preflight option(s): {', '.join(sorted(unknown))}")
            for name in ("system", "server"):
                if name in preflight and not isinstance(preflight[name], bool):
                    errors.append(f"preflight.{name} must be a boolean")

    stage = config.get("stage")
    if stage is not None and not isinstance(stage, dict):
        errors.append("stage must be an object")

    export = config.get("export")
    if export is not None and not isinstance(export, dict):
        errors.append("export must be an object")

    enable_agents = config.get("enable_agents")
    if enable_agents is not None and not isinstance(enable_agents, dict):
        errors.append("enable_agents must be an object")

    rounds = config.get("rounds")
    if rounds is not None:
        try:
            if int(rounds) < 0:
                errors.append("rounds must be greater than or equal to 0")
            elif int(rounds) > MAX_RUN_ROUNDS:
                errors.append(f"rounds must be less than or equal to {MAX_RUN_ROUNDS}")
        except (TypeError, ValueError):
            errors.append("rounds must be an integer")

    max_issues = config.get("max_issues")
    if max_issues is not None:
        try:
            if int(max_issues) < 1:
                errors.append("max_issues must be greater than 0")
            elif int(max_issues) > MAX_RUN_ISSUES:
                errors.append(f"max_issues must be less than or equal to {MAX_RUN_ISSUES}")
        except (TypeError, ValueError):
            errors.append("max_issues must be an integer")

    try:
        validate_provider_api_keys(normalize_agent_models_to_valid_provider(config))
    except Exception as exc:
        errors.append(str(exc))

    return {"valid": not errors, "errors": errors}
