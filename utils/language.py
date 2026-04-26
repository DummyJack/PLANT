import os
import re

from typing import Any, Dict, Optional


def is_likely_english(text: str) -> bool:
    text = str(text or "").strip()
    if not text:
        return False
    ascii_words = re.findall(r"[A-Za-z]+", text)
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", text)
    return len(ascii_words) >= max(3, len(cjk_chars))


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


def current_output_language() -> str:
    """讀取目前輸出語言模式（zh-Hant / en）。"""
    val = str(os.environ.get("PLANT_OUTPUT_LANGUAGE", "zh-Hant")).strip().lower()
    if val in {"en", "english"}:
        return "en"
    return "zh-Hant"


def directive_embed() -> str:
    if current_output_language() == "en":
        return "Please respond in English."
    return "請使用繁體中文回覆。"


def global_conventions_text() -> str:
    if current_output_language() == "en":
        return "Be specific, concise, and actionable; avoid vague wording. When citing URLs, paste full URLs directly instead of Markdown links."
    return "請具體、精簡、可執行；避免空泛描述。引用網址時直接貼出完整 URL，不要使用 Markdown 超連結語法。"


def short_reasoning_line() -> str:
    if current_output_language() == "en":
        return "Use one short English sentence for reasoning."
    return "reasoning 請使用一句繁體中文簡述。"


def user_requirement_cards() -> str:
    if current_output_language() == "en":
        return "Write requirement cards in English."
    return "需求卡片請使用繁體中文。"


def user_stakeholder_name_reason() -> str:
    return "每位利害關係人需包含名稱與理由。"


def analyst_draft_decision_table_note() -> str:
    return "若有決策，請用精簡決策表呈現。"


def expert_topic_bullets_task() -> str:
    return "請提供 2～4 點重點，包含依據與風險。"


def expert_fallback_viewpoint() -> str:
    return "請以領域專家角度，簡短給出觀點與風險提醒。"


def mediator_agenda_language_line() -> str:
    if current_output_language() == "en":
        return "Use English for title/description."
    return "title/description 請使用繁體中文。"


def mediator_collect_line() -> str:
    return "請清楚整理分歧與未解決事項。"


def mediator_human_options_line() -> str:
    return "請提供 2～4 個可選方案並附優缺點。"


def mediator_reasoning_line() -> str:
    if current_output_language() == "en":
        return "reasoning should be one concise English sentence."
    return "reasoning 請使用一句繁體中文。"


def mediator_summary_decision_line() -> str:
    return "請簡述最終決議與理由。"


def mediator_unresolved_vote_task_line() -> str:
    return "若未解決，請明確說明是否升級為人類裁決。"


def modeler_models_array_name_line() -> str:
    return "陣列欄位名稱請使用 models。"


def modeler_name_field_language() -> str:
    if current_output_language() == "en":
        return "Use English in the name field."
    return "name 欄位請使用繁體中文。"


def modeler_review_field_language() -> str:
    if current_output_language() == "en":
        return "Write review field descriptions in English."
    return "review 欄位說明請使用繁體中文。"


def documentor_srs_body_lang() -> str:
    if current_output_language() == "en":
        return "Write the document body in English."
    return "內文請使用繁體中文。"


def srs_title_instruction() -> str:
    return "文件主標題必須為「[系統名稱]軟體需求規格書」。"
