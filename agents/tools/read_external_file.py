"""
讀取外部檔案工具：供 Expert 等 agent 在討論或注入領域時讀取 doc 目錄下的檔案。
支援 .txt, .md, .json, .pdf, .docx。
"""
import logging
from pathlib import Path
from typing import Optional

from .base import BaseTool

logger = logging.getLogger("Plant.ReadExternalFileTool")


class ReadExternalFileTool(BaseTool):
    name = "read_external_file"
    description = "讀取專案 doc 目錄下的外部參考檔案（支援 .txt, .md, .json, .pdf, .docx），用於法規、標準或技術文件參考。"
    parameters = {
        "file_path": {
            "type": "string",
            "description": "相對於 doc 目錄的檔案路徑，例如 'regulation.pdf' 或 'refs/guide.md'",
            "required": True,
        }
    }

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir else Path("doc")

    def execute(self, **kwargs) -> str:
        file_path = kwargs.get("file_path")
        if not file_path or not isinstance(file_path, str):
            return "錯誤：請提供 file_path 參數。"

        try:
            path = (self.base_dir / file_path.strip()).resolve()
            base_resolved = self.base_dir.resolve()
            path.relative_to(base_resolved)
        except ValueError:
            return "錯誤：不允許讀取 doc 目錄以外的檔案。"
        except Exception as e:
            return f"錯誤：路徑無效：{e}"
        if not path.is_file():
            return f"錯誤：檔案不存在或非檔案：{path}"

        suffix = path.suffix.lower()
        try:
            if suffix in (".txt", ".md", ".json"):
                return path.read_text(encoding="utf-8", errors="replace")
            if suffix == ".pdf":
                import PyPDF2
                with open(path, "rb") as f:
                    reader = PyPDF2.PdfReader(f)
                    return "\n".join(page.extract_text() or "" for page in reader.pages)
            if suffix in (".docx", ".doc"):
                from docx import Document
                doc = Document(path)
                return "\n".join(p.text for p in doc.paragraphs)
        except ImportError as e:
            return f"錯誤：缺少依賴（{e}），無法讀取 {suffix} 檔案。"
        except Exception as e:
            logger.warning("read_external_file 讀取失敗 %s: %s", path, e)
            return f"錯誤：無法讀取檔案：{e}"

        return f"錯誤：不支援的副檔名 {suffix}，僅支援 .txt, .md, .json, .pdf, .docx。"
