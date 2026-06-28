# Defines action prompts and output contracts.

def group_detection(*, base_task: str) -> str:
    return f"""{base_task}

# Input
- User Requirements、pairwise_conflicts 與相關 artifact context 由 runtime context 提供。

# Generation Rules
- 本步只找跨多筆需求的共同決策主題。
- pairwise_conflicts 作為可聚合線索之一。
- 第一步先找「決策主題」。可用主題包含：
  - 資料揭露、保存、查詢權限、稽核責任。
  - 流程責任邊界、人工介入與自動化分工。
  - 即時性、效率、簡化流程 vs 安全、驗證、合規。
  - 使用者自主權、平台控管、營運效率、公平性或風險控管。
  - 狀態一致性、資料同步、付款/退款/取消/配送狀態。
  - scope、角色責任、第三方服務或人工流程邊界。
- 第二步才判斷：同一決策主題下，是否有兩筆以上 User Requirements 不能直接同時定稿。
- group 可以包含 2 條或 3 條以上需求；requirement_ids 至少 2 個。2 條也可以，但必須代表共同決策主題。
- 整體判斷應以共同決策主題、規則邊界或一致性問題選取需求。
- pairwise_conflicts 只作為參考；若多個 pairwise conflicts 其實是同一個決策主題，請聚合成一筆 Conflict。
- 即使沒有 pairwise_conflicts，只要 User Requirements 顯示多筆需求在同一決策主題下無法一起寫入 SRS，也要輸出 Conflict。
- 若只是資訊不足、需要補問、語意模糊但尚未形成不能同時定稿的需求關係，可以在 reason 中說明分類依據。
- conflicts 收錄會影響需求取捨、改寫、合併、刪除、責任分工或人類裁決的 Conflict。
- 每筆 Conflict 的 reason 必須說明「共同決策主題」以及「為什麼這些需求不能直接同時定稿」。
- 若 group 來自既有 pairwise_conflicts，才輸出 related_pairs；若是直接從 User Requirements 發現，related_pairs 可省略或輸出空陣列。
- 若沒有可定義的 group conflict，輸出 {{"conflicts": []}}。
- conflicts 只包含 final_label="Conflict" 的項目。

# Output JSON
{{"conflicts":[...]}}"""
