import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from typing import Dict, Any, Optional, List

from agents.base import BaseAgent
from agents.skills.base import get_skill
from utils import (
    current_output_language,
    modeler_models_array_name_line,
    modeler_name_field_language,
    modeler_review_field_language,
    short_reasoning_line,
)


MODELER_ROLE_PROMPT = """你是 UML 系統建模專家，負責把需求轉成可驗證、可追溯的 UML 模型。

規則：
1. 精煉時只改受影響部分，保留未變動元素。
2. 不直接改需求語意；發現不一致時只指出影響、缺口與待確認事項。
3. 資訊不足時用 to_confirm 標示，不可臆造。"""


MODELER_REVIEW_ACTIONS = [
    "assess_impact",
    "update_diagram",
    "validate_diagram",
    "fix_diagram",
    "done",
]

REQUIRED_MODEL_TYPES = [
    "use_case_diagram",
    "class_diagram",
    "sequence_diagram",
]


class ModelerAgent(BaseAgent):
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
            skill_names=["plantuml-syntax"],
            project_config=project_config,
        )

    # ===== Monitor =====

    def run_review_loop(self, artifact, recent_discussions=None, *, max_iterations):
        """Modeler 子 OODA：輪數上限 min(caller, self_review_round_cap)；第一輪可縮短。"""
        observation = None
        actions_taken = []
        pending_issues = []
        loop_cap = self.self_review_round_cap()
        effective_max = min(max_iterations, loop_cap)
        i = 0

        # 單輪策略：在同一輪內完成完整建模流程，而非以保底補跑。
        if effective_max == 1:
            records = self._run_single_round_full_modeling(
                artifact,
                pending_issues,
                last_observation=observation,
            )
            actions_taken.extend(records)
            return {
                "agent": self.name,
                "actions_taken": actions_taken,
                "pending_issues": pending_issues,
            }

        while i < effective_max:
            state = self.build_review_state(
                artifact, recent_discussions, actions_taken, i, effective_max,
            )
            decision = self.decide_next_review_action(state, observation)
            if i == 0:
                n = decision.get("max_iterations")
                if n is not None and isinstance(n, int) and 1 <= n <= effective_max:
                    effective_max = n
                    self.logger.info("  Modeler review 輪數: %s/%s", effective_max, loop_cap)
            action = decision.get("action", "done")
            self.logger.info(f"  Modeler review [{i + 1}/{effective_max}]: {action}")
            if action == "done" or action not in MODELER_REVIEW_ACTIONS:
                break

            params = decision.get("params") or {}
            observation = self.execute_review_action(
                action, params, artifact, pending_issues, observation,
            )
            actions_taken.append({
                "action": action,
                "params": params,
                "result_summary": observation.get("summary", ""),
            })
            if observation.get("error"):
                self.logger.warning(f"  Modeler review error: {observation['error']}")
            i += 1

        return {
            "agent": self.name,
            "actions_taken": actions_taken,
            "pending_issues": pending_issues,
        }

    def build_review_state(
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
        return {
            "current_models": model_summary,
            "requirements": summary_reqs,
            "neutrals": neutrals,
            "recent_discussions": disc_summaries,
            "actions_taken": actions_taken,
            "has_validator": "plantuml_validate" in self.tools,
            "iteration": iteration + 1,
            "max_iterations": max_iterations,
        }

    def execute_review_action(
        self, action, params, artifact, pending_issues, last_observation=None,
    ):
        obs: Dict = {"action": action, "result": None, "error": None, "summary": ""}

        if action == "assess_impact":
            reqs = artifact.get("requirements", [])
            models = artifact.get("system_models", {}).get("models", [])
            context = {
                "requirements": [
                    {"id": r.get("id"), "type": r.get("type"),
                     "text": r.get("text", "")}
                    for r in reqs
                ],
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
- models_to_update：需更新的 diagram type 列表（如 use_case_diagram, class_diagram, sequence_diagram）
- models_to_create：需新建的 diagram type 列表
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
                result = self.model.chat_json(messages)
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
                # 寫入 artifact 供後續查閱
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
                )
                new_plantuml = result.get("plantuml", "")
                new_name = result.get(
                    "name",
                    existing.get("name", diagram_type) if existing else diagram_type,
                )
                if existing:
                    existing["plantuml"] = new_plantuml
                    existing["name"] = new_name
                else:
                    artifact.setdefault("system_models", {}).setdefault(
                        "models", []
                    ).append({
                        "name": new_name,
                        "type": diagram_type,
                        "plantuml": new_plantuml,
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
                active_skill="plantuml-syntax",
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

    def _run_single_round_full_modeling(
        self,
        artifact: Dict[str, Any],
        pending_issues: List[Dict[str, Any]],
        *,
        last_observation: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """單輪內執行 assess → update → validate/fix 的完整建模流程。"""
        self.logger.info("  Modeler: assess → update → validate")
        records: List[Dict[str, Any]] = []

        assess_obs = self.execute_review_action(
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
        refreshed_targets = self._normalize_diagram_types(
            (refreshed_report.get("models_to_update") or [])
            + (refreshed_report.get("models_to_create") or [])
        )
        if refreshed_targets:
            target_types = refreshed_targets

        if not target_types:
            target_types = list(REQUIRED_MODEL_TYPES)

        for diagram_type in target_types:
            update_params = {"diagram_type": diagram_type}
            update_obs = self.execute_review_action(
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

            validate_obs = self.execute_review_action(
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

            fix_obs = self.execute_review_action(
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

            revalidate_obs = self.execute_review_action(
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

    def _normalize_diagram_types(self, items: List[Any]) -> List[str]:
        allowed = set(REQUIRED_MODEL_TYPES)
        out: List[str] = []
        for item in items or []:
            t = str(item or "").strip()
            if t and t in allowed and t not in out:
                out.append(t)
        return out

    # ===== Plan =====

    def decide_next_review_action(self, state, last_observation=None):
        state_text = json.dumps(state, ensure_ascii=False, indent=2)
        obs_text = json.dumps(last_observation or {}, ensure_ascii=False, indent=2)
        sr_current = int(state.get("max_iterations") or 1)

        user_prompt = f"""# 任務
你是系統建模專家。根據當前狀態與上一步結果，選下一個動作。

# 動作
- assess_impact：先判斷哪些圖表受影響
- update_diagram：{{"diagram_type":"use_case_diagram/class_diagram/sequence_diagram"}}
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
                response = self.model.chat_json(messages)
        except Exception as e:
            self.logger.warning(f"Modeler review 決策失敗: {e}")
            return {"action": "done", "params": {}, "reasoning": f"fallback: {e}"}

        action = (response.get("action") or "").strip()
        if action not in MODELER_REVIEW_ACTIONS:
            action = "done"
        out = {
            "action": action,
            "params": response.get("params") or {},
            "reasoning": response.get("reasoning", ""),
        }
        if "max_iterations" in response:
            out["max_iterations"] = response["max_iterations"]
        return out

    # ===== Plan: topic proposal =====

    def propose_topics(
        self,
        artifact: Dict[str, Any],
        *,
        round_num: int,
        max_items: int = 2,
    ) -> List[Dict[str, Any]]:
        proposals: List[Dict[str, Any]] = []
        models = ((artifact.get("system_models") or {}).get("models") or [])
        required_types = {"use_case_diagram", "class_diagram", "sequence_diagram"}
        existing_types = {m.get("type") for m in models if m.get("type")}
        missing = sorted(list(required_types - existing_types))
        if missing:
            proposals.append(
                {
                    "title": "模型覆蓋補齊討論",
                    "description": f"尚缺圖型：{', '.join(missing)}，需確認是否補齊與優先順序。",
                    "category": "open_question",
                    "participants": ["modeler", "analyst", "user"],
                    "discussion_mode": "sequential",
                    "speaking_order": ["modeler", "analyst", "user"],
                    "source_ids": [],
                    "priority_hint": "medium",
                    "impact_level": "medium",
                    "why_now": "模型覆蓋不足會影響後續設計一致性。",
                    "requires_multi_party": False,
                    "blocks_decision": False,
                    "routing_preference": "direct_clarification",
                    "proposed_by": "modeler",
                    "round": round_num,
                }
            )

        for m in models:
            to_confirm = m.get("to_confirm") or []
            if not to_confirm:
                continue
            mtype = (m.get("type") or "").strip()
            proposals.append(
                {
                    "title": f"{mtype or '模型'} 待確認事項討論",
                    "description": "；".join([str(x).strip() for x in to_confirm if str(x).strip()]),
                    "category": "open_question",
                    "participants": ["modeler", "analyst", "user", "expert"],
                    "discussion_mode": "sequential",
                    "speaking_order": ["modeler", "analyst", "user", "expert"],
                    "source_ids": [mtype] if mtype else [],
                    "priority_hint": "medium",
                    "impact_level": "medium",
                    "why_now": "模型存在待確認項，可能影響需求解讀與可實作性。",
                    "requires_multi_party": False,
                    "blocks_decision": False,
                    "routing_preference": "direct_clarification",
                    "proposed_by": "modeler",
                    "round": round_num,
                }
            )

        return proposals[: max(1, max_items)]

    # ===== Action: modeling =====

    def generate_system_model(
        self,
        requirements: List[Dict],
        stakeholders: List[Dict],
        max_iterations: Optional[int] = None,
    ) -> Dict[str, Any]:
        """依 run_review_loop（observe → reason → act → evaluate）產出初始 UML，回傳 system_models。max_iterations 由 caller 從 config 傳入，未傳則用 15。"""
        artifact = {
            "requirements": requirements,
            "stakeholders": stakeholders or [],
            "system_models": {"models": []},
            "conflicts": [],
        }
        n = 15 if max_iterations is None else max_iterations
        self.run_review_loop(artifact, max_iterations=n)
        model_data = artifact.get("system_models", {})
        return self.validate_models(model_data)

    def refine_model(
        self,
        requirements: List[Dict],
        prev_models: List[Dict] = None,
        stakeholders: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """根據更新的需求精煉系統模型；可選傳入 stakeholders 以對應角色與需求來源。"""
        current_model = {"models": prev_models or []}
        current_model_json = json.dumps(current_model, ensure_ascii=False, indent=2)
        requirements_text = json.dumps(requirements, ensure_ascii=False, indent=2)
        sh_block = ""
        if stakeholders:
            sh_text = json.dumps(stakeholders, ensure_ascii=False, indent=2)
            sh_block = f"\n# 利害關係人（供對應需求來源與角色）\n{sh_text}\n\n"

        task = f"""# 任務
根據更新後的需求，評估並更新現有系統模型。
{sh_block}# 當前系統模型
```json
{current_model_json}
```

# 更新後的需求
{requirements_text}

# 規則
- 比較新需求與當前模型，識別差異。
- 只修改受影響的部分，保留未變動元素。
- 可自行決定保留、新增或移除哪些圖表（type 限 use_case_diagram / class_diagram / sequence_diagram）。
- {modeler_models_array_name_line()}
- {modeler_name_field_language()}
- 資訊不足時請在 to_confirm 列出待確認事項。

# 輸出格式
{{
    "models": [{{"name": "...", "type": "use_case_diagram|class_diagram|sequence_diagram", "plantuml": "@startuml\\n...\\n@enduml", "to_confirm": ["待確認事項"]}}]
}}"""

        try:
            skill = get_skill("plantuml-syntax")
            messages = self._build_skill_messages(skill, "plantuml-syntax", task)
            result = self.model.chat_json(messages)
            model_data = self.ensure_model_format(result)
            return self.validate_models(model_data)
        except Exception as e:
            self.logger.warning(f"模型精煉失敗: {e}")
            return {"models": prev_models or []}

    def update_single_diagram(
        self, diagram_type, requirements, stakeholders=None,
        existing_model=None,
    ):
        type_names = {
            "use_case_diagram": "Use Case Diagram",
            "class_diagram": "Class Diagram",
            "sequence_diagram": "Sequence Diagram",
        }
        type_name = type_names.get(diagram_type, diagram_type)
        req_text = json.dumps(requirements, ensure_ascii=False, indent=2)
        diagram_layout_hint = ""
        if diagram_type == "use_case_diagram":
            diagram_layout_hint = """
用例圖版面要求：產出時以「actor 與 use case 的關聯一目了然」為準。請善用 PlantUML 的版面控制（例如 left to right direction、或將 actor 分置系統邊界左右兩側），使連線少交叉、誰對應哪些用例清楚可辨；若單圖用例過多導致連線雜亂，可精簡為核心用例或依角色拆成多張圖。"""
        elif diagram_type == "class_diagram":
            diagram_layout_hint = """
類別圖建模要求：優先呈現可讀的核心結構與關係，不要把所有名詞都畫成類別。請先確保主要類別之間的繼承、關聯、聚合/組合、依賴關係清楚可辨，再補必要屬性與方法；每個類別僅保留關鍵欄位/操作，避免圖面過度擁擠。若領域過大，請依子域拆圖或僅呈現本次需求受影響的核心類別。"""
        elif diagram_type == "sequence_diagram":
            diagram_layout_hint = """
時序圖建模要求：一張圖聚焦一個主要情境流程，僅保留關鍵 lifeline 與關鍵訊息，避免放入過多非必要元件。需清楚表達主流程與關鍵分支/例外（可用 alt/opt），並讓訊息方向與前後順序易於追蹤；訊息名稱請使用具體動詞，避免抽象字眼。"""

        if existing_model and existing_model.get("plantuml"):
            task = f"""根據更新後的需求，精煉以下 {type_name}。只修改受影響的部分，保留未變動的元素。

當前 PlantUML:
{existing_model['plantuml']}

需求:
{req_text}
{diagram_layout_hint}

- {modeler_name_field_language()}
- PlantUML elements（actor/use case/class/message/lifeline/relation label）一律英文，不可混用中文元素名。
- 若資訊不足，不可臆測；請在 to_confirm 列出待確認事項（可為空陣列）。
輸出 JSON:
{{"name": "圖表名稱", "type": "{diagram_type}", "plantuml": "@startuml\\n...\\n@enduml", "to_confirm": ["待確認事項"]}}"""
        else:
            sh_text = json.dumps(stakeholders or [], ensure_ascii=False, indent=2)
            task = f"""根據以下需求產生 {type_name}。

需求:
{req_text}

利害關係人:
{sh_text}
{diagram_layout_hint}

- {modeler_name_field_language()}
- PlantUML elements（actor/use case/class/message/lifeline/relation label）一律英文，不可混用中文元素名。
- 若資訊不足，不可臆測；請在 to_confirm 列出待確認事項（可為空陣列）。
輸出 JSON:
{{"name": "圖表名稱", "type": "{diagram_type}", "plantuml": "@startuml\\n...\\n@enduml", "to_confirm": ["待確認事項"]}}"""

        skill = get_skill("plantuml-syntax")
        messages = self._build_skill_messages(skill, "plantuml-syntax", task)
        return self.model.chat_json(messages)

    def ensure_model_format(self, result) -> Dict[str, Any]:
        if not isinstance(result, dict):
            return {"models": []}
        result.setdefault("models", [])
        return result

    # ===== Action: meeting response =====

    def respond_to_topic(self, topic, previous_responses=None, artifact_snapshot=None):
        topic_text = f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n描述: {topic.get('description', '')}"
        topic_id = str(topic.get("id") or "")

        prev_text = ""
        if previous_responses:
            parts = [
                f"【{r.get('agent', '?')}】\n{r.get('response', {}).get('statement', '')}"
                for r in previous_responses
            ]
            prev_text = "\n# 前面的發言\n" + "\n\n".join(parts)

        snapshot_text = ""
        if artifact_snapshot:
            snapshot_text = f"\n# 當前專案狀態（供參考）\n{json.dumps(artifact_snapshot, ensure_ascii=False, indent=2)}"

        recent_ask_history_text = ""
        recent_ask_history = topic.get("recent_ask_history") or []
        if recent_ask_history:
            recent_ask_history_text = (
                "\n# 最近幾輪正式提問摘要\n"
                + json.dumps(recent_ask_history, ensure_ascii=False, indent=2)
            )

        tool_hint = ""
        if self.tools:
            tool_hint = "\n# 工具使用\n- 若發言中涉及 PlantUML 片段，可先使用 plantuml_validate 驗證語法，再撰寫發言。\n- 最後**必須**輸出下列 JSON。"

        elicitation_hint = ""
        task_block = "請以系統建模專家身分發言，聚焦模型影響、元素邊界與更新建議。"
        rules_block = """- statement 需包含：結論、影響分析、風險/邊界、建議下一步。
- 需明確指出受影響的模型元素、圖型或責任邊界，不要只講抽象原則。
- 若資訊不足，說明需補哪些介面、事件流程或資料邊界，不可臆測。
- 可提到 Use Case / Class / Sequence 的具體影響。
- 若需要他人補資訊，再在 open_questions 提具體問題。
- 可用純文字表格或流程輔助；若使用，請放在程式碼區塊。"""
        if (topic.get("category") or "").strip() == "conflict_discussion":
            task_block = "請以系統建模專家身分逐筆再審查目前這批 Conflict/Neutral pairs，先根據 requirement_a / requirement_b 原文獨立重判，再與 current_label 比較決定 keep 或 modify。"
            rules_block = """- statement 必須是單一合法 JSON object 字串；不可輸出 JSON 以外的前後文。
- statement JSON 結構必須為：{"overall_assessment":"...","pair_reviews":[...]}。
- overall_assessment 用 1-3 句說明整批標註品質是否有系統性偏誤。
- pair_reviews 必須逐筆涵蓋每個 [PAIR-xxx]；每筆都要有：id、independent_label、decision、proposed_label、confidence、reason。
- 你的任務不是提出新需求，而是再審查目前的 Conflict/Neutral 標籤是否合理。
- 只有在兩項需求在資料結構、狀態轉移、事件流程或責任邊界上無法同時成立時，才支持 Conflict。
- 只有在兩項需求可明確判定為不衝突、不重複，且沒有直接語義關係時，才支持 Neutral。
- 若兩項需求描述同一功能範圍、同一流程、同一資料處理或同一輸出行為，即表示存在直接語義關係；不能僅因兩者可共存就判為 Neutral。
- 若一項需求是另一項的子集、細化、補充步驟或同流程的相鄰行為，不能直接判為 Neutral。
- 若只是流程未定、資料欄位未補齊、責任分工未明，不能因看不出衝突就直接支持 Neutral。
- 若支持 Conflict，必須指出模型層的互斥點；若支持 Neutral，必須說明為何兩項需求既不衝突、也不重複，且無直接語義關係。
- 不要跳到技術實作細節。
- 若需要他人補資訊，再在 open_questions 提具體問題。
- 不可用 JSON-like 條列或文字摘要取代合法 JSON。"""
        if topic_id.startswith("ELICIT-") and topic.get("collector_mode"):
            elicitation_hint = """# ELICIT Collector（Modeler）
- 你不是本輪正式提問者。
- 你的任務是替 asker 找出現在最值得問 user 的一個資料、內容或互動缺口。
- 優先補核心資料與互動理解；若核心內容仍不清楚，不要先追後段行為細節。
- 若沒有高價值的新資料/內容問題，要明講。"""
            task_block = "請以建模 collector 身分，輸出一段提問建議，供 asker 整合成正式主問題。"
            rules_block = """- 不要直接對 user 正式發問。
- statement 需包含：需求缺口、建議問題句、為何值得問、如何避免重複。
- 建議問題句只能有 1 個主問題，且要能直接轉成資料內容或互動規則需求。
- open_questions 請輸出空陣列。"""
        elif topic_id.startswith("ELICIT-") and str(topic.get("asker_agent") or "").strip() == self.name:
            stop_phrase = (
                "I have gathered enough information"
                if current_output_language() == "en"
                else "我已蒐集足夠資訊"
            )
            elicitation_hint = """# ELICIT Asker（Modeler）
- 你是本輪唯一正式提問者。
- 你的任務是根據前面 collectors 的提問建議，整合成對 user 的唯一主問題。
- 優先補資料內容、輸出結構、狀態/事件、互動邊界與呈現方式等核心缺口。
- 若核心資料內容仍不清楚，不要優先追問 timeout、retry、resume、regeneration 等後段行為細節。
- 若 collectors 提出的方向太技術化，改寫成 user 能直接回答的一題。"""
            task_block = (
                "請以建模 interviewer 身分，只輸出對 user 的一個正式主問題（1-3 句）；"
                "若你判斷目前已蒐集到足夠資訊、可以收束本輪需求挖掘，則 statement 請只輸出以下固定句"
                f"（勿加引號、勿改寫、勿額外說明）：{stop_phrase}"
            )
            rules_block = f"""- 若你判斷目前資訊已足以支撐核心需求理解，且再往下追問的增益有限，可直接輸出停止句：{stop_phrase}
- 若關鍵資料內容、輸出結構、狀態/事件、互動邊界、介面呈現方式仍未釐清，不可停止。
- 若選擇提問，只能問 1 個主問題，不可合併多題。
- 問題必須可回答、可抽取、可直接轉成資料內容或互動規則需求。
- open_questions 請輸出空陣列。"""
        user_prompt = f"""{topic_text}
{prev_text}
{snapshot_text}
{recent_ask_history_text}
{tool_hint}
{elicitation_hint}

# 任務
{task_block}

# 規則
{rules_block}

# 輸出 JSON
{{{{
    "statement": "針對此議題的完整發言內容",
    "open_questions": [{{{{"to": "目標 agent 名稱", "question": "問題"}}}}]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.chat_for_topic_response(messages)

        return {
            "agent": self.name,
            "statement": response.get("statement", ""),
            "open_questions": response.get("open_questions", []),
        }

    # ===== Tool helpers =====

    def validate_models(self, model_data: Dict[str, Any]) -> Dict[str, Any]:
        """用 plantuml_validate 工具驗證每個模型的 PlantUML 語法，有錯則自動修正"""
        validator = self.tools.get("plantuml_validate")
        if not validator:
            return model_data

        models = model_data.get("models", [])
        if not models:
            return model_data

        # 並行執行所有驗證
        validation_results = {}

        def validate_one(idx: int, m: Dict) -> tuple:
            code = m.get("plantuml", "")
            if not code:
                return (idx, m, None)
            result = self.execute_tool(
                "plantuml_validate",
                {"plantuml_code": code},
                active_skill="plantuml-syntax",
            )
            return (idx, m, result)

        max_workers = min(len(models), 6)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(validate_one, i, m): i for i, m in enumerate(models)
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    i, m, result = future.result()
                    validation_results[i] = (m, result)
                except Exception as e:
                    self.logger.warning(f"  模型驗證失敗: {e}")
                    validation_results[idx] = (models[idx], None)

        # 依序處理需修正的模型（fix_plantuml 呼叫 LLM，維持順序並控制並發）
        for i in range(len(models)):
            m, result = validation_results.get(i, (models[i], None))
            if result is None:
                continue
            if "通過" in result:
                continue
            self.logger.warning(f"  {m.get('name', '')} 語法修正中")
            fixed = self.fix_plantuml(m, result)
            if fixed:
                m["plantuml"] = fixed

        return model_data

    def fix_plantuml(self, model: Dict, error_msg: str) -> Optional[str]:
        """依據錯誤訊息讓 LLM 修正 PlantUML"""
        user_prompt = f"""# 任務
以下 PlantUML 程式碼有語法錯誤，請修正後回傳。

# 模型名稱
{model.get('name', '')}

# 原始程式碼
{model.get('plantuml', '')}

# 驗證錯誤
{error_msg}

- PlantUML elements（actor/use case/class/message/lifeline/relation label）必須維持英文，不可改成中文。
- 若錯誤來自需求資訊不足，請不要臆測補齊；在 to_confirm 列出待確認事項（可為空陣列）。

# 輸出 JSON
{{{{
    "plantuml": "@startuml\\n...修正後的完整程式碼...\\n@enduml",
    "to_confirm": ["待確認事項"]
}}}}"""

        try:
            skill = get_skill("plantuml-syntax")
            messages = self._build_skill_messages(skill, "plantuml-syntax", user_prompt)
            response = self.model.chat_json(messages)
            fixed = response.get("plantuml", "")
            if "@startuml" in fixed and "@enduml" in fixed:
                return fixed
        except Exception as e:
            self.logger.warning(f"  修正失敗: {e}")
        return None
