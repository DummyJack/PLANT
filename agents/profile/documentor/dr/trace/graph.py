import re
from typing import Any, Dict, List, Optional

from storage.markdown import markdown_to_html
from utils.topology import normalize_dr_model_path


class DocumentorDrTraceGraphMixin:
    @classmethod
    def build_trace_graph_from_trace_req(
        cls,
        requirement: Dict[str, Any],
        trace_req_rows: List[Dict[str, Any]],
        *,
        fallback_graph: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not trace_req_rows:
            return {}
        target_id = str(requirement.get("srs_id") or "").strip()
        all_nodes = [
            node for node in (fallback_graph.get("all_nodes") or fallback_graph.get("nodes") or [])
            if isinstance(node, dict)
        ]
        existing_node_ids = {
            str(node.get("id") or "").strip()
            for node in all_nodes
            if str(node.get("id") or "").strip()
        }
        synthetic_meeting_ids: set[str] = set()
        meeting_pattern = re.compile(r"^R\d+-M\d+$", flags=re.IGNORECASE)
        for event in trace_req_rows:
            for key in ("from", "to"):
                node_id = str(event.get(key) or "").strip()
                if meeting_pattern.fullmatch(node_id) and node_id not in existing_node_ids:
                    synthetic_meeting_ids.add(node_id)
        for meeting_id in sorted(synthetic_meeting_ids, key=lambda value: cls.meeting_order_key({"id": value})):
            all_nodes.append({
                "id": meeting_id,
                "type": "Meeting Discussion",
                "label": f"{meeting_id} 需求正式化",
                "title": f"{meeting_id}：需求正式化",
                "content": f"{meeting_id}：需求正式化",
                "content_format": "text",
                "column": "Meeting",
            })
        known_node_ids = {
            str(node.get("id") or "").strip()
            for node in all_nodes
            if str(node.get("id") or "").strip()
        }
        node_aliases: Dict[str, str] = {}
        for node in all_nodes:
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id") or "").strip()
            if not node_id:
                continue
            for alias in node.get("grouped_ids") or []:
                alias_id = str(alias or "").strip()
                if alias_id:
                    node_aliases[alias_id] = node_id

        def resolve_node_id(node_id: Any) -> str:
            clean_id = str(node_id or "").strip()
            return node_aliases.get(clean_id, clean_id)

        node_type_by_id = {
            str(node.get("id") or "").strip(): str(node.get("type") or "").strip()
            for node in all_nodes
            if str(node.get("id") or "").strip()
        }
        url_ids = [
            str(row.get("id") or "").strip()
            for row in (requirement.get("user_requirements") or [])
            if isinstance(row, dict) and str(row.get("id") or "").strip()
        ]
        requirement_req_id = str(requirement.get("id") or "").strip()
        shared_model_ids: set[str] = set()
        for row in requirement.get("system_models") or []:
            if not isinstance(row, dict):
                continue
            row_id = resolve_node_id(row.get("id"))
            related_sources = [
                str(item).strip()
                for item in (row.get("related_sources") or [])
                if str(item).strip()
            ]
            related_req_ids = [
                str(item).strip()
                for item in (row.get("related_req") or [])
                if str(item).strip()
            ]
            direct_url_hits = list(dict.fromkeys(item for item in related_sources if item in url_ids))
            broad_url_model = len(direct_url_hits) > 1
            if row_id and broad_url_model:
                shared_model_ids.add(row_id)
                for node in all_nodes:
                    if str(node.get("id") or "").strip() == row_id:
                        node["column"] = "Background"
        evidence_url_ids: Dict[str, List[str]] = {}
        for row in requirement.get("feedback") or []:
            if not isinstance(row, dict):
                continue
            row_id = resolve_node_id(row.get("id"))
            related = [
                str(item).strip()
                for item in (row.get("related_sources") or [])
                if str(item).strip() in url_ids
            ]
            if not related and row_id not in shared_model_ids:
                related = list(url_ids)
            if row_id and related:
                evidence_url_ids[row_id] = list(dict.fromkeys(related))
        for row in requirement.get("system_models") or []:
            if not isinstance(row, dict):
                continue
            row_id = resolve_node_id(row.get("id"))
            if row_id in shared_model_ids:
                continue
            related = [
                str(item).strip()
                for item in (row.get("related_sources") or [])
                if str(item).strip() in url_ids
            ]
            if not related:
                related = list(url_ids)
            if row_id and related:
                evidence_url_ids[row_id] = list(dict.fromkeys(related))
        for row in requirement.get("conflicts") or []:
            if not isinstance(row, dict):
                continue
            row_id = resolve_node_id(row.get("id"))
            related = [
                str(item).strip()
                for item in (row.get("related_user_requirements") or [])
                if str(item).strip() in url_ids
            ]
            if not related:
                related = list(url_ids)
            if row_id and related:
                evidence_url_ids[row_id] = list(dict.fromkeys(related))
        edges: List[Dict[str, str]] = []
        missing_edges: List[Dict[str, str]] = []

        direct_formalization_meeting_ids = sorted(
            {
                str(event.get("from") or "").strip()
                for event in trace_req_rows
                if str(event.get("to") or "").strip() == target_id
                and meeting_pattern.fullmatch(str(event.get("from") or "").strip())
            },
            key=lambda value: cls.meeting_order_key({"id": value}),
        )
        entry_formalization_meeting_id = direct_formalization_meeting_ids[0] if direct_formalization_meeting_ids else ""
        terminal_meeting_id = ""
        meeting_rows = [
            row for row in (requirement.get("meetings") or [])
            if isinstance(row, dict) and str(row.get("id") or "").strip() in known_node_ids
        ]
        formalization_meeting_ids = [
            str(row.get("id") or "").strip()
            for row in meeting_rows
            if cls.is_requirement_formalization_meeting(row)
        ]
        conflict_resolution_meeting_ids = [
            str(row.get("id") or "").strip()
            for row in meeting_rows
            if cls.is_conflict_resolution_meeting(row)
        ]
        trace_meeting_ids = sorted(
            {
                node_id
                for event in trace_req_rows
                for node_id in (
                    str(event.get("from") or "").strip(),
                    str(event.get("to") or "").strip(),
                )
                if meeting_pattern.fullmatch(node_id) and node_id in known_node_ids
            },
            key=lambda value: cls.meeting_order_key({"id": value}),
        )
        source_meeting_ids = sorted(
            {
                str(item).strip()
                for item in (requirement.get("source") or [])
                if meeting_pattern.fullmatch(str(item).strip()) and str(item).strip() in known_node_ids
            },
            key=lambda value: cls.meeting_order_key({"id": value}),
        )
        visible_meeting_ids = trace_meeting_ids or source_meeting_ids
        if direct_formalization_meeting_ids:
            terminal_meeting_id = direct_formalization_meeting_ids[-1]
        elif formalization_meeting_ids:
            entry_formalization_meeting_id = formalization_meeting_ids[0]
            terminal_meeting_id = formalization_meeting_ids[-1]
        elif visible_meeting_ids:
            entry_formalization_meeting_id = visible_meeting_ids[0]
            terminal_meeting_id = visible_meeting_ids[-1]
        elif target_id in known_node_ids:
            terminal_meeting_id = target_id

        def add_visible_edge(source_id: str, target_node_id: str, event: Dict[str, Any]) -> None:
            source_id = resolve_node_id(source_id)
            target_node_id = resolve_node_id(target_node_id)
            if not source_id or not target_node_id or source_id == target_node_id:
                return
            if source_id not in known_node_ids or target_node_id not in known_node_ids:
                missing_edges.append({
                    "from": source_id,
                    "to": target_node_id,
                    "reason": "trace_req references a node not present in DR context",
                })
                return
            relation = str(event.get("edge_label") or event.get("relation") or "").strip()
            if relation == "整理":
                relation = "分析"
            edge = {
                "from": source_id,
                "to": target_node_id,
                "relation": relation,
            }
            style = str(event.get("style") or "").strip()
            if style:
                edge["style"] = style
            for index, existing in enumerate(edges):
                if (
                    existing.get("from") == edge["from"]
                    and existing.get("to") == edge["to"]
                    and str(existing.get("style") or "") == str(edge.get("style") or "")
                ):
                    existing_relation = str(existing.get("relation") or "").strip()
                    if relation and not existing_relation:
                        edges[index] = edge
                    return
            edges.append(edge)

        explicit_req_visible_inputs: Dict[str, List[str]] = {}
        for event in trace_req_rows:
            source_id = resolve_node_id(event.get("from"))
            target_node_id = resolve_node_id(event.get("to"))
            if not source_id or not target_node_id:
                continue
            if target_node_id.startswith("REQ-") and source_id in known_node_ids:
                explicit_req_visible_inputs.setdefault(target_node_id, [])
                if source_id not in explicit_req_visible_inputs[target_node_id]:
                    explicit_req_visible_inputs[target_node_id].append(source_id)

        req_visible_inputs: Dict[str, List[str]] = {
            req_id: list(inputs)
            for req_id, inputs in explicit_req_visible_inputs.items()
        }

        requirement_req_id = str(requirement.get("id") or "").strip()
        primary_url_ids = [
            str(item).strip()
            for item in (requirement.get("source") or [])
            if str(item).strip() in url_ids
        ]
        if not primary_url_ids and url_ids:
            primary_url_ids = [url_ids[0]]
        if requirement_req_id:
            fallback_sources = [url_id for url_id in primary_url_ids if url_id in known_node_ids]
            if fallback_sources:
                req_visible_inputs[requirement_req_id] = list(dict.fromkeys(
                    list(req_visible_inputs.get(requirement_req_id) or []) + fallback_sources
                ))

        for event in trace_req_rows:
            source_id = resolve_node_id(event.get("from"))
            target_node_id = resolve_node_id(event.get("to"))
            if not source_id or not target_node_id:
                continue
            if (
                target_node_id == target_id
                and source_id in direct_formalization_meeting_ids
            ):
                continue
            if (
                node_type_by_id.get(source_id) == "Conflict"
                and node_type_by_id.get(target_node_id) == "Meeting Discussion"
                and str(event.get("edge_label") or event.get("relation") or "").strip() == "解決"
            ):
                add_visible_edge(source_id, target_node_id, event)
                continue
            if (
                node_type_by_id.get(source_id) in {"Conflict", "Feedback", "Feedback Group", "System Model"}
                and node_type_by_id.get(target_node_id) == "Meeting Discussion"
            ):
                for url_id in evidence_url_ids.get(source_id) or []:
                    evidence_event = dict(event)
                    evidence_event["edge_label"] = ""
                    evidence_event["style"] = "dashed"
                    add_visible_edge(url_id, source_id, evidence_event)
                continue
            if target_node_id.startswith("REQ-"):
                continue
            if source_id.startswith("REQ-"):
                if target_node_id == target_id:
                    folded_source_ids = req_visible_inputs.get(source_id) or []
                    folded_target_id = entry_formalization_meeting_id or terminal_meeting_id or target_id
                    folded_event = dict(event)
                    if folded_target_id != target_id and not str(folded_event.get("edge_label") or "").strip():
                        folded_event["edge_label"] = "正式化"
                else:
                    folded_source_ids = (
                        explicit_req_visible_inputs.get(source_id)
                        or req_visible_inputs.get(source_id)
                        or []
                    )
                    folded_target_id = target_node_id
                    folded_event = event
                for folded_source_id in folded_source_ids:
                    add_visible_edge(folded_source_id, folded_target_id, folded_event)
                continue
            add_visible_edge(source_id, target_node_id, event)

        for row in requirement.get("conflicts") or []:
            if not isinstance(row, dict):
                continue
            conflict_id = resolve_node_id(row.get("id"))
            if not conflict_id or conflict_id not in known_node_ids:
                continue
            for url_id in evidence_url_ids.get(conflict_id) or []:
                add_visible_edge(url_id, conflict_id, {"edge_label": "衝突"})
            for conflict_target_id in conflict_resolution_meeting_ids:
                add_visible_edge(conflict_id, conflict_target_id, {"edge_label": "解決"})

        if direct_formalization_meeting_ids:
            for index, meeting_id in enumerate(direct_formalization_meeting_ids):
                if index > 0:
                    add_visible_edge(
                        direct_formalization_meeting_ids[index - 1],
                        meeting_id,
                        {"edge_label": ""},
                    )
            add_visible_edge(
                direct_formalization_meeting_ids[-1],
                target_id,
                {"edge_label": ""},
            )
        elif visible_meeting_ids:
            for url_id in primary_url_ids:
                add_visible_edge(
                    url_id,
                    visible_meeting_ids[0],
                    {"edge_label": "正式化"},
                )
            add_visible_edge(
                visible_meeting_ids[-1],
                target_id,
                {"edge_label": ""},
            )

        meeting_chain_pairs = {
            (str(edge.get("from") or "").strip(), str(edge.get("to") or "").strip())
            for edge in edges
            if node_type_by_id.get(str(edge.get("from") or "").strip()) == "Meeting Discussion"
            and node_type_by_id.get(str(edge.get("to") or "").strip()) == "Meeting Discussion"
        }
        meeting_reachable: Dict[str, set[str]] = {}
        meeting_next_ids: Dict[str, set[str]] = {}
        for source_id, target_node_id in meeting_chain_pairs:
            meeting_next_ids.setdefault(source_id, set()).add(target_node_id)

        def reachable_meetings(meeting_id: str) -> set[str]:
            if meeting_id in meeting_reachable:
                return meeting_reachable[meeting_id]
            seen: set[str] = set()
            stack = list(meeting_next_ids.get(meeting_id) or [])
            while stack:
                next_id = stack.pop()
                if next_id in seen:
                    continue
                seen.add(next_id)
                stack.extend(meeting_next_ids.get(next_id) or [])
            meeting_reachable[meeting_id] = seen
            return seen

        url_to_meeting_edges = [
            edge for edge in edges
            if str(edge.get("from") or "").strip().startswith("URL-")
            and node_type_by_id.get(str(edge.get("to") or "").strip()) == "Meeting Discussion"
        ]
        shortcut_edges = {
            (str(edge.get("from") or "").strip(), str(edge.get("to") or "").strip())
            for edge in url_to_meeting_edges
            for previous in url_to_meeting_edges
            if str(edge.get("from") or "").strip() == str(previous.get("from") or "").strip()
            and str(edge.get("to") or "").strip() != str(previous.get("to") or "").strip()
            and str(edge.get("to") or "").strip() in reachable_meetings(str(previous.get("to") or "").strip())
        }
        conflict_meeting_sources_by_url: Dict[str, set[str]] = {}
        conflict_ids_by_url = {
            str(edge.get("from") or "").strip(): str(edge.get("to") or "").strip()
            for edge in edges
            if str(edge.get("from") or "").strip().startswith("URL-")
            and node_type_by_id.get(str(edge.get("to") or "").strip()) == "Conflict"
            and str(edge.get("relation") or "").strip() == "衝突"
        }
        for edge in edges:
            conflict_id = str(edge.get("from") or "").strip()
            meeting_id = str(edge.get("to") or "").strip()
            if (
                node_type_by_id.get(conflict_id) == "Conflict"
                and node_type_by_id.get(meeting_id) == "Meeting Discussion"
                and str(edge.get("relation") or "").strip() == "解決"
            ):
                for url_id, url_conflict_id in conflict_ids_by_url.items():
                    if url_conflict_id == conflict_id:
                        conflict_meeting_sources_by_url.setdefault(url_id, set()).add(meeting_id)
        shortcut_edges.update({
            (str(edge.get("from") or "").strip(), str(edge.get("to") or "").strip())
            for edge in url_to_meeting_edges
            if str(edge.get("relation") or "").strip() == "正式化"
            for meeting_id in conflict_meeting_sources_by_url.get(str(edge.get("from") or "").strip()) or set()
            if str(edge.get("to") or "").strip() == meeting_id
            or str(edge.get("to") or "").strip() in reachable_meetings(meeting_id)
        })
        if shortcut_edges:
            edges = [
                edge for edge in edges
                if (
                    str(edge.get("from") or "").strip(),
                    str(edge.get("to") or "").strip(),
                )
                not in shortcut_edges
            ]
        conflict_ids_with_meeting_targets = {
            str(edge.get("from") or "").strip()
            for edge in edges
            if node_type_by_id.get(str(edge.get("from") or "").strip()) == "Conflict"
            and node_type_by_id.get(str(edge.get("to") or "").strip()) == "Meeting Discussion"
        }
        if conflict_ids_with_meeting_targets:
            edges = [
                edge for edge in edges
                if not (
                    str(edge.get("from") or "").strip() in conflict_ids_with_meeting_targets
                    and str(edge.get("to") or "").strip() == target_id
                    and node_type_by_id.get(str(edge.get("from") or "").strip()) == "Conflict"
                )
            ]
        if meeting_rows:
            meeting_order = {
                str(row.get("id") or "").strip(): cls.meeting_order_key(row)
                for row in meeting_rows
                if str(row.get("id") or "").strip()
            }
            edges = [
                edge for edge in edges
                if not (
                    node_type_by_id.get(str(edge.get("from") or "").strip()) == "Meeting Discussion"
                    and node_type_by_id.get(str(edge.get("to") or "").strip()) == "Meeting Discussion"
                    and str(edge.get("from") or "").strip() in meeting_order
                    and str(edge.get("to") or "").strip() in meeting_order
                    and meeting_order[str(edge.get("from") or "").strip()]
                    >= meeting_order[str(edge.get("to") or "").strip()]
                )
            ]
            meeting_sources_with_later_meeting = {
                str(edge.get("from") or "").strip()
                for edge in edges
                if node_type_by_id.get(str(edge.get("from") or "").strip()) == "Meeting Discussion"
                and node_type_by_id.get(str(edge.get("to") or "").strip()) == "Meeting Discussion"
            }
            if meeting_sources_with_later_meeting:
                edges = [
                    edge for edge in edges
                    if not (
                        str(edge.get("from") or "").strip() in meeting_sources_with_later_meeting
                        and str(edge.get("to") or "").strip() == target_id
                    )
                ]
        if not edges:
            return {}
        graph = cls.visible_trace_graph(
            all_nodes=all_nodes,
            edges=edges,
            target_id=target_id,
        )
        visible_ids = {
            str(node.get("id") or "").strip()
            for node in (graph.get("nodes") or [])
            if isinstance(node, dict) and str(node.get("id") or "").strip()
        }
        if target_id not in visible_ids or len(visible_ids) <= 1:
            return {}
        visible_url_ids = [
            str(node.get("id") or "").strip()
            for node in (graph.get("nodes") or [])
            if (
                isinstance(node, dict)
                and str(node.get("id") or "").strip().startswith("URL-")
            )
        ]
        visible_edges = [edge for edge in (graph.get("edges") or []) if isinstance(edge, dict)]
        visible_feedback_urls: Dict[str, List[str]] = {}
        for edge in visible_edges:
            from_id = str(edge.get("from") or "").strip()
            to_id = str(edge.get("to") or "").strip()
            if from_id.startswith("URL-") and node_type_by_id.get(to_id) in {"Feedback", "Feedback Group"}:
                visible_feedback_urls.setdefault(to_id, [])
                if from_id not in visible_feedback_urls[to_id]:
                    visible_feedback_urls[to_id].append(from_id)
        if visible_feedback_urls:
            feedback_by_id = {
                str(row.get("id") or "").strip(): row
                for row in (requirement.get("feedback") or [])
                if isinstance(row, dict) and str(row.get("id") or "").strip()
            }
            for node in graph.get("all_nodes") or []:
                if not isinstance(node, dict):
                    continue
                node_id = str(node.get("id") or "").strip()
                if node_id not in visible_feedback_urls:
                    continue
                allowed_urls = visible_url_ids or visible_feedback_urls.get(node_id) or []
                grouped_ids = [
                    str(item).strip()
                    for item in (node.get("grouped_ids") or [])
                    if str(item).strip()
                ]
                if not grouped_ids:
                    node["related_sources"] = allowed_urls
                    continue
                table_rows = []
                for feedback_id in grouped_ids:
                    row = feedback_by_id.get(feedback_id) or {}
                    source_chips = "".join(
                        f'<span class="dr-trace-source-chip">{cls.html_attr(item)}</span>'
                        for item in dict.fromkeys(allowed_urls)
                    )
                    table_rows.append(
                        "<tr>"
                        f"<td>{cls.html_attr(feedback_id)}</td>"
                        f"<td>{cls.html_attr(row.get('type') or '')}</td>"
                        f"<td>{cls.html_attr(cls.clean_repeated_text(row.get('content')))}</td>"
                        f"<td>{source_chips}</td>"
                        "</tr>"
                    )
                if table_rows:
                    node["content"] = (
                        '<table class="dr-trace-feedback-table dr-trace-feedback-group-table"><thead><tr>'
                        "<th>ID</th><th>Type</th><th>Feedback</th><th>Source</th>"
                        "</tr></thead><tbody>"
                        + "".join(table_rows)
                        + "</tbody></table>"
                    )
                    node["related_sources"] = allowed_urls
        if missing_edges:
            requirement["trace_event_warnings"] = missing_edges
        graph["source"] = "trace_req"
        return graph

    @classmethod
    def visible_trace_graph(
        cls,
        *,
        all_nodes: List[Dict[str, Any]],
        edges: List[Dict[str, str]],
        target_id: str,
    ) -> Dict[str, Any]:
        incoming_by_target: Dict[str, List[str]] = {}
        for edge in edges:
            from_id = str(edge.get("from") or "").strip()
            to_id = str(edge.get("to") or "").strip()
            if from_id and to_id:
                incoming_by_target.setdefault(to_id, []).append(from_id)
        connected_node_ids = {target_id}
        stack = [target_id]
        while stack:
            current_id = stack.pop()
            for from_id in incoming_by_target.get(current_id, []):
                if from_id in connected_node_ids:
                    continue
                connected_node_ids.add(from_id)
                stack.append(from_id)
        node_type_by_id = {
            str(node.get("id") or "").strip(): str(node.get("type") or "").strip()
            for node in all_nodes
            if str(node.get("id") or "").strip()
        }
        for edge in edges:
            from_id = str(edge.get("from") or "").strip()
            to_id = str(edge.get("to") or "").strip()
            if (
                from_id in connected_node_ids
                and node_type_by_id.get(from_id) in {"User Requirement", "User Requirement Group"}
                and node_type_by_id.get(to_id) in {"Conflict", "Feedback", "Feedback Group", "System Model"}
            ):
                connected_node_ids.add(to_id)
        for node in all_nodes:
            node_id = str(node.get("id") or "").strip()
            if node_id and str(node.get("column") or "").strip() == "Background":
                connected_node_ids.add(node_id)
        visible_nodes = [
            node
            for node in all_nodes
            if str(node.get("id") or "").strip() in connected_node_ids
        ]
        visible_edges = [
            edge
            for edge in edges
            if str(edge.get("from") or "").strip() in connected_node_ids
            and str(edge.get("to") or "").strip() in connected_node_ids
        ]
        return {"nodes": visible_nodes, "edges": visible_edges, "all_nodes": all_nodes}

    @classmethod
    def build_trace_graph(cls, requirement: Dict[str, Any]) -> Dict[str, Any]:
        target_id = str(requirement.get("srs_id") or "").strip()
        nodes: Dict[str, Dict[str, str]] = {}
        edges: List[Dict[str, str]] = []

        def add_node(
            node_id: Any,
            node_type: str,
            label: str,
            content: str,
            column: str,
            *,
            content_format: str = "text",
            title: str = "",
            metadata: Optional[Dict[str, Any]] = None,
        ) -> None:
            clean_id = str(node_id or "").strip()
            if not clean_id:
                return
            if clean_id in nodes:
                existing_type = str(nodes[clean_id].get("type") or "").strip()
                if existing_type == "Source" and node_type != "Source":
                    pass
                else:
                    return
            node = {
                "id": clean_id,
                "type": node_type,
                "label": cls.clean_repeated_text(label) or clean_id,
                "title": cls.clean_repeated_text(title) or f"{clean_id} · {node_type}",
                "content": content,
                "content_format": content_format,
                "column": column,
            }
            if metadata:
                node.update(metadata)
            nodes[clean_id] = node

        def add_edge(source: Any, target: Any, relation: str, *, style: str = "") -> None:
            from_id = str(source or "").strip()
            to_id = str(target or "").strip()
            if not from_id or not to_id or from_id == to_id:
                return
            if from_id not in nodes or to_id not in nodes:
                return
            edge = {"from": from_id, "to": to_id, "relation": relation}
            clean_style = str(style or "").strip()
            if clean_style:
                edge["style"] = clean_style
            if edge not in edges:
                edges.append(edge)

        def content_from(row: Dict[str, Any], keys: List[str]) -> str:
            parts = []
            for key in keys:
                value = row.get(key)
                if isinstance(value, list):
                    value = ", ".join(str(item) for item in value if str(item).strip())
                text = cls.clean_repeated_text(value)
                if text:
                    parts.append(f"{key}: {text}")
            return "\n".join(parts) or json.dumps(row, ensure_ascii=False, indent=2)

        def conflict_report_html(row: Dict[str, Any]) -> str:
            markdown_entry = str(row.get("report_markdown_entry") or "").strip()
            if markdown_entry:
                return markdown_to_html(markdown_entry)
            raw = row.get("raw_report_row") if isinstance(row.get("raw_report_row"), dict) else row
            visible = {
                key: value
                for key, value in dict(raw).items()
                if key not in {"report_version", "report_file", "report_id", "raw_report_row", "related_req", "related_user_requirements"}
            }
            content = json.dumps(visible, ensure_ascii=False, indent=2)
            return f'<pre class="dr-trace-report">{cls.html_attr(content)}</pre>'

        def clean_model_description_parts(row: Dict[str, Any]) -> Dict[str, str]:
            raw = cls.clean_repeated_text(row.get("description"))
            if not raw:
                fallback = cls.clean_repeated_text(row.get("name") or row.get("id") or "System Model")
                return {"用途": fallback}
            text = re.sub(r"\*\*", "", raw).strip()
            purpose = ""
            reflected = ""
            purpose_match = re.search(r"用途\s*[：:]\s*(.*?)(?=反映需求\s*[：:]|$)", text)
            reflected_match = re.search(r"反映需求\s*[：:]\s*(.*)$", text)
            if purpose_match:
                purpose = cls.clean_repeated_text(purpose_match.group(1))
            if reflected_match:
                reflected = cls.clean_repeated_text(reflected_match.group(1))
            if not purpose and not reflected:
                return {"說明": text}

            req_id = str(requirement.get("id") or "").strip()
            srs_id = str(requirement.get("srs_id") or "").strip()
            req_desc = cls.dr_summary(requirement.get("description"), 180)
            related_sources = [
                str(item).strip()
                for item in (row.get("related_sources") or row.get("related_req") or [])
                if str(item).strip()
            ]
            if req_id and (req_id in related_sources or req_id in reflected):
                current_req = f"{req_id}"
                if srs_id:
                    current_req += f"／{srs_id}"
                if req_desc:
                    reflected = f"本圖在此處支撐 {current_req}：{req_desc}"
                else:
                    reflected = f"本圖在此處支撐 {current_req}。"
            return {
                key: value
                for key, value in (("用途", purpose), ("反映需求", reflected))
                if value
            }

        def model_image_html(row: Dict[str, Any]) -> str:
            def model_details_html() -> str:
                parts = clean_model_description_parts(row)
                purpose = parts.get("用途") or parts.get("說明") or cls.clean_repeated_text(row.get("name") or row.get("id") or "System Model")
                requirement_sources = [
                    str(item).strip()
                    for item in (requirement.get("user_requirements") or [])
                    if isinstance(item, dict)
                    for item in [item.get("id")]
                    if str(item).strip().startswith("URL-")
                ]
                model_related = {
                    str(value).strip()
                    for value in (row.get("related_sources") or [])
                    if str(value).strip()
                }
                source_values = [
                    value for value in requirement_sources
                    if value in model_related
                ]
                if not source_values and requirement_sources:
                    source_values = requirement_sources[:1]
                source_values = source_values[:1]
                detail_rows = (
                    '<p class="dr-trace-model-description__item">'
                    f'{cls.html_attr(purpose)}'
                    "</p>"
                )
                if source_values:
                    detail_rows += (
                        '<p class="dr-trace-model-description__item">'
                        f'<strong>Source</strong>: {cls.html_attr(", ".join(dict.fromkeys(source_values)))}'
                        "</p>"
                    )
                return f'<div class="dr-trace-model-description">{detail_rows}</div>'

            image_path = normalize_dr_model_path(row.get("image_path"))
            if image_path:
                return (
                    f'<img src="{cls.html_attr(image_path)}" '
                    f'alt="{cls.html_attr(row.get("name") or row.get("id") or "System Model")}" '
                    'onerror="this.hidden=true">'
                    f'{model_details_html()}'
                )
            return model_details_html()

        def feedback_card_html(row: Dict[str, Any]) -> str:
            feedback_type = str(row.get("type") or "Feedback").strip()
            label = feedback_type[:1].upper() + feedback_type[1:] if feedback_type else "Feedback"
            content = cls.clean_repeated_text(row.get("content"))
            return (
                '<div class="dr-trace-card">'
                f'<div class="dr-trace-card__main"><strong>{cls.html_attr(label)}</strong>: '
                f'{cls.html_attr(content)}</div>'
                "</div>"
            )

        for statement_index, row in enumerate(requirement.get("stakeholder_statements") or [], start=1):
            if not isinstance(row, dict):
                continue
            stakeholder = cls.dr_stakeholder_name(row.get("stakeholder"))
            statement_id = str(row.get("id") or "").strip()
            display_id = statement_id
            label = f"{display_id} {stakeholder}".strip()
            statement_text = str(row.get("text") or "").strip()
            card_html = (
                '<div class="dr-trace-card">'
                f'<div class="dr-trace-card__main">{cls.html_attr(f"發言：{statement_text}")}</div>'
                + "</div>"
            )
            add_node(
                row.get("id"),
                "Stakeholder Statement",
                label,
                card_html,
                "Source",
                content_format="html",
                title=f"{display_id} {stakeholder}".strip(),
            )

        for row in requirement.get("user_requirements") or []:
            if not isinstance(row, dict):
                continue
            url_id = str(row.get("id") or "").strip()
            requirement_text = str(row.get("text") or "").strip()
            label = f"{url_id}: {cls.dr_summary(requirement_text, 16)}".strip()
            stakeholder = cls.dr_stakeholder_name(row.get("stakeholder"))
            source_id = str(row.get("source_id") or "").strip()
            card_html = (
                '<div class="dr-trace-card">'
                f'<div class="dr-trace-card__main">{cls.html_attr(f"{url_id}：{requirement_text}")}</div>'
                + "</div>"
            )
            add_node(
                row.get("id"),
                "User Requirement",
                label,
                card_html,
                "User Requirement",
                content_format="html",
                title=url_id,
            )
            if url_id in nodes:
                source_values = []
                if source_id:
                    source_values.append(source_id)
                source_values.extend(
                    str(value).strip()
                    for value in (row.get("related_statement_ids") or [])
                    if str(value).strip()
                )
                nodes[url_id]["source"] = "、".join(dict.fromkeys(source_values))

        for row in requirement.get("user_requirements") or []:
            if not isinstance(row, dict):
                continue
            stakeholder = cls.dr_stakeholder_name(row.get("stakeholder"))
            source_ids = []
            source_id = str(row.get("source_id") or "").strip()
            source_ref = str(row.get("source") or "").strip()
            if not source_id and re.fullmatch(r"R\d+-M\d+", source_ref, flags=re.IGNORECASE):
                source_id = source_ref
            if source_id:
                source_ids.append(source_id)
            source_ids.extend(
                str(value).strip()
                for value in (row.get("related_statement_ids") or [])
                if str(value).strip()
            )
            for source_id in source_ids:
                if source_id in nodes:
                    continue
                display_source_id = source_id
                if source_id.startswith("ST-URL-"):
                    display_source_id = source_id.removeprefix("ST-")
                add_node(
                    source_id,
                    "Source",
                    f"{display_source_id} {stakeholder}".strip(),
                    f"來源：{source_id}",
                    "Source",
                    title=f"{display_source_id} {stakeholder}".strip(),
                )

        for row in requirement.get("conflicts") or []:
            if not isinstance(row, dict):
                continue
            conflict_id = str(row.get("id") or "").strip()
            conflict_title = cls.clean_repeated_text(
                row.get("report_title")
                or row.get("title")
                or row.get("description")
            )
            label = f"{conflict_id} {conflict_title}".strip() if conflict_title else conflict_id
            add_node(
                row.get("id"),
                "Conflict",
                label,
                conflict_report_html(row),
                "Analysis",
                content_format="html",
                title=label,
            )

        for row in requirement.get("system_models") or []:
            if not isinstance(row, dict):
                continue
            model_id = str(row.get("id") or "").strip()
            model_name = cls.clean_repeated_text(row.get("name") or row.get("type"))
            label = f"{model_id} {model_name}".strip()
            title = f"{model_id}：{model_name}".strip("：") if model_name else model_id
            add_node(
                row.get("id"),
                "System Model",
                label,
                model_image_html(row),
                "Analysis",
                content_format="html",
                title=title,
                metadata={
                    "related_sources": [
                        str(value).strip()
                        for value in (row.get("related_sources") or [])
                        if str(value).strip()
                    ],
                },
            )

        for row in requirement.get("meetings") or []:
            if not isinstance(row, dict):
                continue
            topic = cls.clean_repeated_text(row.get("title") or row.get("topic"))
            label = f"{row.get('id')} {topic or '會議'}".strip()
            mom_text = str(row.get("mom_text") or "").strip()
            content_format = "text"
            if mom_text:
                content = markdown_to_html(cls.mom_body_without_title(mom_text))
                content_format = "html"
            else:
                content = content_from(row, ["topic", "participants", "description", "decision"])
            meeting_id = str(row.get("id") or "").strip()
            title = f"{meeting_id}：{topic}".strip("：") if topic else meeting_id
            add_node(
                row.get("id"),
                "Meeting Discussion",
                label,
                content,
                "Meeting",
                title=title,
                content_format=content_format,
            )

        add_node(
            target_id,
            "Requirement",
            f"{target_id}: {str(requirement.get('title') or '').strip()}".strip(": "),
            str(requirement.get("description") or "").strip(),
            "Requirement",
        )

        stakeholder_rows = [row for row in requirement.get("stakeholder_statements") or [] if isinstance(row, dict)]
        url_rows = [row for row in requirement.get("user_requirements") or [] if isinstance(row, dict)]
        conflict_rows = [row for row in requirement.get("conflicts") or [] if isinstance(row, dict)]
        feedback_rows = [row for row in requirement.get("feedback") or [] if isinstance(row, dict)]
        model_rows = [row for row in requirement.get("system_models") or [] if isinstance(row, dict)]
        meeting_rows = [row for row in requirement.get("meetings") or [] if isinstance(row, dict)]
        current_url_ids = [
            str(row.get("id") or "").strip()
            for row in url_rows
            if str(row.get("id") or "").strip()
        ]

        def feedback_display_sources(row: Dict[str, Any]) -> List[str]:
            related = [
                str(item).strip()
                for item in (row.get("related_sources") or [])
                if str(item).strip() in current_url_ids
            ]
            if not related:
                related = [
                    str(item).strip()
                    for item in (row.get("related_user_requirements") or [])
                    if str(item).strip() in current_url_ids
                ]
            if not related:
                related = list(current_url_ids)
            return list(dict.fromkeys(related))

        if len(feedback_rows) > 1:
            table_rows = []
            for row in feedback_rows:
                row_id = str(row.get("id") or "").strip()
                if not row_id:
                    continue
                source_chips = "".join(
                    f'<span class="dr-trace-source-chip">{cls.html_attr(str(item).strip())}</span>'
                    for item in feedback_display_sources(row)
                    if str(item).strip()
                )
                table_rows.append(
                    "<tr>"
                    f"<td>{cls.html_attr(row_id)}</td>"
                    f"<td>{cls.html_attr(row.get('type') or '')}</td>"
                    f"<td>{cls.html_attr(cls.clean_repeated_text(row.get('content')))}</td>"
                    f"<td>{source_chips}</td>"
                    "</tr>"
                )
            feedback_content = (
                '<table class="dr-trace-feedback-table dr-trace-feedback-group-table"><thead><tr>'
                "<th>ID</th><th>Type</th><th>Feedback</th><th>Source</th>"
                "</tr></thead><tbody>"
                + "".join(table_rows)
                + "</tbody></table>"
            )
            feedback_related_sources = []
            feedback_grouped_ids = []
            for row in feedback_rows:
                row_id = str(row.get("id") or "").strip()
                if row_id:
                    feedback_grouped_ids.append(row_id)
                feedback_related_sources.extend(
                    str(item).strip()
                    for item in feedback_display_sources(row)
                    if str(item).strip()
                )
            feedback_rows = [{
                "id": f"FB-GROUP-{target_id}",
                "type": "Feedback Group",
                "count": len(table_rows),
                "content": feedback_content,
                "related_sources": list(dict.fromkeys(feedback_related_sources)),
                "grouped_ids": list(dict.fromkeys(feedback_grouped_ids)),
                "trace_confidence": "explicit",
                "trace_reason": "Multiple feedback items are grouped for topology readability; each item remains listed in the DR trace and appendix.",
                "content_format": "html",
            }]

        for row in feedback_rows:
            if str(row.get("id") or "").startswith("FB-GROUP-"):
                feedback_count = int(row.get("count") or 0)
                label = f"Feedback（{feedback_count} 筆）"
                title = f"Feedback（{feedback_count} 筆）"
            else:
                feedback_count = 1
                label = "Feedback"
                title = "Feedback"
            add_node(
                row.get("id"),
                "Feedback",
                label,
                str(row.get("content") or "") if str(row.get("content_format") or "") == "html" else feedback_card_html(row),
                "Analysis",
                content_format=str(row.get("content_format") or "html"),
                title=title,
            )
            feedback_id = str(row.get("id") or "").strip()
            if feedback_id in nodes and row.get("grouped_ids"):
                nodes[feedback_id]["grouped_ids"] = list(row.get("grouped_ids") or [])

        for url in url_rows:
            url_source_id = str(url.get("source_id") or "").strip()
            if url_source_id:
                add_edge(url_source_id, url.get("id"), "分析")
                continue
            for source_id in url.get("related_statement_ids") or []:
                add_edge(source_id, url.get("id"), "分析")

        for conflict in conflict_rows:
            related_sources = [str(item).strip() for item in (conflict.get("related_user_requirements") or []) if str(item).strip()]
            for source_id in related_sources:
                add_edge(source_id, conflict.get("id"), "衝突")

        conflict_ids = [str(row.get("id") or "").strip() for row in conflict_rows if str(row.get("id") or "").strip()]
        feedback_ids = [str(row.get("id") or "").strip() for row in feedback_rows if str(row.get("id") or "").strip()]
        model_ids = [str(row.get("id") or "").strip() for row in model_rows if str(row.get("id") or "").strip()]
        url_ids = [str(row.get("id") or "").strip() for row in url_rows if str(row.get("id") or "").strip()]
        primary_url_ids = [
            str(item).strip()
            for item in (requirement.get("source") or [])
            if str(item).strip() in url_ids
        ]
        if not primary_url_ids and url_ids:
            primary_url_ids = [url_ids[0]]
        meeting_ids = [str(row.get("id") or "").strip() for row in meeting_rows if str(row.get("id") or "").strip()]
        requirement_req_id = str(requirement.get("id") or "").strip()
        shared_model_ids: set[str] = set()
        for model in model_rows:
            model_id = str(model.get("id") or "").strip()
            related_sources = [
                str(item).strip()
                for item in (model.get("related_sources") or [])
                if str(item).strip()
            ]
            related_req_ids = [
                str(item).strip()
                for item in (model.get("related_req") or [])
                if str(item).strip()
            ]
            direct_url_hits = list(dict.fromkeys(item for item in related_sources if item in url_ids))
            broad_url_model = len(direct_url_hits) > 1
            if model_id and broad_url_model:
                shared_model_ids.add(model_id)
        for model_id in shared_model_ids:
            if model_id in nodes:
                nodes[model_id]["column"] = "Background"

        def related_url_ids(row: Dict[str, Any]) -> List[str]:
            row_id = str(row.get("id") or "").strip()
            if row_id in shared_model_ids:
                return []
            related = [
                str(item).strip()
                for item in (row.get("related_sources") or [])
                if str(item).strip() in url_ids
            ]
            if not related:
                related = [
                    str(item).strip()
                    for item in (row.get("related_user_requirements") or [])
                    if str(item).strip() in url_ids
                ]
            if not related and row_id not in shared_model_ids:
                related = list(url_ids)
            return list(dict.fromkeys(related))

        for feedback in feedback_rows:
            feedback_id = str(feedback.get("id") or "").strip()
            if not feedback_id:
                continue
            for url_id in related_url_ids(feedback):
                add_edge(url_id, feedback_id, "依據", style="dashed")
        for model in model_rows:
            model_id = str(model.get("id") or "").strip()
            if not model_id:
                continue
            for url_id in related_url_ids(model):
                add_edge(url_id, model_id, "建模", style="dashed")

        meeting_by_id = {
            str(row.get("id") or "").strip(): row
            for row in meeting_rows
            if str(row.get("id") or "").strip()
        }
        formalization_meeting_ids = [
            meeting_id
            for meeting_id in meeting_ids
            if cls.is_requirement_formalization_meeting(meeting_by_id.get(meeting_id, {}))
        ]
        conflict_resolution_meeting_ids = [
            meeting_id
            for meeting_id in meeting_ids
            if cls.is_conflict_resolution_meeting(meeting_by_id.get(meeting_id, {}))
        ]
        clarification_meeting_ids = [
            meeting_id
            for meeting_id in meeting_ids
            if cls.is_requirement_clarification_meeting(meeting_by_id.get(meeting_id, {}))
        ]
        explicit_feedback_meeting_ids = set()
        explicit_model_meeting_ids = set()
        for meeting_id in meeting_ids:
            meeting = meeting_by_id.get(meeting_id, {})
            is_formalization_meeting = cls.is_requirement_formalization_meeting(meeting)
            source_ids = {
                str(source_id).strip()
                for source_id in (meeting.get("source_ids") or [])
                if str(source_id).strip()
            }
            for feedback_id in feedback_ids:
                if feedback_id in source_ids:
                    explicit_feedback_meeting_ids.add(feedback_id)
            for feedback in feedback_rows:
                feedback_id = str(feedback.get("id") or "").strip()
                if not feedback_id:
                    continue
                feedback_source_ids = {
                    str(source_id).strip()
                    for source_id in (feedback.get("source_ids") or [])
                    if str(source_id).strip()
                }
                if meeting_id in feedback_source_ids:
                    explicit_feedback_meeting_ids.add(feedback_id)
            for model_id in model_ids:
                if model_id in source_ids:
                    explicit_model_meeting_ids.add(model_id)
            for model in model_rows:
                model_id = str(model.get("id") or "").strip()
                if not model_id:
                    continue
                model_source_ids = {
                    str(source_id).strip()
                    for source_id in (model.get("source_ids") or [])
                    if str(source_id).strip()
                }
                if meeting_id in model_source_ids:
                    explicit_model_meeting_ids.add(model_id)

        if meeting_ids:
            first_conflict_resolution_meeting_id = (
                conflict_resolution_meeting_ids[0] if conflict_resolution_meeting_ids else ""
            )
            entry_meeting_id = first_conflict_resolution_meeting_id if conflict_ids else ""
            for conflict_id in conflict_ids:
                has_conflict_source = any(
                    str(edge.get("to") or "").strip() == conflict_id
                    and str(edge.get("from") or "").strip() in url_ids
                    for edge in edges
                )
                if not has_conflict_source:
                    for url_id in url_ids:
                        add_edge(url_id, conflict_id, "衝突")
            for index, meeting_id in enumerate(meeting_ids):
                meeting = meeting_by_id.get(meeting_id, {})
                is_formalization_meeting = cls.is_requirement_formalization_meeting(meeting)
                has_prior_formalization = any(
                    cls.is_requirement_formalization_meeting(meeting_by_id.get(prior_id, {}))
                    for prior_id in meeting_ids[:index]
                )
                if cls.is_conflict_resolution_meeting(meeting):
                    for conflict_id in conflict_ids:
                        add_edge(conflict_id, meeting_id, "解決")
                if index > 0:
                    previous_meeting = meeting_by_id.get(meeting_ids[index - 1], {})
                    if (
                        is_formalization_meeting
                        and not has_prior_formalization
                        and (
                            cls.is_conflict_resolution_meeting(previous_meeting)
                            or str(meeting_ids[index - 1]).strip() == "R1-M1"
                        )
                    ):
                        relation = "正式化"
                    elif cls.is_requirement_clarification_meeting(meeting) or has_prior_formalization:
                        relation = "精煉"
                    else:
                        relation = ""
                    add_edge(meeting_ids[index - 1], meeting_id, relation)
                if is_formalization_meeting:
                    formalization_sources: List[str] = []
                    if not conflict_ids:
                        formalization_sources = primary_url_ids
                    for source_id in formalization_sources:
                        add_edge(source_id, meeting_id, "精煉" if has_prior_formalization else "正式化")
            if not formalization_meeting_ids and not conflict_ids and meeting_ids:
                for source_id in primary_url_ids:
                    add_edge(source_id, meeting_ids[0], "正式化")

            primary_formalization_meeting_id = formalization_meeting_ids[-1] if formalization_meeting_ids else ""
            for meeting_id in meeting_ids:
                if meeting_id in formalization_meeting_ids or meeting_id in clarification_meeting_ids:
                    continue
                if cls.is_conflict_resolution_meeting(meeting_by_id.get(meeting_id, {})):
                    continue
                if primary_formalization_meeting_id:
                    if (
                        cls.meeting_order_key(meeting_by_id.get(meeting_id, {"id": meeting_id}))
                        > cls.meeting_order_key(meeting_by_id.get(primary_formalization_meeting_id, {"id": primary_formalization_meeting_id}))
                    ):
                        continue
                    add_edge(meeting_id, primary_formalization_meeting_id, "")
                else:
                    add_edge(meeting_id, target_id, "")

            if clarification_meeting_ids:
                terminal_meeting_id = clarification_meeting_ids[-1]
                add_edge(terminal_meeting_id, target_id, "")
            elif formalization_meeting_ids:
                terminal_meeting_id = meeting_ids[-1] if meeting_ids else formalization_meeting_ids[-1]
                add_edge(terminal_meeting_id, target_id, "")
        else:
            for url_id in primary_url_ids:
                add_edge(url_id, target_id, "")

        return cls.visible_trace_graph(
            all_nodes=list(nodes.values()),
            edges=edges,
            target_id=target_id,
        )
