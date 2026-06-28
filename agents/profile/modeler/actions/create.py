# Defines action prompts and output contracts.
from ..rules import (
    model_create_rules,
    model_input_boundary_rules,
    model_language_rules,
    model_output_schema,
)
from agents.profile.base import forbidden_output_rules


def create_model(
    *,
    type_name: str,
    req_text: str,
    context_text: str,
    diagram_layout_hint: str,
    diagram_type: str,
    description_rule: str,
    description_field: str,
) -> str:
    return f"""# 任務
依需求輸入建立 {type_name}。

# Action Boundary
- action=modeler.create_model
- 本 action 根據需求輸入建立一個指定 type 的 system model JSON。
- system model JSON 包含模型名稱、diagram type、PlantUML、related_requirement_ids 與說明欄位。
- artifact 寫回由 runtime 負責。

# Input
需求輸入（優先為 REQ-*；若尚未產生 REQ，則為 URL-*）:
{req_text}

# Context Rules
補充背景（只作為邊界、限制、風險或未決事項參考）:
{context_text}

{diagram_layout_hint}

{model_create_rules()}

{model_input_boundary_rules()}

{model_language_rules()}

{description_rule}

# Output
輸出 schema 如下：

{model_output_schema(diagram_type=diagram_type, description_field=description_field)}

{forbidden_output_rules(
        [
            "不輸出 model_plan。",
            "不輸出多個模型。",
            "不新增未被需求輸入支持的 actor、use case、流程、狀態、message 或資料物件。",
        ]
    )}"""
