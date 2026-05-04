# Modeler agent: UML model generation, model updates, and topic response.
import json
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent, modeler_review_field_language, short_reasoning_line

from .modeling import ModelerModeling
from .topics import ModelerTopics


MODELER_ROLE_PROMPT = """你是 UML 系統建模專家，負責把需求轉成可驗證、可追溯的 UML 模型。

規則：
1. 精煉時只改受影響部分，保留未變動元素。
2. 不直接改需求語意；發現不一致時只指出影響、缺口與待確認事項。
3. 資訊不足時用 to_confirm 標示，不可臆造。"""


MODELER_LOOP_ACTIONS = [
    "build_full_model",
    "assess_impact",
    "update_diagram",
    "validate_diagram",
    "fix_diagram",
    "done",
]


AVAILABLE_MODEL_TYPES = [
    "context_diagram",
    "use_case_diagram",
    "activity_diagram",
    "data_flow_diagram",
    "sequence_diagram",
    "state_machine_diagram",
    "class_diagram",
]

ALL_MODEL_TYPES = AVAILABLE_MODEL_TYPES

MODEL_SELECTION_RULES = """- 所有 diagram type 都不是必產生；只在模型能幫助需求理解、驗證或追溯時才建立或更新。
- 不從模型反推新增需求，也不可把 open_questions / pending candidates 畫成正式模型內容。
- 資訊不足時不要畫死，改在 gaps、to_confirm 或 assumptions 說明。
- Context / Use Case / Activity / Data Flow 可用於呈現系統邊界、角色互動、流程或資料流。
- Sequence Diagram 只在互動順序會影響需求理解時建立。
- State Machine Diagram 只在需求已有明確生命週期或狀態轉換時建立。
- Class Diagram 若建立，只能作為 tentative domain model，不可當成設計模型。"""


class ModelerAgent(
    ModelerModeling,
    ModelerTopics,
    BaseAgent,
):
    """系統建模 Agent — 產生 UML 系統模型（PlantUML 格式）+ 設計 Conflict 辨識"""

    name = "modeler"

    system_prompt = MODELER_ROLE_PROMPT

    def __init__(
        self,
        model,
        tools: Optional[list] = None,
        registry=None,
        project_config=None,
    ):
        super().__init__(
            model,
            tools=tools or [],
            registry=registry,
            skill_names=["UML"],
            project_config=project_config,
        )

    def build_model_observation(self, **kwargs: Any) -> Dict[str, Any]:
        return self.build_model_state(
            kwargs["artifact"],
            kwargs.get("recent_discussions"),
            kwargs.get("actions_taken", []),
            kwargs["iteration"],
            kwargs["max_iterations"],
        )

    def decide_model_action(
        self,
        *,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return self.decide_next_model_action(observation, last_result)

    def execute_model_loop_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return self.execute_model_action(
            decision.get("action", "done"),
            decision.get("params") or {},
            kwargs["artifact"],
            kwargs["pending_issues"],
            kwargs.get("last_result"),
        )

    def run_model_loop(self, artifact, recent_discussions=None, *, max_iterations):
        """Modeler 子 OODA：輪數上限 min(caller, self_review_round_cap)；第一輪可縮短。"""
        loop_cap = self.self_review_round_cap()
        return self.run_action_loop(
            name="model",
            max_iterations=max_iterations,
            loop_cap=loop_cap,
            context={
                "artifact": artifact,
                "recent_discussions": recent_discussions,
            },
            build_observation=self.build_model_observation,
            decide_action=self.decide_model_action,
            execute_action=self.execute_model_loop_action,
        )

    def build_model_state(
        self, artifact, recent_discussions, actions_taken,
        iteration, max_iterations,
    ):
        models = artifact.get("system_models", {}).get("models", [])
        model_summary = [
            {"name": m.get("name"), "type": m.get("type"),
             "has_plantuml": bool(m.get("plantuml"))}
            for m in models
        ]
        reqs = artifact.get("requirements", [])
        summary_reqs = [
            {"id": r.get("id"), "type": r.get("type"),
             "text": (r.get("text") or "")}
            for r in reqs
        ]
        disc_summaries = []
        for disc in (recent_discussions or []):
            topic = disc.get("topic", {})
            resolution = disc.get("resolution", {})
            disc_summaries.append({
                "topic_id": topic.get("id"),
                "title": topic.get("title"),
                "summary": (resolution.get("summary") or ""),
            })
        neutrals = [
            {"id": c.get("id"),
             "description": (c.get("description") or "")}
            for c in artifact.get("conflicts", [])
            if c.get("label") == "Neutral"
        ]
        conflicts_summary = [
            {
                "id": c.get("id"),
                "label": c.get("label"),
                "description": (c.get("description") or ""),
                "requirement_ids": c.get("requirement_ids", []),
            }
            for c in artifact.get("conflicts", [])
            if isinstance(c, dict)
        ]
        return {
            "current_models": model_summary,
            "requirements": summary_reqs,
            "stakeholders": artifact.get("stakeholders", []),
            "scope": artifact.get("scope", {}),
            "open_questions": [
                {
                    "question": q.get("question"),
                    "status": q.get("status"),
                    "type": q.get("type"),
                }
                for q in artifact.get("open_questions", [])
                if isinstance(q, dict)
            ],
            "domain_research": (artifact.get("feedback") or {}).get("domain_research", {}),
            "conflicts_summary": conflicts_summary,
            "neutrals": neutrals,
            "recent_discussions": disc_summaries,
            "actions_taken": actions_taken,
            "has_validator": "plantuml_validate" in self.tools,
            "available_model_types": list(AVAILABLE_MODEL_TYPES),
            "iteration": iteration + 1,
            "max_iterations": max_iterations,
        }

    def execute_model_action(
        self, action, params, artifact, pending_issues, last_observation=None,
    ):
        obs: Dict = {"action": action, "result": None, "error": None, "summary": ""}

        if action == "build_full_model":
            records = self.execute_full_modeling(
                artifact,
                pending_issues,
                last_observation=last_observation,
            )
            obs["result"] = {"records": records}
            obs["summary"] = f"完整建模流程完成：{len(records)} 個步驟"
            return obs

        if action == "assess_impact":
            reqs = artifact.get("requirements", [])
            models = artifact.get("system_models", {}).get("models", [])
            context = {
                "requirements": [
                    {"id": r.get("id"), "type": r.get("type"),
                     "text": r.get("text", "")}
                    for r in reqs
                ],
                "stakeholders": artifact.get("stakeholders", []),
                "scope": artifact.get("scope", {}),
                "conflicts": [
                    {
                        "id": c.get("id"),
                        "label": c.get("label"),
                        "description": c.get("description"),
                        "requirement_ids": c.get("requirement_ids", []),
                    }
                    for c in artifact.get("conflicts", [])
                    if isinstance(c, dict)
                ],
                "open_questions": artifact.get("open_questions", []),
                "domain_research": (artifact.get("feedback") or {}).get("domain_research", {}),
                "workflow_sketch": artifact.get("workflow_sketch", {}),
                "current_models": [
                    {"name": m.get("name"), "type": m.get("type")}
                    for m in models
                ],
            }
            ctx_text = json.dumps(context, ensure_ascii=False, indent=2)
            task = f"""分析需求與現有模型，完成兩件事：(1) 判斷哪些圖表需要更新或新建；(2) 產出與需求的一致性說明與缺口報告。

    # Context
    {ctx_text}

    # 輸出要求
    - models_to_update：需更新的 diagram type 列表（限 context_diagram, use_case_diagram, activity_diagram, data_flow_diagram, sequence_diagram, state_machine_diagram, class_diagram）
    - models_to_create：需新建的 diagram type 列表
    {MODEL_SELECTION_RULES}
    - conflicts 已完成辨識，只可作為背景理解；不要重新判斷 conflict label。
    - domain_research 只作為限制/風險註記，不可擴張功能。
    {modeler_review_field_language()}

    輸出 JSON:
    {{
    "models_to_update": ["需更新的 diagram type"],
    "models_to_create": ["需新建的 diagram type"],
    "impact_summary": "影響摘要",
    "consistency_summary": "與需求一致性的整體說明",
    "gaps": ["缺口或不一致項目1", "缺口或不一致項目2"]
    }}
    只輸出 JSON。"""
            messages = self.build_direct_messages(task)
            try:
                result = self.chat_json(messages)
                obs["result"] = result
                to_update = result.get("models_to_update", [])
                to_create = result.get("models_to_create", [])
                consistency_summary = result.get("consistency_summary", "")
                gaps = result.get("gaps", [])
                if not isinstance(gaps, list):
                    gaps = []
                obs["summary"] = (
                    f"影響評估: 更新 {len(to_update)}, 新建 {len(to_create)}"
                )
                if consistency_summary:
                    obs["summary"] += f"；一致性: {consistency_summary}"
                if gaps:
                    obs["summary"] += f"；缺口 {len(gaps)} 項"
                report = {
                    "consistency_summary": consistency_summary,
                    "gaps": gaps,
                    "models_to_update": to_update,
                    "models_to_create": to_create,
                    "impact_summary": result.get("impact_summary", ""),
                }
                artifact.setdefault("system_models", {})["last_consistency_report"] = report
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"影響評估失敗: {e}"
            return obs

        if action == "update_diagram":
            diagram_type = params.get("diagram_type", "")
            if not diagram_type:
                obs["error"] = "diagram_type 參數為空"
                return obs
            models = artifact.get("system_models", {}).get("models", [])
            existing = next(
                (m for m in models if m.get("type") == diagram_type), None
            )
            reqs = artifact.get("requirements", [])
            stakeholders = artifact.get("stakeholders", [])
            try:
                result = self.update_single_diagram(
                    diagram_type, reqs, stakeholders,
                    existing_model=existing,
                    artifact_context=artifact,
                )
                new_plantuml = result.get("plantuml", "")
                new_name = result.get(
                    "name",
                    existing.get("name", diagram_type) if existing else diagram_type,
                )
                if existing:
                    existing["plantuml"] = new_plantuml
                    existing["name"] = new_name
                    existing["maturity"] = "tentative" if diagram_type == "class_diagram" else "requirement_level"
                    existing["model_stage"] = "generate_system_model"
                    existing["source"] = "requirements_for_system_model"
                    if "to_confirm" in result:
                        existing["to_confirm"] = result.get("to_confirm") or []
                else:
                    artifact.setdefault("system_models", {}).setdefault(
                        "models", []
                    ).append({
                        "name": new_name,
                        "type": diagram_type,
                        "plantuml": new_plantuml,
                        "to_confirm": result.get("to_confirm") or [],
                        "maturity": "tentative" if diagram_type == "class_diagram" else "requirement_level",
                        "model_stage": "generate_system_model",
                        "source": "requirements_for_system_model",
                    })
                label = "更新" if existing else "新建"
                obs["summary"] = f"{diagram_type} 已{label}"
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"{diagram_type} 更新失敗: {e}"
            return obs

        if action == "validate_diagram":
            diagram_type = params.get("diagram_type", "")
            models = artifact.get("system_models", {}).get("models", [])
            target = next(
                (m for m in models if m.get("type") == diagram_type), None
            )
            if not target:
                obs["error"] = f"找不到 {diagram_type}"
                return obs
            validator = self.tools.get("plantuml_validate")
            if not validator:
                obs["result"] = {"valid": True}
                obs["summary"] = f"{diagram_type}: 無驗證工具，跳過"
                return obs
            code = target.get("plantuml", "")
            if not code:
                obs["error"] = f"{diagram_type} 無 PlantUML 內容"
                return obs
            result = self.execute_tool(
                "plantuml_validate",
                {"plantuml_code": code},
                active_skill="UML",
            )
            if "通過" in result:
                obs["result"] = {"valid": True}
                obs["summary"] = f"{diagram_type} 驗證通過"
            else:
                obs["result"] = {"valid": False, "error": result}
                obs["summary"] = f"{diagram_type} 驗證失敗"
            return obs

        if action == "fix_diagram":
            diagram_type = params.get("diagram_type", "")
            models = artifact.get("system_models", {}).get("models", [])
            target = next(
                (m for m in models if m.get("type") == diagram_type), None
            )
            if not target:
                obs["error"] = f"找不到 {diagram_type}"
                return obs
            error_msg = ""
            if (
                last_observation
                and isinstance(last_observation.get("result"), dict)
            ):
                error_msg = last_observation["result"].get("error", "")
            if not error_msg:
                error_msg = "語法錯誤"
            fixed = self.fix_plantuml(target, error_msg)
            if fixed:
                target["plantuml"] = fixed
                obs["summary"] = f"{diagram_type} 已修正"
            else:
                obs["error"] = "修正失敗"
                obs["summary"] = f"{diagram_type} 修正失敗"
            return obs

        obs["error"] = f"未知動作: {action}"
        return obs

    def execute_full_modeling(
        self,
        artifact: Dict[str, Any],
        pending_issues: List[Dict[str, Any]],
        *,
        last_observation: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """在一個 model action 內執行 assess → update → validate/fix 的完整建模流程。"""
        self.logger.info("  Modeler: assess → update → validate")
        records: List[Dict[str, Any]] = []

        assess_obs = self.execute_model_action(
            "assess_impact",
            {},
            artifact,
            pending_issues,
            last_observation,
        )
        records.append(
            {
                "action": "assess_impact",
                "params": {},
                "result_summary": assess_obs.get("summary", ""),
            }
        )
        last_obs = assess_obs

        refreshed_report = (artifact.get("system_models") or {}).get("last_consistency_report") or {}
        refreshed_targets = self.normalize_diagram_types(
            (refreshed_report.get("models_to_update") or [])
            + (refreshed_report.get("models_to_create") or [])
        )
        target_types: List[str] = []
        if refreshed_targets:
            target_types = refreshed_targets

        if not target_types:
            return records

        for diagram_type in target_types:
            update_params = {"diagram_type": diagram_type}
            update_obs = self.execute_model_action(
                "update_diagram",
                update_params,
                artifact,
                pending_issues,
                last_obs,
            )
            records.append(
                {
                    "action": "update_diagram",
                    "params": update_params,
                    "result_summary": update_obs.get("summary", ""),
                }
            )
            last_obs = update_obs
            if update_obs.get("error"):
                continue

            validate_obs = self.execute_model_action(
                "validate_diagram",
                update_params,
                artifact,
                pending_issues,
                last_obs,
            )
            records.append(
                {
                    "action": "validate_diagram",
                    "params": update_params,
                    "result_summary": validate_obs.get("summary", ""),
                }
            )
            last_obs = validate_obs

            valid = (
                isinstance(validate_obs.get("result"), dict)
                and validate_obs["result"].get("valid") is True
            )
            if valid:
                continue

            fix_obs = self.execute_model_action(
                "fix_diagram",
                update_params,
                artifact,
                pending_issues,
                last_obs,
            )
            records.append(
                {
                    "action": "fix_diagram",
                    "params": update_params,
                    "result_summary": fix_obs.get("summary", ""),
                }
            )
            last_obs = fix_obs

            revalidate_obs = self.execute_model_action(
                "validate_diagram",
                update_params,
                artifact,
                pending_issues,
                last_obs,
            )
            records.append(
                {
                    "action": "validate_diagram",
                    "params": update_params,
                    "result_summary": revalidate_obs.get("summary", ""),
                }
            )
            last_obs = revalidate_obs

        return records

    def normalize_diagram_types(self, items: List[Any]) -> List[str]:
        allowed = set(ALL_MODEL_TYPES)
        out: List[str] = []
        for item in items or []:
            t = str(item or "").strip()
            if t and t in allowed and t not in out:
                out.append(t)
        return out

    def decide_next_model_action(self, state, last_observation=None):
        if not state.get("current_models") and not state.get("actions_taken"):
            return {
                "action": "build_full_model",
                "params": {},
                "reasoning": "尚無系統模型，先用單一 model action 建立完整核心 UML。",
            }
        state_text = json.dumps(state, ensure_ascii=False, indent=2)
        obs_text = json.dumps(last_observation or {}, ensure_ascii=False, indent=2)
        sr_current = int(state.get("max_iterations") or 1)

        user_prompt = f"""# 任務
    你是系統建模專家。根據當前狀態與上一步結果，選下一個動作。

    # 動作
    - build_full_model：尚無模型時，一次建立完整 requirement-level models，並完成驗證/修正
    - assess_impact：先判斷哪些圖表受影響
    - update_diagram：{{"diagram_type":"context_diagram/use_case_diagram/activity_diagram/data_flow_diagram/sequence_diagram/state_machine_diagram/class_diagram"}}
    - validate_diagram：{{"diagram_type":"..."}}
    - fix_diagram：{{"diagram_type":"..."}}
    - done：結束

    # 當前狀態
    {state_text}

    # 上一步結果
    {obs_text}

    # 規則
    - 第一輪可選填 max_iterations=1-{sr_current}；不填就沿用 {sr_current}
    - 先 assess_impact，再決定是否更新模型
    {MODEL_SELECTION_RULES}
    - 需要 artifact 細節時先用 artifact_query
    - 每個需更新的圖表都走：update_diagram → validate_diagram →（若失敗）fix_diagram → validate_diagram
    - 所有受影響圖表處理完後選 done
    - {short_reasoning_line()}

    # 輸出 JSON
    {{
      "action": "動作名稱",
      "params": {{}},
      "reasoning": "一句說明",
      "max_iterations": "選填；僅第一輪有效，數字 1-{sr_current}"
    }}"""

        messages = self.build_direct_messages(user_prompt)
        try:
            if "artifact_query" in self.tools:
                raw = self.chat_with_tools(messages, max_rounds=self.tool_call_max_rounds)
                response = self.parse_topic_response_json(raw)
            else:
                response = self.chat_json(messages)
        except Exception as e:
            self.logger.warning(f"Modeler model loop 決策失敗: {e}")
            return {"action": "done", "params": {}, "reasoning": f"fallback: {e}"}

        action = (response.get("action") or "").strip()
        if action not in MODELER_LOOP_ACTIONS:
            action = "done"
        out = {
            "action": action,
            "params": response.get("params") or {},
            "reasoning": response.get("reasoning", ""),
        }
        if "max_iterations" in response:
            out["max_iterations"] = response["max_iterations"]
        return out

    def build_topic_response_observation(self, **kwargs: Any) -> Dict[str, Any]:
        return self.build_topic_response_observation_payload(**kwargs)

    def decide_topic_response_action(
        self,
        *,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return self.decide_default_topic_response_action(
            observation,
            reasoning="根據議題類型選擇對應的建模回應策略。",
        )

    def execute_topic_response_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        user_prompt = self.build_topic_response_prompt(
            topic=kwargs["topic"],
            previous_responses=kwargs.get("previous_responses"),
            artifact_snapshot=kwargs.get("artifact_snapshot"),
        )
        messages = self.build_direct_messages(user_prompt)
        response = self.chat_for_topic_response(messages)
        return {
            "action": decision.get("action", ""),
            "status": "success",
            "statement": response.get("statement", ""),
            "open_questions": response.get("open_questions", []),
            "summary": f"完成 modeler topic_response: {decision.get('action', '')}",
        }
