# Analyst output validation: normalize complex LLM-produced requirement and conflict payloads.
import re
from typing import Any, Dict, List, Optional


CONFLICT_TYPES = {
    "logical",
    "technical",
    "resource",
    "temporal",
    "data",
    "state",
    "priority",
    "scope",
    "other",
}


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def clean_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [clean_text(x) for x in value if clean_text(x)]
    text = clean_text(value)
    return [text] if text else []


def requirement_text(text: Any) -> str:
    value = clean_text(text)
    if not value:
        return ""
    value = re.sub(r"^\s*[-*•]+\s*", "", value)
    value = re.sub(
        r"^\s*(需求|Requirement)\s*[:：]\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = value.strip().strip("\"'“”「」")
    return re.sub(r"\s+", " ", value).strip()


def requirement_record(
    req: Dict[str, Any],
) -> Dict[str, Any]:
    source = dict(req) if isinstance(req, dict) else {}
    out: Dict[str, Any] = {}
    if clean_text(source.get("id")):
        out["id"] = clean_text(source.get("id"))
    out["text"] = requirement_text(
        source.get("text")
        or source.get("description")
        or source.get("requirement")
    )

    stakeholder = source.get("stakeholder")
    if isinstance(stakeholder, dict):
        out["stakeholder"] = {
            "name": clean_text(stakeholder.get("name")),
            "type": clean_text(stakeholder.get("type")),
        }
    out["source"] = clean_text(source.get("source"))
    if clean_text(source.get("source_id")):
        out["source_id"] = clean_text(source.get("source_id"))
    return out


def requirement_records(
    rows: Any,
) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        req = requirement_record(row)
        if req.get("text"):
            normalized.append(req)
    return normalized


def scope_payload(scope: Any) -> Dict[str, Any]:
    if not isinstance(scope, dict):
        return {"in_scope": [], "out_of_scope": []}
    return {
        "in_scope": clean_list(scope.get("in_scope")),
        "out_of_scope": clean_list(scope.get("out_of_scope")),
    }


def validate_elicited_reqts(
    rows: Any,
    *,
    allowed_stakeholders: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    seen_texts = set()
    allowed = {
        clean_text(name)
        for name in (allowed_stakeholders or [])
        if clean_text(name)
    }
    for row in requirement_records(rows):
        text_key = row.get("text", "").lower()
        if not text_key or text_key in seen_texts:
            continue
        stakeholder = row.get("stakeholder") if isinstance(row.get("stakeholder"), dict) else {}
        stakeholder_name = clean_text(stakeholder.get("name"))
        if not stakeholder_name or not row.get("source"):
            continue
        if allowed and stakeholder_name not in allowed:
            continue
        seen_texts.add(text_key)
        candidates.append(row)
    return candidates


def conflict_records(
    rows: Any,
    *,
    pairwise_mode: bool = False,
    pair_count: int = 0,
    pair_requirements: Optional[Dict[int, List[str]]] = None,
) -> List[Dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    if pairwise_mode:
        by_pair: Dict[int, Dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                pair_index = int(row.get("pair_index"))
            except (TypeError, ValueError):
                continue
            if pair_index < 0 or pair_index >= pair_count:
                continue
            label = clean_text(row.get("label"))
            if label not in {"Conflict", "Neutral"}:
                continue
            rel = row.get("requirement_ids")
            rel_ids = clean_list(rel)
            expected_ids = list((pair_requirements or {}).get(pair_index) or [])
            if len(expected_ids) == 2:
                rel_ids = expected_ids
            if len(rel_ids) != 2:
                continue
            entry: Dict[str, Any] = {
                "id": f"PAIR-{pair_index + 1}",
                "label": label,
                "pair_index": pair_index,
                "requirement_ids": rel_ids,
            }
            reason = clean_text(row.get("reason"))
            if reason:
                entry["initial_reason"] = reason
            conflict_type = clean_text(row.get("type") or row.get("conflict_type")).lower()
            if label == "Conflict":
                entry["initial_type"] = conflict_type if conflict_type in CONFLICT_TYPES else "other"
            by_pair[pair_index] = entry
        return [by_pair[i] for i in range(pair_count) if i in by_pair]

    conflicts: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = clean_text(row.get("label"))
        if label not in {"Conflict", "Neutral"}:
            continue
        rel_ids = clean_list(row.get("requirement_ids"))
        if label == "Conflict" and len(rel_ids) < 2:
            continue
        entry: Dict[str, Any] = {"label": label}
        cid = clean_text(row.get("id"))
        if cid:
            entry["id"] = cid
        if rel_ids:
            entry["requirement_ids"] = rel_ids
        reason = clean_text(row.get("reason"))
        if reason:
            entry["initial_reason"] = reason
        related_pairs = clean_list(row.get("related_pairs"))
        if related_pairs:
            entry["related_pairs"] = related_pairs
        conflict_type = clean_text(row.get("type") or row.get("conflict_type")).lower()
        if label == "Conflict":
            entry["initial_type"] = conflict_type if conflict_type in CONFLICT_TYPES else "other"
        conflicts.append(entry)
    return conflicts


def signoff_decisions(rows: Any) -> List[Dict[str, Any]]:
    raw_rows = rows.get("decisions") if isinstance(rows, dict) else rows
    if not isinstance(raw_rows, list):
        return []
    decisions: List[Dict[str, Any]] = []
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        cid = clean_text(row.get("id"))
        label = clean_text(row.get("new_label"))
        if not cid or label not in {"Conflict", "Neutral"}:
            continue
        decisions.append(
            {
                "id": cid,
                "new_label": label,
                "reason": clean_text(row.get("reason")),
            }
        )
    return decisions


def resolution_options_payload(data: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(data, dict):
        return None
    raw_options = data.get("resolution_options") or []
    if not isinstance(raw_options, list):
        raw_options = []
    best_options: List[Dict[str, Any]] = []
    for index, row in enumerate(raw_options, 1):
        if not isinstance(row, dict):
            continue
        option = clean_text(row.get("option"))
        strategy = clean_text(row.get("strategy"))
        title = strategy or option or f"方案 {index}"
        if option and strategy:
            title = f"方案 {option}: {strategy}"
        desc = clean_text(row.get("description"))
        parts = []
        pros = clean_list(row.get("pros"))
        cons = clean_list(row.get("cons"))
        if pros:
            parts.append("優點：" + ", ".join(pros))
        if cons:
            parts.append("缺點：" + ", ".join(cons))
        if parts:
            desc = desc + "\n" + "\n".join(parts) if desc else "\n".join(parts)
        best_options.append(
            {
                "id": index,
                "title": title,
                "description": desc or "(無描述)",
                "source": "analyst",
            }
        )
    recommended = clean_text(data.get("recommended_resolution"))
    compromise = None
    if recommended:
        compromise = {
            "id": 4,
            "title": "需求處理建議（Analyst）",
            "description": recommended,
        }
    if not best_options and not compromise:
        return None
    return {"best_options": best_options, "compromise": compromise}
