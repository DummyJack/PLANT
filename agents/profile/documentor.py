import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Any, Optional
from agents.base import BaseAgent

_TYPE_DIR = Path(__file__).resolve().parent.parent / "type"
with open(_TYPE_DIR / "srs_section_hints.json", "r", encoding="utf-8") as _f:
    SRS_SECTION_HINTS = json.load(_f)


class DocumentorAgent(BaseAgent):
    name = "documentor"

    system_prompt = """你是軟體需求規格書撰寫專家，負責撰寫 SRS 文件。

核心原則：
1. 結構一致 — SRS 文件結構必須符合 spec 範本的章節要求
2. 內容一致 — SRS 中的需求描述必須與需求規格一致
3. 完整性 — 不遺漏任何需求項目
4. 忠實記錄 — 只整理已有資料，禁止添加資料中不存在的需求或決策"""

    def __init__(self, model, store, tools: Optional[list] = None, registry=None):
        super().__init__(model, tools=tools, registry=registry)
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

    def generate_srs(self, artifact: Dict[str, Any], srs_template: List[Dict]) -> Dict[str, Any]:
        """Step F2: 產出 SRS Final（JSON + Markdown）"""
        artifact_text = json.dumps({
            "rough_idea": artifact.get("rough_idea", ""),
            "scope": artifact.get("scope", {}),
            "stakeholders": artifact.get("stakeholders", []),
            "requirements": artifact.get("requirements", []),
            "conflicts": artifact.get("conflicts", []),
            "decisions": artifact.get("decisions", []),
            "system_models": artifact.get("system_models", {}),
            "glossary": artifact.get("glossary", []),
            "assumptions": artifact.get("assumptions", []),
        }, ensure_ascii=False, indent=2)

        def generate_one_section(idx: int, section_template: Dict) -> tuple:
            section_name = section_template.get("section", "")
            hint = SRS_SECTION_HINTS.get(section_name, "")
            section_template_text = json.dumps(section_template, ensure_ascii=False, indent=2)
            user_prompt = f"""# 任務
根據需求資料產生 SRS 的「{section_name}」章節。

# 提示
{hint}

# 需求資料
{artifact_text}

# 約束
- 嚴格遵循模板結構
- 禁止添加資料中不存在的需求
- 若無相關資料，填寫「待補充」

# 輸出 JSON（只輸出此章節）
{section_template_text}"""
            try:
                messages = self.build_direct_messages(user_prompt)
                section_result = self.model.chat_json(messages)
                return (idx, section_result)
            except Exception as e:
                self.logger.warning(f"  SRS 章節 {section_name} 生成失敗: {e}，使用空模板")
                return (idx, section_template)

        max_workers = min(len(srs_template), 6)
        results_by_idx = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(generate_one_section, i, st): i
                for i, st in enumerate(srs_template)
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    i, section_result = future.result()
                    results_by_idx[i] = section_result
                    self.logger.info(f"  生成 SRS 章節: {srs_template[i].get('section', '')}")
                except Exception as e:
                    self.logger.warning(f"  SRS 章節並行生成失敗: {e}")
                    results_by_idx[idx] = srs_template[idx]

        generated_sections = [results_by_idx[i] for i in range(len(srs_template))]
        srs_json = {"srs": generated_sections}

        srs_md = self.generate_srs_markdown(srs_json)
        return srs_json, srs_md

    @staticmethod
    def strip_internal_req_id(text: str) -> str:
        """移除內容開頭的內部需求編號（R-01:、R-C01: 等），SRS 對外只顯示 SR-xx"""
        if not text or not isinstance(text, str):
            return text
        return re.sub(r"^R-(?:C?\d+):\s*", "", text.strip()).strip() or text

    def format_content_item(self, item: Any) -> str:
        """將單一 content 項目轉成 Markdown 一行：支援 dict（id+content/description）或字串"""
        if isinstance(item, dict):
            mid = item.get("id", "")
            text = item.get("content", item.get("description", ""))
            if mid and str(mid).startswith("SR-") and text:
                text = self.strip_internal_req_id(str(text))
                return f"- {mid}: {text}"
            if mid and text:
                return f"- {mid}: {text}"
            if text:
                return f"- {text}"
            return "- " + str(item)
        return f"- {item}"

    def render_section_content(self, section_content: Any) -> str:
        """將章節 content（dict / list / str）轉成 Markdown 片段"""
        md = ""
        if isinstance(section_content, dict):
            for key, value in section_content.items():
                if not value:
                    continue
                label = key.replace("_", " ").title()
                if isinstance(value, str):
                    md += f"**{label}**: {value}\n\n"
                elif isinstance(value, list):
                    md += f"**{label}**\n\n"
                    for v in value:
                        md += f"- {v}\n"
                    md += "\n"
        elif isinstance(section_content, list):
            if section_content and isinstance(section_content[0], dict):
                for item in section_content:
                    sub_id = item.get("id", item.get("stakeholder_name", ""))
                    md += f"### {sub_id}\n\n"
                    if item.get("plantuml"):
                        md += f"```plantuml\n{item['plantuml']}\n```\n\n"
                    for key, value in item.items():
                        if key in ("id", "plantuml"):
                            continue
                        if key == "stakeholder_name" and value == sub_id:
                            continue
                        if isinstance(value, str) and value:
                            md += f"{value}\n\n"
                        elif isinstance(value, list):
                            for v in value:
                                md += f"- {v}\n"
                            md += "\n"
            else:
                for item in section_content:
                    md += self.format_content_item(item) + "\n"
                md += "\n"
        elif isinstance(section_content, str) and section_content:
            md += f"{section_content}\n\n"
        return md

    def generate_srs_markdown(self, srs_data: Dict[str, Any]) -> str:
        md = "# Software Requirements Specification (SRS)\n\n"

        def process_subsection(subsection, level=3):
            nonlocal md
            sub_id = subsection.get("id", "")
            md += f"{'#' * level} {sub_id}\n\n"
            if subsection.get("plantuml"):
                md += f"```plantuml\n{subsection['plantuml']}\n```\n\n"
            content = subsection.get("content", "")
            if isinstance(content, list):
                for item in content:
                    md += self.format_content_item(item) + "\n"
                md += "\n"
            elif isinstance(content, str) and content:
                md += f"{content}\n\n"
            for nested in subsection.get("subsection", []):
                process_subsection(nested, level + 1)

        for section_data in srs_data.get("srs", []):
            md += f"## {section_data.get('section', '')}\n\n"

            section_content = section_data.get("content", None)
            if section_content is not None:
                md += self.render_section_content(section_content)

            for subsection in section_data.get("subsection", []):
                process_subsection(subsection)

        return md

    @staticmethod
    def strip_code_fences(text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("```"):
            first_newline = stripped.find("\n")
            if first_newline != -1:
                stripped = stripped[first_newline + 1:]
            if stripped.endswith("```"):
                stripped = stripped[:-3]
        return stripped.strip()
