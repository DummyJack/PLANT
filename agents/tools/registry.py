# Defines available agent tools and tool execution behavior.
from pathlib import Path
from typing import Any, Dict, List, Optional


# Defines ToolRegistry class for this module workflow.
class ToolRegistry:

    # Defines __init__ function for this module workflow.
    def __init__(self, config: Dict[str, Any], policy, artifact_path: Optional[str] = None):
        self.config = config
        self.policy = policy
        self.enable_tools = config.get("enable_tools") or {}
        self.artifact_path = artifact_path

    # Defines build tools for agent function for this module workflow.
    def build_tools_for_agent(self, agent_name: str) -> List[Any]:
        from .artifact_query import ArtifactQueryTool
        from .plantuml_validator import PlantUMLValidatorTool
        from .read_file import ReadFileTool, has_supported_files
        from .web_search import WebSearchTool

        allowed = set(self.policy.allowed_tools_for_agent(agent_name))
        built: List[Any] = []

        if "web_search" in allowed and self.enable_tools.get("web_search", False):
            built.append(WebSearchTool(stop_config=None))

        if "read_file" in allowed and self.enable_tools.get("read_file", True):
            doc_dir = Path("doc")
            doc_dir.mkdir(parents=True, exist_ok=True)
            if has_supported_files(doc_dir):
                built.append(ReadFileTool(base_dir=doc_dir))

        if "plantuml_validate" in allowed and self.enable_tools.get("plantuml_validate", True):
            built.append(PlantUMLValidatorTool(server_url=""))

        if "artifact_query" in allowed and self.enable_tools.get("artifact_query", True):
            if self.artifact_path:
                built.append(ArtifactQueryTool(artifact_path=self.artifact_path))

        return built
