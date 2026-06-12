# Defines Design Rationale prompt templates.
import json
from typing import Any, List


def design_rationale(requirements: List[dict[str, Any]]) -> str:
    return f"""# 任務
根據 design rationale requirement context array 產生 Design Rationale 主體 Markdown。

# Documentor Action Boundary
- action=documentor.generate_dr
- 本 action 只輸出 Design Rationale 主體 Markdown，不輸出 JSON。
- 不更新 artifact、不新增 REQ、不新增 trace evidence。
- 不輸出 Appendix；runtime 會另外在每個 requirement 上方插入可點選的 trace topology。

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
- Trace Explanation 不要重述 Description 的需求內容；只說明來源、分析、會議與正式化的形成脈絡。
- Trace Explanation 必須能對照 Topology 路徑閱讀；每個 bullet 第一句必須用該段 evidence ID 開頭，並說明該 ID 做了什麼、如何影響下一個節點或正式需求。
- 若 topology 中有 CR、Feedback、System Model 或 Meeting，需說明它們如何由 URL 觸發、如何在會議中提供依據/支撐或被解決。
- topology edge label 使用短語意：ST→URL 為「分析」、URL/CR/FB/SM→formalize meeting 為「正式」、CR→resolve meeting 為「解決」、clarify meeting 為「細化」、FB→meeting 為「依據」、SM→meeting 為「支撐」。
- 只有 formalize_requirement meeting 才代表正式化；clarify_requirement meeting 只能說明後續細化或補充，不要寫成正式化終點。
- 不要把 topology 中所有相關 evidence 寫成同等重要；請依 edge path 說明主要形成鏈，旁支 evidence 只說明它補充了哪個決策、限制、模型依據或需求欄位。
- Meeting Discussion 必須依 meeting 時序書寫；若同時有 resolve_conflict、formalize_requirement、clarify_requirement，順序必須是先解決衝突，再正式化，再說明後續細化。
- 不要只寫「提供支撐」、「成為依據」這種泛稱；必須說清楚支撐哪個會議決定、哪個正式需求或哪個限制。
- 若 Requirement Context 含 trace_warnings，代表該 evidence 關聯不足或被排除；不要把 warning 中被排除的 evidence 寫成已形成正式 trace。
- 若 trace_warnings 顯示 evidence 被排除或未連上，不得在 Trace Explanation 中宣稱它已支撐該需求；只能說該 evidence 未形成可確認追蹤路徑。
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

### FR-N | NFR-N | CON-N: title
**Description**: description


#### Trace Explanation

Stakeholder
- ST-* 表達「...」，作為此需求的原始來源。

User Requirement
- URL-* 將 ST-* 整理為「...」，形成可分析的使用者需求。

Conflict
- 只有有相關 CR-* 時輸出。CR-* 指出 URL-* 與 URL-* 在「...」上衝突，後續需要透過會議或正式化決策收斂。

Feedback
- 只有有相關 FB-* 時輸出。FB-* 補充「...」，作為需求正式化時的限制、風險或外部依據。

System Model
- 只有有相關 SM-* 時輸出。SM-* 將 URL-* 對應到「...」流程、狀態或互動，支撐此需求的系統設計。

Meeting Discussion
- 只有有相關 meeting 時輸出。R*-M* 根據 URL-*、CR-*、FB-* 或 SM-* 討論後，決定「...」。

Requirement Formation
- URL-* 經由 R*-M* 或前述 trace 節點收斂為 FR/NFR/CON-*，正式要求系統「...」。

# Trace Section Rules
- 每個 block 第一行必須使用 context 中的 srs_id，格式為 `### FR-N: title`、`### NFR-N: title` 或 `### CON-N: title`，不得用 REQ-* 當標題。
- `Description` 必須獨立成行。
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
