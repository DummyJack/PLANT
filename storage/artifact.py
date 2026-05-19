# Artifact storage helpers: load/save split artifact files and draft markdown files.
import json

from pathlib import Path
from typing import Any, Dict, List, Optional

from .json import save_json_file


def load_json_path(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json_path(base_dir: Path, data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    save_json_file(base_dir, data, path)


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


STAKEHOLDER_GROUPS = (
    "Primary Users",
    "System Owners & Management",
    "External Parties",
)

def stakeholder_group(row: Dict[str, Any]) -> str:
    stakeholder_type = str(row.get("type") or "").strip()
    if stakeholder_type in STAKEHOLDER_GROUPS:
        return stakeholder_type
    return "Primary Users"


def scenario_payload(data: Any) -> Dict[str, Any]:
    if isinstance(data, dict):
        name = str(data.get("name") or "").strip()
    else:
        name = str(data or "").strip()
    return {
        "name": name,
        "application_type": "",
        "Category": {
            "primary_category": "",
            "subcategories": [],
        },
    }


def project_payload(data: Dict[str, Any]) -> Dict[str, Any]:
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
    return {
        "rough_idea": data.get("rough_idea", ""),
        "scenario": scenario_payload(data.get("scenario", {})),
        "stakeholders": stakeholders,
    }


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


def scope_payload(data: Dict[str, Any]) -> Dict[str, List[Any]]:
    scope = data.get("scope") if isinstance(data.get("scope"), dict) else {}
    return {
        "in_scope": scope.get("in_scope", []) or [],
        "out_of_scope": scope.get("out_of_scope", []) or [],
    }


def stakeholder_names(data: Dict[str, Any]) -> set[str]:
    names = set()
    for item in data.get("stakeholders", []) or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            names.add(name)
    return names


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


def requirement_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for key in ("id", "text", "priority", "stakeholder", "source", "source_ref"):
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


def requirement_payload_rows(rows: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        row = requirement_payload(item)
        if row:
            out.append(row)
    return out


def change_record_payload(rows: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        for key in ("before", "after"):
            if isinstance(row.get(key), dict):
                row[key] = requirement_payload(row[key])
        out.append(row)
    return out


def requirements_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "URL": requirement_candidates(data),
        "change_record": change_record_payload(data.get("change_record", []) or []),
        "requirements": requirement_payload_rows(data.get("requirements", []) or []),
    }


def conflict_requirement_ids(item: Dict[str, Any]) -> List[str]:
    req_ids = [
        str(req_id).strip()
        for req_id in (item.get("requirement_ids") or item.get("reqs") or [])
        if str(req_id).strip()
    ]
    for req in item.get("requirements") or []:
        if not isinstance(req, dict):
            continue
        req_id = str(req.get("id") or "").strip()
        if req_id and req_id not in req_ids:
            req_ids.append(req_id)
    idx = 1
    while True:
        value = str(item.get(f"req_{idx}") or "").strip()
        if not value:
            break
        if value not in req_ids:
            req_ids.append(value)
        idx += 1
    return req_ids


def conflict_output_id(prefix: str, index: int) -> str:
    return f"{prefix}-{index}"


def nested_meeting_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row.pop("id", None)
        out.append(row)
    return out


def requirement_refs_by_id(data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows = requirement_candidates(data)
    rows.extend([
        row for row in (data.get("requirements", []) or [])
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


def conflict_requirements_output(
    row: Dict[str, Any],
    req_refs: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    out = dict(row)
    requirements = conflict_requirement_refs(out, req_refs)
    stakeholders = conflict_stakeholders(out, req_refs)
    idx = 1
    while True:
        key = f"req_{idx}"
        if key not in out:
            break
        out.pop(key, None)
        idx += 1
    out.pop("requirement_ids", None)
    out.pop("reqs", None)
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


def conflict_report_row(item: Dict[str, Any], req_refs: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    row = {}
    if "id" in item:
        row["id"] = item["id"]
    req_refs = req_refs or {}
    req_ids = conflict_requirement_ids(item)
    if not req_ids and isinstance(item.get("meeting"), list) and item["meeting"]:
        first_meeting = item["meeting"][0]
        if isinstance(first_meeting, dict):
            req_ids = conflict_requirement_ids(first_meeting)
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
    conflict_type = str(item.get("final_type") or meeting_row.get("final_type") or "").strip()
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


def existing_report_enrichment(data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    state = data.get("conflict") if isinstance(data.get("conflict"), dict) else {}
    enrichment: Dict[str, Dict[str, Any]] = {}
    for item in state.get("report", []) or []:
        if not isinstance(item, dict):
            continue
        conflict_id = str(item.get("source_id") or item.get("id") or "").strip()
        if not conflict_id:
            continue
        row: Dict[str, Any] = {}
        if isinstance(item.get("resolution_options"), list):
            row["resolution_options"] = item["resolution_options"]
        recommended_resolution = str(item.get("recommended_resolution") or "").strip()
        if recommended_resolution:
            row["recommended_resolution"] = recommended_resolution
        if row:
            enrichment[conflict_id] = row
    return enrichment


def flatten_conflict_meeting_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    meeting = row.get("meeting")
    if not isinstance(meeting, list) or not meeting:
        return row
    first = meeting[0]
    if not isinstance(first, dict):
        row.pop("meeting", None)
        return row
    for key in ("initial_label", "initial_type", "initial_reason", "final_label", "final_type", "description", "status"):
        value = first.get(key)
        if value not in (None, ""):
            row[key] = value
    details = first.get("details")
    if isinstance(details, dict):
        cleaned_details: Dict[str, List[Dict[str, Any]]] = {}
        for round_key, review_rows in details.items():
            rows: List[Dict[str, Any]] = []
            for review in review_rows or []:
                if not isinstance(review, dict):
                    continue
                item = dict(review)
                item.pop("id", None)
                rows.append(item)
            cleaned_details[str(round_key)] = rows
        row["meeting"] = cleaned_details
    else:
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


def remove_final_item_label(row: Dict[str, Any]) -> Dict[str, Any]:
    row.pop("label", None)
    return row


def normalized_pair_id_map(rows: Any) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    idx = 1
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        old_id = str(item.get("id") or item.get("pair_id") or "").strip()
        if not old_id or old_id in mapping:
            continue
        mapping[old_id] = f"PAIR-{idx}"
        idx += 1
    return mapping


def mapped_pair_id(value: Any, id_map: Dict[str, str]) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return id_map.get(raw, raw)


def extend_pair_id_map(id_map: Dict[str, str], rows: Any) -> Dict[str, str]:
    mapping = dict(id_map)
    next_num = len(mapping) + 1
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        old_id = str(item.get("id") or item.get("pair_id") or "").strip()
        if not old_id or old_id in mapping:
            continue
        mapping[old_id] = f"PAIR-{next_num}"
        next_num += 1
    return mapping


def conflict_meeting_descriptions(rows: Any, id_map: Dict[str, str]) -> Dict[str, str]:
    descriptions: Dict[str, str] = {}
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        pair_id = mapped_pair_id(item.get("id", item.get("pair_id")), id_map)
        if not pair_id:
            continue
        description = str(item.get("description") or "").strip()
        if description:
            descriptions[pair_id] = description
    return descriptions


def conflict_meeting_final_labels(rows: Any, id_map: Dict[str, str]) -> Dict[str, str]:
    labels: Dict[str, str] = {}
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        pair_id = mapped_pair_id(item.get("id", item.get("pair_id")), id_map)
        if not pair_id:
            continue
        label = str(item.get("final_label") or "").strip()
        if label in {"Conflict", "Neutral"}:
            labels[pair_id] = label
    return labels


def conflict_pair_payload(rows: Any, meeting_rows: Any) -> List[Dict[str, Any]]:
    id_map = normalized_pair_id_map(rows)
    meeting_descriptions = conflict_meeting_descriptions(meeting_rows, id_map)
    meeting_final_labels = conflict_meeting_final_labels(meeting_rows, id_map)
    reviewed_pairs: List[Dict[str, Any]] = []
    pair_num = 1
    for item in meeting_rows or []:
        if not isinstance(item, dict):
            continue
        req_ids = conflict_requirement_ids(item)
        if len(req_ids) != 2:
            continue
        pair_id = conflict_output_id("PAIR", pair_num)
        pair_num += 1
        source_id = mapped_pair_id(item.get("id", item.get("pair_id")), id_map)
        if not source_id:
            continue
        label = meeting_final_labels.get(source_id)
        if label not in {"Conflict", "Neutral"}:
            continue
        row = {
            "id": pair_id,
            "requirements": [
                {"id": req_ids[0]},
                {"id": req_ids[1]},
            ],
            "label": label,
        }
        description = meeting_descriptions.get(source_id)
        if description:
            row["description"] = description
        meeting = conflict_meeting_payload([item], {str(item.get("id") or item.get("pair_id") or ""): pair_id})
        if meeting:
            row["meeting"] = nested_meeting_rows(meeting)
        reviewed_pairs.append(remove_final_item_label(flatten_conflict_meeting_fields(row)))
    if reviewed_pairs:
        return reviewed_pairs

    out: List[Dict[str, Any]] = []
    pair_num = 1
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        req_ids = conflict_requirement_ids(item)
        if len(req_ids) != 2:
            continue
        row = dict(item)
        old_id = str(row.get("id") or row.get("pair_id") or "").strip()
        new_id = conflict_output_id("PAIR", pair_num)
        pair_num += 1
        row["id"] = new_id
        row["requirements"] = [{"id": req_id} for req_id in req_ids]
        row.pop("pair_id", None)
        for key in (
            "requirement_ids",
            "review_focus",
            "conflict_review",
            "pair_index",
        ):
            row.pop(key, None)
        if meeting_final_labels.get(new_id):
            row["label"] = meeting_final_labels[new_id]
        if meeting_descriptions.get(new_id):
            row["description"] = meeting_descriptions[new_id]
        out.append(remove_final_item_label(flatten_conflict_meeting_fields(row)))
    return out


def conflict_multiple_payload(rows: Any, meeting_rows: Any) -> List[Dict[str, Any]]:
    id_map = normalized_pair_id_map(rows)
    meeting_descriptions = conflict_meeting_descriptions(meeting_rows, id_map)
    meeting_final_labels = conflict_meeting_final_labels(meeting_rows, id_map)
    out: List[Dict[str, Any]] = []
    multiple_num = 1
    source_rows = list(meeting_rows or []) or list(rows or [])
    for item in source_rows:
        if not isinstance(item, dict):
            continue
        req_ids = conflict_requirement_ids(item)
        if len(req_ids) < 3:
            continue
        source_id = mapped_pair_id(item.get("id", item.get("pair_id")), id_map)
        label = (
            meeting_final_labels.get(source_id)
            or str(item.get("final_label") or item.get("label") or "").strip()
        )
        if label not in {"Conflict", "Neutral"}:
            continue
        new_id = conflict_output_id("MULTIPLE", multiple_num)
        multiple_num += 1
        row: Dict[str, Any] = {"id": new_id}
        for idx, req_id in enumerate(req_ids, 1):
            row[f"req_{idx}"] = req_id
        row["label"] = label
        if isinstance(item.get("meeting"), list) and item["meeting"]:
            row["meeting"] = item["meeting"]
        description = meeting_descriptions.get(source_id) or str(item.get("description") or "").strip()
        if description:
            row["description"] = description
        meeting = []
        if item.get("details") or item.get("final_label") or item.get("initial_label"):
            meeting = conflict_meeting_payload([item], {str(item.get("id") or item.get("pair_id") or ""): new_id})
        if meeting:
            row["meeting"] = nested_meeting_rows(meeting)
        out.append(remove_final_item_label(flatten_conflict_meeting_fields(row)))
    return out


def conflict_meeting_payload(rows: Any, id_map: Dict[str, str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row["id"] = mapped_pair_id(row.get("id", row.get("pair_id")), id_map)
        row.pop("pair_id", None)
        row.pop("topic_id", None)
        for key in ("requirement_ids",):
            row.pop(key, None)
        description = str(row.get("description") or "").strip()
        if description:
            row["description"] = description
        details = row.get("details")
        if isinstance(details, dict):
            cleaned_review: Dict[str, List[Dict[str, Any]]] = {}
            for round_key, review_rows in details.items():
                cleaned_rows: List[Dict[str, Any]] = []
                for review in review_rows or []:
                    if not isinstance(review, dict):
                        continue
                    review_row = dict(review)
                    review_row.pop("id", None)
                    cleaned_rows.append(review_row)
                cleaned_review[str(round_key)] = cleaned_rows
            row["details"] = cleaned_review
        out.append(row)
    return out


def conflict_payload(data: Dict[str, Any], *, include_report: bool = False) -> Dict[str, Any]:
    state = data.get("conflict") if isinstance(data.get("conflict"), dict) else {}
    pairs = state.get("pairs") or []
    multiple = state.get("multiple") or []
    pair_payload = conflict_pair_payload(pairs, [])
    multiple_payload = conflict_multiple_payload(list(pairs) + list(multiple), [])
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
        "multiple": multiple_payload,
    }
    if not include_report:
        return payload

    report_rows: List[Dict[str, Any]] = []
    source_rows = list(pairs) + list(multiple)
    report_enrichment = existing_report_enrichment(data)
    source_by_id = {
        str(item.get("id") or "").strip(): item
        for item in source_rows
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    for report_index, item in enumerate(list(pair_payload) + list(multiple_payload), 1):
        source = source_by_id.get(str(item.get("id") or "").strip(), item)
        report_source = {**source, **item}
        conflict_id = str(item.get("id") or "").strip()
        if conflict_id in report_enrichment:
            report_source.update(report_enrichment[conflict_id])
        if conflict_id:
            report_source["source_id"] = conflict_id
        report_source["id"] = f"CR-{report_index}"
        report_source.pop("requirement_ids", None)
        report_source.pop("reqs", None)
        report_rows.append(conflict_report_row(report_source, req_refs))
    payload["report"] = report_rows
    return payload


def conflict_runtime_state(conflict_payload: Any) -> Dict[str, List[Dict[str, Any]]]:
    if not isinstance(conflict_payload, dict):
        return {"report": [], "pairs": [], "multiple": []}
    report = [
        dict(item) for item in (conflict_payload.get("report", []) or [])
        if isinstance(item, dict)
    ]
    pairs = [
        dict(item) for item in (conflict_payload.get("pairs", []) or [])
        if isinstance(item, dict)
    ]
    multiple = [
        dict(item) for item in (conflict_payload.get("multiple", []) or [])
        if isinstance(item, dict)
    ]
    return {"report": report, "pairs": pairs, "multiple": multiple}


def latest_conflict_report_payload(artifact_dir: Path) -> List[Dict[str, Any]]:
    report_dir = artifact_dir / "report"
    if not report_dir.exists():
        return []
    latest_path: Optional[Path] = None
    latest_version = -1
    for path in report_dir.glob("conflict_report_v*.json"):
        stem = path.stem
        raw_version = stem[len("conflict_report_v"):]
        if not raw_version.isdigit():
            continue
        version = int(raw_version)
        if version > latest_version:
            latest_version = version
            latest_path = path
    if latest_path is None:
        return []
    payload = load_json_path(latest_path, [])
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    return []


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


def discussions_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    discussions = data.get("discussions", {}) or {}
    if isinstance(discussions, dict):
        return discussions
    out: Dict[str, Any] = {}
    for row in discussions:
        if not isinstance(row, dict):
            continue
        if row.get("is_final_meeting"):
            key = "final"
        else:
            try:
                key = f"r{int(row.get('round') or len(out) + 1)}"
            except (TypeError, ValueError):
                key = f"r{len(out) + 1}"
        out[key] = row.get("issues", []) or []
    return out


def models_payload(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    models = data.get("system_models", []) or []
    if not isinstance(models, list):
        return []
    rows: List[Dict[str, Any]] = []
    for model in models:
        if not isinstance(model, dict):
            continue
        row = {
            "name": str(model.get("name") or "").strip(),
            "type": str(model.get("type") or "").strip(),
        }
        if model.get("plantuml"):
            row["plantuml"] = str(model.get("plantuml") or "").strip()
        if isinstance(model.get("text"), list):
            row["text"] = [
                dict(item) for item in model.get("text", [])
                if isinstance(item, dict)
            ]
        row["source"] = str(model.get("source") or "").strip()
        rows.append(row)
    return rows


def issue_proposals_payload(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for idx, item in enumerate(data.get("issue_proposals", []) or [], 1):
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row["id"] = row.get("id") or row.get("issue_id") or f"ISSUE-PRO-{idx}"
        row.pop("issue_id", None)
        rows.append(row)
    return rows


def feedback_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    feedback = data.get("feedback") if isinstance(data.get("feedback"), dict) else {}
    return dict(feedback)


def feedback_dict(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    return {}


def split_payload(artifact_dir: Path) -> Optional[Dict[str, Any]]:
    project_file = artifact_dir / "project.json"
    requirements_file = artifact_dir / "requirements.json"
    conflict_file = artifact_dir / "conflict.json"
    if not any(path.exists() for path in (project_file, requirements_file, conflict_file)):
        return None

    project = load_json_path(project_file, {})
    scope = load_json_path(
        artifact_dir / "scope.json",
        {"in_scope": [], "out_of_scope": []},
    )
    requirements = load_json_path(requirements_file, {})
    conflict_payload = load_json_path(conflict_file, {})
    conflict_report = latest_conflict_report_payload(artifact_dir)
    feedback = feedback_dict(load_json_path(artifact_dir / "feedback.json", {}))
    elicitation = load_json_path(artifact_dir / "meeting" / "elicitation_meeting.json", {})
    discussions = load_json_path(artifact_dir / "meeting" / "discussions.json", {})
    decisions = load_json_path(artifact_dir / "meeting" / "decisions.json", [])
    issues = load_json_path(artifact_dir / "meeting" / "issues.json", [])
    models = load_json_path(artifact_dir / "models" / "system_models.json", [])
    stage_status = load_json_path(artifact_dir / "stage_status.json", {})
    issue_rows = []
    for item in issues if isinstance(issues, list) else []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row["issue_id"] = row.get("issue_id") or row.get("id")
        issue_rows.append(row)

    stakeholder_list = stakeholder_rows(project)
    conflict_state = conflict_runtime_state(conflict_payload)
    conflict_state["report"] = conflict_report

    artifact: Dict[str, Any] = {
        "rough_idea": (
            project.get("rough_idea", "")
            if isinstance(project, dict) and project.get("rough_idea")
            else ""
        ),
        "scenario": scenario_payload(project.get("scenario", {})),
        "stakeholders": stakeholder_list,
        "scope": scope if isinstance(scope, dict) else {"in_scope": [], "out_of_scope": []},
        "feedback": feedback,
        "URL": requirement_payload_rows(requirements.get("URL", []) or []),
        "change_record": change_record_payload(requirements.get("change_record", []) or []),
        "requirements": requirement_payload_rows(requirements.get("requirements", []) or []),
        "conflict": conflict_state,
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
                "is_final_meeting": str(key) == "final",
            }
            for idx, (key, rows) in enumerate((discussions or {}).items(), 1)
        ],
        "decisions": decisions if isinstance(decisions, list) else [],
        "issue_proposals": issue_rows,
        "system_models": models if isinstance(models, list) else [],
        "stage_status": stage_status if isinstance(stage_status, dict) else {},
    }
    return artifact


def load_artifact(artifact_dir: Path) -> Optional[Dict[str, Any]]:
    return split_payload(artifact_dir)


def save_artifact(base_dir: Path, artifact_dir: Path, data: Dict[str, Any]) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    save_json_path(base_dir, project_payload(data), artifact_dir / "project.json")
    save_json_path(base_dir, scope_payload(data), artifact_dir / "scope.json")
    save_json_path(base_dir, feedback_payload(data), artifact_dir / "feedback.json")
    save_json_path(base_dir, requirements_payload(data), artifact_dir / "requirements.json")
    save_json_path(base_dir, conflict_payload(data), artifact_dir / "conflict.json")
    save_json_path(base_dir, elicitation_payload(data), artifact_dir / "meeting" / "elicitation_meeting.json")
    save_json_path(base_dir, discussions_payload(data), artifact_dir / "meeting" / "discussions.json")
    save_json_path(base_dir, data.get("decisions", []) or [], artifact_dir / "meeting" / "decisions.json")
    save_json_path(base_dir, issue_proposals_payload(data), artifact_dir / "meeting" / "issues.json")
    save_json_path(base_dir, models_payload(data), artifact_dir / "models" / "system_models.json")
    save_json_path(base_dir, data.get("stage_status", {}) or {}, artifact_dir / "stage_status.json")


def save_draft(artifact_dir: Path, content: str, version: int) -> None:
    """儲存需求草稿為 draft_v{version}.md（Markdown）到 artifact 目錄"""
    drafts_dir = artifact_dir / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    path = drafts_dir / f"draft_v{version}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def get_draft_version(artifact_dir: Path) -> int:
    """回傳目前已有的 draft 最大版本號；若無則回傳 -1"""
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


def load_draft(artifact_dir: Path, version: int) -> Optional[str]:
    """載入指定版本的 draft markdown"""
    path = artifact_dir / "drafts" / f"draft_v{version}.md"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
