# Defines action prompts and output contracts.
import json
from typing import Any, Dict, List, Optional

from utils.language import output_language_directive


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

# Action Boundary
- action=mediator.judge_options
- 本 action 將未收斂議題整理成可供人類裁決的 options JSON。
- options 必須是可寫回需求的規則，而不是流程策略。

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
- option 應裁決需求內容，而不是「現有需求先納入」「暫緩納入」「後續再細化」這類流程決定。
- 若既有決策資料包含衝突解決選項或 recommended_resolution，優先沿用；只能依討論內容補充影響或調整文字。
- 優先使用 agent 在 proposal 中提出的方案，也可從發言萃取可行方案。
- 每個 option 必須包含 pros、cons、impact、risk。
- compromise 只在有合理折衷時輸出；沒有就回空物件。
- recommendation 是建議，不是決議；最後由人類裁決。
- affected_requirement_ids 優先使用議題來源追蹤中的需求 id；沒有就回空陣列。
- {output_language_directive()}

# 輸出 JSON
{{
  "summary": "此議題需要決策的原因",
  "options": [
    {{
      "option_id": "A",
      "title": "可直接寫回需求的決策規則",
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


def closure_vote(
    *,
    role: str,
    proposer_role: str,
    proposer_roles: Optional[List[str]] = None,
    role_focus: str,
    scenario: Dict[str, Any],
    requirements: List[Dict[str, Any]],
    candidate_texts: List[str],
    recent_ask_history: List[Dict[str, Any]],
) -> str:
    proposer_list = [
        str(item or "").strip()
        for item in (proposer_roles or [proposer_role])
        if str(item or "").strip()
    ]
    proposer_label = "、".join(dict.fromkeys(proposer_list)) or proposer_role
    return f"""# 任務
需求擷取會議收束投票。本輪 {proposer_label} 已提議結束需求擷取，但必須由收束投票流程決定是否真的收束。

# Action Boundary
- action=mediator.closure_vote
- 本 action 依指定角色檢查需求擷取是否可收束，輸出 vote JSON。
- vote=close 表示資訊足夠整理下一版 requirement set；vote=continue 表示仍有阻礙需求正確性的關鍵缺口。

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

# Generation Rules
- 如果依此參與者判斷，目前資訊已足夠整理下一版 requirement set，vote 填 close。
- 如果仍有一個會明顯相關需求正確性的關鍵問題沒問，vote 填 continue。
- 只有缺口會影響需求正確性或可用性時才 vote continue。
- coverage 必須逐項判斷 covered 或 missing。
- 必要 coverage 是 user_goal、main_workflow、inputs_outputs；若其中任何一項 missing，通常應 vote continue。
- constraints_risks、exceptions、acceptance_criteria 可以成為 open question；只有會阻礙下一版 requirement set 正確性或可用性時才放進 blocking_gap。
- 若 vote continue，blocking_gap 必須說明真正阻礙需求正確性的缺口，missing_question 必須是一個可直接問利害關係人的單一主問題。
- 輸出只包含下方 JSON。

# Output JSON
{{
  "vote": "close | continue",
  "reason": "一句話理由",
  "coverage": {{
    "user_goal": "covered | missing",
    "main_workflow": "covered | missing",
    "inputs_outputs": "covered | missing",
    "constraints_risks": "covered | missing",
    "exceptions": "covered | missing",
    "acceptance_criteria": "covered | missing"
  }},
  "blocking_gap": "若 vote=continue，填真正阻礙需求正確性的缺口；否則空字串",
  "missing_question": "若 vote=continue，填一個建議追問；否則空字串",
  "open_questions": ["可後續追蹤但不阻擋收束的問題"]
}}"""
