# Defines action prompts and output contracts.

def group_detection(*, base_task: str) -> str:
    return f"""{base_task}

# Input
- User Requirements、pairwise_evaluated_pairs、pairwise_conflicts 與相關 artifact context 由 runtime context 提供。

# Generation Rules
- 本步補查未被兩兩判斷涵蓋的需求組合，並找出至少跨 3 筆需求的共同決策主題。
- pairwise_evaluated_pairs 是已完成判斷的兩兩範圍，不論結果是 Conflict 或 Neutral，都不得重複輸出相同的兩筆需求組合。
- pairwise_conflicts 只作為發現更大共同主題的線索，不可原樣重複輸出。
- 第一步先從輸入需求與 pairwise_conflicts 中抽象出共同「決策主題」；不要使用預設主題清單。
- 第二步才判斷：同一決策主題下，是否有兩筆以上 User Requirements 不能直接同時定稿。
- group 原則上必須包含至少 3 條不同需求。
- 若兩條需求的組合不存在於 pairwise_evaluated_pairs，代表該組合未被兩兩判斷涵蓋；本步可輸出這種 2 條需求的 Conflict。
- 若兩條需求的組合已存在於 pairwise_evaluated_pairs，本步不得重複輸出。
- 整體判斷應以共同決策主題、規則邊界或一致性問題選取需求。
- pairwise_conflicts 只作為參考；若多個 pairwise conflicts 其實是同一個決策主題，且合併後涵蓋至少 3 條不同需求，請聚合成一筆 Conflict。
- 即使沒有 pairwise_conflicts，只要 User Requirements 顯示多筆需求在同一決策主題下無法一起寫入 SRS，也要輸出 Conflict。
- 若只是資訊不足、需要補問、語意模糊但尚未形成不能同時定稿的需求關係，可以在 reason 中說明分類依據。
- conflicts 收錄會影響需求取捨、改寫、合併、刪除、責任分工或人類裁決的 Conflict。
- 每筆 Conflict 的 reason 必須說明「共同決策主題」以及「為什麼這些需求不能直接同時定稿」。
- 若 group 來自既有 pairwise_conflicts，才輸出 related_pairs；若是直接從 User Requirements 發現，related_pairs 可省略或輸出空陣列。
- 若沒有可定義的 group conflict，輸出 {{"conflicts": []}}。
- conflicts 只包含 final_label="Conflict" 的項目。
- 每筆 Conflict 必須包含 title。
- title 必須是 4 到 30 字的名詞片語，描述共同決策主題；不可只輸出 Conflict、衝突、需求衝突或 CR 編號。

# Output JSON
{{
  "conflicts": [
    {{
      "title": "簡短衝突標題",
      "requirement_ids": ["URL-1", "URL-2", "URL-3"],
      "final_label": "Conflict",
      "final_type": "scope",
      "reason": "一句繁中判斷理由"
    }}
  ]
}}"""
