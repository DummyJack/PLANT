# Analyst requirements logic: scope, drafts, requirements, and change candidates.
from agents.profile.prompt_catalog import render_prompt
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.base import parse_json_array, parse_json_object
from storage.markdown import clean_llm_output
from storage.plantuml import plantuml_safe_name
from agents.skills.base import get_skill
from agents.profile.scenario import scenario_prompt_value, scenario_text

from .conflict_store import all_conflict_rows, conflict_entries_count
from .validation import (
    requirement_record as analyst_requirement_record,
    requirement_records,
    requirement_text as analyst_requirement_text,
    scope_payload,
)
from .requirements import requirement_discussion_pool
from .prompts import (
    build_draft_prompt,
    requirements_skill_guidance,
    url_extraction_rules,
)


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
            for question in list(resolution.get("open_questions") or []) + list(resolution.get("new_open_questions") or []):
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
        ("URL", "url_count"),
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
    req_rows = [row for row in (artifact.get("REQ") or []) if isinstance(row, dict)]
    formalized_sources = set()
    formalized_text = ""
    for req in req_rows:
        raw_values = req.get("source") or []
        values = raw_values if isinstance(raw_values, list) else [raw_values]
        for value in values:
            value_text = str(value).strip()
            if value_text:
                formalized_sources.add(value_text)
        text_parts = []
        for key in ("title", "description", "rationale", "constraint_type", "impact"):
            value = str(req.get(key) or "").strip()
            if value:
                text_parts.append(value)
        for key in ("risks", "assumptions", "acceptance_criteria"):
            for value in req.get(key) or []:
                value_text = str(value).strip()
                if value_text:
                    text_parts.append(value_text)
        formalized_text += "\n" + "\n".join(text_parts)

    def is_formalized_feedback(item: Dict[str, Any], text: str) -> bool:
        item_id = str(item.get("id") or "").strip()
        source = str(item.get("source") or "").strip()
        related = {
            str(value).strip()
            for value in (item.get("related_requirement_ids") or [])
            if str(value).strip()
        }
        if item_id and item_id in formalized_sources:
            return True
        if source and source in formalized_sources:
            return True
        if related and related.issubset(formalized_sources):
            return True
        compact_text = re.sub(r"\s+", "", text)
        compact_formalized = re.sub(r"\s+", "", formalized_text)
        return bool(compact_text and compact_text in compact_formalized)

    out: Dict[str, Any] = {}
    for section in ("findings", "constraints", "risks", "recommendations"):
        rows: List[Dict[str, Any]] = []
        for item in feedback.get(section) or []:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            if is_formalized_feedback(item, text):
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
    sources = [
        str(source).strip()
        for source in (feedback.get("sources") or [])
        if str(source).strip()
    ]
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
        "context_diagram": "系統架構圖",
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
    require_traceability: bool = False,
) -> List[str]:
    issues: List[str] = []
    source = md or ""
    forbidden_patterns = {
        "contains_placeholder": r"待補",
        "contains_ellipsis_summary": (
            r"其餘(?:需求|項目|內容|條目|REQ|URL|部分)?(?:同上|略|依輸入資料內容)"
            r"|格式同上"
            r"|依輸入資料內容"
            r"|省略(?:如下|如下列|同上|不列|未列)"
            r"|^\s*略\s*$"
        ),
        "contains_json_fence": r"```json",
    }
    for name, pattern in forbidden_patterns.items():
        if re.search(pattern, source, flags=re.IGNORECASE):
            issues.append(name)

    traceability_match = re.search(
        r"(?ms)^##\s+Traceability\s*\n(?P<body>.*?)(?=^##\s+|\Z)",
        source,
    )
    has_requirements_section = bool(re.search(r"(?m)^##\s+Requirements\s*$", source))
    has_system_requirement_section = bool(re.search(r"(?m)^##\s+System Requirement\s*$", source))
    if has_requirements_section:
        issues.append("unexpected_requirements")
    if not require_traceability and has_system_requirement_section:
        issues.append("unexpected_system_requirement")

    req_ids = [
        str(row.get("id") or "").strip()
        for row in (req_rows or [])
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    ]
    if req_ids and require_traceability:
        if not has_system_requirement_section:
            issues.append("missing_system_requirement")
        detail_heading_ids = set(re.findall(r"(?m)^###\s+(REQ-\d+)\b", source))
        missing_detail_ids = [req_id for req_id in req_ids if req_id not in detail_heading_ids]
        if missing_detail_ids:
            issues.append("missing_system_requirement_rows:" + ",".join(missing_detail_ids))
        if require_traceability:
            if not traceability_match:
                issues.append("missing_traceability")
            else:
                traceability_body = traceability_match.group("body")
                if "| REQ ID | Requirement | Source | System Model |" not in traceability_body:
                    issues.append("invalid_traceability_header")
                after_traceability = source[traceability_match.end():]
                if re.search(r"(?m)^##\s+", after_traceability):
                    issues.append("traceability_not_last")
                missing_trace_ids = [
                    req_id
                    for req_id in req_ids
                    if not re.search(rf"(?m)^\|\s*{re.escape(req_id)}\s*\|", traceability_body)
                ]
                if missing_trace_ids:
                    issues.append("missing_traceability_rows:" + ",".join(missing_trace_ids))
    elif traceability_match:
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
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def system_model_refs_by_req(req_rows: List[Dict[str, Any]], system_models: Any) -> Dict[str, List[str]]:
    refs: Dict[str, List[str]] = {}
    source_to_req: Dict[str, List[str]] = {}
    for row in req_rows or []:
        if not isinstance(row, dict):
            continue
        req_id = str(row.get("id") or "").strip()
        if not req_id:
            continue
        raw_sources = row.get("source") or []
        sources = raw_sources if isinstance(raw_sources, list) else [raw_sources]
        for source in sources:
            source_id = str(source or "").strip()
            if source_id:
                source_to_req.setdefault(source_id, []).append(req_id)
    if not isinstance(system_models, list):
        return refs
    for model in system_models:
        if not isinstance(model, dict):
            continue
        model_id = str(model.get("id") or "").strip()
        if not model_id:
            continue
        for req_id in model.get("related_requirement_ids") or []:
            rid = str(req_id or "").strip()
            if not rid:
                continue
            if rid.startswith("REQ-"):
                refs.setdefault(rid, []).append(model_id)
                continue
            for mapped_req_id in source_to_req.get(rid, []):
                refs.setdefault(mapped_req_id, []).append(model_id)
    return {
        req_id: list(dict.fromkeys(model_ids))
        for req_id, model_ids in refs.items()
    }


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


def render_traceability_section(req_rows: List[Dict[str, Any]], system_models: Any) -> str:
    refs = system_model_refs_by_req(req_rows, system_models)
    lines = [
        "## Traceability",
        "| REQ ID | Requirement | Source | System Model |",
        "|---|---|---|---|",
    ]
    for row in req_rows or []:
        if not isinstance(row, dict):
            continue
        req_id = str(row.get("id") or "").strip()
        if not req_id:
            continue
        requirement = str(row.get("description") or "").strip()
        source = req_source_text(row.get("source"))
        model_ref = ", ".join(refs.get(req_id, []))
        lines.append(f"| {req_id} | {requirement} | {source} | {model_ref} |")
    return "\n".join(lines).rstrip() + "\n"


def replace_or_insert_section(md: str, heading: str, section: str, *, before: List[str]) -> str:
    source = (md or "").strip()
    pattern = rf"(?ms)^##\s+{re.escape(heading)}\s*\n.*?(?=^##\s+|\Z)"
    if re.search(pattern, source):
        return re.sub(pattern, section.rstrip() + "\n\n", source).strip() + "\n"
    insert_at = len(source)
    for name in before:
        match = re.search(rf"(?m)^##\s+{re.escape(name)}\s*$", source)
        if match:
            insert_at = min(insert_at, match.start())
    if insert_at < len(source):
        return (source[:insert_at].rstrip() + "\n\n" + section.rstrip() + "\n\n" + source[insert_at:].lstrip()).strip() + "\n"
    return (source.rstrip() + "\n\n" + section.rstrip()).strip() + "\n"


def ensure_update_draft_requirement_sections(md: str, context: Dict[str, Any]) -> str:
    req_rows = [row for row in (context.get("REQ") or []) if isinstance(row, dict)]
    if not req_rows:
        return md
    system_section = render_system_requirement_section(req_rows)
    trace_section = render_traceability_section(req_rows, context.get("system_models"))
    out = replace_or_insert_section(
        md,
        "System Requirement",
        system_section,
        before=["Feedback", "Open Questions", "System Models", "Traceability"],
    )
    out = replace_or_insert_section(out, "Traceability", trace_section, before=[])
    return out


class AnalystRequirements:
    def run_requirements_analyst(
        self,
        action: str,
        *,
        rough_idea: str = "",
        stakeholders: Optional[List[Dict]] = None,
        artifact: Optional[Dict[str, Any]] = None,
        draft_version: Optional[int] = None,
        previous_draft: Optional[str] = None,
        round_num: Optional[int] = None,
        artifact_dir: Optional[Any] = None,
    ):
        """requirements-analyst skill 統一入口。

        action:
            "analyze_scenario"        -> 回傳 str (scenario)
            "define_scope"          -> 回傳 Dict (scope)
            "analyze_requirements"    -> 回傳 Dict (requirements list)
            "create_draft"          -> 回傳 str  (Markdown)
            "default_update_draft"  -> 回傳 str  (Markdown)
            "general_update_draft"  -> 回傳 str  (Markdown)
        """
        allowed_actions = {
            "analyze_scenario",
            "define_scope",
            "analyze_requirements",
            "create_draft",
            "default_update_draft",
            "general_update_draft",
        }
        if action not in allowed_actions:
            raise ValueError(f"未知 requirements action: {action}")
        opa = self.run_action_loop(
            name="requirements_analysis",
            context={
                "requirements_action": action,
                "rough_idea": rough_idea,
                "stakeholders": stakeholders or [],
                "artifact": artifact or {},
                "version": draft_version,
                "previous_draft": previous_draft,
                "round_num": round_num,
                "artifact_dir": artifact_dir,
            },
            build_observation=self.build_requirements_analysis_observation,
            decide_action=self.decide_requirements_analysis_action,
            execute_action=self.execute_requirements_analysis_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("error"))
        return result.get("output")

    def build_requirements_analysis_observation(self, **kwargs: Any) -> Dict[str, Any]:
        artifact = kwargs.get("artifact") or {}
        stakeholders = kwargs.get("stakeholders") or []
        return {
            "action": kwargs.get("requirements_action", ""),
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs["max_iterations"],
            "stakeholder_count": len(stakeholders),
            "requirements_count": len(requirement_discussion_pool(artifact)),
            "conflicts_count": conflict_entries_count(artifact),
            "has_scope": bool(artifact.get("scope")),
        }

    def decide_requirements_analysis_action(
        self,
        *,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if isinstance(last_result, dict) and not last_result.get("error"):
            return {
                "action": "done",
                "params": {},
                "reasoning": "上一輪需求分析任務已完成，結束本次 requirements analysis。",
            }
        action = str(observation.get("action") or "").strip()
        return {
            "action": action,
            "params": {},
            "reasoning": f"執行 Analyst requirements analysis 任務：{action}。",
        }

    def execute_requirements_analysis_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        action = str(decision.get("action") or "").strip()
        try:
            if action == "analyze_scenario":
                output = self.analyze_scenario(kwargs.get("rough_idea", ""))
            elif action == "define_scope":
                output = self.define_scope(
                    kwargs.get("rough_idea", ""),
                    kwargs.get("stakeholders") or [],
                    artifact=kwargs.get("artifact") or {},
                )
            elif action == "analyze_requirements":
                output = self.analyze_requirements(kwargs.get("stakeholders") or [])
            elif action in {"create_draft", "default_update_draft", "general_update_draft"}:
                output = self.create_draft(
                    kwargs.get("artifact") or {},
                    draft_version=kwargs.get("version"),
                    previous_draft=kwargs.get("previous_draft"),
                    round_num=kwargs.get("round_num"),
                    artifact_dir=kwargs.get("artifact_dir"),
                    mode="create" if action == "create_draft" else "update",
                )
            else:
                raise ValueError(f"未知 requirements action: {action}")
        except Exception as e:
            return {
                "action": action,
                "status": "failed",
                "error": str(e),
                "summary": f"requirements analysis failed: {action}",
            }
        return {
            "action": action,
            "status": "success",
            "output": output,
            "summary": f"完成 requirements analysis: {action}",
        }

    @staticmethod
    def requirement_text(text: str) -> str:
        return analyst_requirement_text(text)

    @staticmethod
    def requirement_record(
        req: Dict[str, Any],
    ) -> Dict[str, Any]:
        return analyst_requirement_record(req)

    def analyze_scenario(self, rough_idea: str) -> str:
        context = {"rough_idea": rough_idea}
        task = render_prompt('agents_profile_analyst_analyze_task_11', **locals())
        try:
            data = self.invoke_direct_requirements_object_json(
                task,
                context,
                action="requirements.scenario",
            )
        except Exception as e:
            raise RuntimeError(f"scenario 分析失敗: {e}") from e
        scenario = data.get("scenario") if isinstance(data, dict) and "scenario" in data else data
        name = scenario_text(scenario)
        if not name:
            raise ValueError("scenario 分析未產生有效 name")
        return name

    def define_scope(
        self, rough_idea: str, stakeholders: List[Dict],
        *, artifact: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        context: Dict[str, Any] = {}
        if artifact:
            if artifact.get("scenario"):
                context["scenario"] = scenario_prompt_value(artifact["scenario"])
            elif rough_idea:
                context["scenario"] = scenario_prompt_value(rough_idea)
            if artifact.get("scope"):
                context["current_scope"] = artifact["scope"]
            req_pool = requirement_discussion_pool(artifact)
            if req_pool:
                context["URL"] = req_pool
        task = render_prompt('agents_profile_analyst_analyze_task_12', **locals())
        try:
            data = self.invoke_direct_requirements_object_json(
                task,
                context,
                action="requirements.scope",
            )
        except Exception as e:
            raise RuntimeError(f"scope 生成失敗: {e}") from e
        scope = data.get("scope") or {}
        return scope_payload(scope)

    def analyze_requirements(self, stakeholders: List[Dict]) -> Dict[str, Any]:
        all_requirements = []
        for idx, one_sh in enumerate(stakeholders):
            sh_label = str(one_sh.get("name") or "").strip()
            if not sh_label:
                raise ValueError(f"stakeholder 缺少 name，無法進行需求分析: index={idx}")
            sh_texts = one_sh.get("text") or []
            if isinstance(sh_texts, list):
                source_texts = [str(text).strip() for text in sh_texts if str(text).strip()]
            else:
                source_text = str(sh_texts or "").strip()
                source_texts = [source_text] if source_text else []
            for source_idx, source_text in enumerate(source_texts, 1):
                existing_requirements_json = json.dumps(
                    [
                        {
                            "id": str(row.get("id") or "").strip(),
                            "text": str(row.get("text") or "").strip(),
                            "stakeholder": (
                                str((row.get("stakeholder") or {}).get("name") or "").strip()
                                if isinstance(row.get("stakeholder"), dict)
                                else str(row.get("stakeholder") or "").strip()
                            ),
                            "source": str(row.get("source") or "").strip(),
                        }
                        for row in all_requirements
                        if isinstance(row, dict) and str(row.get("text") or "").strip()
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
                context = {
                    "stakeholder": {
                        "name": sh_label,
                        "type": one_sh.get("type"),
                        "source_text": source_text,
                        "all_text": source_texts,
                    },
                    "existing_requirements": existing_requirements_json,
                }
                extraction_rules = url_extraction_rules()
                task = render_prompt('agents_profile_analyst_analyze_task_13', **locals())
                try:
                    data = self.invoke_requirements_analyst_array_json(task, context, mode="analysis")
                except Exception as e:
                    try:
                        raw = self.invoke_requirements_analyst_text(task, context, mode="analysis")
                        repair_task = render_prompt('agents_profile_analyst_analyze_repair_task_27', **locals())
                        data = self.invoke_direct_requirements_array_json(
                            repair_task,
                            context={},
                            action="requirements.analysis.repair",
                        )
                    except Exception:
                        raise RuntimeError(f"需求分析失敗（{sh_label}#{source_idx}）: {e}") from e
                raw_rows = data if isinstance(data, list) else []
                normalized_rows = [
                    row for row in requirement_records([
                        {
                            **row,
                            "stakeholder": {
                                "name": sh_label,
                                "type": one_sh.get("type"),
                            },
                            "source": "initial",
                        }
                        for row in raw_rows
                        if isinstance(row, dict)
                    ])
                    if row.get("stakeholder") and row.get("source")
                ]
                existing_texts = {
                    str(row.get("text") or "").strip().lower()
                    for row in all_requirements
                    if isinstance(row, dict) and str(row.get("text") or "").strip()
                }
                for row in normalized_rows:
                    text = str(row.get("text") or "").strip()
                    if not text or text.lower() in existing_texts:
                        continue
                    all_requirements.append(row)
                    existing_texts.add(text.lower())

        return {"URL": all_requirements}

    def create_draft(
        self,
        artifact: Dict[str, Any],
        draft_version: Optional[int] = None,
        previous_draft: Optional[str] = None,
        round_num: Optional[int] = None,
        artifact_dir: Optional[Any] = None,
        mode: str = "create",
    ) -> str:
        mode = "update" if str(mode or "").strip() == "update" else "create"
        user_requirements = requirement_discussion_pool(artifact)
        for req in user_requirements:
            req_norm = self.requirement_record(req)
            req.update(req_norm)

        scope = artifact.get("scope", {}) or {}
        context = {
            "scope": scope,
            "URL": user_requirements,
            "open_questions": consolidated_draft_open_questions(artifact),
            "feedback": draft_feedback(artifact),
            "system_models": draft_system_models(artifact, artifact_dir=artifact_dir),
            "version": draft_version if draft_version is not None else 0,
        }
        if mode == "create":
            context["stakeholders"] = draft_stakeholders(artifact)
            context["rough_idea"] = str(artifact.get("rough_idea") or "").strip()
            context["scenario"] = scenario_prompt_value(artifact.get("scenario", ""))
        previous_draft_text = (previous_draft or "").strip()
        if mode == "update":
            context["meeting_context"] = draft_meeting_context(artifact)
            context["REQ"] = artifact.get("REQ", []) or []
            context["previous_draft"] = previous_draft_text
        version_note = ""
        if draft_version is not None:
            version_note = f" 本稿版本: draft_v{draft_version}。"
        if round_num is not None:
            version_note += f" 對應輪次: Round {round_num}。"
        task = build_draft_prompt(
            mode=mode,
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
        md = clean_llm_output(raw)
        if mode == "update":
            md = ensure_update_draft_requirement_sections(md, context)
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
            repair_task = render_prompt('agents_profile_analyst_analyze_repair_task_28', **locals())
            try:
                repaired = self.invoke_direct_requirements_text(
                    repair_task,
                    context,
                    action="requirements.draft.repair",
                )
                md = clean_llm_output(repaired)
                if mode == "update":
                    md = ensure_update_draft_requirement_sections(md, context)
                unknown_ids, missing_ids = draft_requirement_id_issues(md, expected_ids)
            except Exception as e:
                raise RuntimeError(f"draft 修復失敗: {e}") from e
            if unknown_ids or missing_ids:
                raise RuntimeError(
                    f"draft 修復後仍不符合 URL 覆蓋契約；unknown={unknown_ids}; missing={missing_ids}"
                )

        require_traceability = mode == "update"
        contract_issues = draft_contract_issues(
            md,
            context.get("REQ", []) or [],
            require_traceability=require_traceability,
        )
        if contract_issues:
            traceability_repair_rule = (
                "- Traceability 必須逐筆列出輸入中的所有 REQ-*，欄位為 REQ ID、Requirement、Source、System Model。\n"
                "- Traceability 必須放在文件最後。\n"
                "- System Requirement 不得使用「其餘同上」、「略」、「依輸入資料內容」等省略寫法。\n"
                if require_traceability
                else "- create_draft 不輸出 Requirements、System Requirement 或 Traceability。\n"
            )
            repair_task = (
                "請修復以下 draft Markdown，使其符合草稿輸出契約。\n\n"
                f"問題：{json.dumps(contract_issues, ensure_ascii=False)}\n\n"
                "修復規則：\n"
                "- 保留所有 User Requirements，不得新增、刪除、合併、拆分或重新排序 URL-*。\n"
                + (
                    "- System Requirement 必須逐筆完整列出輸入中的所有 REQ-*。\n"
                    if require_traceability
                    else ""
                )
                + f"{traceability_repair_rule}"
                "- 欄位沒有資料就省略該欄位，不要輸出空欄位，也不要寫待補。\n"
                "- 不得輸出 JSON fenced code block。\n"
                "- 只輸出修復後 Markdown。\n\n"
                "# 原 draft\n"
                f"{md}"
            )
            try:
                repaired = self.invoke_direct_requirements_text(
                    repair_task,
                    context,
                    action="requirements.draft.contract_repair",
                )
                md = clean_llm_output(repaired)
                if mode == "update":
                    md = ensure_update_draft_requirement_sections(md, context)
                contract_issues = draft_contract_issues(
                    md,
                    context.get("REQ", []) or [],
                    require_traceability=require_traceability,
                )
            except Exception as e:
                raise RuntimeError(f"draft 契約修復失敗: {e}") from e
            if contract_issues:
                raise RuntimeError(
                    f"draft 修復後仍不符合草稿輸出契約: {contract_issues}"
                )

        return md

    def invoke_requirements_analyst_text(
        self,
        task: str,
        context: Dict[str, Any],
        *,
        mode: str = "analysis",
        use_tools: bool = False,
    ) -> str:
        self.validate_skill_usage("requirements-analyst")
        skill = get_skill("requirements-analyst")
        skill_content = str(skill.get("content") or "")
        selected_guidance = requirements_skill_guidance(skill_content, mode)
        prompt = (
            "# Skill: requirements-analyst\n\n"
            f"{selected_guidance}\n\n"
            "# 任務\n\n"
            f"{task}"
        )
        messages = self.build_direct_messages(prompt, context=context)
        if self.tools and use_tools:
            return self.chat_with_tools(messages, active_skill="requirements-analyst")
        return self.model.chat(messages, action=self.usage_action("skill.requirements-analyst"))

    def invoke_requirements_analyst_object_json(
        self, task: str, context: Dict[str, Any], *, mode: str = "analysis"
    ) -> Dict[str, Any]:
        # 以傳入 context 取代逐筆 artifact_query，降低 tool-call 運行成本與抖動。
        use_tools = False
        raw = self.invoke_requirements_analyst_text(
            task,
            context,
            mode=mode,
            use_tools=use_tools,
        )
        return parse_json_object(raw)

    def invoke_requirements_analyst_array_json(
        self, task: str, context: Dict[str, Any], *, mode: str = "analysis"
    ) -> List[Any]:
        raw = self.invoke_requirements_analyst_text(task, context, mode=mode)
        return parse_json_array(raw)

    def invoke_direct_requirements_text(
        self, task: str, context: Dict[str, Any], *, action: str
    ) -> str:
        messages = self.build_direct_messages(task, context=context)
        return self.model.chat(messages, action=self.usage_action(action))

    def invoke_direct_requirements_object_json(
        self, task: str, context: Dict[str, Any], *, action: str
    ) -> Dict[str, Any]:
        raw = self.invoke_direct_requirements_text(task, context, action=action)
        return parse_json_object(raw)

    def invoke_direct_requirements_array_json(
        self, task: str, context: Dict[str, Any], *, action: str
    ) -> List[Any]:
        raw = self.invoke_direct_requirements_text(task, context, action=action)
        return parse_json_array(raw)
