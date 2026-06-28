# Defines action prompts and output contracts.
from agents.profile.base import json_only_rules


def create_draft(*, version_note: str, version: int = 0) -> str:
    note_block = f"\n{version_note.strip()}" if version_note.strip() else ""
    return f"""# 任務
規劃初版需求草稿 draft_v{version} 的章節架構。{note_block}

# Action Boundary
- action=create_draft
- 本 action 根據目前 artifact 規劃初版草稿章節，輸出 draft_plan JSON。
- draft_plan 只決定章節順序與每個章節是否納入。
- 初版草稿不得包含 system_requirement 或 traceability，因為正式 REQ-* 尚未形成。

# Input
- artifact 由 runtime context 提供。
- version=draft_v{version}
- version_note={version_note.strip() or "無"}

# Context Rules
- artifact 是判斷章節是否可用的唯一資料來源。
- draft_plan 只能決定 section_order 與 sections.include。
- 如果 artifact 沒有某章節來源資料，該章節 include=false。

# Generation Rules
- 只規劃 artifact 有資料且對讀者有價值的章節；空章節 include=false。
- section_order 只能使用允許章節 id，且順序必須符合 Output JSON 的固定架構。

# Allowed Section IDs
- scope
- user_requirements
- feedback
- open_questions
- system_models

# Output JSON
{{
  "draft_plan": {{
    "section_order": [
      "scope",
      "user_requirements",
      "feedback",
      "open_questions",
      "system_models"
    ],
    "sections": [
      {{"id": "scope", "include": true}},
      {{"id": "user_requirements", "include": true}},
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

{json_only_rules()}"""
