import json

from abc import ABC, abstractmethod
from typing import Dict, Any

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
