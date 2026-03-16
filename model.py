import ollama
import json
import os

from typing import Dict, List, Optional, Any
from abc import ABC, abstractmethod
from openai import OpenAI
from utils import CostTracker


class BaseLLM(ABC):
    """統一 LLM 介面，支援 OpenAI / Ollama"""

    def __init__(self, model_name: str, **kwargs):
        self.model_name = model_name
        self.default_temperature = kwargs.pop("temperature", None)
        self.default_max_tokens = kwargs.pop("max_tokens", None)
        self.kwargs = kwargs
        self.costTracker = CostTracker(model_name=model_name)

    def build_kwargs(self, temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> Dict:
        kwargs = self.kwargs.copy()
        if temperature is not None:
            kwargs["temperature"] = temperature
        elif self.default_temperature is not None:
            kwargs["temperature"] = self.default_temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        elif self.default_max_tokens is not None:
            kwargs["max_tokens"] = self.default_max_tokens
        return kwargs

    @abstractmethod
    def chat(self, messages: List[Dict], temperature: Optional[float] = None,
             max_tokens: Optional[int] = None) -> str: ...

    @abstractmethod
    def chat_json(self, messages: List[Dict], temperature: Optional[float] = None,
                  max_tokens: Optional[int] = None) -> Dict: ...

    def addUsage(self, usage: Optional[Dict[str, Any]]):
        self.costTracker.addUsage(usage)

    def getCostSummary(self) -> Optional[Dict[str, Any]]:
        return self.costTracker.summary()

    def resetCostSummary(self):
        self.costTracker.reset()


class OpenAIModel(BaseLLM):
    def __init__(self, model_name: str, **kwargs):
        super().__init__(model_name, **kwargs)
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment")
        self.client = OpenAI(api_key=api_key)

    def chat(self, messages: List[Dict], temperature: Optional[float] = None,
             max_tokens: Optional[int] = None) -> str:
        kwargs = self.build_kwargs(temperature, max_tokens)
        self.costTracker.start()
        try:
            response = self.client.chat.completions.create(
                model=self.model_name, messages=messages, **kwargs
            )
            usage = getattr(response, "usage", None)
            if usage:
                self.addUsage(
                    {
                        "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                        "completion_tokens": getattr(usage, "completion_tokens", 0),
                        "total_tokens": getattr(usage, "total_tokens", 0),
                    }
                )
            return response.choices[0].message.content
        finally:
            self.costTracker.stop()

    def chat_json(self, messages: List[Dict], temperature: Optional[float] = None,
                  max_tokens: Optional[int] = None) -> Dict:
        kwargs = self.build_kwargs(temperature, max_tokens)

        # OpenAI response_format: json_object 要求 messages 中須包含 "json" 字樣
        has_json_mention = any("json" in msg.get("content", "").lower() for msg in messages)
        if not has_json_mention:
            messages = list(messages)
            messages.append({"role": "user", "content": "請以 JSON 格式回應。"})

        self.costTracker.start()
        try:
            response = self.client.chat.completions.create(
                model=self.model_name, messages=messages,
                response_format={"type": "json_object"}, **kwargs,
            )
            usage = getattr(response, "usage", None)
            if usage:
                self.addUsage(
                    {
                        "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                        "completion_tokens": getattr(usage, "completion_tokens", 0),
                        "total_tokens": getattr(usage, "total_tokens", 0),
                    }
                )
            return json.loads(response.choices[0].message.content)
        finally:
            self.costTracker.stop()


class OllamaModel(BaseLLM):
    def __init__(self, model_name: str, base_url: str = "http://localhost:11434", **kwargs):
        super().__init__(model_name, **kwargs)
        self.client = ollama.Client(host=base_url)

    def build_ollama_options(self, temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> Dict:
        options = {}
        if temperature is not None:
            options["temperature"] = temperature
        elif self.default_temperature is not None:
            options["temperature"] = self.default_temperature
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        elif self.default_max_tokens is not None:
            options["num_predict"] = self.default_max_tokens
        return options

    def chat(self, messages: List[Dict], temperature: Optional[float] = None,
             max_tokens: Optional[int] = None) -> str:
        options = self.build_ollama_options(temperature, max_tokens)
        self.costTracker.start()
        try:
            response = self.client.chat(
                model=self.model_name, messages=messages,
                options=options if options else None
            )
            self.addUsage(
                {
                    "input_tokens": response.get("prompt_eval_count", 0),
                    "output_tokens": response.get("eval_count", 0),
                }
            )
            return response["message"]["content"]
        finally:
            self.costTracker.stop()

    def chat_json(self, messages: List[Dict], temperature: Optional[float] = None,
                  max_tokens: Optional[int] = None) -> Dict:
        content = self.chat(messages, temperature, max_tokens)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            import re
            json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1))
            raise ValueError(f"無法從回應中解析 JSON: {content}")


def create_model(provider: str, model_name: str, **kwargs) -> BaseLLM:
    providers = {"openai": OpenAIModel, "ollama": OllamaModel}
    if provider.lower() not in providers:
        raise ValueError(f"不支援的 provider: {provider}，支援: {list(providers.keys())}")
    return providers[provider.lower()](model_name, **kwargs)
