# Shared requirement candidate review and merge helpers.
import re
from typing import Any, Dict, List


def requirement_dedupe_key(text: str) -> str:
    value = str(text or "").strip().lower()
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[。．.！!？?；;，,、]+$", "", value)
    return value


def requirement_candidate(
    candidate: Dict[str, Any],
) -> Dict[str, Any]:
    out = dict(candidate) if isinstance(candidate, dict) else {}
    return out


def candidate_pool(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        row for row in (artifact.get("URL", []) or [])
        if isinstance(row, dict)
        and str(row.get("status") or "").strip().lower() != "superseded"
    ]


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


def requirement_discussion_pool(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return formal requirements if available, otherwise candidate requirements for pre-final discussion."""
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


def build_initial_requirement_candidates_from_stakeholders(
    stakeholders: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Create coarse User Requirement candidates from stakeholder statements when extraction returns none."""
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
            texts = [str(text).strip() for text in raw_texts if str(text).strip()]
        else:
            text = str(raw_texts or "").strip()
            texts = [text] if text else []
        for text in texts:
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
                }
            )
    return ensure_requirement_candidate_ids(candidates)


def neutralize_stakeholder_requirement_text(text: str, stakeholder_name: str) -> str:
    value = str(text or "").strip()
    name = str(stakeholder_name or "").strip()
    if not value or not name:
        return value
    value = re.sub(r"^\s*我(需要|希望|想要|擔心|要求|必須|可以|能夠|能)\s*", f"{name}\\1", value)
    value = re.sub(r"^\s*我們(需要|希望|想要|擔心|要求|必須|可以|能夠|能)\s*", f"{name}\\1", value)
    return value


def attach_initial_source_ids(
    requirements: List[Dict[str, Any]],
    stakeholders: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    stakeholder_by_name = {
        str(row.get("name") or "").strip(): str(row.get("id") or "").strip()
        for row in stakeholders or []
        if isinstance(row, dict)
        and str(row.get("name") or "").strip()
        and str(row.get("id") or "").strip()
    }
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
            source_id = stakeholder_by_name.get(stakeholder_name)
            if source_id:
                row["source_id"] = source_id
        out.append(row)
    return out


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
