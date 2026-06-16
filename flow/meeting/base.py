# Handles base logic for project flow orchestration and stage execution.
import re
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


POST_REQUIREMENT_CONFLICT_HUMAN_LIMIT = 2


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
            default_draft_decision = self.default_draft_decision(runner)
            if default_draft_decision:
                return default_draft_decision

            pending_decision = self.pending_issue_decision(runner)
            if pending_decision:
                return pending_decision

            general_decision = self.maybe_plan_general_expansion(
                runner,
                state_summary,
                human_decision_status,
            )
            if general_decision:
                return general_decision

        if runner is not None:
            if (
                stage_enabled(self.flow.config, "general_update_draft", True)
                and self.general_meeting_round_enabled(runner.round_num)
            ):
                general_draft_decision = self.general_draft_decision(
                    runner,
                    state_summary,
                    human_decision_status,
                )
                if general_draft_decision:
                    return general_draft_decision

        finish_decision = self.finish_round_decision(state_summary, human_decision_status)
        if finish_decision:
            return finish_decision

        lifecycle_decision = self.issue_lifecycle_decision(state_summary)
        if lifecycle_decision:
            return lifecycle_decision

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
    # Defines default draft decision function for this module workflow.
    # ========
    def default_draft_decision(self, runner: Any) -> Optional[Dict[str, Any]]:
        has_general_issues = any(
            isinstance(issue, dict) and not runner.is_default_issue(issue)
            for issue in runner.current_meeting_issues()
        )
        if has_general_issues:
            return None
        if not stage_enabled(self.flow.config, "default_update_draft", True):
            return None
        if not self.default_draft_ready(runner):
            return None
        return {
            "action": "update_default_draft",
            "params": {},
            "reasoning": "預設會議議題已保存，更新需求草稿。",
        }

    # ========
    # Defines log default draft transition function for this module workflow.
    # ========
    def log_default_draft_transition(self) -> None:
        if stage_enabled(self.flow.config, "general_formal_meeting", True):
            self.flow.logger.info("Default Formal Meeting：已更新 draft，一般正式會議將從 Round 2 開始")
        else:
            self.flow.logger.info("Default Formal Meeting：已更新 draft，general_formal_meeting disabled，略過一般議題提出")

    # ========
    # Defines can expand round issues function for this module workflow.
    # ========
    @staticmethod
    def can_expand_round_issues(state_summary: Dict[str, Any]) -> bool:
        current_issues_saved = bool(state_summary.get("all_current_issues_saved"))
        current_issues_count = int(state_summary.get("issues_count") or 0)
        return current_issues_count == 0 or current_issues_saved

    # ========
    # Defines maybe plan general expansion function for this module workflow.
    # ========
    def maybe_plan_general_expansion(
        self,
        runner: Any,
        state_summary: Dict[str, Any],
        human_decision_status: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if not self.general_meeting_round_enabled(runner.round_num):
            return None
        if not self.can_expand_round_issues(state_summary):
            return None
        if human_decision_status.get("has_pending_human_decisions"):
            return None

        if self.should_run_general_conflict_gate(runner):
            return {
                "action": "run_general_conflict_gate",
                "params": {},
                "reasoning": "一般正式會議開始前執行衝突 gate。",
            }

        if runner.issue_pool and state_summary.get("can_add_issues"):
            return {
                "action": "add_issues",
                "params": {},
                "reasoning": "預設會議已完成並更新 draft，接著加入一般正式會議議題。",
            }
        return None

    # ========
    # Defines should run general conflict gate function for this module workflow.
    # ========
    def should_run_general_conflict_gate(self, runner: Any) -> bool:
        if not stage_enabled(self.flow.config, "general_formal_meeting", True):
            return False
        artifact = runner.output_artifact if isinstance(runner.output_artifact, dict) else runner.artifact
        meta = artifact.setdefault("meta", {})
        flag = f"general_conflict_gate_round_{runner.round_num}"
        if meta.get(flag):
            return False
        if self.has_pending_conflict_issue(runner):
            return True
        if self.unresolved_conflict_rows(artifact):
            return True
        return True

    # ========
    # Defines general draft decision function for this module workflow.
    # ========
    def general_draft_decision(
        self,
        runner: Any,
        state_summary: Dict[str, Any],
        human_decision_status: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if not self.general_draft_ready(runner, state_summary, human_decision_status):
            return None
        return {
            "action": "update_general_draft",
            "params": {},
            "reasoning": "一般正式會議議題已保存，更新需求草稿。",
        }

    # ========
    # Defines finish round decision function for this module workflow.
    # ========
    @staticmethod
    def finish_round_decision(
        state_summary: Dict[str, Any],
        human_decision_status: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if human_decision_status.get("has_pending_human_decisions"):
            return None
        issues_count = int(state_summary.get("issues_count") or 0)
        backlog_count = int(state_summary.get("backlog_count") or 0)
        all_saved = bool(state_summary.get("all_current_issues_saved"))
        can_add_issues = bool(state_summary.get("can_add_issues"))

        if issues_count == 0 and backlog_count == 0:
            return {
                "action": "finish_round",
                "params": {},
                "reasoning": "本輪沒有可產生正式會議議題的 proposal，且沒有待處理 human_decision_queue，直接結束本輪。",
            }
        if all_saved and backlog_count == 0:
            return {
                "action": "finish_round",
                "params": {},
                "reasoning": "所有議題已保存，且沒有剩餘 proposal 或待處理 human_decision_queue，直接結束本輪。",
            }
        if all_saved and backlog_count > 0 and not can_add_issues:
            return {
                "action": "finish_round",
                "params": {},
                "reasoning": "所有本輪議題已保存，剩餘 proposal 保留 backlog，且本輪已達 issue 上限，直接結束本輪。",
            }
        return None

    # ========
    # Defines issue lifecycle decision function for this module workflow.
    # ========
    @staticmethod
    def issue_lifecycle_decision(state_summary: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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
        return None

    # ========
    # Defines default draft ready function for this module workflow.
    # ========
    def default_draft_ready(self, runner: Any) -> bool:
        artifact = runner.output_artifact if isinstance(runner.output_artifact, dict) else runner.artifact
        meta = artifact.setdefault("meta", {})
        flag = f"default_update_draft_round_{runner.round_num}"
        if meta.get(flag):
            return False
        issues = runner.current_meeting_issues()
        default_issues = [
            issue for issue in issues
            if isinstance(issue, dict) and runner.is_default_issue(issue)
        ]
        if not default_issues:
            return False
        all_saved = all(
            runner.issue_states.get(issue.get("id"), {}).get("saved", False)
            for issue in default_issues
            if isinstance(issue, dict)
        )
        if not all_saved:
            return False
        if runner.issue_pool:
            return False
        return True

    # ========
    # Defines general draft ready function for this module workflow.
    # ========
    def general_draft_ready(
        self,
        runner: Any,
        state_summary: Dict[str, Any],
        human_decision_status: Dict[str, Any],
    ) -> bool:
        artifact = runner.output_artifact if isinstance(runner.output_artifact, dict) else runner.artifact
        meta = artifact.setdefault("meta", {})
        final_flag = f"general_update_draft_round_{runner.round_num}"
        if meta.get(final_flag):
            return False
        if not state_summary.get("all_current_issues_saved"):
            return False
        if int(state_summary.get("backlog_count") or 0) != 0 and state_summary.get("can_add_issues"):
            return False
        if human_decision_status.get("has_pending_human_decisions"):
            return False
        return any(
            isinstance(issue, dict) and not runner.is_default_issue(issue)
            for issue in runner.current_meeting_issues()
        )

    # ========
    # Defines general conflict gate function for this module workflow.
    # ========
    def general_conflict_gate(self, runner: Any) -> bool:
        if not stage_enabled(self.flow.config, "general_formal_meeting", True):
            return False
        artifact = runner.output_artifact if isinstance(runner.output_artifact, dict) else runner.artifact
        meta = artifact.setdefault("meta", {})
        flag = f"general_conflict_gate_round_{runner.round_num}"
        if meta.get(flag):
            return False
        if self.has_pending_conflict_issue(runner):
            meta[flag] = True
            self.flow.store.save_artifact(artifact)
            return True

        unresolved = self.unresolved_conflict_rows(artifact)
        if unresolved:
            meta[flag] = True
            self.flow.logger.info(
                "General Conflict Gate：一般會議前發現 %s 筆既有未解衝突，優先加入 resolve_conflict",
                len(unresolved),
            )
            appended = self.append_conflict_issue(runner, artifact)
            self.flow.store.save_artifact(artifact)
            return appended

        meta["requirements_changed"] = True
        meta["requirements_changed_by"] = "general_conflict_gate"
        meta["requirements_changed_reason"] = "pre_general_meeting_conflict_refresh"
        appended = self.ensure_conflicts_resolved(
            runner,
            artifact,
            log_prefix="General Conflict Gate",
        )
        meta[flag] = True
        if runner.artifact is not artifact:
            runner.artifact.setdefault("meta", {}).update(meta)
        if runner.output_artifact is not None and runner.output_artifact is not artifact:
            runner.output_artifact.setdefault("meta", {}).update(meta)
        self.flow.store.save_artifact(artifact)
        return appended

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
        self.flow.logger.step_completed(
            "draft",
            "draft.update_draft",
            f"Draft v{next_version}",
            agent="analyst",
            output_path=f"artifact/drafts/draft_v{next_version}.md",
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
                "discussion_rounds": 1,
                "target_stakeholders": [],
                "trace": {
                    "artifact_ids": unresolved_ids,
                    "proposal_ids": [f"R{runner.round_num}-I{next_index}"],
                },
                "proposed_by": "mediator",
                "expected_actions": {"analyst": ["discuss_conflict"]},
            }
        nums = []
        for row in current_issues:
            issue_id = str((row or {}).get("id") or "").strip()
            m = re.fullmatch(r"M-(\d+)", issue_id)
            if m:
                nums.append(int(m.group(1)))
        issue["id"] = f"M-{(max(nums) if nums else 0) + 1}"
        issue["round"] = runner.round_num
        issue["auto_conflict_loop"] = True
        if force_human_decision:
            issue["force_human_decision"] = True
            issue["description"] = (
                str(issue.get("description") or "").strip()
                + "\n\n已達自動衝突解決上限，本議題直接進入人類裁決。"
            ).strip()

        rows = [
            row for row in (artifact.get("meeting_issues", []) or [])
            if isinstance(row, dict)
        ]
        issue_id = str(issue.get("id") or "").strip()
        existing_idx = next(
            (
                idx
                for idx, row in enumerate(rows)
                if str(row.get("id") or "").strip() == issue_id
            ),
            None,
        )
        if existing_idx is None:
            rows.append(issue)
        else:
            rows[existing_idx] = {**rows[existing_idx], **issue}
        artifact["meeting_issues"] = rows
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
        return self.ensure_conflicts_resolved(
            runner,
            artifact,
            log_prefix="Default Conflict Gate",
        )

    # ========
    # Defines ensure conflicts resolved function for this module workflow.
    # ========
    def ensure_conflicts_resolved(
        self,
        runner: Any,
        artifact: Dict[str, Any],
        *,
        log_prefix: str,
    ) -> bool:
        self.refresh_conflicts(
            runner,
            artifact,
            log_prefix=log_prefix,
            block_on_unresolved=False,
        )
        unresolved = self.unresolved_conflict_rows(artifact)
        if not unresolved:
            return False
        if self.has_pending_conflict_issue(runner):
            return True

        meta = artifact.setdefault("meta", {})
        try:
            post_requirement_streak = int(meta.get("post_requirement_conflict_streak") or 0)
        except (TypeError, ValueError):
            post_requirement_streak = 0
        if post_requirement_streak >= POST_REQUIREMENT_CONFLICT_HUMAN_LIMIT:
            meta[f"default_conflict_human_round_{runner.round_num}"] = True
            self.flow.logger.info(
                "%s：需求更新後連續 %s 次仍有 %s 筆未解決衝突，交由人類裁決",
                log_prefix,
                post_requirement_streak,
                len(unresolved),
            )
            return self.append_conflict_issue(
                runner,
                artifact,
                force_human_decision=True,
            )
        self.flow.logger.info(
            "%s：仍有 %s 筆未解決衝突，追加 resolve_conflict（需求更新後連續 %s/%s）",
            log_prefix,
            len(unresolved),
            post_requirement_streak,
            POST_REQUIREMENT_CONFLICT_HUMAN_LIMIT,
        )
        return self.append_conflict_issue(runner, artifact)

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
                        "to": clean_id(row.get("to")),
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

        self.review_stale_models(runner, artifact, round_num=round_num)

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
        self.flow.logger.step_completed(
            "draft",
            "draft.update_draft",
            f"Draft v{next_version}",
            agent="analyst",
            output_path=f"artifact/drafts/draft_v{next_version}.md",
        )
        return True

    # ========
    # Defines review stale models function for this module workflow.
    # ========
    def review_stale_models(
        self,
        runner: Any,
        artifact: Dict[str, Any],
        *,
        round_num: int,
    ) -> bool:
        if not stage_enabled(self.flow.config, "system_model"):
            return False
        meta = artifact.setdefault("meta", {})
        if not bool(meta.get("models_maybe_stale")):
            return False
        models = [
            row for row in (artifact.get("system_models") or [])
            if isinstance(row, dict)
        ]
        if not models:
            meta["models_maybe_stale"] = False
            meta["models_reviewed_after_requirement_change"] = True
            meta["models_review_note"] = "no_existing_models"
            self.flow.store.save_artifact(artifact)
            return False

        review_issue = {
            "id": f"MODEL-REVIEW-R{round_num}",
            "title": "系統模型同步檢查",
            "category": "align_model",
            "description": "正式會議後需求已更新，請判斷既有系統模型是否需要更新；若不需要更新，直接結束模型流程。",
            "trace": {
                "artifact_ids": [
                    str(row.get("id") or "").strip()
                    for row in models
                    if str(row.get("id") or "").strip()
                ],
                "proposal_ids": [],
            },
        }
        self.flow.modeler_agent.run_model_loop(
            artifact,
            recent_discussions=runner.recent_discussions(limit=5) if hasattr(runner, "recent_discussions") else [],
            issue=review_issue,
            modeling_phase="post_requirement_formalization",
        )
        self.flow.store.save_plantuml_files(artifact.get("system_models", []))
        meta["models_maybe_stale"] = False
        meta["models_reviewed_after_requirement_change"] = True
        meta["models_reviewed_round"] = round_num
        meta.pop("models_stale_reason", None)
        if runner.artifact is not artifact:
            runner.artifact.setdefault("meta", {}).update(meta)
            runner.artifact["system_models"] = artifact.get("system_models", [])
        if runner.output_artifact is not None:
            runner.output_artifact["system_models"] = artifact.get("system_models", [])
        self.flow.store.save_artifact(artifact)
        self.flow.logger.step_completed(
            "system_model",
            "system_model.review_models",
            "系統模型同步檢查",
            agent="modeler",
            output_path="artifact/system_models.json",
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
        runner.update_conflict_report(fake_record)
        meta["requirements_changed"] = False
        meta["conflict_refresh_round"] = runner.round_num
        meta["conflict_refresh_by"] = "default_conflict_gate"
        meta.pop("requirements_changed_by", None)
        meta.pop("requirements_changed_reason", None)
        latest_conflict_report = (
            runner.artifact.get("conflict_report")
            if isinstance(runner.artifact.get("conflict_report"), list)
            else None
        )
        if latest_conflict_report is not None:
            artifact["conflict_report"] = [dict(row) for row in latest_conflict_report if isinstance(row, dict)]
        latest_conflict_state = (
            runner.artifact.get("conflict")
            if isinstance(runner.artifact.get("conflict"), dict)
            else None
        )
        if latest_conflict_state is not None:
            artifact["conflict"] = dict(latest_conflict_state)
        if runner.artifact is not artifact:
            runner.artifact.setdefault("meta", {}).update(meta)
            if "conflict_report" in artifact:
                runner.artifact["conflict_report"] = [dict(row) for row in artifact["conflict_report"]]
            if "conflict" in artifact:
                runner.artifact["conflict"] = dict(artifact["conflict"])
        if runner.output_artifact is not None:
            runner.output_artifact.setdefault("meta", {}).update(meta)
            if "conflict_report" in artifact:
                runner.output_artifact["conflict_report"] = [dict(row) for row in artifact["conflict_report"]]
            if "conflict" in artifact:
                runner.output_artifact["conflict"] = dict(artifact["conflict"])

        unresolved_count = len(self.unresolved_conflict_rows(artifact))

        if unresolved_count:
            try:
                streak = int(meta.get("post_requirement_conflict_streak") or 0)
            except (TypeError, ValueError):
                streak = 0
            meta["post_requirement_conflict_streak"] = streak + 1
            self.flow.store.save_artifact(artifact)
            if block_on_unresolved:
                self.flow.logger.info(
                    "%s：需求更新後連續 %s 次仍有 %s 筆未解決衝突；暫停更新 draft，需先完成需求衝突解決",
                    log_prefix,
                    streak + 1,
                    unresolved_count,
                )
                return True
            self.flow.logger.info(
                "%s：需求更新後連續 %s 次仍有 %s 筆未解決衝突",
                log_prefix,
                streak + 1,
                unresolved_count,
            )
            return False
        meta["post_requirement_conflict_streak"] = 0
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
        action = decision.get("action", "finish_round")
        if action == "update_default_draft":
            draft_version = self.default_update_draft(runner)
            result = {
                "action": action,
                "result": {"draft_version": draft_version},
                "error": None,
                "status": "draft_updated" if draft_version is not None else "skipped",
            }
            if draft_version is not None:
                self.log_default_draft_transition()
        elif action == "run_general_conflict_gate":
            appended = self.general_conflict_gate(runner)
            pending_conflict = self.pending_issue_decision(runner)
            result = {
                "action": action,
                "result": {
                    "appended": appended,
                    "next_action": pending_conflict,
                },
                "error": None,
                "status": "conflict_gate_done",
            }
        elif action == "update_general_draft":
            updated = self.general_update_draft(
                runner,
                observation.get("state_summary") or {},
                (observation.get("state_summary") or {}).get("human_decision_status") or {},
            )
            result = {
                "action": action,
                "result": {"updated": updated},
                "error": None,
                "status": "draft_updated" if updated else "skipped",
            }
        else:
            result = runner.run(action, decision.get("params") or {})
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
