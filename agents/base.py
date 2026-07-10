# Defines shared agent base behavior and LLM call flow.
import json
import logging

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from agents.profile.loop import AgentLoop
from agents.meeting.issue import IssueResponseSupport
from agents.skills.base import SkillSupport
from agents.tools.base import (
    build_tool_context_message,
    build_tool_schemas,
    tool_access_error,
)
from server.services.run_checkpoint import record_run_checkpoint
from storage.artifact import save_artifact as save_split_artifact
from utils.language import output_language_directive
from agents.profile.base import json_format_instruction

if TYPE_CHECKING:
    from agents.tools.base import BaseTool



# ========
# Defines AgentRegistry class for this module workflow.
# ========
class AgentRegistry:
    # Defines __init__ function for this module workflow.
    def __init__(self):
        self.agents: Dict[str, Any] = {}

    # Defines register function for this module workflow.
    def register(self, name: str, agent):
        self.agents[name] = agent

    # Defines get function for this module workflow.
    def get(self, agent_name: str):
        return self.agents.get(agent_name)

    # Defines get names function for this module workflow.
    def get_names(self) -> list:
        return list(self.agents.keys())


# ========
# Defines response language directive function for this module workflow.
# ========
def response_language_directive() -> str:
    return output_language_directive()


def available_data_block(context: Dict[str, Any]) -> str:
    return (
        "# Context\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2)}"
    )


def insert_context_before_task(content: str, context: Optional[Dict[str, Any]]) -> str:
    if context is None:
        return content
    block = available_data_block(context) + "\n\n"
    marker = "# 任務\n"
    idx = content.find(marker)
    if idx >= 0:
        return f"{content[:idx]}{block}{content[idx:]}"
    return f"{block}{content}"

# ========
# Defines parse json payload function for this module workflow.
# ========
def parse_json_payload(raw: str) -> Any:
    if not raw or not isinstance(raw, str):
        return {}
    text = raw.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    candidates = []
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            value = part.strip()
            if value.lower().startswith("json"):
                value = value[4:].strip()
            if (
                (value.startswith("{") and value.endswith("}"))
                or (value.startswith("[") and value.endswith("]"))
            ):
                candidates.append(value)
    for open_char, close_char in (("{", "}"), ("[", "]")):
        start = text.find(open_char)
        end = text.rfind(close_char)
        if start >= 0 and end > start:
            candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise ValueError("Agent output must be a valid JSON object or array.")


# ========
# Defines parse json object function for this module workflow.
# ========
def parse_json_object(raw: str) -> Dict[str, Any]:
    data = parse_json_payload(raw)
    if not isinstance(data, dict):
        raise ValueError("Agent output must be a valid JSON object.")
    return data


# ========
# Defines ToolCallingSupport class for this module workflow.
# ========
class ToolCallingSupport:
    # Defines tool usage policy function for this module workflow.
    def tool_usage_policy(self, active_skill: Optional[str] = None) -> str:
        return ""

    # Defines tool context message function for this module workflow.
    def tool_context_message(
        self,
        active_skill: Optional[str] = None,
    ) -> Optional[Dict[str, str]]:
        if not self.tools:
            return None

        policy_text = str(self.tool_usage_policy(active_skill) or "").strip()
        return build_tool_context_message(
            self.tools,
            policy=self.policy,
            agent_name=self.name,
            active_skill=active_skill,
            policy_text=policy_text,
        )

    # Defines messages with tool context function for this module workflow.
    def messages_with_tool_context(
        self,
        messages: List[Dict[str, Any]],
        active_skill: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        updated = list(messages or [])
        context_message = self.tool_context_message(active_skill=active_skill)
        if context_message:
            updated.append(context_message)
        return updated

    # Defines execute tool function for this module workflow.
    def execute_tool(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        *,
        active_skill: Optional[str] = None,
    ) -> str:
        if tool_name not in self.tools:
            return f"錯誤: 未知工具 '{tool_name}'，可用: {list(self.tools.keys())}"
        access_error = tool_access_error(self.policy, self.name, tool_name, active_skill)
        if access_error:
            return f"錯誤: {access_error}"

        tool = self.tools[tool_name]
        if not tool.validate_args(**tool_args):
            return f"錯誤: 工具 '{tool_name}' 參數不完整"

        try:
            return tool.execute(**tool_args)
        except Exception as e:
            return f"工具 '{tool_name}' 執行失敗: {str(e)}"

    # Defines get tool schemas function for this module workflow.
    def get_tool_schemas(self, active_skill: Optional[str] = None) -> List[Dict]:
        return build_tool_schemas(
            self.tools,
            policy=self.policy,
            agent_name=self.name,
            active_skill=active_skill,
        )

    # Defines supports tool calling function for this module workflow.
    def supports_tool_calling(self) -> bool:
        try:
            c = getattr(self.model, "client", None)
            return hasattr(c, "chat") and hasattr(c.chat, "completions")
        except Exception:
            return False

    # Defines supports gemini tool calling function for this module workflow.
    def supports_gemini_tool_calling(self) -> bool:
        return callable(getattr(self.model, "gemini_chat_with_tools", None))

    # Defines reset tool sessions function for this module workflow.
    def reset_tool_sessions(self) -> None:
        for t in (self.tools or {}).values():
            reset = getattr(t, "reset_session", None)
            if callable(reset):
                try:
                    reset()
                except Exception as e:
                    self.logger.debug("tool reset_session: %s", e)

    # Defines artifact query tool function for this module workflow.
    def artifact_query_tool(self) -> Optional["BaseTool"]:
        tool = (self.tools or {}).get("artifact_query")
        return tool

    # Defines load artifact context from files function for this module workflow.
    def load_artifact_context_from_files(self) -> Dict[str, Any]:
        tool = self.artifact_query_tool()
        load_artifact = getattr(tool, "load_artifact", None)
        if not callable(load_artifact):
            return {}
        try:
            artifact = load_artifact()
        except Exception as e:
            self.logger.debug("artifact_query load_artifact failed: %s", e)
            return {}
        return artifact if isinstance(artifact, dict) else {}

    # Defines sync artifact context files function for this module workflow.
    def sync_artifact_context_files(self, artifact: Optional[Dict[str, Any]]) -> None:
        if not isinstance(artifact, dict):
            return
        tool = self.artifact_query_tool()
        artifact_path = getattr(tool, "artifact_path", None)
        if artifact_path is None:
            return
        try:
            if artifact_path.is_dir():
                save_split_artifact(artifact_path.parent, artifact_path, artifact)
        except Exception as e:
            self.logger.debug("artifact_query sync artifact files failed: %s", e)

    # Defines tool loop action function for this module workflow.
    def tool_loop_action(self, active_skill: Optional[str] = None) -> str:
        return self.usage_action(
            f"tool_loop.{active_skill}" if active_skill else "tool_loop.general"
        )

    # Defines parse tool arguments function for this module workflow.
    def parse_tool_arguments(self, raw_arguments: str) -> Dict[str, Any]:
        try:
            return json.loads(raw_arguments)
        except json.JSONDecodeError:
            return {}

    # Defines run single tool call function for this module workflow.
    def run_single_tool_call(
        self,
        tool_call: Any,
        *,
        active_skill: Optional[str] = None,
    ) -> tuple[str, str]:
        fname = tool_call.function.name
        fargs = self.parse_tool_arguments(tool_call.function.arguments)
        self.logger.info("🔧 %s(%s)", fname, fargs)
        result = self.execute_tool(fname, fargs, active_skill=active_skill)
        return tool_call.id, result

    # Defines append openai tool results function for this module workflow.
    def append_openai_tool_results(
        self,
        messages: List[Dict[str, Any]],
        tool_calls_list: List[Any],
        *,
        active_skill: Optional[str] = None,
    ) -> None:
        if len(tool_calls_list) == 1:
            tool_call_id, result = self.run_single_tool_call(
                tool_calls_list[0], active_skill=active_skill
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": result,
                }
            )
            return

        max_workers = min(len(tool_calls_list), 6)
        results_by_id: Dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_tc = {
                executor.submit(
                    self.run_single_tool_call, tc, active_skill=active_skill
                ): tc
                for tc in tool_calls_list
            }
            for future in as_completed(future_to_tc):
                tc = future_to_tc[future]
                try:
                    tool_call_id, result = future.result()
                    results_by_id[tool_call_id] = result
                except Exception as e:
                    results_by_id[tc.id] = f"工具執行失敗: {e}"
        for tc in tool_calls_list:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": results_by_id.get(tc.id, ""),
                }
            )

    # Defines chat with gemini tools function for this module workflow.
    def chat_with_gemini_tools(
        self,
        messages: List[Dict[str, Any]],
        max_rounds: int,
        *,
        active_skill: Optional[str] = None,
    ) -> str:
        return self.model.gemini_chat_with_tools(
            messages,
            openai_style_tool_schemas=self.get_tool_schemas(active_skill),
            execute_tool_fn=lambda name, args: self.execute_tool(
                name, args, active_skill=active_skill
            ),
            max_rounds=max_rounds,
            action=self.tool_loop_action(active_skill),
        )

    # Defines chat with openai tools function for this module workflow.
    def chat_with_openai_tools(
        self,
        messages: List[Dict[str, Any]],
        max_rounds: int,
        *,
        active_skill: Optional[str] = None,
    ) -> str:
        tool_schemas = self.get_tool_schemas(active_skill)
        action = self.tool_loop_action(active_skill)
        tracker = self.model.costTracker
        for _ in range(max_rounds):
            tracker.start()
            response = None
            try:
                response = self.model.client.chat.completions.create(
                    model=self.model.model_name,
                    messages=messages,
                    tools=tool_schemas,
                    tool_choice="auto",
                )
            except (AttributeError, TypeError) as e:
                tracker.end_segment()
                raise RuntimeError(f"tool calling failed: {e}") from e
            finally:
                run_s = tracker.end_segment()
            raw_usage = getattr(response, "usage", None)
            if raw_usage:
                self.model.add_usage(
                    {
                        "prompt_tokens": getattr(raw_usage, "prompt_tokens", 0),
                        "completion_tokens": getattr(raw_usage, "completion_tokens", 0),
                        "total_tokens": getattr(raw_usage, "total_tokens", 0),
                    },
                    action=action,
                    run_time_s=run_s,
                )
            msg = response.choices[0].message
            if not getattr(msg, "tool_calls", None):
                return msg.content or ""
            messages.append(msg.model_dump())
            self.append_openai_tool_results(
                messages,
                list(msg.tool_calls),
                active_skill=active_skill,
            )

        tracker.start()
        last = None
        try:
            last = self.model.client.chat.completions.create(
                model=self.model.model_name,
                messages=messages,
            )
        except (AttributeError, TypeError) as e:
            tracker.end_segment()
            raise RuntimeError(f"final tool calling response failed: {e}") from e
        finally:
            run_s = tracker.end_segment()
        raw_usage = getattr(last, "usage", None)
        if raw_usage:
            self.model.add_usage(
                {
                    "prompt_tokens": getattr(raw_usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(raw_usage, "completion_tokens", 0),
                    "total_tokens": getattr(raw_usage, "total_tokens", 0),
                },
                action=action,
                run_time_s=run_s,
            )
        return last.choices[0].message.content or ""

    # Defines chat with tools function for this module workflow.
    def chat_with_tools(
        self,
        messages: List[Dict],
        max_rounds: int = 5,
        *,
        active_skill: Optional[str] = None,
    ) -> str:
        self.reset_tool_sessions()
        tool_messages = self.messages_with_tool_context(
            messages,
            active_skill=active_skill,
        )
        if not self.tools or not self.get_tool_schemas(active_skill):
            return self.model.chat(
                tool_messages,
                action=self.usage_action("chat.with_tools"),
            )
        if self.supports_gemini_tool_calling():
            return self.chat_with_gemini_tools(
                tool_messages,
                max_rounds,
                active_skill=active_skill,
            )
        if not self.supports_tool_calling():
            raise RuntimeError("model client does not support tool calling")
        return self.chat_with_openai_tools(
            tool_messages,
            max_rounds,
            active_skill=active_skill,
        )


# ========
# Defines BaseAgent class for this module workflow.
# ========
class BaseAgent(AgentLoop, IssueResponseSupport, SkillSupport, ToolCallingSupport):
    name: str = ""
    system_prompt: str = ""

    # Defines __init__ function for this module workflow.
    def __init__(
        self,
        model,
        tools: Optional[List["BaseTool"]] = None,
        registry=None,
        skill_names: Optional[List[str]] = None,
        project_config: Optional[Dict[str, Any]] = None,
    ):
        self.model = model
        self.tools: Dict[str, "BaseTool"] = {t.name: t for t in (tools or [])}
        self.registry = registry
        self.skill_names: List[str] = list(skill_names or [])
        self.policy = None
        self.project_config: Dict[str, Any] = dict(project_config or {})
        self.logger = logging.getLogger(f"Plant.{self.__class__.__name__}")
        self.runtime_store = None
        self.runtime_run_id = ""

    # Defines record runtime checkpoint function for this module workflow.
    def record_runtime_checkpoint(
        self,
        *,
        stage_id: str,
        step_id: str,
        action: str = "",
    ) -> None:
        store = getattr(self, "runtime_store", None)
        run_id = str(getattr(self, "runtime_run_id", "") or "").strip()
        if not store or not run_id:
            return
        try:
            record_run_checkpoint(
                store,
                run_id=run_id,
                status="running",
                stage_id=stage_id,
                step_id=step_id,
                agent=getattr(self, "name", ""),
                action=action,
            )
        except Exception:
            logger = getattr(self, "logger", None)
            if logger:
                logger.warning("runtime checkpoint failed", exc_info=True)

    # Defines parse issue response json function for this module workflow.
    def parse_issue_response_json(self, raw: str) -> Dict[str, Any]:
        return parse_json_object(raw)


    # Defines ensure json messages function for this module workflow.
    def ensure_json_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        updated = list(messages or [])
        updated.append({"role": "user", "content": json_format_instruction()})
        return updated

    # Defines chat json function for this module workflow.
    def chat_json(self, messages: List[Dict[str, Any]], **kwargs: Any) -> Dict[str, Any]:
        return self.model.chat_json(self.ensure_json_messages(messages), **kwargs)

    # Defines usage action function for this module workflow.
    def usage_action(self, suffix: str) -> str:
        return f"{self.name}.{suffix}"

    # Defines output language directive function for this module workflow.
    def output_language_directive(self) -> str:
        return response_language_directive()

    # Defines build direct messages function for this module workflow.
    def build_direct_messages(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, str]]:
        user_parts = [
            f"# 輸出語系（必須遵守）\n{self.output_language_directive()}",
            insert_context_before_task(task, context),
        ]
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ]
