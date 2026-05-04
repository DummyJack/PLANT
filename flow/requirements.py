# Shared requirement status, candidate review, and merge helpers.
import re
from typing import Any, Dict, List


VALID_REQUIREMENT_STATUSES = {"unverified", "verified"}


def normalize_requirement_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    if status in VALID_REQUIREMENT_STATUSES:
        return status
    if status in {"approved", "baselined"}:
        return "verified"
    return "unverified"


def normalize_requirement_statuses(requirements: List[Dict[str, Any]]) -> Dict[str, int]:
    stats = {"status_normalized": 0}
    for req in requirements or []:
        if not isinstance(req, dict):
            continue
        before = str(req.get("status") or "").strip().lower()
        after = normalize_requirement_status(before)
        if before != after:
            stats["status_normalized"] += 1
        req["status"] = after
    return stats


def normalize_requirement_candidate(
    candidate: Dict[str, Any],
    *,
    candidate_source: str,
) -> Dict[str, Any]:
    out = dict(candidate) if isinstance(candidate, dict) else {}
    out.setdefault("candidate_source", candidate_source)
    return out


def build_requirement_candidates_from_requirements(
    requirements: List[Dict[str, Any]],
    *,
    candidate_source: str,
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for row in requirements or []:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        cand = normalize_requirement_candidate(
            row,
            candidate_source=candidate_source,
        )
        candidates.append(cand)
    return candidates


def review_requirement_candidates_before_merge(
    artifact: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    *,
    stage: str,
    round_num: int,
    candidate_source: str,
) -> Dict[str, Any]:
    normalized = [
        normalize_requirement_candidate(
            cand,
            candidate_source=candidate_source,
        )
        for cand in (candidates or [])
        if isinstance(cand, dict) and str(cand.get("text") or "").strip()
    ]
    return {
        "candidates": normalized,
    }


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


def merge_requirement_candidates(
    requirements: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
    *,
    source_round: int,
) -> Dict[str, int]:
    existing_texts = {
        str(req.get("text") or "").strip().lower()
        for req in requirements or []
        if isinstance(req, dict) and str(req.get("text") or "").strip()
    }
    existing_ids = {
        str(req.get("id") or "").strip()
        for req in requirements or []
        if isinstance(req, dict) and str(req.get("id") or "").strip()
    }
    added = 0
    skipped_duplicate = 0
    skipped_invalid = 0
    for cand in candidates or []:
        if not isinstance(cand, dict):
            skipped_invalid += 1
            continue
        text = str(cand.get("text") or "").strip()
        if not text:
            skipped_invalid += 1
            continue
        key = text.lower()
        if key in existing_texts:
            skipped_duplicate += 1
            continue
        req = dict(cand)
        rid = str(req.get("id") or "").strip()
        if not rid or rid in existing_ids:
            rid = next_requirement_id(requirements)
        candidate_source = str(req.get("candidate_source") or req.get("source") or "").strip()
        req["id"] = rid
        req["text"] = text
        req["status"] = "unverified"
        req.pop("candidate_source", None)
        if not str(req.get("source") or "").strip():
            req["source"] = "elicitation" if "elicitation" in candidate_source else (candidate_source or "candidate_review")
        if "elicitation" in candidate_source or str(req.get("source") or "").strip() == "elicitation":
            req["elicitation_round"] = source_round
        requirements.append(req)
        existing_texts.add(key)
        existing_ids.add(rid)
        added += 1
    return {
        "added": added,
        "skipped_duplicate": skipped_duplicate,
        "skipped_invalid": skipped_invalid,
    }


def verify_requirements_for_final_round(
    artifact: Dict[str, Any],
    *,
    round_num: int,
) -> Dict[str, Any]:
    requirements = [
        req for req in (artifact.get("requirements", []) or [])
        if isinstance(req, dict)
    ]
    unresolved_conflict_req_ids = set()
    for conflict in artifact.get("conflicts", []) or []:
        if not isinstance(conflict, dict):
            continue
        if str(conflict.get("label") or "").strip() != "Conflict":
            continue
        for rid in conflict.get("requirement_ids", []) or []:
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

    verified = 0
    unverified = 0
    reasons: Dict[str, str] = {}
    for req in requirements:
        rid = str(req.get("id") or "").strip()
        missing = []
        if not rid:
            missing.append("id")
        if not str(req.get("text") or "").strip():
            missing.append("text")
        if not str(req.get("verification_method") or "").strip():
            missing.append("verification_method")
        if not str(req.get("acceptance_criteria") or "").strip():
            missing.append("acceptance_criteria")
        if rid in unresolved_conflict_req_ids:
            missing.append("unresolved_conflict")
        if rid in pending_decision_req_ids:
            missing.append("pending_decision")

        if missing:
            req["status"] = "unverified"
            req["verification_round"] = round_num
            req["verification_reason"] = "未通過需求驗證：" + ", ".join(missing)
            unverified += 1
        else:
            req["status"] = "verified"
            req["verification_round"] = round_num
            req["verification_reason"] = "最後正式會議完成需求驗證。"
            verified += 1
        if rid:
            reasons[rid] = req.get("verification_reason", "")

    summary = {
        "round": round_num,
        "verified_count": verified,
        "unverified_count": unverified,
        "total_requirements": len(requirements),
        "reasons": reasons,
    }
    artifact["requirement_verification_summary"] = summary
    return summary
