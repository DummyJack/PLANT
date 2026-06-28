import re
from typing import Any, Dict, List, Optional


class DocumentorDrTraceValidationMixin:
    @classmethod
    def validate_trace_context(cls, requirement: Dict[str, Any]) -> List[str]:
        req_id = str(requirement.get("id") or "").strip()
        srs_id = str(requirement.get("srs_id") or "").strip()
        url_rows = [row for row in requirement.get("user_requirements") or [] if isinstance(row, dict)]
        requirement_kind = str(requirement.get("type") or "").strip().lower()
        is_constraint = requirement_kind == "constraint" or bool(re.match(r"^CON-\d+$", srs_id, flags=re.IGNORECASE))
        if not url_rows:
            if not is_constraint:
                raise ValueError(f"DR trace missing User Requirement for {srs_id or req_id}")
            has_constraint_evidence = any(
                isinstance(requirement.get(section), list) and requirement.get(section)
                for section in ("feedback", "system_models", "meetings", "dependencies")
            ) or bool(requirement.get("source"))
            if not has_constraint_evidence:
                raise ValueError(f"DR trace missing evidence for {srs_id or req_id}")

        warnings: List[str] = []
        if is_constraint and not url_rows:
            warnings.append(f"{srs_id or req_id} is a constraint traced from non-URL evidence")
        for row in requirement.get("trace_event_warnings") or []:
            if not isinstance(row, dict):
                continue
            warnings.append(
                "trace_req edge "
                f"{str(row.get('from') or '').strip()}->{str(row.get('to') or '').strip()} "
                "was excluded because a node was missing from DR context"
            )
        graph = requirement.get("trace_graph") if isinstance(requirement.get("trace_graph"), dict) else {}
        reference_graph = (
            requirement.get("trace_repair_reference_graph")
            if isinstance(requirement.get("trace_repair_reference_graph"), dict)
            else {}
        )
        visible_ids = {
            str(node.get("id") or "").strip()
            for node in (graph.get("nodes") or [])
            if isinstance(node, dict) and str(node.get("id") or "").strip()
        }
        known_graph_ids = {
            str(node.get("id") or "").strip()
            for node in (
                (graph.get("all_nodes") or graph.get("nodes") or [])
                + (reference_graph.get("all_nodes") or reference_graph.get("nodes") or [])
            )
            if isinstance(node, dict) and str(node.get("id") or "").strip()
        }
        node_type_by_id = {
            str(node.get("id") or "").strip(): str(node.get("type") or "").strip()
            for node in (
                (reference_graph.get("all_nodes") or reference_graph.get("nodes") or [])
                + (graph.get("all_nodes") or graph.get("nodes") or [])
            )
            if isinstance(node, dict) and str(node.get("id") or "").strip()
        }
        edge_pairs = {
            (str(edge.get("from") or "").strip(), str(edge.get("to") or "").strip())
            for edge in (graph.get("edges") or [])
            if isinstance(edge, dict)
        }

        for url in url_rows:
            url_id = str(url.get("id") or "").strip()
            if url_id not in visible_ids:
                continue
            source_id = str(url.get("source_id") or "").strip()
            source_ref = str(url.get("source") or "").strip()
            if not source_id and re.fullmatch(r"R\d+-M\d+", source_ref, flags=re.IGNORECASE):
                source_id = source_ref
            related_statement_ids = [
                str(item).strip()
                for item in (url.get("related_statement_ids") or [])
                if str(item).strip()
            ]
            if (
                source_id
                and source_id in known_graph_ids
                and node_type_by_id.get(source_id) != "Meeting Discussion"
                and (source_id, url_id) not in edge_pairs
            ):
                warnings.append(f"{url_id} source_id {source_id} was not connected in topology")
            for statement_id in related_statement_ids:
                if statement_id in known_graph_ids and (statement_id, url_id) not in edge_pairs:
                    warnings.append(f"{url_id} related_statement_id {statement_id} was not connected in topology")
            if not source_id and not related_statement_ids:
                warnings.append(f"{url_id} has no source_id; stakeholder statement edge was skipped")

        for section, label in (
            ("feedback", "Feedback"),
            ("system_models", "System Model"),
            ("conflicts", "Conflict"),
            ("meetings", "Meeting"),
        ):
            rows = [row for row in (requirement.get(section) or []) if isinstance(row, dict)]
            if section == "feedback" and len(rows) > 1:
                group_id = f"FB-GROUP-{srs_id or req_id}"
                if group_id in visible_ids:
                    continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                row_id = str(row.get("id") or row.get("meeting_id") or "").strip()
                if row_id and row_id not in visible_ids:
                    warnings.append(f"{label} {row_id} is related but excluded from topology because it has no valid edge")

        conflict_rows = [row for row in (requirement.get("conflicts") or []) if isinstance(row, dict)]
        meeting_rows = [row for row in (requirement.get("meetings") or []) if isinstance(row, dict)]
        resolve_meeting_ids = {
            str(row.get("id") or "").strip()
            for row in meeting_rows
            if cls.is_conflict_resolution_meeting(row) and str(row.get("id") or "").strip() in visible_ids
        }
        if conflict_rows and not resolve_meeting_ids:
            conflict_ids = [
                str(row.get("id") or "").strip()
                for row in conflict_rows
                if str(row.get("id") or "").strip()
            ]
            warnings.append(f"{', '.join(conflict_ids)} has no visible resolve_conflict meeting")

        formalization_meeting_ids = {
            str(row.get("id") or "").strip()
            for row in meeting_rows
            if cls.is_requirement_formalization_meeting(row) and str(row.get("id") or "").strip() in visible_ids
        }
        formalization_meeting_ids.update(
            str(edge.get("to") or "").strip()
            for edge in (graph.get("edges") or [])
            if isinstance(edge, dict)
            and str(edge.get("to") or "").strip() in visible_ids
            and node_type_by_id.get(str(edge.get("to") or "").strip()) == "Meeting Discussion"
            and str(edge.get("relation") or "").strip() == "正式化"
        )
        if meeting_rows and not formalization_meeting_ids:
            warnings.append(f"{srs_id or req_id} has meetings but no visible formalize_requirement meeting")

        return warnings

    @classmethod
    def build_trace_repair_tasks(cls, requirement: Dict[str, Any]) -> List[Dict[str, Any]]:
        req_id = str(requirement.get("id") or "").strip()
        srs_id = str(requirement.get("srs_id") or "").strip()
        graph = requirement.get("trace_graph") if isinstance(requirement.get("trace_graph"), dict) else {}
        reference_graph = (
            requirement.get("trace_repair_reference_graph")
            if isinstance(requirement.get("trace_repair_reference_graph"), dict)
            else {}
        )
        visible_ids = {
            str(node.get("id") or "").strip()
            for node in (graph.get("nodes") or [])
            if isinstance(node, dict) and str(node.get("id") or "").strip()
        }
        reference_ids = {
            str(node.get("id") or "").strip()
            for node in (reference_graph.get("all_nodes") or reference_graph.get("nodes") or [])
            if isinstance(node, dict) and str(node.get("id") or "").strip()
        }
        edge_pairs = {
            (str(edge.get("from") or "").strip(), str(edge.get("to") or "").strip())
            for edge in (graph.get("edges") or [])
            if isinstance(edge, dict)
        }
        tasks: List[Dict[str, Any]] = []

        def add_task(
            repair_type: str,
            reason: str,
            *,
            candidate_from: str = "",
            candidate_to: str = "",
            edge_label: str = "",
            confidence: str = "medium",
            evidence_ids: Optional[List[str]] = None,
        ) -> None:
            task_index = len(tasks) + 1
            tasks.append({
                "task_id": f"TR-{srs_id or req_id}-{task_index}",
                "target_requirement_id": srs_id or req_id,
                "repair_type": repair_type,
                "candidate_from": candidate_from,
                "candidate_to": candidate_to,
                "edge_label": edge_label,
                "confidence": confidence,
                "status": "needs_agent_repair",
                "reason": reason,
                "evidence_ids": evidence_ids or [item for item in (candidate_from, candidate_to) if item],
                "runtime_rule": "Agent may propose a repair, but runtime must validate node existence, allowed edge type, duplicate edges, and meeting action before applying it as formal trace.",
                "max_agent_repair_rounds": cls.TRACE_AGENT_REPAIR_MAX_ROUNDS,
                "stop_conditions": [
                    "no_new_proposal",
                    "all_proposals_rejected",
                    "trace_warnings_not_reduced",
                    "max_rounds_reached",
                ],
            })

        url_rows = [row for row in requirement.get("user_requirements") or [] if isinstance(row, dict)]
        for url in url_rows:
            url_id = str(url.get("id") or "").strip()
            source_id = str(url.get("source_id") or "").strip()
            related_statement_ids = [
                str(item).strip()
                for item in (url.get("related_statement_ids") or [])
                if str(item).strip()
            ]
            if source_id and (source_id, url_id) not in edge_pairs:
                add_task(
                    "connect_statement_to_url",
                    f"{url_id} declares source_id {source_id}, but the topology did not include that source edge.",
                    candidate_from=source_id,
                    candidate_to=url_id,
                    edge_label="分析",
                    confidence="high",
                )
            for statement_id in related_statement_ids:
                if (statement_id, url_id) not in edge_pairs:
                    add_task(
                        "connect_statement_to_url",
                        f"{url_id} declares related_statement_id {statement_id}, but the topology did not include that source edge.",
                        candidate_from=statement_id,
                        candidate_to=url_id,
                        edge_label="分析",
                        confidence="high",
                    )
            if not source_id and not related_statement_ids:
                add_task(
                    "identify_url_source",
                    f"{url_id} has no explicit source_id or related_statement_ids; Agent may identify candidate stakeholder evidence for human review.",
                    candidate_to=url_id,
                    edge_label="分析",
                    confidence="low",
                    evidence_ids=[url_id],
                )
            elif not graph and url_id in reference_ids:
                add_task(
                    "connect_statement_to_url",
                    f"{url_id} appears in the runtime reference graph, but no formal trace graph was accepted. Agent must decide whether to connect the declared source evidence.",
                    candidate_from=source_id or (related_statement_ids[0] if related_statement_ids else ""),
                    candidate_to=url_id,
                    edge_label="分析",
                    confidence="medium",
                    evidence_ids=[item for item in [source_id, *related_statement_ids, url_id] if item],
                )

        formalize_meeting_ids = [
            str(row.get("id") or "").strip()
            for row in (requirement.get("meetings") or [])
            if isinstance(row, dict)
            and cls.is_requirement_formalization_meeting(row)
            and str(row.get("id") or "").strip()
        ]
        resolve_meeting_ids = [
            str(row.get("id") or "").strip()
            for row in (requirement.get("meetings") or [])
            if isinstance(row, dict)
            and cls.is_conflict_resolution_meeting(row)
            and str(row.get("id") or "").strip()
        ]
        last_formalize_id = formalize_meeting_ids[-1] if formalize_meeting_ids else ""
        last_resolve_id = resolve_meeting_ids[-1] if resolve_meeting_ids else ""

        for section, repair_type, edge_label in (
            ("feedback", "connect_feedback_to_formalize_meeting", ""),
            ("system_models", "connect_model_to_formalize_meeting", ""),
        ):
            if not last_formalize_id:
                continue
            for row in [item for item in (requirement.get(section) or []) if isinstance(item, dict)]:
                row_id = str(row.get("id") or "").strip()
                if row_id and row_id not in visible_ids:
                    add_task(
                        repair_type,
                        f"{row_id} is related to the requirement but is not connected to a formalization meeting.",
                        candidate_from=row_id,
                        candidate_to=last_formalize_id,
                        edge_label=edge_label,
                        confidence="medium",
                    )

        conflict_ids = [
            str(row.get("id") or "").strip()
            for row in (requirement.get("conflicts") or [])
            if isinstance(row, dict) and str(row.get("id") or "").strip()
        ]
        if conflict_ids and not last_resolve_id:
            add_task(
                "identify_conflict_resolution_meeting",
                f"{', '.join(conflict_ids)} has no visible resolve_conflict meeting; Agent may identify a candidate meeting or request human confirmation.",
                edge_label="解決",
                confidence="low",
                evidence_ids=conflict_ids,
            )
        elif last_resolve_id and last_formalize_id and (last_resolve_id, last_formalize_id) not in edge_pairs:
            add_task(
                "connect_resolve_to_formalize_meeting",
                f"{last_resolve_id} and {last_formalize_id} are both present but are not connected in the topology.",
                candidate_from=last_resolve_id,
                candidate_to=last_formalize_id,
                edge_label="正式化",
                confidence="high",
            )

        if requirement.get("meetings") and not last_formalize_id:
            add_task(
                "identify_formalization_meeting",
                f"{srs_id or req_id} has meetings but no visible formalize_requirement meeting.",
                confidence="low",
                evidence_ids=[
                    str(row.get("id") or "").strip()
                    for row in (requirement.get("meetings") or [])
                    if isinstance(row, dict) and str(row.get("id") or "").strip()
                ],
            )

        if not graph and not tasks:
            target_id = srs_id or req_id
            reference_ids_for_review = [
                str(node.get("id") or "").strip()
                for node in (reference_graph.get("nodes") or [])
                if isinstance(node, dict)
                and str(node.get("id") or "").strip()
                and str(node.get("id") or "").strip() != target_id
            ]
            if reference_ids_for_review:
                add_task(
                    "identify_formalization_meeting",
                    f"No accepted trace graph exists for {target_id}; runtime reference graph is available for review, but no concrete validated repair candidate was derived.",
                    edge_label="",
                    confidence="low",
                    evidence_ids=reference_ids_for_review[:8] + [target_id],
                )

        return tasks

    @classmethod
    def split_agent_repair_tasks(cls, requirement: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        agent_tasks: List[Dict[str, Any]] = []
        human_tasks: List[Dict[str, Any]] = list(requirement.get("trace_human_review_tasks") or [])
        for task in requirement.get("trace_repair_tasks") or []:
            if not isinstance(task, dict):
                continue
            confidence = str(task.get("confidence") or "").strip().lower()
            if confidence == "low":
                review_task = dict(task)
                review_task["status"] = "needs_human_review"
                human_tasks.append(review_task)
            else:
                agent_tasks.append(task)
        return agent_tasks, human_tasks

    @classmethod
    def validate_trace_repair_proposal(cls, requirement: Dict[str, Any], proposal: Dict[str, Any]) -> Dict[str, Any]:
        graph = requirement.get("trace_graph") if isinstance(requirement.get("trace_graph"), dict) else {}
        reference_graph = (
            requirement.get("trace_repair_reference_graph")
            if isinstance(requirement.get("trace_repair_reference_graph"), dict)
            else {}
        )
        graph_node_rows = [
            node for node in (graph.get("all_nodes") or graph.get("nodes") or [])
            if isinstance(node, dict)
        ]
        reference_node_rows = [
            node for node in (reference_graph.get("all_nodes") or reference_graph.get("nodes") or [])
            if isinstance(node, dict)
        ]
        node_ids = {
            str(node.get("id") or "").strip()
            for node in graph_node_rows + reference_node_rows
            if str(node.get("id") or "").strip()
        }
        for section in ("stakeholder_statements", "user_requirements", "conflicts", "feedback", "system_models", "meetings"):
            for row in requirement.get(section) or []:
                if isinstance(row, dict) and str(row.get("id") or "").strip():
                    node_ids.add(str(row.get("id") or "").strip())
        target_id = str(requirement.get("srs_id") or "").strip()
        if target_id:
            node_ids.add(target_id)
        target_requirement_id = str(proposal.get("target_requirement_id") or "").strip()
        if target_requirement_id and target_requirement_id not in cls.trace_target_aliases(requirement):
            errors = [f"target_requirement_id does not match requirement: {target_requirement_id}"]
            return {
                "accepted": False,
                "errors": errors,
                "normalized": {
                    "from": "",
                    "to": "",
                    "relation": "",
                    "repair_type": str(proposal.get("repair_type") or "").strip(),
                    "status": "rejected",
                },
            }
        edge_pairs = {
            (str(edge.get("from") or "").strip(), str(edge.get("to") or "").strip())
            for edge in (graph.get("edges") or [])
            if isinstance(edge, dict)
        }
        candidate_from = str(proposal.get("candidate_from") or proposal.get("from") or "").strip()
        candidate_to = str(proposal.get("candidate_to") or proposal.get("to") or "").strip()
        repair_type = str(proposal.get("repair_type") or "").strip()
        edge_label = str(proposal.get("edge_label") or "").strip()
        allowed_labels_by_type = {
            "connect_statement_to_url": {"分析", "整理"},
            "connect_feedback_to_formalize_meeting": {""},
            "connect_model_to_formalize_meeting": {""},
            "connect_resolve_to_formalize_meeting": {"正式化"},
            "identify_url_source": {"分析", "整理"},
            "identify_conflict_resolution_meeting": {"解決"},
            "identify_formalization_meeting": {""},
        }
        errors: List[str] = []
        if repair_type not in allowed_labels_by_type:
            errors.append(f"unsupported repair_type: {repair_type or '<empty>'}")
        if candidate_from and candidate_from not in node_ids:
            errors.append(f"candidate_from does not exist in trace_graph: {candidate_from}")
        if candidate_to and candidate_to not in node_ids:
            errors.append(f"candidate_to does not exist in trace_graph: {candidate_to}")
        if candidate_from and candidate_to and (candidate_from, candidate_to) in edge_pairs:
            errors.append(f"duplicate edge: {candidate_from}->{candidate_to}")
        if repair_type in allowed_labels_by_type and edge_label not in allowed_labels_by_type[repair_type]:
            errors.append(f"edge_label {edge_label or '<empty>'} is not allowed for {repair_type}")
        return {
            "accepted": not errors,
            "errors": errors,
            "normalized": {
                "from": candidate_from,
                "to": candidate_to,
                "relation": edge_label,
                "repair_type": repair_type,
                "status": "validated" if not errors else "rejected",
            },
        }

    @classmethod
    def apply_trace_repair_proposals(cls, requirement: Dict[str, Any], proposals: List[Dict[str, Any]]) -> Dict[str, Any]:
        graph = requirement.get("trace_graph") if isinstance(requirement.get("trace_graph"), dict) else {}
        reference_graph = (
            requirement.get("trace_repair_reference_graph")
            if isinstance(requirement.get("trace_repair_reference_graph"), dict)
            else {}
        )
        all_nodes = [
            node for node in (graph.get("all_nodes") or graph.get("nodes") or [])
            if isinstance(node, dict)
        ]
        if not all_nodes:
            all_nodes = [
                node for node in (reference_graph.get("all_nodes") or reference_graph.get("nodes") or [])
                if isinstance(node, dict)
            ]
        edges = [
            dict(edge) for edge in (graph.get("edges") or [])
            if isinstance(edge, dict)
        ]
        applied: List[Dict[str, Any]] = []
        for proposal in proposals or []:
            if not isinstance(proposal, dict):
                continue
            validation = cls.validate_trace_repair_proposal(requirement, proposal)
            if not validation.get("accepted"):
                continue
            normalized = validation.get("normalized") if isinstance(validation.get("normalized"), dict) else {}
            from_id = str(normalized.get("from") or "").strip()
            to_id = str(normalized.get("to") or "").strip()
            if not from_id or not to_id:
                continue
            edge = {
                "from": from_id,
                "to": to_id,
                "relation": str(normalized.get("relation") or "").strip(),
            }
            if edge not in edges:
                edges.append(edge)
                applied.append(normalized)
        if not applied:
            return requirement
        updated = dict(requirement)
        updated["trace_graph"] = cls.visible_trace_graph(
            all_nodes=all_nodes,
            edges=edges,
            target_id=str(updated.get("srs_id") or "").strip(),
        )
        updated["trace_repair_applied"] = list((updated.get("trace_repair_applied") or [])) + applied
        updated["trace_warnings"] = cls.validate_trace_context(updated)
        updated["trace_repair_tasks"] = cls.build_trace_repair_tasks(updated)
        return updated
