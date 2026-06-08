# Defines action usage timing and output rules.
from agents.profile.base import (
    elicitation_action_rules,
    elicitation_action_task,
    elicitation_context,
    label_rules,
    reason_rules,
    review_contract,
)

# ========
# Defines skill usage policy function for this module workflow.
# ========
def skill_usage_policy() -> str:
    return """domain-research：
- 用於候選需求涉及外部法規、標準、安全、隱私、稽核、認證、第三方限制、外部資料限制、產業流程或 domain risk。
- 只有當外部資料會影響候選需求、constraint、risk 或外部限制邊界判斷時才使用。
- 用於確認某項 obligation 是否真有約束力，或區分強制義務、最佳實務、風險提醒與待查證缺口。
- 不用於一般功能需求討論、scope/priority/UX preference、純需求語意衝突，或既有領域研究資料已足夠的情況。"""


# ========
# Defines tool usage policy function for this module workflow.
# ========
def tool_usage_policy(enabled_tools: set[str]) -> str:
    lines = []
    if "artifact_query" in enabled_tools:
        lines.append(
            "- artifact_query 用於先確認 scenario、scope、需求、stakeholders、open_questions 與既有 domain research；若議題、trace、source 或前文出現 URL-*、REQ-*、SM-*、CR-*，優先用 mode=related_context, item_id=<id>, compact=true 取得關聯脈絡；只有既有資料不足時才用 read_file 或 web_search。"
        )
    if "read_file" in enabled_tools:
        lines.append(
            "- read_file 用於查 doc/ 內專案參考文件；需要文件證據時先搜尋再讀相關片段。"
        )
    if "web_search" in enabled_tools:
        lines.append(
            "- web_search 只用於補外部法規、標準、官方文件、可信組織文件、官方條款或外部風險依據；不得使用部落格、社群媒體、論壇、新聞稿、行銷文章或一般心得文作為 feedback 來源，也不得覆蓋專案已知事實。"
        )
    lines.append(
        "- 區分強制義務、最佳實務、風險提醒與 evidence gap；外部研究結果預設只是候選依據。"
    )
    return "\n".join(lines)


issue_task = "聚焦法規、標準、證據、限制與風險。"
issue_rules = """- text 需包含：暫時結論、依據、風險/限制、建議下一步。
- 若屬強制義務要明講；若只是最佳實務或待補證據也要明講。
- 可引用 requirement id、conflict id、研究發現或來源線索。
- 若資訊不足，明確指出 evidence gap；不要虛構法規或標準。
- 需要外部證據時可使用 web_search 查可信公開資料；引用網址時使用完整 URL 純文字，不要使用 Markdown 連結，避免後續文字被誤判成超連結。
- 可信公開資料優先順序：政府/主管機關、法規資料庫、標準組織、學術/研究機構、消費者保護組織、官方公司條款/隱私/安全/合規文件。
- 不使用部落格、社群媒體、論壇、新聞稿、行銷文章、一般心得文或內容農場作為依據。
- feedback / research finding 是輔助依據，不是正式決議；若要轉成需求，必須標示為候選並交由 analyst/user/mediator 決定。
- 涉及範圍、優先級或需求措辭時，只說明外部限制、證據強度與風險影響。"""
conflict_rules = """# 本議題特別要求（conflict_discussion）
- 任務是逐筆再審查目前這批 Conflict/Neutral 項目，而不是重新定義需求。
- 必須先根據 User Requirements（URL-*）原文獨立重判，並將重判結果填入 proposed_label。"""
conflict_rules += f"""
{review_contract}
- reason 必須寫成完整審查意見：說明獨立判斷依據，以及是否涉及外部規範、標準、合規限制、品質底線或風險；若不需要外部依據即可判斷，也要明確說明判斷依據來自需求本身。
{label_rules}
{reason_rules}
- 需特別檢查：同一領域義務、品質底線、風險限制、證據義務或可接受性標準是否被重複、細化或用不同條件描述，導致軟體需求規格書需要統一、合併或裁定。
- 請明確指出：是哪一條限制、法規、標準、品質邊界、風險或需求本身的條件造成互斥、重複或需要裁定。"""
resolution_rules = """# 本議題特別要求（resolve_conflict）
- 直接針對衝突報告中既有解決選項與建議解法做取捨。
- 不重新判斷 Conflict/Neutral，也不重新執行 conflict detection。
- 從領域限制、法規/標準、品質底線、風險與證據強度判斷既有方案是否可採用。
- text 需說明：支持哪個既有方案、是否需要調整、調整理由、以及不可接受的風險或限制。
- 若資訊足以支持採用或調整某個 resolution，stance.state 填 ready_to_close，stance.proposal 填具體建議。
- 若缺少會改變決策的領域證據，stance.state 填 needs_more_discussion，stance.proposal 仍須填目前最合理的候選方案或可裁決選項；不要提出 open_questions。
- 若無法在會議內判斷，stance.proposal 應整理可交由人類裁決的領域風險取捨，不要求延長討論。"""
expert_elicitation = f"""{elicitation_context}

- 聚焦外部限制、領域規則、政策/合規風險、營運風險、公平性與責任歸屬。
- 若需要提問，只提出最會影響需求是否成立、是否可採用、是否合規或是否有風險底線的那一個問題。
- 不要為了扮演 expert 而硬問合規、法規或安全；若沒有會改變決策的限制缺口，提出收束。
- 不要把會議帶成一般技術選型或工程審查。"""

# ========
# Defines elicitation task function for this module workflow.
# ========
def elicitation_task(stop_phrase: str) -> str:
    return elicitation_action_task(stop_phrase)

# ========
# Defines elicitation rules function for this module workflow.
# ========
def elicitation_rules(stop_phrase: str) -> str:
    return f"""{elicitation_action_rules(stop_phrase)}
- target_stakeholders 優先選擇能說明外部限制、營運限制、資料可信度、結果可接受性、品質邊界或風險底線的 stakeholder。
- 問題應直接補足最關鍵的限制、風險、驗收邊界或證據缺口。
- 不要詢問一般使用者目標或流程狀態細節；這些分別交給 analyst 或 modeler。
- 不要重問利害關係人已回答、已說不在意、或已表示 covered 的方向。"""
