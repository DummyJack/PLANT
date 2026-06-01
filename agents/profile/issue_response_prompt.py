# Shared prompt builders for formal meeting issue responses.
import json
from typing import Any, Dict


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


def issue_response_action_plan_prompt(
    *,
    role: str,
    issue: Dict[str, Any],
    issue_category: str,
    previous_response_count: int,
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
        "has_artifact_context": has_artifact_context,
        "recent_ask_history": recent_ask_history,
    }
    conflict_rules = (
        f"\n\n{CONFLICT_URL_UPDATE_RULES}"
        if str(issue_category or "").strip() == "resolve_conflict"
        else ""
    )
    return f"""請根據 observation 規劃本次正式會議發言的 action plan。

# observation
{json.dumps(observation, ensure_ascii=False, indent=2)}

# 可用 action
{actions_text}

# 規則
- 只輸出 JSON object。
- action 固定輸出 "done"。
- action_plan.steps 可包含 1 到 3 個 step，代表本次輪到該 agent 時要先執行的工作。
- step.action 必須是上述其中之一。
- step.reasoning 用一句話說明為什麼此 action 適合本次發言。
- 依「可用 action」中的「使用時機 / 不要使用 / 寫回或影響」判斷；使用時機不符合，或符合不要使用條件，就不要選該 action。
- 多個 step 只在本次發言確實需要連續工作時使用，例如先抽取新需求再分析衝突、先研究資料再更新 feedback、先建模再驗證。
- step 的順序就是執行順序；不要為了湊數重複相同 action。
- 若只是針對既有資料表達立場，選最小必要 action。
- reasoning 用一句話摘要本次規劃。
- 規劃時必須考慮收斂品質門檻；若本次發言需要補足該門檻，action_plan 要先安排能補足缺口的 action。

{READY_TO_CLOSE_QUALITY_GATE}

{STANCE_RESPONSE_TEXT_RULES}
{conflict_rules}

# 輸出
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
