from typing import Any, Dict, List

from .ids import meeting_order_key, trace_req_first_id, trace_req_ids, trace_req_target_id, is_meeting_id
from .indexes import TraceReqIndexes, trace_conflict_requirement_ids
from .schema import append_trace_req_row


def collect_trace_req_rows(data: Dict[str, Any], indexes: TraceReqIndexes) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def trace_target_for_sources(value: Any) -> str:
        direct = trace_req_target_id(value, indexes.req_to_srs)
        if direct:
            return direct
        for source_id in trace_req_ids(value):
            targets = indexes.source_to_srs.get(source_id) or []
            if targets:
                return targets[0]
        return ""

    collect_url_trace(data, indexes, rows, seen)
    collect_req_trace(data, indexes, rows, seen)
    collect_feedback_trace(data, trace_target_for_sources, rows, seen)
    collect_system_model_trace(data, trace_target_for_sources, rows, seen)
    collect_conflict_trace(indexes, trace_target_for_sources, rows, seen)
    collect_meeting_trace(data, indexes, rows, seen)
    collect_discussion_issue_trace(indexes, rows, seen)
    return rows


def collect_url_trace(
    data: Dict[str, Any],
    indexes: TraceReqIndexes,
    rows: List[Dict[str, Any]],
    seen: set[str],
) -> None:
    for url in data.get("URL") or []:
        if not isinstance(url, dict):
            continue
        url_id = str(url.get("id") or "").strip()
        if not url_id:
            continue
        target_srs_ids = list(dict.fromkeys(indexes.source_to_srs.get(url_id, [])))
        if not target_srs_ids:
            continue
        source_ids = trace_req_ids(url.get("source_id")) + trace_req_ids(url.get("related_statement_ids"))
        for source_id in list(dict.fromkeys(source_ids)):
            for srs_id in target_srs_ids:
                append_trace_req_row(
                    rows,
                    seen,
                    target_requirement_id=srs_id,
                    from_id=source_id,
                    to_id=url_id,
                    edge_label="分析",
                    role="main_chain",
                    stage="requirements",
                    agent="analyst",
                    confidence="explicit",
                )


def collect_req_trace(
    data: Dict[str, Any],
    indexes: TraceReqIndexes,
    rows: List[Dict[str, Any]],
    seen: set[str],
) -> None:
    for req in data.get("REQ") or []:
        if not isinstance(req, dict):
            continue
        req_id = str(req.get("id") or "").strip()
        if not req_id:
            continue
        append_trace_req_row(
            rows,
            seen,
            target_requirement_id=indexes.req_to_srs.get(req_id, ""),
            from_id=trace_req_first_id(req.get("source")),
            to_id=req_id,
            edge_label="分析",
            role="main_chain",
            stage="requirements",
            agent="analyst",
            reason=str(req.get("trace_reason") or "").strip(),
            confidence=str(req.get("trace_confidence") or "explicit").strip() or "explicit",
        )
        srs_id = str(req.get("srs_id") or "").strip()
        if srs_id:
            append_trace_req_row(
                rows,
                seen,
                target_requirement_id=srs_id,
                from_id=req_id,
                to_id=srs_id,
                edge_label="",
                role="main_chain",
                stage="srs",
                agent="documentor",
            )


def collect_feedback_trace(
    data: Dict[str, Any],
    trace_target_for_sources,
    rows: List[Dict[str, Any]],
    seen: set[str],
) -> None:
    feedback = data.get("feedback") if isinstance(data.get("feedback"), dict) else {}
    feedback_index = 0
    for section in ("findings", "constraints", "risks", "recommendations"):
        for item in feedback.get(section) or []:
            if not isinstance(item, dict):
                continue
            feedback_index += 1
            append_trace_req_row(
                rows,
                seen,
                target_requirement_id=trace_target_for_sources(item.get("related_requirement_ids")),
                from_id=trace_req_first_id(item.get("related_requirement_ids")),
                to_id=f"FB-{feedback_index}",
                edge_label="依據",
                role="supporting",
                style="dashed",
                stage="domain_research",
                agent="expert",
                reason=str(item.get("trace_reason") or "").strip(),
                confidence=str(item.get("trace_confidence") or ("explicit" if item.get("related_requirement_ids") else "missing")).strip() or "missing",
            )
            for source_id in trace_req_ids(item.get("source_ids")):
                if is_meeting_id(source_id):
                    append_trace_req_row(
                        rows,
                        seen,
                        target_requirement_id=trace_target_for_sources(item.get("related_requirement_ids")),
                        from_id=f"FB-{feedback_index}",
                        to_id=source_id,
                        edge_label="",
                        role="supporting",
                        style="dashed",
                        stage="domain_research",
                        agent="expert",
                        confidence=str(item.get("trace_confidence") or "explicit").strip() or "explicit",
                        reason=str(item.get("trace_reason") or "").strip(),
                    )


def collect_system_model_trace(
    data: Dict[str, Any],
    trace_target_for_sources,
    rows: List[Dict[str, Any]],
    seen: set[str],
) -> None:
    for model in data.get("system_models") or []:
        if not isinstance(model, dict):
            continue
        model_id = str(model.get("id") or "").strip()
        if not model_id:
            continue
        append_trace_req_row(
            rows,
            seen,
            target_requirement_id=trace_target_for_sources(model.get("related_requirement_ids")),
            from_id=trace_req_first_id(model.get("related_requirement_ids")),
            to_id=model_id,
            edge_label="建模",
            role="supporting",
            style="dashed",
            stage="system_model",
            agent="modeler",
            reason=str(model.get("description") or "").strip(),
        )
        for source_id in trace_req_ids(model.get("source_ids")):
            if is_meeting_id(source_id):
                append_trace_req_row(
                    rows,
                    seen,
                    target_requirement_id=trace_target_for_sources(model.get("related_requirement_ids")),
                    from_id=model_id,
                    to_id=source_id,
                    edge_label="",
                    role="supporting",
                    style="dashed",
                    stage="system_model",
                    agent="modeler",
                    reason=str(model.get("description") or "").strip(),
                )


def collect_conflict_trace(
    indexes: TraceReqIndexes,
    trace_target_for_sources,
    rows: List[Dict[str, Any]],
    seen: set[str],
) -> None:
    for item in indexes.conflict_rows:
        conflict_id = str(item.get("id") or item.get("source_id") or "").strip()
        req_ids = trace_conflict_requirement_ids(item)
        if not conflict_id or len(req_ids) < 2:
            continue
        for source_id in req_ids:
            append_trace_req_row(
                rows,
                seen,
                target_requirement_id=trace_target_for_sources(source_id),
                from_id=source_id,
                to_id=conflict_id,
                edge_label="衝突",
                role="main_chain",
                stage="conflict_detection",
                agent="analyst",
                reason=str(item.get("description") or "").strip(),
            )


def collect_meeting_trace(
    data: Dict[str, Any],
    indexes: TraceReqIndexes,
    rows: List[Dict[str, Any]],
    seen: set[str],
) -> None:
    if not indexes.entry_meeting_id or not indexes.formalization_meeting_id:
        return
    for req in data.get("REQ") or []:
        if not isinstance(req, dict):
            continue
        req_id = str(req.get("id") or "").strip()
        srs_id = indexes.req_to_srs.get(req_id, "")
        if not req_id or not srs_id:
            continue
        source_ids = trace_req_ids(req.get("source"))
        conflict_ids = indexes.conflicts_by_req_id.get(req_id, [])
        if conflict_ids:
            for conflict_id in conflict_ids:
                append_trace_req_row(
                    rows,
                    seen,
                    target_requirement_id=srs_id,
                    from_id=conflict_id,
                    to_id=indexes.entry_meeting_id,
                    edge_label="解決",
                    role="main_chain",
                    stage="formal_meeting",
                    agent="mediator",
                    reason=meeting_decision(indexes, indexes.entry_meeting_id),
                )
            append_trace_req_row(
                rows,
                seen,
                target_requirement_id=srs_id,
                from_id=indexes.entry_meeting_id,
                to_id=indexes.formalization_meeting_id,
                edge_label="正式化",
                role="main_chain",
                stage="formal_meeting",
                agent="mediator",
                reason=meeting_decision(indexes, indexes.formalization_meeting_id),
            )
        else:
            for source_id in source_ids:
                append_trace_req_row(
                    rows,
                    seen,
                    target_requirement_id=srs_id,
                    from_id=source_id,
                    to_id=indexes.formalization_meeting_id,
                    edge_label="正式化",
                    role="main_chain",
                    stage="formal_meeting",
                    agent="mediator",
                    reason=meeting_decision(indexes, indexes.formalization_meeting_id),
                )

        current_meeting_id = indexes.formalization_meeting_id
        later_meeting_ids = [
            meeting_id
            for meeting_id, affected_req_ids in indexes.issue_req_ids_by_meeting.items()
            if meeting_id not in {indexes.entry_meeting_id, indexes.formalization_meeting_id}
            and req_id in affected_req_ids
        ]
        for meeting_id in sorted(later_meeting_ids, key=meeting_order_key):
            issue = indexes.meeting_issue_by_id.get(meeting_id, {})
            category = str(issue.get("category") or "").strip()
            append_trace_req_row(
                rows,
                seen,
                target_requirement_id=srs_id,
                from_id=current_meeting_id,
                to_id=meeting_id,
                edge_label="精煉" if category == "clarify_requirement" else "",
                role="main_chain",
                stage="formal_meeting",
                agent="mediator",
                reason=meeting_decision(indexes, meeting_id),
            )
            current_meeting_id = meeting_id
        append_trace_req_row(
            rows,
            seen,
            target_requirement_id=srs_id,
            from_id=current_meeting_id,
            to_id=srs_id,
            edge_label="",
            role="main_chain",
            stage="formal_meeting",
            agent="mediator",
        )


def collect_discussion_issue_trace(
    indexes: TraceReqIndexes,
    rows: List[Dict[str, Any]],
    seen: set[str],
) -> None:
    for issue in indexes.discussion_issues:
        meeting_id = str(issue.get("meeting_id") or "").strip()
        resolution = issue.get("resolution") if isinstance(issue.get("resolution"), dict) else {}
        affected_req_ids = trace_req_ids(resolution.get("affected_requirement_ids"))
        affected_conflict_ids = trace_req_ids(resolution.get("affected_conflict_ids"))
        issue_source_ids: List[str] = []
        trace = issue.get("trace") if isinstance(issue.get("trace"), dict) else {}
        issue_source_ids.extend(trace_req_ids(trace.get("artifact_ids")))
        for source in issue.get("sources") or []:
            if isinstance(source, dict):
                issue_source_ids.extend(trace_req_ids(source.get("ids")))
        issue_source_ids = list(dict.fromkeys(issue_source_ids))
        if not meeting_id or not affected_req_ids:
            continue
        target_srs_id = trace_req_target_id(affected_req_ids, indexes.req_to_srs)
        category = str(issue.get("category") or "").strip()
        if category == "formalize_requirement" and not affected_conflict_ids:
            for source_id in issue_source_ids:
                if source_id.startswith("URL-"):
                    if indexes.entry_meeting_id:
                        continue
                    append_trace_req_row(
                        rows,
                        seen,
                        target_requirement_id=target_srs_id,
                        from_id=source_id,
                        to_id=meeting_id,
                        edge_label="正式化",
                        role="main_chain",
                        stage="formal_meeting",
                        agent="mediator",
                        reason=str(resolution.get("decision") or resolution.get("summary") or "").strip(),
                    )
        if affected_conflict_ids:
            append_trace_req_row(
                rows,
                seen,
                target_requirement_id=target_srs_id,
                from_id=trace_req_first_id(affected_conflict_ids),
                to_id=meeting_id,
                edge_label="解決",
                role="main_chain",
                stage="formal_meeting",
                agent="mediator",
                reason=str(resolution.get("decision") or resolution.get("summary") or "").strip(),
            )
        if target_srs_id:
            append_trace_req_row(
                rows,
                seen,
                target_requirement_id=target_srs_id,
                from_id=meeting_id,
                to_id=target_srs_id,
                edge_label="",
                role="main_chain",
                stage="formal_meeting",
                agent="mediator",
                reason=str(resolution.get("decision") or resolution.get("summary") or "").strip(),
            )


def meeting_decision(indexes: TraceReqIndexes, meeting_id: str) -> str:
    issue = indexes.meeting_issue_by_id.get(meeting_id, {})
    resolution = issue.get("resolution") if isinstance(issue.get("resolution"), dict) else {}
    return str(resolution.get("decision") or "").strip()
