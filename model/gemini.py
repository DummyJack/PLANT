# Gemini model adapter for chat, JSON responses, and tool calls.
import json
import logging
import os

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Tuple

from .base import BaseLLM


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


class GeminiModel(BaseLLM):
    """Google Gemini（google-genai / google.genai）。需安裝套件與 GEMINI_API_KEY。"""

    def __init__(self, model_name: str, **kwargs):
        super().__init__(model_name, **kwargs)
        try:
            from google import genai
        except ImportError as e:
            raise ImportError(
                "使用 Gemini 請先安裝：pip install google-genai"
            ) from e
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment")
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
        self,
        contents: List[Dict[str, Any]],
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
        self,
        openai_style_schemas: List[Dict[str, Any]],
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
        self,
        response: Any,
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
                    idx: int,
                    fc_obj: Any,
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
                        i,
                        f"工具執行失敗: 無法對應結果（索引 {i}）",
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
                r"```(?:json)?\s*(\{.*?\})\s*```",
                text,
                re.DOTALL,
            )
            if json_match:
                return json.loads(json_match.group(1))
            raise ValueError(f"無法從回應中解析 JSON: {text}")
