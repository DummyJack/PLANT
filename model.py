import json
import logging
import os
import inspect

from typing import Any, Callable, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from abc import ABC, abstractmethod
from openai import OpenAI
from utils import CostTracker


def anthropic_split_messages(
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


def gemini_split_messages(
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
    """統一 LLM 介面，支援 OpenAI / Anthropic Claude / Google Gemini"""

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
             max_output_tokens: Optional[int] = None,
             action: Optional[str] = None) -> str: ...

    @abstractmethod
    def chat_json(self, messages: List[Dict], temperature: Optional[float] = None,
                  max_tokens: Optional[int] = None,
                  max_output_tokens: Optional[int] = None,
                  action: Optional[str] = None) -> Dict: ...

    def _infer_usage_action(self) -> str:
        """嘗試從呼叫堆疊推斷這次 API 呼叫在做什麼。"""
        stack = inspect.stack(context=0)
        try:
            for frame_info in stack[2:]:
                filename = frame_info.filename.replace("\\", "/")
                if filename.endswith("/model.py") or filename.endswith("/utils.py"):
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
        usage_action = action or self._infer_usage_action()
        self.costTracker.addUsage(
            usage,
            metadata={"action": usage_action},
            run_time_s=run_time_s,
        )

    def getCostSummary(self) -> Optional[Dict[str, Any]]:
        return self.costTracker.summary()

    def getUsageCallRecords(self) -> List[Dict[str, Any]]:
        return self.costTracker.get_call_records()

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
             max_output_tokens: Optional[int] = None,
             action: Optional[str] = None) -> str:
        kwargs = self.build_kwargs(temperature, max_tokens, max_output_tokens)
        self.costTracker.start()
        response = None
        try:
            response = self.client.chat.completions.create(
                model=self.model_name, messages=messages, **kwargs
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

    def chat_json(self, messages: List[Dict], temperature: Optional[float] = None,
                  max_tokens: Optional[int] = None,
                  max_output_tokens: Optional[int] = None,
                  action: Optional[str] = None) -> Dict:
        kwargs = self.build_kwargs(temperature, max_tokens, max_output_tokens)

        # OpenAI response_format: json_object 要求 messages 中須包含 "json" 字樣
        has_json_mention = any("json" in msg.get("content", "").lower() for msg in messages)
        if not has_json_mention:
            messages = list(messages)
            messages.append({"role": "user", "content": "請以 JSON 格式回應。"})

        self.costTracker.start()
        response = None
        try:
            response = self.client.chat.completions.create(
                model=self.model_name, messages=messages,
                response_format={"type": "json_object"}, **kwargs,
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

    def chat(
        self,
        messages: List[Dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
        action: Optional[str] = None,
    ) -> str:
        system, msgs = anthropic_split_messages(messages)
        max_out = self.effective_max_tokens(
            temperature, max_tokens, max_output_tokens
        )
        kw = self.build_kwargs(temperature, max_tokens, max_output_tokens)
        temp = kw.get("temperature")

        self.costTracker.start()
        response = None
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
        finally:
            run_s = self.costTracker.end_segment()
        usage = getattr(response, "usage", None) if response is not None else None
        if usage:
            self.addUsage(
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

    def chat_json(
        self,
        messages: List[Dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
        action: Optional[str] = None,
    ) -> Dict:
        messages = list(messages)
        has_json_mention = any(
            "json" in (msg.get("content") or "").lower() for msg in messages
        )
        if not has_json_mention:
            messages.append({"role": "user", "content": "請只輸出合法 JSON，不要其他文字。"})
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
                r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL
            )
            if json_match:
                return json.loads(json_match.group(1))
            raise ValueError(f"無法從回應中解析 JSON: {text}")


class GeminiModel(BaseLLM):
    """Google Gemini（google-genai / google.genai）。需安裝套件與 GOOGLE_API_KEY。"""

    def __init__(self, model_name: str, **kwargs):
        super().__init__(model_name, **kwargs)
        try:
            from google import genai
        except ImportError as e:
            raise ImportError(
                "使用 Gemini 請先安裝：pip install google-genai"
            ) from e
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found in environment")
        self._client = genai.Client(api_key=api_key)

    def gemini_response_text(self, response: Any) -> str:
        """取得 Gemini 文字；部分情況下 .text 會拋錯（例如安全阻擋）。"""
        try:
            t = getattr(response, "text", None)
            if t:
                return t
        except Exception:
            pass
        cands = getattr(response, "candidates", None)
        if cands:
            parts: List[str] = []
            for c in cands:
                content = getattr(c, "content", None)
                for p in getattr(content, "parts", []) or []:
                    if getattr(p, "text", None):
                        parts.append(p.text)
            return "".join(parts)
        return ""

    def contents_dicts_to_genai(
        self, contents: List[Dict[str, Any]]
    ) -> List[Any]:
        from google.genai import types

        out: List[Any] = []
        for item in contents:
            role = item.get("role", "user")
            parts: List[Any] = []
            for p in item.get("parts", []):
                text = p if isinstance(p, str) else str(p)
                parts.append(types.Part.from_text(text=text))
            out.append(types.Content(role=role, parts=parts))
        return out

    def make_generate_config(
        self,
        system_instruction: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
        max_output_tokens: Optional[int] = None,
        response_mime_type: Optional[str] = None,
    ) -> Optional[Any]:
        from google.genai import types

        kw = self.build_kwargs(temperature, max_tokens, max_output_tokens)
        cfg_kw: Dict[str, Any] = {}
        if system_instruction:
            cfg_kw["system_instruction"] = system_instruction
        if kw.get("temperature") is not None:
            cfg_kw["temperature"] = kw["temperature"]
        mt = kw.get("max_tokens")
        if mt is not None:
            cfg_kw["max_output_tokens"] = int(mt)
        if response_mime_type:
            cfg_kw["response_mime_type"] = response_mime_type
        if not cfg_kw:
            return None
        return types.GenerateContentConfig(**cfg_kw)

    def generate(
        self,
        system_instruction: Optional[str],
        contents: List[Dict[str, Any]],
        temperature: Optional[float],
        max_tokens: Optional[int],
        max_output_tokens: Optional[int],
        response_mime_type: Optional[str],
    ) -> Any:
        gen_cfg = self.make_generate_config(
            system_instruction,
            temperature,
            max_tokens,
            max_output_tokens,
            response_mime_type,
        )
        gen_contents = self.contents_dicts_to_genai(contents)
        call_kw: Dict[str, Any] = {
            "model": self.model_name,
            "contents": gen_contents,
        }
        if gen_cfg is not None:
            call_kw["config"] = gen_cfg
        return self._client.models.generate_content(**call_kw)

    def add_usage_from_response(
        self,
        response: Any,
        action: Optional[str] = None,
        run_time_s: Optional[float] = None,
    ) -> None:
        um = getattr(response, "usage_metadata", None)
        if not um:
            return
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
            },
            action=action,
            run_time_s=run_time_s,
        )

    def openai_tool_schemas_to_gemini_tools(
        self, openai_style_schemas: List[Dict[str, Any]]
    ) -> List[Any]:
        """將 BaseAgent.get_tool_schemas() 的 OpenAI function 格式轉成 google.genai Tool。"""
        from google.genai import types

        decls: List[Any] = []
        for item in openai_style_schemas:
            fn = item.get("function") or {}
            name = fn.get("name") or ""
            if not name:
                continue
            params = fn.get("parameters") or {
                "type": "object",
                "properties": {},
            }
            decls.append(
                types.FunctionDeclaration(
                    name=name,
                    description=fn.get("description") or "",
                    parameters_json_schema=params,
                )
            )
        if not decls:
            return []
        return [types.Tool(function_declarations=decls)]

    def make_generate_config_with_tools(
        self,
        system_instruction: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
        max_output_tokens: Optional[int],
        gemini_tools: List[Any],
    ) -> Any:
        from google.genai import types

        kw = self.build_kwargs(temperature, max_tokens, max_output_tokens)
        cfg_kw: Dict[str, Any] = {
            "tools": gemini_tools,
            "automatic_function_calling": types.AutomaticFunctionCallingConfig(
                disable=True
            ),
            "tool_config": types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode=types.FunctionCallingConfigMode.AUTO
                )
            ),
        }
        if system_instruction:
            cfg_kw["system_instruction"] = system_instruction
        if kw.get("temperature") is not None:
            cfg_kw["temperature"] = kw["temperature"]
        mt = kw.get("max_tokens")
        if mt is not None:
            cfg_kw["max_output_tokens"] = int(mt)
        return types.GenerateContentConfig(**cfg_kw)

    def model_content_function_calls(
        self, response: Any
    ) -> Tuple[Optional[Any], List[Any], str]:
        """從 generate_content 回傳解析 model 的 Content、其中的 FunctionCall 列表、純文字。"""
        cands = getattr(response, "candidates", None) or []
        if not cands:
            return None, [], self.gemini_response_text(response)
        c0 = cands[0]
        content = getattr(c0, "content", None)
        if not content:
            return None, [], self.gemini_response_text(response)
        texts: List[str] = []
        calls: List[Any] = []
        for p in getattr(content, "parts", []) or []:
            fc = getattr(p, "function_call", None)
            if fc is not None:
                calls.append(fc)
            elif getattr(p, "text", None):
                texts.append(p.text)
        return content, calls, "".join(texts)

    def gemini_chat_with_tools(
        self,
        messages: List[Dict],
        *,
        openai_style_tool_schemas: List[Dict[str, Any]],
        execute_tool_fn: Callable[[str, Dict[str, Any]], str],
        max_rounds: int = 3,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
        action: Optional[str] = None,
    ) -> str:
        """
        Gemini 手動 function calling 迴圈（與 OpenAI chat.completions tools 對齊）。
        openai_style_tool_schemas：與 get_tool_schemas() 相同格式。
        """
        from google.genai import types

        log = logging.getLogger("Plant.GeminiModel")
        gemini_tools = self.openai_tool_schemas_to_gemini_tools(
            openai_style_tool_schemas
        )
        if not gemini_tools:
            return self.chat(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                max_output_tokens=max_output_tokens,
                action=action,
            )

        system_instruction, contents_dicts = gemini_split_messages(messages)
        contents_genai = self.contents_dicts_to_genai(contents_dicts)

        for _ in range(max_rounds):
            cfg = self.make_generate_config_with_tools(
                system_instruction,
                temperature,
                max_tokens,
                max_output_tokens,
                gemini_tools,
            )
            self.costTracker.start()
            try:
                response = self._client.models.generate_content(
                    model=self.model_name,
                    contents=contents_genai,
                    config=cfg,
                )
            finally:
                run_s = self.costTracker.end_segment()
            self.add_usage_from_response(response, action=action, run_time_s=run_s)

            model_content, fn_calls, text_out = self.model_content_function_calls(
                response
            )
            if not fn_calls:
                if (text_out or "").strip():
                    return text_out
                return text_out or ""

            if model_content is not None:
                contents_genai.append(model_content)

            if len(fn_calls) == 1:
                fc = fn_calls[0]
                fname = getattr(fc, "name", None) or ""
                fargs = dict(getattr(fc, "args", None) or {})
                log.info(f"🔧 {fname}({fargs})")
                result = execute_tool_fn(fname, fargs)
                resp_kw: Dict[str, Any] = {
                    "name": fname,
                    "response": {"result": result},
                }
                fid = getattr(fc, "id", None)
                if fid:
                    resp_kw["id"] = fid
                contents_genai.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part(
                                function_response=types.FunctionResponse(
                                    **resp_kw
                                )
                            )
                        ],
                    )
                )
            else:

                def run_one(
                    idx: int, fc_obj: Any
                ) -> Tuple[int, str, Optional[str], str]:
                    fn = getattr(fc_obj, "name", None) or ""
                    ag = dict(getattr(fc_obj, "args", None) or {})
                    log.info(f"🔧 {fn}({ag})")
                    try:
                        out = execute_tool_fn(fn, ag)
                    except Exception as e:
                        out = f"工具執行失敗: {e}"
                    return idx, fn, getattr(fc_obj, "id", None), out

                max_workers = min(len(fn_calls), 6)
                by_index: Dict[int, str] = {}
                with ThreadPoolExecutor(max_workers=max_workers) as ex:
                    futs = [
                        ex.submit(run_one, i, fc)
                        for i, fc in enumerate(fn_calls)
                    ]
                    for fut in as_completed(futs):
                        try:
                            i, _fn, _fid, out = fut.result()
                            by_index[i] = out
                        except Exception as e:
                            log.warning("並行工具 future 例外: %s", e)
                resp_parts: List[Any] = []
                for i, fc_obj in enumerate(fn_calls):
                    fn = getattr(fc_obj, "name", None) or ""
                    fid = getattr(fc_obj, "id", None)
                    res_text = by_index.get(
                        i, f"工具執行失敗: 無法對應結果（索引 {i}）"
                    )
                    rkw: Dict[str, Any] = {
                        "name": fn,
                        "response": {"result": res_text},
                    }
                    if fid:
                        rkw["id"] = fid
                    resp_parts.append(
                        types.Part(
                            function_response=types.FunctionResponse(**rkw)
                        )
                    )
                contents_genai.append(
                    types.Content(role="user", parts=resp_parts)
                )

        final_cfg = self.make_generate_config(
            system_instruction,
            temperature,
            max_tokens,
            max_output_tokens,
            response_mime_type=None,
        )
        self.costTracker.start()
        try:
            final_resp = self._client.models.generate_content(
                model=self.model_name,
                contents=contents_genai,
                config=final_cfg,
            )
        finally:
            run_s = self.costTracker.end_segment()
        self.add_usage_from_response(final_resp, action=action, run_time_s=run_s)
        return self.gemini_response_text(final_resp) or ""

    def chat(
        self,
        messages: List[Dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
        action: Optional[str] = None,
    ) -> str:
        system_instruction, contents = gemini_split_messages(messages)
        self.costTracker.start()
        response = None
        try:
            response = self.generate(
                system_instruction,
                contents,
                temperature,
                max_tokens,
                max_output_tokens,
                response_mime_type=None,
            )
        finally:
            run_s = self.costTracker.end_segment()
        self.add_usage_from_response(response, action=action, run_time_s=run_s)
        text = self.gemini_response_text(response)
        if text:
            return text
        raise ValueError("Gemini 無回應內容（可能被安全過濾或無候選）")

    def chat_json(
        self,
        messages: List[Dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
        action: Optional[str] = None,
    ) -> Dict:
        messages = list(messages)
        has_json_mention = any(
            "json" in (msg.get("content") or "").lower() for msg in messages
        )
        if not has_json_mention:
            messages.append({"role": "user", "content": "請只輸出合法 JSON。"})
        system_instruction, contents = gemini_split_messages(messages)
        self.costTracker.start()
        text = ""
        response = None
        try:
            response = self.generate(
                system_instruction,
                contents,
                temperature,
                max_tokens,
                max_output_tokens,
                response_mime_type="application/json",
            )
        finally:
            run_s = self.costTracker.end_segment()
        self.add_usage_from_response(response, action=action, run_time_s=run_s)
        text = self.gemini_response_text(response).strip()
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


def create_model(provider: str, model_name: str, **kwargs) -> BaseLLM:
    _aliases = {
        "claude": "anthropic",
    }
    key = _aliases.get(provider.lower(), provider.lower())
    providers = {
        "openai": OpenAIModel,
        "anthropic": AnthropicModel,
        "gemini": GeminiModel,
    }
    if key not in providers:
        raise ValueError(
            f"不支援的 provider: {provider}，支援: {list(providers.keys())} 及別名 claude"
        )
    return providers[key](model_name, **kwargs)
