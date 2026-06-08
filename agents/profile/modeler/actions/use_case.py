# Defines action prompts and output contracts.
from ..rules import use_case_text_rules


def use_case_text(
    *,
    req_text: str,
    use_case_diagram_text: str,
    context_text: str,
) -> str:
    return f"""# 任務
根據已生成的 Use Case Diagram 整理文字版使用案例。

# Action Boundary
- action=modeler.use_case_text
- 本 action 只把已生成的 Use Case Diagram 整理為 use_case_text JSON。
- 不建立或更新 PlantUML 圖。
- 不新增、修改或刪除 REQ、URL、scope、feedback 或 draft。
- artifact 寫回由 runtime 負責。

# Input
需求 ID 對照（只可用於 related_requirement_ids，不可用來新增 use case）:
{req_text}

Use Case Diagram:
{use_case_diagram_text}

補充背景（只作為邊界、限制、風險或未決事項參考）:
{context_text}

# Context Rules
{use_case_text_rules()}

# Output JSON
{{
  "type": "use_case_text",
  "text": [
    {{
      "id": "UC-1",
      "actor": "主要參與者",
      "name": "使用案例名稱",
      "purpose": "目的／說明",
      "interface": "頁面／介面清單",
      "related_requirement_ids": ["REQ-1"]
    }}
  ]
}}

# Forbidden Output
- 不輸出 Markdown 說明。
- 不輸出 PlantUML。
- 不輸出 system model array。
- 不新增圖中不存在的 actor 或 use case。
- 不編造 related_requirement_ids。
- 不輸出 artifact 全文。"""
