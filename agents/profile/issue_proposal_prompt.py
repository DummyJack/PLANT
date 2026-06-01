# Shared issue proposal prompt builder.
import json
from typing import Any, Dict, List, Optional


def build_issue_proposal_prompt(
    *,
    agent_label: str,
    focus: str,
    common_problem_examples: List[str],
    value_gate: List[str],
    reject_rule: str,
    max_items: int,
    proposal_context: Optional[Dict[str, Any]] = None,
) -> str:
    examples = "\n".join(f"- {item}" for item in common_problem_examples)
    gates = "\n".join(f"- {item}" for item in value_gate)
    context_json = json.dumps(proposal_context or {}, ensure_ascii=False, indent=2)
    return f"""# 任務
提出本輪需要進入 issue proposal 的{agent_label}候選議題。目標是讓 latest draft 更接近可生成 SRS 的需求規格。

# 提案邊界
- 輸出只是候選訊號，不是正式會議定題；Mediator 會合併、淘汰與命名。
- latest_draft 是主要依據；proposal_context 只提供摘要訊號，不包含專案資料全文。
- 不得根據 proposal_context 假設專案資料的完整內容；若 context 顯示缺口但 draft 沒有對應內容，只能提出「draft 未呈現該缺口」的議題。
- 只提出最能讓 draft 更接近可生成 SRS 的共同問題：{focus}。
- 每筆 proposal 必須代表一組相關需求背後的共同問題，例如：
{examples}
- 不要為單一 requirement、單一 open question、單一 acceptance criteria、單一來源追蹤、單一模型項目或單一欄位補字建立 proposal；除非它明確代表更大的共同問題。
- 預設會議已先處理整份衝突報告的衝突取捨與全部 User Requirements 的初步正式化；一般提案只處理預設會議後 latest_draft 仍明確留下的特定缺口。
- 優先讓既有 REQ-* 需求條目完整、明確、可測試、可追溯；只有當既有 REQ-* 的主要缺口已處理或 draft 明確指出新共同問題時，才提出下一階段的新議題。
- 不要跳過既有 REQ-* 的重大缺口去討論新的功能方向、延伸方案或低優先建議。
- 提案優先序：
  1. Requirement Completeness：缺 acceptance criteria、verification、可量化 NFR 門檻、外部限制影響、source coverage，或需求仍抽象不可測。
  2. Boundary / Responsibility：系統、人工、第三方或角色責任不清。
  3. Tradeoff：多方需求有方案取捨但尚未形成衝突。
  4. Model Alignment：模型揭露流程、狀態、actor、資料或責任不一致。
  5. New Requirement / Expansion：新增或延伸需求，只有前面高優先缺口不阻礙定稿時才提出。
- 若一組 REQ-* 缺少 acceptance criteria、validation、metric、外部限制影響、風險/假設確認、來源覆蓋或模型一致性，應優先提出這類完善既有需求的議題。
- 同類型、同流程、同角色、同限制或同風險族群的 REQ-* 缺口必須合併成一個議題一起討論；不要拆成一題只處理一個 REQ-*。
- 單一 REQ-* 只能作為 evidence，不應直接成為議題邊界；若 sources 只有一個 REQ-*，reason 必須說明它為何代表跨流程、跨角色、跨限制、跨風險或多個 SRS 章節的共同問題，否則不要提出。
- 不要再提出泛稱的需求整理或衝突解決；只有當 draft 指出具體 source id、open question、角色、接受條件、限制、模型或決策缺口，且它代表一組需求的共同問題時才提案。
- 在 {max_items} 筆上限內，盡可能提出所有符合價值門檻的議題；不要為了湊數降低品質。若沒有符合門檻的議題，才輸出空陣列。

# 價值門檻
符合以下條件才提出；若符合門檻，應盡量保留為候選議題：
{gates}
- sources.evidence 必須指出 draft 中的具體缺口、矛盾、未決問題、角色衝突、限制、模型缺口或來源 id。
- expect_outcome 必須是會議後可落地的結果，優先是補完整既有 REQ-*，例如補 acceptance criteria、validation、metric、外部限制影響、risks、assumptions、source coverage、模型一致性，或確認仍需保留 open question / human decision。
{reject_rule}

# 每筆 issue schema
- title：描述共同問題的短標籤，供 triage 參考；不要只寫單一需求 id 或欄位缺口
- expect_outcome：說明此議題被處理後應得到什麼明確結果
- sources：array，每筆為 object：{{"artifact": "requirements|conflict_report|conversation|system_models|open_questions|scope|feedback", "ids": ["draft 中看得到的具體 id"], "evidence": "draft 中的具體依據、缺口或 id"}}；優先放入同一共同問題下的多個 ids；若只有單一 id，reason 必須說明它代表的較大流程、邊界、限制、風險或模型問題
- importance：high / medium / low
- reason：說明共同問題是什麼、為什麼需要正式會議，以及它為什麼影響需求規格完整性

# proposal_context 摘要
以下只供判斷 draft coverage 與缺口，不是專案資料全文：
```json
{context_json}
```

# 輸出 JSON
[]"""
