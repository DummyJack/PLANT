# Project flow orchestration: run init, meeting rounds, and finalization.
from datetime import datetime, timezone
from typing import Any, Dict
import os


def sync_project_output_language(artifact: Dict[str, Any]) -> None:
    meta = artifact.setdefault("meta", {})
    lang = str(meta.get("output_language") or os.environ.get("PLANT_OUTPUT_LANGUAGE") or "zh-Hant").strip() or "zh-Hant"
    if lang not in {"en", "zh-Hant"}:
        lang = "zh-Hant"
    os.environ["PLANT_OUTPUT_LANGUAGE"] = lang
    meta["output_language"] = lang


def run_meeting_round(flow, artifact: Dict[str, Any], round_num: int) -> Dict[str, Any]:
    return flow.meeting.run_meeting_round(artifact, round_num)


def write_pre_meeting_conflict_report(flow, artifact: Dict[str, Any], round_num: int) -> None:
    if not artifact.get("conflicts"):
        return
    flow.logger.info("產出需求 Conflict 報告")
    conflict_md = flow.analyst_agent.generate_conflict_report(
        artifact,
        round_num=round_num,
        recent_decisions_limit=flow.config.get("agenda_items", 5),
    )
    flow.store.save_markdown(conflict_md, "conflict_report.md")
    flow.logger.info("  ✓ 已存 conflict_report.md")


def run_one_round(
    flow,
    artifact: Dict[str, Any],
    round_num: int,
    *,
    is_retry: bool = False,
) -> Dict[str, Any]:
    if is_retry:
        flow.logger.info(f"=== Round {round_num}: 開會（正式 SRS 未通過，補充討論） ===")
    else:
        flow.logger.info(f"=== Round {round_num}: 開會 ===")
    artifact = flow.run_meeting_round(artifact, round_num)
    flow.store.save_artifact(artifact)
    flow.logger.info(f"Round {round_num} 完成")
    return artifact


def run_project(flow, rough_idea: str) -> Dict[str, Any]:
    rounds = flow.config.get("rounds", 1)
    now = datetime.now(timezone.utc).isoformat()
    artifact = {
        "rough_idea": rough_idea,
        "stakeholders": [],
        "scope": {"in_scope": [], "out_of_scope": [], "description": ""},
        "requirements": [],
        "conflicts": [],
        "feedback": {},
        "system_models": {},
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

    flow.logger.info("=== Phase 0: 初始草稿建立 ===")
    artifact = flow.run_init_phase(artifact)
    flow.store.save_artifact(artifact)
    write_pre_meeting_conflict_report(flow, artifact, round_num=0)

    for round_num in range(1, rounds + 1):
        artifact = run_one_round(flow, artifact, round_num)

    flow.logger.info("=== 規格化 ===")
    flow.finalize(artifact)
    flow.logger.info("流程完成！")
    return artifact


def run_continue_project(flow, existing_artifact: Dict[str, Any]) -> Dict[str, Any]:
    artifact = existing_artifact
    artifact.setdefault(
        "scope", {"in_scope": [], "out_of_scope": [], "description": ""}
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

    write_pre_meeting_conflict_report(flow, artifact, round_num=start_round - 1)

    for round_num in range(start_round, start_round + rounds):
        artifact = run_one_round(flow, artifact, round_num)

    flow.logger.info("=== 規格化 ===")
    flow.finalize(artifact)
    flow.logger.info("流程完成！")
    return artifact
