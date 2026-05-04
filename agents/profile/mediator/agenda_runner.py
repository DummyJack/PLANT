# Decision topic runner: executes agenda actions and records meeting traces.
from typing import Dict, List, Any, Optional

from .agent import MediatorAgent
from .validation import AGENDA_ACTIONS, AGENDA_CATEGORY_LABEL


class AgendaRunner:
    """執行 decision topic 相關動作，維護本輪 topics、topic_status、round_discussions、all_open_questions。"""

    def __init__(
        self,
        mediator_agent: MediatorAgent,
        registry,
        artifact: Dict[str, Any],
        issue_pool: Optional[List[Dict[str, Any]]],
        round_num: int,
        config: Dict[str, Any],
        store,
        collect_module,
        logger,
    ):
        self.mediator = mediator_agent
        self.registry = registry
        self.artifact = artifact
        self.round_num = round_num
        self.config = config
        self.store = store
        self.collect = collect_module
        self.logger = logger
        self.issue_pool = list(issue_pool or [])

        self.topics: List[Dict] = []
        self.topic_status: Dict[str, Dict] = {}
        self.round_discussions: List[Dict] = []
        self.all_open_questions: List[Dict] = []
        self.topic_idx = 0

    def topic_open_questions(self, topic_id: str) -> List[Dict]:
        return [q for q in self.all_open_questions if q.get("topic_id") == topic_id]

    def update_design_rationale_for_topic(
        self,
        topic: Dict[str, Any],
        contributions: List[Dict],
        resolution: Dict[str, Any],
    ) -> None:
        """每個議題存檔後即時更新 design_rationale.md。"""
        try:
            topic_id = topic.get("id", "")
            topic_oq = self.topic_open_questions(topic_id)
            topic_context = self.mediator.build_design_rationale_entry_context(
                topic=topic,
                contributions=contributions,
                resolution=resolution,
                topic_open_questions=topic_oq,
                round_num=self.round_num,
            )

            dr_path = self.store.output_dir / "design_rationale.md"
            if dr_path.exists():
                existing_md = dr_path.read_text(encoding="utf-8")
                dr_md = self.mediator.update_design_rationale(existing_md, topic_context)
            else:
                dr_md = self.mediator.generate_design_rationale(topic_context)
            self.store.save_markdown(dr_md, "design_rationale.md")
            self.logger.info(f"  ✓ 已更新 design_rationale.md（{topic_id}）")
        except Exception as e:
            self.logger.warning(f"  更新 design_rationale.md 失敗: {e}")

    def observe_action(self, action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = params or {}
        action = self.normalize_action_name(action)
        state = self.get_state_summary()
        return {
            "action": action,
            "params": params,
            "topics_count": len(self.topics),
            "round_discussions_count": len(self.round_discussions),
            "open_questions_count": len(self.all_open_questions),
            "state_summary": state,
        }

    def record_runner_opa_trace(
        self,
        *,
        stage: str,
        action: str,
        params: Dict[str, Any],
        observation: Dict[str, Any],
        decision: Dict[str, Any],
        result: Dict[str, Any],
        topic_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        trace_rows = [
            {
                "agent": "agenda_runner",
                "mode": "agenda_action",
                "iteration": 1,
                "observation": {
                    "action": observation.get("action"),
                    "topics_count": observation.get("topics_count"),
                    "round_discussions_count": observation.get("round_discussions_count"),
                    "open_questions_count": observation.get("open_questions_count"),
                },
                "decision": {
                    "action": decision.get("action"),
                    "params": decision.get("params") or {},
                    "reasoning": decision.get("reasoning", ""),
                },
                "result": {
                    "error": result.get("error"),
                    "result": result.get("result"),
                },
            }
        ]
        self.artifact.setdefault("meeting_opa_trace", []).extend(
            {
                "stage": stage,
                "topic_id": topic_id,
                "topic_title": None,
                "topic_category": None,
                "agent": "agenda_runner",
                "trace": row,
            }
            for row in trace_rows
        )
        return trace_rows

    def record_action_substep_trace(
        self,
        *,
        stage: str,
        topic: Optional[Dict[str, Any]],
        substep: str,
        observation: Dict[str, Any],
        decision: Dict[str, Any],
        result: Dict[str, Any],
    ) -> None:
        self.artifact.setdefault("meeting_opa_trace", []).append(
            {
                "stage": stage,
                "topic_id": (topic or {}).get("id"),
                "topic_title": (topic or {}).get("title"),
                "topic_category": (topic or {}).get("category"),
                "agent": "agenda_runner",
                "trace": {
                    "agent": "agenda_runner",
                    "mode": "action_substep",
                    "iteration": 1,
                    "observation": observation,
                    "decision": decision,
                    "result": result,
                    "substep": substep,
                },
            }
        )

    def resolve_topic_via_substeps(
        self,
        *,
        topic: Dict[str, Any],
        contributions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        stage = "agenda_runner.resolve_topic"
        topic_id = topic.get("id")

        converge_obs = {
            "topic_id": topic_id,
            "contributions_count": len(contributions),
        }
        converge_decision = {
            "action": "assess_convergence",
            "params": {"topic_id": topic_id},
            "reasoning": "先判斷議題是否已收斂；未收斂時改整理決策選項與建議，不進行 agent 投票。",
        }
        convergence = self.mediator.assess_discussion_convergence(topic, contributions)
        self.record_action_substep_trace(
            stage=stage,
            topic=topic,
            substep="resolve.assess_convergence",
            observation=converge_obs,
            decision=converge_decision,
            result={
                "converged": bool(convergence.get("converged")),
                "reason": convergence.get("reason", ""),
            },
        )

        suggested_next_actions = self.mediator.collect_suggested_next_actions(contributions)

        if convergence.get("converged"):
            resolution_decision = {
                "action": "build_converged_resolution",
                "params": {"topic_id": topic_id},
                "reasoning": "討論已收斂，直接生成收斂型決議。",
            }
            resolution = self.mediator.build_converged_resolution(
                topic, contributions, convergence,
            )
            resolution["suggested_next_actions"] = suggested_next_actions
            self.record_action_substep_trace(
                stage=stage,
                topic=topic,
                substep="resolve.build_converged_resolution",
                observation={
                    "topic_id": topic_id,
                    "convergence_reason": convergence.get("reason", ""),
                },
                decision=resolution_decision,
                result={
                    "resolution_status": resolution.get("resolution_status", ""),
                    "summary": resolution.get("summary", ""),
                },
            )
        else:
            options_decision = {
                "action": "analyze_decision_options",
                "params": {"topic_id": topic_id},
                "reasoning": "討論未收斂，整理成可供使用者確認的選項、影響與建議。",
            }
            decision_analysis = self.mediator.analyze_decision_options(topic, contributions)
            self.record_action_substep_trace(
                stage=stage,
                topic=topic,
                substep="resolve.analyze_decision_options",
                observation={
                    "topic_id": topic_id,
                    "convergence_reason": convergence.get("reason", ""),
                },
                decision=options_decision,
                result={
                    "options_count": len(decision_analysis.get("options") or []),
                    "recommendation": decision_analysis.get("recommendation", {}),
                },
            )

            resolution = self.mediator.build_topic_result(
                resolution_status="pending_confirmation",
                summary=decision_analysis.get("summary", ""),
                decision="",
                votes={},
                votes_summary="未由代理人定案；改由使用者確認決策選項。",
                mediator_compromise={"title": "", "description": "", "rationale": ""},
                agreed_points=[],
                unresolved_points=decision_analysis.get("unresolved_points", []),
                new_open_questions=[],
                affected_requirement_ids=decision_analysis.get("affected_requirement_ids", []),
                needs_approval=False,
                needs_human=False,
                options=decision_analysis.get("options", []),
                recommendation=decision_analysis.get("recommendation", {}),
                needs_user_confirmation=True,
                confirmation_status="pending",
            )
            resolution["suggested_next_actions"] = suggested_next_actions
            self.record_action_substep_trace(
                stage=stage,
                topic=topic,
                substep="resolve.build_recommendation",
                observation={
                    "topic_id": topic_id,
                    "needs_user_confirmation": True,
                },
                decision={
                    "action": "build_recommendation",
                    "params": {"topic_id": topic_id},
                    "reasoning": "將選項分析保存為 recommendation，等待使用者確認後才套用為正式需求。",
                },
                result={
                    "resolution_status": resolution.get("resolution_status", ""),
                    "summary": resolution.get("summary", ""),
                    "confirmation_status": resolution.get("confirmation_status", ""),
                },
            )

        source_ids = list(topic.get("source_ids", []) or [])
        derived_req_ids = [
            sid for sid in source_ids
            if isinstance(sid, str)
            and sid.startswith(("REQ-", "R-", "FR-", "NFR-"))
        ]
        normalize_decision = {
            "action": "finalize_resolution_contract",
            "params": {"topic_id": topic_id},
            "reasoning": "補齊決議的結構化欄位，讓後續 save/apply 流程只處理完整 contract。",
        }
        cur_req_ids = resolution.get("affected_requirement_ids") or []
        if not cur_req_ids:
            resolution["affected_requirement_ids"] = derived_req_ids
        if not isinstance(resolution.get("verification_impact"), dict):
            resolution["verification_impact"] = {
                "level": "none",
                "notes": "",
            }
        has_changes = bool(resolution.get("requirement_change_candidates"))
        has_affected = bool(resolution.get("affected_requirement_ids"))
        if resolution.get("needs_user_confirmation"):
            resolution["needs_approval"] = False
        else:
            resolution["needs_approval"] = has_affected or has_changes
        resolution["suggested_next_actions"] = suggested_next_actions
        for _rc in (resolution.get("requirement_change_candidates") or []):
            if isinstance(_rc, dict):
                _rc.setdefault("source_topic_id", topic.get("id"))
        self.record_action_substep_trace(
            stage=stage,
            topic=topic,
            substep="resolve.finalize_resolution_contract",
            observation={
                "topic_id": topic_id,
                "source_ids_count": len(source_ids),
            },
            decision=normalize_decision,
            result={
                "affected_requirement_ids": resolution.get("affected_requirement_ids", []),
                "needs_approval": resolution.get("needs_approval", False),
                "change_candidates_count": len(
                    resolution.get("requirement_change_candidates") or []
                ),
            },
        )
        return resolution

    def escalate_topic_via_substeps(
        self,
        *,
        topic: Dict[str, Any],
        contributions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        stage = "agenda_runner.escalate_to_human"
        topic_id = topic.get("id")

        options_decision = {
            "action": "prepare_human_options",
            "params": {"topic_id": topic_id},
            "reasoning": "先整理可供人類裁決的選項，再進入裁決收集。",
        }
        options = None
        if topic.get("category") in ("conflict_discussion",) and self.registry:
            analyst = self.registry.get("analyst")
            if analyst and hasattr(analyst, "get_resolution_options_for_topic"):
                options = analyst.get_resolution_options_for_topic(topic, self.artifact)
        if not options:
            options = self.mediator.prepare_human_options(topic, contributions)
        self.record_action_substep_trace(
            stage=stage,
            topic=topic,
            substep="escalate.prepare_human_options",
            observation={
                "topic_id": topic_id,
                "contributions_count": len(contributions),
            },
            decision=options_decision,
            result={
                "options_count": len(options) if isinstance(options, list) else 0,
            },
        )

        human_decision = {
            "action": "collect_human_decision",
            "params": {"topic_id": topic_id},
            "reasoning": "將整理後的選項交由人類決策。",
        }
        resolution = self.collect.human_decision_on_topic(topic, options)
        decision_text = str(resolution.get("decision", ""))
        self.record_action_substep_trace(
            stage=stage,
            topic=topic,
            substep="escalate.collect_human_decision",
            observation={
                "topic_id": topic_id,
                "options_count": len(options) if isinstance(options, list) else 0,
            },
            decision=human_decision,
            result={
                "decision": decision_text,
            },
        )

        wrap_decision = {
            "action": "wrap_human_resolution",
            "params": {"topic_id": topic_id},
            "reasoning": "將人類裁決轉成標準化 topic result contract。",
        }
        wrapped = self.mediator.build_topic_result(
            resolution_status="human_decision",
            summary=decision_text or "本議題已升級由人類裁決。",
            decision=decision_text,
            votes={},
            votes_summary="human_decision",
            mediator_compromise={},
            agreed_points=[decision_text] if decision_text else [],
            unresolved_points=[],
            new_open_questions=[],
            affected_conflict_ids=[],
            requirement_change_candidates=[],
            needs_human=True,
        )
        wrapped["human_decision_raw"] = resolution
        self.record_action_substep_trace(
            stage=stage,
            topic=topic,
            substep="escalate.wrap_human_resolution",
            observation={
                "topic_id": topic_id,
                "decision": decision_text,
            },
            decision=wrap_decision,
            result={
                "resolution_status": wrapped.get("resolution_status", ""),
                "summary": wrapped.get("summary", ""),
            },
        )
        return wrapped

    def save_topic_via_substeps(
        self,
        *,
        topic: Dict[str, Any],
        contributions: List[Dict[str, Any]],
        resolution: Dict[str, Any],
    ) -> Dict[str, Any]:
        stage = "agenda_runner.save_topic"
        topic_id = topic.get("id")

        proposer_decision = {
            "action": "name_topic",
            "params": {"topic_id": topic_id},
            "reasoning": "依討論結果重新命名議題，確保存檔名稱貼近正式決議。",
        }
        proposer = self.find_topic_proposer(topic)
        topic["proposed_by"] = proposer
        final_title = self.mediator.name_topic_after_discussion(
            topic,
            contributions,
            resolution,
            proposer_agent=proposer,
        )
        if final_title:
            topic["title"] = final_title
        self.record_action_substep_trace(
            stage=stage,
            topic=topic,
            substep="save.name_topic",
            observation={
                "topic_id": topic_id,
                "proposed_by": proposer,
            },
            decision=proposer_decision,
            result={
                "final_title": topic.get("title", ""),
            },
        )

        markdown_decision = {
            "action": "generate_meeting_markdown",
            "params": {"topic_id": topic_id},
            "reasoning": "將議題討論與決議生成正式會議紀錄文件。",
        }
        self.topic_idx += 1
        meeting_md = self.mediator.generate_meeting_markdown(
            topic,
            contributions,
            resolution,
            round_num=self.round_num,
            proposed_by=proposer,
        )
        meeting_filename = f"R{self.round_num}-M{self.topic_idx:02d}.md"
        self.store.save_markdown(meeting_md, meeting_filename)
        self.record_action_substep_trace(
            stage=stage,
            topic=topic,
            substep="save.generate_meeting_markdown",
            observation={
                "topic_id": topic_id,
                "contributions_count": len(contributions),
            },
            decision=markdown_decision,
            result={
                "filename": meeting_filename,
                "markdown_length": len(meeting_md),
            },
        )

        persist_decision = {
            "action": "persist_discussion_record",
            "params": {"topic_id": topic_id, "filename": meeting_filename},
            "reasoning": "把本次議題結果寫入 round discussions 與 OPA trace。",
        }
        topic_record = {
            "schema_version": topic.get("schema_version", "decision_topic.v1"),
            "id": topic.get("id"),
            "title": topic.get("title"),
            "description": topic.get("description", ""),
            "category": topic.get("category", ""),
            "participants": topic.get("participants", []),
            "discussion_mode": topic.get("discussion_mode", "sequential"),
            "speaking_order": topic.get("speaking_order", []),
            "source_ids": topic.get("source_ids", []),
            "source_issue_ids": topic.get("source_issue_ids", []),
            "proposed_by": topic.get("proposed_by"),
            "status": "saved",
            "triage_action": topic.get("triage_action", "formal_meeting"),
        }
        self.round_discussions.append(
            {
                "topic": topic_record,
                "source_ids": topic.get("source_ids", []),
                "contributions": [
                    {"agent": c.get("agent"), "response": c.get("response", {})}
                    for c in contributions
                ],
                "resolution": resolution,
            }
        )
        trace_rows = self.artifact.setdefault("meeting_opa_trace", [])
        contribution_trace_count = 0
        for c in contributions or []:
            if not isinstance(c, dict):
                continue
            response = c.get("response") or {}
            if not isinstance(response, dict):
                continue
            for row in (response.get("opa_trace") or []):
                if not isinstance(row, dict):
                    continue
                contribution_trace_count += 1
                trace_rows.append(
                    {
                        "stage": "decision_topic",
                        "topic_id": topic_record.get("id"),
                        "topic_title": topic_record.get("title"),
                        "topic_category": topic_record.get("category"),
                        "agent": c.get("agent"),
                        "trace": row,
                    }
                )
        self.record_action_substep_trace(
            stage=stage,
            topic=topic,
            substep="save.persist_discussion_record",
            observation={
                "topic_id": topic_id,
                "round_discussions_before": len(self.round_discussions) - 1,
            },
            decision=persist_decision,
            result={
                "round_discussions_after": len(self.round_discussions),
                "contribution_trace_count": contribution_trace_count,
            },
        )

        rationale_decision = {
            "action": "update_design_rationale",
            "params": {"topic_id": topic_id},
            "reasoning": "同步將本議題決議沉澱到 design rationale。",
        }
        self.update_design_rationale_for_topic(topic, contributions, resolution)
        self.record_action_substep_trace(
            stage=stage,
            topic=topic,
            substep="save.update_design_rationale",
            observation={
                "topic_id": topic_id,
                "filename": meeting_filename,
            },
            decision=rationale_decision,
            result={
                "updated": True,
            },
        )
        self.topic_status[topic_id]["saved"] = True
        return {
            "topic_id": topic_id,
            "filename": meeting_filename,
        }

    def plan_action(
        self,
        action: str,
        params: Optional[Dict[str, Any]] = None,
        observation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        params = params or {}
        observation = observation or {}
        state_summary = observation.get("state_summary") or {}
        if not action:
            planned = self.mediator.plan_agenda_action_via_opa(state_summary, None)
            return {
                "action": planned.get("action", "finish_round"),
                "params": planned.get("params") or {},
                "reasoning": planned.get("reasoning", ""),
                "planner_trace": planned.get("opa_trace", []),
                "observation": observation,
            }
        return {
            "action": action,
            "params": params,
            "reasoning": "依 agenda loop 決策執行指定 action。",
            "observation": observation,
        }

    def execute_action(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        action = self.normalize_action_name(decision.get("action", ""))
        params = decision.get("params") or {}
        return self.run_action_impl(action, params)

    def run(self, action: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        action = self.normalize_action_name(action)
        observation = self.observe_action(action, params)
        decision = self.plan_action(action, params, observation)
        result = self.execute_action(decision)
        result["opa_trace"] = self.record_runner_opa_trace(
            stage=f"agenda_runner.{decision.get('action', action)}",
            action=decision.get("action", action),
            params=decision.get("params") or {},
            observation=observation,
            decision=decision,
            result=result,
            topic_id=(decision.get("params") or {}).get("topic_id"),
        )
        return result

    @staticmethod
    def normalize_action_name(action: str) -> str:
        return str(action or "").strip()

    def run_action_impl(self, action: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        action = self.normalize_action_name(action)
        params = params or {}
        obs = {"action": action, "result": None, "error": None}

        if action == "generate_decision_topics":
            skip = set()
            for disc in self.artifact.get("discussions", []):
                for td in disc.get("topics", []):
                    for sid in td.get("source_ids", []):
                        skip.add(sid)
            max_items = self.config.get("agenda_items", 5)
            latest_version = self.store.get_draft_version()
            draft_md = self.store.load_draft(latest_version) if latest_version >= 0 else None
            self.topics = self.mediator.generate_decision_topics(
                self.artifact,
                registry=self.registry,
                max_items=max_items,
                skip_source_ids=skip if skip else None,
                draft_markdown=draft_md,
                issue_pool=self.issue_pool,
            )
            self.issue_pool = list(self.artifact.get("issue_backlog", []) or [])
            self.topic_status = {
                t["id"]: {
                    "discussed": False,
                    "contributions": None,
                    "resolution": None,
                    "saved": False,
                }
                for t in self.topics
            }
            obs["result"] = {
                "topics": [
                    {
                        "id": t["id"],
                        "title": t["title"],
                        "category": t.get("category", ""),
                    }
                    for t in self.topics
                ],
                "count": len(self.topics),
            }
            return obs

        if action == "expand_decision_topics":
            agenda_limit = self.config.get("agenda_items", 5)
            if len(self.topics) >= agenda_limit:
                obs["error"] = "已達decision topic 上限，無法擴充"
                return obs
            all_saved = all(
                self.topic_status.get(t["id"], {}).get("saved", False)
                for t in self.topics
            )
            if not all_saved:
                obs["error"] = "須先將本輪目前所有議題 save_topic 後才能擴充 decision topic"
                return obs
            skip = set()
            for disc in self.artifact.get("discussions", []):
                for td in disc.get("topics", []):
                    for sid in td.get("source_ids", []):
                        skip.add(sid)
            for rd in self.round_discussions:
                for sid in rd.get("source_ids", []):
                    skip.add(sid)
            max_items = agenda_limit - len(self.topics)
            latest_version = self.store.get_draft_version()
            draft_md = self.store.load_draft(latest_version) if latest_version >= 0 else None
            new_items = self.mediator.generate_decision_topics(
                self.artifact,
                registry=self.registry,
                max_items=max_items,
                skip_source_ids=skip if skip else None,
                draft_markdown=draft_md,
                issue_pool=self.issue_pool,
            )
            self.issue_pool = list(self.artifact.get("issue_backlog", []) or [])
            if not new_items:
                obs["result"] = {"expanded": 0, "message": "無新增議題"}
                return obs
            start_idx = len(self.topics) + 1
            for i, item in enumerate(new_items):
                tid = f"T-{start_idx + i:02d}"
                new_topic = {
                    "id": tid,
                    "title": item.get("title", "待討論議題").strip(),
                    "description": item.get("description", ""),
                    "category": item.get("category", ""),
                    "participants": item.get("participants", []),
                    "discussion_mode": item.get("discussion_mode", "sequential"),
                    "speaking_order": item.get("speaking_order", []),
                    "source_ids": item.get("source_ids", []),
                }
                self.topics.append(new_topic)
                self.topic_status[tid] = {
                    "discussed": False,
                    "contributions": None,
                    "resolution": None,
                    "saved": False,
                }
            obs["result"] = {
                "expanded": len(new_items),
                "new_topics": [
                    {"id": t["id"], "title": t["title"], "category": t.get("category", "")}
                    for t in self.topics[-len(new_items):]
                ],
            }
            return obs

        if action == "start_discussion":
            topic_id = params.get("topic_id")
            topic = self.get_topic(topic_id)
            if not topic:
                obs["error"] = f"topic_id 不存在: {topic_id}"
                return obs
            st_disc = self.topic_status.get(topic_id, {})
            if st_disc.get("discussed"):
                obs["error"] = (
                    f"{topic_id} 已討論過，不可重複討論。"
                    f"請使用 save_topic 儲存後繼續下一個議題。"
                )
                return obs
            mode = topic.get("discussion_mode", "sequential")
            if mode == "simultaneous":
                contributions = self.mediator.moderate_simultaneous(
                    topic, self.registry, artifact=self.artifact
                )
                stakeholders = self.artifact.get("stakeholders", [])
                oq_records = self.mediator.handle_open_questions(
                    contributions, self.registry, stakeholders, artifact=self.artifact
                )
            else:
                contributions, oq_records = self.mediator.moderate_sequential(
                    topic, self.registry, artifact=self.artifact
                )
            for oq in oq_records:
                oq["topic_id"] = topic_id
            self.all_open_questions.extend(oq_records)
            self.topic_status[topic_id]["discussed"] = True
            self.topic_status[topic_id]["contributions"] = contributions
            result_info = {
                "topic_id": topic_id,
                "contributions_count": len(contributions),
                "oq_count": len(oq_records),
            }
            if not contributions:
                result_info["warning"] = (
                    "本議題無參與者可發言，請直接執行 save_topic 儲存後繼續。"
                )
            obs["result"] = result_info
            return obs

        if action == "resolve_topic":
            topic_id = params.get("topic_id")
            topic = self.get_topic(topic_id)
            st = self.topic_status.get(topic_id, {})
            if not topic or not st.get("discussed"):
                obs["error"] = f"請先對 {topic_id} 執行 start_discussion"
                return obs
            contributions = st.get("contributions") or []
            resolution = self.resolve_topic_via_substeps(
                topic=topic,
                contributions=contributions,
            )
            convergence_reason = resolution.get("summary", "")
            self.topic_status[topic_id]["resolution"] = resolution
            rv = resolution.get("votes", {})
            status = resolution.get("resolution_status")
            if status == "agreed":
                status_label = "收斂"
            elif status == "pending_confirmation":
                status_label = "待使用者確認"
            else:
                status_label = "未收斂"
            votes_suffix = ""
            if rv:
                votes_str = ", ".join(f"{a}: {v}" for a, v in rv.items())
                votes_suffix = f"；legacy votes: {votes_str}"
            self.logger.info(
                "  決議: [%s] %s｜%s｜結果: %s%s",
                topic_id,
                topic.get("title", ""),
                f"{status_label}（{convergence_reason}）",
                resolution.get("resolution", ""),
                votes_suffix,
            )
            needs_human = bool(resolution.get("needs_human"))
            obs["result"] = {
                "topic_id": topic_id,
                "resolution": resolution.get("resolution"),
                "resolution_status": resolution.get("resolution_status", resolution.get("resolution")),
                "summary": resolution.get("summary", ""),
                "decision_summary": resolution.get("decision_summary", resolution.get("summary", "")),
                "agreed_points_count": len(resolution.get("agreed_points", []) or []),
                "unresolved_points_count": len(resolution.get("unresolved_points", []) or []),
                "needs_human": needs_human,
            }
            obs["status"] = "needs_human" if needs_human else "resolved"
            obs["topic_id"] = topic_id
            obs["summary"] = resolution.get("summary", "") or resolution.get("resolution", "")
            if needs_human:
                self.topic_status[topic_id]["resolution"] = None
            return obs

        if action == "escalate_to_human":
            if not self.mediator.enable_human_escalation:
                self.logger.info("  人類裁決已關閉，自動改為 resolve_topic")
                return self.run("resolve_topic", params)
            topic_id = params.get("topic_id")
            topic = self.get_topic(topic_id)
            st_esc = self.topic_status.get(topic_id, {})
            if not topic or not st_esc.get("discussed"):
                obs["error"] = f"請先對 {topic_id} 執行 start_discussion"
                return obs
            contributions = st_esc.get("contributions") or []
            self.logger.info(f"  人類裁決: [{topic_id}] {topic.get('title', '')}")
            options = None
            wrapped = self.escalate_topic_via_substeps(
                topic=topic,
                contributions=contributions,
            )
            decision_text = str((wrapped.get("human_decision_raw") or {}).get("decision", ""))
            self.topic_status[topic_id]["resolution"] = wrapped
            obs["result"] = {
                "topic_id": topic_id,
                "resolution": "human_decision",
                "summary": decision_text,
            }
            obs["status"] = "human_decided"
            obs["topic_id"] = topic_id
            obs["summary"] = decision_text or "本議題已升級由人類裁決。"
            return obs

        if action == "save_topic":
            topic_id = params.get("topic_id")
            topic = self.get_topic(topic_id)
            st = self.topic_status.get(topic_id, {})
            if not topic or not st.get("discussed"):
                obs["error"] = f"請先對 {topic_id} 執行 start_discussion"
                return obs
            contributions = st.get("contributions") or []
            resolution = st.get("resolution")
            self.logger.info(f"  存檔: [{topic_id}] {topic.get('title', '')}")
            if not resolution:
                obs["error"] = f"請先對 {topic_id} 執行 resolve_topic 或 escalate_to_human，之後才能 save_topic"
                return obs
            save_result = self.save_topic_via_substeps(
                topic=topic,
                contributions=contributions,
                resolution=resolution,
            )
            obs["result"] = save_result
            obs["status"] = "saved"
            obs["topic_id"] = topic_id
            obs["summary"] = f"已儲存 {topic_id} 至 {save_result.get('filename')}"
            return obs

        if action == "finish_round":
            if self.topics:
                unsaved_ids = [
                    t.get("id", "")
                    for t in self.topics
                    if not self.topic_status.get(t.get("id", ""), {}).get("saved", False)
                ]
                if unsaved_ids:
                    obs["error"] = (
                        "尚有未存檔議題，請先完成 save_topic 後再 finish_round: "
                        + ", ".join(i for i in unsaved_ids if i)
                    )
                    return obs
            obs["result"] = "round_complete"
            return obs

        obs["error"] = f"未知動作: {action}，可用: {AGENDA_ACTIONS}"
        return obs

    def get_topic(self, topic_id: Optional[str]) -> Optional[Dict]:
        if not topic_id:
            return None
        for t in self.topics:
            if t.get("id") == topic_id:
                return t
        return None

    def find_topic_proposer(self, topic: Dict) -> Optional[str]:
        """從 topic 的 source_issue_ids 反查提案者。"""
        issue_ids = set(topic.get("source_issue_ids") or [])
        if not issue_ids:
            return None
        for p in self.artifact.get("issue_proposals", []) or []:
            if not isinstance(p, dict):
                continue
            if p.get("issue_id") in issue_ids:
                proposer = (p.get("proposed_by") or "").strip()
                if proposer:
                    return proposer
        return None

    def get_state_summary(self) -> Dict[str, Any]:
        status_list = []
        for tid, st in self.topic_status.items():
            status_list.append(
                {
                    "topic_id": tid,
                    "discussed": st.get("discussed", False),
                    "resolved": st.get("resolution") is not None,
                    "resolution": (st.get("resolution") or {}).get("resolution"),
                    "saved": st.get("saved", False),
                }
            )
        agenda_limit = self.config.get("agenda_items", 5)
        topics_count = len(self.topics)
        issue_pool_count = len(self.issue_pool)
        all_saved = (
            topics_count > 0
            and all(self.topic_status.get(t["id"], {}).get("saved", False) for t in self.topics)
        )
        can_expand_decision_topics = topics_count < agenda_limit and all_saved and issue_pool_count > 0
        clarification_queue = [
            row for row in (self.artifact.get("clarification_queue", []) or [])
            if isinstance(row, dict)
        ]
        human_decision_queue = [
            row for row in (self.artifact.get("human_decision_queue", []) or [])
            if isinstance(row, dict)
        ]
        direct_apply_queue = [
            row for row in (self.artifact.get("direct_apply_queue", []) or [])
            if isinstance(row, dict)
        ]
        return {
            "round_num": self.round_num,
            "agenda_limit": agenda_limit,
            "topics_count": topics_count,
            "issue_pool_count": issue_pool_count,
            "all_current_topics_saved": all_saved,
            "can_expand_decision_topics": can_expand_decision_topics,
            "queue_status": {
                "clarification_queue_count": len(clarification_queue),
                "human_decision_queue_count": len(human_decision_queue),
                "direct_apply_queue_count": len(direct_apply_queue),
                "has_pending_queue_items": bool(
                    clarification_queue or human_decision_queue or direct_apply_queue
                ),
            },
            "topics": [
                {
                    "schema_version": t.get("schema_version", "decision_topic.v1"),
                    "id": t["id"],
                    "title": t["title"],
                    "category": t.get("category", ""),
                    "category_label": AGENDA_CATEGORY_LABEL.get(
                        t.get("category", ""), t.get("category", "")
                    ),
                    "source_issue_ids": t.get("source_issue_ids", []),
                    "triage_action": t.get("triage_action", "formal_meeting"),
                }
                for t in self.topics
            ],
            "topic_status": status_list,
            "round_discussions_length": len(self.round_discussions),
        }

    def get_round_discussions(self) -> List[Dict]:
        return self.round_discussions

    def get_all_open_questions(self) -> List[Dict]:
        return self.all_open_questions

    def get_agenda_snapshot(self) -> List[Dict]:
        return list(self.topics)
