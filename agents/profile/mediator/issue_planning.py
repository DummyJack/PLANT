# Mediator issue planning: triage issue proposals and generate decision issues.
import json
from typing import Any, Dict, List, Optional

from agents.profile.analyst.conflict_store import all_conflict_rows, conflict_entries_count
from agents.profile.analyst.requirements import requirement_discussion_pool

from .prompts import (
    meeting_action_prompt,
    decision_issues_prompt,
    elicitation_plan_prompt,
    meeting_title_batch_prompt,
    meeting_title_prompt,
    conflict_review_prompt,
)
from .validation import (
    ISSUE_TYPE_IDS,
    ISSUE_TYPES,
    meeting_action_decision,
    decision_issue,
    elicitation_plan,
    issue_proposal,
    meeting_title,
    meeting_title_batch,
    conflict_review_plan,
)


class MediatorIssuePlanning:
    def final_meeting_issue(
        self,
        *,
        round_num: int,
        artifact: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        req_ids = [
            str(req.get("id") or "").strip()
            for req in requirement_discussion_pool(artifact)
            if isinstance(req, dict) and str(req.get("id") or "").strip()
        ]
        return issue_proposal(
            {
                "issue_id": f"I-R{round_num}-final-meeting",
                "title": "Final meeting",
                "description": (
                    "請所有 agent 根據自身角色最後確認目前 requirements、scope、conflicts、"
                    "decisions、models 與 stakeholder understanding 是否足以交給 Documentor "
                    "生成正式 SRS。"
                ),
                "category": "srs_open_question",
                "participants": ["analyst", "expert", "modeler", "user"],
                "discussion_mode": "sequential",
                "speaking_order": ["analyst", "expert", "modeler", "user"],
                "source_ids": req_ids,
                "priority_hint": "high",
                "impact_level": "high",
                "why_now": "正式會議輪次上限已完成，需要全員完成最後確認後交付 Documentor 生成正式 SRS。",
                "routing_preference": "formal_meeting",
                "requires_multi_party": True,
                "blocks_decision": True,
            },
            allowed_categories=ISSUE_TYPE_IDS,
            default_participants=["analyst", "expert", "modeler", "user"],
            proposed_by="system",
            round_num=round_num,
            index=1,
        )

    def get_active_issue_types(self):
        """回傳啟用的決策議題類型（tuple of dicts）和 id 列表。"""
        if self.enabled_issue_type_ids is None:
            return ISSUE_TYPES, ISSUE_TYPE_IDS
        active = tuple(
            t for t in ISSUE_TYPES
            if t["id"] in self.enabled_issue_type_ids
        )
        active_ids = [t["id"] for t in active]
        return active, active_ids

    def classify_issue_proposal(
        self,
        proposal: Dict[str, Any],
    ) -> Dict[str, Any]:
        """依 issue proposal schema 與類型規則決定分流：正式會議、定向問答、直接處理或人工裁決。"""
        category = (proposal.get("category") or "").strip()
        impact = (proposal.get("impact_level") or proposal.get("priority_hint") or "medium").strip().lower()
        needs_human = bool(proposal.get("needs_human"))
        routing_preference = (proposal.get("routing_preference") or "formal_meeting").strip()
        source_ids = [s for s in (proposal.get("source_ids") or []) if str(s).strip()]
        participants = [p for p in (proposal.get("participants") or []) if str(p).strip()]
        deferred_rounds = int(proposal.get("deferred_rounds") or 0)
        multi_party = len(participants) >= 3

        action = "direct_clarification"
        reason = "queue_first_default"
        if needs_human or routing_preference == "human_decision":
            action = "human_decision"
            reason = "proposal_marked_for_human"
        elif routing_preference in ("direct_apply", "direct_clarification"):
            action = routing_preference
            reason = "proposal_requested_direct_routing"
        elif category == "srs_open_question":
            if impact == "high" or deferred_rounds >= 1 or multi_party:
                action = "formal_meeting"
                reason = "srs_open_question_requires_group_resolution"
            else:
                action = "direct_clarification"
                reason = "single_point_srs_open_question"
        elif category == "requirement_revision":
            if impact in {"low", "medium"} and not multi_party and len(source_ids) <= 1:
                action = "direct_clarification"
                reason = "requirement_revision_needs_scope_check_only"
            else:
                action = "formal_meeting"
                reason = "requirement_revision_affects_srs"
        elif category == "conflict_resolution":
            action = "formal_meeting"
            reason = "conflict_resolution_requires_group_recheck"
        elif category == "tradeoff_decision":
            if multi_party or impact == "high":
                action = "formal_meeting"
                reason = "tradeoff_decision_requires_group_decision"
            else:
                action = "direct_clarification"
                reason = "tradeoff_decision_not_material_yet"
        return {"action": action, "reason": reason}

    @staticmethod
    def active_category(category: str, active_type_ids: List[str]) -> Optional[str]:
        """停用的議題類型不轉換為其他類型，避免改寫 agent 提案語意。"""
        if category in active_type_ids:
            return category
        return None

    def run_meeting_planning_loop(self, action: str, **context: Any) -> Any:
        opa = self.run_action_loop(
            name="meeting_planning",
            context={
                "meeting_planning_action": action,
                **context,
            },
            build_observation=self.build_meeting_planning_observation,
            decide_action=self.decide_meeting_planning_action,
            execute_action=self.execute_meeting_planning_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("error"))
        return result.get("output")

    def build_meeting_planning_observation(self, **kwargs: Any) -> Dict[str, Any]:
        artifact = kwargs.get("artifact") or {}
        issue_pool = kwargs.get("issue_pool")
        return {
            "action": kwargs.get("meeting_planning_action", ""),
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs["max_iterations"],
            "requirements_count": len(requirement_discussion_pool(artifact)),
            "conflicts_count": conflict_entries_count(artifact),
            "open_questions_count": len(artifact.get("open_questions", []) or []),
            "issue_pool_count": len(issue_pool or []) if isinstance(issue_pool, list) else 0,
        }

    def decide_meeting_planning_action(
        self,
        *,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if isinstance(last_result, dict) and not last_result.get("error"):
            return {
                "action": "done",
                "params": {},
                "reasoning": "上一輪 meeting planning 任務已完成，結束本次規劃。",
            }
        action = str(observation.get("action") or "").strip()
        return {
            "action": action,
            "params": {},
            "reasoning": f"執行 meeting planning 任務：{action}。",
        }

    def execute_meeting_planning_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        action = str(decision.get("action") or "").strip()
        try:
            if action == "generate_decision_issues":
                output = self.generate_decision_issues_internal(
                    kwargs.get("artifact") or {},
                    registry=kwargs.get("registry"),
                    max_items=kwargs.get("max_items"),
                    skip_source_ids=kwargs.get("skip_source_ids"),
                    draft_markdown=kwargs.get("draft_markdown"),
                    issue_pool=kwargs.get("issue_pool"),
                )
            elif action == "plan_elicitation":
                output = self.run_elicitation_planning(
                    artifact=kwargs.get("artifact") or {},
                    turn=kwargs.get("turn", 1),
                    max_turns=kwargs.get("max_turns", 1),
                    default_participants=kwargs.get("default_participants") or [],
                    previous_turn_summary=kwargs.get("previous_turn_summary"),
                    recent_ask_history=kwargs.get("recent_ask_history"),
                )
            elif action == "plan_conflict_review":
                output = self.plan_conflict_review_internal(
                    kwargs.get("conflict") or {},
                    artifact=kwargs.get("artifact"),
                    registry=kwargs.get("registry"),
                )
            else:
                raise ValueError(f"未知 meeting planning action: {action}")
        except Exception as e:
            return {
                "action": action,
                "status": "failed",
                "error": str(e),
                "summary": f"meeting planning failed: {action}",
            }
        return {
            "action": action,
            "status": "success",
            "output": output,
            "summary": f"完成 meeting planning: {action}",
        }

    def generate_decision_issues(
        self,
        artifact: Dict[str, Any],
        registry=None,
        max_items: Optional[int] = None,
        skip_source_ids: Optional[set] = None,
        draft_markdown: Optional[str] = None,
        issue_pool: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict]:
        return self.run_meeting_planning_loop(
            "generate_decision_issues",
            artifact=artifact,
            registry=registry,
            max_items=max_items,
            skip_source_ids=skip_source_ids,
            draft_markdown=draft_markdown,
            issue_pool=issue_pool,
        ) or []

    def plan_elicitation(
        self,
        *,
        artifact: Dict[str, Any],
        turn: int,
        max_turns: int,
        default_participants: List[str],
        previous_turn_summary: Optional[Dict[str, Any]] = None,
        recent_ask_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        output = self.run_meeting_planning_loop(
            "plan_elicitation",
            artifact=artifact,
            turn=turn,
            max_turns=max_turns,
            default_participants=default_participants,
            previous_turn_summary=previous_turn_summary,
            recent_ask_history=recent_ask_history,
        )
        if not isinstance(output, dict):
            raise RuntimeError("plan_elicitation 在 agent loop 後未產生有效計畫")
        return output

    def plan_conflict_review(
        self,
        conflict: Dict[str, Any],
        artifact: Optional[Dict[str, Any]] = None,
        registry=None,
    ) -> Dict[str, Any]:
        output = self.run_meeting_planning_loop(
            "plan_conflict_review",
            conflict=conflict,
            artifact=artifact or {},
            registry=registry,
        )
        if not isinstance(output, dict):
            raise RuntimeError("plan_conflict_review 在 agent loop 後未產生有效計畫")
        return output

    def issue_group_key(self, proposal: Dict[str, Any]) -> tuple:
        category = str(proposal.get("category") or "").strip()
        source_ids = [
            str(s).strip()
            for s in (proposal.get("source_ids") or [])
            if str(s).strip()
        ]
        conflict_ids = [
            s for s in source_ids
            if s.startswith(("PAIR-", "MULTIPLE-"))
        ]
        requirement_ids = [
            s for s in source_ids
            if s.startswith(("REQ-", "FR-", "NFR-", "R-", "ELICIT-"))
        ]
        issue_id = str(proposal.get("issue_id") or "").strip()
        if category == "conflict_resolution" and conflict_ids:
            return (category, "conflict", tuple(sorted(conflict_ids)))
        if category in {"srs_open_question", "requirement_revision", "tradeoff_decision"} and requirement_ids:
            return (category, "requirements", tuple(sorted(requirement_ids)))
        if source_ids:
            return (category, "sources", tuple(sorted(source_ids)))
        return (category, "issue", issue_id or str(proposal.get("title") or "").strip())

    @staticmethod
    def merge_issue_texts(values: List[str]) -> str:
        seen = set()
        rows = []
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            rows.append(text)
        if not rows:
            return ""
        if len(rows) == 1:
            return rows[0]
        return "\n".join(f"- {row}" for row in rows)

    def consolidate_issue_proposals(self, proposals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        groups: Dict[tuple, List[Dict[str, Any]]] = {}
        order: List[tuple] = []
        for proposal in proposals:
            key = self.issue_group_key(proposal)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(proposal)

        pri = {"high": 0, "medium": 1, "low": 2}
        consolidated: List[Dict[str, Any]] = []
        for key in order:
            rows = groups[key]
            if len(rows) == 1:
                row = dict(rows[0])
                row.setdefault("source_issue_ids", [row.get("issue_id")] if row.get("issue_id") else [])
                row.setdefault("proposed_by_agents", [row.get("proposed_by")] if row.get("proposed_by") else [])
                row.setdefault("merged_issue_count", 1)
                consolidated.append(row)
                continue

            sorted_rows = sorted(
                rows,
                key=lambda row: (
                    pri.get(str(row.get("priority_hint") or "medium").strip().lower(), 1),
                    -int(row.get("deferred_rounds") or 0),
                    int(row.get("round") or 0),
                    str(row.get("issue_id") or ""),
                ),
            )
            base = dict(sorted_rows[0])
            source_ids: List[str] = []
            participants: List[str] = []
            speaking_order: List[str] = []
            issue_ids: List[str] = []
            proposed_by_agents: List[str] = []
            descriptions: List[str] = []
            why_now: List[str] = []
            needs_human = False
            requires_multi_party = False
            blocks_decision = False
            best_priority = "low"
            best_impact = "low"
            for row in sorted_rows:
                for sid in row.get("source_ids") or []:
                    sid_s = str(sid or "").strip()
                    if sid_s and sid_s not in source_ids:
                        source_ids.append(sid_s)
                for participant in row.get("participants") or []:
                    name = str(participant or "").strip()
                    if name and name not in participants:
                        participants.append(name)
                for participant in row.get("speaking_order") or []:
                    name = str(participant or "").strip()
                    if name and name not in speaking_order:
                        speaking_order.append(name)
                issue_id = str(row.get("issue_id") or "").strip()
                if issue_id and issue_id not in issue_ids:
                    issue_ids.append(issue_id)
                proposer = str(row.get("proposed_by") or "").strip()
                if proposer and proposer not in proposed_by_agents:
                    proposed_by_agents.append(proposer)
                descriptions.append(row.get("description", ""))
                why_now.append(row.get("why_now", ""))
                needs_human = needs_human or bool(row.get("needs_human"))
                requires_multi_party = requires_multi_party or bool(row.get("requires_multi_party"))
                blocks_decision = blocks_decision or bool(row.get("blocks_decision"))
                priority = str(row.get("priority_hint") or "medium").strip().lower()
                impact = str(row.get("impact_level") or priority or "medium").strip().lower()
                if pri.get(priority, 1) < pri.get(best_priority, 2):
                    best_priority = priority
                if pri.get(impact, 1) < pri.get(best_impact, 2):
                    best_impact = impact

            base["title"] = str(base.get("title") or "待命名合併議題").strip()
            base["description"] = self.merge_issue_texts(descriptions)
            base["why_now"] = self.merge_issue_texts(why_now)
            base["source_ids"] = source_ids
            base["source_issue_ids"] = issue_ids
            base["participants"] = participants or base.get("participants", [])
            base["speaking_order"] = [
                p for p in speaking_order if p in set(base["participants"])
            ] or base["participants"]
            base["proposed_by_agents"] = proposed_by_agents
            base["merged_issue_count"] = len(rows)
            base["needs_human"] = needs_human
            base["requires_multi_party"] = requires_multi_party
            base["blocks_decision"] = blocks_decision
            base["priority_hint"] = best_priority
            base["impact_level"] = best_impact
            consolidated.append(base)
        return consolidated

    def triage_issue_proposals(
        self,
        issue_pool: List[Dict[str, Any]],
        *,
        active_type_ids: List[str],
        registered: List[str],
        max_items: int,
        skip_source_ids: Optional[set] = None,
    ) -> Dict[str, Any]:
        skip = skip_source_ids or set()
        dedup = []
        seen = set()
        for p in issue_pool:
            if not isinstance(p, dict):
                continue
            title = (p.get("title") or "").strip()
            category = (p.get("category") or "").strip()
            src = tuple(sorted([str(s) for s in (p.get("source_ids") or []) if str(s).strip()]))
            key = ((p.get("issue_id") or "").strip(), title, category, src)
            if not title or key in seen:
                continue
            if src and all(s in skip for s in src):
                continue
            seen.add(key)
            dedup.append(p)
        dedup_input_count = len(dedup)
        dedup = self.consolidate_issue_proposals(dedup)
        if not dedup:
            return {"items": [], "backlog": [], "meta": {"input_count": 0, "selected_count": 0, "deferred_count": 0}}

        pri = {"high": 0, "medium": 1, "low": 2}
        ordered = sorted(
            dedup,
            key=lambda x: (
                pri.get((x.get("priority_hint") or "medium").strip().lower(), 1),
                -int(x.get("deferred_rounds") or 0),
                int(x.get("round") or 0),
                (x.get("issue_id") or ""),
            ),
        )
        formal_candidates = []
        direct_clarifications = []
        direct_apply = []
        human_queue = []
        for p in ordered:
            route = self.classify_issue_proposal(p)
            row = dict(p)
            row["triage_action"] = route["action"]
            row["triage_reason"] = route["reason"]
            if route["action"] == "formal_meeting":
                formal_candidates.append(row)
            elif route["action"] == "direct_clarification":
                direct_clarifications.append(row)
            elif route["action"] == "direct_apply":
                direct_apply.append(row)
            elif route["action"] == "human_decision":
                human_queue.append(row)

        selected = formal_candidates[:max_items]
        deferred = []
        for p in formal_candidates[max_items:]:
            row = dict(p)
            row["deferred_rounds"] = int(row.get("deferred_rounds") or 0) + 1
            row["deferred_reason"] = "round_capacity_limit"
            deferred.append(row)

        items = []
        for p in selected:
            category = (p.get("category") or "").strip()
            category = self.active_category(category, active_type_ids)
            if not category:
                continue
            normalized = decision_issue(
                {
                    "title": (p.get("title") or "待討論議題").strip(),
                    "description": (p.get("description") or "").strip(),
                    "category": category,
                    "participants": p.get("participants", []),
                    "discussion_mode": p.get("discussion_mode", "sequential"),
                    "speaking_order": p.get("speaking_order", []),
                    "source_ids": p.get("source_ids", []),
                    "source_issue_ids": p.get("source_issue_ids") or ([p.get("issue_id")] if p.get("issue_id") else []),
                    "triage_action": "formal_meeting",
                },
                allowed_categories=active_type_ids or ISSUE_TYPE_IDS,
                registered_agents=registered,
                index=len(items) + 1,
            )
            if normalized:
                items.append(normalized)
        return {
            "items": items,
            "backlog": deferred,
            "direct_clarifications": direct_clarifications,
            "direct_apply": direct_apply,
            "human_queue": human_queue,
            "meta": {
                "input_count_before_consolidation": dedup_input_count,
                "input_count": len(ordered),
                "consolidated_count": len(ordered),
                "merged_issue_count": sum(
                    max(0, int(row.get("merged_issue_count") or 1) - 1)
                    for row in ordered
                ),
                "formal_candidate_count": len(formal_candidates),
                "selected_count": len(items),
                "deferred_count": len(deferred),
                "direct_clarification_count": len(direct_clarifications),
                "direct_apply_count": len(direct_apply),
                "human_queue_count": len(human_queue),
                "round_capacity_limit": max_items,
            },
        }

    def generate_decision_issues_internal(
        self,
        artifact: Dict[str, Any],
        registry=None,
        max_items: Optional[int] = None,
        skip_source_ids: Optional[set] = None,
        draft_markdown: Optional[str] = None,
        issue_pool: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict]:
        """由 Mediator LLM 根據 issue proposal 或專案狀態產生 decision issues。"""
        limit = max_items or 5
        exclude = {"mediator", "documentor"}
        if registry:
            registered = [n for n in registry.get_names() if n not in exclude]
        else:
            registered = ["user", "analyst", "expert", "modeler"]

        active_types, active_ids = self.get_active_issue_types()
        types_text = json.dumps(active_types, ensure_ascii=False, indent=2)
        skip = skip_source_ids or set()
        context = ""
        raw_items = []
        if issue_pool is not None:
            triage = self.triage_issue_proposals(
                issue_pool or [],
                active_type_ids=active_ids,
                registered=registered,
                max_items=limit,
                skip_source_ids=skip,
            )
            raw_items = triage.get("items", [])
            artifact["issue_backlog"] = triage.get("backlog", [])
            artifact["clarification_queue"] = triage.get("direct_clarifications", [])
            artifact["direct_apply_queue"] = triage.get("direct_apply", [])
            artifact["human_decision_queue"] = triage.get("human_queue", [])
            artifact["issue_triage_meta"] = {
                **(triage.get("meta", {}) or {}),
                "mode": "issue_pool",
            }
            self.logger.info(
                "Issue Triage：%s 筆 → 選 %s 遞延 %s（上限 %s）",
                artifact["issue_triage_meta"].get("input_count", 0),
                artifact["issue_triage_meta"].get("selected_count", 0),
                artifact["issue_triage_meta"].get("deferred_count", 0),
                artifact["issue_triage_meta"].get("round_capacity_limit", limit),
            )
        else:
            context = self.build_issue_context(
                artifact, skip, draft_markdown=draft_markdown
            )
            if not context.strip():
                self.logger.info("無足夠內容產生決策議題")
                return []
        if issue_pool is not None and not raw_items:
            self.logger.info("issue_pool 無可用 decision issue，略過本輪 meeting")
            return []

        user_prompt = decision_issues_prompt(
            types_text=types_text,
            context=context,
            skip=skip,
            registered=registered,
            limit=limit,
        )

        if not raw_items:
            messages = self.build_direct_messages(user_prompt)
            try:
                response = self.chat_json(messages)
            except Exception as e:
                raise RuntimeError(f"決策議題生成 LLM 失敗: {e}") from e
            raw_items = response.get("items", [])

        if not raw_items:
            self.logger.info("本輪無新增決策議題")
            return []

        ordered_items = raw_items[:limit]
        ordered_items = self.merge_open_question_items(
            ordered_items,
            artifact,
            registered,
        )
        ordered_items = self.name_meeting_issues(
            ordered_items,
            context_label="正式需求會議開題",
        )

        issue_items = []
        for idx, item in enumerate(ordered_items, 1):
            category = item.get("category", "")
            category = self.active_category(category, active_ids)
            if not category:
                continue
            normalized = decision_issue(
                {
                    **item,
                    "id": item.get("id") or f"T-{idx}",
                    "category": category,
                    "triage_action": item.get("triage_action", "formal_meeting"),
                },
                allowed_categories=active_ids or ISSUE_TYPE_IDS,
                registered_agents=registered,
                index=idx,
            )
            if normalized:
                issue_items.append(normalized)

        return issue_items

    def name_meeting_issues(
        self,
        items: List[Dict],
        *,
        context_label: str = "需求會議",
    ) -> List[Dict]:
        """由 Mediator 統一為會議議題命名；agent proposal title 只當背景參考。"""
        if not items:
            return items
        entries = []
        for i, item in enumerate(items):
            entries.append({
                "index": i,
                "current_title": (item.get("title") or "").strip(),
                "description": (item.get("description") or "").strip(),
                "category": (item.get("category") or "").strip(),
                "participants": item.get("participants") or [],
                "source_ids": item.get("source_ids") or [],
                "source_issue_ids": item.get("source_issue_ids") or [],
            })
        prompt = meeting_title_batch_prompt(
            entries=entries,
            context_label=context_label,
        )
        messages = self.build_direct_messages(prompt)
        data = self.chat_json(messages)
        title_map = meeting_title_batch(data, expected_count=len(items))
        for i, item in enumerate(items):
            new_title = title_map.get(i)
            item["title"] = new_title
        return items

    def name_meeting_issue(
        self,
        issue: Dict[str, Any],
        *,
        context_label: str = "需求會議",
    ) -> str:
        """由 Mediator 為單一會議 issue 命名。"""
        items = self.name_meeting_issues([dict(issue)], context_label=context_label)
        if items:
            return str(items[0].get("title") or "").strip()
        raise ValueError("Mediator meeting title generation returned no items")

    def name_issue_after_discussion(
        self,
        issue: Dict[str, Any],
        contributions: List[Dict],
        resolution: Dict[str, Any],
        *,
        proposer_agent: Optional[str] = None,
    ) -> str:
        """議題討論結束、存檔前：產出精簡、易懂的一句標題（繁體中文）。失敗或空字串時呼叫端應保留原標題。"""
        prev = (issue.get("title") or "").strip()
        desc = (issue.get("description") or "").strip()
        cat = (issue.get("category") or "").strip()
        summary = (resolution.get("summary") or "").strip()
        decision = (resolution.get("decision") or "").strip()
        rstatus = (
            resolution.get("resolution_status")
            or resolution.get("resolution")
            or ""
        )
        rstatus = str(rstatus).strip()
        contrib_lines: List[str] = []
        for c in contributions[:12]:
            if not isinstance(c, dict):
                continue
            ag = c.get("agent", "?")
            resp = c.get("response") or {}
            stmt = (resp.get("text") or "").strip()
            if stmt:
                contrib_lines.append(f"- [{ag}] {stmt}")
        contrib_text = "\n".join(contrib_lines) if contrib_lines else "（無發言摘要）"
        prompt = meeting_title_prompt(
            previous_title=prev,
            category=cat,
            description=desc,
            proposer_agent=proposer_agent,
            summary=summary,
            decision=decision,
            resolution_status=rstatus,
            contribution_text=contrib_text,
        )
        try:
            messages = self.build_direct_messages(prompt)
            data = self.chat_json(messages)
            return meeting_title(data)
        except Exception as e:
            raise RuntimeError(f"議題結束後標題命名失敗: {e}") from e

    def build_issue_context(
        self,
        artifact: Dict[str, Any],
        skip_source_ids: set,
        draft_markdown: Optional[str] = None,
    ) -> str:
        """有最新草稿時僅回傳該份 Markdown（開放問題等皆應已寫在草稿內）；否則回傳 artifact 結構化摘要作為後備。"""
        dm = (draft_markdown or "").strip()
        if dm:
            return "## 最新需求草稿（Markdown，issue 唯一依據）\n" + dm

        parts = []
        conflicts = [
            c
            for c in (artifact.get("conflict_report", []) or [])
            if isinstance(c, dict) and c.get("id", "") not in skip_source_ids
        ]
        if conflicts:
            parts.append(
                "## 最新衝突報告\n" + json.dumps(conflicts, ensure_ascii=False, indent=2)
            )
        system_models = artifact.get("system_models", [])
        models = [
            {
                "name": m.get("name"),
                "type": m.get("type"),
                "source": m.get("source"),
                "has_plantuml": bool(m.get("plantuml")),
                "has_text": bool(m.get("text")),
            }
            for m in (system_models if isinstance(system_models, list) else [])
            if isinstance(m, dict)
        ]
        if models:
            parts.append(
                "## 系統模型\n" + json.dumps(models, ensure_ascii=False, indent=2)
            )
        feedback = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
        if feedback:
            parts.append(
                "## 領域研究回饋\n"
                + json.dumps(feedback, ensure_ascii=False, indent=2)
            )

        if parts:
            return (
                "## 正式會議輸入摘要（無可用需求草稿檔時之後備依據）\n"
                + "\n\n".join(parts)
            )
        return ""

    def merge_open_question_items(
        self,
        items: List[Dict[str, Any]],
        artifact: Dict[str, Any],
        registered: List[str],
    ) -> List[Dict[str, Any]]:
        """
        將多個 srs_open_question 決策議題合併為單一議題，避免逐題拆散討論。
        需求：只要有 srs_open_question，就由相關 agent 在同一題集中回覆。
        """
        open_items = [it for it in items if (it.get("category") or "").strip() == "srs_open_question"]
        if not open_items:
            return items

        related_agents = set()
        for it in open_items:
            for a in (it.get("participants", []) or []):
                if a in registered:
                    related_agents.add(a)
            for a in (it.get("speaking_order", []) or []):
                if a in registered:
                    related_agents.add(a)

        escalated_questions: List[str] = []
        for q in artifact.get("open_questions", []):
            if q.get("status") == "answered":
                continue
            if not self.should_escalate_open_question(q):
                continue
            to_agent = (q.get("to") or q.get("to_agent") or "").strip()
            if to_agent in registered:
                related_agents.add(to_agent)
            question = str(q.get("question") or "").strip()
            if question:
                escalated_questions.append(f"- {question}")

        participants = [a for a in registered if a in related_agents]
        if not participants:
            participants = list(registered)

        source_ids: List[str] = []
        source_issue_ids: List[str] = []
        descriptions: List[str] = []
        titles: List[str] = []
        seen_ids = set()
        seen_issue_ids = set()
        for it in open_items:
            title = str(it.get("title") or "").strip()
            description = str(it.get("description") or "").strip()
            if title:
                titles.append(title)
            if description:
                descriptions.append(f"- {title or 'srs_open_question'}: {description}")
            for sid in (it.get("source_ids", []) or []):
                if not sid or sid in seen_ids:
                    continue
                seen_ids.add(sid)
                source_ids.append(sid)
            for issue_id in (it.get("source_issue_ids", []) or []):
                issue_id = str(issue_id or "").strip()
                if issue_id and issue_id not in seen_issue_ids:
                    seen_issue_ids.add(issue_id)
                    source_issue_ids.append(issue_id)

        merged_title = "待命名開放問題議題"
        body_parts = []
        if descriptions:
            body_parts.append("來源議題：\n" + "\n".join(descriptions))
        if escalated_questions:
            body_parts.append("待回覆 SRS 待確認問題：\n" + "\n".join(escalated_questions))
        if not body_parts:
            body_parts.append("本議題缺少具體 SRS 待確認問題；請先確認來源 proposal 是否可補齊。")

        merged_item = {
            "title": merged_title,
            "description": "\n\n".join(body_parts),
            "category": "srs_open_question",
            "participants": participants,
            "discussion_mode": "simultaneous",
            "speaking_order": participants,
            "source_ids": source_ids,
            "source_issue_ids": source_issue_ids,
        }

        merged: List[Dict[str, Any]] = []
        inserted = False
        for it in items:
            if (it.get("category") or "").strip() == "srs_open_question":
                if not inserted:
                    merged.append(merged_item)
                    inserted = True
                continue
            merged.append(it)
        return merged

    @staticmethod
    def should_escalate_open_question(q: Dict[str, Any]) -> bool:
        """判斷 open question 是否應升級為正式 decision issue。"""
        if not isinstance(q, dict):
            return False
        if q.get("status") == "answered":
            return False
        if q.get("needs_issue") is True:
            return True
        if q.get("status") == "escalate_to_issue":
            return True
        if int(q.get("deferred_count") or 0) >= 2:
            return True
        return False

    def plan_meeting_action_internal(
        self,
        state_summary: Dict[str, Any],
        last_observation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Meeting action 的實際 planner；由 OPA path 呼叫。"""
        last_observation = last_observation or {}
        user_prompt = meeting_action_prompt(
            state_summary=state_summary,
            last_observation=last_observation,
            enable_human_escalation=self.enable_human_escalation,
        )

        messages = self.build_direct_messages(user_prompt)
        try:
            if "artifact_query" in self.tools:
                raw = self.chat_with_tools(messages)
                response = self.parse_issue_response_json(raw)
            else:
                response = self.chat_json(messages)
        except Exception as e:
            raise RuntimeError(f"meeting action LLM 輸出格式不合格: {e}") from e

        return meeting_action_decision(response)

    def run_elicitation_planning(
        self,
        *,
        artifact: Dict[str, Any],
        turn: int,
        max_turns: int,
        default_participants: List[str],
        previous_turn_summary: Optional[Dict[str, Any]] = None,
        recent_ask_history: Optional[List[Dict[str, Any]]] = None,
        ) -> Dict[str, Any]:
        """由 Mediator 逐輪決定需求擷取會議階段、發言模式、參與者與訪談對象。"""
        prev = previous_turn_summary or {}
        default_interviewers = [p for p in default_participants if p != "user"]
        stakeholder_names = [
            str(row.get("name") or "").strip()
            for row in (artifact.get("stakeholders", []) or [])
            if isinstance(row, dict) and str(row.get("name") or "").strip()
        ]
        if not stakeholder_names:
            stakeholder_names = ["user"]
        current_requirements = [
            {
                "id": str(req.get("id") or "").strip(),
                "text": str(req.get("text") or "").strip(),
                "type": str(req.get("type") or "").strip(),
            }
            for req in requirement_discussion_pool(artifact)
            if isinstance(req, dict) and str(req.get("text") or "").strip()
        ]
        prompt = elicitation_plan_prompt(
            turn=turn,
            max_turns=max_turns,
            default_participants=default_participants,
            stakeholder_names=stakeholder_names,
            scenario=artifact.get("scenario", {}),
            scope=artifact.get("scope", {}),
            current_requirements=current_requirements,
            previous_turn_summary=prev,
            recent_ask_history=recent_ask_history,
        )

        messages = self.build_direct_messages(prompt)
        try:
            data = self.chat_json(messages)
        except Exception as e:
            raise RuntimeError(f"逐輪策略決策輸出格式不合格: {e}") from e
        return elicitation_plan(
            data,
            default_participants=default_participants,
            stakeholder_names=stakeholder_names,
        )

    def plan_conflict_review_internal(
        self,
        conflict: Dict[str, Any],
        artifact: Optional[Dict[str, Any]] = None,
        registry=None,
    ) -> Dict[str, Any]:
        """由主持人模型動態決定衝突再審查的討論模式。

        - 僅回傳 ``discussion_mode`` 與 ``participants``。
        - **sequential**：發言順序完全由 ``participants`` 陣列順序表達，**不**另產生
          ``speaking_order``（下游亦不得推導寫入 record）。
        - **simultaneous**：多人並行發言，同樣不產生 ``speaking_order``。
        """
        participants_def: List[str] = []
        if registry:
            participants_def = [
                n
                for n in registry.get_names()
                if n in {"analyst", "expert", "modeler"}
            ]
        if not participants_def:
            participants_def = ["analyst", "expert", "modeler"]

        n_candidates = 0
        if isinstance(artifact, dict):
            for c in all_conflict_rows(artifact):
                if not isinstance(c, dict):
                    continue
                if str(c.get("label") or "").strip() in {"Conflict", "Neutral"}:
                    n_candidates += 1

        prompt = conflict_review_prompt(
            participants=participants_def,
            candidate_count=n_candidates,
        )
        try:
            messages = self.build_direct_messages(prompt)
            data = self.chat_json(messages)
        except Exception as e:
            raise RuntimeError(f"plan_conflict_review 輸出格式不合格: {e}") from e
        return conflict_review_plan(
            data,
            allowed_participants=participants_def,
        )
