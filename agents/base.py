import json
import logging

from typing import Dict, List, Optional
from agents.tools.base import BaseTool

# Agent 基礎類別
class BaseAgent:
    """
    核心能力：Tool Use（self.tools）、議題回應（respond_to_topic）。
    """

    name: str = ""
    system_prompt: str = ""

    def __init__(self, model, tools: Optional[List[BaseTool]] = None, registry=None):
        self.model = model
        self.tools: Dict[str, BaseTool] = {t.name: t for t in (tools or [])}
        self.registry = registry
        self.logger = logging.getLogger(f"Plant.{self.__class__.__name__}")

    # Topic Discussion
    def respond_to_topic(self, topic: Dict, previous_responses: List[Dict] = None) -> Dict:
        """回應議題討論（供 Mediator 主持使用），子類別應覆寫以提供角色特化回應"""
        topic_text = f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n描述: {topic.get('description', '')}\n類型: {topic.get('type', '')}"

        prev_text = ""
        if previous_responses:
            parts = []
            for r in previous_responses:
                agent = r.get("agent", "?")
                resp = r.get("response", {})
                content = resp.get("content", resp.get("position", json.dumps(resp, ensure_ascii=False)))
                parts.append(f"【{agent}】{content}")
            prev_text = "\n前面的發言:\n" + "\n".join(parts)

        user_prompt = f"""你正在參與一場需求討論會議。請針對以下議題，從你的專業角色角度提供意見。

{topic_text}
{prev_text}

# 回應要求
1. position: 從你的角色出發的明確立場
2. arguments: 支持你立場的具體論點（至少 2 個）
3. suggestions: 可行的具體建議（至少 2 個）
4. questions_to_others: 想請其他角色回答的問題（可為空陣列）

# 約束
- 只從你的角色專業角度發言，不要代替其他角色
- 論點必須基於已知資訊，禁止捏造

輸出 JSON:
{{{{
    "position": "你的立場",
    "arguments": ["論點1", "論點2"],
    "suggestions": ["建議1", "建議2"],
    "questions_to_others": [{{{{"to": "agent名稱", "question": "問題內容"}}}}]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages)

        result = {
            "agent": self.name,
            "position": response.get("position", ""),
            "arguments": response.get("arguments", []),
            "suggestions": response.get("suggestions", []),
            "questions_to_others": response.get("questions_to_others", []),
        }
        return result

    # Internal Helpers

    def build_direct_messages(self, task: str, context: Optional[Dict] = None) -> List[Dict]:
        messages = []
        messages.append({"role": "system", "content": self.system_prompt})

        task_parts = [task]
        if context:
            task_parts.append(f"\n上下文資料:\n{json.dumps(context, ensure_ascii=False, indent=2)}")
        messages.append({"role": "user", "content": "\n".join(task_parts)})
        return messages

    def execute_tool(self, tool_name: str, tool_args: Dict) -> str:
        if tool_name not in self.tools:
            return f"錯誤: 未知工具 '{tool_name}'，可用: {list(self.tools.keys())}"

        tool = self.tools[tool_name]
        if not tool.validate_args(**tool_args):
            return f"錯誤: 工具 '{tool_name}' 參數不完整"

        try:
            return tool.execute(**tool_args)
        except Exception as e:
            return f"工具 '{tool_name}' 執行失敗: {str(e)}"

