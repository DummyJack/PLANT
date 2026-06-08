# Handles Design Rationale generation for documentor workflow.
import html
import json
import re
from pathlib import Path
from typing import Any, Dict, List

from agents.profile.documentor.dr import design_rationale


class DocumentorDr:
    @staticmethod
    def clean_repeated_text(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        text = re.sub(r"\s+", " ", text)
        for sep in ("，", "；", ";", "。"):
            parts = [part.strip() for part in text.split(sep) if part.strip()]
            if len(parts) < 2:
                continue
            cleaned: List[str] = []
            for part in parts:
                if part not in cleaned:
                    cleaned.append(part)
            if len(cleaned) != len(parts):
                text = sep.join(cleaned)
                if value and str(value).strip().endswith(sep):
                    text += sep
        half = len(text) // 2
        if half > 12 and len(text) % 2 == 0 and text[:half].strip("，；;。 ") == text[half:].strip("，；;。 "):
            text = text[:half].strip("，；;。 ")
        return text.strip()

    @classmethod
    def dr_summary(cls, value: Any, max_chars: int = 220) -> str:
        text = cls.clean_repeated_text(value)
        if not text:
            return ""
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) <= max_chars:
            return text
        cut = text[:max_chars].rstrip()
        boundary = max(cut.rfind("。"), cut.rfind("；"), cut.rfind("，"))
        if boundary >= max_chars // 2:
            cut = cut[: boundary + 1]
        return cut.rstrip("，；、 ") + "..."

    @staticmethod
    def dr_cell(value: Any) -> str:
        return str(value or "").strip().replace("|", "\\|").replace("\n", "<br>")

    @staticmethod
    def dr_link(label: str) -> str:
        text = str(label or "").strip()
        return f'<span id="{text.lower()}"></span>{text}' if text else ""

    @staticmethod
    def dr_stakeholder_name(value: Any) -> str:
        if isinstance(value, dict):
            return str(value.get("name") or value.get("role") or "").strip()
        return str(value or "").strip()

    @staticmethod
    def dr_req_sources(row: Dict[str, Any]) -> List[str]:
        raw = row.get("source") if isinstance(row, dict) else []
        values = raw if isinstance(raw, list) else [raw]
        return [str(value).strip() for value in values if str(value).strip()]

    @staticmethod
    def dr_srs_id_map(req_rows: List[Dict[str, Any]]) -> Dict[str, str]:
        counters = {"functional": 0, "non-functional": 0, "constraint": 0}
        prefixes = {
            "functional": "FR",
            "non-functional": "NFR",
            "constraint": "CON",
        }
        out: Dict[str, str] = {}
        for row in req_rows:
            req_id = str(row.get("id") or "").strip()
            req_type = str(row.get("type") or "").strip().lower()
            if not req_id or req_type not in counters:
                continue
            counters[req_type] += 1
            out[req_id] = f"{prefixes[req_type]}-{counters[req_type]}"
        return out

    @staticmethod
    def dr_srs_order_key(row: Dict[str, Any]) -> tuple[int, int, str]:
        srs_id = str(row.get("srs_id") or "").strip()
        match = re.fullmatch(r"(FR|NFR|CON)-(\d+)", srs_id)
        if not match:
            return (99, 999999, srs_id)
        group_order = {"FR": 0, "NFR": 1, "CON": 2}
        return (group_order.get(match.group(1), 99), int(match.group(2)), srs_id)

    @staticmethod
    def dr_related_req_ids_from_sources(
        source_ids: List[str],
        source_to_req: Dict[str, List[str]],
    ) -> List[str]:
        out: List[str] = []
        for source_id in source_ids:
            sid = str(source_id or "").strip()
            if not sid:
                continue
            if sid.startswith("REQ-"):
                out.append(sid)
            out.extend(source_to_req.get(sid, []))
        return list(dict.fromkeys(item for item in out if item))

    @staticmethod
    def dr_source_link(value: Any) -> str:
        if isinstance(value, dict):
            title = DocumentorDr.clean_repeated_text(value.get("title"))
            url = str(value.get("url") or "").strip()
            if title and url:
                return f"[{title}]({url})"
            if url:
                return DocumentorDr.dr_source_link(url)
            return title
        text = str(value or "").strip()
        if not text:
            return ""
        if re.match(r"https?://", text):
            label = re.sub(r"^https?://", "", text).split("/")[0]
            return f"[{label}]({text})"
        return text

    def versioned_conflict_report_rows(self) -> List[Dict[str, Any]]:
        artifact_dir = getattr(getattr(self, "store", None), "artifact_dir", None)
        if not artifact_dir:
            return []
        report_dir = Path(artifact_dir) / "report"
        versioned_paths: List[tuple[int, Path]] = []
        for path in report_dir.glob("conflict_report_v*.json"):
            raw_version = path.stem.removeprefix("conflict_report_v")
            if raw_version.isdigit():
                versioned_paths.append((int(raw_version), path))
        if not versioned_paths:
            return []
        out: List[Dict[str, Any]] = []
        seen_signatures: set[str] = set()
        for version, path in sorted(versioned_paths, key=lambda item: item[0]):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, list):
                continue
            for row in payload:
                if not isinstance(row, dict):
                    continue
                requirement_ids = [
                    str(req.get("id") or "").strip()
                    for req in (row.get("requirements") or [])
                    if isinstance(req, dict) and str(req.get("id") or "").strip()
                ]
                signature = "|".join(sorted(requirement_ids)) or f"v{version}:{row.get('id')}"
                if signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
                item = dict(row)
                item["report_version"] = f"v{version}"
                item["report_id"] = str(row.get("id") or "").strip()
                item["id"] = f"CR-{len(out) + 1}"
                out.append(item)
        return out

    @classmethod
    def build_dr_appendix(cls, artifact: Dict[str, Any]) -> Dict[str, Any]:
        req_rows = [row for row in (artifact.get("REQ") or []) if isinstance(row, dict)]
        url_rows = [row for row in (artifact.get("URL") or []) if isinstance(row, dict)]
        valid_req_ids = {
            str(row.get("id") or "").strip()
            for row in req_rows
            if str(row.get("id") or "").strip().startswith("REQ-")
        }
        url_by_id = {
            str(row.get("id") or "").strip(): row
            for row in url_rows
            if str(row.get("id") or "").strip()
        }
        known_stakeholders = {
            cls.dr_stakeholder_name(row.get("stakeholder"))
            for row in url_rows
            if cls.dr_stakeholder_name(row.get("stakeholder"))
        }
        known_stakeholders.update(
            cls.dr_stakeholder_name(row)
            for row in (artifact.get("stakeholders") or [])
            if isinstance(row, dict) and cls.dr_stakeholder_name(row)
        )
        process_roles = {"analyst", "expert", "mediator", "modeler", "system", "user"}
        source_to_req: Dict[str, List[str]] = {}
        for req in req_rows:
            req_id = str(req.get("id") or "").strip()
            for source_id in cls.dr_req_sources(req):
                source_to_req.setdefault(source_id, []).append(req_id)

        statements: List[Dict[str, Any]] = []

        def add_statement(
            stakeholder: str,
            source: str,
            text: str,
            related_req: List[str],
        ) -> None:
            clean_text = cls.clean_repeated_text(text)
            if not stakeholder or not clean_text:
                return
            row_id = f"ST-{len(statements) + 1}"
            row = {
                "id": row_id,
                "stakeholder": stakeholder,
                "source": source,
                "related_req": list(dict.fromkeys(related_req)),
                "text": clean_text,
            }
            statements.append(row)

        for stakeholder in artifact.get("stakeholders") or []:
            if not isinstance(stakeholder, dict):
                continue
            name = cls.dr_stakeholder_name(stakeholder)
            raw_text = stakeholder.get("text")
            if isinstance(raw_text, list):
                text = "\n".join(str(item).strip() for item in raw_text if str(item).strip())
            else:
                text = str(
                    raw_text or stakeholder.get("description") or stakeholder.get("goal") or ""
                ).strip()
            if not name or not text:
                continue
            related = [
                req_id
                for req_id, req in ((str(req.get("id") or "").strip(), req) for req in req_rows)
                if name
                in " ".join(
                    cls.dr_stakeholder_name(url_by_id.get(source_id, {}).get("stakeholder"))
                    for source_id in cls.dr_req_sources(req)
                )
            ]
            add_statement(name, "initial", text, related)

        elicitation = artifact.get("elicitation") if isinstance(artifact.get("elicitation"), dict) else {}
        meeting = elicitation.get("meeting") if isinstance(elicitation.get("meeting"), dict) else {}
        for round_key, rows in meeting.items():
            if not isinstance(rows, list):
                continue
            source = f"elicitation_{round_key}"
            for row in rows:
                if not isinstance(row, dict):
                    continue
                for key, value in row.items():
                    if key in {"id", "analyst", "expert", "modeler", "user"}:
                        continue
                    speaker = str(key).strip()
                    if not speaker or speaker.lower() in process_roles:
                        continue
                    if known_stakeholders and speaker not in known_stakeholders:
                        continue
                    text = str(value or "").strip()
                    if not text:
                        continue
                    related = [
                        req_id
                        for req_id, req in ((str(req.get("id") or "").strip(), req) for req in req_rows)
                        if speaker
                        in " ".join(
                            cls.dr_stakeholder_name(url_by_id.get(source_id, {}).get("stakeholder"))
                            for source_id in cls.dr_req_sources(req)
                        )
                    ]
                    add_statement(speaker, source, text, related)

        user_requirement_rows: List[Dict[str, Any]] = []
        for url in url_rows:
            url_id = str(url.get("id") or "").strip()
            related_req = source_to_req.get(url_id, [])
            if not url_id:
                continue
            source_value = url.get("source")
            if isinstance(source_value, list):
                source_text = ", ".join(
                    str(item).strip() for item in source_value if str(item).strip()
                )
            else:
                source_text = str(source_value or "").strip()
            user_requirement_rows.append({
                "id": url_id,
                "stakeholder": cls.dr_stakeholder_name(url.get("stakeholder")),
                "source": source_text,
                "related_req": related_req,
                "text": str(url.get("text") or "").strip(),
            })

        conflict_rows = []
        conflict = artifact.get("conflict") if isinstance(artifact.get("conflict"), dict) else {}
        for row in conflict.get("report") or []:
            if not isinstance(row, dict):
                continue
            conflict_id = str(row.get("id") or "").strip()
            source_ids = []
            for req in row.get("requirements") or []:
                if isinstance(req, dict) and str(req.get("id") or "").strip():
                    source_ids.append(str(req.get("id")).strip())
            related_req = cls.dr_related_req_ids_from_sources(source_ids, source_to_req)
            if not conflict_id:
                continue
            conflict_rows.append({
                "id": conflict_id,
                "report_version": str(row.get("report_version") or "").strip(),
                "report_id": str(row.get("report_id") or "").strip(),
                "related_req": related_req,
                "related_user_requirements": source_ids,
                "description": cls.clean_repeated_text(
                    row.get("description") or row.get("reason") or row.get("summary")
                ),
                "resolution": cls.clean_repeated_text(
                    row.get("decision") or row.get("recommended_resolution") or row.get("resolution")
                ),
            })

        feedback_rows = []
        feedback = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
        for section in ("findings", "constraints", "risks", "recommendations"):
            for item in feedback.get(section) or []:
                if not isinstance(item, dict):
                    continue
                related_ids = [
                    str(req_id).strip()
                    for req_id in (item.get("related_requirement_ids") or [])
                    if str(req_id).strip()
                ]
                related_req = [
                    req_id
                    for req_id in cls.dr_related_req_ids_from_sources(related_ids, source_to_req)
                    if req_id in valid_req_ids
                ]
                feedback_rows.append({
                    "id": f"FB-{len(feedback_rows) + 1}",
                    "type": section[:-1] if section.endswith("s") else section,
                    "related_req": list(dict.fromkeys(related_req)),
                    "related_sources": related_ids,
                    "source": str(item.get("source") or "").strip(),
                    "content": cls.clean_repeated_text(item.get("text")),
                })
        feedback_sources: List[Any] = []
        seen_feedback_sources: set[str] = set()
        for source in feedback.get("sources") or []:
            if isinstance(source, dict):
                title = cls.clean_repeated_text(source.get("title"))
                url = str(source.get("url") or "").strip()
                key = url or title
                if key and key not in seen_feedback_sources:
                    feedback_sources.append({"title": title, "url": url})
                    seen_feedback_sources.add(key)
                continue
            text = str(source or "").strip()
            if text and text not in seen_feedback_sources:
                feedback_sources.append(text)
                seen_feedback_sources.add(text)

        model_rows = []
        for model in artifact.get("system_models") or []:
            if not isinstance(model, dict):
                continue
            model_id = str(model.get("id") or "").strip()
            related_req = [
                str(req_id).strip()
                for req_id in (model.get("related_requirement_ids") or [])
                if str(req_id).strip().startswith("REQ-")
            ]
            if not model_id or not related_req:
                continue
            model_rows.append({
                "id": model_id,
                "name": str(model.get("name") or "").strip(),
                "type": str(model.get("type") or "").strip(),
                "related_req": list(dict.fromkeys(related_req)),
                "description": cls.clean_repeated_text(model.get("description")),
                "image_path": str(model.get("image_path") or "").strip(),
                "plantuml": str(model.get("plantuml") or "").strip(),
            })

        meeting_rows = []
        for discussion in artifact.get("discussions") or []:
            if not isinstance(discussion, dict):
                continue
            for issue in discussion.get("issues") or []:
                if not isinstance(issue, dict):
                    continue
                meeting_id = str(issue.get("meeting_id") or "").strip()
                resolution = issue.get("resolution") if isinstance(issue.get("resolution"), dict) else {}
                related_req = [
                    str(req_id).strip()
                    for req_id in (resolution.get("affected_requirement_ids") or [])
                    if str(req_id).strip() in valid_req_ids
                ]
                if not related_req:
                    text_blob = json.dumps(issue, ensure_ascii=False)
                    related_req = [
                        req_id
                        for req_id in (str(req.get("id") or "").strip() for req in req_rows)
                        if req_id and req_id in text_blob
                    ]
                if not meeting_id:
                    continue
                participants = []
                for entry in issue.get("conversation") or []:
                    if not isinstance(entry, dict):
                        continue
                    agent = str(entry.get("agent") or "").strip()
                    if agent:
                        participants.append(agent)
                description = (
                    resolution.get("summary")
                    or issue.get("summary")
                    or issue.get("title")
                )
                decision = resolution.get("decision") or ""
                meeting_rows.append({
                    "id": meeting_id,
                    "category": str(issue.get("category") or "").strip(),
                    "topic": str(issue.get("summary") or issue.get("title") or issue.get("issue_id") or "").strip(),
                    "related_req": list(dict.fromkeys(related_req)),
                    "participants": list(dict.fromkeys(participants)),
                    "description": cls.dr_summary(description),
                    "decision": cls.dr_summary(decision, max_chars=420),
                })

        return {
            "stakeholder_statements": statements,
            "user_requirements": user_requirement_rows,
            "conflicts": conflict_rows,
            "feedback": feedback_rows,
            "feedback_sources": feedback_sources,
            "system_models": model_rows,
            "meeting_discussions": meeting_rows,
        }

    @classmethod
    def build_dr_body_context(
        cls,
        req_rows: List[Dict[str, Any]],
        appendix: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        srs_ids = cls.dr_srs_id_map(req_rows)
        req_contexts: List[Dict[str, Any]] = []

        def related_rows(section: str, req_id: str) -> List[Dict[str, Any]]:
            return [
                row
                for row in appendix.get(section) or []
                if isinstance(row, dict) and req_id in (row.get("related_req") or [])
            ]

        for req in req_rows:
            req_id = str(req.get("id") or "").strip()
            if not req_id:
                continue
            req_contexts.append({
                "id": req_id,
                "title": str(req.get("title") or "").strip(),
                "type": str(req.get("type") or "").strip(),
                "srs_id": srs_ids.get(req_id, ""),
                "description": str(req.get("description") or "").strip(),
                "stakeholder_statements": [
                    {
                        "id": row.get("id"),
                        "stakeholder": row.get("stakeholder"),
                        "source": row.get("source"),
                        "text": row.get("text"),
                    }
                    for row in related_rows("stakeholder_statements", req_id)
                ],
                "user_requirements": [
                    {
                        "id": row.get("id"),
                        "stakeholder": row.get("stakeholder"),
                        "source": row.get("source"),
                        "text": row.get("text"),
                    }
                    for row in related_rows("user_requirements", req_id)
                ],
                "conflicts": [
                    {
                        "id": row.get("id"),
                        "related_user_requirements": row.get("related_user_requirements"),
                        "description": row.get("description"),
                        "resolution": row.get("resolution"),
                    }
                    for row in related_rows("conflicts", req_id)
                ],
                "feedback": [
                    {"id": row.get("id"), "type": row.get("type"), "content": row.get("content")}
                    for row in related_rows("feedback", req_id)
                ],
                "system_models": [
                    {
                        "id": row.get("id"),
                        "name": row.get("name"),
                        "type": row.get("type"),
                        "description": row.get("description"),
                    }
                    for row in related_rows("system_models", req_id)
                ],
                "meetings": [
                    {
                        "id": row.get("id"),
                        "topic": row.get("topic"),
                        "participants": row.get("participants"),
                        "discussion": row.get("discussion"),
                    }
                    for row in related_rows("meeting_discussions", req_id)
                ],
            })
        return sorted(req_contexts, key=cls.dr_srs_order_key)

    @staticmethod
    def split_dr_body_context(
        requirements: List[Dict[str, Any]],
        *,
        batch_size: int = 10,
    ) -> List[List[Dict[str, Any]]]:
        rows = [row for row in (requirements or []) if isinstance(row, dict)]
        if not rows:
            return []
        size = max(1, int(batch_size or 1))
        return [rows[index : index + size] for index in range(0, len(rows), size)]

    @staticmethod
    def normalize_dr_model_path(value: Any) -> str:
        image_path = str(value or "").strip()
        if not image_path:
            return ""
        image_path = re.sub(r"^\./", "", image_path)
        image_path = re.sub(r"^(?:\.\./)+", "", image_path)
        image_path = re.sub(r"^(?:artifact/|output/)?models/", "", image_path)
        return f"./models/{image_path}" if image_path else ""

    @staticmethod
    def normalize_dr_model_description(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        purpose_match = re.search(
            r"\*\*用途\*\*\s*[：:]\s*(.*?)(?=\s*\*\*反映需求\*\*\s*[：:]|$)",
            text,
            flags=re.S,
        )
        if purpose_match:
            text = purpose_match.group(1)
        else:
            text = re.sub(
                r"\*\*反映需求\*\*\s*[：:].*$",
                "",
                text,
                flags=re.S,
            )
            text = re.sub(r"\*\*Description\*\*\s*[：:]\s*", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @classmethod
    def render_dr_appendix(cls, appendix: Dict[str, Any]) -> str:
        sections: List[str] = []

        def html_cell(value: Any) -> str:
            text = str(value or "").strip().replace("\n", "<br>")
            text = html.escape(text, quote=False)
            text = re.sub(
                r'&lt;span id="([^"]+)"&gt;&lt;/span&gt;',
                r'<span id="\1"></span>',
                text,
            )
            return text

        def col_width(header: str) -> str:
            widths = {
                "ID": "8%",
                "Type": "14%",
                "Category": "12%",
                "Source": "10%",
                "Stakeholder": "12%",
                "Participants": "18%",
            }
            return widths.get(str(header or "").strip(), "")

        def table(title: str, headers: List[str], rows: List[List[Any]]) -> None:
            if not rows:
                return
            sections.append(f"### {title}\n")
            sections.append("<table>")
            widths = [col_width(header) for header in headers]
            if any(widths):
                sections.append(
                    "<colgroup>"
                    + "".join(
                        f'<col style="width: {width}">' if width else "<col>"
                        for width in widths
                    )
                    + "</colgroup>"
                )
            sections.append(
                "<thead><tr>"
                + "".join(f"<th>{html_cell(header)}</th>" for header in headers)
                + "</tr></thead>"
            )
            sections.append("<tbody>")
            for row in rows:
                sections.append(
                    "<tr>"
                    + "".join(f"<td>{html_cell(value)}</td>" for value in row)
                    + "</tr>"
                )
            sections.append("</tbody></table>\n")

        def conflict_cell(value: Any) -> str:
            return str(value or "").strip().replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")

        user_requirement_text_by_id = {
            str(row.get("id") or "").strip(): str(row.get("text") or "").strip()
            for row in appendix.get("user_requirements") or []
            if str(row.get("id") or "").strip()
        }

        def conflict_requirements_cell(values: List[str]) -> str:
            lines = []
            for value in values:
                req_id = str(value or "").strip()
                if not req_id:
                    continue
                requirement_text = user_requirement_text_by_id.get(req_id)
                label = f"{req_id}：{requirement_text}" if requirement_text else req_id
                lines.append(conflict_cell(label))
            return "<br>".join(lines)

        def conflict_table(rows: List[Dict[str, Any]]) -> None:
            if not rows:
                return
            sections.append("### C. Conflict Requirements\n")
            sections.append('<table class="dr-conflicts">')
            sections.append("<colgroup><col style=\"width: 8%\"><col style=\"width: 44%\"><col style=\"width: 48%\"></colgroup>")
            sections.append("<thead><tr><th>ID</th><th>User Requirements</th><th>Resolution</th></tr></thead>")
            sections.append("<tbody>")
            for row in rows:
                sections.append(
                    "<tr>"
                    f"<td>{cls.dr_link(row.get('id'))}</td>"
                    f"<td>{conflict_requirements_cell(row.get('related_user_requirements') or [])}</td>"
                    f"<td>{conflict_cell(row.get('resolution'))}</td>"
                    "</tr>"
                )
            sections.append("</tbody></table>\n")

        table(
            "A. Stakeholder Statements",
            ["ID", "Stakeholder", "Statement"],
            [
                [cls.dr_link(row.get("id")), row.get("stakeholder"), row.get("text")]
                for row in appendix.get("stakeholder_statements") or []
            ],
        )
        table(
            "B. User Requirements",
            ["ID", "Stakeholder", "Requirement"],
            [
                [cls.dr_link(row.get("id")), row.get("stakeholder"), row.get("text")]
                for row in appendix.get("user_requirements") or []
            ],
        )
        conflict_rows = appendix.get("conflicts") or []
        conflict_table(conflict_rows)
        table(
            "D. Feedback",
            ["ID", "Type", "Content"],
            [
                [
                    cls.dr_link(row.get("id")),
                    row.get("type"),
                    row.get("content"),
                ]
                for row in appendix.get("feedback") or []
            ],
        )
        feedback_sources = appendix.get("feedback_sources") or []
        if feedback_sources:
            links = [
                link
                for source in feedback_sources
                for link in [cls.dr_source_link(source)]
                if link
            ]
            if links:
                sections.append(f"**Sources**: {', '.join(links)}\n")

        model_rows = appendix.get("system_models") or []
        if model_rows:
            sections.append("### E. System Models\n")
            for row in model_rows:
                model_id = str(row.get("id") or "").strip()
                title = f"{model_id}: {row.get('name') or row.get('type') or ''}".strip()
                if model_id:
                    sections.append(f'<span id="{model_id.lower()}"></span>\n')
                sections.append(f"#### {title}\n")
                image_path = str(row.get("image_path") or "").strip()
                plantuml = str(row.get("plantuml") or "").strip()
                if image_path:
                    image_path = cls.normalize_dr_model_path(image_path)
                    sections.append(f"![{model_id}]({image_path})\n")
                elif plantuml:
                    sections.append("```plantuml\n" + plantuml + "\n```\n")
                description = cls.normalize_dr_model_description(row.get("description"))
                if description:
                    sections.append(f"**Description**: {description}\n")
                sections.append("")

        table(
            "F. Meeting Discussions",
            ["ID", "Category", "Participants", "Description", "Decision"],
            [
                [
                    cls.dr_link(row.get("id")),
                    row.get("category"),
                    ", ".join(row.get("participants") or []),
                    row.get("description"),
                    row.get("decision"),
                ]
                for row in appendix.get("meeting_discussions") or []
            ],
        )
        if not sections:
            return ""
        return "## Appendix\n\n" + "\n".join(sections).strip()

    @staticmethod
    def strip_design_rationale_metadata(block: str) -> str:
        text = str(block or "").strip()
        text = re.sub(r"(?m)^<span id=\"req-\d+\"></span>\s*$", "", text)
        text = re.sub(r"(?m)^#{1,6}\s*REQ-\d+\s*[:：].*$", "", text)
        text = re.sub(r"(?m)^#{1,6}\s*(?:FR|NFR|CON)-\d+\s*[:：].*$", "", text)
        text = re.sub(r"(?m)^REQ-\d+\s*[:：].*$", "", text)
        text = re.sub(r"(?m)^(?:FR|NFR|CON)-\d+\s*[:：].*$", "", text)
        text = re.sub(r"(?m)^\*\*Title\*\*\s*[:：].*$", "", text)
        text = re.sub(r"(?m)^\*\*Description\*\*\s*[:：].*$", "", text)
        text = re.sub(
            r"(?is)\*\*Description\*\*\s*[:：].*?(?=\s+\*\*Type\*\*\s*[:：]|\s+\*\*SRS ID\*\*\s*[:：]|\n\s*\n|$)",
            "",
            text,
        )
        text = re.sub(
            r"(?is)\*\*Type\*\*\s*[:：].*?(?=\s+\*\*SRS ID\*\*\s*[:：]|\n\s*\n|$)",
            "",
            text,
        )
        text = re.sub(r"(?is)\*\*SRS ID\*\*\s*[:：].*?(?=\n\s*\n|$)", "", text)
        text = re.sub(r"(?m)^#{1,6}\s*Trace\s*$", "", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    @classmethod
    def normalize_design_rationale_body(
        cls,
        body: str,
        requirements: List[Dict[str, Any]],
    ) -> str:
        raw_body = str(body or "").strip()
        if re.search(r"(?m)^#{1,6}\s*(?:REQ|FR|NFR|CON)-\d+\s*[:：]", raw_body):
            blocks = [
                block.strip()
                for block in re.split(
                    r"(?m)(?=^#{1,6}\s*(?:REQ|FR|NFR|CON)-\d+\s*[:：])",
                    raw_body,
                )
                if block.strip()
            ]
        else:
            blocks = [
                block.strip()
                for block in re.split(r"\n\s*---+\s*\n", raw_body)
                if block.strip()
            ]
        block_by_id: Dict[str, str] = {}
        sequential_blocks = list(blocks)
        for block in blocks:
            match = re.search(r"(?m)^#{1,6}\s*((?:REQ|FR|NFR|CON)-\d+)\s*[:：]", block)
            if match:
                block_by_id[match.group(1)] = block
                sequential_blocks.remove(block)

        req_order = [str(req.get("id") or "").strip() for req in requirements]
        req_index = {req_id: index for index, req_id in enumerate(req_order) if req_id}
        normalized: List[str] = []
        ordered_requirements = sorted(requirements, key=cls.dr_srs_order_key)
        for req in ordered_requirements:
            req_id = str(req.get("id") or "").strip()
            title = str(req.get("title") or "").strip()
            description = str(req.get("description") or "").strip()
            srs_id = str(req.get("srs_id") or "").strip()
            if not req_id:
                continue
            block = block_by_id.get(req_id) or block_by_id.get(srs_id) or ""
            if not block:
                fallback_index = req_index.get(req_id, -1)
                if 0 <= fallback_index < len(sequential_blocks):
                    block = sequential_blocks[fallback_index]
            trace = cls.strip_design_rationale_metadata(block)
            header = [
                f'<span id="{req_id.lower()}"></span>',
                f'<span id="{srs_id.lower()}"></span>' if srs_id else "",
                f"### {srs_id}: {title}".rstrip(),
                "",
                f"**Description**: {description}  ",
                "",
                "#### Trace",
            ]
            normalized.append("\n".join(line for line in header if line).strip() + ("\n\n" + trace if trace else ""))
        return "\n\n---\n\n".join(normalized).strip()

    @staticmethod
    def normalize_design_rationale_links(markdown: str) -> str:
        text = str(markdown or "")
        id_patterns = (
            r"ST-\d+",
            r"URL-\d+",
            r"CR-\d+",
            r"FB-\d+",
            r"SM-\d+",
            r"R\d+-M\d+",
            r"REQ-\d+",
            r"FR-\d+",
            r"NFR-\d+",
            r"CON-\d+",
        )
        label_pattern = "|".join(id_patterns)

        def replace_placeholder(match: re.Match[str]) -> str:
            label = match.group(1)
            return f"[{label}](#{label.lower()})"

        text = re.sub(rf"\[({label_pattern})\]\(#\)", replace_placeholder, text)

        def replace_bare_reference(match: re.Match[str]) -> str:
            label = match.group(1)
            return f"[{label}](#{label.lower()})"

        text = re.sub(rf"(?<!\!)\[({label_pattern})\](?!\()", replace_bare_reference, text)

        bare_pattern = re.compile(rf"(?<![\[#/\w-])({label_pattern})(?![\]\(\w-])")

        def replace_bare_id(match: re.Match[str]) -> str:
            label = match.group(1)
            return f"[{label}](#{label.lower()})"

        lines: List[str] = []
        for line in text.splitlines():
            if re.match(r"^\s*#{1,6}\s+", line):
                lines.append(line)
                continue
            lines.append(bare_pattern.sub(replace_bare_id, line))
        return "\n".join(lines)

    @staticmethod
    def normalize_design_rationale_citation_phrasing(markdown: str) -> str:
        text = str(markdown or "")
        text = re.sub(
            r"(?P<prefix>[（(])參見\s*(?=\[(?:(?:ST|URL|CR|FB|SM|REQ|FR|NFR|CON)-\d+|R\d+-M\d+)\]\(#)",
            r"\g<prefix>參考 ",
            text,
        )
        return re.sub(
            r"(?P<prefix>[（(])見\s*(?=\[(?:(?:ST|URL|CR|FB|SM|REQ|FR|NFR|CON)-\d+|R\d+-M\d+)\]\(#)",
            r"\g<prefix>參考 ",
            text,
        )

    @staticmethod
    def normalize_horizontal_rules(markdown: str) -> str:
        text = str(markdown or "")
        return re.sub(r"(?m)(^---\s*$)(?:\s*^---\s*$)+", r"\1", text)

    def generate_dr(self, artifact: Dict[str, Any]) -> str:
        artifact_for_dr = dict(artifact or {})
        versioned_conflicts = self.versioned_conflict_report_rows()
        if versioned_conflicts:
            conflict_state = dict(artifact_for_dr.get("conflict") or {})
            conflict_state["report"] = versioned_conflicts
            artifact_for_dr["conflict"] = conflict_state
        req_rows = [row for row in (artifact_for_dr.get("REQ") or []) if isinstance(row, dict)]
        appendix = self.build_dr_appendix(artifact_for_dr)
        requirements = self.build_dr_body_context(req_rows, appendix)
        batches = self.split_dr_body_context(requirements)
        body_parts: List[str] = []
        for batch in batches:
            prompt = design_rationale(batch)
            raw = self.model.chat(
                self.build_direct_messages(prompt),
                action=self.usage_action("documentor.generate_dr"),
            )
            part = str(raw or "").strip()
            if part.startswith("```"):
                part = re.sub(r"^```(?:markdown|md)?\s*", "", part)
                part = re.sub(r"\s*```$", "", part).strip()
            part = re.sub(r"(?m)^#\s+Design Rationale\s*", "", part).strip()
            if (
                "### Source" in part
                or "### Decision" in part
                or "### Rationale" in part
                or "### Impact" in part
            ):
                raise ValueError("design rationale still contains old meeting-entry sections")
            body_parts.append(part)
        body = "\n\n".join(part for part in body_parts if part.strip()).strip()
        body = self.normalize_design_rationale_body(body, requirements)
        body = self.normalize_design_rationale_links(body)
        body = self.normalize_design_rationale_citation_phrasing(body)
        body = self.normalize_horizontal_rules(body)
        appendix_md = self.render_dr_appendix(appendix)
        markdown = "# Design Rationale\n\n" + body.strip() + ("\n\n" + appendix_md if appendix_md else "") + "\n"
        return self.normalize_horizontal_rules(markdown)
