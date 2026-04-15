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
                f"摘要: {row.get('summary', '')}\n"
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


# ---------- 衝突再審查 LLM 呼叫 ----------

_PAIR_ID_RE = re.compile(r"\[(PAIR[^\]]+)\]|\"id\"\s*:\s*\"(PAIR[^\"]+)\"", re.IGNORECASE)
_LABEL_RE = re.compile(r"\b(Conflict|Neutral)\b", re.IGNORECASE)
_DECISION_RE = re.compile(r"\b(keep|modify)\b", re.IGNORECASE)
_CONF_RE = re.compile(r"\b(high|medium|low)\b", re.IGNORECASE)


def _extract_pair_reviews_from_statement(
    statement: str,
    *,
    known_pair_ids: List[str],
) -> List[Dict[str, Any]]:
    text = str(statement or "").strip()
    if not text:
        return []

    reviews: List[Dict[str, Any]] = []
    pair_id_set = {str(x).strip() for x in (known_pair_ids or []) if str(x).strip()}

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
        reviews.append({
            "id": pair_id,
            "independent_label": independent_label,
            "decision": (decision_match.group(1).lower() if decision_match else ""),
            "proposed_label": proposed_label,
            "confidence": (conf_match.group(1).lower() if conf_match else ""),
            "reason": reason,
        })

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

def _summarize_pre_meeting_discussion(
    coordinator: Any,
    contributions: List[Dict[str, Any]],
    conflicts_by_id: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    discussion_rows, extracted_pair_reviews = _collect_discussion_rows_and_pair_reviews(
        contributions,
        known_pair_ids=list(conflicts_by_id.keys()),
    )

    conflict_list = []
    for cid, conflict in conflicts_by_id.items():
        conflict_list.append({
            "id": cid,
            "current_label": str(conflict.get("label") or "").strip(),
            "description": (conflict.get("description") or "").strip(),
            "requirement_ids": [str(r) for r in (conflict.get("requirement_ids") or []) if str(r).strip()],
            "requirement_a": dict((conflict.get("requirement_a") or {})),
            "requirement_b": dict((conflict.get("requirement_b") or {})),
        })

    try:
        return coordinator.flow.mediator_agent.summarize_pre_meeting_conflict_discussion(
            conflict_list,
            discussion_rows,
            extracted_pair_reviews=extracted_pair_reviews,
        )
    except Exception as e:
        coordinator.flow.logger.warning("會前討論彙整失敗: %s", e)
        return []


def _analyst_signoff_conflict_recheck(
    coordinator: Any,
    mediator_proposals: List[Dict[str, Any]],
    contributions: List[Dict[str, Any]],
    conflicts_by_id: Dict[str, Dict[str, Any]],
    *,
    round_num: int,
) -> List[Dict[str, Any]]:
    discussion_rows, extracted_pair_reviews = _collect_discussion_rows_and_pair_reviews(
        contributions,
        known_pair_ids=list(conflicts_by_id.keys()),
    )

    proposal_list = []
    for p in mediator_proposals:
        if not isinstance(p, dict):
            continue
        cid = str(p.get("id") or "").strip()
        conflict = conflicts_by_id.get(cid, {})
        proposal_list.append({
            "id": cid,
            "current_label": str(conflict.get("label") or "").strip(),
            "description": (conflict.get("description") or "").strip(),
            "requirement_ids": [str(r) for r in (conflict.get("requirement_ids") or []) if str(r).strip()],
            "requirement_a": dict((conflict.get("requirement_a") or {})),
            "requirement_b": dict((conflict.get("requirement_b") or {})),
            "mediator_proposed_label": str(p.get("new_label") or "").strip(),
            "mediator_reason": str(p.get("reason") or "").strip(),
        })

    if not proposal_list:
        return mediator_proposals

    try:
        results = coordinator.flow.analyst_agent.signoff_conflict_recheck(
            proposal_list,
            discussion_rows,
            extracted_pair_reviews=extracted_pair_reviews,
        )
        if not results:
            coordinator.flow.logger.warning("Analyst 衝突裁定回傳格式異常，使用 Mediator 建議")
            return mediator_proposals

        for r in results:
            if isinstance(r, dict):
                r["decided_by"] = "analyst"
        coordinator.flow.logger.info("Analyst 衝突裁定完成：%s 筆", len(results))
        return results if results else mediator_proposals
    except Exception as e:
        coordinator.flow.logger.warning("Analyst 衝突裁定失敗，使用 Mediator 建議: %s", e)
        return mediator_proposals


# ---------- 會前衝突再審查主流程 ----------

def run_pre_meeting_conflict_review_block(
    coordinator: Any, artifact: Dict[str, Any], round_num: int
) -> Dict[str, Any]:
    """整批審查所有 Conflict 與 Neutral，透過單次討論決定是否調整標籤。"""
    candidates = [
        c
        for c in (artifact.get("conflicts", []) or [])
        if isinstance(c, dict) and str(c.get("label") or "").strip() in {"Conflict", "Neutral"}
    ]
    if not candidates:
        coordinator.flow.logger.info("會前審查：無需再審查")
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

    decisions = _summarize_pre_meeting_discussion(coordinator, contributions, conflicts_by_id)
    if coordinator.flow.config.get("conflict_recheck_requires_analyst_signoff", True):
        decisions = _analyst_signoff_conflict_recheck(
            coordinator, decisions, contributions, conflicts_by_id, round_num=round_num
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
    recheck_log.append(
        {
            "round": round_num,
            "topic_id": topic.get("id"),
            "discussion_mode": discussion_mode,
            "participants": participants,
            "candidates_count": len(decisions),
            "changed_count": changed,
            "conversation": conversation_rows,
            "decisions": decisions,
        }
    )

    coordinator.flow.logger.info("會前衝突再審查：%s 筆，改 %s", len(conflicts_by_id), changed)
    return artifact
