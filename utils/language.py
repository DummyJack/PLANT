# Handles language logic for shared utility behavior for the Plant runtime.
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Optional


_output_language: ContextVar[Optional[str]] = ContextVar(
    "plant_output_language",
    default=None,
)


def normalize_output_language(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"en", "english"}:
        return "en"
    if text in {"zh-hant", "zh_hant", "traditional-chinese", "traditional_chinese"}:
        return "zh-Hant"
    raise ValueError(f"output_language 不合法: {value}")


def set_output_language(
    language: Any,
    artifact: Optional[Dict[str, Any]] = None,
) -> str:
    normalized = normalize_output_language(language)
    _output_language.set(normalized)
    if isinstance(artifact, dict):
        meta = artifact.get("meta")
        if not isinstance(meta, dict):
            meta = {}
            artifact["meta"] = meta
        meta["output_language"] = normalized
    return normalized


@contextmanager
def output_language_context(language: Any):
    token = _output_language.set(normalize_output_language(language))
    try:
        yield current_output_language()
    finally:
        _output_language.reset(token)


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
    return set_output_language(lang, artifact)


# ========
# Defines current output language function for this module workflow.
# ========
def current_output_language() -> str:
    contextual = _output_language.get()
    if contextual is not None:
        return contextual
    try:
        return normalize_output_language(os.environ.get("PLANT_OUTPUT_LANGUAGE", "zh-Hant"))
    except ValueError:
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
