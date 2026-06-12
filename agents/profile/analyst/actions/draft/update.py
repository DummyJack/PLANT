# Defines action prompts and output contracts.


def update_draft(*, version_note: str, version: int = 0) -> str:
    return f"""# 任務
規劃更新版需求草稿 draft_v{version} 的章節架構。{version_note}

# Action Boundary
- action=update_draft
- 本 action 只輸出 draft_plan JSON，不直接輸出 Markdown。
- Markdown 會由 renderer 根據 draft_plan 與最新 artifact 產生。
- 不新增、改寫或刪除 artifact 內容；只決定章節是否出現與順序。
- 不產生 REQ、不更新 scope、不做衝突辨識、不做模型建模。
- previous_draft 只作為修訂背景；章節是否出現必須以最新 artifact 為準。

# Input
- 最新 artifact 由 runtime context 提供。
- previous_draft 由 runtime context 提供。
- version=draft_v{version}
- version_note={version_note.strip() or "無"}

# Context Rules
- 最新 artifact 是 renderer 後續產生 Markdown 的唯一資料來源。
- previous_draft 只能用來避免章節安排突兀，不可作為保留已過期內容的來源。
- draft_plan 只能決定 section_order、sections.include、sections.reason、draft_notes。
- 如果 artifact 沒有某章節來源資料，該章節 include=false。

# Section Rules
- 若 artifact.REQ 有資料，必須 include system_requirement。
- System Requirement 只能來自 artifact.REQ。
- 不規劃 traceability；需求追蹤表不再放入草稿。
- 只規劃 artifact 有資料且對讀者有價值的章節；空章節 include=false。
- section_order 只能使用允許章節 id，且順序必須符合 Output JSON 的固定架構。

# Allowed Section IDs
- scope
- user_requirements
- system_requirement
- feedback
- open_questions
- system_models

# Output JSON
{{
  "draft_plan": {{
    "section_order": [
      "scope",
      "user_requirements",
      "system_requirement",
      "feedback",
      "open_questions",
      "system_models"
    ],
    "sections": [
      {{"id": "scope", "include": true, "reason": "有 scope 資料"}},
      {{"id": "user_requirements", "include": true, "reason": "有 User Requirements"}},
      {{"id": "system_requirement", "include": true, "reason": "有正式 REQ-*"}},
      {{"id": "feedback", "include": false, "reason": "沒有影響需求判斷的 feedback"}},
      {{"id": "open_questions", "include": false, "reason": "沒有未解問題"}},
      {{"id": "system_models", "include": true, "reason": "有正式 system models"}}
    ],
    "draft_notes": []
  }}
}}

# Forbidden Output
- 不輸出 Markdown 草稿。
- 不輸出 artifact 全文。
- 不輸出舊格式或 draft_plan 以外的 wrapper。
- 不新增、改寫或刪除 artifact 內容。
- 不產生 REQ、scope、conflict、system_models 或 SRS。
- 不保留 latest artifact 已不存在的 previous_draft 內容。
- 只輸出 JSON。"""
