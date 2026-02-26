import json
import logging

from typing import Dict, List, Optional
from agents.tools.base import BaseTool


class BaseAgent:
    name: str = ""
    system_prompt: str = ""

    def __init__(self, model, tools: Optional[List[BaseTool]] = None, registry=None):
        self.model = model
        self.tools: Dict[str, BaseTool] = {t.name: t for t in (tools or [])}
        self.registry = registry
        self.logger = logging.getLogger(f"Plant.{self.__class__.__name__}")

    def respond_to_topic(self, topic: Dict, previous_responses: List[Dict] = None) -> Dict:
        """回應議題討論，子類別應覆寫以提供角色特化回應"""
        topic_text = f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n描述: {topic.get('description', '')}"

        prev_text = ""
        if previous_responses:
            parts = [f"【{r.get('agent', '?')}】\n{r.get('response', {}).get('statement', '')}"
                     for r in previous_responses]
            prev_text = "\n# 前面的發言\n" + "\n\n".join(parts)

        user_prompt = f"""你正在參與一場需求討論會議。請針對以下議題，從你的專業角色角度提供意見。

{topic_text}
{prev_text}

# 要求
- 撰寫一段完整的發言（statement），針對議題表達你的觀點、建議與論述
- 若有需要請其他角色回答的問題，列入 open_questions（to 填寫目標 agent 名稱，如 "user"、"analyst"、"expert"、"modeler"）

# 約束
- 只從你的角色專業角度發言，不要代替其他角色
- statement 必須是完整、有條理的發言內容
- 論點必須基於已知資訊，禁止捏造

輸出 JSON:
{{{{
    "statement": "針對此議題的完整發言內容",
    "open_questions": [{{{{"to": "目標 agent 名稱", "question": "問題內容"}}}}]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages)

        return {
            "agent": self.name,
            "statement": response.get("statement", ""),
            "open_questions": response.get("open_questions", []),
        }

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

    def get_tool_schemas(self) -> List[Dict]:
        """將 self.tools 轉為 OpenAI function calling 格式"""
        schemas = []
        for tool in self.tools.values():
            properties = {}
            required = []
            for pname, pinfo in tool.parameters.items():
                properties[pname] = {
                    "type": pinfo.get("type", "string"),
                    "description": pinfo.get("description", ""),
                }
                if pinfo.get("required", False):
                    required.append(pname)
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            })
        return schemas

    def chat_with_tools(self, messages: List[Dict], max_rounds: int = 3) -> str:
        """帶 tool-call 迴圈的 chat：模型可多次呼叫工具，最終回傳文字結果"""
        if not self.tools:
            return self.model.chat(messages)

        tool_schemas = self.get_tool_schemas()

        for _ in range(max_rounds):
            response = self.model.client.chat.completions.create(
                model=self.model.model_name,
                messages=messages,
                tools=tool_schemas,
                tool_choice="auto",
            )
            msg = response.choices[0].message

            if not msg.tool_calls:
                return msg.content or ""

            messages.append(msg.model_dump())

            for tc in msg.tool_calls:
                fname = tc.function.name
                try:
                    fargs = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    fargs = {}
                self.logger.info(f"🔧 {fname}({fargs})")
                result = self.execute_tool(fname, fargs)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        last = self.model.client.chat.completions.create(
            model=self.model.model_name,
            messages=messages,
        )
        return last.choices[0].message.content or ""
