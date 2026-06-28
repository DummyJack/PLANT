# Defines action prompts and output contracts.
from agents.profile.base import forbidden_output_rules


def research_issue(*, query: str, source_ref: str, value_reason: str = "") -> str:
    return f"""# 任務
針對以下問題蒐集並整理領域研究證據。

# Action Boundary
- action=expert.research_issue
- 本 action 蒐集領域研究證據，輸出 research_evidence JSON。
- research_evidence 包含 findings、constraints、risks、recommendations 與 sources。
- feedback 整理由 expert.update_feedback 負責。
- artifact 寫回由 runtime 負責。

# Input
研究問題:
{query}

研究價值:
{value_reason or "此問題會影響後續需求品質。"}

# Generation Rules
- research_evidence 作為後續 feedback 整理的證據來源。
- 研究價值只用來聚焦，不需要寫入正式 feedback item。
- 優先使用 document_evidence；不足時才用 web_search 補外部公開資料、法規、標準、官方文件、第三方條款或最佳實務。
- 若 context 有 document_evidence / coverage / gaps，外部研究只能針對 not_found_in_documents、document_conflict、needs_external_validation、gaps，或支付、退款、個資、隱私、安全、法規、合規、第三方、資料保存、稽核、責任歸屬、補償、申訴等高風險外部議題。
- findings、constraints、risks、recommendations 的 trace_reason 必須說明該結論補足哪個文件缺口、文件衝突或外部高風險驗證。
- 外部 URL 只接受可信來源：政府/主管機關、法規資料庫、標準組織、學術/研究機構、消費者保護組織，或官方公司條款/隱私/安全/合規文件。
- sources 使用可信來源：政府/主管機關、法規資料庫、標準組織、學術/研究機構、消費者保護組織，或官方公司條款/隱私/安全/合規文件。
- 若 context 內有 web_search_evidence / web_search_urls，必須只從這些搜尋證據中引用外部 URL。
- findings、constraints、risks、recommendations 的每個 item 包含 text、related_requirement_ids、source 與 trace_reason。
- related_requirement_ids 只能引用輸入 URL / User Requirements 中存在且與本次研究 context 相關的 URL-*；無法對應單一需求時用空陣列。
- trace_reason 用一句話說明為什麼此研究證據對應這些 URL-*；若 related_requirement_ids 為空，也要說明無法明確對應的原因。
- sources 集中放在最外層；web 來源使用 {{"title": "可讀來源名稱", "url": "完整 URL"}}，專案引用文件使用 {{"title": "檔名", "url": "專案文件路徑", "type": "file"}}。
- title 使用人可讀的法規、標準、官方文件、組織文章或案例名稱。
- 若輸出任何外部法規、標準、官方文件、第三方條款或最佳實務，sources 必須至少包含對應完整 URL；找不到 URL 或 context 沒有可用 URL 時不要輸出該外部結論。
- constraints / recommendations 使用候選或建議語氣，不寫成已定案需求。
- 本次 item.source 使用：{source_ref}

# Output JSON
{{
  "research_evidence": {{
    "findings": [{{"text": "", "related_requirement_ids": [], "source": "{source_ref}", "trace_reason": ""}}],
    "sources": [{{"title": "電子支付機構管理條例", "url": "https://..."}}, {{"title": "參考文件.pdf", "url": "104431333156/參考文件.pdf", "type": "file"}}],
    "constraints": [{{"text": "", "related_requirement_ids": [], "source": "{source_ref}", "trace_reason": ""}}],
    "risks": [{{"text": "", "related_requirement_ids": [], "source": "{source_ref}", "trace_reason": ""}}],
    "recommendations": [{{"text": "", "related_requirement_ids": [], "source": "{source_ref}", "trace_reason": ""}}]
  }}
}}

{forbidden_output_rules(
        [
            "不輸出 feedback。",
            "不輸出正式需求或決策。",
            "不引用不可信來源。",
            "不編造外部 URL、法規、標準或 requirement id。",
        ]
    )}"""
