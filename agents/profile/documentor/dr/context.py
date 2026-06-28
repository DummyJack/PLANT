# Builds Design Rationale evidence context and trace graphs.
from difflib import SequenceMatcher
import html
import json
import re
from pathlib import Path
from typing import Any, Dict, List

from .trace import (
    DocumentorDrTraceGraphMixin,
    DocumentorDrTracePublicMixin,
    DocumentorDrTraceValidationMixin,
)
from .trace.selection import select_dr_requirement_contexts


class DocumentorDrContext(
    DocumentorDrTraceGraphMixin,
    DocumentorDrTraceValidationMixin,
    DocumentorDrTracePublicMixin,
):
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
        if max_chars <= 0 or len(text) <= max_chars:
            return text
        sentences = re.findall(r"[^。；;.!?！？]+[。；;.!?！？]?", text)
        selected: List[str] = []
        total = 0
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if selected and total + len(sentence) > max_chars:
                break
            if not selected and len(sentence) > max_chars:
                boundary = max(
                    sentence.rfind("，", 0, max_chars),
                    sentence.rfind("、", 0, max_chars),
                    sentence.rfind(",", 0, max_chars),
                    sentence.rfind(" ", 0, max_chars),
                )
                if boundary >= max_chars // 2:
                    sentence = sentence[:boundary]
                else:
                    sentence = sentence[:max_chars]
                sentence = sentence.rstrip(" ，、,。；;.!?！？")
                if sentence and re.search(r"[\u4e00-\u9fff]$", sentence):
                    sentence += "。"
                selected.append(sentence)
                break
            selected.append(sentence)
            total += len(sentence)
        summary = "".join(selected).strip()
        return summary or text[:max_chars].rstrip(" ，、,。；;.!?！？")

    @staticmethod
    def html_attr(value: Any) -> str:
        return html.escape(str(value or ""), quote=True)

    @staticmethod
    def dr_stakeholder_name(value: Any) -> str:
        if isinstance(value, dict):
            return str(value.get("name") or "").strip()
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
        out: Dict[str, str] = {}
        for row in req_rows:
            req_id = str(row.get("id") or "").strip()
            existing_srs_id = str(row.get("srs_id") or "").strip()
            existing_match = re.fullmatch(r"(FR|NFR|CON)-(\d+)", existing_srs_id)
            if req_id and existing_match:
                out[req_id] = existing_srs_id
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
                text = str(raw_text or "").strip()
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

        statements_by_stakeholder: Dict[str, List[Dict[str, Any]]] = {}
        for statement in statements:
            stakeholder_name = str(statement.get("stakeholder") or "").strip()
            if stakeholder_name:
                statements_by_stakeholder.setdefault(stakeholder_name, []).append(statement)

        def infer_related_statement_ids(url: Dict[str, Any], source_text: str) -> List[str]:
            explicit_source_id = str(url.get("source_id") or "").strip()
            explicit_related = [
                str(item).strip()
                for item in (url.get("related_statement_ids") or [])
                if str(item).strip()
            ]
            if explicit_source_id or explicit_related:
                return explicit_related
            if not re.fullmatch(r"R\d+-M\d+", str(source_text or "").strip(), flags=re.IGNORECASE):
                return []
            stakeholder_name = cls.dr_stakeholder_name(url.get("stakeholder"))
            candidates = statements_by_stakeholder.get(stakeholder_name) or []
            url_text = str(url.get("text") or "").strip()
            if not stakeholder_name or not candidates or not url_text:
                return []

            def chinese_chars(value: str) -> set[str]:
                return {
                    char
                    for char in str(value or "")
                    if "\u4e00" <= char <= "\u9fff"
                }

            url_chars = chinese_chars(url_text)
            scored: List[tuple[float, str]] = []
            for statement in candidates:
                statement_id = str(statement.get("id") or "").strip()
                statement_text = str(statement.get("text") or "").strip()
                if not statement_id or not statement_text:
                    continue
                overlap = len(url_chars.intersection(chinese_chars(statement_text))) / max(1, len(url_chars))
                sequence_ratio = SequenceMatcher(None, url_text, statement_text).ratio()
                score = max(overlap, sequence_ratio)
                if overlap >= 0.45 or sequence_ratio >= 0.30:
                    scored.append((score, statement_id))
            scored.sort(reverse=True)
            return [statement_id for _, statement_id in scored[:1]]

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
            if not source_id and not related_statement_ids:
                related_statement_ids = infer_related_statement_ids(url, source_text)
            user_requirement_rows.append({
                "id": url_id,
                "stakeholder": cls.dr_stakeholder_name(url.get("stakeholder")),
                "source": source_text,
                "source_id": source_id,
                "related_statement_ids": related_statement_ids,
                "related_req": related_req,
                "text": str(url.get("text") or "").strip(),
            })

        conflict_report_rows = artifact.get("conflict_report") or []
        conflict_state = artifact.get("conflict") if isinstance(artifact.get("conflict"), dict) else {}
        if not conflict_report_rows:
            conflict_report_rows = conflict_state.get("report") or []
        conflict_rows = []
        for row in conflict_report_rows:
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
                "description": cls.clean_repeated_text(row.get("description")),
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
                source_ids = [
                    str(value).strip()
                    for value in (item.get("source_ids") or [])
                    if str(value).strip()
                ]
                source = str(item.get("source") or "").strip()
                if source:
                    source_ids.append(source)
                feedback_rows.append({
                    "id": f"FB-{len(feedback_rows) + 1}",
                    "type": section[:-1] if section.endswith("s") else section,
                    "related_req": list(dict.fromkeys(related_req)),
                    "related_sources": related_ids,
                    "source_ids": list(dict.fromkeys(source_ids)),
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
            related_ids = [
                str(item).strip()
                for item in (model.get("related_requirement_ids") or [])
                if str(item).strip()
            ]
            related_req = [
                req_id
                for req_id in cls.dr_related_req_ids_from_sources(related_ids, source_to_req)
                if req_id in valid_req_ids
            ]
            if not model_id or not related_req:
                continue
            source_ids = [
                str(value).strip()
                for value in (model.get("source_ids") or [])
                if str(value).strip()
            ]
            source = str(model.get("source") or "").strip()
            if source:
                source_ids.append(source)
            model_rows.append({
                "id": model_id,
                "name": str(model.get("name") or "").strip(),
                "type": str(model.get("type") or "").strip(),
                "related_req": list(dict.fromkeys(related_req)),
                "related_sources": related_ids,
                "source_ids": list(dict.fromkeys(source_ids)),
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
                    "topic": str(issue.get("summary") or issue.get("title") or "").strip(),
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
            "trace_req": [
                dict(row)
                for row in (artifact.get("trace_req") or [])
                if isinstance(row, dict)
            ],
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
        req_contexts: List[Dict[str, Any]] = []
        for req_context in select_dr_requirement_contexts(self, req_rows, appendix):
            req_id = str(req_context.get("id") or "").strip()
            trace_req_rows = [
                row for row in (req_context.get("trace_req_rows") or [])
                if isinstance(row, dict)
            ]
            fallback_graph = cls.build_trace_graph(req_context)
            trace_graph = cls.build_trace_graph_from_trace_req(
                req_context,
                trace_req_rows,
                fallback_graph=fallback_graph,
            )
            req_context["trace_repair_reference_graph"] = fallback_graph
            req_context["trace_graph"] = trace_graph
            if not trace_graph:
                req_context["trace_runtime_status"] = "needs_agent_trace_repair"
                req_context["trace_event_warnings"] = list(req_context.get("trace_event_warnings") or []) + [
                    {
                        "from": "",
                        "to": req_context.get("srs_id") or req_id,
                        "reason": "trace_req did not produce a valid visible graph; runtime fallback graph is available only as repair reference",
                    }
                ]
            elif (
                any(str(node.get("type") or "").strip() == "Meeting Discussion" for node in (fallback_graph.get("nodes") or []))
                and not any(str(node.get("type") or "").strip() == "Meeting Discussion" for node in (trace_graph.get("nodes") or []))
            ):
                req_context["trace_runtime_status"] = "needs_agent_trace_repair"
                req_context["trace_event_warnings"] = list(req_context.get("trace_event_warnings") or []) + [
                    {
                        "from": "",
                        "to": req_context.get("srs_id") or req_id,
                        "reason": "trace_req graph omitted meeting evidence; runtime fallback graph is available only as repair reference",
                    }
                ]
            req_context["trace_warnings"] = cls.validate_trace_context(req_context)
            req_context["trace_repair_tasks"] = cls.build_trace_repair_tasks(req_context)
            for warning in req_context["trace_warnings"]:
                logger = getattr(self, "logger", None)
                if logger:
                    logger.warning("DR trace warning | %s | %s", req_context.get("srs_id") or req_id, warning)
            req_contexts.append(req_context)
        return sorted(req_contexts, key=cls.dr_srs_order_key)

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
