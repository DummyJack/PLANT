# Expert prompt fragments: task-specific rules used outside the system prompt.
from agents.profile.conflict_review import (
    CONFLICT_REVIEW_LABEL_RULES,
    CONFLICT_REVIEW_REASON_RULES,
    CONFLICT_REVIEW_RESPONSE_CONTRACT,
)
from agents.profile.elicitation_prompt import (
    COMMON_ELICITATION_CONTEXT_RULES,
    elicitation_action_rules,
    elicitation_action_task,
)

EXPERT_ISSUE_TASK = "聚焦法規、標準、證據、限制與風險。"

EXPERT_ISSUE_RULES = """- text 需包含：暫時結論、依據、風險/限制、建議下一步。
- 若屬強制義務要明講；若只是最佳實務或待補證據也要明講。
- 可引用 requirement id、conflict id、研究發現或來源線索。
- 若資訊不足，明確指出 evidence gap；不要虛構法規或標準。
- feedback / research finding 是輔助依據，不是正式決議；若要轉成需求，必須標示為候選並交由 analyst/user/mediator 決定。
- 涉及範圍、優先級或需求措辭時，只說明外部限制、證據強度與風險影響。"""

EXPERT_CONFLICT_ISSUE_RULES = """# 本議題特別要求（conflict_discussion）
- 任務是逐筆再審查目前這批 Conflict/Neutral 項目，而不是重新定義需求。
- 你必須先根據 requirements 原文獨立重判，並將重判結果填入 proposed_label。"""
EXPERT_CONFLICT_ISSUE_RULES += f"""
{CONFLICT_REVIEW_RESPONSE_CONTRACT}
- reason 必須寫成完整審查意見：說明你的獨立判斷依據，以及是否涉及外部規範、標準、合規限制、品質底線或風險；若不需要外部依據即可判斷，也要明確說明判斷依據來自需求本身。
{CONFLICT_REVIEW_LABEL_RULES}
{CONFLICT_REVIEW_REASON_RULES}
- 需特別檢查：同一領域義務、品質底線、風險限制、證據義務或可接受性標準是否被重複、細化或用不同條件描述，導致軟體需求規格書需要統一、合併或裁定。
- 請明確指出：是哪一條限制、法規、標準、品質邊界、風險或需求本身的條件造成互斥、重複或需要裁定。"""

EXPERT_ELICITATION_CONTEXT_RULES = f"""{COMMON_ELICITATION_CONTEXT_RULES}

# Expert 角度
- 若需要提問，只提出最會影響需求是否成立、是否可採用、是否合規或是否有風險底線的那一個問題。
- 不要為了扮演 expert 而硬問合規、法規或安全；若沒有會改變決策的限制缺口，提出收束。
- 不要把會議帶成一般技術選型或工程審查。"""


def expert_elicitation_action_task(stop_phrase: str) -> str:
    return elicitation_action_task(stop_phrase)


def expert_elicitation_action_rules(stop_phrase: str) -> str:
    return f"""{elicitation_action_rules(stop_phrase)}
- target_stakeholders 優先選擇能說明外部限制、營運限制、資料可信度、結果可接受性、品質邊界或風險底線的 stakeholder。
- 問題應直接補足最關鍵的限制、風險、驗收邊界或證據缺口。
- 不要重問利害關係人已回答、已說不在意、或已表示 covered 的方向。"""
