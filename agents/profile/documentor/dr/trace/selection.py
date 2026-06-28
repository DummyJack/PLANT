import re
from typing import Any, Dict, List


def select_dr_requirement_contexts(owner: Any, req_rows: List[Dict[str, Any]], appendix: Dict[str, Any]) -> List[Dict[str, Any]]:
    cls = type(owner)
    appendix = dict(appendix or {})
    source_to_req = {
        str(row.get("id") or "").strip(): [
            str(req_id).strip()
            for req_id in (row.get("related_req") or [])
            if str(req_id).strip()
        ]
        for row in appendix.get("user_requirements") or []
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }
    versioned_conflicts = []
    for row in owner.versioned_conflict_report_rows():
        source_ids = [
            str(req.get("id") or "").strip()
            for req in (row.get("requirements") or [])
            if isinstance(req, dict) and str(req.get("id") or "").strip()
        ]
        related_req = cls.dr_related_req_ids_from_sources(source_ids, source_to_req)
        if not related_req:
            continue
        versioned_conflicts.append({
            "id": row.get("id"),
            "report_version": row.get("report_version"),
            "report_file": row.get("report_file"),
            "report_id": row.get("report_id"),
            "report_title": row.get("report_title"),
            "report_markdown_entry": row.get("report_markdown_entry"),
            "raw_report_row": row.get("raw_report_row") if isinstance(row.get("raw_report_row"), dict) else dict(row),
            "related_req": related_req,
            "related_user_requirements": source_ids,
            "description": cls.clean_repeated_text(row.get("description")),
            "resolution": cls.clean_repeated_text(
                row.get("decision") or row.get("recommended_resolution") or row.get("resolution")
            ),
        })
    if versioned_conflicts:
        appendix["conflicts"] = versioned_conflicts

    srs_ids = cls.dr_srs_id_map(req_rows)
    trace_targets_by_node_id: Dict[str, set[str]] = {}
    for trace_row in appendix.get("trace_req") or []:
        if not isinstance(trace_row, dict):
            continue
        target_requirement_id = str(trace_row.get("target_requirement_id") or "").strip()
        if not target_requirement_id:
            continue
        for endpoint_key in ("from", "to"):
            endpoint_id = str(trace_row.get(endpoint_key) or "").strip()
            if endpoint_id.startswith(("FB-", "SM-")):
                trace_targets_by_node_id.setdefault(endpoint_id, set()).add(target_requirement_id)

    mom_text_by_id = owner.load_mom_text_by_id()
    req_contexts: List[Dict[str, Any]] = []

    def related_rows(section: str, req_id: str) -> List[Dict[str, Any]]:
        return [
            row
            for row in appendix.get(section) or []
            if isinstance(row, dict) and req_id in (row.get("related_req") or [])
        ]

    def evidence_is_key_for_req(
        row: Dict[str, Any],
        req_source_ids: set[str],
        conflict_source_ids: set[str],
        *,
        kind: str,
    ) -> bool:
        related_req_ids = {
            str(item).strip()
            for item in (row.get("related_req") or [])
            if str(item).strip()
        }
        related_source_ids = {
            str(item).strip()
            for item in (row.get("related_sources") or [])
            if str(item).strip()
        }
        source_ids = {
            str(item).strip()
            for item in (row.get("source_ids") or [])
            if str(item).strip()
        }
        direct_source_ids = set(req_source_ids) | set(conflict_source_ids)
        direct_hit = bool(related_source_ids.intersection(direct_source_ids))
        meeting_specific = any(re.fullmatch(r"R\d+-M\d+", item, flags=re.IGNORECASE) for item in source_ids)
        broad_evidence = len(related_req_ids) > 5 or len(related_source_ids) > 8
        if kind == "model" and broad_evidence and not meeting_specific:
            return False
        if kind == "feedback" and broad_evidence and not direct_hit and not meeting_specific:
            return False
        return direct_hit or meeting_specific or len(related_req_ids) <= 3

    for req in req_rows:
        req_id = str(req.get("id") or "").strip()
        if not req_id:
            continue
        current_srs_id = srs_ids.get(req_id, "")
        req_source_ids = set(cls.dr_req_sources(req))
        conflict_context_rows = [
            {
                "id": row.get("id"),
                "related_user_requirements": row.get("related_user_requirements"),
                "description": row.get("description"),
                "resolution": row.get("resolution"),
                "report_version": row.get("report_version"),
                "report_file": row.get("report_file"),
                "report_id": row.get("report_id"),
                "report_title": row.get("report_title"),
                "report_markdown_entry": row.get("report_markdown_entry"),
                "raw_report_row": row.get("raw_report_row"),
            }
            for row in related_rows("conflicts", req_id)
        ]
        conflict_source_ids = {
            str(item).strip()
            for row in conflict_context_rows
            for item in (row.get("related_user_requirements") or [])
            if str(item).strip()
        }

        def evidence_trace_targets_current_req(row: Dict[str, Any]) -> bool:
            row_id = str(row.get("id") or "").strip()
            targets = trace_targets_by_node_id.get(row_id)
            if not targets:
                return True
            return bool({req_id, current_srs_id}.intersection(targets))

        feedback_context_rows = [
            {
                "id": row.get("id"),
                "type": row.get("type"),
                "content": row.get("content"),
                "related_sources": row.get("related_sources"),
                "source_ids": row.get("source_ids"),
                "trace_confidence": row.get("trace_confidence"),
                "trace_reason": row.get("trace_reason"),
            }
            for row in related_rows("feedback", req_id)
            if evidence_trace_targets_current_req(row)
            if evidence_is_key_for_req(row, req_source_ids, conflict_source_ids, kind="feedback")
        ]
        model_context_rows = [
            {
                "id": row.get("id"),
                "name": row.get("name"),
                "type": row.get("type"),
                "description": row.get("description"),
                "image_path": row.get("image_path"),
                "related_req": row.get("related_req"),
                "related_sources": row.get("related_sources"),
                "source_ids": row.get("source_ids"),
            }
            for row in related_rows("system_models", req_id)
            if evidence_trace_targets_current_req(row)
            if evidence_is_key_for_req(row, req_source_ids, conflict_source_ids, kind="model")
        ]
        conflict_ids_for_req = {
            str(row.get("id") or "").strip()
            for row in conflict_context_rows
            if str(row.get("id") or "").strip()
        }

        def meeting_context_row(row: Dict[str, Any]) -> Dict[str, Any]:
            meeting_id = str(row.get("id") or "").strip()
            return {
                "id": row.get("id"),
                "category": row.get("category"),
                "topic": row.get("topic"),
                "title": cls.mom_title_from_text(mom_text_by_id.get(meeting_id, "")),
                "participants": row.get("participants"),
                "description": row.get("description"),
                "decision": row.get("decision"),
                "related_conflicts": row.get("related_conflicts"),
                "source_ids": row.get("source_ids"),
                "mom_text": mom_text_by_id.get(meeting_id, ""),
            }

        related_meeting_rows = [
            meeting_context_row(row)
            for row in appendix.get("meeting_discussions") or []
            if isinstance(row, dict)
            and (
                req_id in (row.get("related_req") or [])
                or bool(
                    conflict_ids_for_req.intersection(
                        str(conflict_id).strip()
                        for conflict_id in (row.get("related_conflicts") or [])
                        if str(conflict_id).strip()
                    )
                )
            )
        ]
        existing_meeting_ids = {
            str(row.get("id") or "").strip()
            for row in related_meeting_rows
            if str(row.get("id") or "").strip()
        }
        for row in appendix.get("meeting_discussions") or []:
            if not isinstance(row, dict):
                continue
            meeting_id = str(row.get("id") or "").strip()
            required_common_ids = {"R1-M2"}
            if conflict_context_rows:
                required_common_ids.add("R1-M1")
            if meeting_id in required_common_ids and meeting_id not in existing_meeting_ids:
                related_meeting_rows.append(meeting_context_row(row))
                existing_meeting_ids.add(meeting_id)
        if conflict_context_rows:
            conflict_round_prefixes = {
                str(row.get("id") or "").strip().split("-M", 1)[0]
                for row in related_meeting_rows
                if cls.is_conflict_resolution_meeting(row)
                and "-M" in str(row.get("id") or "").strip()
            }
            for row in appendix.get("meeting_discussions") or []:
                if not isinstance(row, dict):
                    continue
                meeting_id = str(row.get("id") or "").strip()
                if (
                    not meeting_id
                    or meeting_id in existing_meeting_ids
                    or not cls.is_requirement_formalization_meeting(row)
                ):
                    continue
                meeting_round = meeting_id.split("-M", 1)[0] if "-M" in meeting_id else ""
                if meeting_round not in conflict_round_prefixes:
                    continue
                related_meeting_rows.append(meeting_context_row(row))
                existing_meeting_ids.add(meeting_id)
        conflict_resolution_meetings = [
            row for row in related_meeting_rows
            if cls.is_conflict_resolution_meeting(row)
        ]
        if conflict_context_rows and conflict_resolution_meetings:
            meeting_context_rows = conflict_resolution_meetings + [
                row
                for row in related_meeting_rows
                if row not in conflict_resolution_meetings
            ]
        else:
            meeting_context_rows = related_meeting_rows
        meeting_context_rows = sorted(meeting_context_rows, key=cls.meeting_order_key)

        visible_source_ids = set(cls.dr_req_sources(req))
        for row in conflict_context_rows:
            visible_source_ids.update(
                str(item).strip()
                for item in (row.get("related_user_requirements") or [])
                if str(item).strip()
            )
        for row in feedback_context_rows:
            visible_source_ids.update(
                str(item).strip()
                for item in (row.get("related_sources") or [])
                if str(item).strip()
            )

        direct_user_requirements = related_rows("user_requirements", req_id)
        expanded_user_requirements = [
            row
            for row in appendix.get("user_requirements") or []
            if isinstance(row, dict)
            and (
                row in direct_user_requirements
                or str(row.get("id") or "").strip() in visible_source_ids
            )
        ]
        for row in expanded_user_requirements:
            source_id = str(row.get("source_id") or "").strip()
            if source_id:
                visible_source_ids.add(source_id)
            visible_source_ids.update(
                str(item).strip()
                for item in (row.get("related_statement_ids") or [])
                if str(item).strip()
            )
        expanded_stakeholder_statements = [
            row
            for row in appendix.get("stakeholder_statements") or []
            if isinstance(row, dict)
            and (
                req_id in (row.get("related_req") or [])
                or str(row.get("id") or "").strip() in visible_source_ids
            )
        ]
        req_context = {
            "id": req_id,
            "title": str(req.get("title") or "").strip(),
            "type": str(req.get("type") or "").strip(),
            "srs_id": current_srs_id,
            "source": req.get("source"),
            "dependencies": req.get("dependencies"),
            "description": str(req.get("description") or "").strip(),
            "acceptance_criteria": [
                cls.clean_repeated_text(item)
                for item in (req.get("acceptance_criteria") or [])
                if cls.clean_repeated_text(item)
            ],
            "metric": cls.clean_repeated_text(req.get("metric")),
            "stakeholder_statements": [
                {
                    "id": row.get("id"),
                    "stakeholder": row.get("stakeholder"),
                    "source": row.get("source"),
                    "text": row.get("text"),
                }
                for row in expanded_stakeholder_statements
            ],
            "user_requirements": [
                {
                    "id": row.get("id"),
                    "stakeholder": row.get("stakeholder"),
                    "source": row.get("source"),
                    "source_id": row.get("source_id"),
                    "related_statement_ids": row.get("related_statement_ids"),
                    "text": row.get("text"),
                }
                for row in expanded_user_requirements
            ],
            "conflicts": conflict_context_rows,
            "feedback": feedback_context_rows,
            "system_models": model_context_rows,
            "meetings": meeting_context_rows,
        }
        visible_trace_node_ids = {
            str(row.get("id") or "").strip()
            for section in (
                "stakeholder_statements",
                "user_requirements",
                "conflicts",
                "feedback",
                "system_models",
                "meetings",
            )
            for row in (req_context.get(section) or [])
            if isinstance(row, dict) and str(row.get("id") or "").strip()
        }
        visible_trace_node_ids.update({req_id, req_context["srs_id"]})
        req_context["trace_req_rows"] = select_trace_req_rows(
            appendix=appendix,
            req_id=req_id,
            srs_id=req_context["srs_id"],
            visible_trace_node_ids=visible_trace_node_ids,
        )
        req_contexts.append(req_context)

    return req_contexts


def select_trace_req_rows(
    *,
    appendix: Dict[str, Any],
    req_id: str,
    srs_id: str,
    visible_trace_node_ids: set[str],
) -> List[Dict[str, Any]]:
    selected_rows: List[Dict[str, Any]] = []
    for row in appendix.get("trace_req") or []:
        if not isinstance(row, dict):
            continue
        target_requirement_id = str(row.get("target_requirement_id") or "").strip()
        if target_requirement_id not in {req_id, srs_id}:
            continue
        from_id = str(row.get("from") or "").strip()
        to_id = str(row.get("to") or "").strip()
        if (
            (from_id.startswith(("FB-", "SM-")) and from_id not in visible_trace_node_ids)
            or (to_id.startswith(("FB-", "SM-")) and to_id not in visible_trace_node_ids)
        ):
            continue
        selected_rows.append(dict(row))
    return selected_rows
