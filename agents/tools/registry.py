# Defines available agent tools and tool execution behavior.
from pathlib import Path
from typing import Any, Dict, List, Optional


class ToolRegistry:

    def __init__(
        self,
        config: Dict[str, Any],
        policy,
        artifact_path: Optional[str] = None,
        doc_dir: Optional[str] = None,
    ):
        self.config = config
        self.policy = policy
        self.enable_tools = config.get("enable_tools") or {}
        self.artifact_path = artifact_path
        self.doc_dir = Path(doc_dir) if doc_dir else Path("doc")

    def build_tools_for_agent(self, agent_name: str) -> List[Any]:
        from .artifact_query import ArtifactQueryTool
        from .plantuml_validator import PlantUMLValidatorTool
        from storage.plantuml import plantuml_online_enabled, plantuml_server_url
        from .read_file import ReadFileTool
        from .web_search import WebSearchTool

        allowed = set(self.policy.allowed_tools_for_agent(agent_name))
        built: List[Any] = []

        if "web_search" in allowed and self.enable_tools.get("web_search", False):
            built.append(WebSearchTool(stop_config=None))

        if "read_file" in allowed and self.enable_tools.get("read_file", True):
            doc_dir = self.doc_dir
            doc_dir.mkdir(parents=True, exist_ok=True)
            # Files may be uploaded while the flow is already waiting for human
            # input. Keep the tool available; it refreshes its index at execution.
            built.append(ReadFileTool(base_dir=doc_dir))

        if "plantuml_validate" in allowed and self.enable_tools.get("plantuml_validate", True):
            built.append(
                PlantUMLValidatorTool(
                    server_url=plantuml_server_url(),
                    allow_online=plantuml_online_enabled(self.config),
                )
            )

        if "artifact_query" in allowed and self.enable_tools.get("artifact_query", True):
            if self.artifact_path:
                built.append(ArtifactQueryTool(artifact_path=self.artifact_path))

        return built
