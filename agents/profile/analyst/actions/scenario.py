# Defines action prompts and output contracts.
from agents.profile.base import forbidden_output_rules


def name_scenario() -> str:
    return """# 任務
根據 rough_idea，產生高層次的產品/系統情境名稱。

# Action Boundary
- action=name_scenario
- 本 action 將 rough_idea 命名成高層次產品/系統情境，輸出 scenario_definition JSON。
- scenario_definition.name 只描述產品/系統類型。

# Context Rules
- rough_idea 是唯一直接來源。
- 名稱需由 rough_idea 支持。
- rough_idea 若只是模糊概念、代號或不完整描述，只能保留其高層次語意；不要替它推測成常見系統。

# Input
- rough_idea 由 runtime context 提供。

# Generation Rules
- 將 rough_idea 轉成短而高層次的系統名稱。
- scenario_definition.name 只放名稱字串。
- 名稱描述「這是什麼系統/平台/工具」。
- 若 rough_idea 已經是可用名稱，只做最小整理。
- 若 rough_idea 資訊不足以判斷系統類型，輸出保守名稱，例如「未明確系統」或「待釐清系統」，不要自行補成特定領域系統。

# Output JSON
{
  "scenario_definition": {
    "name": "可以做的系統名稱"
  }
}

""" + forbidden_output_rules(
        [
            "不輸出 scope、requirement_candidates、REQ 或 draft_plan。",
            "不輸出 scenario_definition 以外的 wrapper。",
            "不新增 rough_idea 沒有支持的產業、角色、功能、流程、資料物件、使用者類型、商業策略或技術方案。",
        ]
    )
