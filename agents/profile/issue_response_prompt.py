# Shared prompt builders for formal meeting issue responses.
import json
from typing import Any, Dict, List, Optional


READY_TO_CLOSE_QUALITY_GATE = """# 收斂品質門檻
- stance.state 只有 ready_to_close 或 needs_more_discussion。
- ready_to_close 表示本輪已足以產生下一版 draft、resolution 或 human decision options；不代表所有細節都已完美。
- 符合以下條件時，應填 ready_to_close：
  - 本議題的主要需求語意、成功結果、責任邊界或取捨方向已能落地記錄。
  - 若會形成或更新 system requirement，已有可追溯來源。
  - 剩餘不足可明確寫成 acceptance_criteria=待確認、assumptions、risks 或 open_questions，而不會阻止本輪結論。
- 只有缺少會改變結論的關鍵資訊時，才填 needs_more_discussion。
- needs_more_discussion 必須同時提供最小可行 proposal，說明目前建議如何處理，以及仍缺哪個關鍵答案。"""


STANCE_RESPONSE_TEXT_RULES = """# response.text 規則
- text 是會議中的自然發言，不是 action 結果、JSON、報告或專案資料內容貼上。
- text 必須依本 agent / speaking_as 的立場發言，說明此立場會關心的需求、風險、限制、模型影響、取捨或底線。
- text 可使用短段落、條列或簡短表格輔助說明；只有在比較方案、列出缺口、限制、風險、模型不一致或衝突處理時才使用表格。
- 不要在 text 中輸出 JSON、schema、程式碼區塊、大型表格或長篇報告。
- 若本輪先執行 action，text 只用自然語言說明該 action 對本議題立場的影響；完整 action 產物會由 conversation 的 analysis / feedback / system_models 欄位保存。
- text 可以引用必要的 requirement id、conflict id 或 model id，但不要把結構化結果原封不動貼進 text。"""


CONFLICT_URL_UPDATE_RULES = """# resolve_conflict 額外規則
- 若 issue_category 是 resolve_conflict，發言重點是把採用的 resolution 落到 URL 層級。
- 所有發言都要扣回具體 conflict id / URL id；不要只談一般痛點、平台願景或抽象風險。
- 可以在 stance.proposal.url_updates 提出可執行修改：
  - keep：保留 URL。
  - revise：改寫 URL text，讓需求不再互相衝突。
  - remove：移除重複、被取代或不再成立的 URL。
- url_updates 每筆使用 action、ids、text、reason。只有 revise 需要 text。
- Analyst 若本次 action 是 discuss_conflict，必須在 stance.proposal.url_updates 輸出至少一筆可執行修改。
- 不要把多筆 URL 串成一筆巨大需求；語意整合應反映在後續 REQ，不在 URL 層合併。"""


def issue_response_context_sections(
    *,
    issue: Dict[str, Any],
    previous_responses: Optional[List[Dict[str, Any]]],
    artifact_context: Optional[Dict[str, Any]],
    skill_context: str = "",
) -> Dict[str, Any]:
    """Shared context rendering for non-user formal meeting responses."""
    issue_id = str(issue.get("id") or "")
    category = str(issue.get("category") or "").strip()
    target_stakeholders = [
        str(name).strip()
        for name in (issue.get("target_stakeholders") or [])
        if str(name).strip()
    ]
    issue_text = f"議題 [{issue_id}]: {issue.get('title', '')}\n描述: {issue.get('description', '')}"

    prev_text = ""
    if previous_responses:
        parts = [
            f"【{r.get('agent', '?')}】\n{(r.get('response') or {}).get('text', '')}"
            for r in previous_responses
            if isinstance(r, dict)
        ]
        if parts:
            prev_text = "\n# 前面的發言\n" + "\n\n".join(parts)

    context_text = ""
    if artifact_context:
        context_text = f"\n# 當前專案資料（供參考）\n{json.dumps(artifact_context, ensure_ascii=False, indent=2)}"

    recent_ask_history_text = ""
    recent_ask_history = issue.get("recent_ask_history") or []
    if recent_ask_history:
        recent_ask_history_text = (
            "\n# 最近幾輪正式提問摘要\n"
            + json.dumps(recent_ask_history, ensure_ascii=False, indent=2)
        )

    skill_section = ""
    if skill_context:
        skill_section = f"\n# 可用技能參考（本輪自行判斷使用）\n{skill_context}\n"

    return {
        "issue_text": issue_text,
        "issue_id": issue_id,
        "category": category,
        "target_stakeholders": target_stakeholders,
        "prev_text": prev_text,
        "context_text": context_text,
        "recent_ask_history_text": recent_ask_history_text,
        "skill_section": skill_section,
    }


def issue_response_action_plan_prompt(
    *,
    role: str,
    issue: Dict[str, Any],
    issue_category: str,
    previous_response_count: int,
    recent_responses: list,
    has_artifact_context: bool,
    recent_ask_history: list,
    actions_text: str,
    default_action: str,
) -> str:
    observation = {
        "role": role,
        "issue": issue,
        "issue_category": issue_category,
        "previous_response_count": previous_response_count,
        "recent_responses": recent_responses,
        "has_artifact_context": has_artifact_context,
        "recent_ask_history": recent_ask_history,
    }
    conflict_rules = (
        f"\n\n{CONFLICT_URL_UPDATE_RULES}"
        if str(issue_category or "").strip() == "resolve_conflict"
        else ""
    )
    return f"""請根據 observation 規劃本次正式會議發言前要執行的 action plan。

# observation
{json.dumps(observation, ensure_ascii=False, indent=2)}

# 可用 action
{actions_text}

# action 選擇規則
- 只使用「可用 action」中列出的 action。
- steps 可包含 1 到 3 個 action；只在本次發言前確實需要連續工作時使用多個 step。
- 若只是根據既有資料表達立場，選最小必要 action，通常是 {default_action}。
- 若 recent_responses 出現新增、否定、修正或補充需求語意、條件、驗收方式、限制、責任邊界或優先級，必須選擇會寫回對應 artifact 的 action，不要只選 respond_issue。
- 若 recent_responses 只是一般立場、偏好或未形成可記錄變更，使用 respond_issue。
- step 順序就是執行順序；不要重複相同 action，也不要為了湊數加 action。
- 每個 step.reasoning 用一句話說明此 action 為何必要。

{READY_TO_CLOSE_QUALITY_GATE}

# 發言提醒
- action plan 完成後仍要產生自然語言發言；不要把 action 結果、JSON 或大型報告直接當成發言。
- 若 action 產生或更新 artifact，發言只說明它如何影響本議題的需求、限制、風險、模型或取捨。
{conflict_rules}

# 輸出 JSON
{{
  "action": "done",
  "params": {{}},
  "reasoning": "...",
  "action_plan": {{
    "goal": "本次正式會議發言目標",
    "steps": [
      {{"id": "{default_action}", "action": "{default_action}", "params": {{}}, "reasoning": "..."}}
    ]
  }}
}}"""
