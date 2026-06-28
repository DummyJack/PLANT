# Normalizes Design Rationale markdown output.
import re
from typing import Any, Dict, List


class DocumentorDrNormalize:
    @staticmethod
    def _trace_natural_key(value: Any) -> tuple[int, int, int, str]:
        text = str(value or "")
        match = re.search(r"([A-Za-z]+)-(\d+)(?:-M?(\d+))?", text)
        if not match:
            return (999, 999, 999, text)
        group_order = {
            "ST": 1,
            "elicit": 1,
            "URL": 2,
            "CR": 3,
            "FB": 4,
            "SM": 5,
            "R": 6,
            "FR": 7,
            "NFR": 7,
            "CON": 7,
        }.get(match.group(1), 99)
        return (
            group_order,
            int(match.group(2) or 0),
            int(match.group(3) or 0),
            text,
        )

    @staticmethod
    def _strip_trace_html(value: Any) -> str:
        text = str(value or "")
        text = re.sub(r"(?is)<br\s*/?>", "，", text)
        text = re.sub(r"(?is)</(?:p|li|h[1-6]|div|tr)>", "。", text)
        text = re.sub(r"(?is)<[^>]+>", "", text)
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"&lt;", "<", text)
        text = re.sub(r"&gt;", ">", text)
        text = re.sub(r"&amp;", "&", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _truncate_trace_text(raw: Any, max_len: int) -> str:
        text = str(raw or "").strip()
        if max_len <= 0 or len(text) <= max_len:
            return text
        sentences = re.findall(r"[^。；;.!?！？]+[。；;.!?！？]?", text)
        selected: List[str] = []
        total = 0
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if selected and total + len(sentence) > max_len:
                break
            if not selected and len(sentence) > max_len:
                boundary = max(
                    sentence.rfind("，", 0, max_len),
                    sentence.rfind("、", 0, max_len),
                    sentence.rfind(",", 0, max_len),
                    sentence.rfind(" ", 0, max_len),
                )
                if boundary >= max_len // 2:
                    sentence = sentence[:boundary]
                else:
                    sentence = sentence[:max_len]
                sentence = sentence.rstrip(" ，、,。；;.!?！？")
                if sentence and re.search(r"[\u4e00-\u9fff]$", sentence):
                    sentence += "。"
                selected.append(sentence)
                break
            selected.append(sentence)
            total += len(sentence)
        summary = "".join(selected).strip()
        return summary or text[:max_len].rstrip(" ，、,。；;.!?！？")

    @classmethod
    def _trace_node_summary(cls, node: Dict[str, Any], node_id: str = "", max_len: int = 220) -> str:
        raw = cls._strip_trace_html(node.get("content") or node.get("label") or node.get("title") or "")
        if node_id:
            raw = re.sub(rf"^{re.escape(node_id)}\s*[：:]\s*", "", raw)
        raw = re.sub(r"^(?:發言|需求|決議|摘要)\s*[：:]\s*", "", raw)
        raw = raw.strip(" 。，")
        return cls._truncate_trace_text(raw, max_len) if raw else ""

    @classmethod
    def _trace_meeting_summary(cls, node: Dict[str, Any], node_id: str = "", max_len: int = 700) -> str:
        html = str((node or {}).get("content") or "")
        parts: List[str] = []
        for title in ("摘要", "決議"):
            match = re.search(rf"(?is)<h2[^>]*>{re.escape(title)}</h2>\s*<p[^>]*>(.*?)</p>", html)
            if match:
                value = cls._strip_trace_html(match.group(1)).strip(" 。，")
                if value:
                    parts.append(f"{title}：{value}")
        if parts:
            return cls._truncate_trace_text("；".join(parts), max_len)
        return cls._trace_node_summary(node or {}, node_id, min(max_len, 360))

    @staticmethod
    def collapse_design_rationale_separators(markdown: str) -> str:
        text = str(markdown or "")
        text = re.sub(r"(?m)^\s*---\s*$", "---", text)
        text = re.sub(
            r"(?m)(^#{1,6}\s*(?:FR|NFR|CON)-\d+\s*[:：])",
            lambda match: "\n\n" + match.group(1),
            text,
        )
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def validate_design_rationale_block(block: str) -> None:
        text = str(block or "")
        if re.search(r"(?m)^#{1,6}\s*REQ-\d+\s*[:：]", text):
            raise ValueError("design rationale output uses old REQ-* block headings")
        if re.search(r"(?im)^#{1,6}\s*(?:Source|Decision|Rationale|Impact|Context)\s*$", text):
            raise ValueError("design rationale output contains old section headings")
        if re.search(r"(?im)^\*\*(?:Type|Source|Context|Decision|Rationale|Impact|SRS ID)\*\*\s*[:：]", text):
            raise ValueError("design rationale output contains old metadata fields")
        if re.search(r"(?im)^Description\s*[:：]", text):
            raise ValueError("design rationale output contains old unbolded Description field")

    @staticmethod
    def extract_design_rationale_trace(block: str) -> str:
        text = str(block or "").strip()
        text = re.sub(r"(?m)^#{1,6}\s*(?:FR|NFR|CON)-\d+\s*[:：].*$", "", text)
        text = re.sub(r"(?m)^(?:FR|NFR|CON)-\d+\s*[:：].*$", "", text)
        text = re.sub(r"(?m)^\*\*Description\*\*\s*[:：].*$", "", text)
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
        trace_title_pattern = "|".join(re.escape(title) for title in trace_titles)
        text = re.sub(
            rf"(?<!^)(?<!\n)({trace_title_pattern})(?=\n\s*[-*]\s+)",
            r"\n\n\1",
            text,
        )

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
            plain_mapped = normalized_heading_map.get(re.sub(r"\s+", " ", stripped))
            if plain_mapped:
                in_trace_section = True
                if normalized and normalized[-1].strip():
                    normalized.append("")
                normalized.append(plain_mapped)
                continue
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

    @staticmethod
    def normalize_trace_explanation_ids(trace: str, requirement: Dict[str, Any]) -> str:
        text = str(trace or "")
        graph = requirement.get("trace_graph") if isinstance(requirement.get("trace_graph"), dict) else {}
        replacements: Dict[str, str] = {}
        feedback_group_ids: List[str] = []
        for node in graph.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id") or "").strip()
            if not node_id:
                continue
            if str(node.get("type") or "").strip() == "Stakeholder Statement":
                label = str(node.get("label") or "").strip()
                canonical_id = label.split()[0] if label else node_id
                if not canonical_id:
                    continue
                if node_id != canonical_id:
                    replacements[node_id] = canonical_id
                if node_id.startswith("elicit-"):
                    match = re.fullmatch(r"elicit-(\d+)-(\d+)", node_id)
                    if match:
                        replacements[f"ST-{match.group(1)}-{match.group(2)}"] = node_id
            if node_id.startswith("FB-GROUP-"):
                grouped_ids = [
                    str(grouped_id or "").strip()
                    for grouped_id in (node.get("grouped_ids") or [])
                    if str(grouped_id or "").strip()
                ]
                display = "、".join(grouped_ids) if grouped_ids else "Feedback"
                replacements[node_id] = display
                if grouped_ids:
                    feedback_group_ids = grouped_ids

        for old_id, new_id in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
            text = re.sub(rf"(?<![A-Za-z0-9_-]){re.escape(old_id)}(?![A-Za-z0-9_-])", new_id, text)
        if feedback_group_ids:
            full_group_display = "、".join(feedback_group_ids)

            def normalize_feedback_section(match: re.Match[str]) -> str:
                section = match.group(0)
                lines = section.splitlines()
                occurrence_index = 0
                normalized_lines: List[str] = []
                for line in lines:
                    stripped = line.lstrip()
                    prefix = line[: len(line) - len(stripped)]
                    if not stripped.startswith("- "):
                        normalized_lines.append(line)
                        continue
                    content = stripped[2:].strip()
                    if re.match(r"^Feedback（\d+\s*筆）\b", content):
                        replacement = (
                            feedback_group_ids[occurrence_index]
                            if occurrence_index < len(feedback_group_ids)
                            else full_group_display
                        )
                        content = re.sub(r"^Feedback（\d+\s*筆）", replacement, content, count=1)
                        occurrence_index += 1
                    elif content.startswith(full_group_display):
                        replacement = (
                            feedback_group_ids[occurrence_index]
                            if occurrence_index < len(feedback_group_ids)
                            else full_group_display
                        )
                        content = replacement + content[len(full_group_display):]
                        occurrence_index += 1
                    normalized_lines.append(prefix + "- " + content)
                return "\n".join(normalized_lines)

            text = re.sub(
                r"(?ms)^Feedback\s*\n.*?(?=^(?:Stakeholder|User Requirement|Conflict|System Model|Meeting Discussion|Requirement Formation)\s*$|\Z)",
                normalize_feedback_section,
                text,
            )
            text = re.sub(r"Feedback（\d+\s*筆）", full_group_display, text)
        text = re.sub(
            r"\b(FB-\d+)(?:[、,，]\s*\1)+",
            r"\1",
            text,
        )
        return text

    @staticmethod
    def ensure_trace_explanation_meetings(trace: str, requirement: Dict[str, Any]) -> str:
        text = str(trace or "").strip()
        graph = requirement.get("trace_graph") if isinstance(requirement.get("trace_graph"), dict) else {}
        nodes = [node for node in (graph.get("nodes") or []) if isinstance(node, dict)]
        edges = [edge for edge in (graph.get("edges") or []) if isinstance(edge, dict)]
        display_by_id: Dict[str, str] = {}
        for node in nodes:
            node_id = str(node.get("id") or "").strip()
            if not node_id.startswith("FB-GROUP-"):
                continue
            grouped_ids = [
                str(grouped_id or "").strip()
                for grouped_id in (node.get("grouped_ids") or [])
                if str(grouped_id or "").strip()
            ]
            display_by_id[node_id] = "、".join(grouped_ids) if grouped_ids else "Feedback"
        meeting_ids = [
            str(node.get("id") or "").strip()
            for node in nodes
            if str(node.get("type") or "").strip() == "Meeting Discussion"
            and str(node.get("id") or "").strip()
        ]
        if not meeting_ids:
            return text

        def order_key(value: str) -> tuple[int, int, str]:
            match = re.fullmatch(r"R(\d+)-M(\d+)", value)
            if not match:
                return (999, 999, value)
            return (int(match.group(1)), int(match.group(2)), value)

        def visible_id(value: Any) -> str:
            node_id = str(value or "").strip()
            return display_by_id.get(node_id, node_id)

        def format_ids(values: List[str]) -> str:
            unique = [item for item in dict.fromkeys(values) if item]
            if not unique:
                return "前述 trace 節點"
            if len(unique) <= 3:
                return "、".join(unique)
            return "、".join(unique[:3]) + f" 等 {len(unique)} 個節點"

        existing_ids = set(
            re.findall(
                r"\bR\d+-M\d+\b",
                text,
            )
        )
        missing_meeting_ids = [meeting_id for meeting_id in sorted(meeting_ids, key=order_key) if meeting_id not in existing_ids]
        if not missing_meeting_ids:
            return text

        bullets: List[str] = []
        for meeting_id in missing_meeting_ids:
            incoming = [
                edge for edge in edges
                if visible_id(edge.get("to")) == meeting_id
            ]
            outgoing = [
                edge for edge in edges
                if visible_id(edge.get("from")) == meeting_id
            ]
            source_ids = [visible_id(edge.get("from")) for edge in incoming]
            target_ids = [visible_id(edge.get("to")) for edge in outgoing]
            relations = [
                visible_id(edge.get("relation"))
                for edge in incoming + outgoing
                if visible_id(edge.get("relation"))
            ]
            relation_text = "、".join(dict.fromkeys(relations)) if relations else "會議討論"
            bullets.append(
                f"- {meeting_id} 承接 {format_ids(source_ids)} 的{relation_text}，"
                f"並推進到 {format_ids(target_ids)}。"
            )

        section = "Meeting Discussion\n" + "\n".join(bullets)
        if re.search(r"(?m)^Meeting Discussion\s*$", text):
            return re.sub(
                r"(?m)^Meeting Discussion\s*$",
                lambda match: match.group(0) + "\n" + "\n".join(bullets),
                text,
                count=1,
            )
        return text.rstrip() + "\n\n" + section

    @classmethod
    def clarify_trace_explanation_meetings(cls, trace: str, requirement: Dict[str, Any]) -> str:
        text = str(trace or "").strip()
        graph = requirement.get("trace_graph") if isinstance(requirement.get("trace_graph"), dict) else {}
        nodes = [node for node in (graph.get("nodes") or []) if isinstance(node, dict)]
        edges = [edge for edge in (graph.get("edges") or []) if isinstance(edge, dict)]
        if not text or not nodes:
            return text

        node_by_id = {
            str(node.get("id") or "").strip(): node
            for node in nodes
            if str(node.get("id") or "").strip()
        }
        meeting_ids = [
            node_id
            for node_id, node in node_by_id.items()
            if str(node.get("type") or "").strip() == "Meeting Discussion"
        ]
        if not meeting_ids:
            return text

        def node_type(node_id: Any) -> str:
            return str((node_by_id.get(str(node_id or "").strip()) or {}).get("type") or "").strip()

        def edge_from(edge: Dict[str, Any]) -> str:
            return str(edge.get("from") or "").strip()

        def edge_to(edge: Dict[str, Any]) -> str:
            return str(edge.get("to") or "").strip()

        def relation(edge: Dict[str, Any]) -> str:
            return str(edge.get("relation") or "").strip()

        def visible_id(value: Any) -> str:
            node_id = str(value or "").strip()
            node = node_by_id.get(node_id) or {}
            if node_id.startswith("FB-GROUP-"):
                grouped_ids = [
                    str(grouped_id or "").strip()
                    for grouped_id in (node.get("grouped_ids") or [])
                    if str(grouped_id or "").strip()
                ]
                return "、".join(grouped_ids) if grouped_ids else "Feedback"
            return node_id

        def format_ids(values: List[str], limit: int = 8) -> str:
            expanded: List[str] = []
            for value in values:
                display = visible_id(value)
                if not display:
                    continue
                expanded.extend(part for part in display.split("、") if part)
            unique = list(dict.fromkeys(expanded))
            if not unique:
                return "前述節點"
            if len(unique) <= limit:
                return "、".join(unique)
            return "、".join(unique[:limit]) + f" 等 {len(unique)} 個節點"

        incoming_by_meeting: Dict[str, List[Dict[str, Any]]] = {meeting_id: [] for meeting_id in meeting_ids}
        outgoing_by_meeting: Dict[str, List[Dict[str, Any]]] = {meeting_id: [] for meeting_id in meeting_ids}
        for edge in edges:
            to_id = edge_to(edge)
            from_id = edge_from(edge)
            if to_id in incoming_by_meeting:
                incoming_by_meeting[to_id].append(edge)
            if from_id in outgoing_by_meeting:
                outgoing_by_meeting[from_id].append(edge)

        def meeting_purpose(meeting_id: str, incoming: List[Dict[str, Any]], outgoing: List[Dict[str, Any]]) -> str:
            incoming_relations = {relation(edge) for edge in incoming}
            incoming_source_types = {node_type(edge_from(edge)) for edge in incoming}
            if "解決" in incoming_relations or "Conflict" in incoming_source_types:
                return "衝突解決"
            if "正式化" in incoming_relations:
                return "需求正式化"
            if "精練" in incoming_relations:
                return "需求精練"
            if any(relation(edge) == "精練" for edge in outgoing):
                return "模型對齊確認"
            if any(edge_to(edge) == str(requirement.get("srs_id") or "").strip() for edge in outgoing):
                return "最終確認"
            return "會議討論"

        def meeting_effect(meeting_id: str, outgoing: List[Dict[str, Any]]) -> str:
            if not outgoing:
                return "作為後續需求判斷的會議紀錄"
            target_id = str(requirement.get("srs_id") or "").strip()
            meeting_targets = [edge_to(edge) for edge in outgoing if node_type(edge_to(edge)) == "Meeting Discussion"]
            final_targets = [edge_to(edge) for edge in outgoing if edge_to(edge) == target_id]
            other_targets = [
                edge_to(edge)
                for edge in outgoing
                if edge_to(edge) not in set(meeting_targets + final_targets)
            ]
            effects: List[str] = []
            if meeting_targets:
                relation_texts = [relation(edge) for edge in outgoing if edge_to(edge) in meeting_targets and relation(edge)]
                relation_label = "、".join(dict.fromkeys(relation_texts)) if relation_texts else "下一階段"
                effects.append(f"推進到 {format_ids(sorted(meeting_targets, key=cls._trace_natural_key))} 的{relation_label}處理")
            if final_targets:
                effects.append(f"收斂為 {format_ids(final_targets)}")
            if other_targets:
                effects.append(f"連到 {format_ids(sorted(other_targets, key=cls._trace_natural_key))}")
            return "，並".join(effects) if effects else "作為後續需求判斷的會議紀錄"

        def heading_sections(html: str) -> List[Dict[str, Any]]:
            content = str(html or "")
            headings = [
                {
                    "level": int(match.group(1)),
                    "title": cls._strip_trace_html(match.group(2)).strip(),
                    "start": match.start(),
                    "end": match.end(),
                }
                for match in re.finditer(r"(?is)<h([2-6])[^>]*>(.*?)</h\1>", content)
            ]
            sections: List[Dict[str, Any]] = []
            for index, heading in enumerate(headings):
                next_start = len(content)
                for next_heading in headings[index + 1:]:
                    if int(next_heading["level"]) <= int(heading["level"]):
                        next_start = int(next_heading["start"])
                        break
                body = cls._strip_trace_html(content[int(heading["end"]):next_start]).strip(" 。，")
                text_value = (str(heading["title"]) + (" " + body if body else "")).strip()
                if text_value:
                    sections.append({**heading, "text": text_value})
            return sections

        def section_for_focus_ids(meeting_id: str, focus_ids: List[str]) -> str:
            node = node_by_id.get(meeting_id) or {}
            sections = heading_sections(str(node.get("content") or ""))
            if not sections:
                return ""
            primary_focus_ids = {
                str(requirement.get("id") or "").strip(),
                str(requirement.get("srs_id") or "").strip(),
            }
            clean_focus_ids = [
                focus_id for focus_id in dict.fromkeys(str(item or "").strip() for item in focus_ids)
                if focus_id
            ]
            matched: List[str] = []
            full_text = cls._strip_trace_html(str(node.get("content") or ""))
            for focus_id in clean_focus_ids:
                exact_title_matches = [
                    section["text"]
                    for section in sections
                    if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(focus_id)}(?![A-Za-z0-9_-])", str(section.get("title") or ""))
                ]
                if exact_title_matches:
                    value = str(exact_title_matches[0])
                    if focus_id in primary_focus_ids:
                        return cls._truncate_trace_text(value, 520)
                    matched.append(value)
                    if len(matched) >= 2:
                        break
                    continue
                if focus_id in primary_focus_ids:
                    match = re.search(rf"(?<![A-Za-z0-9_-]){re.escape(focus_id)}(?![A-Za-z0-9_-])", full_text)
                    if match:
                        start = max(0, match.start() - 180)
                        end = min(len(full_text), match.end() + 360)
                        return cls._truncate_trace_text(full_text[start:end].strip(" ，。；"), 520)
                body_matches = [
                    section["text"]
                    for section in sections
                    if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(focus_id)}(?![A-Za-z0-9_-])", str(section.get("text") or ""))
                    and str(section.get("title") or "") not in {"摘要", "決議", "模型更新"}
                ]
                if body_matches:
                    matched.append(str(body_matches[0]))
                if len(matched) >= 2:
                    break
            if matched:
                return cls._truncate_trace_text("；".join(dict.fromkeys(matched)), 520)

            for focus_id in clean_focus_ids:
                match = re.search(rf"(?<![A-Za-z0-9_-]){re.escape(focus_id)}(?![A-Za-z0-9_-])", full_text)
                if not match:
                    continue
                start = max(0, match.start() - 180)
                end = min(len(full_text), match.end() + 420)
                snippet = full_text[start:end].strip(" ，。；")
                return cls._truncate_trace_text(snippet, 620)
            return ""

        all_conflict_ids = [
            node_id
            for node_id, node in node_by_id.items()
            if str(node.get("type") or "").strip() == "Conflict"
        ]
        target_focus_ids = [
            str(requirement.get("id") or "").strip(),
            str(requirement.get("srs_id") or "").strip(),
            *all_conflict_ids,
        ]
        requirement_id = str(requirement.get("id") or "").strip()
        requirement_srs_id = str(requirement.get("srs_id") or "").strip()
        requirement_description = str(requirement.get("description") or "").strip()
        acceptance_criteria = [
            str(item or "").strip()
            for item in (requirement.get("acceptance_criteria") or [])
            if str(item or "").strip()
        ]
        model_ids = [
            node_id
            for node_id, node in node_by_id.items()
            if str(node.get("type") or "").strip() == "System Model"
        ]

        def clean_meeting_excerpt(value: str, max_len: int = 360) -> str:
            text_value = re.sub(r"\s+", " ", str(value or "")).strip(" 。，")
            text_value = re.sub(r"([。！？])。+", r"\1", text_value)
            text_value = re.sub(r"\b(?:平台營運管理者|餐廳商家|消費者|外送員|Analyst|analyst|modeler|expert)\s*[。:：]\s*", "", text_value)
            text_value = re.sub(r"類型:\s*\w+\s*[。．]?\s*", "", text_value)
            return cls._truncate_trace_text(text_value, max_len)

        def conflict_resolution_summary(source_ids: List[str]) -> str:
            rows: List[str] = []
            for source_id in source_ids:
                if node_type(source_id) != "Conflict":
                    continue
                node = node_by_id.get(source_id) or {}
                html = str(node.get("content") or "")
                selected = ""
                for title in ("建議解法", "解決選項", "衝突描述"):
                    match = re.search(rf"(?is)<h3[^>]*>{re.escape(title)}</h3>\s*<p[^>]*>(.*?)</p>", html)
                    if match:
                        selected = cls._strip_trace_html(match.group(1)).strip(" 。，")
                        break
                if not selected:
                    selected = cls._trace_node_summary(node, source_id, 260)
                if selected:
                    rows.append(f"{source_id}：{selected}")
            return cls._truncate_trace_text("；".join(rows), 360)

        def meeting_decision_text(
            *,
            purpose: str,
            source_ids: List[str],
            summary: str,
        ) -> str:
            clean_summary = clean_meeting_excerpt(summary)
            target_name = requirement_srs_id or requirement_id
            req_name = requirement_id if requirement_id and requirement_id != target_name else target_name
            if purpose == "衝突解決":
                conflict_summary = conflict_resolution_summary(source_ids)
                if conflict_summary:
                    return (
                        f"{purpose}階段把 {format_ids(source_ids)} 中與 {target_name} 相關的分歧收斂成可正式化的決策："
                        f"{conflict_summary}。這一步說明正式需求必須採用該解法中的條件、責任、例外處理或資訊揭露規則"
                    )
                if clean_summary:
                    return (
                        f"{purpose}階段把 {format_ids(source_ids)} 中與 {target_name} 相關的分歧收斂成可正式化的決策："
                        f"{clean_summary}。這一步決定後續條文必須保留責任區分、例外/異議處理與紀錄可查等要點"
                    )
                return (
                    f"{purpose}階段把 {format_ids(source_ids)} 中與 {target_name} 相關的分歧收斂成可正式化的決策，"
                    "讓後續會議可以把衝突結果寫入需求條文"
                )
            if purpose == "需求正式化":
                ac_text = ""
                if acceptance_criteria:
                    ac_text = "驗收重點是" + "、".join(item.rstrip("。") for item in acceptance_criteria[:3])
                formalized = (
                    f"{purpose}階段將正式化依據寫成 {req_name}/{target_name}："
                    f"{requirement_description.rstrip('。')}"
                )
                if ac_text:
                    formalized += f"；{ac_text}"
                return formalized
            if purpose in {"需求精練", "最終確認", "模型對齊確認"}:
                model_text = f"，並確認與 {format_ids(model_ids, limit=5)} 的模型支撐一致" if model_ids else ""
                return (
                    f"{purpose}階段沒有重新改寫 {target_name} 的需求語意，而是確認 {req_name} 的條文、驗收條件與追蹤關係已可支撐正式 SRS{model_text}"
                )
            if clean_summary:
                return f"此會議針對 {target_name} 補充確認：{clean_summary}"
            return f"此會議承接前述節點，確認 {target_name} 可繼續推進"

        def meeting_intro_text(
            *,
            meeting_id: str,
            purpose: str,
            source_ids: List[str],
        ) -> str:
            source_text = format_ids(source_ids)
            if purpose == "衝突解決":
                return f"{meeting_id} 是衝突解決會議，討論輸入為 {source_text}。"
            if purpose == "需求正式化":
                return f"{meeting_id} 是需求正式化會議，正式化依據為 {source_text}。"
            if purpose == "需求精練":
                return f"{meeting_id} 是需求精練會議，承接 {source_text} 的需求版本做更深入討論。"
            if purpose == "模型對齊確認":
                return f"{meeting_id} 是模型對齊確認會議，承接 {source_text} 檢查需求條文、模型與追蹤關係是否一致。"
            if purpose == "最終確認":
                return f"{meeting_id} 是最終確認會議，承接 {source_text} 確認需求已可收斂為正式 SRS。"
            return f"{meeting_id} 是會議討論，承接 {source_text} 釐清此需求的後續處理。"

        bullets: List[str] = []
        for meeting_id in sorted(meeting_ids, key=cls._trace_natural_key):
            incoming = sorted(incoming_by_meeting.get(meeting_id) or [], key=lambda edge: cls._trace_natural_key(edge_from(edge)))
            outgoing = sorted(outgoing_by_meeting.get(meeting_id) or [], key=lambda edge: cls._trace_natural_key(edge_to(edge)))
            source_ids = [edge_from(edge) for edge in incoming]
            purpose = meeting_purpose(meeting_id, incoming, outgoing)
            content_source_ids = [
                source_id for source_id in source_ids
                if node_type(source_id) != "Meeting Discussion"
            ]
            meeting_focus_ids = [
                str(requirement.get("id") or "").strip(),
                str(requirement.get("srs_id") or "").strip(),
                *content_source_ids,
                *target_focus_ids,
            ]
            summary = section_for_focus_ids(meeting_id, meeting_focus_ids)
            if not summary:
                summary = cls._trace_meeting_summary(node_by_id.get(meeting_id) or {}, meeting_id, 620)
            decision_text = meeting_decision_text(
                purpose=purpose,
                source_ids=source_ids,
                summary=summary,
            )
            bullets.append(
                f"- {meeting_intro_text(meeting_id=meeting_id, purpose=purpose, source_ids=source_ids)}"
                f"針對 {requirement_srs_id}，{decision_text}；因此本會議{meeting_effect(meeting_id, outgoing)}。"
            )

        section_order = [
            "Stakeholder",
            "User Requirement",
            "Conflict",
            "Feedback",
            "System Model",
            "Meeting Discussion",
            "Requirement Formation",
        ]
        section_names = set(section_order)
        preface: List[str] = []
        sections: Dict[str, List[str]] = {section: [] for section in section_order}
        current_section = ""
        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            if stripped in section_names:
                current_section = stripped
                continue
            if current_section:
                target = sections[current_section]
                if not stripped and (not target or not target[-1].strip()):
                    continue
                target.append(line)
                continue
            if stripped or preface:
                preface.append(line)

        sections["Meeting Discussion"] = bullets
        rendered: List[str] = []
        if any(line.strip() for line in preface):
            rendered.extend(preface)
            rendered.append("")
        for section in section_order:
            content = sections.get(section) or []
            while content and not content[0].strip():
                content.pop(0)
            while content and not content[-1].strip():
                content.pop()
            if not content:
                continue
            rendered.append(section)
            rendered.extend(content)
            rendered.append("")
        return re.sub(r"\n{3,}", "\n\n", "\n".join(rendered)).strip()

    @staticmethod
    def ensure_trace_explanation_conflicts(trace: str, requirement: Dict[str, Any]) -> str:
        text = str(trace or "").strip()
        conflict_rows = [
            row for row in (requirement.get("conflicts") or [])
            if isinstance(row, dict) and str(row.get("id") or "").strip()
        ]
        if not conflict_rows:
            return text
        existing_ids = set(re.findall(r"\bCR-\d+\b", text))
        missing_rows = [
            row for row in conflict_rows
            if str(row.get("id") or "").strip() not in existing_ids
        ]
        if not missing_rows:
            return text

        bullets: List[str] = []
        for row in missing_rows:
            conflict_id = str(row.get("id") or "").strip()
            related_sources = [
                str(item).strip()
                for item in (row.get("related_user_requirements") or [])
                if str(item).strip()
            ]
            source_text = "、".join(related_sources[:4])
            if len(related_sources) > 4:
                source_text += f" 等 {len(related_sources)} 個 URL"
            description = str(row.get("description") or "").strip()
            if description:
                bullets.append(f"- {conflict_id} 指出 {source_text or '相關 URL'} 存在衝突：{description}")
            else:
                bullets.append(f"- {conflict_id} 指出 {source_text or '相關 URL'} 存在衝突，需透過會議或正式化決策收斂。")

        section = "Conflict\n" + "\n".join(bullets)
        if re.search(r"(?m)^Conflict\s*$", text):
            return re.sub(
                r"(?m)^Conflict\s*$",
                lambda match: match.group(0) + "\n" + "\n".join(bullets),
                text,
                count=1,
            )
        feedback_match = re.search(r"(?m)^Feedback\s*$", text)
        if feedback_match:
            return text[: feedback_match.start()].rstrip() + "\n\n" + section + "\n\n" + text[feedback_match.start() :].lstrip()
        system_match = re.search(r"(?m)^System Model\s*$", text)
        if system_match:
            return text[: system_match.start()].rstrip() + "\n\n" + section + "\n\n" + text[system_match.start() :].lstrip()
        meeting_match = re.search(r"(?m)^Meeting Discussion\s*$", text)
        if meeting_match:
            return text[: meeting_match.start()].rstrip() + "\n\n" + section + "\n\n" + text[meeting_match.start() :].lstrip()
        return text.rstrip() + "\n\n" + section

    @staticmethod
    def ensure_trace_explanation_topology_coverage(trace: str, requirement: Dict[str, Any]) -> str:
        text = str(trace or "").strip()
        graph = requirement.get("trace_graph") if isinstance(requirement.get("trace_graph"), dict) else {}
        nodes = [node for node in (graph.get("nodes") or []) if isinstance(node, dict)]
        edges = [edge for edge in (graph.get("edges") or []) if isinstance(edge, dict)]
        if not nodes:
            return text

        target_id = str(requirement.get("srs_id") or "").strip()
        node_by_id = {
            str(node.get("id") or "").strip(): node
            for node in nodes
            if str(node.get("id") or "").strip()
        }
        display_by_id: Dict[str, str] = {}
        for node_id, node in node_by_id.items():
            if not node_id.startswith("FB-GROUP-"):
                display_by_id[node_id] = node_id
                continue
            grouped_ids = [
                str(grouped_id or "").strip()
                for grouped_id in (node.get("grouped_ids") or [])
                if str(grouped_id or "").strip()
            ]
            display_by_id[node_id] = "、".join(grouped_ids) if grouped_ids else node_id

        def visible_id(value: Any) -> str:
            node_id = str(value or "").strip()
            return display_by_id.get(node_id, node_id)

        def format_ids(values: List[str]) -> str:
            unique = [visible_id(value) for value in dict.fromkeys(values) if visible_id(value)]
            if not unique:
                return "前述節點"
            if len(unique) <= 6:
                return "、".join(unique)
            return "、".join(unique[:6]) + f" 等 {len(unique)} 個節點"

        def has_id(node_id: str) -> bool:
            display_id = visible_id(node_id)
            if not display_id:
                return True
            if node_id.startswith("FB-GROUP-"):
                return all(
                    re.search(rf"(?<![A-Za-z0-9_-]){re.escape(part)}(?![A-Za-z0-9_-])", text)
                    for part in display_id.split("、")
                    if part
                )
            return bool(re.search(rf"(?<![A-Za-z0-9_-]){re.escape(display_id)}(?![A-Za-z0-9_-])", text))

        def section_for_type(node_type: str) -> str:
            if node_type == "Stakeholder Statement":
                return "Stakeholder"
            if node_type in {"User Requirement", "User Requirement Group"}:
                return "User Requirement"
            if node_type == "Conflict":
                return "Conflict"
            if node_type in {"Feedback", "Feedback Group"}:
                return "Feedback"
            if node_type == "System Model":
                return "System Model"
            if node_type == "Meeting Discussion":
                return "Meeting Discussion"
            return "Requirement Formation"

        def append_to_section(current: str, section: str, bullets: List[str]) -> str:
            clean_bullets = [bullet for bullet in bullets if str(bullet or "").strip()]
            if not clean_bullets:
                return current
            def clean_bullet(value: str) -> str:
                return re.sub(r"^\s*[-*]\s+", "", value).strip()

            insert = "\n".join(f"- {clean_bullet(bullet)}" for bullet in clean_bullets)
            if re.search(rf"(?m)^{re.escape(section)}\s*$", current):
                return re.sub(
                    rf"(?m)^{re.escape(section)}\s*$",
                    lambda match: match.group(0) + "\n" + insert,
                    current,
                    count=1,
                )
            section_order = [
                "Stakeholder",
                "User Requirement",
                "Conflict",
                "Feedback",
                "System Model",
                "Meeting Discussion",
                "Requirement Formation",
            ]
            try:
                section_index = section_order.index(section)
            except ValueError:
                section_index = len(section_order) - 1
            for next_section in section_order[section_index + 1 :]:
                match = re.search(rf"(?m)^{re.escape(next_section)}\s*$", current)
                if match:
                    return (
                        current[: match.start()].rstrip()
                        + "\n\n"
                        + section
                        + "\n"
                        + insert
                        + "\n\n"
                        + current[match.start() :].lstrip()
                    )
            return current.rstrip() + "\n\n" + section + "\n" + insert

        incoming_by_id: Dict[str, List[str]] = {}
        outgoing_by_id: Dict[str, List[str]] = {}
        for edge in edges:
            from_id = str(edge.get("from") or "").strip()
            to_id = str(edge.get("to") or "").strip()
            if not from_id or not to_id:
                continue
            incoming_by_id.setdefault(to_id, []).append(from_id)
            outgoing_by_id.setdefault(from_id, []).append(to_id)

        bullets_by_section: Dict[str, List[str]] = {}
        for node_id, node in node_by_id.items():
            if not node_id or node_id == target_id or has_id(node_id):
                continue
            node_type = str(node.get("type") or "").strip()
            section = section_for_type(node_type)
            incoming = incoming_by_id.get(node_id) or []
            outgoing = outgoing_by_id.get(node_id) or []
            display_id = visible_id(node_id)
            if section == "User Requirement":
                bullets_by_section.setdefault(section, []).append(
                    f"{display_id} 在拓樸中承接 {format_ids(incoming)}，並推進到 {format_ids(outgoing)}，因此也是本需求形成路徑的一部分。"
                )
            elif section == "Conflict":
                bullets_by_section.setdefault(section, []).append(
                    f"{display_id} 在拓樸中由 {format_ids(incoming)} 形成衝突節點，並交由 {format_ids(outgoing)} 處理。"
                )
            elif section == "System Model":
                bullets_by_section.setdefault(section, []).append(
                    f"{display_id} 在拓樸中由 {format_ids(incoming)} 觸發建模支撐，補充本需求形成所需的模型依據。"
                )
            elif section == "Feedback":
                bullets_by_section.setdefault(section, []).append(
                    f"{display_id} 在拓樸中由 {format_ids(incoming)} 提供領域研究或外部依據，補充本需求的限制與判斷基礎。"
                )
            elif section == "Meeting Discussion":
                bullets_by_section.setdefault(section, []).append(
                    f"{display_id} 在拓樸中承接 {format_ids(incoming)}，並推進到 {format_ids(outgoing)}。"
                )
            elif section == "Stakeholder":
                bullets_by_section.setdefault(section, []).append(
                    f"{display_id} 在拓樸中作為來源，經由分析推進到 {format_ids(outgoing)}。"
                )

        relation_bullets_by_section: Dict[str, List[str]] = {}
        for edge in edges:
            from_id = str(edge.get("from") or "").strip()
            to_id = str(edge.get("to") or "").strip()
            relation = str(edge.get("relation") or "").strip()
            if not from_id or not to_id or not relation:
                continue
            if relation and relation in text and visible_id(from_id) in text and visible_id(to_id) in text:
                continue
            from_type = str((node_by_id.get(from_id) or {}).get("type") or "").strip()
            to_type = str((node_by_id.get(to_id) or {}).get("type") or "").strip()
            source = visible_id(from_id)
            target = visible_id(to_id)
            if relation == "分析":
                section = "User Requirement"
                bullet = f"{source} 透過「分析」形成 {target}。"
            elif relation == "衝突":
                section = "Conflict"
                bullet = f"{source} 與相關來源透過「衝突」關係形成 {target}。"
            elif relation == "解決":
                section = "Meeting Discussion"
                bullet = f"{source} 經 {target}「解決」後，才進入後續正式化路徑。"
            elif relation == "正式化":
                section = "Meeting Discussion" if to_type == "Meeting Discussion" else "Requirement Formation"
                bullet = f"{source} 透過「正式化」推進到 {target}。"
            elif relation == "精練":
                section = "Meeting Discussion"
                bullet = f"{source} 透過「精練」推進到 {target}。"
            elif relation == "建模":
                section = "System Model"
                bullet = f"{source} 透過「建模」支撐 {target}。"
            else:
                section = section_for_type(to_type or from_type)
                bullet = f"{source} 透過「{relation}」推進到 {target}。"
            relation_bullets_by_section.setdefault(section, []).append(bullet)

        for section, bullets in relation_bullets_by_section.items():
            bullets_by_section.setdefault(section, []).extend(
                bullet for bullet in bullets if bullet not in bullets_by_section.get(section, [])
            )

        for section in [
            "Stakeholder",
            "User Requirement",
            "Conflict",
            "Feedback",
            "System Model",
            "Meeting Discussion",
            "Requirement Formation",
        ]:
            text = append_to_section(text, section, bullets_by_section.get(section, []))

        return re.sub(r"\n{3,}", "\n\n", text).strip()

    @staticmethod
    def remove_trace_explanation_topology_artifacts(trace: str) -> str:
        text = str(trace or "").strip()
        if not text:
            return ""
        artifact_patterns = [
            r"^\s*[-*]\s+.*在拓樸中.*$",
            r"^\s*[-*]\s+.*承接\s+前述節點.*$",
            r"^\s*[-*]\s+.*透過「依據」推進到.*$",
            r"^\s*[-*]\s+R\d+-M\d+\s+透過「精練」推進到\s+R\d+-M\d+。?\s*$",
        ]
        lines = []
        for line in text.splitlines():
            if any(re.search(pattern, line) for pattern in artifact_patterns):
                continue
            lines.append(line)
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()

    @staticmethod
    def merge_trace_explanation_sections(trace: str) -> str:
        text = str(trace or "").strip()
        if not text:
            return ""
        section_order = [
            "Stakeholder",
            "User Requirement",
            "Conflict",
            "Feedback",
            "System Model",
            "Meeting Discussion",
            "Requirement Formation",
        ]
        section_names = set(section_order)
        preface: List[str] = []
        sections: Dict[str, List[str]] = {section: [] for section in section_order}
        current_section = ""
        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            if stripped in section_names:
                current_section = stripped
                continue
            if current_section:
                target = sections[current_section]
                if not stripped and (not target or not target[-1].strip()):
                    continue
                target.append(line)
                continue
            if stripped or preface:
                preface.append(line)

        rendered: List[str] = []
        if any(line.strip() for line in preface):
            rendered.extend(preface)
            rendered.append("")
        for section in section_order:
            content = sections.get(section) or []
            while content and not content[0].strip():
                content.pop(0)
            while content and not content[-1].strip():
                content.pop()
            if not content:
                continue
            rendered.append(section)
            rendered.extend(content)
            rendered.append("")
        return re.sub(r"\n{3,}", "\n\n", "\n".join(rendered)).strip()

    @classmethod
    def build_trace_explanation_from_topology(cls, requirement: Dict[str, Any]) -> str:
        graph = requirement.get("trace_graph") if isinstance(requirement.get("trace_graph"), dict) else {}
        nodes = [node for node in (graph.get("nodes") or []) if isinstance(node, dict)]
        edges = [edge for edge in (graph.get("edges") or []) if isinstance(edge, dict)]
        if not nodes:
            return ""

        target_id = str(requirement.get("srs_id") or "").strip()
        description = str(requirement.get("description") or "").strip()
        node_by_id = {
            str(node.get("id") or "").strip(): node
            for node in nodes
            if str(node.get("id") or "").strip()
        }

        def natural_key(value: Any) -> tuple[int, int, int, str]:
            text = str(value or "")
            match = re.search(r"([A-Za-z]+)-(\d+)(?:-M?(\d+))?", text)
            if not match:
                return (999, 999, 999, text)
            group_order = {
                "ST": 1,
                "elicit": 1,
                "URL": 2,
                "CR": 3,
                "FB": 4,
                "SM": 5,
                "R": 6,
                "FR": 7,
                "NFR": 7,
                "CON": 7,
            }.get(match.group(1), 99)
            return (
                group_order,
                int(match.group(2) or 0),
                int(match.group(3) or 0),
                text,
            )

        def strip_html(value: Any) -> str:
            text = str(value or "")
            text = re.sub(r"(?is)<br\s*/?>", "，", text)
            text = re.sub(r"(?is)</(?:p|li|h[1-6]|div|tr)>", "。", text)
            text = re.sub(r"(?is)<[^>]+>", "", text)
            text = re.sub(r"&nbsp;", " ", text)
            text = re.sub(r"&lt;", "<", text)
            text = re.sub(r"&gt;", ">", text)
            text = re.sub(r"&amp;", "&", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text

        def truncate_text(raw: str, max_len: int) -> str:
            return cls._truncate_trace_text(raw, max_len)

        def node_summary(node_id: str, max_len: int = 220) -> str:
            node = node_by_id.get(node_id) or {}
            raw = strip_html(node.get("content") or node.get("label") or node.get("title") or "")
            raw = re.sub(rf"^{re.escape(node_id)}\s*[：:]\s*", "", raw)
            raw = re.sub(r"^(?:發言|需求|決議|摘要)\s*[：:]\s*", "", raw)
            raw = raw.strip(" 。，")
            if not raw:
                return ""
            return truncate_text(raw, max_len)

        def feedback_rows(node_id: str) -> List[Dict[str, str]]:
            node = node_by_id.get(node_id) or {}
            html = str(node.get("content") or "")
            rows: List[Dict[str, str]] = []
            for tr in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", html):
                cells = re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", tr)
                if len(cells) < 3:
                    continue
                feedback_id = strip_html(cells[0])
                if not re.fullmatch(r"FB-\d+", feedback_id):
                    continue
                feedback_type = strip_html(cells[1]) if len(cells) > 1 else ""
                feedback_text = strip_html(cells[2]) if len(cells) > 2 else ""
                sources = re.findall(r'(?is)<span[^>]*class="[^"]*dr-trace-source-chip[^"]*"[^>]*>(.*?)</span>', cells[3] if len(cells) > 3 else "")
                source_text = "、".join(strip_html(source) for source in sources if strip_html(source))
                rows.append(
                    {
                        "id": feedback_id,
                        "type": feedback_type,
                        "text": feedback_text,
                        "sources": source_text,
                    }
                )
            return rows

        def meeting_summary(node_id: str) -> str:
            node = node_by_id.get(node_id) or {}
            html = str(node.get("content") or "")
            parts: List[str] = []
            for title in ("摘要", "決議"):
                match = re.search(rf"(?is)<h2[^>]*>{re.escape(title)}</h2>\s*<p[^>]*>(.*?)</p>", html)
                if match:
                    value = strip_html(match.group(1)).strip(" 。，")
                    if value:
                        parts.append(f"{title}：{value}")
            if parts:
                return truncate_text("；".join(parts), 700)
            return node_summary(node_id, 320)

        def display_id(value: Any) -> str:
            node_id = str(value or "").strip()
            node = node_by_id.get(node_id) or {}
            if node_id.startswith("FB-GROUP-"):
                grouped_ids = [
                    str(grouped_id or "").strip()
                    for grouped_id in (node.get("grouped_ids") or [])
                    if str(grouped_id or "").strip()
                ]
                return "、".join(grouped_ids) if grouped_ids else "Feedback"
            return node_id

        def format_ids(values: List[str], limit: int = 8) -> str:
            unique = [display_id(value) for value in dict.fromkeys(values) if display_id(value)]
            if not unique:
                return "前述節點"
            expanded: List[str] = []
            for item in unique:
                expanded.extend(part for part in item.split("、") if part)
            expanded = list(dict.fromkeys(expanded))
            if len(expanded) <= limit:
                return "、".join(expanded)
            return "、".join(expanded[:limit]) + f" 等 {len(expanded)} 個節點"

        def node_type(node_id: str) -> str:
            return str((node_by_id.get(node_id) or {}).get("type") or "").strip()

        def relation(edge: Dict[str, Any]) -> str:
            return str(edge.get("relation") or "").strip()

        def edge_from(edge: Dict[str, Any]) -> str:
            return str(edge.get("from") or "").strip()

        def edge_to(edge: Dict[str, Any]) -> str:
            return str(edge.get("to") or "").strip()

        def append(sections: Dict[str, List[str]], section: str, bullet: str) -> None:
            clean = re.sub(r"\s+", " ", str(bullet or "")).strip()
            if not clean:
                return
            rows = sections.setdefault(section, [])
            if clean not in rows:
                rows.append(clean)

        incoming: Dict[str, List[Dict[str, Any]]] = {}
        outgoing: Dict[str, List[Dict[str, Any]]] = {}
        for edge in edges:
            from_id = edge_from(edge)
            to_id = edge_to(edge)
            if not from_id or not to_id:
                continue
            outgoing.setdefault(from_id, []).append(edge)
            incoming.setdefault(to_id, []).append(edge)

        sections: Dict[str, List[str]] = {}

        analysis_by_source: Dict[str, List[str]] = {}
        for edge in edges:
            if relation(edge) == "分析":
                analysis_by_source.setdefault(edge_from(edge), []).append(edge_to(edge))
        for source_id in sorted(analysis_by_source, key=natural_key):
            urls = sorted(analysis_by_source[source_id], key=natural_key)
            summary = node_summary(source_id, 320)
            tail = f"；來源內容為「{summary}」。" if summary else "。"
            append(
                sections,
                "Stakeholder",
                f"{display_id(source_id)} 透過「分析」形成 {format_ids(urls)}{tail}",
            )

        for node_id in sorted(node_by_id, key=natural_key):
            if node_type(node_id) != "User Requirement":
                continue
            source_ids = [
                edge_from(edge)
                for edge in incoming.get(node_id, [])
                if node_type(edge_from(edge)) == "Stakeholder Statement"
            ]
            conflict_targets = [
                edge_to(edge)
                for edge in outgoing.get(node_id, [])
                if relation(edge) == "衝突"
            ]
            formal_targets = [
                edge_to(edge)
                for edge in outgoing.get(node_id, [])
                if relation(edge) == "正式化" and node_type(edge_to(edge)) == "Meeting Discussion"
            ]
            summary = node_summary(node_id, 260)
            summary_text = f"；需求整理為「{summary}」。" if summary else "。"
            source_text = f"承接 {format_ids(source_ids)}，並" if source_ids else ""
            if conflict_targets:
                append(
                    sections,
                    "User Requirement",
                    f"{display_id(node_id)} {source_text}作為 {format_ids(conflict_targets)} 的衝突來源{summary_text}",
                )
            elif formal_targets:
                source_text = f"承接 {format_ids(source_ids)}，" if source_ids else ""
                append(
                    sections,
                    "User Requirement",
                    f"{display_id(node_id)} {source_text}未進入 CR 衝突節點，直接交由 {format_ids(formal_targets)} 正式化{summary_text}",
                )
            else:
                next_nodes = [edge_to(edge) for edge in outgoing.get(node_id, [])]
                source_text = f"承接 {format_ids(source_ids)}，並" if source_ids else ""
                append(
                    sections,
                    "User Requirement",
                    f"{display_id(node_id)} {source_text}推進到 {format_ids(next_nodes)}{summary_text}",
                )

        for node_id in sorted(node_by_id, key=natural_key):
            if node_type(node_id) != "Conflict":
                continue
            conflict_sources = [
                edge_from(edge)
                for edge in incoming.get(node_id, [])
                if relation(edge) == "衝突"
            ]
            resolution_targets = [
                edge_to(edge)
                for edge in outgoing.get(node_id, [])
                if relation(edge) == "解決"
            ]
            summary = node_summary(node_id, 420)
            detail = f"；衝突內容為「{summary}」。" if summary else "。"
            append(
                sections,
                "Conflict",
                f"{display_id(node_id)} 匯整 {format_ids(conflict_sources)} 的「衝突」關係，後續由 {format_ids(resolution_targets)} 解決{detail}",
            )

        for node_id in sorted(node_by_id, key=natural_key):
            if node_type(node_id) not in {"Feedback", "Feedback Group"}:
                continue
            sources = [edge_from(edge) for edge in incoming.get(node_id, [])]
            if not sources:
                continue
            if node_id.startswith("FB-GROUP-") or node_type(node_id) == "Feedback Group":
                rows = feedback_rows(node_id)
                append(
                    sections,
                    "Feedback",
                    f"{display_id(node_id)} 由 {format_ids(sources)} 連入，作為「領域研究」依據；下列 Feedback 逐項補充本需求的法規、風險或限制判斷。",
                )
                for row in rows:
                    type_text = f"（{row['type']}）" if row.get("type") else ""
                    source_text = f"；來源：{row['sources']}" if row.get("sources") else ""
                    feedback_text = truncate_text(row.get("text") or "", 320).rstrip("。；; ")
                    append(
                        sections,
                        "Feedback",
                        f"{row['id']}{type_text}：{feedback_text}{source_text}。",
                    )
                continue
            summary = node_summary(node_id, 280)
            detail = f"；依據內容為「{summary}」。" if summary else "。"
            append(
                sections,
                "Feedback",
                f"{display_id(node_id)} 由 {format_ids(sources)} 連入，作為「領域研究」依據，補充法規、風險或限制判斷{detail}",
            )

        for node_id in sorted(node_by_id, key=natural_key):
            if node_type(node_id) != "System Model":
                continue
            sources = [
                edge_from(edge)
                for edge in incoming.get(node_id, [])
                if node_type(edge_from(edge)) == "User Requirement"
            ]
            if not sources:
                continue
            summary = node_summary(node_id, 360)
            detail = f"；模型內容說明「{summary}」。" if summary else "。"
            append(
                sections,
                "System Model",
                f"{display_id(node_id)} 由 {format_ids(sources)} 透過「建模」支撐本需求{detail}",
            )

        resolved_by_meeting: Dict[str, List[str]] = {}
        formal_by_meeting: Dict[str, List[str]] = {}
        meeting_to_meeting: List[Dict[str, Any]] = []
        final_sources: List[str] = []
        for edge in edges:
            from_id = edge_from(edge)
            to_id = edge_to(edge)
            rel = relation(edge)
            if rel == "解決" and node_type(to_id) == "Meeting Discussion":
                resolved_by_meeting.setdefault(to_id, []).append(from_id)
            elif rel == "正式化" and node_type(to_id) == "Meeting Discussion":
                formal_by_meeting.setdefault(to_id, []).append(from_id)
            elif node_type(from_id) == "Meeting Discussion" and node_type(to_id) == "Meeting Discussion":
                meeting_to_meeting.append(edge)
            elif to_id == target_id:
                final_sources.append(from_id)

        for meeting_id in sorted(resolved_by_meeting, key=natural_key):
            summary = meeting_summary(meeting_id)
            detail = f"會議內容為「{summary}」" if summary else "該會議負責收斂衝突結論"
            append(
                sections,
                "Meeting Discussion",
                f"{display_id(meeting_id)} 透過「解決」承接 {format_ids(resolved_by_meeting[meeting_id])}，將衝突需求收斂後交給後續正式化；{detail}。",
            )
        for meeting_id in sorted(formal_by_meeting, key=natural_key):
            sources = sorted(formal_by_meeting[meeting_id], key=natural_key)
            source_types = {node_type(source_id) for source_id in sources}
            if "Conflict" in source_types or "Meeting Discussion" in source_types:
                wording = "承接前一階段的解決或整理結果"
            else:
                wording = f"直接承接 {format_ids(sources)}"
            summary = meeting_summary(meeting_id)
            detail = f"會議內容為「{summary}」" if summary else "該會議確認需求可進入正式規格路徑"
            append(
                sections,
                "Meeting Discussion",
                f"{display_id(meeting_id)} 透過「正式化」{wording}，確認需求可進入正式規格路徑；{detail}。",
            )
        for edge in sorted(meeting_to_meeting, key=lambda item: (natural_key(edge_from(item)), natural_key(edge_to(item)))):
            from_id = edge_from(edge)
            to_id = edge_to(edge)
            rel = relation(edge) or "會議承接"
            if rel == "會議承接":
                summary = meeting_summary(to_id)
                detail = f"；後續會議內容為「{summary}」" if summary else ""
                append(
                    sections,
                    "Meeting Discussion",
                    f"{display_id(from_id)} 延續到 {display_id(to_id)}，保留前一會議的決議並進入下一階段處理{detail}。",
                )
                continue
            summary = meeting_summary(to_id)
            detail = f"；後續會議內容為「{summary}」" if summary else ""
            append(
                sections,
                "Meeting Discussion",
                f"{display_id(from_id)} 透過「{rel}」推進到 {display_id(to_id)}，延續前一會議的決議與待精練內容{detail}。",
            )

        target_summary = description or node_summary(target_id)
        if final_sources:
            append(
                sections,
                "Requirement Formation",
                f"{display_id(target_id)} 由 {format_ids(sorted(final_sources, key=natural_key))} 收斂形成；最終需求為「{target_summary}」。",
            )
        elif target_id:
            append(
                sections,
                "Requirement Formation",
                f"{display_id(target_id)} 由上述 trace path 收斂形成；最終需求為「{target_summary}」。",
            )

        section_order = [
            "Stakeholder",
            "User Requirement",
            "Conflict",
            "Feedback",
            "System Model",
            "Meeting Discussion",
            "Requirement Formation",
        ]
        rendered: List[str] = []
        for section in section_order:
            bullets = sections.get(section) or []
            if not bullets:
                continue
            rendered.append(section)
            rendered.extend(f"- {bullet}" for bullet in bullets)
            rendered.append("")
        return re.sub(r"\n{3,}", "\n\n", "\n".join(rendered)).strip()

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
            requirement_kind = str(req.get("type") or "").strip().lower().replace("_", "-")
            if not req_id:
                continue
            block = block_by_id.get(srs_id) or ""
            if not block:
                raise ValueError(f"design rationale output missing block for {srs_id}")
            prompt_trace = cls.extract_design_rationale_trace(block)
            prompt_trace = cls.normalize_trace_explanation(prompt_trace, description)
            topology_trace = cls.build_trace_explanation_from_topology(req)
            trace = topology_trace or prompt_trace
            trace = cls.normalize_trace_explanation_ids(trace, req)
            trace = cls.ensure_trace_explanation_conflicts(trace, req)
            trace = cls.ensure_trace_explanation_meetings(trace, req)
            trace = cls.clarify_trace_explanation_meetings(trace, req)
            if not topology_trace:
                trace = cls.ensure_trace_explanation_topology_coverage(trace, req)
            trace = cls.remove_trace_explanation_topology_artifacts(trace)
            trace = cls.merge_trace_explanation_sections(trace)
            if not trace:
                trace = cls.build_trace_explanation_from_topology(req)
                trace = cls.normalize_trace_explanation_ids(trace, req)
                trace = cls.merge_trace_explanation_sections(trace)
            trace = re.sub(r"(?m)^Stakeholder User Requirement\s*$\n?", "", trace).strip()
            header = [
                f"### {srs_id}: {title}".rstrip(),
                "",
                f"**Description**: {description}  ",
                "",
            ]
            if requirement_kind == "functional":
                criteria = [
                    str(item or "").strip()
                    for item in (req.get("acceptance_criteria") or [])
                    if str(item or "").strip()
                ]
                if criteria:
                    header.extend(["**Acceptance Criteria**:", ""])
                    header.extend(f"{index}. {item}" for index, item in enumerate(criteria, 1))
                    header.append("")
            if requirement_kind == "non-functional":
                metric = str(req.get("metric") or "").strip()
                if metric:
                    header.extend([f"**Metric**: {metric}", ""])
            header.append("#### Trace Explanation")
            normalized.append("\n".join(header).strip() + ("\n\n" + trace if trace else ""))
        return cls.collapse_design_rationale_separators("\n\n---\n\n".join(normalized))

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
