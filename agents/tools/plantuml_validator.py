import logging
import re
import urllib.error
import urllib.request

from typing import Any
from .base import BaseTool

logger = logging.getLogger("Plant.PlantUMLValidator")


DEFAULT_ONLINE_SERVER = "https://www.plantuml.com/plantuml"


class PlantUMLValidatorTool(BaseTool):
    name = "plantuml_validate"
    description = "驗證 PlantUML 語法是否正確，回傳驗證結果與錯誤訊息"
    parameters = {
        "plantuml_code": {
            "type": "string",
            "description": "要驗證的 PlantUML 程式碼（須含 @startuml 與 @enduml）",
            "required": True,
        }
    }

    def __init__(self, use_online: bool = True, server_url: str = ""):
        self.use_online = use_online
        self.server_url = (server_url or DEFAULT_ONLINE_SERVER).rstrip("/")

    def execute(self, **kwargs) -> str:
        code = kwargs.get("plantuml_code", "")
        if not code:
            return "錯誤: plantuml_code 不可為空"

        if "@startuml" not in code or "@enduml" not in code:
            return "語法錯誤: 缺少 @startuml 或 @enduml 標記"

        if self.use_online is True:
            return self.validate_online(code)
        return self.fallback_validate(code)

    def encode_hex(self, code: str) -> str:
        """PlantUML 官方支援的 HEX 編碼：~h + UTF-8 的十六進位"""
        return "~h" + code.encode("utf-8").hex()

    def validate_online(self, code: str) -> str:
        """用官方線上伺服器驗證：請求 PNG，語法錯誤時伺服器會回傳錯誤圖（通常較小）"""
        try:
            encoded = self.encode_hex(code)
            url = f"{self.server_url}/png/{encoded}"
            req = urllib.request.Request(url, headers={"User-Agent": "Plant-Modeler/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read()
            # 語法錯誤時 PlantUML 仍回 200，但內容是「錯誤說明圖」，體積通常較小
            if len(body) < 2000:
                return "語法錯誤: 伺服器回傳錯誤圖（圖表可能無效或語法有誤）"
            return "驗證通過: PlantUML 語法正確（透過線上伺服器）"
        except urllib.error.HTTPError as e:
            return f"語法錯誤或伺服器錯誤: HTTP {e.code}"
        except urllib.error.URLError as e:
            return f"無法連線至 PlantUML 伺服器: {e.reason}"
        except Exception as e:
            logger.warning(f"線上驗證失敗: {e}")
            return self.fallback_validate(code)

    def fallback_validate(self, code: str) -> str:
        """線上驗證不可用時的基本語法檢查"""
        issues = []
        starts = code.count("@startuml")
        ends = code.count("@enduml")
        if starts != ends:
            issues.append(f"@startuml ({starts}) 與 @enduml ({ends}) 數量不匹配")

        open_braces = code.count("{")
        close_braces = code.count("}")
        if open_braces != close_braces:
            issues.append(f"大括號不匹配: {{ 有 {open_braces} 個, }} 有 {close_braces} 個")

        arrow_pattern = re.compile(r"(--|->|<--|<->|\.\.>|<\.\.|--\|>|\.\.)")
        lines = code.splitlines()
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("@") or stripped.startswith("'"):
                continue
            if stripped.startswith(("class ", "actor ", "usecase ", "participant ",
                                    "note ", "package ", "rectangle ", "}", "end ",
                                    "title ", "header ", "footer ", "legend ",
                                    "skinparam", "hide ", "show ", "scale ",
                                    "left to right", "top to bottom")):
                continue
            if arrow_pattern.search(stripped):
                continue
            if ":" in stripped:
                continue

        if issues:
            return "基本檢查發現問題（無法進行完整線上語法驗證）:\n" + "\n".join(f"- {i}" for i in issues)

        return "基本檢查通過（無法進行完整線上語法驗證）"
