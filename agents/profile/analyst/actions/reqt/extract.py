# Defines action prompts and output contracts.
import json

from ...rules import requirement_candidates_output_schema


def extract_requirement(
    *,
    scenario_json: str,
    stakeholder_row: dict,
    existing_rows: list,
    mode_name: str,
    rules: str,
) -> str:
    mode_block = ""
    if str(mode_name or "").strip():
        mode_block = f"""
# 模式
{mode_name}
"""
    existing_block = ""
    if existing_rows:
        existing_block = f"""
# 目前已有的候選需求摘要
{json.dumps(existing_rows, ensure_ascii=False, indent=2)}
"""
    return f"""# 任務
從本輪利害關係人回答中抽取尚未記錄的新 User Requirements。

# Action Boundary
- action=extract_requirement
- 本 action 只抽取 requirement_candidates。
- 不產生 REQ、不更新 scope、不更新 draft、不做衝突辨識。
- 不直接更新 artifact；runtime 會驗證後才合併到 artifact.URL。

# Context Rules
- Stakeholder 回答是唯一可新增候選需求的直接來源。
- 產品情境只作為語境背景，不可單獨產生新需求。
- 目前已有的候選需求摘要只用於去重，不可改寫既有需求。

# Input
產品情境:
{scenario_json}

Stakeholder 回答:
{json.dumps(stakeholder_row, ensure_ascii=False, indent=2)}
{existing_block}{mode_block}
# Generation Rules
{rules}
- 若回答只是重述、同義改寫或細化目前已有候選需求，且沒有形成新的 stakeholder goal、need、constraint 或責任邊界，回傳空陣列。
- 若回答補充的條件、例外、處理方式、SOP 或量化門檻會改變 stakeholder goal、need、constraint、責任邊界或可接受/不可接受情況，必須抽成粗粒度 User Requirement。
- 若只是單純補欄位、單一步驟、單一 UI 細節或驗收方式，且不形成新的需求目標或限制，才不要新增 User Requirement。
- requirement_candidates 每筆只包含 text；不要輸出 priority、acceptance criteria、REQ 欄位、scope 或 reason。

{requirement_candidates_output_schema()}

# Forbidden Output
- 不輸出 Markdown 說明。
- 不輸出 REQ、scope_updates、draft_plan 或 conflicts。
- 不輸出 artifact 全文。
- 不輸出舊格式，例如最外層直接使用陣列。
- 不從產品情境或既有候選需求摘要單獨創造新需求。"""
