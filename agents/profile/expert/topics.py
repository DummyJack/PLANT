# Expert topic logic: propose domain issues and build expert meeting responses.
import json
from typing import Any, Dict, List, Optional

from agents.base import expert_fallback_viewpoint
from utils.language import current_output_language


class ExpertTopics:
    def propose_topics(
        self,
        artifact: Dict[str, Any],
        *,
        round_num: int,
        max_items: int = 2,
    ) -> List[Dict]:
        proposals: List[Dict] = []
        research = ((artifact.get("feedback") or {}).get("domain_research") or {})
        for dr in research.get("binding_obligations", []) or []:
            text = (dr.get("text") or "").strip()
            if not text:
                continue
            rid = (dr.get("id") or "").strip()
            proposals.append(
                {
                    "title": text,
                    "description": text,
                    "category": "new_requirement",
                    "participants": ["expert", "analyst", "user", "modeler"],
                    "discussion_mode": "sequential",
                    "speaking_order": ["expert", "analyst", "user", "modeler"],
                    "source_ids": [rid] if rid else [],
                    "priority_hint": "high",
                    "impact_level": "high",
                    "why_now": "此議題涉及明確外部義務或具約束力條件，值得由會議確認其適用範圍與需求影響。",
                    "proposed_by": "expert",
                    "round": round_num,
                }
            )

        for oq in artifact.get("open_questions", []):
            if oq.get("status") == "answered":
                continue
            if (oq.get("type") or "") != "compliance_risk":
                continue
            proposals.append(
                {
                    "title": "合規風險開放問題釐清",
                    "description": (oq.get("question") or "").strip(),
                    "category": "open_question",
                    "participants": ["expert", "analyst", "user"],
                    "discussion_mode": "simultaneous",
                    "speaking_order": ["expert", "analyst", "user"],
                    "source_ids": [],
                    "priority_hint": "high",
                    "impact_level": "high",
                    "why_now": "合規風險未釐清會影響需求可行性。",
                    "proposed_by": "expert",
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
            prev_text = "\n前面的發言:\n" + "\n\n".join(parts)

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
        my_action = agent_actions.get("expert") if isinstance(agent_actions.get("expert"), dict) else {}
        if my_action:
            my_action_text = (
                "\n# 本輪你的 action\n"
                + json.dumps(my_action, ensure_ascii=False, indent=2)
            )

        skill_section = ""
        skill_context = self.get_optional_skill_context(topic, artifact_snapshot)
        if skill_context:
            skill_section = f"\n# Skill 參考（本輪由 agent 自行判斷使用）\n{skill_context}\n"
        category = (topic.get("category") or "").strip()
        allow_suggested_next_action = (
            category != "conflict_discussion"
            and not topic_id.startswith("ELICIT-")
        )

        tool_hint = ""
        if self.tools:
            fp_line = ""
            if self.has_doc_reference_files():
                fp_line = (
                    "- file_parser：先 search_chunks → read_chunks 再綜合；只有確實需要全文時才 read_full。\n"
                )
            tool_hint = (
                "\n# 工具使用\n"
                "- 先用 artifact_query 查 requirements、conflicts、decisions、open_questions 等專案內部事實。\n"
                f"{fp_line}"
                "- web_search 只用來補外部法規、標準、最佳實務或官方文件，不可覆蓋 artifact 內已知事實。\n"
                "- 最後**必須**輸出下列 JSON。"
            )

        if category == "conflict_discussion":
            category_hint = """# 本議題特別要求（conflict_discussion）
    - 你的任務是逐筆再審查目前這批 Conflict/Neutral pairs，而不是重新定義需求。
    - 你必須先根據 requirement_a / requirement_b 原文獨立重判，並將重判結果填入 proposed_label。
    - statement 必須是單一合法 JSON object 字串；不可輸出 JSON 以外的前後文。
    - statement JSON 結構必須為：{"review_summary":"...","pair_reviews":[...]}。
    - pair_reviews 必須逐筆涵蓋每個 [PAIR-xxx]；每筆都要有：id、proposed_label、confidence、reason。
    - reason 必須以 Expert 角度撰寫成完整審查意見：說明你的獨立判斷依據，以及是否涉及外部規範、標準、合規限制、品質底線或風險。
    - 只有在外部規範、品質底線、權限或安全限制使兩項需求無法同時成立時，才支持 Conflict。
    - 只有在兩項需求可明確判定為不衝突、不重複，且沒有直接語義關係時，才支持 Neutral。
    - 若兩項需求描述同一功能範圍、同一流程、同一資料處理或同一輸出行為，即表示存在直接語義關係；不能僅因兩者可共存就判為 Neutral。
    - 若一項需求是另一項的子集、細化、補充步驟或同流程的相鄰行為，不能直接判為 Neutral。
    - 若只是一般 tradeoff、偏好差異、尚未補齊限制條件，或目前僅缺外部證據，不能因看不出衝突就直接支持 Neutral。
    - 請明確指出：是哪一條限制、法規、標準或品質邊界造成互斥；若支持 Neutral，請說明為何兩項需求既不衝突、也不重複，且無直接語義關係。
    - 此會議不提出 open_questions；資訊不足時請在 reason 中說明不確定性，open_questions 必須輸出空陣列。"""
        elif category == "tradeoff":
            category_hint = """# 本議題特別要求（tradeoff）
    - 優先說明不可同時滿足的限制、你最重視的評估準則，以及合規前提下可接受的折衷範圍。"""
        elif category == "open_question":
            category_hint = """# 本議題特別要求（open_question）
    - 優先回答目前能直接確認的事實與限制；若仍需補資料，明確指出缺口與最適合回答的角色。"""
        elif category == "new_requirement":
            category_hint = """# 本議題特別要求（new_requirement）
    - 優先說明此新增需求是否屬於法規義務、最佳實務或風險緩解措施，以及若納入會影響哪些既有邊界。"""
        else:
            category_hint = ""

        statement_contract = """# statement 結構要求
    - statement 雖然是自然語句，但內容必須至少涵蓋：立場或暫時結論、依據或情境、風險/限制/邊界、建議下一步。
    - statement 不得只表態，必須有依據。
    - statement 不得宣告最終決議已成立；你只能提出觀點、依據、風險與建議。"""

        open_question_contract = """# open_questions 規範
    - 只有在你無法根據目前資料合理完成判斷，且該問題確實應由其他角色回答時，才產生 open_questions。
    - 每一筆 open_question 只能問一件事，問題要具體、可回答。
    - 不得把建議、命令或最終結論偽裝成問題。
    - 若你自己可根據現有資料回答，就不要丟 open_questions。
    - 若沒有真正需要他人回答的問題，open_questions 請輸出空陣列。"""
        next_action_contract = ""
        if allow_suggested_next_action:
            next_action_contract = """# suggested_next_action 規範
    - 若你認為本議題討論結束後應由外層流程安排下一步，可額外提供 suggested_next_action。
    - suggested_next_action 只是會後建議，不會在會議中直接執行。
    - 建議格式：type、reason、target_ids、urgency。若無明確建議可省略或填 null。"""

        elicitation_hint = ""
        task_block = "請以領域專家身分發言，聚焦法規、標準、證據、限制與風險。"
        rules_block = """- statement 需包含：暫時結論、依據、風險/限制、建議下一步。
    - 若屬強制義務要明講；若只是最佳實務或待補證據也要明講。
    - 可引用 requirement id、conflict id、研究發現或來源線索。
    - 若資訊不足，明確指出 evidence gap；不要虛構法規或標準。
    - 不決定產品 scope、優先級或最終需求 wording。
    - 可用純文字表格或流程輔助；若使用，請放在程式碼區塊。"""
        if topic_id.startswith("ELICIT-"):
            stop_phrase = (
                "I have gathered enough information"
                if current_output_language() == "en"
                else "我已蒐集足夠資訊"
            )
            elicitation_hint = """# ELICIT Requirement Interview（Expert）
- 你正在參與實務需求訪談，角色是領域專家。
- 這是同一場會議的接續發言，不是自由提問；你的問題必須承接目前需求理解、前面 agent 發言、user 已回答內容與訪談記憶。
- 你必須遵守「本輪你的 action」：ask_user/supplement_question 才能問 user；review_only 只能審查目前理解，不可提問；propose_finish 只能輸出固定停止句。
- 不要重複問已確認、已拒絕、user 說不在意、或已被記錄成需求的內容。
- 你的角色邊界是需求是否成立、結果是否可信與可接受，以及是否存在會讓系統不能用、不能採用或使用者不能接受的限制。
- 不要替 Analyst 問功能內容、優先級或成功標準；不要替 Modeler 問一般操作流程，除非該流程直接影響需求是否成立或結果是否可信。
- 不要把會議帶成一般技術選型、法規或工程審查；只有限制會直接影響需求是否成立、結果是否可信或使用者能否接受時才追問。
- 前半段請先讓需求主幹成形，不要過早進入細節審查；只有當細節會直接改變需求成立性、結果可信度或使用者接受度時才追問。
- 若本輪已有其他 agent 發言，請先判斷前面問題是否已覆蓋 Expert 關注點；若已覆蓋，不要換句話重問，請提出更精準的下一層追問，或在資訊足夠時提出收束。
- 若目前沒有阻礙需求成立的關鍵限制缺口，可以提出收束；停止句只代表提議收束，系統會再交由 Analyst / Expert / Modeler 三方投票決定是否真的結束。"""
            task_block = (
                "請以領域專家身分依本輪 action 發言。若 action 是 ask_user 或 supplement_question，先用 1 句重述目前理解或缺口，再輸出對 user 的一個主問題（總長 2-4 句）；"
                "若 action 是 review_only，請只輸出簡短審查意見，不要向 user 提問；"
                "若你判斷目前已蒐集到足夠資訊、可以收束本輪需求挖掘，則 statement 請只輸出以下固定句"
                f"（勿加引號、勿改寫、勿額外說明）：{stop_phrase}"
            )
            rules_block = f"""- 只有在目前需求理解已足夠，且依 Expert 角色沒有關鍵限制缺口時，才可輸出停止句：{stop_phrase}
- 輸出停止句不是單方結束會議，只是進入三方收束投票。
- 若本輪 action 是 propose_finish，statement 必須只輸出停止句：{stop_phrase}
- 若本輪 action 是 review_only，不可向 user 提問，也不可輸出問句。
- 若本輪 action 是 ask_user 或 supplement_question，只能問 1 個主問題，不可合併多題。
- 問題必須可回答、可抽取、可直接轉成 requirement。
- 問題應以 probe 為主，直接詢問 user 的偏好、期待、需要、判斷標準或工作方式；避免用「目前不清楚 / it is unclear / could you clarify」作為主要問法。
- 提問前必須避開 `closed_topics` 與 `do_not_repeat`；不要重問 user 已回答、已說不在意、或已表示 covered 的限制/資料來源方向。
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
    {category_hint}
    {elicitation_hint}

    {statement_contract}

    {open_question_contract}

    {next_action_contract}

    # 任務
    {task_block}

    # 規則
    {rules_block}

    # 輸出 JSON
    {{{{
    "statement": "針對此議題的完整發言內容",
    "open_questions": [{{{{"to": "目標 agent 名稱", "question": "問題"}}}}]{suggested_next_action_json}
    }}}}"""
