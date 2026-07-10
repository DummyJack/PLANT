# Defines action prompts and output contracts.
from agents.profile.base import forbidden_output_rules


def update_feedback(*, source_ref: str) -> str:
    return f"""# 任務
根據 research_results 與 document_evidence，整理本次新增的 feedback delta JSON。

# Action Boundary
- action=expert.update_feedback
- 本 action 將本次 research_results 與 document_evidence 整理為新增 feedback delta JSON。
- feedback delta 包含 findings、constraints、risks、recommendations 與 sources。
- existing_research 只用於避免重複；runtime 會用 deterministic merge 寫回 artifact。
- artifact 寫回由 runtime 負責。

# Input
research_results、existing_research 與 document_evidence 由 runtime context 提供。
本次新增 item.source 使用：{source_ref}

# Generation Rules
- 輸出本次 research_results / document_evidence 支持的新增 feedback。
- research_results 每筆的研究證據位於 research_evidence。
- 若 research_results 有 target_type / target_ids，feedback 只能整理與該 target 直接相關的證據；不要把同一來源擴寫到其他需求。
- 優先保留能說明「為什麼適用目前 scenario + target」的情境專屬證據；通用規範或標準只有在 trace_reason 已說明如何套用到 target 時才可保留。
- feedback 作為領域研究輔助資料。
- 人類研究建議若已被用來引導 research_results / document_evidence，需在證據支持且與 artifact 相關時反映。
- 同一研究建議應合併成最少必要的 findings、constraints、risks 或 recommendations。
- findings、constraints、risks、recommendations 的每個 item 保留 text、related_requirement_ids、source、trace_reason 與 evidence_type。
- evidence_type 沿用 research_results / document_evidence；使用外部 URL 證據時必須是 web，使用專案引用文件時必須是 project_document。
- related_requirement_ids 只能引用 research_results.target_ids 或輸入資料中已出現且與本次 context 相關的 URL-*；無法對應 target 時用空陣列。
- trace_reason 用一句話說明為什麼此 feedback 對應這些 URL-*，並說明來源為何適用目前 scenario + target；若 related_requirement_ids 為空，也要說明無法明確對應的原因。
- sources 集中放在最外層；web 來源使用 {{"title": "research_results 中保留的來源標題", "url": "完整 URL"}}，專案引用文件使用 {{"title": "檔名", "url": "專案文件路徑", "type": "file"}}。
- sources.title 必須是人可讀的頁面標題、法規/文件名稱或「發布機關/組織：文件主題」；不得填 URL、網址路徑或純網域。優先沿用 research_results.sources、document_evidence 或文件標題；若上游 title 是 URL，請依來源發布者與頁面主題補成簡短標題。
- sources 只接受可追溯來源；來源可信度依 research_results / document_evidence 保留的來源資訊判斷。
- 不引用部落格、社群媒體、論壇、新聞稿、行銷文章、一般心得文或內容農場。
- 若結論來自 research_results 的網路研究，evidence_type 必須是 web，且必須有完整 URL sources。
- 若結論來自 document_evidence 的專案引用文件，sources 必須列出對應文件路徑並標記 type=file，且 item.text 必須只根據 document_evidence 內容整理，item.source 使用本次 source_ref。
- constraints / recommendations 使用候選或建議語氣，不寫成已定案需求。
- 本次新增 item.source 使用：{source_ref}

# Output JSON
{{
  "feedback": {{
    "findings": [{{"text": "", "related_requirement_ids": [], "source": "{source_ref}", "trace_reason": "", "evidence_type": "web"}}],
    "sources": [{{"title": "發布機關：文件主題", "url": "https://..."}}, {{"title": "參考文件.pdf", "url": "104431333156/參考文件.pdf", "type": "file"}}],
    "constraints": [{{"text": "", "related_requirement_ids": [], "source": "{source_ref}", "trace_reason": "", "evidence_type": "web"}}],
    "risks": [{{"text": "", "related_requirement_ids": [], "source": "{source_ref}", "trace_reason": "", "evidence_type": "web"}}],
    "recommendations": [{{"text": "", "related_requirement_ids": [], "source": "{source_ref}", "trace_reason": "", "evidence_type": "web"}}]
  }}
}}

{forbidden_output_rules(
        [
            "不輸出 research_plan 或 research_evidence。",
            "不輸出正式需求或決策。",
            "不新增 research_results / document_evidence 以外的結論。",
            "不重輸出 existing_research 中已存在的 feedback item。",
            "不編造外部 URL、來源內容或 requirement id。",
        ]
    )}"""
