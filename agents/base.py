import json
import logging

from typing import Dict, List, Any, Optional
from agents.memory import Memory
from agents.tools.base import BaseTool


GLOBAL_GUARDRAILS = """
# 全域約束
1. 只根據已提供的資料回應，禁止捏造不存在的需求、來源或數據
2. 若資訊不足，明確指出「資訊不足」，不得推測
3. 嚴格遵守指定的 JSON 輸出格式
4. 回應語言：繁體中文"""


class BaseAgent:
    """Agent 基礎類別

    四大核心能力：
    1. Tool Use   — self.tools
    2. Memory     — self.memory (短期/長期)
    3. ReAct      — self.run() 多步推理迴圈
    4. Reflection — self.reflect() 自我評估
    """

    name: str = ""
    system_prompt: str = ""
    reflection_criteria: str = ""

    def __init__(self, model, tools: Optional[List[BaseTool]] = None,
                 memory: Optional[Memory] = None, registry=None):
        self.model = model
        self.tools: Dict[str, BaseTool] = {t.name: t for t in (tools or [])}
        self.memory = memory or Memory()
        self.registry = registry
        self.logger = logging.getLogger(f"Plant.{self.__class__.__name__}")

    # ReAct Loop

    def run(self, task: str, context: Optional[Dict] = None,
            max_steps: int = 3, output_format: str = "json",
            min_tool_uses: int = 0, max_reflection_retries: int = 1) -> Any:
        """ReAct 推理迴圈：Think → Act → Observe → Repeat

        行動步數（use_tool / 格式錯誤）與 Reflection 重試分開計數，
        Reflection 失敗不消耗行動步數。
        """
        task_prompt = self.build_task_prompt(task, context)
        self.memory.add("user", task_prompt)

        tool_use_count = 0
        step = 0
        reflection_retries = 0

        while step < max_steps:
            self.logger.debug(f"ReAct step {step + 1}/{max_steps}")
            messages = self.build_react_messages()

            try:
                response = self.model.chat_json(messages)
            except Exception as e:
                self.logger.warning(f"ReAct step {step + 1} LLM 呼叫失敗: {e}")
                break

            thought = response.get("thought", "")
            action = response.get("action", "respond")

            if thought:
                self.logger.debug(f"Thought: {thought}")
                self.memory.add("assistant", f"[Thought] {thought}")

            if action == "use_tool":
                tool_name = response.get("tool_name", "")
                tool_args = response.get("tool_args", {})
                result = self.execute_tool(tool_name, tool_args)
                self.memory.add("observation", f"[Tool: {tool_name}] {result}")
                tool_use_count += 1
                step += 1

            elif action == "respond":
                if min_tool_uses > 0 and tool_use_count < min_tool_uses:
                    remaining = min_tool_uses - tool_use_count
                    self.memory.add("system",
                        f"[System] 你還需要使用工具至少 {remaining} 次才能輸出最終回應。")
                    step += 1
                    continue

                output = response.get("output", response)

                # Reflection 失敗不消耗行動步數，有獨立重試上限
                if self.reflection_criteria:
                    reflection = self.reflect(output, task)
                    if not reflection.get("acceptable", True):
                        reflection_retries += 1
                        if reflection_retries <= max_reflection_retries:
                            feedback = reflection.get("feedback", "品質不足")
                            self.memory.add("system", f"[Reflection] 請改進: {feedback}")
                            continue
                        # 重試次數已達上限，接受當前輸出
                        self.logger.warning(f"Reflection 重試已達上限（{max_reflection_retries}），接受當前輸出")

                self.memory.add("assistant", json.dumps(output, ensure_ascii=False) if isinstance(output, dict) else str(output))
                return output

            else:
                if min_tool_uses > 0 and tool_use_count < min_tool_uses:
                    self.memory.add("system",
                        f"[System] 回應格式不正確，需包含 action 欄位。還需使用工具 {min_tool_uses - tool_use_count} 次。")
                    step += 1
                    continue

                self.logger.warning(f"未知 action: {action}，視為 respond")
                return response.get("output", response)

        self.logger.warning(f"ReAct 步數用盡（{max_steps}），降級為直接生成")
        return self.direct_generate(task, context, output_format)

    # Reflection

    def reflect(self, output: Any, original_task: str) -> Dict:
        output_text = json.dumps(output, ensure_ascii=False, indent=2) if isinstance(output, dict) else str(output)

        prompt = f"""請嚴格評估以下輸出是否符合任務要求和品質標準。

# 原始任務
{original_task[:500]}

# 輸出內容
{output_text[:1000]}

# 評估標準
{self.reflection_criteria}

# 評估重點
1. 輸出是否完整涵蓋任務要求的所有項目？
2. 內容是否有捏造、模糊或缺乏依據的部分？
3. JSON 格式是否符合要求的 Schema？

輸出 JSON:
{{
    "acceptable": true 或 false,
    "feedback": "具體改進建議（若可接受填 '符合標準'）"
}}"""

        try:
            return self.model.generate_json(prompt, self.system_prompt)
        except Exception as e:
            self.logger.warning(f"反思失敗: {e}")
            return {"acceptable": True, "feedback": "反思機制執行失敗，預設通過"}

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

# 約束
- 只從你的角色專業角度發言，不要代替其他角色
- 論點必須基於已知資訊，禁止捏造

輸出 JSON:
{{{{
    "position": "你的立場",
    "arguments": ["論點1", "論點2"],
    "suggestions": ["建議1", "建議2"]
}}}}"""

        self.memory.add("user", f"回應議題: {topic.get('title', '')[:50]}")
        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages)

        result = {
            "agent": self.name,
            "position": response.get("position", ""),
            "arguments": response.get("arguments", []),
            "suggestions": response.get("suggestions", []),
        }
        self.memory.add("assistant", f"已回應議題: {result['position'][:50]}...")
        return result

    # Direct Generate

    def direct_generate(self, task: str, context: Optional[Dict] = None,
                         output_format: str = "json") -> Any:
        messages = self.build_direct_messages(task, context)
        if output_format == "json":
            return self.model.chat_json(messages)
        return self.model.chat(messages)

    # Generate with Reflection

    def generate_with_reflection(self, task: str, context=None,
                                  output_format="json", max_retries=1,
                                  **model_kwargs) -> Any:
        """生成 + 反思 + 修正：所有 agent 通用的品質把關方法

        對設了 reflection_criteria 的 agent 自動執行「生成 → 反思 → 修正」迴圈。
        """
        messages = self.build_direct_messages(task, context)
        if output_format == "json":
            response = self.model.chat_json(messages, **model_kwargs)
        else:
            response = self.model.chat(messages, **model_kwargs)

        if self.reflection_criteria and max_retries > 0:
            for attempt in range(max_retries):
                reflection = self.reflect(response, task)
                if reflection.get("acceptable", True):
                    break
                feedback = reflection.get("feedback", "品質不足")
                self.memory.add("system", f"[Reflection] 請改進: {feedback}")
                retry_task = f"{task}\n\n注意：上次的問題是: {feedback}\n請改進。"
                messages = self.build_direct_messages(retry_task, context)
                if output_format == "json":
                    response = self.model.chat_json(messages, **model_kwargs)
                else:
                    response = self.model.chat(messages, **model_kwargs)

        self.memory.add("assistant",
            json.dumps(response, ensure_ascii=False) if isinstance(response, dict) else str(response))
        return response

    # Internal Helpers

    def build_task_prompt(self, task: str, context: Optional[Dict] = None) -> str:
        parts = [task]
        if context:
            parts.append(f"\n上下文資料:\n{json.dumps(context, ensure_ascii=False, indent=2)}")
        return "\n".join(parts)

    def build_react_messages(self) -> List[Dict]:
        messages = []
        system_parts = [self.system_prompt, GLOBAL_GUARDRAILS]

        memory_context = self.memory.get_context_prompt()
        if memory_context:
            system_parts.append(memory_context)

        action_prompt = self.build_action_prompt()
        if action_prompt:
            system_parts.append(action_prompt)

        messages.append({"role": "system", "content": "\n\n".join(system_parts)})

        for msg in self.memory.messages:
            role = msg["role"]
            if role not in ("user", "assistant"):
                role = "user"
            messages.append({"role": role, "content": msg["content"]})

        return messages

    def build_direct_messages(self, task: str, context: Optional[Dict] = None) -> List[Dict]:
        messages = []
        system_parts = [self.system_prompt, GLOBAL_GUARDRAILS]
        memory_context = self.memory.get_context_prompt()
        if memory_context:
            system_parts.append(memory_context)

        messages.append({"role": "system", "content": "\n\n".join(system_parts)})
        messages.append({"role": "user", "content": self.build_task_prompt(task, context)})
        return messages

    def build_action_prompt(self) -> str:
        if not self.tools:
            return ""

        parts = ["\n# 可用行動\n"]

        parts.append("工具:")
        for tool in self.tools.values():
            parts.append(tool.to_prompt_description())

        parts.append("""
# 回應格式（必須嚴格遵守）

每次回應必須是合法 JSON，且包含 "action" 欄位（use_tool / respond）。

【use_tool】:
{"thought": "...", "action": "use_tool", "tool_name": "工具名稱", "tool_args": {"參數名": "參數值"}}

【respond】:
{"thought": "...", "action": "respond", "output": { ... }}

規則：每次只能選一個 action，output 只在 respond 時使用。""")

        return "\n".join(parts)

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

