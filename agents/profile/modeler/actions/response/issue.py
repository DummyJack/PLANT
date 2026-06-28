# Defines general modeler meeting response prompt rendering.
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
    text_hint: str = '"text": "依需求建模立場對此議題的自然會議發言"',
) -> str:
    sections = response_context(
        issue=issue,
        previous_responses=previous_responses,
        related_context=related_context,
    )
    output_fields = response_output_fields(
        issue_id=sections["issue_id"],
        is_pair_review=is_pair_review,
        text_hint=text_hint,
    )
    return f"""# Issue
{sections["issue_text"]}

{prompt_section("# Previous Responses", sections["prev_text"])}{prompt_section("# Related Context", sections["context_text"])}{prompt_section("# Recent Questions", sections["recent_ask_history_text"])}{prompt_section("# Elicitation Context", elicitation_hint)}# 任務
{task_block}

# Action Boundary
- action=issue_response
- 本 action 產生會議回應 JSON，內容包含發言、表態、提問與模型觀點建議。
- 需要建立或更新模型時，應透過 system_modeling action 執行。
- Related Context 只能作為會議發言依據，不可單獨創造未被來源支持的新模型或需求。

# Rules
{rules_block}

# Output JSON
{{
{output_fields}
}}

{forbidden_output_rules(
        [
            "不輸出 artifact patch。",
            "不輸出 PlantUML 或 system model JSON。",
            "不從模型反推新增需求。",
            "不編造不存在的 SM-*、REQ-*、URL-* 或 CR-*。",
        ]
    )}"""


def model_reference_rules() -> str:
    return (
        "\n- 若本輪已產生或更新 System Models 或模型一致性報告，"
        "text 必須引用本輪模型結果說明它如何釐清需求、流程、狀態、actor/use case、資料或責任邊界；"
        "不要只說已建立或已更新模型。"
        "\n- 若本輪沒有產生新模型，但當前專案資料已有與本議題相關的 System Models，"
        "可以引用既有圖中的 actor、use case、流程、狀態、資料或邊界來支撐發言；"
        "若引用既有圖，需明確說出引用哪張圖與它支持或揭露的需求點。"
        "\n- 只能引用「當前專案資料」中實際存在的 system_models id/name；不要說有 SM-*、use case diagram 或 activity diagram，除非它真的出現在輸入資料或本輪 action result。"
        "\n- 若當前專案資料沒有可引用的 system_models，明確說目前沒有可引用模型；若本議題需要模型支撐，應選 system_modeling，而不是假設已有模型。"
        "\n- 若模型揭露流程缺口、狀態不明、責任邊界不清或資料流不一致，必須明確說明應轉成哪一類後續處理：更新需求、提出 open question、建立/更新模型，或交由 define_boundary 議題處理。"
        "\n- 模型新增或更新後，應說明它支援哪些 REQ-*，並避免從模型反推未被需求來源支持的新需求。"
        "\n- 不要為了引用模型而硬解讀無關的圖；模型與本議題無關時，直接用文字建模觀點回答。"
    )


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
        proposal_subject="模型或需求邊界處理方案",
    )
    if category == "align_model":
        rules_block += "\n- 本議題聚焦模型揭露的流程、狀態、actor、use case、資料或權限不一致；請明確指出需求與模型如何對齊。"
        rules_block += "\n- 若本議題涉及 NFR，請指出品質要求如何影響流程、狀態、互動、資料或驗證路徑。"
    elif category == "define_boundary":
        rules_block += "\n- 本議題聚焦系統邊界、外部系統、人工流程與責任邊界；請用模型觀點說明邊界影響。"
        rules_block += "\n- 若本議題涉及 NFR，請說明品質要求套用的系統邊界、外部責任與例外情境。"
    elif category == "clarify_requirement":
        rules_block += "\n- 本議題聚焦需求語意、條件、成功結果與驗收方式；請指出模型是否需要補充流程或狀態。"
        rules_block += "\n- 若本議題涉及 NFR，請協助釐清 metric、validation 與可觀察的流程或狀態條件。"
    elif category == "tradeoff":
        rules_block += "\n- 本議題聚焦方案取捨；請比較各方案對流程、狀態、資料與 actor 的影響。"
        rules_block += "\n- 若本議題涉及 NFR，請比較品質目標對流程複雜度、資料需求、狀態設計與 FR/NFR priority 的影響；constraint 不作 priority 取捨。"
    rules_block += model_reference_rules()
    return render_response_prompt(
        issue=issue,
        previous_responses=previous_responses,
        related_context=related_context,
        task_block=issue_task,
        rules_block=rules_block,
    )
