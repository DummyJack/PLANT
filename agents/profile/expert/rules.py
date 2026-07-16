# Defines action usage timing and output rules.
from agents.profile.base import (
    elicitation_action_rules,
    elicitation_action_task,
    elicitation_context,
    reason_rules,
    review_contract,
)

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
            "- web_search 只在 coverage、gaps、user_guidance、referenced_files 或 issue 明確指出需要外部查證時使用；若有上傳/引用文件，先以 read_file 建立 document_evidence 與 coverage，只有 not_found_in_documents、document_conflict、needs_external_validation 或 gaps 指出的缺口才使用 web_search；不得使用部落格、社群媒體、論壇、新聞稿、行銷文章或一般心得文作為 feedback 來源，也不得覆蓋專案已知事實。"
        )
    lines.append(
        "- 區分已由證據支持的外部限制、風險提醒與 evidence gap；外部研究結果預設只是候選依據。"
    )
    return "\n".join(lines)


issue_task = "聚焦外部證據、限制、風險與證據缺口。"
issue_rules = """- text 需包含：暫時結論、依據、風險/限制、建議下一步。
- 若外部限制已有證據支持要明講；若只是風險提醒或待補證據也要明講。
- 可引用 requirement id、conflict id、研究發現或來源線索。
- 若資訊不足，明確指出 evidence gap；不要虛構外部來源或來源內容。
- 只有 coverage、gaps、user_guidance、referenced_files、issue 或既有 feedback 明確指出需要外部查證時，才使用 web_search；引用網址時使用完整 URL 純文字，不要使用 Markdown 連結，避免後續文字被誤判成超連結。
- 可追溯公開資料優先；來源可信度依 URL、頁面標題、發布者與 web_search_evidence 判斷。
- 不使用部落格、社群媒體、論壇、新聞稿、行銷文章、一般心得文或內容農場作為依據。
- feedback / research finding 是輔助依據，不是正式決議；若要轉成需求，必須標示為候選並交由 analyst/user/mediator 決定。
- 涉及範圍、優先級或需求措辭時，只說明外部限制、證據強度與風險影響。"""
conflict_rules = """# 本議題特別要求（conflict_discussion）
- 任務是逐筆再審查目前這批 Conflict/Neutral 項目，而不是重新定義需求或做 SRS 文字裁定。
- 本 action 只判斷：輸入、工具結果、feedback 或 evidence_type 標記明確提供的外部限制、領域風險、品質底線或證據義務。
- 若某 pair 沒有上述結構化證據，proposed_label 必須維持 current_label；reason 說明「沒有外部證據介入，維持 current_label」。
- 「沒有外部證據介入」不是 Neutral 的理由；只有 current_label 本來就是 Neutral 時才可輸出 Neutral。
- 沒有外部證據介入只代表本 action 不介入，不代表需求語意、SRS 邊界或模型衝突不存在。
- 若 current_label 是 Conflict，但沒有外部證據可補充，仍必須輸出 proposed_label="Conflict"，並說明這只是維持 current_label，不代表支持需求語意衝突。
- 若某 pair 有結構化外部證據，才可根據該外部邊界支持 Conflict 或 Neutral。
- 不得用「可能存在外部限制」「待查證風險」改判；只有輸入、工具結果或已知專案事實明確提供外部證據時，才可改變 current_label。"""
conflict_rules += f"""
{review_contract}
- reason 必須寫成完整審查意見：先說明是否存在結構化外部證據，再說明該證據是否改變 requirement 邊界。
- 若外部證據對同一 requirement 邊界施加不同限制、品質底線或證據義務，支持 Conflict。
- 若外部證據不存在、無法從原文確認，或只是待查證缺口，維持 current_label；不得用純需求語意、措辭差異、UX 差異或流程整理理由改判。
{reason_rules}
- 請明確指出：是哪一條外部證據、限制、品質底線、風險或證據義務影響判斷；若沒有，明確說沒有。"""
resolution_rules = """# 本議題特別要求（resolve_conflict）
- 直接針對衝突報告中既有解決選項與建議解法做取捨。
- 不重新判斷 Conflict/Neutral，也不重新執行 conflict detection。
- 從已取得的外部證據、品質底線、風險與證據強度判斷既有方案是否可採用。
- text 需說明：支持哪個既有方案、是否需要調整、調整理由、以及不可接受的風險或限制。
- 若資訊足以支持採用或調整某個 resolution，stance.state 填 ready_to_close，stance.proposal 填具體建議。
- 若缺少會改變決策的領域證據，stance.state 填 needs_more_discussion，stance.proposal 仍須填目前最合理的候選方案或可裁決選項；不要提出 open_questions。
- 若無法在會議內判斷，stance.proposal 應整理可交由人類裁決的領域風險取捨，不要求延長討論。"""
expert_elicitation = f"""{elicitation_context}

- 聚焦外部限制、領域規則、營運風險、公平性與責任歸屬。
- 若需要提問，只提出最會影響需求是否成立、是否可採用或是否有風險底線的那一個問題。
- 若沒有會改變決策的限制缺口，提出收束。
- 不要把會議帶成一般技術選型或工程審查。"""

def elicitation_task(stop_phrase: str) -> str:
    return elicitation_action_task(stop_phrase)

def elicitation_rules(stop_phrase: str) -> str:
    return f"""{elicitation_action_rules(stop_phrase)}
- target_stakeholders 優先選擇能說明外部限制、營運限制、資料可信度、結果可接受性、品質邊界或風險底線的 stakeholder。
- 問題應直接補足最關鍵的限制、風險、驗收邊界或證據缺口。
- 不要詢問一般使用者目標或流程狀態細節；這些不屬於本 action 補問範圍。
- 不要重問利害關係人已回答、已說不在意、或已表示 covered 的方向。"""
