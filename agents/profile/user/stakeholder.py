# User stakeholder helpers: derive stakeholder voices and initial requirements.
import json
from typing import Any, Dict, List, Optional

class UserStakeholder:
    @staticmethod
    def scenario_context_text(value: Any) -> str:
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False, indent=2)
        return str(value or "").strip()

    def propose_stakeholders(self, rough_idea: Any) -> List[Dict]:
        opa = self.run_action_loop(
            name="stakeholder_elicitation",
            context={
                "stakeholder_action": "propose_stakeholders",
                "rough_idea": rough_idea,
            },
            build_observation=self.build_stakeholder_elicitation_observation,
            decide_action=self.decide_stakeholder_elicitation_action,
            execute_action=self.execute_stakeholder_elicitation_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("error"))
        return result.get("output", [])

    def generate_stakeholder_requirements(
        self, rough_idea: Any, selected_stakeholders: List
    ) -> List[Dict]:
        opa = self.run_action_loop(
            name="stakeholder_elicitation",
            context={
                "stakeholder_action": "generate_stakeholder_requirements",
                "rough_idea": rough_idea,
                "selected_stakeholders": selected_stakeholders,
            },
            build_observation=self.build_stakeholder_elicitation_observation,
            decide_action=self.decide_stakeholder_elicitation_action,
            execute_action=self.execute_stakeholder_elicitation_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("error"))
        return result.get("output", [])

    def build_stakeholder_elicitation_observation(self, **kwargs) -> Dict:
        selected = kwargs.get("selected_stakeholders") or []
        return {
            "action": kwargs.get("stakeholder_action", ""),
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs["max_iterations"],
            "has_rough_idea": bool(str(kwargs.get("rough_idea") or "").strip()),
            "selected_stakeholder_count": len(selected),
        }

    def decide_stakeholder_elicitation_action(
        self,
        *,
        observation: Dict,
        last_result: Optional[Dict] = None,
        **kwargs,
    ) -> Dict:
        if isinstance(last_result, dict) and not last_result.get("error"):
            return {
                "action": "done",
                "params": {},
                "reasoning": "上一輪利害關係人需求擴展已完成，結束本次任務。",
            }
        action = str(observation.get("action") or "").strip()
        return {
            "action": action,
            "params": {},
            "reasoning": f"以 User agent 情境利害關係人視角執行：{action}。",
        }

    def execute_stakeholder_elicitation_action(
        self,
        *,
        decision: Dict,
        **kwargs,
    ) -> Dict:
        action = str(decision.get("action") or "").strip()
        try:
            if action == "propose_stakeholders":
                output = self.propose_stakeholders_via_llm(kwargs.get("rough_idea", ""))
            elif action == "generate_stakeholder_requirements":
                output = self.generate_stakeholder_requirements_via_llm(
                    kwargs.get("rough_idea", ""),
                    kwargs.get("selected_stakeholders") or [],
                )
            else:
                raise ValueError(f"未知 stakeholder action: {action}")
        except Exception as e:
            return {
                "action": action,
                "status": "failed",
                "error": str(e),
                "summary": f"stakeholder elicitation failed: {action}",
            }
        return {
            "action": action,
            "status": "success",
            "output": output,
            "summary": f"完成 stakeholder elicitation: {action}",
        }

    def propose_stakeholders_via_llm(self, rough_idea: Any) -> List[Dict]:
        scenario_context = self.scenario_context_text(rough_idea)
        user_prompt = f"""# 任務
根據以下產品情境，建議 7-9 位可能相關的利害關係人。

# 產品情境
{scenario_context}

# 利害關係人分類
- Primary Users：每天直接操作系統、輸入資料、接收通知或完成任務的人。
- System Owners & Management：負責派工、監督流程、營運決策、權限、資料品質、系統穩定性、安全或維護的人。
- External Parties：外部會影響或受影響的單位，例如客戶、供應商、第三方服務、稽核、主管機關或合作單位。

# 選擇優先順序
1. Primary Users
2. System Owners & Management
3. External Parties

# 約束
- 三類都必須出現。
- Primary Users 至少 3 位。
- System Owners & Management 至少 3 位。
- External Parties 至少 1 位，但必須是三類中數量最少的類別。
- 輸出順序必須先列 Primary Users，再列 System Owners & Management，最後列 External Parties。
- 每位利害關係人須有明確且不同的使用情境與責任邊界
- 每位利害關係人必須直接存在於初始想法描述的產品情境中；不要加入和此產品無關的泛用企業角色
- 避免使用情境重疊
- name 只填名稱，不要用括號補充說明
- type 只能是 Primary Users、System Owners & Management、External Parties
- reason 選擇理由用一句話即可
- 每位利害關係人需包含名稱、分類與理由。

# 輸出 JSON
{{{{
    "proposed_stakeholders": [
        {{{{"name": "利害關係人名稱", "type": "Primary Users | System Owners & Management | External Parties", "reason": "一句話選擇理由"}}}}
    ]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.chat_json(messages, temperature=1)
        proposed = response.get("proposed_stakeholders", [])
        if not isinstance(proposed, list):
            raise ValueError("proposed_stakeholders must be a list")

        categories = [
            "Primary Users",
            "System Owners & Management",
            "External Parties",
        ]
        counts = {category: 0 for category in categories}
        current_order = 0
        for row in proposed:
            if not isinstance(row, dict):
                raise ValueError("each proposed stakeholder must be an object")
            name = str(row.get("name") or "").strip()
            stakeholder_type = str(row.get("type") or "").strip()
            reason = str(row.get("reason") or "").strip()
            if not name or not reason:
                raise ValueError(
                    "each proposed stakeholder must include name and reason"
                )
            if stakeholder_type not in counts:
                raise ValueError(f"invalid stakeholder type: {stakeholder_type}")
            order = categories.index(stakeholder_type)
            if order < current_order:
                raise ValueError("stakeholders must be ordered by type priority")
            current_order = order
            counts[stakeholder_type] += 1

        if len(proposed) < 7 or len(proposed) > 9:
            raise ValueError("propose_stakeholders must return 7-9 stakeholders")
        if counts["Primary Users"] < 3:
            raise ValueError("Primary Users must include at least 3 stakeholders")
        if counts["System Owners & Management"] < 3:
            raise ValueError(
                "System Owners & Management must include at least 3 stakeholders"
            )
        if counts["External Parties"] < 1:
            raise ValueError("External Parties must include at least 1 stakeholder")
        if counts["External Parties"] >= min(
            counts["Primary Users"], counts["System Owners & Management"]
        ):
            raise ValueError("External Parties must be the smallest stakeholder type")
        return proposed

    def generate_stakeholder_requirements_via_llm(
        self, rough_idea: Any, selected_stakeholders: List
    ) -> List[Dict]:
        scenario_context = self.scenario_context_text(rough_idea)
        stakeholder_rows = []
        for i, sh in enumerate(selected_stakeholders, 1):
            if isinstance(sh, dict):
                name = str(sh.get("name") or "").strip()
            else:
                name = str(sh).strip()
            if not name:
                continue
            stakeholder_rows.append(f"{i}. {name}")
        stakeholder_list = "\n".join(stakeholder_rows)

        user_prompt = f"""# 任務
模擬以下利害關係人，以第一人稱、口語方式從各自角度提出需求。

# 利害關係人
{stakeholder_list}

# 背景
{scenario_context}

# 發言面向
1. 日常使用情境
2. 痛點與困擾
3. 期望功能
4. 擔心的事

# 限制
- 每位 stakeholder 產生 3-5 條 text
- 只根據該 stakeholder 的日常經驗
- 不替未選中的角色發言
- 每條 text 都必須能回扣背景中的產品情境

# 輸出 JSON
{{{{
    "stakeholders": [
        {{{{
            "name": "...",
            "text": ["...", "..."]
        }}}}
    ]
}}}}"""

        try:
            messages = self.build_direct_messages(user_prompt)
            response = self.chat_json(messages, temperature=1)
            stakeholders = response.get("stakeholders", [])

            for sh in stakeholders:
                if not all(key in sh for key in ["name", "text"]):
                    raise ValueError(f"利害關係人格式錯誤: {sh}")
                if isinstance(sh["text"], str):
                    sh["text"] = [
                        s.strip() for s in sh["text"].split("\n") if s.strip()
                    ]
                if len(sh["text"]) < 3:
                    self.logger.warning(
                        f"{sh['name']} 只有 {len(sh['text'])} 條需求，不足 3 條"
                    )

            return stakeholders
        except Exception as e:
            raise RuntimeError(f"User 生成失敗: {e}")
