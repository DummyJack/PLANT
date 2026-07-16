from __future__ import annotations

from typing import Any, Dict

from .config import (
    has_candidate_requirements,
    has_feedback_stage_result,
    has_scope_payload,
    stage_enabled,
)


KNOWN_STAGES = frozenset(
    {
        "init",
        "elicitation",
        "conflict_detection",
        "research_domain",
        "system_model",
        "draft",
        "default_formal_meeting",
        "default_update_draft",
        "general_formal_meeting",
        "general_update_draft",
        "DR",
        "SRS",
    }
)


def validate_stage_overrides(stage_overrides: Dict[str, Any]) -> None:
    """Validate the shared stage configuration shape and supported names."""
    if not isinstance(stage_overrides, dict):
        raise ValueError("stage 必須是物件")
    for key, value in stage_overrides.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("stage 名稱必須是非空白字串")
        if not isinstance(value, bool):
            raise ValueError(f"stage[{key!r}] 必須是布林值")
    unknown = set(stage_overrides) - KNOWN_STAGES
    if unknown:
        raise ValueError(f"未知的 Stage：{', '.join(sorted(unknown))}")


def validate_stage_plan(
    config: Dict[str, Any],
    artifact: Dict[str, Any],
    store: Any,
    *,
    mode: str,
) -> None:
    """Validate stage dependencies before a run starts consuming resources."""
    if mode not in {"new", "continue"}:
        raise ValueError("mode must be new or continue")

    configured_stages = config.get("stage") if isinstance(config.get("stage"), dict) else {}
    validate_stage_overrides(configured_stages)

    meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
    base_ready = has_candidate_requirements(artifact) and has_scope_payload(artifact)
    feedback_ready = has_feedback_stage_result(artifact) and not bool(
        meta.get("research_domain_stale")
    )
    draft_version = store.get_draft_version() if hasattr(store, "get_draft_version") else -1
    draft_ready = bool(
        draft_version >= 0
        and store.load_draft(draft_version)
        and not bool(meta.get("draft_stale"))
    )

    init_enabled = stage_enabled(config, "init", True)
    research_enabled = stage_enabled(config, "research_domain", True)
    draft_enabled = stage_enabled(config, "draft", True)
    default_meeting = stage_enabled(config, "default_formal_meeting", True)
    general_meeting = stage_enabled(config, "general_formal_meeting", True)
    default_update = stage_enabled(config, "default_update_draft", True)
    general_update = stage_enabled(config, "general_update_draft", True)

    base_consumers = [
        name
        for name in (
            "elicitation",
            "conflict_detection",
            "research_domain",
            "system_model",
            "draft",
            "default_formal_meeting",
            "general_formal_meeting",
        )
        if stage_enabled(config, name, True)
    ]
    if base_consumers and not init_enabled and not base_ready:
        raise ValueError(
            "Stage dependency invalid: "
            f"{', '.join(base_consumers)} requires project scope and requirements; "
            "enable init or continue from a project with valid existing inputs"
        )

    if draft_enabled and not research_enabled and not feedback_ready:
        raise ValueError(
            "Stage dependency invalid: draft requires domain research feedback; "
            "enable research_domain or continue from a project with valid, non-stale feedback"
        )

    if not draft_enabled and ((default_meeting and default_update) or (general_meeting and general_update)):
        raise ValueError(
            "Stage dependency invalid: draft updates cannot be enabled when draft is disabled"
        )

    if general_meeting and not default_meeting and not draft_enabled and not draft_ready:
        raise ValueError(
            "Stage dependency invalid: general_formal_meeting without a default meeting "
            "requires an enabled draft stage or a valid existing draft"
        )

    document_stages = [name for name in ("DR", "SRS") if stage_enabled(config, name, True)]
    if document_stages and not draft_enabled and not draft_ready:
        raise ValueError(
            "Stage dependency invalid: "
            f"{', '.join(document_stages)} requires an enabled draft stage or a valid, non-stale existing draft"
        )
