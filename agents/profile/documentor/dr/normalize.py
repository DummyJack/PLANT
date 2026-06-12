# Normalizes Design Rationale markdown output.
import re
from typing import Any, Dict, List


class DocumentorDrNormalize:
    @staticmethod
    def validate_design_rationale_block(block: str) -> None:
        text = str(block or "")
        if re.search(r"(?m)^#{1,6}\s*REQ-\d+\s*[:：]", text):
            raise ValueError("design rationale output uses old REQ-* block headings")
        if re.search(r"(?im)^#{1,6}\s*(?:Source|Decision|Rationale|Impact|Context)\s*$", text):
            raise ValueError("design rationale output contains old section headings")
        if re.search(r"(?im)^\*\*(?:Type|Source|Context|Decision|Rationale|Impact|SRS ID)\*\*\s*[:：]", text):
            raise ValueError("design rationale output contains old metadata fields")

    @staticmethod
    def extract_design_rationale_trace(block: str) -> str:
        text = str(block or "").strip()
        text = re.sub(r"(?m)^#{1,6}\s*(?:FR|NFR|CON)-\d+\s*[:：].*$", "", text)
        text = re.sub(r"(?m)^(?:FR|NFR|CON)-\d+\s*[:：].*$", "", text)
        text = re.sub(r"(?m)^\*\*Description\*\*\s*[:：].*$", "", text)
        text = re.sub(r"(?m)^Description\s*[:：].*$", "", text)
        text = re.sub(r"(?m)^#{1,6}\s*Trace(?:\s+Explanation)?(?:\s*\{[^}]*\})?\s*$", "", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    @staticmethod
    def normalize_trace_explanation(trace: str, description: str) -> str:
        text = str(trace or "").strip()
        description_text = str(description or "").strip()
        if description_text:
            escaped_description = re.escape(description_text)
            text = re.sub(
                rf"(?m)^\s*(?:\*\*Description\*\*\s*[:：]\s*|Description\s*[:：]\s*)?{escaped_description}\s*$\n?",
                "",
                text,
            ).strip()

        title_map = {
            "Stakeholder": "Stakeholder",
            "User Requirement": "User Requirement",
            "Conflict": "Conflict",
            "Feedback": "Feedback",
            "System Model": "System Model",
            "Meeting Discussion": "Meeting Discussion",
            "Requirement Formation": "Requirement Formation",
        }
        normalized_heading_map = {
            "Stakeholder": "Stakeholder",
            "User Requirement": "User Requirement",
            "Conflict": "Conflict",
            "Feedback": "Feedback",
            "System Model": "System Model",
            "Meeting Discussion": "Meeting Discussion",
            "Requirement Formation": "Requirement Formation",
            "利害關係人來源": "Stakeholder",
            "使用者需求": "User Requirement",
            "衝突辨識": "Conflict",
            "需求衝突": "Conflict",
            "領域研究": "Feedback",
            "系統模型": "System Model",
            "會議討論": "Meeting Discussion",
            "需求形成": "Requirement Formation",
        }
        trace_titles = tuple(title_map.keys())

        def append_bullet(rows: List[str], value: str) -> None:
            content = re.sub(r"^\s*[-*]\s+", "", str(value or "").strip())
            if not content:
                return
            rows.append(f"- {content}")

        lines = text.splitlines()
        normalized: List[str] = []
        in_trace_section = False
        for line in lines:
            stripped = line.strip()
            numbered_match = re.match(r"^(\s*)(?:#{1,6}\s*)?(\d+)\.\s+(.+)$", line)
            if numbered_match:
                rest = numbered_match.group(3).strip()
                bold_match = re.match(r"^\*\*([^*]+)\*\*\s*(.*)$", rest)
                if bold_match:
                    title = re.sub(r"\s+", " ", bold_match.group(1)).strip()
                    tail = bold_match.group(2).strip()
                else:
                    title = ""
                    tail = ""
                    for candidate in trace_titles:
                        if rest == candidate or rest.startswith(candidate + " "):
                            title = candidate
                            tail = rest[len(candidate):].strip()
                            break
                if title:
                    in_trace_section = True
                    if normalized and normalized[-1].strip():
                        normalized.append("")
                    normalized.append(title_map[title])
                    if tail:
                        append_bullet(normalized, tail)
                    continue

            heading_match = re.match(r"^#{1,6}\s+(.+?)\s*$", stripped)
            if heading_match:
                heading = re.sub(r"\s+", " ", heading_match.group(1)).strip()
                heading = re.sub(r"^\d+\.\s+", "", heading)
                mapped = normalized_heading_map.get(heading)
                if mapped:
                    in_trace_section = True
                    if normalized and normalized[-1].strip():
                        normalized.append("")
                    normalized.append(mapped)
                    continue
                in_trace_section = False
                normalized.append(line)
                continue

            if in_trace_section:
                bullet_match = re.match(r"^(\s*)[-*]\s+(.+)$", line)
                if bullet_match:
                    append_bullet(normalized, bullet_match.group(2))
                    continue
                if stripped and re.match(r"^(?:#{1,6}\s+|---\s*$)", stripped):
                    in_trace_section = False
                    normalized.append(line)
                    continue
                if stripped:
                    append_bullet(normalized, stripped)
                    continue
            normalized.append(line)

        out = re.sub(r"\n{3,}", "\n\n", "\n".join(normalized)).strip()
        return re.sub(r"\n{3,}", "\n\n", out).strip()

    @classmethod
    def normalize_design_rationale_body(
        cls,
        body: str,
        requirements: List[Dict[str, Any]],
    ) -> str:
        raw_body = str(body or "").strip()
        if re.search(r"(?m)^#{1,6}\s*REQ-\d+\s*[:：]", raw_body):
            raise ValueError("design rationale output uses old REQ-* block headings")
        if not re.search(r"(?m)^#{1,6}\s*(?:FR|NFR|CON)-\d+\s*[:：]", raw_body):
            raise ValueError("design rationale output must use FR/NFR/CON block headings")
        blocks = [
            block.strip()
            for block in re.split(
                r"(?m)(?=^#{1,6}\s*(?:FR|NFR|CON)-\d+\s*[:：])",
                raw_body,
            )
            if block.strip()
        ]
        block_by_id: Dict[str, str] = {}
        for block in blocks:
            cls.validate_design_rationale_block(block)
            match = re.search(r"(?m)^#{1,6}\s*((?:FR|NFR|CON)-\d+)\s*[:：]", block)
            if match:
                block_by_id[match.group(1)] = block

        normalized: List[str] = []
        ordered_requirements = sorted(requirements, key=cls.dr_srs_order_key)
        for req in ordered_requirements:
            req_id = str(req.get("id") or "").strip()
            title = str(req.get("title") or "").strip()
            description = str(req.get("description") or "").strip()
            srs_id = str(req.get("srs_id") or "").strip()
            if not req_id:
                continue
            block = block_by_id.get(srs_id) or ""
            if not block:
                raise ValueError(f"design rationale output missing block for {srs_id}")
            trace = cls.extract_design_rationale_trace(block)
            trace = cls.normalize_trace_explanation(trace, description)
            header = [
                f"### {srs_id}: {title}".rstrip(),
                "",
                f"**Description**: {description}  ",
                "",
                "#### Trace Explanation",
            ]
            normalized.append("\n".join(header).strip() + ("\n\n" + trace if trace else ""))
        return "\n\n---\n\n".join(normalized).strip()

    @staticmethod
    def normalize_design_rationale_links(markdown: str) -> str:
        text = str(markdown or "")
        id_patterns = (
            r"ST-\d+(?:-\d+)?",
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
        text = re.sub(rf"(?<!\!)\[({label_pattern})\]\(#[^)]+\)", r"\1", text)
        text = re.sub(rf"\[({label_pattern})\]\(#\)", r"\1", text)
        return text

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
    def remove_design_rationale_appendix_refs(markdown: str) -> str:
        text = str(markdown or "")
        link_pattern = re.compile(r"\[((?:ST|URL|CR|FB|SM|REQ|FR|NFR|CON)-\d+|R\d+-M\d+)\]\(#[^)]+\)")
        appendix_ref_pattern = re.compile(
            r"[（(](?:見|參考)\s*Appendix\s+"
            r"(?P<links>\[(?:(?:ST|URL|CR|FB|SM|REQ|FR|NFR|CON)-\d+|R\d+-M\d+)\]\(#[^)]+\)"
            r"(?:[、,，]\s*\[(?:(?:ST|URL|CR|FB|SM|REQ|FR|NFR|CON)-\d+|R\d+-M\d+)\]\(#[^)]+\))*)"
            r"[）)]"
        )

        def normalize_ids(segment: str) -> List[str]:
            return [match.group(1) for match in link_pattern.finditer(segment)]

        def clean_line(line: str) -> str:
            result = line
            while True:
                match = appendix_ref_pattern.search(result)
                if not match:
                    return result
                appendix_ids = normalize_ids(match.group("links"))
                prefix_ids = normalize_ids(result[: match.start()])
                if appendix_ids and all(item in prefix_ids for item in appendix_ids):
                    result = (result[: match.start()] + result[match.end() :]).rstrip()
                    continue
                return result

        text = "\n".join(clean_line(line) for line in text.splitlines())
        text = re.sub(r"[（(](?:見|參考)\s*Appendix\s*[^）)]*[）)]", "", text)
        return text

    @staticmethod
    def normalize_horizontal_rules(markdown: str) -> str:
        text = str(markdown or "")
        return re.sub(r"(?m)(^---\s*$)(?:\s*^---\s*$)+", r"\1", text)
