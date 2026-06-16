# Builds Design Rationale evidence context and trace graphs.
from difflib import SequenceMatcher
import html
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

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
                "srs_id": srs_ids.get(req_id, ""),
                "source": req.get("source"),
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
            raw_trace_events = [
                dict(row)
                for row in (appendix.get("trace_req") or [])
                if isinstance(row, dict)
                and str(row.get("target_requirement_id") or "").strip()
                in {req_id, req_context["srs_id"]}
            ]
            trace_events = []
            for row in raw_trace_events:
                from_id = str(row.get("from") or "").strip()
                to_id = str(row.get("to") or "").strip()
                if (
                    (from_id.startswith(("FB-", "SM-")) and from_id not in visible_trace_node_ids)
                    or (to_id.startswith(("FB-", "SM-")) and to_id not in visible_trace_node_ids)
                ):
                    continue
                trace_events.append(row)
            req_context["trace_events"] = trace_events
            fallback_graph = cls.build_trace_graph(req_context)
            trace_graph = cls.build_trace_graph_from_trace_events(
                req_context,
                trace_events,
                fallback_graph=fallback_graph,
            )
            if (
                trace_graph
                and any(str(node.get("type") or "").strip() == "Meeting Discussion" for node in (fallback_graph.get("nodes") or []))
                and not any(str(node.get("type") or "").strip() == "Meeting Discussion" for node in (trace_graph.get("nodes") or []))
            ):
                trace_graph = fallback_graph
            req_context["trace_graph"] = trace_graph or fallback_graph
            req_context["trace_warnings"] = cls.validate_trace_context(req_context)
            req_context["trace_repair_tasks"] = cls.build_trace_repair_tasks(req_context)
            for warning in req_context["trace_warnings"]:
                logger = getattr(self, "logger", None)
                if logger:
                    logger.warning("DR trace warning | %s | %s", req_context.get("srs_id") or req_id, warning)
            req_contexts.append(req_context)
        return sorted(req_contexts, key=cls.dr_srs_order_key)

    @classmethod
    def build_trace_graph_from_trace_events(
        cls,
        requirement: Dict[str, Any],
        trace_events: List[Dict[str, Any]],
        *,
        fallback_graph: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not trace_events:
            return {}
        target_id = str(requirement.get("srs_id") or requirement.get("id") or "").strip()
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
        for event in trace_events:
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
                for event in trace_events
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
        if direct_formalization_meeting_ids:
            terminal_meeting_id = direct_formalization_meeting_ids[-1]
        elif formalization_meeting_ids:
            entry_formalization_meeting_id = formalization_meeting_ids[0]
            terminal_meeting_id = formalization_meeting_ids[-1]
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
            if (
                relation == "整理"
                and target_node_id.startswith("URL-")
                and node_type_by_id.get(source_id) == "Stakeholder Statement"
            ):
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
        for event in trace_events:
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

        for event in trace_events:
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

        fallback_edges = [
            edge for edge in (fallback_graph.get("edges") or [])
            if isinstance(edge, dict)
        ]
        fallback_conflict_meeting_targets: Dict[str, List[str]] = {}
        for edge in fallback_edges:
            source_id = resolve_node_id(edge.get("from"))
            target_node_id = resolve_node_id(edge.get("to"))
            if (
                source_id
                and target_node_id
                and node_type_by_id.get(source_id) == "Conflict"
                and node_type_by_id.get(target_node_id) == "Meeting Discussion"
                and str(edge.get("relation") or edge.get("edge_label") or "").strip() == "解決"
            ):
                fallback_conflict_meeting_targets.setdefault(source_id, [])
                if target_node_id not in fallback_conflict_meeting_targets[source_id]:
                    fallback_conflict_meeting_targets[source_id].append(target_node_id)

        for row in requirement.get("conflicts") or []:
            if not isinstance(row, dict):
                continue
            conflict_id = resolve_node_id(row.get("id"))
            if not conflict_id or conflict_id not in known_node_ids:
                continue
            for url_id in evidence_url_ids.get(conflict_id) or []:
                add_visible_edge(url_id, conflict_id, {"edge_label": "衝突"})
            conflict_target_ids = (
                fallback_conflict_meeting_targets.get(conflict_id)
                or conflict_resolution_meeting_ids
            )
            for conflict_target_id in conflict_target_ids:
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

        for edge in fallback_edges:
            source_id = str(edge.get("from") or "").strip()
            target_node_id = str(edge.get("to") or "").strip()
            source_type = node_type_by_id.get(source_id, "")
            target_type = node_type_by_id.get(target_node_id, "")
            is_source_to_url_edge = (
                target_node_id.startswith("URL-")
                and source_type in {"Source", "Stakeholder Statement"}
            )
            is_url_edge = (
                is_source_to_url_edge
                or target_node_id.startswith("URL-")
                or source_id.startswith("URL-")
            )
            is_meeting_chain_edge = (
                source_type == "Meeting Discussion"
                and (
                    target_type == "Meeting Discussion"
                    or target_node_id == target_id
                )
            )
            is_conflict_resolution_edge = (
                source_type == "Conflict"
                and target_type == "Meeting Discussion"
                and str(edge.get("relation") or edge.get("edge_label") or "").strip() == "解決"
            )
            if is_url_edge or is_meeting_chain_edge or is_conflict_resolution_edge:
                add_visible_edge(source_id, target_node_id, edge)
        meeting_chain_pairs = {
            (str(edge.get("from") or "").strip(), str(edge.get("to") or "").strip())
            for edge in edges
            if node_type_by_id.get(str(edge.get("from") or "").strip()) == "Meeting Discussion"
            and node_type_by_id.get(str(edge.get("to") or "").strip()) == "Meeting Discussion"
        }
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
            and (str(previous.get("to") or "").strip(), str(edge.get("to") or "").strip()) in meeting_chain_pairs
        }
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
            has_entry_meeting = bool(conflict_resolution_meeting_ids or "R1-M1" in meeting_order)
            if requirement.get("conflicts") or has_entry_meeting:
                edges = [
                    edge for edge in edges
                    if not (
                        str(edge.get("from") or "").strip().startswith("URL-")
                        and node_type_by_id.get(str(edge.get("to") or "").strip()) == "Meeting Discussion"
                        and str(edge.get("relation") or "").strip() == "正式化"
                    )
                ]
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
        if missing_edges:
            requirement["trace_event_warnings"] = missing_edges
        graph["source"] = "trace_req"
        return graph

    @classmethod
    def validate_trace_context(cls, requirement: Dict[str, Any]) -> List[str]:
        req_id = str(requirement.get("id") or "").strip()
        srs_id = str(requirement.get("srs_id") or req_id).strip()
        url_rows = [row for row in requirement.get("user_requirements") or [] if isinstance(row, dict)]
        if not url_rows:
            raise ValueError(f"DR trace missing User Requirement for {srs_id or req_id}")

        warnings: List[str] = []
        for row in requirement.get("trace_event_warnings") or []:
            if not isinstance(row, dict):
                continue
            warnings.append(
                "trace_req edge "
                f"{str(row.get('from') or '').strip()}->{str(row.get('to') or '').strip()} "
                "was excluded because a node was missing from DR context"
            )
        graph = requirement.get("trace_graph") if isinstance(requirement.get("trace_graph"), dict) else {}
        visible_ids = {
            str(node.get("id") or "").strip()
            for node in (graph.get("nodes") or [])
            if isinstance(node, dict) and str(node.get("id") or "").strip()
        }
        known_graph_ids = {
            str(node.get("id") or "").strip()
            for node in (graph.get("all_nodes") or graph.get("nodes") or [])
            if isinstance(node, dict) and str(node.get("id") or "").strip()
        }
        node_type_by_id = {
            str(node.get("id") or "").strip(): str(node.get("type") or "").strip()
            for node in (graph.get("all_nodes") or graph.get("nodes") or [])
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
            def model_fallback_html(*, hidden: bool = False) -> str:
                hidden_attr = " hidden" if hidden else ""
                parts = clean_model_description_parts(row)
                body = "".join(
                    '<p class="dr-trace-model-description__item">'
                    f'<strong>{cls.html_attr(label)}</strong>：{cls.html_attr(value)}'
                    "</p>"
                    for label, value in parts.items()
                )
                return f'<div class="dr-trace-model-description"{hidden_attr}>{body}</div>'

            image_path = normalize_dr_model_path(row.get("image_path"))
            if image_path:
                return (
                    f'<img src="{cls.html_attr(image_path)}" '
                    f'alt="{cls.html_attr(row.get("name") or row.get("id") or "System Model")}" '
                    'onerror="this.hidden=true;this.nextElementSibling.hidden=false">'
                    f'{model_fallback_html(hidden=True)}'
                )
            return model_fallback_html()

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
            source_id = str(row.get("source_id") or row.get("source") or "").strip()
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
                    for item in (row.get("related_sources") or [])
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

        def statement_rank(row: Dict[str, Any]) -> tuple[int, int, int]:
            numbers = [int(match) for match in re.findall(r"\d+", str(row.get("id") or ""))]
            if not numbers:
                return (10**9, 0, 0)
            padded = numbers[:3] + [0] * max(0, 3 - len(numbers))
            return (padded[0], padded[1], padded[2])

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
                add_edge(url_id, feedback_id, "", style="dashed")
        for model in model_rows:
            model_id = str(model.get("id") or "").strip()
            if not model_id:
                continue
            for url_id in related_url_ids(model):
                add_edge(url_id, model_id, "", style="dashed")

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
                if cls.is_conflict_resolution_meeting(meeting):
                    for conflict_id in conflict_ids:
                        add_edge(conflict_id, meeting_id, "解決")
                if index > 0:
                    previous_meeting = meeting_by_id.get(meeting_ids[index - 1], {})
                    has_prior_formalization = any(
                        cls.is_requirement_formalization_meeting(meeting_by_id.get(prior_id, {}))
                        for prior_id in meeting_ids[:index]
                    )
                    if (
                        is_formalization_meeting
                        and (
                            cls.is_conflict_resolution_meeting(previous_meeting)
                            or str(meeting_ids[index - 1]).strip() == "R1-M1"
                        )
                    ):
                        relation = "正式化"
                    elif cls.is_requirement_clarification_meeting(meeting) or has_prior_formalization:
                        relation = "精練"
                    else:
                        relation = ""
                    add_edge(meeting_ids[index - 1], meeting_id, relation)
                if is_formalization_meeting:
                    formalization_sources: List[str] = []
                    if not conflict_ids:
                        formalization_sources = primary_url_ids
                    for source_id in formalization_sources:
                        add_edge(source_id, meeting_id, "正式化")

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
