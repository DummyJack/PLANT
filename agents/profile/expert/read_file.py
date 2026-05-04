# Expert file helpers: detect reference docs and parse model JSON safely.
import json
from pathlib import Path
from typing import Dict


DOC_SUPPORTED_SUFFIXES = (".txt", ".md", ".json", ".pdf", ".docx", ".doc")


def has_supported_doc_files(doc_dir: Path) -> bool:
    """檢查 doc 目錄下是否至少有一個支援的檔案（含子目錄）。"""
    if not doc_dir.is_dir():
        return False
    for p in doc_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in DOC_SUPPORTED_SUFFIXES:
            return True
    return False


class ExpertReadFile:
    def has_doc_reference_files(self) -> bool:
        """與 ToolRegistry 一致：doc/ 下是否有至少一個可給 file_parser 使用的檔案。"""
        return has_supported_doc_files(self.doc_dir)


class ExpertParsing:
    @staticmethod
    def parse_first_json(raw: str) -> Dict:
        """從可能含多個 JSON 或後綴文字的內容中，只解析第一個完整 JSON 物件。"""
        if not raw or not isinstance(raw, str):
            return {}
        raw = raw.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        start = raw.find("{")
        if start == -1:
            return {}
        depth = 0
        for i in range(start, len(raw)):
            if raw[i] == "{":
                depth += 1
            elif raw[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(raw[start : i + 1])
                    except json.JSONDecodeError:
                        pass
                    break
        return {}
