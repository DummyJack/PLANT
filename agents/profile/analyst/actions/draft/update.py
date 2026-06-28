# Defines action prompts and output contracts.
from agents.profile.base import json_only_rules


def update_draft(*, version_note: str, version: int = 0) -> str:
    return f"""# 任務
規劃更新版需求草稿 draft_v{version} 的章節架構。{version_note}

# Action Boundary
- action=update_draft
- 本 action 根據最新 artifact 與 previous_draft 規劃更新版草稿章節，輸出 draft_plan JSON。
- draft_plan 只決定章節順序與每個章節是否納入。
- previous_draft 只作為修訂背景；章節是否出現必須以最新 artifact 為準。

# Input
- 最新 artifact 由 runtime context 提供。
- previous_draft 由 runtime context 提供。
- version=draft_v{version}
- version_note={version_note.strip() or "無"}

# Context Rules
- 最新 artifact 是判斷章節是否可用的唯一資料來源。
- previous_draft 只能用來避免章節安排突兀，不可作為保留已過期內容的來源。
- draft_plan 只能決定 section_order 與 sections.include。
- 如果 artifact 沒有某章節來源資料，該章節 include=false。

# Generation Rules
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
      {{"id": "scope", "include": true}},
      {{"id": "user_requirements", "include": true}},
      {{"id": "system_requirement", "include": true}},
      {{"id": "feedback", "include": false}},
      {{"id": "open_questions", "include": false}},
      {{"id": "system_models", "include": true}}
    ]
  }}
}}

# Forbidden Output
- 不輸出 Markdown 草稿。
- 不輸出舊格式或 draft_plan 以外的 wrapper。
- 不新增、改寫或刪除 artifact 內容。
- 不產生 REQ、scope、conflict、system_models 或 SRS。
- 不保留 latest artifact 已不存在的 previous_draft 內容。

{json_only_rules()}"""
