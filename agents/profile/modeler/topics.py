# Modeler topic logic: propose model issues and build modeler meeting responses.
import json
from typing import Any, Dict, List, Optional

from utils.language import current_output_language


class ModelerTopics:
    def propose_topics(
        self,
        artifact: Dict[str, Any],
        *,
        round_num: int,
        max_items: int = 2,
    ) -> List[Dict[str, Any]]:
        proposals: List[Dict[str, Any]] = []
        models = ((artifact.get("system_models") or {}).get("models") or [])
        required_types = {
            "context_diagram",
            "use_case_diagram",
            "activity_diagram",
            "data_flow_diagram",
        }
        existing_types = {m.get("type") for m in models if m.get("type")}
        missing = sorted(list(required_types - existing_types))
        if missing:
            proposals.append(
                {
                    "title": "模型覆蓋補齊討論",
                    "description": f"尚缺圖型：{', '.join(missing)}，需確認是否補齊與優先順序。",
                    "category": "open_question",
                    "participants": ["modeler", "analyst", "user"],
                    "discussion_mode": "sequential",
                    "speaking_order": ["modeler", "analyst", "user"],
                    "source_ids": [],
                    "priority_hint": "medium",
                    "impact_level": "medium",
                    "why_now": "需求工程模型覆蓋不足會影響後續需求理解、流程討論與驗證。",
                    "proposed_by": "modeler",
                    "round": round_num,
                }
            )

        for m in models:
            to_confirm = m.get("to_confirm") or []
            if not to_confirm:
                continue
            mtype = (m.get("type") or "").strip()
            proposals.append(
                {
                    "title": f"{mtype or '模型'} 待確認事項討論",
                    "description": "；".join([str(x).strip() for x in to_confirm if str(x).strip()]),
                    "category": "open_question",
                    "participants": ["modeler", "analyst", "user", "expert"],
                    "discussion_mode": "sequential",
                    "speaking_order": ["modeler", "analyst", "user", "expert"],
                    "source_ids": [mtype] if mtype else [],
                    "priority_hint": "medium",
                    "impact_level": "medium",
                    "why_now": "模型存在待確認項，可能影響需求解讀與可實作性。",
                    "proposed_by": "modeler",
                    "round": round_num,
                }
            )

        return proposals[: max(1, max_items)]

    def build_topic_response_prompt(
        self,
        *,
        topic: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]],
        artifact_snapshot: Optional[Dict[str, Any]],
    ) -> str:
        topic_text = f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n描述: {topic.get('description', '')}"
        topic_id = str(topic.get("id") or "")

        prev_text = ""
        if previous_responses:
            parts = [
                f"【{r.get('agent', '?')}】\n{r.get('response', {}).get('statement', '')}"
                for r in previous_responses
            ]
            prev_text = "\n# 前面的發言\n" + "\n\n".join(parts)

        snapshot_text = ""
        if artifact_snapshot:
            snapshot_text = f"\n# 當前專案狀態（供參考）\n{json.dumps(artifact_snapshot, ensure_ascii=False, indent=2)}"

        recent_ask_history_text = ""
        recent_ask_history = topic.get("recent_ask_history") or []
        if recent_ask_history:
            recent_ask_history_text = (
                "\n# 最近幾輪正式提問摘要\n"
                + json.dumps(recent_ask_history, ensure_ascii=False, indent=2)
            )
        elicitation_memory_text = ""
        elicitation_memory = topic.get("elicitation_memory") or {}
        if elicitation_memory:
            elicitation_memory_text = (
                "\n# 訪談記憶（避免重複）\n"
                + json.dumps(elicitation_memory, ensure_ascii=False, indent=2)
            )
        my_action_text = ""
        agent_actions = topic.get("agent_actions") if isinstance(topic.get("agent_actions"), dict) else {}
        my_action = agent_actions.get("modeler") if isinstance(agent_actions.get("modeler"), dict) else {}
        if my_action:
            my_action_text = (
                "\n# 本輪你的 action\n"
                + json.dumps(my_action, ensure_ascii=False, indent=2)
            )
        skill_section = ""
        skill_context = self.get_optional_skill_context(topic, artifact_snapshot)
        if skill_context:
            skill_section = f"\n# Skill 參考（本輪由 agent 自行判斷使用）\n{skill_context}\n"
        allow_suggested_next_action = (
            (topic.get("category") or "").strip() != "conflict_discussion"
            and not topic_id.startswith("ELICIT-")
        )

        tool_hint = ""
        if self.tools:
            tool_hint = "\n# 工具使用\n- 若發言中涉及 PlantUML 片段，可先使用 plantuml_validate 驗證語法，再撰寫發言。\n- 最後**必須**輸出下列 JSON。"

        elicitation_hint = ""
        task_block = "請以系統建模專家身分發言，聚焦模型影響、元素邊界與更新建議。"
        rules_block = """- statement 需包含：結論、影響分析、風險/邊界、建議下一步。
    - 需明確指出受影響的模型元素、圖型或責任邊界，不要只講抽象原則。
    - 若資訊不足，說明需補哪些介面、事件流程或資料邊界，不可臆測。
    - 可提到 Use Case / Class / Sequence 的具體影響。
    - 若需要他人補資訊，再在 open_questions 提具體問題。
    - 可用純文字表格或流程輔助；若使用，請放在程式碼區塊。"""
        if allow_suggested_next_action:
            rules_block += "\n- 若你認為本議題討論結束後應由外層流程安排下一步，可額外提供 suggested_next_action；這只是建議，不會在會議中直接執行。"
        if (topic.get("category") or "").strip() == "conflict_discussion":
            task_block = "請以系統建模專家身分逐筆再審查目前這批 Conflict/Neutral pairs，先根據 requirement_a / requirement_b 原文獨立重判，並將重判結果填入 proposed_label。"
            rules_block = """- statement 必須是單一合法 JSON object 字串；不可輸出 JSON 以外的前後文。
    - statement JSON 結構必須為：{"review_summary":"...","pair_reviews":[...]}。
    - review_summary 用 1-3 句說明整批標註品質是否有系統性偏誤。
    - pair_reviews 必須逐筆涵蓋每個 [PAIR-xxx]；每筆都要有：id、proposed_label、confidence、reason。
    - reason 必須以 Modeler 角度撰寫成完整審查意見：說明你的獨立判斷依據，並至少指出資料結構、狀態轉移、事件流程、責任邊界、Use Case/Class/Sequence 影響中的一種；不要只寫一般語義判斷。
    - 你的任務不是提出新需求，而是再審查目前的 Conflict/Neutral 標籤是否合理。
    - 只有在兩項需求在資料結構、狀態轉移、事件流程或責任邊界上無法同時成立時，才支持 Conflict。
    - 只有在兩項需求可明確判定為不衝突、不重複，且沒有直接語義關係時，才支持 Neutral。
    - 若兩項需求描述同一功能範圍、同一流程、同一資料處理或同一輸出行為，即表示存在直接語義關係；不能僅因兩者可共存就判為 Neutral。
    - 若一項需求是另一項的子集、細化、補充步驟或同流程的相鄰行為，不能直接判為 Neutral。
    - 若只是流程未定、資料欄位未補齊、責任分工未明，不能因看不出衝突就直接支持 Neutral。
    - 若支持 Conflict，必須指出模型層的互斥點；若支持 Neutral，必須說明為何兩項需求既不衝突、也不重複，且無直接語義關係。
    - 不要跳到技術實作細節。
    - 此會議不提出 open_questions；資訊不足時請在 reason 中說明不確定性，open_questions 必須輸出空陣列。
    - 不可用 JSON-like 條列或文字摘要取代合法 JSON。"""
        if topic_id.startswith("ELICIT-"):
            stop_phrase = (
                "I have gathered enough information"
                if current_output_language() == "en"
                else "我已蒐集足夠資訊"
            )
            elicitation_hint = """# ELICIT Requirement Interview（Modeler）
- 你正在參與實務需求訪談，角色是需求建模者。
- 這是同一場會議的接續發言，不是自由提問；你的問題必須承接目前需求理解、前面 agent 發言、user 已回答內容與訪談記憶。
- 你必須遵守「本輪你的 action」：ask_user/supplement_question 才能問 user；review_only 只能審查目前理解，不可提問；propose_finish 只能輸出固定停止句。
- 不要重複問已確認、已拒絕、user 說不在意、或已被記錄成需求的內容。
- 你的角色邊界是使用者實際流程：怎麼開始、輸入、選擇、產生、查看結果、判斷任務完成，以及流程中的判斷點、例外情況與人工介入。
- 不要替 Analyst 問需求價值、內容優先級或成功標準；不要替 Expert 問可信度、合規或外部限制，除非它直接影響使用流程是否成立。
- 請用 user 能回答的需求訪談語言，不要要求使用者理解 UML、類別、狀態機或技術實作。
- 前半段請先補足主要使用流程，不要把會議變成流程細節審查；只有當細節會直接改變主要流程、任務完成方式或需求成立性時才追問。
- 若本輪已有其他 agent 發言，請先判斷前面問題是否已覆蓋 Modeler 關注點；若已覆蓋，不要換句話重問，請提出更精準的下一層追問，或在資訊足夠時提出收束。
- 若目前流程、操作與例外理解已足夠，可以提出收束；停止句只代表提議收束，系統會再交由 Analyst / Expert / Modeler 三方投票決定是否真的結束。"""
            task_block = (
                "請以需求建模者身分依本輪 action 發言。若 action 是 ask_user 或 supplement_question，先用 1 句重述目前理解或缺口，再輸出對 user 的一個主問題（總長 2-4 句）；"
                "若 action 是 review_only，請只輸出簡短審查意見，不要向 user 提問；"
                "若你判斷目前已蒐集到足夠資訊、可以收束本輪需求挖掘，則 statement 請只輸出以下固定句"
                f"（勿加引號、勿改寫、勿額外說明）：{stop_phrase}"
            )
            rules_block = f"""- 只有在目前需求理解已足夠，且依 Modeler 角色沒有關鍵流程缺口時，才可輸出停止句：{stop_phrase}
- 輸出停止句不是單方結束會議，只是進入三方收束投票。
- 若本輪 action 是 propose_finish，statement 必須只輸出停止句：{stop_phrase}
- 若本輪 action 是 review_only，不可向 user 提問，也不可輸出問句。
- 若本輪 action 是 ask_user 或 supplement_question，只能問 1 個主問題，不可合併多題。
- 問題必須可回答、可抽取、可直接轉成 requirement。
- 問題應以 probe 為主，直接詢問 user 的偏好、期待、需要、判斷標準或工作方式；避免用「目前不清楚 / it is unclear / could you clarify」作為主要問法。
- 提問前必須避開 `closed_topics` 與 `do_not_repeat`；不要重問 user 已回答、已說不在意、或已表示 covered 的流程/互動方向。
- 避免使用「還有什麼需求」「請多說一點」等泛問。
- 提問應承接目前理解，避免孤立訪談題。
- 若問題得到回答，應能讓 Analyst 當場產生或修正一條 requirement。
- open_questions 請輸出空陣列。"""
        suggested_next_action_json = ""
        if allow_suggested_next_action:
            suggested_next_action_json = """,
    "suggested_next_action": {
        "type": "direct_clarification | new_topic",
        "reason": "為何建議會後安排這一步",
        "target_ids": ["可選，相關 requirement/conflict/topic id"],
        "urgency": "low | medium | high"
    }"""
        return f"""{topic_text}
    {prev_text}
    {snapshot_text}
    {recent_ask_history_text}
    {elicitation_memory_text}
    {my_action_text}
    {skill_section}
    {tool_hint}
    {elicitation_hint}

    # 任務
    {task_block}

    # 規則
    {rules_block}

    # 輸出 JSON
    {{{{
    "statement": "針對此議題的完整發言內容",
    "open_questions": [{{{{"to": "目標 agent 名稱", "question": "問題"}}}}]{suggested_next_action_json}
    }}}}"""
