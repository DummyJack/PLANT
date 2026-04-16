import json
import re
from typing import Any, Dict, List, Optional

from utils import Collect


# ---------- artifact 層級靜態工具 ----------

def _append_requirement_change_candidates(
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


def _close_related_open_questions(
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


def _mark_conflicts_resolved_by_ids(
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


def _set_requirement_status_by_ids(
    artifact: Dict[str, Any],
    requirement_ids: List[str],
    *,
    status: str,
    round_num: int,
) -> None:
    if not requirement_ids:
        return
    target = {str(rid).strip() for rid in requirement_ids if str(rid).strip()}
    if not target:
        return
    valid = {"draft", "approved", "baselined", "rejected"}
    normalized = status if status in valid else "draft"
    for req in artifact.get("requirements", []) or []:
        if not isinstance(req, dict):
            continue
        rid = str(req.get("id") or "").strip()
        if rid not in target:
            continue
        req["status"] = normalized
        req["status_updated_round"] = round_num


def _approval_status_by_topic(artifact: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for row in artifact.get("approval_queue", []) or []:
        if not isinstance(row, dict):
            continue
        tid = str(row.get("topic_id") or "").strip()
        if not tid:
            continue
        out[tid] = str(row.get("status") or "pending").strip() or "pending"
    return out


# ---------- approval queue ----------

def _process_approval_queue(
    coordinator: Any,
    artifact: Dict[str, Any],
    *,
    round_num: int,
) -> Dict[str, int]:
    queue = artifact.get("approval_queue", []) or []
    if not queue:
        return {"approved": 0, "rejected": 0, "pending": 0}

    enable_human = bool(coordinator.flow.config.get("enable_human_approval_queue", True))
    approval_log = artifact.get("approval_log", []) or []
    approved = rejected = pending = 0

    for row in queue:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "pending").strip() or "pending"
        if status in {"approved", "rejected"}:
            if status == "approved":
                approved += 1
            else:
                rejected += 1
            continue

        if not enable_human:
            row["status"] = "approved"
            row["approved_round"] = round_num
            row["approved_by"] = "system_auto"
            _set_requirement_status_by_ids(
                artifact, row.get("affected_requirement_ids", []) or [],
                status="approved", round_num=round_num,
            )
            approved += 1
            approval_log.append(
                {"topic_id": row.get("topic_id"), "round": round_num, "status": "approved", "approved_by": "system_auto", "decision": "auto_approved_by_config"}
            )
            continue

        topic = {
            "id": row.get("topic_id"),
            "title": f"需求變更批准：{row.get('topic_id', '')}",
            "description": (
                f"變更說明: {row.get('summary', '')}\n"
                f"決議: {row.get('decision', '')}\n"
                f"影響需求: {row.get('affected_requirement_ids', [])}\n"
                f"驗證影響: {row.get('verification_impact', {})}"
            ),
        }
        options = {
            "best_options": [
                {"id": 1, "title": "批准本次需求變更", "description": "允許本議題相關變更進入下一版需求草稿。", "source": "approval_queue"},
                {"id": 2, "title": "駁回本次需求變更", "description": "不套用本議題相關變更，維持現有需求。", "source": "approval_queue"},
            ],
            "compromise": {"id": 3, "title": "暫緩批准", "description": "保留 pending，待下一輪補充資訊後再決定。", "rationale": "目前資訊不足或仍有風險疑慮。"},
        }
        result = Collect.human_decision_on_topic(topic, options)
        choice = int(result.get("chosen_option_id") or -1)
        if choice == 1:
            row["status"] = "approved"
            row["approved_round"] = round_num
            row["approved_by"] = "human"
            _set_requirement_status_by_ids(
                artifact, row.get("affected_requirement_ids", []) or [],
                status="approved", round_num=round_num,
            )
            approved += 1
        elif choice == 2:
            row["status"] = "rejected"
            row["approved_round"] = round_num
            row["approved_by"] = "human"
            _set_requirement_status_by_ids(
                artifact, row.get("affected_requirement_ids", []) or [],
                status="rejected", round_num=round_num,
            )
            rejected += 1
        elif str(result.get("resolution") or "").strip() == "agreed":
            row["status"] = "approved"
            row["approved_round"] = round_num
            row["approved_by"] = "human"
            _set_requirement_status_by_ids(
                artifact, row.get("affected_requirement_ids", []) or [],
                status="approved", round_num=round_num,
            )
            approved += 1
        else:
            row["status"] = "pending"
            pending += 1
        row["approval_decision"] = result
        approval_log.append(
            {"topic_id": row.get("topic_id"), "round": round_num, "status": row.get("status"), "approved_by": row.get("approved_by", "human"), "decision": result}
        )

    artifact["approval_queue"] = queue
    artifact["approval_log"] = approval_log
    return {"approved": approved, "rejected": rejected, "pending": pending}


# ---------- apply change candidates ----------

def _is_safe_add_candidate(candidate: Dict[str, Any]) -> bool:
    after = candidate.get("after")
    if not isinstance(after, dict):
        return False
    req_id = str(candidate.get("requirement_id") or after.get("id") or "").strip()
    text = str(after.get("text") or "").strip()
    req_type = str(after.get("type") or "").strip()
    priority = str(after.get("priority") or "").strip()
    source_ids = [str(s).strip() for s in (candidate.get("source_ids") or []) if str(s).strip()]
    if not req_id or not text or not source_ids:
        return False
    if req_type not in {"constraint", "NFR"}:
        return False
    if priority not in {"must", "should", "could"}:
        return False
    if len(text) > 120:
        return False
    high_risk_keywords = (
        "整合", "串接", "介接", "第三方", "external", "api", "角色", "actor",
        "支付", "付款", "登入流程", "新功能", "新頁面", "新模組",
    )
    lower_text = text.lower()
    if any(k in text or k in lower_text for k in high_risk_keywords):
        return False
    return True


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
    candidates = artifact.get("requirement_change_candidates", []) or []
    approval_by_topic = _approval_status_by_topic(artifact)
    require_approval = bool(coordinator.flow.config.get("require_human_approval_for_changes", True))

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        cid = candidate.get("id")
        change_type = candidate.get("change_type")
        field = candidate.get("field")
        req_id = candidate.get("requirement_id")
        auto_apply = bool(candidate.get("auto_apply"))
        status = (candidate.get("status") or "").strip()
        topic_id = str(candidate.get("source_topic_id") or candidate.get("topic_id") or "").strip()

        if status == "applied":
            if cid:
                applied_ids.append(cid)
            continue

        if require_approval:
            topic_approval = approval_by_topic.get(topic_id, "pending") if topic_id else "pending"
            if topic_approval != "approved":
                candidate["status"] = "pending_review"
                if cid:
                    pending_ids.append(cid)
                continue

        if change_type == "update" and auto_apply and req_id in by_id:
            if field in {"text", "priority"}:
                by_id[req_id][field] = candidate.get("after")
                by_id[req_id]["status"] = "approved"
                candidate["status"] = "applied"
                if cid:
                    applied_ids.append(cid)
                continue
            if field == "source_stakeholders":
                after = candidate.get("after")
                if isinstance(after, list):
                    by_id[req_id][field] = after
                    by_id[req_id]["status"] = "approved"
                    candidate["status"] = "applied"
                    if cid:
                        applied_ids.append(cid)
                    continue

        if change_type == "add" and auto_apply and req_id and req_id not in by_id:
            after = candidate.get("after")
            if isinstance(after, dict) and _is_safe_add_candidate(candidate):
                new_req = dict(after)
                new_req["status"] = "approved"
                requirements.append(new_req)
                by_id[req_id] = new_req
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
    }
    return artifact


# ---------- 衝突再審查逐筆裁定工具 ----------

_PAIR_ID_RE = re.compile(r"\[(PAIR[^\]]+)\]|\"id\"\s*:\s*\"(PAIR[^\"]+)\"", re.IGNORECASE)
_LABEL_RE = re.compile(r"\b(Conflict|Neutral)\b", re.IGNORECASE)
_DECISION_RE = re.compile(r"\b(keep|modify)\b", re.IGNORECASE)
_CONF_RE = re.compile(r"\b(high|medium|low)\b", re.IGNORECASE)


def _normalize_pair_review_record(
    review: Dict[str, Any],
    *,
    pair_id_set: set[str],
) -> Optional[Dict[str, Any]]:
    if not isinstance(review, dict):
        return None
    pair_id = str(review.get("id") or "").strip()
    if not pair_id or pair_id not in pair_id_set:
        return None
    independent_label = str(review.get("independent_label") or "").strip()
    proposed_label = str(review.get("proposed_label") or "").strip()
    decision = str(review.get("decision") or "").strip().lower()
    confidence = str(review.get("confidence") or "").strip().lower()
    reason = str(review.get("reason") or "").strip()
    if independent_label not in {"Conflict", "Neutral"}:
        independent_label = ""
    if proposed_label not in {"Conflict", "Neutral"}:
        proposed_label = ""
    if decision not in {"keep", "modify"}:
        decision = ""
    if confidence not in {"high", "medium", "low"}:
        confidence = ""
    return {
        "id": pair_id,
        "independent_label": independent_label,
        "decision": decision,
        "proposed_label": proposed_label,
        "confidence": confidence,
        "reason": reason,
    }


def _extract_pair_reviews_from_statement(
    statement: str,
    *,
    known_pair_ids: List[str],
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
                normalized = _normalize_pair_review_record(raw_review, pair_id_set=pair_id_set)
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
        pair_id = (pair_match.group(1) or pair_match.group(2) or "").strip()
        if not pair_id or pair_id not in pair_id_set:
            continue
        decision_match = _DECISION_RE.search(line)
        labels = [m.group(1) for m in _LABEL_RE.finditer(line)]
        conf_match = _CONF_RE.search(line)
        reason = line
        if "理由" in line:
            reason = line.split("理由", 1)[-1].lstrip(":： ").strip() or line

        independent_label = labels[0] if labels else ""
        proposed_label = labels[-1] if labels else ""
        normalized = _normalize_pair_review_record(
            {
                "id": pair_id,
                "independent_label": independent_label,
                "decision": (decision_match.group(1).lower() if decision_match else ""),
                "proposed_label": proposed_label,
                "confidence": (conf_match.group(1).lower() if conf_match else ""),
                "reason": reason,
            },
            pair_id_set=pair_id_set,
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


def _collect_discussion_rows_and_pair_reviews(
    contributions: List[Dict[str, Any]],
    *,
    known_pair_ids: List[str],
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
        for review in _extract_pair_reviews_from_statement(statement, known_pair_ids=known_pair_ids):
            extracted_pair_reviews.append({"agent": agent_name, **review})
    return discussion_rows, extracted_pair_reviews


def _build_fallback_keep_decisions(
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


def _build_programmatic_merge_decisions(
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
                "reason": reasons[0] if reasons else "rule_based_merge_keep_current_label",
                "decided_by": "rule_based_merge",
            }
        )
        if decided_label == current_label:
            debug["auto_keep_count"] += 1
        else:
            debug["auto_modify_count"] += 1

    debug["signoff_target_count"] = len(signoff_targets)
    debug["signoff_target_ids_preview"] = [row.get("id") for row in signoff_targets[:5]]
    return auto_decisions, signoff_targets, debug


def _analyst_signoff_conflict_recheck(
    coordinator: Any,
    contributions: List[Dict[str, Any]],
    conflicts_by_id: Dict[str, Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """由 Analyst 根據 pair 原文與各 agent 逐筆裁定做最終判定。"""
    discussion_rows, extracted_pair_reviews = _collect_discussion_rows_and_pair_reviews(
        contributions,
        known_pair_ids=list(conflicts_by_id.keys()),
    )
    debug_info: Dict[str, Any] = {
        "contributions_count": len(contributions or []),
        "discussion_rows_count": len(discussion_rows),
        "extracted_pair_reviews_count": len(extracted_pair_reviews),
        "extracted_pair_reviews_preview": extracted_pair_reviews[:3],
    }
    coordinator.flow.logger.info(
        "RQ2 signoff debug: contributions=%s discussion_rows=%s extracted_pair_reviews=%s",
        len(contributions or []),
        len(discussion_rows),
        len(extracted_pair_reviews),
    )
    if extracted_pair_reviews:
        coordinator.flow.logger.info(
            "RQ2 signoff debug: pair_reviews preview=%s",
            json.dumps(extracted_pair_reviews[:3], ensure_ascii=False),
        )
    else:
        coordinator.flow.logger.warning(
            "RQ2 signoff debug: no extracted_pair_reviews were produced from meeting contributions"
        )

    auto_decisions, proposal_list, merge_debug = _build_programmatic_merge_decisions(
        conflicts_by_id,
        extracted_pair_reviews,
    )
    debug_info.update(merge_debug)
    debug_info["auto_decisions_preview"] = auto_decisions[:3]

    if not proposal_list:
        coordinator.flow.logger.info("RQ2 signoff debug: no disputed pairs, skip analyst signoff")
        debug_info["proposal_list_count"] = 0
        debug_info["proposal_pair_ids_preview"] = []
        debug_info["signoff_status"] = "skipped_no_disputed_pairs"
        debug_info["decisions_count"] = len(auto_decisions)
        debug_info["decisions_preview"] = auto_decisions[:3]
        return auto_decisions, debug_info
    coordinator.flow.logger.info(
        "RQ2 signoff debug: proposal_list=%s pair_ids=%s",
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
                "RQ2 signoff debug: analyst returned empty/invalid decisions"
            )
            debug_info["signoff_status"] = "empty_or_invalid_decisions"
            fallback = auto_decisions + _build_fallback_keep_decisions(
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
            "RQ2 signoff debug: decisions preview=%s",
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
        fallback = auto_decisions + _build_fallback_keep_decisions(
            {row["id"]: conflicts_by_id[row["id"]] for row in proposal_list if row.get("id") in conflicts_by_id},
            reason="fallback_keep_current_label_due_to_signoff_exception",
        )
        debug_info["decisions_count"] = len(fallback)
        debug_info["decisions_preview"] = fallback[:3]
        debug_info["fallback_applied"] = True
        return fallback, debug_info


# ---------- 會前衝突再審查主流程 ----------

def run_pre_meeting_conflict_review_block(
    coordinator: Any, artifact: Dict[str, Any], round_num: int
) -> Dict[str, Any]:
    """針對本輪所有 Conflict/Neutral pairs 執行一次會前再審查與逐筆裁定。"""
    candidates = [
        c
        for c in (artifact.get("conflicts", []) or [])
        if isinstance(c, dict) and str(c.get("label") or "").strip() in {"Conflict", "Neutral"}
    ]
    if not candidates:
        coordinator.flow.logger.info("會前衝突再審查：無需處理項目")
        return artifact

    conflicts_by_id: Dict[str, Dict[str, Any]] = {
        str(c.get("id") or "").strip(): c
        for c in candidates
        if str(c.get("id") or "").strip()
    }

    requirement_by_id: Dict[str, Dict[str, Any]] = {
        str(r.get("id") or "").strip(): r
        for r in (artifact.get("requirements", []) or [])
        if isinstance(r, dict) and str(r.get("id") or "").strip()
    }

    conflict_summaries = []
    pair_cards = []
    for cid, conflict in conflicts_by_id.items():
        label = str(conflict.get("label") or "").strip()
        desc = (conflict.get("description") or "").strip()
        req_ids = [str(r) for r in (conflict.get("requirement_ids") or []) if str(r).strip()]
        conflict_summaries.append(f"- [{cid}] 標籤={label}  需求={req_ids}  描述: {desc}")
        req_a_id = req_ids[0] if len(req_ids) >= 1 else ""
        req_b_id = req_ids[1] if len(req_ids) >= 2 else ""
        req_a = requirement_by_id.get(req_a_id, {})
        req_b = requirement_by_id.get(req_b_id, {})
        pair_cards.append({
            "id": cid,
            "current_label": label,
            "current_description": desc,
            "current_conflict_type": str(conflict.get("conflict_type") or "").strip(),
            "requirement_ids": req_ids,
            "requirement_a": {
                "id": req_a_id,
                "text": str(req_a.get("text") or "").strip(),
            },
            "requirement_b": {
                "id": req_b_id,
                "text": str(req_b.get("text") or "").strip(),
            },
        })
        conflict["requirement_a"] = {
            "id": req_a_id,
            "text": str(req_a.get("text") or "").strip(),
        }
        conflict["requirement_b"] = {
            "id": req_b_id,
            "text": str(req_b.get("text") or "").strip(),
        }

    plan = coordinator.flow.mediator_agent.plan_pre_meeting_conflict_review(
        candidates[0], artifact=artifact, registry=coordinator.flow.registry
    )
    participants = plan.get("participants") or ["analyst", "expert", "modeler", "user"]
    discussion_mode = str(plan.get("discussion_mode") or "sequential").strip().lower()
    if discussion_mode not in {"sequential", "simultaneous"}:
        discussion_mode = "sequential"

    topic = {
        "id": f"PM-R{round_num}",
        "title": f"會前衝突批次再審查（Round {round_num}）",
        "description": (
            "以下為本輪會前需審查的 Conflict/Neutral 項目。\n"
            "請先只根據每個 pair 的 requirement_a / requirement_b 原文，獨立判斷它應為 Conflict 或 Neutral；"
            "再與 current_label 比較，決定 keep 或 modify。\n"
            "你必須同時做兩層檢視：\n"
            "1) 整體檢視：說明你對整批標註品質的整體判斷（是否有系統性偏誤）。\n"
            "2) 逐筆（pair-by-pair）檢視：每個 [PAIR-xxx] 都必須明確寫出：\n"
            "   - independent_label: 你獨立重判後的標籤\n"
            "   - decision: keep 或 modify\n"
            "   - proposed_label: 最終建議標籤（Conflict 或 Neutral）\n"
            "   - confidence: high / medium / low\n"
            "   - reason: 一句到兩句理由\n"
            "Neutral 的定義：兩項需求既不衝突、也不重複，且沒有直接語義關係。\n\n"
            "待審清單：\n" + "\n".join(conflict_summaries)
        ),
        "category": "conflict_discussion",
        "participants": participants,
        "discussion_mode": discussion_mode,
        "source_ids": list(conflicts_by_id.keys()),
        "pair_cards": pair_cards,
    }

    if discussion_mode == "simultaneous":
        contributions = coordinator.flow.mediator_agent.moderate_simultaneous(
            topic, coordinator.flow.registry, artifact=artifact
        )
        oq_records = []
    else:
        contributions, oq_records = coordinator.flow.mediator_agent.moderate_sequential(
            topic, coordinator.flow.registry, artifact=artifact
        )
    if isinstance(oq_records, list) and oq_records:
        oq_pool = artifact.setdefault("open_questions", [])
        for oq in oq_records:
            if isinstance(oq, dict):
                oq_pool.append(
                    {**oq, "topic_id": topic["id"], "status": oq.get("status") or "pending", "round": round_num}
                )
    coordinator.flow.logger.info(
        "RQ2 review debug: topic=%s mode=%s participants=%s contributions=%s open_questions=%s",
        topic["id"],
        discussion_mode,
        participants,
        len(contributions or []),
        len(oq_records or []),
    )
    if contributions:
        coordinator.flow.logger.info(
            "RQ2 review debug: contribution_agents=%s",
            [
                str(c.get("agent") or "").strip()
                for c in contributions
                if isinstance(c, dict)
            ],
        )
    contribution_agents = [
        str(c.get("agent") or "").strip()
        for c in contributions
        if isinstance(c, dict)
    ]

    conversation_rows: List[str] = []
    for c in contributions:
        if not isinstance(c, dict):
            continue
        agent_name = str(c.get("agent") or "").strip()
        resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
        statement = str(resp.get("statement") or resp.get("content") or "").strip()
        if not agent_name or not statement:
            continue
        conversation_rows.append(f"{agent_name}: {statement}")

    decisions, signoff_debug = _analyst_signoff_conflict_recheck(
        coordinator, contributions, conflicts_by_id
    )

    changed = 0
    for dec in decisions:
        cid = str(dec.get("id") or "").strip()
        conflict = conflicts_by_id.get(cid)
        if not conflict:
            continue
        new_label = str(dec.get("new_label") or "").strip()
        old_label = str(conflict.get("label") or "").strip()
        modify = new_label in {"Conflict", "Neutral"} and new_label != old_label
        if modify:
            conflict["label"] = new_label
            changed += 1
        conflict["pre_meeting_review"] = {
            "round": round_num,
            "result": "modify" if modify else "keep",
            "from_label": old_label,
            "to_label": new_label if modify else old_label,
            "reason": str(dec.get("reason") or ""),
        }

    recheck_log = artifact.setdefault("conflict_recheck_log", [])
    include_debug = bool(coordinator.flow.config.get("rq2_debug", False))
    recheck_log.append(
        {
            "round": round_num,
            "topic_id": topic.get("id"),
            "discussion_mode": discussion_mode,
            "participants": participants,
            "contribution_agents": contribution_agents,
            "candidates_count": len(decisions),
            "changed_count": changed,
            "conversation": conversation_rows,
            "decisions": decisions,
            "debug": (
                {
                    "contributions_count": len(contributions or []),
                    "open_questions_count": len(oq_records or []),
                    **signoff_debug,
                }
                if include_debug
                else {}
            ),
        }
    )

    coordinator.flow.logger.info("會前衝突再審查：%s 筆，改 %s", len(conflicts_by_id), changed)
    return artifact
