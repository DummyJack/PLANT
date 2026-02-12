# BaselineModel — 基礎 OpenAI 基準模型

import os
import sys
import json
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# 載入環境變數
BASE_DIR = Path(__file__).parent.parent
load_dotenv(dotenv_path=BASE_DIR / "config" / ".env")


class BaselineModel:
    def __init__(self, model_name: str = "gpt-4o-mini", temperature: float = 0):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            print("錯誤：未找到 OPENAI_API_KEY 環境變數")
            sys.exit(1)
        self.client = OpenAI(api_key=api_key)
        self.model_name = model_name
        self.temperature = temperature

    # 需求衝突偵測，回傳 "Conflict" 或 "Neutral"
    def detect_conflict(self, text1: str, text2: str) -> str:
        user_prompt = f"Text 1: {text1}\n\nText 2: {text2}\n\n判斷以上兩句是否有衝突，有衝突請回應 Conflict，沒有請回應 Neutral，不要生成其他內容。"
        resp = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=self.temperature,
        )
        raw = resp.choices[0].message.content.strip()
        return raw

    # PlantUML 類別圖生成，回傳 dict 包含 plantuml 和 ast
    def generate_plantuml(self, human_lang: str) -> dict:
        user_prompt = (
            f"請根據描述：{human_lang}，生成 PlantUML 類別圖和對應的 AST。\n\n"
            '請以 JSON 格式輸出:\n'
            '{"PlantUML": "...", "Output_AST": {"type": "root", "children": [...]}}'
        )
        resp = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=self.temperature,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
        return json.loads(content)
