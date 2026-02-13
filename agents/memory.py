import json
import logging

from typing import Dict, List, Any

logger = logging.getLogger("Plant.Memory")

# Agent 記憶系統(短期（當前任務對話）+ 長期（跨輪次摘要）)
class Memory:
    def __init__(self, model=None):
        self.messages: List[Dict[str, str]] = []
        self.history: List[Dict[str, Any]] = []
        self.model = model

    def add(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})

    def get_context_prompt(self) -> str:
        if not self.history:
            return ""
        lines = ["# 先前輪次的記憶摘要"]
        for entry in self.history:
            lines.append(f"\n[Round {entry.get('round', '?')}]\n{entry.get('summary', '')}")
        return "\n".join(lines)

    def summarize_round(self, round_num: int):
        if not self.messages:
            return

        if not self.model:
            self.history.append({"round": round_num, "summary": self.simple_summary()})
            self.clear_short_term()
            return

        messages_text = self.format_messages()
        prompt = f"""請將以下對話記錄摘要為簡潔的重點（保留關鍵決策、衝突、結論）：

{messages_text}

請用繁體中文輸出摘要，保持精簡但不遺漏重要資訊。"""

        try:
            summary = self.model.generate(prompt)
            self.history.append({"round": round_num, "summary": summary})
            logger.info(f"已摘要 Round {round_num}（{len(self.messages)} 則訊息）")
        except Exception as e:
            logger.warning(f"記憶摘要失敗: {e}")
            self.history.append({"round": round_num, "summary": self.simple_summary()})

        self.clear_short_term()

    def clear_short_term(self):
        self.messages = []

    def format_messages(self) -> str:
        lines = []
        for msg in self.messages:
            content = msg["content"]
            lines.append(f"[{msg['role'].upper()}] {content}")
        return "\n".join(lines)

    def simple_summary(self) -> str:
        parts = []
        for msg in self.messages:
            if msg["role"] == "assistant":
                content = msg["content"]
                parts.append(content)
        return " | ".join(parts) if parts else "（無有效記錄）"
