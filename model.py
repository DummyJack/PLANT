import ollama
import json
import os

from typing import Dict, List, Optional, Any, Tuple
from abc import ABC, abstractmethod
from openai import OpenAI
from utils import CostTracker


def _anthropic_split_messages(
    messages: List[Dict],
) -> Tuple[Optional[str], List[Dict[str, str]]]:
    """將 OpenAI 風格 messages 轉成 Anthropic Messages API 格式。"""
    system_parts: List[str] = []
    out: List[Dict[str, str]] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "") or ""
        if role == "system":
            system_parts.append(content)
        elif role == "user":
            out.append({"role": "user", "content": content})
        elif role == "assistant":
            out.append({"role": "assistant", "content": content})
        elif role == "tool":
            out.append({"role": "user", "content": f"[tool result]\n{content}"})
    if not out:
        out = [{"role": "user", "content": "請繼續。"}]
    system = "\n\n".join(system_parts) if system_parts else None
    return system, out


def _gemini_split_messages(
    messages: List[Dict],
) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """將 OpenAI 風格 messages 轉成 Gemini contents 格式。"""
    system_parts: List[str] = []
    contents: List[Dict[str, Any]] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "") or ""
        if role == "system":
            system_parts.append(content)
        elif role == "assistant":
            contents.append({"role": "model", "parts": [content]})
        elif role == "user":
            contents.append({"role": "user", "parts": [content]})
        elif role == "tool":
            contents.append({"role": "user", "parts": [f"[tool result]\n{content}"]})
    if not contents:
        contents = [{"role": "user", "parts": ["Hello"]}]
    system_instruction = "\n\n".join(system_parts) if system_parts else None
    return system_instruction, contents


class BaseLLM(ABC):
    """統一 LLM 介面，支援 OpenAI / Ollama / Anthropic Claude / Google Gemini"""

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
    def chat(self, messages: List[Dict], temperature: Optional[float] = None,
             max_tokens: Optional[int] = None,
             max_output_tokens: Optional[int] = None) -> str: ...

    @abstractmethod
    def chat_json(self, messages: List[Dict], temperature: Optional[float] = None,
                  max_tokens: Optional[int] = None,
                  max_output_tokens: Optional[int] = None) -> Dict: ...

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
             max_tokens: Optional[int] = None,
             max_output_tokens: Optional[int] = None) -> str:
        kwargs = self.build_kwargs(temperature, max_tokens, max_output_tokens)
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
                  max_tokens: Optional[int] = None,
                  max_output_tokens: Optional[int] = None) -> Dict:
        kwargs = self.build_kwargs(temperature, max_tokens, max_output_tokens)

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

    def build_ollama_options(
        self,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
    ) -> Dict:
        options = {}
        if temperature is not None:
            options["temperature"] = temperature
        elif self.default_temperature is not None:
            options["temperature"] = self.default_temperature
        effective_max_tokens = (
            max_output_tokens if max_output_tokens is not None else max_tokens
        )
        if effective_max_tokens is not None:
            options["num_predict"] = effective_max_tokens
        elif self.default_max_tokens is not None:
            options["num_predict"] = self.default_max_tokens
        return options

    def chat(self, messages: List[Dict], temperature: Optional[float] = None,
             max_tokens: Optional[int] = None,
             max_output_tokens: Optional[int] = None) -> str:
        options = self.build_ollama_options(
            temperature, max_tokens, max_output_tokens
        )
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
                  max_tokens: Optional[int] = None,
                  max_output_tokens: Optional[int] = None) -> Dict:
        content = self.chat(messages, temperature, max_tokens, max_output_tokens)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            import re
            json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1))
            raise ValueError(f"無法從回應中解析 JSON: {content}")


class AnthropicModel(BaseLLM):
    """Anthropic Claude（Messages API）。需安裝 anthropic 套件與 ANTHROPIC_API_KEY。"""

    def __init__(self, model_name: str, **kwargs):
        super().__init__(model_name, **kwargs)
        try:
            import anthropic
        except ImportError as e:
            raise ImportError(
                "使用 Claude 請先安裝：pip install anthropic"
            ) from e
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in environment")
        self.client = anthropic.Anthropic(api_key=api_key)

    def _effective_max_tokens(
        self,
        temperature: Optional[float],
        max_tokens: Optional[int],
        max_output_tokens: Optional[int],
    ) -> int:
        kw = self.build_kwargs(temperature, max_tokens, max_output_tokens)
        mt = kw.get("max_tokens")
        if mt is None:
            mt = 4096
        return max(1, int(mt))

    def chat(
        self,
        messages: List[Dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
    ) -> str:
        system, msgs = _anthropic_split_messages(messages)
        max_out = self._effective_max_tokens(
            temperature, max_tokens, max_output_tokens
        )
        kw = self.build_kwargs(temperature, max_tokens, max_output_tokens)
        temp = kw.get("temperature")

        self.costTracker.start()
        try:
            create_kw: Dict[str, Any] = {
                "model": self.model_name,
                "messages": msgs,
                "max_tokens": max_out,
            }
            if system:
                create_kw["system"] = system
            if temp is not None:
                create_kw["temperature"] = temp
            response = self.client.messages.create(**create_kw)
            usage = getattr(response, "usage", None)
            if usage:
                self.addUsage(
                    {
                        "prompt_tokens": getattr(usage, "input_tokens", 0),
                        "completion_tokens": getattr(usage, "output_tokens", 0),
                        "total_tokens": getattr(usage, "input_tokens", 0)
                        + getattr(usage, "output_tokens", 0),
                    }
                )
            parts: List[str] = []
            for b in response.content or []:
                t = getattr(b, "text", None)
                if t:
                    parts.append(t)
            return "".join(parts)
        finally:
            self.costTracker.stop()

    def chat_json(
        self,
        messages: List[Dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
    ) -> Dict:
        messages = list(messages)
        has_json_mention = any(
            "json" in (msg.get("content") or "").lower() for msg in messages
        )
        if not has_json_mention:
            messages.append({"role": "user", "content": "請只輸出合法 JSON，不要其他文字。"})
        text = self.chat(messages, temperature, max_tokens, max_output_tokens)
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            import re

            json_match = re.search(
                r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL
            )
            if json_match:
                return json.loads(json_match.group(1))
            raise ValueError(f"無法從回應中解析 JSON: {text}")


class GeminiModel(BaseLLM):
    """Google Gemini（google-generativeai）。需安裝套件與 GOOGLE_API_KEY。"""

    def __init__(self, model_name: str, **kwargs):
        super().__init__(model_name, **kwargs)
        try:
            import google.generativeai as genai
        except ImportError as e:
            raise ImportError(
                "使用 Gemini 請先安裝：pip install google-generativeai"
            ) from e
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found in environment")
        self._genai = genai
        genai.configure(api_key=api_key)

    def _gemini_response_text(self, response: Any) -> str:
        """取得 Gemini 文字；部分情況下 .text 會拋錯（例如安全阻擋）。"""
        try:
            t = getattr(response, "text", None)
            if t:
                return t
        except Exception:
            pass
        if getattr(response, "candidates", None):
            parts: List[str] = []
            for c in response.candidates:
                for p in getattr(c.content, "parts", []) or []:
                    if getattr(p, "text", None):
                        parts.append(p.text)
            return "".join(parts)
        return ""

    def _make_generation_config(
        self,
        temperature: Optional[float],
        max_tokens: Optional[int],
        max_output_tokens: Optional[int] = None,
        response_mime_type: Optional[str] = None,
    ):
        kw = self.build_kwargs(temperature, max_tokens, max_output_tokens)
        gkw: Dict[str, Any] = {}
        if kw.get("temperature") is not None:
            gkw["temperature"] = kw["temperature"]
        mt = kw.get("max_tokens")
        if mt is not None:
            gkw["max_output_tokens"] = int(mt)
        if response_mime_type:
            gkw["response_mime_type"] = response_mime_type
        if not gkw:
            return None
        return self._genai.GenerationConfig(**gkw)

    def chat(
        self,
        messages: List[Dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
    ) -> str:
        system_instruction, contents = _gemini_split_messages(messages)
        gen_config = self._make_generation_config(
            temperature, max_tokens, max_output_tokens, response_mime_type=None
        )
        model = self._genai.GenerativeModel(
            self.model_name,
            system_instruction=system_instruction,
        )
        self.costTracker.start()
        try:
            response = model.generate_content(
                contents,
                generation_config=gen_config,
            )
            um = getattr(response, "usage_metadata", None)
            if um:
                prompt = getattr(um, "prompt_token_count", 0) or 0
                cand = getattr(um, "candidates_token_count", 0) or 0
                total = getattr(um, "total_token_count", None)
                if total is None:
                    total = prompt + cand
                self.addUsage(
                    {
                        "prompt_tokens": prompt,
                        "completion_tokens": cand,
                        "total_tokens": total,
                    }
                )
            text = self._gemini_response_text(response)
            if text:
                return text
            raise ValueError("Gemini 無回應內容（可能被安全過濾或無候選）")
        finally:
            self.costTracker.stop()

    def chat_json(
        self,
        messages: List[Dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
    ) -> Dict:
        messages = list(messages)
        has_json_mention = any(
            "json" in (msg.get("content") or "").lower() for msg in messages
        )
        if not has_json_mention:
            messages.append({"role": "user", "content": "請只輸出合法 JSON。"})
        system_instruction, contents = _gemini_split_messages(messages)
        gen_config = self._make_generation_config(
            temperature,
            max_tokens,
            max_output_tokens,
            response_mime_type="application/json",
        )
        model = self._genai.GenerativeModel(
            self.model_name,
            system_instruction=system_instruction,
        )
        self.costTracker.start()
        try:
            response = model.generate_content(
                contents,
                generation_config=gen_config,
            )
            um = getattr(response, "usage_metadata", None)
            if um:
                prompt = getattr(um, "prompt_token_count", 0) or 0
                cand = getattr(um, "candidates_token_count", 0) or 0
                total = getattr(um, "total_token_count", None)
                if total is None:
                    total = prompt + cand
                self.addUsage(
                    {
                        "prompt_tokens": prompt,
                        "completion_tokens": cand,
                        "total_tokens": total,
                    }
                )
            text = self._gemini_response_text(response).strip()
            return json.loads(text)
        except json.JSONDecodeError:
            import re

            json_match = re.search(
                r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL
            )
            if json_match:
                return json.loads(json_match.group(1))
            raise ValueError(f"無法從回應中解析 JSON: {text}")
        finally:
            self.costTracker.stop()


def create_model(provider: str, model_name: str, **kwargs) -> BaseLLM:
    _aliases = {
        "claude": "anthropic",
        "google": "gemini",
    }
    key = _aliases.get(provider.lower(), provider.lower())
    providers = {
        "openai": OpenAIModel,
        "ollama": OllamaModel,
        "anthropic": AnthropicModel,
        "gemini": GeminiModel,
    }
    if key not in providers:
        raise ValueError(
            f"不支援的 provider: {provider}，支援: {list(providers.keys())} 及別名 claude, google"
        )
    return providers[key](model_name, **kwargs)
