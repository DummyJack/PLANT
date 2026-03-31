import json
import re
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from typing import Dict, List, Optional, Any
from agents.tools.base import BaseTool


class BaseAgent:
    name: str = ""
    system_prompt: str = ""
    tool_call_max_rounds: int = 3

    def __init__(
        self,
        model,
        tools: Optional[List[BaseTool]] = None,
        registry=None,
        skill_names: Optional[List[str]] = None,
    ):
        self.model = model
        self.tools: Dict[str, BaseTool] = {t.name: t for t in (tools or [])}
        self.registry = registry
        self.skill_names: List[str] = list(skill_names or [])
        self.policy = None
        self.logger = logging.getLogger(f"Plant.{self.__class__.__name__}")
        # 由 Flow 依 rough_idea 偵測後設定；預設繁中
        self.output_language: str = "zh-TW"

    def parse_topic_response_json(self, raw: str) -> Dict[str, Any]:
        """解析工具迴圈輸出中的 JSON。"""
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
        """有 tools 則 chat_with_tools，否則 chat_json。"""
        if self.tools:
            raw = self.chat_with_tools(messages, max_rounds=self.tool_call_max_rounds)
            if parse_json:
                parsed = self.parse_topic_response_json(raw)
                # 若解析後 statement 為空但模型有產出文字，用原始文字當 fallback，避免發言/回答留空
                if not (parsed.get("statement") or "").strip() and (raw or "").strip():
                    fallback = (raw or "").strip()
                    for prefix in ("```json", "```"):
                        if fallback.startswith(prefix):
                            fallback = fallback[len(prefix) :].strip()
                    if fallback.endswith("```"):
                        fallback = fallback[:-3].strip()
                    parsed["statement"] = fallback
                return parsed
            return {"statement": raw, "open_questions": []}
        action = kwargs.pop("action", f"{self.name}.topic.response")
        return self.model.chat_json(messages, action=action, **kwargs)

    def usage_action(self, suffix: str) -> str:
        return f"{self.name}.{suffix}"

    def format_previous_responses(
        self,
        previous_responses: Optional[List[Dict[str, Any]]],
        *,
        title: str = "前面的發言",
    ) -> str:
        """格式化前文發言（含 speaking_as）。"""
        if not previous_responses:
            return ""
        parts: List[str] = []
        for r in previous_responses:
            agent_name = r.get("agent", "?")
            resp = r.get("response", {}) if isinstance(r.get("response"), dict) else {}
            statement = resp.get("statement", "")
            speaking_as = resp.get("speaking_as", [])
            if isinstance(speaking_as, str):
                speaking_as = [speaking_as]
            speaking_as = [s for s in speaking_as if isinstance(s, str) and s.strip()]
            role_hint = f"（代表：{'、'.join(speaking_as)}）" if speaking_as else ""
            parts.append(f"【{agent_name}{role_hint}】\n{statement}")
        return f"\n# {title}\n" + "\n\n".join(parts)

    def get_global_conventions_suffix(self) -> str:
        """全域輸出慣例後綴；子類可覆寫為 ''。"""
        from utils import global_conventions_text

        text = global_conventions_text(self.output_language)
        if not text:
            return ""
        return f"\n\n# 全域輸出慣例\n{text}"

    def lang_directive(self) -> str:
        """task 內語系指示。"""
        from utils import directive_embed

        return directive_embed(self.output_language)

    def get_optional_skill_context(
        self, topic: Dict, artifact_snapshot: Optional[Dict]
    ) -> Optional[str]:
        """可選 skill 參考；預設 None。子類覆寫。"""
        return None

    def respond_to_topic(
        self,
        topic: Dict,
        previous_responses: Optional[List[Dict]] = None,
        artifact_snapshot: Optional[Dict] = None,
    ) -> Dict:
        """子類覆寫：議題回應。"""
        topic_text = f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n描述: {topic.get('description', '')}"

        prev_text = self.format_previous_responses(
            previous_responses, title="前面的發言"
        )

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
- 投票將在討論結束後另行進行，發言時只需專注表達觀點

# 發言風格（像現實會議中的專家）
- 用完整句子、自然語氣表達，如同真人開會發言，避免制式開場白或逐條列點堆砌
- 可適當保留不確定性（例如「依目前資訊看來…」「若在…前提下，建議…」）
- 論點簡潔有據，需要時再展開說明
- 建議採「先結論、再依據、再風險/下一步」的會議表達結構

# 約束
- 只從你的角色專業角度發言，不要代替其他角色
- statement 必須是完整、有條理的發言內容
- 論點必須基於已知資訊，禁止捏造
- 若資訊不足，需明確說明不確定處與待確認事項

輸出 JSON:
{{{{
    "statement": "針對此議題的完整發言內容",
    "open_questions": [{{{{"to": "目標 agent 名稱", "question": "問題內容"}}}}]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.chat_for_topic_response(
            messages,
            action=self.usage_action("topic.response"),
        )

        return {
            "agent": self.name,
            "statement": response.get("statement", ""),
            "open_questions": response.get("open_questions", []),
        }

    def vote_on_topic(
        self,
        topic: Dict,
        previous_responses: Optional[List[Dict]] = None,
        artifact_snapshot: Optional[Dict] = None,
        mediator_compromise: Optional[Dict] = None,
    ) -> Dict[str, str]:
        """議題討論完成後的最終投票。僅回傳 vote 與簡短理由。

        若傳入 mediator_compromise 且含有效方案內容，表決對象為「是否同意採納該主持人方案」，
        而非評判其他與會者發言。
        """
        topic_text = f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n描述: {topic.get('description', '')}"

        mc = mediator_compromise or {}
        mc_title = (mc.get("title") or "").strip()
        mc_desc = (mc.get("description") or "").strip()
        mc_rat = (mc.get("rationale") or "").strip()
        has_mediator_package = bool(mc_desc or mc_title)

        prev_text = ""
        if not has_mediator_package:
            prev_text = self.format_previous_responses(
                previous_responses, title="本議題討論摘要（依發言順序）"
            )

        proposal_text = ""
        if has_mediator_package:
            proposal_text = (
                "\n# 主持人提出的折衷方案（**本題唯一表決對象**）\n"
                f"**標題**: {mc_title or '（無標題）'}\n\n"
                f"**內容**:\n{mc_desc}\n\n"
                f"**說明**: {mc_rat}\n\n"
                "**重要**: 請僅針對上述主持人方案表決是否願意採納為本議題決議基礎；"
                "勿改為比較或評判其他與會者先前發言孰是孰非。\n"
            )

        snapshot_text = ""
        if artifact_snapshot:
            snapshot_text = f"\n# 當前專案狀態（供參考）\n{json.dumps(artifact_snapshot, ensure_ascii=False, indent=2)}"

        if has_mediator_package:
            task_block = """# 任務
- 你正在對「主持人折衷方案」表決是否同意採納（非對整場發言做總評）
- 只需給出 vote 與簡短 rationale（1-2 句）

# 投票規則
- vote 只能是 "agreed" 或 "unresolved"
- agreed：你**同意**以主持人方案作為本議題決議基礎
- unresolved：你**無法接受**該方案（或認為仍有違反你專業底線／關鍵資訊不足），需再修訂
"""
        else:
            task_block = """# 任務
- 主持人方案未能產生，請根據本議題討論摘要與你的專業立場表決
- 只需給出 vote 與簡短 rationale（1-2 句）

# 投票規則
- vote 只能是 "agreed" 或 "unresolved"
- agreed：你認為本議題可形成決策
- unresolved：你認為仍有重要衝突或關鍵不確定，暫不應定案
"""

        user_prompt = f"""你正在進行本議題的「最終投票」。

{topic_text}
{proposal_text}{prev_text}
{snapshot_text}

{task_block}
# 約束
- 不要重寫長篇發言
- 不要新增 open_questions
- 若資訊不足，請投 unresolved 並在 rationale 說明原因

輸出 JSON:
{{
    "vote": "agreed 或 unresolved",
    "rationale": "簡短理由"
}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.chat_for_topic_response(
            messages,
            action=self.usage_action("topic.vote"),
        )
        v = (response.get("vote") or "").strip().lower()
        vote = "agreed" if v == "agreed" else "unresolved"
        rationale = (
            response.get("rationale")
            or response.get("reason")
            or response.get("statement")
            or ""
        )
        return {"agent": self.name, "vote": vote, "rationale": rationale}

    def invoke_skill(
        self,
        skill_name: str,
        task: str,
        context: Optional[Dict] = None,
    ) -> str:
        """
        依名稱呼叫 agent 已賦予的 skill：載入該 skill 的內容與 references，
        組 system + user message 後呼叫 model，回傳模型輸出的字串。
        若此 agent 未賦予該 skill（skill_name 不在 self.skill_names），則拋錯。
        """
        if skill_name not in self.skill_names:
            raise ValueError(
                f"Agent '{self.name}' 未賦予 skill '{skill_name}'，可用: {self.skill_names}"
            )
        if self.policy and not self.policy.can_agent_use_skill(self.name, skill_name):
            raise ValueError(f"Policy 禁止 Agent '{self.name}' 使用 skill '{skill_name}'")
        from agents.skills.base import get_skill

        skill = get_skill(skill_name)
        system_parts = [self.system_prompt]
        if skill.get("content_system"):
            system_parts.append(f"\n\n# Skill: {skill.get('name', skill_name)}\n\n")
            system_parts.append(skill["content_system"])
        user_content = skill.get("content_user") or skill["content"]
        user_parts = []
        if not skill.get("content_system"):
            user_parts.append(f"# Skill: {skill.get('name', skill_name)}\n\n")
        user_parts.extend(
            [
                f"# 輸出語系（必須遵守）\n{self.lang_directive()}\n\n",
                user_content,
                "\n\n# Task\n\n",
                task,
            ]
        )
        if skill.get("template"):
            user_parts.append("\n\n# 範本（必須依此結構）\n\n")
            user_parts.append(skill["template"])
        if skill.get("checklist"):
            user_parts.append("\n\n# 品質檢查清單（產出前須自檢通過）\n\n")
            user_parts.append(skill["checklist"])
        for ref_name, ref_content in (skill.get("reference_files") or {}).items():
            user_parts.append(f"\n\n# {ref_name}\n\n")
            user_parts.append(ref_content)
        if context is not None:
            user_parts.append(f"\n\n# Context\n{json.dumps(context, ensure_ascii=False, indent=2)}")

        suffix = self.get_global_conventions_suffix()
        if suffix:
            system_parts.append(suffix)
        messages = [
            {"role": "system", "content": "".join(system_parts)},
            {"role": "user", "content": "\n".join(user_parts)},
        ]
        if self.tools:
            return self.chat_with_tools(
                messages,
                max_rounds=self.tool_call_max_rounds,
                active_skill=skill_name,
            )
        return self.model.chat(
            messages,
            action=self.usage_action(f"skill.{skill_name}"),
        )

    def build_direct_messages(self, task: str, context: Optional[Dict] = None) -> List[Dict]:
        messages = []
        system_content = self.system_prompt + self.get_global_conventions_suffix()
        messages.append({"role": "system", "content": system_content})

        task_parts = [
            f"# 輸出語系（必須遵守）\n{self.lang_directive()}\n",
            task,
        ]
        if context:
            task_parts.append(f"\n上下文資料:\n{json.dumps(context, ensure_ascii=False, indent=2)}")
        messages.append({"role": "user", "content": "\n".join(task_parts)})
        return messages

    def execute_tool(
        self, tool_name: str, tool_args: Dict, *, active_skill: Optional[str] = None
    ) -> str:
        if tool_name not in self.tools:
            return f"錯誤: 未知工具 '{tool_name}'，可用: {list(self.tools.keys())}"
        if self.policy and not self.policy.can_agent_use_tool(self.name, tool_name):
            return f"錯誤: Policy 禁止 Agent '{self.name}' 使用工具 '{tool_name}'"
        if (
            active_skill
            and self.policy
            and not self.policy.can_skill_use_tool(active_skill, tool_name)
        ):
            return (
                f"錯誤: Policy 禁止在 skill '{active_skill}' 使用工具 '{tool_name}'"
            )

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

    def supports_gemini_tool_calling(self) -> bool:
        """Gemini（google-genai）手動 function calling，見 GeminiModel.gemini_chat_with_tools。"""
        return callable(getattr(self.model, "gemini_chat_with_tools", None))

    def reset_tool_sessions(self) -> None:
        for t in (self.tools or {}).values():
            reset = getattr(t, "reset_session", None)
            if callable(reset):
                try:
                    reset()
                except Exception as e:
                    self.logger.debug("tool reset_session: %s", e)

    def chat_with_tools(
        self,
        messages: List[Dict],
        max_rounds: int = 3,
        *,
        active_skill: Optional[str] = None,
    ) -> str:
        """帶 tool-call 迴圈的 chat：模型可多次呼叫工具，最終回傳文字結果。若 client 不支援 tool calling 則改為普通 chat。
        active_skill：若為 skill 情境（如 domain-research），會額外套用 policy.can_skill_use_tool。"""
        self.reset_tool_sessions()
        if not self.tools:
            return self.model.chat(
                messages,
                action=self.usage_action("chat.with_tools"),
            )
        if self.supports_gemini_tool_calling():
            return self.model.gemini_chat_with_tools(
                messages,
                openai_style_tool_schemas=self.get_tool_schemas(),
                execute_tool_fn=lambda name, args: self.execute_tool(
                    name, args, active_skill=active_skill
                ),
                max_rounds=max_rounds,
                action=self.usage_action(
                    f"tool_loop.{active_skill}" if active_skill else "tool_loop.general"
                ),
            )
        if not self.supports_tool_calling():
            self.logger.warning("目前 model client 不支援 tool calling，改為普通 chat（工具不會被呼叫）")
            return self.model.chat(
                messages,
                action=self.usage_action("chat.no_tool_support"),
            )

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
                return self.model.chat(
                    messages,
                    action=self.usage_action("chat.tool_calling_fallback"),
                )
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
                result = self.execute_tool(
                    fname, fargs, active_skill=active_skill
                )
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
                    result = self.execute_tool(
                        fname, fargs, active_skill=active_skill
                    )
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
            return self.model.chat(
                messages,
                action=self.usage_action("chat.final_fallback"),
            )
