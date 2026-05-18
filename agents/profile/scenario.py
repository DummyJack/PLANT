# Scenario helpers for prompts: expose only the selected system name.
from typing import Any, Dict


def scenario_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or "").strip()
    return str(value or "").strip()


def scenario_prompt_value(value: Any) -> Dict[str, str]:
    return {"name": scenario_name(value)}
