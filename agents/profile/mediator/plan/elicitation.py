# Handles shared agent profile prompts and helper behavior.
import json
from typing import Any, Dict, List, Optional

from storage.requirements import requirement_discussion_pool

from ..validation import elicitation_plan


def build_elicitation_plan(
    *,
    turn: int,
    max_turns: int,
    default_participants: List[str],
    stakeholder_names: List[str],
    scenario: Dict[str, Any],
    scope: Dict[str, Any],
    current_requirements: List[Dict[str, Any]],
    previous_turn_summary: Dict[str, Any],
    recent_ask_history: Optional[List[Dict[str, Any]]],
) -> str:
    prev = previous_turn_summary or {}
    return f"""# 任務
安排本輪需求擷取會議，決定 participants、goal、actions、meeting_phase。

# Action Boundary
- action=mediator.plan_elicitation
- 本 action 規劃下一輪需求擷取會議，輸出 participants、meeting_phase、goal 與各 agent action。
- action 只能安排 ask_user、supplement_question 或 propose_finish。

- turn: {turn}/{max_turns}
- default_participants: {default_participants}

# 產品情境
{json.dumps(str(scenario or "").strip(), ensure_ascii=False, indent=2)}

# Scope
{json.dumps(scope or {}, ensure_ascii=False, indent=2)}

# 利害關係人
{json.dumps(stakeholder_names, ensure_ascii=False, indent=2)}

# 目前 User Requirements
{json.dumps(current_requirements, ensure_ascii=False, indent=2)}

# 上一輪摘要
{json.dumps(prev, ensure_ascii=False, indent=2)}

# 近期提問紀錄
{json.dumps(recent_ask_history or [], ensure_ascii=False, indent=2)}

- 像真實需求訪談主持人一樣，根據已回答內容安排下一個最自然、最能補足需求理解的方向。
- 優先在 scope.in_scope 內推進。
- goal 是本輪需求擷取的主題標題，需簡短、具體、可指導 agent 提問；不要寫成「繼續訪談」「了解更多需求」。
- 若 previous_turn_summary 已標記某方向為已確認、已關閉或不要重複，除非仍阻礙需求成形，否則本輪應往不同但重要的方向推進。
- 先補足需求主幹，再進入細節審查。
- 不要把「動機」當成預設必問項；只有當動機會改變需求內容、優先級、成功標準或範圍時才追問。

- analyst：使用者目標、需求語意、使用條件、成功結果與驗收邊界。
- expert：外部限制、領域規則、營運風險、公平性、責任歸屬與證據缺口。
- modeler：流程節點、狀態轉移、actor 責任、資料輸入輸出、例外流程與人工介入。
- 每個 agent 安排符合自身分工的提問；若某 agent 本輪沒有符合分工的高價值問題，可以不安排該 agent 提問。
- 每個 ask_user/supplement_question 必須指定 target_stakeholders，且問題內容必須從該 stakeholder 的立場出發。
- 問題需符合 target stakeholder 會關心的影響、責任、限制或底線。

同一輪內，不同 agent 不可追問同一個需求缺口。
每個被安排提問的 agent 都必須能問出可轉成候選 User Requirement、限制、流程邊界或待確認缺口的資訊。

- ask_user：本輪主要向 user 問一個主問題。
- supplement_question：從該參與者角度補一個不重複的 user 問題。
- propose_finish：提議結束需求擷取。

meeting_phase 只用來標示本輪狀態：
- initial_requirement：找出最能形成候選需求的核心缺口。
- requirement_discussion：深入釐清流程、內容、互動、呈現、限制、例外或可接受標準。
- conclusion：確認目前理解是否正確或提議收束。

- participants 只能從 default_participants 選，且必須包含 user。
- participants 應包含 2-3 位非 user agent 與 user。
- 除非本輪要 propose_finish，否則至少一個非 user agent 的 action 必須是 ask_user 或 supplement_question。
- propose_finish 只能在資訊足夠收束時使用；若使用 propose_finish，該 agent 的發言只能輸出固定停止句。
- 輸出 JSON。

# Output JSON
{{
  "participants": {json.dumps(default_participants, ensure_ascii=False)},
  "meeting_phase": "initial_requirement | requirement_discussion | conclusion",
  "goal": "本輪訪談目標",
  "actions": {{
    "analyst": {{"action": "ask_user | supplement_question | propose_finish", "target_stakeholders": ["stakeholder name"]}},
    "expert": {{"action": "ask_user | supplement_question | propose_finish", "target_stakeholders": ["stakeholder name"]}},
    "modeler": {{"action": "ask_user | supplement_question | propose_finish", "target_stakeholders": ["stakeholder name"]}}
  }}
}}"""


class ElicitationPlan:
    def run_elicitation_planning(
        self,
        *,
        artifact: Dict[str, Any],
        turn: int,
        max_turns: int,
        default_participants: List[str],
        previous_turn_summary: Optional[Dict[str, Any]] = None,
        recent_ask_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        prev = previous_turn_summary or {}
        stakeholder_names = [
            str(row.get("name") or "").strip()
            for row in (artifact.get("stakeholders", []) or [])
            if isinstance(row, dict) and str(row.get("name") or "").strip()
        ]
        if not stakeholder_names:
            stakeholder_names = ["user"]
        current_requirements = [
            {
                "id": str(req.get("id") or "").strip(),
                "text": str(req.get("text") or "").strip(),
                "type": str(req.get("type") or "").strip(),
            }
            for req in requirement_discussion_pool(artifact)
            if isinstance(req, dict) and str(req.get("text") or "").strip()
        ]
        prompt = build_elicitation_plan(
            turn=turn,
            max_turns=max_turns,
            default_participants=default_participants,
            stakeholder_names=stakeholder_names,
            scenario=artifact.get("scenario", ""),
            scope=artifact.get("scope", {}),
            current_requirements=current_requirements,
            previous_turn_summary=prev,
            recent_ask_history=recent_ask_history,
        )

        messages = self.build_direct_messages(prompt)
        try:
            data = self.chat_json(messages)
        except Exception as e:
            raise RuntimeError(f"逐輪策略決策輸出格式不合格: {e}") from e
        return elicitation_plan(
            data,
            default_participants=default_participants,
            stakeholder_names=stakeholder_names,
        )
