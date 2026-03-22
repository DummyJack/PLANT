# BaselineModel — 基準衝突辨識（OpenAI 或 Google Gemini）

import os
import sys
import threading
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from openai import OpenAI

# 載入環境變數（專案主目錄 .env）
BASE_DIR = Path(__file__).parent.parent
load_dotenv(dotenv_path=BASE_DIR / ".env")


def _gemini_response_text(response: Any) -> str:
    try:
        t = getattr(response, "text", None)
        if t:
            return t
    except Exception:
        pass
    if getattr(response, "candidates", None):
        parts: list[str] = []
        for c in response.candidates:
            for p in getattr(c.content, "parts", []) or []:
                if getattr(p, "text", None):
                    parts.append(p.text)
        return "".join(parts)
    return ""


class BaselineModel:
    def __init__(
        self,
        provider: str = "openai",
        model_name: Optional[str] = None,
        temperature: float = 0,
    ):
        p = (provider or "openai").lower()
        if p in ("google", "gemini"):
            p = "gemini"
        self.provider = p
        self.temperature = temperature

        if p == "openai":
            if model_name is None:
                model_name = "gpt-4o-mini"
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                print("錯誤：未找到 OPENAI_API_KEY 環境變數")
                sys.exit(1)
            self.model_name = model_name
            self.client = OpenAI(api_key=api_key)
            self._genai_client = None
            self._genai_types = None
            self._gemini_lock = None
        elif p == "gemini":
            if model_name is None:
                model_name = "gemini-3-flash-preview"
            api_key = os.getenv("GOOGLE_API_KEY")
            if not api_key:
                print("錯誤：未找到 GOOGLE_API_KEY 環境變數")
                sys.exit(1)
            try:
                from google import genai
                from google.genai import types as genai_types
            except ImportError as e:
                print("錯誤：使用 Gemini 請先安裝 google-genai")
                raise SystemExit(1) from e
            self.model_name = model_name
            self._genai_client = genai.Client(api_key=api_key)
            self._genai_types = genai_types
            self.client = None
            self._gemini_lock = threading.Lock()
        else:
            print(f"錯誤：不支援的 provider: {provider}（請用 openai 或 gemini）")
            sys.exit(1)

    def detect_conflict(self, text1: str, text2: str) -> str:
        user_prompt = (
            f"Text 1: {text1}\n\nText 2: {text2}\n\n"
            "判斷以上兩句是否有衝突，有衝突請回應 Conflict，沒有請回應 Neutral，不要生成其他內容。"
        )
        if self.provider == "openai":
            assert self.client is not None
            resp = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=self.temperature,
            )
            raw = (resp.choices[0].message.content or "").strip()
            return raw

        assert self._genai_client is not None and self._genai_types is not None
        cfg = self._genai_types.GenerateContentConfig(temperature=self.temperature)
        with self._gemini_lock:
            response = self._genai_client.models.generate_content(
                model=self.model_name,
                contents=user_prompt,
                config=cfg,
            )
        raw = _gemini_response_text(response).strip()
        if not raw:
            raise ValueError("Gemini 無回應內容（可能被安全過濾或無候選）")
        return raw
