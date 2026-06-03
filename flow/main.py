# Project flow orchestration: run init, meeting rounds, and finalization.
from typing import Any, Dict, Optional
import os
import re
import shutil
from pathlib import Path

from utils import stage_enabled, export_enabled
from storage import markdown as markdown_storage


MOM_ROUND_FILE = re.compile(r"^R(\d+)-M\d+\.md$")


def sync_project_output_language(artifact: Dict[str, Any]) -> None:
    meta = artifact.setdefault("meta", {})
    explicit_lang = meta.get("output_language")
    lang = str(explicit_lang or os.environ.get("PLANT_OUTPUT_LANGUAGE") or "zh-Hant").strip() or "zh-Hant"
    if lang not in {"en", "zh-Hant"}:
        source = "artifact.meta.output_language" if explicit_lang else "PLANT_OUTPUT_LANGUAGE"
        raise ValueError(f"{source} 不合法: {lang}")
    os.environ["PLANT_OUTPUT_LANGUAGE"] = lang
    meta["output_language"] = lang


def run_meeting_round(flow, artifact: Dict[str, Any], round_num: int) -> Dict[str, Any]:
    return flow.meeting.run_meeting_round(artifact, round_num)


def run_one_round(
    flow,
    artifact: Dict[str, Any],
    round_num: int,
) -> Dict[str, Any]:
    flow.logger.info(f"=== Round {round_num}: 開會 ===")
    artifact = flow.run_meeting_round(artifact, round_num)
    flow.store.save_artifact(artifact)
    flow.logger.info(f"Round {round_num} 完成")
    return artifact


def require_latest_draft(flow, stage_name: str) -> None:
    draft_version = flow.store.get_draft_version() if hasattr(flow.store, "get_draft_version") else -1
    if draft_version >= 0 and flow.store.load_draft(draft_version):
        return
    raise RuntimeError(
        f"stage.{stage_name} 缺少輸入；需要 artifact/drafts/draft_v0.md 或更新版本"
    )


def require_formal_meeting_inputs(artifact: Dict[str, Any]) -> None:
    requirements = artifact.get("URL")
    if isinstance(requirements, list) and requirements:
        return
    raise RuntimeError(
        "正式會議缺少輸入；需要 artifact/requirements.json 中的 requirements"
    )


def require_formal_meeting_stage_inputs(flow, artifact: Dict[str, Any]) -> None:
    require_formal_meeting_inputs(artifact)
    default_enabled = stage_enabled(flow.config, "default_formal_meeting", True)
    general_enabled = stage_enabled(flow.config, "general_formal_meeting", True)
    if general_enabled and not default_enabled:
        require_latest_draft(flow, "general_formal_meeting")


def require_srs_draft_inputs(flow) -> None:
    require_latest_draft(flow, "SRS")


def formal_meeting_stage_enabled(config: Dict[str, Any]) -> bool:
    return (
        stage_enabled(config, "default_formal_meeting", True)
        or stage_enabled(config, "general_formal_meeting", True)
    )


def next_meeting_round_from_mom(flow) -> int:
    completed_rounds = completed_meeting_rounds_from_mom(flow)
    return max(completed_rounds) + 1 if completed_rounds else 1


def completed_meeting_rounds_from_mom(flow) -> set[int]:
    artifact_dir = getattr(flow.store, "artifact_dir", None)
    if artifact_dir is None:
        return set()
    mom_dir = artifact_dir / "MoM"
    if not mom_dir.exists() or not mom_dir.is_dir():
        return set()
    completed_rounds: set[int] = set()
    for path in mom_dir.glob("R*-M*.md"):
        match = MOM_ROUND_FILE.match(path.name)
        if not match:
            continue
        completed_rounds.add(int(match.group(1)))
    return completed_rounds


def _artifact_file_non_empty(flow, *parts: str) -> bool:
    artifact_dir = getattr(flow.store, "artifact_dir", None)
    if artifact_dir is None:
        return False
    path = artifact_dir.joinpath(*parts)
    return path.exists() and path.is_file() and path.stat().st_size > 0


def _has_completed_formal_meeting(flow, artifact: Dict[str, Any], end_round: int) -> bool:
    completed_rounds = completed_meeting_rounds_from_mom(flow)
    return all(round_num in completed_rounds for round_num in range(1, int(end_round) + 1))


def _has_existing_srs(flow) -> bool:
    return _artifact_file_non_empty(flow, "srs.md")


def run_update_drafts_without_meeting(flow, artifact: Dict[str, Any]) -> Dict[str, Any]:
    if not stage_enabled(flow.config, "default_update_draft", True):
        default_enabled = False
    else:
        default_enabled = True
    update_actions = []
    if default_enabled:
        update_actions.append(("default_update_draft", "latest_default_draft_version", "Default Update Draft"))
    if stage_enabled(flow.config, "general_update_draft", True):
        update_actions.append(("general_update_draft", "latest_general_draft_version", "General Update Draft"))
    if not update_actions:
        return artifact

    meta = artifact.setdefault("meta", {})
    for action, meta_key, label in update_actions:
        latest_version = flow.store.get_draft_version()
        previous_draft = flow.store.load_draft(latest_version) if latest_version >= 0 else ""
        next_version = max(0, latest_version + 1)
        draft_md = flow.analyst_agent.run_requirements_analyst(
            action,
            artifact=artifact,
            draft_version=next_version,
            previous_draft=previous_draft,
            round_num=0,
            artifact_dir=getattr(flow.store, "artifact_dir", None),
        )
        flow.store.save_draft(draft_md, version=next_version)
        meta[meta_key] = next_version
        meta[f"{action}_without_meeting"] = True
        flow.store.save_artifact(artifact)
        flow.logger.info("%s：正式會議關閉，已生成 draft_v%s", label, next_version)
    return artifact


def run_export_html_stage(flow) -> None:
    if not export_enabled(flow.config, "html", True):
        flow.logger.info("跳過 HTML 匯出")
        return

    project_dir = flow.store.project_dir
    results_dir = project_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    html_count = 0
    model_count = 0

    # 每次都重建結果目錄，確保輸出反映本次最新內容
    for child in results_dir.glob("*"):
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)

    # 先複製模型資源，避免 HTML 中引用的圖片在轉檔時還沒建立
    model_counter = {"count": 0}
    copy_model_assets(flow.store.artifact_dir, results_dir, counter_ref=model_counter)
    copy_model_assets(flow.store.output_dir, results_dir, counter_ref=model_counter)
    model_count = model_counter["count"]

    # 再轉換 Markdown 為 HTML
    artifact_root = flow.store.artifact_dir
    output_root = flow.store.output_dir
    source_roots = [artifact_root, output_root]

    for root in source_roots:
        if not root.exists():
            continue
        for md_path in sorted(root.rglob("*.md")):
            rel = md_path.relative_to(root)

            html_path = results_dir / rel
            html_path = html_path.with_suffix(".html")
            markdown_storage.save_markdown_as_html(md_path, html_path, results_dir)
            html_count += 1

    flow.logger.info("已轉成 html: results/*")



def copy_model_assets(source_root: Path, results_dir: Path, counter_ref: Optional[dict] = None) -> None:
    """Only copy model artifacts (models/* and images inside model folders) to results/models."""
    model_root = source_root / "models"
    if not model_root.exists() or not model_root.is_dir():
        return
    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
    for model_file in sorted(model_root.rglob("*")):
        if not model_file.is_file():
            continue
        if model_file.suffix.lower() not in image_exts:
            continue
        rel = model_file.relative_to(model_root)
        target = results_dir / "models" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(model_file, target)
        if counter_ref is not None and isinstance(counter_ref.get("count"), int):
            counter_ref["count"] += 1


def save_cost_summary(flow) -> None:
    if not export_enabled(flow.config, "cost", True):
        flow.logger.info("跳過成本統計")
        return

    cost_summary = flow.build_cost_summary()
    if cost_summary:
        flow.store.save_json(cost_summary, flow.store.project_dir / "cost_summary.json")
        flow.logger.info("已輸出成本統計：cost_summary.json")


def run_output_stage(flow) -> None:
    flow.logger.info("=== 輸出 ===")
    html_enabled = export_enabled(flow.config, "html", True)
    cost_enabled = export_enabled(flow.config, "cost", True)

    if html_enabled:
        run_export_html_stage(flow)
    else:
        flow.logger.info("跳過 HTML 匯出")

    if cost_enabled:
        save_cost_summary(flow)
    else:
        flow.logger.info("跳過成本統計")


def run_project(flow, rough_idea: str) -> Dict[str, Any]:
    run_formal = formal_meeting_stage_enabled(flow.config)
    rounds = int(flow.config.get("rounds", 1) or 1) if run_formal else 0
    artifact = {
        "rough_idea": rough_idea,
        "stakeholders": [],
        "scope": {"in_scope": [], "out_of_scope": []},
        "URL": [],
        "feedback": {},
        "system_models": [],
        "meta": {
            "last_round": 0,
        },
    }
    artifact = flow.ensure_artifact_contract(artifact)
    sync_project_output_language(artifact)
    flow.touch_artifact_meta(artifact, round_num=0)
    if run_formal:
        artifact.setdefault("meta", {})["meeting_end_round"] = int(rounds)
    flow.store.save_artifact(artifact)

    flow.logger.info("=== 初始階段 ===")
    artifact = flow.run_init_phase(artifact)
    flow.store.save_artifact(artifact)

    if not run_formal:
        flow.logger.info("=== 正式會議 ===")
        flow.logger.info("跳過正式會議")
        artifact = run_update_drafts_without_meeting(flow, artifact)
    elif _has_completed_formal_meeting(flow, artifact, rounds):
        flow.logger.info("=== 正式會議 ===")
        flow.logger.info("✓ 正式會議輸出已存在，跳過重新開會")
    else:
        require_formal_meeting_stage_inputs(flow, artifact)
        for round_num in range(1, rounds + 1):
            artifact = run_one_round(flow, artifact, round_num)
        flow.store.save_artifact(artifact)

    flow.logger.info("=== 規格化 ===")
    if not stage_enabled(flow.config, "SRS"):
        flow.logger.info("跳過 SRS")
    elif _has_existing_srs(flow):
        require_srs_draft_inputs(flow)
        flow.logger.info("SRS 已存在，不重新產生")
    else:
        require_srs_draft_inputs(flow)
        flow.finalize(artifact)
        flow.store.save_artifact(artifact)
    run_output_stage(flow)
    flow.logger.info("流程完成！")
    return artifact


def run_continue_project(flow, existing_artifact: Dict[str, Any]) -> Dict[str, Any]:
    artifact = existing_artifact
    artifact.setdefault(
        "scope", {"in_scope": [], "out_of_scope": []}
    )
    artifact.setdefault("feedback", {})
    artifact.setdefault("meta", {})
    artifact = flow.ensure_artifact_contract(artifact)
    sync_project_output_language(artifact)

    flow.user_agent.stakeholders = artifact.get("stakeholders", [])

    flow.logger.info("=== 初始階段 ===")
    artifact = flow.run_init_phase(artifact)
    flow.store.save_artifact(artifact)

    run_formal = formal_meeting_stage_enabled(flow.config)
    rounds = int(flow.config.get("rounds", 1) or 1) if run_formal else 0
    start_round = next_meeting_round_from_mom(flow)
    end_round = start_round + int(rounds) - 1
    if run_formal:
        artifact.setdefault("meta", {})["meeting_end_round"] = end_round
        flow.logger.info(f"繼續專案 Round {start_round}，共 {rounds} 輪")

    if not run_formal:
        flow.logger.info("=== 正式會議 ===")
        flow.logger.info("跳過正式會議")
        artifact = run_update_drafts_without_meeting(flow, artifact)
    elif _has_completed_formal_meeting(flow, artifact, end_round):
        flow.logger.info("=== 正式會議 ===")
        flow.logger.info("✓ 正式會議輸出已存在，跳過重新開會")
    else:
        require_formal_meeting_stage_inputs(flow, artifact)
        for round_num in range(start_round, start_round + rounds):
            artifact = run_one_round(flow, artifact, round_num)
        flow.store.save_artifact(artifact)

    flow.logger.info("=== 規格化 ===")
    if not stage_enabled(flow.config, "SRS"):
        flow.logger.info("跳過 SRS")
    elif _has_existing_srs(flow):
        require_srs_draft_inputs(flow)
        flow.logger.info("SRS 已存在，不重新產生")
    else:
        require_srs_draft_inputs(flow)
        flow.finalize(artifact)
        flow.store.save_artifact(artifact)
    run_output_stage(flow)
    flow.logger.info("流程完成！")
    return artifact
