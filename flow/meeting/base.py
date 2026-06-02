# MeetingCoordinator: delegates meeting lifecycle and records round-level traces.
"""MeetingCoordinator — 會議協調窗口。

所有實作已拆至子模組：
  - main               : 每輪主會議生命週期
  - requirement_elicitation : 需求擷取會議
  - conflict_review    : 衝突再審查 / 需求變更
"""
from typing import Any, Dict, List, Optional

from agents.profile.analyst.requirements import requirement_discussion_pool
from agents.profile.analyst.conflict_store import conflict_entries_count
from utils import stage_enabled
from agents.profile.mediator.meeting_runner import (
    run_meeting_loop as run_mediator_meeting_loop,
    run_round_opa_loop as run_mediator_round_opa_loop,
)

from .main import (
    apply_mediator_updates,
    collect_issue_proposals,
    draft_requirement_completeness_proposals,
    issue_proposal,
    recent_issue_discussions,
    run_meeting_round_block,
)
from .conflict_review import conflict_review
from .requirement_elicitation import run_elicitation_meeting


class MeetingCoordinator:
    def __init__(self, flow):
        self.flow = flow

    def json_safe_trace_value(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, list):
            return [self.json_safe_trace_value(item) for item in value]
        if isinstance(value, tuple):
            return [self.json_safe_trace_value(item) for item in value]
        if isinstance(value, dict):
            return {
                str(key): self.json_safe_trace_value(item)
                for key, item in value.items()
            }
        if isinstance(value, MeetingCoordinator):
            return {"type": "MeetingCoordinator"}
        return {
            "type": type(value).__name__,
            "repr": repr(value),
        }

    # ------ 共用小工具（window 保留供 flow/setup.py 委派呼叫） ------

    def is_last_meeting_round(self, artifact: Dict[str, Any], round_num: int) -> bool:
        meta = artifact.get("meta") or {}
        end = meta.get("meeting_end_round")
        if end is not None:
            try:
                return int(round_num) == int(end)
            except (TypeError, ValueError):
                pass
        try:
            total = int(self.flow.config.get("rounds", 1) or 1)
        except (TypeError, ValueError):
            total = 1
        return int(round_num) >= total


    def plan_meeting_action(
        self,
        *,
        state_summary: Dict[str, Any],
        last_observation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.flow.mediator_agent.plan_meeting_action_via_opa(
            state_summary,
            last_observation,
        )

    def run_round_pipeline_step(
        self,
        *,
        stage: str,
        round_num: int,
        artifact: Dict[str, Any],
        action_fn,
        action_kwargs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        action_kwargs = dict(action_kwargs or {})
        observation = {
            "stage": stage,
            "round_num": round_num,
            "requirements_count": len(requirement_discussion_pool(artifact)),
            "conflicts_count": conflict_entries_count(artifact),
            "open_questions_count": len(artifact.get("open_questions", []) or []),
        }
        decision = {
            "action": stage,
            "params": self.json_safe_trace_value(action_kwargs),
            "reasoning": f"執行 {stage} pipeline step。",
        }
        updated_artifact = action_fn(**action_kwargs)
        result = {
            "status": "success",
            "summary": f"completed {stage}",
            "artifact_changed": updated_artifact is not None,
        }
        return updated_artifact if updated_artifact is not None else artifact

    def observe_round_state(
        self,
        *,
        runner: Any,
        last_action_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        state_summary = runner.get_state_summary()
        return {
            "runner": runner,
            "round_num": runner.round_num,
            "state_summary": state_summary,
            "last_action_result": last_action_result or {},
            "issues_count": len(state_summary.get("issues") or []),
            "records_count": state_summary.get("records_count", 0),
            "has_pending_human_decisions": bool(
                ((state_summary.get("human_decision_status") or {}).get("has_pending_human_decisions"))
            ),
            "can_add_issues": bool(state_summary.get("can_add_issues")),
        }

    def plan_round_step(
        self,
        *,
        observation: Dict[str, Any],
    ) -> Dict[str, Any]:
        state_summary = observation.get("state_summary") or {}
        human_decision_status = state_summary.get("human_decision_status") or {}
        runner = observation.get("runner")
        if runner is not None:
            draft_updated = (
                self.default_update_draft(runner)
                if stage_enabled(self.flow.config, "default_update_draft", True)
                else None
            )
            current_issues_saved = bool(state_summary.get("all_current_issues_saved"))
            current_issues_count = int(state_summary.get("issues_count") or 0)
            can_expand_issues = current_issues_count == 0 or current_issues_saved
            if runner.issue_pool and can_expand_issues:
                return {
                    "action": "add_issues",
                    "params": {},
                    "reasoning": "需求更新後產生待處理議題，先追加並完成討論，再更新 draft。",
                }
            if stage_enabled(self.flow.config, "general_formal_meeting", True):
                prepared = self.prepare_draft_issue_proposals_after_defaults(runner)
                if runner.issue_pool and can_expand_issues:
                    return {
                        "action": "add_issues",
                        "params": {},
                        "reasoning": "預設會議後產生待處理議題，先追加並完成討論，再繼續本輪。",
                    }
                if prepared and can_expand_issues:
                    return {
                        "action": "add_issues",
                        "params": {},
                        "reasoning": "預設會議已完成，已根據更新後 draft 產生一般 issue proposals，接著追加正式議題。",
                    }
            elif draft_updated:
                self.flow.logger.info("Default Formal Meeting：已更新 draft，general_formal_meeting disabled，略過一般議題提出")
        if runner is not None:
            if stage_enabled(self.flow.config, "general_update_draft", True):
                self.general_update_draft(runner, state_summary, human_decision_status)
        if (
            int(state_summary.get("issues_count") or 0) == 0
            and int(state_summary.get("backlog_count") or 0) == 0
            and not human_decision_status.get("has_pending_human_decisions")
        ):
            return {
                "action": "finish_round",
                "params": {},
                "reasoning": "本輪沒有可產生正式會議議題的 proposal，且沒有待處理 human_decision_queue，直接結束本輪。",
            }
        if (
            state_summary.get("all_current_issues_saved")
            and int(state_summary.get("backlog_count") or 0) == 0
            and not human_decision_status.get("has_pending_human_decisions")
        ):
            return {
                "action": "finish_round",
                "params": {},
                "reasoning": "所有議題已保存，且沒有剩餘 proposal 或待處理 human_decision_queue，直接結束本輪。",
            }
        for issue_state in state_summary.get("issue_states") or []:
            issue_id = issue_state.get("issue_id")
            if not issue_id:
                continue
            if not issue_state.get("discussed"):
                return {
                    "action": "start_issue",
                    "params": {"issue_id": issue_id},
                    "reasoning": "依議程順序開始下一個未討論議題。",
                }
            if issue_state.get("needs_human"):
                return {
                    "action": "judge_issue",
                    "params": {"issue_id": issue_id},
                    "reasoning": "議題已判定需要人類裁決，進入裁決流程。",
                }
            if not issue_state.get("resolved"):
                return {
                    "action": "resolve_issue",
                    "params": {"issue_id": issue_id},
                    "reasoning": "議題已完成討論，先整理收斂結果。",
                }
            if not issue_state.get("saved"):
                return {
                    "action": "save_issue",
                    "params": {"issue_id": issue_id},
                    "reasoning": "議題已收斂，先保存會議紀錄與設計緣由。",
                }
        last_observation = observation.get("last_action_result") or {}
        decision = self.plan_meeting_action(
            state_summary=state_summary,
            last_observation=last_observation,
        )
        return {
            "action": decision.get("action", "finish_round"),
            "params": decision.get("params") or {},
            "reasoning": decision.get("reasoning", ""),
        }

    def prepare_draft_issue_proposals_after_defaults(self, runner: Any) -> bool:
        if not stage_enabled(self.flow.config, "general_formal_meeting", True):
            return False
        artifact = runner.output_artifact if isinstance(runner.output_artifact, dict) else runner.artifact
        meta = artifact.setdefault("meta", {})
        flag = f"draft_issue_proposals_round_{runner.round_num}"
        if meta.get(flag):
            return False
        if not stage_enabled(self.flow.config, "default_update_draft", True):
            return False
        latest_version = self.default_update_draft(runner)
        if latest_version is None:
            return False
        latest_version = int(latest_version)
        draft_md = self.flow.store.load_draft(latest_version) or ""
        if not draft_md.strip():
            return False
        if self.refresh_conflicts_before_draft_update(
            runner,
            artifact,
            block_on_unresolved=False,
        ):
            return None

        post_default_proposals = self.post_default_conflict_proposals(
            artifact,
            round_num=runner.round_num,
        )
        if post_default_proposals:
            self.flow.logger.info(
                "Issue Proposal：最新 conflict_report 有未解決衝突，先安排需求衝突解決議題"
            )

        proposal_artifact = {
            "latest_draft": draft_md,
            "proposal_context": self.proposal_context_summary(
                artifact,
                draft_version=latest_version,
            ),
        }
        proposal_safety_limit = 20
        proposals = list(post_default_proposals)
        invalid_count = 0
        registry = getattr(self.flow, "registry", None)
        for agent_name in ("analyst", "expert", "modeler"):
            agent = registry.get(agent_name) if registry else None
            if not agent or not hasattr(agent, "propose_issues"):
                continue
            try:
                rows = agent.propose_issues(
                    proposal_artifact,
                    round_num=runner.round_num,
                    max_items=proposal_safety_limit,
                )
            except Exception as e:
                invalid_count += 1
                self.flow.logger.warning(
                    "Issue Proposal：%s draft proposal failed: %s",
                    agent_name,
                    e,
                )
                continue
            for i, row in enumerate(rows or [], 1):
                normalized = self.issue_proposal(
                    row,
                    proposed_by=agent_name,
                    round_num=runner.round_num,
                    index=i,
                )
                if normalized:
                    proposals.append(normalized)
                else:
                    invalid_count += 1
        proposals.extend(
            draft_requirement_completeness_proposals(
                draft_md,
                round_num=runner.round_num,
            )
        )

        meta[flag] = True
        if runner.artifact is not artifact:
            runner.artifact.setdefault("meta", {})[flag] = True
        backlog = [
            row for row in (artifact.get("issue_backlog", []) or [])
            if isinstance(row, dict)
        ]
        if runner.artifact is not artifact:
            backlog = [
                row for row in (runner.artifact.get("issue_backlog", []) or backlog)
                if isinstance(row, dict)
            ]

        if not proposals and not backlog:
            self.flow.store.save_artifact(artifact)
            self.flow.logger.info(
                "Issue Proposal：更新 draft 後無新增一般議題，淘汰 %s 筆",
                invalid_count,
            )
            return False

        existing = artifact.get("issue_proposals", []) or []
        seen = {
            str(row.get("issue_id") or "").strip()
            for row in existing
            if isinstance(row, dict) and str(row.get("issue_id") or "").strip()
        }
        added = []
        for row in proposals:
            issue_id = str(row.get("issue_id") or "").strip()
            if issue_id and issue_id in seen:
                continue
            existing.append(row)
            added.append(row)
            if issue_id:
                seen.add(issue_id)
        artifact["issue_proposals"] = existing
        runner.issue_pool.extend(backlog + added)
        self.flow.store.save_artifact(artifact)
        self.flow.logger.info(
            "Issue Proposal：預設會議後待規劃 %s 筆（backlog %s，新增 %s），淘汰 %s 筆",
            len(backlog) + len(added),
            len(backlog),
            len(added),
            invalid_count,
        )
        return bool(backlog or added)

    def default_update_draft(self, runner: Any) -> Optional[int]:
        if not stage_enabled(self.flow.config, "default_update_draft", True):
            return None
        artifact = runner.output_artifact if isinstance(runner.output_artifact, dict) else runner.artifact
        meta = artifact.setdefault("meta", {})
        flag = f"default_update_draft_round_{runner.round_num}"
        if meta.get(flag):
            value = meta.get("latest_default_draft_version")
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
        issues = runner.current_meeting_issues()
        default_issues = [
            issue for issue in issues
            if isinstance(issue, dict) and runner.is_default_issue(issue)
        ]
        if not default_issues:
            return None
        all_saved = all(
            runner.issue_states.get(issue.get("id"), {}).get("saved", False)
            for issue in default_issues
            if isinstance(issue, dict)
        )
        if not all_saved:
            return None
        if runner.issue_pool:
            return None

        if self.refresh_conflicts_before_draft_update(
            runner,
            artifact,
            block_on_unresolved=False,
        ):
            return None

        latest_version = self.flow.store.get_draft_version()
        previous_draft = self.flow.store.load_draft(latest_version) if latest_version >= 0 else ""
        next_version = max(0, latest_version + 1)
        draft_md = self.flow.analyst_agent.run_requirements_analyst(
            "default_update_draft",
            artifact=artifact,
            draft_version=next_version,
            previous_draft=previous_draft,
            round_num=runner.round_num,
            artifact_dir=getattr(self.flow.store, "artifact_dir", None),
        )
        self.flow.store.save_draft(draft_md, version=next_version)
        meta[flag] = True
        meta["latest_default_draft_version"] = next_version
        if runner.artifact is not artifact:
            runner.artifact.setdefault("meta", {}).update(
                {
                    flag: True,
                    "latest_default_draft_version": next_version,
                }
            )
        self.flow.store.save_artifact(artifact)
        self.flow.logger.info(
            "Default Update Draft：已生成 draft_v%s",
            next_version,
        )
        return next_version

    @staticmethod
    def proposal_context_summary(
        artifact: Dict[str, Any],
        *,
        draft_version: int,
    ) -> Dict[str, Any]:
        if not isinstance(artifact, dict):
            return {"draft": {"version": draft_version}}

        def clean_id(value: Any) -> str:
            return str(value or "").strip()

        def first_ids(rows: List[Dict[str, Any]], limit: int = 30) -> List[str]:
            ids: List[str] = []
            for row in rows:
                rid = clean_id(row.get("id") or row.get("issue_id"))
                if rid:
                    ids.append(rid)
            return list(dict.fromkeys(ids))[:limit]

        raw_requirements = artifact.get("URL") or []
        requirements = [row for row in raw_requirements if isinstance(row, dict)]
        stakeholders = [
            clean_id(row.get("name"))
            for row in (artifact.get("stakeholders") or [])
            if isinstance(row, dict) and clean_id(row.get("name"))
        ]
        req_rows = [
            row for row in (artifact.get("REQ") or [])
            if isinstance(row, dict)
        ]
        req_counts = {"URL": len(requirements), "REQ": len(req_rows), "functional": 0, "non_functional": 0, "constraint": 0}
        for row in req_rows:
            rtype = clean_id(row.get("type")).lower()
            if rtype == "functional":
                req_counts["functional"] += 1
            elif rtype == "non-functional":
                req_counts["non_functional"] += 1
            elif rtype == "constraint":
                req_counts["constraint"] += 1

        conflict = artifact.get("conflict") if isinstance(artifact.get("conflict"), dict) else {}
        conflict_report = conflict.get("report") if isinstance(conflict.get("report"), list) else []
        unresolved_conflicts = []
        for row in conflict_report:
            if not isinstance(row, dict):
                continue
            status = clean_id(row.get("status")).lower()
            if status not in {"agreed", "human_decision"}:
                unresolved_conflicts.append(row)

        open_questions = [
            row for row in (artifact.get("open_questions") or [])
            if isinstance(row, dict) and clean_id(row.get("status")).lower() != "answered"
        ]
        feedback = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
        feedback_counts = {
            "findings": len([row for row in (feedback.get("findings") or []) if isinstance(row, dict)]),
            "constraints": len([row for row in (feedback.get("constraints") or []) if isinstance(row, dict)]),
            "risks": len([row for row in (feedback.get("risks") or []) if isinstance(row, dict)]),
            "recommendations": len([row for row in (feedback.get("recommendations") or []) if isinstance(row, dict)]),
        }
        models = [
            row for row in (artifact.get("system_models") or [])
            if isinstance(row, dict)
        ]
        model_summaries: List[Dict[str, Any]] = []
        for row in models:
            model_id = clean_id(row.get("id"))
            model_type = clean_id(row.get("type") or row.get("diagram_type"))
            name = clean_id(row.get("name"))
            description = clean_id(row.get("description"))
            summary: Dict[str, Any] = {}
            if model_id:
                summary["id"] = model_id
            if name:
                summary["name"] = name
            if model_type:
                summary["type"] = model_type
            if description:
                summary["description"] = description
            if summary:
                model_summaries.append(summary)
        model_types = sorted(
            {
                clean_id(row.get("type") or row.get("diagram_type"))
                for row in models
                if clean_id(row.get("type") or row.get("diagram_type"))
            }
        )

        return {
            "draft": {"version": draft_version},
            "stakeholders": list(dict.fromkeys(stakeholders)),
            "requirement_counts": req_counts,
            "open_questions": {
                "count": len(open_questions),
                "ids": first_ids(open_questions),
            },
            "conflicts": {
                "unresolved_count": len(unresolved_conflicts),
                "ids": first_ids(unresolved_conflicts),
            },
            "feedback": {
                **feedback_counts,
            },
            "system_models": {
                "count": len(models),
                "types": model_types,
                "models": model_summaries,
            },
        }

    @staticmethod
    def post_default_conflict_proposals(
        artifact: Dict[str, Any],
        *,
        round_num: int,
    ) -> List[Dict[str, Any]]:
        if not isinstance(artifact, dict):
            return []
        meta = artifact.setdefault("meta", {})
        added_flag = f"post_refine_conflict_issue_added_round_{round_num}"
        signature_key = f"post_refine_conflict_signature_round_{round_num}"
        if meta.get(added_flag):
            return []
        conflict = artifact.get("conflict") if isinstance(artifact.get("conflict"), dict) else {}
        report = conflict.get("report") if isinstance(conflict.get("report"), list) else []
        unresolved = []
        for row in report:
            if not isinstance(row, dict):
                continue
            status = str(row.get("status") or "").strip().lower()
            if status in {"agreed", "human_decision"}:
                continue
            unresolved.append(row)
        if not unresolved:
            return []
        unresolved_ids = [
            str(row.get("id") or "").strip()
            for row in unresolved
            if str(row.get("id") or "").strip()
        ]
        signature = ",".join(sorted(dict.fromkeys(unresolved_ids)))
        existing_ids = []
        for key in ("issue_proposals", "issue_backlog", "meeting_issues"):
            for row in artifact.get(key) or []:
                if not isinstance(row, dict):
                    continue
                value = str(row.get("issue_id") or row.get("id") or "").strip()
                if "mediator-conflict-review" in value:
                    existing_ids.append(value)
                trace = row.get("trace") if isinstance(row.get("trace"), dict) else {}
                for proposal_id in trace.get("proposal_ids") or []:
                    value = str(proposal_id or "").strip()
                    if "mediator-conflict-review" in value:
                        existing_ids.append(value)
        if existing_ids:
            meta[added_flag] = True
            meta[signature_key] = signature
            return []
        meta[added_flag] = True
        meta[signature_key] = signature
        issue_id = f"I-R{round_num}-mediator-conflict-review"
        return [
            {
                "issue_id": issue_id,
                "title": "解決需求衝突",
                "expect_outcome": "讀取整份 conflict_report，直接討論既有 resolution_options 與 recommended_resolution。若會議中可判斷採用或調整方案則收斂；若無法在內容上做出抉擇，整理選項交由人類裁決。",
                "sources": [
                    {
                        "artifact": "conflict_report",
                        "ids": unresolved_ids,
                        "evidence": f"最新 conflict_report 共有 {len(report)} 筆項目，其中 {len(unresolved)} 筆需求衝突尚未解決。",
                    }
                ],
                "importance": "high",
                "reason": "預設需求整理後產生新的 conflict_report；需求衝突需先處理，之後才提出一般議題。",
                "proposed_by": "mediator",
                "category": "resolve_conflict",
                "expected_actions": {"analyst": ["discuss_conflict"]},
                "participants": ["user", "analyst"],
                "discussion_mode": "sequential",
                "round": round_num,
                "conflict_signature": signature,
            }
        ]

    def general_update_draft(
        self,
        runner: Any,
        state_summary: Dict[str, Any],
        human_decision_status: Dict[str, Any],
    ) -> bool:
        if not stage_enabled(self.flow.config, "general_update_draft", True):
            return False
        artifact = runner.output_artifact if isinstance(runner.output_artifact, dict) else runner.artifact
        meta = artifact.setdefault("meta", {})
        round_num = runner.round_num
        proposal_flag = f"draft_issue_proposals_round_{round_num}"
        final_flag = f"general_update_draft_round_{round_num}"
        if meta.get(final_flag):
            return False
        if not meta.get(proposal_flag):
            return False
        if not state_summary.get("all_current_issues_saved"):
            return False
        if int(state_summary.get("backlog_count") or 0) != 0:
            return False
        if human_decision_status.get("has_pending_human_decisions"):
            return False
        general_issues = [
            issue
            for issue in runner.current_meeting_issues()
            if isinstance(issue, dict) and not runner.is_default_issue(issue)
        ]
        if not general_issues:
            return False

        if self.refresh_conflicts_before_draft_update(
            runner,
            artifact,
            log_prefix="General Update Draft",
        ):
            return False

        latest_version = self.flow.store.get_draft_version()
        previous_draft = self.flow.store.load_draft(latest_version) if latest_version >= 0 else ""
        next_version = max(0, latest_version + 1)
        draft_md = self.flow.analyst_agent.run_requirements_analyst(
            "general_update_draft",
            artifact=artifact,
            draft_version=next_version,
            previous_draft=previous_draft,
            round_num=round_num,
            artifact_dir=getattr(self.flow.store, "artifact_dir", None),
        )
        self.flow.store.save_draft(draft_md, version=next_version)
        meta[final_flag] = True
        meta["latest_general_draft_version"] = next_version
        if runner.artifact is not artifact:
            runner.artifact.setdefault("meta", {}).update(meta)
        self.flow.store.save_artifact(artifact)
        self.flow.logger.info(
            "General Update Draft：已生成 draft_v%s",
            next_version,
        )
        return True

    def refresh_conflicts_before_draft_update(
        self,
        runner: Any,
        artifact: Dict[str, Any],
        *,
        log_prefix: str = "Issue Proposal",
        block_on_unresolved: bool = True,
    ) -> bool:
        meta = artifact.setdefault("meta", {})
        if not bool(meta.get("requirements_changed")):
            return False
        result = self.flow.analyst_agent.execute_issue_conflict_analysis(
            artifact=artifact,
            force=True,
        )
        if result.get("skipped"):
            return False
        fake_record = [
            {
                "agent": "analyst",
                "response": {
                    "text": "需求已更新，已重新辨識需求衝突並產生最新 conflict report。",
                    "issue_action_results": [result],
                },
            }
        ]
        runner.save_formal_conflict_report(fake_record)
        meta["requirements_changed"] = False
        meta["requirements_conflicts_refreshed_round"] = runner.round_num
        meta["requirements_conflicts_refreshed_by"] = "auto_before_update_draft"
        meta.pop("requirements_changed_by", None)
        meta.pop("requirements_changed_reason", None)
        if runner.artifact is not artifact:
            runner.artifact.setdefault("meta", {}).update(meta)
            if "conflict" in artifact:
                runner.artifact["conflict"] = artifact["conflict"]

        conflict_state = artifact.get("conflict") if isinstance(artifact.get("conflict"), dict) else {}
        report_rows = conflict_state.get("report") if isinstance(conflict_state.get("report"), list) else []
        unresolved_count = 0
        for report_row in report_rows:
            if not isinstance(report_row, dict):
                continue
            status = str(report_row.get("status") or "").strip().lower()
            if status not in {"agreed", "human_decision"}:
                unresolved_count += 1

        pending_conflict_proposals = self.post_default_conflict_proposals(
            artifact,
            round_num=runner.round_num,
        )
        if pending_conflict_proposals:
            existing_pool = [
                row for row in (artifact.get("issue_backlog") or [])
                if isinstance(row, dict)
            ]
            existing_keys = {
                (
                    str(row.get("issue_id") or "").strip(),
                    str(row.get("title") or "").strip(),
                )
                for row in existing_pool
            }
            added = []
            for row in pending_conflict_proposals:
                key = (
                    str(row.get("issue_id") or "").strip(),
                    str(row.get("title") or "").strip(),
                )
                if key in existing_keys:
                    continue
                existing_keys.add(key)
                existing_pool.append(row)
                added.append(row)
            artifact["issue_backlog"] = existing_pool
            runner.issue_pool.extend(added)
            if runner.artifact is not artifact:
                runner.artifact["issue_backlog"] = existing_pool
                if "conflict" in artifact:
                    runner.artifact["conflict"] = artifact["conflict"]
            self.flow.store.save_artifact(artifact)
            if added:
                self.flow.logger.info(
                    "%s：需求更新後有 %s 筆未解決衝突，已追加 %s 個預設衝突解決議題",
                    log_prefix,
                    unresolved_count,
                    len(added),
                )
                return True
            if block_on_unresolved:
                self.flow.logger.info(
                    "%s：需求更新後仍有 %s 筆未解決衝突；暫停更新 draft，需先完成需求衝突解決",
                    log_prefix,
                    unresolved_count,
                )
                return True
            self.flow.logger.info(
                "%s：需求更新後仍有 %s 筆未解決衝突，但 default_update_draft 必須更新草稿，接著更新 draft",
                log_prefix,
                unresolved_count,
            )
            return False
        if unresolved_count:
            self.flow.store.save_artifact(artifact)
            if block_on_unresolved:
                self.flow.logger.info(
                    "%s：需求更新後仍有 %s 筆未解決衝突；暫停更新 draft，需先完成需求衝突解決",
                    log_prefix,
                    unresolved_count,
                )
                return True
            self.flow.logger.info(
                "%s：需求更新後仍有 %s 筆未解決衝突，但 default_update_draft 必須更新草稿，接著更新 draft",
                log_prefix,
                unresolved_count,
            )
            return False
        self.flow.store.save_artifact(artifact)
        self.flow.logger.info(
            "%s：需求更新後已重新整理 conflict report，接著更新 draft",
            log_prefix,
        )
        return False

    def act_round_step(
        self,
        *,
        runner: Any,
        decision: Dict[str, Any],
        observation: Dict[str, Any],
    ) -> Dict[str, Any]:
        result = runner.run(decision.get("action", "finish_round"), decision.get("params") or {})
        self.flow.ensure_artifact_contract(runner.artifact)
        return result

    def run_round_opa_loop(self, runner: Any) -> None:
        run_mediator_round_opa_loop(self, runner)

    # ------ 委派：main ------

    def recent_issue_discussions(self, artifact, *, rounds=1):
        return recent_issue_discussions(artifact, rounds=rounds)

    def issue_proposal(self, item, *, proposed_by, round_num, index):
        return issue_proposal(item, proposed_by=proposed_by, round_num=round_num, index=index)

    def collect_issue_proposals(self, artifact, *, round_num):
        return collect_issue_proposals(self, artifact, round_num=round_num)

    def apply_mediator_updates(self, artifact, updates):
        return apply_mediator_updates(artifact, updates)

    def run_meeting_loop(self, runner):
        run_mediator_meeting_loop(self, runner)

    # ------ 委派：主流程入口 ------

    def run_requirement_elicitation_meeting(self, artifact, round_num):
        return self.run_round_pipeline_step(
            stage="requirement_elicitation",
            round_num=round_num,
            artifact=artifact,
            action_fn=run_elicitation_meeting,
            action_kwargs={
                "coordinator": self,
                "artifact": artifact,
                "round_num": round_num,
            },
        )

    def run_conflict_review(self, artifact, round_num):
        return self.run_round_pipeline_step(
            stage="conflict_review",
            round_num=round_num,
            artifact=artifact,
            action_fn=conflict_review,
            action_kwargs={
                "coordinator": self,
                "artifact": artifact,
                "round_num": round_num,
            },
        )

    def run_meeting_round(self, artifact, round_num):
        return run_meeting_round_block(self, artifact, round_num)
