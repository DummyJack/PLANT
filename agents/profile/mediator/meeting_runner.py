# Meeting runner: executes decision issue actions and coordinates round loops.
from typing import Dict, List, Any, Optional

from .agent import MediatorAgent
from .validation import MEETING_ACTIONS, ISSUE_CATEGORY_LABEL


def run_round_opa_loop(coordinator: Any, runner: Any) -> None:
    last_action_result: Optional[Dict[str, Any]] = None
    while True:
        observation = coordinator.observe_round_state(
            runner=runner,
            last_action_result=last_action_result,
        )
        decision = coordinator.plan_round_step(observation=observation)
        action = decision.get("action", "finish_round")
        coordinator.flow.logger.info("  決策: %s — %s", action, decision.get("reasoning", ""))
        if action == "finish_round":
            break
        result = coordinator.act_round_step(
            runner=runner,
            decision=decision,
            observation=observation,
        )
        if result.get("error"):
            raise RuntimeError(f"會議步驟執行失敗: {result['error']}")
        elif action == "save_issue":
            latest = runner.get_round_discussions()
            if latest:
                from flow.meeting.subflows import post_issue_processing

                post_issue_processing(
                    coordinator,
                    runner.artifact,
                    latest[-1],
                    round_num=runner.round_num,
                )
        last_action_result = result


def run_meeting_loop(coordinator: Any, runner: Any) -> None:
    obs = runner.run("generate_decision_issues", None)
    if obs.get("error"):
        raise RuntimeError(f"issue 生成失敗: {obs['error']}")
    drain = coordinator.is_last_meeting_round(runner.artifact, runner.round_num)

    from flow.meeting.subflows import run_routed_queues

    run_routed_queues(
        coordinator,
        runner.artifact,
        runner,
        round_num=runner.round_num,
        drain_non_formal=drain,
    )
    run_round_opa_loop(coordinator, runner)


class MeetingRunner:
    """執行 decision issue 相關動作，維護本輪 issues、issue_status、round_discussions、all_open_questions。"""

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

        self.issues: List[Dict] = []
        self.issue_status: Dict[str, Dict] = {}
        self.round_discussions: List[Dict] = []
        self.all_open_questions: List[Dict] = []
        self.issue_idx = 0

    def issue_open_questions(self, issue_id: str) -> List[Dict]:
        return [q for q in self.all_open_questions if q.get("issue_id") == issue_id]

    def update_design_rationale_for_issue(
        self,
        issue: Dict[str, Any],
        contributions: List[Dict],
        resolution: Dict[str, Any],
    ) -> None:
        """每個議題存檔後即時更新 design_rationale.md。"""
        try:
            issue_id = issue.get("id", "")
            issue_oq = self.issue_open_questions(issue_id)
            issue_context = self.mediator.build_design_rationale_entry_context(
                issue=issue,
                contributions=contributions,
                resolution=resolution,
                issue_open_questions=issue_oq,
                round_num=self.round_num,
            )

            dr_path = self.store.output_dir / "design_rationale.md"
            if dr_path.exists():
                existing_md = dr_path.read_text(encoding="utf-8")
                dr_md = self.mediator.update_design_rationale(existing_md, issue_context)
            else:
                dr_md = self.mediator.generate_design_rationale(issue_context)
            self.store.save_markdown(dr_md, "design_rationale.md")
            self.logger.info(f"  ✓ 已更新 design_rationale.md（{issue_id}）")
        except Exception as e:
            raise RuntimeError("更新 design_rationale.md 失敗") from e

    def observe_action(self, action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = params or {}
        action = self.action_name(action)
        state = self.get_state_summary()
        return {
            "action": action,
            "params": params,
            "issues_count": len(self.issues),
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
        issue_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        trace_rows = [
            {
                "agent": "meeting_runner",
                "mode": "meeting_action",
                "iteration": 1,
                "observation": {
                    "action": observation.get("action"),
                    "issues_count": observation.get("issues_count"),
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
                "issue_id": issue_id,
                "issue_title": None,
                "issue_category": None,
                "agent": "meeting_runner",
                "trace": row,
            }
            for row in trace_rows
        )
        return trace_rows

    def record_action_substep_trace(
        self,
        *,
        stage: str,
        issue: Optional[Dict[str, Any]],
        substep: str,
        observation: Dict[str, Any],
        decision: Dict[str, Any],
        result: Dict[str, Any],
    ) -> None:
        self.artifact.setdefault("meeting_opa_trace", []).append(
            {
                "stage": stage,
                "issue_id": (issue or {}).get("id"),
                "issue_title": (issue or {}).get("title"),
                "issue_category": (issue or {}).get("category"),
                "agent": "meeting_runner",
                "trace": {
                    "agent": "meeting_runner",
                    "mode": "action_substep",
                    "iteration": 1,
                    "observation": observation,
                    "decision": decision,
                    "result": result,
                    "substep": substep,
                },
            }
        )

    def resolve_issue_via_substeps(
        self,
        *,
        issue: Dict[str, Any],
        contributions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        stage = "meeting_runner.resolve_issue"
        issue_id = issue.get("id")

        converge_obs = {
            "issue_id": issue_id,
            "contributions_count": len(contributions),
        }
        converge_decision = {
            "action": "assess_convergence",
            "params": {"issue_id": issue_id},
            "reasoning": "先判斷議題是否已收斂；未收斂時改整理決策選項與建議，不進行 agent 投票。",
        }
        convergence = self.mediator.assess_discussion_convergence(issue, contributions)
        self.record_action_substep_trace(
            stage=stage,
            issue=issue,
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
                "params": {"issue_id": issue_id},
                "reasoning": "討論已收斂，直接生成收斂型決議。",
            }
            resolution = self.mediator.build_converged_resolution(
                issue, contributions, convergence,
            )
            resolution["suggested_next_actions"] = suggested_next_actions
            self.record_action_substep_trace(
                stage=stage,
                issue=issue,
                substep="resolve.build_converged_resolution",
                observation={
                    "issue_id": issue_id,
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
                "params": {"issue_id": issue_id},
                "reasoning": "討論未收斂，整理成可供人類裁決的選項、影響與建議。",
            }
            decision_analysis = self.mediator.analyze_decision_options(issue, contributions)
            self.record_action_substep_trace(
                stage=stage,
                issue=issue,
                substep="resolve.analyze_decision_options",
                observation={
                    "issue_id": issue_id,
                    "convergence_reason": convergence.get("reason", ""),
                },
                decision=options_decision,
                result={
                    "options_count": len(decision_analysis.get("options") or []),
                    "recommendation": decision_analysis.get("recommendation", {}),
                },
            )

            resolution = self.mediator.build_issue_result(
                resolution_status="pending_confirmation",
                summary=decision_analysis.get("summary", ""),
                decision="",
                mediator_compromise={"title": "", "description": "", "rationale": ""},
                agreed_points=[],
                unresolved_points=decision_analysis.get("unresolved_points", []),
                new_open_questions=[],
                affected_requirement_ids=decision_analysis.get("affected_requirement_ids", []),
                needs_approval=False,
                needs_human=True,
                options=decision_analysis.get("options", []),
                recommendation=decision_analysis.get("recommendation", {}),
                needs_user_confirmation=False,
                confirmation_status="pending",
            )
            resolution["suggested_next_actions"] = suggested_next_actions
            self.record_action_substep_trace(
                stage=stage,
                issue=issue,
                substep="resolve.build_recommendation",
                observation={
                    "issue_id": issue_id,
                    "needs_human": True,
                },
                decision={
                    "action": "build_recommendation",
                    "params": {"issue_id": issue_id},
                    "reasoning": "將選項分析保存為 recommendation，等待人類裁決後才套用為正式需求。",
                },
                result={
                    "resolution_status": resolution.get("resolution_status", ""),
                    "summary": resolution.get("summary", ""),
                    "confirmation_status": resolution.get("confirmation_status", ""),
                },
            )

        source_ids = list(issue.get("source_ids", []) or [])
        derived_req_ids = [
            sid for sid in source_ids
            if isinstance(sid, str)
            and sid.startswith(("REQ-", "R-", "FR-", "NFR-"))
        ]
        finalize_contract_decision = {
            "action": "finalize_resolution_contract",
            "params": {"issue_id": issue_id},
            "reasoning": "補齊決議的結構化欄位，讓後續 save/apply 流程只處理完整 contract。",
        }
        cur_req_ids = resolution.get("affected_requirement_ids") or []
        if not cur_req_ids:
            resolution["affected_requirement_ids"] = derived_req_ids
        if not isinstance(resolution.get("requirement_impact"), dict):
            resolution["requirement_impact"] = {
                "level": "none",
                "notes": "",
            }
        has_changes = bool(resolution.get("change_record"))
        has_affected = bool(resolution.get("affected_requirement_ids"))
        if resolution.get("needs_human") or resolution.get("needs_user_confirmation"):
            resolution["needs_approval"] = False
        else:
            resolution["needs_approval"] = has_affected or has_changes
        resolution["suggested_next_actions"] = suggested_next_actions
        for rc in (resolution.get("change_record") or []):
            if isinstance(rc, dict):
                rc.setdefault("source_issue_id", issue.get("id"))
        self.record_action_substep_trace(
            stage=stage,
            issue=issue,
            substep="resolve.finalize_resolution_contract",
            observation={
                "issue_id": issue_id,
                "source_ids_count": len(source_ids),
            },
            decision=finalize_contract_decision,
            result={
                "affected_requirement_ids": resolution.get("affected_requirement_ids", []),
                "needs_approval": resolution.get("needs_approval", False),
                "change_candidates_count": len(
                    resolution.get("change_record") or []
                ),
            },
        )
        return resolution

    def escalate_issue_via_substeps(
        self,
        *,
        issue: Dict[str, Any],
        contributions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        stage = "meeting_runner.escalate_to_human"
        issue_id = issue.get("id")

        options_decision = {
            "action": "prepare_human_options",
            "params": {"issue_id": issue_id},
            "reasoning": "先整理可供人類裁決的選項，再進入裁決收集。",
        }
        options = None
        status_resolution = (self.issue_status.get(issue_id, {}) or {}).get("resolution") or {}
        if status_resolution.get("options"):
            best_options = []
            for idx_opt, opt in enumerate(status_resolution.get("options") or [], start=1):
                if not isinstance(opt, dict):
                    continue
                best_options.append(
                    {
                        "id": idx_opt,
                        "title": f"{opt.get('id')}: {opt.get('summary') or opt.get('title') or ''}",
                        "description": opt.get("summary") or opt.get("description") or "",
                        "source": "formal_meeting_options",
                    }
                )
            options = {"best_options": best_options, "compromise": {}}
        if issue.get("category") in ("conflict_discussion",) and self.registry:
            analyst = self.registry.get("analyst")
            if analyst and hasattr(analyst, "get_resolution_options_for_issue"):
                options = options or analyst.get_resolution_options_for_issue(issue, self.artifact)
        if not options:
            options = self.mediator.prepare_human_options(issue, contributions)
        self.record_action_substep_trace(
            stage=stage,
            issue=issue,
            substep="escalate.prepare_human_options",
            observation={
                "issue_id": issue_id,
                "contributions_count": len(contributions),
            },
            decision=options_decision,
            result={
                "options_count": len(options) if isinstance(options, list) else 0,
            },
        )

        human_decision = {
            "action": "collect_human_decision",
            "params": {"issue_id": issue_id},
            "reasoning": "將整理後的選項交由人類決策。",
        }
        resolution = self.collect.human_decision_on_issue(issue, options)
        decision_text = str(resolution.get("decision", ""))
        self.record_action_substep_trace(
            stage=stage,
            issue=issue,
            substep="escalate.collect_human_decision",
            observation={
                "issue_id": issue_id,
                "options_count": len(options) if isinstance(options, list) else 0,
            },
            decision=human_decision,
            result={
                "decision": decision_text,
            },
        )

        wrap_decision = {
            "action": "wrap_human_resolution",
            "params": {"issue_id": issue_id},
            "reasoning": "將人類裁決轉成標準化 issue result contract。",
        }
        wrapped = self.mediator.build_issue_result(
            resolution_status="human_decision",
            summary=decision_text or "本議題已升級由人類裁決。",
            decision=decision_text,
            mediator_compromise={},
            agreed_points=[decision_text] if decision_text else [],
            unresolved_points=[],
            new_open_questions=[],
            affected_conflict_ids=[],
            change_record=[],
            needs_human=True,
        )
        wrapped["human_decision_raw"] = resolution
        self.record_action_substep_trace(
            stage=stage,
            issue=issue,
            substep="escalate.wrap_human_resolution",
            observation={
                "issue_id": issue_id,
                "decision": decision_text,
            },
            decision=wrap_decision,
            result={
                "resolution_status": wrapped.get("resolution_status", ""),
                "summary": wrapped.get("summary", ""),
            },
        )
        return wrapped

    def save_issue_via_substeps(
        self,
        *,
        issue: Dict[str, Any],
        contributions: List[Dict[str, Any]],
        resolution: Dict[str, Any],
    ) -> Dict[str, Any]:
        stage = "meeting_runner.save_issue"
        issue_id = issue.get("id")

        proposer_decision = {
            "action": "name_issue",
            "params": {"issue_id": issue_id},
            "reasoning": "依討論結果重新命名議題，確保存檔名稱貼近正式決議。",
        }
        proposer = self.find_issue_proposer(issue)
        issue["proposed_by"] = proposer
        final_title = self.mediator.name_issue_after_discussion(
            issue,
            contributions,
            resolution,
            proposer_agent=proposer,
        )
        if final_title:
            issue["title"] = final_title
        self.record_action_substep_trace(
            stage=stage,
            issue=issue,
            substep="save.name_issue",
            observation={
                "issue_id": issue_id,
                "proposed_by": proposer,
            },
            decision=proposer_decision,
            result={
                "final_title": issue.get("title", ""),
            },
        )

        markdown_decision = {
            "action": "generate_meeting_markdown",
            "params": {"issue_id": issue_id},
            "reasoning": "將議題討論與決議生成正式會議紀錄文件。",
        }
        self.issue_idx += 1
        meeting_md = self.mediator.generate_meeting_markdown(
            issue,
            contributions,
            resolution,
            round_num=self.round_num,
            proposed_by=proposer,
        )
        meeting_id = f"R{self.round_num}-M{self.issue_idx}"
        meeting_filename = f"{meeting_id}.md"
        self.store.save_markdown(meeting_md, meeting_filename)
        self.record_action_substep_trace(
            stage=stage,
            issue=issue,
            substep="save.generate_meeting_markdown",
            observation={
                "issue_id": issue_id,
                "contributions_count": len(contributions),
            },
            decision=markdown_decision,
            result={
                "meeting_id": meeting_id,
                "filename": meeting_filename,
                "markdown_length": len(meeting_md),
            },
        )

        persist_decision = {
            "action": "persist_discussion_record",
            "params": {"issue_id": issue_id, "filename": meeting_filename},
            "reasoning": "把本次議題結果寫入 round discussions 與 OPA trace。",
        }
        issue_record = {
            "schema_version": issue.get("schema_version", "decision_issue.v1"),
            "id": issue.get("id"),
            "meeting_id": meeting_id,
            "title": issue.get("title"),
            "description": issue.get("description", ""),
            "category": issue.get("category", ""),
            "participants": issue.get("participants", []),
            "discussion_mode": issue.get("discussion_mode", "sequential"),
            "speaking_order": issue.get("speaking_order", []),
            "source_ids": issue.get("source_ids", []),
            "source_issue_ids": issue.get("source_issue_ids", []),
            "proposed_by": issue.get("proposed_by"),
            "status": "saved",
            "triage_action": issue.get("triage_action", "formal_meeting"),
        }
        self.round_discussions.append(
            {
                "meeting_id": meeting_id,
                "issue": issue_record,
                "source_ids": issue.get("source_ids", []),
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
                        "stage": "decision_issue",
                        "issue_id": issue_record.get("id"),
                        "issue_title": issue_record.get("title"),
                        "issue_category": issue_record.get("category"),
                        "agent": c.get("agent"),
                        "trace": row,
                    }
                )
        self.record_action_substep_trace(
            stage=stage,
            issue=issue,
            substep="save.persist_discussion_record",
            observation={
                "issue_id": issue_id,
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
            "params": {"issue_id": issue_id},
            "reasoning": "同步將本議題決議沉澱到 design rationale。",
        }
        self.update_design_rationale_for_issue(issue, contributions, resolution)
        self.record_action_substep_trace(
            stage=stage,
            issue=issue,
            substep="save.update_design_rationale",
            observation={
                "issue_id": issue_id,
                "filename": meeting_filename,
            },
            decision=rationale_decision,
            result={
                "updated": True,
            },
        )
        self.issue_status[issue_id]["saved"] = True
        return {
            "issue_id": issue_id,
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
            planned = self.mediator.plan_meeting_action_via_opa(state_summary, None)
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
            "reasoning": "依 meeting loop 決策執行指定 action。",
            "observation": observation,
        }

    def execute_action(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        action = self.action_name(decision.get("action", ""))
        params = decision.get("params") or {}
        return self.run_action_internal(action, params)

    def run(self, action: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        action = self.action_name(action)
        observation = self.observe_action(action, params)
        decision = self.plan_action(action, params, observation)
        result = self.execute_action(decision)
        result["opa_trace"] = self.record_runner_opa_trace(
            stage=f"meeting_runner.{decision.get('action', action)}",
            action=decision.get("action", action),
            params=decision.get("params") or {},
            observation=observation,
            decision=decision,
            result=result,
            issue_id=(decision.get("params") or {}).get("issue_id"),
        )
        return result

    @staticmethod
    def action_name(action: str) -> str:
        return str(action or "").strip()

    def run_action_internal(self, action: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        action = self.action_name(action)
        params = params or {}
        obs = {"action": action, "result": None, "error": None}

        if action == "generate_decision_issues":
            skip = set()
            for disc in self.artifact.get("discussions", []):
                for td in disc.get("issues", []):
                    for sid in td.get("source_ids", []):
                        skip.add(sid)
            max_items = self.config.get("issue_items", 5)
            latest_version = self.store.get_draft_version()
            draft_md = self.store.load_draft(latest_version) if latest_version >= 0 else None
            self.issues = self.mediator.generate_decision_issues(
                self.artifact,
                registry=self.registry,
                max_items=max_items,
                skip_source_ids=skip if skip else None,
                draft_markdown=draft_md,
                issue_pool=self.issue_pool,
            )
            self.issue_pool = list(self.artifact.get("issue_backlog", []) or [])
            self.issue_status = {
                t["id"]: {
                    "discussed": False,
                    "contributions": None,
                    "resolution": None,
                    "saved": False,
                }
                for t in self.issues
            }
            obs["result"] = {
                "issues": [
                    {
                        "id": t["id"],
                        "title": t["title"],
                        "category": t.get("category", ""),
                    }
                    for t in self.issues
                ],
                "count": len(self.issues),
            }
            return obs

        if action == "expand_decision_issues":
            issue_limit = self.config.get("issue_items", 5)
            if len(self.issues) >= issue_limit:
                obs["error"] = "已達decision issue 上限，無法擴充"
                return obs
            all_saved = all(
                self.issue_status.get(t["id"], {}).get("saved", False)
                for t in self.issues
            )
            if not all_saved:
                obs["error"] = "須先將本輪目前所有議題 save_issue 後才能擴充 decision issue"
                return obs
            skip = set()
            for disc in self.artifact.get("discussions", []):
                for td in disc.get("issues", []):
                    for sid in td.get("source_ids", []):
                        skip.add(sid)
            for rd in self.round_discussions:
                for sid in rd.get("source_ids", []):
                    skip.add(sid)
            max_items = issue_limit - len(self.issues)
            latest_version = self.store.get_draft_version()
            draft_md = self.store.load_draft(latest_version) if latest_version >= 0 else None
            new_items = self.mediator.generate_decision_issues(
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
            start_idx = len(self.issues) + 1
            for i, item in enumerate(new_items):
                tid = f"T-{start_idx + i}"
                new_issue = {
                    "id": tid,
                    "title": item.get("title", "待討論議題").strip(),
                    "description": item.get("description", ""),
                    "category": item.get("category", ""),
                    "participants": item.get("participants", []),
                    "discussion_mode": item.get("discussion_mode", "sequential"),
                    "speaking_order": item.get("speaking_order", []),
                    "source_ids": item.get("source_ids", []),
                }
                self.issues.append(new_issue)
                self.issue_status[tid] = {
                    "discussed": False,
                    "contributions": None,
                    "resolution": None,
                    "saved": False,
                }
            obs["result"] = {
                "expanded": len(new_items),
                "new_issues": [
                    {"id": t["id"], "title": t["title"], "category": t.get("category", "")}
                    for t in self.issues[-len(new_items):]
                ],
            }
            return obs

        if action == "start_discussion":
            issue_id = params.get("issue_id")
            issue = self.get_issue(issue_id)
            if not issue:
                obs["error"] = f"issue_id 不存在: {issue_id}"
                return obs
            st_disc = self.issue_status.get(issue_id, {})
            if st_disc.get("discussed"):
                obs["error"] = (
                    f"{issue_id} 已討論過，不可重複討論。"
                    f"請使用 save_issue 儲存後繼續下一個議題。"
                )
                return obs
            mode = issue.get("discussion_mode", "sequential")
            if mode == "simultaneous":
                contributions = self.mediator.moderate_simultaneous(
                    issue, self.registry, artifact=self.artifact
                )
                stakeholders = self.artifact.get("stakeholders", [])
                oq_records = self.mediator.handle_open_questions(
                    contributions, self.registry, stakeholders, artifact=self.artifact
                )
            else:
                contributions, oq_records = self.mediator.moderate_sequential(
                    issue, self.registry, artifact=self.artifact
                )
            for oq in oq_records:
                oq["issue_id"] = issue_id
            self.all_open_questions.extend(oq_records)
            self.issue_status[issue_id]["discussed"] = True
            self.issue_status[issue_id]["contributions"] = contributions
            result_info = {
                "issue_id": issue_id,
                "contributions_count": len(contributions),
                "oq_count": len(oq_records),
            }
            if not contributions:
                result_info["warning"] = (
                    "本議題無參與者可發言，請直接執行 save_issue 儲存後繼續。"
                )
            obs["result"] = result_info
            return obs

        if action == "resolve_issue":
            issue_id = params.get("issue_id")
            issue = self.get_issue(issue_id)
            st = self.issue_status.get(issue_id, {})
            if not issue or not st.get("discussed"):
                obs["error"] = f"請先對 {issue_id} 執行 start_discussion"
                return obs
            contributions = st.get("contributions") or []
            resolution = self.resolve_issue_via_substeps(
                issue=issue,
                contributions=contributions,
            )
            convergence_reason = resolution.get("summary", "")
            self.issue_status[issue_id]["resolution"] = resolution
            status = resolution.get("resolution_status")
            if status == "agreed":
                status_label = "收斂"
            elif status == "pending_confirmation":
                status_label = "待人類裁決"
            else:
                status_label = "未收斂"
            self.logger.info(
                "  決議: [%s] %s｜%s｜結果: %s",
                issue_id,
                issue.get("title", ""),
                f"{status_label}（{convergence_reason}）",
                resolution.get("resolution", ""),
            )
            needs_human = bool(resolution.get("needs_human"))
            obs["result"] = {
                "issue_id": issue_id,
                "resolution": resolution.get("resolution"),
                "resolution_status": resolution.get("resolution_status", resolution.get("resolution")),
                "summary": resolution.get("summary", ""),
                "decision_summary": resolution.get("decision_summary", resolution.get("summary", "")),
                "agreed_points_count": len(resolution.get("agreed_points", []) or []),
                "unresolved_points_count": len(resolution.get("unresolved_points", []) or []),
                "needs_human": needs_human,
            }
            obs["status"] = "needs_human" if needs_human else "resolved"
            obs["issue_id"] = issue_id
            obs["summary"] = resolution.get("summary", "") or resolution.get("resolution", "")
            if needs_human:
                self.issue_status[issue_id]["resolution"] = None
            return obs

        if action == "escalate_to_human":
            if not self.mediator.enable_human_escalation:
                self.logger.info("  人類裁決已關閉，自動改為 resolve_issue")
                return self.run("resolve_issue", params)
            issue_id = params.get("issue_id")
            issue = self.get_issue(issue_id)
            st_esc = self.issue_status.get(issue_id, {})
            if not issue or not st_esc.get("discussed"):
                obs["error"] = f"請先對 {issue_id} 執行 start_discussion"
                return obs
            contributions = st_esc.get("contributions") or []
            self.logger.info(f"  人類裁決: [{issue_id}] {issue.get('title', '')}")
            wrapped = self.escalate_issue_via_substeps(
                issue=issue,
                contributions=contributions,
            )
            decision_text = str((wrapped.get("human_decision_raw") or {}).get("decision", ""))
            self.issue_status[issue_id]["resolution"] = wrapped
            obs["result"] = {
                "issue_id": issue_id,
                "resolution": "human_decision",
                "summary": decision_text,
            }
            obs["status"] = "human_decided"
            obs["issue_id"] = issue_id
            obs["summary"] = decision_text or "本議題已升級由人類裁決。"
            return obs

        if action == "save_issue":
            issue_id = params.get("issue_id")
            issue = self.get_issue(issue_id)
            st = self.issue_status.get(issue_id, {})
            if not issue or not st.get("discussed"):
                obs["error"] = f"請先對 {issue_id} 執行 start_discussion"
                return obs
            contributions = st.get("contributions") or []
            resolution = st.get("resolution")
            self.logger.info(f"  存檔: [{issue_id}] {issue.get('title', '')}")
            if not resolution:
                obs["error"] = f"請先對 {issue_id} 執行 resolve_issue 或 escalate_to_human，之後才能 save_issue"
                return obs
            save_result = self.save_issue_via_substeps(
                issue=issue,
                contributions=contributions,
                resolution=resolution,
            )
            obs["result"] = save_result
            obs["status"] = "saved"
            obs["issue_id"] = issue_id
            obs["summary"] = f"已儲存 {issue_id} 至 {save_result.get('filename')}"
            return obs

        if action == "finish_round":
            if self.issues:
                unsaved_ids = [
                    t.get("id", "")
                    for t in self.issues
                    if not self.issue_status.get(t.get("id", ""), {}).get("saved", False)
                ]
                if unsaved_ids:
                    obs["error"] = (
                        "尚有未存檔議題，請先完成 save_issue 後再 finish_round: "
                        + ", ".join(i for i in unsaved_ids if i)
                    )
                    return obs
            obs["result"] = "round_complete"
            return obs

        obs["error"] = f"未知動作: {action}，可用: {MEETING_ACTIONS}"
        return obs

    def get_issue(self, issue_id: Optional[str]) -> Optional[Dict]:
        if not issue_id:
            return None
        for t in self.issues:
            if t.get("id") == issue_id:
                return t
        return None

    def find_issue_proposer(self, issue: Dict) -> Optional[str]:
        """從 issue 的 source_issue_ids 反查提案者。"""
        issue_ids = set(issue.get("source_issue_ids") or [])
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
        for tid, st in self.issue_status.items():
            status_list.append(
                {
                    "issue_id": tid,
                    "discussed": st.get("discussed", False),
                    "resolved": st.get("resolution") is not None,
                    "resolution": (st.get("resolution") or {}).get("resolution"),
                    "saved": st.get("saved", False),
                }
            )
        issue_limit = self.config.get("issue_items", 5)
        issues_count = len(self.issues)
        issue_pool_count = len(self.issue_pool)
        all_saved = (
            issues_count > 0
            and all(self.issue_status.get(t["id"], {}).get("saved", False) for t in self.issues)
        )
        can_expand_decision_issues = issues_count < issue_limit and all_saved and issue_pool_count > 0
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
            "issue_limit": issue_limit,
            "issues_count": issues_count,
            "issue_pool_count": issue_pool_count,
            "all_current_issues_saved": all_saved,
            "can_expand_decision_issues": can_expand_decision_issues,
            "queue_status": {
                "clarification_queue_count": len(clarification_queue),
                "human_decision_queue_count": len(human_decision_queue),
                "direct_apply_queue_count": len(direct_apply_queue),
                "has_pending_queue_items": bool(
                    clarification_queue or human_decision_queue or direct_apply_queue
                ),
            },
            "issues": [
                {
                    "schema_version": t.get("schema_version", "decision_issue.v1"),
                    "id": t["id"],
                    "title": t["title"],
                    "category": t.get("category", ""),
                    "category_label": ISSUE_CATEGORY_LABEL.get(
                        t.get("category", ""), t.get("category", "")
                    ),
                    "source_issue_ids": t.get("source_issue_ids", []),
                    "triage_action": t.get("triage_action", "formal_meeting"),
                }
                for t in self.issues
            ],
            "issue_status": status_list,
            "round_discussions_length": len(self.round_discussions),
        }

    def get_round_discussions(self) -> List[Dict]:
        return self.round_discussions

    def get_all_open_questions(self) -> List[Dict]:
        return self.all_open_questions

    def get_issue_snapshot(self) -> List[Dict]:
        return list(self.issues)
