# Handles base logic for model provider integration and shared LLM client behavior.
import inspect
import json
import os
import re

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from utils import CostTracker


PROVIDER_API_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "local": None,
}

AUTH_ERROR_MESSAGE = "API Key 無效或已失效，請到設定中重新輸入。"


def parse_json_object(text: str) -> Dict[str, Any]:
    source = str(text or "").strip()
    if not source:
        raise ValueError("empty JSON response")

    decoder = json.JSONDecoder()
    try:
        obj, idx = decoder.raw_decode(source)
        trailing = source[idx:].strip()
        if not trailing or all(ch in "}]`" for ch in trailing):
            if isinstance(obj, dict):
                return obj
            raise ValueError("JSON response is not an object")
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*(.*?)\s*```", source, re.DOTALL)
    if match:
        return parse_json_object(match.group(1))

    start = source.find("{")
    if start < 0:
        raise ValueError("JSON object start not found")
    depth = 0
    in_string = False
    escape = False
    for pos in range(start, len(source)):
        ch = source[pos]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                obj = json.loads(source[start : pos + 1])
                if isinstance(obj, dict):
                    return obj
                raise ValueError("JSON response is not an object")
    raise ValueError("JSON object end not found")


def is_authentication_error(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status in {401, 403}:
        return True
    text = " ".join(
        str(part)
        for part in (
            exc.__class__.__name__,
            getattr(exc, "code", ""),
            getattr(exc, "type", ""),
            getattr(exc, "message", ""),
            str(exc),
        )
        if part
    ).lower()
    return bool(
        re.search(
            r"unauthorized|authentication|invalid(?:_|\\s|-)*api(?:_|\\s|-)*key|"
            r"invalid(?:_|\\s|-)*x(?:_|\\s|-)*api(?:_|\\s|-)*key|"
            r"permission denied|api key not valid|api_key|not found in environment|"
            r"incorrect api key|invalid token|expired",
            text,
        )
    )


def normalize_authentication_error(exc: BaseException) -> BaseException:
    if is_authentication_error(exc):
        return ValueError(AUTH_ERROR_MESSAGE)
    return exc


# ========
# Defines providers from agent models function for this module workflow.
# ========
def providers_from_agent_models(config: Dict[str, Any]) -> set:
    agent_models = config.get("agent_models") or {}
    providers = set()
    for agent_cfg in agent_models.values():
        if isinstance(agent_cfg, dict) and agent_cfg.get("provider"):
            providers.add(str(agent_cfg["provider"]).strip().lower())
    return providers


# ========
# Defines validate provider api keys function for this module workflow.
# ========
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
            raise ValueError(AUTH_ERROR_MESSAGE)


# ========
# Defines BaseLLM class for this module workflow.
# ========
class BaseLLM(ABC):

    # ========
    # Defines __init__ function for this module workflow.
    # ========
    def __init__(self, model_name: str, **kwargs):
        self.model_name = model_name
        self.default_temperature = kwargs.pop("temperature", None)
        self.default_max_tokens = kwargs.pop(
            "max_output_tokens",
            kwargs.pop("max_tokens", None),
        )
        self.kwargs = kwargs
        self.costTracker = CostTracker(model_name=model_name)

    # ========
    # Defines build kwargs function for this module workflow.
    # ========
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

    # ========
    # Defines chat function for this module workflow.
    # ========
    @abstractmethod
    def chat(
        self,
        messages: List[Dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
        action: Optional[str] = None,
    ) -> str: ...

    # ========
    # Defines chat json function for this module workflow.
    # ========
    @abstractmethod
    def chat_json(
        self,
        messages: List[Dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
        action: Optional[str] = None,
    ) -> Dict: ...

    # ========
    # Defines infer usage action function for this module workflow.
    # ========
    def infer_usage_action(self) -> str:
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

    # ========
    # Defines add usage function for this module workflow.
    # ========
    def add_usage(
        self,
        usage: Optional[Dict[str, Any]],
        action: Optional[str] = None,
        run_time_s: Optional[float] = None,
    ):
        usage_action = action or self.infer_usage_action()
        self.costTracker.add_usage(
            usage,
            metadata={"action": usage_action},
            run_time_s=run_time_s,
        )

    # ========
    # Defines get cost summary function for this module workflow.
    # ========
    def get_cost_summary(self) -> Optional[Dict[str, Any]]:
        return self.costTracker.summary()

    # ========
    # Defines get usage call records function for this module workflow.
    # ========
    def get_usage_call_records(self) -> List[Dict[str, Any]]:
        return self.costTracker.get_call_records()


# ========
# Defines create model function for this module workflow.
# ========
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
