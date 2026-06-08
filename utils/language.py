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
    return len(ascii_words) >= max(3, len(cjk_chars))


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
