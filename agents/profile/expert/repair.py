# Defines module workflow behavior.
import json
from typing import Any


# ========
# Defines domain research output schema function for this module workflow.
# ========
def domain_research_output_schema(*, wrapper: str, source_ref: str) -> str:
    return f"""輸出 JSON：
{{
  "{wrapper}": {{
    "findings": [{{"text": "", "related_requirement_ids": [], "source": "{source_ref}"}}],
    "sources": [{{"title": "電子支付機構管理條例", "url": "https://..."}}, {{"title": "參考文件.pdf", "url": "104431333156/參考文件.pdf", "type": "file"}}],
    "constraints": [{{"text": "", "related_requirement_ids": [], "source": "{source_ref}"}}],
    "risks": [{{"text": "", "related_requirement_ids": [], "source": "{source_ref}"}}],
    "recommendations": [{{"text": "", "related_requirement_ids": [], "source": "{source_ref}"}}]
  }}
}}"""


# ========
# Defines repair plan output function for this module workflow.
# ========
def repair_plan_output(*, raw: Any, error: str) -> str:
    raw_text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False, indent=2)
    return f"""修正 Expert research_domain plan 輸出格式。

錯誤：
{error}

規則：
- 只修正 research_plan、action 名稱、params 結構與 action_plan 格式。
- 最外層必須只有 research_plan。
- 可用 action 只有 read_reference_docs、research_issue、update_feedback、done。
- read_reference_docs / research_issue 必須有 params.query。
- research_issue 必須有 params.value_reason，說明為什麼此問題是 high-value research issue。
- high-value 指會影響需求是否成立、系統邊界、法規/合規/安全、責任歸屬、驗收標準、多個 URL/REQ，或目前 artifact 沒有清楚答案。
- research_issue 最多 4 個；若超過，合併相近題目。
- 若 action_plan.steps 有 research_issue，最後必須包含 update_feedback。
- update_feedback 只允許放在 action_plan 最後一次。
- 若輸入內容涉及支付、退款、個資、隱私、安全、法規、合規、第三方、資料保存、稽核、責任歸屬、補償或申訴，且目前沒有 existing feedback / research_results，必須輸出 research_issue + update_feedback。
- 沒有高價值且可取得可靠來源的研究問題時，可以輸出 done，不要硬塞低品質 research_issue。
- 不新增新的研究結論；這裡只決定下一步要跑什麼。

輸出 JSON：
{{
  "research_plan": {{
    "action": "done",
    "params": {{}},
    "reasoning": "使用目前輸出語系的一句說明",
    "action_plan": {{
      "goal": "本輪 research_domain 目標",
      "steps": [
        {{"action": "read_reference_docs", "params": {{"query": "具體文件查詢問題"}}}},
        {{
          "action": "research_issue",
          "params": {{
            "query": "具體高價值研究問題",
            "value_reason": "為什麼此問題會影響需求品質"
          }}
        }},
        {{"action": "update_feedback", "params": {{}}}}
      ]
    }}
  }}
}}

原始輸出：
{raw_text}
"""


# ========
# Defines repair action output function for this module workflow.
# ========
def repair_action_output(
    *,
    action: str,
    raw: Any,
    error: str,
    source_ref: str,
) -> str:
    raw_text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False, indent=2)
    if action == "read_reference_docs":
        return f"""修正 Expert read_reference_docs action 的輸出格式。

錯誤：
{error}

規則：
- 只修正格式與欄位，不新增原始內容沒有支持的文件證據。
- document_evidence 每筆必須包含 source、summary、related_requirement_ids。
- source 要能追蹤到文件名稱、路徑或片段位置。
- related_requirement_ids 只能是輸入資料中已存在的 URL-*；無法對應時用空陣列。
- coverage 每筆必須包含 target_id、status、reason；status 只能是 document_supported、not_found_in_documents、document_conflict、needs_external_validation。
- 若沒有相關文件證據，document_evidence 輸出空陣列，並在 gaps 說明缺口。

輸出 JSON：
{{
  "document_evidence": [
    {{
      "source": "doc/...",
      "section": "章節或片段位置",
      "summary": "文件證據摘要",
      "related_requirement_ids": ["URL-1"]
    }}
  ],
  "coverage": [
    {{
      "target_id": "URL-1",
      "status": "document_supported",
      "reason": "文件支持、缺口、衝突或仍需外部驗證的簡短原因"
    }}
  ],
  "gaps": []
}}

原始輸出：
{raw_text}
"""
    wrapper = "research_evidence" if action == "research_issue" else "feedback"
    output_schema = domain_research_output_schema(wrapper=wrapper, source_ref=source_ref)
    return f"""修正 Expert domain research action 的輸出格式。

action：
{action}

錯誤：
{error}

規則：
- 只修正格式與欄位，不新增原始內容沒有支持的結論。
- findings、constraints、risks、recommendations 的每筆 item 只包含 text、related_requirement_ids、source；不要在 item 內放 sources。
- related_requirement_ids 只能是輸入資料中已存在的 URL-*；無法對應時用空陣列。
- sources 集中放在最外層；web 來源使用 {{"title": "可讀來源名稱", "url": "完整 URL"}}，專案引用文件使用 {{"title": "檔名", "url": "專案文件路徑", "type": "file"}}。
- title 使用人可讀的法規、標準、官方文件、組織文章或案例名稱。
- sources 只接受可信來源：政府/主管機關、法規資料庫、標準組織、學術/研究機構、消費者保護組織，或官方公司條款/隱私/安全/合規文件。
- 不引用部落格、社群媒體、論壇、新聞稿、行銷文章、一般心得文或內容農場。
- 若結論來自網路研究，外部法規、標準、官方文件、第三方條款或最佳實務必須有完整 URL sources；找不到 URL 時移除該外部結論。
- 若結論來自 document_evidence 的專案引用文件，sources 必須列出對應文件路徑並標記 type=file，且不得新增 document_evidence 沒有支持的外部結論。
- constraints / recommendations 使用候選或建議語氣，不寫成已定案需求。
- 本次新增 item.source 使用：{source_ref}
- research_issue 必須輸出 research_evidence wrapper。
- update_feedback 必須輸出 feedback wrapper。

{output_schema}

原始輸出：
{raw_text}
"""
