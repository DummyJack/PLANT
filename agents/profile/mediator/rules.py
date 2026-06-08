# Defines action usage timing and output rules.


def tool_usage_policy() -> str:
    return """- artifact_query 用於查詢目前需求、衝突、未決問題、決策、討論紀錄與議題池相關脈絡。
- 若議題、trace、source 或前文出現 URL-*、REQ-*、SM-*、CR-*，優先用 artifact_query mode=related_context, item_id=<id>, compact=true 取得關聯脈絡。
- 工具只能補足主持、分類、分流、收斂判斷所需的專案事實。
- 若資訊不足或未收斂，整理成待決選項或升級人類裁決，不得自行替利害關係人定案。"""


def issue_required_actions() -> dict:
    return {
        "clarify_requirement": {
            "analyst": ["refine_requirement"],
            "user": ["respond_issue"],
        },
        "define_boundary": {
            "analyst": ["refine_scope"],
            "modeler": ["system_modeling"],
        },
        "tradeoff": {
            "analyst": ["refine_requirement"],
            "expert": ["research_domain"],
            "user": ["respond_issue"],
        },
        "align_model": {
            "modeler": ["system_modeling"],
            "analyst": ["refine_requirement"],
        },
    }
