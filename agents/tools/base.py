# Defines available agent tools and tool execution behavior.
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


# Defines BaseTool class for this module workflow.
class BaseTool(ABC):
    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}

    @abstractmethod
    # Defines execute function for this module workflow.
    def execute(self, **kwargs) -> str:
        pass

    # Defines validate args function for this module workflow.
    def validate_args(self, **kwargs) -> bool:
        for param_name, param_info in self.parameters.items():
            if param_info.get("required", False) and param_name not in kwargs:
                return False
        return True


def is_tool_allowed(policy: Any, agent_name: str, tool_name: str, active_skill: Optional[str] = None) -> bool:
    if not policy:
        return True
    check = getattr(policy, "check_tool_access", None)
    if callable(check):
        allowed, _ = check(agent_name, tool_name, active_skill)
        return bool(allowed)
    if not policy.can_agent_use_tool(agent_name, tool_name):
        return False
    if active_skill and not policy.can_skill_use_tool(active_skill, tool_name):
        return False
    return True


def tool_access_error(policy: Any, agent_name: str, tool_name: str, active_skill: Optional[str] = None) -> str:
    if not policy:
        return ""
    check = getattr(policy, "check_tool_access", None)
    if callable(check):
        allowed, reason = check(agent_name, tool_name, active_skill)
        return "" if allowed else reason
    if not policy.can_agent_use_tool(agent_name, tool_name):
        return f"Policy 禁止 Agent '{agent_name}' 使用工具 '{tool_name}'"
    if active_skill and not policy.can_skill_use_tool(active_skill, tool_name):
        return f"Policy 禁止在 skill '{active_skill}' 使用工具 '{tool_name}'"
    return ""


def allowed_tool_items(
    tools: Dict[str, Any],
    *,
    policy: Any,
    agent_name: str,
    active_skill: Optional[str] = None,
):
    for tool_name, tool in tools.items():
        if is_tool_allowed(policy, agent_name, tool_name, active_skill):
            yield tool_name, tool


def build_tool_context_message(
    tools: Dict[str, Any],
    *,
    policy: Any,
    agent_name: str,
    active_skill: Optional[str] = None,
    policy_text: str = "",
) -> Optional[Dict[str, str]]:
    tool_lines = []
    for tool_name, tool in allowed_tool_items(
        tools,
        policy=policy,
        agent_name=agent_name,
        active_skill=active_skill,
    ):
        description = str(getattr(tool, "description", "") or "").strip()
        tool_lines.append(f"- {tool_name}: {description}")

    if not tool_lines:
        return None

    skill_line = f"\n# 啟用的 Skill\n{active_skill}\n" if active_skill else ""
    policy_section = f"\n# 工具使用規則\n{policy_text}\n" if policy_text else ""
    content = (
        "# 工具使用資料\n"
        "以下內容說明本輪可用工具與使用邊界，不是任務輸出格式。\n"
        f"{skill_line}"
        "\n# 可用工具\n"
        + "\n".join(tool_lines)
        + policy_section
    )
    return {"role": "user", "content": content}


def build_tool_schemas(
    tools: Dict[str, Any],
    *,
    policy: Any,
    agent_name: str,
    active_skill: Optional[str] = None,
) -> list[Dict[str, Any]]:
    schemas: list[Dict[str, Any]] = []
    for _, tool in allowed_tool_items(
        tools,
        policy=policy,
        agent_name=agent_name,
        active_skill=active_skill,
    ):
        properties = {}
        required = []
        for pname, pinfo in tool.parameters.items():
            ptype = pinfo.get("type", "string")
            prop = {
                "type": pinfo.get("type", "string"),
                "description": pinfo.get("description", ""),
            }
            if ptype == "array":
                prop["items"] = pinfo.get("items", {"type": "string"})
            properties[pname] = prop
            if pinfo.get("required", False):
                required.append(pname)
        schemas.append(
            {
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
            }
        )
    return schemas
