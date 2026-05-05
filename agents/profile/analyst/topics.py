# Analyst topic logic: propose decision issues and build analyst meeting responses.
import json
from typing import Any, Dict, List, Optional

from utils.language import current_output_language


class AnalystTopics:
    def propose_topics(
        self,
        artifact: Dict[str, Any],
        *,
        round_num: int,
        max_items: int = 3,
    ) -> List[Dict[str, Any]]:
        proposals: List[Dict[str, Any]] = []
        for c in artifact.get("conflicts", []):
            if not isinstance(c, dict):
                continue
            cid = (c.get("id") or "").strip()
            label = (c.get("label") or "").strip()
            if not cid or label != "Conflict":
                continue
            category = "conflict_discussion"
            title = f"{cid} 衝突解法協調"
            why_now = "目前仍為 Conflict，需會議協調可執行決策。"
            proposals.append(
                {
                    "title": title,
                    "description": (c.get("description") or "").strip(),
                    "category": category,
                    "participants": ["analyst", "expert", "modeler", "user"],
                    "discussion_mode": "sequential",
                    "speaking_order": ["analyst", "expert", "modeler", "user"],
                    "source_ids": [cid] + list(c.get("requirement_ids", []) or []),
                    "priority_hint": "high",
                    "impact_level": "high",
                    "why_now": why_now,
                    "requires_multi_party": True,
                    "blocks_decision": True,
                    "routing_preference": "formal_meeting",
                    "proposed_by": "analyst",
                    "round": round_num,
                }
            )

        for oq in artifact.get("open_questions", []):
            if oq.get("status") == "answered":
                continue
            q = (oq.get("question") or "").strip()
            if not q:
                continue
            src = str(oq.get("source_conflict_id") or "").strip()
            proposals.append(
                {
                    "title": "待回答開放問題釐清",
                    "description": q,
                    "category": "open_question",
                    "participants": ["analyst", "expert", "modeler", "user"],
                    "discussion_mode": "simultaneous",
                    "speaking_order": ["analyst", "expert", "modeler", "user"],
                    "source_ids": [src] if src else [],
                    "priority_hint": "high",
                    "impact_level": "medium",
                    "why_now": "開放問題未解，會影響本輪收斂品質。",
                    "requires_multi_party": False,
                    "blocks_decision": True,
                    "routing_preference": "direct_clarification",
                    "proposed_by": "analyst",
                    "round": round_num,
                }
            )

        return proposals[: max(1, max_items)]

    def get_resolution_options_for_topic(
        self, topic: Dict, artifact: Dict[str, Any]
    ) -> Optional[Dict]:
        """議題為 Conflict 協調時，依 conflict-analyzer 產出 resolution_options，供人類裁決使用。回傳格式同 Mediator.prepare_human_options：best_options、compromise。"""
        if topic.get("category") not in ("conflict_discussion",):
            return None
        if "conflict-analyzer" not in self.skill_names:
            return None
        source_ids = topic.get("source_ids") or []
        conflict_ids = [
            s
            for s in source_ids
            if isinstance(s, str)
            and (s.startswith("CF-") or s.startswith("CF-D") or s.startswith("NF-"))
        ]
        conflicts = artifact.get("conflicts", [])
        if conflict_ids:
            relevant = [c for c in conflicts if c.get("id") in conflict_ids]
        else:
            relevant = [c for c in conflicts if c.get("label") == "Conflict"]
        if not relevant:
            return None
        context = {
            "topic": topic,
            "conflicts": relevant,
            "requirements": artifact.get("requirements", []),
            "stakeholders": artifact.get("stakeholders", []),
        }
        task = """針對 Context 中的議題與對應 Conflict/Neutral，依 conflict-analyzer skill 產出解決方案選項。

只輸出一個 JSON 物件，須含：
- resolution_options：每筆含 option、strategy、description、pros、cons、recommendation
- recommended_resolution：建議方案摘要

勿輸出 Markdown 或其它文字。"""
        try:
            raw = self.invoke_skill("conflict-analyzer", task, context=context)
            data = self.parse_topic_response_json(raw)
        except Exception as e:
            self.logger.warning("resolution_options 生成失敗: %s", e)
            return None
        opts = data.get("resolution_options") or []
        recommended = (data.get("recommended_resolution") or "").strip()
        best_options = []
        for i, o in enumerate(opts[:3], 1):
            title = (o.get("strategy") or o.get("option") or "").strip()
            if o.get("option"):
                title = f"方案 {o.get('option')}: {title}"
            desc = (o.get("description") or "").strip()
            if o.get("pros") or o.get("cons"):
                parts = []
                if o.get("pros"):
                    pl = "優點："
                    parts.append(
                        pl
                        + (
                            ", ".join(o["pros"])
                            if isinstance(o["pros"], list)
                            else str(o["pros"])
                        )
                    )
                if o.get("cons"):
                    cl = "缺點："
                    parts.append(
                        cl
                        + (
                            ", ".join(o["cons"])
                            if isinstance(o["cons"], list)
                            else str(o["cons"])
                        )
                    )
                if parts:
                    desc = desc + "\n" + "\n".join(parts) if desc else "\n".join(parts)
            best_options.append(
                {
                    "id": i,
                    "title": title or f"方案 {i}",
                    "description": desc or "(無描述)",
                    "source": "analyst",
                }
            )
        compromise = None
        if recommended:
            c_title = "建議方案（Analyst）"
            c_rat = "依 conflict-analyzer 建議採用的解決方案"
            compromise = {
                "id": 4,
                "title": c_title,
                "description": recommended,
                "rationale": c_rat,
            }
        if not best_options and not compromise:
            return None
        return {"best_options": best_options, "compromise": compromise}

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
        my_action = agent_actions.get("analyst") if isinstance(agent_actions.get("analyst"), dict) else {}
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
            topic.get("category") != "conflict_discussion"
            and not topic_id.startswith("ELICIT-")
        )

        tool_hint = ""
        if self.tools:
            tool_hint = "\n# 工具使用\n- 最後**必須**輸出下列 JSON。"

        elicitation_hint = ""
        task_block = "請以需求分析師身分發言，聚焦需求定義、驗收邊界、風險與下一步。"
        rules_block = """- statement 需包含：結論、依據、風險/邊界、建議下一步。
- 依據優先引用 requirement id、conflict id、既有討論或議題描述。
- 保持中立；資訊不足時明確指出缺口，不可假設已確認。
- 不要講實作細節；決策分析與使用者確認不在此步完成。
- 若需要他人補資訊，才在 open_questions 中提出具體問題。
- open_questions 的 to 欄位只能用系統角色名：user、analyst、expert、modeler；禁止用利害關係人名稱。
- 可用純文字表格、流程或草圖輔助說明；若使用，請放在程式碼區塊。"""
        if allow_suggested_next_action:
            rules_block += "\n- 若你認為本議題討論結束後應由外層流程安排下一步，可額外提供 suggested_next_action；這只是建議，不會在會議中直接執行。"
        if topic.get("category") == "conflict_discussion":
            task_block = "請以需求分析師身分逐筆再審查目前這批 Conflict/Neutral pairs，先根據 requirement_a / requirement_b 原文獨立重判，並將重判結果填入 proposed_label。"
            rules_block = """- statement 必須是單一合法 JSON object 字串；不可輸出 JSON 以外的前後文。
- statement JSON 結構必須為：{"review_summary":"...","pair_reviews":[...]}。
- review_summary 用 1-3 句說明整批標註品質是否有系統性偏誤。
- pair_reviews 必須逐筆涵蓋每個 [PAIR-xxx]；每筆都要有：id、proposed_label、confidence、reason。
- reason 必須以 Analyst 角度撰寫成完整審查意見：說明你的獨立判斷依據，並說明需求語意、範圍、條件、互斥點或可驗證性；不要只重述兩句需求文字。
- 先只根據 requirement_a / requirement_b 原文獨立判斷 proposed_label；不要先順著既有標籤想理由。
- 只有在兩項需求無法同時成立、或一方成立會直接違反另一方時，才支持 Conflict。
- 只有在兩項需求可明確判定為不衝突、不重複，且沒有直接語義關係時，才支持 Neutral。
- 若兩項需求描述同一功能範圍、同一流程、同一資料處理或同一輸出行為，即表示存在直接語義關係；不能僅因兩者可共存就判為 Neutral。
- 若一項需求是另一項的子集、細化、補充步驟或同流程的相鄰行為，不能直接判為 Neutral。
- 若只是語意模糊、範圍未明、角色不同、情境不同、優先級不同或仍需補充條件，不能因看不出衝突就直接支持 Neutral。
- 若支持 Conflict，必須清楚指出互斥點；若支持 Neutral，必須清楚說明為何既不衝突、也不重複，且無直接語義關係。
- 不要跳到實作方案或最終決策。
- 此會議不提出 open_questions；資訊不足時請在 reason 中說明不確定性，open_questions 必須輸出空陣列。
- 不可用 JSON-like 條列或文字摘要取代合法 JSON。"""
        if topic_id.startswith("ELICIT-"):
            stop_phrase = (
                "I have gathered enough information"
                if current_output_language() == "en"
                else "我已蒐集足夠資訊"
            )
            elicitation_hint = """# ELICIT Requirement Interview（Analyst）
- 你正在參與實務需求訪談，角色是需求分析師。
- 這是同一場會議的接續發言，不是自由提問；你的問題必須承接目前需求理解、前面 agent 發言、user 已回答內容與訪談記憶。
- 你必須遵守「本輪你的 action」：ask_user/supplement_question 才能問 user；review_only 只能審查目前理解，不可提問；propose_finish 只能輸出固定停止句。
- 不要重複問已確認、已拒絕、user 說不在意、或已被記錄成需求的內容。
- 你的角色邊界是需求意圖、使用價值、內容優先級、呈現方式、must-have / nice-to-have、成功標準與最後確認目前理解是否正確。
- 不要替 Expert 問限制/合規/可信度問題；不要替 Modeler 問操作流程、狀態或例外細節，除非它直接影響需求意圖。
- 若本輪已有其他 agent 發言，請先判斷前面問題是否已覆蓋 Analyst 關注點；若已覆蓋，不要換句話重問，請提出更精準的下一層追問，或在資訊足夠時提出收束。
- 前半段請先補足需求主幹，不要過早進入細節審查；只有當細節會直接改變需求意圖、產出、使用價值或成功標準時才追問。
- 問題要能直接支援新增或修正 requirement；不要泛問「還有什麼需求」。
- 若目前理解已足夠清楚，可以提出收束；停止句只代表提議收束，系統會再交由 Analyst / Expert / Modeler 三方投票決定是否真的結束。"""
            task_block = (
                "請以需求分析師身分依本輪 action 發言。若 action 是 ask_user 或 supplement_question，先用 1 句重述目前理解或缺口，再輸出對 user 的一個主問題（總長 2-4 句）；"
                "若 action 是 review_only，請只輸出簡短審查意見，不要向 user 提問；"
                "若你判斷目前已蒐集到足夠資訊、可以收束本輪需求挖掘，則 statement 請只輸出以下固定句"
                f"（勿加引號、勿改寫、勿額外說明）：{stop_phrase}"
            )
            rules_block = f"""- 只有在 user 已確認目前理解沒有錯漏時，才可輸出停止句：{stop_phrase}
- 輸出停止句不是單方結束會議，只是進入三方收束投票。
- 若本輪 action 是 propose_finish，statement 必須只輸出停止句：{stop_phrase}
- 如果尚未明確做過收斂確認，不可停止，必須提出 1 個主問題。
- 若本輪 action 是 review_only，不可向 user 提問，也不可輸出問句。
- 若本輪 action 是 ask_user 或 supplement_question，只能問 1 個主問題，不可合併多題。
- 問題必須可回答、可抽取、可直接轉成 requirement。
- 問題應以 probe 為主，直接詢問 user 的偏好、期待、需要、判斷標準或工作方式；避免用「目前不清楚 / it is unclear / could you clarify」作為主要問法。
- 提問前必須避開 `closed_topics` 與 `do_not_repeat`；不要重問 user 已回答、已說不在意、或已表示 covered 的方向。
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
