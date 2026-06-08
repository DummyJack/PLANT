# Handles base logic for project flow orchestration and stage execution.
from typing import Any, Dict, List, Optional

from storage.requirements import requirement_discussion_pool
from agents.profile.analyst.conflicts import conflict_entries_count
from utils import stage_enabled
from agents.meeting.main import (
    run_meeting_loop as run_mediator_meeting_loop,
    run_round_opa_loop as run_mediator_round_opa_loop,
)

from .main import (
    apply_mediator_updates,
    collect_issue_proposals,
    conflict_report_row_ids,
    conflict_report_rows,
    default_meeting_issues,
    issue_proposal,
    recent_issue_discussions,
    run_meeting_round_block,
    unresolved_conflict_report_rows,
)
from .conflict_review import conflict_review
from .requirement_elicitation import run_elicitation


DEFAULT_CONFLICT_RESOLUTION_LIMIT = 1


# ========
# Defines MeetingCoordinator class for this module workflow.
# ========
class MeetingCoordinator:
    # ========
    # Defines __init__ function for this module workflow.
    # ========
    def __init__(self, flow):
        self.flow = flow

    # ========
    # Defines json safe trace value function for this module workflow.
    # ========
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


    # ========
    # Defines is last meeting round function for this module workflow.
    # ========
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

    # ========
    # Defines general meeting round enabled function for this module workflow.
    # ========
    def general_meeting_round_enabled(self, round_num: int) -> bool:
        if not stage_enabled(self.flow.config, "general_formal_meeting", True):
            return False
        default_enabled = stage_enabled(self.flow.config, "default_formal_meeting", True)
        if default_enabled:
            return int(round_num or 0) >= 2
        return int(round_num or 0) >= 1


    # ========
    # Defines plan meeting action function for this module workflow.
    # ========
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

    # ========
    # Defines run round pipeline step function for this module workflow.
    # ========
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

    # ========
    # Defines observe round state function for this module workflow.
    # ========
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

    # ========
    # Defines plan round step function for this module workflow.
    # ========
    def plan_round_step(
        self,
        *,
        observation: Dict[str, Any],
    ) -> Dict[str, Any]:
        state_summary = observation.get("state_summary") or {}
        human_decision_status = state_summary.get("human_decision_status") or {}
        runner = observation.get("runner")
        if runner is not None:
            has_general_issues = any(
                isinstance(issue, dict) and not runner.is_default_issue(issue)
                for issue in runner.current_meeting_issues()
            )
            draft_updated = (
                self.default_update_draft(runner)
                if stage_enabled(self.flow.config, "default_update_draft", True)
                and not has_general_issues
                else None
            )
            pending_decision = self.pending_issue_decision(runner)
            if pending_decision:
                return pending_decision
            current_issues_saved = bool(state_summary.get("all_current_issues_saved"))
            current_issues_count = int(state_summary.get("issues_count") or 0)
            can_expand_issues = current_issues_count == 0 or current_issues_saved
            can_add_issues = bool(state_summary.get("can_add_issues"))
            if self.general_meeting_round_enabled(runner.round_num):
                if runner.issue_pool and can_expand_issues and can_add_issues:
                    return {
                        "action": "add_issues",
                        "params": {},
                        "reasoning": "預設會議已完成並更新 draft，接著加入一般正式會議議題。",
                    }
            elif draft_updated:
                if stage_enabled(self.flow.config, "general_formal_meeting", True):
                    self.flow.logger.info("Default Formal Meeting：已更新 draft，一般正式會議將從 Round 2 開始")
                else:
                    self.flow.logger.info("Default Formal Meeting：已更新 draft，general_formal_meeting disabled，略過一般議題提出")
        if runner is not None:
            if (
                stage_enabled(self.flow.config, "general_update_draft", True)
                and self.general_meeting_round_enabled(runner.round_num)
            ):
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
        if (
            state_summary.get("all_current_issues_saved")
            and int(state_summary.get("backlog_count") or 0) > 0
            and not state_summary.get("can_add_issues")
            and not human_decision_status.get("has_pending_human_decisions")
        ):
            return {
                "action": "finish_round",
                "params": {},
                "reasoning": "所有本輪議題已保存，剩餘 proposal 保留 backlog，且本輪已達 issue 上限，直接結束本輪。",
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
                    "reasoning": "議題已收斂，先保存會議紀錄。",
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

    # ========
    # Defines pending issue decision function for this module workflow.
    # ========
    @staticmethod
    def pending_issue_decision(runner: Any) -> Optional[Dict[str, Any]]:
        for issue in runner.current_meeting_issues():
            if not isinstance(issue, dict):
                continue
            issue_id = str(issue.get("id") or "").strip()
            if not issue_id:
                continue
            issue_state = runner.issue_states.get(issue_id, {})
            if issue_state.get("saved"):
                continue
            if not issue_state.get("discussed"):
                return {
                    "action": "start_issue",
                    "params": {"issue_id": issue_id},
                    "reasoning": "偵測到新增或未完成議題，先開始討論。",
                }
            if issue_state.get("needs_human"):
                return {
                    "action": "judge_issue",
                    "params": {"issue_id": issue_id},
                    "reasoning": "議題已判定需要人類裁決，進入裁決流程。",
                }
            if not issue_state.get("resolution"):
                return {
                    "action": "resolve_issue",
                    "params": {"issue_id": issue_id},
                    "reasoning": "議題已完成討論，先整理收斂結果。",
                }
            return {
                "action": "save_issue",
                "params": {"issue_id": issue_id},
                "reasoning": "議題已收斂，先保存會議紀錄。",
            }
        return None

    # ========
    # Defines default update draft function for this module workflow.
    # ========
    def default_update_draft(self, runner: Any) -> Optional[int]:
        if not stage_enabled(self.flow.config, "default_update_draft", True):
            return None
        artifact = runner.output_artifact if isinstance(runner.output_artifact, dict) else runner.artifact
        meta = artifact.setdefault("meta", {})
        flag = f"default_update_draft_round_{runner.round_num}"
        if meta.get(flag):
            value = meta.get("default_draft_v")
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

        if self.ensure_default_conflicts_resolved(runner, artifact):
            return None

        latest_version = self.flow.store.get_draft_version()
        previous_draft = self.flow.store.load_draft(latest_version) if latest_version >= 0 else ""
        next_version = max(0, latest_version + 1)
        draft_md = self.flow.analyst_agent.run_requirements_analyst(
            "update_draft",
            artifact=artifact,
            draft_version=next_version,
            previous_draft=previous_draft,
            round_num=runner.round_num,
            artifact_dir=getattr(self.flow.store, "artifact_dir", None),
        )
        self.flow.store.save_draft(draft_md, version=next_version)
        meta[flag] = True
        meta["default_draft_v"] = next_version
        if runner.artifact is not artifact:
            runner.artifact.setdefault("meta", {}).update(
                {
                    flag: True,
                    "default_draft_v": next_version,
                }
            )
        self.flow.store.save_artifact(artifact)
        self.flow.logger.info(
            "Default Update Draft：已生成 draft_v%s",
            next_version,
        )
        return next_version

    # ========
    # Defines unresolved conflict rows function for this module workflow.
    # ========
    @staticmethod
    def unresolved_conflict_rows(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
        return unresolved_conflict_report_rows(conflict_report_rows(artifact))

    # ========
    # Defines has pending conflict issue function for this module workflow.
    # ========
    @staticmethod
    def has_pending_conflict_issue(runner: Any) -> bool:
        for issue in runner.current_meeting_issues():
            if not isinstance(issue, dict):
                continue
            if str(issue.get("category") or "").strip() != "resolve_conflict":
                continue
            state = runner.issue_states.get(str(issue.get("id") or "").strip(), {})
            if not state.get("saved", False):
                return True
        return False

    # ========
    # Defines append conflict issue function for this module workflow.
    # ========
    def append_conflict_issue(
        self,
        runner: Any,
        artifact: Dict[str, Any],
        *,
        force_human_decision: bool = False,
    ) -> bool:
        candidates = [
            issue for issue in default_meeting_issues(
                self,
                artifact,
                round_num=runner.round_num,
            )
            if isinstance(issue, dict)
            and str(issue.get("category") or "").strip() == "resolve_conflict"
        ]

        current_issues = runner.current_meeting_issues()
        next_index = len(current_issues) + 1
        if candidates:
            issue = dict(candidates[0])
        else:
            unresolved = self.unresolved_conflict_rows(artifact)
            unresolved_ids = conflict_report_row_ids(unresolved)
            if not unresolved_ids:
                return False
            issue = {
                "title": "解決需求衝突",
                "category": "resolve_conflict",
                "description": "需求正式化後仍有未解需求衝突，需在預設會議中收斂或裁決。",
                "participants": ["user", "analyst"],
                "discussion_mode": "sequential",
                "discussion_rounds": 2,
                "target_stakeholders": [],
                "trace": {
                    "artifact_ids": unresolved_ids,
                    "proposal_ids": [f"I-R{runner.round_num}-mediator-conflict-loop"],
                },
                "proposed_by": "mediator",
                "expected_actions": {"analyst": ["discuss_conflict"]},
            }
        issue["id"] = f"T-{next_index}"
        issue["round"] = runner.round_num
        issue["auto_conflict_loop"] = True
        if force_human_decision:
            issue["force_human_decision"] = True
            issue["description"] = (
                str(issue.get("description") or "").strip()
                + "\n\n已達自動衝突解決上限，本議題直接進入人類裁決。"
            ).strip()

        other_rounds = [
            row for row in (artifact.get("meeting_issues", []) or [])
            if isinstance(row, dict)
            and int(row.get("round") or -1) != int(runner.round_num)
        ]
        round_issues = current_issues + [issue]
        artifact["meeting_issues"] = other_rounds + round_issues
        runner.artifact["meeting_issues"] = list(artifact["meeting_issues"])
        if runner.output_artifact is not None:
            runner.output_artifact["meeting_issues"] = list(artifact["meeting_issues"])
        runner.issue_states[issue["id"]] = {
            "discussed": False,
            "conversation": None,
            "resolution": None,
            "saved": False,
        }
        self.flow.store.save_artifact(artifact)
        runner.log_agenda(label="追加預設衝突", issues=[issue])
        return True

    # ========
    # Defines ensure default conflicts resolved function for this module workflow.
    # ========
    def ensure_default_conflicts_resolved(self, runner: Any, artifact: Dict[str, Any]) -> bool:
        self.refresh_conflicts(
            runner,
            artifact,
            log_prefix="Default Conflict Gate",
            block_on_unresolved=False,
        )
        unresolved = self.unresolved_conflict_rows(artifact)
        if not unresolved:
            return False
        if self.has_pending_conflict_issue(runner):
            return True

        meta = artifact.setdefault("meta", {})
        loop_key = f"default_conflict_loop_round_{runner.round_num}"
        try:
            attempts = int(meta.get(loop_key) or 0)
        except (TypeError, ValueError):
            attempts = 0
        if attempts < DEFAULT_CONFLICT_RESOLUTION_LIMIT:
            meta[loop_key] = attempts + 1
            self.flow.logger.info(
                "Default Conflict Gate：仍有 %s 筆未解決衝突，追加 resolve_conflict（%s/%s）",
                len(unresolved),
                attempts + 1,
                DEFAULT_CONFLICT_RESOLUTION_LIMIT,
            )
            return self.append_conflict_issue(runner, artifact)

        meta[f"default_conflict_human_round_{runner.round_num}"] = True
        self.flow.logger.info(
            "Default Conflict Gate：仍有 %s 筆未解決衝突，已達上限 %s，交由人類裁決",
            len(unresolved),
            DEFAULT_CONFLICT_RESOLUTION_LIMIT,
        )
        return self.append_conflict_issue(
            runner,
            artifact,
            force_human_decision=True,
        )

    # ========
    # Defines proposal artifact slices function for this module workflow.
    # ========
    @staticmethod
    def proposal_artifact_slices(
        artifact: Dict[str, Any],
        *,
        draft_version: int,
    ) -> Dict[str, Any]:
        if not isinstance(artifact, dict):
            return {"draft": {"version": draft_version}}

        def clean_id(value: Any) -> str:
            return str(value or "").strip()

        def first_ids(rows: List[Dict[str, Any]]) -> List[str]:
            ids: List[str] = []
            for row in rows:
                rid = clean_id(row.get("id") or row.get("issue_id"))
                if rid:
                    ids.append(rid)
            return list(dict.fromkeys(ids))

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

        conflict_report = conflict_report_rows(artifact)
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
        req_summaries: List[Dict[str, Any]] = []
        for row in req_rows:
            summary: Dict[str, Any] = {}
            for key in (
                "id",
                "type",
                "title",
                "description",
                "priority",
                "category",
                "metric",
                "validation",
                "source",
                "acceptance_criteria",
                "risks",
                "assumptions",
            ):
                value = row.get(key)
                if value not in (None, "", [], {}):
                    summary[key] = value
            if summary:
                req_summaries.append(summary)

        feedback_items: Dict[str, List[Dict[str, Any]]] = {}
        for section in ("findings", "constraints", "risks", "recommendations", "sources"):
            rows: List[Dict[str, Any]] = []
            for idx, row in enumerate(feedback.get(section) or [], 1):
                if not isinstance(row, dict):
                    continue
                item: Dict[str, Any] = {"id": clean_id(row.get("id") or f"{section}.{idx}")}
                for key in ("text", "title", "url", "related_requirement_ids", "source"):
                    value = row.get(key)
                    if value not in (None, "", [], {}):
                        item[key] = value
                rows.append(item)
            if rows:
                feedback_items[section] = rows

        models = [
            row for row in (artifact.get("system_models") or [])
            if isinstance(row, dict)
        ]
        model_summaries: List[Dict[str, Any]] = []
        for row in models:
            model_id = clean_id(row.get("id"))
            model_type = clean_id(row.get("type"))
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
            related_requirement_ids = row.get("related_requirement_ids")
            if related_requirement_ids:
                summary["related_requirement_ids"] = related_requirement_ids
            if summary:
                model_summaries.append(summary)
        model_types = sorted(
            {
                clean_id(row.get("type"))
                for row in models
                if clean_id(row.get("type"))
            }
        )

        return {
            "draft": {"version": draft_version},
            "stakeholders": list(dict.fromkeys(stakeholders)),
            "requirement_counts": req_counts,
            "REQ": req_summaries,
            "scope": artifact.get("scope", {}) if isinstance(artifact.get("scope"), dict) else {},
            "open_questions": {
                "count": len(open_questions),
                "ids": first_ids(open_questions),
                "items": [
                    {
                        "id": clean_id(row.get("id")),
                        "question": clean_id(row.get("question")),
                        "to": clean_id(row.get("to") or row.get("to_agent")),
                        "status": clean_id(row.get("status")),
                    }
                    for row in open_questions
                ],
            },
            "conflicts": {
                "unresolved_count": len(unresolved_conflicts),
                "ids": first_ids(unresolved_conflicts),
                "items": [
                    {
                        "id": clean_id(row.get("id")),
                        "title": clean_id(row.get("title")),
                        "description": clean_id(row.get("description")),
                        "status": clean_id(row.get("status")),
                    }
                    for row in unresolved_conflicts
                ],
            },
            "feedback": {
                **feedback_counts,
                "items": feedback_items,
            },
            "system_models": {
                "count": len(models),
                "types": model_types,
                "models": model_summaries,
            },
        }

    # ========
    # Defines general update draft function for this module workflow.
    # ========
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
        final_flag = f"general_update_draft_round_{round_num}"
        if meta.get(final_flag):
            return False
        if not state_summary.get("all_current_issues_saved"):
            return False
        if int(state_summary.get("backlog_count") or 0) != 0 and state_summary.get("can_add_issues"):
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

        latest_version = self.flow.store.get_draft_version()
        previous_draft = self.flow.store.load_draft(latest_version) if latest_version >= 0 else ""
        next_version = max(0, latest_version + 1)
        draft_md = self.flow.analyst_agent.run_requirements_analyst(
            "update_draft",
            artifact=artifact,
            draft_version=next_version,
            previous_draft=previous_draft,
            round_num=round_num,
            artifact_dir=getattr(self.flow.store, "artifact_dir", None),
        )
        self.flow.store.save_draft(draft_md, version=next_version)
        meta[final_flag] = True
        meta["general_draft_v"] = next_version
        if runner.artifact is not artifact:
            runner.artifact.setdefault("meta", {}).update(meta)
        self.flow.store.save_artifact(artifact)
        self.flow.logger.info(
            "General Update Draft：已生成 draft_v%s",
            next_version,
        )
        return True

    # ========
    # Defines refresh conflicts function for this module workflow.
    # ========
    def refresh_conflicts(
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
        result = self.flow.analyst_agent.analyze_conflicts(
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
        meta["conflict_refresh_round"] = runner.round_num
        meta["conflict_refresh_by"] = "default_conflict_gate"
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
                "%s：需求更新後仍有 %s 筆未解決衝突",
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

    # ========
    # Defines act round step function for this module workflow.
    # ========
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

    # ========
    # Defines run round opa loop function for this module workflow.
    # ========
    def run_round_opa_loop(self, runner: Any) -> None:
        run_mediator_round_opa_loop(self, runner)


    # ========
    # Defines recent issue discussions function for this module workflow.
    # ========
    def recent_issue_discussions(self, artifact, *, rounds=1):
        return recent_issue_discussions(artifact, rounds=rounds)

    # ========
    # Defines issue proposal function for this module workflow.
    # ========
    def issue_proposal(self, item, *, proposed_by, round_num, index):
        return issue_proposal(item, proposed_by=proposed_by, round_num=round_num, index=index)

    # ========
    # Defines collect issue proposals function for this module workflow.
    # ========
    def collect_issue_proposals(self, artifact, *, round_num):
        return collect_issue_proposals(self, artifact, round_num=round_num)

    # ========
    # Defines apply mediator updates function for this module workflow.
    # ========
    def apply_mediator_updates(self, artifact, updates):
        return apply_mediator_updates(artifact, updates)

    # ========
    # Defines run meeting loop function for this module workflow.
    # ========
    def run_meeting_loop(self, runner):
        run_mediator_meeting_loop(self, runner)


    # ========
    # Defines run elicitation function for this module workflow.
    # ========
    def run_elicitation(self, artifact, round_num):
        return self.run_round_pipeline_step(
            stage="requirement_elicitation",
            round_num=round_num,
            artifact=artifact,
            action_fn=run_elicitation,
            action_kwargs={
                "coordinator": self,
                "artifact": artifact,
                "round_num": round_num,
            },
        )

    # ========
    # Defines run conflict review function for this module workflow.
    # ========
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

    # ========
    # Defines run meeting round function for this module workflow.
    # ========
    def run_meeting_round(self, artifact, round_num):
        return run_meeting_round_block(self, artifact, round_num)
