# Builds Design Rationale evidence context and trace graphs.
import html
import json
import re
from pathlib import Path
from typing import Any, Dict, List

from storage.markdown import markdown_to_html
from utils.topology import normalize_dr_model_path


class DocumentorDrContext:
    TRACE_AGENT_REPAIR_MAX_ROUNDS = 2

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
    def html_attr(value: Any) -> str:
        return html.escape(str(value or ""), quote=True)

    @staticmethod
    def dr_stakeholder_name(value: Any) -> str:
        if isinstance(value, dict):
            return str(value.get("name") or value.get("role") or "").strip()
        return str(value or "").strip()

    @staticmethod
    def dr_req_sources(row: Dict[str, Any]) -> List[str]:
        raw = row.get("source") if isinstance(row, dict) else []
        values = raw if isinstance(raw, list) else [raw]
        if isinstance(row, dict):
            source_id = str(row.get("source_id") or "").strip()
            if source_id:
                values = list(values) + [source_id]
            related_statement_ids = row.get("related_statement_ids")
            if isinstance(related_statement_ids, list):
                values = list(values) + related_statement_ids
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
            existing_srs_id = str(row.get("srs_id") or "").strip()
            existing_match = re.fullmatch(r"(FR|NFR|CON)-(\d+)", existing_srs_id)
            if req_id and existing_match:
                reverse_prefixes = {"FR": "functional", "NFR": "non-functional", "CON": "constraint"}
                counter_key = reverse_prefixes.get(existing_match.group(1))
                if counter_key in counters:
                    counters[counter_key] = max(counters[counter_key], int(existing_match.group(2)))
                out[req_id] = existing_srs_id
                continue
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
    def meeting_order_key(row: Dict[str, Any]) -> tuple[int, int, str]:
        meeting_id = str(row.get("id") or "").strip()
        match = re.fullmatch(r"R(\d+)-M(\d+)", meeting_id, flags=re.IGNORECASE)
        if match:
            return (int(match.group(1)), int(match.group(2)), meeting_id)
        numbers = [int(value) for value in re.findall(r"\d+", meeting_id)]
        if numbers:
            padded = numbers[:2] + [0] * max(0, 2 - len(numbers))
            return (padded[0], padded[1], meeting_id)
        return (10**9, 10**9, meeting_id)

    @staticmethod
    def is_conflict_resolution_meeting(row: Dict[str, Any]) -> bool:
        return str(row.get("category") or "").strip() == "resolve_conflict"

    @staticmethod
    def is_requirement_formalization_meeting(row: Dict[str, Any]) -> bool:
        return str(row.get("category") or "").strip() == "formalize_requirement"

    @staticmethod
    def is_requirement_clarification_meeting(row: Dict[str, Any]) -> bool:
        return str(row.get("category") or "").strip() == "clarify_requirement"

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
            try:
                markdown_text = path.with_suffix(".md").read_text(encoding="utf-8")
            except OSError:
                markdown_text = ""
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
                item["report_file"] = path.name
                item["report_id"] = str(row.get("id") or "").strip()
                item["report_markdown_entry"] = self.markdown_conflict_entry(markdown_text, item["report_id"])
                item["report_title"] = self.markdown_conflict_title(item["report_markdown_entry"], item["report_id"])
                item["id"] = f"CR-{len(out) + 1}"
                out.append(item)
        return out

    def load_mom_text_by_id(self) -> Dict[str, str]:
        artifact_dir = getattr(getattr(self, "store", None), "artifact_dir", None)
        if not artifact_dir:
            return {}
        mom_dir = Path(artifact_dir) / "MoM"
        out: Dict[str, str] = {}
        for path in sorted(mom_dir.glob("R*-M*.md")):
            meeting_id = path.stem
            try:
                text = path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if text:
                out[meeting_id] = text
        return out

    @staticmethod
    def mom_title_from_text(text: str) -> str:
        for line in str(text or "").splitlines():
            clean = line.strip()
            if clean.startswith("# "):
                return clean[2:].strip()
        return ""

    @classmethod
    def markdown_conflict_entry(cls, markdown: str, row_id: str) -> str:
        target_id = str(row_id or "").strip()
        if not target_id:
            return ""
        lines = str(markdown or "").splitlines()
        start_index = -1
        heading_pattern = re.compile(rf"^##\s+{re.escape(target_id)}(?:\b|[：:.\s-])")
        for index, line in enumerate(lines):
            if heading_pattern.match(line.strip()):
                start_index = index
                break
        if start_index >= 0:
            end_index = len(lines)
            for index in range(start_index + 1, len(lines)):
                stripped = lines[index].strip()
                if stripped.startswith("## ") and not stripped.startswith("### "):
                    end_index = index
                    break
            return "\n".join(lines[start_index:end_index]).strip()
        return ""

    @staticmethod
    def markdown_conflict_title(markdown_entry: str, row_id: str) -> str:
        target_id = str(row_id or "").strip()
        for line in str(markdown_entry or "").splitlines():
            stripped = line.strip()
            match = re.match(r"^##\s+(.+?)\s*$", stripped)
            if not match:
                continue
            title = match.group(1).strip()
            if target_id and title.startswith(target_id):
                title = title[len(target_id):].strip(" ：:-")
            return title
        return ""

    @staticmethod
    def mom_body_without_title(text: str) -> str:
        lines = str(text or "").splitlines()
        out: List[str] = []
        removed = False
        for line in lines:
            if not removed and line.strip().startswith("# "):
                removed = True
                continue
            out.append(line)
        return "\n".join(out).strip()

    def resolve_dr_model_image_path(self, model: Dict[str, Any]) -> str:
        raw_path = str(model.get("image_path") or "").strip()
        model_id = str(model.get("id") or "").strip()
        artifact_dir = Path(getattr(getattr(self, "store", None), "artifact_dir", "") or "")
        output_dir = Path(getattr(getattr(self, "store", None), "output_dir", "") or "")
        project_dir = artifact_dir.parent if artifact_dir else Path()
        search_dirs = [
            artifact_dir / "models",
            output_dir / "models",
            project_dir / "results" / "models",
        ]

        def basename(value: str) -> str:
            text = str(value or "").strip()
            text = re.sub(r"^(?:\.\./|\./)+", "", text)
            text = re.sub(r"^(?:artifact/|output/|results/)?models/", "", text)
            return Path(text).name

        def exists_in_models(filename: str) -> bool:
            if not filename:
                return False
            return any((directory / filename).exists() for directory in search_dirs if directory)

        raw_name = basename(raw_path)
        if raw_name and exists_in_models(raw_name):
            return raw_path

        if model_id and artifact_dir:
            drafts_dir = artifact_dir / "drafts"
            draft_paths: List[tuple[int, Path]] = []
            for path in drafts_dir.glob("draft_v*.md"):
                match = re.fullmatch(r"draft_v(\d+)", path.stem)
                if match:
                    draft_paths.append((int(match.group(1)), path))
            for _, path in sorted(draft_paths, reverse=True):
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                section_match = re.search(
                    rf"(?ms)^###\s+{re.escape(model_id)}\b.*?(?=^###\s+SM-\d+\b|\Z)",
                    text,
                )
                if not section_match:
                    continue
                image_match = re.search(r"!\[[^\]]*\]\(([^)]+)\)", section_match.group(0))
                if not image_match:
                    continue
                candidate = image_match.group(1).strip()
                candidate_name = basename(candidate)
                if candidate_name and exists_in_models(candidate_name):
                    return candidate

        return raw_path

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
            *,
            statement_id: str = "",
        ) -> None:
            clean_text = cls.clean_repeated_text(text)
            if not stakeholder or not clean_text:
                return
            row_id = str(statement_id or "").strip() or f"ST-{len(statements) + 1}"
            if any(row.get("id") == row_id for row in statements):
                row_id = f"ST-{len(statements) + 1}"
            row = {
                "id": row_id,
                "stakeholder": stakeholder,
                "source": source,
                "related_req": list(dict.fromkeys(related_req)),
                "text": clean_text,
            }
            statements.append(row)

        for stakeholder_index, stakeholder in enumerate(artifact.get("stakeholders") or [], start=1):
            if not isinstance(stakeholder, dict):
                continue
            name = cls.dr_stakeholder_name(stakeholder)
            raw_text = stakeholder.get("text")
            if isinstance(raw_text, list):
                statement_rows = [
                    (
                        {"id": str(item.get("id") or "").strip(), "text": str(item.get("text") or "").strip()}
                        if isinstance(item, dict)
                        else {"id": "", "text": str(item).strip()}
                    )
                    for item in raw_text
                ]
            else:
                text = str(raw_text or stakeholder.get("description") or stakeholder.get("goal") or "").strip()
                statement_rows = [{"id": "", "text": text}] if text else []
            statement_rows = [row for row in statement_rows if row.get("text")]
            if not name or not statement_rows:
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
            for text_index, statement in enumerate(statement_rows, start=1):
                text = str(statement.get("text") or "").strip()
                add_statement(
                    name,
                    "initial",
                    text,
                    related,
                    statement_id=str(statement.get("id") or "").strip() or f"ST-{stakeholder_index}-{text_index}",
                )

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
                    add_statement(
                        speaker,
                        source,
                        text,
                        related,
                        statement_id=str(row.get("id") or "").strip(),
                    )

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
            source_id = str(url.get("source_id") or "").strip()
            related_statement_ids = [
                str(item).strip()
                for item in (url.get("related_statement_ids") or [])
                if str(item).strip()
            ]
            user_requirement_rows.append({
                "id": url_id,
                "stakeholder": cls.dr_stakeholder_name(url.get("stakeholder")),
                "source": source_text,
                "source_id": source_id,
                "related_statement_ids": related_statement_ids,
                "related_req": related_req,
                "text": str(url.get("text") or "").strip(),
            })

        conflict_rows = []
        for row in artifact.get("conflict_report") or []:
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
                "report_file": str(row.get("report_file") or "").strip(),
                "report_id": str(row.get("report_id") or "").strip(),
                "report_markdown_entry": str(row.get("report_markdown_entry") or "").strip(),
                "raw_report_row": dict(row),
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
                    "trace_confidence": str(item.get("trace_confidence") or "").strip(),
                    "trace_reason": cls.clean_repeated_text(item.get("trace_reason")),
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
                related_conflicts = [
                    str(conflict_id).strip()
                    for conflict_id in (resolution.get("affected_conflict_ids") or [])
                    if str(conflict_id).strip()
                ]
                source_ids = []
                trace = issue.get("trace") if isinstance(issue.get("trace"), dict) else {}
                source_ids.extend(
                    str(source_id).strip()
                    for source_id in (trace.get("artifact_ids") or [])
                    if str(source_id).strip()
                )
                for source in issue.get("sources") or []:
                    if not isinstance(source, dict):
                        continue
                    source_ids.extend(
                        str(source_id).strip()
                        for source_id in (source.get("ids") or [])
                        if str(source_id).strip()
                    )
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
                    "related_conflicts": list(dict.fromkeys(related_conflicts)),
                    "source_ids": list(dict.fromkeys(source_ids)),
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

    def resolve_dr_appendix_model_images(self, appendix: Dict[str, Any]) -> None:
        for row in appendix.get("system_models") or []:
            if isinstance(row, dict):
                row["image_path"] = self.resolve_dr_model_image_path(row)

    def build_dr_body_context(
        self,
        req_rows: List[Dict[str, Any]],
        appendix: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        cls = type(self)
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
        for row in self.versioned_conflict_report_rows():
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
                "description": cls.clean_repeated_text(
                    row.get("description") or row.get("reason") or row.get("summary")
                ),
                "resolution": cls.clean_repeated_text(
                    row.get("decision") or row.get("recommended_resolution") or row.get("resolution")
                ),
            })
        if versioned_conflicts:
            appendix["conflicts"] = versioned_conflicts
        srs_ids = cls.dr_srs_id_map(req_rows)
        req_contexts: List[Dict[str, Any]] = []
        mom_text_by_id = self.load_mom_text_by_id()

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
            feedback_context_rows = [
                {
                    "id": row.get("id"),
                    "type": row.get("type"),
                    "content": row.get("content"),
                    "related_sources": row.get("related_sources"),
                    "trace_confidence": row.get("trace_confidence"),
                    "trace_reason": row.get("trace_reason"),
                }
                for row in related_rows("feedback", req_id)
            ]
            model_context_rows = [
                {
                    "id": row.get("id"),
                    "name": row.get("name"),
                    "type": row.get("type"),
                    "description": row.get("description"),
                    "image_path": row.get("image_path"),
                    "related_req": row.get("related_req"),
                }
                for row in related_rows("system_models", req_id)
            ]
            conflict_ids_for_req = {
                str(row.get("id") or "").strip()
                for row in conflict_context_rows
                if str(row.get("id") or "").strip()
            }
            related_meeting_rows = [
                {
                    "id": row.get("id"),
                    "category": row.get("category"),
                    "topic": row.get("topic"),
                    "title": cls.mom_title_from_text(mom_text_by_id.get(str(row.get("id") or "").strip(), "")),
                    "participants": row.get("participants"),
                    "description": row.get("description"),
                    "decision": row.get("decision"),
                    "related_conflicts": row.get("related_conflicts"),
                    "source_ids": row.get("source_ids"),
                    "mom_text": mom_text_by_id.get(str(row.get("id") or "").strip(), ""),
                }
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
            conflict_resolution_meetings = [
                row for row in related_meeting_rows
                if cls.is_conflict_resolution_meeting(row)
            ]
            requirement_formalization_meetings = [
                row for row in related_meeting_rows
                if cls.is_requirement_formalization_meeting(row)
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
                "srs_id": srs_ids.get(req_id, ""),
                "description": str(req.get("description") or "").strip(),
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
            req_context["trace_graph"] = cls.build_trace_graph(req_context)
            req_context["trace_warnings"] = cls.validate_trace_context(req_context)
            req_context["trace_repair_tasks"] = cls.build_trace_repair_tasks(req_context)
            for warning in req_context["trace_warnings"]:
                logger = getattr(self, "logger", None)
                if logger:
                    logger.warning("DR trace warning | %s | %s", req_context.get("srs_id") or req_id, warning)
            req_contexts.append(req_context)
        return sorted(req_contexts, key=cls.dr_srs_order_key)

    @classmethod
    def validate_trace_context(cls, requirement: Dict[str, Any]) -> List[str]:
        req_id = str(requirement.get("id") or "").strip()
        srs_id = str(requirement.get("srs_id") or req_id).strip()
        url_rows = [row for row in requirement.get("user_requirements") or [] if isinstance(row, dict)]
        if not url_rows:
            raise ValueError(f"DR trace missing User Requirement for {srs_id or req_id}")

        warnings: List[str] = []
        graph = requirement.get("trace_graph") if isinstance(requirement.get("trace_graph"), dict) else {}
        visible_ids = {
            str(node.get("id") or "").strip()
            for node in (graph.get("nodes") or [])
            if isinstance(node, dict) and str(node.get("id") or "").strip()
        }
        edge_pairs = {
            (str(edge.get("from") or "").strip(), str(edge.get("to") or "").strip())
            for edge in (graph.get("edges") or [])
            if isinstance(edge, dict)
        }

        for url in url_rows:
            url_id = str(url.get("id") or "").strip()
            source_id = str(url.get("source_id") or "").strip()
            related_statement_ids = [
                str(item).strip()
                for item in (url.get("related_statement_ids") or [])
                if str(item).strip()
            ]
            if source_id and (source_id, url_id) not in edge_pairs:
                warnings.append(f"{url_id} source_id {source_id} was not connected in topology")
            for statement_id in related_statement_ids:
                if (statement_id, url_id) not in edge_pairs:
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
                row_id = str(row.get("id") or "").strip()
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
        if meeting_rows and not formalization_meeting_ids:
            warnings.append(f"{srs_id or req_id} has meetings but no visible formalize_requirement meeting")

        return warnings

    @classmethod
    def build_trace_repair_tasks(cls, requirement: Dict[str, Any]) -> List[Dict[str, Any]]:
        req_id = str(requirement.get("id") or "").strip()
        srs_id = str(requirement.get("srs_id") or req_id).strip()
        graph = requirement.get("trace_graph") if isinstance(requirement.get("trace_graph"), dict) else {}
        visible_ids = {
            str(node.get("id") or "").strip()
            for node in (graph.get("nodes") or [])
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
            evidence_ids: List[str] | None = None,
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
                    edge_label="整理",
                    confidence="high",
                )
            for statement_id in related_statement_ids:
                if (statement_id, url_id) not in edge_pairs:
                    add_task(
                        "connect_statement_to_url",
                        f"{url_id} declares related_statement_id {statement_id}, but the topology did not include that source edge.",
                        candidate_from=statement_id,
                        candidate_to=url_id,
                        edge_label="整理",
                        confidence="high",
                    )
            if not source_id and not related_statement_ids:
                add_task(
                    "identify_url_source",
                    f"{url_id} has no explicit source_id or related_statement_ids; Agent may identify candidate stakeholder evidence for human review.",
                    candidate_to=url_id,
                    edge_label="整理",
                    confidence="low",
                    evidence_ids=[url_id],
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
    def public_dr_requirement_context(cls, requirement: Dict[str, Any]) -> Dict[str, Any]:
        public = dict(requirement)
        graph = public.get("trace_graph")
        if isinstance(graph, dict) and "all_nodes" in graph:
            public["trace_graph"] = {key: value for key, value in graph.items() if key != "all_nodes"}
        return public

    @classmethod
    def public_dr_requirement_contexts(cls, requirements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [cls.public_dr_requirement_context(req) for req in requirements]

    @staticmethod
    def trace_target_aliases(requirement: Dict[str, Any]) -> set[str]:
        return {
            str(requirement.get("id") or "").strip(),
            str(requirement.get("srs_id") or "").strip(),
        } - {""}

    @classmethod
    def validate_trace_repair_proposal(cls, requirement: Dict[str, Any], proposal: Dict[str, Any]) -> Dict[str, Any]:
        graph = requirement.get("trace_graph") if isinstance(requirement.get("trace_graph"), dict) else {}
        graph_node_rows = [
            node for node in (graph.get("all_nodes") or graph.get("nodes") or [])
            if isinstance(node, dict)
        ]
        node_ids = {
            str(node.get("id") or "").strip()
            for node in graph_node_rows
            if str(node.get("id") or "").strip()
        }
        for section in ("stakeholder_statements", "user_requirements", "conflicts", "feedback", "system_models", "meetings"):
            for row in requirement.get(section) or []:
                if isinstance(row, dict) and str(row.get("id") or "").strip():
                    node_ids.add(str(row.get("id") or "").strip())
        target_id = str(requirement.get("srs_id") or requirement.get("id") or "").strip()
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
            "connect_statement_to_url": {"整理"},
            "connect_feedback_to_formalize_meeting": {""},
            "connect_model_to_formalize_meeting": {""},
            "connect_resolve_to_formalize_meeting": {"正式化"},
            "identify_url_source": {"整理"},
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
        all_nodes = [
            node for node in (graph.get("all_nodes") or graph.get("nodes") or [])
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
            target_id=str(updated.get("srs_id") or updated.get("id") or "").strip(),
        )
        updated["trace_repair_applied"] = list((updated.get("trace_repair_applied") or [])) + applied
        updated["trace_warnings"] = cls.validate_trace_context(updated)
        updated["trace_repair_tasks"] = cls.build_trace_repair_tasks(updated)
        return updated

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
        target_id = str(requirement.get("srs_id") or requirement.get("id") or "").strip()
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
        ) -> None:
            clean_id = str(node_id or "").strip()
            if not clean_id or clean_id in nodes:
                return
            nodes[clean_id] = {
                "id": clean_id,
                "type": node_type,
                "label": cls.clean_repeated_text(label) or clean_id,
                "title": cls.clean_repeated_text(title) or f"{clean_id} · {node_type}",
                "content": content,
                "content_format": content_format,
                "column": column,
            }

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

        def model_image_html(row: Dict[str, Any]) -> str:
            image_path = normalize_dr_model_path(row.get("image_path"))
            if image_path:
                return (
                    f'<img src="{cls.html_attr(image_path)}" '
                    f'alt="{cls.html_attr(row.get("name") or row.get("id") or "System Model")}">'
                )
            return content_from(row, ["name", "type", "description"])

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
            display_id = re.sub(r"^(ST-\d+)-\d+$", r"\1", statement_id) or statement_id
            if re.fullmatch(r"elicit-\d+-\d+", display_id):
                display_id = f"ST-{statement_index}"
            label = f"{display_id} {stakeholder}".strip()
            statement_text = str(row.get("text") or "").strip()
            card_html = (
                '<div class="dr-trace-card">'
                f'<div class="dr-trace-card__main">{cls.html_attr(f"發言：{statement_text}")}</div>'
                f'<div class="dr-trace-card__meta">{cls.html_attr(f"來源：{statement_id}")}</div>'
                "</div>"
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
            source_id = str(row.get("source_id") or row.get("source") or "").strip()
            meta_parts = []
            if stakeholder:
                meta_parts.append(f"利害關係人：{stakeholder}")
            if source_id:
                meta_parts.append(f"來源：{source_id}")
            card_html = (
                '<div class="dr-trace-card">'
                f'<div class="dr-trace-card__main">{cls.html_attr(f"{url_id}：{requirement_text}")}</div>'
                f'<div class="dr-trace-card__meta">{cls.html_attr("  ".join(meta_parts))}</div>'
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

        for row in requirement.get("user_requirements") or []:
            if not isinstance(row, dict):
                continue
            stakeholder = cls.dr_stakeholder_name(row.get("stakeholder"))
            source_ids = []
            source_id = str(row.get("source_id") or "").strip()
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
            target_id,
            str(requirement.get("description") or "").strip(),
            "Requirement",
        )

        stakeholder_rows = [row for row in requirement.get("stakeholder_statements") or [] if isinstance(row, dict)]
        url_rows = [row for row in requirement.get("user_requirements") or [] if isinstance(row, dict)]
        conflict_rows = [row for row in requirement.get("conflicts") or [] if isinstance(row, dict)]
        feedback_rows = [row for row in requirement.get("feedback") or [] if isinstance(row, dict)]
        model_rows = [row for row in requirement.get("system_models") or [] if isinstance(row, dict)]
        meeting_rows = [row for row in requirement.get("meetings") or [] if isinstance(row, dict)]
        if len(feedback_rows) > 1:
            table_rows = []
            for row in feedback_rows:
                row_id = str(row.get("id") or "").strip()
                if not row_id:
                    continue
                source_chips = "".join(
                    f'<span class="dr-trace-source-chip">{cls.html_attr(str(item).strip())}</span>'
                    for item in (row.get("related_sources") or [])
                    if str(item).strip()
                )
                table_rows.append(
                    "<tr>"
                    f"<td>{cls.html_attr(row_id)}</td>"
                    f"<td>{cls.html_attr(row.get('type') or '')}</td>"
                    f"<td>{source_chips}</td>"
                    f"<td>{cls.html_attr(cls.clean_repeated_text(row.get('content')))}</td>"
                    "</tr>"
                )
            feedback_content = (
                '<table class="dr-trace-feedback-table"><thead><tr>'
                "<th>ID</th><th>Type</th><th>Source</th><th>Content</th>"
                "</tr></thead><tbody>"
                + "".join(table_rows)
                + "</tbody></table>"
            )
            feedback_related_sources = []
            for row in feedback_rows:
                feedback_related_sources.extend(
                    str(item).strip()
                    for item in (row.get("related_sources") or [])
                    if str(item).strip()
                )
            feedback_rows = [{
                "id": f"FB-GROUP-{target_id}",
                "type": "Feedback Group",
                "count": len(table_rows),
                "content": feedback_content,
                "related_sources": list(dict.fromkeys(feedback_related_sources)),
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

        def statement_rank(row: Dict[str, Any]) -> tuple[int, int, int]:
            numbers = [int(match) for match in re.findall(r"\d+", str(row.get("id") or ""))]
            if not numbers:
                return (10**9, 0, 0)
            padded = numbers[:3] + [0] * max(0, 3 - len(numbers))
            return (padded[0], padded[1], padded[2])

        for url in url_rows:
            url_source_id = str(url.get("source_id") or "").strip()
            if url_source_id:
                add_edge(url_source_id, url.get("id"), "整理")
                continue
            for source_id in url.get("related_statement_ids") or []:
                add_edge(source_id, url.get("id"), "整理")

        for conflict in conflict_rows:
            related_sources = [str(item).strip() for item in (conflict.get("related_user_requirements") or []) if str(item).strip()]
            for source_id in related_sources:
                add_edge(source_id, conflict.get("id"), "")

        for feedback in feedback_rows:
            related_sources = [str(item).strip() for item in (feedback.get("related_sources") or []) if str(item).strip()]
            for source_id in related_sources:
                add_edge(source_id, feedback.get("id"), "依據")

        for model in model_rows:
            model_id = str(model.get("id") or "").strip()
            if not model_id:
                continue
            source_ids = [
                str(row.get("id") or "").strip()
                for row in url_rows
                if str(row.get("id") or "").strip()
            ]
            for source_id in source_ids:
                add_edge(source_id, model_id, "建模")

        conflict_ids = [str(row.get("id") or "").strip() for row in conflict_rows if str(row.get("id") or "").strip()]
        feedback_ids = [str(row.get("id") or "").strip() for row in feedback_rows if str(row.get("id") or "").strip()]
        model_ids = [str(row.get("id") or "").strip() for row in model_rows if str(row.get("id") or "").strip()]
        url_ids = [str(row.get("id") or "").strip() for row in url_rows if str(row.get("id") or "").strip()]
        meeting_ids = [str(row.get("id") or "").strip() for row in meeting_rows if str(row.get("id") or "").strip()]
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
                    add_edge(feedback_id, meeting_id, "" if is_formalization_meeting else "依據")
                    explicit_feedback_meeting_ids.add(feedback_id)
            for model_id in model_ids:
                if model_id in source_ids:
                    add_edge(model_id, meeting_id, "" if is_formalization_meeting else "建模")
                    explicit_model_meeting_ids.add(model_id)

        if meeting_ids:
            for index, meeting_id in enumerate(meeting_ids):
                meeting = meeting_by_id.get(meeting_id, {})
                is_formalization_meeting = cls.is_requirement_formalization_meeting(meeting)
                if cls.is_conflict_resolution_meeting(meeting):
                    for conflict_id in conflict_ids:
                        add_edge(conflict_id, meeting_id, "解決")
                if index > 0:
                    previous_meeting = meeting_by_id.get(meeting_ids[index - 1], {})
                    if cls.is_requirement_clarification_meeting(meeting):
                        relation = "釐清"
                    elif is_formalization_meeting and cls.is_conflict_resolution_meeting(previous_meeting):
                        relation = "正式化"
                    else:
                        relation = ""
                    add_edge(meeting_ids[index - 1], meeting_id, relation)
                if is_formalization_meeting:
                    for source_id in ([] if conflict_ids else url_ids):
                        add_edge(source_id, meeting_id, "正式化")

            primary_formalization_meeting_id = formalization_meeting_ids[-1] if formalization_meeting_ids else ""
            for feedback_id in feedback_ids:
                if primary_formalization_meeting_id:
                    add_edge(feedback_id, primary_formalization_meeting_id, "")
            for model_id in model_ids:
                if primary_formalization_meeting_id:
                    add_edge(model_id, primary_formalization_meeting_id, "")
            for meeting_id in meeting_ids:
                if meeting_id in formalization_meeting_ids or meeting_id in clarification_meeting_ids:
                    continue
                if cls.is_conflict_resolution_meeting(meeting_by_id.get(meeting_id, {})):
                    continue
                if primary_formalization_meeting_id:
                    add_edge(meeting_id, primary_formalization_meeting_id, "")
                else:
                    add_edge(meeting_id, target_id, "")

            if clarification_meeting_ids:
                terminal_meeting_id = clarification_meeting_ids[-1]
                add_edge(terminal_meeting_id, target_id, "")
            elif formalization_meeting_ids:
                terminal_meeting_id = formalization_meeting_ids[-1]
                add_edge(terminal_meeting_id, target_id, "")
        else:
            for url in url_rows:
                add_edge(url.get("id"), target_id, "")

        return cls.visible_trace_graph(
            all_nodes=list(nodes.values()),
            edges=edges,
            target_id=target_id,
        )

    @staticmethod
    def split_dr_body_context(
        requirements: List[Dict[str, Any]],
        *,
        batch_size: int = 1,
    ) -> List[List[Dict[str, Any]]]:
        rows = [row for row in (requirements or []) if isinstance(row, dict)]
        if not rows:
            return []
        size = max(1, int(batch_size or 1))
        return [rows[index : index + size] for index in range(0, len(rows), size)]
