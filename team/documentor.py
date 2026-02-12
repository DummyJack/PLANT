import json

from typing import Dict, List, Any, Optional

from agents.base import BaseAgent
from agents.memory import Memory


class DocumentorAgent(BaseAgent):
    """文件生成 Agent — Reflection + Agent Communication (Analyst)"""

    name = "documentor"

    system_prompt = """你是軟體需求規格書撰寫專家（Documentor Agent），負責撰寫符合 IEEE 29148 標準的 SRS 文件。

核心原則：
1. IEEE 29148 合規 — 文件結構必須符合 IEEE 29148 標準章節要求
2. 一致性 — SRS 中的需求描述必須與需求草稿和 UML 模型一致
4. 完整性 — 不遺漏需求草稿中的任何需求項目
5. 忠實記錄 — 只整理已有資料，禁止添加資料中不存在的需求或決策"""

    reflection_criteria = "SRS 文件必須涵蓋需求草稿中所有需求項目，格式符合 IEEE 29148 標準。"

    def __init__(self, model, store, tools: Optional[list] = None,
                 memory: Optional[Memory] = None, registry=None):
        super().__init__(model, tools=tools, memory=memory, registry=registry)
        self.store = store

    def generate_design_rationale(self, mom_data: Dict[str, Any]) -> str:
        extracted_data = self.extract_dr_data(mom_data)
        mom_json_str = json.dumps(extracted_data, ensure_ascii=False, indent=2)

        user_prompt = f"""# 任務
根據以下會議記錄資料，整理 Design Rationale 文件。

# 資料
{mom_json_str}

# 整理結構
## 1. 決策理由 — 從 conflict_resolutions 提取每個衝突的最終決策及其理由
## 2. 方案取捨過程 — 從 options 提取曾考慮的方案及選擇/放棄原因
## 3. 替代方案 — 未採用的方案及其優缺點
## 4. 依據與參考 — 從 feedback 提取引用的法規、標準、文件

# 約束
- 只整理已有資料，禁止推測或添加不存在的決策
- 若某個章節沒有對應資料，標註「本輪無相關資料」
- 以 Markdown 格式輸出"""

        self.memory.add("user", "生成 Design Rationale")
        messages = self.build_direct_messages(user_prompt)
        dr_content = self.model.chat(messages)
        self.memory.add("assistant", "已生成 Design Rationale")
        return dr_content

    def extract_dr_data(self, mom_data: Dict[str, Any]) -> Dict[str, Any]:
        extracted = {"feedback": [], "options": [], "conflict_resolutions": []}

        for round_data in mom_data.get("rounds", []):
            if "conflict_resolutions" in round_data:
                extracted["conflict_resolutions"].extend(round_data["conflict_resolutions"])

            for stage in round_data.get("stages", []):
                outputs = stage.get("outputs", {})
                if "feedback" in outputs:
                    extracted["feedback"].extend(outputs["feedback"])
                if "decision_options" in outputs:
                    extracted["options"].extend(outputs["decision_options"])

        return extracted

    def summarize_uml(self, uml: Dict[str, Any]) -> str:
        """將 UML 模型摘要化，只保留 AST 結構，不傳完整 PlantUML 原碼"""
        if not uml:
            return "無 UML 模型"

        summary_parts = []

        # AST 結構
        ast = uml.get("ast", {})
        components = ast.get("components", [])
        relationships = ast.get("relationships", [])

        if components:
            summary_parts.append("# 系統元件")
            for c in components:
                attrs = ", ".join(c.get("attributes", [])[:5])
                methods = ", ".join(c.get("methods", [])[:5])
                summary_parts.append(f"- {c.get('id', '')}: {c.get('name', '')} ({c.get('type', '')})")
                if attrs:
                    summary_parts.append(f"  屬性: {attrs}")
                if methods:
                    summary_parts.append(f"  方法: {methods}")

        if relationships:
            summary_parts.append("\n# 元件關係")
            for r in relationships:
                summary_parts.append(f"- {r.get('from', '')} → {r.get('to', '')} ({r.get('type', '')}): {r.get('description', '')}")

        # 圖表清單（只列出名稱和類型）
        models = uml.get("models", [])
        if models:
            summary_parts.append("\n# 圖表清單")
            for m in models:
                summary_parts.append(f"- {m.get('name', '')} ({m.get('type', '')})")

        return "\n".join(summary_parts) if summary_parts else "無 UML 模型"

    # 每個 SRS 章節對應的 draft 章節和額外資料來源
    SRS_SECTION_MAP = {
        "1. Introduction": {
            "draft_sections": ["1. System Overview", "3. System Stakeholders"],
            "hint": "從 System Overview 撰寫 Purpose、Scope、Product overview，從 Stakeholders 撰寫 User characteristics。",
        },
        "2. References": {
            "draft_sections": [],
            "hint": "列出所有對本 SRS 具有約束力或解釋作用的外部文件與標準。若無相關參考文件，標註「目前無外部參考文件」。",
            "use_uml": False,
        },
        "3. Requirements": {
            "draft_sections": ["2. Requirement Engineering", "5. Functional Requirements", "6. Non-Functional Requirements"],
            "hint": (
                "從 Functional Requirements 產生 3.1 Functions（FR-xx），"
                "從 Non-Functional Requirements 產生 3.2-3.7 各類需求（PR/UR/IR/LDR 等）。"
            ),
        },
        "4. Verification": {
            "draft_sections": ["5. Functional Requirements", "6. Non-Functional Requirements"],
            "hint": "為第 3 章的每個需求說明驗證方法（測試 / 檢查 / 分析 / 演示），確保所有需求皆可驗證。",
            "use_uml": False,
        },
        "5. Appendices": {
            "draft_sections": [],
            "hint": "將 UML 模型清單附入附錄。",
            "use_uml": True,
        },
    }

    def generate_srs_json(self, draft: Dict[str, Any], uml: Dict[str, Any],
                          ieee_template: List[Dict]) -> Dict[str, Any]:
        uml_summary = self.summarize_uml(uml)

        # 預先拆分 draft 的各章節文字
        draft_section_texts = {}
        for section_data in draft.get("draft", []):
            section_name = section_data.get("section", "")
            draft_section_texts[section_name] = json.dumps(section_data, ensure_ascii=False, indent=2)

        generated_sections = []

        for section_template in ieee_template:
            section_name = section_template.get("section", "")
            self.logger.info(f"  生成 SRS 章節: {section_name}")

            section_config = self.SRS_SECTION_MAP.get(section_name, {})
            hint = section_config.get("hint", "")
            relevant_draft_sections = section_config.get("draft_sections", [])
            use_uml = section_config.get("use_uml", False)

            # 組裝該章節所需的 draft 資料
            draft_context_parts = []
            for ds_name in relevant_draft_sections:
                if ds_name in draft_section_texts:
                    draft_context_parts.append(draft_section_texts[ds_name])
            draft_context = "\n\n".join(draft_context_parts) if draft_context_parts else "（此章節無對應的草稿資料）"

            section_template_text = json.dumps(section_template, ensure_ascii=False, indent=2)

            user_prompt = f"""# 任務
根據需求草稿產生 SRS 的「{section_name}」章節，須符合 IEEE 29148 標準。

# 提示
{hint}

# 相關草稿資料
{draft_context}

# 約束
- 嚴格遵循模板結構
- 禁止添加草稿中不存在的需求
- 若無相關資料，填寫「待補充」

# 輸出 JSON（只輸出此章節）
{section_template_text}"""

            try:
                section_result = self.generate_with_reflection(user_prompt)
                generated_sections.append(section_result)
            except Exception as e:
                self.logger.warning(f"  SRS 章節 {section_name} 生成失敗: {e}，使用空模板")
                generated_sections.append(section_template)

        srs = {"ieee_29148": generated_sections}
        self.memory.add("assistant", f"已生成 SRS 文件（{len(generated_sections)} 章節）")
        return srs
