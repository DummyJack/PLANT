# OpenAI model adapter for chat and JSON responses.
import json
import os

from typing import Dict, List, Optional

from .base import BaseLLM

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional dependency at import-time
    OpenAI = None


class OpenAIModel(BaseLLM):
    def __init__(self, model_name: str, **kwargs):
        super().__init__(model_name, **kwargs)
        if OpenAI is None:
            raise ImportError("openai package is required for OpenAIModel")
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment")
        self.client = OpenAI(api_key=api_key)

    def chat(
        self,
        messages: List[Dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
        action: Optional[str] = None,
    ) -> str:
        kwargs = self.build_kwargs(temperature, max_tokens, max_output_tokens)
        self.costTracker.start()
        response = None
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                **kwargs,
            )
        finally:
            run_s = self.costTracker.end_segment()
        usage = getattr(response, "usage", None) if response is not None else None
        if usage:
            self.addUsage(
                {
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(usage, "completion_tokens", 0),
                    "total_tokens": getattr(usage, "total_tokens", 0),
                },
                action=action,
                run_time_s=run_s,
            )
        return response.choices[0].message.content

    def chat_json(
        self,
        messages: List[Dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
        action: Optional[str] = None,
    ) -> Dict:
        kwargs = self.build_kwargs(temperature, max_tokens, max_output_tokens)

        self.costTracker.start()
        response = None
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                response_format={"type": "json_object"},
                **kwargs,
            )
        finally:
            run_s = self.costTracker.end_segment()
        usage = getattr(response, "usage", None) if response is not None else None
        if usage:
            self.addUsage(
                {
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(usage, "completion_tokens", 0),
                    "total_tokens": getattr(usage, "total_tokens", 0),
                },
                action=action,
                run_time_s=run_s,
            )
        return json.loads(response.choices[0].message.content)
