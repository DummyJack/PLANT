# Defines action prompts and output contracts.


from typing import List, Optional


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
- 本 action 只整理專案內部文件證據。
- 不查外部 web。
- 不產生 feedback。
- 不新增或修改 REQ、URL、scope、conflict 或 draft。
- artifact 寫回由 runtime 負責。

# Input
研究問題:
{query}

# Generation Rules
- 必須使用 read_file 搜尋或讀取相關文件片段。
- 只整理和研究問題、source requirements 或目前議題直接相關的文件證據。
- 若文件沒有相關內容，document_evidence 輸出空陣列，並在 gaps 說明缺口。
- 每筆 document_evidence 必須包含 source；source 要能追蹤到文件名稱、路徑或片段位置。
- related_requirement_ids 只能引用輸入 URL / User Requirements 中存在的 id；不能編造 URL-*。
- 不要根據文件證據產生正式需求；只做 evidence summary。

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
  "gaps": []
}}

# Forbidden Output
- 不輸出 Markdown 說明。
- 不輸出 feedback 或 research_evidence。
- 不輸出正式需求、決策或 artifact 全文。
- 不編造文件來源、URL-* 或 requirement id。"""
