# Config helpers for model summaries and human settings.
import json
from typing import Any, Dict


def format_loaded_models_summary(config: dict) -> str:
    """僅依 config 內 agent_models 原樣列出；不顯示 default 槽位。"""
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


def human_setting(config: Dict[str, Any], key: str, default: Any) -> Any:
    """與人類互動／核准／挖掘流程相關設定。

    優先讀 config["human"][key]；若無則讀頂層同名鍵；再否則 default。
    """
    block = config.get("human")
    if isinstance(block, dict) and key in block:
        return block[key]
    return config.get(key, default)


def meeting_setting(config: Dict[str, Any], key: str, default: Any) -> Any:
    """讀取會議開關設定。

    優先讀 config["enable_meeting"][key]；若無則 default。
    """
    block = config.get("enable_meeting")
    if isinstance(block, dict) and key in block:
        return block[key]
    return default


def stage_enabled(config: Dict[str, Any], name: str, default: bool = True) -> bool:
    """讀取 stage 開關；true 表示執行，false 表示跳過。"""
    stages = config.get("stage") if isinstance(config.get("stage"), dict) else {}
    value = stages.get(name, default)
    return bool(value)


def export_enabled(config: Dict[str, Any], name: str, default: bool = True) -> bool:
    """讀取輸出匯出設定；預設讀取 config["export"][name]。"""
    exports = config.get("export") if isinstance(config.get("export"), dict) else {}

    # 提供舊欄位相容（html_export / cost_summary）。
    if name == "html" and "html_export" in config.get("stage", {}) and "html" not in exports:
        return bool(config["stage"].get("html_export", default))
    if name == "cost" and "cost_summary" in config.get("stage", {}) and "cost" not in exports:
        return bool(config["stage"].get("cost_summary", default))

    return bool(exports.get(name, default))


def artifact_path_non_empty(flow: Any, *parts: str) -> bool:
    artifact_dir = getattr(flow.store, "artifact_dir", None)
    if artifact_dir is None:
        return False
    path = artifact_dir.joinpath(*parts)
    return path.exists() and path.is_file() and path.stat().st_size > 0


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


def artifact_json_non_empty(flow: Any, *parts: str) -> bool:
    return payload_non_empty(artifact_json_payload(flow, *parts))


def has_draft_payload(flow: Any) -> bool:
    if not hasattr(flow.store, "get_draft_version") or not hasattr(flow.store, "load_draft"):
        return False
    draft_version = flow.store.get_draft_version()
    return draft_version >= 0 and bool(str(flow.store.load_draft(draft_version) or "").strip())


def has_candidate_requirements(artifact: Dict[str, Any]) -> bool:
    return bool(artifact.get("URL"))


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


def has_scope_payload(artifact: Dict[str, Any]) -> bool:
    scope = artifact.get("scope") if isinstance(artifact.get("scope"), dict) else {}
    return bool(scope.get("in_scope") or scope.get("out_of_scope"))


def has_feedback_payload(artifact: Dict[str, Any]) -> bool:
    feedback = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
    return any(
        bool(feedback.get(key))
        for key in ("findings", "sources", "constraints", "risks", "recommendations")
    )


def has_system_models_payload(artifact: Dict[str, Any]) -> bool:
    return bool([
        row for row in (artifact.get("system_models", []) or [])
        if isinstance(row, dict) and (row.get("name") or row.get("type") or row.get("text") or row.get("plantuml"))
    ])


def has_project_scope_requirements(flow: Any, artifact: Dict[str, Any]) -> bool:
    return (
        artifact_json_non_empty(flow, "project.json")
        and artifact_json_non_empty(flow, "scope.json")
        and artifact_json_non_empty(flow, "requirements.json")
        and has_scope_payload(artifact)
        and has_candidate_requirements(artifact)
    )


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
    if stage_name == "domain_research":
        if has_project_scope_requirements(flow, artifact):
            return
        raise RuntimeError(
            "stage.domain_research 缺少輸入；需要 artifact/project.json、artifact/scope.json、artifact/requirements.json"
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
    if stage_name == "SRS":
        if has_draft_payload(flow):
            return
        raise RuntimeError(
            "stage.SRS 缺少輸入；需要 artifact/drafts/draft_v0.md 或更新版本"
        )
