# Support helpers for conflict review and requirement-change application.
import json
import re
from typing import Any, Dict, List, Optional

from agents.profile.analyst.requirements import next_requirement_id
from utils import human_setting

_PAIR_ID_RE = re.compile(
    r"\[(PAIR[^\]]+)\]|\"id\"\s*:\s*\"(PAIR[^\"]+)\"|\b(PAIR-\d+)\b",
    re.IGNORECASE,
)
_LABEL_RE = re.compile(r"\b(Conflict|Neutral)\b", re.IGNORECASE)
_CONF_RE = re.compile(r"\b(high|medium|low)\b", re.IGNORECASE)
_PROPOSED_LABEL_RE = re.compile(
    r"\bproposed_label\s*[:：]\s*(Conflict|Neutral)\b",
    re.IGNORECASE,
)
_REASON_FIELD_RE = re.compile(r"\breason\s*[:：]\s*(.+)$", re.IGNORECASE)
_PAIRWISE_CONFLICT_JUDGMENT_MODE = "pairwise_conflict_judgment"
def pending_decision_status_by_topic(artifact: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for row in artifact.get("pending_decisions", []) or []:
        if not isinstance(row, dict):
            continue
        tid = str(row.get("topic_id") or "").strip()
        if not tid:
            continue
        status = str(row.get("status") or "pending_confirmation").strip()
        if status in {"confirmed", "approved"}:
            out[tid] = "confirmed"
        elif status in {"rejected", "declined"}:
            out[tid] = "rejected"
        else:
            out[tid] = "pending_confirmation"

    return out

def is_low_risk_update_candidate(
    candidate: Dict[str, Any],
    *,
    requirements_by_id: Dict[str, Dict[str, Any]],
) -> bool:
    change_type = str(candidate.get("change_type") or "").strip()
    field = str(candidate.get("field") or "").strip()
    req_id = str(candidate.get("requirement_id") or "").strip()
    source_ids = [str(s).strip() for s in (candidate.get("source_ids") or []) if str(s).strip()]
    if any(sid.startswith("CF-") for sid in source_ids):
        return False

    if change_type == "add":
        return is_safe_add_candidate(candidate)

    if change_type != "update" or not req_id or req_id not in requirements_by_id:
        return False

    req = requirements_by_id[req_id]
    if field == "source_stakeholders":
        return isinstance(candidate.get("after"), list)
    if field == "priority":
        return str(candidate.get("after") or "").strip() in {"must", "should", "could"}
    if field in {"acceptance_criteria", "verification_method"}:
        after = str(candidate.get("after") or "").strip()
        return bool(after) and len(after) <= 220 and "\n" not in after
    if field != "text":
        return False

    before = str(req.get("text") or "").strip()
    after = str(candidate.get("after") or "").strip()
    if not before or not after or before == after:
        return False
    if len(after) > max(220, len(before) + 80):
        return False
    if "\n" in after:
        return False
    return True

def extract_pair_reviews_from_statement(
    statement: str,
    *,
    known_pair_ids: List[str],
    current_labels_by_id: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """從 agent statement 提取逐筆 pair_reviews。

    優先解析合法 JSON statement；若格式漂移，再退回行文字 fallback。
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
                normalized = normalize_pair_review_record(
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
        pair_match = _PAIR_ID_RE.search(line)
        if not pair_match:
            continue
        pair_id = (pair_match.group(1) or pair_match.group(2) or pair_match.group(3) or "").strip()
        if not pair_id or pair_id not in pair_id_set:
            continue
        proposed_label_match = _PROPOSED_LABEL_RE.search(line)
        labels = [m.group(1) for m in _LABEL_RE.finditer(line)]
        conf_match = _CONF_RE.search(line)
        reason = line
        reason_match = _REASON_FIELD_RE.search(line)
        if reason_match:
            reason = reason_match.group(1).strip() or line
        elif "理由" in line:
            reason = line.split("理由", 1)[-1].lstrip(":： ").strip() or line

        proposed_label = proposed_label_match.group(1) if proposed_label_match else (labels[0] if labels else "")
        normalized = normalize_pair_review_record(
            {
                "id": pair_id,
                "proposed_label": proposed_label,
                "confidence": (conf_match.group(1).lower() if conf_match else ""),
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

def mark_conflicts_resolved_by_ids(
    artifact: Dict[str, Any],
    conflict_ids: List[str],
    *,
    decision_id: Optional[str] = None,
) -> None:
    if not conflict_ids:
        return
    target = {str(cid).strip() for cid in conflict_ids if str(cid).strip()}
    for c in artifact.get("conflicts", []) or []:
        cid = str(c.get("id") or "").strip()
        if cid not in target:
            continue
        c["label"] = "Neutral"
        if decision_id:
            c["resolved_by_decision_id"] = decision_id

def normalize_pair_review_record(
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
    confidence = str(review.get("confidence") or "").strip().lower()
    reason = str(review.get("reason") or "").strip()
    if proposed_label not in {"Conflict", "Neutral"}:
        proposed_label = ""
    current_label = ""
    if current_labels_by_id:
        current_label = str(current_labels_by_id.get(pair_id) or "").strip()
    decision = ""
    if proposed_label and current_label in {"Conflict", "Neutral"}:
        decision = "keep" if proposed_label == current_label else "modify"
    if confidence not in {"high", "medium", "low"}:
        confidence = ""
    return {
        "id": pair_id,
        "decision": decision,
        "proposed_label": proposed_label,
        "confidence": confidence,
        "reason": reason,
    }

def normalize_conflict_review_statement_for_record(
    statement: str,
    *,
    known_pair_ids: List[str],
    current_labels_by_id: Optional[Dict[str, str]] = None,
) -> str:
    """將 conflict review 發言正規化為 review_summary + pair_reviews 的 JSON 字串。"""
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
        first_pair = _PAIR_ID_RE.search(text)
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

def is_safe_add_candidate(candidate: Dict[str, Any]) -> bool:
    after = candidate.get("after")
    if not isinstance(after, dict):
        return False
    req_id = str(candidate.get("requirement_id") or after.get("id") or "").strip()
    text = str(after.get("text") or "").strip()
    req_type = str(after.get("type") or after.get("requirement_type") or "").strip().upper()
    priority = str(after.get("priority") or "").strip()
    source_ids = [str(s).strip() for s in (candidate.get("source_ids") or []) if str(s).strip()]
    source_topic_id = str(candidate.get("source_topic_id") or candidate.get("topic_id") or "").strip()
    if source_topic_id.startswith("ELICIT-") or any(sid.startswith("ELICIT-") for sid in source_ids):
        return False
    if not req_id or not text or not source_ids:
        return False
    if priority not in {"must", "should", "could"}:
        return False
    # 允許低風險 FR/NFR/constraint 新增，避免 elicitation candidate 長期停在 pending_review。
    normalized_type = req_type.lower()
    if normalized_type not in {"constraint", "nfr", "fr"} and not req_type.startswith(("FR", "NFR")):
        return False
    if len(text) > 220 or "\n" in text:
        return False
    # 功能需求僅在屬於需求補完型來源時自動吸收，避免一般會議決議過度擴 scope。
    if req_type.startswith("FR") or normalized_type == "fr":
        allowed_prefixes = ("ELICIT-", "OQ-", "DR-", "REQ-")
        if not any(sid.startswith(allowed_prefixes) for sid in source_ids):
            return False
    return True

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

def normalize_requirement_text_key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()

def collect_discussion_rows_and_pair_reviews(
    contributions: List[Dict[str, Any]],
    *,
    known_pair_ids: List[str],
    current_labels_by_id: Optional[Dict[str, str]] = None,
) -> tuple[list[dict], list[dict]]:
    """整理會議發言與逐筆裁定資料。"""
    discussion_rows: List[Dict[str, Any]] = []
    extracted_pair_reviews: List[Dict[str, Any]] = []
    for c in contributions or []:
        if not isinstance(c, dict):
            continue
        resp = c.get("response") or {}
        statement = ""
        if isinstance(resp, dict):
            statement = (resp.get("statement") or resp.get("content") or "").strip()
        else:
            statement = str(resp).strip()
        if not statement:
            continue
        agent_name = str(c.get("agent") or "").strip()
        discussion_rows.append({"agent": agent_name, "statement": statement})
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
        dict(req) for req in (artifact.get("requirements", []) or [])
        if isinstance(req, dict)
    ]
    by_id = {req.get("id"): req for req in requirements if req.get("id")}
    applied_ids: List[str] = []
    pending_ids: List[str] = []
    skipped_duplicate_ids: List[str] = []
    candidates = artifact.get("requirement_change_candidates", []) or []
    decision_status_by_topic = pending_decision_status_by_topic(artifact)
    require_confirmation = bool(
        human_setting(
            coordinator.flow.config, "require_user_confirmation_for_changes", True
        )
    )

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        cid = candidate.get("id")
        change_type = candidate.get("change_type")
        field = candidate.get("field")
        req_id = candidate.get("requirement_id")
        status = (candidate.get("status") or "").strip()
        topic_id = str(candidate.get("source_topic_id") or candidate.get("topic_id") or "").strip()
        low_risk_auto_approve = is_low_risk_update_candidate(candidate, requirements_by_id=by_id)

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

            new_req = AnalystAgent.normalize_requirement_record(dict(after))
            text_key = normalize_requirement_text_key(new_req.get("text"))
            existing_texts = {
                normalize_requirement_text_key(req.get("text"))
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
            new_req["status"] = "unverified"
            requirements.append(new_req)
            by_id[req_id] = new_req
            candidate["requirement_id"] = req_id
            candidate["status"] = "applied"
            candidate["confirmation_bypassed"] = "new_requirement_added_unverified"
            if cid:
                applied_ids.append(cid)
            continue

        if require_confirmation:
            decision_status = decision_status_by_topic.get(topic_id, "pending_confirmation") if topic_id else "pending_confirmation"
            if decision_status != "confirmed" and not low_risk_auto_approve:
                candidate["status"] = "pending_review"
                if cid:
                    pending_ids.append(cid)
                continue
            if decision_status != "confirmed" and low_risk_auto_approve:
                candidate["confirmation_bypassed"] = "low_risk_auto_approve"

        apply_allowed = (
            not require_confirmation
            or decision_status_by_topic.get(topic_id, "pending_confirmation") == "confirmed"
            or low_risk_auto_approve
        )

        if change_type == "update" and apply_allowed and req_id in by_id:
            if field in {"text", "priority", "acceptance_criteria", "verification_method"}:
                proposed_req = dict(by_id[req_id])
                proposed_req[field] = candidate.get("after")
                by_id[req_id][field] = candidate.get("after")
                by_id[req_id]["status"] = "unverified"
                candidate["status"] = "applied"
                if cid:
                    applied_ids.append(cid)
                continue
            if field == "source_stakeholders":
                after = candidate.get("after")
                if isinstance(after, list):
                    by_id[req_id][field] = after
                    by_id[req_id]["status"] = "unverified"
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

def build_fallback_keep_decisions(
    conflicts_by_id: Dict[str, Dict[str, Any]],
    *,
    reason: str,
) -> List[Dict[str, Any]]:
    decisions: List[Dict[str, Any]] = []
    for cid, conflict in conflicts_by_id.items():
        current_label = str(conflict.get("label") or "").strip()
        if current_label not in {"Conflict", "Neutral"}:
            continue
        decisions.append(
            {
                "id": cid,
                "new_label": current_label,
                "reason": reason,
                "decided_by": "fallback",
            }
        )
    return decisions

def get_contribution_statement(contribution: Dict[str, Any]) -> str:
    if not isinstance(contribution, dict):
        return ""
    resp = contribution.get("response", {}) if isinstance(contribution.get("response"), dict) else {}
    return str(resp.get("statement") or resp.get("content") or "").strip()

def ensure_conflict_review_participant_contributions(
    coordinator: Any,
    topic: Dict[str, Any],
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
    retry_topic = {
        **topic,
        "discussion_mode": "simultaneous",
        "participants": missing,
        "title": f"{topic.get('title', '')}｜缺席角色補審",
    }
    for agent_name in missing:
        agent = coordinator.flow.registry.get(agent_name)
        if not agent:
            coordinator.flow.logger.warning("Conflict review 補審：Agent '%s' 未註冊，跳過", agent_name)
            continue
        try:
            response = coordinator.flow.mediator_agent.collect_topic_response(
                agent,
                retry_topic,
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
    coordinator.flow.logger.info(
        "Conflict judgment signoff: contributions=%s discussion_rows=%s extracted_pair_reviews=%s",
        len(contributions or []),
        len(discussion_rows),
        len(extracted_pair_reviews),
    )
    if extracted_pair_reviews:
        coordinator.flow.logger.info(
            "Conflict judgment signoff: pair_reviews preview=%s",
            json.dumps(extracted_pair_reviews[:3], ensure_ascii=False),
        )
    else:
        coordinator.flow.logger.warning(
            "Conflict judgment signoff: no extracted_pair_reviews were produced from meeting contributions"
        )

    auto_decisions, proposal_list, merge_debug = build_programmatic_merge_decisions(
        conflicts_by_id,
        extracted_pair_reviews,
    )
    debug_info.update(merge_debug)
    debug_info["auto_decisions_preview"] = auto_decisions[:3]

    if not proposal_list:
        coordinator.flow.logger.info("Conflict judgment signoff: no disputed pairs, skip analyst signoff")
        debug_info["proposal_list_count"] = 0
        debug_info["proposal_pair_ids_preview"] = []
        debug_info["signoff_status"] = "skipped_no_disputed_pairs"
        debug_info["decisions_count"] = len(auto_decisions)
        debug_info["decisions_preview"] = auto_decisions[:3]
        return auto_decisions, debug_info
    coordinator.flow.logger.info(
        "Conflict judgment signoff: proposal_list=%s pair_ids=%s",
        len(proposal_list),
        [row.get("id") for row in proposal_list[:5]],
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
            coordinator.flow.logger.warning("Analyst 衝突裁定回傳格式異常，維持原標籤")
            coordinator.flow.logger.warning(
                "Conflict judgment signoff: analyst returned empty/invalid decisions"
            )
            debug_info["signoff_status"] = "empty_or_invalid_decisions"
            fallback = auto_decisions + build_fallback_keep_decisions(
                {row["id"]: conflicts_by_id[row["id"]] for row in proposal_list if row.get("id") in conflicts_by_id},
                reason="fallback_keep_current_label_due_to_empty_signoff",
            )
            debug_info["decisions_count"] = len(fallback)
            debug_info["decisions_preview"] = fallback[:3]
            debug_info["fallback_applied"] = True
            return fallback, debug_info

        for r in results:
            if isinstance(r, dict):
                r["decided_by"] = "analyst"
        merged_results = auto_decisions + results
        coordinator.flow.logger.info("Analyst 衝突裁定完成：%s 筆", len(results))
        coordinator.flow.logger.info(
            "Conflict judgment signoff: decisions preview=%s",
            json.dumps(merged_results[:3], ensure_ascii=False),
        )
        debug_info["signoff_status"] = "ok"
        debug_info["decisions_count"] = len(merged_results)
        debug_info["decisions_preview"] = merged_results[:3]
        return merged_results, debug_info
    except Exception as e:
        coordinator.flow.logger.warning("Analyst 衝突裁定失敗，維持原標籤: %s", e)
        debug_info["signoff_status"] = "exception"
        debug_info["exception"] = str(e)
        fallback = auto_decisions + build_fallback_keep_decisions(
            {row["id"]: conflicts_by_id[row["id"]] for row in proposal_list if row.get("id") in conflicts_by_id},
            reason="fallback_keep_current_label_due_to_signoff_exception",
        )
        debug_info["decisions_count"] = len(fallback)
        debug_info["decisions_preview"] = fallback[:3]
        debug_info["fallback_applied"] = True
        return fallback, debug_info

def build_programmatic_merge_decisions(
    conflicts_by_id: Dict[str, Dict[str, Any]],
    extracted_pair_reviews: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
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
        unresolved = (not reviews) or (not valid_labels) or any_modify or len(unique_labels) > 1

        if unresolved:
            signoff_targets.append(
                {
                    "id": cid,
                    "current_label": current_label,
                    "description": (conflict.get("description") or "").strip(),
                    "requirement_ids": [str(r) for r in (conflict.get("requirement_ids") or []) if str(r).strip()],
                    "requirement_a": dict((conflict.get("requirement_a") or {})),
                    "requirement_b": dict((conflict.get("requirement_b") or {})),
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
