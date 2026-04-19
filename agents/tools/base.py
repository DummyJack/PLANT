from pathlib import Path

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


# Agent 工具的抽象基礎類別
class BaseTool(ABC):
    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """執行工具

        Args:
            **kwargs: 工具參數（由 Agent 提供）

        Returns:
            工具執行結果的文字描述
        """
        pass

    def validate_args(self, **kwargs) -> bool:
        """驗證工具參數

        Args:
            **kwargs: 要驗證的參數

        Returns:
            參數是否有效
        """
        for param_name, param_info in self.parameters.items():
            if param_info.get("required", False) and param_name not in kwargs:
                return False
        return True


class ToolRegistry:
    """宣告式工具註冊與配置入口。"""

    def __init__(self, config: Dict[str, Any], policy, artifact_path: Optional[str] = None):
        self.config = config
        self.policy = policy
        self.enable_tools = config.get("enable_tools") or {}
        self.artifact_path = artifact_path

    def build_tools_for_agent(self, agent_name: str) -> List[Any]:
        from agents.profile.expert import has_supported_doc_files
        from .web_search import WebSearchTool
        from .plantuml_validator import PlantUMLValidatorTool
        from .file_parser import FileParserTool
        from .artifact_query import ArtifactQueryTool

        allowed = set(self.policy.allowed_tools_for_agent(agent_name))
        built: List[Any] = []

        if "web_search" in allowed and self.enable_tools.get("web_search", False):
            from utils import MAX_WEB_SEARCH_RESULTS
            built.append(
                WebSearchTool(
                    stop_config=None,
                    max_results_cap=MAX_WEB_SEARCH_RESULTS,
                )
            )

        if "file_parser" in allowed and (
            self.enable_tools.get("file_parser", True)
        ):
            doc_dir = Path("doc")
            doc_dir.mkdir(parents=True, exist_ok=True)
            if has_supported_doc_files(doc_dir):
                built.append(
                    FileParserTool(
                        base_dir=doc_dir,
                        chunk_max_chars=1200,
                        chunk_overlap=150,
                        read_chunks_max_chars=48000,
                        read_full_max_chars=16000,
                    )
                )

        if "plantuml_validate" in allowed and self.enable_tools.get("plantuml_validate", True):
            built.append(
                PlantUMLValidatorTool(
                    use_online=True,
                    server_url="",
                )
            )

        if "artifact_query" in allowed and self.enable_tools.get("artifact_query", True):
            if self.artifact_path:
                built.append(ArtifactQueryTool(artifact_path=self.artifact_path))

        return built
