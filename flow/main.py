# Project flow orchestration: run init, meeting rounds, and finalization.
from datetime import datetime, timezone
from typing import Any, Dict
import os

from .init_flow import stage_skip


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


def require_formal_meeting_inputs(flow) -> None:
    draft_version = flow.store.get_draft_version() if hasattr(flow.store, "get_draft_version") else -1
    if draft_version >= 0 and flow.store.load_draft(draft_version):
        return
    raise RuntimeError(
        "stage.formal_meeting 缺少輸入；需要 artifact/drafts/draft_v0.md 或更新版本"
    )


def require_final_meeting_inputs(flow) -> None:
    draft_version = flow.store.get_draft_version() if hasattr(flow.store, "get_draft_version") else -1
    if draft_version >= 0 and flow.store.load_draft(draft_version):
        return
    raise RuntimeError(
        "stage.final_meeting 缺少輸入；需要 artifact/drafts/draft_v0.md 或更新版本"
    )


def require_srs_inputs(artifact: Dict[str, Any]) -> None:
    requirements = [
        row for row in (artifact.get("requirements", []) or [])
        if isinstance(row, dict)
    ]
    if requirements:
        return
    raise RuntimeError("stage.SRS 缺少輸入；需要 artifact 內已有 requirements")


def run_project(flow, rough_idea: str) -> Dict[str, Any]:
    rounds = flow.config.get("rounds", 1)
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
    artifact.setdefault("meta", {})["session_end_round"] = int(rounds)
    flow.store.save_artifact(artifact)

    flow.logger.info("=== 初始階段 ===")
    artifact = flow.run_init_phase(artifact)
    flow.store.save_artifact(artifact)

    if stage_skip(flow.config, "formal_meeting"):
        require_formal_meeting_inputs(flow)
        flow.logger.info("=== 正式會議 ===")
        flow.logger.info("跳過正式會議：使用既有需求草稿")
    else:
        require_formal_meeting_inputs(flow)
        for round_num in range(1, rounds + 1):
            artifact = run_one_round(flow, artifact, round_num)

    flow.logger.info("=== Final ===")
    if stage_skip(flow.config, "final_meeting"):
        require_final_meeting_inputs(flow)
        flow.logger.info("跳過 Final：使用既有會議結果")
    else:
        require_final_meeting_inputs(flow)
        artifact = flow.meeting.run_final(artifact)
        flow.store.save_artifact(artifact)

    flow.logger.info("=== 規格化 ===")
    if stage_skip(flow.config, "SRS"):
        require_srs_inputs(artifact)
        flow.logger.info("跳過 SRS：使用既有正式規格文件")
    else:
        require_srs_inputs(artifact)
        flow.finalize(artifact)
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

    rounds = flow.config.get("rounds", 1)
    start_round = len(artifact.get("discussions", [])) + 1
    end_round = start_round + int(rounds) - 1
    artifact.setdefault("meta", {})["session_end_round"] = end_round
    flow.logger.info(f"繼續專案 Round {start_round}，共 {rounds} 輪")

    if stage_skip(flow.config, "formal_meeting"):
        require_formal_meeting_inputs(flow)
        flow.logger.info("=== 正式會議 ===")
        flow.logger.info("跳過正式會議：使用既有需求草稿")
    else:
        require_formal_meeting_inputs(flow)
        for round_num in range(start_round, start_round + rounds):
            artifact = run_one_round(flow, artifact, round_num)

    flow.logger.info("=== Final ===")
    if stage_skip(flow.config, "final_meeting"):
        require_final_meeting_inputs(flow)
        flow.logger.info("跳過 Final：使用既有會議結果")
    else:
        require_final_meeting_inputs(flow)
        artifact = flow.meeting.run_final(artifact)
        flow.store.save_artifact(artifact)

    flow.logger.info("=== 規格化 ===")
    if stage_skip(flow.config, "SRS"):
        require_srs_inputs(artifact)
        flow.logger.info("跳過 SRS：使用既有正式規格文件")
    else:
        require_srs_inputs(artifact)
        flow.finalize(artifact)
    flow.logger.info("流程完成！")
    return artifact
