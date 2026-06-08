# Defines available agent tools and tool execution behavior.
from abc import ABC, abstractmethod
from typing import Any, Dict


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
