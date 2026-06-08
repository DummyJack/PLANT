# Defines action prompts and output contracts.
import json
from typing import Any, Dict, List, Optional


# ========
# Defines judge options function for this module workflow.
# ========
def judge_options(
    *,
    issue: Dict[str, Any],
    discussion_text: str,
    decision_context: Optional[Dict[str, Any]] = None,
) -> str:
    context_block = ""
    if decision_context:
        context_block = (
            "\n# 既有決策資料\n"
            f"{json.dumps(decision_context, ensure_ascii=False, indent=2)}\n"
        )
    return f"""# 任務
把尚未自然收斂的正式會議議題整理成人類裁決選項。
不要替人類做最終決策，也不要模擬投票。
選項必須是可寫回需求的規則，不是「先納入 / 暫緩 / 分階段」這類流程策略。

# 議題
標題: {issue.get("title", "")}
類型: {issue.get("category", "")}
描述: {issue.get("description", "")}
預期結果: {issue.get("expect_outcome", "")}

# 討論紀錄
{discussion_text or "（無發言紀錄）"}
{context_block}
# 規則
- options 列 2-5 個可執行的需求規則；同一議題可讓人類同時採用多個 option。
- 每個 option 要裁決一個具體需求內容，且該內容必須能直接影響需求條文、驗收條件、限制、風險或後續行動。
- 不要產生「現有需求先納入」「暫緩納入」「後續再細化」這類只決定流程、不決定需求內容的 option。
- 若既有決策資料包含衝突解決選項或 recommended_resolution，優先沿用；只能依討論內容補充影響或調整文字。
- 優先使用 agent 在 proposal 中提出的方案，也可從發言萃取可行方案。
- 每個 option 必須包含 pros、cons、impact、risk。
- compromise 只在有合理折衷時輸出；沒有就回空物件。
- recommendation 是建議，不是決議；最後由人類裁決。
- affected_requirement_ids 優先使用議題來源追蹤中的需求 id；沒有就回空陣列。
- 使用繁體中文。

# 輸出 JSON
{{
  "summary": "此議題需要決策的原因",
  "options": [
    {{
      "id": "A",
      "summary": "可直接寫回需求的決策規則",
      "pros": ["優點"],
      "cons": ["限制或代價"],
      "impact": ["對需求、範圍、驗收或設計的影響"],
      "risk": "low | medium | high"
    }}
  ],
  "recommendation": {{
    "option_id": "A",
    "rationale": "為何建議此方案",
    "needs_human": true
  }},
  "compromise": {{
    "title": "折衷方案標題",
    "description": "折衷方案內容",
    "rationale": "為何此方案能平衡各方需求"
  }},
  "affected_requirement_ids": ["REQ-1"],
  "unresolved_points": ["需要人類裁決的事項"]
}}"""


# ========
# Defines closure vote function for this module workflow.
# ========
def closure_vote(
    *,
    role: str,
    proposer_role: str,
    role_focus: str,
    scenario: Dict[str, Any],
    requirements: List[Dict[str, Any]],
    candidate_texts: List[str],
    recent_ask_history: List[Dict[str, Any]],
) -> str:
    return f"""# 任務
需求擷取會議收束投票。本輪 {proposer_role} 已提議結束需求擷取，但必須由收束投票流程決定是否真的收束。

# Role
{role}

# Role Focus
{role_focus}

# Scenario
{json.dumps(str(scenario or "").strip(), ensure_ascii=False, indent=2)}

# Requirements
{json.dumps(requirements, ensure_ascii=False, indent=2)}

# Candidate Texts
{json.dumps(candidate_texts, ensure_ascii=False, indent=2)}

# Recent Ask History
{json.dumps(recent_ask_history or [], ensure_ascii=False, indent=2)}

# Voting Rules
- 如果依此參與者判斷，目前資訊已足夠整理下一版 requirement set，vote 填 close。
- 如果仍有一個會明顯相關需求正確性的關鍵問題沒問，vote 填 continue。
- 不要因為還可以問更多細節就反對收束；只有缺口會相關需求正確性或可用性時才 vote continue。
- 若 vote continue，missing_question 必須是一個可直接問利害關係人的單一主問題。
- 輸出只包含下方 JSON。

# Output JSON
{{"vote":"close|continue","reason":"一句話理由","missing_question":"若 vote=continue，填一個建議追問；否則空字串"}}"""
