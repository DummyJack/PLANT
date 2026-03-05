import json
import re
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from typing import Dict, List, Optional, Any
from agents.tools.base import BaseTool


class BaseAgent:
    name: str = ""
    system_prompt: str = ""

    def __init__(self, model, tools: Optional[List[BaseTool]] = None, registry=None):
        self.model = model
        self.tools: Dict[str, BaseTool] = {t.name: t for t in (tools or [])}
        self.registry = registry
        self.logger = logging.getLogger(f"Plant.{self.__class__.__name__}")

    def parse_topic_response_json(self, raw: str) -> Dict[str, Any]:
        """從工具迴圈後的最終文字中解析 statement / open_questions JSON"""
        if not raw or not isinstance(raw, str):
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", raw, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass
        return {}

    def chat_for_topic_response(
        self, messages: List[Dict], parse_json: bool = True, **kwargs: Any
    ) -> Dict[str, Any]:
        """討論回合：有 tools 時走 chat_with_tools 並解析 JSON，否則 chat_json（kwargs 傳給 model.chat_json）"""
        if self.tools:
            raw = self.chat_with_tools(messages, max_rounds=3)
            if parse_json:
                return self.parse_topic_response_json(raw)
            return {"statement": raw, "open_questions": []}
        return self.model.chat_json(messages, **kwargs)

    def respond_to_topic(
        self,
        topic: Dict,
        previous_responses: Optional[List[Dict]] = None,
        artifact_snapshot: Optional[Dict] = None,
    ) -> Dict:
        """回應議題討論，子類別應覆寫以提供角色特化回應。若有 tools 可先使用再輸出 JSON。"""
        topic_text = f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n描述: {topic.get('description', '')}"

        prev_text = ""
        if previous_responses:
            parts = [f"【{r.get('agent', '?')}】\n{r.get('response', {}).get('statement', '')}"
                     for r in previous_responses]
            prev_text = "\n# 前面的發言\n" + "\n\n".join(parts)

        snapshot_text = ""
        if artifact_snapshot:
            snapshot_text = f"\n# 當前專案狀態（供參考）\n{json.dumps(artifact_snapshot, ensure_ascii=False, indent=2)}"

        tool_hint = ""
        if self.tools:
            tool_hint = "\n# 工具使用\n- 若需要查證、搜尋或驗證，可先使用可用工具。\n- 使用完工具後，**必須**根據結果與你的判斷輸出下列 JSON，勿僅回傳工具結果。"

        user_prompt = f"""你正在參與一場需求討論會議。請針對以下議題，從你的專業角色角度提供意見。

{topic_text}
{prev_text}
{snapshot_text}
{tool_hint}

# 要求
- 撰寫一段完整的發言（statement），針對議題表達你的觀點、建議與論述
- 若有需要請其他角色回答的問題，列入 open_questions（to 填寫目標 agent 名稱，如 "user"、"analyst"、"expert"、"modeler"）
- 依你的立場投票（vote）：agreed 表示你認為本議題可達成共識、可形成決策；unresolved 表示你認為仍有衝突或無法接受，需升級裁決

# 發言風格（像現實會議中的專家）
- 用完整句子、自然語氣表達，如同真人開會發言，避免制式開場白或逐條列點堆砌
- 可適當保留不確定性（例如「依目前資訊看來…」「若在…前提下，建議…」）
- 論點簡潔有據，需要時再展開說明

# 約束
- 只從你的角色專業角度發言，不要代替其他角色
- statement 必須是完整、有條理的發言內容
- 論點必須基於已知資訊，禁止捏造

輸出 JSON:
{{{{
    "statement": "針對此議題的完整發言內容",
    "vote": "agreed 或 unresolved（依你的立場）",
    "open_questions": [{{{{"to": "目標 agent 名稱", "question": "問題內容"}}}}]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.chat_for_topic_response(messages)

        return {
            "agent": self.name,
            "statement": response.get("statement", ""),
            "vote": response.get("vote", "unresolved"),
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

    def supports_tool_calling(self) -> bool:
        """是否為 OpenAI 相容 client（支援 chat.completions.create 的 tools 參數）"""
        try:
            c = getattr(self.model, "client", None)
            return hasattr(c, "chat") and hasattr(c.chat, "completions")
        except Exception:
            return False

    def chat_with_tools(self, messages: List[Dict], max_rounds: int = 3) -> str:
        """帶 tool-call 迴圈的 chat：模型可多次呼叫工具，最終回傳文字結果。若 client 不支援 tool calling 則改為普通 chat。"""
        if not self.tools:
            return self.model.chat(messages)
        if not self.supports_tool_calling():
            self.logger.warning("目前 model client 不支援 tool calling，改為普通 chat（工具不會被呼叫）")
            return self.model.chat(messages)

        tool_schemas = self.get_tool_schemas()

        for _ in range(max_rounds):
            try:
                response = self.model.client.chat.completions.create(
                    model=self.model.model_name,
                    messages=messages,
                    tools=tool_schemas,
                    tool_choice="auto",
                )
            except (AttributeError, TypeError) as e:
                self.logger.warning(f"tool calling 呼叫失敗，改為普通 chat: {e}")
                return self.model.chat(messages)
            msg = response.choices[0].message

            if not getattr(msg, "tool_calls", None):
                return msg.content or ""

            messages.append(msg.model_dump())

            tool_calls_list = list(msg.tool_calls)
            if len(tool_calls_list) == 1:
                tc = tool_calls_list[0]
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
            else:
                def run_one(tc):
                    fname = tc.function.name
                    try:
                        fargs = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        fargs = {}
                    self.logger.info(f"🔧 {fname}({fargs})")
                    result = self.execute_tool(fname, fargs)
                    return (tc.id, result)

                max_workers = min(len(tool_calls_list), 6)
                results_by_id = {}
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    future_to_tc = {executor.submit(run_one, tc): tc for tc in tool_calls_list}
                    for future in as_completed(future_to_tc):
                        tc = future_to_tc[future]
                        try:
                            tool_call_id, result = future.result()
                            results_by_id[tool_call_id] = result
                        except Exception as e:
                            results_by_id[tc.id] = f"工具執行失敗: {e}"
                for tc in tool_calls_list:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": results_by_id.get(tc.id, ""),
                    })

        try:
            last = self.model.client.chat.completions.create(
                model=self.model.model_name,
                messages=messages,
            )
            return last.choices[0].message.content or ""
        except (AttributeError, TypeError):
            return self.model.chat(messages)
