from pathlib import Path
from typing import Any, Dict, List

from agents.policy import AgentSkillToolPolicy
from agents.profile.expert import has_supported_doc_files
from agents.tools import PlantUMLValidatorTool, WebSearchTool
from agents.tools.file_parser import FileParserTool


class ToolRegistry:
    """宣告式工具註冊與配置入口。"""

    def __init__(self, config: Dict[str, Any], policy: AgentSkillToolPolicy):
        self.config = config
        self.policy = policy
        self.enable_tools = config.get("enable_tools") or {}

    def build_tools_for_agent(self, agent_name: str) -> List[Any]:
        allowed = set(self.policy.allowed_tools_for_agent(agent_name))
        built: List[Any] = []

        if "web_search" in allowed and self.enable_tools.get("web_search", False):
            built.append(WebSearchTool())

        if "file_parser" in allowed and (
            self.enable_tools.get("file_parser", self.enable_tools.get("read_external_file", True))
        ):
            doc_dir = Path("doc")
            doc_dir.mkdir(parents=True, exist_ok=True)
            if has_supported_doc_files(doc_dir):
                built.append(FileParserTool(base_dir=doc_dir))

        if "plantuml_validate" in allowed and self.enable_tools.get("plantuml_validate", True):
            opts = self.config.get("plantuml_validate") or {}
            built.append(
                PlantUMLValidatorTool(
                    jar_path=opts.get("jar_path", "plantuml.jar"),
                    use_online=opts.get("use_online", True),
                    server_url=opts.get("server_url", ""),
                )
            )

        return built
