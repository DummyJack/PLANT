# Handles module workflow behavior.
import json
from typing import Any, Dict, List, Optional

from agents.base import parse_json_object
from agents.skills.base import get_skill

from .conflicts import conflict_entries_count
from .actions.reqt.extract import extract_requirement
from .validation import (
    requirement_record as analyst_requirement_record,
    requirement_records,
    requirement_text as analyst_requirement_text,
    validate_elicited_reqts,
)
from storage.requirements import requirement_discussion_pool
from .rules import url_extraction_rules
from .actions.scenario import name_scenario
from .actions.reqt.analyze import analyze_requirement
from .repair import render_repair_prompt
from .skill import requirements_skill_guidance, requirements_skill_prompt


# ========
# Defines AnalystRequirements class for this module workflow.
# ========
class AnalystRequirements:
    # Defines run requirements analyst function for this module workflow.
    def run_requirements_analyst(
        self,
        action: str,
        *,
        rough_idea: str = "",
        stakeholders: Optional[List[Dict]] = None,
        artifact: Optional[Dict[str, Any]] = None,
        draft_version: Optional[int] = None,
        previous_draft: Optional[str] = None,
        round_num: Optional[int] = None,
        artifact_dir: Optional[Any] = None,
    ):
        allowed_actions = {
            "analyze_scenario",
            "generate_scope",
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
                "round_num": round_num,
                "artifact_dir": artifact_dir,
            },
            obs_fn=self.obs_requirements_analysis,
            decide_action=self.decide_requirements_analysis_action,
            execute_action=self.execute_requirements_analysis_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("error"))
        return result.get("output")

    # Defines obs requirements analysis function for this module workflow.
    def obs_requirements_analysis(self, **kwargs: Any) -> Dict[str, Any]:
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

    # Defines decide requirements analysis action function for this module workflow.
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

    # Defines execute requirements analysis action function for this module workflow.
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
            elif action == "generate_scope":
                output = self.generate_scope(
                    kwargs.get("rough_idea", ""),
                    kwargs.get("stakeholders") or [],
                    artifact=kwargs.get("artifact") or {},
                )
            elif action == "analyze_requirements":
                output = self.analyze_requirements(kwargs.get("stakeholders") or [])
            elif action == "create_draft":
                output = self.create_draft(
                    kwargs.get("artifact") or {},
                    draft_version=kwargs.get("version"),
                    round_num=kwargs.get("round_num"),
                    artifact_dir=kwargs.get("artifact_dir"),
                )
            elif action == "update_draft":
                output = self.update_draft(
                    kwargs.get("artifact") or {},
                    draft_version=kwargs.get("version"),
                    previous_draft=kwargs.get("previous_draft"),
                    round_num=kwargs.get("round_num"),
                    artifact_dir=kwargs.get("artifact_dir"),
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
    # Defines requirement text function for this module workflow.
    def requirement_text(text: str) -> str:
        return analyst_requirement_text(text)

    @staticmethod
    # Defines requirement record function for this module workflow.
    def requirement_record(
        req: Dict[str, Any],
    ) -> Dict[str, Any]:
        return analyst_requirement_record(req)

    # Defines analyze scenario function for this module workflow.
    def analyze_scenario(self, rough_idea: str) -> str:
        context = {"rough_idea": rough_idea}
        task = name_scenario()
        try:
            data = self.invoke_direct_requirements_object_json(
                task,
                context,
                action="requirements.scenario",
            )
        except Exception as e:
            raise RuntimeError(f"scenario 分析失敗: {e}") from e
        scenario_definition = (
            data.get("scenario_definition")
            if isinstance(data, dict) and isinstance(data.get("scenario_definition"), dict)
            else {}
        )
        scenario = scenario_definition.get("name")
        name = str(scenario or "").strip()
        if not name:
            raise ValueError("scenario 分析未產生有效 name")
        return name

    # Defines analyze requirements function for this module workflow.
    def analyze_requirements(self, stakeholders: List[Dict]) -> List[Dict[str, Any]]:
        all_requirements = []
        for idx, one_sh in enumerate(stakeholders):
            sh_label = str(one_sh.get("name") or "").strip()
            if not sh_label:
                raise ValueError(f"stakeholder 缺少 name，無法進行需求分析: index={idx}")
            sh_texts = one_sh.get("text") or []
            if isinstance(sh_texts, list):
                source_rows = []
                for item in sh_texts:
                    if isinstance(item, dict):
                        statement_text = str(
                            item.get("text")
                            or item.get("statement")
                            or item.get("content")
                            or item.get("description")
                            or ""
                        ).strip()
                        statement_id = str(item.get("id") or item.get("statement_id") or "").strip()
                    else:
                        statement_text = str(item or "").strip()
                        statement_id = ""
                    if statement_text:
                        source_rows.append({"id": statement_id, "text": statement_text})
            else:
                source_text = str(sh_texts or "").strip()
                source_rows = [{"id": "", "text": source_text}] if source_text else []
            source_texts = [row["text"] for row in source_rows]
            for source_idx, source_row in enumerate(source_rows, 1):
                source_text = source_row["text"]
                source_id = source_row["id"]
                context = {
                    "stakeholder": {
                        "name": sh_label,
                        "type": one_sh.get("type"),
                        "source_text": source_text,
                        "all_text": source_texts,
                    },
                    "existing_requirements": [
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
                }
                extraction_rules = url_extraction_rules()
                task = analyze_requirement(
                    extraction_rules=extraction_rules,
                )
                try:
                    data = self.requirement_candidates_payload(
                        self.invoke_requirements_analyst_object_json(task, context, mode="analysis"),
                        action_name="analyze_requirements",
                    )
                except Exception as e:
                    try:
                        raw = self.invoke_requirements_analyst_text(task, context, mode="analysis")
                        repair_task = render_repair_prompt('url_repair', raw=raw)
                        data = self.requirement_candidates_payload(
                            self.invoke_direct_requirements_object_json(
                                repair_task,
                                context={},
                                action="requirements.analysis.repair",
                            ),
                            action_name="analyze_requirements repair",
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
                            "source_id": source_id,
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

        return all_requirements

    @staticmethod
    # Defines requirement candidates payload function for this module workflow.
    def requirement_candidates_payload(data: Any, *, action_name: str) -> List[Dict[str, Any]]:
        if not isinstance(data, dict) or not isinstance(data.get("requirement_candidates"), list):
            raise ValueError(f"{action_name} output must contain requirement_candidates list")
        return data["requirement_candidates"]

    # Defines invoke requirements analyst text function for this module workflow.
    def invoke_requirements_analyst_text(
        self,
        task: str,
        context: Dict[str, Any],
        *,
        mode: str = "analysis",
        use_tools: bool = False,
    ) -> str:
        self.validate_skill_usage("requirements-analyst")
        skill = get_skill("requirements-analyst")
        skill_content = str(skill.get("content") or "")
        selected_guidance = requirements_skill_guidance(skill_content, mode)
        prompt = requirements_skill_prompt(
            selected_guidance=selected_guidance,
            task=task,
        )
        messages = self.build_direct_messages(prompt, context=context)
        if self.tools and use_tools:
            return self.chat_with_tools(messages, active_skill="requirements-analyst")
        return self.model.chat(messages, action=self.usage_action("skill.requirements-analyst"))

    # Defines invoke requirements analyst object json function for this module workflow.
    def invoke_requirements_analyst_object_json(
        self, task: str, context: Dict[str, Any], *, mode: str = "analysis"
    ) -> Dict[str, Any]:
        use_tools = "artifact_query" in getattr(self, "tools", {})
        raw = self.invoke_requirements_analyst_text(
            task,
            context,
            mode=mode,
            use_tools=use_tools,
        )
        return parse_json_object(raw)

    # Defines invoke direct requirements text function for this module workflow.
    def invoke_direct_requirements_text(
        self, task: str, context: Dict[str, Any], *, action: str
    ) -> str:
        messages = self.build_direct_messages(task, context=context)
        return self.model.chat(messages, action=self.usage_action(action))

    # Defines invoke direct requirements object json function for this module workflow.
    def invoke_direct_requirements_object_json(
        self, task: str, context: Dict[str, Any], *, action: str
    ) -> Dict[str, Any]:
        raw = self.invoke_direct_requirements_text(task, context, action=action)
        return parse_json_object(raw)

# ========
# Defines AnalystElicitation class for this module workflow.
# ========
class AnalystElicitation:
    # Defines extract elicited reqts function for this module workflow.
    def extract_elicited_reqts(
        self,
        stakeholders: List[Dict[str, str]],
        existing_requirements: List[Dict[str, Any]],
        *,
        mode: str = "oracle",
        scenario: Any = None,
        source: str = "",
    ) -> List[Dict[str, Any]]:
        opa = self.run_action_loop(
            name="extract_reqts",
            context={
                "elicitation_action": "extract_elicited_reqts",
                "stakeholders": stakeholders,
                "existing_requirements": existing_requirements,
                "mode": mode,
                "scenario": scenario or "",
                "source": source,
            },
            obs_fn=self.obs_elicitation,
            decide_action=self.decide_elicitation_action,
            execute_action=self.execute_elicitation_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("error"))
        output = result.get("output")
        if not isinstance(output, list):
            raise RuntimeError("elicited requirement extraction output must be requirement_candidates list")
        return output

    # Defines obs elicitation function for this module workflow.
    def obs_elicitation(self, **kwargs: Any) -> Dict[str, Any]:
        return {
            "action": kwargs.get("elicitation_action", ""),
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs["max_iterations"],
            "stakeholder_count": len(kwargs.get("stakeholders") or []),
            "existing_requirement_count": len(kwargs.get("existing_requirements") or []),
            "mode": kwargs.get("mode", "oracle"),
        }

    # Defines decide elicitation action function for this module workflow.
    def decide_elicitation_action(
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
                "reasoning": "上一輪 elicitation extraction 已完成，結束本次候選需求抽取。",
            }
        return {
            "action": str(observation.get("action") or ""),
            "params": {},
            "reasoning": "從 requirement elicitation 討論中抽取可追蹤、可驗收的需求候選。",
        }

    # Defines execute elicitation action function for this module workflow.
    def execute_elicitation_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        action = str(decision.get("action") or "").strip()
        try:
            if action != "extract_elicited_reqts":
                raise ValueError(f"未知 elicitation action: {action}")
            output = self.parse_elicited_reqts(
                kwargs.get("stakeholders") or [],
                kwargs.get("existing_requirements") or [],
                mode=kwargs.get("mode", "oracle"),
                scenario=kwargs.get("scenario") or "",
                source=kwargs.get("source") or "",
            )
        except Exception as e:
            return {
                "action": action,
                "error": str(e),
                "summary": f"elicitation extraction failed: {action}",
            }
        return {
            "action": action,
            "status": "success",
            "output": output,
            "summary": "完成 elicitation extraction",
        }

    # Defines parse elicited reqts function for this module workflow.
    def parse_elicited_reqts(
        self,
        stakeholders: List[Dict[str, str]],
        existing_requirements: List[Dict[str, Any]],
        *,
        mode: str = "oracle",
        scenario: Any = None,
        source: str = "",
    ) -> List[Dict[str, Any]]:
        mode_name = str(mode or "oracle").strip().lower()
        scenario_json = json.dumps(str(scenario or "").strip(), ensure_ascii=False, indent=2)
        stakeholder_rows = [
            {
                "name": str(row.get("name") or "").strip(),
                "type": str(row.get("type") or "").strip(),
                "text": str(row.get("text") or "").strip(),
                "source_id": str(row.get("source_id") or "").strip(),
            }
            for row in (stakeholders or [])
            if isinstance(row, dict)
            and str(row.get("name") or "").strip()
            and str(row.get("text") or "").strip()
        ]
        existing_rows = [
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
            for row in (existing_requirements or [])
            if isinstance(row, dict) and str(row.get("text") or "").strip()
        ]
        rules = f"{url_extraction_rules()}\n\n"
        mapped: List[Dict[str, Any]] = []
        for stakeholder_row in stakeholder_rows:
            prompt = extract_requirement(
                scenario_json=scenario_json,
                stakeholder_row=stakeholder_row,
                existing_rows=existing_rows,
                mode_name=mode_name,
                rules=rules,
            )
            raw_text = self.invoke_requirements_analyst_text(
                prompt,
                {},
                mode="analysis",
            )
            try:
                raw = self.requirement_candidates_payload(
                    parse_json_object(raw_text),
                    action_name="extract_elicited_reqts",
                )
            except ValueError as first_error:
                repair_prompt = render_repair_prompt('extract_repair', raw_text=raw_text)
                repaired = self.model.chat(
                    self.build_direct_messages(repair_prompt),
                    action="extract_repair",
                ) or ""
                try:
                    raw = self.requirement_candidates_payload(
                        parse_json_object(repaired),
                        action_name="extract_elicited_reqts repair",
                    )
                except ValueError as repair_error:
                    raw_preview = str(raw_text or "").strip().replace("\n", "\\n")[:500]
                    raise ValueError(
                        f"elicitation extraction output must contain requirement_candidates: {first_error}; "
                        f"repair failed: {repair_error}; raw_preview={raw_preview}"
                    ) from repair_error
            for row in raw:
                if not isinstance(row, dict):
                    continue
                mapped.append({
                    "text": row.get("text"),
                    "stakeholder": {
                        "name": stakeholder_row["name"],
                        "type": stakeholder_row.get("type") or "",
                    },
                    "source": source or "elicitation",
                    "source_id": stakeholder_row.get("source_id") or "",
                })
        return validate_elicited_reqts(mapped)
