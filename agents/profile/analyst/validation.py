# Validates and normalizes agent output data formats.
import re
from typing import Any, Dict, List, Optional


conflict_types = {
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


# ========
# Defines clean text function for this module workflow.
# ========
def clean_text(value: Any) -> str:
    return str(value or "").strip()


# ========
# Defines clean list function for this module workflow.
# ========
def clean_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [clean_text(x) for x in value if clean_text(x)]
    text = clean_text(value)
    return [text] if text else []


# ========
# Defines requirement text function for this module workflow.
# ========
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


# ========
# Defines requirement record function for this module workflow.
# ========
def requirement_record(
    req: Dict[str, Any],
) -> Dict[str, Any]:
    source = dict(req) if isinstance(req, dict) else {}
    out: Dict[str, Any] = {}
    if clean_text(source.get("id")):
        out["id"] = clean_text(source.get("id"))
    out["text"] = requirement_text(source.get("text"))

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


# ========
# Defines requirement records function for this module workflow.
# ========
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


# ========
# Defines scope payload function for this module workflow.
# ========
def scope_payload(scope: Any) -> Dict[str, Any]:
    if not isinstance(scope, dict):
        return {"in_scope": [], "out_of_scope": []}
    return {
        "in_scope": clean_list(scope.get("in_scope")),
        "out_of_scope": clean_list(scope.get("out_of_scope")),
    }


# ========
# Defines validate elicited reqts function for this module workflow.
# ========
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


# ========
# Defines conflict records function for this module workflow.
# ========
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
            label = clean_text(row.get("final_label"))
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
                "initial_label": label,
                "final_label": label,
                "pair_index": pair_index,
                "requirement_ids": rel_ids,
            }
            title = clean_text(row.get("title"))
            if label == "Conflict":
                if not title:
                    continue
                entry["title"] = title
            reason = clean_text(row.get("reason"))
            if reason:
                entry["initial_reason"] = reason
            conflict_type = clean_text(row.get("final_type")).lower()
            if label == "Conflict":
                entry["final_type"] = conflict_type if conflict_type in conflict_types else "other"
            by_pair[pair_index] = entry
        return [by_pair[i] for i in range(pair_count) if i in by_pair]

    conflicts: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = clean_text(row.get("final_label"))
        if label not in {"Conflict", "Neutral"}:
            continue
        rel_ids = clean_list(row.get("requirement_ids"))
        if label == "Conflict" and len(rel_ids) < 2:
            continue
        entry: Dict[str, Any] = {
            "initial_label": label,
            "final_label": label,
        }
        cid = clean_text(row.get("id"))
        if cid:
            entry["id"] = cid
        if rel_ids:
            entry["requirement_ids"] = rel_ids
        title = clean_text(row.get("title"))
        if label == "Conflict":
            if not title:
                continue
            entry["title"] = title
        reason = clean_text(row.get("reason"))
        if reason:
            entry["initial_reason"] = reason
        related_pairs = clean_list(row.get("related_pairs"))
        if related_pairs:
            entry["related_pairs"] = related_pairs
        conflict_type = clean_text(row.get("final_type")).lower()
        if label == "Conflict":
            entry["final_type"] = conflict_type if conflict_type in conflict_types else "other"
        conflicts.append(entry)
    return conflicts


# ========
# Defines signoff decisions function for this module workflow.
# ========
def signoff_decisions(rows: Any) -> List[Dict[str, Any]]:
    raw_rows = rows.get("decisions") if isinstance(rows, dict) else rows
    if not isinstance(raw_rows, list):
        return []
    decisions: List[Dict[str, Any]] = []
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        cid = clean_text(row.get("id"))
        label = clean_text(row.get("final_label"))
        if not cid or label not in {"Conflict", "Neutral"}:
            continue
        decisions.append(
            {
                "id": cid,
                "final_label": label,
                "reason": clean_text(row.get("reason")),
            }
        )
    return decisions
