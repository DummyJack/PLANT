# Defines action prompts and output contracts.

from typing import List

from agents.profile.base import prompt_section


def issue_response(
    *,
    stakeholder_contract_text: str,
    roles_text: str,
    issue_text: str,
    prev_text: str,
    context_text: str,
    category_hint: str,
    flow_hint: str,
    json_hint: str,
    stance_json_text: str,
    stance_rule_text: str,
    open_questions_rule: str,
    answer_all_questions: bool,
    need_speaking_as: bool,
    names_list_text: str,
    target_stakeholders: List[str],
) -> str:
    return f"""# 任務
以指定 speaking_as 利害關係人身份在會議中自然發言。

# Action Boundary
- action=user.issue_response
- 本 action 產生會議回應 JSON。
- text 代表 speaking_as 的第一人稱需求、顧慮、底線、可接受條件或回答。

# Stakeholder Contract
{stakeholder_contract_text}

# Available Roles
{roles_text}

# Issue
{issue_text}

{prompt_section("# Previous Responses", prev_text)}{prompt_section("# Related Context", context_text)}{prompt_section("# Category Rules", category_hint)}{prompt_section("# Flow Rules", flow_hint)}# Response Rules
- text 要自然、口語、貼近日常使用情境。
- text 使用第一人稱，以 speaking_as 身份在會議中直接發言；不要寫成第三人稱需求描述。
- 回答必須扣回原始產品情境與 speaking_as 指定身份。
- 只表達需求、顧慮、底線與可接受條件；不要寫技術解法或最終需求文字。
- text 必須像該 speaking_as 身份在會議中的發言，不是需求規格文字、JSON、action 結果或專案資料內容貼上。
- 在一般正式會議中，發言作用是利害關係人確認：明確說明目前 REQ 或決策是否符合該身份需求，並補充缺少的條件、例外、驗收方式、風險或不可接受底線。
- 若本輪是需求正式化，請針對前面整理出的 REQ-* 結果回應；若有遺漏或欄位需要修正，具體說明要補哪個使用情境、業務規則、例外條件、驗收條件、限制、優先級、風險或假設。
- 需求正式化不提出 open_questions；若整理結果仍不完整，請在 text 與 stance.proposal 說明需要補充或修正的內容。
- 若本輪是解決需求衝突，必須引用具體 URL id 或 conflict id 表態，說明採用、調整或拒絕既有 resolution 的理由；不要只描述一般痛點。
- 不得使用其他利害關係人的第一人稱經驗回答；每段發言必須符合 speaking_as 指定身份的責任、痛點與視角。
- 若同一題指定多個 speaking_as，text 必須用「【身份名稱】」分段，各段內容要反映該身份不同的責任、痛點、利益或限制，不得複製同一段回答。
- 若本輪是回答 open question，只回答被問的問題，不做正式提案或收斂判斷。
{open_questions_rule.rstrip()}
{stance_rule_text.rstrip()}
- 若資訊不足，可直接說明不確定之處。
{('- 若前面有多位參與者提問，text 必須逐題回答每一題。' if answer_all_questions else '')}
{f'- speaking_as 的名稱必須從以下選一個或數個：{names_list_text}' if need_speaking_as else ''}
{f'- 若本輪有指定回答身份，speaking_as 必須只使用議題規劃指定的 target_stakeholders：{", ".join(target_stakeholders)}' if target_stakeholders else ''}

# Output JSON
{{
    {json_hint}{stance_json_text}
}}"""
