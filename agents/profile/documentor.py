from typing import Dict, Any, Optional
from agents.base import BaseAgent
from utils import documentor_srs_body_lang, srs_title_instruction


class DocumentorAgent(BaseAgent):
    name = "documentor"

    system_prompt = """你是 SRS 撰寫專家，負責把既有需求草稿與 artifact 轉成正式文件。

規則：
1. requirement_change_candidates、pending_review、未回答 open_questions、未解 conflict 與未正式套用的變更，不得寫成已定案 requirement。
2. 你只根據最新 draft 與 artifact 轉寫，不自行補決策。
3. 文件結構需符合正式 SRS 範本，保留文件資訊、版本與修訂紀錄，章節編號從 1 開始連續。"""

    def __init__(
        self,
        model,
        store,
        tools: Optional[list] = None,
        registry=None,
        project_config=None,
    ):
        super().__init__(
            model,
            tools=tools,
            registry=registry,
            skill_names=["srs-generation"],
            project_config=project_config,
        )
        self.store = store

    def generate_srs(self, artifact: Optional[Dict[str, Any]] = None) -> str:
        """Step F2: 以 store 中最新需求草稿為輸入，invoke srs-generation skill 產出正式 SRS（ISO 29148），回傳 SRS Markdown。"""
        latest_version = self.store.get_draft_version()
        if latest_version < 0:
            raise ValueError("尚無需求草稿，請先產生 draft 再生成 SRS")
        draft_md = self.store.load_draft(latest_version)
        if not draft_md:
            raise ValueError(f"無法載入草稿 draft_v{latest_version}.md")

        artifact = artifact or {}
        scope = artifact.get("scope", {})
        rough_idea = artifact.get("rough_idea", "")
        decisions = artifact.get("decisions", [])
        context = {
            "draft_version": latest_version,
            "draft_markdown": draft_md,
            "rough_idea": rough_idea,
            "scope": scope,
            "stakeholders": artifact.get("stakeholders", []),
            "requirements": artifact.get("requirements", []),
            "conflicts": artifact.get("conflicts", []),
            "decisions": decisions,
            "open_questions": artifact.get("open_questions", []),
            "system_models": artifact.get("system_models", {}),
            "feedback": artifact.get("feedback", {}),
        }
        title_rule = srs_title_instruction()
        body_lang = documentor_srs_body_lang()
        task = f"""依 srs-generation skill、範本與檢查清單，根據 Context 的最新需求草稿與結構化資料產出正式 SRS（Markdown）。

正式文件要求：
- 必須保留正式 SRS 的前置章節：Document Information 與 Revision History。
- 章節結構至少完整涵蓋：Introduction、Overall Description、Functional Requirements、Non-Functional Requirements、Data Requirements、External Interface Requirements、Requirements Traceability Matrix、Appendix。
- 若某正式章節在來源不足時無法完整展開，請保留章節並以「待補」標示缺口；不要省略正式主章節。
- Functional Requirements 應寫成正式 requirement specification；每條 FR 應有 Description、Actors、Preconditions、Main Flow、Alternative Flows、Postconditions、Acceptance Criteria。
- Acceptance Criteria 應為可驗證條件，優先使用 Given/When/Then 或明確 pass/fail 條件。
- Non-Functional Requirements 應包含 Metric、Target、Measurement；若缺明確數值或門檻依據，標示「待補」，不得虛構。
- 文件語氣使用正式規格語言；強制要求用 shall，建議用 should，可選用 may；避免模糊形容詞。

嚴格來源規則（最重要）：
- SRS 的所有功能性需求必須且僅可來自 Context.requirements 與 Context.draft_markdown；不得自行新增、推測或編造任何需求。
- 非功能性需求的具體指標與目標值必須來自 Context.requirements（NFR 類）；若來源中無明確數值，該欄位標示「待補」，不得虛構數字。
- Context.decisions 中的會議決議必須反映到對應需求的細節中。
- Context.conflicts 中 label=Conflict 的衝突標為未解決；label=Neutral 的標為已解決。
- 需求溯源矩陣（RTM）僅在有上游 PRD 時才產出；無 PRD 時省略該章節，不得虛構 PRD ID。
- 參考資料表中的法規、文件只列 Context 中實際提及的來源；不得自行杜撰法規名稱或版本日期。
- 無來源資料的章節、表格或欄位，請標示「待補」或直接省略，不要留範本空殼，更不得填入虛構內容。

其他規則：
1. requirement_change_candidates、pending_review、未回答 open questions、未解 conflict 與未正式套用的變更，不得寫成已定案需求。
2. 標題格式：{title_rule}
3. 章節編號從 1 開始連續，不得跳號。
4. Context.requirements 中的每一條都必須出現在 SRS 中，不得遺漏。

{body_lang} 只輸出 SRS Markdown，勿包程式碼區塊。"""

        srs_md_full = self.invoke_skill("srs-generation", task, context=context)
        srs_md_full = self.strip_code_fences(srs_md_full)
        self.logger.info(
            f"  已依 srs-generation skill 由 draft_v{latest_version} 產生正式 SRS"
        )
        return srs_md_full.strip()

    @staticmethod
    def strip_code_fences(text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("```"):
            first_newline = stripped.find("\n")
            if first_newline != -1:
                stripped = stripped[first_newline + 1 :]
            if stripped.endswith("```"):
                stripped = stripped[:-3]
        return stripped.strip()
