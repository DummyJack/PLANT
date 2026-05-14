# Final meeting stage: run closure review after configured meeting rounds.
from typing import Any, Dict

from utils import Collect
from agents.profile.analyst.requirements import assess_requirements_for_final_meeting
from agents.profile.mediator import ISSUE_CATEGORY_LABEL
from agents.profile.mediator.meeting_runner import MeetingRunner
from agents.profile.mediator.validation import decision_issue

from .main import post_round_pipeline


def final_round_num(artifact: Dict[str, Any]) -> int:
    meta = artifact.get("meta") or {}
    base = meta.get("session_end_round")
    if base is None:
        base = meta.get("last_round") or len(artifact.get("discussions", []) or [])
    try:
        return int(base) + 1
    except (TypeError, ValueError):
        return len(artifact.get("discussions", []) or []) + 1


def build_runner(
    coordinator: Any,
    artifact: Dict[str, Any],
    *,
    issue_pool,
    round_num: int,
) -> MeetingRunner:
    return MeetingRunner(
        coordinator.flow.mediator_agent,
        coordinator.flow.registry,
        artifact,
        issue_pool,
        round_num,
        coordinator.flow.config,
        coordinator.flow.store,
        Collect,
        coordinator.flow.logger,
    )


def run_final(
    coordinator: Any,
    artifact: Dict[str, Any],
    *,
    round_num: int,
) -> Dict[str, Any]:
    proposal = coordinator.flow.mediator_agent.final_meeting_issue(
        artifact=artifact,
        round_num=round_num,
    )
    issue_pool = [proposal] if proposal else []
    existing_issue_proposals = artifact.get("issue_proposals", []) or []
    if proposal:
        seen_issue_ids = {
            row.get("issue_id")
            for row in existing_issue_proposals
            if isinstance(row, dict) and row.get("issue_id")
        }
        if proposal.get("issue_id") not in seen_issue_ids:
            existing_issue_proposals.append(proposal)
            artifact["issue_proposals"] = existing_issue_proposals

    runner = build_runner(
        coordinator,
        artifact,
        issue_pool=issue_pool,
        round_num=round_num,
    )
    if proposal:
        issue = decision_issue(
            {
                "id": "FRD-01",
                "title": proposal.get("title", "最終需求收斂確認"),
                "description": proposal.get("description", ""),
                "category": proposal.get("category", "open_question"),
                "participants": proposal.get("participants", []),
                "discussion_mode": proposal.get("discussion_mode", "sequential"),
                "speaking_order": proposal.get("speaking_order", []),
                "source_ids": proposal.get("source_ids", []),
                "source_issue_ids": [proposal.get("issue_id")] if proposal.get("issue_id") else [],
                "triage_action": "formal_meeting",
                "status": "pending",
            },
            allowed_categories=list(ISSUE_CATEGORY_LABEL.keys()),
            registered_agents=list(coordinator.flow.registry.get_names())
            if coordinator.flow.registry
            else ["analyst", "expert", "modeler", "user"],
            index=1,
        )
        if issue:
            mediator_title = coordinator.flow.mediator_agent.name_meeting_issue(
                issue,
                context_label="最終需求收斂確認",
            )
            issue["title"] = mediator_title
            runner.issues = [issue]
            runner.issue_status = {
                issue["id"]: {
                    "discussed": False,
                    "contributions": None,
                    "resolution": None,
                    "saved": False,
                }
            }
    coordinator.run_round_opa_loop(runner)
    artifact = post_round_pipeline(
        coordinator,
        artifact,
        runner,
        round_num=round_num,
        finalize_requirements=True,
    )
    discussions = artifact.get("discussions", [])
    if isinstance(discussions, list) and discussions:
        discussions[-1]["is_final_meeting"] = True
    final_meeting_stats = assess_requirements_for_final_meeting(
        artifact,
        round_num=round_num,
    )
    coordinator.flow.logger.info(
        "Final meeting：confirmed=%s needs_followup=%s",
        final_meeting_stats.get("confirmed_count", 0),
        final_meeting_stats.get("needs_followup_count", 0),
    )
    coordinator.flow.touch_artifact_meta(
        artifact,
        updated_by="flow.final",
        round_num=round_num,
    )
    coordinator.flow.store.save_artifact(artifact)
    return artifact
