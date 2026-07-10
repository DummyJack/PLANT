# Handles main logic for project flow orchestration and stage execution.
from typing import Any, Dict, List, Optional
import json
import os
import re
import shutil
from pathlib import Path

from utils import stage_enabled, export_enabled, force_regenerate_output
from utils.cancel import raise_if_cancelled
from storage import markdown as markdown_storage
from storage.export import export_project_manual, should_export_html, should_export_manual
from flow.init_flow import emit_markdown_section_deltas
from server.services.run_checkpoint import record_run_checkpoint


MOM_ROUND_FILE = re.compile(r"^R(\d+)-M\d+\.md$")


def _project_id_from_flow(flow) -> Optional[str]:
    return getattr(flow.store, "project_id", None)


def _check_flow_cancelled(flow) -> None:
    raise_if_cancelled(_project_id_from_flow(flow))


def sync_agent_runtime(flow) -> None:
    run_id = str(getattr(flow, "run_id", "") or "")
    for attr in (
        "user_agent",
        "analyst_agent",
        "expert_agent",
        "mediator_agent",
        "modeler_agent",
        "documentor_agent",
    ):
        agent = getattr(flow, attr, None)
        if agent is None:
            continue
        agent.runtime_store = flow.store
        agent.runtime_run_id = run_id


def _checkpoint_step(
    flow,
    *,
    stage_id: str,
    step_id: str,
    round_num: int | None = None,
    agent: str = "",
    action: str = "",
) -> None:
    run_id = str(getattr(flow, "run_id", "") or "")
    if not run_id:
        return
    record_run_checkpoint(
        flow.store,
        run_id=run_id,
        status="running",
        stage_id=stage_id,
        step_id=step_id,
        round_num=round_num,
        agent=agent,
        action=action,
    )


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
    _checkpoint_step(
        flow,
        stage_id="formal_meeting",
        step_id=f"formal_meeting.round_{round_num}.run_meeting",
        round_num=round_num,
        agent="mediator",
        action="run_meeting",
    )
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
# Defines checkpoint meeting round function for this module workflow.
# ========
def checkpoint_meeting_round(meta: Dict[str, Any]) -> Optional[int]:
    for key in ("run_checkpoint", "last_resume_checkpoint"):
        checkpoint = meta.get(key)
        if not isinstance(checkpoint, dict):
            continue
        stage_id = str(checkpoint.get("stage_id") or "").strip()
        if stage_id not in {"formal_meeting", "meeting_issue_proposal_review"}:
            continue
        try:
            round_num = int(checkpoint.get("round") or 0)
        except (TypeError, ValueError):
            round_num = 0
        if round_num > 0:
            return round_num
    return None


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
    section = data.get("meeting_issues") if isinstance(data, dict) else {}
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
# Defines completed formal meeting rounds function for this module workflow.
# ========
def completed_formal_meeting_rounds(flow) -> set[int]:
    return completed_meeting_rounds_from_issue_state(flow) | completed_meeting_rounds_from_mom(flow)


# ========
# Defines formal meeting draft update plan function for this module workflow.
# ========
def formal_meeting_draft_update_plan(flow, completed_rounds: set[int]) -> List[Dict[str, Any]]:
    default_enabled = stage_enabled(flow.config, "default_formal_meeting", True)
    general_enabled = stage_enabled(flow.config, "general_formal_meeting", True)
    updates: List[Dict[str, Any]] = []
    if (
        default_enabled
        and stage_enabled(flow.config, "default_update_draft", True)
        and 1 in completed_rounds
    ):
        updates.append({
            "action": "default_update_draft",
            "meta_key": "default_draft_v",
            "round": 1,
            "label": "Default Update Draft",
        })
    if general_enabled and stage_enabled(flow.config, "general_update_draft", True):
        general_rounds = sorted(
            round_num for round_num in completed_rounds
            if round_num >= (2 if default_enabled else 1)
        )
        for round_num in general_rounds:
            updates.append({
                "action": "general_update_draft",
                "meta_key": f"general_draft_v_r{round_num}",
                "round": round_num,
                "label": f"General Update Draft R{round_num}",
            })
    return updates


# ========
# Defines ensure formal meeting draft updates function for this module workflow.
# ========
def ensure_formal_meeting_draft_updates(
    flow,
    artifact: Dict[str, Any],
    *,
    completed_rounds: Optional[set[int]] = None,
) -> Dict[str, Any]:
    if not formal_meeting_stage_enabled(flow.config):
        return artifact
    rounds = completed_rounds if completed_rounds is not None else completed_formal_meeting_rounds(flow)
    if not rounds:
        return artifact
    update_plan = formal_meeting_draft_update_plan(flow, rounds)
    if not update_plan:
        return artifact

    latest_version = flow.store.get_draft_version()
    if latest_version >= len(update_plan):
        return artifact
    if latest_version < 0:
        require_latest_draft(flow, "formal_meeting_draft_update")

    meta = artifact.setdefault("meta", {})
    flow.logger.stage_started("draft", "草稿更新")
    for index, update in enumerate(update_plan, 1):
        latest_version = flow.store.get_draft_version()
        if latest_version >= index:
            continue
        previous_draft = flow.store.load_draft(latest_version) if latest_version >= 0 else ""
        next_version = max(0, latest_version + 1)
        action = str(update["action"])
        label = str(update["label"])
        round_num = int(update["round"])
        flow.logger.step_started(
            "draft",
            f"draft.{action}",
            "更新需求草稿",
            agent="analyst",
            message=f"{label}：補齊會議後需求草稿",
        )
        draft_md = flow.analyst_agent.run_requirements_analyst(
            "update_draft",
            artifact=artifact,
            draft_version=next_version,
            previous_draft=previous_draft,
            round_num=round_num,
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
        meta[str(update["meta_key"])] = next_version
        if action == "default_update_draft":
            meta["default_draft_v"] = next_version
            meta[f"default_update_draft_round_{round_num}"] = True
        else:
            meta["general_draft_v"] = next_version
            meta[f"general_update_draft_round_{round_num}"] = True
        flow.store.save_artifact(artifact)
        flow.logger.step_completed(
            "draft",
            f"draft.{action}",
            f"Draft v{next_version}",
            agent="analyst",
            message=f"{label}：已補齊會議後需求草稿",
            output_path=f"artifact/drafts/draft_v{next_version}.md",
        )
        flow.logger.artifact_created(
            "draft",
            f"draft.{action}",
            f"Draft v{next_version} 已產生",
            f"artifact/drafts/draft_v{next_version}.md",
        )
    flow.logger.stage_completed("draft", "草稿更新")
    return artifact


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
def run_specification_stage(
    flow,
    artifact: Dict[str, Any],
    *,
    force_regenerate: bool = False,
) -> None:
    flow.logger.stage_started("document_generation", "規格化")
    flow.logger.info("=== 規格化 ===")
    force_dr = force_regenerate or force_regenerate_output(flow.config, "DR")
    force_srs = force_regenerate or force_regenerate_output(flow.config, "SRS")
    if not stage_enabled(flow.config, "DR", stage_enabled(flow.config, "SRS")):
        flow.logger.info("跳過設計緣由")
    elif has_existing_dr(flow) and not force_dr:
        require_dr_draft_inputs(flow)
        flow.logger.info("設計緣由已存在，不重新產生")
    else:
        require_dr_draft_inputs(flow)
        if force_dr and has_existing_dr(flow):
            flow.logger.info("已要求重新產生設計緣由")
        _checkpoint_step(
            flow,
            stage_id="document_generation",
            step_id="document_generation.generate_dr",
            agent="documentor",
            action="generate_dr",
        )
        flow.generate_dr(artifact)
        flow.store.save_artifact(artifact)

    if not stage_enabled(flow.config, "SRS"):
        flow.logger.info("跳過規格化")
    elif has_existing_srs(flow) and not force_srs:
        require_srs_draft_inputs(flow)
        flow.logger.info("規格化已存在，不重新產生")
    else:
        require_srs_draft_inputs(flow)
        if force_srs and has_existing_srs(flow):
            flow.logger.info("已要求重新產生規格化")
        _checkpoint_step(
            flow,
            stage_id="document_generation",
            step_id="document_generation.generate_srs",
            agent="documentor",
            action="generate_srs",
        )
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
            output_path=f"artifact/drafts/draft_v{next_version}.md",
        )
        flow.logger.artifact_created(
            "draft",
            f"draft.{action}",
            f"Draft v{next_version}",
            f"artifact/drafts/draft_v{next_version}.md",
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

    for child in results_dir.glob("*"):
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)

    model_counter = {"count": 0}
    copy_model_assets(flow.store.artifact_dir, results_dir, counter_ref=model_counter)
    copy_model_assets(flow.store.output_dir, results_dir, counter_ref=model_counter)

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
            markdown_storage.save_markdown_as_html(
                md_path,
                html_path,
                results_dir,
                project_id=flow.store.project_id,
            )

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
def cost_summary_has_usage(cost_summary: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(cost_summary, dict):
        return False
    totals = cost_summary.get("totals")
    if not isinstance(totals, dict):
        return False
    return bool(
        int(totals.get("total_tokens", 0) or 0) > 0
        or float(totals.get("estimated_cost(USD)", 0.0) or 0.0) > 0
    )


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _int_sum(a: Any, b: Any) -> int:
    return int(round(_num(a) + _num(b)))


def _float_sum(a: Any, b: Any, *, digits: int = 8) -> float:
    return round(_num(a) + _num(b), digits)


def _merge_cost_row(existing: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(existing or {})
    current = dict(current or {})
    if current.get("model"):
        previous_model = str(merged.get("model") or "").strip()
        current_model = str(current.get("model") or "").strip()
        if previous_model and previous_model != current_model:
            models = [
                item.strip()
                for item in previous_model.split(" + ")
                if item.strip()
            ]
            if current_model not in models:
                models.append(current_model)
            merged["model"] = " + ".join(models)
        else:
            merged["model"] = current_model
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        merged[key] = _int_sum(merged.get(key), current.get(key))
    merged["run_time(s)"] = _float_sum(merged.get("run_time(s)"), current.get("run_time(s)"), digits=3)
    merged["estimated_cost(USD)"] = _float_sum(
        merged.get("estimated_cost(USD)", merged.get("estimated_cost")),
        current.get("estimated_cost(USD)", current.get("estimated_cost")),
        digits=8,
    )
    return merged


def merge_cost_summaries(existing: Dict[str, Any], current: Dict[str, Any], *, run_id: str) -> Dict[str, Any]:
    existing = dict(existing or {})
    current = dict(current or {})
    existing_run_ids = [
        str(item).strip()
        for item in (existing.get("_run_ids") or [])
        if str(item).strip()
    ]
    if run_id and run_id in existing_run_ids:
        return existing

    existing_agents = existing.get("agents") if isinstance(existing.get("agents"), dict) else {}
    current_agents = current.get("agents") if isinstance(current.get("agents"), dict) else {}
    merged_agents: Dict[str, Any] = {
        str(agent): dict(row)
        for agent, row in existing_agents.items()
        if isinstance(row, dict)
    }
    for agent, row in current_agents.items():
        if not isinstance(row, dict):
            continue
        key = str(agent)
        merged_agents[key] = _merge_cost_row(
            merged_agents.get(key, {}),
            row,
        )

    merged_totals = _merge_cost_row(
        existing.get("totals") if isinstance(existing.get("totals"), dict) else {},
        current.get("totals") if isinstance(current.get("totals"), dict) else {},
    )
    merged = {
        **existing,
        "project_id": current.get("project_id") or existing.get("project_id"),
        "agents": merged_agents,
        "totals": merged_totals,
    }
    if run_id:
        merged["_run_ids"] = [*existing_run_ids, run_id]
    return merged


def save_cost_summary(flow) -> None:
    if not export_enabled(flow.config, "cost", True):
        flow.logger.info("跳過成本統計")
        return

    cost_summary = flow.build_cost_summary()
    if cost_summary:
        cost_path = flow.store.project_dir / "cost_summary.json"
        existing = None
        if cost_path.exists():
            try:
                existing = json.loads(cost_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = None
        if not cost_summary_has_usage(cost_summary) and cost_path.exists():
            if cost_summary_has_usage(existing):
                flow.logger.info("成本統計無新 usage，保留既有 cost_summary.json")
                return
        run_mode = str(getattr(flow, "run_mode", "") or "").strip()
        run_id = str(getattr(flow, "run_id", "") or "").strip()
        if run_mode == "continue" and cost_summary_has_usage(existing):
            cost_summary = merge_cost_summaries(
                existing,
                cost_summary,
                run_id=run_id,
            )
        flow.store.save_json(cost_summary, cost_path)
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
    sync_agent_runtime(flow)
    run_formal = formal_meeting_stage_enabled(flow.config)
    general_enabled = stage_enabled(flow.config, "general_formal_meeting", True)
    default_enabled = stage_enabled(flow.config, "default_formal_meeting", True)
    end_round = formal_meeting_end_round(flow.config) if run_formal else 0
    ran_general_meeting_this_run = False
    draft_version_before_formal = flow.store.get_draft_version()
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
            if general_enabled and (round_num > 1 or not default_enabled):
                ran_general_meeting_this_run = True
        flow.store.save_artifact(artifact)

    _check_flow_cancelled(flow)
    artifact = ensure_formal_meeting_draft_updates(flow, artifact)
    _check_flow_cancelled(flow)
    draft_version_after_formal = flow.store.get_draft_version()
    generated_new_draft_this_run = draft_version_after_formal > draft_version_before_formal
    if ran_general_meeting_this_run and generated_new_draft_this_run:
        artifact.setdefault("meta", {})["general_meeting_ran_this_run"] = True
        flow.store.save_artifact(artifact)
    run_specification_stage(
        flow,
        artifact,
        force_regenerate=generated_new_draft_this_run,
    )
    _check_flow_cancelled(flow)
    run_output_stage(flow)
    flow.logger.info("流程完成！")
    return artifact


# ========
# Defines run continue project function for this module workflow.
# ========
def run_continue_project(flow, existing_artifact: Dict[str, Any]) -> Dict[str, Any]:
    sync_agent_runtime(flow)
    artifact = existing_artifact
    artifact.setdefault(
        "scope", {"in_scope": [], "out_of_scope": []}
    )
    artifact.setdefault("feedback", {})
    artifact.setdefault("meta", {})
    artifact = flow.ensure_artifact_contract(artifact)
    sync_project_output_language(artifact)

    flow.user_agent.stakeholders = artifact.get("stakeholders", [])
    meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
    resume_checkpoint = (
        meta.get("last_resume_checkpoint")
        if isinstance(meta.get("last_resume_checkpoint"), dict)
        else {}
    )
    resume_stage = str(resume_checkpoint.get("stage_id") or "").strip()
    skip_init_for_resume = resume_stage in {
        "formal_meeting",
        "meeting_issue_proposal_review",
        "document_generation",
        "export",
    }

    if skip_init_for_resume:
        flow.logger.stage_started("init", "初始階段")
        flow.logger.info("=== 初始階段 ===")
        flow.logger.info("依 checkpoint 從 %s 繼續，略過初始化階段", resume_stage)
        flow.logger.stage_completed("init", "初始階段", message="依 checkpoint 略過初始化階段")
    else:
        flow.logger.stage_started("init", "初始階段")
        flow.logger.info("=== 初始階段 ===")
        _check_flow_cancelled(flow)
        artifact = flow.run_init_phase(artifact)
        flow.store.save_artifact(artifact)
        flow.logger.stage_completed("init", "初始階段")

    run_formal = formal_meeting_stage_enabled(flow.config)
    general_enabled = stage_enabled(flow.config, "general_formal_meeting", True)
    default_enabled = stage_enabled(flow.config, "default_formal_meeting", True)
    checkpoint_round = checkpoint_meeting_round(meta)
    start_round = checkpoint_round if checkpoint_round is not None else next_meeting_round_from_mom(flow)
    end_round = formal_meeting_end_round(flow.config, start_round=start_round) if run_formal else 0
    ran_general_meeting_this_run = False
    draft_version_before_formal = flow.store.get_draft_version()
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
            if general_enabled and (round_num > 1 or not default_enabled):
                ran_general_meeting_this_run = True
        flow.store.save_artifact(artifact)

    _check_flow_cancelled(flow)
    artifact = ensure_formal_meeting_draft_updates(flow, artifact)
    _check_flow_cancelled(flow)
    draft_version_after_formal = flow.store.get_draft_version()
    generated_new_draft_this_run = draft_version_after_formal > draft_version_before_formal
    if ran_general_meeting_this_run and generated_new_draft_this_run:
        artifact.setdefault("meta", {})["general_meeting_ran_this_run"] = True
        flow.store.save_artifact(artifact)
    run_specification_stage(
        flow,
        artifact,
        force_regenerate=generated_new_draft_this_run,
    )
    _check_flow_cancelled(flow)
    run_output_stage(flow)
    flow.logger.info("流程完成！")
    return artifact
