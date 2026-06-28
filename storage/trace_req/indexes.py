from dataclasses import dataclass
from typing import Any, Dict, List, Set

from .ids import meeting_order_key, trace_req_first_id, trace_req_ids


@dataclass
class TraceReqIndexes:
    req_to_srs: Dict[str, str]
    source_to_srs: Dict[str, List[str]]
    discussion_issues: List[Dict[str, Any]]
    meeting_id_by_category: Dict[str, List[str]]
    meeting_issue_by_id: Dict[str, Dict[str, Any]]
    entry_meeting_id: str
    formalization_meeting_id: str
    issue_req_ids_by_meeting: Dict[str, List[str]]
    conflict_rows: List[Dict[str, Any]]
    conflicts_by_req_id: Dict[str, List[str]]
    conflict_target_ids: Set[str]


def trace_conflict_requirement_ids(item: Dict[str, Any]) -> List[str]:
    req_ids = [
        str(req_id).strip()
        for req_id in (item.get("requirement_ids") or [])
        if str(req_id).strip()
    ]
    for req_id in item.get("related_user_requirements") or []:
        clean_id = str(req_id).strip()
        if clean_id and clean_id not in req_ids:
            req_ids.append(clean_id)
    for req in item.get("requirements") or []:
        if not isinstance(req, dict):
            continue
        req_id = str(req.get("id") or "").strip()
        if req_id and req_id not in req_ids:
            req_ids.append(req_id)
    return req_ids


def build_trace_req_indexes(data: Dict[str, Any]) -> TraceReqIndexes:
    req_to_srs = {
        str(req.get("id") or "").strip(): str(req.get("srs_id") or "").strip()
        for req in (data.get("REQ") or [])
        if isinstance(req, dict)
        and str(req.get("id") or "").strip()
        and str(req.get("srs_id") or "").strip()
    }

    source_to_srs: Dict[str, List[str]] = {}
    for req in data.get("REQ") or []:
        if not isinstance(req, dict):
            continue
        srs_id = req_to_srs.get(str(req.get("id") or "").strip(), "")
        if not srs_id:
            continue
        for source_id in trace_req_ids(req.get("source")):
            source_to_srs.setdefault(source_id, []).append(srs_id)

    discussion_issues: List[Dict[str, Any]] = []
    for discussion in data.get("discussions") or []:
        if not isinstance(discussion, dict):
            continue
        for issue in discussion.get("issues") or []:
            if isinstance(issue, dict):
                discussion_issues.append(issue)

    meeting_id_by_category: Dict[str, List[str]] = {}
    meeting_issue_by_id: Dict[str, Dict[str, Any]] = {}
    for issue in discussion_issues:
        meeting_id = str(issue.get("meeting_id") or "").strip()
        category = str(issue.get("category") or "").strip()
        if not meeting_id:
            continue
        meeting_issue_by_id[meeting_id] = issue
        if category:
            meeting_id_by_category.setdefault(category, [])
            if meeting_id not in meeting_id_by_category[category]:
                meeting_id_by_category[category].append(meeting_id)

    for category, meeting_ids in list(meeting_id_by_category.items()):
        meeting_id_by_category[category] = sorted(meeting_ids, key=meeting_order_key)

    entry_meeting_id = (
        trace_req_first_id(meeting_id_by_category.get("resolve_conflict"))
        or ("R1-M1" if "R1-M1" in meeting_issue_by_id else "")
    )
    formalization_meeting_id = (
        trace_req_first_id(meeting_id_by_category.get("formalize_requirement"))
        or ("R1-M2" if "R1-M2" in meeting_issue_by_id else "")
    )

    issue_req_ids_by_meeting: Dict[str, List[str]] = {}
    for issue in discussion_issues:
        meeting_id = str(issue.get("meeting_id") or "").strip()
        if not meeting_id:
            continue
        resolution = issue.get("resolution") if isinstance(issue.get("resolution"), dict) else {}
        affected_req_ids = trace_req_ids(resolution.get("affected_requirement_ids"))
        if affected_req_ids:
            issue_req_ids_by_meeting[meeting_id] = affected_req_ids

    conflict = data.get("conflict") if isinstance(data.get("conflict"), dict) else {}
    conflict_rows: List[Dict[str, Any]] = [
        item
        for section in ("pairs", "multiple", "report", "resolved_report")
        for item in (conflict.get(section) or [])
        if isinstance(item, dict)
    ]

    conflicts_by_req_id: Dict[str, List[str]] = {}
    for item in conflict_rows:
        conflict_id = str(item.get("id") or item.get("source_id") or "").strip()
        if not conflict_id:
            continue
        for related_id in trace_conflict_requirement_ids(item):
            for srs_id in source_to_srs.get(related_id, []):
                for req_id, mapped_srs_id in req_to_srs.items():
                    if mapped_srs_id == srs_id:
                        conflicts_by_req_id.setdefault(req_id, [])
                        if conflict_id not in conflicts_by_req_id[req_id]:
                            conflicts_by_req_id[req_id].append(conflict_id)
            if related_id in req_to_srs:
                conflicts_by_req_id.setdefault(related_id, [])
                if conflict_id not in conflicts_by_req_id[related_id]:
                    conflicts_by_req_id[related_id].append(conflict_id)

    conflict_target_ids = {
        req_to_srs.get(req_id, "")
        for req_id, conflict_ids in conflicts_by_req_id.items()
        if conflict_ids and req_to_srs.get(req_id, "")
    }

    return TraceReqIndexes(
        req_to_srs=req_to_srs,
        source_to_srs=source_to_srs,
        discussion_issues=discussion_issues,
        meeting_id_by_category=meeting_id_by_category,
        meeting_issue_by_id=meeting_issue_by_id,
        entry_meeting_id=entry_meeting_id,
        formalization_meeting_id=formalization_meeting_id,
        issue_req_ids_by_meeting=issue_req_ids_by_meeting,
        conflict_rows=conflict_rows,
        conflicts_by_req_id=conflicts_by_req_id,
        conflict_target_ids=conflict_target_ids,
    )
