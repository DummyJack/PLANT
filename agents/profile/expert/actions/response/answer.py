# Defines expert open-question answer prompt.
from typing import Any, Dict, List, Optional

from agents.profile.base import response_context, response_target_stakeholder_rule

from .issue import render_response_prompt


def issue_response(
    *,
    issue: Dict[str, Any],
    previous_responses: Optional[List[Dict[str, Any]]],
    related_context: Optional[Dict[str, Any]],
) -> str:
    sections = response_context(
        issue=issue,
        previous_responses=previous_responses,
        related_context=related_context,
    )
    rules_block = """# 回應契約
- 只回答 description 中的問題；不要做正式議題提案或收斂判斷。
- 回答需聚焦領域限制、法規/標準、風險、證據強度或 evidence gap。
- 不更新專案資料，不輸出 stance。
- open_questions 預設輸出空陣列；只有問題本身無法回答且答案會影響本議題結論時才提出。"""
    rules_block += response_target_stakeholder_rule(sections["target_stakeholders"], sections["issue_id"])
    return render_response_prompt(
        issue=issue,
        previous_responses=previous_responses,
        related_context=related_context,
        task_block="以領域專家角度直接回答提問。",
        rules_block=rules_block,
    )
