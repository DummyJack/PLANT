# Handles main logic for project flow orchestration and stage execution.
from typing import Any, Dict, List, Optional
import json
import os
import re
import shutil
from pathlib import Path

from utils import stage_enabled, export_enabled
from utils.cancel import raise_if_cancelled
from storage import markdown as markdown_storage
from storage.export import export_project_manual, should_export_html, should_export_manual
from flow.init_flow import emit_markdown_section_deltas


MOM_ROUND_FILE = re.compile(r"^R(\d+)-M\d+\.md$")


def _project_id_from_flow(flow) -> Optional[str]:
    return getattr(flow.store, "project_id", None)


def _check_flow_cancelled(flow) -> None:
    raise_if_cancelled(_project_id_from_flow(flow))


# ========
# Defines sync project output language function for this module workflow.
# ========
def sync_project_output_language(artifact: Dict[str, Any]) -> None:
    meta = artifact.setdefault("meta", {})
    explicit_lang = meta.get("output_language")
    lang = str(explicit_lang or os.environ.get("PLANT_OUTPUT_LANGUAGE") or "zh-Hant").strip() or "zh-Hant"
    if lang not in {"en", "zh-Hant"}:
        source = "artifact.meta.output_language" if explicit_lang else "PLANT_OUTPUT_LANGUAGE"
        raise ValueError(f"{source} 不合法: {lang}")
    os.environ["PLANT_OUTPUT_LANGUAGE"] = lang
    meta["output_language"] = lang


# ========
# Defines run meeting round function for this module workflow.
# ========
def run_meeting_round(flow, artifact: Dict[str, Any], round_num: int) -> Dict[str, Any]:
    return flow.meeting.run_meeting_round(artifact, round_num)


# ========
# Defines run one round function for this module workflow.
# ========
def run_one_round(
    flow,
    artifact: Dict[str, Any],
    round_num: int,
) -> Dict[str, Any]:
    flow.logger.stage_started("formal_meeting", "正式會議", message=f"第 {round_num} 輪正式會議開始")
    flow.logger.info(f"=== Round {round_num}: 開會 ===")
    flow.logger.step_started(
        "formal_meeting",
        f"formal_meeting.round_{round_num}.run_meeting",
        f"第 {round_num} 輪會議",
        agent="mediator",
        message="規劃中 ...",
    )
    artifact = flow.run_meeting_round(artifact, round_num)
    flow.store.save_artifact(artifact)
    flow.logger.step_completed(
        "formal_meeting",
        f"formal_meeting.round_{round_num}.run_meeting",
        f"第 {round_num} 輪會議",
        agent="mediator",
        message=f"第 {round_num} 輪會議完成",
    )
    flow.logger.info(f"Round {round_num} 完成")
    flow.logger.stage_completed("formal_meeting", "正式會議", message=f"第 {round_num} 輪正式會議完成")
    return artifact


# ========
# Defines require latest draft function for this module workflow.
# ========
def require_latest_draft(flow, stage_name: str) -> None:
    draft_version = flow.store.get_draft_version() if hasattr(flow.store, "get_draft_version") else -1
    if draft_version >= 0 and flow.store.load_draft(draft_version):
        return
    raise RuntimeError(
        f"stage.{stage_name} 缺少輸入；需要 artifact/drafts/draft_v0.md 或更新版本"
    )


# ========
# Defines require formal meeting inputs function for this module workflow.
# ========
def require_formal_meeting_inputs(artifact: Dict[str, Any]) -> None:
    requirements = artifact.get("URL")
    if isinstance(requirements, list) and requirements:
        return
    raise RuntimeError(
        "正式會議缺少輸入；需要 artifact/requirements.json 中的 requirements"
    )


# ========
# Defines require formal meeting stage inputs function for this module workflow.
# ========
def require_formal_meeting_stage_inputs(flow, artifact: Dict[str, Any]) -> None:
    require_formal_meeting_inputs(artifact)
    default_enabled = stage_enabled(flow.config, "default_formal_meeting", True)
    general_enabled = stage_enabled(flow.config, "general_formal_meeting", True)
    if general_enabled and not default_enabled:
        require_latest_draft(flow, "general_formal_meeting")


# ========
# Defines require srs draft inputs function for this module workflow.
# ========
def require_srs_draft_inputs(flow) -> None:
    require_latest_draft(flow, "SRS")


# ========
# Defines require DR draft inputs function for this module workflow.
# ========
def require_dr_draft_inputs(flow) -> None:
    require_latest_draft(flow, "DR")


# ========
# Defines formal meeting stage enabled function for this module workflow.
# ========
def formal_meeting_stage_enabled(config: Dict[str, Any]) -> bool:
    return (
        stage_enabled(config, "default_formal_meeting", True)
        or stage_enabled(config, "general_formal_meeting", True)
    )


# ========
# Defines general only meeting stage function for this module workflow.
# ========
def general_only_meeting_stage_enabled(config: Dict[str, Any]) -> bool:
    return (
        stage_enabled(config, "general_formal_meeting", True)
        and not stage_enabled(config, "default_formal_meeting", True)
    )


# ========
# Defines formal meeting end round function for this module workflow.
# ========
def formal_meeting_end_round(config: Dict[str, Any], *, start_round: int = 1) -> int:
    if not formal_meeting_stage_enabled(config):
        return 0
    general_rounds = int(config.get("rounds", 1) or 1)
    default_enabled = stage_enabled(config, "default_formal_meeting", True)
    general_enabled = stage_enabled(config, "general_formal_meeting", True)
    if int(start_round) > 1 and general_enabled:
        return int(start_round) + general_rounds - 1
    if default_enabled and general_enabled:
        return 1 + general_rounds
    if general_enabled and not default_enabled:
        return int(start_round) + general_rounds - 1
    return 1


# ========
# Defines next meeting round from mom function for this module workflow.
# ========
def next_meeting_round_from_mom(flow) -> int:
    completed_rounds = completed_meeting_rounds_from_mom(flow)
    return max(completed_rounds) + 1 if completed_rounds else 1


# ========
# Defines completed meeting rounds from mom function for this module workflow.
# ========
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


# ========
# Defines completed meeting rounds from issue state function for this module workflow.
# ========
def completed_meeting_rounds_from_issue_state(flow) -> set[int]:
    artifact_dir = getattr(flow.store, "artifact_dir", None)
    if artifact_dir is None:
        return set()
    issues_path = artifact_dir / "meeting" / "issues.json"
    if not issues_path.exists() or not issues_path.is_file():
        return set()
    try:
        data = json.loads(issues_path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    section = data.get("meeting_issues") if isinstance(data, dict) else []
    rows: List[Dict[str, Any]] = []
    if isinstance(section, dict):
        for key, values in section.items():
            try:
                section_round = int(str(key)[1:]) if str(key).startswith("r") else int(key)
            except (TypeError, ValueError):
                section_round = None
            for item in values if isinstance(values, list) else []:
                if not isinstance(item, dict):
                    continue
                row = dict(item)
                if section_round is not None:
                    row["round"] = section_round
                rows.append(row)
    elif isinstance(section, list):
        rows = [row for row in section if isinstance(row, dict)]
    else:
        return set()
    by_round: Dict[int, list[Dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            round_num = int(row.get("round") or 0)
        except (TypeError, ValueError):
            round_num = 0
        if round_num <= 0:
            continue
        by_round.setdefault(round_num, []).append(row)
    return {
        round_num
        for round_num, round_rows in by_round.items()
        if round_rows and all(bool(row.get("completed")) for row in round_rows)
    }


# ========
# Defines artifact file non empty function for this module workflow.
# ========
def artifact_file_non_empty(flow, *parts: str) -> bool:
    artifact_dir = getattr(flow.store, "artifact_dir", None)
    if artifact_dir is None:
        return False
    path = artifact_dir.joinpath(*parts)
    return path.exists() and path.is_file() and path.stat().st_size > 0


# ========
# Defines has completed formal meeting function for this module workflow.
# ========
def has_completed_formal_meeting(flow, artifact: Dict[str, Any], end_round: int) -> bool:
    meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
    try:
        last_round = int(meta.get("last_round") or 0)
    except (TypeError, ValueError):
        last_round = 0
    if last_round >= int(end_round):
        return True
    issue_rounds = completed_meeting_rounds_from_issue_state(flow)
    if issue_rounds:
        return all(round_num in issue_rounds for round_num in range(1, int(end_round) + 1))
    completed_rounds = completed_meeting_rounds_from_mom(flow)
    return all(round_num in completed_rounds for round_num in range(1, int(end_round) + 1))


# ========
# Defines has existing srs function for this module workflow.
# ========
def has_existing_srs(flow) -> bool:
    output_dir = getattr(flow.store, "output_dir", None)
    if output_dir is None:
        return False
    path = output_dir / "srs.md"
    return path.exists() and path.is_file() and path.stat().st_size > 0


# ========
# Defines has existing DR function for this module workflow.
# ========
def has_existing_dr(flow) -> bool:
    output_dir = getattr(flow.store, "output_dir", None)
    if output_dir is None:
        return False
    path = output_dir / "design_rationale.md"
    return path.exists() and path.is_file() and path.stat().st_size > 0


# ========
# Defines run specification stage function for this module workflow.
# ========
def run_specification_stage(flow, artifact: Dict[str, Any]) -> None:
    flow.logger.stage_started("document_generation", "規格化")
    flow.logger.info("=== 規格化 ===")
    if not stage_enabled(flow.config, "DR", stage_enabled(flow.config, "SRS")):
        flow.logger.info("跳過 DR")
    elif has_existing_dr(flow):
        require_dr_draft_inputs(flow)
        flow.logger.info("DR 已存在，不重新產生")
    else:
        require_dr_draft_inputs(flow)
        flow.generate_dr(artifact)
        flow.store.save_artifact(artifact)

    if not stage_enabled(flow.config, "SRS"):
        flow.logger.info("跳過 SRS")
    elif has_existing_srs(flow):
        require_srs_draft_inputs(flow)
        flow.logger.info("SRS 已存在，不重新產生")
    else:
        require_srs_draft_inputs(flow)
        flow.generate_srs(artifact)
        flow.store.save_artifact(artifact)
    flow.logger.stage_completed("document_generation", "規格化")


# ========
# Defines run update drafts without meeting function for this module workflow.
# ========
def run_update_drafts_without_meeting(flow, artifact: Dict[str, Any]) -> Dict[str, Any]:
    if not stage_enabled(flow.config, "default_update_draft", True):
        default_enabled = False
    else:
        default_enabled = True
    update_actions = []
    if default_enabled:
        update_actions.append(("default_update_draft", "default_draft_v", "Default Update Draft"))
    if stage_enabled(flow.config, "general_update_draft", True):
        update_actions.append(("general_update_draft", "general_draft_v", "General Update Draft"))
    if not update_actions:
        return artifact

    meta = artifact.setdefault("meta", {})
    flow.logger.stage_started("draft", "草稿更新")
    for action, meta_key, label in update_actions:
        latest_version = flow.store.get_draft_version()
        previous_draft = flow.store.load_draft(latest_version) if latest_version >= 0 else ""
        next_version = max(0, latest_version + 1)
        flow.logger.step_started(
            "draft",
            f"draft.{action}",
            "更新需求草稿",
            agent="analyst",
            message=f"{label}：正在更新需求草稿",
        )
        draft_md = flow.analyst_agent.run_requirements_analyst(
            "update_draft",
            artifact=artifact,
            draft_version=next_version,
            previous_draft=previous_draft,
            round_num=0,
            artifact_dir=getattr(flow.store, "artifact_dir", None),
        )
        flow.store.save_draft(draft_md, version=next_version)
        emit_markdown_section_deltas(
            flow,
            "draft",
            f"draft.{action}",
            draft_md,
            agent="analyst",
        )
        meta[meta_key] = next_version
        meta[f"{action}_without_meeting"] = True
        flow.store.save_artifact(artifact)
        flow.logger.step_completed(
            "draft",
            f"draft.{action}",
            f"Draft v{next_version}",
            agent="analyst",
            message=f"{label}：正式會議關閉，已更新需求草稿",
            output_path=f"results/drafts/draft_v{next_version}.html",
        )
        flow.logger.artifact_created(
            "draft",
            f"draft.{action}",
            f"Draft v{next_version}",
            f"results/drafts/draft_v{next_version}.html",
        )
    flow.logger.stage_completed("draft", "草稿更新")
    return artifact


# ========
# Defines run export html stage function for this module workflow.
# ========
def run_export_html_stage(flow, *, force: bool = False) -> None:
    if not force and not should_export_html(flow.config):
        flow.logger.info("跳過 HTML 匯出")
        return

    project_dir = flow.store.project_dir
    results_dir = project_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    html_count = 0
    model_count = 0

    for child in results_dir.glob("*"):
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)

    model_counter = {"count": 0}
    copy_model_assets(flow.store.artifact_dir, results_dir, counter_ref=model_counter)
    copy_model_assets(flow.store.output_dir, results_dir, counter_ref=model_counter)
    model_count = model_counter["count"]

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


def run_export_manual_stage(flow) -> None:
    if not should_export_manual(flow.config):
        flow.logger.info("跳過 Manual 匯出")
        return
    if not should_export_html(flow.config):
        flow.logger.info("Manual 匯出需要 HTML，已自動執行 HTML 匯出")
        run_export_html_stage(flow, force=True)
    manual_dir = export_project_manual(flow.store.project_dir)
    flow.logger.info("已輸出 Manual：%s", manual_dir.relative_to(flow.store.project_dir))



# ========
# Defines copy model assets function for this module workflow.
# ========
def copy_model_assets(source_root: Path, results_dir: Path, counter_ref: Optional[dict] = None) -> None:
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


# ========
# Defines save cost summary function for this module workflow.
# ========
def save_cost_summary(flow) -> None:
    if not export_enabled(flow.config, "cost", True):
        flow.logger.info("跳過成本統計")
        return

    cost_summary = flow.build_cost_summary()
    if cost_summary:
        flow.store.save_json(cost_summary, flow.store.project_dir / "cost_summary.json")
        flow.logger.info("已輸出成本統計：cost_summary.json")


# ========
# Defines run output stage function for this module workflow.
# ========
def run_output_stage(flow) -> None:
    flow.logger.stage_started("export", "輸出")
    flow.logger.info("=== 輸出 ===")
    html_enabled = should_export_html(flow.config)
    cost_enabled = export_enabled(flow.config, "cost", True)
    manual_enabled = should_export_manual(flow.config)

    if html_enabled:
        run_export_html_stage(flow)
    else:
        flow.logger.info("跳過 HTML 匯出")

    if cost_enabled:
        save_cost_summary(flow)
    else:
        flow.logger.info("跳過成本統計")

    if manual_enabled:
        run_export_manual_stage(flow)
    else:
        flow.logger.info("跳過 Manual 匯出")
    flow.logger.stage_completed("export", "輸出")


# ========
# Defines run project function for this module workflow.
# ========
def run_project(flow, rough_idea: str) -> Dict[str, Any]:
    run_formal = formal_meeting_stage_enabled(flow.config)
    end_round = formal_meeting_end_round(flow.config) if run_formal else 0
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
        artifact.setdefault("meta", {})["meeting_end_round"] = int(end_round)
    flow.store.save_artifact(artifact)

    flow.logger.stage_started("init", "初始階段")
    flow.logger.info("=== 初始階段 ===")
    _check_flow_cancelled(flow)
    artifact = flow.run_init_phase(artifact)
    flow.store.save_artifact(artifact)
    flow.logger.stage_completed("init", "初始階段")

    if not run_formal:
        flow.logger.stage_started("formal_meeting", "正式會議")
        flow.logger.info("=== 正式會議 ===")
        flow.logger.info("跳過正式會議")
        _check_flow_cancelled(flow)
        artifact = run_update_drafts_without_meeting(flow, artifact)
        flow.logger.stage_completed("formal_meeting", "正式會議", message="正式會議已跳過")
    elif has_completed_formal_meeting(flow, artifact, end_round):
        flow.logger.stage_started("formal_meeting", "正式會議")
        flow.logger.info("=== 正式會議 ===")
        flow.logger.info("✓ 正式會議輸出已存在，跳過重新開會")
        flow.logger.stage_completed("formal_meeting", "正式會議", message="正式會議輸出已存在")
    else:
        require_formal_meeting_stage_inputs(flow, artifact)
        for round_num in range(1, end_round + 1):
            _check_flow_cancelled(flow)
            artifact = run_one_round(flow, artifact, round_num)
        flow.store.save_artifact(artifact)

    _check_flow_cancelled(flow)
    run_specification_stage(flow, artifact)
    _check_flow_cancelled(flow)
    run_output_stage(flow)
    flow.logger.info("流程完成！")
    return artifact


# ========
# Defines run continue project function for this module workflow.
# ========
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

    flow.logger.stage_started("init", "初始階段")
    flow.logger.info("=== 初始階段 ===")
    _check_flow_cancelled(flow)
    artifact = flow.run_init_phase(artifact)
    flow.store.save_artifact(artifact)
    flow.logger.stage_completed("init", "初始階段")

    run_formal = formal_meeting_stage_enabled(flow.config)
    start_round = next_meeting_round_from_mom(flow)
    end_round = formal_meeting_end_round(flow.config, start_round=start_round) if run_formal else 0
    if run_formal:
        artifact.setdefault("meta", {})["meeting_end_round"] = end_round
        if start_round > end_round:
            flow.logger.info(f"已完成目標正式會議輪數：目前下一輪 Round {start_round}，目標至 Round {end_round}")
        else:
            flow.logger.info(f"繼續專案 Round {start_round}，目標至 Round {end_round}")

    if not run_formal:
        flow.logger.stage_started("formal_meeting", "正式會議")
        flow.logger.info("=== 正式會議 ===")
        flow.logger.info("跳過正式會議")
        _check_flow_cancelled(flow)
        artifact = run_update_drafts_without_meeting(flow, artifact)
        flow.logger.stage_completed("formal_meeting", "正式會議", message="正式會議已跳過")
    elif has_completed_formal_meeting(flow, artifact, end_round):
        flow.logger.stage_started("formal_meeting", "正式會議")
        flow.logger.info("=== 正式會議 ===")
        flow.logger.info("✓ 正式會議輸出已存在，跳過重新開會")
        flow.logger.stage_completed("formal_meeting", "正式會議", message="正式會議輸出已存在")
    elif start_round > end_round:
        flow.logger.stage_started("formal_meeting", "正式會議")
        flow.logger.info("=== 正式會議 ===")
        flow.logger.info("✓ 已完成目標正式會議輪數，跳過重新開會")
        flow.logger.stage_completed("formal_meeting", "正式會議", message="已完成目標正式會議輪數")
    else:
        require_formal_meeting_stage_inputs(flow, artifact)
        for round_num in range(start_round, end_round + 1):
            _check_flow_cancelled(flow)
            artifact = run_one_round(flow, artifact, round_num)
        flow.store.save_artifact(artifact)

    _check_flow_cancelled(flow)
    run_specification_stage(flow, artifact)
    _check_flow_cancelled(flow)
    run_output_stage(flow)
    flow.logger.info("流程完成！")
    return artifact
