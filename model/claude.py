# Handles claude logic for model provider integration and shared LLM client behavior.
import json

from typing import Dict, List, Optional, Tuple

from .base import AUTH_ERROR_MESSAGE, BaseLLM, normalize_authentication_error


def claude_split_messages(
    messages: List[Dict],
) -> Tuple[Optional[str], List[Dict[str, str]]]:
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


# ========
# Defines ClaudeModel class for this module workflow.
# ========
class ClaudeModel(BaseLLM):

    # ========
    # Defines __init__ function for this module workflow.
    # ========
    def __init__(self, model_name: str, **kwargs):
        super().__init__(model_name, **kwargs)
        try:
            import anthropic
        except ImportError as e:
            raise ImportError(
                "使用 Claude 請先安裝：pip install anthropic"
            ) from e
        import os

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(AUTH_ERROR_MESSAGE)
        self.client = anthropic.Anthropic(api_key=api_key)

    # ========
    # Defines effective max tokens function for this module workflow.
    # ========
    def effective_max_tokens(
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
        system, msgs = claude_split_messages(messages)
        max_out = self.effective_max_tokens(
            temperature,
            max_tokens,
            max_output_tokens,
        )
        kw = self.build_kwargs(temperature, max_tokens, max_output_tokens)
        temp = kw.get("temperature")

        self.costTracker.start()
        response = None
        try:
            create_kw = {
                "model": self.model_name,
                "messages": msgs,
                "max_tokens": max_out,
            }
            if system:
                create_kw["system"] = system
            if temp is not None:
                create_kw["temperature"] = temp
            response = self.client.messages.create(**create_kw)
        except Exception as exc:
            raise normalize_authentication_error(exc) from exc
        finally:
            run_s = self.costTracker.end_segment()
        usage = getattr(response, "usage", None) if response is not None else None
        if usage:
            self.add_usage(
                {
                    "prompt_tokens": getattr(usage, "input_tokens", 0),
                    "completion_tokens": getattr(usage, "output_tokens", 0),
                    "total_tokens": getattr(usage, "input_tokens", 0)
                    + getattr(usage, "output_tokens", 0),
                },
                action=action,
                run_time_s=run_s,
            )
        parts: List[str] = []
        for b in response.content or []:
            t = getattr(b, "text", None)
            if t:
                parts.append(t)
        return "".join(parts)

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
    ) -> Dict:
        text = self.chat(
            messages,
            temperature,
            max_tokens,
            max_output_tokens,
            action=action,
        )
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            import re

            json_match = re.search(
                r"```(?:json)?\s*(\{.*?\})\s*```",
                text,
                re.DOTALL,
            )
            if json_match:
                return json.loads(json_match.group(1))
            raise ValueError(f"無法從回應中解析 JSON: {text}")
