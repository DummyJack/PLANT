import ollama
import json
import os

from typing import Dict, Optional
from abc import ABC, abstractmethod
from openai import OpenAI

# 支援多種 LLM 的統一介面
# 支援：OpenAI, Anthropic, Gemini, Ollama
class BaseLLM(ABC):
    def __init__(self, model_name: str, **kwargs):
        self.model_name = model_name
        self.default_temperature = kwargs.pop("temperature", None)
        self.kwargs = kwargs

    @abstractmethod
    def generate(
        self, 
        user_prompt: Optional[str] = None, 
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None
    ) -> str:
        # 生成回應
        pass

    @abstractmethod
    def generate_json(
        self, 
        user_prompt: Optional[str] = None, 
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None
    ) -> Dict:
        # 生成 JSON 格式回應
        pass


# OpenAI Model
class OpenAIModel(BaseLLM):
    def __init__(self, model_name: str, **kwargs):
        super().__init__(model_name, **kwargs)

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment")
        self.client = OpenAI(api_key=api_key)

    def generate(
        self, 
        user_prompt: Optional[str] = None, 
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None
    ) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        # 使用傳入的 temperature，若無則使用預設值
        kwargs = self.kwargs.copy()
        if temperature is not None:
            kwargs["temperature"] = temperature
        elif self.default_temperature is not None:
            kwargs["temperature"] = self.default_temperature

        response = self.client.chat.completions.create(
            model=self.model_name, messages=messages, **kwargs
        )
        return response.choices[0].message.content

    def generate_json(
        self, 
        user_prompt: Optional[str] = None, 
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None
    ) -> Dict:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        # 使用傳入的 temperature，若無則使用預設值
        kwargs = self.kwargs.copy()
        if temperature is not None:
            kwargs["temperature"] = temperature
        elif self.default_temperature is not None:
            kwargs["temperature"] = self.default_temperature

        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            response_format={"type": "json_object"},
            **kwargs,
        )
        content = response.choices[0].message.content
        return json.loads(content)


# Ollama Model
class OllamaModel(BaseLLM):
    def __init__(
        self,
        model_name: str,
        base_url: str = "http://localhost:11434",
        **kwargs,
    ):
        super().__init__(model_name, **kwargs)
        self.client = ollama.Client(host=base_url)

    def generate(
        self, 
        user_prompt: Optional[str] = None, 
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None
    ) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        # 準備選項參數
        options = {}
        if temperature is not None:
            options["temperature"] = temperature
        elif self.default_temperature is not None:
            options["temperature"] = self.default_temperature

        response = self.client.chat(
            model=self.model_name, 
            messages=messages,
            options=options if options else None
        )
        return response["message"]["content"]

    def generate_json(
        self, 
        user_prompt: Optional[str] = None, 
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None
    ) -> Dict:
        content = self.generate(user_prompt, system_prompt, temperature)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            import re

            json_match = re.search(
                r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL
            )
            if json_match:
                return json.loads(json_match.group(1))
            raise ValueError(f"無法從回應中解析 JSON: {content}")


# 根據 provider 建立對應的模型實例
def create_model(provider: str, model_name: str, **kwargs) -> BaseLLM:
    providers = {
        "openai": OpenAIModel,
        "ollama": OllamaModel,
    }

    if provider.lower() not in providers:
        raise ValueError(
            f"不支援的 provider: {provider}，支援的有: {list(providers.keys())}"
        )

    return providers[provider.lower()](model_name, **kwargs)
