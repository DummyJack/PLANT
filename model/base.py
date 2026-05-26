# LLM base layer: provider factory, usage tracking, and API key validation.
import inspect
import os

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from utils import CostTracker


PROVIDER_API_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "local": None,
}


def providers_from_agent_models(config: Dict[str, Any]) -> set:
    agent_models = config.get("agent_models") or {}
    providers = set()
    for agent_cfg in agent_models.values():
        if isinstance(agent_cfg, dict) and agent_cfg.get("provider"):
            providers.add(str(agent_cfg["provider"]).strip().lower())
    return providers


def validate_provider_api_keys(config: Dict[str, Any]) -> None:
    providers_to_check = providers_from_agent_models(config)
    if not providers_to_check:
        raise ValueError(
            "agent_models 內未設定任何 provider（請在 default 或各 agent 區塊填寫 provider）"
        )

    for used_provider in providers_to_check:
        required_key = PROVIDER_API_KEY_ENV.get(used_provider)
        if used_provider not in PROVIDER_API_KEY_ENV:
            raise ValueError(f"不支援的 provider: {used_provider}")
        if not required_key:
            continue
        if not os.getenv(required_key):
            raise ValueError(
                f"找不到 {required_key} 環境變數（provider={used_provider}）\n"
                f"請在專案主目錄的 .env 檔案中設定 {required_key}=your_api_key"
            )


class BaseLLM(ABC):
    """統一 LLM 介面，支援 OpenAI / Claude / Google Gemini"""

    def __init__(self, model_name: str, **kwargs):
        self.model_name = model_name
        self.default_temperature = kwargs.pop("temperature", None)
        self.default_max_tokens = kwargs.pop(
            "max_output_tokens",
            kwargs.pop("max_tokens", None),
        )
        self.kwargs = kwargs
        self.costTracker = CostTracker(model_name=model_name)

    def build_kwargs(
        self,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
    ) -> Dict:
        kwargs = self.kwargs.copy()
        if temperature is not None:
            kwargs["temperature"] = temperature
        elif self.default_temperature is not None:
            kwargs["temperature"] = self.default_temperature
        effective_max_tokens = (
            max_output_tokens if max_output_tokens is not None else max_tokens
        )
        if effective_max_tokens is not None:
            kwargs["max_tokens"] = effective_max_tokens
        elif self.default_max_tokens is not None:
            kwargs["max_tokens"] = self.default_max_tokens
        return kwargs

    @abstractmethod
    def chat(
        self,
        messages: List[Dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
        action: Optional[str] = None,
    ) -> str: ...

    @abstractmethod
    def chat_json(
        self,
        messages: List[Dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
        action: Optional[str] = None,
    ) -> Dict: ...

    def infer_usage_action(self) -> str:
        """嘗試從呼叫堆疊推斷這次 API 呼叫在做什麼。"""
        stack = inspect.stack(context=0)
        try:
            for frame_info in stack[2:]:
                filename = frame_info.filename.replace("\\", "/")
                if (
                    "/model/" in filename
                    or "/utils/" in filename
                ):
                    continue
                caller_self = frame_info.frame.f_locals.get("self")
                class_name = (
                    caller_self.__class__.__name__
                    if caller_self is not None
                    else None
                )
                module_name = os.path.splitext(os.path.basename(filename))[0]
                func_name = frame_info.function
                if class_name:
                    return f"{module_name}.{class_name}.{func_name}"
                return f"{module_name}.{func_name}"
        finally:
            del stack
        return "unknown"

    def addUsage(
        self,
        usage: Optional[Dict[str, Any]],
        action: Optional[str] = None,
        run_time_s: Optional[float] = None,
    ):
        usage_action = action or self.infer_usage_action()
        self.costTracker.addUsage(
            usage,
            metadata={"action": usage_action},
            run_time_s=run_time_s,
        )

    def getCostSummary(self) -> Optional[Dict[str, Any]]:
        return self.costTracker.summary()

    def getUsageCallRecords(self) -> List[Dict[str, Any]]:
        return self.costTracker.get_call_records()


def create_model(provider: str, model_name: str, **kwargs) -> BaseLLM:
    from .claude import ClaudeModel
    from .gemini import GeminiModel
    from .local import LocalModel
    from .openai import OpenAIModel

    key = provider.lower()
    providers = {
        "openai": OpenAIModel,
        "claude": ClaudeModel,
        "gemini": GeminiModel,
        "local": LocalModel,
    }
    if key not in providers:
        raise ValueError(
            f"不支援的 provider: {provider}，支援: {list(providers.keys())}"
        )
    return providers[key](model_name, **kwargs)
