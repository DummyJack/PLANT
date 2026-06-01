# Meeting round lifecycle: pre-round checks, issue planning, and meeting execution.
from typing import Any, Dict, List, Optional

from utils import Collect, stage_enabled
from agents.profile.mediator import ISSUE_CATEGORY_LABEL
from agents.profile.mediator.meeting_runner import MeetingRunner
from agents.profile.mediator.validation import issue_proposal as issue_proposal_schema
from agents.profile.analyst.conflict_store import (
    all_conflict_rows,
    set_conflict_entries,
)
from agents.profile.analyst.requirements import requirement_discussion_pool


def save_meeting_preparation_outputs(
    coordinator: Any,
    artifact: Dict[str, Any],
    round_num: int,
) -> None:
    coordinator.flow.store.save_artifact(artifact)
    requirements = artifact.get("URL")
    if not isinstance(requirements, list) or not requirements:
        raise RuntimeError(
            "正式會議缺少輸入；需要 artifact/requirements.json 中的 requirements"
        )


def build_formal_meeting_artifact(coordinator: Any, artifact: Dict[str, Any]) -> Dict[str, Any]:
    """正式會議輸入保留審查上下文與跨輪 issue backlog。"""
    conflict_state = artifact.get("conflict") if isinstance(artifact.get("conflict"), dict) else {}
    return {
        "meta": artifact.get("meta", {}) if isinstance(artifact.get("meta"), dict) else {},
        "scenario": str(artifact.get("scenario") or "").strip(),
        "scope": artifact.get("scope", {}) if isinstance(artifact.get("scope"), dict) else {},
        "stakeholders": artifact.get("stakeholders", []) if isinstance(artifact.get("stakeholders"), list) else [],
        "URL": requirement_discussion_pool(artifact),
        "REQ": artifact.get("REQ", []) if isinstance(artifact.get("REQ"), list) else [],
        "system_models": artifact.get("system_models", []) if isinstance(artifact.get("system_models"), list) else [],
        "conflict_report": conflict_state.get("report", []) if isinstance(conflict_state.get("report"), list) else [],
        "conflict": conflict_state,
        "feedback": artifact.get("feedback", {}) if isinstance(artifact.get("feedback"), dict) else {},
        "open_questions": artifact.get("open_questions", []) if isinstance(artifact.get("open_questions"), list) else [],
        "discussions": artifact.get("discussions", []) if isinstance(artifact.get("discussions"), list) else [],
        "issue_backlog": artifact.get("issue_backlog", []) if isinstance(artifact.get("issue_backlog"), list) else [],
        "issue_discarded": artifact.get("issue_discarded", []) if isinstance(artifact.get("issue_discarded"), list) else [],
    }


# ---------- issue proposals ----------

def recent_issue_discussions(
    artifact: Dict[str, Any],
    *,
    rounds: int = 1,
) -> List[Dict[str, Any]]:
    discussions = artifact.get("discussions", []) or []
    recent_rounds = discussions[-max(1, rounds):]
    out: List[Dict[str, Any]] = []
    for rd in recent_rounds:
        out.extend(rd.get("issues", []) or [])
    return out


def issue_proposal(
    item: Dict[str, Any],
    *,
    proposed_by: str,
    round_num: int,
    index: int,
) -> Optional[Dict[str, Any]]:
    return issue_proposal_schema(
        item,
        allowed_categories=list(ISSUE_CATEGORY_LABEL.keys()),
        default_participants=["analyst", "expert", "modeler", "user"],
        proposed_by=proposed_by,
        round_num=round_num,
        index=index,
    )


FINAL_CONFLICT_STATUSES = {"agreed", "human_decision"}


def unresolved_conflict_report_rows(conflict_report: Any) -> List[Dict[str, Any]]:
    if not isinstance(conflict_report, list):
        return []
    unresolved: List[Dict[str, Any]] = []
    for row in conflict_report:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "").strip().lower()
        if status in FINAL_CONFLICT_STATUSES:
            continue
        unresolved.append(row)
    return unresolved


def conflict_report_row_ids(rows: List[Dict[str, Any]]) -> List[str]:
    return [
        str(row.get("id") or "").strip()
        for row in rows
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    ]


def mediator_issue_proposals(
    artifact: Dict[str, Any],
    *,
    round_num: int,
) -> List[Dict[str, Any]]:
    """Default SRS review issues without expanding large source pools."""
    rows: List[Dict[str, Any]] = []
    conflict_report = artifact.get("conflict_report")
    unresolved_conflicts = unresolved_conflict_report_rows(conflict_report)
    if unresolved_conflicts:
        unresolved_ids = conflict_report_row_ids(unresolved_conflicts)
        rows.append(
            {
                "issue_id": f"I-R{round_num}-mediator-conflict-review",
                "title": "解決需求衝突",
                "category": "resolve_conflict",
                "evidence": [
                    f"conflict_report 共有 {len(conflict_report or [])} 筆項目，其中 {len(unresolved_conflicts)} 筆需求衝突尚未解決；此會議只討論既有 resolution_options / recommended_resolution 的採用、調整或人類裁決，不重新辨識衝突。"
                ],
                "expect_outcome": "讀取整份 conflict_report，直接討論既有 resolution_options 與 recommended_resolution。若會議中可判斷採用或調整方案則收斂；若無法在內容上做出抉擇，整理選項交由人類裁決。",
                "sources": [{"artifact": "conflict_report", "ids": unresolved_ids, "evidence": "整份 conflict_report 需要討論既有 resolution。"}],
                "expected_actions": {"analyst": ["discuss_conflict"]},
                "participants": ["user", "analyst"],
                "discussion_mode": "sequential",
                "importance": "high",
                "reason": "需求衝突報告已包含解決方案候選與推薦；正式會議目標是對既有 resolution 做取捨，不重新辨識衝突。",
            }
        )

    meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
    reviewed_requirements = str(meta.get("requirements_review_status") or "").strip() in FINAL_CONFLICT_STATUSES
    requirements = artifact.get("URL")
    if isinstance(requirements, list) and requirements and not reviewed_requirements:
        rows.append(
            {
                "issue_id": f"I-R{round_num}-mediator-requirement-review",
                "title": "需求分類",
                "category": "clarify_requirement",
                "evidence": [
                    "User Requirements 需先整體整理，再正式化為初步 REQ-* 需求條目；此會議只做需求整理，不做業務裁決。"
                ],
                "expect_outcome": "Analyst 先整理全部 User Requirements，產生初步 REQ-* 需求條目與可推得的欄位；User 再檢查是否漏掉重要使用情境、業務規則、例外條件、驗收條件、品質限制、優先級、風險或假設。若有關鍵補充，下一輪由 Analyst 再更新 REQ。",
                "sources": [{"artifact": "URL", "ids": [], "evidence": "全部 User Requirements 需整理為初步 REQ-* 需求條目。"}],
                "expected_actions": {"analyst": ["refine_requirement"]},
                "participants": ["analyst", "user"],
                "discussion_mode": "sequential",
                "importance": "high",
                "reason": "User Requirements 需要先整理並轉成可追蹤、可驗收的 REQ-* 需求條目；爭議與業務取捨應留給後續議題或人類裁決。",
            }
        )
    proposals: List[Dict[str, Any]] = []
    for i, row in enumerate(rows, 1):
        normalized = issue_proposal(
            row,
            proposed_by="mediator",
            round_num=round_num,
            index=i,
        )
        if normalized:
            proposals.append(normalized)
    return proposals


def is_conflict_report_only_proposal(row: Dict[str, Any]) -> bool:
    sources = row.get("sources")
    if not isinstance(sources, list) or not sources:
        return False
    artifacts = {
        str(item.get("artifact") or "").strip()
        for item in sources
        if isinstance(item, dict)
    }
    return artifacts == {"conflict_report"}


def collect_issue_proposals(
    coordinator: Any,
    artifact: Dict[str, Any],
    *,
    round_num: int,
) -> List[Dict[str, Any]]:
    general_enabled = stage_enabled(coordinator.flow.config, "general_formal_meeting", True)
    if stage_enabled(coordinator.flow.config, "default_formal_meeting", True):
        proposals: List[Dict[str, Any]] = mediator_issue_proposals(
            artifact,
            round_num=round_num,
        )
    else:
        proposals = []
        coordinator.flow.logger.info("Default Formal Meeting：stage disabled，略過預設正式會議議題")
    seen_issue_ids = {
        row.get("issue_id")
        for row in proposals
        if isinstance(row, dict) and row.get("issue_id")
    }
    has_whole_conflict_report_issue = any(
        isinstance(row, dict)
        and str(row.get("proposed_by") or "").strip() == "mediator"
        and is_conflict_report_only_proposal(row)
        for row in proposals
    )
    invalid_count = 0

    def append_proposal(row: Optional[Dict[str, Any]]) -> bool:
        if not row:
            return False
        if (
            has_whole_conflict_report_issue
            and str(row.get("proposed_by") or "").strip() != "mediator"
            and is_conflict_report_only_proposal(row)
        ):
            return True
        issue_id = row.get("issue_id")
        if issue_id and issue_id in seen_issue_ids:
            return True
        proposals.append(row)
        if issue_id:
            seen_issue_ids.add(issue_id)
        return True

    if general_enabled and not proposals:
        latest_version = coordinator.flow.store.get_draft_version()
        draft_md = coordinator.flow.store.load_draft(latest_version) if latest_version >= 0 else ""
        if draft_md.strip():
            proposal_context = (
                coordinator.proposal_context_summary(artifact, draft_version=latest_version)
                if hasattr(coordinator, "proposal_context_summary")
                else {"draft": {"version": latest_version}}
            )
            proposal_artifact = {
                "latest_draft": draft_md,
                "proposal_context": proposal_context,
            }
            registry = getattr(coordinator.flow, "registry", None)
            max_items = 5
            for agent_name in ("analyst", "expert", "modeler"):
                agent = registry.get(agent_name) if registry else None
                if not agent or not hasattr(agent, "propose_issues"):
                    continue
                try:
                    rows = agent.propose_issues(
                        proposal_artifact,
                        round_num=round_num,
                        max_items=max_items,
                    )
                except Exception as e:
                    invalid_count += 1
                    coordinator.flow.logger.warning(
                        "Issue Proposal：%s draft proposal failed: %s",
                        agent_name,
                        e,
                    )
                    continue
                for i, row in enumerate(rows or [], 1):
                    normalized = issue_proposal(
                        row,
                        proposed_by=agent_name,
                        round_num=round_num,
                        index=i,
                    )
                    if not append_proposal(normalized):
                        invalid_count += 1
            if proposals or invalid_count:
                meta = artifact.setdefault("meta", {})
                meta[f"draft_issue_proposals_round_{round_num}"] = True
                coordinator.flow.logger.info(
                    "Issue Proposal：latest draft 產生 %s 筆一般候選，淘汰 %s 筆",
                    len(proposals),
                    invalid_count,
                )

    return proposals

# ---------- apply mediator updates ----------

def apply_mediator_updates(
    artifact: Dict[str, Any],
    updates: Dict[str, Any],
) -> Dict[str, Any]:
    def dict_rows(value: Any) -> List[Dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [row for row in value if isinstance(row, dict)]

    current_conflicts = dict_rows(all_conflict_rows(artifact))
    prev_conflicts_by_id = {
        c.get("id"): c for c in current_conflicts if c.get("id")
    }
    candidate_conflicts = updates.get("conflicts", current_conflicts)
    new_conflicts = dict_rows(candidate_conflicts) or current_conflicts
    extra_new_conflicts = dict_rows(updates.get("new_conflicts", []))
    next_pair_num = len(
        [c for c in new_conflicts if isinstance(c, dict) and str(c.get("id") or "").startswith("PAIR-")]
    ) + 1
    next_multiple_num = len(
        [c for c in new_conflicts if isinstance(c, dict) and str(c.get("id") or "").startswith("MULTIPLE-")]
    ) + 1
    for row in extra_new_conflicts:
        if not isinstance(row, dict):
            continue
        candidate = dict(row)
        if not str(candidate.get("id") or "").strip():
            req_ids = [
                str(item).strip()
                for item in (candidate.get("requirement_ids") or [])
                if str(item).strip()
            ]
            conflict_scope = str(
                candidate.get("scope")
                or candidate.get("kind")
                or candidate.get("conflict_scope")
                or ""
            ).strip().lower()
            is_group_conflict = (
                conflict_scope in {"group", "multiple", "set", "group_conflict"}
                or bool(candidate.get("related_pairs"))
                or len(req_ids) > 2
            )
            if len(req_ids) >= 2 and is_group_conflict:
                candidate["id"] = f"MULTIPLE-{next_multiple_num}"
                next_multiple_num += 1
            else:
                candidate["id"] = f"PAIR-{next_pair_num}"
                next_pair_num += 1
        new_conflicts.append(candidate)
    for c in new_conflicts:
        if not isinstance(c, dict):
            continue
        orig = prev_conflicts_by_id.get(c.get("id"))
        if not orig:
            continue
        if orig.get("requirement_ids") is not None:
            c.setdefault("requirement_ids", orig["requirement_ids"])
    set_conflict_entries(artifact, new_conflicts)
    return {}


# ---------- 主入口 ----------

def run_meeting_round_block(
    coordinator: Any,
    artifact: Dict[str, Any],
    round_num: int,
) -> Dict[str, Any]:
    artifact = coordinator.flow.ensure_artifact_contract(artifact)
    coordinator.run_round_pipeline_step(
        stage="save_meeting_preparation_outputs",
        round_num=round_num,
        artifact=artifact,
        action_fn=save_meeting_preparation_outputs,
        action_kwargs={
            "coordinator": coordinator,
            "artifact": artifact,
            "round_num": round_num,
        },
    )
    meeting_artifact = build_formal_meeting_artifact(coordinator, artifact)
    latest_draft_version = coordinator.flow.store.get_draft_version()
    latest_draft = (
        coordinator.flow.store.load_draft(latest_draft_version)
        if latest_draft_version >= 0
        else ""
    )
    if latest_draft:
        meeting_artifact["latest_draft"] = {
            "version": latest_draft_version,
            "content": latest_draft,
        }
    current_round_proposals = collect_issue_proposals(
        coordinator, meeting_artifact, round_num=round_num,
    )
    existing_issue_proposals = artifact.get("issue_proposals", []) or []
    seen_issue_ids = {
        row.get("issue_id")
        for row in existing_issue_proposals
        if isinstance(row, dict) and row.get("issue_id")
    }
    for row in current_round_proposals:
        if not isinstance(row, dict):
            continue
        issue_id = row.get("issue_id")
        if issue_id and issue_id in seen_issue_ids:
            continue
        existing_issue_proposals.append(row)
        if issue_id:
            seen_issue_ids.add(issue_id)
    artifact["issue_proposals"] = existing_issue_proposals
    coordinator.flow.store.save_artifact(artifact)

    meeting_artifact["issue_proposals"] = current_round_proposals
    runner = MeetingRunner(
        coordinator.flow.mediator_agent,
        coordinator.flow.registry,
        meeting_artifact,
        current_round_proposals,
        round_num,
        coordinator.flow.config,
        coordinator.flow.store,
        Collect,
        coordinator.flow.logger,
        output_artifact=artifact,
    )
    coordinator.run_round_pipeline_step(
        stage="meeting_loop",
        round_num=round_num,
        artifact=artifact,
        action_fn=coordinator.run_meeting_loop,
        action_kwargs={"runner": runner},
    )
    coordinator.flow.touch_artifact_meta(artifact, round_num=round_num)
    return artifact
