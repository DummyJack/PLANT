# Defines action prompts and output contracts.
from typing import Optional

from ...rules import (
    requirement_context_rules,
    requirement_coverage_gap_rules,
    requirement_formalization_rules,
    requirement_output_schema,
    requirement_quality_rules,
)


def update_requirement(
    *,
    requirement_mode: str,
    source_id: str,
    coverage_gaps: Optional[list] = None,
) -> str:
    return f"""# 任務
將 current_URL 正式化為 requirements.json 中的 REQ-* 條目。

# Action Boundary
- action=update_requirement
- mode={requirement_mode}
- create：根據 current_URL 建立初步 REQ-*。
- update：根據 current_URL 與 current_REQ 更新 REQ-*；若有清楚未覆蓋內容，新增 REQ。
- 本 action 只負責 URL / User Requirements → REQ，不修單一議題、不更新 draft、不跑衝突辨識。
- 若發現單一 REQ 需要拆分功能、品質或限制，或需要合併/調整粒度，只標記為後續 refine_requirement 的清理對象；不要在本 action 內做議題式精修。
- 明確且有來源支持的 NFR 直接寫成 type=non-functional；只有 metric、validation、適用範圍、FR/NFR priority 或品質取捨需要決策時，才留作 open_questions、risks 或後續會議。
- 不直接更新 artifact；runtime 會驗證 requirement_update 後才寫入 artifact.REQ / artifact.coverage。
- 最外層只能輸出 requirement_update。
- update 模式若發現既有多筆 REQ 其實只是同一能力、同一限制或同一品質面向的細節拆分，請保留最合適的一筆既有 REQ id，將來源合併到該 REQ.source，並在 remove_REQ 列出被合併移除的舊 REQ id。

# Input
- current_URL、current_REQ、scope、feedback、system_models、discussion 與 coverage_gaps 由 runtime context 提供。
- source_id={source_id}
- requirement_mode={requirement_mode}

# Context Boundary
- current_URL 是正式化的主要來源。
- current_REQ 是更新、合併、避免重複與 coverage 對照用。
- scope、feedback、system_models 只作為邊界、限制、風險或一致性參考；不能單獨創造 stakeholder 未支持的新 REQ。
- discussion 只作為本輪整理背景；若沒有 current_URL 或 current_REQ 支持，不要新增 REQ。

{requirement_context_rules()}

{requirement_formalization_rules()}

{requirement_quality_rules()}

{requirement_coverage_gap_rules(coverage_gaps)}

# Generation Rules
- 只回傳本次新增或需要更新的 REQ；已完整且未變更的既有 REQ 不要重複回傳。
- REQ title 必須是需求本體名稱，聚焦系統能力、限制或品質面向；不要把 current_URL 的 stakeholder 名稱放在 title 開頭。
- reason 只用一句話說明本次整理結果。

{requirement_output_schema(source_id=source_id, include_remove_req=True)}

# Forbidden Output
- 不輸出 Markdown 說明。
- 不輸出 draft_plan、scope_updates、conflicts 或 system_models。
- 不輸出 artifact 全文。
- 不輸出舊格式，例如最外層直接使用 REQ。
- 不從 feedback、system_models 或 discussion 單獨創造 stakeholder 未支持的新 REQ。"""
