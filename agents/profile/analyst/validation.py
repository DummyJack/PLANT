# Analyst output validation: normalize complex LLM-produced requirement and conflict payloads.
import re
from typing import Any, Dict, List, Optional


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
    out = dict(req) if isinstance(req, dict) else {}
    out["text"] = requirement_text(out.get("text"))

    rtype = clean_text(out.get("type")) or "FR"
    rtype_upper = rtype.upper()
    if rtype_upper in {"FUNCTIONAL", "FUNCTIONAL REQUIREMENT"}:
        rtype = "FR"
    elif rtype_upper in {"NON-FUNCTIONAL", "NON_FUNCTIONAL", "NON-FUNCTIONAL REQUIREMENT"}:
        rtype = "NFR"
    elif rtype.lower() == "constraint":
        rtype = "constraint"
    elif rtype_upper in {"FR", "NFR"}:
        rtype = rtype_upper
    else:
        rtype = "FR"
    out["type"] = rtype

    priority = clean_text(out.get("priority")).lower() or "should"
    if priority not in {"must", "should", "could"}:
        priority = "should"
    out["priority"] = priority

    sources = clean_list(out.get("source_stakeholders"))
    out["source_stakeholders"] = sources

    out["acceptance_criteria"] = clean_text(out.get("acceptance_criteria"))
    out["source"] = clean_text(out.get("source"))
    out.pop("rationale", None)
    out.pop("status", None)
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


def validate_elicited_reqts(rows: Any) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    seen_texts = set()
    for row in requirement_records(rows):
        text_key = row.get("text", "").lower()
        if not text_key or text_key in seen_texts:
            continue
        if not row.get("source"):
            continue
        if not row.get("acceptance_criteria"):
            continue
        seen_texts.add(text_key)
        candidates.append(row)
    return candidates


def conflict_records(
    rows: Any,
    *,
    pairwise_mode: bool = False,
    pair_count: int = 0,
    pair_id_prefix: str = "PAIR",
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
            rid_a = f"{pair_id_prefix}-P{pair_index}-a"
            rid_b = f"{pair_id_prefix}-P{pair_index}-b"
            rel = row.get("requirement_ids") or row.get("related_requirements") or [rid_a, rid_b]
            rel_ids = clean_list(rel) or [rid_a, rid_b]
            entry: Dict[str, Any] = {
                "id": f"PAIR-{pair_index + 1}",
                "label": label,
                "pair_index": pair_index,
                "requirement_ids": rel_ids,
            }
            by_pair[pair_index] = entry
        return [by_pair[i] for i in range(pair_count) if i in by_pair]

    conflicts: List[Dict[str, Any]] = []
    neutral_count = 0
    design_count = 0
    conflict_count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = clean_text(row.get("label"))
        if label == "Neutral":
            neutral_count += 1
            conflicts.append(
                {
                    "id": f"NF-{neutral_count}",
                    "label": "Neutral",
                    "requirement_ids": clean_list(row.get("requirement_ids") or row.get("related_requirements")),
                }
            )
            continue
        if label != "Conflict":
            continue
        conflict_count += 1
        rel_ids = clean_list(row.get("requirement_ids") or row.get("related_requirements"))
        stakeholders = clean_list(row.get("stakeholder_names"))
        if rel_ids or stakeholders:
            entry: Dict[str, Any] = {
                "id": f"CF-{conflict_count}",
                "label": "Conflict",
            }
            if rel_ids:
                entry["requirement_ids"] = rel_ids
            if stakeholders:
                entry["stakeholder_names"] = stakeholders
        else:
            design_count += 1
            entry = {
                "id": f"CF-D{design_count}",
                "label": "Conflict",
                "requirement_ids": [],
            }
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
            "rationale": "依 conflict-analyzer 的需求關係判斷整理需求處理建議",
        }
    if not best_options and not compromise:
        return None
    return {"best_options": best_options, "compromise": compromise}
