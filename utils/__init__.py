"""Public utility exports loaded only when they are first requested."""

from __future__ import annotations

from importlib import import_module
from typing import Dict, Tuple


_EXPORTS: Dict[str, Tuple[str, str]] = {
    "Collect": ("utils.human", "Collect"),
    "CostTracker": ("utils.cost", "CostTracker"),
    "Logger": ("utils.log", "Logger"),
    "ProjectManager": ("utils.project_manager", "ProjectManager"),
    "ProjectSession": ("utils.project_manager", "ProjectSession"),
    "artifact_path_non_empty": ("utils.config", "artifact_path_non_empty"),
    "artifact_json_non_empty": ("utils.config", "artifact_json_non_empty"),
    "artifact_json_payload": ("utils.config", "artifact_json_payload"),
    "current_output_language": ("utils.language", "current_output_language"),
    "format_loaded_models_summary": ("utils.config", "format_loaded_models_summary"),
    "has_candidate_requirements": ("utils.config", "has_candidate_requirements"),
    "has_draft_payload": ("utils.config", "has_draft_payload"),
    "has_feedback_payload": ("utils.config", "has_feedback_payload"),
    "has_feedback_stage_result": ("utils.config", "has_feedback_stage_result"),
    "has_project_scope_requirements": ("utils.config", "has_project_scope_requirements"),
    "has_scope_payload": ("utils.config", "has_scope_payload"),
    "has_stakeholder_text": ("utils.config", "has_stakeholder_text"),
    "has_system_models_payload": ("utils.config", "has_system_models_payload"),
    "export_enabled": ("utils.config", "export_enabled"),
    "force_regenerate_output": ("utils.config", "force_regenerate_output"),
    "formal_meeting_enabled": ("utils.config", "formal_meeting_enabled"),
    "general_formal_meeting_enabled": ("utils.config", "general_formal_meeting_enabled"),
    "human_setting": ("utils.config", "human_setting"),
    "is_likely_english": ("utils.language", "is_likely_english"),
    "json_dump_no_scientific": ("storage", "json_dump_no_scientific"),
    "json_dumps_no_scientific": ("storage", "json_dumps_no_scientific"),
    "model_has_token_pricing": ("utils.cost", "model_has_token_pricing"),
    "meeting_setting": ("utils.config", "meeting_setting"),
    "output_language_directive": ("utils.language", "output_language_directive"),
    "output_language_context": ("utils.language", "output_language_context"),
    "require_stage_inputs": ("utils.config", "require_stage_inputs"),
    "stage_enabled": ("utils.config", "stage_enabled"),
    "set_output_language": ("utils.language", "set_output_language"),
    "sync_output_language": ("utils.language", "sync_output_language"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
