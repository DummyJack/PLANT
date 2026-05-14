# Expert validation: keep domain research payloads consistent before artifact writes.
import json
from typing import Any, Dict, List


DOMAIN_RESEARCH_LIST_FIELDS = (
    "findings",
    "sources",
    "derived_requirements",
    "compliance_risks",
    "binding_obligations",
    "risk_notes",
    "recommendations",
    "gaps_for_further_research",
)


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


def derived_requirements_list(values: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen = set()
    for value in compact_list(values):
        if isinstance(value, dict):
            row = dict(value)
            text = clean_text(row.get("text"))
            if not text:
                continue
            row["text"] = text
            for key in ("source", "category", "rationale"):
                if key in row:
                    cleaned = clean_text(row.get(key))
                    if cleaned:
                        row[key] = cleaned
                    else:
                        row.pop(key, None)
        else:
            text = clean_text(value)
            if not text:
                continue
            row = {"text": text}

        dedupe_key = clean_text(row.get("text")).lower()
        if dedupe_key and dedupe_key not in seen:
            rows.append(row)
            seen.add(dedupe_key)
    return rows


def research_result_payload(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        result = dict(raw)
    else:
        result = {}

    result["findings"] = compact_list(result.get("findings"))
    result["sources"] = compact_list(result.get("sources"))
    result["derived_requirements"] = derived_requirements_list(
        result.get("derived_requirements")
    )
    result["binding_obligations"] = compact_list(result.get("binding_obligations"))
    result["risk_notes"] = compact_list(result.get("risk_notes"))
    result["recommendations"] = compact_list(result.get("recommendations"))
    return result


def domain_research_payload(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        source = raw.get("domain_research") if isinstance(raw.get("domain_research"), dict) else raw
        if not source:
            return {}
        result = dict(source)
    else:
        return {}

    for field in DOMAIN_RESEARCH_LIST_FIELDS:
        result[field] = compact_list(result.get(field))

    result["derived_requirements"] = derived_requirements_list(
        result.get("derived_requirements")
    )
    return result
