# Expert prompt fragments: task-specific rules used outside the system prompt.
from agents.profile.conflict_review import (
    CONFLICT_REVIEW_EVIDENCE_RULES,
    CONFLICT_REVIEW_RESPONSE_CONTRACT,
)

EXPERT_ISSUE_TASK = "聚焦法規、標準、證據、限制與風險。"

EXPERT_ISSUE_RULES = """- statement 需包含：暫時結論、依據、風險/限制、建議下一步。
- 若屬強制義務要明講；若只是最佳實務或待補證據也要明講。
- 可引用 requirement id、conflict id、研究發現或來源線索。
- 若資訊不足，明確指出 evidence gap；不要虛構法規或標準。
- 涉及 scope、優先級或需求 wording 時，只說明外部限制、證據強度與風險影響。"""

EXPERT_CONFLICT_ISSUE_RULES = """# 本議題特別要求（conflict_discussion）
- 任務是逐筆再審查目前這批 Conflict/Neutral pairs，而不是重新定義需求。
- 你必須先根據 requirements 原文清單獨立重判，並將重判結果填入 proposed_label。
- 若只有兩筆需求，requirement_a / requirement_b 是前兩筆需求的別名。"""
EXPERT_CONFLICT_ISSUE_RULES += f"""
{CONFLICT_REVIEW_RESPONSE_CONTRACT}
- 可使用 domain-research skill / tools 查證；若未使用，也必須從領域專家角度判斷。
- Expert 角度：看外部限制、風險、安全/合規底線、證據義務、品質邊界與可接受性標準是否不一致。
- 若需求原文顯示其他領域義務、風險、證據責任或採用條件衝突，也可判為 Conflict；reason 必須明確說明。
- 若兩條需求涉及同一 domain obligation、evidence relationship、external source、risk control 或 acceptability standard，但描述了不同責任、來源、證據邊界或採用條件，請判斷是否代表不同領域承諾；若是，標為 Conflict。
- 若 proposed_label 為 Neutral，reason 必須說明為什麼兩個需求不產生外部限制、風險、證據義務或可接受性標準上的衝突。
{CONFLICT_REVIEW_EVIDENCE_RULES}
- 此會議不提出 open_questions；資訊不足時請在 reason 中說明不確定性，open_questions 必須輸出空陣列。"""

EXPERT_ELICITATION_CONTEXT_RULES = """# ELICIT Requirement Interview
- 必須遵守「本輪你的 action」：ask_user/supplement_question 才能問 user；propose_finish 只能輸出固定停止句。
- 只追問會影響需求是否成立、結果是否可信、是否可採用、是否合規或是否存在安全/風險底線的限制。
- 提問聚焦外部限制、domain risk、營運限制、資料可信度、品質邊界、信任邊界或可接受性；若問題無法改變限制或風險判斷，就不要追問。
- 不要為了扮演 expert 而硬問合規、法規或安全；只有當產品情境、既有需求或 user 回答顯示這些因素會影響需求成立時才深入。
- 若沒有明確外部限制缺口，優先檢查資料來源可信度、結果可接受性、營運限制或風險底線；仍無有效缺口時可提出收束。
- 不要把會議帶成一般技術選型或工程審查。
- 若沒有關鍵限制缺口，可以提出收束；停止句只代表提議收束，系統會再進入收束投票流程決定是否真的結束。"""


def expert_elicitation_action_task(stop_phrase: str) -> str:
    return (
        "依本輪 action 發言。若 action 是 ask_user 或 supplement_question，先用 1 句重述目前理解或缺口，"
        "再輸出對 user 的一個主問題（總長 2-4 句）；"
        "若你判斷目前已蒐集到足夠資訊、可以收束本輪需求挖掘，則 statement 請只輸出以下固定句"
        f"（勿加引號、勿改寫、勿額外說明）：{stop_phrase}"
    )


def expert_elicitation_action_rules(stop_phrase: str) -> str:
    return f"""- 只有在目前需求理解已足夠，且沒有關鍵限制缺口時，才可輸出停止句：{stop_phrase}
- 輸出停止句不是單方結束會議，只是進入三方收束投票。
- 若本輪 action 是 propose_finish，statement 必須只輸出停止句：{stop_phrase}
- 若本輪 action 是 ask_user 或 supplement_question，只能問 1 個主問題，不可合併多題。
- 若本輪 action 是 ask_user 或 supplement_question，必須輸出 target_stakeholders，從已選 stakeholder 中選擇一位或多位。
- target_stakeholders 優先選擇能說明外部限制、營運限制、資料可信度、結果可接受性、品質邊界或風險底線的 stakeholder。
- 問題必須能轉成 constraint、NFR、risk、acceptance boundary 或 evidence gap。
- 問題應直接詢問使用情境中的限制、可接受風險、可信度要求、外部規範或採用條件。
- 不要重複 analyst 的需求目標/優先級問題，也不要重複 modeler 的操作流程問題；你的問題必須補上 expert 角度才看得到的限制或風險。
- 不要重問 user 已回答、已說不在意、或已表示 covered 的限制/資料來源方向。
- open_questions 請輸出空陣列。"""
