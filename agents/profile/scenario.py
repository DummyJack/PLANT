# Scenario helpers for prompts: expose only the selected system name.
from typing import Any


def scenario_text(value: Any) -> str:
    return str(value or "").strip()


def scenario_prompt_value(value: Any) -> str:
    return scenario_text(value)
