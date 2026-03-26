from pathlib import Path

from abc import ABC, abstractmethod
from typing import Any, Dict, List


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

    def __init__(self, config: Dict[str, Any], policy):
        self.config = config
        self.policy = policy
        self.enable_tools = config.get("enable_tools") or {}

    def build_tools_for_agent(self, agent_name: str) -> List[Any]:
        from agents.profile.expert import has_supported_doc_files
        from .web_search import WebSearchTool
        from .plantuml_validator import PlantUMLValidatorTool
        from .file_parser import FileParserTool

        allowed = set(self.policy.allowed_tools_for_agent(agent_name))
        built: List[Any] = []

        if "web_search" in allowed and self.enable_tools.get("web_search", False):
            ws_stop = self.config.get("web_search_stop")
            built.append(
                WebSearchTool(stop_config=ws_stop if isinstance(ws_stop, dict) else None)
            )

        if "file_parser" in allowed and (
            self.enable_tools.get("file_parser", self.enable_tools.get("read_external_file", True))
        ):
            doc_dir = Path("doc")
            doc_dir.mkdir(parents=True, exist_ok=True)
            if has_supported_doc_files(doc_dir):
                fp_cfg = self.config.get("file_parser_rag") or {}
                built.append(
                    FileParserTool(
                        base_dir=doc_dir,
                        chunk_max_chars=int(fp_cfg.get("chunk_max_chars", 1200)),
                        chunk_overlap=int(fp_cfg.get("chunk_overlap", 150)),
                        read_chunks_max_chars=int(
                            fp_cfg.get("read_chunks_max_chars", 48000)
                        ),
                    )
                )

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
