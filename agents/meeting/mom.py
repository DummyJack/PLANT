from __future__ import annotations

# Utilities for MoM rendering and prompt-backed grouping.
import re
from typing import Any, Callable, Dict, List


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


def artifact_id_sort_key(value: Any) -> tuple[str, int, str]:
    text = str(value or "").strip()
    match = re.fullmatch(r"([A-Za-z]+)-(\d+)", text)
    if not match:
        return (text, 999999, text)
    return (match.group(1).upper(), int(match.group(2)), text)


def option_display_label(value: Any, index: int = 0) -> str:
    raw_values = [
        row.strip().upper()
        for row in re.split(r"[,，、]", str(value or ""))
        if row.strip()
    ]
    if not raw_values:
        raw_values = [chr(ord("A") + index)]
    labels: List[str] = []
    for text in raw_values:
        if text.isdigit():
            text = chr(ord("A") + max(0, int(text) - 1))
        labels.append(f"選項 {text}")
    return "、".join(labels)


def unclear_header_text(value: Any, *, allow_empty: bool = False) -> bool:
    text = clean_repeated_text(value)
    if not text:
        return allow_empty
    normalized = re.sub(r"[\s。．.，,；;：:、-]+", "", text).lower()
    unclear_values = {
        "agreed",
        "resolved",
        "completed",
        "done",
        "closed",
        "human_decision",
        "已同意",
        "已解決",
        "已完成",
        "已關閉",
        "完成",
        "同意",
        "解決",
    }
    return normalized in unclear_values or len(text) < 16


def valid_artifact_id(value: Any, prefixes: tuple[str, ...]) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    prefix_pattern = "|".join(re.escape(prefix) for prefix in prefixes)
    return bool(re.fullmatch(rf"(?:{prefix_pattern})-\d+", text))


def clean_id_list(values: Any, prefixes: tuple[str, ...]) -> List[str]:
    rows = values if isinstance(values, list) else [values]
    out: List[str] = []
    for value in rows:
        text = str(value or "").strip()
        if valid_artifact_id(text, prefixes) and text not in out:
            out.append(text)
    return out


def referenced_ids(
    issue: Dict[str, Any],
    conversation: List[Dict[str, Any]],
    resolution: Dict[str, Any],
) -> List[str]:
    values: List[Any] = []
    trace = issue.get("trace") if isinstance(issue.get("trace"), dict) else {}
    values.extend(trace.get("artifact_ids") or [])
    for key in ("affected_requirement_ids", "affected_conflict_ids", "affected_model_ids"):
        values.extend(resolution.get(key) or [])
    for entry in conversation or []:
        if not isinstance(entry, dict):
            continue
        resp = entry.get("response") if isinstance(entry.get("response"), dict) else {}
        action_results = entry.get("issue_action_results")
        if not isinstance(action_results, list):
            action_results = resp.get("issue_action_results")
        for result in action_results if isinstance(action_results, list) else []:
            if not isinstance(result, dict):
                continue
            for row in (result.get("REQ") or []):
                if isinstance(row, dict):
                    values.append(row.get("id"))
            for row in (result.get("requirements") or []):
                if isinstance(row, dict):
                    values.append(row.get("id"))
            for row in (result.get("system_models") or result.get("model_changes") or []):
                if isinstance(row, dict):
                    values.append(row.get("id") or row.get("target_model_id"))
            for row in result.get("conflict_report") or []:
                if isinstance(row, dict):
                    values.append(row.get("id"))
    ids = [
        str(value).strip()
        for value in values
        if str(value or "").strip()
    ]
    return list(dict.fromkeys(ids))


def build_conflict_rows(
    conflict_options: List[Dict[str, Any]],
    resolution: Dict[str, Any],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index, option in enumerate(conflict_options or []):
        if not isinstance(option, dict):
            continue
        if option.get("kind") == "conflict_decision":
            conflict_id = str(option.get("conflict_id") or "").strip() or f"CR-{index + 1}"
            rows.append(
                {
                    "id": conflict_id,
                    "title": str(option.get("title") or "").strip(),
                    "options": option.get("options") or [],
                    "recommended_resolution": option.get("recommended_resolution") or "",
                }
            )
    if not rows:
        affected_ids = [
            str(value).strip()
            for value in (resolution.get("affected_conflict_ids") or [])
            if str(value).strip().startswith("CR-")
        ]
        rows = [{"id": conflict_id, "title": ""} for conflict_id in affected_ids]
    return rows


def sanitize_conflict_discussion_groups(
    data: Any,
    conflict_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    known_ids = {str(row.get("id") or "").strip() for row in conflict_rows if str(row.get("id") or "").strip()}
    title_by_id = {
        str(row.get("id") or "").strip(): clean_repeated_text(row.get("title", ""))[:100].rstrip()
        for row in conflict_rows
        if str(row.get("id") or "").strip()
    }

    option_details: Dict[str, str] = {}
    for conflict in conflict_rows or []:
        if not isinstance(conflict, dict):
            continue
        for option_index, option in enumerate(conflict.get("options") or []):
            if not isinstance(option, dict):
                continue
            option_id = str(option.get("id") or option.get("option") or "").strip()
            label = option_display_label(option_id, option_index)
            detail = clean_repeated_text(option.get("summary") or option.get("description") or option.get("title") or "")
            if label and detail:
                option_details[label] = detail

    def expand_option_mentions(value: Any) -> str:
        text = clean_repeated_text(value)
        if not text:
            return ""
        for label, detail in option_details.items():
            raw_label = label.replace("選項 ", "").strip()
            if not raw_label:
                continue
            if not detail or detail in text:
                continue
            replacement = f"{label}：{detail}"
            next_text = re.sub(
                rf"(採用|選擇|建議採用|決議採用)(選項|方案)?\s*{re.escape(raw_label)}(?![A-Za-z])",
                rf"\1{replacement}",
                text,
                count=1,
            )
            if next_text != text:
                text = next_text
                continue
            next_text = re.sub(
                rf"(選項|方案)\s*{re.escape(raw_label)}(?![A-Za-z])",
                replacement,
                text,
                count=1,
            )
            if next_text != text:
                text = next_text
                continue
            text = re.sub(
                rf"(?<![A-Za-z]){re.escape(raw_label)}(?![A-Za-z])",
                replacement,
                text,
                count=1,
            )
        text = re.sub(r"。{2,}", "。", text)
        text = re.sub(r"．{2,}", "．", text)
        return text

    groups: List[Dict[str, Any]] = []
    for row in data.get("discussion_groups") or []:
        if not isinstance(row, dict):
            continue
        conflict_id = str(row.get("conflict_id") or "").strip()
        if known_ids and conflict_id not in known_ids:
            continue
        turns: List[Dict[str, str]] = []
        for turn in row.get("turns") or []:
            if not isinstance(turn, dict):
                continue
            speaker = str(turn.get("speaker") or "").strip()
            text = expand_option_mentions(turn.get("text", ""))
            if speaker and text and len(text) >= 8:
                turns.append({"speaker": speaker, "text": text[:700].rstrip()})
        if turns:
            title = clean_repeated_text(row.get("title", ""))[:100].rstrip()
            groups.append(
                {
                    "conflict_id": conflict_id,
                    "title": title or title_by_id.get(conflict_id, ""),
                    "turns": turns[:8],
                }
            )
    overall_turns: List[Dict[str, str]] = []
    for turn in data.get("overall_turns") or []:
        if not isinstance(turn, dict):
            continue
        speaker = str(turn.get("speaker") or "").strip()
        text = expand_option_mentions(turn.get("text", ""))
        if speaker and text and len(text) >= 8:
            overall_turns.append({"speaker": speaker, "text": text[:700].rstrip()})
    if overall_turns:
        groups.append({"conflict_id": "總結", "title": "", "turns": overall_turns[:8]})
    return groups


def render_discussion_groups(groups: List[Dict[str, Any]]) -> str:
    blocks: List[str] = []
    for group in groups:
        conflict_id = str(group.get("conflict_id") or "").strip()
        title = str(group.get("title") or "").strip()
        heading = conflict_id or "總結"
        if heading == "整體討論":
            heading = "總結"
        if title and heading != "總結":
            heading += f"：{title}"
        block = [f"### {heading}", ""]
        for turn in group.get("turns") or []:
            if not isinstance(turn, dict):
                continue
            speaker = str(turn.get("speaker") or "").strip() or "Agent"
            text = str(turn.get("text") or "").strip()
            if text:
                if heading == "總結" and speaker == "總結":
                    block.extend([text, ""])
                else:
                    block.extend([f"#### {speaker}", "", text, ""])
        blocks.append("\n".join(block).rstrip())
    return "\n\n".join(blocks).strip()


def write_conflict_discussion_groups(
    *,
    issue: Dict[str, Any],
    conversation: List[Dict[str, Any]],
    resolution: Dict[str, Any],
    conflict_options: List[Dict[str, Any]],
    chat_json: Callable[..., Any] | None,
    build_direct_messages: Callable[..., Any] | None,
) -> List[Dict[str, Any]]:
    if str((issue or {}).get("category") or "").strip() != "resolve_conflict":
        return []
    if not chat_json or not build_direct_messages:
        return []
    conflict_rows = build_conflict_rows(conflict_options, resolution)
    if not conflict_rows:
        return []
    discussion_rows: List[Dict[str, str]] = []
    for entry in conversation or []:
        if not isinstance(entry, dict) or entry.get("is_reply"):
            continue
        agent = str(entry.get("agent") or "").strip()
        resp = entry.get("response") if isinstance(entry.get("response"), dict) else {}
        text = clean_repeated_text(resp.get("text", ""))[:1600].rstrip()
        if agent and text:
            discussion_rows.append({"speaker": agent, "text": text})
    if not discussion_rows:
        return []

    prompt = """# 任務
你要把需求衝突解決會議的原始發言，重組成以 CR 為單位的 MoM 討論紀錄；無法歸到單一 CR 的內容要改寫成「總結」。

# 邊界
- 只能拆分、摘要或改寫 context 中已有的發言，不可新增觀點。
- 每個 discussion_groups item 對應一個 conflict_id。
- 每個 turns item 必須只描述該 speaker 對該 conflict_id 的觀點。
- 如果 speaker 沒有明確談到該 CR，不要硬補。
- 如果一段發言同時提到多個 CR，可以拆到多個 CR。
- 如果無法判斷屬於哪個 CR，放到 overall_turns，不要亂塞。
- overall_turns 是總結，不是逐字討論；speaker 可用「總結」，text 應像正式會議總結，摘要整體討論重點、已確認差異與決議方向。
- 若總結提到選項 A/B/C，必須把選項內容自然寫進句子中，例如「採用選項 A：完整顯示配送費率與預估里程」，不可只寫 A/B/C。
- 每個 discussion_groups item 的 conflict_id 必須使用 context.conflicts 中的 CR-N；若該 CR 有 title，title 必須保留。
- 不要把 human decision 或最終裁決寫進討論紀錄；裁決留給 MoM 決議區。
- speaker 必須沿用原始 speaker，例如 Analyst、Expert、Modeler、User。
- 使用繁體中文。

# 輸出 JSON
{
  "discussion_groups": [
    {
      "conflict_id": "CR-1",
      "title": "衝突標題",
      "turns": [
        {"speaker": "Analyst", "text": "Analyst 針對 CR-1 的觀點"}
      ]
    }
  ],
  "overall_turns": [
    {"speaker": "總結", "text": "整體摘要與決議方向；若提到選項 A，需寫出選項 A 的內容"}
  ]
}"""
    context = {
        "issue": {
            "title": issue.get("title", ""),
            "description": issue.get("description", ""),
            "trace": issue.get("trace", {}),
        },
        "conflicts": conflict_rows[:12],
        "resolution": {
            "status": resolution.get("status", ""),
            "summary": resolution.get("summary", ""),
            "decision": resolution.get("decision", ""),
            "affected_conflict_ids": resolution.get("affected_conflict_ids", []),
        },
        "discussion": discussion_rows[:16],
    }
    try:
        data = chat_json(build_direct_messages(prompt, context=context))
    except Exception:
        return []
    return sanitize_conflict_discussion_groups(data, conflict_rows)
