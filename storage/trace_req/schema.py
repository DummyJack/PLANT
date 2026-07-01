import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from .ids import trace_req_next_id, trace_req_trace_id


def trace_req_event_defaults(event_type: str, relation: str = "") -> Dict[str, str]:
    event = str(event_type or "").strip()
    rel = str(relation or "").strip()
    defaults = {
        "derive_requirement": {"role": "main_chain", "edge_label": "分析"},
        "formalize_requirement": {"role": "main_chain", "edge_label": ""},
        "generate_feedback": {"role": "supporting", "edge_label": "依據", "style": "dashed"},
        "generate_model": {"role": "supporting", "edge_label": "建模", "style": "dashed"},
        "detect_conflict": {"role": "main_chain", "edge_label": "衝突"},
        "resolve_issue": {"role": "main_chain", "edge_label": "解決"},
    }.get(event, {"role": "supporting", "edge_label": rel})
    return {
        "role": defaults.get("role", "supporting"),
        "edge_label": defaults.get("edge_label", rel),
        "style": defaults.get("style", ""),
    }


def enrich_trace_req_row(row: Dict[str, Any], req_to_srs: Dict[str, str]) -> Dict[str, Any]:
    event_type = str(row.get("event_type") or row.get("stage") or "").strip()
    relation = str(row.get("relation") or "").strip()
    target_requirement_id = str(row.get("target_requirement_id") or "").strip()
    if target_requirement_id:
        row["target_requirement_id"] = target_requirement_id
        row["trace_id"] = str(row.get("trace_id") or "").strip() or trace_req_trace_id(target_requirement_id)

    from_id = str(row.get("from") or "").strip()
    to_id = str(row.get("to") or "").strip()
    if from_id:
        row["from"] = from_id
    if to_id:
        row["to"] = to_id

    defaults = trace_req_event_defaults(event_type, relation)
    row["role"] = str(row.get("role") or defaults["role"]).strip() or defaults["role"]
    if "edge_label" not in row:
        row["edge_label"] = defaults["edge_label"]
    if defaults.get("style") and not str(row.get("style") or "").strip():
        row["style"] = defaults["style"]
    return row


def trace_req_public_signature(row: Dict[str, Any]) -> str:
    return json.dumps(
        {
            "trace_id": str(row.get("trace_id") or "").strip(),
            "target_requirement_id": str(row.get("target_requirement_id") or "").strip(),
            "from": str(row.get("from") or "").strip(),
            "to": str(row.get("to") or "").strip(),
            "edge_label": str(row.get("edge_label") or "").strip(),
            "role": str(row.get("role") or "").strip(),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def public_trace_req_row(row: Dict[str, Any]) -> Dict[str, Any]:
    public: Dict[str, Any] = {}
    for key in (
        "event_id",
        "trace_id",
        "target_requirement_id",
        "from",
        "to",
        "edge_label",
        "role",
        "style",
        "stage",
        "agent",
        "confidence",
        "reason",
        "trace_reason",
        "created_at",
    ):
        value = row.get(key)
        if value not in (None, "", []):
            public[key] = value
    return public


def append_trace_req_row(
    rows: List[Dict[str, Any]],
    seen: set[str],
    *,
    trace_id: str = "",
    target_requirement_id: str,
    from_id: str,
    to_id: str,
    edge_label: str = "",
    role: str = "supporting",
    style: str = "",
    stage: str = "",
    agent: str = "",
    confidence: str = "explicit",
    reason: str = "",
    trace_reason: str = "",
) -> None:
    target = str(target_requirement_id or "").strip()
    source = str(from_id or "").strip()
    target_node = str(to_id or "").strip()
    if not target or not source or not target_node:
        return
    row = {
        "trace_id": str(trace_id or "").strip() or trace_req_trace_id(target),
        "target_requirement_id": target,
        "from": source,
        "to": target_node,
        "edge_label": str(edge_label or "").strip(),
        "role": str(role or "supporting").strip() or "supporting",
    }
    public_signature = trace_req_public_signature(row)
    if public_signature in seen:
        return
    seen.add(public_signature)
    row["event_id"] = trace_req_next_id(rows)
    if style:
        row["style"] = style
    if stage:
        row["stage"] = stage
    if agent:
        row["agent"] = agent
    if confidence:
        row["confidence"] = confidence
    detail = str(trace_reason or reason or "").strip()
    if reason:
        row["reason"] = reason
    if detail:
        row["trace_reason"] = detail
    row["created_at"] = datetime.now(timezone.utc).isoformat()
    rows.append(row)
