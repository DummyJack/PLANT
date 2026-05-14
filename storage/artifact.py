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
    for key in ("requirements", "goals", "concerns"):
        value = row.get(key)
        if isinstance(value, list):
            text_rows.extend(str(x).strip() for x in value if str(x).strip())
        elif str(value or "").strip():
            text_rows.append(str(value).strip())
    return {
        "name": str(row.get("name") or row.get("id") or "").strip(),
        "text": list(dict.fromkeys(text_rows)),
    }


STAKEHOLDER_GROUPS = (
    "Primary Users",
    "System Owners & Management",
    "External Parties",
)

def stakeholder_group(row: Dict[str, Any]) -> str:
    category = str(row.get("category") or row.get("group") or "").strip()
    if category in STAKEHOLDER_GROUPS:
        return category
    return "Primary Users"


def stakeholders_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    grouped: Dict[str, List[Dict[str, Any]]] = {key: [] for key in STAKEHOLDER_GROUPS}
    for item in data.get("stakeholders", []) or []:
        row = stakeholder_record(item)
        if not row.get("name") and not row.get("text"):
            continue
        grouped[stakeholder_group(item if isinstance(item, dict) else row)].append(row)
    return {
        "rough_idea": data.get("rough_idea", ""),
        **grouped,
    }


def stakeholder_rows(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [stakeholder_record(row) for row in payload]
    if not isinstance(payload, dict):
        return []
    rows: List[Dict[str, Any]] = []
    for group in STAKEHOLDER_GROUPS:
        for item in payload.get(group, []) or []:
            row = stakeholder_record(item)
            row["category"] = group
            rows.append(row)
    return rows


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


def combined_requirement_candidates(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen = set()
    elicitation = data.get("elicitation") if isinstance(data.get("elicitation"), dict) else {}
    sources = [
        data.get("reqt_candidates", []) or [],
        elicitation.get("elicited_reqts", []) or [],
    ]
    for source_rows in sources:
        for item in source_rows:
            if not isinstance(item, dict):
                continue
            marker = str(item.get("text") or item.get("statement") or "").strip().lower()
            if not marker:
                marker = str(item.get("id") or "").strip()
            if marker in seen:
                continue
            seen.add(marker)
            row = dict(item)
            clean_requirement_fields(row, allowed_source_stakeholders=stakeholder_names(data))
            rows.append(row)
    return rows


def clean_requirement_fields(
    row: Dict[str, Any],
    *,
    allowed_source_stakeholders: Optional[set[str]] = None,
) -> None:
    for key in (
        "verification_method",
        "status",
        "rationale",
        "final_meeting_round",
        "final_meeting_note",
        "readiness_round",
        "readiness_reason",
        "baseline_version",
    ):
        row.pop(key, None)
    if allowed_source_stakeholders is not None:
        values = row.get("source_stakeholders")
        if not isinstance(values, list):
            values = [values] if values not in (None, "") else []
        filtered = []
        for value in values:
            name = str(value or "").strip()
            if name and name in allowed_source_stakeholders and name not in filtered:
                filtered.append(name)
        row["source_stakeholders"] = filtered


def requirement_payload_rows(
    rows: Any,
    *,
    allowed_source_stakeholders: Optional[set[str]] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        clean_requirement_fields(
            row,
            allowed_source_stakeholders=allowed_source_stakeholders,
        )
        out.append(row)
    return out


def change_record_payload(rows: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        if row.get("field") in {"verification_method", "status", "rationale"}:
            continue
        for key in ("before", "after"):
            if isinstance(row.get(key), dict):
                row[key] = dict(row[key])
                clean_requirement_fields(row[key])
        out.append(row)
    return out


def requirements_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    allowed_stakeholders = stakeholder_names(data)
    return {
        "reqt_candidates": combined_requirement_candidates(data),
        "change_record": change_record_payload(data.get("change_record", data.get("requirement_change_candidates", [])) or []),
        "requirements": requirement_payload_rows(
            data.get("requirements", []) or [],
            allowed_source_stakeholders=allowed_stakeholders,
        ),
    }


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
        description = str(
            item.get("description")
            or item.get("rationale")
            or item.get("reason")
            or ""
        ).strip()
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
    for item in meeting_rows or []:
        if not isinstance(item, dict):
            continue
        pair_id = mapped_pair_id(item.get("id", item.get("pair_id")), id_map)
        if not pair_id:
            continue
        label = meeting_final_labels.get(pair_id)
        if label not in {"Conflict", "Neutral"}:
            continue
        row = {
            "id": pair_id,
            "label": label,
        }
        description = meeting_descriptions.get(pair_id)
        if description:
            row["description"] = description
        reviewed_pairs.append(row)
    if reviewed_pairs:
        return reviewed_pairs

    out: List[Dict[str, Any]] = []
    for idx, item in enumerate(rows or [], 1):
        if not isinstance(item, dict):
            continue
        row = dict(item)
        old_id = str(row.get("id") or row.get("pair_id") or "").strip()
        new_id = id_map.get(old_id) or f"PAIR-{idx}"
        row["id"] = new_id
        row.pop("pair_id", None)
        for key in (
            "supplemented",
            "supplement_reason",
            "requirement_ids",
            "conflict_review",
            "pre_meeting_review",
            "resolved_by_decision_id",
            "pair_index",
            "conflict_type",
            "requirement_a",
            "requirement_b",
        ):
            row.pop(key, None)
        if meeting_final_labels.get(new_id):
            row["label"] = meeting_final_labels[new_id]
        if meeting_descriptions.get(new_id):
            row["description"] = meeting_descriptions[new_id]
        out.append(row)
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
        description = str(
            row.get("description")
            or row.get("rationale")
            or ""
        ).strip()
        row.pop("rationale", None)
        if description:
            row["description"] = description
        decided_by = str(row.pop("decided_by", "") or "").strip()
        if decided_by:
            row["status"] = decided_by
        meeting_review = row.pop("meeting_conflict_review", None)
        if isinstance(meeting_review, dict):
            cleaned_review: Dict[str, List[Dict[str, Any]]] = {}
            for round_key, review_rows in meeting_review.items():
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


def conflicts_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    pairs = data.get(
        "reqt_pairs",
        data.get("conflicting_reqt", data.get("conflicts", [])),
    ) or []
    meeting = data.get("conflict_meeting", data.get("pair_reviews", [])) or []
    id_map = extend_pair_id_map(normalized_pair_id_map(pairs), meeting)
    return {
        "reqt_pairs": conflict_pair_payload(pairs, meeting),
        "conflict_meeting": conflict_meeting_payload(meeting, id_map),
    }


def elicitation_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    elicitation = data.get("elicitation") if isinstance(data.get("elicitation"), dict) else {}
    plan = elicitation.get("plan", {}) or {}
    max_turns = plan.get("round_limit", plan.get("max_turns"))
    if max_turns is None:
        max_turns = data.get("elicitation_max_turns")
    meeting_rows = elicitation.get("meeting", {})
    if not isinstance(meeting_rows, dict):
        meeting_rows = {}
    return {
        "plan": {
            "round_limit": max_turns,
            "participants": plan.get("participants", []) or [],
            "mode": plan.get("mode", ""),
        },
        "meeting": meeting_rows,
        "elicited_reqts": requirement_payload_rows(
            elicitation.get("elicited_reqts", data.get("elicited_reqts", [])) or [],
            allowed_source_stakeholders=stakeholder_names(data),
        ),
        "elicitation_stop_reason": elicitation.get(
            "elicitation_stop_reason",
            data.get("elicitation_stop_reason", ""),
        ),
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
    if isinstance(models, dict):
        models = models.get("models", []) or []
    return models if isinstance(models, list) else []


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


def feedback_payload(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    feedback = data.get("feedback") if isinstance(data.get("feedback"), dict) else {}
    rows: List[Dict[str, Any]] = []
    domain_research = feedback.get("domain_research")
    if isinstance(domain_research, dict) and domain_research:
        row = dict(domain_research)
        row.pop("type", None)
        rows.append(row)
    for item in data.get("feedback_records", []) or []:
        if isinstance(item, dict):
            rows.append(dict(item))
    return rows


def is_domain_research_feedback(row: Dict[str, Any]) -> bool:
    domain_keys = {
        "findings",
        "sources",
        "derived_requirements",
        "compliance_risks",
        "binding_obligations",
        "risk_notes",
        "recommendations",
        "gaps_for_further_research",
    }
    return bool(domain_keys.intersection(row.keys()))


def feedback_dict(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    feedback: Dict[str, Any] = {}
    if not isinstance(payload, list):
        return feedback
    records: List[Dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        feedback_type = str(row.pop("type", "") or "").strip()
        if feedback_type == "domain_research" or (
            not feedback_type
            and "domain_research" not in feedback
            and is_domain_research_feedback(row)
        ):
            feedback["domain_research"] = row
        else:
            if feedback_type:
                row["type"] = feedback_type
            records.append(row)
    if records:
        feedback["records"] = records
    return feedback


def split_payload(artifact_dir: Path) -> Optional[Dict[str, Any]]:
    project_file = artifact_dir / "project.json"
    stakeholders_file = artifact_dir / "stakeholders.json"
    requirements_file = artifact_dir / "requirements.json"
    reqt_pairs_file = artifact_dir / "reqt_pairs.json"
    legacy_conflicts_file = artifact_dir / "conflicts.json"
    if not any(path.exists() for path in (stakeholders_file, project_file, requirements_file, reqt_pairs_file, legacy_conflicts_file)):
        return None

    project = load_json_path(project_file, {})
    stakeholders = load_json_path(
        stakeholders_file,
        project.get("stakeholders", []),
    )
    scope = load_json_path(
        artifact_dir / "scope.json",
        project.get("scope", {"in_scope": [], "out_of_scope": []}),
    )
    requirements = load_json_path(requirements_file, {})
    conflicts = load_json_path(
        reqt_pairs_file,
        load_json_path(legacy_conflicts_file, {}),
    )
    feedback = feedback_dict(load_json_path(artifact_dir / "feedback.json", []))
    elicitation = load_json_path(artifact_dir / "meeting" / "elicitation_meeting.json", {})
    discussions = load_json_path(artifact_dir / "meeting" / "discussions.json", {})
    decisions = load_json_path(artifact_dir / "meeting" / "decisions.json", [])
    issues = load_json_path(artifact_dir / "meeting" / "issues.json", [])
    models = load_json_path(artifact_dir / "models" / "system_models.json", [])
    issue_rows = []
    for item in issues if isinstance(issues, list) else []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row["issue_id"] = row.get("issue_id") or row.get("id")
        issue_rows.append(row)

    stakeholder_list = stakeholder_rows(stakeholders)
    allowed_stakeholders = {
        str(row.get("name") or "").strip()
        for row in stakeholder_list
        if str(row.get("name") or "").strip()
    }
    artifact: Dict[str, Any] = {
        "rough_idea": (
            stakeholders.get("rough_idea", "")
            if isinstance(stakeholders, dict)
            else project.get("rough_idea", "")
        ),
        "stakeholders": stakeholder_list,
        "scope": scope if isinstance(scope, dict) else {"in_scope": [], "out_of_scope": []},
        "feedback": feedback,
        "reqt_candidates": requirement_payload_rows(
            requirements.get("reqt_candidates", []) or [],
            allowed_source_stakeholders=allowed_stakeholders,
        ),
        "requirement_change_candidates": change_record_payload(requirements.get("change_record", []) or []),
        "requirements": requirement_payload_rows(
            requirements.get("requirements", []) or [],
            allowed_source_stakeholders=allowed_stakeholders,
        ),
        "conflicts": conflicts.get("reqt_pairs", conflicts.get("conflicting_reqt", [])) or [],
        "conflict_meeting": conflicts.get("conflict_meeting", []) or [],
        "pair_reviews": conflicts.get("conflict_meeting", []) or [],
        "elicitation": {
            "plan": elicitation.get("plan", {}) or {},
            "meeting": elicitation.get("meeting", {}) or {},
            "elicited_reqts": requirement_payload_rows(
                elicitation.get("elicited_reqts", []) or [],
                allowed_source_stakeholders=allowed_stakeholders,
            ),
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
        "system_models": {"models": models if isinstance(models, list) else []},
    }
    return artifact


def load_artifact(artifact_dir: Path) -> Optional[Dict[str, Any]]:
    return split_payload(artifact_dir)


def save_artifact(base_dir: Path, artifact_dir: Path, data: Dict[str, Any]) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    legacy_project_file = artifact_dir / "project.json"
    if legacy_project_file.exists():
        legacy_project_file.unlink()
    legacy_conflicts_file = artifact_dir / "conflicts.json"
    if legacy_conflicts_file.exists():
        legacy_conflicts_file.unlink()
    save_json_path(base_dir, stakeholders_payload(data), artifact_dir / "stakeholders.json")
    save_json_path(base_dir, scope_payload(data), artifact_dir / "scope.json")
    save_json_path(base_dir, feedback_payload(data), artifact_dir / "feedback.json")
    save_json_path(base_dir, requirements_payload(data), artifact_dir / "requirements.json")
    save_json_path(base_dir, conflicts_payload(data), artifact_dir / "reqt_pairs.json")
    save_json_path(base_dir, elicitation_payload(data), artifact_dir / "meeting" / "elicitation_meeting.json")
    save_json_path(base_dir, discussions_payload(data), artifact_dir / "meeting" / "discussions.json")
    save_json_path(base_dir, data.get("decisions", []) or [], artifact_dir / "meeting" / "decisions.json")
    save_json_path(base_dir, issue_proposals_payload(data), artifact_dir / "meeting" / "issues.json")
    save_json_path(base_dir, models_payload(data), artifact_dir / "models" / "system_models.json")


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
    draft_dirs = [artifact_dir / "drafts", artifact_dir]
    for draft_dir in draft_dirs:
        if not draft_dir.exists():
            continue
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
        path = artifact_dir / f"draft_v{version}.md"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
