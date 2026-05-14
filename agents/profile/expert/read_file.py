# Expert file helpers: detect reference docs and parse strict model JSON.
import json
from typing import Dict


class ExpertReadFile:
    pass


class ExpertParsing:
    @staticmethod
    def parse_first_json(raw: str) -> Dict:
        """解析完整合法 JSON 物件。"""
        if not raw or not isinstance(raw, str):
            raise ValueError("Agent output must be a valid JSON object.")
        try:
            parsed = json.loads(raw.strip())
        except json.JSONDecodeError as e:
            raise ValueError(f"Agent output must be a valid JSON object: {e}") from e
        if not isinstance(parsed, dict):
            raise ValueError("Agent output must be a JSON object.")
        return parsed
