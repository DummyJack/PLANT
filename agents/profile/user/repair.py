# Defines repair prompts for agent output.
import json
from typing import Any, List, Optional


def retry_response(
    *,
    user_prompt: str,
    format_error: str,
    include_stance: bool,
    need_speaking_as: bool = False,
    names_list_text: str = "",
    target_stakeholders: Optional[List[str]] = None,
    invalid_response: Any = None,
) -> str:
    speaking_as_field = (
        '  "speaking_as": ["本輪發言身份名稱"],\n'
        if need_speaking_as
        else ""
    )
    stance_field = (
        ',\n  "stance": {"state": "ready_to_close", "needs_human_decision": false}'
        if include_stance
        else ""
    )
    output_contract = (
        "{\n"
        f"{speaking_as_field}"
        '  "text": "自然語言回答",\n'
        '  "open_questions": []'
        f"{stance_field}\n"
        "}"
    )
    rule = (
        "- stance.state 必須輸出，且只能是 ready_to_close 或 needs_more_discussion。\n"
        if include_stance
        else ""
    )
    speaking_as_rule = ""
    allowed_names = ", ".join(
        str(name).strip()
        for name in (target_stakeholders or [])
        if str(name).strip()
    ) or names_list_text
    if need_speaking_as:
        speaking_as_rule = (
            "- speaking_as 必須輸出為非空陣列。\n"
            f"- speaking_as 只能使用這些名稱：{allowed_names}。\n"
            "- 不可省略 speaking_as，也不可使用未列出的身份名稱。\n"
        )
    return (
        "# 任務\n"
        "上一個利害關係人回應格式不合格。請只修正輸出格式與必要欄位，重新產生自然語言回應。\n\n"
        "# 限制\n"
        "- text 必須是自然語言，不要輸出 action 結果 JSON。\n"
        f"{rule}"
        f"{speaking_as_rule}"
        "- 不要輸出 Markdown code fence。\n\n"
        "# 原始任務\n"
        f"{user_prompt}\n\n"
        "# 格式錯誤\n"
        f"{format_error}\n\n"
        "# 前次回應\n"
        f"{json.dumps(invalid_response or {}, ensure_ascii=False, separators=(',', ':'))}\n\n"
        "- 前次回應中沒有被格式錯誤點名的有效欄位必須原樣保留。\n"
        "- 只修正錯誤欄位，不得改寫原本有效的 text、open_questions、stance 或 pair_reviews。\n\n"
        "# 必須符合的 JSON 結構\n"
        f"{output_contract}"
    )
