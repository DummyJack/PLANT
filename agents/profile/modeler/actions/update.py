# Defines action prompts and output contracts.
from ..rules import (
    model_input_boundary_rules,
    model_language_rules,
    model_output_schema,
    model_update_rules,
)


def update_model(
    *,
    type_name: str,
    existing_plantuml: str,
    req_text: str,
    context_text: str,
    diagram_layout_hint: str,
    diagram_type: str,
    description_rule: str,
    description_field: str,
) -> str:
    return f"""# 任務
依更新後的需求輸入修訂既有 {type_name}。

# Action Boundary
- action=modeler.update_model
- 本 action 只修訂一個既有 system model JSON。
- 不產生 model_plan。
- 不更新 REQ、URL、scope、feedback 或 draft。
- 不裁決需求衝突。
- artifact 寫回由 runtime 負責。

# Current PlantUML
{existing_plantuml}

# Input
需求輸入（優先為 REQ-*；若尚未產生 REQ，則為 URL-*）:
{req_text}

# Context Rules
補充背景（只作為邊界、限制、風險或未決事項參考）:
{context_text}

{diagram_layout_hint}

{model_update_rules()}

{model_input_boundary_rules()}

{model_language_rules()}

{description_rule}

{model_output_schema(diagram_type=diagram_type, description_field=description_field)}

# Forbidden Output
- 不輸出 Markdown 說明。
- 不輸出 model_plan。
- 不輸出多個模型。
- 不輸出 artifact 全文。
- 不因格式整理改變原圖需求語意。
- 不新增未被需求輸入支持的 actor、use case、流程、狀態、message 或資料物件。"""
