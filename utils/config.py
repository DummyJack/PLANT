# Handles config logic for shared utility behavior for the Plant runtime.
import json
from typing import Any, Dict


# ========
# Defines format loaded models summary function for this module workflow.
# ========
def format_loaded_models_summary(config: dict) -> str:
    am = config.get("agent_models") or {}
    parts: list[str] = []
    for name, slot in am.items():
        if name == "default":
            continue
        if not isinstance(slot, dict):
            continue
        raw = slot.get("model")
        model_name = raw if (raw is not None and str(raw).strip() != "") else "—"
        parts.append(f"{name}: {model_name}")
    if not parts:
        return "✓ 載入配置（agent_models 無有效項目）"
    return "✓ 載入配置 — " + " | ".join(parts)


# ========
# Defines human setting function for this module workflow.
# ========
def human_setting(config: Dict[str, Any], key: str, default: Any) -> Any:
    block = config.get("human")
    if isinstance(block, dict) and key in block:
        return block[key]
    return config.get(key, default)


# ========
# Defines meeting setting function for this module workflow.
# ========
def meeting_setting(config: Dict[str, Any], key: str, default: Any) -> Any:
    block = config.get("enable_meeting")
    if isinstance(block, dict) and key in block:
        return block[key]
    return default


# ========
# Defines stage enabled function for this module workflow.
# ========
def stage_enabled(config: Dict[str, Any], name: str, default: bool = True) -> bool:
    stages = config.get("stage") if isinstance(config.get("stage"), dict) else {}
    value = stages.get(name, default)
    return bool(value)


# ========
# Defines export enabled function for this module workflow.
# ========
def export_enabled(config: Dict[str, Any], name: str, default: bool = True) -> bool:
    exports = config.get("export") if isinstance(config.get("export"), dict) else {}
    return bool(exports.get(name, default))


# ========
# Defines artifact path non empty function for this module workflow.
# ========
def artifact_path_non_empty(flow: Any, *parts: str) -> bool:
    artifact_dir = getattr(flow.store, "artifact_dir", None)
    if artifact_dir is None:
        return False
    path = artifact_dir.joinpath(*parts)
    return path.exists() and path.is_file() and path.stat().st_size > 0


# ========
# Defines artifact json payload function for this module workflow.
# ========
def artifact_json_payload(flow: Any, *parts: str) -> Any:
    artifact_dir = getattr(flow.store, "artifact_dir", None)
    if artifact_dir is None:
        return None
    path = artifact_dir.joinpath(*parts)
    if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


# ========
# Defines payload non empty function for this module workflow.
# ========
def payload_non_empty(payload: Any) -> bool:
    if payload is None:
        return False
    if isinstance(payload, dict):
        return any(payload_non_empty(value) for value in payload.values())
    if isinstance(payload, list):
        return any(payload_non_empty(value) for value in payload)
    if isinstance(payload, str):
        return bool(payload.strip())
    return True


# ========
# Defines artifact json non empty function for this module workflow.
# ========
def artifact_json_non_empty(flow: Any, *parts: str) -> bool:
    return payload_non_empty(artifact_json_payload(flow, *parts))


# ========
# Defines has draft payload function for this module workflow.
# ========
def has_draft_payload(flow: Any) -> bool:
    if not hasattr(flow.store, "get_draft_version") or not hasattr(flow.store, "load_draft"):
        return False
    draft_version = flow.store.get_draft_version()
    return draft_version >= 0 and bool(str(flow.store.load_draft(draft_version) or "").strip())


# ========
# Defines has candidate requirements function for this module workflow.
# ========
def has_candidate_requirements(artifact: Dict[str, Any]) -> bool:
    return bool(artifact.get("URL"))


# ========
# Defines has stakeholder text function for this module workflow.
# ========
def has_stakeholder_text(artifact: Dict[str, Any]) -> bool:
    for row in artifact.get("stakeholders", []) or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        text = row.get("text")
        if isinstance(text, list):
            has_text = any(str(item).strip() for item in text)
        else:
            has_text = bool(str(text or "").strip())
        if name and has_text:
            return True
    return False


# ========
# Defines has scope payload function for this module workflow.
# ========
def has_scope_payload(artifact: Dict[str, Any]) -> bool:
    scope = artifact.get("scope") if isinstance(artifact.get("scope"), dict) else {}
    return bool(scope.get("in_scope") or scope.get("out_of_scope"))


# ========
# Defines has feedback payload function for this module workflow.
# ========
def has_feedback_payload(artifact: Dict[str, Any]) -> bool:
    feedback = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
    if feedback.get("status") == "no_applicable_feedback":
        return True
    return any(
        bool(feedback.get(key))
        for key in ("findings", "sources", "constraints", "risks", "recommendations")
    )


# ========
# Defines has system models payload function for this module workflow.
# ========
def has_system_models_payload(artifact: Dict[str, Any]) -> bool:
    return bool([
        row for row in (artifact.get("system_models", []) or [])
        if isinstance(row, dict) and (row.get("name") or row.get("type") or row.get("text") or row.get("plantuml"))
    ])


# ========
# Defines has project scope requirements function for this module workflow.
# ========
def has_project_scope_requirements(flow: Any, artifact: Dict[str, Any]) -> bool:
    return (
        artifact_json_non_empty(flow, "project.json")
        and artifact_json_non_empty(flow, "scope.json")
        and artifact_json_non_empty(flow, "requirements.json")
        and has_scope_payload(artifact)
        and has_candidate_requirements(artifact)
    )


# ========
# Defines require stage inputs function for this module workflow.
# ========
def require_stage_inputs(flow: Any, artifact: Dict[str, Any], stage_name: str) -> None:
    if stage_name == "init":
        if (
            artifact.get("scenario")
            and has_stakeholder_text(artifact)
            and has_scope_payload(artifact)
            and has_candidate_requirements(artifact)
        ):
            return
        raise RuntimeError(
            "stage.init 缺少輸入；需要 artifact 內已有 scenario、stakeholders、scope 與 requirements"
        )
    if stage_name == "elicitation":
        if (
            has_project_scope_requirements(flow, artifact)
            and has_stakeholder_text(artifact)
        ):
            return
        raise RuntimeError(
            "stage.elicitation 缺少輸入；需要 artifact/project.json、artifact/scope.json、artifact/requirements.json，且 artifact 內已有 stakeholders 與 requirements"
        )
    if stage_name == "conflict_detection":
        if artifact_json_non_empty(flow, "requirements.json") and has_candidate_requirements(artifact):
            return
        raise RuntimeError(
            "stage.conflict_detection 缺少輸入；需要 artifact/requirements.json 且 artifact 內已有 requirements"
        )
    if stage_name == "research_domain":
        if has_project_scope_requirements(flow, artifact):
            return
        raise RuntimeError(
            "stage.research_domain 缺少輸入；需要 artifact/project.json、artifact/scope.json、artifact/requirements.json"
        )
    if stage_name == "system_model":
        if has_project_scope_requirements(flow, artifact):
            return
        raise RuntimeError(
            "stage.system_model 缺少輸入；需要 artifact/project.json、artifact/scope.json、artifact/requirements.json"
        )
    if stage_name == "draft":
        if (
            has_project_scope_requirements(flow, artifact)
            and artifact_json_non_empty(flow, "feedback.json")
            and artifact_json_non_empty(flow, "system_models.json")
            and has_feedback_payload(artifact)
            and has_system_models_payload(artifact)
        ):
            return
        raise RuntimeError(
            "stage.draft 缺少輸入；需要 artifact/project.json、artifact/scope.json、artifact/requirements.json、artifact/feedback.json、artifact/system_models.json"
        )
    if stage_name in {"DR", "SRS"}:
        if has_draft_payload(flow):
            return
        raise RuntimeError(
            f"stage.{stage_name} 缺少輸入；需要 artifact/drafts/draft_v0.md 或更新版本"
        )
