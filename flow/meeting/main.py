# Handles main logic for project flow orchestration and stage execution.
import re
from typing import Any, Dict, List, Optional

from storage import compact_markdown_context
from storage.artifact import conflict_payload, latest_conflict_report_payload
from utils import Collect, stage_enabled
from agents.profile.mediator import category_labels
from agents.meeting.main import MeetingRunner
from agents.profile.mediator.validation import (
    issue_proposal as issue_proposal_schema,
    meeting_issue as meeting_issue_schema,
)
from agents.profile.analyst.conflicts import (
    all_conflict_rows,
    set_conflict_entries,
)
from storage.requirements import requirement_discussion_pool


# ========
# Defines save meeting preparation outputs function for this module workflow.
# ========
def save_meeting_preparation_outputs(
    coordinator: Any,
    artifact: Dict[str, Any],
    round_num: int,
) -> None:
    coordinator.flow.store.save_artifact(artifact)
    requirements = artifact.get("URL")
    if not isinstance(requirements, list) or not requirements:
        raise RuntimeError(
            "正式會議缺少輸入；需要 artifact/requirements.json 中的 URL"
        )


# ========
# Defines build formal meeting artifact function for this module workflow.
# ========
def sync_conflict_report_history(
    artifact: Dict[str, Any],
    *,
    artifact_dir: Any = None,
) -> List[Dict[str, Any]]:
    history_rows: List[Dict[str, Any]] = []
    if artifact_dir is not None:
        history_rows = latest_conflict_report_payload(artifact_dir)
    if history_rows:
        conflict_state = artifact.setdefault("conflict", {})
        if isinstance(conflict_state, dict):
            conflict_state["report"] = history_rows
        artifact["conflict_report"] = history_rows
        return history_rows
    return conflict_report_rows(artifact)


def build_formal_meeting_artifact(coordinator: Any, artifact: Dict[str, Any]) -> Dict[str, Any]:
    conflict_report = sync_conflict_report_history(
        artifact,
        artifact_dir=getattr(coordinator.flow.store, "artifact_dir", None),
    )
    conflict_state = artifact.get("conflict") if isinstance(artifact.get("conflict"), dict) else {}
    return {
        "meta": artifact.get("meta", {}) if isinstance(artifact.get("meta"), dict) else {},
        "scenario": str(artifact.get("scenario") or "").strip(),
        "scope": artifact.get("scope", {}) if isinstance(artifact.get("scope"), dict) else {},
        "stakeholders": artifact.get("stakeholders", []) if isinstance(artifact.get("stakeholders"), list) else [],
        "URL": requirement_discussion_pool(artifact),
        "REQ": artifact.get("REQ", []) if isinstance(artifact.get("REQ"), list) else [],
        "system_models": artifact.get("system_models", []) if isinstance(artifact.get("system_models"), list) else [],
        "conflict_report": conflict_report,
        "conflict": conflict_state,
        "feedback": artifact.get("feedback", {}) if isinstance(artifact.get("feedback"), dict) else {},
        "open_questions": artifact.get("open_questions", []) if isinstance(artifact.get("open_questions"), list) else [],
        "discussions": artifact.get("discussions", []) if isinstance(artifact.get("discussions"), list) else [],
        "issue_proposals": artifact.get("issue_proposals", []) if isinstance(artifact.get("issue_proposals"), list) else [],
        "meeting_issues": artifact.get("meeting_issues", []) if isinstance(artifact.get("meeting_issues"), list) else [],
        "issue_backlog": artifact.get("issue_backlog", []) if isinstance(artifact.get("issue_backlog"), list) else [],
        "issue_discarded": artifact.get("issue_discarded", []) if isinstance(artifact.get("issue_discarded"), list) else [],
    }



# ========
# Defines recent issue discussions function for this module workflow.
# ========
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


# ========
# Defines issue proposal function for this module workflow.
# ========
def issue_proposal(
    item: Dict[str, Any],
    *,
    proposed_by: str,
    round_num: int,
    index: int,
) -> Optional[Dict[str, Any]]:
    return issue_proposal_schema(
        item,
        allowed_categories=list(category_labels.keys()),
        default_participants=["analyst", "expert", "modeler", "user"],
        proposed_by=proposed_by,
        round_num=round_num,
        index=index,
    )


FINAL_CONFLICT_STATUSES = {"agreed", "human_decision"}


# ========
# Defines conflict report rows function for this module workflow.
# ========
def conflict_report_rows(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    report = artifact.get("conflict_report")
    if isinstance(report, list):
        return [row for row in report if isinstance(row, dict)]
    payload = conflict_payload(artifact, include_report=True)
    report = payload.get("report") if isinstance(payload, dict) else []
    return [row for row in (report or []) if isinstance(row, dict)]


# ========
# Defines unresolved conflict report rows function for this module workflow.
# ========
def unresolved_conflict_report_rows(conflict_report: Any) -> List[Dict[str, Any]]:
    if not isinstance(conflict_report, list):
        return []
    unresolved: List[Dict[str, Any]] = []
    for row in conflict_report:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "").strip()
        if label and label != "Conflict":
            continue
        status = str(row.get("status") or "").strip().lower()
        if status in FINAL_CONFLICT_STATUSES:
            continue
        unresolved.append(row)
    return unresolved


# ========
# Defines conflict report row ids function for this module workflow.
# ========
def conflict_report_row_ids(rows: List[Dict[str, Any]]) -> List[str]:
    return [
        str(row.get("id") or "").strip()
        for row in rows
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    ]


# ========
# Defines stakeholder names function for this module workflow.
# ========
def stakeholder_names(artifact: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    for row in (artifact.get("stakeholders") or []):
        if isinstance(row, dict):
            name = str(row.get("name") or "").strip()
        else:
            name = str(row or "").strip()
        if name:
            names.append(name)
    return list(dict.fromkeys(names))


# ========
# Defines artifact ids from sources function for this module workflow.
# ========
def artifact_ids_from_sources(sources: Any) -> List[str]:
    ids: List[str] = []
    for source in sources or []:
        if not isinstance(source, dict):
            continue
        for source_id in source.get("ids") or []:
            value = str(source_id or "").strip()
            if value:
                ids.append(value)
    return list(dict.fromkeys(ids))


# ========
# Defines target stakeholders function for this module workflow.
# ========
def target_stakeholders(
    artifact: Dict[str, Any],
    artifact_ids: List[str],
) -> List[str]:
    artifact_id_set = set(artifact_ids)
    for row in artifact.get("conflict_report", []) or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("id") or "").strip() not in artifact_id_set:
            continue
        for requirement in row.get("requirements") or []:
            if isinstance(requirement, dict):
                req_id = str(requirement.get("id") or "").strip()
            else:
                req_id = str(requirement or "").strip()
            if req_id:
                artifact_id_set.add(req_id)
    targets: List[str] = []
    for row in (artifact.get("URL") or []):
        if not isinstance(row, dict):
            continue
        if str(row.get("id") or "").strip() not in artifact_id_set:
            continue
        stakeholder = row.get("stakeholder")
        if isinstance(stakeholder, dict):
            name = str(stakeholder.get("name") or "").strip()
        else:
            name = str(stakeholder or "").strip()
        if name:
            targets.append(name)
    return list(dict.fromkeys(targets))


# ========
# Defines completed default issue check function for this module workflow.
# ========
def completed_default_issue(
    artifact: Dict[str, Any],
    *,
    title: str,
    category: str,
    artifact_ids: Optional[List[str]] = None,
) -> bool:
    expected_ids = {
        str(item or "").strip()
        for item in (artifact_ids or [])
        if str(item or "").strip()
    }
    for row in artifact.get("meeting_issues", []) or []:
        if not isinstance(row, dict) or not row.get("completed"):
            continue
        if str(row.get("proposed_by") or "").strip() != "mediator":
            continue
        if str(row.get("title") or "").strip() != title:
            continue
        if str(row.get("category") or "").strip() != category:
            continue
        if not expected_ids:
            return True
        trace = row.get("trace") if isinstance(row.get("trace"), dict) else {}
        row_ids = {
            str(item or "").strip()
            for item in (trace.get("artifact_ids", []) or [])
            if str(item or "").strip()
        }
        if row_ids == expected_ids:
            return True
    return False


# ========
# Defines default issues function for this module workflow.
# ========
def default_issues(
    artifact: Dict[str, Any],
    *,
    round_num: int,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    conflict_report = conflict_report_rows(artifact)
    unresolved_conflicts = unresolved_conflict_report_rows(conflict_report)
    if unresolved_conflicts:
        unresolved_ids = conflict_report_row_ids(unresolved_conflicts)
        if not completed_default_issue(
            artifact,
            title="解決需求衝突",
            category="resolve_conflict",
            artifact_ids=unresolved_ids,
        ):
            rows.append(
                {
                    "issue_id": f"R{round_num}-I1",
                    "title": "解決需求衝突",
                    "category": "resolve_conflict",
                    "evidence": [
                        f"conflict_report 共有 {len(conflict_report or [])} 筆項目，其中 {len(unresolved_conflicts)} 筆需求衝突尚未解決；此會議只討論既有 resolution_options / recommended_resolution 的採用、調整或人類裁決，不重新辨識衝突。"
                    ],
                    "expect_outcome": "讀取整份 conflict_report，直接討論既有 resolution_options 與 recommended_resolution。若會議中可判斷採用或調整方案則收斂；若無法在內容上做出抉擇，整理選項交由人類裁決。",
                    "sources": [{"artifact": "conflict_report", "ids": unresolved_ids, "evidence": "整份 conflict_report 需要討論既有 resolution。"}],
                    "expected_actions": {"analyst": ["discuss_conflict"]},
                    "participants": ["user", "analyst"],
                    "participant_reasoning": {
                        "user": "代表受影響利害關係人確認衝突解法是否可接受",
                        "analyst": "根據 conflict report 討論並寫回衝突解決結果",
                    },
                    "discussion_mode": "sequential",
                    "issue_level": "blocking",
                    "importance": "high",
                    "reason": "需求衝突報告已包含解決方案候選與推薦；正式會議目標是對既有 resolution 做取捨，不重新辨識衝突。",
                }
            )

    meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
    requirements = artifact.get("URL")
    url_ids = [
        str(row.get("id") or "").strip()
        for row in requirements
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    ] if isinstance(requirements, list) else []
    requirement_review_done = bool(url_ids) and (
        completed_default_issue(
            artifact,
            title="需求正式化",
            category="formalize_requirement",
        )
        or completed_default_issue(
            artifact,
            title="需求正式化",
            category="clarify_requirement",
        )
    )
    if isinstance(requirements, list) and requirements and not requirement_review_done:
        rows.append(
            {
                "issue_id": f"R{round_num}-I2",
                "title": "需求正式化",
                "category": "formalize_requirement",
                "evidence": [
                    "User Requirements 需先整體整理，再正式化為初步 REQ-* 需求條目；此會議只做需求整理，不做業務裁決。"
                ],
                "expect_outcome": "Analyst 先整理全部 User Requirements，產生初步 REQ-* 需求條目與可推得的欄位；User 再檢查是否漏掉重要使用情境、業務規則、例外條件、驗收條件、品質限制、優先級、風險或假設。若有關鍵補充，下一輪由 Analyst 再更新 REQ。",
                "sources": [{"artifact": "URL", "ids": url_ids, "evidence": "全部 User Requirements 需整理為初步 REQ-* 需求條目。"}],
                "expected_actions": {"analyst": ["update_requirement"]},
                "participants": ["analyst", "user"],
                "participant_reasoning": {
                    "analyst": "將全部 User Requirements 正式化為 REQ-*",
                    "user": "依指定利害關係人角度檢查遺漏情境與可接受條件",
                },
                "discussion_mode": "sequential",
                "issue_level": "blocking",
                "importance": "high",
                "reason": "User Requirements 需要先整理並轉成可追蹤、可驗收的 REQ-* 需求條目；爭議與業務取捨應留給後續議題或人類裁決。",
            }
        )
    return rows


# ========
# Defines default meeting issues function for this module workflow.
# ========
def default_meeting_issues(
    coordinator: Any,
    artifact: Dict[str, Any],
    *,
    round_num: int,
) -> List[Dict[str, Any]]:
    registry = getattr(coordinator.flow, "registry", None)
    exclude = {"mediator", "documentor"}
    registered = [name for name in registry.get_names() if name not in exclude] if registry else ["user", "analyst", "expert", "modeler"]
    stakeholders = stakeholder_names(artifact)
    issues: List[Dict[str, Any]] = []
    for idx, spec in enumerate(default_issues(artifact, round_num=round_num), 1):
        proposal_id = f"R{round_num}-I{idx}"
        artifact_ids = artifact_ids_from_sources(spec.get("sources"))
        targets = target_stakeholders(artifact, artifact_ids)
        if "user" in (spec.get("participants") or []) and not targets:
            targets = stakeholders
        normalized = meeting_issue_schema(
            {
                **spec,
                "id": f"M-{idx}",
                "description": str(spec.get("expect_outcome") or spec.get("reason") or "").strip(),
                "discussion_rounds": 1,
                "target_stakeholders": targets,
                "trace": {
                    "artifact_ids": artifact_ids,
                    "proposal_ids": [proposal_id],
                },
                "proposed_by": "mediator",
            },
            allowed_categories=list(dict.fromkeys(list(category_labels.keys()) + ["formalize_requirement", "resolve_conflict"])),
            registered_agents=registered,
            allowed_stakeholders=stakeholders,
            index=idx,
        )
        if normalized:
            issues.append(normalized)
    return issues


# ========
# Defines is conflict report only proposal function for this module workflow.
# ========
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


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def renumber_issue_proposals(
    proposals: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], Dict[str, str]]:
    counters: Dict[int, int] = {}
    id_map: Dict[str, str] = {}
    rows: List[Dict[str, Any]] = []
    for row in proposals or []:
        if not isinstance(row, dict):
            continue
        new_row = dict(row)
        try:
            round_num = int(new_row.get("round") or 1)
        except (TypeError, ValueError):
            round_num = 1
        old_id = clean_text(new_row.get("issue_id") or new_row.get("id"))
        if (
            str(new_row.get("proposed_by") or "").strip().lower() == "human"
            and re.fullmatch(rf"R{round_num}-H\d+", old_id)
        ):
            new_row["issue_id"] = old_id
            rows.append(new_row)
            continue
        counters[round_num] = counters.get(round_num, 0) + 1
        new_id = f"R{round_num}-I{counters[round_num]}"
        if old_id:
            id_map[old_id] = new_id
        new_row["issue_id"] = new_id
        rows.append(new_row)
    return rows, id_map


def human_issue_titles(response: Any, *, max_issues: int) -> List[str]:
    if not isinstance(response, dict):
        return []
    values = response.get("custom_issues")
    if values is None:
        values = response.get("issues")
    if values is None:
        values = response.get("titles")
    titles: List[str] = []
    if isinstance(values, list):
        for item in values:
            if isinstance(item, dict):
                title = clean_text(item.get("title"))
            else:
                title = clean_text(item)
            if title and title not in titles:
                titles.append(title)
            if len(titles) >= max_issues:
                break
    return titles


def apply_human_issue_proposals(
    proposals: List[Dict[str, Any]],
    response: Any,
    *,
    round_num: int,
    max_issues: int,
) -> List[Dict[str, Any]]:
    titles = human_issue_titles(response, max_issues=max_issues)
    if not titles:
        return proposals
    rows = [row for row in proposals or [] if isinstance(row, dict)]
    used = {
        int(match.group(1))
        for row in rows
        for match in [re.fullmatch(rf"R{round_num}-H(\d+)", clean_text(row.get("issue_id")))]
        if match
    }
    next_num = 1
    human_rows: List[Dict[str, Any]] = []
    for title in titles:
        while next_num in used:
            next_num += 1
        issue_id = f"R{round_num}-H{next_num}"
        used.add(next_num)
        next_num += 1
        human_rows.append({
            "issue_id": issue_id,
            "round": round_num,
            "title": title,
            "category": "clarify_requirement",
            "issue_focus": "human_added_issue",
            "issue_level": "blocking",
            "importance": "high",
            "expect_outcome": "釐清並決定此議題在本輪會議中的處理方式。",
            "reason": "使用者於候選議題階段人工加入。",
            "proposed_by": "human",
            "sources": [
                {
                    "artifact": "human_issue_proposal",
                    "ids": [issue_id],
                    "evidence": title,
                }
            ],
        })
    return [*human_rows, *rows]


def update_trace_proposal_ids(trace: Any, id_map: Dict[str, str]) -> Any:
    if not isinstance(trace, dict):
        return trace
    updated = dict(trace)
    proposal_ids = [
        clean_text(id_map.get(clean_text(value), clean_text(value)))
        for value in (trace.get("proposal_ids") or [])
        if clean_text(value)
    ]
    if proposal_ids:
        updated["proposal_ids"] = list(dict.fromkeys(proposal_ids))
    return updated


def renumber_meeting_issues(
    issues: List[Dict[str, Any]],
    *,
    proposal_id_map: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    used_nums: set[int] = set()
    for row in issues or []:
        if not isinstance(row, dict):
            continue
        issue_id = clean_text(row.get("id"))
        match = re.fullmatch(r"M-(\d+)", issue_id)
        if match:
            used_nums.add(int(match.group(1)))

    next_num = 1
    for row in [r for r in issues or [] if isinstance(r, dict)]:
        new_row = dict(row)
        issue_id = clean_text(new_row.get("id"))
        if not re.fullmatch(r"M-\d+", issue_id):
            while next_num in used_nums:
                next_num += 1
            issue_id = f"M-{next_num}"
            used_nums.add(next_num)
            next_num += 1
        new_row["id"] = issue_id
        if proposal_id_map:
            new_row["trace"] = update_trace_proposal_ids(new_row.get("trace"), proposal_id_map)
        rows.append(new_row)
    return rows


def normalize_issue_ids_for_storage(artifact: Dict[str, Any]) -> Dict[str, str]:
    proposals = artifact.get("issue_proposals")
    proposal_id_map: Dict[str, str] = {}
    if isinstance(proposals, list):
        normalized_proposals, proposal_id_map = renumber_issue_proposals(proposals)
        artifact["issue_proposals"] = normalized_proposals

    meeting_issues = artifact.get("meeting_issues")
    if isinstance(meeting_issues, list):
        artifact["meeting_issues"] = renumber_meeting_issues(
            meeting_issues,
            proposal_id_map=proposal_id_map,
        )
    return proposal_id_map


def list_values(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def has_content(value: Any) -> bool:
    if value in (None, "", [], {}):
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(has_content(item) for item in value)
    if isinstance(value, dict):
        return any(has_content(item) for item in value.values())
    return True


WEAK_FIELD_TERMS = (
    "待確認",
    "待協議",
    "合理",
    "快速",
    "穩定",
    "清楚",
    "明確",
    "適時",
    "即時",
)
STAKEHOLDER_TITLE_TERMS = (
    "消費者",
    "餐廳店員",
    "外送員",
    "平台營運",
    "平台營運主管",
    "店家管理者",
    "財務",
    "客服",
)


def requirement_field_gap_proposals(
    artifact: Dict[str, Any],
    *,
    round_num: int,
) -> List[Dict[str, Any]]:
    req_rows = [
        row for row in list_values((artifact or {}).get("REQ"))
        if isinstance(row, dict)
    ]
    if not req_rows:
        return []

    gap_rows: List[Dict[str, Any]] = []
    for row in req_rows:
        req_id = clean_text(row.get("id"))
        if not req_id:
            continue
        rtype = clean_text(row.get("type")).lower()
        gaps: List[str] = []
        if not has_content(row.get("description")):
            gaps.append("缺 description")
        if not has_content(row.get("acceptance_criteria")):
            gaps.append("缺 acceptance_criteria")
        if not has_content(row.get("source")):
            gaps.append("缺 source trace")
        if not has_content(row.get("risks")):
            gaps.append("缺 risks")
        if not has_content(row.get("assumptions")):
            gaps.append("缺 assumptions")
        if rtype == "non-functional":
            if not has_content(row.get("category")):
                gaps.append("NFR 缺 category")
            if not has_content(row.get("metric")):
                gaps.append("NFR 缺 metric")
            if not has_content(row.get("validation")):
                gaps.append("NFR 缺 validation")
        if gaps:
            gap_rows.append({"id": req_id, "title": clean_text(row.get("title")), "gaps": gaps})

    if not gap_rows:
        return []

    ids = [row["id"] for row in gap_rows]
    evidence = "；".join(f"{row['id']}：{', '.join(row['gaps'])}" for row in gap_rows[:12])
    row = {
        "issue_id": f"R{round_num}-I1",
        "title": "補齊既有需求的可驗收欄位",
        "category": "clarify_requirement",
        "issue_focus": "requirement_completeness",
        "expect_outcome": "逐筆確認缺欄位是否可由現有 artifact 推得；能推得則補齊 acceptance criteria、source、risks、assumptions 與 NFR metric/validation，不能推得則形成明確 open question。",
        "sources": [{"artifact": "REQ", "ids": ids, "evidence": evidence}],
        "expected_actions": {"analyst": ["refine_requirement"]},
        "suggested_participants": ["analyst", "user"],
        "participant_reasoning": {
            "analyst": "判斷哪些欄位可由既有需求推得並寫回 REQ",
            "user": "確認可接受條件、風險與假設是否符合利害關係人期待",
        },
        "issue_level": "blocking",
        "importance": "high",
        "reason": "既有 REQ 缺少可驗收、可追蹤或可風險管理的欄位，會直接影響 SRS 是否能定稿。",
    }
    normalized = issue_proposal(row, proposed_by="mediator", round_num=round_num, index=880)
    return [normalized] if normalized else []


def model_alignment_gap_proposals(
    artifact: Dict[str, Any],
    *,
    round_num: int,
) -> List[Dict[str, Any]]:
    req_ids = {
        clean_text(row.get("id"))
        for row in list_values((artifact or {}).get("REQ"))
        if isinstance(row, dict) and clean_text(row.get("id"))
    }
    models = [
        row for row in list_values((artifact or {}).get("system_models"))
        if isinstance(row, dict)
    ]
    if not req_ids or not models:
        return []

    model_related: Dict[str, List[str]] = {}
    for row in models:
        model_id = clean_text(row.get("id") or row.get("name"))
        related = [
            clean_text(item)
            for item in list_values(row.get("related_requirement_ids"))
            if clean_text(item)
        ]
        if model_id:
            model_related[model_id] = related

    uncovered = sorted(req_ids - {rid for ids in model_related.values() for rid in ids})
    model_without_req = sorted(mid for mid, ids in model_related.items() if not ids)
    if not uncovered and not model_without_req:
        return []

    evidence_parts: List[str] = []
    source_ids: List[str] = []
    if uncovered:
        source_ids.extend(uncovered)
        evidence_parts.append("REQ 未被模型關聯：" + ", ".join(uncovered[:12]))
    if model_without_req:
        source_ids.extend(model_without_req)
        evidence_parts.append("模型缺 related_requirement_ids：" + ", ".join(model_without_req[:12]))

    row = {
        "issue_id": f"R{round_num}-I2",
        "title": "對齊需求與系統模型關聯",
        "category": "align_model",
        "issue_focus": "model_alignment",
        "expect_outcome": "確認未關聯的 REQ 是否需要補模型、補 related_requirement_ids、調整模型描述，或把模型揭露的缺口回寫成需求/open question。",
        "sources": [{"artifact": "system_models", "ids": list(dict.fromkeys(source_ids)), "evidence": "；".join(evidence_parts)}],
        "expected_actions": {"modeler": ["system_modeling"]},
        "suggested_participants": ["modeler", "analyst"],
        "participant_reasoning": {
            "modeler": "檢查模型與 REQ 關聯是否缺漏或不一致",
            "analyst": "判斷模型缺口是否需要回寫需求或 open question",
        },
        "issue_level": "blocking",
        "importance": "high",
        "reason": "需求與模型沒有互相追蹤時，SRS 和設計草稿容易出現流程、狀態、actor 或資料責任不一致。",
    }
    normalized = issue_proposal(row, proposed_by="mediator", round_num=round_num, index=881)
    return [normalized] if normalized else []


def feedback_gap_proposals(
    artifact: Dict[str, Any],
    *,
    round_num: int,
) -> List[Dict[str, Any]]:
    feedback = artifact.get("feedback") if isinstance((artifact or {}).get("feedback"), dict) else {}
    rows: List[Dict[str, Any]] = []
    for section in ("findings", "constraints", "risks", "recommendations"):
        for idx, item in enumerate(list_values(feedback.get(section)), 1):
            if not isinstance(item, dict):
                continue
            item_id = clean_text(item.get("id") or f"{section}.{idx}")
            text = clean_text(item.get("text") or item.get("title") or item.get("summary"))
            related = [
                clean_text(value)
                for value in list_values(item.get("related_requirement_ids"))
                if clean_text(value)
            ]
            if item_id and text and not related:
                rows.append({"id": item_id, "section": section, "text": text})
    if not rows:
        return []

    evidence = "；".join(f"{row['id']}({row['section']})：{row['text']}" for row in rows[:8])
    row = {
        "issue_id": f"R{round_num}-I3",
        "title": "確認 feedback 風險與限制是否回寫需求",
        "category": "clarify_requirement",
        "issue_focus": "requirement_completeness",
        "expect_outcome": "判斷 feedback 中尚未連到 REQ 的 finding、constraint、risk 或 recommendation 是否應回寫為需求欄位、風險、假設、驗收條件或 open question。",
        "sources": [{"artifact": "feedback", "ids": [row["id"] for row in rows], "evidence": evidence}],
        "expected_actions": {"analyst": ["refine_requirement"]},
        "suggested_participants": ["analyst", "expert"],
        "participant_reasoning": {
            "analyst": "決定 feedback 如何落到 REQ 欄位或 open question",
            "expert": "確認領域限制、風險與建議是否仍成立",
        },
        "issue_level": "improvement",
        "importance": "medium",
        "reason": "未追蹤的 feedback 可能代表風險、限制或專家建議沒有被 SRS 吸收。",
    }
    normalized = issue_proposal(row, proposed_by="mediator", round_num=round_num, index=882)
    return [normalized] if normalized else []


def deterministic_issue_proposals(
    artifact: Dict[str, Any],
    *,
    round_num: int,
) -> List[Dict[str, Any]]:
    proposals: List[Dict[str, Any]] = []
    for builder in (
        requirement_field_gap_proposals,
        model_alignment_gap_proposals,
        feedback_gap_proposals,
    ):
        proposals.extend(builder(artifact, round_num=round_num))
    return proposals


def final_verification_proposals(
    artifact: Dict[str, Any],
    *,
    round_num: int,
) -> List[Dict[str, Any]]:
    backlog = [
        row for row in list_values((artifact or {}).get("issue_backlog"))
        if isinstance(row, dict)
        and clean_text(row.get("importance")).lower() in {"high", "medium"}
    ]
    detector_rows = deterministic_issue_proposals(artifact, round_num=round_num)
    source_ids = [
        clean_text(row.get("issue_id") or row.get("id"))
        for row in backlog
        if clean_text(row.get("issue_id") or row.get("id"))
    ]
    for row in detector_rows:
        source_ids.append(clean_text(row.get("issue_id") or row.get("id")))
    source_ids = list(dict.fromkeys([sid for sid in source_ids if sid]))
    if not source_ids:
        return []

    row = {
        "issue_id": f"R{round_num}-I99",
        "title": "最終檢查未收斂的需求與模型缺口",
        "category": "clarify_requirement",
        "issue_focus": "requirement_completeness",
        "expect_outcome": "確認本輪結束前仍存在的 high/medium backlog 或 deterministic 缺口，決定立即補寫、形成 open question，或明確保留到下一輪處理。",
        "sources": [{"artifact": "issue_proposals", "ids": source_ids, "evidence": "最後檢查仍有高/中重要度候選或可偵測缺口未收斂。"}],
        "suggested_participants": ["analyst", "modeler", "expert", "user"],
        "participant_reasoning": {
            "analyst": "確認需求欄位與 open question 是否足以支撐 SRS",
            "modeler": "確認模型對齊缺口是否仍阻礙設計草稿",
            "expert": "確認風險、限制與建議是否已被吸收",
            "user": "確認剩餘缺口是否影響使用者接受標準",
        },
        "issue_level": "blocking",
        "importance": "high",
        "reason": "最後一輪前若仍有具體缺口，必須明確處理或保留，避免 MoM 有討論但 artifact 未收斂。",
    }
    normalized = issue_proposal(row, proposed_by="mediator", round_num=round_num, index=990)
    return [normalized] if normalized else []


def pre_round_review(
    proposals: List[Dict[str, Any]],
    *,
    round_num: int,
    default_issue_count: int = 0,
) -> Dict[str, Any]:
    rows = [row for row in (proposals or []) if isinstance(row, dict)]
    focus_counts: Dict[str, int] = {}
    source_counts: Dict[str, int] = {}
    proposer_counts: Dict[str, int] = {}
    blocking_ids: List[str] = []
    high_ids: List[str] = []
    for row in rows:
        focus = clean_text(row.get("issue_focus") or row.get("category")) or "unspecified"
        focus_counts[focus] = focus_counts.get(focus, 0) + 1
        proposer = clean_text(row.get("proposed_by")) or "unknown"
        proposer_counts[proposer] = proposer_counts.get(proposer, 0) + 1
        if clean_text(row.get("issue_level")).lower() == "blocking":
            issue_id = clean_text(row.get("issue_id") or row.get("id"))
            if issue_id:
                blocking_ids.append(issue_id)
        if clean_text(row.get("importance")).lower() == "high":
            issue_id = clean_text(row.get("issue_id") or row.get("id"))
            if issue_id:
                high_ids.append(issue_id)
        for source in row.get("sources") or []:
            if not isinstance(source, dict):
                continue
            artifact_name = clean_text(source.get("artifact")) or "unknown"
            source_counts[artifact_name] = source_counts.get(artifact_name, 0) + 1

    selected_focus = [
        key for key, _ in sorted(focus_counts.items(), key=lambda item: (-item[1], item[0]))[:4]
    ]
    source_summary = [
        key for key, _ in sorted(source_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    ]
    reasons: List[str] = []
    if default_issue_count:
        reasons.append(f"本輪有 {default_issue_count} 筆預設正式會議議題。")
    if rows:
        reasons.append(f"收集到 {len(rows)} 筆一般候選議題。")
    if selected_focus:
        reasons.append("主要焦點：" + "、".join(selected_focus) + "。")
    if source_summary:
        reasons.append("主要來源：" + "、".join(source_summary) + "。")
    if blocking_ids:
        reasons.append(f"{len(blocking_ids)} 筆 blocking 候選需要優先 triage。")
    if not reasons:
        reasons.append("本輪沒有可用候選議題。")

    return {
        "schema_version": "pre_round_review.v1",
        "round": round_num,
        "proposal_count": len(rows),
        "default_issue_count": default_issue_count,
        "selected_focus": selected_focus,
        "source_summary": source_summary,
        "proposer_counts": proposer_counts,
        "blocking_issue_ids": list(dict.fromkeys(blocking_ids)),
        "high_importance_issue_ids": list(dict.fromkeys(high_ids)),
        "reason": " ".join(reasons),
    }


def save_pre_round_review(
    artifact: Dict[str, Any],
    review: Dict[str, Any],
) -> None:
    if not isinstance(artifact, dict) or not isinstance(review, dict):
        return
    rows = [
        row for row in (artifact.get("pre_round_reviews") or [])
        if isinstance(row, dict)
        and int(row.get("round") or -1) != int(review.get("round") or -2)
    ]
    rows.append(review)
    artifact["pre_round_reviews"] = rows


# ========
# Defines draft gaps function for this module workflow.
# ========
def draft_gaps(
    draft_md: str,
    *,
    round_num: int,
) -> List[Dict[str, Any]]:
    if not str(draft_md or "").strip():
        return []

    req_blocks: List[Dict[str, Any]] = []
    matches = list(re.finditer(r"^###\s+(REQ-\d+):\s*(.+?)\s*$", draft_md, re.MULTILINE))
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(draft_md)
        block = draft_md[start:end]
        req_blocks.append(
            {
                "id": match.group(1).strip(),
                "title": match.group(2).strip(),
                "block": block,
            }
        )

    if not req_blocks:
        return []

    weak_rows: List[Dict[str, str]] = []
    for row in req_blocks:
        req_id = row["id"]
        block = row["block"]
        reasons: List[str] = []
        is_nfr = bool(re.search(r"^\s*-\s*Type:\s*non-functional\s*$", block, re.MULTILINE))
        title = row["title"]
        if any(term in title for term in STAKEHOLDER_TITLE_TERMS):
            reasons.append("Title 可能混入 stakeholder，需確認是否可改成需求核心短語")

        if is_nfr and not re.search(r"^\s*-\s*Category:\s*(.+?)\s*$", block, re.MULTILINE):
            reasons.append("NFR 缺 Category")

        description_match = re.search(r"^\s*-\s*Description:\s*(.+?)\s*$", block, re.MULTILINE)
        if description_match:
            description = description_match.group(1).strip()
            if description.count("；") >= 2 or description.count("，") >= 5:
                reasons.append("Description 可能混入多個能力或條件")

        validation_match = re.search(r"^\s*-\s*Validation:\s*(.+?)\s*$", block, re.MULTILINE)
        if validation_match:
            validation = validation_match.group(1).strip()
            if validation.lower() in {"test", "inspection", "walkthrough"}:
                reasons.append(f"Validation 只寫泛稱 `{validation}`")
        elif is_nfr:
            reasons.append("NFR 缺 Validation")

        metric_match = re.search(r"^\s*-\s*Metric:\s*(.+?)\s*$", block, re.MULTILINE)
        if metric_match:
            metric = metric_match.group(1).strip()
            if any(term in metric for term in WEAK_FIELD_TERMS):
                reasons.append(f"Metric 仍含待確認或抽象條件：{metric}")
        elif is_nfr:
            reasons.append("NFR 缺 Metric")

        acceptance_match = re.search(
            r"^\s*-\s*Acceptance Criteria:\s*(.*?)(?=^\s*-\s*[A-Z][A-Za-z _-]+:|^###\s+REQ-|\Z)",
            block,
            re.MULTILINE | re.DOTALL,
        )
        if acceptance_match:
            acceptance = acceptance_match.group(1).strip()
            if not acceptance:
                reasons.append("Acceptance Criteria 為空")
            elif any(term in acceptance for term in ("待確認", "待協議", "細節待確認")):
                reasons.append("Acceptance Criteria 仍含待確認內容")
        else:
            reasons.append("缺 Acceptance Criteria")

        source_match = re.search(r"^\s*-\s*Source:\s*(.+?)\s*$", block, re.MULTILINE)
        if source_match:
            source_text = source_match.group(1).strip()
            if source_text and not re.search(r"\b(?:URL-\d+|R\d+-M\d+|SM-\d+|Feedback)\b", source_text):
                reasons.append("Source 不是可追蹤 ID")

        if reasons:
            weak_rows.append(
                {
                    "id": req_id,
                    "title": row["title"],
                    "reason": "；".join(reasons),
                }
            )

    if not weak_rows:
        return []

    ids = [row["id"] for row in weak_rows]
    evidence = "；".join(f"{row['id']}：{row['reason']}" for row in weak_rows)

    row = {
        "title": "補強既有需求的驗收與品質欄位",
        "category": "clarify_requirement",
        "issue_focus": "requirement_completeness",
        "expect_outcome": "針對 latest draft 中多筆 REQ-* 的弱化欄位，討論並補強 acceptance criteria、NFR category、metric、validation、風險或假設，使需求更可測試、可追溯並可寫入 SRS。",
        "sources": [
            {
                "artifact": "REQ",
                "ids": ids,
                "evidence": evidence,
            }
        ],
        "issue_level": "blocking",
        "importance": "high",
        "reason": "latest draft 中多筆既有 REQ-* 欄位雖存在但內容仍抽象、待確認或不可驗收；這是需求完整性問題，應優先於新增需求處理。",
    }
    normalized = issue_proposal(
        row,
        proposed_by="analyst",
        round_num=round_num,
        index=900,
    )
    return [normalized] if normalized else []


# ========
# Defines open question proposals function for this module workflow.
# ========
def open_question_proposals(
    artifact: Dict[str, Any],
    *,
    round_num: int,
) -> List[Dict[str, Any]]:
    if not isinstance(artifact, dict):
        return []

    rows = [
        row for row in (artifact.get("open_questions") or [])
        if isinstance(row, dict)
        and str(row.get("question") or "").strip()
        and str(row.get("status") or "").strip().lower() != "answered"
    ]
    if not rows:
        return []

    expected_actions: Dict[str, List[str]] = {}
    participants: List[str] = []
    source_ids: List[str] = []
    question_lines: List[str] = []
    for index, row in enumerate(rows, 1):
        qid = str(row.get("id") or f"OQ-{index}").strip()
        question = str(row.get("question") or "").strip()
        to_agent = str(row.get("to") or row.get("to_agent") or "").strip()
        if qid:
            source_ids.append(qid)
        if question:
            question_lines.append(f"{qid}: {question}")
        if to_agent:
            participants.append(to_agent)
            expected_actions.setdefault(to_agent, [])
            if "answer_question" not in expected_actions[to_agent]:
                expected_actions[to_agent].append("answer_question")

    if not question_lines:
        return []

    row = {
        "issue_id": f"OQ-R{round_num}",
        "title": "回答待釐清需求問題",
        "category": "clarify_requirement",
        "issue_focus": "open_question_answer",
        "expect_outcome": "針對目前尚未回答的 Open Questions 取得回覆，必要時供後續需求、風險、假設或模型調整使用。",
        "sources": [
            {
                "artifact": "open_questions",
                "ids": list(dict.fromkeys(source_ids)),
                "evidence": "；".join(question_lines),
            }
        ],
        "expected_actions": expected_actions,
        "suggested_participants": list(dict.fromkeys(participants)),
        "issue_level": "blocking",
        "importance": "high",
        "reason": "尚未回答的 Open Questions 可能影響需求、驗收、風險、假設或模型邊界，應於一般正式會議中明確回覆。",
    }
    normalized = issue_proposal(
        row,
        proposed_by="mediator",
        round_num=round_num,
        index=950,
    )
    return [normalized] if normalized else []


# ========
# Defines collect issue proposals function for this module workflow.
# ========
def collect_issue_proposals(
    coordinator: Any,
    artifact: Dict[str, Any],
    *,
    round_num: int,
) -> List[Dict[str, Any]]:
    general_enabled = stage_enabled(coordinator.flow.config, "general_formal_meeting", True)
    proposals: List[Dict[str, Any]] = []
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
            row = dict(row)
            next_num = len(proposals) + 1
            while f"R{round_num}-I{next_num}" in seen_issue_ids:
                next_num += 1
            issue_id = f"R{round_num}-I{next_num}"
            row["issue_id"] = issue_id
        proposals.append(row)
        if issue_id:
            seen_issue_ids.add(issue_id)
        return True

    if general_enabled:
        latest_version = coordinator.flow.store.get_draft_version()
        draft_md = coordinator.flow.store.load_draft(latest_version) if latest_version >= 0 else ""
        if draft_md.strip():
            artifact_slices = coordinator.proposal_artifact_slices(
                artifact,
                draft_version=latest_version,
            )
            proposal_artifact = {
                "latest_draft": compact_markdown_context(draft_md),
                "artifact_slices": artifact_slices,
            }
            registry = getattr(coordinator.flow, "registry", None)
            proposal_safety_limit = 20
            for row in deterministic_issue_proposals(
                artifact,
                round_num=round_num,
            ):
                append_proposal(row)
            for agent_name in ("analyst", "expert", "modeler", "user"):
                agent = registry.get(agent_name) if registry else None
                if not agent or not hasattr(agent, "propose_issues"):
                    continue
                try:
                    rows = agent.propose_issues(
                        proposal_artifact,
                        round_num=round_num,
                        max_items=proposal_safety_limit,
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
            for row in draft_gaps(
                draft_md,
                round_num=round_num,
            ):
                append_proposal(row)
            for row in open_question_proposals(
                artifact,
                round_num=round_num,
            ):
                append_proposal(row)
            meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
            config = getattr(coordinator.flow, "config", {}) or {}
            try:
                end_round = int(meta.get("meeting_end_round") or config.get("rounds", 1) or 1)
            except (TypeError, ValueError):
                end_round = 1
            if int(round_num or 0) >= end_round:
                for row in final_verification_proposals(
                    artifact,
                    round_num=round_num,
                ):
                    append_proposal(row)
            if proposals or invalid_count:
                meta = artifact.setdefault("meta", {})
                meta[f"draft_issue_proposals_round_{round_num}"] = True
                coordinator.flow.logger.info(
                    "Issue Proposal：latest draft 產生 %s 筆一般候選，淘汰 %s 筆",
                    len(proposals),
                    invalid_count,
                )

    return proposals


# ========
# Defines apply mediator updates function for this module workflow.
# ========
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



# ========
# Defines run meeting round block function for this module workflow.
# ========
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
            **compact_markdown_context(latest_draft),
        }
    default_issues: List[Dict[str, Any]] = []
    if int(round_num or 0) == 1:
        if stage_enabled(coordinator.flow.config, "default_formal_meeting", True):
            default_issues = default_meeting_issues(
                coordinator,
                meeting_artifact,
                round_num=round_num,
            )
        else:
            coordinator.flow.logger.info("Default Formal Meeting：stage disabled，略過預設正式會議議題")

    if default_issues:
        existing = [
            row for row in (artifact.get("meeting_issues", []) or [])
            if isinstance(row, dict)
        ]
        round_issues = [
            row for row in existing
            if int(row.get("round") or -1) == int(round_num)
        ]
        seen_current_ids = {
            clean_text(row.get("id"))
            for row in round_issues
            if clean_text(row.get("id"))
        }
        for issue in default_issues:
            if not isinstance(issue, dict):
                continue
            issue_id = clean_text(issue.get("id"))
            if issue_id and issue_id in seen_current_ids:
                continue
            row = {**issue, "round": round_num}
            round_issues.append(row)
            if clean_text(row.get("id")):
                seen_current_ids.add(clean_text(row.get("id")))
        review = pre_round_review([], round_num=round_num, default_issue_count=len(round_issues))
        save_pre_round_review(artifact, review)
        preserved_other_rounds = [
            row for row in existing
            if int(row.get("round") or -1) != int(round_num)
        ]
        artifact["meeting_issues"] = [*preserved_other_rounds, *round_issues]
        normalize_issue_ids_for_storage(artifact)
        round_issues = [
            row for row in (artifact.get("meeting_issues", []) or [])
            if isinstance(row, dict)
            and int(row.get("round") or -1) == int(round_num)
        ]
        meeting_artifact["meeting_issues"] = list(round_issues)
        meeting_artifact["pre_round_reviews"] = list(artifact.get("pre_round_reviews", []) or [])
        coordinator.flow.store.save_artifact(artifact)
        current_round_proposals: List[Dict[str, Any]] = []
    else:
        proposal_step_id = f"formal_meeting.round_{round_num}.propose_issues"
        coordinator.flow.logger.step_started(
            "formal_meeting",
            proposal_step_id,
            "Agent 議題提案",
            agent="mediator",
            message="Agent 正在提出候選議題 ...",
        )
        current_round_proposals = collect_issue_proposals(
            coordinator, meeting_artifact, round_num=round_num,
        )
        current_round_proposals, _ = renumber_issue_proposals(current_round_proposals)
        max_issues = max(1, int(getattr(coordinator.flow.config, "get", lambda *_: 5)("max_issues", 5) or 5))
        if current_round_proposals:
            current_round_proposals = apply_human_issue_proposals(
                current_round_proposals,
                Collect.meeting_issue_proposal_review(
                    current_round_proposals,
                    round_num,
                    max_issues=max_issues,
                ),
                round_num=round_num,
                max_issues=max_issues,
            )
        else:
            coordinator.flow.logger.info("Issue Proposal：無候選議題，略過人工介入")
        review = pre_round_review(current_round_proposals, round_num=round_num)
        save_pre_round_review(artifact, review)
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
    normalize_issue_ids_for_storage(artifact)
    coordinator.flow.store.save_artifact(artifact)

    current_round_proposals = [
        row for row in (artifact.get("issue_proposals", []) or [])
        if isinstance(row, dict)
        and int(row.get("round") or -1) == int(round_num)
    ]
    meeting_artifact["issue_proposals"] = current_round_proposals
    meeting_artifact["meeting_issues"] = [
        row for row in (artifact.get("meeting_issues", []) or [])
        if isinstance(row, dict)
        and int(row.get("round") or -1) == int(round_num)
    ]
    meeting_artifact["pre_round_reviews"] = list(artifact.get("pre_round_reviews", []) or [])
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
