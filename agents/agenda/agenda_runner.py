from typing import Dict, List, Any, Optional

from agents.profile.mediator import (
    MediatorAgent,
    AGENDA_CATEGORY_LABEL,
    AGENDA_ACTIONS,
)


def self_review_round_cap_from_config(config: Dict[str, Any]) -> int:
    mi = config.get("max_iterations")
    if isinstance(mi, dict):
        return max(1, int(mi.get("self_review_round_cap", 5)))
    try:
        return max(1, int(mi))
    except (TypeError, ValueError):
        return 5


class AgendaRunner:
    """執行議程相關動作，維護本輪 topics、topic_status、round_discussions、all_open_questions。"""

    def __init__(
        self,
        mediator_agent: MediatorAgent,
        registry,
        artifact: Dict[str, Any],
        proposal_pool: Optional[List[Dict[str, Any]]],
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
        self.proposal_pool = list(proposal_pool or [])

        self.topics: List[Dict] = []
        self.topic_status: Dict[str, Dict] = {}
        self.round_discussions: List[Dict] = []
        self.all_open_questions: List[Dict] = []
        self.topic_idx = 0
        self.pending_review_issues: List[Dict] = []

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

    def run(self, action: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        params = params or {}
        obs = {"action": action, "result": None, "error": None}

        if action == "generate_agenda":
            skip = set()
            for disc in self.artifact.get("discussions", []):
                for td in disc.get("topics", []):
                    for sid in td.get("source_ids", []):
                        skip.add(sid)
            max_items = self.config.get("agenda_items", 5)
            latest_version = self.store.get_draft_version()
            draft_md = self.store.load_draft(latest_version) if latest_version >= 0 else None
            self.topics = self.mediator.generate_agenda(
                self.artifact,
                registry=self.registry,
                max_items=max_items,
                skip_source_ids=skip if skip else None,
                draft_markdown=draft_md,
                proposal_pool=self.proposal_pool,
            )
            self.proposal_pool = list(self.artifact.get("proposal_backlog", []) or [])
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

        if action == "expand_agenda":
            agenda_limit = self.config.get("agenda_items", 5)
            if len(self.topics) >= agenda_limit:
                obs["error"] = "已達議程上限，無法擴充"
                return obs
            all_saved = all(
                self.topic_status.get(t["id"], {}).get("saved", False)
                for t in self.topics
            )
            if not all_saved:
                obs["error"] = "須先將本輪目前所有議題 save_topic 後才能擴充議程"
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
            new_items = self.mediator.generate_agenda(
                self.artifact,
                registry=self.registry,
                max_items=max_items,
                skip_source_ids=skip if skip else None,
                draft_markdown=draft_md,
                proposal_pool=self.proposal_pool,
            )
            self.proposal_pool = list(self.artifact.get("proposal_backlog", []) or [])
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
            self.logger.info(f"  決議: [{topic_id}] {topic.get('title', '')}")

            convergence = self.mediator.assess_discussion_convergence(topic, contributions)
            if convergence.get("converged"):
                self.logger.info(f"    收斂：{convergence.get('reason', '')}")
                resolution = self.mediator.build_converged_resolution(
                    topic, contributions, convergence,
                )
            else:
                self.logger.info(f"    未收斂：{convergence.get('reason', '')}，提出折衷方案")
                mc = self.mediator.propose_compromise_for_vote(topic, contributions)
                votes = self.mediator.collect_compromise_votes(
                    topic, contributions, mc, self.registry, artifact=self.artifact,
                )
                proposer = self._find_topic_proposer(topic)
                resolution = self.mediator.synthesize_and_resolve(
                    topic, contributions,
                    final_votes=votes,
                    mediator_compromise=mc,
                    proposer_agent=proposer,
                )

            self.topic_status[topic_id]["resolution"] = resolution
            rv = resolution.get("votes", {})
            if rv:
                votes_str = ", ".join(f"{a}: {v}" for a, v in rv.items())
                self.logger.info(f"    投票: {votes_str} → {resolution.get('resolution', '')}")
            else:
                self.logger.info(f"    結果: {resolution.get('resolution', '')}")
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
            if topic.get("category") in ("conflict_resolution",) and self.registry:
                analyst = self.registry.get("analyst")
                if analyst and hasattr(analyst, "get_resolution_options_for_topic"):
                    options = analyst.get_resolution_options_for_topic(topic, self.artifact)
            if not options:
                options = self.mediator.prepare_human_options(topic, contributions)
            resolution = self.collect.human_decision_on_topic(topic, options)
            decision_text = str(resolution.get("decision", ""))
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
            self.topic_status[topic_id]["resolution"] = wrapped
            obs["result"] = {
                "topic_id": topic_id,
                "resolution": "human_decision",
                "summary": decision_text,
            }
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
            self.topic_idx += 1
            meeting_md = self.mediator.generate_meeting_markdown(
                topic, contributions, resolution, round_num=self.round_num
            )
            meeting_filename = f"R{self.round_num}-M{self.topic_idx:02d}.md"
            self.store.save_markdown(meeting_md, meeting_filename)
            topic_record = {
                "schema_version": topic.get("schema_version", "agenda_topic.v1"),
                "id": topic.get("id"),
                "title": topic.get("title"),
                "description": topic.get("description", ""),
                "category": topic.get("category", ""),
                "participants": topic.get("participants", []),
                "discussion_mode": topic.get("discussion_mode", "sequential"),
                "speaking_order": topic.get("speaking_order", []),
                "source_ids": topic.get("source_ids", []),
                "source_proposal_ids": topic.get("source_proposal_ids", []),
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
            self.update_design_rationale_for_topic(topic, contributions, resolution)
            self.topic_status[topic_id]["saved"] = True
            obs["result"] = {"topic_id": topic_id, "filename": meeting_filename}
            return obs

        if action == "expert_review":
            expert = self.registry.get("expert") if self.registry else None
            if not expert or not hasattr(expert, "run_review_loop"):
                obs["error"] = "Expert agent 不可用"
                return obs
            ri = self.config.get("max_iterations") or {}
            cap = self_review_round_cap_from_config(self.config)
            n = params.get("max_iterations")
            if n is not None and isinstance(n, int) and 1 <= n <= cap:
                max_iter = n
            else:
                max_iter = min(int(ri.get("expert_review", cap)), cap)
            self.logger.info("  Expert review（%s 輪）", max_iter)
            result = expert.run_review_loop(
                self.artifact, self.round_discussions,
                max_iterations=max_iter,
            )
            for issue in result.get("pending_issues", []):
                self.pending_review_issues.append(issue)
            self.store.save_artifact(self.artifact)
            obs["result"] = {
                "actions_count": len(result.get("actions_taken", [])),
                "pending_issues_count": len(
                    result.get("pending_issues", [])
                ),
                "summary": "; ".join(
                    a.get("result_summary", "")
                    for a in result.get("actions_taken", [])
                ),
            }
            return obs

        if action == "analyst_review":
            analyst = self.registry.get("analyst") if self.registry else None
            if not analyst or not hasattr(analyst, "run_review_loop"):
                obs["error"] = "Analyst agent 不可用"
                return obs
            ri = self.config.get("max_iterations") or {}
            cap = self_review_round_cap_from_config(self.config)
            n = params.get("max_iterations")
            if n is not None and isinstance(n, int) and 1 <= n <= cap:
                max_iter = n
            else:
                max_iter = min(int(ri.get("analyst_review", cap)), cap)
            self.logger.info("  Analyst review（%s 輪）", max_iter)
            result = analyst.run_review_loop(
                self.artifact, self.round_discussions,
                max_iterations=max_iter,
            )
            for issue in result.get("pending_issues", []):
                self.pending_review_issues.append(issue)
            self.store.save_artifact(self.artifact)
            obs["result"] = {
                "actions_count": len(result.get("actions_taken", [])),
                "pending_issues_count": len(
                    result.get("pending_issues", [])
                ),
                "summary": "; ".join(
                    a.get("result_summary", "")
                    for a in result.get("actions_taken", [])
                ),
            }
            return obs

        if action == "modeler_review":
            modeler = self.registry.get("modeler") if self.registry else None
            if not modeler or not hasattr(modeler, "run_review_loop"):
                obs["error"] = "Modeler agent 不可用"
                return obs
            ri = self.config.get("max_iterations") or {}
            cap = self_review_round_cap_from_config(self.config)
            n = params.get("max_iterations")
            if n is not None and isinstance(n, int) and 1 <= n <= cap:
                max_iter = n
            else:
                max_iter = min(int(ri.get("modeler_review", cap)), cap)
            self.logger.info("  Modeler review（%s 輪）", max_iter)
            result = modeler.run_review_loop(
                self.artifact, self.round_discussions,
                max_iterations=max_iter,
            )
            for issue in result.get("pending_issues", []):
                self.pending_review_issues.append(issue)
            self.store.save_artifact(self.artifact)
            obs["result"] = {
                "actions_count": len(result.get("actions_taken", [])),
                "pending_issues_count": len(
                    result.get("pending_issues", [])
                ),
                "summary": "; ".join(
                    a.get("result_summary", "")
                    for a in result.get("actions_taken", [])
                ),
            }
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

    def _find_topic_proposer(self, topic: Dict) -> Optional[str]:
        """從 topic 的 source_proposal_ids 反查提案者。"""
        proposal_ids = set(topic.get("source_proposal_ids") or [])
        if not proposal_ids:
            return None
        for p in self.artifact.get("topic_proposals", []) or []:
            if not isinstance(p, dict):
                continue
            if p.get("proposal_id") in proposal_ids:
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
        all_saved = (
            topics_count > 0
            and all(self.topic_status.get(t["id"], {}).get("saved", False) for t in self.topics)
        )
        can_expand_agenda = topics_count < agenda_limit and all_saved
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
            "all_current_topics_saved": all_saved,
            "can_expand_agenda": can_expand_agenda,
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
                    "schema_version": t.get("schema_version", "agenda_topic.v1"),
                    "id": t["id"],
                    "title": t["title"],
                    "category": t.get("category", ""),
                    "category_label": AGENDA_CATEGORY_LABEL.get(
                        t.get("category", ""), t.get("category", "")
                    ),
                    "source_proposal_ids": t.get("source_proposal_ids", []),
                    "triage_action": t.get("triage_action", "formal_meeting"),
                }
                for t in self.topics
            ],
            "topic_status": status_list,
            "round_discussions_length": len(self.round_discussions),
            "pending_review_issues": self.pending_review_issues,
        }

    def get_round_discussions(self) -> List[Dict]:
        return self.round_discussions

    def get_all_open_questions(self) -> List[Dict]:
        return self.all_open_questions

    def get_agenda_snapshot(self) -> List[Dict]:
        return list(self.topics)
