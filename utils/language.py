# Handles language logic for shared utility behavior for the Plant runtime.
import os
import re
from typing import Any, Dict, Optional


# ========
# Defines is likely english function for this module workflow.
# ========
def is_likely_english(text: str) -> bool:
    text = str(text or "").strip()
    if not text:
        return False
    ascii_words = re.findall(r"[A-Za-z]+", text)
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", text)
    if cjk_chars:
        return False
    return bool(ascii_words)


# ========
# Defines sync output language function for this module workflow.
# ========
def sync_output_language(
    rough_idea: str,
    artifact: Optional[Dict[str, Any]] = None,
) -> str:
    lang = "en" if is_likely_english(rough_idea) else "zh-Hant"
    os.environ["PLANT_OUTPUT_LANGUAGE"] = lang
    if isinstance(artifact, dict):
        meta = artifact.get("meta")
        if not isinstance(meta, dict):
            meta = {}
            artifact["meta"] = meta
        meta["output_language"] = lang
    return lang


# ========
# Defines current output language function for this module workflow.
# ========
def current_output_language() -> str:
    val = str(os.environ.get("PLANT_OUTPUT_LANGUAGE", "zh-Hant")).strip().lower()
    if val in {"en", "english"}:
        return "en"
    return "zh-Hant"


# ========
# Defines output language directive function for this module workflow.
# ========
def output_language_directive() -> str:
    if current_output_language() == "en":
        return (
            "Use English for all generated natural-language content. Preserve "
            "technical terms, product names, API names, code identifiers, and "
            "required IDs in their conventional form."
        )
    return (
        "請使用繁體中文產生所有自然語言內容。技術術語、產品名稱、API 名稱、"
        "程式碼識別字與必要 ID 可保留其慣用形式。"
    )
