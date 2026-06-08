# Handles artifact logic for project artifact storage and file export behavior.
import json
import re

from pathlib import Path
from typing import Any, Dict, List, Optional

from .json import save_json_file


# ========
# Defines load json path function for this module workflow.
# ========
def load_json_path(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ========
# Defines save json path function for this module workflow.
# ========
def save_json_path(base_dir: Path, data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    save_json_file(base_dir, data, path)


# ========
# Defines has payload content function for this module workflow.
# ========
def has_payload_content(data: Any) -> bool:
    if data is None:
        return False
    if isinstance(data, dict):
        return any(has_payload_content(value) for value in data.values())
    if isinstance(data, list):
        return any(has_payload_content(value) for value in data)
    if isinstance(data, str):
        return bool(data.strip())
    return True


# ========
# Defines compact markdown context function for this module workflow.
# ========
def compact_markdown_context(markdown: Any) -> Dict[str, Any]:
    text = str(markdown or "").strip()
    if not text:
        return {"content": ""}

    headings: List[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"^#{1,4}\s+", stripped):
            headings.append(stripped)

    return {
        "content": text,
        "headings": headings,
        "truncated": False,
        "source_length": len(text),
    }


# ========
# Defines save optional json path function for this module workflow.
# ========
def save_optional_json_path(base_dir: Path, data: Any, path: Path) -> None:
    if has_payload_content(data):
        save_json_path(base_dir, data, path)
        return
    path.unlink(missing_ok=True)


# ========
# Defines stakeholder record function for this module workflow.
# ========
def stakeholder_record(row: Any) -> Dict[str, Any]:
    if not isinstance(row, dict):
        return {"name": "", "text": [str(row).strip()] if str(row).strip() else []}
    text = row.get("text")
    if isinstance(text, list):
        text_rows = [str(x).strip() for x in text if str(x).strip()]
    else:
        text_rows = []
    record = {
        "name": str(row.get("name") or row.get("id") or "").strip(),
        "text": list(dict.fromkeys(text_rows)),
    }
    stakeholder_type = str(row.get("type") or "").strip()
    if stakeholder_type:
        record["type"] = stakeholder_type
    return record


STAKEHOLDER_TYPES = (
    "primary_user",
    "system_owner",
    "external_party",
)

# ========
# Defines stakeholder group function for this module workflow.
# ========
def stakeholder_group(row: Dict[str, Any]) -> str:
    stakeholder_type = str(row.get("type") or "").strip()
    if stakeholder_type in STAKEHOLDER_TYPES:
        return stakeholder_type
    raise ValueError(f"stakeholder type invalid: {stakeholder_type or '<empty>'}")


# ========
# Defines scenario payload function for this module workflow.
# ========
def scenario_payload(data: Any) -> str:
    return str(data or "").strip()


# ========
# Defines project payload function for this module workflow.
# ========
def project_payload(data: Dict[str, Any], existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    stakeholders: List[Dict[str, Any]] = []
    for item in data.get("stakeholders", []) or []:
        row = stakeholder_record(item)
        if not row.get("name") and not row.get("text"):
            continue
        stakeholders.append({
            "name": row.get("name", ""),
            "type": stakeholder_group(item if isinstance(item, dict) else row),
            "text": row.get("text", []),
        })
    existing_rough_idea = (
        str(existing.get("rough_idea") or "").strip()
        if isinstance(existing, dict)
        else ""
    )
    rough_idea = existing_rough_idea or str(data.get("rough_idea") or "").strip()
    scenario = scenario_payload(data.get("scenario", ""))
    if not scenario and isinstance(existing, dict):
        scenario = scenario_payload(existing.get("scenario", ""))
    if not stakeholders and isinstance(existing, dict):
        stakeholders = stakeholder_rows(existing)
    return {
        "rough_idea": rough_idea,
        "scenario": scenario,
        "stakeholders": stakeholders,
    }


# ========
# Defines stakeholder rows function for this module workflow.
# ========
def stakeholder_rows(payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("stakeholders"), list):
        rows = []
        for item in payload.get("stakeholders", []) or []:
            row = stakeholder_record(item)
            row["type"] = stakeholder_group(item if isinstance(item, dict) else row)
            rows.append(row)
        return rows
    return []


# ========
# Defines scope payload function for this module workflow.
# ========
def scope_payload(data: Dict[str, Any]) -> Dict[str, List[Any]]:
    scope = data.get("scope") if isinstance(data.get("scope"), dict) else {}
    payload = {
        "in_scope": scope.get("in_scope", []) or [],
        "out_of_scope": scope.get("out_of_scope", []) or [],
    }
    return payload if has_payload_content(payload) else {}


# ========
# Defines stakeholder names function for this module workflow.
# ========
def stakeholder_names(data: Dict[str, Any]) -> set[str]:
    names = set()
    for item in data.get("stakeholders", []) or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            names.add(name)
    return names


# ========
# Defines requirement candidates function for this module workflow.
# ========
def requirement_candidates(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen = set()
    for item in data.get("URL", []) or []:
        if not isinstance(item, dict):
            continue
        marker = str(item.get("text") or "").strip().lower()
        if not marker:
            marker = str(item.get("id") or "").strip()
        if marker in seen:
            continue
        seen.add(marker)
        row = requirement_payload(item)
        if row:
            rows.append(row)
    return rows


# ========
# Defines requirement payload function for this module workflow.
# ========
def requirement_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for key in (
        "id",
        "text",
        "stakeholder",
        "source",
        "source_id",
    ):
        value = row.get(key)
        if value not in (None, "", []):
            if key == "stakeholder" and isinstance(value, dict):
                stakeholder = {
                    "name": str(value.get("name") or "").strip(),
                    "type": str(value.get("type") or "").strip(),
                }
                if stakeholder["name"] or stakeholder["type"]:
                    payload[key] = stakeholder
            else:
                payload[key] = value
    return payload


# ========
# Defines requirement payload rows function for this module workflow.
# ========
def requirement_payload_rows(rows: Any, *, active_only: bool = False) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        if active_only and str(item.get("status") or "").strip().lower() == "superseded":
            continue
        row = requirement_payload(item)
        if row:
            out.append(row)
    return out


# ========
# Defines system requirement payload function for this module workflow.
# ========
def system_requirement_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for key in (
        "id",
        "title",
        "type",
        "priority",
        "description",
        "rationale",
    ):
        value = row.get(key)
        if value not in (None, "", [], {}):
            payload[key] = value
    if not str(payload.get("description") or "").strip():
        req_id = str(payload.get("id") or row.get("id") or "").strip()
        raise ValueError(f"REQ description 缺失: {req_id or '(missing id)'}")
    req_type = str(payload.get("type") or "").strip().lower().replace("_", "-")
    if req_type in {"functional", "non-functional", "constraint"}:
        payload["type"] = req_type
    else:
        req_id = str(payload.get("id") or row.get("id") or "").strip()
        raise ValueError(f"REQ type 不合法: {req_id or '(missing id)'}")
    priority = str(payload.get("priority") or "").strip().lower()
    if priority in {"must", "should", "could"}:
        payload["priority"] = priority
    elif "priority" in payload:
        req_id = str(payload.get("id") or row.get("id") or "").strip()
        raise ValueError(f"REQ priority 不合法: {req_id or '(missing id)'}")
    source_rows: List[str] = []
    value = row.get("source")
    if isinstance(value, list):
        source_rows.extend(str(item).strip() for item in value if str(item).strip())
    else:
        text = str(value or "").strip()
        if text:
            source_rows.append(text)
    if source_rows:
        payload["source"] = list(dict.fromkeys(source_rows))
    if payload.get("type") == "non-functional":
        for key in ("category", "metric", "validation"):
            value = str(row.get(key) or "").strip()
            if value:
                payload[key] = value
    for key in (
        "acceptance_criteria",
        "dependencies",
        "risks",
        "assumptions",
    ):
        value = row.get(key)
        if isinstance(value, list):
            rows = [str(item).strip() for item in value if str(item).strip()]
            if rows:
                payload[key] = rows
    return payload


# ========
# Defines split system requirement payload function for this module workflow.
# ========
def split_system_requirement_payload(data: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    sections = {"REQ": []}
    for item in data.get("REQ", []) or []:
        if not isinstance(item, dict):
            continue
        row = system_requirement_payload(item)
        if not row:
            continue
        sections["REQ"].append(row)
    return sections


# ========
# Defines system requirement rows from sections function for this module workflow.
# ========
def system_requirement_rows_from_sections(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in payload.get("REQ", []) or []:
        if not isinstance(item, dict):
            continue
        row = system_requirement_payload(item)
        req_type = str(row.get("type") or "").strip().lower().replace("_", "-")
        if req_type not in {"functional", "non-functional", "constraint"}:
            req_id = str(row.get("id") or "").strip()
            raise ValueError(f"REQ type 不合法: {req_id or '(missing id)'}")
        row["type"] = req_type
        rows.append(row)
    return rows


# ========
# Defines meeting resolution payload function for this module workflow.
# ========
def meeting_resolution_payload(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    status = str(data.get("status") or "").strip()
    summary = str(data.get("summary") or "").strip()
    decision = str(data.get("decision") or "").strip()
    needs_human = bool(data.get("needs_human"))
    if not any((status, summary, decision, needs_human)):
        return {}
    payload: Dict[str, Any] = {
        "summary": summary,
        "decision": decision,
    }
    if status:
        if status not in {"agreed", "human_decision"}:
            raise ValueError(f"resolution status 不合法: {status}")
        payload["status"] = status
    affected_conflict_ids = data.get("affected_conflict_ids", []) or []
    affected_requirement_ids = data.get("affected_requirement_ids", []) or []
    if affected_conflict_ids:
        payload["affected_conflict_ids"] = affected_conflict_ids
    if affected_requirement_ids:
        payload["affected_requirement_ids"] = affected_requirement_ids
    if status == "human_decision" or needs_human:
        payload["unresolved_points"] = data.get("unresolved_points", []) or []
        payload["needs_human"] = needs_human
        payload["options"] = data.get("options", []) or []
        payload["recommendation"] = data.get("recommendation", {}) or {}
    return payload


# ========
# Defines requirements payload function for this module workflow.
# ========
def requirements_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "URL": requirement_payload_rows(data.get("URL", []) or [], active_only=True),
    }
    for key, rows in split_system_requirement_payload(data).items():
        if rows:
            payload[key] = rows
    return payload


# ========
# Defines conflict requirement ids function for this module workflow.
# ========
def conflict_requirement_ids(item: Dict[str, Any]) -> List[str]:
    req_ids = [
        str(req_id).strip()
        for req_id in (item.get("requirement_ids") or [])
        if str(req_id).strip()
    ]
    for req in item.get("requirements") or []:
        if not isinstance(req, dict):
            continue
        req_id = str(req.get("id") or "").strip()
        if req_id and req_id not in req_ids:
            req_ids.append(req_id)
    return req_ids


# ========
# Defines conflict output id function for this module workflow.
# ========
def conflict_output_id(prefix: str, index: int) -> str:
    return f"{prefix}-{index}"


# ========
# Defines requirement refs by id function for this module workflow.
# ========
def requirement_refs_by_id(data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows = requirement_candidates(data)
    rows.extend([
        row for row in (data.get("URL", []) or [])
        if isinstance(row, dict)
    ])
    refs: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        req_id = str(row.get("id") or "").strip()
        text = str(row.get("text") or "").strip()
        if not req_id or not text:
            continue
        ref: Dict[str, Any] = {"id": req_id, "text": text}
        stakeholder = row.get("stakeholder")
        stakeholder_name = (
            str(stakeholder.get("name") or "").strip()
            if isinstance(stakeholder, dict)
            else str(stakeholder or "").strip()
        )
        if stakeholder_name:
            ref["stakeholder"] = stakeholder_name
        refs[req_id] = ref
    return refs


# ========
# Defines conflict requirement refs function for this module workflow.
# ========
def conflict_requirement_refs(
    item: Dict[str, Any],
    req_refs: Dict[str, Dict[str, Any]],
) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for req_id in conflict_requirement_ids(item):
        ref = req_refs.get(req_id)
        if ref:
            out.append({
                "id": str(ref.get("id") or "").strip(),
                "text": str(ref.get("text") or "").strip(),
            })
        else:
            out.append({"id": req_id, "text": req_id})
    return [row for row in out if row.get("id") or row.get("text")]


# ========
# Defines conflict stakeholders function for this module workflow.
# ========
def conflict_stakeholders(
    item: Dict[str, Any],
    req_refs: Dict[str, Dict[str, Any]],
) -> List[str]:
    names: List[str] = []
    for req_id in conflict_requirement_ids(item):
        ref = req_refs.get(req_id) or {}
        name = str(ref.get("stakeholder") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


# ========
# Defines conflict requirements output function for this module workflow.
# ========
def conflict_requirements_output(
    row: Dict[str, Any],
    req_refs: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    out = dict(row)
    requirements = conflict_requirement_refs(out, req_refs)
    stakeholders = conflict_stakeholders(out, req_refs)
    out.pop("requirement_ids", None)
    out.pop("requirements", None)
    ordered: Dict[str, Any] = {}
    if "id" in out:
        ordered["id"] = out.pop("id")
    if requirements:
        ordered["requirements"] = requirements
    if stakeholders:
        ordered["stakeholders"] = stakeholders
    ordered.update(out)
    return ordered


# ========
# Defines conflict report row function for this module workflow.
# ========
def conflict_report_row(item: Dict[str, Any], req_refs: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    row = {}
    if "id" in item:
        row["id"] = item["id"]
    req_refs = req_refs or {}
    req_ids = conflict_requirement_ids(item)
    row_source = dict(item)
    if req_ids:
        row_source["requirement_ids"] = req_ids
    requirements = conflict_requirement_refs(row_source, req_refs)
    stakeholders = conflict_stakeholders(row_source, req_refs)
    if requirements:
        row["requirements"] = requirements
    if stakeholders:
        row["stakeholders"] = stakeholders
    meeting_row = {}
    if isinstance(item.get("meeting"), list) and item["meeting"] and isinstance(item["meeting"][0], dict):
        meeting_row = item["meeting"][0]
    final_label = str(
        item.get("final_label")
        or meeting_row.get("final_label")
        or item.get("label")
        or ""
    ).strip()
    if final_label:
        row["label"] = final_label
    conflict_type = str(
        item.get("final_type")
        or meeting_row.get("final_type")
        or item.get("initial_type")
        or item.get("type")
        or ""
    ).strip()
    if final_label == "Conflict" and conflict_type:
        row["type"] = conflict_type
    description = str(item.get("description") or meeting_row.get("description") or "").strip()
    if description:
        row["description"] = description
    resolution_options = item.get("resolution_options")
    if isinstance(resolution_options, list):
        row["resolution_options"] = resolution_options
    recommended_resolution = str(item.get("recommended_resolution") or "").strip()
    if recommended_resolution:
        row["recommended_resolution"] = recommended_resolution
    return row


# ========
# Defines reindex conflict report rows function for this module workflow.
# ========
def reindex_conflict_report_rows(rows: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for idx, row in enumerate(
        [item for item in (rows or []) if isinstance(item, dict)],
        1,
    ):
        item: Dict[str, Any] = {"id": f"CR-{idx}"}
        item.update({
            key: value
            for key, value in row.items()
            if key not in {"id", "source"}
        })
        out.append(item)
    return out


# ========
# Defines conflict requirement signature function for this module workflow.
# ========
def conflict_requirement_signature(item: Dict[str, Any]) -> str:
    req_ids = sorted(conflict_requirement_ids(item))
    if not req_ids:
        return ""
    return "REQSIG:" + "|".join(req_ids)


FINAL_CONFLICT_STATUSES = {"agreed", "human_decision"}


# ========
# Defines conflict report resolved function for this module workflow.
# ========
def conflict_report_resolved(item: Dict[str, Any]) -> bool:
    status = str(item.get("status") or "").strip().lower()
    return status in FINAL_CONFLICT_STATUSES


# ========
# Defines unresolved conflict report rows function for this module workflow.
# ========
def unresolved_conflict_report_rows(rows: Any, resolved_signatures: Optional[set[str]] = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    resolved: set[str] = set(resolved_signatures or set())
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        signature = conflict_requirement_signature(row)
        if conflict_report_resolved(row):
            if signature:
                resolved.add(signature)
            continue
        if signature and signature in resolved:
            continue
        if signature and signature in seen:
            continue
        if signature:
            seen.add(signature)
        out.append(dict(row))
    return out


# ========
# Defines merge conflict report history function for this module workflow.
# ========
def merge_conflict_report_history(versioned_rows: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
    unresolved_by_signature: Dict[str, Dict[str, Any]] = {}
    unresolved_without_signature: List[Dict[str, Any]] = []
    resolved_signatures: set[str] = set()

    for rows in versioned_rows:
        for row in rows:
            if not isinstance(row, dict):
                continue
            signature = conflict_requirement_signature(row)
            if conflict_report_resolved(row):
                if signature:
                    resolved_signatures.add(signature)
                    unresolved_by_signature.pop(signature, None)
                continue
            if signature:
                if signature in resolved_signatures:
                    continue
                unresolved_by_signature[signature] = dict(row)
            else:
                unresolved_without_signature.append(dict(row))

    return {
        "report": list(unresolved_by_signature.values()) + unresolved_without_signature,
        "resolved_signatures": sorted(resolved_signatures),
    }


# ========
# Defines flatten conflict meeting fields function for this module workflow.
# ========
def flatten_conflict_meeting_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    meeting = row.get("meeting")
    if isinstance(meeting, dict):
        cleaned_meeting: Dict[str, List[Dict[str, Any]]] = {}
        for round_key, review_rows in meeting.items():
            rows: List[Dict[str, Any]] = []
            for review in review_rows or []:
                if not isinstance(review, dict):
                    continue
                item = dict(review)
                item.pop("id", None)
                rows.append(item)
            if rows:
                cleaned_meeting[str(round_key)] = rows
        if cleaned_meeting:
            row["meeting"] = cleaned_meeting
        else:
            row.pop("meeting", None)
        return row
    if "meeting" in row:
        row.pop("meeting", None)
    ordered: Dict[str, Any] = {}
    for key, value in row.items():
        if key in {"meeting", "initial_label", "initial_type", "initial_reason", "final_label", "final_type", "description", "status"}:
            continue
        ordered[key] = value
    for key in ("initial_label", "initial_type", "initial_reason", "final_label", "final_type", "description", "status", "meeting"):
        if key in row:
            ordered[key] = row[key]
    return ordered


# ========
# Defines remove final item label function for this module workflow.
# ========
def remove_final_item_label(row: Dict[str, Any]) -> Dict[str, Any]:
    row.pop("label", None)
    return row


# ========
# Defines conflict pair payload function for this module workflow.
# ========
def conflict_pair_payload(rows: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    pair_num = 1
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        req_ids = conflict_requirement_ids(item)
        if len(req_ids) != 2:
            continue
        row = dict(item)
        new_id = conflict_output_id("PAIR", pair_num)
        pair_num += 1
        row["id"] = new_id
        row["requirements"] = [{"id": req_id} for req_id in req_ids]
        for key in (
            "requirement_ids",
            "review_focus",
            "conflict_review",
            "pair_index",
        ):
            row.pop(key, None)
        out.append(remove_final_item_label(flatten_conflict_meeting_fields(row)))
    return out


# ========
# Defines conflict multiple payload function for this module workflow.
# ========
def conflict_multiple_payload(rows: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    multiple_num = 1
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        req_ids = conflict_requirement_ids(item)
        if len(req_ids) < 2:
            continue
        label = str(item.get("final_label") or item.get("label") or "").strip()
        if label not in {"Conflict", "Neutral"}:
            continue
        new_id = conflict_output_id("MULTIPLE", multiple_num)
        multiple_num += 1
        row: Dict[str, Any] = {
            "id": new_id,
            "requirements": [{"id": req_id} for req_id in req_ids],
        }
        row["label"] = label
        if isinstance(item.get("meeting"), dict) and item["meeting"]:
            row["meeting"] = item["meeting"]
        description = str(item.get("description") or "").strip()
        if description:
            row["description"] = description
        out.append(remove_final_item_label(flatten_conflict_meeting_fields(row)))
    return out


# ========
# Defines conflict payload function for this module workflow.
# ========
def conflict_payload(data: Dict[str, Any], *, include_report: bool = False) -> Dict[str, Any]:
    state = data.get("conflict") if isinstance(data.get("conflict"), dict) else {}
    pairs = state.get("pairs") or []
    multiple = state.get("multiple") or []
    pair_payload = conflict_pair_payload(pairs)
    multiple_payload = conflict_multiple_payload(multiple)
    req_refs = requirement_refs_by_id(data)
    pair_payload = [
        conflict_requirements_output(row, req_refs)
        for row in pair_payload
    ]
    multiple_payload = [
        conflict_requirements_output(row, req_refs)
        for row in multiple_payload
    ]
    payload = {
        "pairs": pair_payload,
    }
    if multiple_payload:
        payload["multiple"] = multiple_payload
    if not include_report:
        return payload if has_payload_content(payload) else {}

    report_rows: List[Dict[str, Any]] = []
    source_rows = list(pairs) + list(multiple)
    source_by_id = {
        str(item.get("id") or "").strip(): item
        for item in source_rows
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    report_sources: List[Dict[str, Any]] = []
    seen_report_signatures: set[str] = set()
    for item in list(pair_payload) + list(multiple_payload):
        signature = conflict_requirement_signature(item)
        if signature and signature in seen_report_signatures:
            continue
        if signature:
            seen_report_signatures.add(signature)
        report_sources.append(item)
    for report_index, item in enumerate(report_sources, 1):
        source = source_by_id.get(str(item.get("id") or "").strip(), item)
        report_source = {**source, **item}
        conflict_id = str(item.get("id") or "").strip()
        if conflict_id:
            report_source["source_id"] = conflict_id
        report_source["id"] = f"CR-{report_index}"
        report_source.pop("requirement_ids", None)
        report_rows.append(conflict_report_row(report_source, req_refs))
    payload["report"] = report_rows
    return payload if has_payload_content(payload) else {}


# ========
# Defines conflict storage payload function for this module workflow.
# ========
def conflict_storage_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    payload = conflict_payload(data, include_report=False)
    if not isinstance(payload, dict):
        return {}
    return {
        key: value
        for key, value in payload.items()
        if key in {"pairs", "multiple"} and value not in (None, "", [], {})
    }


# ========
# Defines conflict runtime state function for this module workflow.
# ========
def conflict_runtime_state(conflict_payload: Any) -> Dict[str, List[Dict[str, Any]]]:
    if not isinstance(conflict_payload, dict):
        return {"report": [], "pairs": [], "multiple": []}
    def runtime_row(item: Dict[str, Any]) -> Dict[str, Any]:
        row = dict(item)
        req_ids = conflict_requirement_ids(row)
        if req_ids:
            row["requirement_ids"] = req_ids
        return row

    report = [
        runtime_row(item) for item in (conflict_payload.get("report", []) or [])
        if isinstance(item, dict)
    ]
    pairs = [
        runtime_row(item) for item in (conflict_payload.get("pairs", []) or [])
        if isinstance(item, dict)
    ]
    multiple = [
        runtime_row(item) for item in (conflict_payload.get("multiple", []) or [])
        if isinstance(item, dict)
    ]
    return {"report": report, "pairs": pairs, "multiple": multiple}


# ========
# Defines latest conflict report payload function for this module workflow.
# ========
def conflict_report_history_state(artifact_dir: Path) -> Dict[str, Any]:
    report_dir = artifact_dir / "report"
    if not report_dir.exists():
        return {"report": [], "resolved_signatures": []}
    versioned_paths: List[tuple[int, Path]] = []
    for path in report_dir.glob("conflict_report_v*.json"):
        stem = path.stem
        raw_version = stem[len("conflict_report_v"):]
        if not raw_version.isdigit():
            continue
        versioned_paths.append((int(raw_version), path))
    if not versioned_paths:
        return {"report": [], "resolved_signatures": []}
    versioned_paths.sort(key=lambda item: item[0])
    history: List[List[Dict[str, Any]]] = []
    for _, path in versioned_paths:
        payload = load_json_path(path, [])
        if not isinstance(payload, list):
            continue
        history.append([dict(item) for item in payload if isinstance(item, dict)])
    return merge_conflict_report_history(history)


# ========
# Defines latest conflict report payload function for this module workflow.
# ========
def latest_conflict_report_payload(artifact_dir: Path) -> List[Dict[str, Any]]:
    state = conflict_report_history_state(artifact_dir)
    return [dict(item) for item in (state.get("report") or []) if isinstance(item, dict)]


# ========
# Defines elicitation payload function for this module workflow.
# ========
def elicitation_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    elicitation = data.get("elicitation") if isinstance(data.get("elicitation"), dict) else {}
    plan = elicitation.get("plan", {}) or {}
    meeting_rows = elicitation.get("meeting", {})
    if not isinstance(meeting_rows, dict):
        meeting_rows = {}
    return {
        "plan": {
            "round_limit": plan.get("round_limit"),
            "participants": plan.get("participants", []) or [],
            "mode": plan.get("mode", ""),
        },
        "meeting": meeting_rows,
        "elicited_reqts": requirement_payload_rows(elicitation.get("elicited_reqts", []) or []),
        "elicitation_stop_reason": elicitation.get("elicitation_stop_reason", ""),
    }


# ========
# Defines discussions payload function for this module workflow.
# ========
def discussions_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    def clean_discussion_item(item: Any) -> Dict[str, Any]:
        if not isinstance(item, dict):
            return {}
        row_item: Dict[str, Any] = {}
        if item.get("meeting_id") not in (None, ""):
            row_item["meeting_id"] = item.get("meeting_id")
        if item.get("issue_id") not in (None, ""):
            row_item["issue_id"] = item.get("issue_id")
        category = str(item.get("category") or "").strip()
        if category:
            row_item["category"] = category
        proposed_by = str(item.get("proposed_by") or "").strip()
        if proposed_by:
            row_item["proposed_by"] = proposed_by
        participants = item.get("participants")
        if isinstance(participants, list) and participants:
            row_item["participants"] = participants
        discussion_mode = str(item.get("discussion_mode") or "").strip()
        if discussion_mode:
            row_item["discussion_mode"] = discussion_mode
        conversation = item.get("conversation")
        if isinstance(conversation, list) and conversation:
            row_item["conversation"] = conversation
        resolution = meeting_resolution_payload(item.get("resolution"))
        if resolution:
            row_item["resolution"] = resolution
        return row_item

    discussions = data.get("discussions", {}) or {}
    if isinstance(discussions, dict):
        out: Dict[str, Any] = {}
        for key, rows in discussions.items():
            if not isinstance(rows, list):
                continue
            cleaned = [
                clean_discussion_item(item)
                for item in rows
            ]
            out[str(key)] = [item for item in cleaned if item]
        return out
    out: Dict[str, Any] = {}
    for row in discussions:
        if not isinstance(row, dict):
            continue
        try:
            key = f"r{int(row.get('round') or len(out) + 1)}"
        except (TypeError, ValueError):
            key = f"r{len(out) + 1}"
        rows: List[Dict[str, Any]] = []
        for item in row.get("issues", []) or []:
            row_item = clean_discussion_item(item)
            if not row_item:
                continue
            rows.append(row_item)
        out[key] = rows
    return out


# ========
# Defines formal meeting payloads function for this module workflow.
# ========
def formal_meeting_payloads(data: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    discussions = discussions_payload(data)
    payloads: Dict[str, List[Dict[str, Any]]] = {}
    for round_key, rows in discussions.items():
        if not isinstance(rows, list):
            continue
        clean_rows = [row for row in rows if isinstance(row, dict)]
        if not clean_rows:
            continue
        raw_num = round_key[1:] if round_key.startswith("r") else round_key
        filename = f"formal_meeting_r{raw_num}.json"
        payloads[filename] = clean_rows
    return payloads


# ========
# Defines models payload function for this module workflow.
# ========
def models_payload(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    models = data.get("system_models", []) or []
    if not isinstance(models, list):
        return []
    rows: List[Dict[str, Any]] = []
    for index, model in enumerate(models, 1):
        if not isinstance(model, dict):
            continue
        row = {
            "id": f"SM-{index}",
            "name": str(model.get("name") or "").strip(),
            "type": str(model.get("type") or "").strip(),
        }
        if model.get("plantuml"):
            row["plantuml"] = str(model.get("plantuml") or "").strip()
        if model.get("image_path"):
            row["image_path"] = str(model.get("image_path") or "").strip()
        related_requirement_ids = [
            str(value).strip()
            for value in (model.get("related_requirement_ids") or [])
            if str(value).strip()
        ]
        if related_requirement_ids:
            row["related_requirement_ids"] = related_requirement_ids
        if model.get("description"):
            row["description"] = str(model.get("description") or "").strip()
        if isinstance(model.get("text"), list):
            row["text"] = [
                dict(item) for item in model.get("text", [])
                if isinstance(item, dict)
            ]
        row["source"] = str(model.get("source") or "").strip()
        rows.append(row)
    return rows


# ========
# Defines issue proposals payload function for this module workflow.
# ========
def issue_proposals_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    agent_rows: Dict[str, List[Dict[str, Any]]] = {}
    keep_keys = (
        "issue_id",
        "title",
        "expect_outcome",
        "sources",
        "importance",
        "reason",
        "proposed_by",
        "expected_actions",
    )
    for item in data.get("issue_proposals", []) or []:
        if not isinstance(item, dict):
            continue
        full_row = dict(item)
        if not str(full_row.get("issue_id") or "").strip():
            raise ValueError("issue proposal 缺少 issue_id")
        row = {}
        for key in keep_keys:
            value = full_row.get(key)
            if value in (None, "", [], {}):
                continue
            row[key] = value
        try:
            round_num = int(full_row.get("round") or 1)
        except (TypeError, ValueError):
            round_num = 1
        agent_rows.setdefault(f"r{round_num}", []).append(row)
    if agent_rows:
        out["agents"] = agent_rows
    meeting_rows: Dict[str, List[Dict[str, Any]]] = {}
    meeting_keep_keys = (
        "id",
        "title",
        "category",
        "participants",
        "discussion_mode",
        "discussion_rounds",
        "target_stakeholders",
        "trace",
        "proposed_by",
        "expected_actions",
        "meeting_id",
        "completed",
    )
    for item in data.get("meeting_issues", []) or []:
        if not isinstance(item, dict):
            continue
        row = {}
        for key in meeting_keep_keys:
            value = item.get(key)
            if value in (None, "", [], {}):
                continue
            row[key] = value
        if not row:
            continue
        try:
            round_num = int(item.get("round") or 1)
        except (TypeError, ValueError):
            round_num = 1
        meeting_rows.setdefault(f"r{round_num}", []).append(row)
    if meeting_rows:
        out["meeting_issues"] = meeting_rows
    return out


# ========
# Defines feedback payload function for this module workflow.
# ========
def feedback_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    feedback = data.get("feedback") if isinstance(data.get("feedback"), dict) else {}
    return dict(feedback)


# ========
# Defines feedback dict function for this module workflow.
# ========
def feedback_dict(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    return {}


# ========
# Defines load formal meeting discussions function for this module workflow.
# ========
def load_formal_meeting_discussions(artifact_dir: Path) -> Dict[str, List[Dict[str, Any]]]:
    meeting_dir = artifact_dir / "meeting"
    out: Dict[str, List[Dict[str, Any]]] = {}

    def merge(path: Path, payload: Any) -> None:
        if not isinstance(payload, list):
            return
        raw_num = path.stem[len("formal_meeting_r"):]
        key = f"r{raw_num}"
        out.setdefault(key, []).extend(
            row for row in payload if isinstance(row, dict)
        )

    for path in sorted(meeting_dir.glob("formal_meeting_r*.json")):
        merge(path, load_json_path(path, []))
    return out


# ========
# Defines split payload function for this module workflow.
# ========
def split_payload(artifact_dir: Path) -> Optional[Dict[str, Any]]:
    project_file = artifact_dir / "project.json"
    requirements_file = artifact_dir / "requirements.json"
    if not any(path.exists() for path in (project_file, requirements_file)):
        return None

    project = load_json_path(project_file, {})
    scope = load_json_path(artifact_dir / "scope.json", None)
    requirements = load_json_path(requirements_file, {})
    conflict_file_payload = load_json_path(artifact_dir / "conflict.json", None)
    conflict_report_state = conflict_report_history_state(artifact_dir)
    conflict_report = [
        dict(item) for item in (conflict_report_state.get("report") or [])
        if isinstance(item, dict)
    ]
    resolved_conflict_signatures = [
        str(value).strip()
        for value in (conflict_report_state.get("resolved_signatures") or [])
        if str(value).strip()
    ]
    feedback = feedback_dict(load_json_path(artifact_dir / "feedback.json", {}))
    elicitation = load_json_path(artifact_dir / "meeting" / "elicitation_meeting.json", {})
    discussions = load_formal_meeting_discussions(artifact_dir)
    issues_path = artifact_dir / "meeting" / "issues.json"
    issues = load_json_path(issues_path, {})
    models = load_json_path(artifact_dir / "system_models.json", [])
    issue_rows = []
    meeting_issue_rows = []
    if issues_path.exists() and not isinstance(issues, dict):
        raise ValueError("issues.json 必須是 object")
    issue_iter = []
    agent_sections = issues.get("agents")
    if isinstance(agent_sections, dict):
        for key, rows in agent_sections.items():
            try:
                round_num = int(str(key)[1:]) if str(key).startswith("r") else int(key)
            except (TypeError, ValueError):
                round_num = None
            for item in rows if isinstance(rows, list) else []:
                issue_iter.append((round_num, item))
    meeting_issue_section = issues.get("meeting_issues")
    if isinstance(meeting_issue_section, dict):
        for key, rows in meeting_issue_section.items():
            try:
                round_num = int(str(key)[1:]) if str(key).startswith("r") else int(key)
            except (TypeError, ValueError):
                round_num = None
            for item in rows if isinstance(rows, list) else []:
                if not isinstance(item, dict):
                    continue
                row = dict(item)
                if round_num is not None:
                    row["round"] = round_num
                meeting_issue_rows.append(row)
    elif isinstance(meeting_issue_section, list):
        meeting_issue_rows.extend(
            dict(item) for item in meeting_issue_section if isinstance(item, dict)
        )
    for round_num, item in issue_iter:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        if not str(row.get("issue_id") or "").strip():
            raise ValueError("issue proposal 缺少 issue_id")
        if round_num is not None:
            row["round"] = round_num
        issue_rows.append(row)

    stakeholder_list = stakeholder_rows(project)
    artifact: Dict[str, Any] = {
        "rough_idea": (
            project.get("rough_idea", "")
            if isinstance(project, dict) and project.get("rough_idea")
            else ""
        ),
        "scenario": scenario_payload(project.get("scenario", "")),
        "stakeholders": stakeholder_list,
        "feedback": feedback,
        "URL": requirement_payload_rows(requirements.get("URL", []) or []),
        "REQ": system_requirement_rows_from_sections(requirements),
        "elicitation": {
            "plan": elicitation.get("plan", {}) or {},
            "meeting": elicitation.get("meeting", {}) or {},
            "elicited_reqts": requirement_payload_rows(elicitation.get("elicited_reqts", []) or []),
            "elicitation_stop_reason": elicitation.get("elicitation_stop_reason", ""),
        },
        "discussions": [
            {
                "round": int(key[1:])
                if str(key).startswith("r") and str(key)[1:].isdigit()
                else idx,
                "issues": rows,
            }
            for idx, (key, rows) in enumerate((discussions or {}).items(), 1)
        ],
        "issue_proposals": issue_rows,
        "meeting_issues": meeting_issue_rows,
        "system_models": models if isinstance(models, list) else [],
    }
    if isinstance(scope, dict) and has_payload_content(scope):
        artifact["scope"] = scope
    if isinstance(conflict_file_payload, dict) and has_payload_content(conflict_file_payload):
        conflict_state = conflict_runtime_state(conflict_file_payload)
        if conflict_report:
            conflict_state["report"] = conflict_report
        if resolved_conflict_signatures:
            conflict_state["resolved_signatures"] = resolved_conflict_signatures
        artifact["conflict"] = conflict_state
    elif conflict_report:
        artifact["conflict"] = {
            "report": conflict_report,
            "pairs": [],
            "multiple": [],
            "resolved_signatures": resolved_conflict_signatures,
        }
    elif resolved_conflict_signatures:
        artifact["conflict"] = {
            "report": [],
            "pairs": [],
            "multiple": [],
            "resolved_signatures": resolved_conflict_signatures,
        }
    return artifact


# ========
# Defines load artifact function for this module workflow.
# ========
def load_artifact(artifact_dir: Path) -> Optional[Dict[str, Any]]:
    return split_payload(artifact_dir)


# ========
# Defines save artifact function for this module workflow.
# ========
def save_artifact(base_dir: Path, artifact_dir: Path, data: Dict[str, Any]) -> None:
    try:
        from .requirements import renumber_system_requirement_ids

        renumber_system_requirement_ids(data)
    except Exception as exc:
        raise RuntimeError("儲存 artifact 前整理 REQ id 失敗") from exc

    artifact_dir.mkdir(parents=True, exist_ok=True)
    meeting_dir = artifact_dir / "meeting"
    project_path = artifact_dir / "project.json"
    existing_project = load_json_path(project_path, {})
    save_json_path(base_dir, project_payload(data, existing_project), project_path)
    save_optional_json_path(base_dir, scope_payload(data), artifact_dir / "scope.json")
    save_json_path(base_dir, requirements_payload(data), artifact_dir / "requirements.json")
    save_optional_json_path(base_dir, conflict_storage_payload(data), artifact_dir / "conflict.json")
    save_optional_json_path(base_dir, feedback_payload(data), artifact_dir / "feedback.json")
    save_optional_json_path(base_dir, elicitation_payload(data), meeting_dir / "elicitation_meeting.json")
    for pattern in ("formal_meeting_r*.json",):
        for path in meeting_dir.glob(pattern):
            path.unlink(missing_ok=True)
    meeting_payloads = formal_meeting_payloads(data)
    for filename, payload in meeting_payloads.items():
        save_optional_json_path(base_dir, payload, meeting_dir / filename)
    if any(key in data for key in ("issue_proposals", "meeting_issues")):
        save_optional_json_path(base_dir, issue_proposals_payload(data), meeting_dir / "issues.json")
    save_optional_json_path(base_dir, models_payload(data), artifact_dir / "system_models.json")


# ========
# Defines save draft function for this module workflow.
# ========
def save_draft(artifact_dir: Path, content: str, version: int) -> None:
    drafts_dir = artifact_dir / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    path = drafts_dir / f"draft_v{version}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# ========
# Defines get draft version function for this module workflow.
# ========
def get_draft_version(artifact_dir: Path) -> int:
    max_v = -1
    if not artifact_dir.exists():
        return max_v
    draft_dir = artifact_dir / "drafts"
    if not draft_dir.exists():
        return max_v
    for f in draft_dir.iterdir():
        if not f.name.startswith("draft_v") or not f.name.endswith(".md"):
            continue
        try:
            v = int(f.name[len("draft_v") : -len(".md")])
            max_v = max(max_v, v)
        except ValueError:
            pass
    return max_v


# ========
# Defines load draft function for this module workflow.
# ========
def load_draft(artifact_dir: Path, version: int) -> Optional[str]:
    path = artifact_dir / "drafts" / f"draft_v{version}.md"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
