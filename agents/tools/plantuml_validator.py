# Defines available agent tools and tool execution behavior.
import logging
import re
import socket
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from storage.plantuml import plantuml_online_enabled, plantuml_server_url
from storage.plantuml_runtime import PlantUMLRuntime, inspect_plantuml_runtime

from .base import BaseTool

logger = logging.getLogger("Plant.PlantUMLValidator")


class PlantUMLValidatorTool(BaseTool):
    name = "plantuml_validate"
    description = (
        "驗證 PlantUML 語法是否正確，回傳驗證結果與錯誤訊息。"
        "必須填 plantuml_code，內容必須包含 @startuml 與 @enduml。"
    )
    parameters = {
        "plantuml_code": {
            "type": "string",
            "description": "必填。要驗證的 PlantUML 程式碼，須含 @startuml 與 @enduml。",
            "required": True,
        }
    }

    def __init__(self, server_url: str = "", allow_online: Optional[bool] = None):
        self.server_url = (server_url or plantuml_server_url()).rstrip("/")
        self.allow_online = plantuml_online_enabled() if allow_online is None else bool(allow_online)

    def execute(self, **kwargs) -> str:
        code = kwargs.get("plantuml_code", "")
        if not code:
            return "錯誤: plantuml_code 不可為空"

        if "@startuml" not in code or "@enduml" not in code:
            return "語法錯誤: 缺少 @startuml 或 @enduml 標記"

        runtime = inspect_plantuml_runtime()
        if runtime.command_path or (runtime.java_path and runtime.jar_path):
            return self.validate_local(code, runtime)
        if not self.allow_online:
            return "驗證跳過: 線上 PlantUML 驗證未啟用；已保留原始 PlantUML 供本機工具處理"
        return self.validate_online(code)

    def validate_local(self, code: str, runtime: PlantUMLRuntime) -> str:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source = Path(tmp_dir) / "diagram.plantuml"
            source.write_text(code, encoding="utf-8")
            if runtime.command_path:
                command = [str(runtime.command_path), "-checkonly", str(source)]
            else:
                command = [
                    str(runtime.java_path),
                    "-jar",
                    str(runtime.jar_path),
                    "-checkonly",
                    str(source),
                ]
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                logger.info("PlantUML 本機驗證不可用: %s", exc)
                if self.allow_online:
                    return self.validate_online(code)
                return f"驗證失敗: PlantUML 本機驗證無法執行。reason={exc}"
            output = (result.stderr or result.stdout or "").strip()
            if result.returncode == 0:
                return "驗證通過: PlantUML 語法正確（透過本機執行環境）"
            return f"語法錯誤: PlantUML 本機驗證失敗。detail={output[:500]}"

    def encode_hex(self, code: str) -> str:
        return "~h" + code.encode("utf-8").hex()

    def validate_online(self, code: str) -> str:
        url = ""
        try:
            encoded = self.encode_hex(code)
            url = f"{self.server_url}/svg/{encoded}"
            req = urllib.request.Request(url, headers={"User-Agent": "Plant-Modeler/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
            if re.search(r"(syntax\s+error|error\s+line|plantuml\s+error)", body, re.IGNORECASE):
                snippet = re.sub(r"\s+", " ", body).strip()[:500]
                return f"語法錯誤: PlantUML server 回傳語法錯誤。detail={snippet}"
            return "驗證通過: PlantUML 語法正確（透過線上伺服器）"
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="ignore")
            except Exception:
                body = ""
            snippet = re.sub(r"\s+", " ", body).strip()[:500]
            reason = getattr(e, "reason", "") or ""
            return (
                "驗證失敗: PlantUML server HTTP 錯誤"
                f"。status={e.code}; reason={reason}; detail={snippet}; url={url}"
            )
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            logger.info("PlantUML 線上驗證不可用: %s", reason)
            return f"驗證失敗: PlantUML server 連線錯誤。reason={reason}; url={url}"
        except socket.timeout:
            return f"驗證失敗: PlantUML server 連線逾時。timeout=15s; url={url}"
        except TimeoutError:
            return f"驗證失敗: PlantUML server 連線逾時。timeout=15s; url={url}"
        except Exception as e:
            logger.warning(f"線上驗證失敗: {e}")
            return (
                "驗證失敗: PlantUML server 未知錯誤"
                f"。error_type={type(e).__name__}; error={e}; url={url}"
            )
