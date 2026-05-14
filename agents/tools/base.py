# Tool base interface.
from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseTool(ABC):
    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """執行工具並回傳文字結果。"""
        pass

    def validate_args(self, **kwargs) -> bool:
        """檢查 required 參數是否齊全。"""
        for param_name, param_info in self.parameters.items():
            if param_info.get("required", False) and param_name not in kwargs:
                return False
        return True
