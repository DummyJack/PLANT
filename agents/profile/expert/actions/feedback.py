# Defines action prompts and output contracts.


def update_feedback(*, source_ref: str) -> str:
    return f"""# 任務
綜合 research_results 與 existing_research，整理成本專案 feedback JSON。

# Action Boundary
- action=expert.update_feedback
- 本 action 只把 research_results、existing_research 與 document_evidence 整理為 feedback JSON。
- 不新增研究結論。
- 不新增或修改 REQ、URL、scope、conflict 或 draft。
- 不把 feedback 定案為正式需求。
- artifact 寫回由 runtime 負責。

# Input
research_results、existing_research 與 document_evidence 由 runtime context 提供。
本次新增 item.source 使用：{source_ref}

# Generation Rules
- 只做合併、去重、保留來源與整理格式；不新增 research_results / existing_research / document_evidence 以外的結論。
- research_results 每筆的研究證據位於 research_evidence。
- feedback 只作為領域研究輔助資料，不產生正式需求。
- findings、constraints、risks、recommendations 的每個 item 只保留 text、related_requirement_ids 與 source；不要在 item 內放 sources。
- related_requirement_ids 只能引用輸入資料中已出現的 URL-*；無法對應單一需求時用空陣列。
- sources 集中放在最外層，每筆使用 {{"title": "可讀來源名稱", "url": "完整 URL"}}；沒有 URL 時輸出空陣列。
- title 使用人可讀的法規、標準、官方文件、組織文章或案例名稱。
- sources 只接受可信來源：政府/主管機關、法規資料庫、標準組織、學術/研究機構、消費者保護組織，或官方公司條款/隱私/安全/合規文件。
- 不引用部落格、社群媒體、論壇、新聞稿、行銷文章、一般心得文或內容農場。
- 若輸出任何外部法規、標準、官方文件、第三方條款或最佳實務，sources 必須至少包含對應完整 URL；找不到 URL 時不要輸出該外部結論。
- constraints / recommendations 使用候選或建議語氣，不寫成已定案需求。
- 本次新增 item.source 使用：{source_ref}

# Output JSON
{{
  "feedback": {{
    "findings": [{{"text": "", "related_requirement_ids": [], "source": "{source_ref}"}}],
    "sources": [{{"title": "電子支付機構管理條例", "url": "https://..."}}],
    "constraints": [{{"text": "", "related_requirement_ids": [], "source": "{source_ref}"}}],
    "risks": [{{"text": "", "related_requirement_ids": [], "source": "{source_ref}"}}],
    "recommendations": [{{"text": "", "related_requirement_ids": [], "source": "{source_ref}"}}]
  }}
}}

# Forbidden Output
- 不輸出 Markdown 說明。
- 不輸出 research_plan 或 research_evidence。
- 不輸出正式需求、決策或 artifact 全文。
- 不新增 research_results / existing_research / document_evidence 以外的結論。
- 不編造外部 URL、法規、標準或 requirement id。"""
