# Analyst requirements logic: scope, drafts, requirements, and change candidates.
from agents.profile.prompt_catalog import render_prompt
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.base import parse_json_array, parse_json_object
from storage.markdown import clean_llm_output
from storage.plantuml import plantuml_safe_name
from agents.skills.base import get_skill
from agents.profile.scenario import scenario_prompt_value, scenario_text

from .conflict_store import all_conflict_rows, conflict_entries_count
from .validation import (
    requirement_record as analyst_requirement_record,
    requirement_records,
    requirement_text as analyst_requirement_text,
    scope_payload,
)
from .requirements import requirement_discussion_pool
from .prompts import (
    build_draft_prompt,
    requirements_skill_guidance,
    url_extraction_rules,
)


def draft_stakeholders(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for stakeholder in artifact.get("stakeholders", []) or []:
        if not isinstance(stakeholder, dict):
            continue
        name = str(stakeholder.get("name") or "").strip()
        if not name:
            continue
        row = {"name": name}
        stakeholder_type = str(stakeholder.get("type") or "").strip()
        if stakeholder_type:
            row["type"] = stakeholder_type
        text = stakeholder.get("text")
        if isinstance(text, list):
            clean_texts = [
                str(item).strip()
                for item in text
                if str(item).strip()
            ]
            if clean_texts:
                row["text"] = clean_texts
        elif str(text or "").strip():
            row["text"] = str(text).strip()
        rows.append(row)
    return rows


def draft_open_questions(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()

    for question in artifact.get("open_questions", []) or []:
        if not isinstance(question, dict):
            continue
        text = str(question.get("question") or "").strip()
        if not text:
            continue
        qid = str(question.get("id") or "").strip()
        if qid:
            seen_ids.add(qid)
        row = {"question": text}
        for key in ("id", "to", "status", "source", "type"):
            value = question.get(key)
            if value:
                row[key] = value
        rows.append(row)
    return rows


def draft_feedback(artifact: Dict[str, Any]) -> Dict[str, Any]:
    feedback = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
    req_rows = [row for row in (artifact.get("REQ") or []) if isinstance(row, dict)]
    formalized_sources = set()
    formalized_text = ""
    for req in req_rows:
        for key in ("source_ids", "source_meeting"):
            for value in req.get(key) or []:
                value_text = str(value).strip()
                if value_text:
                    formalized_sources.add(value_text)
        text_parts = []
        for key in ("title", "description", "rationale", "constraint_type", "impact"):
            value = str(req.get(key) or "").strip()
            if value:
                text_parts.append(value)
        for key in ("risks", "assumptions", "acceptance_criteria"):
            for value in req.get(key) or []:
                value_text = str(value).strip()
                if value_text:
                    text_parts.append(value_text)
        formalized_text += "\n" + "\n".join(text_parts)

    def is_formalized_feedback(item: Dict[str, Any], text: str) -> bool:
        item_id = str(item.get("id") or "").strip()
        source = str(item.get("source") or "").strip()
        related = {
            str(value).strip()
            for value in (item.get("related_requirement_ids") or [])
            if str(value).strip()
        }
        if item_id and item_id in formalized_sources:
            return True
        if source and source in formalized_sources:
            return True
        if related and related.issubset(formalized_sources):
            return True
        compact_text = re.sub(r"\s+", "", text)
        compact_formalized = re.sub(r"\s+", "", formalized_text)
        return bool(compact_text and compact_text in compact_formalized)

    out: Dict[str, Any] = {}
    for section in ("findings", "constraints", "risks", "recommendations"):
        rows: List[Dict[str, Any]] = []
        for item in feedback.get(section) or []:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            if is_formalized_feedback(item, text):
                continue
            row: Dict[str, Any] = {"text": text}
            related = item.get("related_requirement_ids")
            if isinstance(related, list):
                related_rows = [str(value).strip() for value in related if str(value).strip()]
                if related_rows:
                    row["related_requirement_ids"] = related_rows
            source = str(item.get("source") or "").strip()
            if source:
                row["source"] = source
            rows.append(row)
        if rows:
            out[section] = rows
    sources = [
        str(source).strip()
        for source in (feedback.get("sources") or [])
        if str(source).strip()
    ]
    if sources:
        out["sources"] = sources
    return out


def draft_meeting_context(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for discussion in artifact.get("discussions", []) or []:
        if not isinstance(discussion, dict):
            continue
        round_num = discussion.get("round")
        for issue in discussion.get("issues", []) or []:
            if not isinstance(issue, dict):
                continue
            row: Dict[str, Any] = {
                "round": round_num,
                "meeting_id": issue.get("meeting_id"),
                "issue_id": issue.get("issue_id"),
            }
            conversation = []
            for entry in issue.get("conversation", []) or []:
                if not isinstance(entry, dict):
                    continue
                response = entry.get("response") if isinstance(entry.get("response"), dict) else {}
                text = str(response.get("text") or "").strip()
                if not text:
                    continue
                item = {
                    "agent": entry.get("agent"),
                    "actions": entry.get("actions", []) or [],
                    "text": text,
                }
                if entry.get("is_reply"):
                    item["is_reply"] = True
                    item["reply_to_question"] = response.get("reply_to_question")
                    item["reply_to_agent"] = response.get("reply_to_agent")
                action_results = response.get("action_results")
                if isinstance(action_results, list) and action_results:
                    item["action_results"] = action_results
                conversation.append(item)
            if conversation:
                row["conversation"] = conversation
            resolution = issue.get("resolution") if isinstance(issue.get("resolution"), dict) else {}
            if resolution:
                row["resolution"] = {
                    "resolution_status": resolution.get("resolution_status"),
                    "summary": resolution.get("summary"),
                    "decision": resolution.get("decision"),
                    "affected_requirement_ids": resolution.get("affected_requirement_ids", []) or [],
                    "affected_conflict_ids": resolution.get("affected_conflict_ids", []) or [],
                    "new_open_questions": resolution.get("new_open_questions", []) or [],
                    "artifact_updates": resolution.get("artifact_updates", {}) or {},
                }
            if row.get("conversation") or row.get("resolution"):
                rows.append(row)
    return rows


def draft_system_models(
    artifact: Dict[str, Any],
    artifact_dir: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    type_labels = {
        "context_diagram": "Context Diagram",
        "use_case_diagram": "Use Case Diagram",
        "activity_diagram": "Activity Diagram",
        "sequence_diagram": "Sequence Diagram",
        "state_machine": "State Machine Diagram",
        "class_diagram": "Class Diagram",
    }
    artifact_path = Path(artifact_dir) if artifact_dir else None
    rows: List[Dict[str, Any]] = []
    for model in artifact.get("system_models", []) or []:
        if not isinstance(model, dict):
            continue
        model_type = str(model.get("type") or "").strip()
        name = str(model.get("name") or "").strip()
        if not model_type and not name:
            continue
        row: Dict[str, Any] = {}
        if name:
            row["name"] = name
        if model_type:
            row["type"] = model_type
            row["display_type"] = type_labels.get(
                model_type,
                model_type.replace("_", " ").title(),
            )
        description = str(model.get("description") or "").strip()
        if model_type == "use_case_diagram":
            description = ""
        if description:
            row["description"] = description
        if model.get("text"):
            row["text"] = model.get("text")
        plantuml = str(model.get("plantuml") or "").strip()
        row["has_plantuml"] = bool(plantuml)
        if row["has_plantuml"] and artifact_path:
            filename = f"{plantuml_safe_name(model)}.png"
            if (artifact_path / "models" / filename).is_file():
                row["image_path"] = f"../models/{filename}"
        if row["has_plantuml"] and not row.get("image_path"):
            row["plantuml"] = plantuml
        rows.append(row)
    return rows


def draft_requirement_id_issues(md: str, expected_ids: set[str]) -> tuple[List[str], List[str]]:
    draft_req_ids = set(re.findall(r"\bURL-\d+\b", md or ""))
    unknown_ids = sorted(draft_req_ids - expected_ids)
    missing_ids = sorted(expected_ids - draft_req_ids)
    return unknown_ids, missing_ids


class AnalystRequirements:
    def run_requirements_analyst(
        self,
        action: str,
        *,
        rough_idea: str = "",
        stakeholders: Optional[List[Dict]] = None,
        artifact: Optional[Dict[str, Any]] = None,
        draft_version: Optional[int] = None,
        previous_draft: Optional[str] = None,
        conflict_report_md: str = "",
        round_num: Optional[int] = None,
        artifact_dir: Optional[Any] = None,
    ):
        """requirements-analyst skill 統一入口。

        action:
            "analyze_scenario"        -> 回傳 str (scenario)
            "define_scope"          -> 回傳 Dict (scope)
            "analyze_requirements"    -> 回傳 Dict (requirements list)
            "create_draft"          -> 回傳 str  (Markdown)
            "update_draft"          -> 回傳 str  (Markdown)
        """
        allowed_actions = {
            "analyze_scenario",
            "define_scope",
            "analyze_requirements",
            "create_draft",
            "update_draft",
        }
        if action not in allowed_actions:
            raise ValueError(f"未知 requirements action: {action}")
        opa = self.run_action_loop(
            name="requirements_analysis",
            context={
                "requirements_action": action,
                "rough_idea": rough_idea,
                "stakeholders": stakeholders or [],
                "artifact": artifact or {},
                "version": draft_version,
                "previous_draft": previous_draft,
                "conflict_report_md": conflict_report_md,
                "round_num": round_num,
                "artifact_dir": artifact_dir,
            },
            build_observation=self.build_requirements_analysis_observation,
            decide_action=self.decide_requirements_analysis_action,
            execute_action=self.execute_requirements_analysis_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("error"))
        return result.get("output")

    def build_requirements_analysis_observation(self, **kwargs: Any) -> Dict[str, Any]:
        artifact = kwargs.get("artifact") or {}
        stakeholders = kwargs.get("stakeholders") or []
        return {
            "action": kwargs.get("requirements_action", ""),
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs["max_iterations"],
            "stakeholder_count": len(stakeholders),
            "requirements_count": len(requirement_discussion_pool(artifact)),
            "conflicts_count": conflict_entries_count(artifact),
            "has_scope": bool(artifact.get("scope")),
        }

    def decide_requirements_analysis_action(
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
                "reasoning": "上一輪需求分析任務已完成，結束本次 requirements analysis。",
            }
        action = str(observation.get("action") or "").strip()
        return {
            "action": action,
            "params": {},
            "reasoning": f"執行 Analyst requirements analysis 任務：{action}。",
        }

    def execute_requirements_analysis_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        action = str(decision.get("action") or "").strip()
        try:
            if action == "analyze_scenario":
                output = self.analyze_scenario(kwargs.get("rough_idea", ""))
            elif action == "define_scope":
                output = self.define_scope(
                    kwargs.get("rough_idea", ""),
                    kwargs.get("stakeholders") or [],
                    artifact=kwargs.get("artifact") or {},
                )
            elif action == "analyze_requirements":
                output = self.analyze_requirements(kwargs.get("stakeholders") or [])
            elif action in {"create_draft", "update_draft"}:
                output = self.create_draft(
                    kwargs.get("artifact") or {},
                    draft_version=kwargs.get("version"),
                    previous_draft=kwargs.get("previous_draft"),
                    conflict_report_md=kwargs.get("conflict_report_md") or "",
                    round_num=kwargs.get("round_num"),
                    artifact_dir=kwargs.get("artifact_dir"),
                    mode="update" if action == "update_draft" else "create",
                )
            else:
                raise ValueError(f"未知 requirements action: {action}")
        except Exception as e:
            return {
                "action": action,
                "status": "failed",
                "error": str(e),
                "summary": f"requirements analysis failed: {action}",
            }
        return {
            "action": action,
            "status": "success",
            "output": output,
            "summary": f"完成 requirements analysis: {action}",
        }

    @staticmethod
    def requirement_text(text: str) -> str:
        return analyst_requirement_text(text)

    @staticmethod
    def requirement_record(
        req: Dict[str, Any],
    ) -> Dict[str, Any]:
        return analyst_requirement_record(req)

    def analyze_scenario(self, rough_idea: str) -> str:
        context = {"rough_idea": rough_idea}
        task = render_prompt('agents_profile_analyst_analyze_task_11', **locals())
        try:
            data = self.invoke_direct_requirements_object_json(
                task,
                context,
                action="requirements.scenario",
            )
        except Exception as e:
            raise RuntimeError(f"scenario 分析失敗: {e}") from e
        scenario = data.get("scenario") if isinstance(data, dict) and "scenario" in data else data
        name = scenario_text(scenario)
        if not name:
            raise ValueError("scenario 分析未產生有效 name")
        return name

    def define_scope(
        self, rough_idea: str, stakeholders: List[Dict],
        *, artifact: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        context: Dict[str, Any] = {}
        if artifact:
            if artifact.get("scenario"):
                context["scenario"] = scenario_prompt_value(artifact["scenario"])
            elif rough_idea:
                context["scenario"] = scenario_prompt_value(rough_idea)
            if artifact.get("scope"):
                context["current_scope"] = artifact["scope"]
            req_pool = requirement_discussion_pool(artifact)
            if req_pool:
                context["user_requirements"] = req_pool
        task = render_prompt('agents_profile_analyst_analyze_task_12', **locals())
        try:
            data = self.invoke_direct_requirements_object_json(
                task,
                context,
                action="requirements.scope",
            )
        except Exception as e:
            raise RuntimeError(f"scope 生成失敗: {e}") from e
        scope = data.get("scope") or {}
        return scope_payload(scope)

    def analyze_requirements(self, stakeholders: List[Dict]) -> Dict[str, Any]:
        all_requirements = []
        for idx, one_sh in enumerate(stakeholders):
            sh_label = str(one_sh.get("name") or "").strip()
            if not sh_label:
                raise ValueError(f"stakeholder 缺少 name，無法進行需求分析: index={idx}")
            sh_texts = one_sh.get("text") or []
            if isinstance(sh_texts, list):
                source_texts = [str(text).strip() for text in sh_texts if str(text).strip()]
            else:
                source_text = str(sh_texts or "").strip()
                source_texts = [source_text] if source_text else []
            for source_idx, source_text in enumerate(source_texts, 1):
                existing_requirements_json = json.dumps(
                    [
                        {
                            "id": str(row.get("id") or "").strip(),
                            "text": str(row.get("text") or "").strip(),
                            "stakeholder": (
                                str((row.get("stakeholder") or {}).get("name") or "").strip()
                                if isinstance(row.get("stakeholder"), dict)
                                else str(row.get("stakeholder") or "").strip()
                            ),
                            "source": str(row.get("source") or "").strip(),
                        }
                        for row in all_requirements
                        if isinstance(row, dict) and str(row.get("text") or "").strip()
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
                context = {
                    "stakeholder": {
                        "name": sh_label,
                        "type": one_sh.get("type"),
                        "source_text": source_text,
                        "all_text": source_texts,
                    },
                    "existing_requirements": existing_requirements_json,
                }
                extraction_rules = url_extraction_rules()
                task = render_prompt('agents_profile_analyst_analyze_task_13', **locals())
                try:
                    data = self.invoke_requirements_analyst_array_json(task, context, mode="analysis")
                except Exception as e:
                    try:
                        raw = self.invoke_requirements_analyst_text(task, context, mode="analysis")
                        repair_task = render_prompt('agents_profile_analyst_analyze_repair_task_27', **locals())
                        data = self.invoke_direct_requirements_array_json(
                            repair_task,
                            context={},
                            action="requirements.analysis.repair",
                        )
                    except Exception:
                        raise RuntimeError(f"需求分析失敗（{sh_label}#{source_idx}）: {e}") from e
                raw_rows = data if isinstance(data, list) else []
                normalized_rows = [
                    row for row in requirement_records([
                        {
                            **row,
                            "stakeholder": {
                                "name": sh_label,
                                "type": one_sh.get("type"),
                            },
                            "source": "initial",
                        }
                        for row in raw_rows
                        if isinstance(row, dict)
                    ])
                    if row.get("stakeholder") and row.get("source")
                ]
                existing_texts = {
                    str(row.get("text") or "").strip().lower()
                    for row in all_requirements
                    if isinstance(row, dict) and str(row.get("text") or "").strip()
                }
                for row in normalized_rows:
                    text = str(row.get("text") or "").strip()
                    if not text or text.lower() in existing_texts:
                        continue
                    all_requirements.append(row)
                    existing_texts.add(text.lower())

        return {"URL": all_requirements}

    def create_draft(
        self,
        artifact: Dict[str, Any],
        draft_version: Optional[int] = None,
        previous_draft: Optional[str] = None,
        conflict_report_md: str = "",
        round_num: Optional[int] = None,
        artifact_dir: Optional[Any] = None,
        mode: str = "create",
    ) -> str:
        mode = "update" if str(mode or "").strip() == "update" else "create"
        user_requirements = requirement_discussion_pool(artifact)
        for req in user_requirements:
            req_norm = self.requirement_record(req)
            req.update(req_norm)

        scope = artifact.get("scope", {}) or {}
        context = {
            "scope": scope,
            "stakeholders": draft_stakeholders(artifact),
            "user_requirements": user_requirements,
            "conflict_report": (conflict_report_md or "").strip(),
            "open_questions": draft_open_questions(artifact),
            "feedback": draft_feedback(artifact),
            "meeting_context": draft_meeting_context(artifact),
            "REQ": artifact.get("REQ", []) or [],
            "system_models": draft_system_models(artifact, artifact_dir=artifact_dir),
            "version": draft_version if draft_version is not None else 0,
        }
        if mode == "create":
            context["rough_idea"] = str(artifact.get("rough_idea") or "").strip()
            context["scenario"] = scenario_prompt_value(artifact.get("scenario", ""))
        previous_draft_text = (previous_draft or "").strip()
        if mode == "update":
            context["previous_draft"] = previous_draft_text
        version_note = ""
        if draft_version is not None:
            version_note = f" 本稿版本: draft_v{draft_version}。"
        if round_num is not None:
            version_note += f" 對應輪次: Round {round_num}。"
        task = build_draft_prompt(
            mode=mode,
            version_note=version_note,
            version=draft_version if draft_version is not None else 0,
        )
        try:
            raw = self.invoke_direct_requirements_text(
                task,
                context,
                action="requirements.draft",
            )
        except Exception as e:
            raise RuntimeError(f"draft 生成失敗: {e}") from e
        md = clean_llm_output(raw)
        expected_ids = {
            str(req.get("id") or "").strip()
            for req in user_requirements
            if isinstance(req, dict) and str(req.get("id") or "").strip()
        }
        unknown_ids, missing_ids = draft_requirement_id_issues(md, expected_ids)
        if unknown_ids:
            self.logger.warning("draft 包含 User Requirements 以外的需求 ID: %s", unknown_ids)
        if missing_ids:
            self.logger.warning("draft 未保留部分 User Requirements ID: %s", missing_ids)
        if unknown_ids or missing_ids:
            repair_task = render_prompt('agents_profile_analyst_analyze_repair_task_28', **locals())
            try:
                repaired = self.invoke_direct_requirements_text(
                    repair_task,
                    context,
                    action="requirements.draft.repair",
                )
                md = clean_llm_output(repaired)
                unknown_ids, missing_ids = draft_requirement_id_issues(md, expected_ids)
            except Exception as e:
                raise RuntimeError(f"draft 修復失敗: {e}") from e
            if unknown_ids or missing_ids:
                raise RuntimeError(
                    f"draft 修復後仍不符合 URL 覆蓋契約；unknown={unknown_ids}; missing={missing_ids}"
                )

        return md

    def invoke_requirements_analyst_text(
        self, task: str, context: Dict[str, Any], *, mode: str = "analysis"
    ) -> str:
        self.validate_skill_usage("requirements-analyst")
        skill = get_skill("requirements-analyst")
        skill_content = str(skill.get("content") or "")
        selected_guidance = requirements_skill_guidance(skill_content, mode)
        prompt = (
            "# Skill: requirements-analyst\n\n"
            f"{selected_guidance}\n\n"
            "# 任務\n\n"
            f"{task}"
        )
        messages = self.build_direct_messages(prompt, context=context)
        if self.tools:
            return self.chat_with_tools(messages, active_skill="requirements-analyst")
        return self.model.chat(messages, action=self.usage_action("skill.requirements-analyst"))

    def invoke_requirements_analyst_object_json(
        self, task: str, context: Dict[str, Any], *, mode: str = "analysis"
    ) -> Dict[str, Any]:
        raw = self.invoke_requirements_analyst_text(task, context, mode=mode)
        return parse_json_object(raw)

    def invoke_requirements_analyst_array_json(
        self, task: str, context: Dict[str, Any], *, mode: str = "analysis"
    ) -> List[Any]:
        raw = self.invoke_requirements_analyst_text(task, context, mode=mode)
        return parse_json_array(raw)

    def invoke_direct_requirements_text(
        self, task: str, context: Dict[str, Any], *, action: str
    ) -> str:
        messages = self.build_direct_messages(task, context=context)
        return self.model.chat(messages, action=self.usage_action(action))

    def invoke_direct_requirements_object_json(
        self, task: str, context: Dict[str, Any], *, action: str
    ) -> Dict[str, Any]:
        raw = self.invoke_direct_requirements_text(task, context, action=action)
        return parse_json_object(raw)

    def invoke_direct_requirements_array_json(
        self, task: str, context: Dict[str, Any], *, action: str
    ) -> List[Any]:
        raw = self.invoke_direct_requirements_text(task, context, action=action)
        return parse_json_array(raw)
