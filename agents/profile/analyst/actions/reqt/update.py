# Defines action prompts and output contracts.
from typing import Optional

from ...rules import (
    requirement_context_rules,
    requirement_coverage_gap_rules,
    requirement_formalization_rules,
    requirement_quality_rules,
)
from agents.profile.base import forbidden_output_rules


def requirement_records_output_schema(*, source_id: str) -> str:
    return f"""# Output JSON
{{
  "REQ": [
    {{
      "type": "functional | non-functional | constraint",
      "id": "既有 REQ-*；新增時省略或留空",
      "title": "短標題",
      "description": "系統應...",
      "priority": "functional / non-functional 才填 must | should | could；constraint 不填",
      "category": "non-functional 才填 ISO/IEC 25010 品質特性",
      "metric": "non-functional 才填可觀察或可測量條件",
      "validation": "non-functional 才填可執行驗證方式",
      "source": ["URL-1", "{source_id}"],
      "acceptance_criteria": [],
      "rationale": "為何需要此需求",
      "dependencies": [],
      "risks": [],
      "assumptions": []
    }}
  ],
  "remove_REQ": [],
  "reason": "一句說明"
}}"""


def update_requirement_coverage() -> str:
    return """# 任務
判斷 current_URL 中仍未被 current_REQ.source 覆蓋的 User Requirements 應如何處理。

# Action Boundary
- 本階段只輸出 coverage，不建立、更新或移除 REQ。
- current_REQ 已包含上一階段配置完成的正式 REQ ID。
- 若資訊不足以形成 REQ，依語意標示 needs_clarification、assumption、risk 或 excluded，並提供具體 reason。
- covered_by 只能引用 current_REQ 中存在的 REQ-*；沒有對應 REQ 時使用空陣列。

# Output JSON
{
  "coverage": [
    {
      "source_id": "URL-1",
      "status": "covered | needs_clarification | assumption | risk | excluded",
      "covered_by": ["REQ-1"],
      "reason": "判斷理由"
    }
  ]
}

# Output Rules
- current_URL 每筆必須恰好輸出一筆 coverage。
- 不輸出 REQ、remove_REQ、reason、draft_plan、scope_updates、conflicts 或 system_models。
- 只輸出合法 JSON，不要 Markdown 或額外文字。"""


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
- 本 action 只生成 REQ、remove_REQ 與 reason；coverage 由下一階段根據已配置的正式 REQ ID 處理。
- mode={requirement_mode}；create 建立初步 REQ-*，update 更新既有 REQ-* 並補清楚未覆蓋內容。
- 若發現單一 REQ 需要拆分功能、品質或限制，或需要合併/調整粒度，只標記為後續 refine_requirement 的清理對象；不要在本 action 內做議題式精修。
- 明確且有來源支持的 NFR 直接寫成 type=non-functional；只有 metric、validation、適用範圍、FR/NFR priority 或品質取捨需要決策時，才留作 open_questions、risks 或後續會議。
- runtime 會先驗證並寫入 artifact.REQ，再獨立建立 artifact.coverage。
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
- 本階段不輸出 coverage。
- REQ title 必須是需求本體名稱，聚焦系統能力、限制或品質面向；不要把 current_URL 的 stakeholder 名稱放在 title 開頭。
- reason 只用一句話說明本次整理結果。

{requirement_records_output_schema(source_id=source_id)}

{forbidden_output_rules(
        [
            "不輸出 draft_plan、scope_updates、conflicts 或 system_models。",
            "不輸出 coverage；coverage 由下一階段獨立處理。",
            "不從 feedback、system_models 或 discussion 單獨創造 stakeholder 未支持的新 REQ。",
        ]
    )}"""
