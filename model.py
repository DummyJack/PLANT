import os
from typing import Dict, List, Any, Optional
from abc import ABC, abstractmethod
import json

# 支援多種 LLM 的統一介面
# 支援：OpenAI, Anthropic, Gemini, Ollama
class BaseLLM(ABC):
    # LLM 基礎類別
    
    def __init__(self, model_name: str, **kwargs):
        self.model_name = model_name
        self.kwargs = kwargs
    
    @abstractmethod
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        # 生成回應
        pass
    
    @abstractmethod
    def generate_json(self, prompt: str, system_prompt: Optional[str] = None) -> Dict:
        # 生成 JSON 格式回應
        pass


class OpenAIModel(BaseLLM):
    # OpenAI 模型實作
    
    def __init__(self, model_name: str = "gpt-4", **kwargs):
        super().__init__(model_name, **kwargs)
        try:
            from openai import OpenAI
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY not found in environment")
            self.client = OpenAI(api_key=api_key)
        except ImportError:
            raise ImportError("請安裝 openai: pip install openai")
    
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            **self.kwargs
        )
        return response.choices[0].message.content
    
    def generate_json(self, prompt: str, system_prompt: Optional[str] = None) -> Dict:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            response_format={"type": "json_object"},
            **self.kwargs
        )
        content = response.choices[0].message.content
        return json.loads(content)


class AnthropicModel(BaseLLM):
    # Anthropic Claude 模型實作
    
    def __init__(self, model_name: str = "claude-3-5-sonnet-20241022", **kwargs):
        super().__init__(model_name, **kwargs)
        try:
            from anthropic import Anthropic
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not found in environment")
            self.client = Anthropic(api_key=api_key)
        except ImportError:
            raise ImportError("請安裝 anthropic: pip install anthropic")
    
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        kwargs = {"max_tokens": 4096, **self.kwargs}
        
        response = self.client.messages.create(
            model=self.model_name,
            system=system_prompt if system_prompt else "",
            messages=[{"role": "user", "content": prompt}],
            **kwargs
        )
        return response.content[0].text
    
    def generate_json(self, prompt: str, system_prompt: Optional[str] = None) -> Dict:
        content = self.generate(prompt, system_prompt)
        # 嘗試提取 JSON
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # 嘗試從 markdown code block 中提取
            import re
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1))
            raise ValueError(f"無法從回應中解析 JSON: {content}")


class GeminiModel(BaseLLM):
    # Google Gemini 模型實作
    
    def __init__(self, model_name: str = "gemini-pro", **kwargs):
        super().__init__(model_name, **kwargs)
        try:
            import google.generativeai as genai
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise ValueError("GEMINI_API_KEY not found in environment")
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(model_name)
        except ImportError:
            raise ImportError("請安裝 google-generativeai: pip install google-generativeai")
    
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        response = self.model.generate_content(full_prompt)
        return response.text
    
    def generate_json(self, prompt: str, system_prompt: Optional[str] = None) -> Dict:
        content = self.generate(prompt, system_prompt)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            import re
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1))
            raise ValueError(f"無法從回應中解析 JSON: {content}")


class OllamaModel(BaseLLM):
    # Ollama 本地模型實作
    
    def __init__(self, model_name: str = "llama2", base_url: str = "http://localhost:11434", **kwargs):
        super().__init__(model_name, **kwargs)
        try:
            import ollama
            self.client = ollama.Client(host=base_url)
        except ImportError:
            raise ImportError("請安裝 ollama: pip install ollama")
    
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        response = self.client.chat(
            model=self.model_name,
            messages=messages
        )
        return response['message']['content']
    
    def generate_json(self, prompt: str, system_prompt: Optional[str] = None) -> Dict:
        content = self.generate(prompt, system_prompt)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            import re
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1))
            raise ValueError(f"無法從回應中解析 JSON: {content}")


# 根據 provider 建立對應的模型實例
def create_model(provider: str, model_name: str, **kwargs) -> BaseLLM:
    providers = {
        "openai": OpenAIModel,
        "anthropic": AnthropicModel,
        "gemini": GeminiModel,
        "ollama": OllamaModel
    }
    
    if provider.lower() not in providers:
        raise ValueError(f"不支援的 provider: {provider}，支援的有: {list(providers.keys())}")
    
    return providers[provider.lower()](model_name, **kwargs)
