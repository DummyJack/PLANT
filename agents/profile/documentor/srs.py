# Handles module workflow behavior.
import ast
import difflib
from pathlib import Path
import re
import shutil
from typing import Optional

from .actions.srs import generate_srs
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

    # Defines fix model image filenames function for this module workflow.
    def fix_model_image_filenames(self, srs_md: str) -> str:
        models_dir = Path(self.store.output_dir) / "models"
        if not models_dir.exists():
            return srs_md

        existing = [
            path.name
            for path in models_dir.iterdir()
            if path.is_file() and path.suffix.lower() in self.image_suffixes
        ]
        if not existing:
            return srs_md

        def best_match(label: str, filename: str) -> str:
            candidates = []
            for existing_name in existing:
                stem = Path(existing_name).stem
                score = max(
                    difflib.SequenceMatcher(None, label, stem).ratio(),
                    difflib.SequenceMatcher(None, Path(filename).stem, stem).ratio(),
                )
                candidates.append((score, existing_name))
            score, name = max(candidates, key=lambda item: item[0])
            return name if score >= 0.45 else filename

        def repl(match: re.Match) -> str:
            alt = match.group("alt").strip()
            path = match.group("path").strip()
            filename = Path(path).name
            if (models_dir / filename).exists():
                return match.group(0)
            fixed = best_match(alt, filename)
            if fixed == filename:
                return match.group(0)
            return f"![{alt}](./models/{fixed})"

        return re.sub(
            r"!\[(?P<alt>[^\]]*)\]\((?P<path>\./models/[^)]+)\)",
            repl,
            srs_md or "",
        )

    @staticmethod
    def validate_srs_new_format(srs_md: str) -> None:
        text = str(srs_md or "")
        if re.search(r"(?m)^#{2,6}\s+REQ-\d+\s*[:：]", text):
            raise ValueError("SRS output uses old REQ-* requirement headings")
        if re.search(r"(?m)^Description\s*[:：]", text):
            raise ValueError("SRS output uses old unbolded Description field")
        if re.search(r"\(\./design_rationale\.(?:md|html)(?:#[^)]+)?\)", text):
            raise ValueError("SRS output links to old design_rationale artifact")
        if re.search(r"(?mi)^#{2,6}\s+(?:Traceability|需求追蹤表)\s*$", text):
            raise ValueError("SRS output contains old traceability section")
        if re.search(r"(?mi)REQ ID\s*\|\s*Requirement\s*\|\s*Source", text):
            raise ValueError("SRS output contains old traceability table")

    @staticmethod
    def retry_srs_prompt(prompt: str, error: Exception) -> str:
        return (
            f"{prompt.rstrip()}\n\n"
            "# Format Validation Error\n"
            f"{error}\n\n"
            "# Retry Instruction\n"
            "- 你剛剛輸出了舊格式或不合法格式。\n"
            "- 請只重新輸出完整 Markdown SRS。\n"
            "- 必須使用新格式：SRS 需求標題只能是 `#### FR-*`、`#### NFR-*`；constraint 只放在系統限制。\n"
            "- 不得使用 `REQ-*` 作為 SRS 需求標題。\n"
            "- 需求欄位必須使用粗體欄位名，例如 `**Description**:`。\n"
            "- 不得連到 `design_rationale.md`；追蹤連結使用 `dr`。\n"
            "- 不要解釋錯誤，不要包程式碼區塊。\n"
        )

    @staticmethod
    def restore_appendix_heading(srs_md: str) -> str:
        text = str(srs_md or "")
        if re.search(r"(?m)^##\s+附錄\s*$", text):
            return text.rstrip() + "\n"
        text = re.sub(
            r"(?m)^###\s+A\.\s+系統模型\s*$",
            "## 附錄\n\n### A. 系統模型",
            text,
            count=1,
        )
        return re.sub(r"\n{3,}", "\n\n", text).rstrip() + "\n"

    @staticmethod
    def insert_design_rationale_links(srs_md: str) -> str:
        text = str(srs_md or "")
        text = re.sub(
            r"(?m)^\*\*Design Rationale\*\*[:：]\s*\[[^\]]+\]\([^)]*\)\s*\n?",
            "",
            text,
        )
        text = re.sub(
            r"(?m)^(####\s+(?:FR|NFR)-\d+\s*[:：].*?)\s+\[\[DR\]\]\(\./dr#(?:fr|nfr)-\d+\)\s*$",
            r"\1",
            text,
        )
        text = re.sub(
            r"(?m)^(\d+\.\s+.*?)(?:\s+\[\[DR\]\]\(\./dr#con-\d+\))\s*$",
            r"\1",
            text,
        )

        heading_pattern = re.compile(r"(?m)^####\s+((?:FR|NFR)-\d+\s*[:：].*?)\s*$")

        def repl(match: re.Match) -> str:
            title = match.group(1).rstrip()
            srs_id = title.split(":", 1)[0].split("：", 1)[0].strip()
            anchor = srs_id.lower()
            return f"#### {title} [[DR]](./dr#{anchor})"

        text = heading_pattern.sub(repl, text)

        def link_constraint_section(match: re.Match) -> str:
            heading = match.group("heading").rstrip()
            body = match.group("body")
            counter = 0

            def link_item(item_match: re.Match) -> str:
                nonlocal counter
                counter += 1
                marker = item_match.group("marker")
                content = item_match.group("content").rstrip()
                if "<a " in content and "dr#con-" in content:
                    return item_match.group(0)
                return f'{marker}{content} [[DR]](./dr#con-{counter})'

            linked_body = re.sub(
                r"(?m)^(?P<marker>\d+\.\s+)(?P<content>.+)$",
                link_item,
                body,
            )
            return f"{heading}\n\n{linked_body.rstrip()}\n\n"

        text = re.sub(
            r"(?ms)^(?P<heading>##\s+系統限制)\s*\n+(?P<body>.*?)(?=^##\s+|\Z)",
            link_constraint_section,
            text,
        )
        return re.sub(r"\n{3,}", "\n\n", text).rstrip() + "\n"

    @staticmethod
    def srs_id_map(req_rows: list[dict]) -> dict[str, str]:
        out: dict[str, str] = {}
        for row in req_rows:
            req_id = str(row.get("id") or "").strip()
            existing_srs_id = str(row.get("srs_id") or "").strip()
            existing_match = re.fullmatch(r"(FR|NFR|CON)-(\d+)", existing_srs_id)
            if req_id and existing_match:
                out[req_id] = existing_srs_id
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
    def normalize_model_description_labels(srs_md: str) -> str:
        lines = (srs_md or "").splitlines()
        normalized: list[str] = []
        previous_was_model_description = False
        in_system_context = False
        in_model_appendix = False
        for line in lines:
            stripped = line.strip()
            if re.match(r"^##\s+系統情境\s*$", stripped):
                in_system_context = True
                in_model_appendix = False
            elif re.match(r"^###\s+A\.\s+系統模型\s*$", stripped):
                in_model_appendix = True
                in_system_context = False
            elif re.match(r"^##\s+", stripped):
                in_system_context = False
                in_model_appendix = False
            labels = "用途|反映需求"
            if in_system_context or in_model_appendix:
                labels = "Description|用途|反映需求"
            match = re.match(rf"^\*\*(?:{labels})\*\*[：:]\s*(.*)$", stripped)
            if match:
                content = match.group(1).strip()
                if previous_was_model_description and content and normalized and normalized[-1] != "":
                    normalized.append("")
                normalized.append(content)
                previous_was_model_description = True
                continue
            normalized.append(line)
            previous_was_model_description = False if stripped else previous_was_model_description
        return "\n".join(normalized).rstrip() + "\n"

    @staticmethod
    def normalize_serialized_list_cells(markdown_text: str) -> str:
        def clean_literal(value: str) -> str:
            text = value.strip()
            if not (text.startswith("[") and text.endswith("]")):
                return value
            try:
                parsed = ast.literal_eval(text)
            except (ValueError, SyntaxError):
                return value
            if not isinstance(parsed, list):
                return value
            cleaned = "、".join(str(item).strip() for item in parsed if str(item).strip())
            prefix = " " if value.startswith(" ") else ""
            suffix = " " if value.endswith(" ") else ""
            return f"{prefix}{cleaned}{suffix}"

        def repl(match: re.Match) -> str:
            cells = [clean_literal(cell) for cell in match.group(0).split("|")]
            return "|".join(cells)

        return re.sub(r"(?m)^\|.*\|$", repl, markdown_text or "").rstrip() + "\n"

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
    def remove_empty_sections(srs_md: str) -> str:
        text = str(srs_md or "")

        def is_placeholder_body(body: str) -> bool:
            cleaned = re.sub(r"<!--.*?-->", "", body or "", flags=re.DOTALL)
            cleaned = re.sub(r"(?m)^\s*[-*+]\s*", "", cleaned)
            cleaned = re.sub(r"[（）()]", "", cleaned).strip()
            if not cleaned:
                return True
            if re.fullmatch(r"(?:無|無。|無\.|N/?A|n/?a)", cleaned):
                return True
            return bool(
                re.search(
                    r"(?:本草稿|本文件|目前)?(?:未明確列出|未列出|沒有|無).{0,40}(?:本節省略|故本節省略)",
                    cleaned,
                )
                or re.search(r"本節省略", cleaned)
            )

        def remove_empty_requirement_group(match: re.Match) -> str:
            heading = match.group("heading")
            body = match.group("body")
            has_requirement = bool(re.search(r"(?m)^####\s+(?:FR|NFR)-\d+\b", body))
            if has_requirement:
                return match.group(0).rstrip() + "\n\n"
            if is_placeholder_body(body):
                return ""
            return match.group(0)

        text = re.sub(
            r"(?ms)^(?P<heading>###\s+(?:功能性需求|非功能性需求)\s*)\n+(?P<body>.*?)(?=^###\s+|^##\s+|\Z)",
            remove_empty_requirement_group,
            text,
        )

        def remove_empty_top_section(match: re.Match) -> str:
            heading = match.group("heading")
            body = match.group("body")
            if is_placeholder_body(body):
                return ""
            return f"{heading.rstrip()}\n\n{body.strip()}\n\n"

        text = re.sub(
            r"(?ms)^(?P<heading>##\s+系統限制\s*)\n+(?P<body>.*?)(?=^##\s+|\Z)",
            remove_empty_top_section,
            text,
        )

        def remove_empty_requirement_section(match: re.Match) -> str:
            heading = match.group("heading")
            body = match.group("body").strip()
            if not body:
                return ""
            if not re.search(r"(?m)^###\s+(?:功能性需求|非功能性需求)\s*$", body):
                return ""
            return f"{heading.rstrip()}\n\n{body}\n\n"

        text = re.sub(
            r"(?ms)^(?P<heading>##\s+需求\s*)\n+(?P<body>.*?)(?=^##\s+|\Z)",
            remove_empty_requirement_section,
            text,
        )
        return re.sub(r"\n{3,}", "\n\n", text).rstrip() + "\n"

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
        draft_md = self.normalize_serialized_list_cells(draft_md)
        prompt = generate_srs(draft_md=draft_md)
        action = self.usage_action("documentor.generate_srs")
        last_error: Optional[ValueError] = None
        srs_md = ""
        for attempt in range(2):
            task = prompt if attempt == 0 else self.retry_srs_prompt(prompt, last_error or ValueError("invalid SRS format"))
            srs_md = self.model.chat(
                self.build_direct_messages(task),
                action=action,
            )
            srs_md = clean_llm_output(srs_md)
            try:
                self.validate_srs_new_format(srs_md)
                break
            except ValueError as exc:
                last_error = exc
                if attempt == 1:
                    raise
        srs_md = self.restore_model_heading_ids(srs_md, draft_md)
        srs_md = self.fix_model_links(srs_md)
        srs_md = self.fix_model_image_filenames(srs_md)
        srs_md = normalize_model_image_markdown(srs_md)
        srs_md = self.normalize_scope_headings(srs_md)
        srs_md = self.normalize_system_purpose_paragraph(srs_md)
        srs_md = self.restore_appendix_heading(srs_md)
        srs_md = self.remove_empty_sections(srs_md)
        srs_md = self.insert_design_rationale_links(srs_md)
        srs_md = self.normalize_requirement_field_spacing(srs_md)
        srs_md = self.normalize_model_description_labels(srs_md)
        srs_md = self.normalize_serialized_list_cells(srs_md)
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
