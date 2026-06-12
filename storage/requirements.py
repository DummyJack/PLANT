# Handles requirements logic for project artifact storage and file export behavior.
import re
from typing import Any, Dict, List, Tuple



# ========
# Defines requirement dedupe key function for this module workflow.
# ========
def requirement_dedupe_key(text: str) -> str:
    value = str(text or "").strip().lower()
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[。．.！!？?；;，,、]+$", "", value)
    return value


# ========
# Defines requirement candidate function for this module workflow.
# ========
def requirement_candidate(
    candidate: Dict[str, Any],
) -> Dict[str, Any]:
    out = dict(candidate) if isinstance(candidate, dict) else {}
    return out


# ========
# Defines candidate pool function for this module workflow.
# ========
def candidate_pool(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        row for row in (artifact.get("URL", []) or [])
        if isinstance(row, dict)
        and str(row.get("status") or "").strip().lower() != "superseded"
    ]


# ========
# Defines requirement candidate id function for this module workflow.
# ========
def requirement_candidate_id(candidates: List[Dict[str, Any]]) -> str:
    max_num = 0
    for row in candidates or []:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("id") or "").strip()
        m = re.fullmatch(r"URL-(\d+)", cid)
        if not m:
            continue
        try:
            max_num = max(max_num, int(m.group(1)))
        except ValueError:
            continue
    return f"URL-{max_num + 1}"


# ========
# Defines ensure requirement candidate ids function for this module workflow.
# ========
def ensure_requirement_candidate_ids(
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    seen_ids = set()
    for item in candidates or []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        cid = str(row.get("id") or "").strip()
        if not re.fullmatch(r"URL-\d+", cid) or cid in seen_ids:
            cid = requirement_candidate_id(normalized)
        row["id"] = cid
        row["text"] = text
        seen_ids.add(cid)
        normalized.append(row)
    return normalized


# ========
# Defines renumber requirement candidate ids function for this module workflow.
# ========
def renumber_requirement_candidate_ids(
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for index, item in enumerate(candidates or [], 1):
        if not isinstance(item, dict):
            continue
        row = dict(item)
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        row["id"] = f"URL-{index}"
        row["text"] = text
        normalized.append(row)
    return normalized


# ========
# Defines requirement discussion pool function for this module workflow.
# ========
def requirement_discussion_pool(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    requirements = [
        dict(row)
        for row in artifact.get("URL", []) or []
        if isinstance(row, dict) and str(row.get("text") or "").strip()
        and str(row.get("status") or "").strip().lower() != "superseded"
    ]
    if requirements:
        return requirements
    candidates: List[Dict[str, Any]] = []
    seen = set()
    elicitation = artifact.get("elicitation") if isinstance(artifact.get("elicitation"), dict) else {}
    for rows in (
        candidate_pool(artifact),
        elicitation.get("elicited_reqts", []) or [],
    ):
        for item in rows:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            marker = requirement_dedupe_key(text)
            if marker in seen:
                continue
            seen.add(marker)
            candidates.append(dict(item))
    return ensure_requirement_candidate_ids(candidates)


# ========
# Defines build requirement candidates from requirements function for this module workflow.
# ========
def build_requirement_candidates_from_requirements(
    requirements: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for row in requirements or []:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        cand = requirement_candidate(row)
        candidates.append(cand)
    return ensure_requirement_candidate_ids(candidates)


# ========
# Defines build initial requirement candidates from stakeholders function for this module workflow.
# ========
def build_initial_requirement_candidates_from_stakeholders(
    stakeholders: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    seen = set()
    for stakeholder in stakeholders or []:
        if not isinstance(stakeholder, dict):
            continue
        stakeholder_name = str(stakeholder.get("name") or "").strip()
        if not stakeholder_name:
            continue
        stakeholder_type = str(stakeholder.get("type") or "").strip()
        raw_texts = stakeholder.get("text") or []
        if isinstance(raw_texts, list):
            statement_rows = [
                (
                    {"id": str(item.get("id") or "").strip(), "text": str(item.get("text") or "").strip()}
                    if isinstance(item, dict)
                    else {"id": "", "text": str(item).strip()}
                )
                for item in raw_texts
            ]
        else:
            text = str(raw_texts or "").strip()
            statement_rows = [{"id": "", "text": text}] if text else []
        statement_rows = [row for row in statement_rows if row.get("text")]
        for statement in statement_rows:
            text = str(statement.get("text") or "").strip()
            neutral_text = neutralize_stakeholder_requirement_text(text, stakeholder_name)
            marker = requirement_dedupe_key(f"{stakeholder_name}:{neutral_text}")
            if not marker or marker in seen:
                continue
            seen.add(marker)
            candidates.append(
                {
                    "text": neutral_text,
                    "stakeholder": {
                        "name": stakeholder_name,
                        "type": stakeholder_type,
                    },
                    "source": "initial",
                    "source_id": str(statement.get("id") or "").strip(),
                }
            )
    return ensure_requirement_candidate_ids(candidates)


# ========
# Defines neutralize stakeholder requirement text function for this module workflow.
# ========
def neutralize_stakeholder_requirement_text(text: str, stakeholder_name: str) -> str:
    value = str(text or "").strip()
    name = str(stakeholder_name or "").strip()
    if not value or not name:
        return value
    value = re.sub(r"^\s*我(需要|希望|想要|擔心|要求|必須|可以|能夠|能)\s*", f"{name}\\1", value)
    value = re.sub(r"^\s*我們(需要|希望|想要|擔心|要求|必須|可以|能夠|能)\s*", f"{name}\\1", value)
    return value


# ========
# Defines attach initial source ids function for this module workflow.
# ========
def attach_initial_source_ids(
    requirements: List[Dict[str, Any]],
    stakeholders: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    statement_by_text = {}
    for stakeholder in stakeholders or []:
        if not isinstance(stakeholder, dict):
            continue
        stakeholder_name = str(stakeholder.get("name") or "").strip()
        for statement in stakeholder.get("text") or []:
            if not isinstance(statement, dict):
                continue
            statement_id = str(statement.get("id") or "").strip()
            statement_text = str(statement.get("text") or "").strip()
            if not stakeholder_name or not statement_id or not statement_text:
                continue
            neutral_text = neutralize_stakeholder_requirement_text(statement_text, stakeholder_name)
            statement_by_text[(stakeholder_name, requirement_dedupe_key(neutral_text))] = statement_id
    out: List[Dict[str, Any]] = []
    for req in requirements or []:
        row = dict(req)
        if str(row.get("source") or "").strip() == "initial" and not str(row.get("source_id") or "").strip():
            stakeholder = row.get("stakeholder")
            stakeholder_name = (
                str(stakeholder.get("name") or "").strip()
                if isinstance(stakeholder, dict)
                else str(stakeholder or "").strip()
            )
            req_text_key = requirement_dedupe_key(str(row.get("text") or ""))
            source_id = statement_by_text.get((stakeholder_name, req_text_key))
            if source_id:
                row["source_id"] = source_id
        out.append(row)
    return out


# ========
# Defines next requirement id function for this module workflow.
# ========
def next_requirement_id(requirements: List[Dict[str, Any]]) -> str:
    max_num = 0
    for req in requirements or []:
        if not isinstance(req, dict):
            continue
        rid = str(req.get("id") or "").strip()
        m = re.fullmatch(r"REQ-(\d+)", rid)
        if not m:
            continue
        try:
            max_num = max(max_num, int(m.group(1)))
        except ValueError:
            continue
    return f"REQ-{max_num + 1}"


# ========
# Defines replace system requirement refs function for this module workflow.
# ========
def replace_system_requirement_refs(value: Any, mapping: Dict[str, str]) -> Any:
    if not mapping:
        return value
    if isinstance(value, dict):
        return {
            key: replace_system_requirement_refs(item, mapping)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [replace_system_requirement_refs(item, mapping) for item in value]
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            token = match.group(0)
            return mapping.get(token, token)

        return re.sub(r"\bREQ-\d+\b", replace, value)
    return value


# ========
# Defines renumber system requirement ids function for this module workflow.
# ========
def renumber_system_requirement_ids(artifact: Dict[str, Any]) -> Dict[str, str]:
    rows = [
        row for row in (artifact.get("REQ") or [])
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    ]
    mapping: Dict[str, str] = {}
    for index, row in enumerate(rows, 1):
        old_id = str(row.get("id") or "").strip()
        new_id = f"REQ-{index}"
        if old_id != new_id:
            mapping[old_id] = new_id
    if not mapping:
        clean_invalid_system_requirement_refs(artifact)
        return {}

    updated = replace_system_requirement_refs(artifact, mapping)
    if isinstance(updated, dict):
        artifact.clear()
        artifact.update(updated)
    clean_invalid_system_requirement_refs(artifact)
    return mapping


# ========
# Defines clean invalid system requirement refs function for this module workflow.
# ========
def clean_invalid_system_requirement_refs(artifact: Dict[str, Any]) -> None:
    valid_req_ids = {
        str(row.get("id") or "").strip()
        for row in (artifact.get("REQ") or [])
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }
    if not valid_req_ids:
        return
    for model in artifact.get("system_models") or []:
        if not isinstance(model, dict):
            continue
        def ref_sort_key(value: str) -> Tuple[int, Any]:
            match = re.fullmatch(r"REQ-(\d+)", value)
            if match:
                return (0, int(match.group(1)))
            return (1, value)

        def clean_ref_list(values: Any) -> List[str]:
            cleaned: List[str] = []
            if not isinstance(values, list):
                return cleaned
            for req_id in (str(value).strip() for value in values):
                if not req_id:
                    continue
                if req_id.startswith("REQ-") and req_id not in valid_req_ids:
                    continue
                if req_id not in cleaned:
                    cleaned.append(req_id)
            return sorted(cleaned, key=ref_sort_key)

        if isinstance(model.get("related_requirement_ids"), list):
            model["related_requirement_ids"] = clean_ref_list(model.get("related_requirement_ids"))
        for row in model.get("text") or []:
            if isinstance(row, dict) and isinstance(row.get("related_requirement_ids"), list):
                row["related_requirement_ids"] = clean_ref_list(row.get("related_requirement_ids"))


# ========
# Defines assign stable SRS ids function for this module workflow.
# ========
def assign_stable_srs_ids(artifact: Dict[str, Any]) -> None:
    counters = {"functional": 0, "non-functional": 0, "constraint": 0}
    prefixes = {
        "functional": "FR",
        "non-functional": "NFR",
        "constraint": "CON",
    }
    for row in artifact.get("REQ") or []:
        if not isinstance(row, dict):
            continue
        req_type = str(row.get("type") or "").strip().lower().replace("_", "-")
        if req_type not in counters:
            continue
        counters[req_type] += 1
        row["srs_id"] = f"{prefixes[req_type]}-{counters[req_type]}"
