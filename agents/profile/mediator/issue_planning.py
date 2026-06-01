# Mediator issue planning: triage issue proposals and generate formal meeting issues.
import json
from typing import Any, Dict, List, Optional

from agents.profile.analyst.conflict_store import all_conflict_rows, conflict_entries_count
from agents.profile.analyst.requirements import requirement_discussion_pool

from .prompts import (
    meeting_action_prompt,
    issue_selection_prompt,
    issue_meeting_plan_prompt,
    elicitation_plan_prompt,
    conflict_review_prompt,
)
from .validation import (
    ISSUE_TYPE_IDS,
    ISSUE_TYPES,
    meeting_action_decision,
    meeting_issue,
    elicitation_plan,
    issue_proposal,
    conflict_review_plan,
)


class MediatorIssuePlanning:
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

    @staticmethod
    def active_category(category: str, active_type_ids: List[str]) -> Optional[str]:
        """Reject disabled issue categories."""
        category = str(category or "").strip()
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
            "backlog_count": len(issue_pool or []) if isinstance(issue_pool, list) else 0,
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
            if action == "plan_issues":
                output = self.plan_issues_internal(
                    kwargs.get("artifact") or {},
                    registry=kwargs.get("registry"),
                    max_items=kwargs.get("max_items"),
                    skip_source_ids=kwargs.get("skip_source_ids"),
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

    def plan_issues(
        self,
        artifact: Dict[str, Any],
        registry=None,
        max_items: Optional[int] = None,
        skip_source_ids: Optional[set] = None,
        issue_pool: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict]:
        return self.run_meeting_planning_loop(
            "plan_issues",
            artifact=artifact,
            registry=registry,
            max_items=max_items,
            skip_source_ids=skip_source_ids,
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

    @staticmethod
    def artifact_source(artifact: Dict[str, Any], meeting_artifact: Dict[str, Any]) -> Dict[str, Any]:
        """Use the full artifact when loaded; otherwise use the meeting artifact."""
        return artifact if isinstance(artifact, dict) and artifact else meeting_artifact

    @staticmethod
    def related_items(rows: Any, source_ids: List[str], *, limit: int = 20) -> List[Dict[str, Any]]:
        if not isinstance(rows, list):
            return []
        ids = {str(x).strip() for x in source_ids if str(x).strip()}
        if not ids:
            return [row for row in rows if isinstance(row, dict)]
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_id = str(row.get("id") or row.get("issue_id") or "").strip()
            blob = json.dumps(row, ensure_ascii=False)
            if row_id not in ids and not any(source_id in blob for source_id in ids):
                continue
            out.append(row)
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def related_feedback(feedback: Any, source_ids: List[str]) -> Dict[str, Any]:
        if not isinstance(feedback, dict):
            return {}
        ids = {str(x).strip() for x in source_ids if str(x).strip()}
        if not ids:
            return {}
        related: Dict[str, Any] = {}
        for section in ("findings", "constraints", "risks", "recommendations"):
            rows = []
            for idx, row in enumerate(feedback.get(section) or [], 1):
                if not isinstance(row, dict):
                    continue
                row_id = str(row.get("id") or f"{section}_{idx}").strip()
                related_ids = {
                    str(value).strip()
                    for value in (row.get("related_requirement_ids") or [])
                    if str(value).strip()
                }
                source = str(row.get("source") or "").strip()
                if row_id in ids or source in ids or related_ids.intersection(ids):
                    item = dict(row)
                    item.setdefault("id", row_id)
                    rows.append(item)
            if rows:
                related[section] = rows
        return related

    def related_artifact_context(
        self,
        issue: Dict[str, Any],
        artifact: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build focused artifact context for a single issue proposal."""
        full_artifact = self.load_artifact_context_from_files()
        source = self.artifact_source(full_artifact, artifact)
        meeting_source = artifact if isinstance(artifact, dict) else {}
        related_rows = issue.get("sources") if isinstance(issue, dict) else []
        context: Dict[str, Any] = {}

        def add_section(name: str, value: Any) -> None:
            if value in (None, [], {}):
                return
            context[name] = value

        for rel in related_rows or []:
            if not isinstance(rel, dict):
                continue
            artifact_name = str(rel.get("artifact") or "").strip()
            source_ids = [
                str(x).strip()
                for x in (rel.get("ids") or [])
                if str(x).strip()
            ]
            if not artifact_name:
                continue

            if artifact_name in {"requirements", "requirement", "user_requirements"}:
                rows = requirement_discussion_pool(source) or requirement_discussion_pool(meeting_source)
                add_section("requirements", self.related_items(rows, source_ids))
                continue

            if artifact_name == "conflict_report":
                conflict = source.get("conflict") if isinstance(source.get("conflict"), dict) else {}
                rows = conflict.get("report") if isinstance(conflict.get("report"), list) else meeting_source.get("conflict_report", [])
                add_section("conflict_report", self.related_items(rows, source_ids))
                continue

            if artifact_name in {"system_models", "models", "model"}:
                rows = source.get("system_models") if isinstance(source.get("system_models"), list) else meeting_source.get("system_models", [])
                add_section("system_models", self.related_items(rows, source_ids, limit=12))
                continue

            if artifact_name in {"open_questions", "open_question"}:
                rows = source.get("open_questions") if isinstance(source.get("open_questions"), list) else meeting_source.get("open_questions", [])
                add_section("open_questions", self.related_items(rows, source_ids, limit=20))
                continue

            if artifact_name in {"conversation", "discussions"}:
                discussions = source.get("discussions") if isinstance(source.get("discussions"), list) else []
                decisions = source.get("decisions") if isinstance(source.get("decisions"), list) else []
                add_section("discussions", self.related_items(discussions, source_ids, limit=10))
                add_section("decisions", self.related_items(decisions, source_ids, limit=10))
                continue

            if artifact_name == "scope":
                add_section("scope", source.get("scope") or meeting_source.get("scope"))
                continue

            if artifact_name == "feedback":
                feedback = source.get("feedback") or meeting_source.get("feedback")
                add_section("feedback", self.related_feedback(feedback, source_ids))
                continue

            value = source.get(artifact_name) or meeting_source.get(artifact_name)
            if isinstance(value, list):
                value = self.related_items(value, source_ids, limit=20)
            add_section(artifact_name, value)

        return context

    def triage_issue_proposals(
        self,
        issue_pool: List[Dict[str, Any]],
        *,
        artifact: Optional[Dict[str, Any]] = None,
        active_type_ids: List[str],
        registered: List[str],
        max_items: int,
        skip_source_ids: Optional[set] = None,
        is_last_round: bool = False,
        round_num: Optional[int] = None,
    ) -> Dict[str, Any]:
        skip = skip_source_ids or set()
        default_proposals = []
        proposals = []
        seen = set()
        for p in issue_pool:
            if not isinstance(p, dict):
                continue
            p = dict(p)
            title = (p.get("title") or "").strip()
            related = []
            for x in p.get("sources") or []:
                if isinstance(x, dict):
                    artifact_name = str(x.get("artifact") or "").strip()
                    source_ids = tuple(str(s).strip() for s in (x.get("ids") or []) if str(s).strip())
                    if artifact_name:
                        related.append((artifact_name, source_ids))
            src = tuple(sorted(related))
            key = ((p.get("issue_id") or "").strip(), title, src)
            if not title or key in seen:
                continue
            seen.add(key)
            if (p.get("proposed_by") or "").strip() == "mediator":
                default_proposals.append(p)
                continue
            proposals.append(p)
        if not default_proposals and not proposals:
            return {
                "issues": [],
                "backlog": [],
                "discarded": [],
            }

        triage = {"issues": [], "backlog": [], "discarded": []}
        if proposals:
            prompt = issue_selection_prompt(
                proposals=proposals,
                max_items=max_items,
                skip_source_ids=sorted(str(s) for s in skip),
                is_last_round=is_last_round,
                round_num=int(round_num or 1),
            )
            try:
                triage = self.chat_json(self.build_direct_messages(prompt))
            except Exception as e:
                raise RuntimeError(f"Issue triage LLM failed: {e}") from e
            if not isinstance(triage, dict):
                raise RuntimeError("Issue triage must return a JSON object")

        selected_proposals = default_proposals + [
            p for p in (triage.get("issues") or []) if isinstance(p, dict)
        ]
        general_type_ids = list(active_type_ids or ISSUE_TYPE_IDS)
        is_default_conflict = lambda proposal: (
            isinstance(proposal, dict)
            and str(proposal.get("proposed_by") or "").strip() == "mediator"
            and str(proposal.get("title") or "").strip() == "解決需求衝突"
        )
        category_definitions = "\n".join(
            f"- {t['id']}：{t.get('description') or t.get('label') or t['id']}"
            for t in ISSUE_TYPES
            if t["id"] in set(general_type_ids)
        )
        stakeholder_names = []
        for row in ((artifact or {}).get("stakeholders", []) or []):
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            if name:
                stakeholder_names.append(name)
        meeting_issues = []
        for proposal in selected_proposals:
            default_title = str(proposal.get("title") or "").strip()
            if str(proposal.get("proposed_by") or "").strip() == "mediator":
                if default_title == "解決需求衝突":
                    proposal.setdefault("category", "resolve_conflict")
                    proposal.setdefault("participants", ["user", "analyst"])
                    proposal.setdefault("discussion_mode", "sequential")
                    proposal.setdefault("expected_actions", {"analyst": ["discuss_conflict"]})
                elif default_title == "需求分類":
                    proposal.setdefault("category", "clarify_requirement")
                    proposal.setdefault("participants", ["analyst", "user"])
                    proposal.setdefault("discussion_mode", "sequential")
                    proposal.setdefault("expected_actions", {"analyst": ["refine_requirement"]})
            if (
                str(proposal.get("proposed_by") or "").strip() == "mediator"
                and proposal.get("category")
                and proposal.get("participants")
            ):
                meeting_issues.append(
                    {
                        "title": proposal.get("title", ""),
                        "description": "",
                        "category": proposal.get("category", ""),
                        "participants": proposal.get("participants", []),
                        "discussion_mode": proposal.get("discussion_mode", "sequential"),
                        **({"discussion_rounds": proposal.get("discussion_rounds")} if proposal.get("discussion_rounds") else {}),
                        "target_stakeholders": (
                            proposal.get("target_stakeholders")
                            or (
                                stakeholder_names
                                if "user" in (proposal.get("participants") or [])
                                else []
                            )
                        ),
                        "trace": {
                            "artifact_ids": [
                                source_id
                                for source in (proposal.get("sources") or [])
                                if isinstance(source, dict)
                                for source_id in (source.get("ids") or [])
                                if str(source_id).strip()
                            ],
                            "proposal_ids": [proposal.get("issue_id", "")],
                        },
                        "proposed_by": "mediator",
                        "expected_actions": proposal.get("expected_actions", {}),
                    }
                )
                continue
            proposal_type_ids = list(general_type_ids)
            proposal_category_definitions = category_definitions
            if is_default_conflict(proposal):
                proposal_type_ids = list(dict.fromkeys(proposal_type_ids + ["resolve_conflict"]))
                proposal_category_definitions = (
                    category_definitions
                    + "\n- resolve_conflict：預設需求衝突會議專用；採用或調整既有 resolution，讓需求一致。"
                ).strip()
            artifact_context = self.related_artifact_context(
                proposal,
                artifact or {},
            )
            plan_prompt = issue_meeting_plan_prompt(
                issue=proposal,
                artifact_context=artifact_context,
                active_types=proposal_type_ids,
                category_definitions=proposal_category_definitions,
                registered=registered,
                stakeholder_names=stakeholder_names,
            )
            try:
                planned = self.chat_json(self.build_direct_messages(plan_prompt))
            except Exception as e:
                raise RuntimeError(f"Issue meeting planning LLM failed: {e}") from e
            if not isinstance(planned, dict):
                raise RuntimeError("Issue meeting planning must return a JSON object")
            for row in planned.get("issues") or []:
                if isinstance(row, dict):
                    row.setdefault("proposed_by", proposal.get("proposed_by", ""))
                    row.setdefault("trace", {"artifact_ids": [], "proposal_ids": [proposal.get("issue_id", "")]})
                    if proposal.get("expected_actions") and not row.get("expected_actions"):
                        row["expected_actions"] = proposal.get("expected_actions")
                    for key in ("participants", "discussion_mode", "discussion_rounds"):
                        if proposal.get(key) and not row.get(key):
                            row[key] = proposal.get(key)
                    meeting_issues.append(row)

        items = []
        for p in meeting_issues:
            if not isinstance(p, dict):
                continue
            normalized = meeting_issue(
                p,
                allowed_categories=(
                    list(dict.fromkeys(general_type_ids + ["resolve_conflict"]))
                    if str(p.get("title") or "").strip() == "解決需求衝突"
                    else general_type_ids
                ),
                registered_agents=registered,
                allowed_stakeholders=stakeholder_names,
                index=len(items) + 1,
            )
            if normalized:
                items.append(normalized)

        def backlog_rows() -> List[Dict[str, Any]]:
            rows = []
            for row in triage.get("backlog") or []:
                if not isinstance(row, dict):
                    continue
                rows.append(dict(row))
            return rows

        def discarded_rows() -> List[Dict[str, Any]]:
            rows = []
            for row in triage.get("discarded") or []:
                if not isinstance(row, dict):
                    continue
                rows.append(dict(row))
            return rows

        return {
            "issues": items,
            "backlog": backlog_rows(),
            "discarded": discarded_rows(),
        }

    def plan_issues_internal(
        self,
        artifact: Dict[str, Any],
        registry=None,
        max_items: Optional[int] = None,
        skip_source_ids: Optional[set] = None,
        issue_pool: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict]:
        """根據 issue proposals 產生正式會議議題。"""
        limit = max_items or 5
        exclude = {"mediator", "documentor"}
        if registry:
            registered = [n for n in registry.get_names() if n not in exclude]
        else:
            registered = ["user", "analyst", "expert", "modeler"]

        _, active_ids = self.get_active_issue_types()
        skip = skip_source_ids or set()
        raw_items = []

        if issue_pool is None:
            raise ValueError("plan_issues requires issue_pool")

        meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
        try:
            current_round = int((issue_pool[0] or {}).get("round") or meta.get("last_round") or 1) if issue_pool else int(meta.get("last_round") or 1)
        except (AttributeError, TypeError, ValueError):
            current_round = 1
        config = getattr(self, "config", {}) or {}
        try:
            end_round = int(meta.get("meeting_end_round") or config.get("rounds", 1) or 1)
        except (TypeError, ValueError):
            end_round = 1
        is_last_round = current_round >= end_round
        triage_pool = list(issue_pool or [])
        triage = self.triage_issue_proposals(
            triage_pool,
            artifact=artifact,
            active_type_ids=active_ids,
            registered=registered,
            max_items=limit,
            skip_source_ids=skip,
            is_last_round=is_last_round,
            round_num=current_round,
        )
        raw_items = triage.get("issues", [])
        artifact["issue_backlog"] = triage.get("backlog", [])
        artifact["issue_discarded"] = triage.get("discarded", [])
        default_count = len(
            [
                row for row in raw_items
                if isinstance(row, dict)
                and str(row.get("proposed_by") or "").strip() == "mediator"
            ]
        )
        self.logger.info(
            "Issue Triage：%s 筆 → 預設 %s 額外 %s backlog %s discarded %s（額外上限 %s）",
            len(triage_pool),
            default_count,
            max(0, len(raw_items) - default_count),
            len(artifact["issue_backlog"]),
            len(artifact["issue_discarded"]),
            limit,
        )

        if not raw_items:
            self.logger.info("issue_pool 無可用正式會議議題，略過本輪 meeting")
            return []

        if not raw_items:
            self.logger.info("本輪無新增決策議題")
            return []

        default_items = [
            item for item in raw_items
            if isinstance(item, dict)
            and str(item.get("proposed_by") or "").strip() == "mediator"
        ]
        extra_items = [
            item for item in raw_items
            if isinstance(item, dict)
            and str(item.get("proposed_by") or "").strip() != "mediator"
        ]
        ordered_items = default_items + extra_items[:limit]
        ordered_items = self.merge_open_question_items(
            ordered_items,
            artifact,
            registered,
        )

        issue_items = []
        for idx, item in enumerate(ordered_items, 1):
            category = item.get("category", "")
            if (
                str(item.get("title") or "").strip() == "解決需求衝突"
                and str(category or "").strip() == "resolve_conflict"
            ):
                category = "resolve_conflict"
                allowed_categories = list(dict.fromkeys(list(active_ids or ISSUE_TYPE_IDS) + ["resolve_conflict"]))
            else:
                category = self.active_category(category, active_ids)
                allowed_categories = active_ids or ISSUE_TYPE_IDS
            if not category:
                continue
            normalized = meeting_issue(
                {
                    **item,
                    "id": item.get("id") or f"T-{idx}",
                    "category": category,
                },
                allowed_categories=allowed_categories,
                registered_agents=registered,
                index=idx,
            )
            if normalized:
                issue_items.append(normalized)

        return issue_items

    def merge_open_question_items(
        self,
        items: List[Dict[str, Any]],
        artifact: Dict[str, Any],
        registered: List[str],
    ) -> List[Dict[str, Any]]:
        """
        將多個 open question 來源合併為單一需求釐清議題，避免逐題拆散討論。
        需求：只要有 open question 來源，就由相關 agent 在同一題集中回覆。
        """
        open_question_items = [
            it for it in items
            if (it.get("category") or "").strip() == "clarify_requirement"
            and any(
                str(src).strip().startswith("OQ-")
                for src in ((it.get("trace") or {}).get("artifact_ids", []) or [])
            )
        ]
        if not open_question_items:
            return items

        related_agents = set()
        for it in open_question_items:
            for a in (it.get("participants", []) or []):
                if a in registered:
                    related_agents.add(a)

        issue_questions: List[str] = []
        question_source_ids: List[str] = []
        expected_actions: Dict[str, List[str]] = {}
        requested_oq_ids = {
            str(src).strip()
            for it in open_question_items
            for src in ((it.get("trace") or {}).get("artifact_ids", []) or [])
            if str(src).strip().startswith("OQ-")
        }
        for q in artifact.get("open_questions", []):
            if q.get("status") == "answered":
                continue
            qid = str(q.get("id") or "").strip()
            if qid not in requested_oq_ids and not self.should_add_open_question_issue(q):
                continue
            to_agent = (q.get("to") or q.get("to_agent") or "").strip()
            if to_agent in registered:
                related_agents.add(to_agent)
                expected_actions.setdefault(to_agent, [])
                if "answer_question" not in expected_actions[to_agent]:
                    expected_actions[to_agent].append("answer_question")
            question = str(q.get("question") or "").strip()
            if question:
                issue_questions.append(f"- {question}")
            if qid:
                question_source_ids.append(qid)

        participants = [a for a in registered if a in related_agents]
        if not participants:
            participants = list(registered)

        source_ids: List[str] = []
        proposal_ids: List[str] = []
        descriptions: List[str] = []
        titles: List[str] = []
        seen_ids = set()
        seen_proposal_ids = set()
        for it in open_question_items:
            title = str(it.get("title") or "").strip()
            description = str(it.get("description") or "").strip()
            if title:
                titles.append(title)
            if description:
                descriptions.append(f"- {title or 'open question'}: {description}")
            trace = it.get("trace") if isinstance(it.get("trace"), dict) else {}
            for sid in (trace.get("artifact_ids", []) or []):
                if not sid or sid in seen_ids:
                    continue
                seen_ids.add(sid)
                source_ids.append(sid)
            for proposal_id in (trace.get("proposal_ids", []) or []):
                proposal_id = str(proposal_id or "").strip()
                if proposal_id and proposal_id not in seen_proposal_ids:
                    seen_proposal_ids.add(proposal_id)
                    proposal_ids.append(proposal_id)
            item_expected = it.get("expected_actions") if isinstance(it.get("expected_actions"), dict) else {}
            for agent, actions in item_expected.items():
                if agent not in registered:
                    continue
                expected_actions.setdefault(agent, [])
                for action in actions if isinstance(actions, list) else [actions]:
                    action_name = str(action or "").strip()
                    if action_name and action_name not in expected_actions[agent]:
                        expected_actions[agent].append(action_name)
        for qid in question_source_ids:
            if qid not in seen_ids:
                seen_ids.add(qid)
                source_ids.append(qid)

        merged_title = "釐清待回答需求問題"
        body_parts = []
        if descriptions:
            body_parts.append("來源議題：\n" + "\n".join(descriptions))
        if issue_questions:
            body_parts.append("待回覆開放問題：\n" + "\n".join(issue_questions))
        if not body_parts:
            body_parts.append("本議題缺少具體開放問題；請先確認來源 proposal 是否可補齊。")

        merged_item = {
            "title": merged_title,
            "description": "\n\n".join(body_parts),
            "category": "clarify_requirement",
            "participants": participants,
            "discussion_mode": "simultaneous",
            "trace": {"artifact_ids": source_ids, "proposal_ids": proposal_ids},
            "expected_actions": expected_actions,
        }

        merged: List[Dict[str, Any]] = []
        inserted = False
        for it in items:
            if it in open_question_items:
                if not inserted:
                    merged.append(merged_item)
                    inserted = True
                continue
            merged.append(it)
        return merged

    @staticmethod
    def should_add_open_question_issue(q: Dict[str, Any]) -> bool:
        """判斷 open question 是否應升級為正式會議議題。"""
        if not isinstance(q, dict):
            return False
        if q.get("status") == "answered":
            return False
        if q.get("needs_issue") is True:
            return True
        if q.get("status") == "add_to_issue":
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
            enable_human_judgment=self.enable_human_judgment,
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
            scenario=artifact.get("scenario", ""),
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
        - **sequential**：衝突再審查的發言順序由 ``participants`` 陣列順序表達。
        - **simultaneous**：多人並行發言。
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
