# Initializes the utils package and ensures the repo root is importable.
import sys
from pathlib import Path

from setup import apply_runtime_setup

apply_runtime_setup()

_repo_root = Path(__file__).resolve().parent.parent
_repo_root_str = str(_repo_root)
if _repo_root_str not in sys.path:
    sys.path.insert(0, _repo_root_str)

from storage import json_dump_no_scientific, json_dumps_no_scientific

from .config import (
    artifact_path_non_empty,
    artifact_json_non_empty,
    artifact_json_payload,
    format_loaded_models_summary,
    has_candidate_requirements,
    has_draft_payload,
    has_feedback_payload,
    has_project_scope_requirements,
    has_scope_payload,
    has_stakeholder_text,
    has_system_models_payload,
    human_setting,
    meeting_setting,
    require_stage_inputs,
    export_enabled,
    force_regenerate_output,
    stage_enabled,
)
from .cost import CostTracker, model_has_token_pricing
from .human import Collect
from .language import current_output_language, is_likely_english, sync_output_language
from .log import Logger
from .project_manager import ProjectManager, ProjectSession

__all__ = [
    "Collect",
    "CostTracker",
    "Logger",
    "ProjectManager",
    "ProjectSession",
    "artifact_path_non_empty",
    "artifact_json_non_empty",
    "artifact_json_payload",
    "current_output_language",
    "format_loaded_models_summary",
    "has_candidate_requirements",
    "has_draft_payload",
    "has_feedback_payload",
    "has_project_scope_requirements",
    "has_scope_payload",
    "has_stakeholder_text",
    "has_system_models_payload",
    "export_enabled",
    "force_regenerate_output",
    "human_setting",
    "is_likely_english",
    "json_dump_no_scientific",
    "json_dumps_no_scientific",
    "model_has_token_pricing",
    "meeting_setting",
    "require_stage_inputs",
    "stage_enabled",
    "sync_output_language",
]
