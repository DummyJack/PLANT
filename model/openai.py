# Handles openai logic for model provider integration and shared LLM client behavior.
import os

from typing import Dict, List, Optional

from .base import (
    AUTH_ERROR_MESSAGE,
    BaseLLM,
    normalize_authentication_error,
    parse_json_object,
)

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional dependency at import-time
    OpenAI = None


# ========
# Defines OpenAIModel class for this module workflow.
# ========
class OpenAIModel(BaseLLM):
    # ========
    # Defines __init__ function for this module workflow.
    # ========
    def __init__(self, model_name: str, **kwargs):
        super().__init__(model_name, **kwargs)
        if OpenAI is None:
            raise ImportError("openai package is required for OpenAIModel")
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(AUTH_ERROR_MESSAGE)
        self.client = OpenAI(api_key=api_key)

    # ========
    # Defines chat function for this module workflow.
    # ========
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
        except Exception as exc:
            raise normalize_authentication_error(exc) from exc
        finally:
            run_s = self.costTracker.end_segment()
        usage = getattr(response, "usage", None) if response is not None else None
        if usage:
            self.add_usage(
                {
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(usage, "completion_tokens", 0),
                    "total_tokens": getattr(usage, "total_tokens", 0),
                },
                action=action,
                run_time_s=run_s,
            )
        return response.choices[0].message.content

    # ========
    # Defines chat json function for this module workflow.
    # ========
    def chat_json(
        self,
        messages: List[Dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
        action: Optional[str] = None,
        schema: Optional[Dict] = None,
    ) -> Dict:
        kwargs = self.build_kwargs(temperature, max_tokens, max_output_tokens)
        response_format = {"type": "json_object"}
        if schema is not None:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "agent_output",
                    "strict": True,
                    "schema": self.strict_json_schema(schema),
                },
            }

        self.costTracker.start()
        response = None
        try:
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    response_format=response_format,
                    **kwargs,
                )
            except Exception as exc:
                if schema is None or not self.structured_output_unsupported(exc):
                    raise
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    response_format={"type": "json_object"},
                    **kwargs,
                )
        except Exception as exc:
            raise normalize_authentication_error(exc) from exc
        finally:
            run_s = self.costTracker.end_segment()
        usage = getattr(response, "usage", None) if response is not None else None
        if usage:
            self.add_usage(
                {
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(usage, "completion_tokens", 0),
                    "total_tokens": getattr(usage, "total_tokens", 0),
                },
                action=action,
                run_time_s=run_s,
            )
        return parse_json_object(response.choices[0].message.content)
