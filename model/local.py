# Local OpenAI-compatible model adapter.
import json
import os

from typing import Any, Dict, List, Optional

from .base import BaseLLM

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional dependency at import-time
    OpenAI = None


def _parse_json_payload(raw: str) -> Dict[str, Any]:
    if not raw or not isinstance(raw, str):
        return {}
    text = raw.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        return data

    candidates = []
    if "```" in text:
        for part in text.split("```"):
            value = part.strip()
            if value.lower().startswith("json"):
                value = value[4:].strip()
            if value.startswith("{") and value.endswith("}"):
                candidates.append(value)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raise ValueError("Local model output must be a valid JSON object.")


class LocalModel(BaseLLM):
    """OpenAI-compatible local LLM, e.g. Ollama, LM Studio, or vLLM."""

    def __init__(self, model_name: str, **kwargs):
        base_url = kwargs.pop("base_url", None) or os.getenv("LOCAL_MODEL_BASE_URL")
        api_key = kwargs.pop("api_key", None) or os.getenv("LOCAL_MODEL_API_KEY") or "local"
        self.json_response_format = bool(kwargs.pop("json_response_format", True))
        super().__init__(model_name, **kwargs)
        if OpenAI is None:
            raise ImportError("openai package is required for LocalModel")
        if not base_url:
            base_url = "http://localhost:11434/v1"
        self.base_url = base_url
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def _record_usage(self, response: Any, action: Optional[str], run_time_s: Optional[float]) -> None:
        usage = getattr(response, "usage", None) if response is not None else None
        if not usage:
            return
        self.addUsage(
            {
                "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                "completion_tokens": getattr(usage, "completion_tokens", 0),
                "total_tokens": getattr(usage, "total_tokens", 0),
            },
            action=action,
            run_time_s=run_time_s,
        )

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
        self._record_usage(response, action, run_s)
        return response.choices[0].message.content or ""

    def chat_json(
        self,
        messages: List[Dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
        action: Optional[str] = None,
    ) -> Dict:
        kwargs = self.build_kwargs(temperature, max_tokens, max_output_tokens)
        request_kwargs = dict(kwargs)
        if self.json_response_format:
            request_kwargs["response_format"] = {"type": "json_object"}

        self.costTracker.start()
        response = None
        try:
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    **request_kwargs,
                )
            except Exception:
                if not self.json_response_format:
                    raise
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    **kwargs,
                )
        finally:
            run_s = self.costTracker.end_segment()
        self._record_usage(response, action, run_s)
        return _parse_json_payload(response.choices[0].message.content or "")
