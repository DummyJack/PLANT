# Handles module workflow behavior.
import html
from pathlib import Path
import re
import shutil
from typing import Optional

from .prompt import generate_srs
from storage.markdown import clean_llm_output, normalize_model_image_markdown


# Defines DocumentorSrs class for this module workflow.
class DocumentorSrs:
    image_suffixes = {".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".bmp"}

    # Defines sync model images function for this module workflow.
    def sync_model_images(self) -> None:
        artifact_models = Path(self.store.artifact_dir) / "models"
        output_models = Path(self.store.output_dir) / "models"
        if not artifact_models.exists():
            return

        output_models.mkdir(parents=True, exist_ok=True)
        for src in artifact_models.iterdir():
            if not src.is_file():
                continue
            if src.suffix.lower() not in self.image_suffixes:
                continue
            dst = output_models / src.name
            shutil.copy2(src, dst)

    @staticmethod
    # Defines fix model links function for this module workflow.
    def fix_model_links(srs_md: str) -> str:
        return re.sub(r"\(\.\./models/", "(./models/", srs_md or "")

    @staticmethod
    # Defines fix design rationale links function for this module workflow.
    def fix_design_rationale_links(srs_md: str) -> str:
        return re.sub(r"\(\./design_rationale\.html(#.*?)?\)", r"(./design_rationale.md\1)", srs_md or "")

    @staticmethod
    # Defines fix traceability requirement links function for this module workflow.
    def fix_traceability_requirement_links(srs_md: str) -> str:
        text = str(srs_md or "")
        pattern = re.compile(
            r"(?m)^(\|\s*)\[((?:FR|NFR|CON)-\d+)\]\([^)]*\)(\s*\|)"
        )

        def repl(match: re.Match) -> str:
            prefix, requirement_id, suffix = match.groups()
            anchor = requirement_id.lower()
            return f"{prefix}[{requirement_id}](./design_rationale.md#{anchor}){suffix}"

        return pattern.sub(repl, text)

    @staticmethod
    def srs_id_map(req_rows: list[dict]) -> dict[str, str]:
        counters = {"functional": 0, "non-functional": 0, "constraint": 0}
        prefixes = {
            "functional": "FR",
            "non-functional": "NFR",
            "constraint": "CON",
        }
        out: dict[str, str] = {}
        for row in req_rows:
            req_id = str(row.get("id") or "").strip()
            req_type = str(row.get("type") or "").strip().lower()
            if not req_id or req_type not in counters:
                continue
            counters[req_type] += 1
            out[req_id] = f"{prefixes[req_type]}-{counters[req_type]}"
        return out

    @staticmethod
    def srs_id_sort_key(value: str) -> tuple[int, int, str]:
        label = str(value or "").strip()
        match = re.fullmatch(r"(FR|NFR|CON)-(\d+)", label)
        if not match:
            return (99, 0, label)
        group_order = {"FR": 0, "NFR": 1, "CON": 2}
        return (group_order.get(match.group(1), 99), int(match.group(2)), label)

    @staticmethod
    def model_anchor(text: str) -> str:
        slug = re.sub(r"[^\w\u4e00-\u9fff -]", "", str(text or "").strip().lower())
        slug = re.sub(r"\s+", "-", slug)
        return slug

    @classmethod
    def model_anchor_map_from_srs(cls, srs_md: str) -> dict[str, str]:
        anchors: dict[str, str] = {}
        for match in re.finditer(r"(?m)^####\s+(SM-\d+)\s*:\s*(.+?)\s*$", srs_md or ""):
            model_id = match.group(1)
            heading = f"{model_id}: {match.group(2).strip()}"
            anchors[model_id] = "#" + cls.model_anchor(heading)
        return anchors

    @staticmethod
    def trace_html_cell(value: str) -> str:
        return html.escape(str(value or "").strip(), quote=False).replace("\n", "<br>")

    @classmethod
    def trace_link(cls, label: str, href: str) -> str:
        clean_label = cls.trace_html_cell(label)
        clean_href = html.escape(str(href or "").strip(), quote=True)
        return f'<a href="{clean_href}">{clean_label}</a>' if clean_label and clean_href else clean_label

    @classmethod
    def trace_source_cell(cls, source: str, model_anchors: Optional[dict[str, str]] = None) -> str:
        label = str(source or "").strip()
        if not label:
            return ""
        if label.lower() in {"feedback", "discussion", "meeting", "system_model", "system_models"}:
            return ""
        if re.fullmatch(r"SM-\d+", label):
            return cls.trace_link(label, (model_anchors or {}).get(label, f"#{label.lower()}"))
        if re.fullmatch(r"(?:ST|URL|CR|FB|SM|REQ|FR|NFR|CON)-\d+|R\d+-M\d+", label):
            return cls.trace_link(label, f"./design_rationale.md#{label.lower()}")
        return cls.trace_html_cell(label)

    @classmethod
    def render_traceability_table(cls, srs_md: str, artifact: dict) -> str:
        req_rows = [row for row in (artifact.get("REQ") or []) if isinstance(row, dict)]
        if not req_rows:
            return ""
        srs_ids = cls.srs_id_map(req_rows)
        model_anchors = cls.model_anchor_map_from_srs(srs_md)

        rows: list[str] = []
        rows.append('<table class="srs-traceability">')
        rows.append('<colgroup><col style="width: 10%"><col style="width: 64%"><col style="width: 26%"></colgroup>')
        rows.append("<thead><tr><th>REQ ID</th><th>Requirement</th><th>Source</th></tr></thead>")
        rows.append("<tbody>")
        sorted_req_rows = sorted(
            req_rows,
            key=lambda req: cls.srs_id_sort_key(srs_ids.get(str(req.get("id") or "").strip(), "")),
        )
        for req in sorted_req_rows:
            req_id = str(req.get("id") or "").strip()
            srs_id = srs_ids.get(req_id)
            if not srs_id:
                continue
            req_link = cls.trace_link(srs_id, f"./design_rationale.md#{srs_id.lower()}")
            requirement = cls.trace_html_cell(req.get("description") or req.get("title") or "")
            raw_sources = req.get("source") if isinstance(req.get("source"), list) else [req.get("source")]
            source_links = [
                cell
                for source in raw_sources
                for cell in [cls.trace_source_cell(str(source).strip(), model_anchors=model_anchors)]
                if str(source or "").strip()
                if cell
            ]
            rows.append(
                "<tr>"
                f"<td>{req_link}</td>"
                f"<td>{requirement}</td>"
                f"<td>{', '.join(source_links)}</td>"
                "</tr>"
            )
        rows.append("</tbody></table>")
        return "\n".join(rows)

    def rebuild_traceability_table(self, srs_md: str) -> str:
        try:
            artifact = self.store.load_artifact() or {}
        except Exception:
            return srs_md
        table = self.render_traceability_table(srs_md, artifact)
        if not table:
            return srs_md
        pattern = re.compile(r"(?ms)^###\s+B\.\s+需求追蹤表\s*\n.*?(?=^###\s+|\Z)")
        replacement = "### B. 需求追蹤表\n\n" + table + "\n"
        text, count = pattern.subn(replacement, srs_md or "")
        return text if count else (srs_md.rstrip() + "\n\n" + replacement)

    @staticmethod
    def normalize_requirement_field_spacing(srs_md: str) -> str:
        text = re.sub(
            r"(?m)^(\*\*Description\*\*[:：])\s*\n+([^\n].*)$",
            lambda match: f"{match.group(1)} {match.group(2).strip()}",
            srs_md or "",
        )
        field_names = "Priority|Acceptance Criteria|Category|Metric|Validation"
        text = re.sub(
            rf"\s+(\*\*(?:{field_names})\*\*[:：])",
            r"\n\n\1",
            text,
        )
        field_pattern = re.compile(
            r"^\*\*(?:Description|Priority|Acceptance Criteria|Category|Metric|Validation)\*\*[:：]"
        )
        lines = text.splitlines()
        normalized: list[str] = []
        for idx, line in enumerate(lines):
            normalized.append(line)
            if not field_pattern.match(line.strip()):
                continue
            if re.match(r"^\*\*Description\*\*[:：]\s+\S", line.strip()):
                continue
            next_line = lines[idx + 1].strip() if idx + 1 < len(lines) else ""
            if next_line and not normalized[-1].endswith("  "):
                normalized.append("")
        return "\n".join(normalized).rstrip() + "\n"

    @staticmethod
    def normalize_model_description_spacing(srs_md: str) -> str:
        text = re.sub(
            r"(?m)^(\*\*用途\*\*[：:].+)\n(\*\*反映需求\*\*[：:])",
            r"\1\n\n\2",
            srs_md or "",
        )
        return text.rstrip() + "\n"

    @staticmethod
    def normalize_scope_headings(srs_md: str) -> str:
        lines = (srs_md or "").splitlines()
        normalized: list[str] = []
        in_scope_section = False
        for line in lines:
            if re.match(r"^##\s+系統範圍\s*$", line):
                in_scope_section = True
                normalized.append(line)
                continue
            if in_scope_section and re.match(r"^##\s+", line):
                in_scope_section = False
            if in_scope_section and re.match(r"^#{3,6}\s+(?:In Scope|Out of Scope)\s*$", line, flags=re.IGNORECASE):
                continue
            normalized.append(line)
        return "\n".join(normalized).rstrip() + "\n"

    @staticmethod
    def normalize_system_purpose_paragraph(srs_md: str) -> str:
        def repl(match: re.Match) -> str:
            heading = match.group(1).rstrip()
            body = match.group(2).strip()
            if not body:
                return f"{heading}\n\n"
            lines = [
                re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", line).strip()
                for line in body.splitlines()
                if line.strip()
            ]
            paragraph = re.sub(r"\s+", " ", " ".join(lines)).strip()
            return f"{heading}\n\n{paragraph}\n\n"

        return re.sub(
            r"(?ms)^(##\s+系統目的\s*)\n+(.*?)(?=^##\s+|\Z)",
            repl,
            srs_md or "",
        ).rstrip() + "\n"

    @staticmethod
    # Defines model heading map function for this module workflow.
    def model_heading_map(draft_md: str) -> dict[str, str]:
        headings: dict[str, str] = {}
        for match in re.finditer(r"(?m)^###\s+(SM-\d+)\s*:?\s+(.+?)\s*$", draft_md or ""):
            model_id = match.group(1).strip()
            title = match.group(2).strip()
            if model_id and title:
                headings[title] = model_id
        return headings

    @classmethod
    # Defines restore model heading ids function for this module workflow.
    def restore_model_heading_ids(cls, srs_md: str, draft_md: str) -> str:
        title_to_id = cls.model_heading_map(draft_md)
        if not title_to_id:
            return srs_md

        def repl(match: re.Match) -> str:
            level = match.group(1)
            title = match.group(2).strip()
            if re.match(r"SM-\d+\b", title):
                return match.group(0)
            model_id = title_to_id.get(title)
            if not model_id:
                return match.group(0)
            return f"{level} {model_id}: {title}"

        return re.sub(r"(?m)^(#{3,4})\s+(.+?)\s*$", repl, srs_md or "")

    # Defines generate from draft function for this module workflow.
    def generate_from_draft(
        self,
        draft_md: str,
    ) -> str:
        self.sync_model_images()
        prompt = generate_srs(draft_md=draft_md)
        srs_md = self.model.chat(
            self.build_direct_messages(prompt),
            action=self.usage_action("documentor.generate_srs"),
        )
        srs_md = clean_llm_output(srs_md)
        srs_md = self.restore_model_heading_ids(srs_md, draft_md)
        srs_md = self.fix_model_links(srs_md)
        srs_md = self.fix_design_rationale_links(srs_md)
        srs_md = self.fix_traceability_requirement_links(srs_md)
        srs_md = normalize_model_image_markdown(srs_md)
        srs_md = self.normalize_scope_headings(srs_md)
        srs_md = self.normalize_system_purpose_paragraph(srs_md)
        srs_md = self.normalize_requirement_field_spacing(srs_md)
        srs_md = self.normalize_model_description_spacing(srs_md)
        srs_md = self.rebuild_traceability_table(srs_md)
        return srs_md

    # Defines generate latest srs function for this module workflow.
    def generate_latest_srs(self) -> str:
        latest_version = self.store.get_draft_version()
        if latest_version < 0:
            raise ValueError("尚無需求草稿，請先產生 draft 再生成 SRS")
        draft_md = self.store.load_draft(latest_version)
        if not draft_md:
            raise ValueError(f"無法載入草稿 draft_v{latest_version}.md")

        return self.generate_from_draft(draft_md)
