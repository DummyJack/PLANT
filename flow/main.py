# Project flow orchestration: run init, meeting rounds, and finalization.
from datetime import datetime, timezone
from typing import Any, Dict
import os

from utils import stage_enabled


def sync_project_output_language(artifact: Dict[str, Any]) -> None:
    meta = artifact.setdefault("meta", {})
    lang = str(meta.get("output_language") or os.environ.get("PLANT_OUTPUT_LANGUAGE") or "zh-Hant").strip() or "zh-Hant"
    if lang not in {"en", "zh-Hant"}:
        lang = "zh-Hant"
    os.environ["PLANT_OUTPUT_LANGUAGE"] = lang
    meta["output_language"] = lang


def run_meeting_round(flow, artifact: Dict[str, Any], round_num: int) -> Dict[str, Any]:
    return flow.meeting.run_meeting_round(artifact, round_num)


def run_one_round(
    flow,
    artifact: Dict[str, Any],
    round_num: int,
    *,
    is_retry: bool = False,
) -> Dict[str, Any]:
    if is_retry:
        flow.logger.info(f"=== Round {round_num}: 開會（Final meeting 後補充討論） ===")
    else:
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


def require_formal_meeting_inputs(flow) -> None:
    require_latest_draft(flow, "formal_meeting")


def require_final_meeting_inputs(flow) -> None:
    require_latest_draft(flow, "final_meeting")


def require_srs_draft_inputs(flow) -> None:
    require_latest_draft(flow, "SRS")


def _artifact_file_non_empty(flow, *parts: str) -> bool:
    artifact_dir = getattr(flow.store, "artifact_dir", None)
    if artifact_dir is None:
        return False
    path = artifact_dir.joinpath(*parts)
    return path.exists() and path.is_file() and path.stat().st_size > 0


def _has_completed_formal_meeting(flow, artifact: Dict[str, Any], end_round: int) -> bool:
    draft_version = flow.store.get_draft_version() if hasattr(flow.store, "get_draft_version") else -1
    discussions = [
        row for row in (artifact.get("discussions", []) or [])
        if isinstance(row, dict)
    ]
    return draft_version >= int(end_round) and len(discussions) >= int(end_round)


def _has_completed_final_meeting(artifact: Dict[str, Any]) -> bool:
    return any(
        bool(row.get("is_final_meeting"))
        for row in (artifact.get("discussions", []) or [])
        if isinstance(row, dict)
    )


def _has_existing_srs(flow) -> bool:
    return _artifact_file_non_empty(flow, "srs.md")


def save_cost_summary(flow) -> None:
    cost_summary = flow.build_cost_summary()
    if cost_summary:
        flow.store.save_json(cost_summary, flow.store.project_dir / "cost_summary.json")
        flow.logger.info("✓ 已儲存 cost_summary.json")
    else:
        flow.logger.info("無定價資訊，略過 cost_summary")


def run_project(flow, rough_idea: str) -> Dict[str, Any]:
    run_formal = stage_enabled(flow.config, "formal_meeting")
    rounds = int(flow.config.get("rounds", 1) or 1) if run_formal else 0
    now = datetime.now(timezone.utc).isoformat()
    artifact = {
        "rough_idea": rough_idea,
        "stakeholders": [],
        "scope": {"in_scope": [], "out_of_scope": []},
        "requirements": [],
        "feedback": {},
        "system_models": [],
        "discussions": [],
        "decisions": [],
        "open_questions": [],
        "meta": {
            "schema_version": 1,
            "created_at": now,
            "updated_at": now,
            "updated_by": "flow.run.init",
            "last_round": 0,
        },
    }
    artifact = flow.ensure_artifact_contract(artifact)
    sync_project_output_language(artifact)
    flow.touch_artifact_meta(
        artifact,
        updated_by="flow.run.init",
        round_num=0,
    )
    if run_formal:
        artifact.setdefault("meta", {})["session_end_round"] = int(rounds)
    flow.store.save_artifact(artifact)

    flow.logger.info("=== 初始階段 ===")
    artifact = flow.run_init_phase(artifact)
    flow.store.save_artifact(artifact)

    if not run_formal:
        flow.logger.info("=== 正式會議 ===")
        flow.logger.info("跳過正式會議")
    elif _has_completed_formal_meeting(flow, artifact, rounds):
        flow.logger.info("=== 正式會議 ===")
        flow.logger.info("✓ 正式會議輸出已存在，跳過重新開會")
    else:
        require_formal_meeting_inputs(flow)
        for round_num in range(1, rounds + 1):
            artifact = run_one_round(flow, artifact, round_num)
        flow.store.save_artifact(artifact)

    flow.logger.info("=== Final ===")
    if not stage_enabled(flow.config, "final_meeting"):
        flow.logger.info("跳過 Final")
    elif _has_completed_final_meeting(artifact):
        flow.logger.info("✓ Final 輸出已存在，跳過重新生成")
    else:
        require_final_meeting_inputs(flow)
        artifact = flow.meeting.run_final(artifact)
        flow.store.save_artifact(artifact)

    flow.logger.info("=== 規格化 ===")
    if not stage_enabled(flow.config, "SRS"):
        flow.logger.info("跳過 SRS")
    elif _has_existing_srs(flow):
        require_srs_draft_inputs(flow)
        flow.logger.info("✓ SRS 已存在，跳過重新生成")
    else:
        require_srs_draft_inputs(flow)
        flow.finalize(artifact)
        flow.store.save_artifact(artifact)
    save_cost_summary(flow)
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
    flow.touch_artifact_meta(
        artifact,
        updated_by="flow.run_continue.init",
    )

    flow.user_agent.stakeholders = artifact.get("stakeholders", [])

    flow.logger.info("=== 初始階段 ===")
    artifact = flow.run_init_phase(artifact)
    flow.store.save_artifact(artifact)

    run_formal = stage_enabled(flow.config, "formal_meeting")
    rounds = int(flow.config.get("rounds", 1) or 1) if run_formal else 0
    start_round = len(artifact.get("discussions", [])) + 1
    end_round = start_round + int(rounds) - 1
    if run_formal:
        artifact.setdefault("meta", {})["session_end_round"] = end_round
        flow.logger.info(f"繼續專案 Round {start_round}，共 {rounds} 輪")

    if not run_formal:
        flow.logger.info("=== 正式會議 ===")
        flow.logger.info("跳過正式會議")
    elif _has_completed_formal_meeting(flow, artifact, end_round):
        flow.logger.info("=== 正式會議 ===")
        flow.logger.info("✓ 正式會議輸出已存在，跳過重新開會")
    else:
        require_formal_meeting_inputs(flow)
        for round_num in range(start_round, start_round + rounds):
            artifact = run_one_round(flow, artifact, round_num)
        flow.store.save_artifact(artifact)

    flow.logger.info("=== Final ===")
    if not stage_enabled(flow.config, "final_meeting"):
        flow.logger.info("跳過 Final")
    elif _has_completed_final_meeting(artifact):
        flow.logger.info("✓ Final 輸出已存在，跳過重新生成")
    else:
        require_final_meeting_inputs(flow)
        artifact = flow.meeting.run_final(artifact)
        flow.store.save_artifact(artifact)

    flow.logger.info("=== 規格化 ===")
    if not stage_enabled(flow.config, "SRS"):
        flow.logger.info("跳過 SRS")
    elif _has_existing_srs(flow):
        require_srs_draft_inputs(flow)
        flow.logger.info("✓ SRS 已存在，跳過重新生成")
    else:
        require_srs_draft_inputs(flow)
        flow.finalize(artifact)
        flow.store.save_artifact(artifact)
    save_cost_summary(flow)
    flow.logger.info("流程完成！")
    return artifact
