# Support helpers for conflict review and requirement-change application.
import json
import re
from typing import Any, Dict, List, Optional

from agents.profile.analyst.conflict_store import all_conflict_rows, normalize_conflict_state
from agents.profile.analyst.requirements import next_requirement_id, requirement_discussion_pool

CONFLICT_ITEM_ID_RE = re.compile(
    r"\[((?:PAIR|MULTIPLE)[^\]]+)\]|\"id\"\s*:\s*\"((?:PAIR|MULTIPLE)[^\"]+)\"|\b((?:PAIR|MULTIPLE)-\d+)\b",
    re.IGNORECASE,
)
LABEL_RE = re.compile(r"\b(Conflict|Neutral)\b", re.IGNORECASE)
PROPOSED_LABEL_RE = re.compile(
    r"\bproposed_label\s*[:：]\s*(Conflict|Neutral)\b",
    re.IGNORECASE,
)
CONFIDENCE_FIELD_RE = re.compile(r"\bconfidence\s*[:：]\s*(high|medium|low)\b", re.IGNORECASE)
REASON_FIELD_RE = re.compile(r"\breason\s*[:：]\s*(.+)$", re.IGNORECASE)


def mark_conflicts_resolved_by_ids(
    artifact: Dict[str, Any],
    conflict_ids: List[str],
    *,
    decision_id: Optional[str] = None,
) -> None:
    if not conflict_ids:
        return
    target = {str(cid).strip() for cid in conflict_ids if str(cid).strip()}
    for c in all_conflict_rows(artifact):
        cid = str(c.get("id") or "").strip()
        if cid not in target:
            continue
        c["label"] = "Neutral"
        if decision_id:
            c["resolved_by_decision_id"] = decision_id
    normalize_conflict_state(artifact)

def pair_review_record(
    review: Dict[str, Any],
    *,
    pair_id_set: set[str],
    current_labels_by_id: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, Any]]:
    if not isinstance(review, dict):
        return None
    pair_id = str(review.get("id") or "").strip()
    if not pair_id or pair_id not in pair_id_set:
        return None
    proposed_label = str(review.get("proposed_label") or "").strip()
    reason = str(review.get("reason") or "").strip()
    confidence = str(review.get("confidence") or "").strip().lower()
    if proposed_label not in {"Conflict", "Neutral"}:
        proposed_label = ""
    if confidence not in {"high", "medium", "low"}:
        confidence = ""
    current_label = ""
    if current_labels_by_id:
        current_label = str(current_labels_by_id.get(pair_id) or "").strip()
    decision = ""
    if proposed_label and current_label in {"Conflict", "Neutral"}:
        decision = "keep" if proposed_label == current_label else "modify"
    return {
        "id": pair_id,
        "decision": decision,
        "proposed_label": proposed_label,
        "confidence": confidence,
        "reason": reason,
    }

def extract_pair_reviews_from_statement(
    statement: str,
    *,
    known_pair_ids: List[str],
    current_labels_by_id: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """從 agent statement 提取逐筆 pair review。

    舊版行為：優先解析 JSON；若 agent 輸出漂移成自然語言或行文字，仍盡量從文字抽出 pair id、
    label 與 reason，避免格式問題直接中斷審查。
    """
    text = str(statement or "").strip()
    if not text:
        return []

    pair_id_set = {str(x).strip() for x in (known_pair_ids or []) if str(x).strip()}
    reviews: List[Dict[str, Any]] = []

    try:
        parsed = json.loads(text)
    except Exception:
        parsed = None

    if isinstance(parsed, dict):
        raw_reviews = parsed.get("pair_reviews")
        if isinstance(raw_reviews, list):
            for raw_review in raw_reviews:
                normalized = pair_review_record(
                    raw_review,
                    pair_id_set=pair_id_set,
                    current_labels_by_id=current_labels_by_id,
                )
                if normalized:
                    reviews.append(normalized)
    if reviews:
        return reviews

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        pair_match = CONFLICT_ITEM_ID_RE.search(line)
        if not pair_match:
            continue
        pair_id = (
            pair_match.group(1)
            or pair_match.group(2)
            or pair_match.group(3)
            or ""
        ).strip()
        if not pair_id or pair_id not in pair_id_set:
            continue
        proposed_label_match = PROPOSED_LABEL_RE.search(line)
        confidence_match = CONFIDENCE_FIELD_RE.search(line)
        labels = [m.group(1) for m in LABEL_RE.finditer(line)]
        reason = line
        reason_match = REASON_FIELD_RE.search(line)
        if reason_match:
            reason = reason_match.group(1).strip() or line
        elif "理由" in line:
            reason = line.split("理由", 1)[-1].lstrip(":： ").strip() or line

        proposed_label = (
            proposed_label_match.group(1)
            if proposed_label_match
            else (labels[0] if labels else "")
        )
        normalized = pair_review_record(
            {
                "id": pair_id,
                "proposed_label": proposed_label,
                "confidence": (
                    confidence_match.group(1).lower()
                    if confidence_match
                    else ""
                ),
                "reason": reason,
            },
            pair_id_set=pair_id_set,
            current_labels_by_id=current_labels_by_id,
        )
        if normalized:
            reviews.append(normalized)

    seen = set()
    deduped: List[Dict[str, Any]] = []
    for review in reviews:
        key = (review.get("id"), review.get("decision"), review.get("proposed_label"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(review)
    return deduped


def normalize_conflict_review_statement_for_record(
    statement: str,
    *,
    known_pair_ids: List[str],
    current_labels_by_id: Optional[Dict[str, str]] = None,
) -> str:
    """將 conflict review 發言正規化成 review_summary + pair_reviews JSON 字串。"""
    text = str(statement or "").strip()
    if not text:
        return ""

    reviews = extract_pair_reviews_from_statement(
        text,
        known_pair_ids=known_pair_ids,
        current_labels_by_id=current_labels_by_id,
    )
    if not reviews:
        return text

    review_summary = ""
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        review_summary = str(
            parsed.get("review_summary") or parsed.get("overall_assessment") or ""
        ).strip()

    if not review_summary:
        first_pair = CONFLICT_ITEM_ID_RE.search(text)
        prefix = text[: first_pair.start()].strip() if first_pair else ""
        review_summary = re.sub(
            r"^(overall\s*[:,]?\s*)",
            "",
            prefix,
            flags=re.IGNORECASE,
        ).strip()

    return json.dumps(
        {
            "review_summary": review_summary,
            "pair_reviews": reviews,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )

def close_related_open_questions(
    artifact: Dict[str, Any],
    source_ids: List[str],
    *,
    round_num: int,
) -> None:
    if not source_ids:
        return
    source_set = {str(s).strip() for s in source_ids if str(s).strip()}
    for q in artifact.get("open_questions", []) or []:
        if q.get("status") == "answered":
            continue
        q_source_ids = {
            str(s).strip()
            for s in (q.get("source_ids") or [])
            if str(s).strip()
        }
        source_conflict = str(q.get("source_conflict_id") or "").strip()
        if source_conflict:
            q_source_ids.add(source_conflict)
        if not (source_set & q_source_ids):
            continue
        q["status"] = "answered"
        q["answered_round"] = round_num

def append_requirement_change_candidates(
    artifact: Dict[str, Any],
    change_candidates: List[Dict[str, Any]],
) -> None:
    if not isinstance(change_candidates, list) or not change_candidates:
        return
    existing = artifact.get("requirement_change_candidates", []) or []
    seen = {
        (
            item.get("change_type"),
            item.get("requirement_id"),
            item.get("field"),
            str(item.get("after")),
        )
        for item in existing
        if isinstance(item, dict)
    }
    meta = artifact.get("meta") or {}
    cur_round = int(meta.get("last_round") or 0)
    for candidate in change_candidates:
        if not isinstance(candidate, dict):
            continue
        key = (
            candidate.get("change_type"),
            candidate.get("requirement_id"),
            candidate.get("field"),
            str(candidate.get("after")),
        )
        if key in seen:
            continue
        candidate.setdefault("created_round", cur_round)
        existing.append(candidate)
        seen.add(key)
    artifact["requirement_change_candidates"] = existing

def requirement_text_key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()

def collect_discussion_rows(contributions: List[Dict[str, Any]]) -> list[dict]:
    """整理會議發言。"""
    discussion_rows: List[Dict[str, Any]] = []
    for c in contributions or []:
        if not isinstance(c, dict):
            continue
        resp = c.get("response") or {}
        statement = ""
        if isinstance(resp, dict):
            statement = (resp.get("statement") or resp.get("content") or "").strip()
        else:
            statement = str(resp).strip()
        agent_name = str(c.get("agent") or "").strip()
        if statement:
            discussion_rows.append({"agent": agent_name, "statement": statement})
    return discussion_rows

def collect_discussion_rows_and_pair_reviews(
    contributions: List[Dict[str, Any]],
    *,
    known_pair_ids: List[str],
    current_labels_by_id: Optional[Dict[str, str]] = None,
) -> tuple[list[dict], list[dict]]:
    discussion_rows = collect_discussion_rows(contributions)
    extracted_pair_reviews: List[Dict[str, Any]] = []
    for c in contributions or []:
        if not isinstance(c, dict):
            continue
        agent_name = str(c.get("agent") or "").strip()
        resp = c.get("response") or {}
        if isinstance(resp, dict):
            statement = (resp.get("statement") or resp.get("content") or "").strip()
        else:
            statement = str(resp).strip()
        raw_reviews = resp.get("pair_reviews") if isinstance(resp, dict) else None
        if isinstance(raw_reviews, list) and raw_reviews:
            pair_id_set = {str(x).strip() for x in known_pair_ids if str(x).strip()}
            for raw_review in raw_reviews:
                normalized = pair_review_record(
                    raw_review,
                    pair_id_set=pair_id_set,
                    current_labels_by_id=current_labels_by_id,
                )
                if normalized:
                    extracted_pair_reviews.append({"agent": agent_name, **normalized})
            continue
        for review in extract_pair_reviews_from_statement(
            statement,
            known_pair_ids=known_pair_ids,
            current_labels_by_id=current_labels_by_id,
        ):
            extracted_pair_reviews.append({"agent": agent_name, **review})
    return discussion_rows, extracted_pair_reviews

def apply_requirement_change_candidates(
    coordinator: Any,
    artifact: Dict[str, Any],
) -> Dict[str, Any]:
    requirements = [
        dict(req) for req in requirement_discussion_pool(artifact)
        if isinstance(req, dict)
    ]
    by_id = {req.get("id"): req for req in requirements if req.get("id")}
    applied_ids: List[str] = []
    pending_ids: List[str] = []
    skipped_duplicate_ids: List[str] = []
    candidates = artifact.get("requirement_change_candidates", []) or []

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        cid = candidate.get("id")
        change_type = candidate.get("change_type")
        field = candidate.get("field")
        req_id = candidate.get("requirement_id")
        status = (candidate.get("status") or "").strip()
        if status == "applied":
            if cid:
                applied_ids.append(cid)
            continue

        if change_type == "add":
            after = candidate.get("after")
            if not isinstance(after, dict):
                candidate["status"] = "pending_review"
                if cid:
                    pending_ids.append(cid)
                continue

            from agents.profile.analyst import AnalystAgent

            new_req = AnalystAgent.requirement_record(dict(after))
            text_key = requirement_text_key(new_req.get("text"))
            existing_texts = {
                requirement_text_key(req.get("text"))
                for req in requirements
                if isinstance(req, dict) and str(req.get("text") or "").strip()
            }
            if not text_key:
                candidate["status"] = "pending_review"
                if cid:
                    pending_ids.append(cid)
                continue
            if text_key in existing_texts:
                candidate["status"] = "skipped_duplicate"
                if cid:
                    skipped_duplicate_ids.append(cid)
                continue

            if not req_id or req_id in by_id:
                req_id = new_req.get("id") or next_requirement_id(requirements)
            if req_id in by_id:
                req_id = next_requirement_id(requirements)
            new_req["id"] = req_id
            requirements.append(new_req)
            by_id[req_id] = new_req
            candidate["requirement_id"] = req_id
            candidate["status"] = "applied"
            if cid:
                applied_ids.append(cid)
            continue

        if change_type == "update" and req_id in by_id:
            if field in {"text", "priority", "acceptance_criteria"}:
                proposed_req = dict(by_id[req_id])
                proposed_req[field] = candidate.get("after")
                by_id[req_id][field] = candidate.get("after")
                candidate["status"] = "applied"
                if cid:
                    applied_ids.append(cid)
                continue
            if field == "source_stakeholders":
                after = candidate.get("after")
                if isinstance(after, list):
                    by_id[req_id][field] = after
                    candidate["status"] = "applied"
                    if cid:
                        applied_ids.append(cid)
                    continue

        candidate["status"] = "pending_review"
        if cid:
            pending_ids.append(cid)

    artifact["requirements"] = requirements
    artifact["requirement_change_candidates"] = candidates
    artifact["requirement_change_apply_result"] = {
        "applied_ids": applied_ids,
        "pending_ids": pending_ids,
        "skipped_duplicate_ids": skipped_duplicate_ids,
    }
    return artifact

def get_contribution_statement(contribution: Dict[str, Any]) -> str:
    if not isinstance(contribution, dict):
        return ""
    resp = contribution.get("response", {}) if isinstance(contribution.get("response"), dict) else {}
    return str(resp.get("statement") or resp.get("content") or "").strip()


def build_programmatic_merge_decisions(
    conflicts_by_id: Dict[str, Dict[str, Any]],
    extracted_pair_reviews: List[Dict[str, Any]],
    *,
    expected_agents: Optional[set[str]] = None,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    expected_agents = expected_agents or {"analyst", "expert", "modeler"}
    reviews_by_id: Dict[str, List[Dict[str, Any]]] = {}
    for review in extracted_pair_reviews or []:
        if not isinstance(review, dict):
            continue
        rid = str(review.get("id") or "").strip()
        if not rid or rid not in conflicts_by_id:
            continue
        reviews_by_id.setdefault(rid, []).append(review)

    auto_decisions: List[Dict[str, Any]] = []
    signoff_targets: List[Dict[str, Any]] = []
    debug: Dict[str, Any] = {
        "auto_keep_count": 0,
        "auto_modify_count": 0,
        "signoff_target_count": 0,
        "signoff_target_ids_preview": [],
    }

    for cid, conflict in conflicts_by_id.items():
        current_label = str(conflict.get("label") or "").strip()
        reviews = reviews_by_id.get(cid, [])
        review_agents = {
            str(r.get("agent") or "").strip()
            for r in reviews
            if str(r.get("agent") or "").strip()
        }
        missing_expected_agents = sorted(expected_agents - review_agents)
        valid_labels = [
            str(r.get("proposed_label") or "").strip()
            for r in reviews
            if str(r.get("proposed_label") or "").strip() in {"Conflict", "Neutral"}
        ]
        valid_decisions = [
            str(r.get("decision") or "").strip().lower()
            for r in reviews
            if str(r.get("decision") or "").strip().lower() in {"keep", "modify"}
        ]
        reasons = [
            str(r.get("reason") or "").strip()
            for r in reviews
            if str(r.get("reason") or "").strip()
        ]
        any_modify = "modify" in valid_decisions
        unique_labels = sorted(set(valid_labels))
        unresolved = (
            (not reviews)
            or bool(missing_expected_agents)
            or (not valid_labels)
            or any_modify
            or len(unique_labels) > 1
        )

        if unresolved:
            signoff_targets.append(
                {
                    "id": cid,
                    "current_label": current_label,
                    "description": (conflict.get("description") or "").strip(),
                    "requirement_ids": [
                        str(r)
                        for r in (conflict.get("requirement_ids") or [])
                        if str(r).strip()
                    ],
                    "requirements": list(conflict.get("requirements") or []),
                    "requirement_a": dict((conflict.get("requirement_a") or {})),
                    "requirement_b": dict((conflict.get("requirement_b") or {})),
                    "signoff_reason": (
                        "missing_expected_agent_review"
                        if missing_expected_agents
                        else "missing_or_disputed_pair_review"
                    ),
                    "missing_expected_agents": missing_expected_agents,
                }
            )
            continue

        decided_label = unique_labels[0] if unique_labels else current_label
        auto_decisions.append(
            {
                "id": cid,
                "new_label": decided_label,
                "reason": reasons[0] if reasons else "consensus_keep_current_label",
                "decided_by": "consensus",
            }
        )
        if decided_label == current_label:
            debug["auto_keep_count"] += 1
        else:
            debug["auto_modify_count"] += 1

    debug["signoff_target_count"] = len(signoff_targets)
    debug["signoff_target_ids_preview"] = [row.get("id") for row in signoff_targets[:5]]
    return auto_decisions, signoff_targets, debug


def analyst_changed_label_ids(
    extracted_pair_reviews: List[Dict[str, Any]],
    conflicts_by_id: Dict[str, Dict[str, Any]],
) -> List[str]:
    changed: List[str] = []
    for review in extracted_pair_reviews or []:
        if not isinstance(review, dict):
            continue
        if str(review.get("agent") or "").strip() != "analyst":
            continue
        cid = str(review.get("id") or "").strip()
        proposed_label = str(review.get("proposed_label") or "").strip()
        current_label = str((conflicts_by_id.get(cid) or {}).get("label") or "").strip()
        if cid and proposed_label in {"Conflict", "Neutral"} and current_label in {"Conflict", "Neutral"}:
            if proposed_label != current_label and cid not in changed:
                changed.append(cid)
    return changed


def consensus_decisions_from_pair_reviews(
    conflicts_by_id: Dict[str, Dict[str, Any]],
    extracted_pair_reviews: List[Dict[str, Any]],
    *,
    min_valid_labels: int = 2,
    expected_agents: Optional[set[str]] = None,
) -> tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Any]]:
    expected_agents = expected_agents or {"analyst", "expert", "modeler"}
    reviews_by_id: Dict[str, List[Dict[str, Any]]] = {}
    for review in extracted_pair_reviews or []:
        if not isinstance(review, dict):
            continue
        cid = str(review.get("id") or "").strip()
        if cid in conflicts_by_id:
            reviews_by_id.setdefault(cid, []).append(review)

    decisions: List[Dict[str, Any]] = []
    unresolved: Dict[str, Dict[str, Any]] = {}
    debug = {
        "consensus_count": 0,
        "unresolved_count": 0,
        "unresolved_ids_preview": [],
    }
    for cid, conflict in conflicts_by_id.items():
        reviews = reviews_by_id.get(cid, [])
        review_agents = {
            str(r.get("agent") or "").strip()
            for r in reviews
            if str(r.get("agent") or "").strip()
        }
        has_expected_reviews = expected_agents.issubset(review_agents)
        labels = [
            str(r.get("proposed_label") or "").strip()
            for r in reviews
            if str(r.get("proposed_label") or "").strip() in {"Conflict", "Neutral"}
        ]
        unique_labels = sorted(set(labels))
        if has_expected_reviews and len(labels) >= min_valid_labels and len(unique_labels) == 1:
            reasons = [
                str(r.get("reason") or "").strip()
                for r in reviews
                if str(r.get("reason") or "").strip()
            ]
            decisions.append(
                {
                    "id": cid,
                    "new_label": unique_labels[0],
                    "reason": reasons[0] if reasons else "second_round_proposed_label_consensus",
                    "decided_by": "second_round_consensus",
                }
            )
            debug["consensus_count"] += 1
        else:
            unresolved[cid] = conflict
    debug["unresolved_count"] = len(unresolved)
    debug["unresolved_ids_preview"] = list(unresolved.keys())[:5]
    return decisions, unresolved, debug

def analyst_finalize_conflict_review_reasons(
    coordinator: Any,
    decisions: List[Dict[str, Any]],
    conflicts_by_id: Dict[str, Dict[str, Any]],
    contributions: List[Dict[str, Any]],
    extracted_pair_reviews: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if not decisions:
        return {"final_reason_status": "skipped_no_decisions"}
    discussion_rows, extracted_from_contributions = collect_discussion_rows_and_pair_reviews(
        contributions,
        known_pair_ids=list(conflicts_by_id.keys()),
        current_labels_by_id={
            cid: str(conflict.get("label") or "").strip()
            for cid, conflict in conflicts_by_id.items()
            if isinstance(conflict, dict)
        },
    )
    reviews_for_prompt = (
        extracted_pair_reviews
        if isinstance(extracted_pair_reviews, list) and extracted_pair_reviews
        else extracted_from_contributions
    )
    decision_items: List[Dict[str, Any]] = []
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        cid = str(decision.get("id") or "").strip()
        if not cid or cid not in conflicts_by_id:
            continue
        conflict = conflicts_by_id[cid]
        decision_items.append(
            {
                "id": cid,
                "current_label": str(conflict.get("label") or "").strip(),
                "final_label": str(decision.get("new_label") or "").strip(),
                "decided_by": str(decision.get("decided_by") or "").strip(),
                "existing_reason": str(decision.get("reason") or "").strip(),
                "description": str(conflict.get("description") or "").strip(),
                "requirement_ids": list(conflict.get("requirement_ids") or []),
                "requirements": list(conflict.get("requirements") or []),
                "requirement_a": dict(conflict.get("requirement_a") or {}),
                "requirement_b": dict(conflict.get("requirement_b") or {}),
            }
        )
    def reviews_for_ids(pair_ids: set[str]) -> List[Dict[str, Any]]:
        return [
            row for row in reviews_for_prompt
            if isinstance(row, dict) and str(row.get("id") or "").strip() in pair_ids
        ]

    def fetch_reason_batch(batch: List[Dict[str, Any]]) -> tuple[List[Dict[str, str]], str]:
        batch_ids = {
            str(item.get("id") or "").strip()
            for item in batch
            if str(item.get("id") or "").strip()
        }
        return coordinator.flow.analyst_agent.finalize_conflict_review_reasons(
            batch,
            discussion_rows,
            extracted_pair_reviews=reviews_for_ids(batch_ids),
        )

    reason_by_id: Dict[str, str] = {}
    raw_outputs: List[str] = []
    batch_size = 8
    for start in range(0, len(decision_items), batch_size):
        batch = decision_items[start : start + batch_size]
        reason_rows, raw_output = fetch_reason_batch(batch)
        if raw_output:
            raw_outputs.append(raw_output)
        for row in reason_rows:
            if not isinstance(row, dict):
                continue
            pair_id = str(row.get("id") or "").strip()
            reason = str(row.get("reason") or "").strip()
            if pair_id and reason:
                reason_by_id[pair_id] = reason

    missing = [
        str(item.get("id") or "").strip()
        for item in decision_items
        if str(item.get("id") or "").strip() not in reason_by_id
    ]
    if missing:
        retry_items = [
            item for item in decision_items
            if str(item.get("id") or "").strip() in set(missing)
        ]
        for start in range(0, len(retry_items), batch_size):
            batch = retry_items[start : start + batch_size]
            reason_rows, raw_output = fetch_reason_batch(batch)
            if raw_output:
                raw_outputs.append(raw_output)
            for row in reason_rows:
                if not isinstance(row, dict):
                    continue
                pair_id = str(row.get("id") or "").strip()
                reason = str(row.get("reason") or "").strip()
                if pair_id and reason:
                    reason_by_id[pair_id] = reason

    missing = [
        str(item.get("id") or "").strip()
        for item in decision_items
        if str(item.get("id") or "").strip() not in reason_by_id
    ]
    if missing:
        raise RuntimeError(f"Analyst final reason 缺少 pair: {missing}")
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        cid = str(decision.get("id") or "").strip()
        if cid in reason_by_id:
            decision["reason"] = reason_by_id[cid]
            decision["reason_by"] = "analyst"
    return {
        "final_reason_status": "ok",
        "reason_count": len(reason_by_id),
        "raw_final_reason_output": raw_outputs,
    }

def ensure_conflict_review_participant_contributions(
    coordinator: Any,
    issue: Dict[str, Any],
    artifact: Dict[str, Any],
    contributions: List[Dict[str, Any]],
    participants: List[str],
) -> List[Dict[str, Any]]:
    """若某位審查 agent 沒有有效發言，單獨補收一次，避免 meeting_conflict_review 只剩少數角色。"""
    existing_with_statement = {
        str(c.get("agent") or "").strip()
        for c in contributions or []
        if isinstance(c, dict)
        and str(c.get("agent") or "").strip()
        and get_contribution_statement(c)
    }
    missing = [
        str(p).strip()
        for p in participants or []
        if str(p).strip() and str(p).strip() not in existing_with_statement
    ]
    if not missing:
        return contributions

    snapshot = coordinator.flow.mediator_agent.build_artifact_snapshot(artifact)
    out = list(contributions or [])
    retry_issue = {
        **issue,
        "discussion_mode": "simultaneous",
        "participants": missing,
        "title": "待命名會議",
    }
    retry_title = coordinator.flow.mediator_agent.name_meeting_issue(
        retry_issue,
        context_label="衝突缺席角色補審",
    )
    retry_issue["title"] = retry_title
    for agent_name in missing:
        agent = coordinator.flow.registry.get(agent_name)
        if not agent:
            coordinator.flow.logger.warning("Conflict review 補審：Agent '%s' 未註冊，跳過", agent_name)
            continue
        try:
            response = coordinator.flow.mediator_agent.collect_issue_response(
                agent,
                retry_issue,
                previous_responses=None,
                artifact_snapshot=snapshot,
            )
            out.append(
                {
                    "agent": agent_name,
                    "response": response if isinstance(response, dict) else {"content": str(response)},
                }
            )
        except Exception as e:
            if isinstance(issue.get("response_contract"), dict):
                raise
            coordinator.flow.logger.warning("Conflict review 補審：%s 發言失敗: %s", agent_name, e)
    return out

def analyst_signoff_conflict_recheck(
    coordinator: Any,
    contributions: List[Dict[str, Any]],
    conflicts_by_id: Dict[str, Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """由 Analyst 根據 pair 原文與各 agent 逐筆裁定做最終判定。"""
    discussion_rows, extracted_pair_reviews = collect_discussion_rows_and_pair_reviews(
        contributions,
        known_pair_ids=list(conflicts_by_id.keys()),
        current_labels_by_id={
            cid: str(conflict.get("label") or "").strip()
            for cid, conflict in conflicts_by_id.items()
            if isinstance(conflict, dict)
        },
    )
    debug_info: Dict[str, Any] = {
        "contributions_count": len(contributions or []),
        "discussion_rows_count": len(discussion_rows),
        "extracted_pair_reviews_count": len(extracted_pair_reviews),
        "extracted_pair_reviews_preview": extracted_pair_reviews[:3],
        "extracted_pair_reviews": extracted_pair_reviews,
    }
    if extracted_pair_reviews:
        coordinator.flow.logger.info(
            "需求衝突再審查裁定：pair_reviews 預覽=%s",
            json.dumps(extracted_pair_reviews[:3], ensure_ascii=False),
        )
    else:
        coordinator.flow.logger.warning(
            "需求衝突再審查裁定：未解析出 pair_reviews"
        )

    auto_decisions, proposal_list, merge_debug = build_programmatic_merge_decisions(
        conflicts_by_id,
        extracted_pair_reviews,
    )
    debug_info.update(merge_debug)
    debug_info["auto_decisions_preview"] = auto_decisions[:3]

    if not proposal_list:
        coordinator.flow.logger.info("需求衝突再審查裁定：無爭議 pair，略過 Analyst 最終裁定")
        debug_info["proposal_list_count"] = 0
        debug_info["proposal_pair_ids_preview"] = []
        debug_info["signoff_status"] = "skipped_no_disputed_pairs"
        debug_info["decisions_count"] = len(auto_decisions)
        debug_info["decisions_preview"] = auto_decisions[:3]
        return auto_decisions, debug_info
    coordinator.flow.logger.info(
        "需求衝突再審查裁定：待 Analyst 裁定 pairs=%s",
        len(proposal_list),
        ", ".join([str(row.get("id") or "") for row in proposal_list[:5]]),
    )
    debug_info["proposal_list_count"] = len(proposal_list)
    debug_info["proposal_pair_ids_preview"] = [row.get("id") for row in proposal_list[:5]]

    try:
        results, raw_signoff_output = coordinator.flow.analyst_agent.signoff_conflict_recheck(
            proposal_list,
            discussion_rows,
            extracted_pair_reviews=extracted_pair_reviews,
        )
        debug_info["raw_signoff_output"] = raw_signoff_output
        if not results:
            debug_info["signoff_status"] = "empty_or_invalid_decisions"
            raise RuntimeError("Analyst 衝突裁定在 agent loop 後仍未產生有效 decisions")

        for r in results:
            if isinstance(r, dict):
                r["decided_by"] = "analyst"
        merged_results = auto_decisions + results
        coordinator.flow.logger.info("Analyst 衝突裁定完成：%s 筆", len(results))
        coordinator.flow.logger.info(
            "需求衝突再審查裁定：Analyst 裁定結果預覽=%s",
            json.dumps(merged_results[:3], ensure_ascii=False),
        )
        debug_info["signoff_status"] = "ok"
        debug_info["decisions_count"] = len(merged_results)
        debug_info["decisions_preview"] = merged_results[:3]
        return merged_results, debug_info
    except Exception as e:
        debug_info["signoff_status"] = "exception"
        debug_info["exception"] = str(e)
        raise RuntimeError(f"Analyst 衝突裁定失敗: {e}") from e
