from typing import Any, Dict, List

from model import validate_provider_api_keys


def validate_config(config: Any) -> Dict[str, Any]:
    errors: List[str] = []
    if not isinstance(config, dict):
        return {"valid": False, "errors": ["config must be an object"]}

    agent_models = config.get("agent_models")
    if agent_models is not None and not isinstance(agent_models, dict):
        errors.append("agent_models must be an object")

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
        except (TypeError, ValueError):
            errors.append("rounds must be an integer")

    max_issues = config.get("max_issues")
    if max_issues is not None:
        try:
            if int(max_issues) < 1:
                errors.append("max_issues must be greater than 0")
        except (TypeError, ValueError):
            errors.append("max_issues must be an integer")

    try:
        validate_provider_api_keys(config)
    except Exception as exc:
        errors.append(str(exc))

    return {"valid": not errors, "errors": errors}
