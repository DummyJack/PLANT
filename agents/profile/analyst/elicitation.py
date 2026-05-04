# Analyst elicitation logic: extract hidden requirement candidates from meeting turns.
import json
from typing import Any, Dict, List


class AnalystElicitation:
    def extract_elicitation_candidates(
        self,
        discussion_text: str,
        existing_ids: List[str],
        *,
        mode: str = "oracle",
        rough_idea: str = "",
    ) -> List[Dict[str, Any]]:
        """從隱性需求挖掘討論中提取候選需求（原始 JSON）。"""
        mode_name = str(mode or "oracle").strip().lower()
        if mode_name == "main_flow":
            rules = (
                "# 規則\n"
                "- 只從本輪 interviewer/user 對話中提取尚未被記錄的新需求候選\n"
                "- 只有 user signal 明確支持需求意圖時才提取；不得憑空新增功能、角色、外部系統或量化目標\n"
                "- 可消化 user 對情境、痛點、流程修正、例外處理、風險或驗收期待的回答，整理成清楚 requirement\n"
                "- 只提取與原始產品概念直接相關的需求；偏離產品概念的回答必須忽略\n"
                "- 每筆需含：text, type (FR/NFR/constraint), priority (must/should/could), "
                "source_stakeholders, source（引用討論中的原話或情境片段作為依據，不可編造）, "
                "rationale（一句話理由，基於討論內容）, "
                "verification_method (test/review/inspection), acceptance_criteria\n"
                "- acceptance_criteria 要可觀察、可驗收；不要只重述需求文字\n"
                "- 若 user 回答修正了既有理解，candidate text 應反映修正後的需求，而不是只摘錄 user 原話\n"
                "- 若只是 open question 或支持不足，不要硬轉成 candidate；若無新需求，回傳空陣列\n"
                "- 不要重複已有需求；若無法找到明確 source 引述，不得新增\n\n"
            )
        else:
            rules = (
                "# 規則\n"
                "- 只提取討論中明確提及、尚未被記錄，且與原始產品概念直接相關的新需求\n"
                "- 每筆需含：text, type (FR/NFR/constraint), priority (must/should/could), "
                "source_stakeholders, source（討論中的原話引述，作為來源憑證）, "
                "rationale（一句話理由）, "
                "verification_method (test/review/inspection), acceptance_criteria\n"
                "- acceptance_criteria 要可觀察、可驗收；不要只重述需求文字\n"
                "- 若只是 open question、支持不足、缺乏 source 引述或重複已有需求，不要輸出\n"
                "- 若無新需求，回傳空陣列\n\n"
            )
        prompt = (
            "你是需求分析師。以下是一場隱性需求挖掘會議的討論內容。"
            "請從中提取**尚未被記錄**的新需求候選。\n\n"
            f"# 原始產品概念（不可偏離）\n{rough_idea or '（未提供）'}\n\n"
            f"# 討論內容\n{discussion_text}\n\n"
            f"# 目前已有的需求 ID\n{json.dumps(sorted(existing_ids), ensure_ascii=False)}\n\n"
            f"# 模式\n{mode_name}\n\n"
            f"{rules}"
            "- 候選需求的 text、rationale 與 acceptance_criteria 必須能看出和原始產品概念的關聯；看不出關聯就不要輸出。\n"
            '# 輸出 JSON\n{"candidates": [...]}'
        )
        messages = self.build_direct_messages(prompt)
        data = self.chat_json(messages, action="elicitation_extract")
        raw = data.get("candidates", []) if isinstance(data, dict) else []
        return raw if isinstance(raw, list) else []
