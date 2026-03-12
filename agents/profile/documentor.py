import json
import re
from typing import Dict, Any, Optional
from agents.base import BaseAgent


class DocumentorAgent(BaseAgent):
    name = "documentor"

    system_prompt = """你是一個專業的軟體需求規格書撰寫專家，負責撰寫 SRS 文件。

核心原則（依序遵守）：
1. 禁止硬掰 — 只轉寫與整理「需求草稿與 artifact」中已有的內容；不得憑空新增需求、資料模型、介面規格、技術選型或範本佔位（如 [Name]、YYYY-MM-DD、[Describe...]）。若某章節在來源中無對應資料，該節直接標註「待補」或「本文件無相關資料」，勿填寫猜測或範例。
2. 缺料就標待補 — 對資訊缺口、假設與待確認項目做明確標示；區分「已決議」與「討論中／待確認」。
3. 結構一致 — SRS 章節結構須符合 spec 範本，且章節編號從 1 開始依序撰寫（1. Introduction, 2. Overall Description, 3. …, 勿從 3 開始）。
4. 內容一致 — SRS 中的需求描述必須與需求規格一致，不遺漏既有需求，也不新增草稿沒有的項目。
5. 忠實記錄 — 只整理已有資料，禁止添加資料中不存在的需求或決策。"""

    def __init__(self, model, store, tools: Optional[list] = None, registry=None):
        super().__init__(
            model,
            tools=tools,
            registry=registry,
            skill_names=["srs-generation"],
        )
        self.store = store

    def generate_design_rationale(self, artifact: Dict[str, Any]) -> str:
        """Step F1: 產生 Design Rationale（Markdown）"""
        context = {
            "decisions": artifact.get("decisions", []),
            "conflicts": artifact.get("conflicts", []),
            "discussions": artifact.get("discussions", []),
            "feedback": artifact.get("feedback", {}),
        }
        context_text = json.dumps(context, ensure_ascii=False, indent=2)

        user_prompt = f"""# 任務
根據以下討論記錄和決策資料，整理出設計緣由文件。

# 資料
{context_text}

# 整理結構（Markdown 格式）

提取每個議題的最終決策，每個決策包含：背景、選項、理由、依據與參考(專家引用的法規、標準、文件 or 人類裁決的決策依據 or agent 共識的推理過程)。

# 約束
- 只整理已有資料，禁止推測或添加不存在的決策
- 若某個章節沒有對應資料，標註「本輪無相關資料」
- 對資料不足但又影響判讀的內容，請明確標註「待確認」或「假設前提」
- 清楚區分「已決議」與「尚在討論中」內容，避免混寫
- 產出內容請使用繁體中文
- 以 Markdown 格式輸出"""

        messages = self.build_direct_messages(user_prompt)
        dr_md = self.model.chat(messages)
        dr_md = self.strip_code_fences(dr_md)
        return dr_md

    def generate_srs(self, artifact: Optional[Dict[str, Any]] = None) -> str:
        """Step F2: 以 store 中最新需求草稿為輸入，invoke srs-generation skill 產出正式 SRS（ISO 29148），回傳 SRS Markdown。"""
        latest_version = self.store.get_draft_version()
        if latest_version < 0:
            raise ValueError("尚無需求草稿，請先產生 draft 再生成 SRS")
        draft_md = self.store.load_draft(latest_version)
        if not draft_md:
            raise ValueError(f"無法載入草稿 draft_v{latest_version}.md")

        context = {
            "draft_version": latest_version,
            "draft_markdown": draft_md,
            "feedback": (artifact or {}).get("feedback", {}),
        }
        task = """依 srs-generation skill、範本與檢查清單，僅根據 Context 的**最新需求草稿**（draft_markdown）與 **feedback**（如有）產出正式 Software Requirements Specification（Markdown）。

強制規則（依序遵守）：
1. 禁止硬掰：只轉寫草稿與 Context 中已有的需求、範圍、約束與決策；不得憑空新增需求、資料模型、介面規格、技術選型或佔位符（如 [Name]、YYYY-MM-DD、[Describe...]）。若某章節在來源中無對應資料，該節直接標註「待補」或「本文件無相關資料」，勿填寫猜測或範例。
2. 缺料就標待補：對無來源的 References、Open Questions、Change Request 等表單，若無實際資料則標「待補」或省略該表，勿留範本佔位。
3. 章節編號從 1 開始：產出章節依序為 1. Introduction, 2. Overall Description, 3. …, 勿從 3 開始。

其他要求：以草稿為唯一輸入來源，忠實轉寫為符合 ISO/IEC/IEEE 29148；使用 FR-<MODULE>-<NNN>、NFR-<CATEGORY>-<NNN> 編號；產出須通過 skill 品質檢查清單。產出的 SRS 全文請使用繁體中文，需求編號格式維持英文。只輸出 SRS Markdown，勿包程式碼區塊。"""

        srs_md_full = self.invoke_skill("srs-generation", task, context=context)
        srs_md_full = self.strip_code_fences(srs_md_full)
        self.logger.info(
            f"  已依 srs-generation skill 由 draft_v{latest_version} 產生正式 SRS"
        )
        return self.strip_document_info_and_revision_history(srs_md_full)

    @staticmethod
    def strip_document_info_and_revision_history(md: str) -> str:
        """從 SRS Markdown 移除「Document Information」與「Revision History」區塊，供存成 srs.md 使用。"""
        if not md or not isinstance(md, str):
            return md
        # 支援章節從 1 開始：從 Document Information 刪到 ## 1. Introduction 或 ## 3. Introduction 之前
        for start_anchor in (r"\n## 1\. Introduction", r"\n## 3\. Introduction"):
            pattern = r"\n## (?:1\. )?Document Information\s.*?(?=" + start_anchor + r")"
            out = re.sub(pattern, "\n\n", md, flags=re.DOTALL)
            if out != md:
                return out.strip()
            pattern_alt = r"\n## Document Information\s.*?(?=" + start_anchor + r")"
            out = re.sub(pattern_alt, "\n\n", md, flags=re.DOTALL)
            if out != md:
                return out.strip()
        return md

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
