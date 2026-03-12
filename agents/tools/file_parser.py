"""
檔案解析工具：供 Expert 在討論或研究時讀取 doc 目錄下的檔案。
輸入:
- file_path: 相對於 doc/ 的路徑
- output_format: text | json_summary
輸出:
- 純文字（text）或 JSON 字串（json_summary）
"""
import json
import logging
from pathlib import Path
from typing import Optional

from .base import BaseTool

logger = logging.getLogger("Plant.FileParserTool")


class FileParserTool(BaseTool):
    name = "file_parser"
    description = (
        "解析專案 doc 目錄下的外部參考檔案（支援 .txt, .md, .json, .pdf, .docx），"
        "可輸出純文字或摘要 JSON。"
    )
    parameters = {
        "file_path": {
            "type": "string",
            "description": "相對於 doc 目錄的檔案路徑，例如 'regulation.pdf' 或 'refs/guide.md'",
            "required": True,
        },
        "output_format": {
            "type": "string",
            "description": "輸出格式：text 或 json_summary（預設 text）",
            "required": False,
        },
    }

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir else Path("doc")

    def execute(self, **kwargs) -> str:
        file_path = kwargs.get("file_path")
        output_format = (kwargs.get("output_format") or "text").strip()
        if not file_path or not isinstance(file_path, str):
            return "錯誤：請提供 file_path 參數。"
        if output_format not in ("text", "json_summary"):
            return "錯誤：output_format 僅支援 text 或 json_summary。"

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
            text = self._read_text_by_type(path, suffix)
        except ImportError as e:
            return f"錯誤：缺少依賴（{e}），無法讀取 {suffix} 檔案。"
        except Exception as e:
            logger.warning("file_parser 讀取失敗 %s: %s", path, e)
            return f"錯誤：無法讀取檔案：{e}"

        if output_format == "text":
            return text

        payload = {
            "file_path": str(path.relative_to(self.base_dir.resolve())),
            "suffix": suffix,
            "char_count": len(text),
            "preview": text[:2000],
        }
        return json.dumps(payload, ensure_ascii=False)

    def _read_text_by_type(self, path: Path, suffix: str) -> str:
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
        raise ValueError(f"不支援的副檔名 {suffix}，僅支援 .txt, .md, .json, .pdf, .docx。")
