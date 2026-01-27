from typing import Dict, List, Any
import json

class DocumentorAgent:
    """
    Documentor Agent: srs 產生代理
        - 依 mom.json 產出 Design Rationale (dr.md)
        - 依 spec.json + 29148.json 產出 srs.json 和 srs.md
    """
    
    def __init__(self, model):
        self.model = model
    
    def generate_design_rationale(self, mom_data: Dict[str, Any]) -> str:
        """
        根據 MoM 產生 Design Rationale
        
        Args:
            mom_data: 會議記錄資料
        
        Returns:
            str: Design Rationale (Markdown 格式)
        """
        # 準備 MoM 摘要
        mom = self._prepare_mom(mom_data)
        
        user_prompt = f"""請根據以下會議記錄整理 Design Rationale。

                會議記錄：
                {mom}

                請整理出以下章節的 Design Rationale（只整理會議記錄中已有的資訊，不要額外假設）：
                1. **決策理由**：整理每個重要決策的原因和考量因素
                2. **方案取捨過程**：整理如何在多個方案中進行選擇的過程
                3. **替代方案**：整理被考慮但未採用的方案
                4. **依據與參考**：整理決策所依據的專家建議或資源

                請以完整的 Markdown 格式輸出，使用清晰的章節結構和要點列表。
                重要：只整理會議記錄中已有的內容，不要添加額外的建議或假設。"""
        
        dr_content = self.model.generate(user_prompt)
        return dr_content
    
    def _prepare_mom(self, mom_data: Dict[str, Any]) -> str:
        """準備 MoM 摘要供 LLM 處理"""
        summary = []
        
        rounds = mom_data.get("rounds")
        for i, round_data in enumerate(rounds, 1):
            summary.append(f"## Round {i}")
            
            stages = round_data.get("stages")
            for stage in stages:
                agent = stage.get("agent")
                description = stage.get("description")
                summary.append(f"- {agent}: {description}")
        
        # 添加衝突解決記錄（從每個 round 中提取）
        all_resolutions = []
        for round_data in rounds:
            resolutions = round_data.get("conflict_resolutions", [])
            all_resolutions.extend(resolutions)
        
        if all_resolutions:
            summary.append("\n## 衝突解決記錄")
            for cr in all_resolutions:
                summary.append(f"- {cr['conflict_id']}: {cr['decision']}")
                summary.append(f"  理由: {cr['rationale']}")
        
        return "\n".join(summary)
    
    def generate_srs_json(
        self,
        draft: Dict[str, Any],
        ieee_template: List[Dict]
    ) -> Dict[str, Any]:
        # 根據 draft.json 和 IEEE 29148 模板產生 srs.json
        draft_text = json.dumps(draft, ensure_ascii=False, indent=2)
        template_text = json.dumps(ieee_template, ensure_ascii=False, indent=2)

        system_prompt = "你是軟體需求規格書撰寫專家，擅長撰寫符合 IEEE 29148 標準的 SRS 文件。"
        
        user_prompt = f"""需求草稿（Draft）：
                {draft_text}

                IEEE 29148 標準結構：
                {template_text}

                請將需求草稿轉換為符合 IEEE 29148 標準的 SRS 文件。
                將 draft 中的內容對應到 IEEE 29148 的章節結構中。

                請以 JSON 格式回應，遵循 IEEE 29148 結構。"""
        
        srs = self.model.generate_json(user_prompt, system_prompt)
        return srs

    
    def generate_srs_markdown(self, srs_json: Dict[str, Any]) -> str:
        # 將 srs.json 轉換為 Markdown 格式
        md = "# Software Requirements Specification (SRS)\n\n"
        md += "---\n\n"
        
        # 遞迴處理 IEEE 結構
        ieee_sections = srs_json.get("ieee_29148")
        md += self._render_sections(ieee_sections, level=2)
        
        return md
    
    def _render_sections(self, sections: List[Dict], level: int) -> str:
        # 遞迴渲染章節
        md = ""
        if sections is None:
            return md
        
        for section in sections:
            # 章節標題
            section_title = section.get("section", "")
            md += f"{'#' * level} {section_title}\n\n"
            
            # 注釋
            if section.get("note"):
                md += f"*{section['note']}*\n\n"
            
            # 內容
            content = section.get("content", "")
            if isinstance(content, str):
                md += f"{content}\n\n"
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, str):
                        md += f"- {item}\n"
                    elif isinstance(item, dict):
                        md += f"- **{item.get('id', '')}**: {item.get('content', '')}\n"
                md += "\n"
            
            # 子章節
            if section.get("subsection"):
                md += self._render_sections(section["subsection"], level + 1)
        
        return md
