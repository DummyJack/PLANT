import json
from typing import Any, Dict, List, Optional

from .agenda_runner import AgendaRunner
from agents.profile.mediator import AGENDA_CATEGORY_LABEL
from utils import Collect, read_max_iterations
from utils import normalize_agenda_topic, normalize_topic_proposal


class MeetingCoordinator:
    def __init__(self, flow):
        self.flow = flow

    @staticmethod
    def _count_unanswered_open_questions(artifact: Dict[str, Any]) -> int:
        return sum(
            1
            for q in (artifact.get("open_questions", []) or [])
            if isinstance(q, dict) and q.get("status") != "answered"
        )

    def _run_enabled_reviews(
        self,
        artifact: Dict[str, Any],
        *,
        recent_discussions: Optional[List[Dict[str, Any]]],
        roles: List[str],
    ) -> None:
        enabled = self.flow.config.get("enable_agents") or {}
        role_to_agent = {
            "analyst": self.flow.analyst_agent,
            "expert": self.flow.expert_agent,
            "modeler": self.flow.modeler_agent,
        }
        max_iter = read_max_iterations(self.flow.config, default=3)
        for role in roles:
            if not enabled.get(role, True):
                continue
            agent = role_to_agent.get(role)
            if not agent:
                continue
            agent.run_review_loop(
                artifact,
                recent_discussions=recent_discussions,
                max_iterations=max_iter,
            )

    def _run_pre_round_review(
        self,
        artifact: Dict[str, Any],
        *,
        recent_discussions: Optional[List[Dict[str, Any]]] = None,
        round_num: Optional[int] = None,
    ) -> Dict[str, Any]:
        self.flow.logger.info("Pre-Round Review")
        if round_num is not None:
            artifact = self.run_pre_meeting_conflict_review(artifact, round_num)
        should_run_role_review = bool(
            self._recent_topic_discussions(artifact, rounds=1)
            or any(
                isinstance(c, dict) and (c.get("label") or "").strip() in {"Conflict", "Neutral"}
                for c in (artifact.get("conflicts", []) or [])
            )
            or self._count_unanswered_open_questions(artifact) > 0
        )
        if should_run_role_review:
            self._run_enabled_reviews(
                artifact,
                recent_discussions=recent_discussions,
                roles=["analyst", "expert", "modeler"],
            )
        return artifact

    def _save_pre_meeting_updates(
        self,
        artifact: Dict[str, Any],
        round_num: int,
    ) -> None:
        """會前審查後立即持久化 artifact、衝突報告與草稿。"""
        self.flow.store.save_artifact(artifact)
        if artifact.get("conflicts"):
            conflict_md = self.flow.analyst_agent.generate_conflict_report(
                artifact,
                round_num=round_num,
                recent_decisions_limit=self.flow.config.get("agenda_items", 5),
            )
            self.flow.store.save_markdown(conflict_md, "conflict_report.md")
        next_version = self.flow.store.get_draft_version() + 1
        draft_md = self.flow.analyst_agent.run_requirements_analyst(
            "create_draft",
            artifact=artifact,
            draft_version=next_version,
            round_num=round_num,
            recent_decisions_limit=self.flow.config.get("agenda_items", 5),
        )
        self.flow.store.save_draft(draft_md, version=next_version)
        self.flow.logger.info(
            "會前審查更新：artifact + conflict_report + draft_v%s", next_version,
        )

    def _recent_topic_discussions(
        self,
        artifact: Dict[str, Any],
        *,
        rounds: int = 1,
    ) -> List[Dict[str, Any]]:
        discussions = artifact.get("discussions", []) or []
        recent_rounds = discussions[-max(1, rounds):]
        out: List[Dict[str, Any]] = []
        for rd in recent_rounds:
            out.extend(rd.get("topics", []) or [])
        return out

    def _normalize_topic_proposal(
        self,
        item: Dict[str, Any],
        *,
        proposed_by: str,
        round_num: int,
        index: int,
    ) -> Optional[Dict[str, Any]]:
        return normalize_topic_proposal(
            item,
            allowed_categories=list(AGENDA_CATEGORY_LABEL.keys()),
            default_participants=["analyst", "expert", "modeler", "user"],
            proposed_by=proposed_by,
            round_num=round_num,
            index=index,
        )

    def _collect_topic_proposals(
        self,
        artifact: Dict[str, Any],
        *,
        round_num: int,
    ) -> List[Dict[str, Any]]:
        proposals: List[Dict[str, Any]] = []
        invalid_count = 0

        backlog = artifact.get("proposal_backlog", [])
        if isinstance(backlog, list):
            for i, row in enumerate(backlog, 1):
                normalized = self._normalize_topic_proposal(
                    row,
                    proposed_by=(row.get("proposed_by") or "backlog"),
                    round_num=round_num,
                    index=i,
                )
                if normalized:
                    proposals.append(normalized)
                else:
                    invalid_count += 1

        enabled = self.flow.config.get("enable_agents") or {}
        proposal_specs = [
            ("analyst", self.flow.analyst_agent, 4),
            ("expert", self.flow.expert_agent, 3),
            ("modeler", self.flow.modeler_agent, 3),
            ("user", self.flow.user_agent, 2),
        ]
        for role, agent, default_cap in proposal_specs:
            if not enabled.get(role, True):
                continue
            if not hasattr(agent, "propose_topics"):
                continue
            try:
                rows = agent.propose_topics(
                    artifact,
                    round_num=round_num,
                    max_items=default_cap,
                )
                if isinstance(rows, list):
                    for i, row in enumerate(rows, 1):
                        normalized = self._normalize_topic_proposal(
                            row,
                            proposed_by=role,
                            round_num=round_num,
                            index=i,
                        )
                        if normalized:
                            proposals.append(normalized)
                        else:
                            invalid_count += 1
            except Exception as e:
                self.flow.logger.warning("%s 提案階段失敗，略過: %s", role, e)
        self.flow.logger.info("Topic Proposal：%s 筆有效，%s 筆淘汰", len(proposals), invalid_count)
        return proposals

    def run_pre_meeting_conflict_review(
        self, artifact: Dict[str, Any], round_num: int
    ) -> Dict[str, Any]:
        """整批審查所有 Conflict 與 Neutral，透過單次討論決定是否調整標籤。"""
        candidates = [
            c for c in (artifact.get("conflicts", []) or [])
            if isinstance(c, dict)
            and str(c.get("label") or "").strip() in {"Conflict", "Neutral"}
        ]
        if not candidates:
            self.flow.logger.info("會前審查：無需複核")
            return artifact

        conflicts_by_id: Dict[str, Dict[str, Any]] = {
            str(c.get("id") or "").strip(): c
            for c in candidates
            if str(c.get("id") or "").strip()
        }

        conflict_summaries = []
        for cid, conflict in conflicts_by_id.items():
            label = str(conflict.get("label") or "").strip()
            desc = (conflict.get("description") or "").strip()
            req_ids = [str(r) for r in (conflict.get("requirement_ids") or []) if str(r).strip()]
            conflict_summaries.append(
                f"- [{cid}] 標籤={label}  需求={req_ids}  描述: {desc}"
            )

        plan = self.flow.mediator_agent.plan_pre_meeting_conflict_review(
            candidates[0], artifact=artifact, registry=self.flow.registry,
        )
        participants = plan.get("participants") or ["analyst", "expert", "modeler", "user"]
        speaking_order = plan.get("speaking_order") or participants

        topic = {
            "id": f"PM-R{round_num}",
            "title": f"會前衝突批次審查（Round {round_num}）",
            "description": (
                "以下為本輪會前需審查的 Conflict/Neutral 項目。\n"
                "請逐一說明哪些項目的標籤可能有誤（Conflict↔Neutral），並給出理由。\n"
                "若無意見可回覆「皆無異議」。\n\n"
                + "\n".join(conflict_summaries)
            ),
            "category": "conflict_resolution",
            "participants": participants,
            "discussion_mode": "sequential",
            "speaking_order": speaking_order,
            "source_ids": list(conflicts_by_id.keys()),
        }

        contributions, oq_records = self.flow.mediator_agent.moderate_sequential(
            topic, self.flow.registry, artifact=artifact,
        )
        if isinstance(oq_records, list) and oq_records:
            oq_pool = artifact.setdefault("open_questions", [])
            for oq in oq_records:
                if isinstance(oq, dict):
                    oq_pool.append({
                        **oq,
                        "topic_id": topic["id"],
                        "status": oq.get("status") or "pending",
                        "round": round_num,
                    })

        decisions = self._summarize_pre_meeting_discussion(
            contributions, conflicts_by_id,
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

        self.flow.logger.info(
            "會前衝突複核：%s 筆，改 %s", len(conflicts_by_id), changed,
        )
        return artifact

    def _summarize_pre_meeting_discussion(
        self,
        contributions: List[Dict[str, Any]],
        conflicts_by_id: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """請 Mediator 根據討論內容，為每筆 conflict 產出是否調整標籤的結論。"""
        discussion_rows = []
        for c in contributions or []:
            if not isinstance(c, dict):
                continue
            resp = c.get("response") or {}
            statement = ""
            if isinstance(resp, dict):
                statement = (resp.get("statement") or resp.get("content") or "").strip()
            else:
                statement = str(resp).strip()
            if statement:
                discussion_rows.append({"agent": c.get("agent"), "statement": statement})

        conflict_list = []
        for cid, conflict in conflicts_by_id.items():
            conflict_list.append({
                "id": cid,
                "current_label": str(conflict.get("label") or "").strip(),
                "description": (conflict.get("description") or "").strip(),
            })

        prompt = f"""你是需求會議主持人。根據以下會前衝突審查的討論內容，判定每筆衝突的標籤是否需要調整。

待審衝突清單:
{json.dumps(conflict_list, ensure_ascii=False, indent=2)}

討論內容:
{json.dumps(discussion_rows, ensure_ascii=False, indent=2)}

規則:
- 對每筆衝突，若討論中多數意見認為標籤有誤，new_label 填入應調整的值（Conflict 或 Neutral）。
- 若多數意見認為標籤正確或無明確共識，new_label 維持 current_label。
- 僅輸出 JSON array。

輸出:
[
  {{"id": "衝突 ID", "new_label": "Conflict 或 Neutral", "reason": "一句繁中理由"}}
]"""
        try:
            messages = self.flow.mediator_agent.build_direct_messages(prompt)
            data = self.flow.mediator_agent.model.chat_json(messages)
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and isinstance(data.get("decisions"), list):
                return data["decisions"]
            return []
        except Exception as e:
            self.flow.logger.warning("會前討論彙整失敗: %s", e)
            return []

    @staticmethod
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
            existing.append(candidate)
            seen.add(key)
        artifact["requirement_change_candidates"] = existing

    @staticmethod
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

    @staticmethod
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

    def apply_requirement_change_candidates(
        self,
        artifact: Dict[str, Any],
    ) -> Dict[str, Any]:
        """正式套用已允許自動套用的變更候選，並保留其餘 pending。"""
        requirements = [
            dict(req) for req in (artifact.get("requirements", []) or [])
            if isinstance(req, dict)
        ]
        by_id = {
            req.get("id"): req
            for req in requirements
            if req.get("id")
        }
        applied_ids: List[str] = []
        pending_ids: List[str] = []
        candidates = artifact.get("requirement_change_candidates", []) or []

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            cid = candidate.get("id")
            change_type = candidate.get("change_type")
            field = candidate.get("field")
            req_id = candidate.get("requirement_id")
            auto_apply = bool(candidate.get("auto_apply"))
            status = (candidate.get("status") or "").strip()

            if status == "applied":
                if cid:
                    applied_ids.append(cid)
                continue

            if change_type == "update" and auto_apply and req_id in by_id:
                if field in {"text", "priority"}:
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

            if change_type == "add" and auto_apply and req_id and req_id not in by_id:
                after = candidate.get("after")
                if isinstance(after, dict) and self._is_safe_add_candidate(candidate):
                    new_req = dict(after)
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

    @staticmethod
    def _is_safe_add_candidate(candidate: Dict[str, Any]) -> bool:
        """極保守的 add auto-apply 規則：只放行有來源的 constraint/NFR 類新增需求。"""
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
        # 避免把過長、像完整新功能敘述的文字直接落地
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

    @staticmethod
    def _build_queue_round_summary(
        artifact: Dict[str, Any],
        *,
        round_num: int,
    ) -> Dict[str, Any]:
        logs = [
            row for row in (artifact.get("queue_execution_log", []) or [])
            if isinstance(row, dict) and int(row.get("round") or -1) == round_num
        ]
        summary = {
            "round": round_num,
            "clarification_queue": {"processed": 0, "answered": 0, "deferred": 0},
            "human_decision_queue": {"processed": 0, "decided": 0, "deferred": 0},
            "direct_apply_queue": {"processed": 0, "queued_change_candidate": 0, "skipped": 0},
        }
        for row in logs:
            queue = row.get("queue")
            status = row.get("status")
            if queue == "clarification_queue":
                summary[queue]["processed"] += 1
                if status == "answered":
                    summary[queue]["answered"] += 1
                else:
                    summary[queue]["deferred"] += 1
            elif queue == "human_decision_queue":
                summary[queue]["processed"] += 1
                if status == "decided":
                    summary[queue]["decided"] += 1
                else:
                    summary[queue]["deferred"] += 1
            elif queue == "direct_apply_queue":
                summary[queue]["processed"] += 1
                if status == "queued_change_candidate":
                    summary[queue]["queued_change_candidate"] += 1
                else:
                    summary[queue]["skipped"] += 1
        return summary

    def _ingest_round_resolution_effects(
        self,
        artifact: Dict[str, Any],
        round_discussions: List[Dict[str, Any]],
        *,
        round_num: int,
    ) -> None:
        """將 topic_result 的 open question / conflict / requirement change effects 併入 artifact。"""
        oq_pool = artifact.get("open_questions", []) or []
        new_candidates: List[Dict[str, Any]] = []
        for item in round_discussions:
            if not isinstance(item, dict):
                continue
            topic = item.get("topic", {}) if isinstance(item.get("topic"), dict) else {}
            resolution = item.get("resolution", {}) if isinstance(item.get("resolution"), dict) else {}
            source_ids = list(topic.get("source_ids", []) or [])
            for oq in resolution.get("new_open_questions", []) or []:
                if not isinstance(oq, dict):
                    continue
                oq_pool.append(
                    {
                        **oq,
                        "topic_id": topic.get("id"),
                        "status": oq.get("status") or "pending",
                        "round": round_num,
                    }
                )
            if resolution.get("resolution_status") in {"agreed", "human_decision", "direct_clarification"}:
                self._close_related_open_questions(artifact, source_ids, round_num=round_num)
            affected_conflict_ids = resolution.get("affected_conflict_ids", []) or []
            decision_id = str(resolution.get("decision_id") or "").strip()
            if resolution.get("resolution_status") == "human_decision" and affected_conflict_ids and decision_id:
                self._mark_conflicts_resolved_by_ids(
                    artifact,
                    affected_conflict_ids,
                    decision_id=decision_id,
                )
            for candidate in resolution.get("requirement_change_candidates", []) or []:
                if not isinstance(candidate, dict):
                    continue
                new_candidates.append(candidate)
        artifact["open_questions"] = oq_pool
        self._append_requirement_change_candidates(artifact, new_candidates)

    def _queue_topic_record(
        self,
        row: Dict[str, Any],
        *,
        queue_prefix: str,
        index: int,
        triage_action: str,
    ) -> Dict[str, Any]:
        normalized = normalize_agenda_topic(
            {
                "id": f"{queue_prefix}-{index:02d}",
                "title": (row.get("title") or "待處理事項").strip(),
                "description": (row.get("description") or "").strip(),
                "category": row.get("category") or "open_question",
                "participants": row.get("participants", []),
                "discussion_mode": row.get("discussion_mode", "sequential"),
                "speaking_order": row.get("speaking_order", []),
                "source_ids": row.get("source_ids", []),
                "source_proposal_ids": [row.get("proposal_id")] if row.get("proposal_id") else [],
                "triage_action": triage_action,
                "status": "processed",
            },
            allowed_categories=list(AGENDA_CATEGORY_LABEL.keys()),
            registered_agents=list(self.flow.registry.get_names()) if self.flow.registry else ["analyst", "expert", "modeler", "user"],
            index=index,
        )
        return normalized or {
            "schema_version": "agenda_topic.v1",
            "id": f"{queue_prefix}-{index:02d}",
            "title": (row.get("title") or "待處理事項").strip(),
            "description": (row.get("description") or "").strip(),
            "category": row.get("category") or "open_question",
            "participants": row.get("participants", []),
            "discussion_mode": row.get("discussion_mode", "sequential"),
            "speaking_order": row.get("speaking_order", []),
            "source_ids": row.get("source_ids", []),
            "source_proposal_ids": [row.get("proposal_id")] if row.get("proposal_id") else [],
            "status": "processed",
            "triage_action": triage_action,
        }

    def _execute_clarification_queue(
        self,
        artifact: Dict[str, Any],
        runner: AgendaRunner,
        *,
        round_num: int,
    ) -> None:
        queue = artifact.get("clarification_queue", []) or []
        if not queue:
            return
        snapshot = self.flow.mediator_agent.build_artifact_snapshot(artifact)
        oq_pool = artifact.get("open_questions", []) or []
        execution_log = artifact.get("queue_execution_log", []) or []
        for idx, row in enumerate(queue, 1):
            if not isinstance(row, dict):
                continue
            topic = self._queue_topic_record(
                row,
                queue_prefix="CQ",
                index=idx,
                triage_action="direct_clarification",
            )
            target_name = ((topic.get("speaking_order") or topic.get("participants") or ["analyst"])[0] or "analyst")
            agent = self.flow.registry.get(target_name) if self.flow.registry else None
            if not agent:
                row["status"] = "deferred"
                row["queue_processed_round"] = round_num
                execution_log.append(
                    {
                        "round": round_num,
                        "queue": "clarification_queue",
                        "proposal_id": row.get("proposal_id"),
                        "status": "deferred_no_agent",
                    }
                )
                continue
            try:
                response = agent.respond_to_topic(
                    topic,
                    previous_responses=None,
                    artifact_snapshot=snapshot,
                )
                statement = (response.get("statement") or "").strip()
                open_questions = response.get("open_questions", []) or []
                for q in open_questions:
                    if not isinstance(q, dict):
                        continue
                    oq_pool.append(
                        {
                            "topic_id": topic.get("id"),
                            "from_agent": target_name,
                            "to_agent": q.get("to"),
                            "question": (q.get("question") or "").strip(),
                            "status": "pending",
                            "round": round_num,
                            "type": "clarification_follow_up",
                        }
                    )
                resolution = self.flow.mediator_agent.build_topic_result(
                    resolution_status="direct_clarification",
                    summary=statement or "已執行定向釐清，但未取得明確回答。",
                    decision="",
                    votes={},
                    votes_summary="direct_clarification",
                    mediator_compromise={},
                    agreed_points=[statement] if statement else [],
                    unresolved_points=[] if statement else ["尚未取得可用回答。"],
                    new_open_questions=[],
                    affected_conflict_ids=[
                        sid for sid in (topic.get("source_ids") or [])
                        if isinstance(sid, str) and sid.startswith("CF-")
                    ],
                    requirement_change_candidates=(
                        [
                            {
                                "id": f"RC-CQ-{round_num:02d}-{idx:02d}",
                                "requirement_id": next(
                                    (
                                        sid for sid in (topic.get("source_ids") or [])
                                        if isinstance(sid, str) and sid.startswith(("REQ-", "FR-", "NFR-"))
                                    ),
                                    "",
                                ),
                                "change_type": "update",
                                "field": "text",
                                "before": None,
                                "after": statement,
                                "reason": "Derived from direct clarification response.",
                                "source_ids": list(topic.get("source_ids", [])),
                                "status": "pending_review",
                                "auto_apply": False,
                            }
                        ]
                        if statement
                        and any(
                            isinstance(sid, str) and sid.startswith(("REQ-", "FR-", "NFR-"))
                            for sid in (topic.get("source_ids") or [])
                        )
                        else []
                    ),
                    needs_human=False,
                )
                runner.round_discussions.append(
                    {
                        "topic": {
                            **topic,
                            "status": "processed",
                        },
                        "source_ids": topic.get("source_ids", []),
                        "contributions": [
                            {
                                "agent": target_name,
                                "response": response,
                            }
                        ],
                        "resolution": resolution,
                    }
                )
                row["status"] = "answered" if statement else "deferred"
                row["queue_processed_round"] = round_num
                execution_log.append(
                    {
                        "round": round_num,
                        "queue": "clarification_queue",
                        "proposal_id": row.get("proposal_id"),
                        "status": row["status"],
                        "handled_by": target_name,
                    }
                )
            except Exception as e:
                self.flow.logger.warning("clarification_queue 執行失敗: %s", e)
                row["status"] = "deferred"
                row["queue_processed_round"] = round_num
        artifact["open_questions"] = oq_pool
        artifact["queue_execution_log"] = execution_log

    def _execute_human_decision_queue(
        self,
        artifact: Dict[str, Any],
        runner: AgendaRunner,
        *,
        round_num: int,
    ) -> None:
        queue = artifact.get("human_decision_queue", []) or []
        if not queue:
            return
        execution_log = artifact.get("queue_execution_log", []) or []
        for idx, row in enumerate(queue, 1):
            if not isinstance(row, dict):
                continue
            topic = self._queue_topic_record(
                row,
                queue_prefix="HQ",
                index=idx,
                triage_action="human_decision",
            )
            options = {
                "best_options": [],
                "compromise": {
                    "id": 1,
                    "title": topic.get("title", ""),
                    "description": topic.get("description", ""),
                    "rationale": row.get("why_now", ""),
                },
            }
            resolution_raw = Collect.human_decision_on_topic(topic, options)
            decision_text = str(resolution_raw.get("decision", "")).strip()
            decision_id = f"DEC-HQ-{round_num:02d}-{idx:02d}" if decision_text else ""
            resolution = self.flow.mediator_agent.build_topic_result(
                resolution_status="human_decision",
                summary=decision_text or "此議題已送人工裁決，但暫未定案。",
                decision=decision_text,
                votes={},
                votes_summary="human_decision_queue",
                mediator_compromise={},
                agreed_points=[decision_text] if decision_text else [],
                unresolved_points=[] if decision_text else ["人類選擇暫不裁決。"],
                new_open_questions=[],
                affected_conflict_ids=[
                    sid for sid in (topic.get("source_ids") or [])
                    if isinstance(sid, str) and sid.startswith("CF-")
                ],
                requirement_change_candidates=(
                    [
                        {
                            "id": f"RC-HQ-{round_num:02d}-{idx:02d}",
                            "requirement_id": next(
                                (
                                    sid for sid in (topic.get("source_ids") or [])
                                    if isinstance(sid, str) and sid.startswith(("REQ-", "FR-", "NFR-"))
                                ),
                                "",
                            ),
                            "change_type": "update",
                            "field": "text",
                            "before": None,
                            "after": decision_text,
                            "reason": "Derived from human decision queue result.",
                            "source_ids": list(topic.get("source_ids", [])),
                            "status": "pending_review",
                            "auto_apply": False,
                        }
                    ]
                    if decision_text
                    and any(
                        isinstance(sid, str) and sid.startswith(("REQ-", "FR-", "NFR-"))
                        for sid in (topic.get("source_ids") or [])
                    )
                    else []
                ),
                needs_human=True,
            )
            if decision_id:
                resolution["decision_id"] = decision_id
            resolution["human_decision_raw"] = resolution_raw
            runner.round_discussions.append(
                {
                    "topic": {
                        **topic,
                        "status": "processed",
                    },
                    "source_ids": topic.get("source_ids", []),
                    "contributions": [],
                    "resolution": resolution,
                }
            )
            if decision_text:
                decisions = artifact.get("decisions", []) or []
                decisions.append(
                    {
                        "id": decision_id,
                        "summary": decision_text,
                        "decision": decision_text,
                        "source_topic_id": topic.get("id"),
                        "resolved_conflict_ids": resolution.get("affected_conflict_ids", []),
                    }
                )
                artifact["decisions"] = decisions
                self._mark_conflicts_resolved_by_ids(
                    artifact,
                    resolution.get("affected_conflict_ids", []),
                    decision_id=decision_id,
                )
                row["status"] = "decided"
            else:
                row["status"] = "deferred"
            row["queue_processed_round"] = round_num
            execution_log.append(
                {
                    "round": round_num,
                    "queue": "human_decision_queue",
                    "proposal_id": row.get("proposal_id"),
                    "status": row["status"],
                }
            )
        artifact["queue_execution_log"] = execution_log

    def _execute_direct_apply_queue(
        self,
        artifact: Dict[str, Any],
        *,
        round_num: int,
    ) -> None:
        queue = artifact.get("direct_apply_queue", []) or []
        if not queue:
            return
        execution_log = artifact.get("queue_execution_log", []) or []
        candidates: List[Dict[str, Any]] = []
        next_idx = len(artifact.get("requirement_change_candidates", []) or []) + 1
        for row in queue:
            if not isinstance(row, dict):
                continue
            req_ids = [
                sid for sid in (row.get("source_ids") or [])
                if isinstance(sid, str) and sid.startswith(("REQ-", "FR-", "NFR-"))
            ]
            if not req_ids:
                row["status"] = "skipped_no_requirement_id"
                row["queue_processed_round"] = round_num
                execution_log.append(
                    {
                        "round": round_num,
                        "queue": "direct_apply_queue",
                        "proposal_id": row.get("proposal_id"),
                        "status": row["status"],
                    }
                )
                continue
            candidates.append(
                {
                    "id": f"RC-QA-{next_idx:03d}",
                    "requirement_id": req_ids[0],
                    "change_type": "update",
                    "field": "text",
                    "before": None,
                    "after": row.get("description", ""),
                    "reason": row.get("why_now") or "Queued direct-apply proposal pending analyst review.",
                    "source_ids": list(row.get("source_ids", [])),
                    "status": "pending_review",
                    "auto_apply": False,
                }
            )
            next_idx += 1
            row["status"] = "queued_change_candidate"
            row["queue_processed_round"] = round_num
            execution_log.append(
                {
                    "round": round_num,
                    "queue": "direct_apply_queue",
                    "proposal_id": row.get("proposal_id"),
                    "status": row["status"],
                }
            )
        self._append_requirement_change_candidates(artifact, candidates)
        artifact["queue_execution_log"] = execution_log

    def _run_routed_queues(
        self,
        artifact: Dict[str, Any],
        runner: AgendaRunner,
        *,
        round_num: int,
    ) -> None:
        self._execute_clarification_queue(artifact, runner, round_num=round_num)
        self._execute_human_decision_queue(artifact, runner, round_num=round_num)
        self._execute_direct_apply_queue(artifact, round_num=round_num)
        artifact["clarification_queue"] = [
            row for row in (artifact.get("clarification_queue", []) or [])
            if isinstance(row, dict) and row.get("status") == "deferred"
        ]
        artifact["human_decision_queue"] = [
            row for row in (artifact.get("human_decision_queue", []) or [])
            if isinstance(row, dict) and row.get("status") == "deferred"
        ]
        artifact["direct_apply_queue"] = [
            row for row in (artifact.get("direct_apply_queue", []) or [])
            if isinstance(row, dict) and row.get("status") not in {"queued_change_candidate"}
        ]

    @staticmethod
    def _triggered_roles_for_topic(
        topic_discussion: Dict[str, Any],
        artifact: Dict[str, Any],
    ) -> List[str]:
        """根據單一議題的 resolution 判斷需觸發哪些 agent review。"""
        roles: List[str] = []
        resolution = topic_discussion.get("resolution", {})
        if not isinstance(resolution, dict):
            return roles
        status = (resolution.get("resolution_status") or "").strip()
        if status not in {"agreed", "human_decision", "direct_clarification"}:
            roles.extend(["analyst", "expert"])
        if resolution.get("new_open_questions"):
            roles.append("expert")
        if resolution.get("requirement_change_candidates"):
            roles.append("analyst")
        if (
            artifact.get("system_models", {}).get("models")
            and resolution.get("requirement_change_candidates")
        ):
            roles.append("modeler")
        deduped: List[str] = []
        for r in roles:
            if r not in deduped:
                deduped.append(r)
        return deduped

    def _post_topic_processing(
        self,
        artifact: Dict[str, Any],
        topic_discussion: Dict[str, Any],
        *,
        round_num: int,
    ) -> None:
        """單一議題 save 後：ingest effects → save artifact → 觸發 agent review。"""
        self._ingest_round_resolution_effects(
            artifact, [topic_discussion], round_num=round_num,
        )
        self.flow.store.save_artifact(artifact)
        roles = self._triggered_roles_for_topic(topic_discussion, artifact)
        if roles:
            self.flow.logger.info("議題後觸發 review：%s", ", ".join(roles))
            self._run_enabled_reviews(
                artifact,
                recent_discussions=[topic_discussion],
                roles=roles,
            )
            self.flow.store.save_artifact(artifact)

    def _run_agenda_loop(self, runner: AgendaRunner) -> None:
        obs = runner.run("generate_agenda", None)
        if obs.get("error"):
            self.flow.logger.warning(f"  議程生成失敗: {obs['error']}")
        self._run_routed_queues(runner.artifact, runner, round_num=runner.round_num)
        observation = None
        while True:
            state = runner.get_state_summary()
            decision = self.flow.mediator_agent.decide_next_agenda_action(state, observation)
            action = decision.get("action", "finish_round")
            params = decision.get("params") or {}
            self.flow.logger.info(f"  決策: {action} — {decision.get('reasoning', '')}")
            if action == "finish_round":
                break
            observation = runner.run(action, params)
            if observation.get("error"):
                self.flow.logger.warning(f"  執行失敗: {observation['error']}")
            elif action == "save_topic":
                latest = runner.get_round_discussions()
                if latest:
                    self._post_topic_processing(
                        runner.artifact,
                        latest[-1],
                        round_num=runner.round_num,
                    )

    @staticmethod
    def _append_round_discussion_record(
        artifact: Dict[str, Any],
        *,
        round_num: int,
        round_discussions: List[Dict[str, Any]],
        agenda_snapshot: List[Dict[str, Any]],
        queue_round_summary: Dict[str, Any],
    ) -> None:
        artifact.setdefault("discussions", []).append(
            {
                "round": round_num,
                "topics": round_discussions,
                "agenda_snapshot": agenda_snapshot or [],
                "queue_summary": queue_round_summary,
            }
        )

    def _post_round_pipeline(
        self,
        artifact: Dict[str, Any],
        runner: AgendaRunner,
        *,
        round_num: int,
    ) -> Dict[str, Any]:
        round_discussions = runner.get_round_discussions()
        all_open_questions = runner.get_all_open_questions()
        agenda_snapshot = runner.get_agenda_snapshot()
        queue_round_summary = self._build_queue_round_summary(
            artifact,
            round_num=round_num,
        )
        self._append_round_discussion_record(
            artifact,
            round_num=round_num,
            round_discussions=round_discussions,
            agenda_snapshot=agenda_snapshot,
            queue_round_summary=queue_round_summary,
        )
        oq_pool = artifact.get("open_questions", [])
        seen = {
            (q.get("topic_id"), q.get("from_agent"), q.get("to_agent"), q.get("question"))
            for q in oq_pool
        }
        for oq in all_open_questions:
            oq["round"] = round_num
            k = (oq.get("topic_id"), oq.get("from_agent"), oq.get("to_agent"), oq.get("question"))
            if k in seen:
                continue
            oq_pool.append(oq)
            seen.add(k)
        artifact["open_questions"] = oq_pool
        self.flow.store.save_artifact(artifact)

        updates = self.flow.mediator_agent.update_decisions(artifact, round_discussions)
        self._apply_mediator_updates(artifact, updates)

        # apply safe changes
        draft = self.flow.analyst_agent.run_requirements_analyst(
            "update_draft", artifact=artifact,
        )
        artifact["requirements"] = draft["requirements"]
        change_candidates = draft.get("requirement_change_candidates", [])
        if isinstance(change_candidates, list) and change_candidates:
            self._append_requirement_change_candidates(artifact, change_candidates)
        artifact = self.apply_requirement_change_candidates(artifact)

        # regenerate draft/model
        prev_models = artifact.get("system_models", {}).get("models", [])
        if prev_models:
            model_data = self.flow.modeler_agent.refine_model(
                artifact["requirements"],
                prev_models,
                stakeholders=artifact.get("stakeholders", []),
            )
        else:
            model_data = self.flow.modeler_agent.generate_system_model(
                artifact["requirements"],
                artifact["stakeholders"],
                max_iterations=read_max_iterations(self.flow.config, default=3),
            )
        artifact["system_models"] = model_data
        next_version = self.flow.store.get_draft_version() + 1
        draft_md = self.flow.analyst_agent.run_requirements_analyst(
            "create_draft",
            artifact=artifact,
            draft_version=next_version,
            round_num=round_num,
            recent_decisions_limit=self.flow.config.get("agenda_items", 5),
        )
        self.flow.store.save_draft(draft_md, version=next_version)
        self.flow._touch_artifact_meta(
            artifact,
            updated_by="flow.run_meeting_round",
            round_num=round_num,
        )
        self.flow.store.save_artifact(artifact)
        self.flow.store.save_plantuml_files(model_data)
        return artifact

    @staticmethod
    def _apply_mediator_updates(
        artifact: Dict[str, Any],
        updates: Dict[str, Any],
    ) -> Dict[str, Any]:
        prev_conflicts_by_id = {
            c.get("id"): c for c in artifact.get("conflicts", []) if c.get("id")
        }
        new_decisions = updates.get("new_decisions", [])
        artifact.setdefault("decisions", []).extend(new_decisions)
        new_conflicts = list(updates.get("conflicts", artifact.get("conflicts", [])))
        extra_new_conflicts = updates.get("new_conflicts", []) or []
        next_conflict_num = len(
            [c for c in new_conflicts if isinstance(c, dict) and str(c.get("id") or "").startswith("CF-")]
        ) + 1
        for row in extra_new_conflicts:
            if not isinstance(row, dict):
                continue
            candidate = dict(row)
            if not str(candidate.get("id") or "").strip():
                candidate["id"] = f"CF-{next_conflict_num:02d}"
                next_conflict_num += 1
            new_conflicts.append(candidate)
        cf_to_decision = {}
        for d in new_decisions:
            did = d.get("id")
            for cf_id in d.get("resolved_conflict_ids", []):
                if cf_id:
                    cf_to_decision[cf_id] = did
        for c in new_conflicts:
            if c.get("label") == "Neutral" and c.get("id"):
                c.setdefault("resolved_by_decision_id", cf_to_decision.get(c["id"]))
            orig = prev_conflicts_by_id.get(c.get("id"))
            if not orig:
                continue
            if orig.get("requirement_ids") is not None:
                c.setdefault("requirement_ids", orig["requirement_ids"])
            if orig.get("conflict_type") and c.get("label") == "Conflict":
                c.setdefault("conflict_type", orig["conflict_type"])
            if orig.get("resolved_by_decision_id") and c.get("label") == "Neutral":
                c.setdefault("resolved_by_decision_id", orig["resolved_by_decision_id"])
        artifact["conflicts"] = new_conflicts
        return {"new_decisions": new_decisions}

    def run_meeting_round(
        self, artifact: Dict[str, Any], round_num: int
    ) -> Dict[str, Any]:
        artifact = self.flow._ensure_artifact_contract(artifact)
        artifact = self._run_pre_round_review(
            artifact,
            recent_discussions=self._recent_topic_discussions(artifact, rounds=1),
            round_num=round_num,
        )
        self._save_pre_meeting_updates(artifact, round_num)
        current_round_proposals = self._collect_topic_proposals(
            artifact,
            round_num=round_num,
        )
        existing_topic_proposals = artifact.get("topic_proposals", []) or []
        seen_proposal_ids = {
            row.get("proposal_id")
            for row in existing_topic_proposals
            if isinstance(row, dict) and row.get("proposal_id")
        }
        for row in current_round_proposals:
            if not isinstance(row, dict):
                continue
            proposal_id = row.get("proposal_id")
            if proposal_id and proposal_id in seen_proposal_ids:
                continue
            existing_topic_proposals.append(row)
            if proposal_id:
                seen_proposal_ids.add(proposal_id)
        artifact["topic_proposals"] = existing_topic_proposals
        self.flow.store.save_artifact(artifact)

        runner = AgendaRunner(
            self.flow.mediator_agent,
            self.flow.registry,
            artifact,
            current_round_proposals,
            round_num,
            self.flow.config,
            self.flow.store,
            Collect,
            self.flow.logger,
        )
        self._run_agenda_loop(runner)
        return self._post_round_pipeline(
            artifact,
            runner,
            round_num=round_num,
        )
