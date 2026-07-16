# Handles draft creation, updates, and draft content assembly.
import ast
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.base import parse_json_object
from storage.markdown import normalize_model_image_markdown
from storage.plantuml import plantuml_safe_name

from .actions.draft.create import create_draft
from .actions.draft.update import update_draft
from storage.requirements import requirement_discussion_pool


draft_section_order = [
    "scope",
    "user_requirements",
    "system_requirement",
    "feedback",
    "open_questions",
    "system_models",
]

create_draft_sections = {
    "scope",
    "user_requirements",
    "feedback",
    "open_questions",
    "system_models",
}

update_draft_sections = set(draft_section_order)


def draft_stakeholders(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for stakeholder in artifact.get("stakeholders", []) or []:
        if not isinstance(stakeholder, dict):
            continue
        name = str(stakeholder.get("name") or "").strip()
        if not name:
            continue
        row = {"name": name}
        stakeholder_type = str(stakeholder.get("type") or "").strip()
        if stakeholder_type:
            row["type"] = stakeholder_type
        text = stakeholder.get("text")
        if isinstance(text, list):
            clean_texts = [
                str(item).strip()
                for item in text
                if str(item).strip()
            ]
            if clean_texts:
                row["text"] = clean_texts
        elif str(text or "").strip():
            row["text"] = str(text).strip()
        rows.append(row)
    return rows


def draft_open_questions(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    for question in artifact.get("open_questions", []) or []:
        if not isinstance(question, dict):
            continue
        text = str(question.get("question") or "").strip()
        if not text:
            continue
        row = {"question": text}
        for key in ("id", "to", "owner", "status", "source", "related_source", "type"):
            value = question.get(key)
            if value:
                row[key] = value
        rows.append(row)
    return rows


def draft_resolution_open_questions(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for discussion in artifact.get("discussions", []) or []:
        if not isinstance(discussion, dict):
            continue
        for issue in discussion.get("issues", []) or []:
            if not isinstance(issue, dict):
                continue
            resolution = issue.get("resolution") if isinstance(issue.get("resolution"), dict) else {}
            if not resolution:
                continue
            related_source = [
                str(value).strip()
                for value in (
                    issue.get("meeting_id"),
                    issue.get("issue_id"),
                    *(resolution.get("affected_requirement_ids") or []),
                    *(resolution.get("affected_conflict_ids") or []),
                )
                if str(value or "").strip()
            ]
            for question in list(resolution.get("open_questions") or []):
                if isinstance(question, str):
                    row = {"question": question}
                elif isinstance(question, dict):
                    row = dict(question)
                else:
                    continue
                text = str(row.get("question") or "").strip()
                if not text:
                    continue
                row["question"] = text
                if not row.get("status"):
                    row["status"] = "open"
                if not row.get("related_source") and related_source:
                    row["related_source"] = related_source
                rows.append(row)
    return rows


def consolidated_draft_open_questions(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def add(row: Dict[str, Any], *, default_source: str = "") -> None:
        text = str(row.get("question") or "").strip()
        if not text:
            return
        status = str(row.get("status") or "open").strip().lower()
        if status not in {"open", "pending", "unresolved"}:
            return
        key = re.sub(r"\s+", "", text).lower()
        if key in seen:
            return
        seen.add(key)
        item: Dict[str, Any] = {"question": text, "status": status}
        for field in ("id", "to", "type"):
            value = row.get(field)
            if value:
                item[field] = value
        related = row.get("related_source") or row.get("source") or default_source
        if isinstance(related, list):
            related_rows = [str(value).strip() for value in related if str(value).strip()]
            if related_rows:
                item["related_source"] = related_rows
        elif str(related or "").strip():
            item["related_source"] = str(related).strip()
        rows.append(item)

    for row in draft_resolution_open_questions(artifact):
        add(row)
    for row in draft_open_questions(artifact):
        add(row)
    return rows


def compact_draft_action_result(result: Dict[str, Any]) -> Dict[str, Any]:
    action = str(result.get("action") or "").strip()
    compact: Dict[str, Any] = {}
    if action:
        compact["action"] = action
    status = str(result.get("status") or "").strip()
    if status:
        compact["status"] = status

    for key in ("summary", "decision", "message"):
        value = str(result.get(key) or "").strip()
        if value:
            compact[key] = value

    artifact_updates = result.get("artifact_updates")
    if isinstance(artifact_updates, dict) and artifact_updates:
        compact["artifact_updates"] = artifact_updates

    for source_key, output_key in (
        ("updated_requirement_ids", "updated_requirement_ids"),
        ("created_requirement_ids", "created_requirement_ids"),
        ("affected_requirement_ids", "affected_requirement_ids"),
        ("affected_conflict_ids", "affected_conflict_ids"),
        ("updated_model_ids", "updated_model_ids"),
        ("created_model_ids", "created_model_ids"),
        ("updated_feedback_ids", "updated_feedback_ids"),
    ):
        values = result.get(source_key)
        if isinstance(values, list):
            clean_values = [str(value).strip() for value in values if str(value).strip()]
            if clean_values:
                compact[output_key] = clean_values

    for source_key, output_key in (
        ("requirements", "requirement_count"),
        ("REQ", "requirement_count"),
        ("system_models", "system_model_count"),
        ("feedback", "feedback_sections"),
    ):
        value = result.get(source_key)
        if isinstance(value, list):
            compact[output_key] = len(value)
        elif isinstance(value, dict) and source_key == "feedback":
            compact[output_key] = [
                key for key, rows in value.items()
                if isinstance(rows, list) and rows
            ]

    return compact


def draft_feedback(artifact: Dict[str, Any]) -> Dict[str, Any]:
    feedback = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
    out: Dict[str, Any] = {}
    for section in ("findings", "constraints", "risks", "recommendations"):
        rows: List[Dict[str, Any]] = []
        for item in feedback.get(section) or []:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            row: Dict[str, Any] = {"text": text}
            related = item.get("related_requirement_ids")
            if isinstance(related, list):
                related_rows = [str(value).strip() for value in related if str(value).strip()]
                if related_rows:
                    row["related_requirement_ids"] = related_rows
            source = str(item.get("source") or "").strip()
            if source:
                row["source"] = source
            rows.append(row)
        if rows:
            out[section] = rows
    sources: List[Any] = []
    seen_sources = set()
    for source in feedback.get("sources") or []:
        if not isinstance(source, dict):
            continue
        key = str(source.get("url") or "").strip()
        clean_source = dict(source)
        if key and key not in seen_sources:
            sources.append(clean_source)
            seen_sources.add(key)
    if sources:
        out["sources"] = sources
    return out


def draft_meeting_context(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for discussion in artifact.get("discussions", []) or []:
        if not isinstance(discussion, dict):
            continue
        round_num = discussion.get("round")
        for issue in discussion.get("issues", []) or []:
            if not isinstance(issue, dict):
                continue
            row: Dict[str, Any] = {
                "round": round_num,
                "meeting_id": issue.get("meeting_id"),
                "issue_id": issue.get("issue_id"),
            }
            action_results = []
            for entry in issue.get("conversation", []) or []:
                if not isinstance(entry, dict):
                    continue
                response = entry.get("response") if isinstance(entry.get("response"), dict) else {}
                results = response.get("action_results")
                if not isinstance(results, list) or not results:
                    continue
                compact_results = [
                    compact_draft_action_result(result)
                    for result in results
                    if isinstance(result, dict)
                ]
                compact_results = [result for result in compact_results if result]
                if not compact_results:
                    continue
                item = {
                    "agent": entry.get("agent"),
                    "actions": entry.get("actions", []) or [],
                    "results": compact_results,
                }
                action_results.append(item)
            if action_results:
                row["action_results"] = action_results
            resolution = issue.get("resolution") if isinstance(issue.get("resolution"), dict) else {}
            if resolution:
                row["resolution"] = {
                    "status": resolution.get("status"),
                    "summary": resolution.get("summary"),
                    "decision": resolution.get("decision"),
                    "affected_requirement_ids": resolution.get("affected_requirement_ids", []) or [],
                    "affected_conflict_ids": resolution.get("affected_conflict_ids", []) or [],
                    "artifact_updates": resolution.get("artifact_updates", {}) or {},
                }
            if row.get("action_results") or row.get("resolution"):
                rows.append(row)
    return rows


def draft_system_models(
    artifact: Dict[str, Any],
    artifact_dir: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    type_labels = {
        "context_diagram": "情境圖",
        "use_case_diagram": "Use Case Diagram",
        "activity_diagram": "Activity Diagram",
        "sequence_diagram": "Sequence Diagram",
        "state_machine": "State Machine Diagram",
        "class_diagram": "Class Diagram",
    }
    artifact_path = Path(artifact_dir) if artifact_dir else None
    rows: List[Dict[str, Any]] = []
    for model in artifact.get("system_models", []) or []:
        if not isinstance(model, dict):
            continue
        model_type = str(model.get("type") or "").strip()
        name = str(model.get("name") or "").strip()
        if not model_type and not name:
            continue
        row: Dict[str, Any] = {}
        model_id = str(model.get("id") or "").strip()
        if model_id:
            row["id"] = model_id
        if name:
            row["name"] = name
        if model_type:
            row["type"] = model_type
            row["display_type"] = type_labels.get(
                model_type,
                model_type.replace("_", " ").title(),
            )
        description = str(model.get("description") or "").strip()
        if model_type == "use_case_diagram":
            description = ""
        if description:
            row["description"] = description
        related_requirement_ids = [
            str(value).strip()
            for value in (model.get("related_requirement_ids") or [])
            if str(value).strip()
        ]
        if related_requirement_ids:
            row["related_requirement_ids"] = related_requirement_ids
        if model.get("text"):
            row["text"] = model.get("text")
        plantuml = str(model.get("plantuml") or "").strip()
        row["has_plantuml"] = bool(plantuml)
        if row["has_plantuml"] and artifact_path:
            filename = f"{plantuml_safe_name(model)}.png"
            if (artifact_path / "models" / filename).is_file():
                row["image_path"] = f"../models/{filename}"
        if row["has_plantuml"] and not row.get("image_path"):
            row["plantuml"] = plantuml
        rows.append(row)
    return rows


def draft_requirement_id_issues(md: str, expected_ids: set[str]) -> tuple[List[str], List[str]]:
    draft_req_ids = set(re.findall(r"\bURL-\d+\b", md or ""))
    unknown_ids = sorted(draft_req_ids - expected_ids)
    missing_ids = sorted(expected_ids - draft_req_ids)
    return unknown_ids, missing_ids


def draft_contract_issues(
    md: str,
    req_rows: List[Dict[str, Any]],
    *,
    require_system_requirement: bool = False,
) -> List[str]:
    issues: List[str] = []
    source = md or ""
    forbidden_patterns = {
        "contains_placeholder": (
            r"(?m)(?:^|[|:：\-*#\s])(?:待補|TBD|TODO|未填|未定|待確認|待釐清)(?:[|,，。；;:：\s]|$)"
        ),
        "contains_ellipsis_summary": (
            r"其餘(?:需求|項目|內容|條目|REQ|URL|部分)?(?:同上|略|依輸入資料內容)"
            r"|格式同上"
            r"|依輸入資料內容"
            r"|省略(?:如下|如下列|同上|不列|未列)"
            r"|^\s*略\s*$"
        ),
        "contains_json_fence": r"```json",
        "contains_meeting_context": r"(?m)^##\s+(?:meeting_context|Meeting Context)\s*$",
        "contains_empty_open_questions": r"本草稿階段無已知\s*open_questions|目前無(?:已知)?\s*open_questions",
    }
    for name, pattern in forbidden_patterns.items():
        if re.search(pattern, source, flags=re.IGNORECASE):
            issues.append(name)

    traceability_match = re.search(r"(?ms)^##\s+Traceability\s*\n.*?(?=^##\s+|\Z)", source)
    has_requirements_section = bool(re.search(r"(?m)^##\s+Requirements\s*$", source))
    has_system_requirement_section = bool(re.search(r"(?m)^##\s+System Requirement\s*$", source))
    if has_requirements_section:
        issues.append("unexpected_requirements")
    if not require_system_requirement and has_system_requirement_section:
        issues.append("unexpected_system_requirement")

    req_ids = [
        str(row.get("id") or "").strip()
        for row in (req_rows or [])
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    ]
    if req_ids and require_system_requirement:
        if not has_system_requirement_section:
            issues.append("missing_system_requirement")
        detail_heading_ids = set(re.findall(r"(?m)^###\s+(REQ-\d+)\b", source))
        missing_detail_ids = [req_id for req_id in req_ids if req_id not in detail_heading_ids]
        if missing_detail_ids:
            issues.append("missing_system_requirement_rows:" + ",".join(missing_detail_ids))
    if traceability_match:
        issues.append("unexpected_traceability")

    scalar_empty_patterns = [
        r"(?m)^-\s+Validation:\s*$",
        r"(?m)^-\s+Rationale:\s*$",
        r"(?m)^-\s+Source:\s*$",
    ]
    list_fields = {"Acceptance Criteria", "Risks", "Assumptions"}
    lines = source.splitlines()
    has_empty_list_field = False
    for idx, line in enumerate(lines):
        match = re.match(r"^-\s+(.+?):\s*$", line)
        if not match or match.group(1) not in list_fields:
            continue
        next_nonempty = ""
        for following in lines[idx + 1:]:
            if following.strip():
                next_nonempty = following
                break
        if not next_nonempty.startswith("  - "):
            has_empty_list_field = True
            break
    if any(re.search(pattern, source) for pattern in scalar_empty_patterns) or has_empty_list_field:
        issues.append("contains_empty_detail_fields")
    return issues


def markdown_list(items: Any, *, indent: str = "  - ") -> List[str]:
    if not isinstance(items, list):
        return []
    return [f"{indent}{str(item).strip()}" for item in items if str(item).strip()]


def req_source_text(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = ast.literal_eval(text)
                if isinstance(parsed, list):
                    return ", ".join(str(item).strip() for item in parsed if str(item).strip())
            except (ValueError, SyntaxError):
                pass
        return text
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def markdown_table_cell(value: Any) -> str:
    if isinstance(value, list):
        text = "、".join(str(item).strip() for item in value if str(item).strip())
    elif isinstance(value, dict):
        text = "、".join(
            f"{str(key).strip()}：{str(item).strip()}"
            for key, item in value.items()
            if str(key).strip() and str(item).strip()
        )
    else:
        text = str(value or "").strip()
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = ast.literal_eval(text)
                if isinstance(parsed, list):
                    text = "、".join(str(item).strip() for item in parsed if str(item).strip())
            except (ValueError, SyntaxError):
                pass
    return text.replace("|", "\\|").replace("\n", "<br>")


def markdown_source_link(source: Any, index: int) -> str:
    title = ""
    url = ""
    if isinstance(source, dict):
        title = str(source.get("title") or "").strip()
        url = str(source.get("url") or "").strip()
    if not url:
        return ""
    if not title:
        title = re.sub(r"^https?://(?:www\.)?", "", url).split("/")[0] or f"Source {index}"
    if re.match(r"^https?://", url):
        return f"[{title}](<{url}>)"
    return title if title == url else f"{title} ({url})"


def source_label(row: Dict[str, Any]) -> str:
    source = req_source_text(row.get("source"))
    if source:
        return source
    return "initial"


def stakeholder_label(row: Dict[str, Any]) -> str:
    stakeholder = row.get("stakeholder")
    if isinstance(stakeholder, dict):
        name = str(stakeholder.get("name") or "").strip()
        if name:
            return name
    return ""


def render_draft_title(context: Dict[str, Any]) -> str:
    _ = context
    return "# Draft"


def render_scope_section(scope: Dict[str, Any]) -> str:
    if not isinstance(scope, dict):
        return ""
    lines: List[str] = []
    in_scope = [
        str(item).strip()
        for item in (scope.get("in_scope") or [])
        if str(item).strip()
    ]
    out_scope = [
        str(item).strip()
        for item in (scope.get("out_of_scope") or [])
        if str(item).strip()
    ]
    if not in_scope and not out_scope:
        return ""
    lines.extend(["## Scope", ""])
    if in_scope:
        lines.extend(["### In Scope"])
        lines.extend(f"- {item}" for item in in_scope)
        lines.append("")
    if out_scope:
        lines.extend(["### Out of Scope"])
        lines.extend(f"- {item}" for item in out_scope)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_user_requirements_section(url_rows: List[Dict[str, Any]]) -> str:
    rows = [row for row in (url_rows or []) if isinstance(row, dict)]
    if not rows:
        return ""
    lines = [
        "## User Requirements",
        "| ID | Stakeholder | Requirement | Source |",
        "|---|---|---|---|",
    ]
    for row in rows:
        source_id = str(row.get("id") or "").strip()
        text = str(row.get("text") or "").strip()
        if not source_id or not text:
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_table_cell(source_id),
                    markdown_table_cell(stakeholder_label(row)),
                    markdown_table_cell(text),
                    markdown_table_cell(source_label(row)),
                ]
            )
            + " |"
        )
    return "\n".join(lines).rstrip() + "\n" if len(lines) > 3 else ""


def render_feedback_section(feedback: Dict[str, Any]) -> str:
    if not isinstance(feedback, dict):
        return ""
    section_labels = {
        "findings": "Findings",
        "constraints": "Constraints",
        "risks": "Risks",
        "recommendations": "Recommendations",
    }
    lines: List[str] = ["## Feedback", ""]
    has_content = False
    for key, label in section_labels.items():
        rows = [row for row in (feedback.get(key) or []) if isinstance(row, dict)]
        if not rows:
            continue
        has_content = True
        lines.append(f"### {label}")
        for row in rows:
            text = str(row.get("text") or "").strip()
            if text:
                lines.append(f"- {text}")
        lines.append("")
    sources: List[Any] = []
    seen_sources = set()
    for source in feedback.get("sources") or []:
        if isinstance(source, dict):
            key = str(source.get("url") or source).strip()
            clean_source = source
        else:
            key = str(source or "").strip()
            clean_source = key
        if key and key not in seen_sources:
            sources.append(clean_source)
            seen_sources.add(key)
    if sources:
        has_content = True
        lines.append("### Sources")
        for index, source in enumerate(sources, 1):
            link = markdown_source_link(source, index)
            if link:
                lines.append(f"- {link}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n" if has_content else ""


def render_open_questions_section(open_questions: List[Dict[str, Any]]) -> str:
    rows = [row for row in (open_questions or []) if isinstance(row, dict)]
    if not rows:
        return ""
    lines = [
        "## Open Questions",
        "| ID | Question | Source |",
        "|---|---|---|",
    ]
    for index, row in enumerate(rows, 1):
        question = str(row.get("question") or "").strip()
        if not question:
            continue
        question_id = str(row.get("id") or "").strip() or f"OQ-{index}"
        related = row.get("related_source") or ""
        if isinstance(related, list):
            related_text = ", ".join(str(value).strip() for value in related if str(value).strip())
        else:
            related_text = str(related or "").strip()
        lines.append(
            f"| {markdown_table_cell(question_id)} | "
            f"{markdown_table_cell(question)} | "
            f"{markdown_table_cell(related_text)} |"
        )
    return "\n".join(lines).rstrip() + "\n" if len(lines) > 3 else ""


def render_system_models_section(
    system_models: List[Dict[str, Any]],
    valid_req_ids: Optional[set[str]] = None,
) -> str:
    rows = [row for row in (system_models or []) if isinstance(row, dict)]
    if not rows:
        return ""
    lines = ["## System Models", ""]
    for row in rows:
        model_id = str(row.get("id") or "").strip()
        name = str(row.get("name") or "").strip()
        model_type = str(row.get("type") or "").strip()
        if not model_id and not name:
            continue
        title = " ".join(part for part in [model_id, name] if part)
        if model_type:
            title += f" ({model_type})"
        lines.append(f"### {title}")
        image_path = str(row.get("image_path") or "").strip()
        if image_path:
            image_label = name or model_id or "system model"
            lines.append("")
            lines.append(f"![{image_label}]({image_path})")
        description = str(row.get("description") or "").strip()
        if description and model_type != "use_case_diagram":
            lines.append("")
            lines.append(description)
        if model_type == "use_case_diagram":
            text_rows = [
                item for item in (row.get("text") or [])
                if isinstance(item, dict)
            ]
            if text_rows:
                lines.append("")
                grouped_rows: Dict[str, List[Dict[str, Any]]] = {}
                for item in text_rows:
                    actor = str(item.get("actor") or "未指定角色").strip()
                    grouped_rows.setdefault(actor, []).append(item)
                for actor_index, (actor, actor_rows) in enumerate(grouped_rows.items(), 1):
                    lines.append(f"#### {actor_index}. {actor}")
                    lines.append("")
                    lines.append("| UC ID | Use Case | Purpose | Interface | Related Requirement |")
                    lines.append("|---|---|---|---|---|")
                    for item in actor_rows:
                        related_values = []
                        for value in item.get("related_requirement_ids") or []:
                            req_id = str(value).strip()
                            if not req_id:
                                continue
                            if valid_req_ids is not None and req_id.startswith("REQ-") and req_id not in valid_req_ids:
                                continue
                            if req_id not in related_values:
                                related_values.append(req_id)
                        related = ", ".join(
                            related_values
                        )
                        lines.append(
                            "| "
                            f"{markdown_table_cell(item.get('id'))} | "
                            f"{markdown_table_cell(item.get('name'))} | "
                            f"{markdown_table_cell(item.get('purpose'))} | "
                            f"{markdown_table_cell(item.get('interface'))} | "
                            f"{markdown_table_cell(related)} |"
                        )
                    lines.append("")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_system_requirement_section(req_rows: List[Dict[str, Any]]) -> str:
    lines = ["## System Requirement", ""]
    for row in req_rows or []:
        if not isinstance(row, dict):
            continue
        req_id = str(row.get("id") or "").strip()
        if not req_id:
            continue
        title = str(row.get("title") or "").strip()
        lines.append(f"### {req_id}: {title}" if title else f"### {req_id}")
        field_pairs = [
            ("SRS ID", row.get("srs_id")),
            ("Type", row.get("type")),
            ("Priority", row.get("priority")),
            ("Description", row.get("description")),
        ]
        if str(row.get("type") or "").strip().lower() == "non-functional":
            field_pairs.extend([
                ("Category", row.get("category")),
                ("Metric", row.get("metric")),
                ("Validation", row.get("validation")),
            ])
        field_pairs.extend([
            ("Rationale", row.get("rationale")),
            ("Source", req_source_text(row.get("source"))),
        ])
        for label, value in field_pairs:
            text = str(value or "").strip()
            if text:
                lines.append(f"- {label}: {text}")
        for label, key in (
            ("Acceptance Criteria", "acceptance_criteria"),
            ("Risks", "risks"),
            ("Assumptions", "assumptions"),
        ):
            items = markdown_list(row.get(key))
            if items:
                lines.append(f"- {label}:")
                lines.extend(items)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_complete_draft(
    context: Dict[str, Any],
    *,
    require_system_requirement: bool,
    draft_plan: Optional[Dict[str, Any]] = None,
) -> str:
    sections: List[str] = [render_draft_title(context)]
    req_rows = [row for row in (context.get("REQ") or []) if isinstance(row, dict)]
    valid_req_ids = {
        str(row.get("id") or "").strip()
        for row in (context.get("REQ") or [])
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }
    plan = draft_plan if isinstance(draft_plan, dict) else default_draft_plan(
        context,
        mode="update" if require_system_requirement else "create",
    )
    include_by_id = {
        str(item.get("id") or "").strip(): bool(item.get("include"))
        for item in (plan.get("sections") or [])
        if isinstance(item, dict)
    }
    order = [
        section_id for section_id in (plan.get("section_order") or draft_section_order)
        if section_id in draft_section_order
    ]
    for section_id in draft_section_order:
        if section_id not in order:
            order.append(section_id)

    for section_id in order:
        if not include_by_id.get(section_id, False):
            continue
        if section_id == "scope":
            section = render_scope_section(context.get("scope") or {})
        elif section_id == "user_requirements":
            section = render_user_requirements_section(context.get("user_requirements") or [])
        elif section_id == "system_requirement":
            section = render_system_requirement_section(req_rows) if require_system_requirement and req_rows else ""
        elif section_id == "feedback":
            section = render_feedback_section(context.get("feedback") or {})
        elif section_id == "open_questions":
            section = render_open_questions_section(context.get("open_questions") or [])
        elif section_id == "system_models":
            section = render_system_models_section(
                context.get("system_models") or [],
                valid_req_ids or None,
            )
        else:
            section = ""
        if section:
            sections.append(section.rstrip())
    return normalize_model_image_markdown("\n\n".join(sections).strip() + "\n")


# Defines draft plan helpers for this module workflow.
def context_has_draft_section(context: Dict[str, Any], section_id: str) -> bool:
    if section_id == "scope":
        scope = context.get("scope") if isinstance(context.get("scope"), dict) else {}
        return bool(scope.get("in_scope") or scope.get("out_of_scope"))
    if section_id == "user_requirements":
        return any(isinstance(row, dict) for row in (context.get("user_requirements") or []))
    if section_id == "system_requirement":
        return any(isinstance(row, dict) for row in (context.get("REQ") or []))
    if section_id == "feedback":
        feedback = context.get("feedback") if isinstance(context.get("feedback"), dict) else {}
        return any(
            isinstance(feedback.get(key), list) and feedback.get(key)
            for key in ("findings", "constraints", "risks", "recommendations", "open_items")
        )
    if section_id == "open_questions":
        return any(isinstance(row, dict) for row in (context.get("open_questions") or []))
    if section_id == "system_models":
        return any(isinstance(row, dict) for row in (context.get("system_models") or []))
    return False


def default_draft_plan(context: Dict[str, Any], *, mode: str) -> Dict[str, Any]:
    allowed = create_draft_sections if mode == "create" else update_draft_sections
    order = [section_id for section_id in draft_section_order if section_id in allowed]
    sections = []
    for section_id in order:
        include = context_has_draft_section(context, section_id)
        if mode == "create" and section_id == "system_requirement":
            include = False
        sections.append({
            "id": section_id,
            "include": include,
        })
    return {
        "section_order": order,
        "sections": sections,
    }


def normalize_draft_plan(raw: Any, context: Dict[str, Any], *, mode: str) -> Dict[str, Any]:
    fallback = default_draft_plan(context, mode=mode)
    if not isinstance(raw, dict) or not isinstance(raw.get("draft_plan"), dict):
        raise ValueError("draft action output must contain draft_plan object")
    source = raw["draft_plan"]
    allowed = create_draft_sections if mode == "create" else update_draft_sections
    order = []
    for value in source.get("section_order") or []:
        section_id = str(value or "").strip()
        if section_id in allowed and section_id not in order:
            order.append(section_id)
    if not order:
        order = list(fallback["section_order"])
    for section_id in fallback["section_order"]:
        if section_id not in order:
            order.append(section_id)

    include_by_id: Dict[str, bool] = {}
    for item in source.get("sections") or []:
        if not isinstance(item, dict):
            continue
        section_id = str(item.get("id") or "").strip()
        if section_id not in allowed:
            continue
        include_by_id[section_id] = bool(item.get("include"))

    req_present = context_has_draft_section(context, "system_requirement")
    sections = []
    for section_id in order:
        has_data = context_has_draft_section(context, section_id)
        include = include_by_id.get(section_id, has_data)
        include = bool(include and has_data)
        if section_id == "user_requirements" and has_data:
            include = True
        if mode == "create" and section_id == "system_requirement":
            include = False
        if mode == "update" and req_present and section_id == "system_requirement":
            include = True
        sections.append({
            "id": section_id,
            "include": include,
        })

    return {
        "section_order": order,
        "sections": sections,
    }


def parse_draft_plan(raw: str, context: Dict[str, Any], *, mode: str) -> Dict[str, Any]:
    data = parse_json_object(raw)
    return normalize_draft_plan(data, context, mode=mode)




class AnalystDraft:
    def create_draft(
        self,
        artifact: Dict[str, Any],
        draft_version: Optional[int] = None,
        round_num: Optional[int] = None,
        artifact_dir: Optional[Any] = None,
    ) -> str:
        user_requirements = requirement_discussion_pool(artifact)
        for req in user_requirements:
            req_norm = self.requirement_record(req)
            req.update(req_norm)

        scope = artifact.get("scope", {}) or {}
        context = {
            "scope": scope,
            "user_requirements": user_requirements,
            "open_questions": consolidated_draft_open_questions(artifact),
            "feedback": draft_feedback(artifact),
            "system_models": draft_system_models(artifact, artifact_dir=artifact_dir),
            "version": draft_version if draft_version is not None else 0,
        }
        context["stakeholders"] = draft_stakeholders(artifact)
        context["rough_idea"] = str(artifact.get("rough_idea") or "").strip()
        context["scenario"] = str(artifact.get("scenario", "") or "").strip()
        version_note = ""
        if draft_version is not None:
            version_note = f" 本稿版本: draft_v{draft_version}。"
        if round_num is not None:
            version_note += f" 對應輪次: Round {round_num}。"
        task = create_draft(
            version_note=version_note,
            version=draft_version if draft_version is not None else 0,
        )
        try:
            raw = self.invoke_direct_requirements_text(
                task,
                context,
                action="requirements.draft",
            )
        except Exception as e:
            raise RuntimeError(f"draft 生成失敗: {e}") from e
        try:
            draft_plan = parse_draft_plan(raw, context, mode="create")
        except Exception as e:
            raise RuntimeError(f"draft plan 解析失敗: {e}") from e
        context["draft_plan"] = draft_plan
        md = render_complete_draft(
            context,
            require_system_requirement=False,
            draft_plan=draft_plan,
        )
        expected_ids = {
            str(req.get("id") or "").strip()
            for req in user_requirements
            if isinstance(req, dict) and str(req.get("id") or "").strip()
        }
        unknown_ids, missing_ids = draft_requirement_id_issues(md, expected_ids)
        if unknown_ids:
            self.logger.warning("draft 包含 User Requirements 以外的需求 ID: %s", unknown_ids)
        if missing_ids:
            self.logger.warning("draft 未保留部分 User Requirements ID: %s", missing_ids)
        if unknown_ids or missing_ids:
            raise RuntimeError(
                f"draft 不符合 User Requirements 覆蓋契約；unknown={unknown_ids}; missing={missing_ids}"
            )

        contract_issues = draft_contract_issues(
            md,
            context.get("REQ", []) or [],
            require_system_requirement=False,
        )
        if contract_issues:
            raise RuntimeError(f"draft 不符合草稿輸出契約: {contract_issues}")

        return normalize_model_image_markdown(md)

    def update_draft(
        self,
        artifact: Dict[str, Any],
        draft_version: Optional[int] = None,
        previous_draft: Optional[str] = None,
        round_num: Optional[int] = None,
        artifact_dir: Optional[Any] = None,
    ) -> str:
        user_requirements = requirement_discussion_pool(artifact)
        for req in user_requirements:
            req_norm = self.requirement_record(req)
            req.update(req_norm)

        context = {
            "scope": artifact.get("scope", {}) or {},
            "user_requirements": user_requirements,
            "open_questions": consolidated_draft_open_questions(artifact),
            "feedback": draft_feedback(artifact),
            "system_models": draft_system_models(artifact, artifact_dir=artifact_dir),
            "version": draft_version if draft_version is not None else 0,
            "meeting_context": draft_meeting_context(artifact),
            "REQ": artifact.get("REQ", []) or [],
            "previous_draft": (previous_draft or "").strip(),
        }
        version_note = ""
        if draft_version is not None:
            version_note = f" 本稿版本: draft_v{draft_version}。"
        if round_num is not None:
            version_note += f" 對應輪次: Round {round_num}。"
        task = update_draft(
            version_note=version_note,
            version=draft_version if draft_version is not None else 0,
        )
        try:
            raw = self.invoke_direct_requirements_text(
                task,
                context,
                action="requirements.draft",
            )
        except Exception as e:
            raise RuntimeError(f"draft 更新失敗: {e}") from e
        try:
            draft_plan = parse_draft_plan(raw, context, mode="update")
        except Exception as e:
            raise RuntimeError(f"draft plan 解析失敗: {e}") from e
        context["draft_plan"] = draft_plan
        md = render_complete_draft(
            context,
            require_system_requirement=bool(context.get("REQ")),
            draft_plan=draft_plan,
        )

        expected_ids = {
            str(req.get("id") or "").strip()
            for req in user_requirements
            if isinstance(req, dict) and str(req.get("id") or "").strip()
        }
        unknown_ids, missing_ids = draft_requirement_id_issues(md, expected_ids)
        if unknown_ids:
            self.logger.warning("draft 包含 User Requirements 以外的需求 ID: %s", unknown_ids)
        if missing_ids:
            self.logger.warning("draft 未保留部分 User Requirements ID: %s", missing_ids)
        if unknown_ids or missing_ids:
            raise RuntimeError(
                f"draft 不符合 User Requirements 覆蓋契約；unknown={unknown_ids}; missing={missing_ids}"
            )

        contract_issues = draft_contract_issues(
            md,
            context.get("REQ", []) or [],
            require_system_requirement=True,
        )
        if contract_issues:
            raise RuntimeError(f"draft 不符合草稿輸出契約: {contract_issues}")

        return normalize_model_image_markdown(md)
