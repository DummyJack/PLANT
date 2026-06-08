# Defines action prompts and output contracts.


def name_scenario() -> str:
    return """# 任務
根據 rough_idea，產生一個可實際開發的系統情境名稱。

# Action Boundary
- action=name_scenario
- 本 action 只負責把 rough_idea 命名成產品/系統情境。
- 不產生 scope、不抽取 User Requirements、不產生 REQ、不寫 draft。
- 不直接更新 artifact；只輸出 scenario_definition JSON。

# Context Rules
- rough_idea 是唯一直接來源。
- 不要自行補充不存在的產業、角色、功能範圍或商業策略。

# Input
- rough_idea 由 runtime context 提供。

# Generation Rules
- 將 rough_idea 轉成清楚的系統名稱。
- scenario_definition.name 只放名稱字串，不要放描述段落。
- 名稱要短、可作為後續需求討論的系統名稱。

# Output JSON
{
  "scenario_definition": {
    "name": "可以做的系統名稱"
  }
}

# Forbidden Output
- 不輸出 Markdown 說明。
- 不輸出 scope、requirement_candidates、REQ 或 draft_plan。
- 不輸出 artifact 全文。
- 不輸出 scenario_definition 以外的 wrapper。
- 不新增 rough_idea 沒有支持的產業、角色、功能範圍或商業策略。"""
