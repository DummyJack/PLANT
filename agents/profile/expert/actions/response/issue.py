# Defines general expert meeting response prompt rendering.
from typing import Any, Dict, List, Optional

from agents.profile.base import (
    prompt_section,
    question_rules,
    response_context,
    response_output_fields,
    response_rules as base_response_rules,
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
    category_hint: str = "",
    elicitation_hint: str = "",
    is_pair_review: bool = False,
    text_hint: str = '"text": "依領域/風險/限制立場對此議題的自然會議發言"',
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
    extra_rules = issue_rules if task_block == issue_task else ""
    return f"""# Issue
{sections["issue_text"]}

{prompt_section("# Previous Responses", sections["prev_text"])}{prompt_section("# Related Context", sections["context_text"])}{prompt_section("# Recent Questions", sections["recent_ask_history_text"])}{prompt_section("# Category Rules", category_hint)}{prompt_section("# Elicitation Context", elicitation_hint)}{rules_block}

# 任務
{task_block}

# Action Boundary
- action=issue_response
- 本 action 產生會議回應 JSON，內容包含發言、表態、提問與領域/風險觀點建議。
- 需要領域研究或 feedback 更新時，應透過 research_domain action 執行。
- Related Context 只能作為會議發言依據，不可單獨創造外部證據或正式需求。

{prompt_section("# Rules", extra_rules)}# Output JSON
{{
{output_fields}
}}

{forbidden_output_rules(
        [
            "不輸出 artifact patch。",
            "不輸出 research_evidence 或 feedback JSON。",
            "不把 feedback 或外部研究結果定案為正式需求。",
            "不編造外部 URL、來源內容、REQ-*、URL-* 或 CR-*。",
        ]
    )}"""


def category_rules(category: str) -> str:
    if category == "tradeoff":
        return """# 本議題特別要求（tradeoff）
- 說明已取得的外部限制、證據強度、風險後果，以及不可接受的選項。
- 若本議題涉及 NFR，說明品質底線、可接受風險、FR/NFR priority 影響與驗證依據；constraint 不作 priority 取捨。"""
    if category == "clarify_requirement":
        return """# 本議題特別要求（clarify_requirement）
- 說明需求語意、驗收邊界或風險條件是否需要外部證據支撐。
- 若本議題涉及 NFR，協助釐清 category、metric、validation 或適用條件；明確 NFR 不需因為是 NFR 而開會。"""
    if category == "define_boundary":
        return """# 本議題特別要求（define_boundary）
- 說明本系統、第三方服務、人工流程或責任歸屬的外部限制與風險邊界。
- 若本議題涉及 NFR，說明品質要求適用範圍與外部責任邊界；constraint 只討論成立、例外與遵守方式。"""
    if category == "align_model":
        return """# 本議題特別要求（align_model）
- 說明模型揭露的流程、資料、狀態或責任歸屬是否受到外部限制或風險影響。
- 若本議題涉及 NFR，說明品質要求對可靠性、可用性或驗證方式的外部依據。"""
    return ""


def expert_response_contract() -> str:
    return f"""# 回應契約
- text 必須有依據，不可只表態或宣告最終決議。
- 若本輪已產生或更新 feedback，text 必須引用本輪 feedback 結果說明它如何影響本議題的限制、風險、證據強度、驗收邊界或可接受方案；不要只說已更新 feedback。
- 若本輪沒有更新 feedback，但當前專案資料已有與本議題相關的 feedback.json 內容，可以引用既有 findings、constraints、risks 或 recommendations 來支撐發言；若引用既有 feedback，需明確說出引用的是哪一類內容與它支持或揭露的需求點。
- 只有 coverage、gaps、user_guidance、referenced_files、issue 或既有 feedback 明確指出需要文件證據、外部查證或 feedback 更新時，才需要 domain research；一般需求語意或模型對齊問題優先使用既有 feedback 或直接發言。
- 若進行新的 domain research，必須更新 feedback.json，並保留來源 URL；不要只在會議發言中描述研究結論。
- 不要為了引用 feedback 而硬套無關資料；feedback 與本議題無關時，直接以外部限制、風險或證據觀點回答。
- open_questions 只放真正需要後續回答、且會影響限制、風險、驗收邊界或本議題結論的具體問題；沒有就輸出空陣列。
- ready_to_close 仍可提出 open_questions；若目前已有可落地結論，但某個具體答案會影響限制、風險、驗收邊界或需求可接受條件，應輸出 open_questions，而不是只寫進風險或假設。
- stance.state 表示本次發言的討論狀態：ready_to_close=資訊已足夠且可讓 mediator 結束本議題；needs_more_discussion=還需要其他參與者補充或回應。
- 若 stance.state 是 needs_more_discussion，必須在 stance.proposal 提供 proposal，說明建議的領域限制、風險或處理方案。
- ready_to_close 表示本輪已足以產生下一版 draft 或 resolution；不代表所有細節都已完美。
- 若本議題已有可收束內容，但仍需要人類在多個可行需求規則中裁決，stance.needs_human_decision=true。
- ready_to_close 可以同時帶 open_questions；這表示本議題可先收斂，但仍有需要後續回答並追蹤的具體問題。
- needs_more_discussion 必須同時提供最小可行 proposal，說明目前建議如何處理，以及仍缺哪個關鍵答案。

{base_response_rules}

{question_rules}"""


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
    rules_block = expert_response_contract()
    rules_block += response_target_stakeholder_rule(sections["target_stakeholders"], sections["issue_id"])
    return render_response_prompt(
        issue=issue,
        previous_responses=previous_responses,
        related_context=related_context,
        task_block=issue_task,
        rules_block=rules_block,
        category_hint=category_rules(str(issue.get("category") or "").strip()),
    )
