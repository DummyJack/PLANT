import logging
import zlib
import string

from typing import Optional
from .base import BaseTool

logger = logging.getLogger("Plant.PlantUMLValidatorTool")


class PlantUMLValidatorTool(BaseTool):
    """PlantUML 語法驗證工具 — 透過 PlantUML Server API 驗證"""

    name = "plantuml_validate"
    description = "驗證 PlantUML 程式碼語法是否正確，回傳驗證結果或語法錯誤訊息"
    parameters = {
        "code": {
            "type": "string",
            "description": "要驗證的 PlantUML 程式碼（包含 @startuml 和 @enduml）",
            "required": True
        }
    }

    def __init__(self, server_url: str = "http://www.plantuml.com/plantuml"):
        self.server_url = server_url.rstrip("/")

    def execute(self, **kwargs) -> str:
        code = kwargs.get("code", "")
        if not code:
            return "錯誤: PlantUML 程式碼不可為空"

        basic_check = self.basic_syntax_check(code)
        if basic_check:
            return basic_check

        try:
            return self.server_validate(code)
        except Exception as e:
            logger.warning(f"PlantUML Server 驗證失敗，改用本地檢查: {e}")
            return self.local_syntax_check(code)

    def basic_syntax_check(self, code: str) -> Optional[str]:
        lines = code.strip().split("\n")
        if not any(line.strip().startswith("@startuml") for line in lines):
            return "語法錯誤: 缺少 @startuml 開頭標記"
        if not any(line.strip().startswith("@enduml") for line in lines):
            return "語法錯誤: 缺少 @enduml 結尾標記"
        return None

    def server_validate(self, code: str) -> str:
        """透過 /png/ 端點驗證，利用回應 header 判斷語法正確性"""
        import requests

        encoded = self.encode_plantuml(code)
        png_url = f"{self.server_url}/png/{encoded}"

        try:
            response = requests.get(png_url, timeout=15)

            # PlantUML Server 在 header 中提供診斷資訊
            error = response.headers.get("X-Plantuml-Diagram-Error", "")
            error_line = response.headers.get("X-Plantuml-Diagram-Error-Line", "")
            description = response.headers.get("X-Plantuml-Diagram-Description", "")

            if error:
                msg = f"PlantUML 語法錯誤: {error}"
                if error_line:
                    msg += f" (第 {error_line} 行)"
                return msg

            if response.status_code == 400:
                return "PlantUML 語法錯誤（Server 回傳 400）"

            if response.status_code == 200:
                if description:
                    return f"PlantUML 語法驗證通過 — {description}"
                return "PlantUML 語法驗證通過，程式碼有效。"

            return f"PlantUML Server 回傳狀態碼 {response.status_code}"

        except ImportError:
            return self.local_syntax_check(code)
        except requests.exceptions.RequestException as e:
            logger.warning(f"PlantUML Server 連線失敗: {e}")
            return self.local_syntax_check(code)

    def local_syntax_check(self, code: str) -> str:
        issues = []
        lines = code.strip().split("\n")

        open_braces = 0
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            open_braces += stripped.count("{") - stripped.count("}")
            if open_braces < 0:
                issues.append(f"第 {i} 行: 多餘的右大括號 }}")

        if open_braces > 0:
            issues.append(f"缺少 {open_braces} 個右大括號 }}")

        has_content = any(
            line.strip() and not line.strip().startswith("@") and not line.strip().startswith("'")
            for line in lines
        )
        if not has_content:
            issues.append("圖表內容為空")

        if issues:
            return "本地語法檢查發現問題:\n" + "\n".join(f"- {issue}" for issue in issues)
        return "本地語法檢查通過（建議使用 PlantUML Server 進行完整驗證）。"

    @staticmethod
    def encode_plantuml(text: str) -> str:
        compressed = zlib.compress(text.encode("utf-8"))[2:-4]
        return PlantUMLValidatorTool.base64_encode(compressed)

    @staticmethod
    def base64_encode(data: bytes) -> str:
        encode_table = string.digits + string.ascii_uppercase + string.ascii_lowercase + "-_"
        result = []
        for i in range(0, len(data), 3):
            chunk = data[i:i+3]
            if len(chunk) == 3:
                b1, b2, b3 = chunk
                result.append(encode_table[b1 >> 2])
                result.append(encode_table[((b1 & 0x3) << 4) | (b2 >> 4)])
                result.append(encode_table[((b2 & 0xF) << 2) | (b3 >> 6)])
                result.append(encode_table[b3 & 0x3F])
            elif len(chunk) == 2:
                b1, b2 = chunk
                result.append(encode_table[b1 >> 2])
                result.append(encode_table[((b1 & 0x3) << 4) | (b2 >> 4)])
                result.append(encode_table[(b2 & 0xF) << 2])
            elif len(chunk) == 1:
                b1 = chunk[0]
                result.append(encode_table[b1 >> 2])
                result.append(encode_table[(b1 & 0x3) << 4])
        return "".join(result)
