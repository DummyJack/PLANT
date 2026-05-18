# Expert file helpers: detect reference docs and parse strict model JSON.
import json
from typing import Dict


class ExpertReadFile:
    pass


class ExpertParsing:
    @staticmethod
    def parse_first_json(raw: str) -> Dict:
        """解析模型輸出中的第一個 JSON object。"""
        if not raw or not isinstance(raw, str):
            raise ValueError("Agent output must be a valid JSON object.")
        text = raw.strip()
        candidates = [text]
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

        last_error = None
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError as e:
                last_error = e
                continue
            if isinstance(parsed, dict):
                return parsed
        if last_error is not None:
            raise ValueError(f"Agent output must be a valid JSON object: {last_error}") from last_error
        raise ValueError("Agent output must be a JSON object.")
