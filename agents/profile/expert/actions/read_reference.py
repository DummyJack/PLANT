# Defines action prompts and output contracts.


from typing import List, Optional

from agents.profile.base import forbidden_output_rules


def read_docs(*, query: str, attached_references: Optional[List[str]] = None) -> str:
    priority_block = ""
    if attached_references:
        listed = "\n".join(f"- {path}" for path in attached_references)
        priority_block = f"""
# Priority References
本次任務使用者特別附上以下參考文件，請優先從這些檔案搜尋與讀取相關證據：
{listed}
"""
    return f"""# 任務
針對以下研究問題，先查找 doc/ 內專案參考文件並整理文件證據。
{priority_block}

# Action Boundary
- action=expert.read_reference_docs
- 本 action 查找專案內部參考文件，輸出 document_evidence、coverage 與 gaps JSON。
- document_evidence 是文件證據摘要；coverage 說明文件對相關需求或問題的支持、缺口或衝突。
- artifact 寫回由 runtime 負責。

# Input
研究問題:
{query}

# Generation Rules
- 必須使用 read_file 搜尋或讀取相關文件片段。
- 只整理和研究問題、source requirements 或目前議題直接相關的文件證據。
- 若文件沒有相關內容，document_evidence 輸出空陣列，並在 gaps 說明缺口。
- 每筆 document_evidence 必須包含 source；source 要能追蹤到文件名稱、路徑或片段位置。
- 必須對相關 URL / REQ / open_questions 做 coverage 判斷，status 只能是 document_supported、not_found_in_documents、document_conflict、needs_external_validation。
- 若文件只有局部支持、內容過時、互相矛盾，或 query / issue / user_guidance / referenced_files 指出仍需外部查證，coverage 應標成 needs_external_validation 或 document_conflict，不要誤標為完全支持。
- related_requirement_ids 只能引用輸入 URL / User Requirements 中存在的 id；不能編造 URL-*。
- 文件證據只做 evidence summary。

# Output JSON
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
  "gaps": ["文件未涵蓋或仍需外部驗證的具體缺口"]
}}

{forbidden_output_rules(
        [
            "不輸出 feedback 或 research_evidence。",
            "不輸出正式需求或決策。",
            "不編造文件來源、URL-* 或 requirement id。",
        ]
    )}"""
