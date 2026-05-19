# Shared requirement candidate review, merge helpers, and final meeting checks.
import re
from typing import Any, Dict, List

from .conflict_store import all_conflict_rows, requirement_ids


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
    return artifact.get("URL", []) or []


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


def requirement_discussion_pool(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return formal requirements if available, otherwise candidate requirements for pre-final discussion."""
    requirements = [
        dict(row)
        for row in artifact.get("requirements", []) or []
        if isinstance(row, dict) and str(row.get("text") or "").strip()
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


def attach_initial_source_refs(
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
        if str(row.get("source") or "").strip() == "initial" and not str(row.get("source_ref") or "").strip():
            stakeholder = row.get("stakeholder")
            stakeholder_name = (
                str(stakeholder.get("name") or "").strip()
                if isinstance(stakeholder, dict)
                else str(stakeholder or "").strip()
            )
            source_ref = stakeholder_by_name.get(stakeholder_name)
            if source_ref:
                row["source_ref"] = source_ref
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


def assess_requirements_for_final_meeting(
    artifact: Dict[str, Any],
    *,
    round_num: int,
) -> Dict[str, Any]:
    requirements = [
        req for req in (artifact.get("requirements", []) or [])
        if isinstance(req, dict)
    ]
    unresolved_conflict_req_ids = set()
    for conflict in all_conflict_rows(artifact):
        if not isinstance(conflict, dict):
            continue
        if str(conflict.get("label") or "").strip() != "Conflict":
            continue
        for rid in requirement_ids(conflict):
            rid_s = str(rid or "").strip()
            if rid_s:
                unresolved_conflict_req_ids.add(rid_s)

    pending_decision_req_ids = set()
    for row in artifact.get("pending_decisions", []) or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "").strip() not in {"pending", "pending_confirmation"}:
            continue
        for rid in row.get("affected_requirement_ids", []) or []:
            rid_s = str(rid or "").strip()
            if rid_s:
                pending_decision_req_ids.add(rid_s)

    reasons: Dict[str, str] = {}
    needs_followup = 0
    for req in requirements:
        rid = str(req.get("id") or "").strip()
        missing = []
        if not rid:
            missing.append("id")
        if not str(req.get("text") or "").strip():
            missing.append("text")
        stakeholder = req.get("stakeholder")
        stakeholder_name = (
            str(stakeholder.get("name") or "").strip()
            if isinstance(stakeholder, dict)
            else str(stakeholder or "").strip()
        )
        if not stakeholder_name:
            missing.append("stakeholder")
        if not str(req.get("source") or "").strip():
            missing.append("source")
        if rid in unresolved_conflict_req_ids:
            missing.append("unresolved_conflict")
        if rid in pending_decision_req_ids:
            missing.append("pending_decision")

        if missing:
            req["final_meeting_round"] = round_num
            req["final_meeting_note"] = "Final meeting 仍需確認：" + ", ".join(missing)
            needs_followup += 1
        else:
            req["final_meeting_round"] = round_num
            req["final_meeting_note"] = "Final meeting 已完成全員確認。"
        if rid:
            reasons[rid] = req.get("final_meeting_note", "")

    summary = {
        "round": round_num,
        "confirmed_count": len(requirements) - needs_followup,
        "needs_followup_count": needs_followup,
        "total_requirements": len(requirements),
        "reasons": reasons,
    }
    artifact["final_meeting_summary"] = summary
    return summary
