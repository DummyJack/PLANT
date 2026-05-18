# Expert validation: keep domain research payloads consistent before artifact writes.
import json
from typing import Any, Dict, List


RESEARCH_FIELDS = (
    "findings",
    "sources",
    "constraints",
    "risks",
    "recommendations",
    "open_items",
)

TRACEABLE_RESEARCH_FIELDS = (
    "findings",
    "constraints",
    "risks",
    "recommendations",
    "open_items",
)


def has_research_content(payload: Dict[str, Any]) -> bool:
    return any(bool(payload.get(field)) for field in RESEARCH_FIELDS)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def compact_list(values: Any) -> List[Any]:
    if values is None:
        return []
    if not isinstance(values, list):
        values = [values]

    rows: List[Any] = []
    seen = set()
    for value in values:
        if value is None:
            continue
        if isinstance(value, dict):
            row = {str(k): v for k, v in value.items() if v not in (None, "", [], {})}
            if not row:
                continue
            key = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
            if key not in seen:
                rows.append(row)
                seen.add(key)
            continue
        text = clean_text(value)
        if not text or text in seen:
            continue
        rows.append(text)
        seen.add(text)
    return rows


def requirement_refs(values: Any) -> List[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []

    refs: List[str] = []
    seen = set()
    for value in values:
        ref = clean_text(value)
        if not ref or ref in seen:
            continue
        refs.append(ref)
        seen.add(ref)
    return refs


def research_items(values: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen = set()
    for value in compact_list(values):
        if isinstance(value, dict):
            text = clean_text(value.get("text") or value.get("finding") or value.get("note"))
            if not text:
                continue
            row = {
                "text": text,
                "related_URL": requirement_refs(value.get("related_URL")),
            }
        else:
            text = clean_text(value)
            if not text:
                continue
            row = {"text": text, "related_URL": []}

        key = json.dumps(row, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            rows.append(row)
            seen.add(key)
    return rows


def clean_research_result(raw: Any) -> Dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    result: Dict[str, Any] = {}

    result["findings"] = research_items(source.get("findings"))
    result["sources"] = compact_list(source.get("sources"))
    result["constraints"] = research_items(source.get("constraints"))
    result["risks"] = research_items(source.get("risks"))
    result["recommendations"] = research_items(source.get("recommendations"))
    result["open_items"] = research_items(source.get("open_items"))
    return result if has_research_content(result) else {}


def clean_domain_research(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        if not raw:
            return {}
        result = {}
    else:
        return {}

    for field in RESEARCH_FIELDS:
        if field in TRACEABLE_RESEARCH_FIELDS:
            result[field] = research_items(raw.get(field))
        else:
            result[field] = compact_list(raw.get(field))

    return result if has_research_content(result) else {}
