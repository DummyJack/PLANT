# Defines Design Rationale prompt templates.
import json
from typing import Any, List


def design_rationale(requirements: List[dict[str, Any]]) -> str:
    return f"""# 任務
根據 design rationale requirement context array 產生 Design Rationale 主體 Markdown。

# Action Boundary
- action=documentor.generate_dr
- 本 action 根據 Requirement Context 產生 Design Rationale 主體 Markdown。
- Design Rationale 說明每個 FR/NFR/CON 的來源、會議決策、trace 形成脈絡與最終需求形成原因。
- runtime 會另外在每個 requirement 上方插入可點選的 trace topology。

# Source Boundary
- Requirement Context 是唯一直接來源。
- 只引用 context 中存在的 REQ、URL、ST、CR、FB、SM 或 meeting。
- 不得使用外部資料或推測不存在的決策。

# Input
Requirement Context:
{json.dumps(requirements, ensure_ascii=False, indent=2)}

# Generation Rules
- 說明每個正式需求（FR-*、NFR-*、CON-*）是如何從原始發言、User Requirement、衝突、回饋、模型與會議討論逐步形成。
- 主體以正式需求 block 為單位，不以會議為單位。
- Trace 是連貫形成鏈，不是 evidence 清單；每一步都要說明它如何承接前一步。
- Trace Explanation 是用來解釋 runtime 插入的 Trace Topology；文字要說明圖中的節點與連線如何形成正式需求。
- Trace Explanation 不要重述 Description 的需求內容；只說明來源整理、會議決策與正式化的形成脈絡。
- Trace Explanation 必須能對照 Topology 路徑閱讀；每個 bullet 第一句必須用該段 evidence ID 開頭，並說明該 ID 做了什麼、如何影響下一個節點或正式需求。
- Trace Explanation 本身必須是一條可讀的形成軌跡，不要只列 evidence 清單；讀者從 Stakeholder / User Requirement / Conflict / System Model / Meeting Discussion / Requirement Formation 依序讀下來，就要能知道 FR/NFR/CON 是怎麼產生的。
- 每個 section 的第一句要承接前一段，說明「因此下一步發生什麼」；不要每段都獨立描述。
- 若 topology 中有 CR、Feedback、System Model 或 Meeting，需說明它們如何由 URL 觸發、如何在會議中提供依據、建模或被解決。
- Trace Explanation 必須優先依 trace_graph.edges 的可達路徑順序敘述：Source → User Requirement → Analysis → Meeting → Requirement。
- 若有 Feedback 或 System Model 支線，請在它接回 meeting 的位置說明它補充了哪個決策、限制、模型依據或需求欄位，不要獨立寫成同等主線。
- topology edge label 只能使用固定短語，不要自創長句或同義詞：ST→URL 為「分析」；URL→FB 為「依據」；URL→SM 為「建模」；URL→CR 不顯示文字；CR→resolve meeting 為「解決」；沒有衝突時 URL→formalize meeting 為「正式化」；有衝突時 resolve meeting→formalize meeting 為「正式化」；formalize meeting→clarify meeting 為「精練」；FB/SM→meeting 不顯示文字；最後 meeting→FR/NFR/CON 不顯示文字。
- 若 trace_graph.edges 的 relation 為空字串，Trace Explanation 可以說明節點承接關係，但不得替該邊命名或寫成新的 edge label。
- 若需要描述「依據」或「建模」支線，請在文字中說明它補充哪個 meeting decision、限制或模型依據；不要把支線寫成與主鏈同等的正式化步驟。
- 只有 formalize_requirement meeting 才代表正式化；若有後續 clarify_requirement meeting，則由最後一個 clarify_requirement meeting 連到正式需求但不顯示文字，表示精練後收斂。clarify_requirement meeting 不要寫成正式化本身。
- 不要把 topology 中所有相關 evidence 寫成同等重要；請依 edge path 說明主要形成鏈，旁支 evidence 只說明它補充了哪個決策、限制、模型依據或需求欄位。
- Meeting Discussion 必須依 meeting 時序書寫；若同時有 resolve_conflict、formalize_requirement、clarify_requirement，順序必須是先解決衝突，再正式化，再說明後續釐清。
- Meeting Discussion 的每個 bullet 都必須說清楚四件事：該 meeting 的用途（解決衝突、需求正式化或精練/深入討論）、承接來源、會議中「目前這個 FR/NFR/CON」如何被決定或確認、以及它對下一個 meeting 或最後 FR/NFR/CON 的影響。只有衝突解決會議可以寫「討論輸入」；需求正式化會議要寫「正式化依據」；後續 clarify/refine meeting 要寫「承接前一版需求做更深入討論/精練」，不要再寫成衝突解決的討論輸入。不要寫整場會議的總摘要；要聚焦目前 block 的需求如何在該 meeting 產生、保留、調整、補齊或收斂。
- 不要只寫「成為依據」這種泛稱；必須說清楚依據哪個會議決定、哪個正式需求或哪個限制。
- 若 Requirement Context 含 trace_warnings，代表該 evidence 關聯不足或被排除；不要把 warning 中被排除的 evidence 寫成已形成正式 trace。
- 若 trace_warnings 顯示 evidence 被排除或未連上，不得在 Trace Explanation 中宣稱它已支撐該需求；只能說該 evidence 未形成可確認追蹤路徑。
- trace_repair_tasks 已由 runtime 的 repair loop 處理；Design Rationale 正文只描述已驗證 trace、trace_warnings 與 trace_human_review_tasks，不輸出 repair proposal。
- 若含 trace_human_review_tasks，代表修補需要人工確認；只能說明仍待確認，不得寫成已驗證、已套用或已進正式圖的 trace。
- Evidence ID 只用純文字引用，例如 `CR-1`、`SM-3`、`R1-M2`；不要輸出 Markdown 連結。
- 同一句中同一批 evidence ID 只能出現一次；不要寫「見 Appendix」。
- 不貼完整 evidence；完整內容由 trace topology modal 顯示。
- 會議決定放在 Meeting Discussion 中自然說明，不另開 Decision 章節。

# Output Format
- 請只輸出多個 REQ block。
- 不輸出 H1。
- 不輸出 Appendix。
- 不輸出 JSON。
- 不要包在程式碼區塊中。
- 不要解釋。
- 每個 FR/NFR/CON block 之間必須使用單獨一行 `---` 作為分割線。

### FR-N | NFR-N | CON-N: title
**Description**: description

**Acceptance Criteria**:
1. FR only; omit when context has no acceptance_criteria.

**Metric**: NFR only; omit when context has no metric.

#### Trace Explanation

Stakeholder
- ST-* 表達具體利害關係人需求或限制，作為此需求的原始來源。

User Requirement
- URL-* 將 ST-* 整理為具體使用者需求，形成可分析的需求項目。

Conflict
- 只有有相關 CR-* 時輸出。CR-* 指出 URL-* 與 URL-* 在具體需求邊界、資料責任、流程順序或品質取捨上衝突，後續需要透過會議或正式化決策收斂。

System Model
- 只有有相關 SM-* 時輸出。SM-* 將 URL-* 對應到具體流程、狀態、資料結構或互動，建模此需求的系統設計。

Meeting Discussion
- 只有有相關 meeting 時輸出。若是解決衝突會議，寫明「R*-M* 是衝突解決會議，討論輸入為 CR-*」並說明該衝突如何被處理；若是需求正式化會議，寫明「R*-M* 是需求正式化會議，正式化依據為 URL-*／前一場會議」並說明保留或調整了什麼；若是後續 clarify/refine meeting，寫明「R*-M* 承接前一版需求做更深入討論或精練」並說明補齊了哪個需求細節。會議決定或確認具體需求內容，因此該內容被保留、調整、補齊或推進到下一個 meeting/正式需求。

Requirement Formation
- URL-* 經由 R*-M* 或前述 trace 節點收斂為 FR/NFR/CON-*，正式要求系統履行該 block 的具體功能、品質或限制。

# Trace Section Rules
- 每個 block 第一行必須使用 context 中的 srs_id，格式為 `### FR-N: title`、`### NFR-N: title` 或 `### CON-N: title`，不得用 REQ-* 當標題。
- `Description` 必須獨立成行，後面空一行再輸出下一個欄位。
- FR-* 若 context.acceptance_criteria 有資料，必須在 Description 下方空一行輸出 `**Acceptance Criteria**:`，並用 `1. 2.` 編號清單列出；Acceptance Criteria 結束後也要空一行。沒有資料就省略整個欄位。
- NFR-* 若 context.metric 有資料，必須在 Description 下方空一行輸出 `**Metric**: ...`；Metric 結束後也要空一行。沒有資料就省略整個欄位。
- CON-* 不輸出 Acceptance Criteria 或 Metric。
- Trace 步驟標題必須使用 `Stakeholder`、`User Requirement` 這種英文純文字標籤，不得使用 `###`，也不得使用 `1. Stakeholder` 這種編號標題。
- Trace 步驟內容必須使用 bullet，每個 bullet 第一句必須以 evidence ID 開頭，例如 `- ST-1-1 ...`、`- URL-1 ...`、`- FB-1 ...`、`- R1-M1 ...`。
- Requirement Formation 必須明確寫出 `URL-*`/`R*-M*` 如何收斂成目前 block 的 `FR-*`、`NFR-*` 或 `CON-*`。
- 不要輸出 `SRS ID` 欄位，因為標題已經使用 SRS ID。
- 有資料才輸出該 Trace 步驟；省略步驟後仍保留語意編號。
- Stakeholder 與 User Requirement 通常必須存在；若 context 沒有，才可省略。

# Forbidden Output
- 不得新增 context 沒有的 REQ、URL、ST、CR、FB、SM 或 meeting。
- 舊格式不相容：不得使用 REQ-* 作為 block 標題，不得輸出表格式 rationale，不得輸出舊 metadata 欄位。
- 不得輸出 Type、Source、Context、Decision、Rationale、Impact 這些舊章節或欄位。
- 不要輸出「待補」、空章節、JSON、程式碼區塊或 prompt 說明。
- 不要只列 ID；每個 Trace 步驟都必須用自然語言說明該 evidence 對 REQ 形成的影響。
- 不要輸出 Markdown evidence links，例如 `[SM-3](#sm-3)`；請輸出純文字 `SM-3`。
- 不要寫「見 Appendix」或「參考 Appendix」。
"""
