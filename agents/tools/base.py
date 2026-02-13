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
            **kwargs: 工具參數（由 Agent 在 ReAct 迴圈中提供）

        Returns:
            工具執行結果的文字描述
        """
        pass

    def to_prompt_description(self) -> str:
        """將工具資訊格式化為 prompt 描述

        Returns:
            供 Agent prompt 使用的工具說明文字
        """
        params_desc = ""
        if self.parameters:
            params_list = []
            for param_name, param_info in self.parameters.items():
                param_type = param_info.get("type", "string")
                param_desc = param_info.get("description", "")
                required = "必填" if param_info.get("required", False) else "選填"
                params_list.append(f"    - {param_name} ({param_type}, {required}): {param_desc}")
            params_desc = "\n" + "\n".join(params_list)

        return f"- {self.name}: {self.description}{params_desc}"

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
