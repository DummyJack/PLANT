import json

from typing import Dict, List, Any, Optional
from agents.base import BaseAgent
from agents.memory import Memory


class DocumentorAgent(BaseAgent):
    name = "documentor"

    system_prompt = """你是軟體需求規格書撰寫專家，負責撰寫 SRS 文件。

核心原則：
1. 結構一致 — SRS 文件結構必須符合 spec 範本的章節要求
2. 內容一致 — SRS 中的需求描述必須與需求規格和 UML 模型一致
3. 完整性 — 不遺漏需求規格中的任何需求項目
4. 忠實記錄 — 只整理已有資料，禁止添加資料中不存在的需求或決策"""

    reflection_criteria = "SRS 文件必須涵蓋需求規格中所有需求項目，格式符合 spec 範本結構。"

    def __init__(self, model, store, tools: Optional[list] = None,
                 memory: Optional[Memory] = None, registry=None):
        super().__init__(model, tools=tools, memory=memory, registry=registry)
        self.store = store

    def generate_design_rationale(self, mom_data: Dict[str, Any]) -> str:
        extracted_data = self.extract_dr_data(mom_data)
        mom_json_str = json.dumps(extracted_data, ensure_ascii=False, indent=2)

        user_prompt = f"""# 任務
根據以下會議記錄資料，整理出 Design Rationale

# 資料
{mom_json_str}

# 整理結構
## 決策理由 — 提取每個議題的最終決策及其理由，包含人類裁決和 agent 共識
## 替代方案 — 討論中提出但未採用的方案
## 依據與參考 — 包含：(1) 專家 feedback 引用的法規、標準、文件 (2) 人類裁決的決策依據 (3) agent 共識的推理過程

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
        extracted = {"rounds": []}

        for round_data in mom_data.get("rounds", []):
            round_entry = {
                "round": round_data.get("round", 0),
                "stages": [],
                "meetings": [],
            }

            # 第一輪的 stages
            for stage in round_data.get("stages", []):
                stage_entry = {
                    "stage": stage.get("stage", ""),
                    "agent": stage.get("agent", ""),
                    "description": stage.get("description", ""),
                }
                outputs = stage.get("outputs", {})
                if "feedback" in outputs:
                    stage_entry["feedback"] = outputs["feedback"]
                if "analyse" in outputs:
                    stage_entry["analyse_count"] = len(outputs["analyse"])
                if "report" in outputs:
                    stage_entry["report"] = outputs["report"]
                round_entry["stages"].append(stage_entry)

            # 第二輪的 meetings
            for meeting in round_data.get("meetings", []):
                resolution = meeting.get("resolution", {})
                round_entry["meetings"].append({
                    "topic": meeting.get("topic", {}),
                    "contributions": meeting.get("contributions", []),
                    "resolution": resolution,
                })

            extracted["rounds"].append(round_entry)

        return extracted

    # 每個 SRS 章節的提示
    SRS_SECTION_HINTS = {
        "1. System Overview": "整理系統概述，包含目的、範圍、產品概觀。",
        "2. Requirement Engineering": "整理使用者需求和系統需求，確保需求編號一致。",
        "3. System Stakeholders": "列出利害關係人，整理各自的關注點和需求。",
        "4. Conflicting Requirements": "整理衝突需求，包含解決方案和決策結果。",
        "5. Functional Requirements": "整理功能性需求，確保每個需求有明確的描述。",
        "6. Non-Functional Requirements": "整理非功能性需求（效能、安全、可用性等）。",
        "7. Appendices": "整理附錄內容，包含 UML 模型圖表（PlantUML）和系統元件結構。",
    }

    def generate_srs_json(self, spec_md: str, srs_template: List[Dict]) -> Dict[str, Any]:
        generated_sections = []

        for section_template in srs_template:
            section_name = section_template.get("section", "")
            self.logger.info(f"  生成 SRS 章節: {section_name}")

            hint = self.SRS_SECTION_HINTS.get(section_name, "")
            section_template_text = json.dumps(section_template, ensure_ascii=False, indent=2)

            user_prompt = f"""# 任務
根據需求規格產生 SRS 的「{section_name}」章節。

# 提示
{hint}

# 需求規格（完整 Markdown，含 UML 附錄）
{spec_md}

# 約束
- 嚴格遵循模板結構
- 禁止添加規格中不存在的需求
- 若無相關資料，填寫「待補充」

# 輸出 JSON（只輸出此章節）
{section_template_text}"""

            try:
                section_result = self.generate_with_reflection(user_prompt)
                generated_sections.append(section_result)
            except Exception as e:
                self.logger.warning(f"  SRS 章節 {section_name} 生成失敗: {e}，使用空模板")
                generated_sections.append(section_template)

        srs = {"srs": generated_sections}
        self.memory.add("assistant", f"已生成 SRS 文件（{len(generated_sections)} 章節）")
        return srs
