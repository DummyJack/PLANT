# Defines repair prompts for agent output.
import json
from typing import Any

from utils.template import render_template


repair_prompts: dict[str, tuple[bool, str]] = {
    'model_plan_repair': (True, '''# 任務
修正 Modeler plan_models 的 JSON 輸出格式。

# 錯誤
{error_msg}

# 原始輸出
{raw}

# Repair Rules
- 只修正欄位與 JSON 結構，不新增模型結論。
- 最外層必須只有 model_plan。
- model_plan.model_targets 可以是空陣列；沒有 high-value model target 時輸出空陣列。
- 每個 model target 必須是 object，且 operation 只能是 create 或 update。
- 每個 model target 必須包含 type、name、related_requirement_ids、reason、value_reason。
- update 必須有 target_model_id，或至少有 type + name。
- create 必須有 name。
- value_reason 必須說明此模型能釐清的高價值需求問題；不可空白。
- 最多保留 4 個 model target；超過時保留最有需求釐清價值者。
- 不要把 use_case_text 放進 model_targets；use_case_text 由流程自動處理。
- 輸出只能使用 model_plan.model_targets 表達 create/update 目標。

# Output JSON
{{
  "model_plan": {{
    "phase_decision": "本輪如何依 modeling_phase 與 policy 決定模型目標",
    "model_targets": [
      {{
        "operation": "create | update",
        "type": "context_diagram | use_case_diagram | activity_diagram | sequence_diagram | state_machine | class_diagram",
        "target_model_id": "既有模型 id，create 時留空",
        "name": "模型名稱",
        "related_requirement_ids": ["REQ-1"],
        "reason": "為何需要 create 或 update",
        "value_reason": "此模型能釐清哪些高價值需求問題"
      }}
    ],
    "skipped_targets": [{{"type": "diagram type", "reason": "為什麼本輪跳過"}}],
    "impact_summary": "影響摘要",
    "consistency_summary": "與需求一致性的整體說明",
    "gaps": []
  }}
}}'''),
    'model_output_repair': (True, '''# 任務
修正 Modeler system_models 的 JSON 輸出格式。

# 錯誤
{error_msg}

# 原始輸出
{raw}

# Repair Rules
- 輸出必須是 JSON array。
- 只修正缺失欄位、欄位型別或 JSON 結構，不得改變 PlantUML 的需求語意、角色、流程、資料關係或狀態。
- 每個 diagram model 必須包含 name、type、plantuml、description。
- 若是 class_diagram，class 與 enum 顯示名稱可維持目前輸出語言；attribute 名稱、attribute type、association label 與 enum value 固定使用英文，PlantUML 語法關鍵字與型別標註必須保持可解析。
- context_diagram 的 description 只用一段話說明此圖用來釐清的系統邊界、已選利害關係人、主要互動或責任邊界。
- context_diagram 不得新增未被選擇為 stakeholders 的外部系統節點；若原圖有第三方服務、外部系統、監管/社區/金融/身分驗證服務，修復時不得把它們當成新節點補強。
- use_case_diagram 的 description 只用一段話說明此圖用來釐清哪些 actor 與系統能力。
- 其他 diagram 的 description 必須使用兩段固定格式：**用途**：...\n**反映需求**：...
- related_requirement_ids 只能保留原輸出中已存在的需求 ID，不得新增不存在的 ID。
- use_case_text model 必須包含 type=use_case_text 與 text array。
- 不要新增新模型；只修正原有模型。

# Output JSON
[
  {{
    "name": "模型名稱",
    "type": "context_diagram | use_case_diagram | activity_diagram | sequence_diagram | state_machine | class_diagram",
    "plantuml": "@startuml\\n...\\n@enduml",
    "description": "模型說明",
    "related_requirement_ids": ["REQ-1"]
  }}
]'''),
    'modeler_plantuml_repair': (True, '# 任務\n    以下 PlantUML 程式碼有語法錯誤，請修正後回傳。\n\n    # 模型名稱\n    {model.get(\'name\', \'\')}\n\n    # 原始程式碼\n    {model.get(\'plantuml\', \'\')}\n\n    # 驗證錯誤\n    {error_msg}\n\n    - 只修正 PlantUML 語法，不得改變圖的需求語意、範圍、角色、流程或資料關係。\n    - 修正語法時必須維持原圖元素語言；但若是 class_diagram，attribute 名稱、attribute type、association label 與 enum value 必須維持或修正為英文。\n    - 不要新增或移除需求內容；如果資訊不足，維持原本抽象元素，不要臆測補齊。\n\n    # Output JSON\n    {{\n    "plantuml": "@startuml\\\\n...修正後的完整程式碼...\\\\n@enduml"\n    }}'),
}


def render_repair_prompt(key: str, **context: Any) -> str:
    is_f, template = repair_prompts[key]
    if not is_f:
        return template
    return render_template(template, {"json": json, **context})
