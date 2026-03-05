import json
from typing import Dict, Any, Optional, Tuple
from agents.base import BaseAgent


class DocumentorAgent(BaseAgent):
    name = "documentor"

    system_prompt = """你是一個專業的軟體需求規格書撰寫專家，負責撰寫 SRS 文件。

核心原則：
1. 結構一致 — SRS 文件結構必須符合 spec 範本的章節要求
2. 內容一致 — SRS 中的需求描述必須與需求規格一致
3. 完整性 — 不遺漏任何需求項目
4. 忠實記錄 — 只整理已有資料，禁止添加資料中不存在的需求或決策"""

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
- 以 Markdown 格式輸出"""

        messages = self.build_direct_messages(user_prompt)
        dr_md = self.model.chat(messages)
        dr_md = self.strip_code_fences(dr_md)
        return dr_md

    def generate_srs(self, artifact: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        """Step F2: 以最新需求草稿為輸入，invoke srs-generation skill 產出正式 SRS（ISO 29148），回傳 (srs_json, srs_md)。"""
        latest_version = self.store.get_draft_version()
        if latest_version < 0:
            raise ValueError("尚無需求草稿，請先產生 draft 再生成 SRS")
        draft_md = self.store.load_draft(latest_version)
        if not draft_md:
            raise ValueError(f"無法載入草稿 draft_v{latest_version}.md")

        context = {
            "draft_version": latest_version,
            "draft_markdown": draft_md,
        }
        task = """依 srs-generation skill、範本與檢查清單，僅根據 Context 的**最新需求草稿**（draft_markdown）產出正式 Software Requirements Specification（Markdown）。
要求：以草稿為唯一輸入來源，忠實轉寫為符合 ISO/IEC/IEEE 29148；使用 FR-<MODULE>-<NNN>、NFR-<CATEGORY>-<NNN> 編號；產出須通過 skill 品質檢查清單。只輸出 SRS Markdown，勿包程式碼區塊。"""

        srs_md = self.invoke_skill("srs-generation", task, context=context)
        srs_md = self.strip_code_fences(srs_md)
        self.logger.info(
            f"  已依 srs-generation skill 由 draft_v{latest_version} 產生正式 SRS"
        )

        srs_json = {
            "srs": [
                {"section": "Software Requirements Specification", "content": srs_md}
            ],
            "source": "srs-generation-skill",
        }
        return srs_json, srs_md

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
