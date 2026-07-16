# Defines general meeting response prompt rendering.
from typing import Any, Dict, List, Optional

from agents.profile.base import (
    prompt_section,
    question_rules,
    response_context,
    response_output_fields,
    response_rules,
    response_stance_rules,
    response_target_stakeholder_rule,
)
from agents.profile.base import forbidden_output_rules

from ...rules import issue_rules, issue_task


def render_response_prompt(
    *,
    issue: Dict[str, Any],
    previous_responses: Optional[List[Dict[str, Any]]],
    related_context: Optional[Dict[str, Any]],
    task_block: str,
    rules_block: str,
    is_pair_review: bool = False,
    elicitation_hint: str = "",
    text_hint: str = '"text": "依需求分析立場對此議題的自然會議發言"',
) -> str:
    sections = response_context(
        issue=issue,
        previous_responses=previous_responses,
        related_context=related_context,
    )
    output_fields = response_output_fields(
        issue_id=sections["issue_id"],
        issue_category=str(issue.get("category") or "").strip(),
        is_pair_review=is_pair_review,
        text_hint=text_hint,
    )
    return f"""# Issue
{sections["issue_text"]}

{prompt_section("# Previous Responses", sections["prev_text"])}{prompt_section("# Related Context", sections["context_text"])}{prompt_section("# Recent Questions", sections["recent_ask_history_text"])}{prompt_section("# Elicitation Context", elicitation_hint)}# 任務
{task_block}

# Action Boundary
- action=issue_response
- 本 action 產生會議回應 JSON，內容包含發言、表態、提問與需求處理建議。
- Related Context 只能作為會議發言依據，不可單獨創造未被來源支持的新需求。

# Rules
{rules_block}

# Output JSON
{{
{output_fields}
}}

{forbidden_output_rules(
        [
            "不輸出 artifact patch。",
            "不輸出 requirement_update、scope_updates、draft_plan 或 conflicts。",
            "不新增未被來源支持的新需求。",
            "不編造不存在的 REQ-*、URL-*、SM-* 或 CR-*。",
        ]
    )}"""


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
    issue_id = sections["issue_id"]
    category = str(issue.get("category") or "").strip()
    rules_block = issue_rules
    rules_block += response_target_stakeholder_rule(sections["target_stakeholders"], issue_id)
    rules_block += "\n" + response_rules
    rules_block += "\n" + question_rules
    rules_block += response_stance_rules(
        issue_id=issue_id,
        category=category,
        proposal_subject="需求處理方案",
    )
    if category == "clarify_requirement":
        rules_block += "\n- 本議題聚焦釐清需求語意、條件、成功結果與驗收方式；不要擴張未被來源支持的新需求。"
        rules_block += "\n- 若本議題涉及 NFR，只釐清 category、metric、validation、適用範圍或 FR/NFR priority；明確 NFR 應建議直接寫回 REQ。"
    elif category == "define_boundary":
        rules_block += "\n- 本議題聚焦系統、外部服務、人工流程與責任邊界；請明確指出應寫入 scope、requirement 或 open question 的結果。"
        rules_block += "\n- 若本議題涉及 NFR，請說明品質要求套用在哪些流程、參與者、資料或情境；constraint 不討論 priority，只討論適用邊界與遵守方式。"
    elif category == "tradeoff":
        rules_block += "\n- 本議題聚焦方案比較、取捨與推薦；stance.proposal 必須提出可落地的需求處理方案。"
        rules_block += "\n- 若本議題涉及 NFR，請比較品質目標、成本、使用體驗、技術可行性與 FR/NFR priority；constraint 不作 priority 取捨。"
    elif category == "align_model":
        rules_block += "\n- 本議題聚焦模型揭露的流程、狀態、actor、資料或權限不一致；請指出應更新需求、模型或 open question。"
        rules_block += "\n- 若本議題涉及 NFR，請指出品質要求是否影響流程、狀態、資料、權限或模型驗證方式。"
    return render_response_prompt(
        issue=issue,
        previous_responses=previous_responses,
        related_context=related_context,
        task_block=issue_task,
        rules_block=rules_block,
    )
