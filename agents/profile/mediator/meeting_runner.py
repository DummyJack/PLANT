# Meeting runner: executes formal meeting issue actions and coordinates round loops.
import re
import json
from typing import Dict, List, Any, Optional

from .agent import MediatorAgent
from .validation import (
    MEETING_ACTIONS,
    ISSUE_CATEGORY_LABEL,
    meeting_issue,
    normalize_trace,
    trace_artifact_ids,
    trace_proposal_ids,
)
from utils import Collect


def issue_trace(issue: Optional[Dict[str, Any]]) -> Dict[str, List[str]]:
    return normalize_trace((issue or {}).get("trace"))


def issue_artifact_ids(issue: Optional[Dict[str, Any]]) -> List[str]:
    return trace_artifact_ids(issue)


def issue_proposal_ids(issue: Optional[Dict[str, Any]]) -> List[str]:
    return trace_proposal_ids(issue)


def conflict_report_resolution_ids(
    artifact: Dict[str, Any],
    issue: Optional[Dict[str, Any]],
    resolution: Dict[str, Any],
) -> List[str]:
    ids = [
        str(value).strip()
        for value in (resolution.get("affected_conflict_ids") or [])
        if str(value).strip()
    ]
    if ids:
        return list(dict.fromkeys(ids))
    if str((issue or {}).get("category") or "").strip() != "resolve_conflict":
        return []
    conflict = artifact.get("conflict") if isinstance(artifact.get("conflict"), dict) else {}
    rows = conflict.get("report") if isinstance(conflict.get("report"), list) else []
    out: List[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "").strip().lower()
        if status in {"agreed", "human_decision"}:
            continue
        row_id = str(row.get("id") or "").strip()
        if row_id:
            out.append(row_id)
    return list(dict.fromkeys(out))


def conflict_report_requirement_ids(row: Dict[str, Any]) -> List[str]:
    ids: List[str] = []
    for req in row.get("requirements") or []:
        if not isinstance(req, dict):
            continue
        req_id = str(req.get("id") or "").strip()
        if req_id:
            ids.append(req_id)
    return list(dict.fromkeys(ids))


def adopted_resolution_option_text(
    conflict_row: Dict[str, Any],
    decision_text: str,
) -> str:
    """If a conflict resolution adopts an existing option, render that option explicitly."""
    if not isinstance(conflict_row, dict) or not str(decision_text or "").strip():
        return ""
    options = conflict_row.get("resolution_options")
    if not isinstance(options, list) or not options:
        return ""

    def compact(value: Any) -> str:
        return re.sub(r"[\s:：,，。.\-_/]+", "", str(value or "").strip().lower())

    compact_decision = compact(decision_text)
    if not compact_decision:
        return ""

    matched: Optional[Dict[str, Any]] = None
    for option in options:
        if not isinstance(option, dict):
            continue
        option_id = str(option.get("option") or "").strip()
        strategy = str(option.get("strategy") or "").strip()
        labels = [
            option_id,
            f"選項{option_id}" if option_id else "",
            f"方案{option_id}" if option_id else "",
            strategy,
            f"採用選項{option_id}" if option_id else "",
            f"採用方案{option_id}" if option_id else "",
        ]
        if any(compact(label) and compact(label) in compact_decision for label in labels):
            matched = option
            break

    if matched is None:
        recommended = str(conflict_row.get("recommended_resolution") or "").strip()
        if recommended and compact(recommended) and compact(recommended) in compact_decision:
            matched = next(
                (
                    option
                    for option in options
                    if isinstance(option, dict) and bool(option.get("recommendation"))
                ),
                None,
            )

    if matched is None:
        return ""

    option_id = str(matched.get("option") or "").strip()
    description = str(matched.get("description") or "").strip()
    if not description:
        return ""
    label = f"選項 {option_id}" if option_id else "既有選項"
    return f"採用{label}，{description}"


def ingest_round_resolution_effects(
    coordinator: Any,
    artifact: Dict[str, Any],
    meeting_records: List[Dict[str, Any]],
    round_num: int,
) -> None:
    resolution_effects = artifact.get("issue_resolution_effects", []) or []
    for item in meeting_records:
        if not isinstance(item, dict):
            continue
        issue_id_value = str(item.get("issue_id") or "").strip()
        resolution = item.get("resolution", {}) if isinstance(item.get("resolution"), dict) else {}
        affected_conflict_ids = resolution.get("affected_conflict_ids", []) or []
        source_ids = list(dict.fromkeys([
            str(sid).strip()
            for sid in list(affected_conflict_ids) + list(resolution.get("affected_requirement_ids", []) or [])
            if str(sid).strip()
        ]))
        decision_id = str(resolution.get("decision_id") or "").strip()
        if resolution.get("status") == "human_decision" and affected_conflict_ids and decision_id:
            from flow.meeting.conflict_review import mark_conflicts_resolved_by_ids
            mark_conflicts_resolved_by_ids(
                artifact, affected_conflict_ids, decision_id=decision_id,
            )
        affected_requirement_ids = [
            str(rid).strip()
            for rid in (resolution.get("affected_requirement_ids", []) or [])
            if str(rid).strip()
        ]
        needs_human = bool(resolution.get("needs_human"))
        effect_row = {
            "issue_id": issue_id_value,
            "round": round_num,
            "status": resolution.get("status"),
            "needs_human": needs_human,
        }
        if affected_requirement_ids:
            effect_row["affected_requirement_ids"] = affected_requirement_ids
        resolution_effects.append(effect_row)
        if needs_human:
            existing_human_ids = {
                str(row.get("issue_id") or "").strip()
                for row in (artifact.get("human_decision_queue", []) or [])
                if isinstance(row, dict)
            }
            issue_id = f"HQ-R{round_num}-{issue_id_value or len(existing_human_ids) + 1}"
            if issue_id not in existing_human_ids:
                queue_row = {
                    "issue_id": issue_id,
                    "round": round_num,
                    "title": resolution.get("summary") or issue_id_value,
                    "description": str(resolution.get("summary") or "").strip(),
                    "category": "tradeoff",
                    "trace": {"artifact_ids": source_ids, "proposal_ids": [issue_id_value] if issue_id_value else []},
                    "status": "pending",
                    "needs_human": True,
                    "meeting_type": "human_decision",
                    "options": resolution.get("options", []) or [],
                    "recommendation": resolution.get("recommendation", {}) or {},
                    "unresolved_points": resolution.get("unresolved_points", []) or [],
                }
                if affected_requirement_ids:
                    queue_row["affected_requirement_ids"] = affected_requirement_ids
                artifact.setdefault("human_decision_queue", []).append(queue_row)
            continue
    artifact["issue_resolution_effects"] = resolution_effects


def post_issue_processing(
    coordinator: Any,
    artifact: Dict[str, Any],
    issue_discussion: Dict[str, Any],
    *,
    round_num: int,
) -> None:
    ingest_round_resolution_effects(
        coordinator, artifact, [issue_discussion], round_num=round_num,
    )
    coordinator.flow.store.save_artifact(artifact)


def human_decision_issue_record(
    coordinator: Any,
    row: Dict[str, Any],
    *,
    item_prefix: str,
    index: int,
) -> Dict[str, Any]:
    normalized = meeting_issue(
        {
            "id": f"{item_prefix}-{index}",
            "title": str(row.get("title") or "").strip(),
            "description": "",
            "category": row.get("category"),
            "participants": row.get("participants", []),
            "discussion_mode": row.get("discussion_mode"),
            "trace": normalize_trace(row.get("trace")),
        },
        allowed_categories=list(ISSUE_CATEGORY_LABEL.keys()),
        registered_agents=list(coordinator.flow.registry.get_names()) if coordinator.flow.registry else ["analyst", "expert", "modeler", "user"],
        index=index,
    )
    if not normalized:
        raise ValueError(f"human decision issue 不合法: {item_prefix}-{index}")
    return normalized


def execute_human_decision_queue(
    coordinator: Any,
    artifact: Dict[str, Any],
    runner: Any,
    *,
    round_num: int,
) -> None:
    items = artifact.get("human_decision_queue", []) or []
    if not items:
        return
    for idx, row in enumerate(items, 1):
        if not isinstance(row, dict):
            continue
        issue = human_decision_issue_record(
            coordinator, row, item_prefix="HQ", index=idx,
        )
        options = {
            "best_options": [],
            "compromise": {
                "id": 1,
                "title": issue.get("title", ""),
                "description": issue.get("description", ""),
                "rationale": row.get("reason", ""),
            },
        }
        if row.get("options"):
            best_options = []
            for idx_opt, opt in enumerate(row.get("options") or [], start=1):
                if not isinstance(opt, dict):
                    continue
                best_options.append(
                    {
                        "id": idx_opt,
                        "title": opt.get("summary") or opt.get("title") or "",
                        "description": opt.get("summary") or opt.get("description") or "",
                        "source": "judgment_options",
                    }
                )
            options = {"best_options": best_options, "compromise": {}}
        resolution_raw = Collect.human_decision_on_issue(issue, options)
        decision_text = str(resolution_raw.get("decision", "")).strip()
        decision_id = f"DEC-HQ-{round_num}-{idx}" if decision_text else ""
        resolution = coordinator.flow.mediator_agent.build_issue_result(
            status="human_decision" if decision_text else "",
            summary=decision_text or "此議題已送人工裁決，但暫未定案。",
            decision=decision_text,
            mediator_compromise={},
            agreed_points=[decision_text] if decision_text else [],
            unresolved_points=[] if decision_text else ["人類選擇暫不裁決。"],
            new_open_questions=[],
            affected_conflict_ids=[
                sid for sid in (issue_artifact_ids(issue))
                if isinstance(sid, str) and sid.startswith(("CR-", "PAIR-", "MULTIPLE-"))
            ],
            needs_human=True,
        )
        if decision_id:
            resolution["decision_id"] = decision_id
        resolution["human_choice"] = {
            "chosen_option_id": resolution_raw.get("chosen_option_id", ""),
            "chosen_option_title": resolution_raw.get("chosen_option_title", ""),
            "chosen_options": resolution_raw.get("chosen_options", []),
        }
        runner.meeting_records.append(
            {"issue_id": issue.get("id"), "resolution": resolution}
        )
        if decision_text:
            from flow.meeting.conflict_review import mark_conflicts_resolved_by_ids
            mark_conflicts_resolved_by_ids(
                artifact, resolution.get("affected_conflict_ids", []), decision_id=decision_id,
            )
            row["status"] = "decided"
        else:
            row["status"] = "deferred"
        row["human_decision_processed_round"] = round_num


def run_human_decision_queue(
    coordinator: Any,
    artifact: Dict[str, Any],
    runner: Any,
    *,
    round_num: int,
    drain_all: bool = False,
) -> None:
    keys = ("human_decision_queue",)
    max_passes = 50 if drain_all else 1
    prev_after = -1
    for pass_idx in range(max_passes):
        total_before = sum(len(artifact.get(k) or []) for k in keys)
        if drain_all and total_before == 0:
            break
        execute_human_decision_queue(coordinator, artifact, runner, round_num=round_num)
        artifact["human_decision_queue"] = [
            row for row in (artifact.get("human_decision_queue", []) or [])
            if isinstance(row, dict) and row.get("status") == "deferred"
        ]
        total_after = sum(len(artifact.get(k) or []) for k in keys)
        if not drain_all:
            break
        if total_after == 0:
            coordinator.flow.logger.info("最後一輪：human_decision_queue 已清空（第 %s 輪執行）", pass_idx + 1)
            break
        if pass_idx > 0 and total_after == prev_after:
            coordinator.flow.logger.warning("最後一輪：human_decision_queue 無進度，停止重試（剩餘 %s 筆）", total_after)
            break
        prev_after = total_after


def run_round_opa_loop(coordinator: Any, runner: Any) -> None:
    last_action_result: Optional[Dict[str, Any]] = None
    while True:
        observation = coordinator.observe_round_state(
            runner=runner,
            last_action_result=last_action_result,
        )
        decision = coordinator.plan_round_step(observation=observation)
        action = decision.get("action", "finish_round")
        coordinator.flow.logger.debug(
            "Formal meeting action: %s reason=%s",
            action,
            decision.get("reasoning", ""),
        )
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
            latest = runner.get_meeting_records()
            if latest:
                post_issue_processing(
                    coordinator,
                    runner.artifact,
                    latest[-1],
                    round_num=runner.round_num,
                )
        last_action_result = result


def run_meeting_loop(coordinator: Any, runner: Any) -> None:
    obs = runner.run("plan_issues", None)
    if obs.get("error"):
        raise RuntimeError(f"issue 生成失敗: {obs['error']}")
    drain = coordinator.is_last_meeting_round(runner.artifact, runner.round_num)

    run_human_decision_queue(
        coordinator,
        runner.artifact,
        runner,
        round_num=runner.round_num,
        drain_all=drain,
    )
    run_round_opa_loop(coordinator, runner)


class MeetingRunner:
    """執行正式會議議題動作，維護本輪 issues、issue_states、meeting_records、open_questions。"""

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
        output_artifact: Optional[Dict[str, Any]] = None,
    ):
        self.mediator = mediator_agent
        self.registry = registry
        self.artifact = artifact
        self.round_num = round_num
        self.config = config
        self.store = store
        self.collect = collect_module
        self.logger = logger
        self.output_artifact = output_artifact
        self.issue_pool = list(issue_pool or [])

        self.issue_states: Dict[str, Dict] = {}
        self.meeting_records: List[Dict] = []
        self.open_questions: List[Dict] = []
        self.issue_idx = 0

    def log_agenda(
        self,
        *,
        label: str,
        issues: List[Dict[str, Any]],
        backlog_count: Optional[int] = None,
    ) -> None:
        backlog_text = "" if backlog_count is None else f"，backlog {backlog_count} 筆"
        self.logger.info("正式會議議程：%s %s 筆%s", label, len(issues), backlog_text)
        for issue in issues:
            participants = "、".join(issue.get("participants", []) or []) or "未指定"
            self.logger.info(
                "  %s｜%s｜%s｜%s，%s 輪｜%s",
                issue.get("id", ""),
                issue.get("title", ""),
                issue.get("category", ""),
                issue.get("discussion_mode", ""),
                issue.get("discussion_rounds", 1),
                participants,
            )

    def log_discussion_start(self, issue: Dict[str, Any]) -> None:
        participants = "、".join(issue.get("participants", []) or []) or "未指定"
        self.logger.info(
            "[%s] 開始：%s（%s，%s，預計 %s 輪；參與：%s）",
            issue.get("id", ""),
            issue.get("title", ""),
            issue.get("category", ""),
            issue.get("discussion_mode", "sequential"),
            issue.get("discussion_rounds", 1),
            participants,
        )

    def log_discussion_done(self, issue_id: str, result: Dict[str, Any]) -> None:
        self.logger.info(
            "  討論完成：%s/%s 輪，%s 則發言，%s 個 open question",
            result.get("actual_rounds", ""),
            result.get("round_limit", ""),
            result.get("conversation_count", ""),
            result.get("oq_count", ""),
        )

    def log_resolution_done(self, issue_id: str, resolution: Dict[str, Any]) -> None:
        status = str(resolution.get("status") or "").strip() or "unknown"
        if resolution.get("needs_human"):
            self.logger.info("  收斂結果：需要人類裁決｜%s", resolution.get("summary", ""))
        else:
            self.logger.info("  收斂結果：%s｜%s", status, resolution.get("summary", ""))

    def log_human_judgment_done(self, issue_id: str, decision_text: str) -> None:
        self.logger.info("  人類裁決：%s", decision_text or "已完成")

    def log_issue_saved(self, issue_id: str, save_result: Dict[str, Any]) -> None:
        self.logger.info("  已保存：%s", save_result.get("filename") or issue_id)

    def issue_open_questions(self, issue_id: str) -> List[Dict]:
        return [q for q in self.open_questions if q.get("issue_id") == issue_id]

    @staticmethod
    def enrich_resolution_changes(resolution: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(resolution, dict):
            return {}
        if not resolution.get("requirement_changes"):
            requirement_changes = []
            for req_id in resolution.get("affected_requirement_ids") or []:
                req_id = str(req_id or "").strip()
                if req_id:
                    requirement_changes.append({"id": req_id, "change": "confirmed_or_updated"})
            for row in resolution.get("url_updates") or []:
                if not isinstance(row, dict):
                    continue
                target = str(row.get("id") or row.get("source_id") or "").strip()
                action = str(row.get("action") or "").strip()
                if target and action:
                    requirement_changes.append({"id": target, "change": action})
            if requirement_changes:
                resolution["requirement_changes"] = requirement_changes
        if not resolution.get("model_changes"):
            model_updates = []
            artifact_updates = resolution.get("artifact_updates") if isinstance(resolution.get("artifact_updates"), dict) else {}
            model_update = artifact_updates.get("system_models") if isinstance(artifact_updates, dict) else None
            if isinstance(model_update, dict) and model_update:
                model_updates.append(model_update)
            elif isinstance(model_update, list):
                model_updates.extend(row for row in model_update if isinstance(row, dict))
            if model_updates:
                resolution["model_changes"] = model_updates
        if not resolution.get("open_questions") and resolution.get("new_open_questions"):
            resolution["open_questions"] = resolution.get("new_open_questions") or []
        if not resolution.get("follow_up_actions"):
            follow_ups = []
            if resolution.get("new_open_questions") or resolution.get("unresolved_points"):
                follow_ups.append("track_open_questions")
            if resolution.get("affected_requirement_ids") or resolution.get("url_updates"):
                follow_ups.append("general_update_draft")
            if resolution.get("model_changes"):
                follow_ups.append("sync_system_models")
            if follow_ups:
                resolution["follow_up_actions"] = follow_ups
        return resolution

    def current_meeting_issues(self) -> List[Dict[str, Any]]:
        rows = []
        source = self.artifact.get("meeting_issues", []) or []
        if not isinstance(source, list):
            return rows
        for row in source:
            if not isinstance(row, dict):
                continue
            row_round = row.get("round")
            if row_round is not None and int(row_round or -1) != int(self.round_num):
                continue
            normalized = dict(row)
            normalized.setdefault("round", self.round_num)
            rows.append(normalized)
        return rows

    def load_meeting_issues(self) -> None:
        rows = self.current_meeting_issues()
        for issue in rows:
            issue_id = issue.get("id")
            if not issue_id or issue_id in self.issue_states:
                continue
            self.issue_states[issue_id] = {
                "discussed": False,
                "conversation": None,
                "resolution": None,
                "saved": False,
            }

    @staticmethod
    def is_default_issue(issue: Dict[str, Any]) -> bool:
        return str(issue.get("proposed_by") or "").strip() == "mediator"

    def load_agenda_issue(self, issue_id: Optional[str]) -> Optional[Dict[str, Any]]:
        return self.get_issue(issue_id)

    def prepare_discussion(self, issue: Dict[str, Any]) -> Optional[str]:
        issue_id = issue.get("id")
        state = self.issue_states.get(issue_id, {})
        if state.get("discussed"):
            return (
                f"{issue_id} 已討論過，不可重複討論。"
                f"請使用 save_issue 儲存後繼續下一個議題。"
            )
        meeting_record = self.ensure_meeting_record(issue)
        meeting_id = str(meeting_record.get("meeting_id") or "").strip()
        if meeting_id:
            issue["meeting_id"] = meeting_id
        issue["issue_context"] = self.issue_context_summary(issue)
        return None

    def run_discussion(self, issue: Dict[str, Any]) -> Dict[str, Any]:
        issue_id = issue.get("id")
        mode = issue.get("discussion_mode", "sequential")
        try:
            planned_rounds = int(issue.get("discussion_rounds") or 1)
        except (TypeError, ValueError):
            planned_rounds = 1
        planned_rounds = max(1, min(3, planned_rounds))
        max_rounds = min(5, planned_rounds + 2)
        conversation: List[Dict[str, Any]] = []
        question_records: List[Dict[str, Any]] = []
        actual_rounds = 0
        is_requirement_review = self.is_requirement_review_issue(issue)
        if is_requirement_review:
            max_rounds = max(planned_rounds, 2)

        for round_index in range(1, max_rounds + 1):
            actual_rounds = round_index
            round_issue = dict(issue)
            round_issue["discussion_round_index"] = round_index
            round_issue["discussion_rounds"] = planned_rounds
            round_issue["round_limit"] = max_rounds
            if is_requirement_review and round_index > planned_rounds:
                round_issue["participants"] = ["analyst"]
                round_issue["expected_actions"] = {"analyst": ["refine_requirement"]}
            if mode == "simultaneous":
                round_conversation, round_questions = self.mediator.moderate_simultaneous(
                    round_issue,
                    self.registry,
                    artifact=self.artifact,
                    artifact_context=round_issue.get("issue_context"),
                    previous_responses=conversation,
                    return_open_questions=True,
                )
                conversation.extend(round_conversation)
            else:
                round_issue["seed_previous_responses"] = conversation
                round_conversation, round_questions = self.mediator.moderate_sequential(
                    round_issue,
                    self.registry,
                    artifact=self.artifact,
                    artifact_context=round_issue.get("issue_context"),
                )
                conversation = round_conversation
            for oq in round_questions:
                oq["issue_id"] = issue_id
                oq["discussion_round_index"] = round_index
            question_records.extend(round_questions)
            if is_requirement_review and round_index >= planned_rounds:
                if round_index == planned_rounds and self.requirement_review_needs_refine_followup(round_conversation):
                    continue
                break
            if round_index >= planned_rounds and not self.needs_extra_round(round_conversation):
                break

        self.open_questions.extend(question_records)
        self.sync_open_questions_to_artifact(issue, conversation, question_records)
        self.issue_states.setdefault(issue_id, {})
        self.issue_states[issue_id]["discussed"] = True
        self.issue_states[issue_id]["conversation"] = conversation
        self.persist_formal_meeting_progress(issue, conversation=conversation)
        self.save_formal_conflict_report(conversation)
        self.artifact.pop("_issue_research_results", None)
        self.artifact.pop("current_issue", None)
        if self.output_artifact is not None:
            for key in ("URL", "REQ", "scope", "system_models", "feedback", "conflict", "open_questions"):
                if key in self.artifact:
                    self.output_artifact[key] = self.artifact[key]
            self.store.save_artifact(self.output_artifact)
            model_updated = self.conversation_updated_system_models(conversation)
            if model_updated and "system_models" in self.artifact:
                self.store.save_plantuml_files(self.artifact.get("system_models", []))
                self.output_artifact["system_models"] = self.artifact.get("system_models", [])
                self.store.save_artifact(self.output_artifact)
        result = {
            "issue_id": issue_id,
            "planned_rounds": planned_rounds,
            "actual_rounds": actual_rounds,
            "round_limit": max_rounds,
            "conversation_count": len(conversation),
            "oq_count": len(question_records),
        }
        if not conversation:
            result["warning"] = (
                "本議題無參與者可發言，請直接執行 save_issue 儲存後繼續。"
            )
        return result

    @staticmethod
    def conversation_updated_system_models(conversation: List[Dict[str, Any]]) -> bool:
        model_actions = {"model_system", "create_model", "update_model"}
        for entry in conversation or []:
            if not isinstance(entry, dict):
                continue
            actions = {
                str(action or "").strip()
                for action in (entry.get("actions") or [])
                if str(action or "").strip()
            }
            if actions & model_actions:
                return True
            response = entry.get("response") if isinstance(entry.get("response"), dict) else {}
            for result in response.get("issue_action_results") or []:
                if not isinstance(result, dict):
                    continue
                action = str(result.get("action") or "").strip()
                if action in model_actions:
                    return True
                if result.get("system_models") not in (None, "", [], {}):
                    return True
        return False

    def sync_open_questions_to_artifact(
        self,
        issue: Dict[str, Any],
        conversation: List[Dict[str, Any]],
        question_records: List[Dict[str, Any]],
    ) -> None:
        existing = [
            row for row in (self.artifact.get("open_questions") or [])
            if isinstance(row, dict)
        ]
        answered: Dict[tuple[str, str, str], Dict[str, Any]] = {}
        for row in question_records or []:
            key = (
                str(row.get("from_agent") or "").strip(),
                str(row.get("to_agent") or "").strip(),
                str(row.get("question") or "").strip(),
            )
            if key[2]:
                answered[key] = row
        next_num = len(existing) + 1
        seen = {
            (
                str(row.get("from_agent") or "").strip(),
                str(row.get("to_agent") or row.get("owner") or "").strip(),
                str(row.get("question") or "").strip(),
            )
            for row in existing
        }
        for entry in conversation or []:
            if not isinstance(entry, dict):
                continue
            response = entry.get("response") if isinstance(entry.get("response"), dict) else {}
            from_agent = str(entry.get("agent") or "").strip()
            for question in response.get("open_questions", []) or []:
                q = question if isinstance(question, dict) else {"question": str(question)}
                text = str(q.get("question") or "").strip()
                if not text:
                    continue
                to_agent = str(q.get("to") or "user").strip()
                key = (from_agent, to_agent, text)
                if key in seen:
                    continue
                answer = answered.get(key, {})
                status = "answered" if answer else "open"
                existing.append({
                    "id": f"OQ-{next_num}",
                    "question": text,
                    "from_agent": from_agent,
                    "to_agent": to_agent,
                    "owner": to_agent,
                    "status": status,
                    "answer": str(answer.get("answer_text") or "").strip(),
                    "related_source": [
                        item for item in (
                            str(issue.get("id") or "").strip(),
                            str(issue.get("meeting_id") or "").strip(),
                        )
                        if item
                    ],
                })
                next_num += 1
                seen.add(key)
        self.artifact["open_questions"] = existing

    @staticmethod
    def response_state(response: Dict[str, Any]) -> str:
        if not isinstance(response, dict):
            return ""
        state = str(response.get("state") or "").strip()
        if state:
            return state
        stance = response.get("stance") if isinstance(response.get("stance"), dict) else {}
        return str(stance.get("state") or "").strip()

    @staticmethod
    def response_proposal(response: Dict[str, Any]) -> Any:
        if not isinstance(response, dict):
            return {}
        proposal = response.get("proposal")
        if proposal not in (None, "", [], {}):
            return proposal
        stance = response.get("stance") if isinstance(response.get("stance"), dict) else {}
        return stance.get("proposal")

    @staticmethod
    def needs_extra_round(conversation: List[Dict[str, Any]]) -> bool:
        for record_entry in conversation or []:
            if not isinstance(record_entry, dict):
                continue
            if record_entry.get("is_reply"):
                continue
            response = record_entry.get("response") if isinstance(record_entry.get("response"), dict) else {}
            if MeetingRunner.response_state(response) == "needs_more_discussion":
                return True
        return False

    def issue_context_summary(self, issue: Dict[str, Any]) -> Dict[str, Any]:
        source_ids = [
            str(source_id).strip()
            for source_id in issue_artifact_ids(issue)
            if str(source_id).strip()
        ]
        source_set = set(source_ids)

        def selected_rows(rows: Any, prefixes: tuple[str, ...] = ()) -> List[Dict[str, Any]]:
            out: List[Dict[str, Any]] = []
            if not source_set or not isinstance(rows, list):
                return out
            for row in rows:
                if not isinstance(row, dict):
                    continue
                row_id = str(row.get("id") or row.get("issue_id") or "").strip()
                if not row_id:
                    continue
                if source_set and row_id not in source_set:
                    continue
                if prefixes and not row_id.startswith(prefixes):
                    continue
                item: Dict[str, Any] = {"id": row_id}
                for key in ("title", "type", "category", "priority", "status"):
                    value = row.get(key)
                    if value not in (None, "", [], {}):
                        item[key] = value
                out.append(item)
            return out

        conflict_state = self.artifact.get("conflict") if isinstance(self.artifact.get("conflict"), dict) else {}
        conflict_report = conflict_state.get("report")
        if not isinstance(conflict_report, list):
            conflict_report = self.artifact.get("conflict_report", [])
        selected_conflicts = selected_rows(conflict_report, ("CR-", "PAIR-", "MULTIPLE-", "C-"))
        if str(issue.get("category") or "").strip() == "resolve_conflict":
            source_conflicts = [
                row for row in (conflict_report or [])
                if isinstance(row, dict)
                and (
                    not source_set
                    or str(row.get("id") or "").strip() in source_set
                    or str(row.get("source_id") or "").strip() in source_set
                )
            ]
            if source_conflicts:
                selected_conflicts = self.conflict_report_summary(source_conflicts)

        feedback = self.artifact.get("feedback") if isinstance(self.artifact.get("feedback"), dict) else {}
        feedback_items = []
        for section in ("findings", "constraints", "risks", "recommendations"):
            for idx, row in enumerate(feedback.get(section) or [], 1):
                if not isinstance(row, dict):
                    continue
                row_id = str(row.get("id") or f"{section}_{idx}").strip()
                if not source_set or row_id not in source_set:
                    continue
                feedback_items.append({"id": row_id, "section": section, "status": row.get("status")})

        return {
            "issue": {
                "id": issue.get("id"),
                "meeting_id": issue.get("meeting_id"),
                "title": issue.get("title"),
                "category": issue.get("category"),
                "discussion_mode": issue.get("discussion_mode"),
                "discussion_rounds": issue.get("discussion_rounds"),
            },
            "source_summary": {
                "source": source_ids,
                "URL": selected_rows(self.artifact.get("URL", []), ("URL-",)),
                "REQ": selected_rows(self.artifact.get("REQ", []), ("REQ-",)),
                "conflicts": selected_conflicts,
                "feedback": feedback_items,
                "system_models": selected_rows(self.artifact.get("system_models", [])),
                "open_questions": selected_rows(self.artifact.get("open_questions", []), ("OQ-",)),
            },
        }

    def judgment_context(self, issue: Dict[str, Any]) -> Dict[str, Any]:
        category = str(issue.get("category") or "").strip()
        source_ids = [
            str(source_id).strip()
            for source_id in (issue_artifact_ids(issue))
            if str(source_id).strip()
        ]
        context: Dict[str, Any] = {}
        if category == "resolve_conflict":
            conflict_state = self.artifact.get("conflict") if isinstance(self.artifact.get("conflict"), dict) else {}
            report = conflict_state.get("report")
            if not isinstance(report, list):
                report = self.artifact.get("conflict_report")
            if isinstance(report, list):
                rows = report
                if source_ids:
                    selected = [
                        row for row in report
                        if isinstance(row, dict) and str(row.get("id") or "").strip() in source_ids
                    ]
                    if selected:
                        rows = selected
                summary = self.conflict_report_summary(rows)
                if summary:
                    context["conflict_report"] = summary
        return context

    def save_formal_conflict_report(self, conversation: List[Dict[str, Any]]) -> None:
        report_rows: List[Dict[str, Any]] = []
        report_md = ""
        generated = False
        for record_entry in conversation or []:
            if not isinstance(record_entry, dict):
                continue
            if record_entry.get("is_reply"):
                continue
            response = record_entry.get("response") if isinstance(record_entry.get("response"), dict) else {}
            action_results = response.get("issue_action_results")
            if not isinstance(action_results, list):
                continue
            for result in action_results:
                if not isinstance(result, dict):
                    continue
                if str(result.get("action") or "").strip() != "analyze_conflicts":
                    continue
                rows = result.get("conflict_report")
                if isinstance(rows, list) and rows:
                    report_rows = [dict(row) for row in rows if isinstance(row, dict)]
                markdown = str(result.get("conflict_report_markdown") or "").strip()
                if markdown:
                    report_md = markdown
                steps = result.get("steps")
                if isinstance(steps, list):
                    generated = any(
                        isinstance(step, dict)
                        and str(step.get("action") or "").strip() == "generate_conflict_report"
                        for step in steps
                    )
        if not generated or not report_rows:
            return
        try:
            from storage.artifact import (
                conflict_enrichment_matches,
                conflict_requirement_signature,
                existing_report_enrichment,
                latest_conflict_report_payload,
                reindex_conflict_report_rows,
                save_json_path,
            )

            report_dir = self.store.artifact_dir / "report"
            latest_version = 0
            if report_dir.exists():
                for path in report_dir.glob("conflict_report_v*.json"):
                    raw_version = path.stem[len("conflict_report_v"):]
                    if raw_version.isdigit():
                        latest_version = max(latest_version, int(raw_version))
            next_version = max(latest_version + 1, int(self.round_num or 1))
            report_path = report_dir / f"conflict_report_v{next_version}.json"
            report_rows = reindex_conflict_report_rows(report_rows)
            history_rows = latest_conflict_report_payload(self.store.artifact_dir)
            if history_rows:
                enrichment = existing_report_enrichment({"conflict": {"report": list(history_rows) + list(report_rows)}})
                merged_rows: List[Dict[str, Any]] = []
                for row in report_rows:
                    item = dict(row)
                    signature = conflict_requirement_signature(item)
                    known = enrichment.get(signature) if signature else None
                    if known and conflict_enrichment_matches(item, known):
                        for key, value in known.items():
                            if key.startswith("_"):
                                continue
                            if item.get(key) in (None, "", [], {}):
                                item[key] = value
                    merged_rows.append(item)
                report_rows = merged_rows
            save_json_path(self.store.base_dir, report_rows, report_path)
            if report_md and hasattr(self.store, "save_markdown"):
                self.store.save_markdown(report_md, "conflict_report.md")
            self.logger.info("  已更新衝突報告：artifact/report/%s", report_path.name)
        except Exception as e:
            raise RuntimeError("正式會議 conflict report 寫檔失敗") from e

    def discussion_round_block(self, *, create: bool = True) -> Optional[Dict[str, Any]]:
        discussions = self.artifact.setdefault("discussions", [])
        for block in discussions:
            if isinstance(block, dict) and int(block.get("round") or -1) == int(self.round_num):
                block.setdefault("issues", [])
                return block
        if not create:
            return None
        block = {"round": self.round_num, "issues": []}
        discussions.append(block)
        return block

    @staticmethod
    def meeting_record_participants(issue: Dict[str, Any]) -> List[str]:
        participants = list(issue.get("participants", []) or [])
        proposer = str(issue.get("proposed_by") or "").strip()
        if proposer and proposer not in participants:
            participants.insert(0, proposer)
        return list(dict.fromkeys(participants))

    def ensure_meeting_record(self, issue: Dict[str, Any]) -> Dict[str, Any]:
        issue_id = str(issue.get("id") or "").strip()
        block = self.discussion_round_block(create=True)
        rows = block.setdefault("issues", []) if isinstance(block, dict) else []
        for row in rows:
            if isinstance(row, dict) and str(row.get("issue_id") or "").strip() == issue_id:
                return row
        meeting_id = f"R{self.round_num}-M{len(rows) + 1}"
        meeting_record = {
            "meeting_id": meeting_id,
            "issue_id": issue_id,
            "category": issue.get("category", ""),
            "proposed_by": issue.get("proposed_by", ""),
            "participants": self.meeting_record_participants(issue),
            "discussion_mode": issue.get("discussion_mode", "sequential"),
        }
        issue_context = issue.get("issue_context")
        if isinstance(issue_context, dict) and issue_context:
            meeting_record["issue_context"] = issue_context
        rows.append(meeting_record)
        self.meeting_records = rows
        return meeting_record

    def persist_formal_meeting_progress(
        self,
        issue: Dict[str, Any],
        *,
        conversation: Optional[List[Dict[str, Any]]] = None,
        resolution: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        meeting_record = self.ensure_meeting_record(issue)
        meeting_id = str(meeting_record.get("meeting_id") or "").strip()
        if meeting_id:
            issue["meeting_id"] = meeting_id
        meeting_record["category"] = issue.get("category", "")
        meeting_record["proposed_by"] = issue.get("proposed_by", "")
        meeting_record["participants"] = self.meeting_record_participants(issue)
        meeting_record["discussion_mode"] = issue.get("discussion_mode", "sequential")
        issue_context = issue.get("issue_context")
        if isinstance(issue_context, dict) and issue_context:
            meeting_record["issue_context"] = issue_context
        if conversation is not None:
            clean_rows: List[Dict[str, Any]] = []
            for row in conversation:
                if isinstance(row, dict):
                    clean_rows.extend(self.conversation_entry_records(row))
            if clean_rows:
                meeting_record["conversation"] = clean_rows
        if resolution is not None:
            resolution = self.enrich_resolution_changes(resolution)
            self.apply_conflict_report_resolution(issue, resolution)
            meeting_record["resolution"] = resolution
            self.apply_default_issue_completion(issue, resolution, meeting_record)
        block = self.discussion_round_block(create=True)
        self.meeting_records = list(block.get("issues", []) if isinstance(block, dict) else [])
        if self.output_artifact is not None:
            for key in ("meta", "feedback", "URL", "conflict"):
                if key in self.artifact:
                    self.output_artifact[key] = self.artifact[key]
            self.output_artifact["discussions"] = list(self.artifact.get("discussions", []) or [])
            self.store.save_artifact(self.output_artifact)
        return meeting_record

    def apply_conflict_report_resolution(
        self,
        issue: Dict[str, Any],
        resolution: Dict[str, Any],
    ) -> None:
        status = str(resolution.get("status") or "").strip()
        if status not in {"agreed", "human_decision"}:
            return
        conflict = self.artifact.get("conflict") if isinstance(self.artifact.get("conflict"), dict) else {}
        rows = conflict.get("report") if isinstance(conflict.get("report"), list) else []
        if not rows:
            return
        ordered_target_ids = conflict_report_resolution_ids(self.artifact, issue, resolution)
        target_ids = set(ordered_target_ids)
        if not ordered_target_ids:
            return
        meeting_id = str(issue.get("meeting_id") or "").strip()
        changed = False
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_ids = {
                str(row.get("id") or "").strip(),
                str(row.get("source_id") or "").strip(),
            }
            if not target_ids.intersection(row_ids):
                continue
            row["status"] = status
            if meeting_id:
                row["meeting_id"] = meeting_id
            summary = str(resolution.get("summary") or "").strip()
            decision = str(resolution.get("decision") or "").strip()
            option_decision = adopted_resolution_option_text(row, decision)
            if summary:
                row["summary"] = summary
            if option_decision:
                row["decision"] = option_decision
            elif decision:
                row["decision"] = decision
            changed = True
        if not changed:
            return
        resolution["affected_conflict_ids"] = ordered_target_ids
        self.artifact.setdefault("conflict", {})["report"] = rows
        if self.output_artifact is not None:
            self.output_artifact.setdefault("conflict", {})["report"] = rows
        self.apply_conflict_resolution_to_url(
            issue=issue,
            resolution=resolution,
            conflict_rows=rows,
            target_ids=target_ids,
        )
        self.save_latest_conflict_report(rows)

    def apply_conflict_resolution_to_url(
        self,
        *,
        issue: Dict[str, Any],
        resolution: Dict[str, Any],
        conflict_rows: List[Dict[str, Any]],
        target_ids: set[str],
    ) -> None:
        if str(issue.get("category") or "").strip() != "resolve_conflict":
            return
        try:
            from agents.profile.analyst.requirements import (
                renumber_requirement_candidate_ids,
            )
        except Exception as e:
            raise RuntimeError("載入 URL id helper 失敗") from e

        url_rows = [
            dict(row)
            for row in (self.artifact.get("URL", []) or [])
            if isinstance(row, dict)
        ]
        if not url_rows:
            return
        by_id = {
            str(row.get("id") or "").strip(): row
            for row in url_rows
            if str(row.get("id") or "").strip()
        }
        meeting_id = str(issue.get("meeting_id") or "").strip()
        changed = False
        update_plan = self.normalize_url_update_plan(resolution.get("url_updates"), by_id=by_id)
        if update_plan:
            remove_ids: set[str] = set()
            for update in update_plan:
                action = str(update.get("action") or "").strip()
                ids = [
                    str(req_id or "").strip()
                    for req_id in (update.get("ids") or [])
                    if str(req_id or "").strip() in by_id
                ]
                if not ids:
                    continue
                reason = str(update.get("reason") or "").strip()
                if action == "remove":
                    remove_ids.update(ids)
                    changed = True
                    continue
                for req_id in ids:
                    row = by_id.get(req_id)
                    if not row:
                        continue
                    if action == "revise":
                        text = self.clean_requirement_text(update.get("text"))
                        if text:
                            row["text"] = text
                    elif action == "keep":
                        cleaned_text = self.cleaned_single_url_text(row)
                        if cleaned_text:
                            row["text"] = cleaned_text
                    row["source"] = meeting_id or str(issue.get("id") or "").strip()
                    row.pop("source_id", None)
                    if reason:
                        row["resolution_reason"] = reason
                    changed = True
            if remove_ids:
                url_rows = [
                    row for row in url_rows
                    if str(row.get("id") or "").strip() not in remove_ids
                ]
                url_rows = renumber_requirement_candidate_ids(url_rows)
            if changed:
                self.artifact["URL"] = url_rows
                meta = self.artifact.setdefault("meta", {})
                meta["requirements_changed"] = True
                meta["requirements_changed_by"] = meeting_id or str(issue.get("id") or "").strip()
                meta["requirements_changed_reason"] = "resolve_conflict"
            return

        for conflict_row in conflict_rows:
            if not isinstance(conflict_row, dict):
                continue
            conflict_ids = {
                str(conflict_row.get("id") or "").strip(),
                str(conflict_row.get("source_id") or "").strip(),
            }
            conflict_ids.discard("")
            if not target_ids.intersection(conflict_ids):
                continue
            conflict_id = str(conflict_row.get("id") or "").strip()
            if not conflict_id:
                continue
            source_ids = [
                req_id for req_id in conflict_report_requirement_ids(conflict_row)
                if req_id in by_id
            ]
            if not source_ids:
                continue
            source_rows = [by_id[source_id] for source_id in source_ids]
            duplicate_groups = self.duplicate_url_groups(source_rows)
            duplicate_ids = {
                req_id
                for group in duplicate_groups
                for req_id in group[1:]
            }
            source_set = set(duplicate_ids)
            for source_id in source_ids:
                row = by_id.get(source_id)
                if not row:
                    continue
                if source_id in duplicate_ids:
                    continue
                cleaned_text = self.cleaned_single_url_text(row)
                if cleaned_text and cleaned_text != str(row.get("text") or "").strip():
                    row["text"] = cleaned_text
                    changed = True
                row["source"] = meeting_id or str(issue.get("id") or "").strip()
                row.pop("source_id", None)
                changed = True
            if not source_set:
                continue
            url_rows = [
                row for row in url_rows
                if str(row.get("id") or "").strip() not in source_set
            ]
            url_rows = renumber_requirement_candidate_ids(url_rows)
            by_id = {
                str(row.get("id") or "").strip(): row
                for row in url_rows
                if str(row.get("id") or "").strip()
            }
            changed = True

        if not changed:
            return
        self.artifact["URL"] = url_rows
        meta = self.artifact.setdefault("meta", {})
        meta["requirements_changed"] = True
        meta["requirements_changed_by"] = meeting_id or str(issue.get("id") or "").strip()
        meta["requirements_changed_reason"] = "resolve_conflict"

    @staticmethod
    def normalize_url_update_plan(
        value: Any,
        *,
        by_id: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        rows = value if isinstance(value, list) else []
        out: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            action = str(row.get("action") or "").strip()
            if action not in {"keep", "revise", "remove"}:
                continue
            raw_ids = row.get("ids")
            if isinstance(raw_ids, str):
                raw_ids = [raw_ids]
            ids = [
                str(req_id or "").strip()
                for req_id in (raw_ids or [])
                if str(req_id or "").strip() in by_id
            ]
            ids = list(dict.fromkeys(ids))
            if not ids:
                continue
            item: Dict[str, Any] = {
                "action": action,
                "ids": ids,
                "reason": str(row.get("reason") or "").strip(),
            }
            if action == "revise":
                text = str(row.get("text") or "").strip()
                if not text:
                    continue
                item["text"] = text
            out.append(item)
        return out

    def conversation_url_update_plan(
        self,
        conversation: List[Dict[str, Any]],
        *,
        by_id: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for entry in conversation or []:
            if not isinstance(entry, dict):
                continue
            response = entry.get("response") if isinstance(entry.get("response"), dict) else {}
            candidates: List[Any] = []
            if isinstance(response.get("url_updates"), list):
                candidates.append(response.get("url_updates"))
            stance = response.get("stance") if isinstance(response.get("stance"), dict) else {}
            proposal = stance.get("proposal") if isinstance(stance.get("proposal"), dict) else {}
            if isinstance(proposal.get("url_updates"), list):
                candidates.append(proposal.get("url_updates"))
            for candidate in candidates:
                out.extend(self.normalize_url_update_plan(candidate, by_id=by_id))
        return out

    def default_conflict_url_update_plan(
        self,
        conflict_rows: List[Dict[str, Any]],
        *,
        target_ids: set[str],
    ) -> List[Dict[str, Any]]:
        url_rows = [
            row for row in (self.artifact.get("URL", []) or [])
            if isinstance(row, dict)
        ]
        by_id = {
            str(row.get("id") or "").strip(): row
            for row in url_rows
            if str(row.get("id") or "").strip()
        }
        out: List[Dict[str, Any]] = []
        seen: set[tuple[str, tuple[str, ...]]] = set()
        for conflict_row in conflict_rows or []:
            if not isinstance(conflict_row, dict):
                continue
            conflict_ids = {
                str(conflict_row.get("id") or "").strip(),
                str(conflict_row.get("source_id") or "").strip(),
            }
            conflict_ids.discard("")
            if target_ids and not target_ids.intersection(conflict_ids):
                continue
            source_ids = [
                req_id for req_id in conflict_report_requirement_ids(conflict_row)
                if req_id in by_id
            ]
            source_rows = [by_id[source_id] for source_id in source_ids]
            duplicate_groups = self.duplicate_url_groups(source_rows)
            duplicate_ids = {
                req_id
                for group in duplicate_groups
                for req_id in group[1:]
            }
            for source_id in source_ids:
                row = by_id.get(source_id)
                if not row:
                    continue
                if source_id in duplicate_ids:
                    update = {
                        "action": "remove",
                        "ids": [source_id],
                        "reason": "與同一衝突中的其他 URL 內容完全重複。",
                    }
                else:
                    cleaned_text = self.cleaned_single_url_text(row)
                    current_text = str(row.get("text") or "").strip()
                    if cleaned_text and cleaned_text != current_text:
                        update = {
                            "action": "revise",
                            "ids": [source_id],
                            "text": cleaned_text,
                            "reason": "清理重複片段，保留單筆 URL 的原始需求語意。",
                        }
                    else:
                        update = {
                            "action": "keep",
                            "ids": [source_id],
                            "reason": "此 URL 作為衝突解決後仍有效的使用者需求來源。",
                        }
                marker = (update["action"], tuple(update["ids"]))
                if marker in seen:
                    continue
                seen.add(marker)
                out.append(update)
        return out

    @staticmethod
    def is_decision_text(value: Any) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        markers = (
            "採用",
            "決議",
            "裁決",
            "折衷",
            "CR-",
            "resolution",
            "human_decision",
        )
        return any(marker in text for marker in markers)

    @staticmethod
    def clean_requirement_text(value: Any) -> str:
        text = re.sub(r"\s+", " ", str(value or "").strip())
        text = re.sub(r"^(使用者需求|需求|Requirement)\s*[:：]\s*", "", text, flags=re.I)
        while True:
            cleaned = re.sub(
                r"^[^。；;：:]{0,40}?需要系統以一致規格整合處理\s*[:：]\s*",
                "",
                text,
            ).strip()
            if cleaned == text:
                break
            text = cleaned
        return text.strip("；;，,。 ")

    @classmethod
    def requirement_text_clauses(cls, value: Any) -> List[str]:
        text = cls.clean_requirement_text(value)
        if not text:
            return []
        clauses = [
            cls.clean_requirement_text(part)
            for part in re.split(r"[；;]\s*", text)
        ]
        out: List[str] = []
        seen = set()
        for clause in clauses:
            if not clause or cls.is_decision_text(clause):
                continue
            marker = re.sub(r"\s+", "", clause).lower()
            if marker in seen:
                continue
            seen.add(marker)
            out.append(clause)
        return out

    @classmethod
    def cleaned_single_url_text(cls, row: Dict[str, Any]) -> str:
        clauses = cls.requirement_text_clauses(row.get("text") or row.get("description"))
        if not clauses:
            return ""
        if len(clauses) == 1:
            return clauses[0]
        return "；".join(clauses)

    @classmethod
    def duplicate_url_groups(cls, source_rows: List[Dict[str, Any]]) -> List[List[str]]:
        by_text: Dict[str, List[str]] = {}
        for row in source_rows or []:
            if not isinstance(row, dict):
                continue
            req_id = str(row.get("id") or "").strip()
            text = cls.cleaned_single_url_text(row)
            if not req_id or not text:
                continue
            marker = re.sub(r"\s+", "", text).lower()
            by_text.setdefault(marker, []).append(req_id)
        return [ids for ids in by_text.values() if len(ids) > 1]

    @staticmethod
    def common_url_stakeholder(rows: List[Dict[str, Any]]) -> Dict[str, str]:
        stakeholders = []
        for row in rows or []:
            stakeholder = row.get("stakeholder")
            if isinstance(stakeholder, dict):
                name = str(stakeholder.get("name") or "").strip()
                if name:
                    stakeholders.append(
                        {
                            "name": name,
                            "type": str(stakeholder.get("type") or "").strip(),
                        }
                    )
        if not stakeholders:
            return {}
        first = stakeholders[0]
        if all(item == first for item in stakeholders):
            return first
        return {}

    def save_latest_conflict_report(self, rows: List[Dict[str, Any]]) -> None:
        try:
            from storage.artifact import reindex_conflict_report_rows, save_json_path

            report_dir = self.store.artifact_dir / "report"
            latest_path = None
            latest_version = -1
            if report_dir.exists():
                for path in report_dir.glob("conflict_report_v*.json"):
                    raw_version = path.stem[len("conflict_report_v"):]
                    if raw_version.isdigit() and int(raw_version) > latest_version:
                        latest_version = int(raw_version)
                        latest_path = path
            if latest_path is None:
                report_dir.mkdir(parents=True, exist_ok=True)
                latest_path = report_dir / f"conflict_report_v{max(1, int(self.round_num or 1))}.json"
            save_json_path(self.store.base_dir, reindex_conflict_report_rows(rows), latest_path)
        except Exception as e:
            raise RuntimeError("正式會議 conflict report 狀態寫檔失敗") from e

    def apply_default_issue_completion(
        self,
        issue: Dict[str, Any],
        resolution: Dict[str, Any],
        meeting_record: Optional[Dict[str, Any]] = None,
    ) -> None:
        status = str(resolution.get("status") or "").strip()
        if status not in {"agreed", "human_decision"}:
            return
        proposal_ids = {
            str(item).strip()
            for item in (issue_proposal_ids(issue))
            if str(item).strip()
        }
        meeting_id = str(issue.get("meeting_id") or "").strip()
        issue_id = str(issue.get("id") or "").strip()
        if any(source_id.endswith("-mediator-requirement-review") for source_id in proposal_ids):
            meta = self.artifact.setdefault("meta", {})
            meta["requirements_review_status"] = status
            meta["requirements_review_by"] = meeting_id or issue_id
            meta["requirements_review_round"] = self.round_num
            meta["requirements_review_cycle"] = int(meta.get("requirements_review_cycle") or 0) + 1
            meta.pop("requirements_review_invalidated_by", None)
            meta.pop("requirements_review_invalidated_round", None)
            self.run_model_system_after_requirement_review(issue, meeting_record)

    def run_model_system_after_requirement_review(
        self,
        issue: Dict[str, Any],
        meeting_record: Optional[Dict[str, Any]] = None,
    ) -> None:
        req_rows = self.artifact.get("REQ")
        if not isinstance(req_rows, list) or not req_rows:
            return
        modeler = self.registry.get("modeler") if self.registry is not None else None
        if modeler is None or not hasattr(modeler, "run_model_loop"):
            return
        model_issue = {
            "id": issue.get("id"),
            "meeting_id": issue.get("meeting_id"),
            "title": issue.get("title"),
            "category": "align_model",
            "description": "需求正式化完成後，根據最新 REQ-* 建立或更新系統模型。",
            "trace": issue.get("trace", {}),
        }
        try:
            loop_result = modeler.run_model_loop(
                self.artifact,
                recent_discussions=self.issue_states.get(issue.get("id"), {}).get("conversation"),
                issue=model_issue,
            )
            meeting_id = str(issue.get("meeting_id") or issue.get("id") or "").strip()
            for model in self.artifact.get("system_models", []) or []:
                if isinstance(model, dict) and meeting_id:
                    model["source"] = meeting_id
            self.append_requirement_review_model_record(
                issue,
                loop_result if isinstance(loop_result, dict) else {},
                meeting_record,
            )
            meta = self.artifact.setdefault("meta", {})
            meta["model_alignment_status"] = "agreed"
            meta["model_alignment_by"] = meeting_id
            meta["model_alignment_round"] = self.round_num
            meta["model_alignment_cycle"] = int(meta.get("model_alignment_cycle") or 0) + 1
            if self.output_artifact is not None:
                for key in ("meta", "system_models"):
                    if key in self.artifact:
                        self.output_artifact[key] = self.artifact[key]
                self.store.save_artifact(self.output_artifact)
                if "system_models" in self.artifact:
                    self.store.save_plantuml_files(self.artifact.get("system_models", []))
                    self.output_artifact["system_models"] = self.artifact.get("system_models", [])
                    self.store.save_artifact(self.output_artifact)
        except Exception as e:
            meta = self.artifact.setdefault("meta", {})
            meta["model_alignment_status"] = "failed"
            meta["model_alignment_error"] = str(e)

    def append_requirement_review_model_record(
        self,
        issue: Dict[str, Any],
        loop_result: Dict[str, Any],
        meeting_record: Optional[Dict[str, Any]] = None,
    ) -> None:
        issue_id = issue.get("id")
        action_result = {
            "action": "model_system",
            "steps": [
                str((row.get("decision") or {}).get("action") or "").strip()
                for row in (loop_result.get("opa_trace") or [])
                if isinstance(row, dict) and str((row.get("decision") or {}).get("action") or "").strip()
            ],
            "system_models": self.artifact.get("system_models", []),
        }
        model_rows = self.artifact.get("system_models") if isinstance(self.artifact.get("system_models"), list) else []
        text = (
            f"需求正式化完成後已根據最新 REQ-* 建立或更新系統模型，共 {len(model_rows)} 筆模型。"
        )
        raw_record = {
            "agent": "modeler",
            "round_index": "post",
            "response": {
                "actions": ["model_system"],
                "text": text,
                "issue_action_results": [action_result],
                "stance": {"state": "ready_to_close"},
            },
        }
        status = self.issue_states.setdefault(issue_id, {})
        conversation = status.get("conversation")
        if not isinstance(conversation, list):
            conversation = []
        conversation.append(raw_record)
        status["conversation"] = conversation
        clean_rows = self.conversation_entry_records(raw_record)
        if clean_rows and meeting_record is not None:
            existing = meeting_record.get("conversation")
            if not isinstance(existing, list):
                existing = []
            existing.extend(clean_rows)
            meeting_record["conversation"] = existing

    def update_rationale_for_issue(
        self,
        issue: Dict[str, Any],
        conversation: List[Dict],
        resolution: Dict[str, Any],
    ) -> None:
        """每個議題存檔後即時更新 design_rationale.md。"""
        try:
            issue_id = issue.get("id", "")
            issue_oq = self.issue_open_questions(issue_id)
            issue_context = self.mediator.build_design_rationale_entry_context(
                issue=issue,
                conversation=conversation,
                resolution=resolution,
                issue_open_questions=issue_oq,
                round_num=self.round_num,
            )

            dr_path = self.store.output_dir / "design_rationale.md"
            if dr_path.exists():
                existing_md = dr_path.read_text(encoding="utf-8")
                dr_md = self.mediator.update_rationale(existing_md, issue_context)
            else:
                dr_md = self.mediator.write_rationale(issue_context)
            self.store.save_markdown(dr_md, "design_rationale.md")
            self.logger.info("  已更新設計緣由：design_rationale.md")
        except Exception as e:
            raise RuntimeError("更新 design_rationale.md 失敗") from e

    def observe_action(self, action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = params or {}
        action = self.action_name(action)
        state = self.get_state_summary()
        issues = self.current_meeting_issues()
        return {
            "action": action,
            "params": params,
            "issues_count": len(issues),
            "records_count": len(self.meeting_records),
            "open_questions_count": len(self.open_questions),
            "state_summary": state,
        }

    def resolve_issue_via_substeps(
        self,
        *,
        issue: Dict[str, Any],
        conversation: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        issue_id = issue.get("id")

        readiness = self.collect_stance_summary(issue, conversation)

        if str(issue.get("category") or "").strip() == "resolve_conflict":
            resolution = self.close_conflict_resolution_issue(issue, conversation, readiness)
        elif readiness.get("ready_to_close"):
            resolution = self.mediator.close_issue(
                issue, conversation, readiness,
            )
        elif self.is_requirement_review_issue(issue):
            resolution = self.close_requirement_review_issue(issue, conversation, readiness)
        else:
            decision_context = self.judgment_context(issue)
            decision_analysis = self.mediator.prepare_judgment(
                issue,
                conversation,
                decision_context=decision_context,
            )
    
            resolution = self.mediator.build_issue_result(
                status="",
                summary=decision_analysis.get("summary", ""),
                decision="",
                agreed_points=[],
                unresolved_points=decision_analysis.get("unresolved_points", []),
                new_open_questions=[],
                affected_requirement_ids=decision_analysis.get("affected_requirement_ids", []),
                needs_human=True,
                options=decision_analysis.get("options", []),
                recommendation=decision_analysis.get("recommendation", {}),
                mediator_compromise=decision_analysis.get("compromise", {}),
            )

        self.settle_requirements_after_issue(issue, conversation, resolution)
    
        source_ids = list(issue_artifact_ids(issue) or [])
        derived_req_ids = [
            sid for sid in source_ids
            if isinstance(sid, str)
            and sid.startswith(("REQ-", "R-"))
        ]
        cur_req_ids = resolution.get("affected_requirement_ids") or []
        if not cur_req_ids:
            resolution["affected_requirement_ids"] = derived_req_ids
        resolution["artifact_updates"] = self.artifact_updates_summary(
            issue,
            conversation,
            resolution,
        )
        return resolution

    def should_settle_requirements_after_issue(
        self,
        issue: Dict[str, Any],
        conversation: List[Dict[str, Any]],
        resolution: Dict[str, Any],
    ) -> bool:
        if self.is_requirement_review_issue(issue):
            return False
        if str(issue.get("category") or "").strip() == "resolve_conflict":
            return False
        if str(resolution.get("status") or "").strip() not in {"agreed", "human_decision"}:
            return False
        if self.issue_states.get(str(issue.get("id") or "").strip(), {}).get("requirements_settled"):
            return False
        category = str(issue.get("category") or "").strip()
        if category == "clarify_requirement":
            return True
        if any(resolution.get(key) for key in ("affected_requirement_ids", "requirement_changes", "url_updates")):
            return True
        for entry in conversation or []:
            if not isinstance(entry, dict):
                continue
            response = entry.get("response") if isinstance(entry.get("response"), dict) else {}
            for result in response.get("issue_action_results") or []:
                if not isinstance(result, dict):
                    continue
                if str(result.get("action") or "").strip() in {
                    "analyze_requirements",
                }:
                    return True
        return False

    def settle_requirements_after_issue(
        self,
        issue: Dict[str, Any],
        conversation: List[Dict[str, Any]],
        resolution: Dict[str, Any],
    ) -> None:
        if not self.should_settle_requirements_after_issue(issue, conversation, resolution):
            return
        analyst = self.registry.get("analyst") if self.registry is not None else None
        if analyst is None or not hasattr(analyst, "execute_refine_requirement"):
            return
        issue_id = str(issue.get("id") or "").strip()
        resolution_text = "；".join(
            part
            for part in (
                str(resolution.get("summary") or "").strip(),
                str(resolution.get("decision") or "").strip(),
            )
            if part
        )
        synthetic_resolution = {
            "agent": "mediator",
            "response": {
                "text": f"本議題收斂結果：{resolution_text}" if resolution_text else "本議題已收斂，請將可寫入需求的內容沉澱到 REQ。",
            },
        }
        try:
            action_result = analyst.execute_refine_requirement(
                artifact=self.artifact,
                issue=issue,
                previous_responses=list(conversation or []) + [synthetic_resolution],
            )
        except Exception as exc:
            self.logger.warning("  需求沉澱失敗：%s", exc)
            return
        raw_record = {
            "agent": "analyst",
            "round_index": "settle",
            "is_follow_up": True,
            "response": {
                "actions": ["refine_requirement"],
                "text": "根據本議題收斂結果，已將可寫入需求規格的內容沉澱到 REQ。",
                "issue_action_results": [action_result],
                "stance": {"state": "ready_to_close"},
            },
        }
        conversation.append(raw_record)
        self.issue_states.setdefault(issue_id, {})["requirements_settled"] = True
        req_ids = [
            str(row.get("id") or "").strip()
            for row in (action_result.get("REQ") or [])
            if isinstance(row, dict) and str(row.get("id") or "").strip()
        ]
        if req_ids:
            current = [
                str(value).strip()
                for value in (resolution.get("affected_requirement_ids") or [])
                if str(value).strip()
            ]
            resolution["affected_requirement_ids"] = list(dict.fromkeys(current + req_ids))

    def conflict_rows_for_issue(self, issue: Dict[str, Any]) -> List[Dict[str, Any]]:
        conflict_state = self.artifact.get("conflict") if isinstance(self.artifact.get("conflict"), dict) else {}
        report = conflict_state.get("report")
        if not isinstance(report, list):
            report = self.artifact.get("conflict_report", [])
        if not isinstance(report, list):
            return []
        source_ids = [
            str(source_id).strip()
            for source_id in issue_artifact_ids(issue)
            if str(source_id).strip()
        ]
        selected = [
            row for row in report
            if isinstance(row, dict)
            and (not source_ids or str(row.get("id") or "").strip() in source_ids)
            and str(row.get("label") or "").strip() == "Conflict"
        ]
        if selected:
            return selected
        return [
            row for row in report
            if isinstance(row, dict)
            and str(row.get("label") or "").strip() == "Conflict"
            and str(row.get("status") or "").strip().lower() not in {"agreed", "human_decision"}
        ]

    @staticmethod
    def has_major_conflict_objection(conversation: List[Dict[str, Any]]) -> bool:
        keywords = (
            "反對",
            "不同意",
            "不可採用",
            "不能採用",
            "不建議採用",
            "無法採用",
            "重大風險",
            "高風險",
            "合規風險",
            "安全風險",
            "仍有衝突",
            "無法收斂",
            "must not",
            "cannot adopt",
            "major risk",
            "compliance risk",
            "security risk",
        )
        for entry in conversation or []:
            if not isinstance(entry, dict):
                continue
            response = entry.get("response") if isinstance(entry.get("response"), dict) else {}
            if MeetingRunner.response_state(response) != "needs_more_discussion":
                continue
            text_parts = [str(response.get("text") or "")]
            for question in response.get("open_questions") or []:
                if isinstance(question, dict):
                    text_parts.append(str(question.get("question") or ""))
                else:
                    text_parts.append(str(question or ""))
            text = "\n".join(text_parts).lower()
            if any(keyword.lower() in text for keyword in keywords):
                return True
        return False

    def close_conflict_resolution_issue(
        self,
        issue: Dict[str, Any],
        conversation: List[Dict[str, Any]],
        readiness: Dict[str, Any],
    ) -> Dict[str, Any]:
        conflict_rows = self.conflict_rows_for_issue(issue)
        missing_recommendation = [
            str(row.get("id") or "").strip()
            for row in conflict_rows
            if not str(row.get("recommended_resolution") or "").strip()
        ]
        if not conflict_rows or missing_recommendation or self.has_major_conflict_objection(conversation):
            decision_context = self.judgment_context(issue)
            decision_analysis = self.mediator.prepare_judgment(
                issue,
                conversation,
                decision_context=decision_context,
            )
            return self.mediator.build_issue_result(
                status="",
                summary=decision_analysis.get("summary", ""),
                decision="",
                agreed_points=[],
                unresolved_points=decision_analysis.get("unresolved_points", []),
                new_open_questions=[],
                affected_requirement_ids=decision_analysis.get("affected_requirement_ids", []),
                affected_conflict_ids=[
                    str(row.get("id") or "").strip()
                    for row in conflict_rows
                    if str(row.get("id") or "").strip()
                ],
                needs_human=True,
                options=decision_analysis.get("options", []),
                recommendation=decision_analysis.get("recommendation", {}),
                mediator_compromise=decision_analysis.get("compromise", {}),
            )

        affected_conflict_ids = [
            str(row.get("id") or "").strip()
            for row in conflict_rows
            if str(row.get("id") or "").strip()
        ]
        target_ids = set(affected_conflict_ids)
        url_rows = [
            row for row in (self.artifact.get("URL", []) or [])
            if isinstance(row, dict)
        ]
        by_id = {
            str(row.get("id") or "").strip(): row
            for row in url_rows
            if str(row.get("id") or "").strip()
        }
        url_updates = self.conversation_url_update_plan(conversation, by_id=by_id)
        if not url_updates:
            url_updates = self.default_conflict_url_update_plan(
                conflict_rows,
                target_ids=target_ids,
            )
        recommended = [
            str(row.get("recommended_resolution") or "").strip()
            for row in conflict_rows
            if str(row.get("recommended_resolution") or "").strip()
        ]
        summary = f"已採用 conflict report 中 {len(recommended)} 筆既有推薦解法處理需求衝突。"
        if len(recommended) == 1:
            decision = recommended[0]
        else:
            decision = "；".join(
                f"{conflict_id}：{text}"
                for conflict_id, text in zip(affected_conflict_ids, recommended)
            )
        return self.mediator.build_issue_result(
            status="agreed",
            summary=summary,
            decision=decision,
            agreed_points=recommended,
            unresolved_points=[],
            new_open_questions=[],
            affected_conflict_ids=affected_conflict_ids,
            url_updates=url_updates,
            needs_human=False,
        )

    @staticmethod
    def is_requirement_review_issue(issue: Dict[str, Any]) -> bool:
        title = str((issue or {}).get("title") or "").strip()
        category = str((issue or {}).get("category") or "").strip()
        proposal_ids = {
            str(item).strip()
            for item in issue_proposal_ids(issue)
            if str(item).strip()
        }
        return (
            title == "需求正式化"
            or (
                category == "clarify_requirement"
                and any(source_id.endswith("-mediator-requirement-review") for source_id in proposal_ids)
            )
        )

    @staticmethod
    def requirement_review_needs_refine_followup(conversation: List[Dict[str, Any]]) -> bool:
        for entry in conversation or []:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("agent") or "").strip() == "analyst":
                continue
            response = entry.get("response") if isinstance(entry.get("response"), dict) else {}
            text = str(response.get("text") or "").strip()
            if not text:
                continue
            lowered = text.lower()
            if any(
                keyword in lowered
                for keyword in (
                    "驗收",
                    "時效",
                    "門檻",
                    "例外",
                    "限制",
                    "風險",
                    "假設",
                    "優先",
                    "資安",
                    "合規",
                    "安全",
                    "效能",
                    "可靠",
                    "同步",
                    "通知",
                    "退款",
                    "公平",
                    "validation",
                    "metric",
                    "constraint",
                    "risk",
                    "assumption",
                    "priority",
                )
            ):
                return True
        return False

    def close_requirement_review_issue(
        self,
        issue: Dict[str, Any],
        conversation: List[Dict[str, Any]],
        readiness: Dict[str, Any],
    ) -> Dict[str, Any]:
        req_ids: List[str] = []
        unresolved_points: List[str] = []
        for entry in conversation or []:
            if not isinstance(entry, dict):
                continue
            response = entry.get("response") if isinstance(entry.get("response"), dict) else {}
            proposal = self.response_proposal(response)
            proposal = proposal if isinstance(proposal, dict) else {}
            summary = str(proposal.get("summary") or response.get("text") or "").strip()
            if self.response_state(response) == "needs_more_discussion" and summary:
                unresolved_points.append(summary)
            for result in response.get("issue_action_results") or []:
                if not isinstance(result, dict):
                    continue
                if str(result.get("action") or "").strip() != "refine_requirement":
                    continue
                for row in result.get("REQ") or []:
                    if isinstance(row, dict):
                        req_id = str(row.get("id") or "").strip()
                        if req_id:
                            req_ids.append(req_id)
        req_ids = list(dict.fromkeys(req_ids))
        unresolved_points = list(dict.fromkeys(unresolved_points))
        summary = "需求正式化已完成；未完全確認的內容已保留於 REQ 的 assumptions、risks 或 open questions。"
        if req_ids:
            summary = f"需求正式化已完成，更新 {len(req_ids)} 筆 REQ；未完全確認的內容已保留於 assumptions、risks 或 open questions。"
        decision = (
            "接受目前 REQ 草稿作為下一版需求草稿輸入；"
            "未確認欄位不交由人類裁決，先沉澱為 assumptions、risks 或 open questions，後續正式議題再處理。"
        )
        return self.mediator.build_issue_result(
            status="agreed",
            summary=summary,
            decision=decision,
            mediator_compromise={"title": "", "description": "", "rationale": ""},
            agreed_points=[decision],
            unresolved_points=unresolved_points,
            new_open_questions=[],
            affected_requirement_ids=req_ids,
            needs_human=False,
        )

    def artifact_updates_summary(
        self,
        issue: Dict[str, Any],
        conversation: List[Dict[str, Any]],
        resolution: Dict[str, Any],
    ) -> Dict[str, Any]:
        updates: Dict[str, Any] = {}
        affected_requirements = [
            str(value).strip()
            for value in (resolution.get("affected_requirement_ids") or [])
            if str(value).strip()
        ]
        if affected_requirements:
            updates["REQ"] = {
                "ids": affected_requirements,
            }
        if resolution.get("url_updates"):
            updates["URL"] = {
                "updates": len(resolution.get("url_updates") or [])
            }
        affected_conflicts = [
            str(value).strip()
            for value in (resolution.get("affected_conflict_ids") or [])
            if str(value).strip()
        ]
        if affected_conflicts:
            updates["conflict_report"] = {"ids": affected_conflicts}
        if resolution.get("new_open_questions"):
            updates["open_questions"] = {
                "count": len(resolution.get("new_open_questions") or [])
            }

        for entry in conversation or []:
            if not isinstance(entry, dict):
                continue
            response = entry.get("response") if isinstance(entry.get("response"), dict) else {}
            for result in response.get("issue_action_results") or []:
                if not isinstance(result, dict):
                    continue
                action = str(result.get("action") or "").strip()
                if action == "analyze_requirements":
                    updates.setdefault("URL", {}).setdefault("actions", [])
                    if action not in updates["URL"]["actions"]:
                        updates["URL"]["actions"].append(action)
                elif action == "refine_requirement":
                    updates.setdefault("REQ", {}).setdefault("actions", [])
                    if action not in updates["REQ"]["actions"]:
                        updates["REQ"]["actions"].append(action)
                    if isinstance(result.get("REQ"), list):
                        updates["REQ"]["count"] = len(result.get("REQ") or [])
                elif action == "refine_scope":
                    updates.setdefault("scope", {}).setdefault("actions", [])
                    if action not in updates["scope"]["actions"]:
                        updates["scope"]["actions"].append(action)
                elif action == "analyze_conflicts":
                    updates.setdefault("conflict_report", {}).setdefault("actions", [])
                    if action not in updates["conflict_report"]["actions"]:
                        updates["conflict_report"]["actions"].append(action)
                    if isinstance(result.get("conflict_report"), list):
                        updates["conflict_report"]["count"] = len(result.get("conflict_report") or [])
                elif action in {"research_domain", "update_feedback"} or result.get("feedback") not in (None, "", [], {}):
                    feedback = result.get("feedback") if isinstance(result.get("feedback"), dict) else {}
                    updates["feedback"] = {
                        "action": action or "update_feedback",
                        "sections": [
                            key for key in ("findings", "constraints", "risks", "recommendations")
                            if feedback.get(key)
                        ],
                    }
                elif action in {"model_system", "create_model", "update_model"} or result.get("system_models") not in (None, "", [], {}):
                    models = result.get("system_models")
                    if isinstance(models, list):
                        updates["system_models"] = {
                            "action": action or "model_system",
                            "ids": [
                                str(model.get("id") or model.get("name") or "").strip()
                                for model in models
                                if isinstance(model, dict) and str(model.get("id") or model.get("name") or "").strip()
                            ],
                            "count": len(models),
                        }
        return updates

    def collect_stance_summary(
        self,
        issue: Dict[str, Any],
        conversation: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        status_counts = {
            "ready_to_close": 0,
            "needs_more_discussion": 0,
        }
        participant_status: List[Dict[str, Any]] = []
        proposer = str(issue.get("proposed_by") or self.find_issue_proposer(issue) or "").strip()
        proposer_status = ""
        for record_entry in conversation or []:
            if not isinstance(record_entry, dict):
                continue
            if record_entry.get("is_reply"):
                continue
            response = record_entry.get("response") if isinstance(record_entry.get("response"), dict) else {}
            status = self.response_state(response)
            if status not in status_counts:
                continue
            status_counts[status] += 1
            agent_name = str(record_entry.get("agent") or "").strip()
            if proposer and agent_name == proposer and not proposer_status:
                proposer_status = status
            participant_status.append(
                {
                    "agent": agent_name,
                    "status": status,
                    "has_open_questions": bool(response.get("open_questions")),
                    "is_proposer": bool(proposer and agent_name == proposer),
                }
            )
        if not participant_status:
            return {
                "ready_to_close": False,
                "reason": "無發言",
                "summary": "本議題沒有足夠發言可形成結論。",
                "decision": "",
                "status_counts": status_counts,
                "participant_status": participant_status,
            }
        ready_count = status_counts["ready_to_close"]
        needs_count = status_counts["needs_more_discussion"]
        majority_ready = ready_count > needs_count
        proposer_ready = (not proposer or not proposer_status or proposer_status == "ready_to_close")
        if not majority_ready or not proposer_ready:
            reason = (
                f"{ready_count} 位認為可收束，{needs_count} 位仍需討論；"
                f"提案者 {proposer or '未指定'} 狀態為 {proposer_status or '未參與'}。"
            )
            return {
                "ready_to_close": False,
                "reason": reason,
                "summary": reason,
                "decision": "",
                "status_counts": status_counts,
                "participant_status": participant_status,
            }
        summary = (
            f"多數參與者認為可收束，且提案者 {proposer or '未指定'} "
            "未要求更多討論，可以結束本議題。"
        )
        return {
            "ready_to_close": True,
            "reason": summary,
            "summary": summary,
            "decision": summary,
            "status_counts": status_counts,
            "participant_status": participant_status,
        }

    def judge_issue_via_substeps(
        self,
        *,
        issue: Dict[str, Any],
        conversation: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        issue_id = issue.get("id")

        status_resolution = (self.issue_states.get(issue_id, {}) or {}).get("resolution") or {}
        if not status_resolution.get("options"):
            decision_context = self.judgment_context(issue)
            decision_analysis = self.mediator.prepare_judgment(
                issue,
                conversation,
                decision_context=decision_context,
            )
            status_resolution = self.mediator.build_issue_result(
                status="",
                summary=decision_analysis.get("summary", ""),
                decision="",
                agreed_points=[],
                unresolved_points=decision_analysis.get("unresolved_points", []),
                new_open_questions=[],
                affected_requirement_ids=decision_analysis.get("affected_requirement_ids", []),
                needs_human=True,
                options=decision_analysis.get("options", []),
                recommendation=decision_analysis.get("recommendation", {}),
                mediator_compromise=decision_analysis.get("compromise", {}),
            )
            self.issue_states.setdefault(issue_id, {})["resolution"] = status_resolution
        best_options = []
        for idx_opt, opt in enumerate(status_resolution.get("options") or [], start=1):
            if not isinstance(opt, dict):
                continue
            best_options.append(
                {
                    "id": idx_opt,
                    "title": opt.get("summary") or opt.get("title") or "",
                    "description": opt.get("description") or opt.get("summary") or "",
                    "source": "judgment",
                }
            )
        options = {
            "best_options": best_options,
            "compromise": status_resolution.get("mediator_compromise", {}) or {},
        }

        display_issue = dict(issue)
        if not str(display_issue.get("description") or "").strip():
            display_issue["description"] = (
                status_resolution.get("summary")
                or status_resolution.get("decision")
                or issue.get("expect_outcome")
                or ""
            )
        resolution = self.collect.human_decision_on_issue(display_issue, options)
        human_status = str(resolution.get("status") or "").strip()
        if human_status != "human_decision":
            pending = self.mediator.build_issue_result(
                status="",
                summary=resolution.get("summary") or "人類暫未裁決。",
                decision="",
                agreed_points=[],
                unresolved_points=["等待人類裁決。"],
                new_open_questions=[],
                needs_human=True,
                options=status_resolution.get("options", []),
                recommendation=status_resolution.get("recommendation", {}),
                mediator_compromise=status_resolution.get("mediator_compromise", {}),
            )
            pending["artifact_updates"] = self.artifact_updates_summary(
                issue,
                conversation,
                pending,
            )
            return pending
        decision_text = str(resolution.get("decision", ""))
        affected_conflict_ids = [
            sid for sid in issue_artifact_ids(issue)
            if isinstance(sid, str) and sid.startswith(("CR-", "PAIR-", "MULTIPLE-"))
        ]
        if not affected_conflict_ids:
            affected_conflict_ids = conflict_report_resolution_ids(
                self.artifact,
                issue,
                {"affected_conflict_ids": []},
            )
        url_updates: List[Dict[str, Any]] = []
        if str(issue.get("category") or "").strip() == "resolve_conflict":
            conflict_rows = self.conflict_rows_for_issue(issue)
            url_rows = [
                row for row in (self.artifact.get("URL", []) or [])
                if isinstance(row, dict)
            ]
            by_id = {
                str(row.get("id") or "").strip(): row
                for row in url_rows
                if str(row.get("id") or "").strip()
            }
            url_updates = self.conversation_url_update_plan(conversation, by_id=by_id)
            if not url_updates:
                url_updates = self.default_conflict_url_update_plan(
                    conflict_rows,
                    target_ids=set(affected_conflict_ids),
                )

        wrapped = self.mediator.build_issue_result(
            status="human_decision",
            summary=decision_text or "本議題已升級由人類裁決。",
            decision=decision_text,
            mediator_compromise={},
            agreed_points=[decision_text] if decision_text else [],
            unresolved_points=[],
            new_open_questions=[],
            affected_conflict_ids=affected_conflict_ids,
            url_updates=url_updates,
            needs_human=True,
        )
        wrapped["human_choice"] = {
            "chosen_option_id": resolution.get("chosen_option_id", ""),
            "chosen_option_title": resolution.get("chosen_option_title", ""),
            "chosen_options": resolution.get("chosen_options", []),
        }
        wrapped["artifact_updates"] = self.artifact_updates_summary(
            issue,
            conversation,
            wrapped,
        )
        return wrapped

    def load_saved_formal_meeting_issue(
        self,
        issue: Dict[str, Any],
    ) -> Dict[str, Any]:
        from storage.artifact import load_formal_meeting_discussions

        issue_id = str(issue.get("id") or "").strip()
        formal_meeting = load_formal_meeting_discussions(self.store.artifact_dir)
        round_key = f"r{int(self.round_num or 1)}"
        rows = formal_meeting.get(round_key) if isinstance(formal_meeting, dict) else []
        search_rows = rows if isinstance(rows, list) else []
        if not search_rows and isinstance(formal_meeting, dict):
            for value in formal_meeting.values():
                if isinstance(value, list):
                    search_rows.extend(value)
        for row in search_rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("issue_id") or "").strip() == issue_id:
                conversation = row.get("conversation")
                resolution = row.get("resolution")
                if not isinstance(conversation, list):
                    raise RuntimeError(f"formal meeting record 中 {issue_id} 缺少 conversation")
                if not isinstance(resolution, dict):
                    raise RuntimeError(f"formal meeting record 中 {issue_id} 缺少 resolution")
                return row
        raise RuntimeError(f"formal meeting record 找不到 issue_id: {issue_id}")

    def save_issue_artifacts(
        self,
        *,
        issue: Dict[str, Any],
    ) -> Dict[str, Any]:
        issue_id = issue.get("id")

        proposer = (
            str(issue.get("proposed_by") or "").strip()
            or self.find_issue_proposer(issue)
            or "mediator"
        )
        issue["proposed_by"] = proposer

        meeting_record = self.load_saved_formal_meeting_issue(issue)
        meeting_id = str(meeting_record.get("meeting_id") or "").strip()
        if not meeting_id:
            raise RuntimeError(f"formal meeting record 中 {issue_id} 缺少 meeting_id")
        issue["meeting_id"] = meeting_id
        conversation = meeting_record.get("conversation") or []
        resolution = meeting_record.get("resolution") or {}
        meeting_md = self.mediator.write_meeting_note(
            issue,
            conversation,
            resolution,
            round_num=self.round_num,
            proposed_by=proposer,
        )
        meeting_filename = f"{meeting_id}.md"
        self.store.save_markdown(meeting_md, meeting_filename)

        self.update_rationale_for_issue(issue, conversation, resolution)
        self.issue_states[issue_id]["saved"] = True
        return {
            "issue_id": issue_id,
            "filename": meeting_filename,
        }

    def conversation_entry_records(self, record_entry: Dict[str, Any]) -> List[Dict[str, Any]]:
        response = record_entry.get("response") if isinstance(record_entry.get("response"), dict) else {}
        actions = [str(item).strip() for item in response.get("actions", []) if str(item).strip()]
        response_text = str(response.get("text") or "").strip()
        is_conflict_round = "discuss_conflict" in actions

        if not is_conflict_round and response_text and response_text.startswith("{") and response_text.endswith("}"):
            try:
                parsed = json.loads(response_text)
            except Exception:
                parsed = None
            else:
                if isinstance(parsed, dict) and "pair_reviews" in parsed:
                    response["text"] = "（本發言無可讀內容）"

        if not is_conflict_round:
            response.pop("pair_reviews", None)

        response_keys = (
            "actions",
            "text",
            "open_questions",
            "state",
            "proposal",
            "pair_reviews",
            "speaking_as",
            "reply_to_question",
            "reply_to_agent",
        )
        clean_response = {
            key: response.get(key)
            for key in response_keys
            if response.get(key) not in (None, "", [], {})
        }
        agent_name = record_entry.get("agent")
        agents = [agent_name]
        text_by_agent: Dict[str, str] = {}
        if agent_name == "user":
            speaking_as = clean_response.get("speaking_as")
            if isinstance(speaking_as, list) and speaking_as:
                agents = [
                    str(name).strip()
                    for name in speaking_as
                    if str(name).strip()
                ] or [agent_name]
                text_by_agent = MeetingRunner.split_speaking_as_text(
                    str(clean_response.get("text") or ""),
                    agents,
                )
                clean_response.pop("speaking_as", None)
        records = []
        for name in agents:
            if record_entry.get("round_index") not in (None, ""):
                record = {"round_index": record_entry.get("round_index")}
            else:
                record = {}
            record["agent"] = name
            actions = self.record_actions(clean_response.get("actions"))
            if actions:
                record["actions"] = actions
            response_text = text_by_agent.get(name) or str(clean_response.get("text") or "").strip()
            response_record = {"text": response_text}
            state = self.response_state(response)
            if state:
                response_record["state"] = state
            proposal = self.response_proposal(response)
            if proposal not in (None, "", [], {}):
                response_record["proposal"] = proposal
            for key in (
                "open_questions",
                "pair_reviews",
                "reply_to_question",
                "reply_to_agent",
            ):
                value = clean_response.get(key)
                if value not in (None, "", [], {}):
                    response_record[key] = value
            record["response"] = response_record
            issue_action_results = (
                response.get("issue_action_results")
                if isinstance(response.get("issue_action_results"), list)
                else []
            )
            artifacts: Dict[str, Any] = {}
            if name == "analyst":
                analysis_artifacts = self.analyst_issue_artifacts(
                    issue_action_results,
                )
                if analysis_artifacts:
                    artifacts.update(analysis_artifacts)
            if name == "expert":
                feedback = self.issue_action_result_value(
                    issue_action_results,
                    "feedback",
                )
                if isinstance(feedback, dict) and feedback:
                    artifacts["feedback"] = self.feedback_summary(feedback)
            if name == "modeler":
                system_models = self.issue_action_result_value(
                    issue_action_results,
                    "system_models",
                )
                if isinstance(system_models, list) and system_models:
                    artifacts["system_models"] = system_models
            if artifacts:
                record["artifacts"] = artifacts
            if record_entry.get("is_reply"):
                record["is_reply"] = True
            if record_entry.get("is_follow_up"):
                record["is_follow_up"] = True
            records.append(record)
        return records

    @staticmethod
    def split_speaking_as_text(text: str, names: List[str]) -> Dict[str, str]:
        source = str(text or "").strip()
        clean_names = [str(name or "").strip() for name in names or [] if str(name or "").strip()]
        if not source or not clean_names:
            return {}
        escaped = "|".join(re.escape(name) for name in clean_names)
        pattern = re.compile(rf"(?:^|\n)\s*【({escaped})】\s*")
        matches = list(pattern.finditer(source))
        if not matches:
            return {}
        parts: Dict[str, str] = {}
        for index, match in enumerate(matches):
            name = str(match.group(1) or "").strip()
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
            body = source[start:end].strip()
            body = re.sub(r"^\s*[-—]+\s*", "", body).strip()
            if name and body:
                parts[name] = body
        return parts

    @staticmethod
    def record_actions(actions: Any) -> List[str]:
        if isinstance(actions, str):
            actions = [actions]
        if not isinstance(actions, list):
            return []
        hidden = set()
        return [
            str(action).strip()
            for action in actions
            if str(action).strip() and str(action).strip() not in hidden
        ]

    @staticmethod
    def issue_action_result_value(action_results: Any, key: str) -> Any:
        if not isinstance(action_results, list):
            return None
        for row in reversed(action_results):
            if isinstance(row, dict) and row.get(key) not in (None, "", [], {}):
                return row.get(key)
        return None

    @staticmethod
    def analyst_issue_artifacts(action_results: Any) -> Dict[str, Any]:
        if not isinstance(action_results, list):
            return {}
        artifacts: Dict[str, Any] = {}
        for row in action_results:
            if not isinstance(row, dict):
                continue
            action = str(row.get("action") or "").strip()
            if action == "analyze_requirements":
                candidates = MeetingRunner.requirement_candidate_summary(
                    {"URL": row.get("URL", [])}
                )
                if candidates:
                    artifacts["URL"] = candidates
            elif action == "refine_requirement":
                req_rows = row.get("REQ")
                if isinstance(req_rows, list) and req_rows:
                    artifacts["REQ"] = MeetingRunner.system_requirement_summary(req_rows)
                reason = str(row.get("reason") or "").strip()
                if reason:
                    artifacts["requirement_reason"] = reason
            elif action == "analyze_conflicts":
                conflict_report = row.get("conflict_report")
                if conflict_report not in (None, "", [], {}):
                    artifacts["conflict_report"] = MeetingRunner.conflict_report_summary(conflict_report)
                elif isinstance(output, dict):
                    payload = output.get("conflict") if isinstance(output.get("conflict"), dict) else {}
                    report = payload.get("report")
                    if report not in (None, "", [], {}):
                        artifacts["conflict_report"] = MeetingRunner.conflict_report_summary(report)
            elif action == "refine_scope":
                scope_updates = row.get("scope_updates")
                if isinstance(scope_updates, dict) and any(scope_updates.get(key) for key in scope_updates):
                    artifacts["scope"] = scope_updates
                reason = str(row.get("reason") or "").strip()
                if reason:
                    artifacts["scope_reason"] = reason
        return artifacts

    @staticmethod
    def system_requirement_summary(rows: Any) -> List[Dict[str, Any]]:
        if not isinstance(rows, list):
            return []
        summaries: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            item: Dict[str, Any] = {}
            for key in ("id", "type", "title", "description", "priority"):
                value = row.get(key)
                if value not in (None, "", [], {}):
                    item[key] = value
            raw_source = row.get("source") or []
            if isinstance(raw_source, list):
                source = [str(value).strip() for value in raw_source if str(value).strip()]
            else:
                source = [str(raw_source).strip()] if str(raw_source or "").strip() else []
            if source:
                item["source"] = list(dict.fromkeys(source))
            for key in ("acceptance_criteria", "risks", "assumptions"):
                values = [
                    str(value).strip()
                    for value in (row.get(key) or [])
                    if str(value).strip()
                ]
                if values:
                    item[key] = values
            if item:
                summaries.append(item)
        return summaries

    @staticmethod
    def requirement_candidate_summary(output: Any) -> List[Dict[str, Any]]:
        if not isinstance(output, dict):
            return []
        rows = output.get("URL")
        if not isinstance(rows, list):
            return []
        summaries: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            item: Dict[str, Any] = {}
            for key in ("id", "text", "source"):
                value = row.get(key)
                if value not in (None, "", [], {}):
                    item[key] = value
            stakeholder = row.get("stakeholder")
            if isinstance(stakeholder, dict):
                name = str(stakeholder.get("name") or "").strip()
                if name:
                    item["stakeholder"] = name
            elif str(stakeholder or "").strip():
                item["stakeholder"] = str(stakeholder).strip()
            if "source" not in item:
                item["source"] = "meeting"
            if item.get("text"):
                summaries.append(item)
        return summaries

    @staticmethod
    def conflict_report_summary(report: Any) -> List[Dict[str, Any]]:
        if not isinstance(report, list):
            return []
        summaries: List[Dict[str, Any]] = []
        for row in report:
            if not isinstance(row, dict):
                continue
            item: Dict[str, Any] = {}
            for key in ("id", "source", "label", "type", "description", "recommended_resolution"):
                value = row.get(key)
                if value not in (None, "", [], {}):
                    item[key] = value
            requirements = []
            for req in row.get("requirements") or []:
                if not isinstance(req, dict):
                    continue
                req_item = {}
                for key in ("id", "text"):
                    value = req.get(key)
                    if value not in (None, "", [], {}):
                        req_item[key] = value
                if req_item:
                    requirements.append(req_item)
            if requirements:
                item["requirements"] = requirements
            options = []
            for option in row.get("resolution_options") or []:
                if not isinstance(option, dict):
                    continue
                option_item = {}
                for key in ("option", "description", "recommendation"):
                    value = option.get(key)
                    if value not in (None, "", [], {}):
                        option_item[key] = value
                if option_item:
                    options.append(option_item)
            if options:
                item["resolution_options"] = options
            if item:
                summaries.append(item)
        return summaries

    @staticmethod
    def feedback_summary(feedback: Any) -> Dict[str, Any]:
        if not isinstance(feedback, dict):
            return {}
        summary: Dict[str, Any] = {}
        for section in ("findings", "constraints", "risks", "recommendations"):
            rows = []
            for row in feedback.get(section) or []:
                if not isinstance(row, dict):
                    continue
                item = {}
                for key in ("text", "related_requirement_ids", "source"):
                    value = row.get(key)
                    if value not in (None, "", [], {}):
                        item[key] = value
                if item:
                    rows.append(item)
            if rows:
                summary[section] = rows
        sources = [
            str(source).strip()
            for source in (feedback.get("sources") or [])
            if str(source).strip()
        ]
        if sources:
            summary["sources"] = sources
        return summary

    @staticmethod
    def system_model_summary(system_models: Any) -> List[Dict[str, Any]]:
        if not isinstance(system_models, list):
            return []
        summaries: List[Dict[str, Any]] = []
        for model in system_models:
            if not isinstance(model, dict):
                continue
            item: Dict[str, Any] = {}
            for key in ("id", "name", "type", "description", "source"):
                value = model.get(key)
                if value not in (None, "", [], {}):
                    item[key] = value
            if str(model.get("plantuml") or "").strip():
                item["diagram_available"] = True
            if item:
                summaries.append(item)
        return summaries

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
        return result

    @staticmethod
    def action_name(action: str) -> str:
        return str(action or "").strip()

    def run_action_internal(self, action: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        action = self.action_name(action)
        params = params or {}
        obs = {"action": action, "result": None, "error": None}

        def sync_meeting_issues(issues: List[Dict[str, Any]]) -> None:
            existing = [
                row for row in (self.artifact.get("meeting_issues", []) or [])
                if isinstance(row, dict)
                and int(row.get("round") or -1) != int(self.round_num)
            ]
            self.artifact["meeting_issues"] = existing + [
                {**issue, "round": self.round_num}
                for issue in issues
                if isinstance(issue, dict)
            ]
            if self.output_artifact is not None:
                self.output_artifact["meeting_issues"] = list(self.artifact["meeting_issues"])
                self.store.save_artifact(self.output_artifact)
            self.load_meeting_issues()

        if action == "plan_issues":
            existing_issues = self.current_meeting_issues()
            if existing_issues:
                self.load_meeting_issues()
                self.log_agenda(label="沿用既有議程", issues=existing_issues)
                obs["result"] = {
                    "issues": [
                        {
                            "id": t["id"],
                            "title": t["title"],
                            "category": t.get("category", ""),
                        }
                        for t in existing_issues
                    ],
                    "count": len(existing_issues),
                    "agenda_reused": True,
                }
                return obs

            skip = set()
            for disc in self.artifact.get("discussions", []):
                for td in disc.get("issues", []):
                    for sid in trace_artifact_ids(td):
                        skip.add(sid)
            max_items = self.config.get("max_issues", 5)
            planned_issues = self.mediator.plan_issues(
                self.artifact,
                registry=self.registry,
                max_items=max_items,
                skip_source_ids=skip if skip else None,
                issue_pool=self.issue_pool,
            )
            sync_meeting_issues(planned_issues)
            issues = self.current_meeting_issues()
            self.log_agenda(
                label="產生",
                issues=issues,
                backlog_count=len(self.artifact.get("issue_backlog", []) or []),
            )
            self.issue_pool = list(self.artifact.get("issue_backlog", []) or [])
            self.issue_states = {
                t["id"]: {
                    "discussed": False,
                    "conversation": None,
                    "resolution": None,
                    "saved": False,
                }
                for t in issues
            }
            obs["result"] = {
                "issues": [
                    {
                        "id": t["id"],
                        "title": t["title"],
                        "category": t.get("category", ""),
                    }
                    for t in issues
                ],
                "count": len(issues),
            }
            return obs

        if action == "add_issues":
            issues = self.current_meeting_issues()
            issue_limit = self.config.get("max_issues", 5)
            extra_issue_count = len([issue for issue in issues if not self.is_default_issue(issue)])
            if extra_issue_count >= issue_limit:
                obs["error"] = "已達 issue 上限，無法擴充"
                return obs
            all_saved = all(
                self.issue_states.get(t["id"], {}).get("saved", False)
                for t in issues
            )
            if not all_saved:
                unsaved_ids = [
                    str(t.get("id") or "").strip()
                    for t in issues
                    if not self.issue_states.get(t.get("id", ""), {}).get("saved", False)
                ]
                obs["result"] = {
                    "added": 0,
                    "message": "尚有未存檔議題，略過追加議題",
                    "unsaved_issue_ids": [issue_id for issue_id in unsaved_ids if issue_id],
                }
                return obs
            skip = set()
            for disc in self.artifact.get("discussions", []):
                for td in disc.get("issues", []):
                    for sid in trace_artifact_ids(td):
                        skip.add(sid)
            meeting_issues_by_id = {
                str(row.get("id") or "").strip(): row
                for row in (self.artifact.get("meeting_issues", []) or [])
                if isinstance(row, dict) and str(row.get("id") or "").strip()
            }
            for rd in self.meeting_records:
                issue_ref = meeting_issues_by_id.get(str(rd.get("issue_id") or "").strip()) or {}
                for sid in trace_artifact_ids(issue_ref):
                    skip.add(sid)
            max_items = issue_limit - extra_issue_count
            new_items = self.mediator.plan_issues(
                self.artifact,
                registry=self.registry,
                max_items=max_items,
                skip_source_ids=skip if skip else None,
                issue_pool=self.issue_pool,
            )
            self.issue_pool = list(self.artifact.get("issue_backlog", []) or [])
            if not new_items:
                obs["result"] = {"added": 0, "message": "無新增議題"}
                return obs
            start_idx = len(issues) + 1
            added_issues = []
            for i, item in enumerate(new_items):
                tid = f"T-{start_idx + i}"
                new_issue = {
                    "id": tid,
                    "title": item.get("title", "待討論議題").strip(),
                    "description": item.get("description", ""),
                    "category": item.get("category", ""),
                    "participants": item.get("participants", []),
                    "discussion_mode": item.get("discussion_mode", "sequential"),
                    "discussion_rounds": item.get("discussion_rounds", 1),
                    "target_stakeholders": item.get("target_stakeholders", []),
                    "trace": normalize_trace(item.get("trace")),
                    "proposed_by": item.get("proposed_by", ""),
                    "expected_actions": item.get("expected_actions", {}),
                }
                added_issues.append(new_issue)
                self.issue_states[tid] = {
                    "discussed": False,
                    "conversation": None,
                    "resolution": None,
                    "saved": False,
                }
            sync_meeting_issues(issues + added_issues)
            self.log_agenda(label="追加", issues=added_issues)
            obs["result"] = {
                "added": len(new_items),
                "new_issues": [
                    {"id": t["id"], "title": t["title"], "category": t.get("category", "")}
                    for t in added_issues
                ],
            }
            return obs

        if action == "start_issue":
            issue_id = params.get("issue_id")
            issue = self.load_agenda_issue(issue_id)
            if not issue:
                obs["error"] = f"issue_id 不存在: {issue_id}"
                return obs
            error = self.prepare_discussion(issue)
            if error:
                obs["error"] = error
                return obs
            self.log_discussion_start(issue)
            obs["result"] = self.run_discussion(issue)
            result = obs["result"] if isinstance(obs.get("result"), dict) else {}
            self.log_discussion_done(issue_id, result)
            return obs

        if action == "resolve_issue":
            issue_id = params.get("issue_id")
            issue = self.get_issue(issue_id)
            issue_state = self.issue_states.get(issue_id, {})
            if not issue or not issue_state.get("discussed"):
                obs["error"] = f"請先對 {issue_id} 執行 start_issue"
                return obs
            conversation = issue_state.get("conversation") or []
            resolution = self.resolve_issue_via_substeps(
                issue=issue,
                conversation=conversation,
            )
            self.issue_states[issue_id]["resolution"] = resolution
            self.log_resolution_done(issue_id, resolution)
            needs_human = bool(resolution.get("needs_human"))
            obs["result"] = {
                "issue_id": issue_id,
                "status": resolution.get("status", ""),
                "summary": resolution.get("summary", ""),
                "agreed_points_count": len(resolution.get("agreed_points", []) or []),
                "unresolved_points_count": len(resolution.get("unresolved_points", []) or []),
                "needs_human": needs_human,
            }
            obs["status"] = "needs_human" if needs_human else "resolved"
            obs["issue_id"] = issue_id
            obs["summary"] = resolution.get("summary", "") or resolution.get("status", "")
            if needs_human:
                self.issue_states[issue_id]["needs_human"] = True
                self.issue_states[issue_id]["pending_resolution"] = resolution
                self.issue_states[issue_id]["resolution"] = None
            else:
                self.issue_states[issue_id]["needs_human"] = False
                self.issue_states[issue_id]["pending_resolution"] = None
                self.persist_formal_meeting_progress(
                    issue,
                    conversation=conversation,
                    resolution=resolution,
                )
            return obs

        if action == "judge_issue":
            if not self.mediator.enable_human_judgment:
                self.logger.debug("Formal meeting judge_issue disabled; running resolve_issue")
                return self.run("resolve_issue", params)
            issue_id = params.get("issue_id")
            issue = self.get_issue(issue_id)
            issue_state = self.issue_states.get(issue_id, {})
            if not issue or not issue_state.get("discussed"):
                obs["error"] = f"請先對 {issue_id} 執行 start_issue"
                return obs
            conversation = issue_state.get("conversation") or []
            self.logger.info("  進入人類裁決：%s", issue.get("title", ""))
            wrapped = self.judge_issue_via_substeps(
                issue=issue,
                conversation=conversation,
            )
            decision_text = str(wrapped.get("decision") or "")
            self.log_human_judgment_done(issue_id, decision_text)
            self.settle_requirements_after_issue(issue, conversation, wrapped)
            wrapped["artifact_updates"] = self.artifact_updates_summary(
                issue,
                conversation,
                wrapped,
            )
            self.issue_states[issue_id]["resolution"] = wrapped
            self.issue_states[issue_id]["needs_human"] = False
            self.issue_states[issue_id]["pending_resolution"] = None
            self.persist_formal_meeting_progress(
                issue,
                conversation=conversation,
                resolution=wrapped,
            )
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
            issue_state = self.issue_states.get(issue_id, {})
            if not issue or not issue_state.get("discussed"):
                obs["error"] = f"請先對 {issue_id} 執行 start_issue"
                return obs
            conversation = issue_state.get("conversation") or []
            resolution = issue_state.get("resolution")
            if not resolution:
                obs["error"] = f"請先對 {issue_id} 執行 resolve_issue 或 judge_issue，之後才能 save_issue"
                return obs
            save_result = self.save_issue_artifacts(issue=issue)
            self.log_issue_saved(issue_id, save_result)
            obs["result"] = save_result
            obs["status"] = "saved"
            obs["issue_id"] = issue_id
            obs["summary"] = f"已儲存 {issue_id} 至 {save_result.get('filename')}"
            return obs

        if action == "finish_round":
            issues = self.current_meeting_issues()
            if issues:
                unsaved_ids = [
                    t.get("id", "")
                    for t in issues
                    if not self.issue_states.get(t.get("id", ""), {}).get("saved", False)
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
        self.load_meeting_issues()
        for issue in self.current_meeting_issues():
            if issue.get("id") == issue_id:
                return issue
        return None

    def find_issue_proposer(self, issue: Dict) -> Optional[str]:
        """從 issue 的 trace.proposal_ids 反查提案者。"""
        issue_ids = set(issue_proposal_ids(issue))
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
        issue_state_rows = []
        for issue_id, issue_state in self.issue_states.items():
            issue_state_rows.append(
                {
                    "issue_id": issue_id,
                    "discussed": issue_state.get("discussed", False),
                    "resolved": issue_state.get("resolution") is not None,
                    "needs_human": bool(issue_state.get("needs_human")),
                    "resolution": (issue_state.get("resolution") or {}).get("status"),
                    "saved": issue_state.get("saved", False),
                }
            )
        issue_limit = self.config.get("max_issues", 5)
        issues = self.current_meeting_issues()
        issues_count = len(issues)
        general_issues_count = len([issue for issue in issues if not self.is_default_issue(issue)])
        backlog_count = len(self.issue_pool)
        all_saved = (
            issues_count > 0
            and all(self.issue_states.get(t["id"], {}).get("saved", False) for t in issues)
        )
        can_add_issues = general_issues_count < issue_limit and all_saved and backlog_count > 0
        human_decision_queue = [
            row for row in (self.artifact.get("human_decision_queue", []) or [])
            if isinstance(row, dict)
        ]
        return {
            "round_num": self.round_num,
            "issue_limit": issue_limit,
            "issues_count": issues_count,
            "default_issues_count": issues_count - general_issues_count,
            "general_issues_count": general_issues_count,
            "backlog_count": backlog_count,
            "all_current_issues_saved": all_saved,
            "can_add_issues": can_add_issues,
            "human_decision_status": {
                "human_decision_queue_count": len(human_decision_queue),
                "has_pending_human_decisions": bool(human_decision_queue),
            },
            "issues": [
                {
                    "schema_version": t.get("schema_version", "meeting_issue.v1"),
                    "id": t["id"],
                    "title": t["title"],
                    "category": t.get("category", ""),
                    "category_label": ISSUE_CATEGORY_LABEL.get(
                        t.get("category", ""), t.get("category", "")
                    ),
                    "trace": normalize_trace(t.get("trace")),
                }
                for t in issues
            ],
            "issue_states": issue_state_rows,
            "records_count": len(self.meeting_records),
        }

    def get_meeting_records(self) -> List[Dict]:
        return self.meeting_records

    def get_open_questions(self) -> List[Dict]:
        return self.open_questions

    def get_issue_snapshot(self) -> List[Dict]:
        self.load_meeting_issues()
        return self.current_meeting_issues()
